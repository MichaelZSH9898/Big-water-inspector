# -*- coding: utf-8 -*-
"""重启哨兵：通知正在运行的哨兵体面退出（和托盘“退出”一样写好状态），等它退出后再启动新的。
更新了程序文件（比如换了新立绘、新代码）之后用：双击根目录的 `重启督察员.bat`。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from ctypes import sizeof

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from winapi import autostart, ipc  # noqa: E402
from winapi.tray import CALLBACK_MSG  # noqa: E402
from winapi.win32 import IS_WINDOWS, NIM_DELETE, NOTIFYICONDATAW, WM_CLOSE, shell32, user32  # noqa: E402


def stop(timeout: float = 10.0) -> bool:
    hwnd = ipc.sentinel_hwnd()
    if not hwnd:
        print("督察员没在运行。")
        return True
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    t0 = time.time()
    while ipc.sentinel_hwnd() and time.time() - t0 < timeout:
        time.sleep(0.2)
    if ipc.sentinel_hwnd():
        print("旧的督察员没有在 10 秒内退出，请在托盘里右键 → 退出，再双击 启动督察员.bat。")
        return False
    nid = NOTIFYICONDATAW()                      # 旧版本收到 WM_CLOSE 不会自己删托盘图标，这里顺手删掉
    nid.cbSize = sizeof(NOTIFYICONDATAW)
    nid.hWnd = hwnd
    nid.uID = 1
    nid.uCallbackMessage = CALLBACK_MSG
    shell32.Shell_NotifyIconW(NIM_DELETE, nid)
    time.sleep(1.0)                              # 等进程完全退出、释放单实例互斥量
    print("旧的督察员已退出。")
    return True


def start() -> None:
    flags = 0x00000008 | 0x00000200              # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(autostart.launch_args(os.path.join(ROOT, "main.py")), cwd=ROOT, creationflags=flags,
                     close_fds=True)
    for _ in range(50):
        if ipc.sentinel_hwnd():
            print("新的督察员已启动（托盘里的粉色小水杯）。")
            return
        time.sleep(0.2)
    print("已尝试启动，但 10 秒内没看到它的窗口；请看 logs/app.log。")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if not IS_WINDOWS:
        print("只能在 Windows 上运行。")
        return 2
    if not stop():
        return 1
    start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
