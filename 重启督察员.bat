@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在重启大水理论督察员……
python tools\restart_sentinel.py
timeout /t 4 >nul
