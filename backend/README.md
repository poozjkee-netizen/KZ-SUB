# KZ-SUB Backend

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

Коды ответа: `401` нет ключа · `402` квота исчерпана · `413` файл слишком длинный · `500` ошибка транскрибации.

## Конфигурация (env, префикс `KZSUB_`)
| Переменная                    | По умолчанию | Назначение                          |
|-------------------------------|--------------|-------------------------------------|
| `KZSUB_WHISPER_MODEL`         | `large-v3`   | модель Whisper                      |
| `KZSUB_DEVICE`                | `cpu`        | `cpu` / `cuda`                      |
| `KZSUB_COMPUTE_TYPE`          | `int8`       | тип вычислений                      |
| `KZSUB_FREE_MINUTES_PER_MONTH`| `30`         | бесплатный лимит                    |
| `KZSUB_MAX_AUDIO_SECONDS`     | `5400`       | лимит длительности файла            |
| `KZSUB_CAPTION_STYLE`         | `word`       | `word` (караоке, по слову) / `phrase` (фразы) |
| `KZSUB_GLUE_MAX_CHARS`        | `2`          | в режиме `word`: короткие слова липнут к следующему |
| `KZSUB_MAX_LINE_CHARS`        | `42`         | (режим `phrase`) макс. символов в строке |
| `KZSUB_MAX_LINES`             | `2`          | макс. строк в реплике               |
| `KZSUB_MAX_CUE_SECONDS`       | `7.0`        | макс. длительность реплики          |
| `KZSUB_MAX_GAP_SECONDS`       | `0.8`        | пауза для разрыва реплики           |

## Тесты
```bash
# Без тяжёлых зависимостей (чистая логика):
python tests/test_srt.py
python tests/test_quota.py
python tests/test_segmentation.py

# Интеграционный тест HTTP-контракта /transcribe (нужен fastapi/httpx,
# модель Whisper замокана — GPU/веса не требуются):
pytest tests/test_api.py
```

## Что здесь заглушка (доработать для прода)
- **`app/quota.py`** — учёт в памяти процесса. Заменить на БД + биллинг.
- **Аутентификация** — статичный словарь ключей. Нужны реальные пользователи/токены.
- **Хранение аудио** — временный файл на диске. Для масштаба — объектное хранилище + очередь.
