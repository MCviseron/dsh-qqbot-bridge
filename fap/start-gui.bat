@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 启动 fap 控制台（原生窗口）…
python -m framework.cli --gui
if errorlevel 1 pause
