@echo off
chcp 65001 >nul
echo 停止所有 fap 进程…
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'framework.cli' } | ForEach-Object { taskkill /PID $_.ProcessId /T /F }"
echo 完成
pause
