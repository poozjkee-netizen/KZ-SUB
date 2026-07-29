"""Клиент Runpod Serverless для прокси-режима шлюза.

Шлюз (этот FastAPI на дешёвом CPU-хостинге) отправляет аудио в Runpod-эндпоинт
(GPU, посекундная оплата) и ждёт результат: /run -> опрос /status/{id}.

Только стандартная библиотека — шлюзу не нужны тяжёлые зависимости.
"""
from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request

from .config import settings

logger = logging.getLogger("kzsub.runpod")


class RunpodError(Exception):
    """Ошибка вызова Runpod (конфигурация, сеть, упавшее задание)."""


class AudioTooLarge(RunpodError):
    """Аудио (после base64) не влезает в лимит тела Runpod /run (10 MiB)."""


# Лимит тела запроса Runpod /run. Оставляем запас на JSON-обёртку и заголовки.
RUNPOD_MAX_BODY_BYTES = 10 * 1024 * 1024
_BODY_SAFETY_BYTES = 64 * 1024


def _request(url: str, payload: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {settings.runpod_api_key}",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise RunpodError(f"Runpod HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RunpodError(f"Runpod недоступен: {e.reason}") from e


def transcribe_via_runpod(audio_bytes: bytes, fmt: str = "json",
                          style: str = "", want_words: bool = False) -> dict:
    """Отправляет аудио в Runpod и возвращает output задания.

    Возвращаемый dict — то, что отдал runpod_handler: для fmt="json" это
    {"language", "duration", "segments": [...]}.

    want_words=True просит СЫРЫЕ сегменты со словами: нарезку и оформление
    делает шлюз, поэтому их правки катятся одним `fly deploy`. Старый воркер
    этот флаг не знает и вернёт уже нарезанные сегменты — шлюз это распознаёт
    по отсутствию признака `raw` и работает по-старому.

    style — режим нарезки ("word" / "phrase") для старого воркера, который режет
    сам. При want_words он не нужен, но передаётся для совместимости.
    """
    if not (settings.runpod_endpoint_id and settings.runpod_api_key):
        raise RunpodError("Runpod не сконфигурирован (KZSUB_RUNPOD_ENDPOINT_ID/API_KEY)")

    base = f"https://api.runpod.ai/v2/{settings.runpod_endpoint_id}"
    audio_b64 = base64.b64encode(audio_bytes).decode()

    # Отсекаем заранее: Runpod вернёт 400 "exceeded max body size of 10MiB",
    # а мы дадим клиенту понятную причину (слишком длинный/тяжёлый файл).
    if len(audio_b64) + _BODY_SAFETY_BYTES > RUNPOD_MAX_BODY_BYTES:
        raise AudioTooLarge(
            "Аудио слишком большое для обработки одним запросом "
            f"({len(audio_b64) // (1024 * 1024)} МБ после кодирования, лимит 10 МБ). "
            "Сократите длительность ролика."
        )

    payload = {
        "input": {
            "api_key": settings.runpod_worker_key,
            "audio_base64": audio_b64,
            "fmt": fmt,
        }
    }
    if style:
        payload["input"]["style"] = style
    if want_words:
        payload["input"]["want_words"] = True

    job = _request(base + "/run", payload)
    job_id = job.get("id")
    if not job_id:
        raise RunpodError(f"Не удалось создать задание: {job}")
    logger.info("Runpod job %s создан (%d байт аудио)", job_id, len(audio_bytes))

    deadline = time.time() + settings.runpod_timeout_seconds
    while time.time() < deadline:
        st = _request(f"{base}/status/{job_id}")
        status = st.get("status")
        if status == "COMPLETED":
            out = st.get("output") or {}
            if isinstance(out, dict) and out.get("error"):
                raise RunpodError(str(out["error"]))
            return out
        if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
            raise RunpodError(f"Задание {status}: {st.get('error') or 'без деталей'}")
        # IN_QUEUE / IN_PROGRESS — ждём (холодный старт может занять десятки секунд)
        time.sleep(2.0)

    raise RunpodError("Таймаут ожидания результата Runpod")
