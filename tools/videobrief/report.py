"""Сборка итоговых файлов: имя папки и шапка отчёта.

Только stdlib: имена файлов и шапка — то, с чем пользователь сталкивается
каждый раз, поэтому они закрыты тестом.
"""
from __future__ import annotations

import re
import unicodedata

from .transcript import format_tc

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ә": "a", "ғ": "g", "қ": "q", "ң": "n", "ө": "o", "ұ": "u", "ү": "u",
    "һ": "h", "і": "i",
}


def slugify(title: str, fallback: str = "video") -> str:
    """Название ролика -> имя папки: латиница, дефисы, не длиннее 60 символов.

    Кириллица транслитерируется, а не выбрасывается: иначе все казахские и
    русские ролики получили бы одно и то же имя папки и затирали друг друга.
    """
    text = unicodedata.normalize("NFKC", title or "").lower()
    out = []
    for ch in text:
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        else:
            out.append("-")
    slug = re.sub(r"-{2,}", "-", "".join(out)).strip("-")[:60].strip("-")
    return slug or fallback


def folder_name(meta: dict) -> str:
    """Имя папки ролика: '<название>-<id площадки>'.

    Идентификатор в имени нужен против совпадений: у виральных роликов названия
    повторяются («Как я заработал миллион»), и без него один разбор затирал бы
    другой. Повторный прогон того же ролика, наоборот, обязан попадать в ту же
    папку — поэтому идентификатор, а не дата.
    """
    slug = slugify(meta.get("title") or "")
    video_id = re.sub(r"[^A-Za-z0-9_-]", "", str(meta.get("id") or ""))[:12]
    return f"{slug}-{video_id}" if video_id else slug


def header(meta: dict, source_note: str, model: str) -> str:
    """Шапка brief.md: откуда ролик, чем расшифрован, чем разобран."""
    lines = [f"# Разбор: {meta.get('title') or 'ролик без названия'}", ""]
    rows = [
        ("Ссылка", meta.get("url")),
        ("Автор", meta.get("uploader")),
        ("Площадка", meta.get("platform")),
        ("Длительность", format_tc(meta["duration"]) if meta.get("duration") else None),
        ("Просмотры", meta.get("view_count")),
        ("Расшифровка", source_note),
        ("Разбор", model),
    ]
    lines += [f"- **{name}:** {value}" for name, value in rows if value not in (None, "")]
    lines.append("")
    return "\n".join(lines)
