# KZ-SUB Plugin (CEP-панель для Premiere Pro)

Панель, которая выгружает аудио активной секвенции, отправляет его на
[бэкенд KZ-SUB](../backend/README.md), получает казахские субтитры и
импортирует их обратно в проект Premiere.

## Технология
- **CEP** (Common Extensibility Platform) — HTML/CSS/JS панель + ExtendScript.
- Выбран CEP, а не UXP: для Premiere UXP ещё незрелый, а CEP даёт полный
  доступ к секвенциям и экспорту/импорту. Переход на UXP — в roadmap.

## Файлы
| Путь                     | Назначение                                        |
|--------------------------|---------------------------------------------------|
| `CSXS/manifest.xml`      | описание расширения (host PPRO)                   |
| `index.html`             | UI панели                                         |
| `css/style.css`          | стили                                             |
| `js/main.js`             | логика: экспорт → загрузка → импорт               |
| `js/CSInterface.js`      | **нужно скачать** у Adobe (см. ниже)              |
| `jsx/host.jsx`           | ExtendScript: экспорт аудио, импорт .srt          |
| `presets/audio_wav.epr`  | **нужно создать** аудио-пресет (см. presets/README) |
| `.debug`                 | порт удалённой отладки                            |

## Установка (режим разработки)

### 1. Скачать CSInterface.js
Из [Adobe-CEP/CEP-Resources](https://github.com/Adobe-CEP/CEP-Resources)
(папка `CEP_11.x/CSInterface.js`) → положить в `plugin/js/CSInterface.js`.

### 2. Включить debug-режим CEP (неподписанные расширения)
- **macOS:** `defaults write com.adobe.CSXS.11 PlayerDebugMode 1`
- **Windows:** в реестре `HKEY_CURRENT_USER\Software\Adobe\CSXS.11`
  строковый параметр `PlayerDebugMode = 1`

> Номер (`CSXS.11`) зависит от версии Premiere. Для новых версий может быть
> `CSXS.12`. Поставьте флаг для той версии, что используете.

### 3. Положить панель в папку расширений
Скопируйте (или симлинкните) папку `plugin/` как `kz.kzsub.panel` в:
- **macOS:** `~/Library/Application Support/Adobe/CEP/extensions/`
- **Windows:** `%APPDATA%\Adobe\CEP\extensions\`

### 4. Создать аудио-пресет
См. [`presets/README.md`](presets/README.md).

### 5. Запустить
Premiere → **Window → Extensions → KZ-SUB**. Укажите API URL и ключ, откройте
секвенцию, нажмите **«Субтитр жасау»**.

## Дистрибуция (прод)
Для установки у пользователей без debug-режима панель нужно **подписать**
(`.zxp`) с помощью `ZXPSignCmd` и выложить на **Adobe Exchange**. См.
[`docs/ROADMAP.md`](../docs/ROADMAP.md).

## Известные ограничения (MVP)
- Импорт `.srt` кладёт ассет в бин проекта — пользователь перетаскивает его на
  таймлайн вручную (одно действие). Автоматическую вставку caption-дорожки —
  в roadmap.
- Требуется предварительно созданный `.epr` аудио-пресет.
