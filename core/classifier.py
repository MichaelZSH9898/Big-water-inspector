# -*- coding: utf-8 -*-
"""状态识别（第 6.3 节）。

分两层：
  · 屏蔽层 blocker：会议 > 全屏/演示 > 勿扰。命中任一，所有场景（含硬上限）都不出现。
  · 时机层 moment：心流 > 游离 > 断点 > 普通。与屏蔽层分开算，这样被屏蔽的候选也能记日志。
对外的 state = blocker 或 moment。

断点信号（满足任一）：
  · burst_pause    爆发后停顿：最近 10 分钟有输入 ≥ 5 分钟，随后出现 20–90 秒无输入
  · category_switch 类别切换：前台从生产力切到沟通/浏览器/娱乐
  · close          收尾动作：前台窗口关闭或应用退出后 10 秒内
心流期间这些信号不生效（只允许久坐硬上限）；但 break_signal 字段总会给出“原始断点”，
供“硬上限被屏蔽、解除后在第一个断点出现”使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .history import ENTERTAINMENT, PRODUCTIVITY, History

MEETING = "meeting"
FULLSCREEN = "fullscreen"
DND = "dnd"
FLOW = "flow"
WANDER = "wander"
BREAK = "break"
NORMAL = "normal"

BLOCKERS = (MEETING, FULLSCREEN, DND)
GOOD_MOMENTS = (WANDER, BREAK)


@dataclass
class Blockers:
    meeting: bool = False
    meeting_why: str = ""
    fullscreen: bool = False
    fullscreen_why: str = ""
    dnd: bool = False
    dnd_why: str = ""

    def first(self) -> tuple[str | None, str]:
        if self.meeting:
            return MEETING, self.meeting_why
        if self.fullscreen:
            return FULLSCREEN, self.fullscreen_why
        if self.dnd:
            return DND, self.dnd_why
        return None, ""


@dataclass
class Classification:
    state: str
    blocker: str | None
    moment: str
    break_signal: str | None
    why: str
    facts: dict = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.blocker is not None


def break_signal(now: float, P, hist: History, idle_s: float, current_has_input: bool) -> str | None:
    """原始断点信号（不考虑心流）。"""
    if P.pause_min_s <= idle_s <= P.pause_max_s:
        if hist.input_minutes(P.window_buckets, current_has_input) >= P.burst_input_buckets:
            return "burst_pause"
    if hist.last_category_switch(now, P.category_switch_window_s) is not None:
        return "category_switch"
    if hist.recent_close(now, P.close_window_s) is not None:
        return "close"
    return None


def classify_moment(now: float, P, hist: History, idle_s: float, current_has_input: bool):
    """只算时机层（便宜，不查任何系统信号）。返回 (moment, break_signal, why, facts)。"""
    inp10 = hist.input_minutes(P.window_buckets, current_has_input)
    inp5 = hist.input_minutes(P.wander_window_buckets, current_has_input)
    sw10 = hist.switch_count(now, P.window_s)
    sw5 = hist.switch_count(now, P.wander_window_s)
    cat = hist.category or "other"
    sig = break_signal(now, P, hist, idle_s, current_has_input)
    facts = {"input10": inp10, "input5": inp5, "switch10": sw10, "switch5": sw5,
             "category": cat, "idle_s": round(idle_s, 1)}

    if inp10 >= P.flow_input_buckets and sw10 <= P.flow_max_switches and cat == PRODUCTIVITY:
        return FLOW, sig, f"心流：10 分钟内输入 {inp10} 分钟、切换 {sw10} 次、前台为生产力", facts
    if sw5 >= P.wander_min_switches:
        return WANDER, sig, f"游离：5 分钟内切换 {sw5} 次", facts
    if cat == ENTERTAINMENT and inp5 <= P.sparse_input_max:
        return WANDER, sig, f"游离：前台娱乐且 5 分钟内仅 {inp5} 分钟有输入", facts
    if sig:
        return BREAK, sig, f"断点：{sig}", facts
    return NORMAL, sig, "普通", facts


def classify(now: float, P, hist: History, idle_s: float, current_has_input: bool,
             blockers: Blockers) -> Classification:
    moment, sig, why, facts = classify_moment(now, P, hist, idle_s, current_has_input)
    blk, blk_why = blockers.first()
    state = blk or moment
    return Classification(state=state, blocker=blk, moment=moment, break_signal=sig,
                          why=blk_why if blk else why, facts=facts)
