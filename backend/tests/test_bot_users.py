"""Тесты хранения языка Telegram-бота (dep-free: только stdlib sqlite3).

Запуск: python tests/test_bot_users.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import bot_users  # noqa: E402


def _fresh():
    bot_users.configure(os.path.join(tempfile.mkdtemp(), "bot_users.db"))
    bot_users.init_db()


def test_unknown_user_has_empty_lang():
    _fresh()
    assert bot_users.get_lang(12345) == ""


def test_set_then_get_roundtrip():
    _fresh()
    bot_users.set_lang(42, "kk")
    assert bot_users.get_lang(42) == "kk"
    # Другой пользователь не задет.
    assert bot_users.get_lang(43) == ""


def test_lang_command_can_overwrite_choice():
    """/lang должен уметь сменить выбор в любой момент, а не только задать один раз."""
    _fresh()
    bot_users.set_lang(42, "ru")
    assert bot_users.get_lang(42) == "ru"
    bot_users.set_lang(42, "kk")
    assert bot_users.get_lang(42) == "kk"


def test_user_id_is_stored_as_string_regardless_of_input_type():
    """Telegram присылает user_id числом, а колонка — TEXT: не должно рассыпаться."""
    _fresh()
    bot_users.set_lang(999, "ru")
    assert bot_users.get_lang("999") == "ru"
    assert bot_users.get_lang(999) == "ru"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты языка бота пройдены.")
