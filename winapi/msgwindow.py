# -*- coding: utf-8 -*-
"""哨兵的隐藏顶层窗口 + 消息循环 + 定时器。

用“不可见的顶层窗口”而不是 message-only 窗口：WM_POWERBROADCAST、WM_DISPLAYCHANGE、
TaskbarCreated 这些广播只发给顶层窗口。窗口从不显示，带 WS_EX_TOOLWINDOW，不进任务栏。
GetMessageW 阻塞等待：没有消息时线程睡在内核里，CPU 为 0。
"""

from __future__ import annotations

import ctypes
from ctypes import byref, sizeof

from winapi.win32 import (MSG, WM_TIMER, WNDCLASSEXW, WNDPROC, WS_EX_TOOLWINDOW, WS_POPUP, kernel32, user32)


class MessageWindow:
    def __init__(self, class_name: str, title: str, handler, log=None):
        self.handler = handler            # handler(msg, wparam, lparam) -> int | None
        self.log = log
        self._proc = WNDPROC(self._wndproc)
        self.hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = self.hinst
        wc.lpszClassName = class_name
        if not user32.RegisterClassExW(byref(wc)):
            raise OSError(f"RegisterClassExW 失败（{ctypes.get_last_error()}）")
        self.hwnd = user32.CreateWindowExW(WS_EX_TOOLWINDOW, class_name, title, WS_POPUP, 0, 0, 0, 0,
                                           None, None, self.hinst, None)
        if not self.hwnd:
            raise OSError(f"CreateWindowExW 失败（{ctypes.get_last_error()}）")
        self._timers: dict[int, tuple] = {}
        self._next_id = 1000

    # ── 窗口过程 ─────────────────────────────────────────────────────────
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TIMER and wparam in self._timers:
                fn, repeat = self._timers[wparam]
                if not repeat:
                    self.cancel(wparam)
                fn()
                return 0
            r = self.handler(msg, wparam, lparam)
            if r is not None:
                return r
        except Exception:  # noqa: BLE001  窗口过程里的异常绝不能冒出去
            if self.log:
                self.log.app(f"消息 0x{msg:04X} 处理出错", exc=True)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ── 定时器 ───────────────────────────────────────────────────────────
    def set_timer(self, tid: int, ms: int, fn, repeat: bool = False) -> int:
        self._timers[tid] = (fn, repeat)
        user32.SetTimer(self.hwnd, tid, max(10, int(ms)), None)
        return tid

    def call_later(self, seconds: float, fn) -> int:
        self._next_id += 1
        return self.set_timer(self._next_id, int(seconds * 1000), fn, repeat=False)

    def every(self, ms: int, fn) -> int:
        self._next_id += 1
        return self.set_timer(self._next_id, ms, fn, repeat=True)

    def cancel(self, tid: int) -> None:
        if tid in self._timers:
            user32.KillTimer(self.hwnd, tid)
            del self._timers[tid]

    # ── 消息循环 ─────────────────────────────────────────────────────────
    def run(self) -> int:
        msg = MSG()
        while True:
            r = user32.GetMessageW(byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                return int(msg.wParam) if r == 0 else -1
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))

    def destroy(self) -> None:
        for tid in list(self._timers):
            self.cancel(tid)
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
