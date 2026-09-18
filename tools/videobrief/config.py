"""Настройки инструмента. Только stdlib — модуль импортируется тестами.

Префикс намеренно свой, `VIDEOBRIEF_`, а не `KZSUB_`: это отдельная утилита, её
переменные не должны попадать в конфиг шлюза и путать при деплое.
"""
from __future__ import annotations

import os


def _get(name: str, default: str) -> str:
    return os.environ.get(f"VIDEOBRIEF_{name}", default)


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(f"VIDEOBRIEF_{name}", str(default)))
    except ValueError:
        return default


class Settings:
    # Чем разбирать: "auto" — локальной моделью, если она запущена, иначе Claude;
    # "local" — только локальной (без интернета и ключей); "claude" — только по ключу.
    engine: str = _get("ENGINE", "auto")

    # Адрес локального сервера моделей. Пусто = перебрать обычные порты:
    # Ollama 11434, LM Studio 1234, llama.cpp 8080.
    local_url: str = _get("LOCAL_URL", "")

    # Какую локальную модель брать. Пусто = выбрать самой (Gemma в приоритете).
    # Достаточно куска имени: "gemma" найдёт "gemma3:12b".
    local_model: str = _get("LOCAL_MODEL", "")

    # Окно контекста локальной модели (токенов). У Ollama по умолчанию мало, и
    # длинная расшифровка молча обрезается — задаём явно.
    local_ctx: int = _get_int("LOCAL_CTX", 16384)

    # Сколько символов расшифровки отдавать локальной модели за раз. Больше —
    # сжимаем по частям (longtext.py), иначе конец ролика не влезет в окно.
    local_max_chars: int = _get_int("LOCAL_MAX_CHARS", 16000)

    # Модель для разбора. Разбор — главная ценность инструмента, поэтому по
    # умолчанию самая сильная: экономия здесь стоит дороже, чем токены.
    model: str = _get("MODEL", "claude-opus-5")

    # Глубина рассуждений (low|medium|high|xhigh|max).
    effort: str = _get("EFFORT", "high")

    # Потолок ответа. Разбор длинный (структура + сценарий + свой черновик),
    # поэтому запрос всегда стриминговый — иначе упрёмся в таймаут HTTP.
    max_tokens: int = _get_int("MAX_TOKENS", 32000)

    # Язык выдачи: ролик может быть любым, вывод — всегда этот язык.
    target_lang: str = _get("TARGET_LANG", "ru")

    # Whisper на случай, когда у ролика нет готовых субтитров.
    whisper_model: str = _get("WHISPER_MODEL", "large-v3")
    device: str = _get("DEVICE", "cpu")
    compute_type: str = _get("COMPUTE_TYPE", "int8")

    # Куда складывать результаты (папка на ролик).
    out_dir: str = _get("OUT_DIR", "out/briefs")

    # Приоритет языков готовых субтитров: сначала оригинал ролика, потом эти.
    sub_langs: str = _get("SUB_LANGS", "ru,en,kk")


settings = Settings()
