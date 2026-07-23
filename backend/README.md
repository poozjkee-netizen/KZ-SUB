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
| `KZSUB_MAX_AUDIO_SECONDS`     | `5400`       | лимит длительности файла            |
| `KZSUB_CAPTION_STYLE`         | `word`       | `word` (караоке, по слову) / `phrase` (фразы) |
| `KZSUB_GLUE_MAX_CHARS`        | `2`          | в режиме `word`: короткие слова липнут к следующему |
| `KZSUB_UPPERCASE`             | `false`      | ВЕРХНИЙ регистр субтитров            |
| `KZSUB_STRIP_PUNCTUATION`     | `true`       | убирать пунктуацию (караоке-стиль)   |
| `KZSUB_PUNCT_KEEP`            | `!`          | какие знаки оставить при очистке     |
| `KZSUB_MAX_LINE_CHARS`        | `42`         | (режим `phrase`) макс. символов в строке |
| `KZSUB_MAX_LINES`             | `2`          | макс. строк в реплике               |
| `KZSUB_MAX_CUE_SECONDS`       | `7.0`        | макс. длительность реплики          |
| `KZSUB_MAX_GAP_SECONDS`       | `0.8`        | пауза для разрыва реплики           |

## Тесты
```bash
# Без тяжёлых зависимостей (чистая логика):
python tests/test_srt.py
python tests/test_licenses.py
python tests/test_segmentation.py
python tests/test_style.py
python tests/test_devices.py

# Интеграционный тест HTTP-контракта /transcribe (нужен fastapi/httpx,
# модель Whisper замокана — GPU/веса не требуются):
pytest tests/test_api.py
```

## Лицензии (app/licenses.py)
Постоянное хранилище лицензий на SQLite (том Fly). Типы: `developer` (безлимит),
`trial` (по времени), `subscription` (30 дней + минуты), `minute_pack` (минуты),
`lifetime`. При каждом запросе проверяются существование ключа, статус, срок и
лимит минут. Выдача ключей вручную (до автоматизации оплаты):
```bash
python -m app.licenses create --email user@mail --type subscription --minutes 300 --days 30
python -m app.licenses list
python -m app.licenses topup <api_key> --minutes 100
```

## Что здесь заглушка (доработать для прода)
- **Оплата** — ключи выдаются вручную через CLI. Нужен вебхук Kaspi/Stripe → авто-создание лицензий.
- **Регистрация/кабинет** — задел в `licenses.py` есть (поля email/статусы/остаток), UI и эндпоинты — впереди.
- **Хранение аудио** — временный файл на диске. Для масштаба — объектное хранилище + очередь.
- **Масштаб БД** — SQLite на томе (один инстанс). При мультирегионе — Postgres (интерфейс модуля тот же).
