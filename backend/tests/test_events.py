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


def _step_users(fn, step):
    return next(s.users for s in fn.steps if s.step == step)


def test_funnel_counts_people_not_clicks():
    """Один человек, нажавший «скачать» трижды, — это один человек."""
    _fresh_db()
    events.record_step(1, events.STEP_START, source="dock")
    events.record_step(1, events.STEP_LANG, lang="ru")
    for _ in range(3):
        events.record_step(1, events.STEP_DOWNLOAD)
    events.record_step(2, events.STEP_START, source="dock")

    fn = events.funnel(days=1)
    assert _step_users(fn, events.STEP_START) == 2
    assert _step_users(fn, events.STEP_DOWNLOAD) == 1
    assert fn.sources == [("dock", 2)]


def test_activation_is_derived_from_actual_runs():
    """«Сделал субтитры» нельзя отметить в боте — только сшив ключ с прогоном."""
    _fresh_db()
    events.record_step(1, events.STEP_DEMO, api_key="key-a")
    events.record_step(2, events.STEP_DEMO, api_key="key-b")
    events.record_run("key-a", "ok", audio_seconds=60)

    fn = events.funnel(days=1)
    assert _step_users(fn, events.STEP_DEMO) == 2
    assert _step_users(fn, events.STEP_ACTIVATED) == 1, "взял ключ ≠ воспользовался"


def test_failed_run_is_not_an_activation():
    _fresh_db()
    events.record_step(1, events.STEP_DEMO, api_key="key-a")
    events.record_run("key-a", "error", reason="http_402")
    assert _step_users(events.funnel(days=1), events.STEP_ACTIVATED) == 0


def test_activation_counts_runs_outside_the_window():
    """Вчерашняя регистрация + сегодняшний прогон — это активация, а не провал."""
    _fresh_db()
    events.record_step(1, events.STEP_DEMO, api_key="key-a")
    events.record_run("key-a", "ok", audio_seconds=60)
    # Прогон «состарим» так, чтобы он не попал в окно, а шаг — попал.
    with events._connect() as conn:  # noqa: SLF001 — правим время ради проверки
        conn.execute("UPDATE runs SET at = ?", (time.time() - 30 * 86400,))
    assert _step_users(events.funnel(days=1), events.STEP_ACTIVATED) == 1


def test_biggest_drop_points_at_the_step_to_fix():
    _fresh_db()
    for uid in range(10):
        events.record_step(uid, events.STEP_START)
    for uid in range(9):
        events.record_step(uid, events.STEP_LANG)
    for uid in range(2):            # здесь теряем семерых — самый большой обрыв
        events.record_step(uid, events.STEP_DEMO)
    for uid in range(2):
        events.record_step(uid, events.STEP_DOWNLOAD)

    before, after, lost = events.funnel(days=1).biggest_drop
    assert (before.step, after.step, lost) == (events.STEP_LANG, events.STEP_DEMO, 7)


def test_share_is_counted_from_the_entry_step():
    """Шаги не вложены строго — доля от предыдущего давала бы >100%."""
    _fresh_db()
    for uid in range(4):
        events.record_step(uid, events.STEP_START)
    events.record_step(50, events.STEP_BUY)   # пришёл сразу к покупке
    fn = events.funnel(days=1)
    assert abs(fn.share(fn.steps[0]) - 1.0) < 1e-9
    assert fn.entered == 4


def test_empty_funnel_does_not_divide_by_zero():
    _fresh_db()
    fn = events.funnel(days=1)
    assert fn.entered == 0
    assert fn.share(fn.steps[0]) == 0.0
    assert fn.purchase_rate == 0.0
    assert fn.biggest_drop is None


def test_funnel_stores_no_raw_telegram_id():
    _fresh_db()
    events.record_step(123456789, events.STEP_START)
    with events._connect() as conn:  # noqa: SLF001
        row = conn.execute("SELECT user_hash FROM funnel").fetchone()
    assert "123456789" not in row["user_hash"]


def test_old_steps_fall_out_of_the_window():
    _fresh_db()
    events.record_step(1, events.STEP_START)
    with events._connect() as conn:  # noqa: SLF001
        conn.execute("UPDATE funnel SET at = ?", (time.time() - 40 * 86400,))
    assert events.funnel(days=30).entered == 0


def test_disabled_analytics_writes_no_steps():
    _fresh_db()
    old = settings.analytics
    try:
        settings.analytics = False
        events.record_step(1, events.STEP_START)
        assert events.funnel(days=1).entered == 0
    finally:
        settings.analytics = old


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты учёта прогонов пройдены.")
