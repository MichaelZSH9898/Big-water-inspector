@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist tools\reports mkdir tools\reports
set LOG=tools\reports\selfcheck.log
echo ==== 自检开始 %date% %time% ==== > %LOG%
echo 正在自检，约 2 分钟。闪现验收那一步会自动打字、点按钮，期间请不要动键鼠。
where python >> %LOG% 2>&1
python --version >> %LOG% 2>&1
echo ---- 1 安装依赖 ---- >> %LOG%
python -m pip install -q -r requirements.txt >> %LOG% 2>&1
echo ---- 2 单元测试 ---- >> %LOG%
python -m unittest discover -s tests >> %LOG% 2>&1
echo ---- 3 模拟器 ---- >> %LOG%
python -m sim.run sim\scripts\*.sim --quiet >> %LOG% 2>&1
python -m sim.run sim\scripts\*.sim --quiet --demo >> %LOG% 2>&1
echo ---- 4 信号探针 ---- >> %LOG%
python tools\probe_signals.py >> %LOG% 2>&1
echo ---- 5 闪现验收 ---- >> %LOG%
python tools\accept_overlay.py >> %LOG% 2>&1
echo ---- 6 多屏巡检 ---- >> %LOG%
python tools\accept_overlay.py --tour >> %LOG% 2>&1
echo ---- 7 闪现回落测试（会启动督察员） ---- >> %LOG%
python tools\measure.py --flash >> %LOG% 2>&1
echo ==== 自检结束 %date% %time% ==== >> %LOG%
type %LOG%
echo.
echo 自检完成，结果在 tools\reports\selfcheck.log
pause
