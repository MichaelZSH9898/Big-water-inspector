# -*- coding: utf-8 -*-
"""前台窗口切换：SetWinEventHook(EVENT_SYSTEM_FOREGROUND)。

· 回调里取进程名（OpenProcess + QueryFullProcessImageNameW）和标题（InternalGetWindowText，
  只读缓存、不给目标窗口发消息，目标程序卡死也不会连累我们），映射成类别后立即丢弃标题。
· 只挂这一个低频事件；绝不挂 WH_KEYBOARD_LL / WH_MOUSE_LL。
· “收尾动作”：切走 0.7 秒后看上一个前台窗口还在不在（IsWindow），不在了就是被关闭/应用退出。
  （不挂 EVENT_OBJECT_DESTROY：那个事件全系统每秒成百上千次，Python 回调扛不住。）
· 浏览器里切标签页不会触发前台事件：前台是浏览器时，哨兵每次空闲采样顺便 refresh() 看一眼标题。
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import byref

from winapi.win32 import (DWORD, EVENT_SYSTEM_FOREGROUND, IS_WINDOWS, PROCESS_QUERY_LIMITED_INFORMATION,
                          WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS, WINEVENTPROC, kernel32, user32)

from .categories import CategoryTable

# 系统外壳的过渡窗口：Alt+Tab 切换器、任务栏、开始菜单、锁屏、通知中心等，不算前台切换
IGNORE_CLASSES = {
    "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "MultitaskingViewFrame", "XamlExplorerHostIslandWindow",
    "ForegroundStaging", "TaskSwitcherWnd", "TaskListThumbnailWnd", "NotifyIconOverflowWindow",
    "Windows.UI.Core.CoreWindow", "TopLevelWindowForOverflowXamlIsland", "#32768", "LockScreenBackstopFrame",
    "Progman", "WorkerW", "WaterInspector.Sentinel", "WaterInspector.Flash",
    "zoom_acc_notify_wnd",          # Zoom 的无障碍通知辅助窗口（实测会抢到前台，不是真正的切换）
}
IGNORE_PROCS = {"lockapp.exe", "searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe",
                "shellexperiencehost.exe", "textinputhost.exe"}


def process_name(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, byref(n)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def window_class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_title(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.InternalGetWindowText(hwnd, buf, 512)
    return buf.value


class WinForeground:
    def __init__(self, raw_categories: dict, on_change, on_close, call_later, log=None):
        self.table = CategoryTable(raw_categories)
        self.on_change = on_change          # on_change(category)
        self.on_close = on_close            # on_close(t_closed)
        self.call_later = call_later        # call_later(seconds, fn)
        self.log = log
        self.own_pid = os.getpid()
        self.hwnd = None
        self.category = None
        self._is_browser = False
        self._pid_cache: dict[int, str] = {}
        self._proc = WINEVENTPROC(self._callback)     # 必须持有引用，否则会被回收
        self._hook = None

    def start(self) -> bool:
        if not IS_WINDOWS:
            return False
        self._hook = user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, self._proc,
                                            0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            cat = self._classify(hwnd)
            if cat:
                self.hwnd, self.category = hwnd, cat
        return bool(self._hook)

    def stop(self) -> None:
        if self._hook:
            user32.UnhookWinEvent(self._hook)
            self._hook = None

    def reload(self, raw_categories: dict) -> None:
        self.table = CategoryTable(raw_categories)

    # ── 分类 ─────────────────────────────────────────────────────────────
    def _proc_name(self, hwnd) -> tuple[int, str]:
        pid = DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, byref(pid))
        p = pid.value
        name = self._pid_cache.get(p)
        if name is None:
            if len(self._pid_cache) > 256:
                self._pid_cache.clear()
            name = process_name(p)
            self._pid_cache[p] = name
        return p, name

    def _classify(self, hwnd) -> str | None:
        """返回类别；系统过渡窗口、自己的窗口返回 None。"""
        if not hwnd or not user32.IsWindow(hwnd):
            return None
        if window_class(hwnd) in IGNORE_CLASSES:
            return None
        pid, name = self._proc_name(hwnd)
        if pid == self.own_pid or name in IGNORE_PROCS:
            return None
        self._is_browser = self.table.is_browser(name)
        title = window_title(hwnd) if self._is_browser else None
        cat = self.table.classify(name, title)
        del title                                       # 标题用完即弃
        return cat

    # ── 事件 ─────────────────────────────────────────────────────────────
    def _callback(self, hook, event, hwnd, id_object, id_child, thread, ms):
        try:
            if id_object != 0 or not hwnd or hwnd == self.hwnd:
                return
            cat = self._classify(hwnd)
            if cat is None:
                return
            prev, t_switch = self.hwnd, time.time()
            self.hwnd, self.category = hwnd, cat
            if prev:
                self.call_later(0.7, lambda: self._check_closed(prev, t_switch))
            self.on_change(cat)
        except Exception:  # noqa: BLE001  回调里的异常不能往外抛
            if self.log:
                self.log.app("前台切换回调出错", exc=True)

    def _check_closed(self, prev, t_switch) -> None:
        if not user32.IsWindow(prev):
            self.on_close(t_switch)

    # ── 供哨兵调用 ───────────────────────────────────────────────────────
    def current_category(self) -> str | None:
        return self.category

    def refresh(self) -> str | None:
        """前台是浏览器时重新看一次标题（换标签页不触发前台事件）。类别变了返回新类别。"""
        if not self._is_browser or not self.hwnd or not IS_WINDOWS:
            return None
        if user32.GetForegroundWindow() != self.hwnd:
            return None
        cat = self._classify(self.hwnd)
        if cat and cat != self.category:
            self.category = cat
            return cat
        return None
