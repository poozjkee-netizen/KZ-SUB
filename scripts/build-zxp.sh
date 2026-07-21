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
# Результат: dist/KZ-SUB.zxp  (+ самоподписанный сертификат dist/kzsub-cert.p12)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN="$ROOT/plugin"
DIST="$ROOT/dist"

SIGN="${ZXPSIGNCMD:-ZXPSignCmd}"
CERT="$DIST/kzsub-cert.p12"
CERT_PASS="${KZSUB_CERT_PASS:-kzsub2026}"
ZXP="$DIST/KZ-SUB.zxp"

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

# 2. Подпись плагина в .zxp (с временной меткой — подпись не «протухает»).
echo "==> Подписываю плагин в .zxp…"
rm -f "$ZXP"
"$SIGN" -sign "$PLUGIN" "$ZXP" "$CERT" "$CERT_PASS" \
        -tsa https://timestamp.digicert.com

echo ""
echo "Готово: $ZXP"
echo "Раздавай пользователям этот файл + инструкцию из docs/DISTRIBUTION.md"
