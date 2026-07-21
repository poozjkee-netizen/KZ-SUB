"""Конфигурация бэкенда.

Значения читаются из переменных окружения с префиксом ``KZSUB_`` (можно через
файл ``.env``, если он загружен окружением). Намеренно без внешних зависимостей —
чтобы core-логика (srt/quota) была тестируемой без установки тяжёлых пакетов.
"""
from __future__ import annotations

import os


def _get(name: str, default: str) -> str:
    return os.environ.get(f"KZSUB_{name}", default)


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(f"KZSUB_{name}", str(default)))
    except ValueError:
        return default


class Settings:
    # Модель Whisper. Для казахского минимально пригоден "large-v3".
    # Меньшие модели ("medium", "small") заметно хуже на казахском — использовать
    # только для быстрых локальных тестов.
    whisper_model: str = _get("WHISPER_MODEL", "large-v3")

    # "cpu" | "cuda". На проде — cuda (GPU), иначе транскрибация медленная.
    device: str = _get("DEVICE", "cpu")

    # Тип вычислений faster-whisper: "int8" (cpu), "float16" (gpu) и т.п.
    compute_type: str = _get("COMPUTE_TYPE", "int8")

    # Язык фиксируем: продукт про казахский.
    language: str = _get("LANGUAGE", "kk")

    # Бесплатная квота (минуты аудио в месяц) для ключей без подписки.
    free_minutes_per_month: int = _get_int("FREE_MINUTES_PER_MONTH", 30)

    # Максимальная длительность одного файла (сек), защита от абьюза.
    max_audio_seconds: int = _get_int("MAX_AUDIO_SECONDS", 60 * 90)  # 1.5 часа

    # Директория для временных файлов.
    tmp_dir: str = _get("TMP_DIR", "tmp")

    # --- Параметры нарезки субтитров (читаемость) ---
    # Максимум символов в одной строке субтитра (норма для читаемости ~42).
    max_line_chars: int = _get_int("MAX_LINE_CHARS", 42)

    # Максимум строк в одной реплике субтитра.
    max_lines: int = _get_int("MAX_LINES", 2)

    # Максимальная длительность одной реплики (сек).
    max_cue_seconds: float = float(_get("MAX_CUE_SECONDS", "7.0"))

    # Пауза между словами, по которой принудительно разрываем реплику (сек).
    max_gap_seconds: float = float(_get("MAX_GAP_SECONDS", "0.8"))

    # Стиль субтитров:
    #   "word"   — по одному слову на реплику (караоке-стиль для Shorts/Reels),
    #              короткие предлоги/частицы прилипают к следующему слову;
    #   "phrase" — аккуратные реплики-фразы (см. resegment).
    caption_style: str = _get("CAPTION_STYLE", "word")

    # В режиме "word": слова не длиннее этого числа символов считаются
    # «служебными» и прилипают к следующему слову (в дополнение к списку предлогов).
    glue_max_chars: int = _get_int("GLUE_MAX_CHARS", 2)


settings = Settings()
