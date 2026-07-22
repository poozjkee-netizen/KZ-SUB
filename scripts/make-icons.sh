#!/usr/bin/env bash
#
# Превращает ваше изображение логотипа в иконку расширения (macOS).
# Использует встроенный в macOS `sips` — ничего устанавливать не нужно.
#
# Использование:
#   bash scripts/make-icons.sh ~/Desktop/np-icon.png
#
# Кладёт готовую иконку в plugin/icons/icon.png (23x23, PNG).
# После этого пересоберите .zxp (scripts/build-zxp.sh).
#
set -euo pipefail

SRC="${1:?Укажите путь к картинке: bash scripts/make-icons.sh <файл.png/jpg>}"
if [ ! -f "$SRC" ]; then
  echo "Файл не найден: $SRC"; exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$ROOT/plugin/icons"
mkdir -p "$DIR"

# 23x23 — стандартный размер иконки вкладки CEP.
sips -s format png -z 23 23 "$SRC" --out "$DIR/icon.png" >/dev/null

echo "Готово: $DIR/icon.png (23x23)"
echo "Теперь пересоберите плагин: scripts/build-zxp.sh"
