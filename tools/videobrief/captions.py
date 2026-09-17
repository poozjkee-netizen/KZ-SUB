"""Разбор готовых субтитров ролика (.vtt / .srt) в сегменты.

Зачем это раньше Whisper: у большинства виральных роликов на YouTube субтитры
уже есть. Взять их — секунды вместо минут распознавания и ноль нагрузки на
машину. Whisper остаётся запасным путём для TikTok/Reels и «немых» роликов.
"""
from __future__ import annotations

import html
import re

from .transcript import Segment

_TIME = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*"
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
)
# Внутри реплики авто-субтитров лежит пословная разметка:
# "привет<00:00:01.359><c> мир</c>". Для текста она мусор.
_TAG = re.compile(r"<[^>]*>")


def _seconds(hours: str | None, minutes: str, secs: str, millis: str) -> float:
    return (int(hours or 0) * 3600 + int(minutes) * 60 + int(secs)
            + int(millis.ljust(3, "0")) / 1000.0)


def clean_cue_text(raw: str) -> str:
    """Реплика субтитров -> голый текст (без тегов, сущностей и меток позиции)."""
    text = _TAG.sub("", raw)
    text = html.unescape(text)
    text = text.replace("​", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse(content: str) -> list[Segment]:
    """Содержимое .vtt или .srt -> список сегментов.

    Формат определяется по строке с '-->' — она одинакова в обоих, отличаются
    только разделитель миллисекунд и наличие номера блока. Поэтому один разбор
    на два формата: меньше кода, меньше поводов разойтись.
    """
    segments: list[Segment] = []
    start = end = 0.0
    buffer: list[str] = []
    collecting = False

    def flush() -> None:
        if collecting:
            text = clean_cue_text(" ".join(buffer))
            if text:
                segments.append(Segment(start=start, end=end, text=text))

    for line in content.splitlines():
        stripped = line.strip()
        match = _TIME.search(stripped)
        if match:
            flush()
            g = match.groups()
            start = _seconds(g[0], g[1], g[2], g[3])
            end = _seconds(g[4], g[5], g[6], g[7])
            buffer = []
            collecting = True
            continue
        if not stripped:
            flush()
            collecting = False
            buffer = []
            continue
        if collecting:
            buffer.append(stripped)
    flush()
    return segments
