"""Точная оценка длительности аудио (заголовок WAV) вместо оценки по размеру.

Прежняя эвристика в main.py ("1 МБ ≈ 1 минута") предполагала битрейт ~17.5 КБ/с,
что заметно ниже реального (16 kHz mono 16-bit PCM ≈ 32 КБ/с — панель шлёт
именно такой WAV, см. plugin/presets/README.md). Из-за этого короткие ролики
завышались по оценке и упирались в лимит минут лицензии раньше времени.

Только stdlib (wave) — dep-free-тестируемый модуль (см. CLAUDE.md §11).
"""
from __future__ import annotations

import wave


def probe_duration_seconds(path: str, fallback_size_bytes: int) -> float:
    """Длительность в секундах.

    Точно — из заголовка PCM WAV (кадры / частота дискретизации). Если файл не
    открылся как WAV (неожиданный формат) — грубая оценка по размеру как
    запасной вариант, чтобы не блокировать запрос из-за самой проверки.
    """
    try:
        with wave.open(path, "rb") as wf:
            rate = wf.getframerate()
            frames = wf.getnframes()
            if rate > 0:
                return frames / float(rate)
    except (wave.Error, EOFError, OSError):
        pass
    return max(1.0, fallback_size_bytes / (1 << 20) * 60)
