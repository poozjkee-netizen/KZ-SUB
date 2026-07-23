"""Тесты лицензий и учёта минут (чистая логика, SQLite на временном файле).

Запуск без тяжёлых пакетов: python tests/test_licenses.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import licenses  # noqa: E402
from app.config import settings  # noqa: E402
from app.licenses import (  # noqa: E402
    InvalidKey, LicenseExhausted, LicenseExpired, LicenseInactive,
    LicenseStatus, LicenseType,
)

_tmpdir = tempfile.mkdtemp()
_n = [0]


def _fresh():
    """Свежая пустая БД лицензий для очередного теста."""
    _n[0] += 1
    licenses.configure(os.path.join(_tmpdir, f"lic_{_n[0]}.db"))
    licenses.init_db()


def test_create_and_get():
    _fresh()
    lic = licenses.create_license("a@b.c", LicenseType.SUBSCRIPTION,
                                  total_minutes=100, days=30, api_key="k1")
    got = licenses.get_license("k1")
    assert got is not None
    assert got.email == "a@b.c"
    assert got.type == LicenseType.SUBSCRIPTION
    assert got.total_minutes == 100
    assert got.used_minutes == 0
    assert got.status == LicenseStatus.ACTIVE
    assert got.expires_at is not None
    assert got.id == lic.id


def test_generated_key_is_unique_and_prefixed():
    _fresh()
    a = licenses.create_license("", LicenseType.TRIAL, total_minutes=30, days=7)
    b = licenses.create_license("", LicenseType.TRIAL, total_minutes=30, days=7)
    assert a.api_key != b.api_key
    assert a.api_key.startswith("kzsub_")


def test_unknown_key_is_invalid():
    _fresh()
    try:
        licenses.check_license("nope", 0.0)
        assert False, "ожидался InvalidKey"
    except InvalidKey as e:
        assert e.http_status == 401


def test_developer_bypasses_all_limits():
    _fresh()
    licenses.create_license("dev@np", LicenseType.DEVELOPER, api_key="devk")
    # даже с гигантским запросом — проходит
    licenses.check_license("devk", 10_000_000)
    # и минуты не списываются
    licenses.commit_usage("devk", 500)
    assert licenses.get_license("devk").used_minutes == 0


def test_expired_license_rejected():
    _fresh()
    # days=-1 → срок в прошлом
    licenses.create_license("", LicenseType.SUBSCRIPTION, total_minutes=100,
                            days=-1, api_key="exp")
    try:
        licenses.check_license("exp", 1.0)
        assert False, "ожидался LicenseExpired"
    except LicenseExpired as e:
        assert e.http_status == 402
    assert licenses.get_license("exp").status == LicenseStatus.EXPIRED


def test_minutes_exhausted():
    _fresh()
    licenses.create_license("", LicenseType.MINUTE_PACK, total_minutes=10, api_key="mp")
    licenses.check_license("mp", 5)          # запас есть
    licenses.commit_usage("mp", 10)          # выбрали всё
    assert licenses.get_license("mp").status == LicenseStatus.EXHAUSTED
    try:
        licenses.check_license("mp", 1)
        assert False, "ожидался LicenseExhausted"
    except LicenseExhausted as e:
        assert e.http_status == 402


def test_minute_headroom_check():
    _fresh()
    licenses.create_license("", LicenseType.SUBSCRIPTION, total_minutes=10, api_key="hr")
    licenses.commit_usage("hr", 9)
    licenses.check_license("hr", 0.5)        # 9 + 0.5 <= 10 — ок
    try:
        licenses.check_license("hr", 2)      # 9 + 2 > 10 — нет
        assert False, "ожидался LicenseExhausted"
    except LicenseExhausted:
        pass


def test_suspended_and_revoked_rejected():
    _fresh()
    licenses.create_license("", LicenseType.SUBSCRIPTION, total_minutes=100, api_key="s1")
    licenses.suspend("s1")
    try:
        licenses.check_license("s1", 1)
        assert False, "ожидался LicenseInactive (suspended)"
    except LicenseInactive as e:
        assert e.http_status == 403
    licenses.activate("s1")
    licenses.check_license("s1", 1)          # снова доступна
    licenses.revoke("s1")
    try:
        licenses.check_license("s1", 1)
        assert False, "ожидался LicenseInactive (revoked)"
    except LicenseInactive:
        pass


def test_remaining_minutes():
    _fresh()
    licenses.create_license("", LicenseType.LIFETIME, total_minutes=None, api_key="inf")
    assert licenses.get_license("inf").remaining_minutes() is None  # безлимит
    licenses.create_license("", LicenseType.MINUTE_PACK, total_minutes=10, api_key="lim")
    licenses.commit_usage("lim", 3)
    assert licenses.get_license("lim").remaining_minutes() == 7


def test_renew_resets_and_extends():
    _fresh()
    licenses.create_license("", LicenseType.SUBSCRIPTION, total_minutes=100,
                            days=-1, api_key="rn")
    licenses.commit_usage("rn", 40)
    licenses.renew("rn", days=30)
    lic = licenses.get_license("rn")
    assert lic.status == LicenseStatus.ACTIVE
    assert lic.used_minutes == 0
    assert lic.expires_at > licenses.time.time()
    licenses.check_license("rn", 1)          # снова работает


def test_topup_adds_minutes():
    _fresh()
    licenses.create_license("", LicenseType.MINUTE_PACK, total_minutes=10, api_key="tp")
    licenses.commit_usage("tp", 10)          # исчерпан
    assert licenses.get_license("tp").status == LicenseStatus.EXHAUSTED
    licenses.topup("tp", 20)
    lic = licenses.get_license("tp")
    assert lic.total_minutes == 30
    assert lic.status == LicenseStatus.ACTIVE
    licenses.check_license("tp", 5)          # снова есть запас


def test_seed_developer_key():
    _fresh()
    old_dev, old_keys = settings.developer_key, settings.api_keys
    settings.developer_key = "seed-dev"
    settings.api_keys = ""
    try:
        licenses.ensure_seeded()
        lic = licenses.get_license("seed-dev")
        assert lic is not None and lic.type == LicenseType.DEVELOPER
        licenses.ensure_seeded()             # идемпотентно
        assert len(licenses.list_licenses()) == 1
    finally:
        settings.developer_key, settings.api_keys = old_dev, old_keys


def test_seed_env_keys_map_to_types():
    _fresh()
    old_dev, old_keys = settings.developer_key, settings.api_keys
    settings.developer_key = ""
    settings.api_keys = "prokey:pro,freekey:free"
    try:
        licenses.ensure_seeded()
        assert licenses.get_license("prokey").type == LicenseType.SUBSCRIPTION
        assert licenses.get_license("prokey").total_minutes is None  # легаси безлимит
        free = licenses.get_license("freekey")
        assert free.type == LicenseType.TRIAL
        assert free.total_minutes == settings.free_minutes_per_month
    finally:
        settings.developer_key, settings.api_keys = old_dev, old_keys


def test_no_default_test_keys():
    _fresh()
    old_dev, old_keys = settings.developer_key, settings.api_keys
    settings.developer_key = ""
    settings.api_keys = ""
    try:
        licenses.ensure_seeded()
        # Ни старого dev-key, ни free-demo — тестовых ключей больше нет.
        assert licenses.get_license("dev-key") is None
        assert licenses.get_license("free-demo") is None
        assert licenses.list_licenses() == []
    finally:
        settings.developer_key, settings.api_keys = old_dev, old_keys


def test_seed_is_race_safe():
    _fresh()
    licenses.create_license("", LicenseType.DEVELOPER, api_key="dupe")
    # Повторный засев того же ключа (имитация второго воркера) НЕ падает.
    licenses._seed(email="x", type=LicenseType.DEVELOPER, api_key="dupe")
    assert len(licenses.list_licenses()) == 1
    # ensure_seeded с уже существующим developer-ключом тоже не падает.
    old = settings.developer_key
    settings.developer_key = "dupe"
    try:
        licenses.ensure_seeded()
        licenses.ensure_seeded()
    finally:
        settings.developer_key = old
    assert len(licenses.list_licenses()) == 1


def test_describe_is_readonly_and_accurate():
    _fresh()
    assert licenses.describe("missing") is None

    licenses.create_license("", LicenseType.SUBSCRIPTION, total_minutes=100, api_key="ok")
    d = licenses.describe("ok")
    assert d["active"] is True
    assert d["remaining_minutes"] == 100

    licenses.create_license("", LicenseType.MINUTE_PACK, total_minutes=5, api_key="ex")
    licenses.commit_usage("ex", 5)
    d = licenses.describe("ex")
    assert d["active"] is False and d["status"] == LicenseStatus.EXHAUSTED

    licenses.create_license("", LicenseType.DEVELOPER, api_key="dv")
    assert licenses.describe("dv")["active"] is True

    # describe НЕ мутирует статус (в отличие от check_license)
    licenses.create_license("", LicenseType.SUBSCRIPTION, total_minutes=100,
                            days=-1, api_key="expd")
    assert licenses.describe("expd")["active"] is False
    assert licenses.get_license("expd").status == LicenseStatus.ACTIVE


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты лицензий пройдены.")
