@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 演示模式：所有时间阈值 x1/60（分钟变秒），日志打印在本窗口。关闭本窗口即退出。
echo 如果督察员已经在后台运行，请先在托盘里退出它。
python main.py --demo --console
pause
