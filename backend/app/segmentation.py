"""Пересборка «сырых» сегментов Whisper в аккуратные субтитры.

Whisper часто отдаёт длинные реплики на весь экран. Здесь мы режем поток слов
на короткие читаемые реплики по правилам субтитрования:
  - не длиннее max_line_chars * max_lines символов;
  - не дольше max_cue_seconds секунд;
  - разрыв на заметной паузе между словами (max_gap_seconds);
и переносим текст на строки (до max_lines), балансируя длину.
"""
from __future__ import annotations

from .asr_types import RawSegment, Word
from .srt import Segment


def _flatten_words(raw: list[RawSegment]) -> list[Word]:
    """Собирает все слова из сегментов. Если пословных тайм-кодов нет —
    использует сегмент целиком как один «блок» (деградация без падения)."""
    words: list[Word] = []
    for seg in raw:
        if seg.words:
            words.extend(seg.words)
        else:
            t = seg.text.strip()
            if t:
                words.append(Word(start=seg.start, end=seg.end, text=t))
    return words


def _wrap(text: str, max_line_chars: int, max_lines: int) -> str:
    """Переносит текст на строки (жадно по словам), не более max_lines строк."""
    tokens = text.split()
    lines: list[str] = []
    cur = ""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        candidate = tok if not cur else cur + " " + tok
        if len(candidate) > max_line_chars and cur:
            lines.append(cur)
            cur = ""
            if len(lines) == max_lines - 1:
                # Достигли последней допустимой строки — досыпаем остаток целиком.
                lines.append(" ".join(tokens[i:]))
                return "\n".join(lines)
            continue  # tok начинает новую строку, i не двигаем
        cur = candidate
        i += 1
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def resegment(
    raw: list[RawSegment],
    max_line_chars: int,
    max_lines: int,
    max_cue_seconds: float,
    max_gap_seconds: float,
) -> list[Segment]:
    """Поток RawSegment -> список аккуратных субтитров (Segment)."""
    max_cue_chars = max_line_chars * max_lines
    words = _flatten_words(raw)

    cues: list[Segment] = []
    cur: list[Word] = []
    cur_len = 0  # длина текста в текущей реплике (символы)

    def flush() -> None:
        if not cur:
            return
        text = " ".join(w.text for w in cur).strip()
        cues.append(
            Segment(
                start=cur[0].start,
                end=cur[-1].end,
                text=_wrap(text, max_line_chars, max_lines),
            )
        )

    for w in words:
        wt = w.text.strip()
        if not wt:
            continue
        if cur:
            gap = w.start - cur[-1].end
            add_len = len(wt) + 1  # слово + пробел
            duration = w.end - cur[0].start
            if (
                gap > max_gap_seconds
                or cur_len + add_len > max_cue_chars
                or duration > max_cue_seconds
            ):
                flush()
                cur = []
                cur_len = 0
        cur.append(w)
        cur_len += len(wt) + (1 if cur_len else 0)

    flush()
    return cues
