"""Конфигурация бэкенда. Всё переопределяется через переменные окружения (.env)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KZSUB_", env_file=".env", extra="ignore")

    # Модель Whisper. Для казахского минимально пригоден "large-v3".
    # Меньшие модели ("medium", "small") заметно хуже на казахском — использовать
    # только для быстрых локальных тестов.
    whisper_model: str = "large-v3"

    # "cpu" | "cuda". На проде — cuda (GPU), иначе транскрибация медленная.
    device: str = "cpu"

    # Тип вычислений faster-whisper: "int8" (cpu), "float16" (gpu) и т.п.
    compute_type: str = "int8"

    # Язык фиксируем: продукт про казахский.
    language: str = "kk"

    # Бесплатная квота (минуты аудио в месяц) для ключей без подписки.
    free_minutes_per_month: int = 30

    # Максимальная длительность одного файла (сек), защита от абьюза.
    max_audio_seconds: int = 60 * 90  # 1.5 часа

    # Директория для временных файлов.
    tmp_dir: str = "tmp"


settings = Settings()
