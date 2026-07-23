"""Лицензии и учёт минут NP SUB (постоянное хранилище на SQLite).

Заменяет прежнюю заглушку quota.py (учёт в памяти). Источник правды о доступе —
ТОЛЬКО шлюз (у него эта БД); воркер лицензии не проверяет.

Типы лицензий (поле ``type``):
    developer    — бессрочная, безлимитная, всегда active; только для разработчика.
    trial        — по времени (и опц. по минутам).
    subscription — 30 дней + лимит минут за период (used сбрасывается при продлении).
    minute_pack  — X минут без срока (разовая покупка, тратятся когда угодно).
    lifetime     — навсегда, безлимит (или с fair-use капом через total_minutes).

Поля лицензии: id, api_key, email, type, created_at, expires_at,
total_minutes, used_minutes, status — ровно те, что нужны кабинету/оплате.

Только стандартная библиотека (sqlite3/uuid/secrets) — модуль остаётся
dep-free-тестируемым (см. CLAUDE.md §11) и не тянет fastapi/whisper.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass

from .config import settings


# --- Перечисления (простые строковые константы, без Enum ради простоты) -----
class LicenseType:
    DEVELOPER = "developer"
    TRIAL = "trial"
    SUBSCRIPTION = "subscription"
    MINUTE_PACK = "minute_pack"
    LIFETIME = "lifetime"

    ALL = {DEVELOPER, TRIAL, SUBSCRIPTION, MINUTE_PACK, LIFETIME}


class LicenseStatus:
    ACTIVE = "active"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


# --- Ошибки (http_status → код, который вернёт main.py) ----------------------
class LicenseError(Exception):
    """Базовая ошибка лицензии. http_status — HTTP-код для клиента."""
    http_status = 402


class InvalidKey(LicenseError):
    http_status = 401


class LicenseInactive(LicenseError):     # suspended / revoked
    http_status = 403


class LicenseExpired(LicenseError):
    http_status = 402


class LicenseExhausted(LicenseError):
    http_status = 402


@dataclass
class License:
    id: str
    api_key: str
    email: str
    type: str
    created_at: float
    expires_at: float | None
    total_minutes: float | None
    used_minutes: float
    status: str

    def remaining_minutes(self) -> float | None:
        """Остаток минут (None = безлимит). Для кабинета/заголовка ответа."""
        if self.total_minutes is None:
            return None
        return max(0.0, self.total_minutes - self.used_minutes)


# --- Путь к БД (переопределяемый в тестах через configure) -------------------
_lock = threading.Lock()
_db_path: str | None = None


def _resolve_db_path() -> str:
    """Файл БД: явный KZSUB_LICENSE_DB, иначе том состояния, иначе tmp."""
    global _db_path
    if _db_path is not None:
        return _db_path
    if settings.license_db:
        _db_path = settings.license_db
    elif settings.state_dir:
        _db_path = os.path.join(settings.state_dir, "licenses.db")
    else:
        _db_path = os.path.join(settings.tmp_dir, "licenses.db")
    return _db_path


def configure(path: str) -> None:
    """Задать путь к БД вручную (используется в тестах)."""
    global _db_path
    _db_path = path


def _connect() -> sqlite3.Connection:
    path = _resolve_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # timeout — ждать освобождения блокировки, а не падать с "database is locked"
    # при параллельных запросах (несколько потоков threadpool в одном воркере).
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # читатели не блокируют писателя
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db() -> None:
    """Создаёт таблицу лицензий, если её нет."""
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS licenses (
                id            TEXT PRIMARY KEY,
                api_key       TEXT UNIQUE NOT NULL,
                email         TEXT,
                type          TEXT NOT NULL,
                created_at    REAL NOT NULL,
                expires_at    REAL,
                total_minutes REAL,
                used_minutes  REAL NOT NULL DEFAULT 0,
                status        TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_licenses_api_key ON licenses(api_key)")


def _row_to_license(row: sqlite3.Row) -> License:
    return License(
        id=row["id"],
        api_key=row["api_key"],
        email=row["email"] or "",
        type=row["type"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        total_minutes=row["total_minutes"],
        used_minutes=row["used_minutes"],
        status=row["status"],
    )


def get_license(api_key: str) -> License | None:
    if not api_key:
        return None
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM licenses WHERE api_key = ?", (api_key,)
        ).fetchone()
    return _row_to_license(row) if row else None


def _gen_key() -> str:
    """Секретный клиентский ключ (то, что панель шлёт в X-API-Key)."""
    return "kzsub_" + secrets.token_urlsafe(24)


def create_license(
    email: str,
    type: str,
    total_minutes: float | None = None,
    days: int | None = None,
    api_key: str | None = None,
    status: str = LicenseStatus.ACTIVE,
) -> License:
    """Создаёт лицензию. days → expires_at = now + days; иначе бессрочно."""
    if type not in LicenseType.ALL:
        raise ValueError(f"Неизвестный тип лицензии: {type}")
    now = time.time()
    lic = License(
        id=uuid.uuid4().hex,
        api_key=api_key or _gen_key(),
        email=email or "",
        type=type,
        created_at=now,
        expires_at=(now + days * 86400) if days else None,
        total_minutes=total_minutes,
        used_minutes=0.0,
        status=status,
    )
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO licenses
               (id, api_key, email, type, created_at, expires_at,
                total_minutes, used_minutes, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (lic.id, lic.api_key, lic.email, lic.type, lic.created_at,
             lic.expires_at, lic.total_minutes, lic.used_minutes, lic.status),
        )
    return lic


def create_from_plan(email: str, plan_name: str, api_key: str | None = None) -> License:
    """Выдаёт лицензию по тарифу из каталога plans.py (минуты/срок/тип оттуда).

    Это шов для будущего вебхука оплаты: платёж по тарифу → create_from_plan.
    Импорт plans локальный — plans зависит от licenses (LicenseType), не наоборот.
    """
    from .plans import get_plan  # локально: избегаем кругового импорта

    plan = get_plan(plan_name)
    if plan is None:
        raise ValueError(f"Неизвестный тариф: {plan_name}")
    return create_license(
        email=email, type=plan.license_type,
        total_minutes=plan.minutes, days=plan.days, api_key=api_key,
    )


def check_license(api_key: str, estimated_minutes: float = 0.0) -> License:
    """Проверка при каждом запросе: существование, статус, срок, лимит минут.

    Бросает подкласс LicenseError (с http_status) при проблеме, иначе возвращает
    актуальную лицензию. Developer-лицензия проходит без проверок.
    """
    lic = get_license(api_key)
    if lic is None:
        raise InvalidKey("Неизвестный API-ключ")

    if lic.type == LicenseType.DEVELOPER:
        return lic  # безлимитный разработчик — все проверки пропускаем

    if lic.status in (LicenseStatus.SUSPENDED, LicenseStatus.REVOKED):
        raise LicenseInactive(f"Лицензия недоступна ({lic.status})")

    if lic.expires_at is not None and time.time() > lic.expires_at:
        _set_status(lic.api_key, LicenseStatus.EXPIRED)
        raise LicenseExpired("Срок действия лицензии истёк")

    if lic.total_minutes is not None:
        if lic.used_minutes + estimated_minutes > lic.total_minutes:
            if lic.used_minutes >= lic.total_minutes:
                _set_status(lic.api_key, LicenseStatus.EXHAUSTED)
            raise LicenseExhausted("Лимит минут исчерпан")

    return lic


def commit_usage(api_key: str, actual_minutes: float) -> None:
    """Списывает фактически обработанные минуты после успешной транскрибации."""
    lic = get_license(api_key)
    if lic is None or lic.type == LicenseType.DEVELOPER:
        return
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE licenses SET used_minutes = used_minutes + ? WHERE api_key = ?",
            (max(0.0, actual_minutes), api_key),
        )
        # Если минуты выбраны полностью — помечаем лицензию как исчерпанную.
        row = conn.execute(
            "SELECT total_minutes, used_minutes FROM licenses WHERE api_key = ?",
            (api_key,),
        ).fetchone()
        if row and row["total_minutes"] is not None and \
                row["used_minutes"] >= row["total_minutes"]:
            conn.execute(
                "UPDATE licenses SET status = ? WHERE api_key = ?",
                (LicenseStatus.EXHAUSTED, api_key),
            )


def _set_status(api_key: str, status: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE licenses SET status = ? WHERE api_key = ?", (status, api_key)
        )


# --- Админ-хелперы (задел под кабинет/оплату/смену тарифа) -------------------
def revoke(api_key: str) -> None:
    _set_status(api_key, LicenseStatus.REVOKED)


def suspend(api_key: str) -> None:
    _set_status(api_key, LicenseStatus.SUSPENDED)


def activate(api_key: str) -> None:
    _set_status(api_key, LicenseStatus.ACTIVE)


def renew(api_key: str, days: int = 30, reset_minutes: bool = True) -> None:
    """Продление подписки: сдвигает срок и (опц.) обнуляет израсходованные минуты."""
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE licenses
               SET expires_at = ?,
                   used_minutes = CASE WHEN ? THEN 0 ELSE used_minutes END,
                   status = ?
               WHERE api_key = ?""",
            (time.time() + days * 86400, 1 if reset_minutes else 0,
             LicenseStatus.ACTIVE, api_key),
        )


