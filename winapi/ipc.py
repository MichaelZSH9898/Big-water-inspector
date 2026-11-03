# -*- coding: utf-8 -*-
"""设置进程 → 哨兵 的通知：找到哨兵的隐藏窗口，PostMessage 一条注册消息。零轮询、零依赖。"""

from __future__ import annotations

from winapi.win32 import IS_WINDOWS, user32

SENTINEL_CLASS = "WaterInspector.Sentinel"
RELOAD_MSG_NAME = "WaterInspector.Reload"
SHOW_DEMO_MSG_NAME = "WaterInspector.Demo"


def reload_message_id() -> int:
    return user32.RegisterWindowMessageW(RELOAD_MSG_NAME) if IS_WINDOWS else 0


def demo_message_id() -> int:
    return user32.RegisterWindowMessageW(SHOW_DEMO_MSG_NAME) if IS_WINDOWS else 0


def sentinel_hwnd():
    return user32.FindWindowW(SENTINEL_CLASS, None) if IS_WINDOWS else None


def notify_reload() -> bool:
    """通知哨兵重新加载配置和角色包。哨兵没在运行时返回 False。"""
    hwnd = sentinel_hwnd()
    if not hwnd:
        return False
    return bool(user32.PostMessageW(hwnd, reload_message_id(), 0, 0))


def request_demo() -> bool:
    hwnd = sentinel_hwnd()
    if not hwnd:
        return False
    return bool(user32.PostMessageW(hwnd, demo_message_id(), 0, 0))
