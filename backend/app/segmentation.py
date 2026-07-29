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


# Короткие служебные слова, которые логично держать вместе со следующим словом.
# В основном русские предлоги (казахский агглютинативен, там частицы обычно
# постпозитивны и покрываются правилом по длине glue_max_chars).
GLUE_WORDS = {
    # русские предлоги
    "в", "во", "на", "за", "к", "ко", "с", "со", "у", "о", "об", "обо",
    "от", "ото", "до", "из", "изо", "по", "под", "подо", "над", "надо",
    "при", "про", "без", "для", "не", "ни",
    # казахские короткие частицы/союзы, встречающиеся в потоке
    "әрі", "әр", "бір",
}


def _clean(text: str) -> str:
    """Слово без пунктуации по краям — для проверки «служебности»."""
    return text.strip().strip(".,!?;:—-«»\"'()").lower()


def _is_glue(text: str, glue_max_chars: int) -> bool:
    w = _clean(text)
    if not w:
        return True
    return len(w) <= glue_max_chars or w in GLUE_WORDS


def resegment_words(raw: list[RawSegment], glue_max_chars: int) -> list[Segment]:
    """Караоке-режим: одно слово на реплику.

    Короткие предлоги/частицы (см. _is_glue) прилипают к СЛЕДУЮЩЕМУ слову.
    Хвостовые служебные слова без следующего — прилипают к предыдущей реплике.
    """
    words = _flatten_words(raw)

    cues: list[Segment] = []
    pending: list[Word] = []  # накопленные служебные слова, ждут «настоящее» слово

    for w in words:
        if not w.text.strip():
            continue
        if _is_glue(w.text, glue_max_chars):
            pending.append(w)
            continue
        group = pending + [w]
        pending = []
        cues.append(
            Segment(
                start=group[0].start,
                end=group[-1].end,
                text=" ".join(x.text.strip() for x in group).strip(),
            )
        )

    # Остались только служебные слова (например, в самом конце) — приклеим к
    # предыдущей реплике, либо, если её нет, выпустим как есть.
    if pending:
        tail = " ".join(x.text.strip() for x in pending).strip()
        if cues:
            cues[-1] = Segment(cues[-1].start, pending[-1].end, cues[-1].text + " " + tail)
        elif tail:
            cues.append(Segment(pending[0].start, pending[-1].end, tail))

    return cues


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


# --- Выбор режима нарезки ------------------------------------------------
# Режимов два, и выбирать между ними приходится в трёх местах: локальный
# режим шлюза, GPU-воркер и скрипт локального прогона. Пока выбор был
# скопирован в каждом, любая правка одного из режимов рисковала разъехаться —
# особенно теперь, когда режим приходит в запросе от панели.
WORD = "word"
PHRASE = "phrase"
STYLES = (WORD, PHRASE)


def build_captions(
    raw: list[RawSegment],
    style: str,
    *,
    glue_max_chars: int,
    max_line_chars: int,
    max_lines: int,
    max_cue_seconds: float,
    max_gap_seconds: float,
) -> list[Segment]:
    """Нарезать субтитры в выбранном режиме: `word` (караоке) или `phrase`.

    Неизвестное значение считаем фразовым: лучше выдать читаемые субтитры,
    чем упасть из-за опечатки в параметре.
    """
    if style == WORD:
        return resegment_words(raw, glue_max_chars=glue_max_chars)
    return resegment(
        raw,
        max_line_chars=max_line_chars,
        max_lines=max_lines,
        max_cue_seconds=max_cue_seconds,
        max_gap_seconds=max_gap_seconds,
    )


def strip_punctuation_for(style: str, strip_punctuation: bool,
                          phrase_punctuation: bool) -> bool:
    """Снимать ли пунктуацию при выбранном режиме нарезки.

    В караоке одно слово со знаком препинания выглядит мусором, поэтому знаки
    снимаются. Во фразах пунктуация — это читаемость, и по умолчанию она
    остаётся: Whisper расставляет её сам, терять её незачем.
    """
    if style == PHRASE and phrase_punctuation:
        return False
    return strip_punctuation
