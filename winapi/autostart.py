# -*- coding: utf-8 -*-
"""开机自启：写 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run（当前用户，不需要管理员）。"""

from __future__ import annotations

import os
import sys
import subprocess

try:
    import winreg
except ImportError:  # 非 Windows
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "WaterInspector"


def pythonw() -> str:
    exe = sys.executable
    if getattr(sys, "frozen", False):
        return exe
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def command(main_py: str) -> str:
    return subprocess.list2cmdline(launch_args(main_py))


def launch_args(main_py: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [pythonw(), os.path.abspath(main_py)]


def is_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            v, _ = winreg.QueryValueEx(k, VALUE)
            return bool(v)
    except OSError:
        return False


def set_enabled(on: bool, main_py: str) -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command(main_py))
            else:
                try:
                    winreg.DeleteValue(k, VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
