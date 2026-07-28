"""Учёт событий прода: сколько прогонов, минут, отказов и по каким причинам.

Зачем: без цифр нельзя калибровать лимиты, цену и приоритеты — решения
превращаются в догадки (см. docs/tasks/06-analytics.md). Учёт минут уже ведут
лицензии, здесь — то, чего в них нет: частота прогонов, время обработки,
структура отказов (упёрся в лимит ≠ упал сервис) и удержание по дням.

Что НЕ пишем принципиально: ни аудио, ни распознанный текст, ни сам ключ.
Ключ и устройство хранятся только как короткий хеш — этого хватает, чтобы
считать уникальных пользователей и повторные визиты, но по базе нельзя
восстановить ни ключ, ни содержимое ролика.

Только stdlib (sqlite3) — модуль обязан оставаться dep-free-тестируемым.

CLI:
    python -m app.events summary --days 7
    python -m app.events recent --limit 20
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from dataclasses import dataclass

from .config import settings

_lock = threading.Lock()
_db_path: str | None = None


def _resolve_db_path() -> str:
    """Файл БД: явный KZSUB_EVENTS_DB, иначе том состояния, иначе tmp."""
    global _db_path
    if _db_path is not None:
        return _db_path
    if settings.events_db:
        _db_path = settings.events_db
    elif settings.state_dir:
        _db_path = os.path.join(settings.state_dir, "events.db")
    else:
        _db_path = os.path.join(settings.tmp_dir, "events.db")
    return _db_path


def configure(path: str) -> None:
    """Задать путь к БД вручную (используется в тестах)."""
    global _db_path
    _db_path = path


def anon(value: str) -> str:
    """Короткий необратимый идентификатор: считать уникальных, но не узнать кого."""
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _connect() -> sqlite3.Connection:
    path = _resolve_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db() -> None:
    """Создаёт таблицу событий, если её нет."""
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                at          REAL NOT NULL,
                key_hash    TEXT NOT NULL,
                device_hash TEXT,
                license     TEXT,
                mode        TEXT,
                status      TEXT NOT NULL,
                reason      TEXT,
                audio_sec   REAL NOT NULL DEFAULT 0,
                wall_sec    REAL NOT NULL DEFAULT 0,
                segments    INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_at ON runs(at)")


def record_run(
    api_key: str,
    status: str,
    *,
    device_id: str = "",
    license_type: str = "",
    mode: str = "",
    reason: str = "",
    audio_seconds: float = 0.0,
    wall_seconds: float = 0.0,
    segments: int = 0,
) -> None:
    """Записать один прогон. Никогда не бросает исключений.

    Аналитика не имеет права ронять продукт: если БД недоступна или заблокирована,
    пользователь всё равно должен получить свои субтитры.
    """
    if not settings.analytics:
        return
    row = (time.time(), anon(api_key), anon(device_id), license_type, mode,
           status, reason, float(audio_seconds), float(wall_seconds), int(segments))
    try:
        _insert(row)
    except Exception:  # noqa: BLE001
        # Чаще всего это «no such table» на свежем томе: startup мог не успеть
        # или БД пересоздали. Чиним на месте и пробуем ещё раз — иначе учёт
        # молча замолчал бы навсегда, а заметили бы это по пустому отчёту.
        try:
            init_db()
            _insert(row)
        except Exception:  # noqa: BLE001 — намеренно проглатываем ошибку учёта
            pass


def _insert(row: tuple) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO runs (at, key_hash, device_hash, license, mode, status,"
            " reason, audio_sec, wall_sec, segments)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )


@dataclass
class Summary:
    """Срез за период: то, по чему принимаются решения о цене и лимитах."""
    days: int
    runs: int
    users: int
    ok: int
    failed: int
    audio_minutes: float
    gpu_minutes: float
    reasons: list[tuple[str, int]]
    by_license: list[tuple[str, int]]

    @property
    def success_rate(self) -> float:
        return (self.ok / self.runs) if self.runs else 0.0

    @property
    def minutes_per_user(self) -> float:
        return (self.audio_minutes / self.users) if self.users else 0.0

    @property
    def realtime_factor(self) -> float:
        """Сколько секунд обработки на секунду аудио — рычаг маржи.

        Меньше единицы значит, что минута ролика стоит меньше минуты GPU.
        """
        return (self.gpu_minutes / self.audio_minutes) if self.audio_minutes else 0.0


def summary(days: int = 7) -> Summary:
    """Агрегат за последние N дней."""
    since = time.time() - days * 86400
    init_db()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS runs, COUNT(DISTINCT key_hash) AS users,"
            " SUM(status = 'ok') AS ok, SUM(audio_sec) AS audio, SUM(wall_sec) AS wall"
            " FROM runs WHERE at >= ?",
            (since,),
        ).fetchone()
        reasons = conn.execute(
            "SELECT reason, COUNT(*) AS n FROM runs"
            " WHERE at >= ? AND status <> 'ok' AND reason <> ''"
            " GROUP BY reason ORDER BY n DESC",
            (since,),
        ).fetchall()
        by_license = conn.execute(
            "SELECT license, COUNT(*) AS n FROM runs WHERE at >= ? AND license <> ''"
            " GROUP BY license ORDER BY n DESC",
            (since,),
        ).fetchall()

    runs = row["runs"] or 0
    ok = row["ok"] or 0
    return Summary(
        days=days,
        runs=runs,
        users=row["users"] or 0,
        ok=ok,
        failed=runs - ok,
        audio_minutes=(row["audio"] or 0.0) / 60.0,
        gpu_minutes=(row["wall"] or 0.0) / 60.0,
        reasons=[(r["reason"], r["n"]) for r in reasons],
        by_license=[(r["license"], r["n"]) for r in by_license],
    )


def recent(limit: int = 20) -> list[sqlite3.Row]:
    """Последние прогоны — для быстрой отладки «что сейчас происходит»."""
    init_db()
    with _lock, _connect() as conn:
        return conn.execute(
            "SELECT * FROM runs ORDER BY at DESC LIMIT ?", (limit,)
        ).fetchall()


def _main() -> None:
    import argparse
    import datetime

    p = argparse.ArgumentParser(description="Метрики прода NP SUB")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("summary", help="срез за период")
    s.add_argument("--days", type=int, default=7)

    r = sub.add_parser("recent", help="последние прогоны")
    r.add_argument("--limit", type=int, default=20)

    args = p.parse_args()

    if args.cmd == "summary":
        m = summary(args.days)
        print(f"За {m.days} дн.: прогонов {m.runs}, пользователей {m.users}")
        print(f"  успешных {m.ok} / отказов {m.failed} "
              f"({m.success_rate * 100:.1f}% успеха)")
        print(f"  аудио {m.audio_minutes:.1f} мин, обработка {m.gpu_minutes:.1f} мин "
              f"(x{m.realtime_factor:.2f} от длительности)")
        print(f"  на пользователя {m.minutes_per_user:.1f} мин")
        if m.by_license:
            print("  по тарифам: " + ", ".join(f"{k or '—'} {n}" for k, n in m.by_license))
        if m.reasons:
            print("  причины отказов:")
            for reason, n in m.reasons:
                print(f"    {reason}: {n}")
        return

    print(f"{'когда':<20} {'тариф':<12} {'статус':<8} {'причина':<16} "
          f"{'аудио,с':>8} {'обраб,с':>8}")
    for row in recent(args.limit):
        when = datetime.datetime.fromtimestamp(row["at"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{when:<20} {row['license'] or '—':<12} {row['status']:<8} "
              f"{row['reason'] or '—':<16} {row['audio_sec']:>8.1f} {row['wall_sec']:>8.1f}")


if __name__ == "__main__":
    _main()
