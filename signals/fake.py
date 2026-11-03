# -*- coding: utf-8 -*-
"""假数据信号源：一个可脚本化的“世界”，同时实现全部信号接口。测试和模拟器用。"""

from __future__ import annotations

from .base import MicCamStatus, NotifyStatus, Signals


class FakeWorld:
    def __init__(self, clock, input_lag: float = 0.5):
        self.clock = clock
        self.input_lag = input_lag     # 停止打字时，最后一次按键在“现在”之前多少秒
        self.typing = False            # True：此刻在持续输入（last_input = now）
        self.last_input: float | None = None
        self.audio = False
        self.fullscreen = False
        self.dnd = False
        self.mic = False
        self.mic_last_stop: float | None = None
        self.category: str | None = None
        self._pending_refresh: str | None = None
        self.calls = {"idle": 0, "notify": 0, "miccam": 0, "audio": 0}

    # ── 操作世界 ─────────────────────────────────────────────────────────
    def start_typing(self):
        self.typing = True
        self.last_input = self.clock.now()

    def stop_typing(self):
        if self.typing:
            self.last_input = self.clock.now() - self.input_lag
        self.typing = False

    def input_once(self):
        self.last_input = self.clock.now()

    def set_mic(self, on: bool):
        if self.mic and not on:
            self.mic_last_stop = self.clock.now()
        self.mic = on

    def set_tab_category(self, cat: str):
        """浏览器内切换标签页（不触发前台切换事件，等哨兵下次 refresh 时发现）。"""
        if cat != self.category:
            self._pending_refresh = cat
            self.category = cat

    # ── 信号接口 ─────────────────────────────────────────────────────────
    def idle_seconds(self) -> float:
        self.calls["idle"] += 1
        now = self.clock.now()
        if self.typing:
            return 0.0
        if self.last_input is None:
            return 10 ** 7
        return max(0.0, now - self.last_input)

    def query(self) -> NotifyStatus:
        self.calls["notify"] += 1
        return NotifyStatus(fullscreen=self.fullscreen, fullscreen_why="全屏" if self.fullscreen else "",
                            dnd=self.dnd, dnd_why="勿扰" if self.dnd else "")

    def status(self, now: float) -> MicCamStatus:
        self.calls["miccam"] += 1
        return MicCamStatus(in_use=self.mic, last_stop_t=self.mic_last_stop,
                            why="麦克风使用中" if self.mic else "")

    def is_playing(self) -> bool:
        self.calls["audio"] += 1
        return self.audio

    def current_category(self):
        return self.category

    def refresh(self):
        c, self._pending_refresh = self._pending_refresh, None
        return c

    def signals(self) -> Signals:
        return Signals(idle=self, notify=self, miccam=self, audio=self, foreground=self)
