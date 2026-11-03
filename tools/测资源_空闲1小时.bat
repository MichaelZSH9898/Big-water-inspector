@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo 资源实测：空闲 1 小时。双击后离开电脑（锁屏或不锁都行），窗口别关。
python tools\measure.py --label idle --minutes 60
pause
