@echo off
setlocal
rem 静默启动（pythonw，无黑框）+ 守护重启。
rem 注意：不要用 DSH 的后台任务启动它，那会阻塞 DSH 自己的重启。

rem 与点歌机器人共用同一个 conda 环境（SDK 以 editable 方式装在该环境里，只读使用）
call "D:\anaconda3\Scripts\activate.bat" "D:\anaconda3" >nul 2>&1
call conda activate ChatClone-BotPy >nul 2>&1
if errorlevel 1 (
  echo [FAIL] conda env ChatClone-BotPy not found
  pause
  exit /b 1
)

cd /d "%~dp0"
if exist "pythonw.exe" (
  start "" pythonw.exe -u main.py --supervise
) else (
  start "" python.exe -u main.py --supervise
)
echo [ok] started in background (hidden). Settings: DSH sidebar -^> QQ bot
timeout /t 2 >nul
exit /b 0
