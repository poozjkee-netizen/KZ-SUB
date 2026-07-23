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
    name: str               # ключ каталога (starter/creator/...)
    title: str              # человекочитаемое имя
    license_type: str       # тип лицензии (LicenseType.*)
    minutes: float | None   # включённые минуты (None = безлимит)
    days: int | None        # срок в днях (None = бессрочно)
    price_usd: float
    price_kzt: int


# Тарифная сетка (см. docs/MONETIZATION.md). Подписки — 30 дней.
PLANS: dict[str, Plan] = {
    "free":    Plan("free",    "Free",    LicenseType.TRIAL,           3, None,  0,     0),
    "starter": Plan("starter", "Starter", LicenseType.SUBSCRIPTION,   60,   30,  5,  2490),
    "creator": Plan("creator", "Creator", LicenseType.SUBSCRIPTION,  300,   30, 12,  5990),
    "pro":     Plan("pro",     "Pro",     LicenseType.SUBSCRIPTION, 1200,   30, 29, 14900),
    "studio":  Plan("studio",  "Studio",  LicenseType.SUBSCRIPTION, 3600,   30, 59, 29900),
}

# Разовые пакеты минут (без подписки) — тоже единый источник.
MINUTE_PACKS: dict[str, Plan] = {
    "pack120": Plan("pack120", "Пакет 120 мин", LicenseType.MINUTE_PACK, 120, None,  5, 2490),
    "pack600": Plan("pack600", "Пакет 600 мин", LicenseType.MINUTE_PACK, 600, None, 19, 9490),
}

ALL: dict[str, Plan] = {**PLANS, **MINUTE_PACKS}


def get_plan(name: str) -> Plan | None:
    return ALL.get((name or "").strip().lower())


def plan_names() -> list[str]:
    return list(ALL.keys())
