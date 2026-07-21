"""Оформление готовых субтитров: регистр и удаление пунктуации.

Применяется к финальному списку реплик (после нарезки), поэтому работает
одинаково и для караоке-режима, и для режима фраз.
"""
from __future__ import annotations

import re

from .srt import Segment

# Пунктуация, которую убираем в караоке-стиле. Дефис и апостроф НЕ трогаем —
# они бывают внутри слов (например, «тайм-код», казахские сокращения).
_PUNCT = set(".,!?;:…«»\"“”„‚‘’()[]{}—–/\\|*")


def _strip_punct(text: str) -> str:
    cleaned = "".join(ch for ch in text if ch not in _PUNCT)
    # Схлопываем лишние пробелы, но сохраняем переносы строк.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = "\n".join(line.strip() for line in cleaned.split("\n"))
    return cleaned.strip()


def apply_style(
    segments: list[Segment],
    uppercase: bool,
    strip_punctuation: bool,
) -> list[Segment]:
    """Возвращает новый список реплик с применённым оформлением.

    Реплики, ставшие пустыми после чистки (например, состояли из одного тире),
    отбрасываются.
    """
    if not uppercase and not strip_punctuation:
        return segments

    out: list[Segment] = []
    for seg in segments:
        text = seg.text
        if strip_punctuation:
            text = _strip_punct(text)
        if uppercase:
            text = text.upper()
        if text.strip():
            out.append(Segment(seg.start, seg.end, text))
    return out
