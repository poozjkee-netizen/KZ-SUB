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
| `KZSUB_CONDITION_ON_PREVIOUS_TEXT`| `false`  | опора на предыдущий текст — главный источник «выдуманных слов» (воркер) |
| `KZSUB_NO_SPEECH_THRESHOLD`   | `0.6`        | порог «здесь нет речи» (воркер) |
| `KZSUB_LOG_PROB_THRESHOLD`    | `-1.5`       | отсев сегментов с низкой уверенностью; мягче штатных `-1.0`, иначе теряются реплики на казахском (воркер) |
| `KZSUB_COMPRESSION_RATIO_THRESHOLD`| `2.4`   | ловит зацикленный повторяющийся бред (воркер) |
| `KZSUB_HALLUCINATION_SILENCE_THRESHOLD`| `0` | пропускать тишину длиннее N сек (0 = выкл; выключено — уносил настоящую речь; воркер) |
| `KZSUB_VAD_SPEECH_PAD_MS`     | `200`        | паддинг VAD; штатные 400 мс = субтитр раньше слова (воркер) |
| `KZSUB_VAD_MIN_SILENCE_MS`    | `400`        | пауза для деления речи на фрагменты (воркер) |
| `KZSUB_VAD_THRESHOLD`         | `0.35`       | чувствительность VAD: ниже — не теряем тихую речь (воркер) |
| `KZSUB_INITIAL_PROMPT`        | (пусто)      | затравка декодера: пример смешанной каз/рус речи против «оказашивания» русских слов (воркер) |
| `KZSUB_HOTWORDS`              | (пусто)      | подсказка редких слов/имён через запятую (воркер) |
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
| `KZSUB_SNAP_TO_SPEECH`        | `false`      | подтягивать начало реплики к началу речи (выкл по умолчанию) |
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
python tests/test_timing.py
python tests/test_transcribe_options.py

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
**Тайминги и «выдуманные слова».** Оба дефекта родом из декодирования, поэтому
основные рычаги — в **воркере** (`transcribe.py`, `decode_options()`), и для
прода они требуют **пересборки GPU-образа**:
- `KZSUB_CONDITION_ON_PREVIOUS_TEXT=false` — главный источник галлюцинаций:
  модель подхватывает собственный выдуманный текст как контекст;
- `KZSUB_HALLUCINATION_SILENCE_THRESHOLD`, `KZSUB_NO_SPEECH_THRESHOLD`,
  `KZSUB_LOG_PROB_THRESHOLD`, `KZSUB_COMPRESSION_RATIO_THRESHOLD` — отсев текста,
  надуманного в тишине и на музыке. **Каждый из них умеет выбросить настоящую
  речь**, и замер 2026-07-28 показал, что именно они, а не модель, съедали целые
  предложения. Поэтому баланс сдвинут к полноте: `hallucination_silence_threshold`
  выключен, `log_prob_threshold` мягче (`-1.5`), VAD чувствительнее (`0.35`).
  Проверить, не режут ли фильтры речь на конкретном ролике:
  `python scripts/transcribe-local.py запись.wav --no-filters`;
- `KZSUB_VAD_SPEECH_PAD_MS=200` (вместо штатных 400) — именно этот паддинг
  сдвигал начало субтитра раньше слова.

Дополнительно на шлюзе есть привязка начала реплики к фактическому началу речи
(`timing.py`, `KZSUB_SNAP_TO_SPEECH`) — **выключена по умолчанию**: на реальном
материале она сделала хуже, включать только с проверкой результата.

Постобработка текста живёт на **шлюзе** (катится `fly deploy`, без пересборки
GPU-образа): фильтр зацикливаний Whisper (`KZSUB_MAX_REPEATS`), пользовательский
словарь правок (`KZSUB_LEXICON` / `KZSUB_LEXICON_PATH`), опционально — отсев
неправдоподобно долгих реплик (`KZSUB_MAX_CUE_DROP_SECONDS`).

Замер качества — обязательный гейт для любой правки «на качество»:
```bash
python -m app.wer эталон.txt распознанное.srt              # WER + CER, разбор ошибок
python -m app.wer эталон.txt a.srt b.srt c.srt             # сравнить модели: таблица по WER
python -m app.wer эталон.txt распознанное.srt --keep-punct
```
Сравнение нескольких файлов сортирует их по WER — так выбирают модель по цифрам,
а не на глаз (обзор вариантов — `docs/ASR_PROVIDERS.md`).
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
