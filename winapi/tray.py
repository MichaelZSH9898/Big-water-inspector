# -*- coding: utf-8 -*-
"""托盘图标（Shell_NotifyIconW，原生实现，不用 pystray——它会把 Pillow 拉进常驻进程）。

图标：粉色小水杯，5 档水位（assets/tray/tea_0.ico 满杯 … tea_4.ico 见底），饮水账越高水越少，
只在档位变化时换图。右键菜单由调用方给出条目；“今日统计”是一个只读子菜单。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import byref, sizeof

from winapi.win32 import (IMAGE_ICON, LR_LOADFROMFILE, MF_CHECKED, MF_GRAYED, MF_POPUP, MF_SEPARATOR, MF_STRING,
                          NIF_ICON, NIF_MESSAGE, NIF_SHOWTIP, NIF_TIP, NIM_ADD, NIM_DELETE, NIM_MODIFY,
                          NIM_SETVERSION, NIN_KEYSELECT, NIN_SELECT, NOTIFYICON_VERSION_4, NOTIFYICONDATAW, POINT,
                          SM_CXSMICON, SM_CYSMICON, TPM_BOTTOMALIGN, TPM_NONOTIFY, TPM_RETURNCMD, TPM_RIGHTBUTTON,
                          WM_APP, WM_CONTEXTMENU, WM_NULL, shell32, user32)

CALLBACK_MSG = WM_APP + 1
LEVELS = 5


def water_level(water: float, threshold: float) -> int:
    """饮水账 → 0（满杯）… 4（见底）。"""
    if threshold <= 0:
        return 0
    r = water / threshold
    if r >= 1.0:
        return 4
    return min(3, int(r * 4))


class Tray:
    def __init__(self, hwnd, icon_dir: str, tip: str, log=None):
        self.hwnd = hwnd
        self.log = log
        cx, cy = user32.GetSystemMetrics(SM_CXSMICON), user32.GetSystemMetrics(SM_CYSMICON)
        self.icons = []
        for i in range(LEVELS):
            path = os.path.join(icon_dir, f"tea_{i}.ico")
            h = user32.LoadImageW(None, path, IMAGE_ICON, cx, cy, LR_LOADFROMFILE)
            self.icons.append(h)
        self.level = 0
        self.tip = tip
        self.added = False

    def _nid(self, flags: int) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = CALLBACK_MSG
        nid.hIcon = self.icons[self.level] if self.icons else None
        nid.szTip = self.tip[:127]
        return nid

    def add(self) -> bool:
        nid = self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP)
        ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, byref(nid)))
        nid.uVersion = NOTIFYICON_VERSION_4
        shell32.Shell_NotifyIconW(NIM_SETVERSION, byref(nid))
        self.added = ok
        return ok

    def remove(self) -> None:
        if self.added:
            nid = self._nid(0)
            shell32.Shell_NotifyIconW(NIM_DELETE, byref(nid))
            self.added = False

    def set_state(self, level: int, tip: str) -> None:
        level = max(0, min(LEVELS - 1, level))
        if level == self.level and tip == self.tip:
            return
        flags = 0
        if level != self.level:
            self.level = level
            flags |= NIF_ICON
        if tip != self.tip:
            self.tip = tip
            flags |= NIF_TIP | NIF_SHOWTIP
        nid = self._nid(flags)
        shell32.Shell_NotifyIconW(NIM_MODIFY, byref(nid))

    def is_menu_request(self, lparam: int) -> bool:
        """NOTIFYICON_VERSION_4：右键 = WM_CONTEXTMENU，左键单击 = NIN_SELECT，键盘 = NIN_KEYSELECT。"""
        ev = lparam & 0xFFFF
        return ev in (WM_CONTEXTMENU, NIN_SELECT, NIN_KEYSELECT)

    def popup(self, items) -> int:
        """items: [(id, 文本, {"grayed":…, "checked":…})] / ("-",) 分隔线 / ("sub", 文本, items)。返回选中的 id。"""
        menus = []

        def build(entries):
            hm = user32.CreatePopupMenu()
            menus.append(hm)
            for it in entries:
                if it[0] == "-":
                    user32.AppendMenuW(hm, MF_SEPARATOR, 0, None)
                elif it[0] == "sub":
                    sub = build(it[2])
                    user32.AppendMenuW(hm, MF_POPUP | MF_STRING, sub, it[1])
                else:
                    iid, text, opt = it[0], it[1], (it[2] if len(it) > 2 else {})
                    fl = MF_STRING | (MF_GRAYED if opt.get("grayed") else 0) | (MF_CHECKED if opt.get("checked") else 0)
                    user32.AppendMenuW(hm, fl, iid, text)
            return hm

        root = build(items)
        pt = POINT()
        user32.GetCursorPos(byref(pt))
        # 托盘菜单的标准做法：先把隐藏窗口设为前台，菜单才会在点别处时自动收起（只在用户主动点托盘时）
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(root, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY | TPM_BOTTOMALIGN,
                                    pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(root)       # 会连带销毁子菜单
        return int(cmd)

    def destroy(self) -> None:
        self.remove()
        for h in self.icons:
            if h:
                user32.DestroyIcon(h)
        self.icons = []
