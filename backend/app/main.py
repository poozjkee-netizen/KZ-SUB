"""KZ-SUB API — приём аудио и возврат казахских субтитров (.srt).

Эндпоинты:
    GET  /health                — проверка живости
    POST /transcribe            — аудио -> .srt (text/plain) или JSON-сегменты
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from . import dataset, events, licenses, telegram_bot
from .audio_chunk import split_wav_for_runpod
from .audio_convert import to_16k_mono_wav_bytes
from .audio_probe import probe_duration_seconds
from .config import settings
from .devices import DeviceLimitError, check_device
from .licenses import LicenseError
from .postprocess import postprocess
from .runpod_client import AudioTooLarge, RunpodError, transcribe_via_runpod
from .segmentation import resegment, resegment_words
from .srt import Segment, segments_to_srt
from .style import apply_style
from .timing import snap_starts_to_speech
from .transcribe import transcribe_file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kzsub.api")

app = FastAPI(title="KZ-SUB API", version="0.1.0")

os.makedirs(settings.tmp_dir, exist_ok=True)


def _runpod_transcribe(
    tmp_path: str, total_duration: float,
) -> tuple[list[Segment], float, bytes]:
    """Прокси-режим: конвертирует, при нужде режет на куски и склеивает сегменты.

    Синхронная (urllib внутри) — вызывается через run_in_threadpool одним заходом,
    чтобы весь цикл нарезки шёл вне event loop. Куски гонятся параллельно
    (до chunk_concurrency одновременно), порядок сегментов восстанавливается по
    индексу куска, тайм-коды сдвигаются на смещение куска в исходном аудио.
    total_duration — реальная длительность файла (из probe), для списания минут.
    Возвращает также конвертированное аудио: оно нужно для привязки таймингов к
    речи (timing.py), а конвертировать 16 kHz mono второй раз незачем.

    Время по этапам пишется в лог: без этого непонятно, что тормозит на длинных
    файлах — конвертация на шлюзе или прогоны на GPU.
    """
    t0 = time.monotonic()
    wav_bytes = to_16k_mono_wav_bytes(tmp_path)
    convert_seconds = time.monotonic() - t0

    chunks = split_wav_for_runpod(wav_bytes, settings.chunk_seconds)

    def run_chunk(item: tuple[int, tuple[bytes, float]]) -> tuple[int, list[Segment]]:
        idx, (chunk_bytes, offset) = item
        started = time.monotonic()
        out = transcribe_via_runpod(chunk_bytes, "json")
        segs = [
            Segment(float(s["start"]) + offset, float(s["end"]) + offset, str(s["text"]))
            for s in (out.get("segments") or [])
        ]
        logger.info("Кусок %d/%d: %d сегментов за %.1f c",
                    idx + 1, len(chunks), len(segs), time.monotonic() - started)
        return idx, segs

    t1 = time.monotonic()
    if len(chunks) == 1:
        results = [run_chunk((0, chunks[0]))]
    else:
        workers = max(1, min(settings.chunk_concurrency, len(chunks)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(run_chunk, enumerate(chunks)))

    results.sort(key=lambda r: r[0])          # порядок кусков, а не порядок ответов
    segments = [seg for _, segs in results for seg in segs]

    logger.info(
        "Аудио %.0f c: конвертация %.1f c, кусков %d, распознавание %.1f c, сегментов %d",
        total_duration, convert_seconds, len(chunks), time.monotonic() - t1, len(segments),
    )
    return segments, total_duration, wav_bytes


@app.on_event("startup")
def _startup() -> None:
    # Готовим БД лицензий: таблица + developer-ключ + бутстрап-ключи из env.
    licenses.ensure_seeded()
    # И таблицу событий: пишем в неё из горячего пути, создавать её там поздно.
    if settings.analytics:
        events.init_db()


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
    """Транскрибация плюс учёт прогона (events.py).

    Метрики снимаются здесь, снаружи обработки: так в статистику попадают и
    отказы по лимиту (сигнал к покупке), и падения сервиса, а сам обработчик
    остаётся только про субтитры. Учёт не может сорвать ответ — record_run
    молча проглатывает свои ошибки.
    """
    started = time.monotonic()
    stat: dict = {"license": "", "mode": "", "audio": 0.0, "segments": 0}
    status, reason = "ok", ""
    try:
        return await _transcribe(file, x_api_key, x_device_id, fmt, stat)
    except HTTPException as e:
        status, reason = "error", f"http_{e.status_code}"
        raise
    except Exception:
        status, reason = "error", "crash"
        raise
    finally:
        events.record_run(
            x_api_key or "", status,
            device_id=(x_device_id or "").strip(),
            license_type=stat["license"],
            mode=stat["mode"],
            reason=reason,
            audio_seconds=stat["audio"],
            wall_seconds=time.monotonic() - started,
            segments=stat["segments"],
        )


async def _transcribe(
    file: UploadFile,
    x_api_key: str | None,
    x_device_id: str | None,
    fmt: str,
    stat: dict,
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Требуется заголовок X-API-Key")

    # Лицензия: существование ключа, статус, срок действия — ДО привязки
    # устройства и чтения файла (не биндим устройства к несуществующим ключам).
    try:
        licenses.check_license(x_api_key, 0.0)
    except LicenseError as e:
        raise HTTPException(status_code=e.http_status, detail=str(e))

    # Тариф — в метрику: отказ по лимиту у demo и у standard означает разное
    # (первый — сигнал к покупке, второй — что лимит тесен).
    lic = licenses.get_license(x_api_key)
    stat["license"] = lic.type if lic else ""

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
        # Длительность для предварительной проверки лимита/квоты (уточним по
        # факту после транскрибации) — точно из заголовка WAV, см. audio_probe.py.
        estimated_seconds = probe_duration_seconds(tmp_path, size)
        stat["audio"] = estimated_seconds
        if estimated_seconds > settings.max_audio_seconds:
            raise HTTPException(status_code=413, detail="Слишком длинный файл")

        # Лимит минут: хватит ли остатка лицензии на этот файл.
        try:
            licenses.check_license(x_api_key, estimated_seconds / 60.0)
        except LicenseError as e:
            raise HTTPException(status_code=e.http_status, detail=str(e))

        proxy_mode = bool(settings.runpod_endpoint_id and settings.runpod_api_key)
        stat["mode"] = "proxy" if proxy_mode else "local"

        if proxy_mode:
            # Прокси-режим: тяжёлая работа на Runpod GPU. Воркер возвращает уже
            # нарезанные и оформленные сегменты (общий код в runpod_handler).
            # Аудио конвертируется в 16 kHz mono и при нужде режется на куски —
            # панель шлёт 48 kHz stereo, а у Runpod лимит 10 MiB на запрос
            # (см. audio_convert / audio_chunk).
            try:
                segments, duration, wav_bytes = await run_in_threadpool(
                    _runpod_transcribe, tmp_path, estimated_seconds
                )
            except AudioTooLarge as e:
                logger.warning("Аудио слишком большое: %s", e)
                raise HTTPException(status_code=413, detail=str(e))
            except RunpodError as e:
                logger.error("Runpod: %s", e)
                raise HTTPException(status_code=502, detail="Сервис транскрибации недоступен")
        else:
            # Локальный режим: Whisper на этой машине.
            wav_bytes = b""      # для привязки таймингов конвертируем ниже, по нужде
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

        # Тайминги: подтягиваем начала реплик к фактическому началу речи —
        # пословные метки Whisper «спешат» (см. timing.py). Нужно само аудио в
        # 16 kHz mono: в прокси-режиме оно уже есть, в локальном конвертируем тут.
        if settings.snap_to_speech and settings.snap_window_seconds > 0:
            if not wav_bytes:
                wav_bytes = await run_in_threadpool(to_16k_mono_wav_bytes, tmp_path)
            segments = await run_in_threadpool(
                snap_starts_to_speech, segments, wav_bytes,
                settings.snap_window_seconds,
            )

        # Постобработка текста (зацикливания модели, пользовательский словарь).
        # Общая для обоих режимов и намеренно на шлюзе: катится fly deploy, без
        # пересборки GPU-образа (см. postprocess.py).
        segments = postprocess(segments)
        stat["segments"] = len(segments)
        stat["audio"] = duration or estimated_seconds

        # Датасет под будущее дообучение (выключен по умолчанию, только со
        # своих ключей — см. dataset.py). Пишем после постобработки: разметка
        # должна совпадать с тем, что получил пользователь.
        if dataset.should_collect(x_api_key):
            if not wav_bytes:
                wav_bytes = await run_in_threadpool(to_16k_mono_wav_bytes, tmp_path)
            await run_in_threadpool(
                dataset.store, x_api_key, wav_bytes, segments,
                duration or estimated_seconds,
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
