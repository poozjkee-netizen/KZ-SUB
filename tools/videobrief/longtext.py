"""Подготовка длинной расшифровки под маленькое окно локальной модели.

У локальных моделей окно контекста в разы меньше облачных, и длинный ролик в
него не влезает. Резать «по последнему символу» нельзя — потеряется конец
ролика, а вместе с ним вывод и призыв к действию. Поэтому длинная расшифровка
сначала сжимается по частям, и разбор идёт уже по конспекту.

Только stdlib: это чистая работа с текстом, закрытая тестами.
"""
from __future__ import annotations


def split_lines(text: str, max_chars: int) -> list[str]:
    """Режет текст на части не длиннее max_chars, не разрывая строки.

    Строка расшифровки — это «[тайм-код] реплика», поэтому граница части всегда
    проходит между репликами: в каждой части остаются свои тайм-коды, и после
    сжатия их можно собрать обратно в один конспект по порядку.
    """
    if max_chars <= 0:
        return [text] if text.strip() else []
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines():
        extra = len(line) + 1
        if current and size + extra > max_chars:
            parts.append("\n".join(current))
            current, size = [], 0
        # Строка длиннее лимита целиком (расшифровка без тайм-кодов) — кладём
        # как есть: рвать её было бы хуже, модель сама справится с перебором.
        current.append(line)
        size += extra
    if current:
        parts.append("\n".join(current))
    return [p for p in parts if p.strip()]


def needs_condensing(text: str, max_chars: int) -> bool:
    """Нужен ли предварительный пересказ по частям."""
    return max_chars > 0 and len(text) > max_chars
