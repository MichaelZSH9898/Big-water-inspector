# -*- coding: utf-8 -*-
"""最近一段时间的行为记录：每分钟是否有输入、前台切换、窗口关闭。只在内存里。

前台切换只记“类别”，不记进程名和标题。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

PRODUCTIVITY = "productivity"
COMMUNICATION = "communication"
BROWSER = "browser"
ENTERTAINMENT = "entertainment"
MEETING = "meeting"
OTHER = "other"

LEAVE_PRODUCTIVITY_TO = (COMMUNICATION, BROWSER, ENTERTAINMENT)


@dataclass
class Switch:
    t: float
    frm: str | None
    to: str


class History:
    def __init__(self, P, maxlen: int = 128):
        self.P = P
        self.buckets: deque[tuple[float, bool]] = deque(maxlen=maxlen)   # (start, had_input)
        self.switches: deque[Switch] = deque(maxlen=maxlen)
        self.closes: deque[float] = deque(maxlen=32)
        self.category: str | None = None

    # ── 写入 ─────────────────────────────────────────────────────────────
    def add_bucket(self, start: float, had_input: bool) -> None:
        self.buckets.append((start, had_input))

    def record_foreground(self, t: float, category: str) -> Switch | None:
        """记录一次前台切换。1.5 秒内的连续切换（如 Alt+Tab 经过的中间窗口）合并为一次。"""
        prev = self.category
        if self.switches and t - self.switches[-1].t < self.P.switch_debounce_s:
            last = self.switches[-1]
            last.to = category
            last.t = t
            self.category = category
            if last.frm == last.to:          # 绕了一圈回到原类别：不算切换
                self.switches.pop()
                return None
            return last
        self.category = category
        if prev == category:
            # 同类别内换窗口也算一次前台切换（用于计数），但不是“类别切换”
            sw = Switch(t, prev, category)
            self.switches.append(sw)
            return sw
        sw = Switch(t, prev, category)
        self.switches.append(sw)
        return sw

    def record_close(self, t: float) -> None:
        self.closes.append(t)

    def clear_recent(self) -> None:
        """锁屏回来之后，锁屏前的切换不再影响状态。"""
        self.switches.clear()
        self.closes.clear()

    # ── 查询 ─────────────────────────────────────────────────────────────
    def input_minutes(self, n: int, current_has_input: bool) -> int:
        """最近 n 分钟里有输入的分钟数（当前这一分钟 + 之前 n-1 个已结束的分钟）。"""
        total = 1 if current_has_input else 0
        if n <= 1:
            return total
        recent = list(self.buckets)[-(n - 1):]
        return total + sum(1 for _, had in recent if had)

    def switch_count(self, now: float, window_s: float) -> int:
        return sum(1 for s in self.switches if now - s.t <= window_s)

    def last_category_switch(self, now: float, window_s: float) -> Switch | None:
        """最近 window_s 秒内“从生产力切到沟通/浏览器/娱乐”的那次切换。"""
        for s in reversed(self.switches):
            if now - s.t > window_s:
                return None
            if s.frm == PRODUCTIVITY and s.to in LEAVE_PRODUCTIVITY_TO:
                return s
        return None

    def recent_close(self, now: float, window_s: float) -> float | None:
        for t in reversed(self.closes):
            if 0 <= now - t <= window_s:
                return t
        return None
