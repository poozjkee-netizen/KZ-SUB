"""Тесты привязки ключей к устройствам (чистая логика)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import devices  # noqa: E402
from app.config import settings  # noqa: E402


def _reset(state_dir=""):
    devices._bindings.clear()
    devices._loaded = False
    settings.state_dir = state_dir


def test_first_devices_allowed_then_blocked():
    _reset()
    settings.max_devices_per_key = 2
    devices.check_device("key1", "dev-a")
    devices.check_device("key1", "dev-b")
    devices.check_device("key1", "dev-a")  # повторно — ок
    try:
        devices.check_device("key1", "dev-c")
        assert False, "ожидался DeviceLimitError"
    except devices.DeviceLimitError:
        pass


def test_keys_are_independent():
    _reset()
    settings.max_devices_per_key = 1
    devices.check_device("key1", "dev-a")
    devices.check_device("key2", "dev-b")  # другой ключ — своя квота


def test_disabled_when_zero():
    _reset()
    settings.max_devices_per_key = 0
    for i in range(10):
        devices.check_device("key1", f"dev-{i}")  # всё разрешено


def test_missing_device_id_rejected():
    _reset()
    settings.max_devices_per_key = 2
    try:
        devices.check_device("key1", "")
        assert False, "ожидался DeviceLimitError"
    except devices.DeviceLimitError:
        pass


def test_reset_devices():
    _reset()
    settings.max_devices_per_key = 1
    devices.check_device("key1", "dev-a")
    devices.reset_devices("key1")
    devices.check_device("key1", "dev-b")  # после сброса — новое устройство ок


def test_persistence_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        _reset(tmp)
        settings.max_devices_per_key = 1
        devices.check_device("key1", "dev-a")
        assert os.path.exists(os.path.join(tmp, "devices.json"))

        # «Рестарт процесса»: сбрасываем кэш, состояние должно подняться с диска.
        devices._bindings.clear()
        devices._loaded = False
        try:
            devices.check_device("key1", "dev-b")
            assert False, "привязка не пережила рестарт"
        except devices.DeviceLimitError:
            pass
    _reset()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты привязки устройств пройдены.")