def topup(api_key: str, minutes: float) -> None:
    """Пополнение минут (minute_pack): увеличивает лимит и снимает 'исчерпан'."""
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE licenses
               SET total_minutes = COALESCE(total_minutes, 0) + ?,
                   status = ?
               WHERE api_key = ?""",
            (minutes, LicenseStatus.ACTIVE, api_key),
        )


def delete_license(api_key: str) -> bool:
    """Удаляет лицензию НАВСЕГДА из БД. True — если что-то удалено."""
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM licenses WHERE api_key = ?", (api_key,))
        return cur.rowcount > 0


def purge_revoked() -> int:
    """Удаляет ВСЕ отозванные (revoked) лицензии. Возвращает число удалённых."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "DELETE FROM licenses WHERE status = ?", (LicenseStatus.REVOKED,)
        )
        return cur.rowcount


def change_plan(
    api_key: str, type: str, total_minutes: float | None = None,
    days: int | None = None,
) -> None:
    """Смена тарифа: обновляет тип, лимит и срок (задел под апгрейд/даунгрейд)."""
    if type not in LicenseType.ALL:
        raise ValueError(f"Неизвестный тип лицензии: {type}")
    expires = (time.time() + days * 86400) if days else None
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE licenses
               SET type = ?, total_minutes = ?, expires_at = ?, status = ?
               WHERE api_key = ?""",
            (type, total_minutes, expires, LicenseStatus.ACTIVE, api_key),
        )


def describe(api_key: str) -> dict | None:
    """Состояние лицензии БЕЗ побочных эффектов (для эндпоинта /license и кабинета).

    Возвращает None, если ключа нет. Иначе — dict с active/status/type/остатком,
    не меняя статус в БД (в отличие от check_license, который его фиксирует).
    """
    lic = get_license(api_key)
    if lic is None:
        return None
    active = True
    status = lic.status
    if lic.type == LicenseType.DEVELOPER:
        active, status = True, LicenseStatus.ACTIVE
    elif lic.status in (LicenseStatus.SUSPENDED, LicenseStatus.REVOKED):
        active = False
    elif lic.expires_at is not None and time.time() > lic.expires_at:
        active, status = False, LicenseStatus.EXPIRED
    elif lic.total_minutes is not None and lic.used_minutes >= lic.total_minutes:
        active, status = False, LicenseStatus.EXHAUSTED
    return {
        "active": active,
        "status": status,
        "type": lic.type,
        "remaining_minutes": lic.remaining_minutes(),
        "expires_at": lic.expires_at,
    }


def list_licenses() -> list[License]:
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT * FROM licenses ORDER BY created_at DESC").fetchall()
    return [_row_to_license(r) for r in rows]


# --- Начальное наполнение (developer-ключ + опц. ключи из env) ---------------
def _seed(**kwargs) -> None:
    """Идемпотентный засев одной лицензии.

    Молча игнорируем UNIQUE-гонку: uvicorn запускается с несколькими воркерами,
    и каждый процесс выполняет ensure_seeded() на старте — без этого второй
    воркер падал на `UNIQUE constraint failed`, роняя всё приложение.
    """
    try:
        create_license(**kwargs)
    except sqlite3.Error:
        pass  # ключ уже создан другим воркером/ранее, либо гонка блокировки


def ensure_seeded() -> None:
    """Готовит БД к работе: таблица + developer-ключ + бутстрап-ключи из env.

    Тестовых ключей по умолчанию НЕТ (в отличие от старой quota.py). Пустой env
    → в БД только developer-ключ (если задан KZSUB_DEVELOPER_KEY).
    """
    init_db()

    dev = settings.developer_key.strip()
    if dev and get_license(dev) is None:
        _seed(email="developer@np-sub", type=LicenseType.DEVELOPER, api_key=dev)

    # Бутстрап из KZSUB_API_KEYS="ключ:тариф,..." — для ключей, выданных вручную
    # до появления оплаты/кабинета. Идемпотентно: вставляем только отсутствующие.
    raw = settings.api_keys.strip()
    if not raw:
        return
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, _, tier = pair.partition(":")
        key = key.strip()
        tier = (tier.strip() or "pro").lower()
        if not key or get_license(key) is not None:
            continue
        if tier == "free":
            _seed(email="", type=LicenseType.TRIAL, api_key=key,
                  total_minutes=settings.free_minutes_per_month)
        else:
            # Легаси pro/studio — бессрочная безлимитная подписка (как раньше).
            _seed(email="", type=LicenseType.SUBSCRIPTION, api_key=key)


# --- Мини-CLI для ручной выдачи ключей (ops до автоматизации оплаты) ---------
def _main() -> None:
    import argparse
    from datetime import datetime, timezone

    p = argparse.ArgumentParser(description="Управление лицензиями NP SUB")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="создать лицензию")
    c.add_argument("--email", default="")
    c.add_argument("--plan", default=None, help="тариф из каталога (см. команду plans)")
    c.add_argument("--type", default=None, choices=sorted(LicenseType.ALL),
                   help="или вручную: тип лицензии (если без --plan)")
    c.add_argument("--minutes", type=float, default=None, help="лимит минут (пусто = безлимит)")
    c.add_argument("--days", type=int, default=None, help="срок в днях (пусто = бессрочно)")
    c.add_argument("--key", default=None, help="задать ключ вручную (иначе сгенерируется)")

    sub.add_parser("list", help="список лицензий")
    sub.add_parser("plans", help="показать каталог тарифов")

    for name in ("revoke", "suspend", "activate"):
        s = sub.add_parser(name, help=f"{name} лицензию")
        s.add_argument("api_key")

    dl = sub.add_parser("delete", help="удалить лицензию НАВСЕГДА")
    dl.add_argument("api_key")

    sub.add_parser("purge-revoked", help="удалить ВСЕ отозванные лицензии")

    r = sub.add_parser("renew", help="продлить подписку")
    r.add_argument("api_key")
    r.add_argument("--days", type=int, default=30)

    tp = sub.add_parser("topup", help="пополнить минуты")
    tp.add_argument("api_key")
    tp.add_argument("--minutes", type=float, required=True)

    args = p.parse_args()
    init_db()

    def fmt_ts(ts):
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d") if ts else "—"

    if args.cmd == "create":
        if args.plan:
            lic = create_from_plan(args.email, args.plan, args.key)
        elif args.type:
            lic = create_license(args.email, args.type, args.minutes, args.days, args.key)
        else:
            p.error("нужен --plan <тариф> или --type <тип>")
        print("Создана лицензия:")
        print("  api_key :", lic.api_key)
        print("  type    :", lic.type)
        print("  minutes :", "∞" if lic.total_minutes is None else lic.total_minutes)
        print("  expires :", fmt_ts(lic.expires_at))
    elif args.cmd == "plans":
        from .plans import ALL as _PLANS
        for pl in _PLANS.values():
            mins = "∞" if pl.minutes is None else int(pl.minutes)
            days = "бессрочно" if pl.days is None else f"{pl.days} дн."
            print(f"{pl.name:9} {pl.title:14} мин={mins:<5} {days:11} "
                  f"${pl.price_usd:<3g} / {pl.price_kzt}₸  [{pl.license_type}]")
    elif args.cmd == "list":
        for lic in list_licenses():
            rem = "∞" if lic.remaining_minutes() is None else f"{lic.remaining_minutes():.0f}"
            print(f"{lic.api_key}  {lic.type:12}  {lic.status:9}  "
                  f"осталось={rem}  до={fmt_ts(lic.expires_at)}  {lic.email}")
    elif args.cmd in ("revoke", "suspend", "activate"):
        _set_status(args.api_key,
                    {"revoke": LicenseStatus.REVOKED,
                     "suspend": LicenseStatus.SUSPENDED,
                     "activate": LicenseStatus.ACTIVE}[args.cmd])
        print(f"{args.cmd}: {args.api_key}")
    elif args.cmd == "delete":
        ok = delete_license(args.api_key)
        print(("удалено: " if ok else "не найдено: ") + args.api_key)
    elif args.cmd == "purge-revoked":
        n = purge_revoked()
        print(f"удалено отозванных лицензий: {n}")
    elif args.cmd == "renew":
        renew(args.api_key, args.days)
        print(f"продлено на {args.days} дн.: {args.api_key}")
    elif args.cmd == "topup":
        topup(args.api_key, args.minutes)
        print(f"+{args.minutes} мин: {args.api_key}")


if __name__ == "__main__":
    _main()
