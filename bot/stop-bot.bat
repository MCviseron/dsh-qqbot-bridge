@echo off
setlocal
title DSH-QQ-Bot STOP

call "D:\anaconda3\Scripts\activate.bat" "D:\anaconda3" >nul 2>&1
call conda activate ChatClone-BotPy >nul 2>&1

cd /d "%~dp0"
echo Stopping the supervised bot (auto-restart will NOT bring it back)...
python -u main.py --stop
timeout /t 2 >nul
