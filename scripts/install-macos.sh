#!/usr/bin/env bash
#
# Установка панели KZ-SUB в Premiere Pro (macOS), режим разработки.
# Включает debug-режим CEP (неподписанные расширения) и линкует папку plugin/
# в директорию расширений Adobe. Симлинк — чтобы правки в репозитории сразу
# подхватывались (после перезапуска панели).
#
# Запуск:  bash scripts/install-macos.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/../plugin" && pwd)"
EXT_DIR="$HOME/Library/Application Support/Adobe/CEP/extensions"
LINK="$EXT_DIR/kz.kzsub.panel"

echo "==> Включаю debug-режим CEP (CSXS 9–13)…"
# Номер CSXS зависит от версии Premiere; ставим флаг для диапазона, чтобы
# точно попасть в нужную версию.
for v in 9 10 11 12 13; do
  defaults write "com.adobe.CSXS.$v" PlayerDebugMode 1 2>/dev/null || true
done

echo "==> Линкую панель в $EXT_DIR…"
mkdir -p "$EXT_DIR"
rm -rf "$LINK"
ln -s "$PLUGIN_DIR" "$LINK"

echo ""
echo "Готово:"
echo "  $LINK  ->  $PLUGIN_DIR"
echo ""
echo "Дальше:"
echo "  1. Полностью закройте и снова откройте Premiere Pro."
echo "  2. Window → Extensions → «KZ-SUB — қазақша субтитр»."
echo "  3. Запустите бэкенд:  bash scripts/run-backend.sh"
echo ""
echo "Удалить установку:  rm \"$LINK\""
