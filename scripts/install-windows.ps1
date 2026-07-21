# Установка панели KZ-SUB в Premiere Pro (Windows), режим разработки.
#
# Включает debug-режим CEP (неподписанные расширения) и линкует папку plugin\
# в директорию расширений Adobe.
#
# Запуск (PowerShell):  powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
#
# Символьная ссылка (mklink /D) требует прав администратора ИЛИ включённого
# «Режима разработчика» Windows. Если ссылку создать не удалось — скрипт
# копирует папку (тогда правки нужно переустанавливать этим же скриптом).

$ErrorActionPreference = "Stop"

$pluginDir = (Resolve-Path (Join-Path $PSScriptRoot "..\plugin")).Path
$extDir = Join-Path $env:APPDATA "Adobe\CEP\extensions"
$link = Join-Path $extDir "kz.kzsub.panel"

Write-Host "==> Включаю debug-режим CEP (CSXS 9-13)..."
foreach ($v in 9,10,11,12,13) {
  $key = "HKCU:\Software\Adobe\CSXS.$v"
  New-Item -Path $key -Force | Out-Null
  New-ItemProperty -Path $key -Name "PlayerDebugMode" -Value "1" -PropertyType String -Force | Out-Null
}

Write-Host "==> Устанавливаю панель в $extDir..."
New-Item -ItemType Directory -Force -Path $extDir | Out-Null
if (Test-Path $link) { Remove-Item $link -Recurse -Force }

$linked = $false
try {
  cmd /c mklink /D "`"$link`"" "`"$pluginDir`"" | Out-Null
  if (Test-Path $link) { $linked = $true }
} catch { }

if (-not $linked) {
  Write-Host "   Симлинк недоступен — копирую папку (нужен запуск от админа или Режим разработчика для симлинка)."
  Copy-Item -Recurse -Force $pluginDir $link
}

Write-Host ""
Write-Host "Готово: $link"
Write-Host ""
Write-Host "Дальше:"
Write-Host "  1. Полностью закройте и снова откройте Premiere Pro."
Write-Host "  2. Window -> Extensions -> 'KZ-SUB - qazaqsha subtitr'."
Write-Host "  3. Запустите бэкенд: scripts\run-backend.bat"
Write-Host ""
Write-Host "Удалить установку: Remove-Item -Recurse -Force `"$link`""
