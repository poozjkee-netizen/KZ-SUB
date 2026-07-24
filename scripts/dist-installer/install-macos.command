#!/bin/bash
# ============================================================
#   NP SUB — установщик панели для Adobe Premiere Pro (macOS)
#   Двойной клик в Finder. Пароль/root НЕ нужны — всё ставится
#   в домашнюю папку пользователя.
#   Ставит панель в папку расширений и включает режим
#   самоподписанных расширений (PlayerDebugMode) для всех
#   версий Premiere (CEP 9–13).
# ============================================================

# Папка, где лежит сам установщик (рядом должна быть папка NP-SUB).
DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$DIR/NP-SUB"
DEST="$HOME/Library/Application Support/Adobe/CEP/extensions/kz.kzsub.panel"

echo ""
echo "==== Установка панели NP SUB ===="
echo ""

if [ ! -f "$SRC/CSXS/manifest.xml" ]; then
  echo "ОШИБКА: рядом с установщиком нет папки NP-SUB с плагином."
  echo "Распакуйте архив полностью и запустите установщик из распакованной папки."
  echo ""
  read -r -p "Нажмите Enter, чтобы закрыть..." _
  exit 1
fi

echo "[1/3] Включаю режим расширений (только для вашего пользователя)..."
for v in 9 10 11 12 13; do
  defaults write "com.adobe.CSXS.$v" PlayerDebugMode 1 >/dev/null 2>&1 || true
done
# Сбрасываем кэш настроек, чтобы флаг применился без перезагрузки.
killall cfprefsd >/dev/null 2>&1 || true

echo "[2/3] Копирую панель в папку расширений Adobe..."
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -R "$SRC" "$DEST"
# Снимаем «карантин» с скопированных файлов (иначе macOS может блокировать).
xattr -dr com.apple.quarantine "$DEST" >/dev/null 2>&1 || true

echo "[3/3] Готово!"
echo ""
echo "Панель установлена сюда:"
echo "  $DEST"
echo ""
echo "Дальше:"
echo "  1. Полностью закройте и снова откройте Premiere Pro."
echo "  2. Верхнее меню: Window → Extensions → NP SUB."
echo "  3. Введите ключ активации."
echo ""
read -r -p "Нажмите Enter, чтобы закрыть..." _
