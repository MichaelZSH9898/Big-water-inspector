# -*- coding: utf-8 -*-
"""可注入时钟。

内核里所有“现在几点”都通过 Clock 取得，测试和模拟器换成 FakeClock 就能脚本化地控制时间。
时间一律用 epoch 秒（float）；本地日期按 day_start（默认 04:00）换日。
"""

from __future__ import annotations

import datetime as _dt
import time as _time


class RealClock:
    """真实时钟。"""

    def now(self) -> float:
        return _time.time()


class FakeClock:
    """测试 / 模拟器用的时钟，时间只会被显式推进。"""

    def __init__(self, t: float = 0.0):
        self.t = float(t)

    def now(self) -> float:
        return self.t

    def set(self, t: float) -> None:
        self.t = float(t)

    def advance(self, seconds: float) -> None:
        self.t += float(seconds)


def local_dt(t: float) -> _dt.datetime:
    return _dt.datetime.fromtimestamp(t)


def parse_hhmm(s: str) -> float:
    """'17:30' → 1050（当天第几分钟）；也接受 '17:30:20'（带秒，返回小数分钟）。"""
    parts = s.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"时间格式不对：{s!r}")
    h, m = int(parts[0]), int(parts[1])
    sec = float(parts[2]) if len(parts) == 3 else 0.0
    v = h * 60 + m + sec / 60.0
    if not 0 <= v < 24 * 60 or not 0 <= m < 60 or not 0 <= sec < 60:
        raise ValueError(f"时间格式不对：{s!r}")
    return int(v) if v == int(v) else v


def day_key(t: float, day_start_min: int) -> str:
    """t 属于哪一“天”（04:00 换日：凌晨 2 点仍算前一天）。"""
    d = local_dt(t) - _dt.timedelta(minutes=day_start_min)
    return d.date().isoformat()


def minute_of_day(t: float) -> float:
    d = local_dt(t)
    return d.hour * 60 + d.minute + d.second / 60.0


def minutes_since_day_start(t: float, day_start_min: int) -> float:
    """距本“天”开始（04:00）过了多少分钟，范围 [0, 1440)。"""
    return (minute_of_day(t) - day_start_min) % (24 * 60)


def next_day_start(t: float, day_start_min: int) -> float:
    """t 之后下一次换日时刻的 epoch 秒。"""
    d = local_dt(t)
    m = int(day_start_min)
    start = d.replace(hour=m // 60, minute=m % 60, second=0, microsecond=0)
    if start <= d:
        start += _dt.timedelta(days=1)
    return start.timestamp()


def in_window(minute: float, start: int, end: int) -> bool:
    """minute 是否落在 [start, end) 内，支持跨午夜（如 22:00–08:00）。"""
    if start == end:
        return False
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def iso(t: float) -> str:
    return local_dt(t).astimezone().isoformat(timespec="seconds")
