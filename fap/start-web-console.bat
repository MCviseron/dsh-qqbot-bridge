@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 启动浏览器控制台：http://127.0.0.1:39080/
start "" http://127.0.0.1:39080/
python -m framework.cli --gui --web-console
if errorlevel 1 pause
