"""Runpod Serverless-обработчик KZ-SUB.

Самый дешёвый способ хостинга на старте: GPU-воркер поднимается только на время
запроса, оплата посекундная, при простое — $0. HTTPS-эндпоинт даёт Runpod.

Вход (job["input"]):
    audio_base64: аудиофайл в base64 (wav/mp3/m4a)
    api_key:      ключ KZ-SUB (проверяется как в основном API)
    fmt:          "srt" (по умолчанию) или "json"

Выход: {"srt": "..."} или {"segments": [...], "duration": ...}
       либо {"error": "..."} при ошибке.

Деплой: см. docs/HOSTING.md (раздел Runpod Serverless).
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile

# app/ лежит уровнем выше (образ собирается из backend/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.quota import QuotaError, check_and_reserve, commit  # noqa: E402
from app.segmentation import resegment, resegment_words  # noqa: E402
from app.srt import segments_to_srt  # noqa: E402
from app.style import apply_style  # noqa: E402
from app.transcribe import transcribe_file  # noqa: E402


def handler(job: dict) -> dict:
    inp = job.get("input") or {}

    api_key = (inp.get("api_key") or "").strip()
    if not api_key:
        return {"error": "api_key required"}

    audio_b64 = inp.get("audio_base64")
    if not audio_b64:
        return {"error": "audio_base64 required"}

    try:
        audio = base64.b64decode(audio_b64)
    except Exception:
        return {"error": "audio_base64 is not valid base64"}

    estimated_seconds = max(1.0, len(audio) / (1 << 20) * 60)
    if estimated_seconds > settings.max_audio_seconds:
        return {"error": "audio too long"}
    try:
        check_and_reserve(api_key, estimated_seconds)
    except QuotaError as e:
        return {"error": f"quota: {e}"}

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as f:
            f.write(audio)
            tmp_path = f.name

        raw_segments, duration = transcribe_file(tmp_path)

        if settings.caption_style == "word":
            segments = resegment_words(raw_segments, glue_max_chars=settings.glue_max_chars)
        else:
            segments = resegment(
                raw_segments,
                max_line_chars=settings.max_line_chars,
                max_lines=settings.max_lines,
                max_cue_seconds=settings.max_cue_seconds,
                max_gap_seconds=settings.max_gap_seconds,
            )
        segments = apply_style(
            segments,
            uppercase=settings.uppercase,
            strip_punctuation=settings.strip_punctuation,
        )

        commit(api_key, duration or estimated_seconds)

        if (inp.get("fmt") or "srt") == "json":
            return {
                "language": settings.language,
                "duration": duration,
                "segments": [
                    {"start": s.start, "end": s.end, "text": s.text} for s in segments
                ],
            }
        return {"srt": segments_to_srt(segments)}
    except Exception as e:  # noqa: BLE001 — отдать ошибку в ответе задания
        return {"error": f"transcription failed: {e}"}
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    import runpod  # доступен в образе Runpod Serverless

    runpod.serverless.start({"handler": handler})
