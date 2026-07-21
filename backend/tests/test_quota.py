"""Тесты учёта квоты (чистая логика, без Whisper/FastAPI)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import quota  # noqa: E402
from app.config import settings  # noqa: E402


def _reset():
    quota._usage.clear()


def test_unknown_key_raises():
    _reset()
    try:
        quota.check_and_reserve("no-such-key", 10)
        assert False, "ожидалась QuotaError"
    except quota.QuotaError:
        pass


def test_pro_key_has_no_limit():
    _reset()
    # Много часов подряд — pro не упирается в лимит.
    for _ in range(100):
        quota.check_and_reserve("dev-key", 3600)
        quota.commit("dev-key", 3600)


def test_free_key_within_limit():
    _reset()
    # 10 минут при лимите 30 — проходит.
    quota.check_and_reserve("free-demo", 10 * 60)
    quota.commit("free-demo", 10 * 60)


def test_free_key_exceeds_limit():
    _reset()
    limit = settings.free_minutes_per_month * 60
    quota.commit("free-demo", limit)  # выбрали весь лимит
    try:
        quota.check_and_reserve("free-demo", 60)
        assert False, "ожидалась QuotaError (лимит исчерпан)"
    except quota.QuotaError:
        pass


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты квоты пройдены.")
