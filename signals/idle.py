# -*- coding: utf-8 -*-
"""空闲时长：GetLastInputInfo。

GetLastInputInfo 给的是 32 位毫秒 tick，要和同样 32 位的 GetTickCount 相减并按 2^32 回绕
（约 49.7 天一次）。这个坑每日一题踩过：用 GetTickCount64 却没声明返回类型，开机 25 天后算错。
只读一个系统计数，不挂任何键鼠钩子。
"""

from __future__ import annotations

from ctypes import byref, sizeof

from winapi.win32 import IS_WINDOWS, LASTINPUTINFO, kernel32, user32


def idle_from(now_ms: int, last_ms: int) -> float:
    """两个 32 位毫秒计数之差（处理回绕），单位秒。"""
    return ((now_ms - last_ms) & 0xFFFFFFFF) / 1000.0


class WinIdle:
    def __init__(self):
        self._lii = LASTINPUTINFO()
        self._lii.cbSize = sizeof(LASTINPUTINFO)

    def idle_seconds(self) -> float:
        if not IS_WINDOWS:
            return 0.0
        if not user32.GetLastInputInfo(byref(self._lii)):
            return 0.0
        return idle_from(kernel32.GetTickCount(), self._lii.dwTime)
