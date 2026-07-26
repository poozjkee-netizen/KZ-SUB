# NP SUB Backend

API транскрибации казахской речи: аудио → субтитры `.srt`.

## Стек
- **FastAPI** — HTTP API
- **faster-whisper** — распознавание речи (модель `large-v3`, язык `kk`)

## Запуск (dev, CPU)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
> На CPU `large-v3` работает медленно — для быстрой локальной проверки можно
> временно выставить `KZSUB_WHISPER_MODEL=small`, но качество казахского упадёт.

## Прод (GPU)
```bash
export KZSUB_DEVICE=cuda
export KZSUB_COMPUTE_TYPE=float16
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```
Один воркер на GPU-инстанс (модель держит VRAM). Масштабирование — горизонтально,
за очередью задач (см. `docs/ROADMAP.md`).

## API

### `POST /transcribe`
Заголовок: `X-API-Key: <ключ>` (dev-ключ: `dev-key`).
Параметр `fmt`: `srt` (по умолчанию) или `json`.

```bash
# .srt
curl -F "file=@sample_kz.wav" -H "X-API-Key: dev-key" \
     "http://localhost:8000/transcribe" -o out.srt

# JSON-сегменты
curl -F "file=@sample_kz.wav" -H "X-API-Key: dev-key" \
     "http://localhost:8000/transcribe?fmt=json"
```

Коды ответа: `401` нет/неизвестный ключ · `402` истёк срок или лимит минут · `403` заблокирован/лимит устройств · `413` файл слишком длинный · `500` ошибка транскрибации.
Ответ несёт заголовок `X-Minutes-Remaining` (остаток минут или `unlimited`).

## Конфигурация (env, префикс `KZSUB_`)
| Переменная                    | По умолчанию | Назначение                          |
|-------------------------------|--------------|-------------------------------------|
| `KZSUB_WHISPER_MODEL`         | `large-v3`   | модель Whisper                      |
| `KZSUB_DEVICE`                | `cpu`        | `cpu` / `cuda`                      |
| `KZSUB_COMPUTE_TYPE`          | `int8`       | тип вычислений                      |
| `KZSUB_DEVELOPER_KEY`         | (пусто)      | бессрочный безлимитный ключ разработчика (Fly secret) |
| `KZSUB_API_KEYS`              | (пусто)      | бутстрап-ключи `ключ:тариф,...` → заносятся в БД лицензий |
| `KZSUB_LICENSE_DB`            | (пусто)      | путь к БД лицензий (пусто = `STATE_DIR/licenses.db`) |
| `KZSUB_FREE_MINUTES_PER_MONTH`| `30`         | лимит минут для бутстрап-ключей `:free` |
| `KZSUB_MAX_AUDIO_SECONDS`     | `600`        | лимит длительности файла (сек) = 10 мин (длинные режутся на куски) |
| `KZSUB_CHUNK_SECONDS`         | `180`        | длина куска при нарезке длинного аудио (сек); кусок должен влезать в 10 MiB Runpod |
| `KZSUB_CHUNK_CONCURRENCY`     | `3`          | сколько кусков гнать в Runpod параллельно (ограничено Max Workers эндпоинта) |
| `KZSUB_CAPTION_STYLE`         | `word`       | `word` (караоке, по слову) / `phrase` (фразы) |
| `KZSUB_GLUE_MAX_CHARS`        | `2`          | в режиме `word`: короткие слова липнут к следующему |
| `KZSUB_UPPERCASE`             | `false`      | ВЕРХНИЙ регистр субтитров            |
| `KZSUB_STRIP_PUNCTUATION`     | `true`       | убирать пунктуацию (караоке-стиль)   |
| `KZSUB_PUNCT_KEEP`            | `!`          | какие знаки оставить при очистке     |
| `KZSUB_MAX_LINE_CHARS`        | `42`         | (режим `phrase`) макс. символов в строке |
| `KZSUB_MAX_LINES`             | `2`          | макс. строк в реплике               |
| `KZSUB_MAX_CUE_SECONDS`       | `7.0`        | макс. длительность реплики          |
| `KZSUB_MAX_GAP_SECONDS`       | `0.8`        | пауза для разрыва реплики           |
| `KZSUB_SNAP_TO_SPEECH`        | `true`       | подтягивать начало реплики к фактическому началу речи |
| `KZSUB_SNAP_WINDOW_SECONDS`   | `1.0`        | окно поиска начала речи вперёд, сек (0 = выключить привязку) |
| `KZSUB_MAX_REPEATS`           | `3`          | макс. одинаковых реплик подряд (фильтр зацикливаний Whisper; 0 = выкл) |
| `KZSUB_MAX_CUE_DROP_SECONDS`  | `0`          | отбрасывать реплики длиннее N сек (0 = выкл) |
| `KZSUB_LEXICON`               | (пусто)      | словарь правок `было=стало,...` (пустая правая часть удаляет слово) |
| `KZSUB_LEXICON_PATH`          | (пусто)      | файл со словарём (строка на правило, `#` — комментарий) |
| `KZSUB_TELEGRAM_BOT_TOKEN`    | (пусто)      | токен бота (@BotFather); пусто = вебхук отключён (404) |
| `KZSUB_TELEGRAM_WEBHOOK_SECRET`| (пусто)     | секрет вебхука (заголовок `X-Telegram-Bot-Api-Secret-Token`) |
| `KZSUB_TELEGRAM_ADMIN_IDS`    | (пусто)      | Telegram ID продавца(ов) через запятую — подтверждают оплату |
| `KZSUB_KASPI_PHONE`           | (пусто)      | реквизит Kaspi, который бот показывает в `/buy` |

