# -*- coding: utf-8 -*-
"""全屏 / 演示 / 勿扰。

全屏或演示（任一即可）：
  1. SHQueryUserNotificationState 返回 QUNS_BUSY(2) / QUNS_RUNNING_D3D_FULL_SCREEN(3) /
     QUNS_PRESENTATION_MODE(4) / QUNS_APP(7)。
  2. 前台窗口铺满它所在的整个显示器（补漏：浏览器 F11 网页、部分播放器）。可在配置里关掉。
勿扰 / 专注：
  1. QUNS_QUIET_TIME(6)；
  2. “专注助手”状态（WNF_SHEL_QUIETHOURS_ACTIVE_PROFILE_CHANGED，非公开接口，读不到就当没开）。
各返回值与系统设置的实际对应关系，用 tools/probe_signals.py 实测，结论写在 DECISIONS.md D-06。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import byref, c_int, c_uint32, c_ulong, c_void_p, sizeof

from winapi.win32 import IS_WINDOWS, MONITOR_DEFAULTTONEAREST, MONITORINFOEXW, RECT, DWORD, ntdll, shell32, user32

from .base import NotifyStatus

QUNS = {1: "not_present", 2: "busy", 3: "d3d_fullscreen", 4: "presentation", 5: "accepts_notifications",
        6: "quiet_time", 7: "app"}
QUNS_LABEL = {2: "有全屏程序在运行", 3: "全屏视频或游戏", 4: "演示模式", 6: "系统勿扰时段", 7: "全屏应用"}
FULLSCREEN_STATES = (2, 3, 4, 7)

# 桌面、任务栏这类窗口铺满屏幕不算全屏程序
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}

# WNF_SHEL_QUIETHOURS_ACTIVE_PROFILE_CHANGED
_WNF_FOCUS = 0x0D83063EA3BF1C75
FOCUS_LABEL = {1: "专注助手：仅优先通知", 2: "专注助手：仅闹钟"}


def query_quns() -> int | None:
    if not IS_WINDOWS:
        return None
    v = c_int(0)
    try:
        if shell32.SHQueryUserNotificationState(byref(v)) != 0:
            return None
    except OSError:
        return None
    return v.value


def focus_assist_profile() -> int | None:
    """0 关、1 仅优先通知、2 仅闹钟；读不到返回 None。"""
    if not IS_WINDOWS or ntdll is None:
        return None
    try:
        fn = ntdll.NtQueryWnfStateData
    except AttributeError:
        return None
    state = ctypes.c_uint64(_WNF_FOCUS)
    stamp = c_ulong(0)
    buf = c_uint32(0)
    size = c_ulong(sizeof(buf))
    try:
        st = fn(byref(state), None, None, byref(stamp), byref(buf), byref(size))
    except OSError:
        return None
    if st != 0:
        return None
    return int(buf.value)


def foreground_covers_monitor(own_pid: int | None = None) -> str | None:
    """前台窗口是否铺满它所在显示器（含任务栏区域）。命中返回窗口类名（不读标题）。"""
    if not IS_WINDOWS:
        return None
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    if cls.value in SHELL_CLASSES:
        return None
    pid = DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, byref(pid))
    if pid.value == (own_pid or os.getpid()):
        return None
    r = RECT()
    if not user32.GetWindowRect(hwnd, byref(r)):
        return None
    mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFOEXW()
    mi.cbSize = sizeof(MONITORINFOEXW)
    if not mon or not user32.GetMonitorInfoW(mon, byref(mi)):
        return None
    m = mi.rcMonitor
    if r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom:
        return cls.value
    return None


class WinNotify:
    def __init__(self, check_foreground: bool = True):
        self.check_foreground = check_foreground

    def query(self) -> NotifyStatus:
        st = NotifyStatus()
        q = query_quns()
        st.raw = q
        if q in FULLSCREEN_STATES:
            st.fullscreen, st.fullscreen_why = True, QUNS_LABEL.get(q, str(q))
        elif self.check_foreground:
            cls = foreground_covers_monitor()
            if cls:
                st.fullscreen, st.fullscreen_why = True, "前台窗口铺满显示器"
        if q == 6:
            st.dnd, st.dnd_why = True, QUNS_LABEL[6]
        else:
            fa = focus_assist_profile()
            if fa in (1, 2):
                st.dnd, st.dnd_why = True, FOCUS_LABEL[fa]
        return st
