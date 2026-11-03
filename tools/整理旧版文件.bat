@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
set PYTHONUTF8=1
python tools\move_obsolete.py
timeout /t 4 >nul
