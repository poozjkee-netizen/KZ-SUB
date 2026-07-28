"""Тесты учёта прогонов (dep-free: только stdlib sqlite3).

Запуск: python tests/test_events.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import events  # noqa: E402
from app.config import settings  # noqa: E402


def _fresh_db():
    events.configure(os.path.join(tempfile.mkdtemp(), "events.db"))
    events.init_db()


def test_summary_counts_runs_users_and_failures():
    _fresh_db()
    events.record_run("key-a", "ok", license_type="demo", audio_seconds=60,
                      wall_seconds=20, segments=30)
    events.record_run("key-a", "ok", license_type="demo", audio_seconds=120,
                      wall_seconds=40, segments=55)
    events.record_run("key-b", "error", license_type="demo", reason="http_402")

    m = events.summary(days=1)
    assert m.runs == 3
    assert m.users == 2                    # ключей два, прогонов три
    assert (m.ok, m.failed) == (2, 1)
    assert abs(m.audio_minutes - 3.0) < 1e-9
    assert m.reasons == [("http_402", 1)]
    assert m.by_license == [("demo", 3)]


def test_realtime_factor_is_the_margin_lever():
    """Секунды обработки на секунду аудио — из этого считается стоимость минуты."""
    _fresh_db()
    events.record_run("key", "ok", audio_seconds=100, wall_seconds=25)
    assert abs(events.summary(days=1).realtime_factor - 0.25) < 1e-9


def test_api_key_is_not_stored_in_plain_text():
    """Приватность: по базе нельзя восстановить ключ, но можно считать уникальных."""
    _fresh_db()
    events.record_run("super-secret-key", "ok", device_id="device-42")
    row = events.recent(1)[0]
    assert "super-secret-key" not in str(dict(row))
    assert "device-42" not in str(dict(row))
    assert row["key_hash"] == events.anon("super-secret-key")
    # Один и тот же ключ даёт один и тот же хеш — иначе уникальных не посчитать.
    assert events.anon("super-secret-key") == events.anon("super-secret-key")


def test_old_runs_fall_out_of_the_window():
    _fresh_db()
    events.record_run("key", "ok", audio_seconds=60)
    # Двигаем событие на 10 дней назад — недельный срез его уже не видит.
    with events._connect() as conn:  # noqa: SLF001 — проверяем поведение окна
        conn.execute("UPDATE runs SET at = ?", (time.time() - 10 * 86400,))
    assert events.summary(days=7).runs == 0
    assert events.summary(days=30).runs == 1


def test_missing_table_is_repaired_instead_of_silent_loss():
    """Учёт чинит себя сам: иначе он замолчал бы навсегда и незаметно.

    Так бывает на свежем томе — БД ещё не создана, а прогон уже идёт.
    """
    events.configure(os.path.join(tempfile.mkdtemp(), "events.db"))  # без init_db
    events.record_run("key", "ok", audio_seconds=60)
    assert events.summary(days=1).runs == 1


def test_recording_never_breaks_the_request():
    """Учёт не имеет права уронить прогон: пользователь получает субтитры всегда."""
    _fresh_db()
    events.configure("/nonexistent-dir-\0/events.db")  # заведомо нерабочий путь
    try:
        events.record_run("key", "ok", audio_seconds=1)  # не должно бросить
    finally:
        _fresh_db()


def test_disabled_analytics_writes_nothing():
    _fresh_db()
    old = settings.analytics
    try:
        settings.analytics = False
        events.record_run("key", "ok", audio_seconds=60)
        assert events.summary(days=1).runs == 0
    finally:
        settings.analytics = old


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты учёта прогонов пройдены.")
