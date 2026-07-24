"""Приведение аудио к 16 kHz mono 16-bit перед отправкой в Runpod.

Зачем: у Runpod жёсткий лимит 10 MiB на тело запроса (/run). Панель по факту
экспортирует WAV в 48 kHz stereo (~192 КБ/с) — ролик на 2,5 минуты весит ~29 МБ,
а после base64 тело раздувается до ~39 МБ и Runpod отвечает 400. Whisper всё
равно работает на 16 kHz mono, поэтому шлюз ужимает аудио сам — 6× меньше,
без пересборки .zxp у пользователя (серверная правка, см. золотое правило CLAUDE.md).

Только stdlib: wave + audioop. audioop помечен deprecated и удалён в Python 3.13;
образ шлюза на python:3.12-slim (есть). На случай будущего апгрейда базового
образа импорт защищён — без audioop конвертация пропускается (аудио уходит как есть).
"""
from __future__ import annotations

import io
import logging
import wave

try:
    import audioop  # stdlib до 3.13; в 3.13 удалён
    _HAVE_AUDIOOP = True
except ImportError:  # pragma: no cover — зависит от версии Python базового образа
    _HAVE_AUDIOOP = False

logger = logging.getLogger("kzsub.audio")

TARGET_RATE = 16000  # Whisper работает на 16 kHz
TARGET_WIDTH = 2     # 16-bit PCM
TARGET_CHANNELS = 1  # mono


def to_16k_mono_wav_bytes(path: str) -> bytes:
    """Читает WAV с диска и возвращает его как 16 kHz mono 16-bit WAV (bytes).

    Если файл уже 16 kHz mono 16-bit — просто возвращает его байты. Если это не
    PCM WAV или audioop недоступен — возвращает исходные байты без изменений
    (пусть решает воркер; лучше передать как есть, чем упасть на самой конвертации).
    """
    try:
        with wave.open(path, "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError, OSError):
        with open(path, "rb") as f:
            return f.read()  # не WAV — отдаём как есть

    # Уже в целевом формате — ничего не делаем.
    if channels == TARGET_CHANNELS and width == TARGET_WIDTH and rate == TARGET_RATE:
        return _wrap_wav(frames)

    if not _HAVE_AUDIOOP or channels not in (1, 2):
        # Не можем безопасно сконвертировать (нет audioop или экзотические каналы)
        # — отдаём исходный файл целиком.
        with open(path, "rb") as f:
            return f.read()

    # 1) К 16-битному сэмплу (audioop.tomono/ratecv работают с шириной 1/2/4).
    if width != TARGET_WIDTH:
        frames = audioop.lin2lin(frames, width, TARGET_WIDTH)
        width = TARGET_WIDTH

    # 2) В моно (равномерно смешиваем каналы).
    if channels == 2:
        frames = audioop.tomono(frames, width, 0.5, 0.5)

    # 3) Ресемпл до 16 kHz.
    if rate != TARGET_RATE:
        frames, _ = audioop.ratecv(frames, width, 1, rate, TARGET_RATE, None)

    logger.info("Аудио сконвертировано: %d Hz %dch -> 16000 Hz mono", rate, channels)
    return _wrap_wav(frames)


def _wrap_wav(frames: bytes) -> bytes:
    """Заворачивает сырые 16 kHz mono 16-bit кадры в WAV-контейнер (bytes)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(TARGET_CHANNELS)
        out.setsampwidth(TARGET_WIDTH)
        out.setframerate(TARGET_RATE)
        out.writeframes(frames)
    return buf.getvalue()
