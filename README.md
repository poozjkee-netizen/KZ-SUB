# NP SUB — авто-субтитры на казахском для Adobe Premiere Pro

Плагин для Premiere Pro, который автоматически распознаёт **казахскую речь** и
вставляет субтитры на таймлайн. Premiere «из коробки» не транскрибирует казахский —
это и есть проблема, которую решает продукт.

> Внутренний идентификатор проекта — `kzsub` (env-префикс `KZSUB_`, имена
> инфраструктуры). Пользователь видит только «NP SUB». Подробнее — [`CLAUDE.md`](CLAUDE.md).

## Как это устроено (прод)

Три независимо деплоящихся части:

```
┌────────────────────┐   HTTPS    ┌────────────────────┐   Runpod API  ┌──────────────────┐
│  Панель (CEP)      │ ─────────▶ │  Шлюз (FastAPI)    │ ────────────▶ │  GPU-воркер      │
│  plugin/ → .zxp    │ multipart  │  backend/ → Fly.io │  /run+/status │ serverless/→Runpod│
│  у пользователя    │ ◀───────── │  ключи+квоты+      │ ◀──────────── │  Whisper large-v3│
│                    │   .srt     │  device-binding    │   сегменты    │                  │
└────────────────────┘            └────────────────────┘               └──────────────────┘
```

Ядро продукта — **не плагин, а движок распознавания казахского**. Панель лишь
тонкий клиент: одна кнопка, вся техника спрятана. Качество ASR = ценность, за
которую платят.

## Статус

**Рабочий продукт (v1.0.0).** Панель ставится из подписанного `.zxp` на macOS и
Windows, прод-бэкенд поднят на Fly + Runpod, есть выдача ключей с привязкой к
устройствам. Что дальше — [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Структура репозитория

| Папка / файл | Что внутри |
|---|---|
| `plugin/`   | CEP-панель для Premiere (UI, выгрузка аудио, вставка субтитров) → `.zxp` |
| `backend/app/` | Шлюз FastAPI: приём аудио, ключи, квоты, два режима (локальный/прокси) |
| `backend/serverless/` | GPU-воркер Runpod (Whisper large-v3) |
| `backend/tests/` | Тесты (dep-free + интеграционный) |
| `scripts/`  | Установка панели, запуск бэкенда, сборка `.zxp`, генерация иконок |
| `docs/`     | Архитектура, решения, хостинг, дистрибуция, релизы, монетизация, roadmap |
| `CLAUDE.md` | Постоянные правила разработки (читать первым) |

## Быстрый старт (локальная разработка)

Полный сценарий первого запуска — [`docs/RUNBOOK.md`](docs/RUNBOOK.md). Кратко:

```bash
# 1. Установить панель в Premiere (dev-режим)
bash scripts/install-macos.sh          # Windows: scripts\install-windows.ps1

# 2. Запустить локальный бэкенд (Whisper в процессе)
bash scripts/run-backend.sh            # Windows: scripts\run-backend.bat

# 3. Тесты
cd backend && pytest
```
Затем в Premiere: **Window → Extensions → NP SUB**, ключ `dev-key` → «Тест».

## Деплой и раздача

- **Поднять бэкенд** (Fly + Runpod, сетевой том, анти-шаринг) — [`docs/HOSTING.md`](docs/HOSTING.md).
- **Собрать/подписать `.zxp` и раздать клиентам** — [`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md).
- **Порядок релизов** (панель / шлюз / воркер) — [`docs/RELEASE_PROCESS.md`](docs/RELEASE_PROCESS.md).

## Документация

Оглавление — [`docs/README.md`](docs/README.md).

- [Правила разработки (CLAUDE.md)](CLAUDE.md) · [Архитектура](docs/ARCHITECTURE.md) · [Решения (ADR)](docs/DECISIONS.md)
- [Хостинг](docs/HOSTING.md) · [Дистрибуция](docs/DISTRIBUTION.md) · [Релизы](docs/RELEASE_PROCESS.md)
- [Монетизация](docs/MONETIZATION.md) · [Roadmap](docs/ROADMAP.md) · [Changelog](CHANGELOG.md)

## Лицензия

Проприетарное ПО, все права защищены — [`LICENSE`](LICENSE).
