#!/usr/bin/env bash
#
# Сборка подписанного .zxp плагина KZ-SUB для раздачи пользователям.
#
# Требуется инструмент Adobe ZXPSignCmd (см. docs/DISTRIBUTION.md, как получить).
# Укажи путь к нему через переменную ZXPSIGNCMD, либо положи его в PATH.
#
# Запуск:
#   ZXPSIGNCMD=/path/to/ZXPSignCmd bash scripts/build-zxp.sh
#
# Результат: dist/NP-SUB-<версия>.zxp  (+ самоподписанный сертификат dist/kzsub-cert.p12)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN="$ROOT/plugin"
DIST="$ROOT/dist"

SIGN="${ZXPSIGNCMD:-ZXPSignCmd}"
CERT="$DIST/kzsub-cert.p12"
CERT_PASS="${KZSUB_CERT_PASS:-kzsub2026}"

# Версия берётся из манифеста — имя файла всегда совпадает с версией панели,
# чтобы не путать сборки: dist/NP-SUB-<версия>.zxp.
VERSION="$(grep -o 'ExtensionBundleVersion="[^"]*"' "$PLUGIN/CSXS/manifest.xml" \
           | head -1 | sed 's/.*="\(.*\)"/\1/')"
VERSION="${VERSION:-dev}"
ZXP="$DIST/NP-SUB-$VERSION.zxp"

# Данные для самоподписанного сертификата (можно переопределить переменными).
CERT_COUNTRY="${KZSUB_CERT_COUNTRY:-KZ}"
CERT_STATE="${KZSUB_CERT_STATE:-Almaty}"
CERT_ORG="${KZSUB_CERT_ORG:-np3_player}"
CERT_NAME="${KZSUB_CERT_NAME:-KZ-SUB}"

if ! command -v "$SIGN" >/dev/null 2>&1 && [ ! -x "$SIGN" ]; then
  echo "ОШИБКА: не найден ZXPSignCmd."
  echo "Укажи путь: ZXPSIGNCMD=/path/to/ZXPSignCmd bash scripts/build-zxp.sh"
  echo "Как получить — см. docs/DISTRIBUTION.md"
  exit 1
fi

mkdir -p "$DIST"

# 1. Самоподписанный сертификат (создаётся один раз).
if [ ! -f "$CERT" ]; then
  echo "==> Создаю самоподписанный сертификат…"
  "$SIGN" -selfSignedCert "$CERT_COUNTRY" "$CERT_STATE" "$CERT_ORG" "$CERT_NAME" \
          "$CERT_PASS" "$CERT"
fi

# 2. Подпись плагина в .zxp.
# Временная метка (TSA) желательна, но если сервер недоступен — подписываем без
# неё (для прямой раздачи клиентам это нормально). Отключить принудительно:
# KZSUB_TSA= bash scripts/build-zxp.sh
TSA="${KZSUB_TSA-http://timestamp.digicert.com}"
echo "==> Подписываю плагин в .zxp…"
rm -f "$ZXP"

signed=0
if [ -n "$TSA" ]; then
  if "$SIGN" -sign "$PLUGIN" "$ZXP" "$CERT" "$CERT_PASS" -tsa "$TSA"; then
    signed=1
  else
    echo "   TSA недоступен — подписываю без временной метки…"
    rm -f "$ZXP"
  fi
fi
if [ "$signed" -eq 0 ]; then
  "$SIGN" -sign "$PLUGIN" "$ZXP" "$CERT" "$CERT_PASS"
fi

# 3. Установщик-«одним-кликом» для клиентов (Windows .bat + macOS .command).
# Ставит панель без ZXP Installer и без ручной правки реестра — самый
# надёжный путь установки для нетехнических пользователей (см. DISTRIBUTION.md).
echo "==> Собираю установщик для клиентов…"
STAGE="$DIST/NP-SUB-$VERSION-installer"
INSTALLER_ZIP="$DIST/NP-SUB-$VERSION-installer.zip"
rm -rf "$STAGE" "$INSTALLER_ZIP"
mkdir -p "$STAGE/NP-SUB"
# Копируем файлы панели, исключая dev-only .debug (удалённая отладка CEF).
cp -R "$PLUGIN/." "$STAGE/NP-SUB/"
rm -f "$STAGE/NP-SUB/.debug"
cp "$SCRIPT_DIR/dist-installer/install-windows.bat" "$STAGE/"
cp "$SCRIPT_DIR/dist-installer/install-macos.command" "$STAGE/"
cp "$SCRIPT_DIR/dist-installer/README.txt" "$STAGE/"
chmod +x "$STAGE/install-macos.command"
( cd "$DIST" && zip -r -q "NP-SUB-$VERSION-installer.zip" "NP-SUB-$VERSION-installer" )
rm -rf "$STAGE"

# 4. Копия для раздачи: сайт и Telegram-бот берут установщик по ОДНОЙ постоянной
# ссылке, поэтому имя файла без версии. Иначе каждая новая сборка ломала бы
# ссылку на лендинге и в боте, а версия и так лежит внутри архива (README.txt).
PUBLIC_DIR="$ROOT/site/download"
PUBLIC_ZIP="$PUBLIC_DIR/NP-SUB-installer.zip"
mkdir -p "$PUBLIC_DIR"
cp "$INSTALLER_ZIP" "$PUBLIC_ZIP"
printf '%s\n' "$VERSION" > "$PUBLIC_DIR/VERSION"

echo ""
echo "Готово:"
echo "  $ZXP"
echo "  $INSTALLER_ZIP   (установщик одним кликом — рекомендуется клиентам)"
echo "  $PUBLIC_ZIP   (для сайта и бота — закоммить и запушь)"
echo ""
echo "Чтобы раздача обновилась:"
echo "  git add site/download && git commit -m \"Обнови установщик до $VERSION\" && git push"
