"""Постобработка распознанного текста: зацикливания и пользовательский словарь.

Работает на ШЛЮЗЕ, поверх уже нарезанных и оформленных реплик (в прокси-режиме
их присылает воркер). Так сделано осознанно: правки здесь катятся одним
`fly deploy`, а те же изменения внутри воркера потребовали бы пересборки
GPU-образа и смены образа у эндпоинта Runpod (см. золотое правило CLAUDE.md).

Что чинит:
    1. Зацикливания Whisper — модель на тишине/шуме залипает и печатает одно и
       то же слово десятки раз подряд. В караоке-режиме это выглядит как стена
       одинаковых субтитров.
    2. Повторяющиеся ошибки на именах и терминах — исправляются словарём
       (KZSUB_LEXICON / KZSUB_LEXICON_PATH), без переобучения модели.
    3. Опционально — реплики с неправдоподобной длительностью (галлюцинации в
       тишине обычно получают долгий тайм-код). По умолчанию выключено.

Только stdlib — модуль остаётся dep-free-тестируемым (CLAUDE.md §11).
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata

from .config import settings
from .srt import Segment

logger = logging.getLogger("kzsub.postprocess")


def _norm(text: str) -> str:
    """Ключ для сравнения реплик: регистр и диакритика не должны мешать."""
    return unicodedata.normalize("NFC", text).casefold().strip()


def collapse_repeats(segments: list[Segment], max_repeats: int) -> list[Segment]:
    """Оставляет не больше max_repeats одинаковых реплик подряд.

    Порог, а не полное удаление: повтор слова — нормальная речь («жоқ, жоқ»),
    а вот длинная серия одинаковых реплик — признак зацикливания модели.
    max_repeats <= 0 отключает фильтр.
    """
    if max_repeats <= 0 or not segments:
        return segments

    out: list[Segment] = []
    streak_key: str | None = None
    streak = 0
    dropped = 0
    for seg in segments:
        key = _norm(seg.text)
        if key and key == streak_key:
            streak += 1
        else:
            streak_key, streak = key, 1
        if streak <= max_repeats:
            out.append(seg)
        else:
            dropped += 1
    if dropped:
        logger.info("Отброшено %d повторов (зацикливание модели)", dropped)
    return out


def drop_long_cues(segments: list[Segment], max_seconds: float) -> list[Segment]:
    """Убирает реплики длиннее max_seconds (0 = выключено).

    Галлюцинация в тишине обычно получает неправдоподобно долгий тайм-код,
    тогда как настоящее слово в караоке-режиме занимает доли секунды.
    """
    if max_seconds <= 0:
        return segments
    out = [s for s in segments if (s.end - s.start) <= max_seconds]
    if len(out) != len(segments):
        logger.info("Отброшено %d слишком долгих реплик", len(segments) - len(out))
    return out


def parse_lexicon(raw: str) -> list[tuple[str, str]]:
    """Разбирает правила словаря: «было=стало», по строке или через запятую.

    Пустая правая часть («мусор=») означает удалить слово. Порядок правил
    сохраняется — более специфичные можно поставить выше.
    """
    rules: list[tuple[str, str]] = []
    for chunk in re.split(r"[\n,]", raw or ""):
        item = chunk.strip()
        if not item or item.startswith("#") or "=" not in item:
            continue
        wrong, _, right = item.partition("=")
        wrong = wrong.strip()
        if wrong:
            rules.append((wrong, right.strip()))
    return rules


def load_lexicon() -> list[tuple[str, str]]:
    """Правила из KZSUB_LEXICON и/или файла KZSUB_LEXICON_PATH."""
    rules = parse_lexicon(settings.lexicon)
    path = settings.lexicon_path.strip()
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8-sig") as f:
                rules += parse_lexicon(f.read())
        except OSError as e:
            logger.warning("Словарь %s не прочитан: %s", path, e)
    return rules


def _match_case(source: str, replacement: str) -> str:
    """Подгоняет регистр замены под найденное слово.

    Правила:
      • НАЙДЕНО КАПСОМ  → замена капсом. Обязательно: оформление (ВЕРХНИЙ
        регистр) применяется ДО постобработки, иначе исправление вставляло бы
        строчные буквы в текст из заглавных.
      • Найдено С Заглавной → замена с заглавной (сохраняем начало предложения).
      • найдено строчными → замена как написана в правиле. Так задумано:
        правило «алматы=Алматы» существует именно чтобы поправить регистр
        имени собственного, и навязывать ему строчные было бы неверно.
    """
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def apply_lexicon(segments: list[Segment], rules: list[tuple[str, str]]) -> list[Segment]:
    """Применяет словарь замен по границам слов, сохраняя регистр.

    Реплики, опустевшие после удаления слова, отбрасываются.
    """
    if not rules or not segments:
        return segments

    compiled = [
        (re.compile(r"(?<!\w)" + re.escape(wrong) + r"(?!\w)", re.IGNORECASE), right)
        for wrong, right in rules
    ]

    out: list[Segment] = []
    changed = 0
    for seg in segments:
        text = seg.text
        for pattern, right in compiled:
            text = pattern.sub(lambda m: _match_case(m.group(0), right), text)
        text = " ".join(text.split())
        if text != seg.text:
            changed += 1
        if text:
            out.append(Segment(seg.start, seg.end, text))
    if changed:
        logger.info("Словарь исправил %d реплик", changed)
    return out


def postprocess(segments: list[Segment]) -> list[Segment]:
    """Полный проход постобработки по настройкам (вызывается из main.py)."""
    segments = collapse_repeats(segments, settings.max_repeats)
    segments = drop_long_cues(segments, settings.max_cue_drop_seconds)
    return apply_lexicon(segments, load_lexicon())
