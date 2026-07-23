# Система лицензий

Статус: 🟢 Базовое готово · 🟡 развитие
Приоритет: **P1**
Зависимости: нет (фундамент для [03-sales-automation](03-sales-automation.md), [05-ui-ux](05-ui-ux.md))

← [Индекс проекта (PROJECT.md)](../PROJECT.md)

## Цель

Надёжно контролировать доступ и учёт минут: каждый запрос проверяет ключ,
статус, срок и лимит; выдача/управление ключами доступны без переустановки
панели. Заложить швы под будущую автоматизацию и кабинет, не переусложняя.

## Описание

Реализовано в `backend/app/licenses.py` (SQLite на томе Fly, stdlib-only,
dep-free-тестируемо) + каталог тарифов `backend/app/plans.py`. Типы:
developer/trial/subscription/minute_pack/lifetime. Статусы:
active/expired/exhausted/suspended/revoked. Ответ несёт `X-Minutes-Remaining`.
Экономика и тарифы — в [MONETIZATION.md](../MONETIZATION.md), выдача — в
[DISTRIBUTION.md](../DISTRIBUTION.md).

## Подзадачи

- [x] Типы лицензий + поля (id/api_key/email/type/created_at/expires_at/total_minutes/used_minutes/status)
- [x] Проверка на каждом запросе: существование/статус/срок/лимит минут
- [x] Developer-ключ (обходит проверки) через `KZSUB_DEVELOPER_KEY`
- [x] CLI: create/list/plans/topup/renew/revoke/suspend/activate/delete/purge-revoked
- [x] Каталог тарифов `plans.py` как единый источник + `create_from_plan`
- [x] `GET /license` — read-only статус ключа
- [x] Удалены тестовые ключи (`dev-key`/`free-demo`); БД в проде чистая
- [x] Гонка засева при мультиворкере устранена (один воркер + busy_timeout)
- [x] Dep-free тест `test_licenses.py`
- [ ] Овередж (сверх лимита): тарификация $0.03–0.05/мин вместо отказа
- [ ] Поверхность `change_plan` (апгрейд/даунгрейд) — функция есть, нужен вызов из потока продажи/кабинета
- [ ] `POST /register {email}` → trial-лицензия (шов для регистрации, реализация — совместно с [05-ui-ux](05-ui-ux.md))
- [ ] Политика fair-use cap для `lifetime` (через `total_minutes`) — задокументировать значение по умолчанию

## Definition of Done

- Любой недействительный доступ отклоняется с корректным HTTP-кодом (401/402/403) и понятным сообщением.
- Все операции управления ключом доступны из CLI и покрыты dep-free тестом.
- Швы под автоматизацию (`create_from_plan`) и кабинет (`describe`/`X-Minutes-Remaining`) существуют и задокументированы.

## Заметки

- Легаси `KZSUB_API_KEYS` работает как бутстрап (заносится в БД при старте) — основной путь выдачи — CLI.
- Масштаб БД (Postgres) — вынесен в [07-scaling](07-scaling.md); интерфейс модуля при переезде тот же.
- Автоматизация оплаты — [03-sales-automation](03-sales-automation.md).

## История

- 2026-07-23 — Задача выделена из STATUS.md (§4, §5, §6). Базовая система в проде; отмечены остаточные пункты (овередж, change_plan, register).
