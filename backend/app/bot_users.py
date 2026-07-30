"""Язык интерфейса Telegram-бота — по пользователю (app/telegram_bot.py).

Зачем отдельным модулем и отдельной БД, а не колонкой в licenses.py: язык
нужно знать ДО того, как у пользователя вообще появится лицензия — сначала
выбор языка первым сообщением, потом уже /demo или /buy. Не у каждого, кто
писал боту, есть ключ, поэтому привязка к лицензии не покрыла бы всех.

Только stdlib (sqlite3) — dep-free-тестируемый модуль, как licenses.py/events.py.
"""
from __future__ import annotations

import os
import sqlite3
import threading

from .config import settings

_lock = threading.Lock()
_db_path: str | None = None


def _resolve_db_path() -> str:
    """Файл БД: явный KZSUB_BOT_USERS_DB, иначе том состояния, иначе tmp."""
    global _db_path
    if _db_path is not None:
        return _db_path
    if settings.bot_users_db:
        _db_path = settings.bot_users_db
    elif settings.state_dir:
        _db_path = os.path.join(settings.state_dir, "bot_users.db")
    else:
        _db_path = os.path.join(settings.tmp_dir, "bot_users.db")
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
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db() -> None:
    """Создаёт таблицу языковых предпочтений, если её нет."""
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id TEXT PRIMARY KEY,
                lang    TEXT NOT NULL
            )
            """
        )


def get_lang(user_id) -> str:
    """Выбранный язык пользователя. "" — ещё ни разу не выбирал."""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT lang FROM bot_users WHERE user_id = ?", (str(user_id),)
        ).fetchone()
    return (row["lang"] if row else "") or ""


def set_lang(user_id, lang: str) -> None:
    """Запомнить выбор языка (перезаписывает прежний — /lang меняет в любой момент)."""
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO bot_users (user_id, lang) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang",
            (str(user_id), lang),
        )
