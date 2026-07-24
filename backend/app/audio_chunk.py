"""Нарезка длинного аудио на части для Runpod (лимит 10 MiB на тело /run).

Даже после сжатия до 16 kHz mono инлайн-base64 упирается в ~4 минуты на запрос.
Чтобы обрабатывать более длинные ролики, шлюз режет аудио на куски по
KZSUB_CHUNK_SECONDS, гонит каждый через Runpod и склеивает сегменты со сдвигом
тайм-кодов (см. main.py). Точка реза ищется по тишине рядом с целевой границей,
чтобы не рвать слово посередине.

Только stdlib: wave + audioop (audioop есть до Python 3.13; образ шлюза на 3.12).
На вход — WAV 16 kHz mono 16-bit (то, что отдаёт audio_convert). Если это не
такой WAV или audioop недоступен — возвращаем один кусок как есть.
"""
from __future__ import annotations

import io
import logging
import wave

try:
    import audioop
    _HAVE_AUDIOOP = True
except ImportError:  # pragma: no cover — зависит от версии Python базового образа
    _HAVE_AUDIOOP = False

logger = logging.getLogger("kzsub.audio")

RATE = 16000
WIDTH = 2  # 16-bit


def split_wav_for_runpod(wav_bytes: bytes, chunk_seconds: float,
                         search_seconds: float = 3.0) -> list[tuple[bytes, float]]:
    """Режет 16 kHz mono WAV на куски ≤ chunk_seconds.

    Возвращает список (wav_bytes_куска, смещение_старта_в_секундах). Если аудио
    короче куска (или не парсится как WAV) — один элемент со смещением 0.0.
    """
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            channels, width, rate = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
            pcm = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError, OSError):
        return [(wav_bytes, 0.0)]  # не WAV — отдаём как есть

    # Работаем только с ожидаемым форматом; иначе не рискуем и шлём одним куском.
    if (channels, width, rate) != (1, WIDTH, RATE):
        return [(wav_bytes, 0.0)]

    total_frames = len(pcm) // WIDTH
    chunk_frames = int(chunk_seconds * RATE)
    if chunk_frames <= 0 or total_frames <= chunk_frames:
        return [(wav_bytes, 0.0)]

    search_frames = int(search_seconds * RATE)
    chunks: list[tuple[bytes, float]] = []
    start = 0
    while start < total_frames:
        target = start + chunk_frames
        if target >= total_frames:
            end = total_frames
        else:
            end = _best_cut(pcm, target, search_frames, total_frames)
        chunk_pcm = pcm[start * WIDTH:end * WIDTH]
        chunks.append((_wrap_wav(chunk_pcm), start / RATE))
        start = end

    logger.info("Аудио нарезано на %d кусков по ~%.0f c", len(chunks), chunk_seconds)
    return chunks


def _best_cut(pcm: bytes, target: int, search: int, total: int) -> int:
    """Ищет тихую точку реза рядом с target (минимум RMS в окне 100 мс).

    Без audioop — режем ровно по target (просто, но может задеть слово).
    """
    if not _HAVE_AUDIOOP or search <= 0:
        return target

    lo = max(1, target - search)
    hi = min(total - 1, target + search)
    win = int(0.1 * RATE)          # окно анализа 100 мс
    step = int(0.05 * RATE) or 1   # шаг поиска 50 мс
    best_pos, best_rms = target, None
    pos = lo
    while pos <= hi:
        a = max(0, pos - win // 2) * WIDTH
        b = min(total, pos + win // 2) * WIDTH
        rms = audioop.rms(pcm[a:b], WIDTH)
        if best_rms is None or rms < best_rms:
            best_rms, best_pos = rms, pos
        pos += step
    return best_pos


def _wrap_wav(pcm: bytes) -> bytes:
    """Заворачивает сырые 16 kHz mono 16-bit кадры в WAV-контейнер (bytes)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(WIDTH)
        out.setframerate(RATE)
        out.writeframes(pcm)
    return buf.getvalue()
