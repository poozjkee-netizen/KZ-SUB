"""Простейший учёт квоты по API-ключу.

ЭТО ЗАГЛУШКА для MVP: хранит потраченные минуты в памяти процесса.
Для прода заменить на постоянное хранилище (Postgres/Redis) и связать с
биллингом (см. docs/MONETIZATION.md). Интерфейс намеренно оставлен узким,
чтобы реализацию можно было подменить, не трогая main.py.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import settings


class QuotaError(Exception):
    """Квота исчерпана / ключ невалиден."""


@dataclass
class _Usage:
    used_seconds: float = 0.0
    period_start: float = field(default_factory=time.time)


# Демонстрационный набор ключей. В проде — БД пользователей/подписок.
# tier: "free" -> free_minutes_per_month; "pro"/"studio" -> без жёсткого лимита здесь.
_KEYS: dict[str, str] = {
    "dev-key": "pro",       # ключ для локальной разработки
    "free-demo": "free",    # демонстрация бесплатного лимита
}

_usage: dict[str, _Usage] = {}
_MONTH_SECONDS = 30 * 24 * 3600


def _tier(api_key: str) -> str:
    tier = _KEYS.get(api_key)
    if tier is None:
        raise QuotaError("Неизвестный API-ключ")
    return tier


def check_and_reserve(api_key: str, estimated_seconds: float) -> None:
    """Проверяет, что ключу хватает квоты. Бросает QuotaError, если нет."""
    tier = _tier(api_key)
    if tier != "free":
        return  # платные тарифы без лимита на этом уровне (лимитит биллинг)

    u = _usage.setdefault(api_key, _Usage())
    if time.time() - u.period_start > _MONTH_SECONDS:
        u.used_seconds = 0.0
        u.period_start = time.time()

    limit = settings.free_minutes_per_month * 60
    if u.used_seconds + estimated_seconds > limit:
        remaining = max(0, limit - u.used_seconds) / 60
        raise QuotaError(
            f"Бесплатный лимит исчерпан. Осталось ~{remaining:.1f} мин. "
            f"Оформите подписку для продолжения."
        )


def commit(api_key: str, actual_seconds: float) -> None:
    """Списывает фактически обработанные секунды после успешной транскрибации."""
    if _tier(api_key) == "free":
        _usage.setdefault(api_key, _Usage()).used_seconds += actual_seconds
