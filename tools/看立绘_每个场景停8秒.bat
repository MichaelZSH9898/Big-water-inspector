@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
set PYTHONUTF8=1
echo 每块显示器上依次出现 A 解锁训话、B 侧边探头、C 加班关怀，每个停 8 秒。
python tools\accept_overlay.py --tour --hold 8
timeout /t 3 >nul
