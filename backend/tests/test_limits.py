"""Тесты ограничителей запросов (dep-free: чистая логика без ASGI).

Запуск: python tests/test_limits.py
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.limits import JobGate, upload_reject  # noqa: E402

MB = 1024 * 1024


def test_body_over_limit_is_rejected_before_parsing():
    """Главная дыра: без этой проверки тело читается до проверки ключа."""
    v = upload_reject("POST", "/transcribe", str(300 * MB), True, 150 * MB)
    assert v is not None and v[0] == 413
    assert "150" in v[1]


def test_body_within_limit_passes():
    assert upload_reject("POST", "/transcribe", str(20 * MB), True, 150 * MB) is None


def test_missing_api_key_rejected_without_reading_body():
    """401 должен наступить в middleware, иначе гигабайты уже на диске."""
    v = upload_reject("POST", "/transcribe", str(20 * MB), False, 150 * MB)
    assert v is not None and v[0] == 401


def test_missing_content_length_is_rejected():
    """Без Content-Length размер заранее неизвестен — читать «сколько придёт» нельзя."""
    v = upload_reject("POST", "/transcribe", None, True, 150 * MB)
    assert v is not None and v[0] == 411


def test_broken_content_length_is_rejected():
    for bad in ("abc", "-5", ""):
        v = upload_reject("POST", "/transcribe", bad, True, 150 * MB)
        assert v is not None and v[0] == 400, bad


def test_other_endpoints_and_methods_untouched():
    """Ограничитель не должен мешать /health, /license и вебхуку бота."""
    assert upload_reject("GET", "/health", None, False, 150 * MB) is None
    assert upload_reject("GET", "/license", None, False, 150 * MB) is None
    assert upload_reject("POST", "/telegram/webhook", None, False, 150 * MB) is None


def test_gate_allows_up_to_limit_then_reports_busy():
    gate = JobGate(max_concurrent=2)
    assert gate.try_acquire("k1") == (True, "")
    assert gate.try_acquire("k2") == (True, "")
    ok, why = gate.try_acquire("k3")
    assert (ok, why) == (False, "busy")
    assert gate.active == 2

    gate.release("k1")
    assert gate.try_acquire("k3") == (True, "")


def test_same_key_cannot_run_two_jobs_at_once():
    """Один ключ — один ролик за раз: иначе один клиент занимает весь сервер."""
    gate = JobGate(max_concurrent=4)
    assert gate.try_acquire("k1") == (True, "")
    assert gate.try_acquire("k1") == (False, "duplicate")
    gate.release("k1")
    assert gate.try_acquire("k1") == (True, "")


def test_release_of_unknown_key_does_not_break_counter():
    gate = JobGate(max_concurrent=1)
    gate.release("никогда-не-занимал")      # не должно уводить счётчик в минус
    assert gate.active == 0
    assert gate.try_acquire("k1") == (True, "")


def test_gate_is_thread_safe_under_contention():
    """Слоты выдаются из threadpool: без блокировки лимит бы протекал."""
    gate = JobGate(max_concurrent=3)
    granted = []
    lock = threading.Lock()

    def worker(i):
        ok, _ = gate.try_acquire(f"key-{i}")
        if ok:
            with lock:
                granted.append(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(granted) == 3, f"выдано слотов: {len(granted)}"
    assert gate.active == 3


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты ограничителей пройдены.")
