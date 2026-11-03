# -*- coding: utf-8 -*-
"""场景触发决策（第 6.4、7 节）。

每个场景是一个 Trigger，注册进 Policy 即生效。新增场景 =
  1. 写一个 Trigger 子类（candidate 判断“想不想出场”）并 register；
  2. 在角色包的 lines/*.json 里加一个同名的台词键；persona.json 的 scenes 里指定姿势。

决策顺序：按 priority 依次问每个触发器；第一个“想出场且没被屏蔽”的出场。
被屏蔽的候选全部返回给 engine 记日志（用来判断屏蔽规则是否过严）。

屏蔽原因（按优先级）：
  paused 暂停 > quiet_hours 静默时段 > meeting/fullscreen/dnd 系统状态 > min_gap 最小间隔
  > 触发器自己的原因（A 的频率上限、B 的心流/等待断点）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import classifier as C
from .clock import in_window, minute_of_day, minutes_since_day_start

PAUSED = "paused"
QUIET_HOURS = "quiet_hours"
MIN_GAP = "min_gap"
CAP = "cap"
FLOW_ONLY_HARD = "flow"
WAITING_BREAK = "waiting_break"


@dataclass
class UnlockInfo:
    t: float
    lock_s: float
    kind: str = "lock"


@dataclass
class Ctx:
    now: float
    P: object
    day: str
    water: float
    sitting: float
    effective_today: int
    cls: C.Classification
    last_flash_t: float | None
    flash_times: dict              # scene -> [t, ...]（最近的出场时间）
    paused_until: float | None = None
    unlock: UnlockInfo | None = None
    present: bool = True           # 用户在电脑前（按 6.1 的口径：此刻这一分钟会被计为有效）


@dataclass
class Candidate:
    trigger: "Trigger"
    basis: str
    line_key: str
    ledgers: tuple = ()
    hard: bool = False
    wait_reason: str | None = None   # 触发器自己的屏蔽原因（如心流、等待断点）

    @property
    def scene(self) -> str:
        return self.trigger.scene


@dataclass
class Decision:
    fire: Candidate | None = None
    blocked: list = field(default_factory=list)   # [(Candidate, reason)]


class Trigger:
    scene = "?"          # 日志里的场景代号
    name = "?"           # 场景名 = 配置 [scenes.<name>] = 台词键前缀
    pose = "?"           # 默认姿势（角色包 persona.json 可覆盖）
    anchor = "center"    # top_center / right_edge / bottom_right
    priority = 100
    retry_when_blocked = True
    # 系统状态（会议/全屏/勿扰）之外，是否也受暂停、静默时段、最小间隔约束
    respects_global = True

    def candidate(self, ctx: Ctx) -> Candidate | None:  # pragma: no cover - 接口
        raise NotImplementedError

    def extra_block(self, ctx: Ctx, cand: Candidate) -> str | None:
        return cand.wait_reason

    def on_fired(self, ctx: Ctx, cand: Candidate) -> None:
        pass

    def on_blocked(self, ctx: Ctx, cand: Candidate, reason: str) -> None:
        pass

    # 持久化（重启后恢复当天状态）
    def dump(self) -> dict:
        return {}

    def load(self, d: dict) -> None:
        pass


class UnlockScold(Trigger):
    """场景 A：解锁训话。"""
    scene, name, pose, anchor, priority = "A", "unlock_scold", "scold", "top_center", 10
    retry_when_blocked = False      # 出场前被会议/全屏挡住就放弃，不补发

    def candidate(self, ctx):
        u, P = ctx.unlock, ctx.P
        if u is None:
            return None
        if u.lock_s < P.a_min_lock_s or ctx.water < P.water_threshold:
            return None
        return Candidate(self, f"解锁：{u.kind} {u.lock_s / P.bucket_s:.1f} 分钟，饮水账 {ctx.water:.0f}",
                         "unlock_scold", ("water",))

    def extra_block(self, ctx, cand):
        recent = [t for t in ctx.flash_times.get(self.scene, []) if ctx.now - t < ctx.P.a_cap_s]
        return CAP if recent else None


class SidePeek(Trigger):
    """场景 B：侧边探头。"""
    scene, name, pose, anchor, priority = "B", "side_peek", "peek", "right_edge", 20

    def __init__(self):
        self.hard_deferred = False   # 硬上限被会议/全屏/勿扰挡过：解除后等第一个断点

    def candidate(self, ctx):
        P, cls = ctx.P, ctx.cls
        if ctx.sitting < P.sitting_soft:
            self.hard_deferred = False
            return None
        line, ledgers = "side_peek", ("sitting",)
        if ctx.water >= P.water_threshold and ctx.water / P.water_threshold > ctx.sitting / P.sitting_soft:
            line, ledgers = "side_peek_water", ("water",)
        tag = f"久坐账 {ctx.sitting:.0f}"
        if ctx.sitting < P.sitting_hard and self.hard_deferred:
            self.hard_deferred = False   # 账被削减到硬上限以下，回到普通规则
        if ctx.sitting >= P.sitting_hard:
            if self.hard_deferred and cls.blocker is None:
                if cls.break_signal:
                    return Candidate(self, f"{tag} ≥ 硬上限；屏蔽解除后的断点：{cls.break_signal}",
                                     line, ledgers, hard=True)
                return Candidate(self, f"{tag} ≥ 硬上限；屏蔽已解除，等待断点", line, ledgers,
                                 hard=True, wait_reason=WAITING_BREAK)
            return Candidate(self, f"{tag} ≥ 硬上限", line, ledgers, hard=True)
        if cls.moment in C.GOOD_MOMENTS:
            return Candidate(self, f"{tag} ≥ 软阈值；{cls.moment}：{cls.break_signal or cls.why}",
                             line, ledgers)
        wait = FLOW_ONLY_HARD if cls.moment == C.FLOW else WAITING_BREAK
        return Candidate(self, f"{tag} ≥ 软阈值；{cls.moment}", line, ledgers, wait_reason=wait)

    def on_fired(self, ctx, cand):
        self.hard_deferred = False

    def on_blocked(self, ctx, cand, reason):
        if cand.hard and reason in C.BLOCKERS:
            self.hard_deferred = True

    def dump(self):
        return {"hard_deferred": self.hard_deferred}

    def load(self, d):
        self.hard_deferred = bool(d.get("hard_deferred", False))


class OvertimeCare(Trigger):
    """场景 C：加班关怀。每天一次；被屏蔽就等解除后补上。"""
    scene, name, pose, anchor, priority = "C", "overtime_care", "care", "bottom_right", 30

    def __init__(self):
        self.shown_day: str | None = None

    def candidate(self, ctx):
        P = ctx.P
        if self.shown_day == ctx.day or not ctx.present:
            return None
        if ctx.effective_today < P.c_effective_buckets:
            return None
        need = (P.c_after_min - P.day_start_min) % (24 * 60)
        if minutes_since_day_start(ctx.now, P.day_start_min) < need:
            return None
        ca = int(P.c_after_min)
        return Candidate(self, f"今日有效 {ctx.effective_today / 60:.1f} 小时，已过 {ca // 60:02d}:{ca % 60:02d}",
                         "overtime_care", ())

    def on_fired(self, ctx, cand):
        self.shown_day = ctx.day

    def dump(self):
        return {"shown_day": self.shown_day}

    def load(self, d):
        self.shown_day = d.get("shown_day")


class Policy:
    def __init__(self, triggers: list[Trigger] | None = None):
        self.triggers: list[Trigger] = []
        for t in (triggers if triggers is not None else default_triggers()):
            self.register(t)

    def register(self, trigger: Trigger) -> None:
        self.triggers.append(trigger)
        self.triggers.sort(key=lambda t: t.priority)

    def get(self, scene: str) -> Trigger | None:
        for t in self.triggers:
            if t.scene == scene or t.name == scene:
                return t
        return None

    @staticmethod
    def global_block(ctx: Ctx, trig: Trigger) -> str | None:
        P = ctx.P
        if trig.respects_global:
            if ctx.paused_until is not None and ctx.now < ctx.paused_until:
                return PAUSED
            m = minute_of_day(ctx.now)
            for a, b in P.quiet_hours:
                if in_window(m, a, b):
                    return QUIET_HOURS
        if ctx.cls.blocker:
            return ctx.cls.blocker
        if trig.respects_global and ctx.last_flash_t is not None and ctx.now - ctx.last_flash_t < P.min_gap_s:
            return MIN_GAP
        return None

    def evaluate(self, ctx: Ctx) -> Decision:
        dec = Decision()
        for trig in self.triggers:
            cand = trig.candidate(ctx)
            if cand is None:
                continue
            reason = self.global_block(ctx, trig) or trig.extra_block(ctx, cand)
            if reason:
                trig.on_blocked(ctx, cand, reason)
                dec.blocked.append((cand, reason))
                continue
            dec.fire = cand
            return dec
        return dec


def default_triggers() -> list[Trigger]:
    return [UnlockScold(), SidePeek(), OvertimeCare()]
