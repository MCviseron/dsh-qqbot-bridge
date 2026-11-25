@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 启动 fap（无界面，Ctrl+C 停止）…
python -m framework.cli --no-gui
if errorlevel 1 pause
