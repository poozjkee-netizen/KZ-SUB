"""KZ-SUB API — приём аудио и возврат казахских субтитров (.srt).

Эндпоинты:
    GET  /health                — проверка живости
    POST /transcribe            — аудио -> .srt (text/plain) или JSON-сегменты
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from . import licenses, telegram_bot
from .config import settings
from .devices import DeviceLimitError, check_device
from .licenses import LicenseError
from .runpod_client import RunpodError, transcribe_via_runpod
from .segmentation import resegment, resegment_words
from .srt import Segment, segments_to_srt
from .style import apply_style
from .transcribe import transcribe_file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kzsub.api")

app = FastAPI(title="KZ-SUB API", version="0.1.0")

os.makedirs(settings.tmp_dir, exist_ok=True)


@app.on_event("startup")
def _startup() -> None:
    # Готовим БД лицензий: таблица + developer-ключ + бутстрап-ключи из env.
    licenses.ensure_seeded()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.whisper_model, "language": settings.language}


@app.get("/license")
def license_info(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    """Статус лицензии по ключу (для кнопки «Проверить» и будущего кабинета).

    Read-only: не меняет статус и не привязывает устройства. 401 — ключа нет.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Требуется заголовок X-API-Key")
    info = licenses.describe(x_api_key)
    if info is None:
        raise HTTPException(status_code=401, detail="Неизвестный ключ")
    return info


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict:
    """Вебхук Telegram-бота выдачи ключей (app/telegram_bot.py).

    404, если бот не настроен (KZSUB_TELEGRAM_BOT_TOKEN пуст) — эндпоинт не
    существует в проде, пока владелец явно не включит бота. 401, если задан
    KZSUB_TELEGRAM_WEBHOOK_SECRET и заголовок не совпадает (регистрируется
    через `python -m app.telegram_bot set-webhook`).
    """
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=404)
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if settings.telegram_webhook_secret and secret != settings.telegram_webhook_secret:
        raise HTTPException(status_code=401)
    update = await request.json()
    await run_in_threadpool(telegram_bot.handle_update, update)
    return {"ok": True}


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
    fmt: str = Query(default="srt", description="Формат ответа: 'srt' или 'json'"),
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Требуется заголовок X-API-Key")

    # Лицензия: существование ключа, статус, срок действия — ДО привязки
    # устройства и чтения файла (не биндим устройства к несуществующим ключам).
    try:
        licenses.check_license(x_api_key, 0.0)
    except LicenseError as e:
        raise HTTPException(status_code=e.http_status, detail=str(e))

    # Анти-шаринг: ключ работает максимум на N устройствах.
    try:
        check_device(x_api_key, (x_device_id or "").strip())
    except DeviceLimitError as e:
        raise HTTPException(status_code=403, detail=str(e))

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

        # Лимит минут: хватит ли остатка лицензии на этот файл.
        try:
            licenses.check_license(x_api_key, estimated_seconds / 60.0)
        except LicenseError as e:
            raise HTTPException(status_code=e.http_status, detail=str(e))

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

        # Списываем фактически обработанные минуты.
        licenses.commit_usage(x_api_key, (duration or estimated_seconds) / 60.0)

        # Остаток минут — в заголовок ответа (задел под отображение баланса
        # в панели/кабинете). "unlimited" для безлимитных лицензий.
        lic_after = licenses.get_license(x_api_key)
        remaining = lic_after.remaining_minutes() if lic_after else None
        headers = {
            "X-Minutes-Remaining": "unlimited" if remaining is None else str(int(remaining))
        }

        if fmt == "json":
            return JSONResponse(
                {
                    "language": settings.language,
                    "duration": duration,
                    "segments": [
                        {"start": s.start, "end": s.end, "text": s.text.strip()}
                        for s in segments
                    ],
                },
                headers=headers,
            )
        return PlainTextResponse(
            segments_to_srt(segments),
            media_type="application/x-subrip",
            headers=headers,
        )
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
