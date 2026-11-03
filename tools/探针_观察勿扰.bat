@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo 信号探针：接下来 90 秒每 2 秒读一次。
echo 请在这期间依次：打开/关闭“勿扰”（Win+N 通知中心里），把一个视频全屏再退出，开一个会议或语音再挂断。
python tools\probe_signals.py --watch 90
pause
