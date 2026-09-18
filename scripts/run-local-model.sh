#!/bin/bash
# Поднимает локальную модель (.gguf) сервером, к которому подключается NP Brief.
#
# Зачем отдельный скрипт: у модели на диске нет «розетки» — файл .gguf сам по
# себе ничего не отдаёт. Нужен сервер, который её загрузит и ответит по HTTP.
# Скрипт находит и то, и другое сам.
#
# Запуск:
#   bash scripts/run-local-model.sh                 # найдёт модель сам
#   bash scripts/run-local-model.sh путь/модель.gguf # конкретный файл
#
# Окно с этим сервером нужно держать открытым, пока пользуешься NP Brief.
set -euo pipefail

PORT="${NPBRIEF_PORT:-8080}"
CTX="${NPBRIEF_CTX:-16384}"
MODEL="${1:-}"

# Где обычно лежат .gguf на маке: свои папки, Cotypist, LM Studio, загрузки.
SEARCH_DIRS=(
  "$HOME/Models"
  "$HOME/Library/Application Support/NPAutocomplete/Models"
  "$HOME/.cache/lm-studio/models"
  "$HOME/.lmstudio/models"
  "$HOME/Downloads"
)

find_server() {
  if command -v llama-server >/dev/null 2>&1; then
    command -v llama-server
    return 0
  fi
  for candidate in /opt/homebrew/bin/llama-server /usr/local/bin/llama-server; do
    [ -x "$candidate" ] && echo "$candidate" && return 0
  done
  return 1
}

pick_model() {
  local files it
  files=$(find "${SEARCH_DIRS[@]}" -maxdepth 4 -name "*.gguf" -size +100M 2>/dev/null || true)
  [ -z "$files" ] && return 1
  # Инструкт-версии («-it», «instruct», «chat») умеют выполнять указания; базовые
  # модели просто продолжают текст и для разбора не годятся.
  it=$(printf '%s\n' "$files" | grep -iE '(\-it|instruct|chat)' || true)
  [ -n "$it" ] && files="$it"
  # Из оставшихся берём самый большой файл: обычно это самая сильная модель.
  printf '%s\n' "$files" | while IFS= read -r f; do
    [ -f "$f" ] && printf '%s\t%s\n' "$(stat -f '%z' "$f")" "$f"
  done | sort -rn | head -1 | cut -f2-
}

SERVER="$(find_server || true)"
if [ -z "$SERVER" ]; then
  echo "Не найден llama-server — это он загружает .gguf и отдаёт её по сети."
  echo ""
  echo "Поставь его одной командой:"
  echo "    brew install llama.cpp"
  echo ""
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew тоже нет. Сначала он (одна команда, спросит пароль):"
    echo '    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    echo ""
  fi
  echo "Либо поставь Ollama (https://ollama.com) — NP Brief понимает и её."
  exit 1
fi

if [ -z "$MODEL" ]; then
  MODEL="$(pick_model || true)"
fi
if [ -z "$MODEL" ] || [ ! -f "$MODEL" ]; then
  echo "Не нашёл ни одной модели .gguf в обычных местах:"
  printf '    %s\n' "${SEARCH_DIRS[@]}"
  echo ""
  echo "Укажи файл сам:  bash scripts/run-local-model.sh путь/к/модели.gguf"
  exit 1
fi

echo "Модель:  $MODEL"
echo "Адрес:   http://127.0.0.1:$PORT   (его NP Brief найдёт сам)"
echo "Окно держи открытым. Остановить — Ctrl+C."
echo ""
exec "$SERVER" -m "$MODEL" --host 127.0.0.1 --port "$PORT" -c "$CTX"
