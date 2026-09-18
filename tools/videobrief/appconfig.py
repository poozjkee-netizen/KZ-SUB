"""Настройки приложения: ключ API, аудитория, куда складывать разборы.

Нужны, потому что у окна приложения нет ни переменных окружения, ни аргументов
командной строки: человек вводит ключ один раз в самом окне, и он должен
пережить перезапуск. Файл лежит рядом с самим приложением в папке поддержки —
не в репозитории, чтобы ключ туда физически не мог попасть.
Только stdlib.
"""
from __future__ import annotations

import json
import os
import sys

APP_NAME = "NP Brief"

DEFAULTS: dict = {
    "engine": "auto",       # auto | local | claude (см. config.py)
    "local_url": "",        # адрес локального сервера моделей; пусто = поиск сам
    "local_model": "",      # имя локальной модели; пусто = выбрать самой
    "api_key": "",
    "audience": "русскоязычная аудитория СНГ",
    "out_dir": "",          # пусто = ~/Movies/NP Brief
    "whisper": "large-v3",  # модель распознавания, если субтитров нет
    "auto_subs": True,      # брать авто-субтитры площадки (быстро)
    "model": "",            # пусто = значение из config.py
}


def state_dir() -> str:
    """Папка приложения: на macOS — Application Support, иначе ~/.config."""
    override = os.environ.get("VIDEOBRIEF_STATE_DIR")
    if override:
        return override
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    return os.path.expanduser("~/.config/np-brief")


def settings_path() -> str:
    return os.path.join(state_dir(), "settings.json")


def default_out_dir() -> str:
    """Куда складывать разборы по умолчанию — видимая человеку папка, не temp."""
    movies = os.path.expanduser("~/Movies")
    base = movies if os.path.isdir(movies) else os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def load() -> dict:
    """Настройки с диска поверх значений по умолчанию. Битый файл не роняет приложение."""
    data = dict(DEFAULTS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            data.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    if not data["out_dir"]:
        data["out_dir"] = default_out_dir()
    return data


def save(values: dict) -> dict:
    """Сохраняет только известные ключи и возвращает итоговые настройки.

    Файл кладётся с правами 600: в нём лежит ключ API.
    """
    data = load()
    data.update({k: v for k, v in values.items() if k in DEFAULTS})
    os.makedirs(state_dir(), exist_ok=True)
    path = settings_path()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover — зависит от файловой системы
        pass
    return data


def masked(values: dict) -> dict:
    """Настройки для показа в окне: ключ заменён на «есть/нет»."""
    out = dict(values)
    key = out.pop("api_key", "") or ""
    out["api_key_set"] = bool(key.strip())
    out["api_key_hint"] = f"…{key.strip()[-4:]}" if key.strip() else ""
    return out
