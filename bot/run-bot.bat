@echo off
setlocal
title DSH-QQ-Bot (supervised)

rem 与点歌机器人共用同一个 conda 环境（SDK 以 editable 方式装在该环境里，只读使用）
call "D:\anaconda3\Scripts\activate.bat" "D:\anaconda3" >nul 2>&1
call conda activate ChatClone-BotPy >nul 2>&1
if errorlevel 1 (
  echo [FAIL] conda env ChatClone-BotPy not found
  pause
  exit /b 1
)

cd /d "%~dp0"
echo [supervised] crash -^> auto restart; Ctrl+C or stop-bot.bat -^> stays stopped
python -u main.py --supervise
pause
