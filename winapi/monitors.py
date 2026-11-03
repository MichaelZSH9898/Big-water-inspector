# -*- coding: utf-8 -*-
"""显示器信息：位置、工作区（不含任务栏）、每显示器 DPI。进程需先声明 Per-Monitor V2，坐标即物理像素。"""

from __future__ import annotations

from ctypes import byref, sizeof
from dataclasses import dataclass

from winapi.win32 import (IS_WINDOWS, MDT_EFFECTIVE_DPI, MONITOR_DEFAULTTOPRIMARY, MONITORENUMPROC,
                          MONITORINFOEXW, UINT, shcore, user32)


@dataclass
class Monitor:
    left: int
    top: int
    right: int
    bottom: int
    work_left: int
    work_top: int
    work_right: int
    work_bottom: int
    dpi: int
    primary: bool
    name: str = ""

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def scale(self) -> float:
        return self.dpi / 96.0


def _info(hmon) -> Monitor | None:
    mi = MONITORINFOEXW()
    mi.cbSize = sizeof(MONITORINFOEXW)
    if not user32.GetMonitorInfoW(hmon, byref(mi)):
        return None
    dpi = 96
    if shcore is not None:
        x, y = UINT(96), UINT(96)
        try:
            if shcore.GetDpiForMonitor(hmon, MDT_EFFECTIVE_DPI, byref(x), byref(y)) == 0:
                dpi = int(x.value)
        except OSError:
            pass
    m, w = mi.rcMonitor, mi.rcWork
    return Monitor(m.left, m.top, m.right, m.bottom, w.left, w.top, w.right, w.bottom, dpi,
                   bool(mi.dwFlags & 1), mi.szDevice)


def all_monitors() -> list[Monitor]:
    if not IS_WINDOWS:
        return []
    out: list[Monitor] = []

    def cb(hmon, hdc, rect, data):
        m = _info(hmon)
        if m:
            out.append(m)
        return True

    proc = MONITORENUMPROC(cb)
    user32.EnumDisplayMonitors(None, None, proc, 0)
    return out


def foreground_monitor() -> Monitor | None:
    """前台窗口所在的显示器；没有前台窗口时用主显示器。"""
    if not IS_WINDOWS:
        return None
    hwnd = user32.GetForegroundWindow()
    hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTOPRIMARY) if hwnd else None
    if not hmon:
        from winapi.win32 import POINT
        hmon = user32.MonitorFromPoint(POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
    return _info(hmon) if hmon else None


def monitor_sizes() -> list[tuple[int, int]]:
    """[(高度像素, DPI)]，去重。渲染缓存按这个出图。"""
    return sorted({(m.height, m.dpi) for m in all_monitors()})
