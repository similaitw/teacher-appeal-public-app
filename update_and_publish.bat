@echo off
rem Double-click to update public data and publish. Options: --skip-crawl --no-push --yes
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
"%PY%" scripts\update_and_publish.py %*
echo.
pause
