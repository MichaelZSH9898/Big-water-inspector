# -*- coding: utf-8 -*-
"""有效使用时长（第 6.1 节），按“分钟桶”计。

一分钟算“有效”，当且仅当满足任一条件：
  1. 这一分钟内有键鼠输入；
  2. 没有输入，但有音频在播放，并且（处于全屏状态，或距上次输入不到 20 分钟）。
锁屏、睡眠期间（与锁屏重叠且无输入的分钟）一律不计。

无输入、无音频的分钟：
  · count_short_idle = true（默认）：先“暂记”为有效——可能在看文档、思考；
    连续满 5 分钟（按“距上次输入/解锁”的实际时长，或连续 5 个这样的分钟）则回溯，
    把暂记的分钟撤回，之后的同类分钟直接记为离开；
  · count_short_idle = false：直接记为离开，满 5 分钟时同样触发“长时间离开”。
两种读法的取舍见 DECISIONS.md D-10。

本模块只做分类，不碰账本；由 engine 根据返回的 MinuteResult 去改账。
音频、全屏是“昂贵信号”，以回调形式传入，只有在这一分钟无输入时才会被调用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# 分钟类别
INPUT = "input"          # 有输入
AUDIO = "audio"          # 无输入，但在看视频/听音频（满足条件）
IDLE_PROV = "idle_prov"  # 无输入无音频，暂记为有效
AWAY = "away"            # 离开（不计）
LOCKED = "locked"        # 锁屏 / 睡眠（不计）


@dataclass
class MinuteResult:
    start: float
    kind: str
    had_input: bool
    counted: bool                 # 这一分钟是否计入有效时长与两本账
    provisional: bool = False     # 是否为暂记
    retracted: int = 0            # 本次回溯撤回了多少暂记分钟
    long_idle: bool = False       # 本分钟使“无输入无音频”连续满 5 分钟
    audio_checked: bool = False


class EffectiveTime:
    def __init__(self, P):
        self.P = P
        self.today_buckets = 0      # 今日有效分钟（含暂记）
        self.prov_buckets = 0       # 其中暂记的分钟
        self.idle_run = 0           # 连续“无输入无音频”的分钟数
        self.away_mode = False      # 已确认离开：之后的无输入分钟直接记离开

    # ── 状态维护 ─────────────────────────────────────────────────────────
    def confirm(self) -> None:
        """停顿被打断（有输入/有音频/锁屏）：暂记转正。"""
        self.prov_buckets = 0

    def reset_run(self) -> None:
        self.confirm()
        self.idle_run = 0
        self.away_mode = False

    def new_day(self) -> None:
        self.today_buckets = 0
        self.prov_buckets = 0

    @property
    def today_minutes(self) -> int:
        return self.today_buckets

    # ── 一分钟结束时调用 ─────────────────────────────────────────────────
    def close_bucket(
        self,
        start: float,
        end: float,
        had_input: bool,
        absent_overlap: bool,
        idle_ref: float | None,
        audio_playing: Callable[[], bool],
        fullscreen: Callable[[], bool],
    ) -> MinuteResult:
        """idle_ref：最后一次输入或解锁的时刻（空闲从这里起算）；None 表示从没见过输入。"""
        P = self.P

        if had_input:
            self.reset_run()
            self.today_buckets += 1
            return MinuteResult(start, INPUT, True, True)

        if absent_overlap:
            # 锁屏 / 睡眠：不计入，并结束当前停顿（暂记转正）
            self.reset_run()
            return MinuteResult(start, LOCKED, False, False)

        # 无输入：只有这时才查音频（昂贵信号）
        playing = False
        try:
            playing = bool(audio_playing())
        except Exception:  # noqa: BLE001
            playing = False
        if playing:
            recent = idle_ref is not None and (end - idle_ref) < P.audio_recent_input_s
            fs = False
            if not recent:
                try:
                    fs = bool(fullscreen())
                except Exception:  # noqa: BLE001
                    fs = False
            if recent or fs:
                self.reset_run()
                self.today_buckets += 1
                return MinuteResult(start, AUDIO, False, True, audio_checked=True)

        # 无输入、无（有效）音频
        if self.away_mode:
            return MinuteResult(start, AWAY, False, False, audio_checked=True)

        self.idle_run += 1
        idle_long = idle_ref is None or (end - idle_ref) >= P.grace_idle_buckets * P.bucket_s - 1e-6
        if self.idle_run >= P.grace_idle_buckets or idle_long:
            retracted = self.prov_buckets
            self.today_buckets -= retracted
            self.prov_buckets = 0
            self.away_mode = True
            return MinuteResult(start, AWAY, False, False, retracted=retracted,
                                long_idle=True, audio_checked=True)

        if P.count_short_idle:
            self.today_buckets += 1
            self.prov_buckets += 1
            return MinuteResult(start, IDLE_PROV, False, True, provisional=True, audio_checked=True)
        return MinuteResult(start, AWAY, False, False, audio_checked=True)
