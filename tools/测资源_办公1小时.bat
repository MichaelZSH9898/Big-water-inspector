@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo 资源实测：正常办公 1 小时。这期间照常用电脑即可，窗口别关。
python tools\measure.py --label office --minutes 60
pause
