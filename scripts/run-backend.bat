@echo off
REM Запуск бэкенда KZ-SUB локально (Windows).
REM Создаёт venv, ставит зависимости и поднимает API на http://127.0.0.1:8000
REM
REM Запуск:  scripts\run-backend.bat
REM
REM Модель по умолчанию large-v3 (первый запуск качает ~3 ГБ). Для быстрого
REM smoke-теста заранее выполните:  set KZSUB_WHISPER_MODEL=small

setlocal
cd /d "%~dp0..\backend"

if not exist ".venv" (
  echo ==^> Создаю виртуальное окружение...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo ==^> Устанавливаю зависимости...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

if "%KZSUB_WHISPER_MODEL%"=="" set KZSUB_WHISPER_MODEL=large-v3
if "%KZSUB_DEVICE%"=="" set KZSUB_DEVICE=cpu
if "%KZSUB_COMPUTE_TYPE%"=="" set KZSUB_COMPUTE_TYPE=int8

echo.
echo Модель: %KZSUB_WHISPER_MODEL% · device: %KZSUB_DEVICE% · compute: %KZSUB_COMPUTE_TYPE%
echo API-кілт для панели: dev-key
echo Слушаю http://127.0.0.1:8000  (Ctrl+C - стоп)
echo.
uvicorn app.main:app --host 127.0.0.1 --port 8000
endlocal
