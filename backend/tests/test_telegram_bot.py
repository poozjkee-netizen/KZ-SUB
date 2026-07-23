"""Тесты Telegram-бота выдачи ключей (сеть замокана, БД лицензий временная).

Запуск без тяжёлых пакетов: python tests/test_telegram_bot.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import licenses, telegram_bot  # noqa: E402
from app.config import settings  # noqa: E402
from app.licenses import LicenseType  # noqa: E402

_tmpdir = tempfile.mkdtemp()
_n = [0]
_sent = []  # захваченные вызовы: (kind, chat_id/cq_id, text, reply_markup)


def _fresh():
    """Свежая пустая БД лицензий + один настроенный админ (id 111)."""
    _n[0] += 1
    licenses.configure(os.path.join(_tmpdir, f"lic_{_n[0]}.db"))
    licenses.init_db()
    _sent.clear()
    settings.telegram_admin_ids = "111"
    settings.telegram_bot_token = "test-token"  # чтобы _call не жаловался в логах


def _patch_network():
    """Подменяем реальные HTTP-вызовы Telegram на запись в _sent."""
    def fake_send(chat_id, text, reply_markup=None):
        _sent.append(("send", chat_id, text, reply_markup))
        return {"ok": True, "result": {"message_id": 1, "chat": {"id": chat_id}}}

    def fake_edit(chat_id, message_id, text, reply_markup=None):
        _sent.append(("edit", chat_id, text, reply_markup))
        return {"ok": True}

    def fake_answer(cq_id, text=None, show_alert=False):
        _sent.append(("answer", cq_id, text))
        return {"ok": True}

    telegram_bot.send_message = fake_send
    telegram_bot.edit_message_text = fake_edit
    telegram_bot.answer_callback_query = fake_answer


def _sent_texts(chat_id=None):
    return [s[2] for s in _sent if s[0] == "send" and (chat_id is None or str(s[1]) == str(chat_id))]


def test_demo_issues_key_once_per_account():
    _fresh(); _patch_network()
    update = {"message": {"chat": {"id": 1}, "from": {"id": 42}, "text": "/demo"}}

    telegram_bot.handle_update(update)
    lic = licenses.find_by_email("tg:42", LicenseType.TRIAL)
    assert lic is not None and lic.total_minutes == 3
    assert any(lic.api_key in t for t in _sent_texts(1))

    _sent.clear()
    telegram_bot.handle_update(update)  # повторный /demo — второй ключ не выдаём
    assert len(licenses.list_licenses()) == 1
    assert any("уже был выдан" in t for t in _sent_texts(1))


def test_buy_then_admin_approve_issues_standard_key():
    _fresh(); _patch_network()

    pay_update = {"callback_query": {
        "id": "cq1", "data": "pay:1:42",
        "from": {"id": 42, "username": "client"},
        "message": {"chat": {"id": 1}, "message_id": 5},
    }}
    telegram_bot.handle_update(pay_update)
    # заявка ушла админу (id=111), ключ ещё НЕ выдан
    assert _sent_texts(111), "ожидалось уведомление админу"
    assert licenses.find_by_email("tg:42", LicenseType.SUBSCRIPTION) is None

    _sent.clear()
    non_admin = {"callback_query": {
        "id": "cq2", "data": "confirm:1:42",
        "from": {"id": 999}, "message": {"chat": {"id": 111}, "message_id": 6},
    }}
    telegram_bot.handle_update(non_admin)
    assert licenses.find_by_email("tg:42", LicenseType.SUBSCRIPTION) is None  # не-админ не подтверждает

    _sent.clear()
    admin_confirm = {"callback_query": {
        "id": "cq3", "data": "confirm:1:42",
        "from": {"id": 111}, "message": {"chat": {"id": 111}, "message_id": 6},
    }}
    telegram_bot.handle_update(admin_confirm)
    lic = licenses.find_by_email("tg:42", LicenseType.SUBSCRIPTION)
    assert lic is not None and lic.total_minutes == 60
    assert any(lic.api_key in t for t in _sent_texts(1))  # ключ ушёл клиенту (chat_id=1)


def test_double_confirm_does_not_issue_second_key():
    _fresh(); _patch_network()
    confirm = {"callback_query": {
        "id": "cqX", "data": "confirm:7:55",
        "from": {"id": 111}, "message": {"chat": {"id": 111}, "message_id": 9},
    }}
    telegram_bot.handle_update(confirm)
    telegram_bot.handle_update(confirm)  # повторное подтверждение (гонка/двойной клик)
    matches = [lic for lic in licenses.list_licenses() if lic.email == "tg:55"]
    assert len(matches) == 1


def test_reject_does_not_issue_key():
    _fresh(); _patch_network()
    reject = {"callback_query": {
        "id": "cq4", "data": "reject:1:42",
        "from": {"id": 111}, "message": {"chat": {"id": 111}, "message_id": 7},
    }}
    telegram_bot.handle_update(reject)
    assert licenses.find_by_email("tg:42", LicenseType.SUBSCRIPTION) is None
    assert any("не найдена" in t for t in _sent_texts(1))


def test_whoami_replies_with_id():
    _fresh(); _patch_network()
    update = {"message": {"chat": {"id": 3}, "from": {"id": 777}, "text": "/whoami"}}
    telegram_bot.handle_update(update)
    assert any("777" in t for t in _sent_texts(3))


def test_unknown_command_gets_welcome():
    _fresh(); _patch_network()
    update = {"message": {"chat": {"id": 3}, "from": {"id": 777}, "text": "что это"}}
    telegram_bot.handle_update(update)
    assert any("NP SUB" in t for t in _sent_texts(3))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты Telegram-бота пройдены.")
