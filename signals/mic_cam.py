# -*- coding: utf-8 -*-
"""麦克风 / 摄像头占用（会议屏蔽）。

读 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\{microphone,webcam}
下每个应用的 LastUsedTimeStart / LastUsedTimeStop（FILETIME）。NonPackaged 子键下是普通桌面程序。
  · 任一项 Start > 0 且 Stop == 0 → 正在使用；
  · 所有项里最大的 Stop → 最近一次停止使用的时刻，用来实现“会议结束 2 分钟后才恢复”，无需轮询。
  · Start 早于 meeting_stale_hours（默认 12 小时）却一直没 Stop 的，视为注册表残留，忽略。
思路参考了每日一题 ui/quiet.py 的 capture_in_use()（复制改写，不 import，保持两个程序松耦合）。
只读注册表元数据，不碰任何音视频内容。
"""

from __future__ import annotations

import time

from .base import MicCamStatus

try:
    import winreg
except ImportError:  # 非 Windows
    winreg = None

ROOT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
CAPS = {"microphone": "麦克风", "webcam": "摄像头"}
_EPOCH_AS_FILETIME = 116444736000000000


def filetime_to_epoch(ft: int) -> float:
    return (ft - _EPOCH_AS_FILETIME) / 10_000_000


def _subkeys(key):
    i = 0
    while True:
        try:
            yield winreg.EnumKey(key, i)
        except OSError:
            return
        i += 1


def _times(key):
    try:
        start, _ = winreg.QueryValueEx(key, "LastUsedTimeStart")
        stop, _ = winreg.QueryValueEx(key, "LastUsedTimeStop")
        return int(start), int(stop)
    except (OSError, ValueError, TypeError):
        return None


def scan(now: float | None = None, stale_s: float = 12 * 3600):
    """返回 (in_use_list, last_stop_epoch, stale_list)。in_use_list 里是 (设备, 程序名)。"""
    now = time.time() if now is None else now
    in_use, stale = [], []
    last_stop = None
    if winreg is None:
        return in_use, last_stop, stale

    def visit(k, cap, name):
        nonlocal last_stop
        t = _times(k)
        if not t:
            return
        start, stop = t
        if stop:
            e = filetime_to_epoch(stop)
            if last_stop is None or e > last_stop:
                last_stop = e
        if start and stop == 0:
            if now - filetime_to_epoch(start) > stale_s:
                stale.append((cap, name))
            else:
                in_use.append((cap, name))

    for cap in CAPS:
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{ROOT}\\{cap}")
        except OSError:
            continue
        with root:
            for name in list(_subkeys(root)):
                try:
                    with winreg.OpenKey(root, name) as k:
                        if name == "NonPackaged":
                            for app in list(_subkeys(k)):
                                with winreg.OpenKey(k, app) as ak:
                                    visit(ak, cap, app.replace("#", "\\").rsplit("\\", 1)[-1])
                        else:
                            visit(k, cap, name.split("_")[0])
                except OSError:
                    continue
    return in_use, last_stop, stale


class WinMicCam:
    def __init__(self, stale_s: float = 12 * 3600, log=None):
        self.stale_s = stale_s
        self.log = log
        self._reported_stale: set = set()

    def status(self, now: float) -> MicCamStatus:
        in_use, last_stop, stale = scan(now, self.stale_s)
        for item in stale:
            if item not in self._reported_stale and self.log:
                self.log.app(f"忽略疑似残留的{CAPS.get(item[0], item[0])}占用记录")
            self._reported_stale.add(item)
        if in_use:
            cap, _ = in_use[0]
            return MicCamStatus(True, last_stop, f"{CAPS.get(cap, cap)}使用中")   # 不记程序名
        return MicCamStatus(False, last_stop, "")
