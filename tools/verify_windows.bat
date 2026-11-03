@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
echo ==== 1/5 单元测试 ====
python -m unittest discover -s tests
echo.
echo ==== 2/5 模拟器回放（正常 + 演示模式）====
python -m sim.run sim\scripts\*.sim --quiet
python -m sim.run sim\scripts\*.sim --quiet --demo
echo.
echo ==== 3/5 信号探针（30 秒，期间可以开关勿扰/全屏/会议试试）====
python tools\probe_signals.py --watch 30
echo.
echo ==== 4/5 闪现验收：打字不丢字 + 点击穿透（约 15 秒，请勿操作键鼠）====
python tools\accept_overlay.py
echo.
echo ==== 5/5 多显示器/缩放巡检 ====
python tools\accept_overlay.py --tour
echo.
echo 全部完成。报告在 tools\reports\ 里。
pause
