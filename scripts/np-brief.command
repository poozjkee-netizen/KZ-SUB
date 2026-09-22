#!/bin/bash
# Запуск NP Brief двойным кликом из Finder.
#
# Кладётся рядом с репозиторием, поэтому сам находит и проект, и окружение
# Python. Окно открывается в браузере, адрес постоянный — его можно сохранить
# в закладки. Закрыть программу: Ctrl+C в этом окне Терминала.
cd "$(dirname "$0")/.." || exit 1

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
elif [ -x "$HOME/Library/Application Support/NP Brief/venv/bin/python" ]; then
  PYTHON="$HOME/Library/Application Support/NP Brief/venv/bin/python"
else
  PYTHON="python3"
fi

exec "$PYTHON" -m tools.videobrief.webapp
