"""Общие типы данных ASR (чтобы избежать циклических импортов между модулями)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class RawSegment:
    """Сегмент, как его вернул Whisper (до пересборки в аккуратные субтитры)."""
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
