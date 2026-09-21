"""Единственный конфиг программы: файл настроек + значения по умолчанию.

Раньше конфигов было два — переменные окружения для командной строки и файл
для окна, — и они расходились. Теперь источник один: файл в папке поддержки,
поверх которого можно положить переменную окружения `VIDEOBRIEF_<ИМЯ>`
(удобно для разовых прогонов из терминала).

Только stdlib.
"""
from __future__ import annotations

import json
import os
import sys

APP_NAME = "NP Brief"

DEFAULTS: dict = {
    # Путь к файлу модели .gguf. Пусто — программа выберет сама (см. llm.py).
    "model_path": "",
    # Под кого делаем свою версию ролика — попадает прямо в задание модели.
    "audience": "русскоязычная аудитория СНГ",
    # Куда складывать разборы. Пусто = ~/Movies/NP Brief.
    "out_dir": "",
    # Модель распознавания речи, когда у ролика нет готовых субтитров.
    "whisper": "large-v3",
    # Окно контекста модели (токенов). Каждая тысяча — это память под KV-кэш,
    # которая отнимается у системы; 8192 хватает на ролик до ~15 минут, длиннее
    # всё равно сжимается по частям.
    "ctx": 8192,
    # Сколько символов расшифровки отдавать модели за раз. Больше — сжимаем
    # по частям, иначе конец длинного ролика не влезет в окно. Держим с запасом
    # к окну: модели нужно место ещё и на собственный ответ.
    "max_chars": 7000,
}


def state_dir() -> str:
    """Папка программы: на macOS — Application Support, иначе ~/.config."""
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


def _coerce(key: str, value):
    """Приводит значение к типу значения по умолчанию (из env приходят строки)."""
    default = DEFAULTS[key]
    if isinstance(default, int) and not isinstance(value, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return value


def load() -> dict:
    """Настройки: значения по умолчанию -> файл -> переменные окружения.

    Битый файл не роняет программу: с пустыми настройками она всё равно
    работает, а человек поправит их в окне.
    """
    data = dict(DEFAULTS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            data.update({k: _coerce(k, v) for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    for key in DEFAULTS:
        env = os.environ.get(f"VIDEOBRIEF_{key.upper()}")
        if env:
            data[key] = _coerce(key, env)
    if not data["out_dir"]:
        data["out_dir"] = default_out_dir()
    return data


def save(values: dict) -> dict:
    """Сохраняет известные ключи и возвращает итоговые настройки."""
    data = load()
    data.update({k: _coerce(k, v) for k, v in values.items() if k in DEFAULTS})
    os.makedirs(state_dir(), exist_ok=True)
    with open(settings_path(), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return data
