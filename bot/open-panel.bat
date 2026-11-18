@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "TOKEN="
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
  if /i "%%A"=="BRIDGE_TOKEN" set "TOKEN=%%B"
)
if "%TOKEN%"=="" (
  echo [FAIL] BRIDGE_TOKEN not found in .env
  pause
  exit /b 1
)
start "" "http://127.0.0.1:39062/?t=%TOKEN%"
