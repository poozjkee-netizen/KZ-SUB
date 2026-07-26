"""Конфигурация бэкенда.

Значения читаются из переменных окружения с префиксом ``KZSUB_`` (можно через
файл ``.env``, если он загружен окружением). Намеренно без внешних зависимостей —
чтобы core-логика (srt/licenses) была тестируемой без установки тяжёлых пакетов.
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


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(f"KZSUB_{name}")
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "да")


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

    # Максимальная длительность одного файла (сек). Длинные файлы шлюз режет на
    # куски по chunk_seconds (audio_chunk.py) и гонит частями — потолок Runpod
    # 10 MiB на /run снят. Лимит держим для защиты от абьюза и по памяти шлюза.
    max_audio_seconds: int = _get_int("MAX_AUDIO_SECONDS", 60 * 10)  # 10 минут

    # Длительность одного куска при нарезке длинного аудио (сек). Каждый кусок
    # после base64 должен влезать в лимит Runpod 10 MiB: 16 kHz mono = 32 КБ/с,
    # 180 с ≈ 5.8 МБ → base64 ~7.7 МБ (запас до 10 МБ). Больше не ставить.
    chunk_seconds: int = _get_int("CHUNK_SECONDS", 180)

    # Сколько кусков гнать через Runpod одновременно. Ускоряет длинные файлы в
    # разы, но реальный выигрыш ограничен настройкой Max Workers у эндпоинта
    # Runpod: если там 1, задания встанут в очередь. 1 = строго последовательно.
    chunk_concurrency: int = _get_int("CHUNK_CONCURRENCY", 3)

    # Директория для временных файлов.
    tmp_dir: str = _get("TMP_DIR", "tmp")

    # Бутстрап-ключи в формате "ключ:тариф,ключ2:тариф2" (тариф: free|pro|studio).
    # ПУСТО ПО УМОЛЧАНИЮ — тестовых ключей больше нет. При старте эти ключи
    # заносятся в БД лицензий (licenses.py) как обычные лицензии, если их там
    # ещё нет (для ключей, выданных вручную до автоматизации оплаты).
    api_keys: str = _get("API_KEYS", "")

    # --- Лицензии (licenses.py, постоянное хранилище на SQLite) ---
    # Секретный ключ разработчика: бессрочная безлимитная лицензия без квот,
    # только для тебя. Задаётся в Fly secrets, в код/чат не попадает.
    developer_key: str = _get("DEVELOPER_KEY", "")

    # Путь к файлу БД лицензий. Пусто — вычисляется: STATE_DIR/licenses.db
    # (на Fly — том /data), иначе TMP_DIR/licenses.db. Задавать явно нужно редко.
    license_db: str = _get("LICENSE_DB", "")

    # --- Прокси-режим шлюза: Runpod Serverless GPU ---
    # Если заданы оба значения ниже, /transcribe НЕ гоняет Whisper локально,
    # а отправляет аудио в Runpod-эндпоинт. Шлюз тогда можно хостить на
    # копеечном CPU (ключи/квоты остаются здесь).
    runpod_endpoint_id: str = _get("RUNPOD_ENDPOINT_ID", "")
    runpod_api_key: str = _get("RUNPOD_API_KEY", "")

    # Внутренний ключ, который шлюз передаёт воркеру Runpod. На воркере
    # задайте KZSUB_API_KEYS="<это значение>:pro".
    runpod_worker_key: str = _get("RUNPOD_WORKER_KEY", "gateway-internal")

    # Сколько ждать результат задания (сек), включая холодный старт GPU.
    runpod_timeout_seconds: int = _get_int("RUNPOD_TIMEOUT_SECONDS", 900)

    # --- Анти-шаринг: привязка ключа к устройствам ---
    # Максимум устройств на один ключ (0 = проверка отключена).
    max_devices_per_key: int = _get_int("MAX_DEVICES_PER_KEY", 2)

    # Директория постоянного состояния (привязки устройств). На Fly — том /data.
    # Пусто = хранить в памяти процесса (только для разработки).
    state_dir: str = _get("STATE_DIR", "")

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

    # --- Оформление (стиль вывода) ---
    # ВЕРХНИЙ РЕГИСТР всего текста (типично для караоке-субтитров Shorts/Reels).
    uppercase: bool = _get_bool("UPPERCASE", False)

    # Убирать пунктуацию (точки, запятые и т.п.) — караоке-стиль. Включено по
    # умолчанию по пожеланию продукта: субтитры чище.
    strip_punctuation: bool = _get_bool("STRIP_PUNCTUATION", True)

    # Символы пунктуации, которые НЕ удаляются (по умолчанию — "!":
    # восклицательные знаки остаются).
    punct_keep: str = _get("PUNCT_KEEP", "!")

    # --- Тайминги (timing.py, работает на шлюзе) ---
    # Подтягивать начало реплики к фактическому началу речи в аудио. Лечит
    # «текст появляется раньше, чем сказано»: VAD добавляет паддинг перед речью,
    # а пословное выравнивание Whisper само смещено вперёд.
    snap_to_speech: bool = _get_bool("SNAP_TO_SPEECH", True)

    # Насколько далеко вперёд искать начало речи (сек). 0 = выключить привязку.
    snap_window_seconds: float = float(_get("SNAP_WINDOW_SECONDS", "1.0"))

    # --- Постобработка текста (postprocess.py, работает на шлюзе) ---
    # Максимум одинаковых реплик подряд: Whisper на тишине залипает и печатает
    # одно слово десятки раз. 0 = фильтр выключен. Порог щедрый, чтобы не
    # тронуть нормальные повторы в речи.
    max_repeats: int = _get_int("MAX_REPEATS", 3)

    # Отбрасывать реплики длиннее N секунд (галлюцинации в тишине получают
    # долгий тайм-код). 0 = выключено — включай осознанно и сверяй по WER.
    max_cue_drop_seconds: float = float(_get("MAX_CUE_DROP_SECONDS", "0"))

    # Пользовательский словарь исправлений: "было=стало,было2=стало2".
    # Пустая правая часть удаляет слово. Правит систематические ошибки на
    # именах/терминах без переобучения модели.
    lexicon: str = _get("LEXICON", "")

    # Путь к файлу словаря (те же правила, по строке на правило; # — коммент).
    lexicon_path: str = _get("LEXICON_PATH", "")

    # --- Telegram-бот выдачи ключей (app/telegram_bot.py) ---
    # Токен бота от @BotFather. Пусто = вебхук /telegram/webhook отключён (404).
    telegram_bot_token: str = _get("TELEGRAM_BOT_TOKEN", "")

    # Секрет вебхука (задаётся при `python -m app.telegram_bot set-webhook`,
    # сверяется с заголовком X-Telegram-Bot-Api-Secret-Token). Пусто = заголовок
    # не проверяется — небезопасно, задавай в проде.
    telegram_webhook_secret: str = _get("TELEGRAM_WEBHOOK_SECRET", "")

    # Telegram ID продавца(ов), кто подтверждает оплату Standard, через запятую.
    # Свой ID узнать командой /whoami у бота.
    telegram_admin_ids: str = _get("TELEGRAM_ADMIN_IDS", "")

    # Номер/реквизит Kaspi для оплаты — показывается клиенту в /buy.
    kaspi_phone: str = _get("KASPI_PHONE", "")


settings = Settings()
