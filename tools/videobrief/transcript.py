"""Работа с расшифровкой: сегменты -> чистый текст и текст с тайм-кодами.

Только stdlib: сюда стекаются оба источника (готовые субтитры ролика и Whisper),
и именно эта логика решает, что увидит модель при разборе. Поэтому она обязана
быть тестируемой без установки yt-dlp и faster-whisper.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Segment:
    start: float  # секунды
    end: float    # секунды
    text: str


def format_tc(seconds: float) -> str:
    """Секунды -> 'MM:SS' (или 'H:MM:SS' для роликов длиннее часа)."""
    if seconds < 0:
        seconds = 0.0
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def dedupe_rolling(segments: list[Segment]) -> list[Segment]:
    """Убирает повторы «бегущей строки» авто-субтитров YouTube.

    В авто-субтитрах каждая следующая реплика начинается с хвоста предыдущей
    (так строка «наезжает» на экране). Без чистки текст раздувается вдвое, а
    модель на разборе принимает повторы за приём автора.
    """
    out: list[Segment] = []
    prev: list[str] = []
    for seg in segments:
        cur = _words(seg.text)
        if not cur:
            continue
        # Наибольший хвост предыдущей реплики, совпадающий с началом текущей.
        overlap = 0
        for k in range(min(len(prev), len(cur)), 0, -1):
            if [w.lower() for w in prev[-k:]] == [w.lower() for w in cur[:k]]:
                overlap = k
                break
        rest = cur[overlap:]
        prev = cur
        if not rest:
            continue
        out.append(Segment(start=seg.start, end=seg.end, text=" ".join(rest)))
    return out


def merge_blocks(segments: list[Segment], max_seconds: float = 12.0,
                 max_chars: int = 220) -> list[Segment]:
    """Склеивает короткие реплики в блоки по ~12 секунд.

    Зачем: субтитры режут речь на куски по 2-3 слова, и текст с тайм-кодом на
    каждой строке съедает контекст модели и ломает чтение. Блок примерно равен
    одной мысли — по нему удобно размечать структуру ролика.
    """
    out: list[Segment] = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        if out:
            last = out[-1]
            fits_time = seg.end - last.start <= max_seconds
            fits_len = len(last.text) + 1 + len(text) <= max_chars
            if fits_time and fits_len:
                last.text = f"{last.text} {text}"
                last.end = seg.end
                continue
        out.append(Segment(start=seg.start, end=seg.end, text=text))
    return out


def clean_text(segments: list[Segment]) -> str:
    """Сплошной текст ролика без тайм-кодов — то, что просили «чистым текстом».

    Абзац начинается после паузы длиннее 2 секунд: так текст остаётся читаемым,
    а не превращается в одну простыню.
    """
    paragraphs: list[list[str]] = []
    prev_end: float | None = None
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        if prev_end is None or seg.start - prev_end > 2.0 or not paragraphs:
            paragraphs.append([text])
        else:
            paragraphs[-1].append(text)
        prev_end = seg.end
    return "\n\n".join(" ".join(p) for p in paragraphs).strip() + "\n"


def timed_text(segments: list[Segment]) -> str:
    """Текст с тайм-кодами: '[00:07] реплика' — основа для разметки структуры."""
    lines = [f"[{format_tc(seg.start)}] {seg.text.strip()}"
             for seg in segments if seg.text.strip()]
    return "\n".join(lines) + ("\n" if lines else "")


_TIMED_LINE = re.compile(r"^\[(?:(\d+):)?(\d{1,2}):(\d{2})\]\s*(.+)$")


def parse_timed_text(content: str) -> list[Segment]:
    """Разбирает наш же формат '[MM:SS] реплика' обратно в сегменты.

    Нужен, чтобы повторный прогон разбора шёл по готовому transcript.timed.txt —
    без повторного скачивания и распознавания (и его можно поправить руками).
    """
    segments: list[Segment] = []
    for line in content.splitlines():
        match = _TIMED_LINE.match(line.strip())
        if not match:
            continue
        hours, minutes, secs, text = match.groups()
        start = int(hours or 0) * 3600 + int(minutes) * 60 + int(secs)
        if segments:
            segments[-1].end = float(start)
        segments.append(Segment(start=float(start), end=float(start), text=text.strip()))
    if segments:
        # Конец последней реплики неизвестен — считаем её типовой по длине.
        segments[-1].end = segments[-1].start + max(2.0, len(segments[-1].text) / 15.0)
    return segments


def duration(segments: list[Segment]) -> float:
    """Длительность по последнему сегменту (когда метаданных ролика нет)."""
    return max((seg.end for seg in segments), default=0.0)
