"""Привязка API-ключей к устройствам (анти-шаринг).

Ключ закрепляется за первыми N устройствами (device_id — хэш, который панель
считает из характеристик машины). Запрос с не-привязанного устройства сверх
лимита отклоняется.

Состояние хранится в JSON-файле в KZSUB_STATE_DIR (на Fly — том /data),
чтобы привязки переживали рестарты. Без STATE_DIR — деградация в память
процесса (подходит только для локальной разработки).
"""
from __future__ import annotations

import json
import logging
import os
import threading

from .config import settings

logger = logging.getLogger("kzsub.devices")


class DeviceLimitError(Exception):
    """Ключ уже привязан к максимуму устройств."""


_lock = threading.Lock()
_bindings: dict[str, list[str]] = {}
_loaded = False


def _state_path() -> str:
    return os.path.join(settings.state_dir, "devices.json") if settings.state_dir else ""


def _load_locked() -> None:
    global _bindings, _loaded
    if _loaded:
        return
    path = _state_path()
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            _bindings = {str(k): list(v) for k, v in data.items()}
            logger.info("Загружены привязки устройств: %d ключей", len(_bindings))
        except Exception:
            logger.exception("Не удалось прочитать %s — стартуем с пустыми привязками", path)
            _bindings = {}
    _loaded = True


def _save_locked() -> None:
    path = _state_path()
    if not path:
        return
    os.makedirs(settings.state_dir, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_bindings, f)
    os.replace(tmp, path)  # атомарная запись — не порвём файл при падении


def check_device(api_key: str, device_id: str) -> None:
    """Регистрирует/проверяет устройство для ключа.

    Бросает DeviceLimitError, если устройство новое, а лимит уже выбран.
    При max_devices_per_key <= 0 проверка отключена.
    """
    limit = settings.max_devices_per_key
    if limit <= 0:
        return
    if not device_id:
        raise DeviceLimitError("Требуется идентификатор устройства (обновите плагин)")

    with _lock:
        _load_locked()
        devices = _bindings.setdefault(api_key, [])
        if device_id in devices:
            return
        if len(devices) >= limit:
            raise DeviceLimitError("Ключ уже используется на другом устройстве")
        devices.append(device_id)
        _save_locked()
        logger.info("Ключ %s…: привязано устройство %d/%d", api_key[:4], len(devices), limit)


def reset_devices(api_key: str) -> None:
    """Сбросить привязки ключа (поддержка: пользователь сменил компьютер)."""
    with _lock:
        _load_locked()
        _bindings.pop(api_key, None)
        _save_locked()
