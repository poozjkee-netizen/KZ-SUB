"""Преобразование сегментов транскрибации в формат SubRip (.srt).

Premiere Pro импортирует .srt как нативную дорожку субтитров, поэтому SRT —
основной формат обмена между бэкендом и плагином.
"""
from dataclasses import dataclass


@dataclass
class Segment:
    start: float  # секунды
    end: float    # секунды
    text: str


def _format_timestamp(seconds: float) -> str:
    """Секунды -> 'HH:MM:SS,mmm' (запятая перед миллисекундами — стандарт SRT)."""
    if seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: list[Segment]) -> str:
    """Список сегментов -> строка .srt."""
    blocks: list[str] = []
    index = 0
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        index += 1
        blocks.append(
            f"{index}\n"
            f"{_format_timestamp(seg.start)} --> {_format_timestamp(seg.end)}\n"
            f"{text}\n"
        )
    return "\n".join(blocks) + ("\n" if blocks else "")
