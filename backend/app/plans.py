"""Каталог тарифов NP SUB — единый источник (цена / минуты / срок).

Меняешь тариф — правишь ТОЛЬКО здесь. Цены синхронизированы с
docs/MONETIZATION.md. Используется при выдаче ключей (licenses.create_from_plan
и CLI), а позже — вебхуком оплаты: платёж по тарифу → create_from_plan.

Только stdlib — модуль остаётся dep-free-тестируемым.
"""
from __future__ import annotations

from dataclasses import dataclass

from .licenses import LicenseType


@dataclass(frozen=True)
class Plan:
    name: str               # ключ каталога (demo/standard)
    title: str              # человекочитаемое имя
    license_type: str       # тип лицензии (LicenseType.*)
    minutes: float | None   # включённые минуты (None = безлимит)
    days: int | None        # срок в днях (None = бессрочно)
    price_usd: float
    price_kzt: int


# Тарифная сетка (см. docs/MONETIZATION.md) — единственный платный тариф.
# Standard ограничен ОБОИМИ условиями сразу: 60 минут ИЛИ 30 дней, что
# наступит раньше (эту развилку уже проверяет check_license — оба лимита
# у типа SUBSCRIPTION работают независимо, без отдельного механизма).
PLANS: dict[str, Plan] = {
    "demo":     Plan("demo",     "Demo",     LicenseType.TRIAL,          3, None,  0,    0),
    "standard": Plan("standard", "Standard", LicenseType.SUBSCRIPTION,  60,   30,  3, 1490),
}

ALL: dict[str, Plan] = {**PLANS}


def get_plan(name: str) -> Plan | None:
    return ALL.get((name or "").strip().lower())


def plan_names() -> list[str]:
    return list(ALL.keys())