## Тесты
```bash
# Без тяжёлых зависимостей (чистая логика):
python tests/test_srt.py
python tests/test_licenses.py
python tests/test_segmentation.py
python tests/test_style.py
python tests/test_devices.py
python tests/test_postprocess.py
python tests/test_wer.py
python tests/test_audio_probe.py
python tests/test_audio_convert.py
python tests/test_audio_chunk.py
python tests/test_telegram_bot.py

# Интеграционный тест HTTP-контракта /transcribe (нужен fastapi/httpx,
# модель Whisper замокана — GPU/веса не требуются):
pytest tests/test_api.py
```

## Лицензии (app/licenses.py)
Постоянное хранилище лицензий на SQLite (том Fly). Типы: `developer` (безлимит),
`trial` (по времени), `subscription` (30 дней + минуты); `minute_pack`/`lifetime`
реализованы, но пока не используются в тарифной сетке. При каждом запросе
проверяются существование ключа, статус, срок и лимит минут — оба лимита
(минуты и срок) у `subscription` независимы. Тарифы — в `app/plans.py` (единый
источник, синхрон с MONETIZATION): единственный платный тариф **standard**
(60 мин или 30 дней, что раньше) + бесплатный **demo** (3 мин, без срока).

Выдача ключей вручную (до автоматизации оплаты):
```bash
python -m app.licenses plans                              # каталог тарифов
python -m app.licenses create --email user@mail --plan standard  # выдать по тарифу
python -m app.licenses list
python -m app.licenses topup <api_key> --minutes 100
python -m app.licenses revoke <api_key>                   # пометить отозванной
python -m app.licenses delete <api_key>                   # удалить навсегда
python -m app.licenses purge-revoked                      # снести все отозванные
```

## Telegram-бот выдачи ключей (app/telegram_bot.py)
Demo (3 мин) выдаётся автоматически, один раз на Telegram-аккаунт. Standard
(60 мин/30 дней) — полу-авто: клиент жмёт «Я оплатил» после перевода на Kaspi,
заявка с кнопками Подтвердить/Отклонить уходит продавцу (`KZSUB_TELEGRAM_ADMIN_IDS`);
после подтверждения бот сам создаёт лицензию и присылает ключ клиенту. Kaspi не
даёт публичного API для авто-проверки перевода, поэтому решение — за человеком.

Настройка (см. также `.env.example`):
```bash
fly secrets set KZSUB_TELEGRAM_BOT_TOKEN=<токен от @BotFather>
fly secrets set KZSUB_TELEGRAM_WEBHOOK_SECRET=<случайная строка>
fly secrets set KZSUB_TELEGRAM_ADMIN_IDS=<твой Telegram ID>   # узнать: /whoami у бота
fly secrets set KZSUB_KASPI_PHONE="<номер/реквизит Kaspi>"
fly deploy --remote-only
python -m app.telegram_bot set-webhook https://kzsub-gateway.fly.dev/telegram/webhook
```
`python -m app.telegram_bot webhook-info` — проверить регистрацию;
`delete-webhook` — снять (например, для локальной отладки long-polling).

## Качество распознавания (timing.py + postprocess.py + wer.py)
**Тайминги.** Пословные метки Whisper систематически «спешат» (VAD добавляет
паддинг перед речью, плюс смещение самого выравнивания), из-за чего текст
появлялся раньше, чем произнесён. `timing.py` находит фактическое начало речи в
аудио и подтягивает начало реплики к нему — только вперёд и только если реплика
начинается в тишине, поэтому обрезать слово он не может. Настройки:
`KZSUB_SNAP_TO_SPEECH`, `KZSUB_SNAP_WINDOW_SECONDS`.

Постобработка текста живёт на **шлюзе** (катится `fly deploy`, без пересборки
GPU-образа): фильтр зацикливаний Whisper (`KZSUB_MAX_REPEATS`), пользовательский
словарь правок (`KZSUB_LEXICON` / `KZSUB_LEXICON_PATH`), опционально — отсев
неправдоподобно долгих реплик (`KZSUB_MAX_CUE_DROP_SECONDS`).

Замер качества — обязательный гейт для любой правки «на качество»:
```bash
python -m app.wer эталон.txt распознанное.srt     # WER + CER, разбор ошибок
python -m app.wer эталон.txt распознанное.srt --keep-punct
```
Порядок работы: получить `.srt` до правки → сохранить WER → внести правку →
сравнить. Без цифр улучшения недоказуемы, а регресс не виден.
См. `docs/tasks/04-asr-quality.md`.

## Что здесь заглушка (доработать для прода)
- **Оплата** — Standard выдаётся полу-авто через Telegram-бота (см. выше) или
  вручную через CLI. Полностью авто (без участия продавца) упирается в
  отсутствие публичного API проверки платежа у Kaspi.
- **Регистрация/кабинет** — задел в `licenses.py` есть (поля email/статусы/остаток), UI и эндпоинты — впереди.
- **Хранение аудио** — временный файл на диске. Для масштаба — объектное хранилище + очередь.
- **Масштаб БД** — SQLite на томе (один инстанс). При мультирегионе — Postgres (интерфейс модуля тот же).
