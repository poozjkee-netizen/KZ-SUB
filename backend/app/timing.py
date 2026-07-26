"""Привязка начала субтитров к реальному началу речи.

Проблема: пословные тайм-коды Whisper систематически «спешат» — текст на
таймлайне появляется раньше, чем слово произнесено. Причин две: VAD добавляет
паддинг (по умолчанию 400 мс) перед фрагментом речи, а выравнивание слов внутри
окна делается по cross-attention и само по себе смещено на десятки-сотни мс.

Решение: у шлюза есть аудио, поэтому мы не гадаем с фиксированным сдвигом, а
ищем фактическое начало речи рядом с началом реплики и подтягиваем реплику к
нему. Правило намеренно односторонее — двигаем только ВПЕРЁД (позже) и только
если реплика начинается в тишине. Так исправляется именно «текст раньше речи»,
и мы не можем случайно обрезать слово, начав реплику позже настоящей речи.

Только stdlib (wave + audioop) — модуль dep-free-тестируемый (CLAUDE.md §11).
Ожидает WAV 16 kHz mono 16-bit (то, что готовит audio_convert).
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

from .srt import Segment

logger = logging.getLogger("kzsub.timing")

FRAME_MS = 20          # шаг анализа энергии: компромисс точности и объёма работы
MIN_RUN_FRAMES = 3     # 60 мс подряд выше порога = речь, а не щелчок
MIN_CUE_SECONDS = 0.15  # короче реплику не делаем — лучше сдвинуть её целиком


def _frame_energies(pcm: bytes, width: int, frame_bytes: int) -> list[int]:
    """RMS по кадрам (уровень C: audioop.rms на срезах, без Python-арифметики)."""
    return [
        audioop.rms(pcm[i:i + frame_bytes], width)
        for i in range(0, len(pcm) - frame_bytes + 1, frame_bytes)
    ]


def _speech_threshold(energies: list[int]) -> int:
    """Порог «речь/тишина» от шумового пола записи, а не абсолютный.

    Берём 20-й процентиль как оценку фона (в речи паузы занимают заметную долю)
    и поднимаем втрое. Нижняя граница страхует случай почти идеальной тишины,
    где утроенный ноль остался бы нулём.
    """
    if not energies:
        return 0
    ordered = sorted(energies)
    floor = ordered[len(ordered) // 5]
    return max(floor * 3, 150)


def _find_onset(energies: list[int], start_idx: int, limit_idx: int,
                threshold: int) -> int | None:
    """Первый кадр устойчивой речи в диапазоне [start_idx, limit_idx]."""
    run = 0
    for i in range(max(0, start_idx), min(limit_idx, len(energies) - 1) + 1):
        if energies[i] >= threshold:
            run += 1
            if run >= MIN_RUN_FRAMES:
                return i - run + 1
        else:
            run = 0
    return None


def snap_starts_to_speech(
    segments: list[Segment], wav_bytes: bytes, window_seconds: float,
) -> list[Segment]:
    """Подтягивает начала реплик к фактическому началу речи.

    window_seconds — насколько далеко вперёд искать речь (0 = выключено).
    Реплика, которая уже начинается на речи, не трогается. Если сдвиг съел бы
    почти всю реплику, двигаем её целиком, сохраняя длительность: при
    систематическом лиде это и нужно. Порядок и отсутствие наложений сохраняются.
    """
    if window_seconds <= 0 or not segments or not _HAVE_AUDIOOP or not wav_bytes:
        return segments

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            channels, width, rate = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
            pcm = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError, OSError):
        return segments
    if channels != 1 or width != 2:
        return segments  # ждём результат audio_convert; иначе не рискуем

    frame_bytes = int(rate * FRAME_MS / 1000) * width
    if frame_bytes <= 0:
        return segments
    energies = _frame_energies(pcm, width, frame_bytes)
    if not energies:
        return segments

    threshold = _speech_threshold(energies)
    frame_s = FRAME_MS / 1000.0
    window_frames = int(window_seconds / frame_s)

    out: list[Segment] = []
    moved = 0
    prev_end = 0.0
    for seg in segments:
        start, end = seg.start, seg.end
        idx = int(start / frame_s)

        # Двигаем только реплики, начинающиеся в тишине: если слово уже звучит,
        # сдвиг вперёд отрезал бы его начало.
        if 0 <= idx < len(energies) and energies[idx] < threshold:
            onset = _find_onset(energies, idx, idx + window_frames, threshold)
            if onset is not None and onset > idx:
                new_start = onset * frame_s
                duration = end - start
                if new_start > end - MIN_CUE_SECONDS:
                    end = new_start + duration      # сдвиг целиком
                start = new_start
                moved += 1

        # Не наезжаем на предыдущую реплику и не переворачиваем порядок.
        if start < prev_end:
            shift = prev_end - start
            start += shift
            end = max(end, start + MIN_CUE_SECONDS)
        prev_end = end
        out.append(Segment(start, end, seg.text))

    if moved:
        logger.info("Тайминги: подтянуто к началу речи %d из %d реплик",
                    moved, len(segments))
    return out
