#!/bin/bash
# Установщик NP Brief для macOS: ссылка на ролик -> расшифровка -> разбор.
#
# Что делает:
#   1) создаёт отдельное окружение Python в ~/Library/Application Support/NP Brief
#   2) ставит туда yt-dlp, anthropic и faster-whisper
#   3) копирует туда сам инструмент (tools/videobrief)
#   4) создаёт ~/Applications/NP Brief.app — его и запускаешь двойным кликом
#
# Запуск из корня репозитория:
#   bash scripts/install-np-brief-mac.sh
#
# Повторный запуск = обновление: окружение и файлы просто перезаписываются.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="NP Brief"
SUPPORT="$HOME/Library/Application Support/$APP_NAME"
APP_DIR="$HOME/Applications/$APP_NAME.app"
VENV="$SUPPORT/venv"

say() { printf '\033[1m%s\033[0m\n' "$*"; }

if [ "$(uname)" != "Darwin" ]; then
  echo "Этот установщик для macOS. На другой системе запускай: python -m tools.videobrief.webapp"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Нет python3. Установи инструменты разработчика Apple и повтори:"
  echo "    xcode-select --install"
  exit 1
fi

say "1/4 Готовлю окружение (это разово, пара минут)…"
mkdir -p "$SUPPORT"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null

say "2/4 Ставлю зависимости: yt-dlp, anthropic, faster-whisper…"
"$VENV/bin/python" -m pip install -r "$REPO_DIR/tools/videobrief/requirements.txt"

say "3/4 Копирую приложение…"
rm -rf "$SUPPORT/app"
mkdir -p "$SUPPORT/app"
cp -R "$REPO_DIR/tools/videobrief" "$SUPPORT/app/videobrief"
rm -rf "$SUPPORT/app/videobrief/tests" "$SUPPORT/app/videobrief/__pycache__"

say "4/4 Собираю NP Brief.app…"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"

cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>kz.kzsub.npbrief</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>np-brief</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# Запускающий скрипт. PATH расширен на Homebrew: там обычно лежит ffmpeg, а
# приложения, запущенные из Finder, не видят переменных из ~/.zshrc.
cat > "$APP_DIR/Contents/MacOS/np-brief" <<LAUNCH
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
export PYTHONPATH="$SUPPORT/app"
exec "$VENV/bin/python" -m videobrief.webapp
LAUNCH
chmod +x "$APP_DIR/Contents/MacOS/np-brief"

say ""
say "Готово. NP Brief лежит в ~/Applications."
echo "Открой его двойным кликом — откроется окно в браузере."
echo "Первым делом нажми ⚙︎ и вставь ключ Anthropic — без него будет только расшифровка."
echo ""
echo "Открыть сейчас:  open \"$APP_DIR\""
