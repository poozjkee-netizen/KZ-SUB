"""KZ-SUB API — приём аудио и возврат казахских субтитров (.srt).

Эндпоинты:
    GET  /health                — проверка живости
    POST /transcribe            — аудио -> .srt (text/plain) или JSON-сегменты
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from .config import settings
from .quota import QuotaError, check_and_reserve, commit
from .runpod_client import RunpodError, transcribe_via_runpod
from .segmentation import resegment, resegment_words
from .srt import Segment, segments_to_srt
from .style import apply_style
from .transcribe import transcribe_file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kzsub.api")

app = FastAPI(title="KZ-SUB API", version="0.1.0")

os.makedirs(settings.tmp_dir, exist_ok=True)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.whisper_model, "language": settings.language}


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    fmt: str = Query(default="srt", description="Формат ответа: 'srt' или 'json'"),
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Требуется заголовок X-API-Key")

    # Сохраняем загруженный файл во временную директорию.
    tmp_path = os.path.join(settings.tmp_dir, f"{uuid.uuid4().hex}_{file.filename or 'audio'}")
    size = 0
    with open(tmp_path, "wb") as out:
        while chunk := await file.read(1 << 20):  # по 1 МБ
            size += len(chunk)
            out.write(chunk)
    logger.info("Принят файл %s (%d байт)", tmp_path, size)

    try:
        # Грубая оценка длительности для предварительной проверки квоты
        # (уточним по факту после транскрибации). ~1 МБ ≈ 60 сек сжатого аудио.
        estimated_seconds = max(1.0, size / (1 << 20) * 60)
        if estimated_seconds > settings.max_audio_seconds:
            raise HTTPException(status_code=413, detail="Слишком длинный файл")

        try:
            check_and_reserve(x_api_key, estimated_seconds)
        except QuotaError as e:
            raise HTTPException(status_code=402, detail=str(e))

        proxy_mode = bool(settings.runpod_endpoint_id and settings.runpod_api_key)

        if proxy_mode:
            # Прокси-режим: тяжёлая работа на Runpod GPU. Воркер возвращает уже
            # нарезанные и оформленные сегменты (общий код в runpod_handler).
            with open(tmp_path, "rb") as f:
                audio_bytes = f.read()
            try:
                out = await run_in_threadpool(transcribe_via_runpod, audio_bytes, "json")
            except RunpodError as e:
                logger.error("Runpod: %s", e)
                raise HTTPException(status_code=502, detail="Сервис транскрибации недоступен")
            segments = [
                Segment(float(s["start"]), float(s["end"]), str(s["text"]))
                for s in (out.get("segments") or [])
            ]
            duration = float(out.get("duration") or 0.0)
        else:
            # Локальный режим: Whisper на этой машине.
            try:
                raw_segments, duration = await run_in_threadpool(transcribe_file, tmp_path)
            except Exception:
                logger.exception("Ошибка транскрибации")
                raise HTTPException(status_code=500, detail="Ошибка транскрибации")

            # Нарезаем субтитры в выбранном стиле.
            if settings.caption_style == "word":
                # Караоке-стиль: одно слово на реплику (предлоги липнут к слову).
                segments = resegment_words(raw_segments, glue_max_chars=settings.glue_max_chars)
            else:
                # Аккуратные реплики-фразы.
                segments = resegment(
                    raw_segments,
                    max_line_chars=settings.max_line_chars,
                    max_lines=settings.max_lines,
                    max_cue_seconds=settings.max_cue_seconds,
                    max_gap_seconds=settings.max_gap_seconds,
                )

            # Оформление: регистр / пунктуация.
            segments = apply_style(
                segments,
                uppercase=settings.uppercase,
                strip_punctuation=settings.strip_punctuation,
                punct_keep=settings.punct_keep,
            )

        commit(x_api_key, duration or estimated_seconds)

        if fmt == "json":
            return JSONResponse(
                {
                    "language": settings.language,
                    "duration": duration,
                    "segments": [
                        {"start": s.start, "end": s.end, "text": s.text.strip()}
                        for s in segments
                    ],
                }
            )
        return PlainTextResponse(segments_to_srt(segments), media_type="application/x-subrip")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
