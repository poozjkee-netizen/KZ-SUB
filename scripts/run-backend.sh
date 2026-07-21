#!/usr/bin/env bash
#
# Запуск бэкенда KZ-SUB локально (macOS/Linux).
# Создаёт venv, ставит зависимости и поднимает API на http://127.0.0.1:8000
#
# Запуск:  bash scripts/run-backend.sh
#
# Модель по умолчанию — large-v3 (лучшее качество казахского, но на CPU
# медленно и первый запуск качает ~3 ГБ весов). Для быстрого smoke-теста можно:
#   KZSUB_WHISPER_MODEL=small bash scripts/run-backend.sh
# (качество ниже — только чтобы проверить, что цепочка работает).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../backend"

if [ ! -d .venv ]; then
  echo "==> Создаю виртуальное окружение…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Устанавливаю зависимости…"
pip install -q --upgrade pip
pip install -q -r requirements.txt

export KZSUB_WHISPER_MODEL="${KZSUB_WHISPER_MODEL:-large-v3}"
export KZSUB_DEVICE="${KZSUB_DEVICE:-cpu}"
export KZSUB_COMPUTE_TYPE="${KZSUB_COMPUTE_TYPE:-int8}"

echo ""
echo "Модель: $KZSUB_WHISPER_MODEL · device: $KZSUB_DEVICE · compute: $KZSUB_COMPUTE_TYPE"
echo "API-кілт для панели: dev-key"
echo "Слушаю http://127.0.0.1:8000  (Ctrl+C — стоп)"
echo ""
uvicorn app.main:app --host 127.0.0.1 --port 8000
