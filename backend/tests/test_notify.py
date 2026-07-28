"""Тесты напоминаний о лимите и сроке (dep-free: только stdlib).

Запуск: python tests/test_notify.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import licenses, notify  # noqa: E402
from app.config import settings  # noqa: E402
from app.licenses import LicenseStatus, LicenseType  # noqa: E402


def _fresh():
    licenses.configure(os.path.join(tempfile.mkdtemp(), "lic.db"))
    licenses.init_db()
    settings.notify_enabled = True
    settings.notify_days_before = 3
    settings.notify_min_minutes = 5


def test_warns_before_subscription_expires():
    _fresh()
    lic = licenses.create_license("tg:100", LicenseType.SUBSCRIPTION,
                                  total_minutes=60, days=2)
    hit = notify.reminder_for(lic)
    assert hit is not None and hit[0] == "expiring"
    assert "/buy" in hit[1]

    # За неделю до конца — рано.
    far = licenses.create_license("tg:101", LicenseType.SUBSCRIPTION,
                                  total_minutes=60, days=10)
    assert notify.reminder_for(far) is None


def test_expired_license_is_not_reminded():
    """Истёкшей лицензии напоминать поздно — там сработает обычный отказ."""
    _fresh()
    lic = licenses.create_license("tg:102", LicenseType.SUBSCRIPTION, total_minutes=60)
    lic.expires_at = time.time() - 86400
    assert notify.reminder_for(lic) is None


def test_warns_when_minutes_run_low():
    _fresh()
    lic = licenses.create_license("tg:103", LicenseType.SUBSCRIPTION, total_minutes=60)
    lic.used_minutes = 57.0            # осталось 3 из 60
    hit = notify.reminder_for(lic)
    assert hit is not None and hit[0] == "low_minutes"
    assert "3" in hit[1]


def test_fresh_demo_is_not_warned_immediately():
    """Порог в 5 минут на demo из 3 минут сработал бы прямо при выдаче ключа."""
    _fresh()
    lic = licenses.create_license("tg:104", LicenseType.TRIAL, total_minutes=3)
    assert notify.reminder_for(lic) is None          # ещё ничего не потрачено

    lic.used_minutes = 2.5                            # осталось 0.5 из 3
    hit = notify.reminder_for(lic)
    assert hit is not None and hit[0] == "low_minutes"


def test_developer_and_inactive_are_skipped():
    _fresh()
    dev = licenses.create_license("tg:105", LicenseType.DEVELOPER)
    assert notify.reminder_for(dev) is None

    lic = licenses.create_license("tg:106", LicenseType.SUBSCRIPTION,
                                  total_minutes=60, days=1)
    lic.status = LicenseStatus.REVOKED
    assert notify.reminder_for(lic) is None


def test_same_reminder_is_not_repeated():
    _fresh()
    lic = licenses.create_license("tg:107", LicenseType.SUBSCRIPTION,
                                  total_minutes=60, days=1)
    assert len(notify.pending()) == 1
    licenses.set_notified(lic.api_key, "expiring")
    assert notify.pending() == []


def test_renewal_allows_warning_again():
    """Продление возвращает право предупредить: квота изменилась."""
    _fresh()
    lic = licenses.create_license("tg:108", LicenseType.SUBSCRIPTION,
                                  total_minutes=60, days=1)
    licenses.set_notified(lic.api_key, "expiring")
    assert licenses.get_notified(lic.api_key) == "expiring"

    licenses.renew(lic.api_key, days=1)
    assert licenses.get_notified(lic.api_key) == ""
    assert len(notify.pending()) == 1


def test_topup_also_resets_the_mark():
    _fresh()
    lic = licenses.create_license("tg:109", LicenseType.SUBSCRIPTION, total_minutes=60)
    licenses.set_notified(lic.api_key, "low_minutes")
    licenses.topup(lic.api_key, 30)
    assert licenses.get_notified(lic.api_key) == ""


def test_chat_id_only_for_bot_issued_keys():
    _fresh()
    bot_key = licenses.create_license("tg:12345", LicenseType.TRIAL, total_minutes=3)
    manual = licenses.create_license("client@mail.kz", LicenseType.TRIAL, total_minutes=3)
    assert notify.chat_id_of(bot_key) == "12345"
    assert notify.chat_id_of(manual) == ""      # писать некуда, но и не падаем


def test_send_is_off_without_bot_token():
    _fresh()
    old = settings.telegram_bot_token
    try:
        settings.telegram_bot_token = ""
        licenses.create_license("tg:110", LicenseType.SUBSCRIPTION,
                                total_minutes=60, days=1)
        assert notify.send_reminders() == 0
    finally:
        settings.telegram_bot_token = old


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты напоминаний пройдены.")
