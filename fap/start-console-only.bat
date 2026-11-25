@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 只启动控制台窗口（不连 QQ，用于调界面/插件）…
python -m framework.cli --gui --no-connect
if errorlevel 1 pause
