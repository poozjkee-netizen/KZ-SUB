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


def transcribe_via_runpod(audio_bytes: bytes, fmt: str = "json") -> dict:
    """Отправляет аудио в Runpod и возвращает output задания.

    Возвращаемый dict — то, что отдал runpod_handler: для fmt="json" это
    {"language", "duration", "segments": [...]}.
    """
    if not (settings.runpod_endpoint_id and settings.runpod_api_key):
        raise RunpodError("Runpod не сконфигурирован (KZSUB_RUNPOD_ENDPOINT_ID/API_KEY)")

    base = f"https://api.runpod.ai/v2/{settings.runpod_endpoint_id}"
    payload = {
        "input": {
            "api_key": settings.runpod_worker_key,
            "audio_base64": base64.b64encode(audio_bytes).decode(),
            "fmt": fmt,
        }
    }

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
