# -*- coding: utf-8 -*-
"""锁屏 / 解锁、睡眠 / 唤醒：把窗口消息翻译成内核事件。

· WTSRegisterSessionNotification → WM_WTSSESSION_CHANGE（WTS_SESSION_LOCK / UNLOCK）
· WM_POWERBROADCAST（PBT_APMSUSPEND / PBT_APMRESUMESUSPEND / PBT_APMRESUMEAUTOMATIC），睡眠视同锁屏
两者都只发给顶层窗口，所以哨兵用的是一个不可见的顶层窗口（不是 message-only 窗口）。
"""

from __future__ import annotations

from winapi.win32 import (IS_WINDOWS, NOTIFY_FOR_THIS_SESSION, PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND,
                          PBT_APMSUSPEND, WM_POWERBROADCAST, WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK,
                          WTS_SESSION_UNLOCK, wtsapi32)

LOCK, UNLOCK, SUSPEND, RESUME = "lock", "unlock", "suspend", "resume"


def register(hwnd) -> bool:
    if not IS_WINDOWS or wtsapi32 is None:
        return False
    return bool(wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION))


def unregister(hwnd) -> None:
    if IS_WINDOWS and wtsapi32 is not None:
        wtsapi32.WTSUnRegisterSessionNotification(hwnd)


def translate(msg: int, wparam: int) -> str | None:
    if msg == WM_WTSSESSION_CHANGE:
        if wparam == WTS_SESSION_LOCK:
            return LOCK
        if wparam == WTS_SESSION_UNLOCK:
            return UNLOCK
    elif msg == WM_POWERBROADCAST:
        if wparam == PBT_APMSUSPEND:
            return SUSPEND
        if wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
            return RESUME
    return None
