@echo off
chcp 65001 >nul
setlocal enableextensions

rem ============================================================
rem   NP SUB — установщик панели для Adobe Premiere Pro (Windows)
rem   Двойной клик. Права администратора НЕ нужны.
rem   Ставит панель в папку расширений пользователя и включает
rem   режим самоподписанных расширений (PlayerDebugMode) для
rem   всех версий Premiere (CEP 9–13).
rem ============================================================

set "SRC=%~dp0NP-SUB"
set "DEST=%APPDATA%\Adobe\CEP\extensions\kz.kzsub.panel"

echo.
echo ==== Установка панели NP SUB ====
echo.

if not exist "%SRC%\CSXS\manifest.xml" (
  echo ОШИБКА: рядом с этим файлом нет папки NP-SUB с плагином.
  echo Распакуйте архив ПОЛНОСТЬЮ и запустите установщик из распакованной папки.
  echo.
  pause
  exit /b 1
)

echo [1/3] Включаю режим расширений (реестр, только для вашего пользователя)...
for %%V in (9 10 11 12 13) do (
  reg add "HKCU\Software\Adobe\CSXS.%%V" /v PlayerDebugMode /t REG_SZ /d 1 /f >nul 2>&1
)

echo [2/3] Копирую панель в папку расширений Adobe...
if exist "%DEST%" rmdir /S /Q "%DEST%"
mkdir "%DEST%" >nul 2>&1
xcopy "%SRC%" "%DEST%\" /E /I /Y /Q >nul
if errorlevel 1 (
  echo ОШИБКА: не удалось скопировать файлы. Закройте Premiere и попробуйте снова.
  echo.
  pause
  exit /b 1
)

echo [3/3] Готово!
echo.
echo Панель установлена сюда:
echo   %DEST%
echo.
echo Дальше:
echo   1. Полностью закройте и снова откройте Premiere Pro.
echo   2. Верхнее меню: Window - Extensions - NP SUB.
echo   3. Введите ключ активации.
echo.
pause
endlocal
