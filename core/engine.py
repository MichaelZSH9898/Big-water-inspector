# -*- coding: utf-8 -*-
"""逻辑内核编排：接收事件与定时唤醒，驱动 有效时长 → 两本账 → 状态识别 → 决策 → 显示 → 日志。

本模块不 import 任何 Windows 代码。真实运行时由 main.py 驱动，测试 / 模拟器里由 sim 驱动：
  · 定时：外部在 next_wake() 给出的时刻调用 tick()
  · 事件：on_lock / on_unlock / on_suspend / on_resume / on_foreground / on_window_closed
  · 命令：pause / resume / demo_all / reload / stats_today

时间桶：一个“分钟桶”长 P.bucket_s 秒（演示模式下为 1 秒），按 epoch 对齐。
每个桶结束时恰好醒一次，用“最后一次输入时刻 ≥ 桶起点”判断这一分钟内有没有输入——
不挂任何键鼠钩子也能精确到分钟。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from . import classifier as C
from .clock import day_key, iso, next_day_start
from .effective_time import AUDIO, IDLE_PROV, INPUT, LOCKED, EffectiveTime, MinuteResult
from .eventlog import EventLog
from .history import LEAVE_PRODUCTIVITY_TO, PRODUCTIVITY, History
from .ledger import Ledger
from .policy import Ctx, Policy, UnlockInfo
from .state_file import STATE_VERSION, atomic_write_json, read_json

EPS = 0.05          # 桶边界之后多久醒（秒）
WAIT_REASONS = ("flow", "waiting_break")
RUNTIME_VERSION = 1


@dataclass
class FlashRequest:
    scene: str            # A / B / C
    name: str             # unlock_scold / side_peek / overtime_care
    pose: str             # scold / peek / care
    line_key: str
    line_idx: int
    text: str
    anchor: str
    show_s: float
    fade_s: float
    demo: bool = False


class NullDisplay:
    def __init__(self):
        self.shown: list[tuple[float, FlashRequest]] = []

    def show(self, req: FlashRequest) -> bool:
        self.shown.append((0.0, req))
        return True


class Engine:
    def __init__(self, cfg, clock, signals, display=None, log: EventLog | None = None,
                 lines=None, policy: Policy | None = None,
                 state_path: str | None = None, runtime_path: str | None = None, restore: bool = True):
        self.cfg = cfg
        self.P = cfg.P
        self.clock = clock
        self.sig = signals
        self.display = display or NullDisplay()
        self.log = log or EventLog(None, clock)
        self.lines = lines
        self.policy = policy or Policy()
        self.state_path = state_path
        self.runtime_path = runtime_path

        self.ledger = Ledger()
        self.eff = EffectiveTime(self.P)
        self.hist = History(self.P)

        now = clock.now()
        self.day = day_key(now, self.P.day_start_min)
        self.bucket_start = math.floor(now / self.P.bucket_s) * self.P.bucket_s
        self.cur_input = False
        self.cur_absent = False
        self.last_input_t: float | None = None     # 最后一次真实键鼠输入（只用于判断“这一分钟有没有输入”）
        self.idle_origin_t: float | None = None    # 最近一次解锁/唤醒：空闲时长从这里起算（解锁不伪造输入）
        self.idle_s = 0.0

        self.absent_flags: set[str] = set()
        self.absent_since: float | None = None
        self.absent_kind: str | None = None

        self.pending_unlock: UnlockInfo | None = None
        self.pending_unlock_due: float | None = None
        self.responses: list[dict] = []
        self.last_flash_t: float | None = None
        self.flash_times: dict[str, list[float]] = {}
        self.counts: dict[str, dict] = {}
        self.paused_until: float | None = None
        self.flash_seq = 0
        self.last_cls: C.Classification | None = None
        self._blocked_seen: dict[tuple, float] = {}

        self.last_tick: float | None = None
        self.ticks = 0                      # 诊断：被唤醒了多少次（资源实测用）
        self.started_at = now
        self.next_idle_t = now
        self.next_decision_t = self.bucket_start + self.P.bucket_s + EPS
        self.next_state_write = now
        self._rng = random.Random()

        self.log.adopt_day(self.day)
        if restore and self.runtime_path:
            self._restore(now)
        self.log.event("app", what="start", demo=self.P.demo)

    # ════════════════════════════════════════════════════════════════════
    # 调度
    # ════════════════════════════════════════════════════════════════════
    @property
    def absent(self) -> bool:
        return bool(self.absent_flags)

    def near_threshold(self) -> bool:
        P = self.P
        trig_b = self.policy.get("B")
        deferred = bool(getattr(trig_b, "hard_deferred", False))
        return self.ledger.sitting >= P.sitting_soft - P.near_margin or deferred

    def idle_interval(self) -> float:
        return self.P.idle_near_s if self.near_threshold() else self.P.idle_far_s

    def _gap_limit(self) -> float:
        return 2.5 * max(self.P.idle_far_s, self.P.decision_interval_s, self.P.bucket_s) + 1.0

    def next_wake(self) -> float:
        c = [self.bucket_start + self.P.bucket_s + EPS]     # state.json 搭这些唤醒的便车写，不单独醒
        if not self.absent:
            c.append(self.next_idle_t)
            c.append(self.next_decision_t)
            ref = self._idle_ref()
            for r in self.responses:
                c.append(r["deadline"] + EPS)
                base = r["t"] if ref is None else max(ref, r["t"])
                c.append(base + self.P.response_idle_s + EPS)
        if self.pending_unlock_due is not None:
            c.append(self.pending_unlock_due)
        return min(c)

    # ════════════════════════════════════════════════════════════════════
    # 定时唤醒
    # ════════════════════════════════════════════════════════════════════
    def tick(self) -> None:
        now = self.clock.now()
        self.ticks += 1
        if now < self.bucket_start - 1:            # 系统时间被往回调了
            self.bucket_start = math.floor(now / self.P.bucket_s) * self.P.bucket_s
            self.last_tick = now
            self.log.app("系统时间回拨，已重新对齐分钟桶")
        self._detect_gap(now)
        sampled = self._advance(now)
        self._check_responses(now)

        if sampled and self.sig.foreground is not None and not self.absent:
            try:
                newcat = self.sig.foreground.refresh()
            except Exception:  # noqa: BLE001
                newcat = None
            if newcat:
                self._record_foreground(now, newcat)

        if self.pending_unlock_due is not None and now >= self.pending_unlock_due - 1e-6:
            unlock = self.pending_unlock
            self.pending_unlock, self.pending_unlock_due = None, None
            if not self.absent:
                self._decide(now, "unlock", unlock)
        elif not self.absent and now >= self.next_decision_t - 1e-6:
            self._decide(now, "timer")
        elif sampled and self.near_threshold():
            self._maybe_decide_quick(now, "sample")

        if now >= self.next_decision_t - 1e-6:
            # 下一次定时决策对齐到下一个桶边界之后
            k = math.floor((now - EPS) / self.P.decision_interval_s) + 1
            self.next_decision_t = k * self.P.decision_interval_s + EPS
        if now >= self.next_state_write - 1e-6:
            self.write_state(now)
            self.next_state_write = now + self.P.state_write_s
        self.last_tick = now

    def _advance(self, now: float) -> bool:
        """采样空闲时长（不在锁屏时）、结算已结束的分钟桶。返回是否做了空闲采样。"""
        sampled = False
        li_new = None
        if not self.absent:
            li_new = self._sample_idle(now)
            sampled = True
            self.next_idle_t = now + self.idle_interval()
        self._close_buckets(now, li_new)
        if li_new is not None and (self.last_input_t is None or li_new > self.last_input_t):
            self.last_input_t = li_new
        self.idle_s = self.idle_at(now)
        return sampled

    def _sample_idle(self, now: float) -> float | None:
        """返回最近一次输入的时刻。不立刻改 last_input_t：要先用旧值结算它之前的分钟桶。"""
        try:
            idle = max(0.0, float(self.sig.idle.idle_seconds()))
        except Exception:  # noqa: BLE001
            self.log.app("空闲时长采样失败", exc=True)
            return None
        li = now - idle
        # 只把落在“当前这一分钟”里的输入记到当前桶；更晚的输入留给结算循环按时刻归桶
        if self.bucket_start <= li < self.bucket_start + self.P.bucket_s:
            self.cur_input = True
        return li

    def _idle_ref(self) -> float | None:
        refs = [t for t in (self.last_input_t, self.idle_origin_t) if t is not None]
        return max(refs) if refs else None

    def idle_at(self, now: float) -> float:
        ref = self._idle_ref()
        return 0.0 if ref is None else max(0.0, now - ref)

    def _detect_gap(self, now: float) -> None:
        """进程被挂起（睡眠但没收到电源事件）时，把这段空白当作睡眠处理。"""
        if self.last_tick is None or self.absent:
            return
        if now - self.last_tick > self._gap_limit():
            t0 = self.last_tick
            self.log.app(f"检测到 {now - t0:.0f} 秒没有被唤醒，按睡眠处理")
            self._absence_begin("gap", t0)
            self._absence_end("gap", now)

    # ── 分钟桶 ───────────────────────────────────────────────────────────
    def _close_buckets(self, now: float, li_new: float | None = None) -> None:
        """结算 now 之前已经结束的分钟桶。li_new：本次采样得到、尚未提交的最近输入时刻。"""
        bs = self.P.bucket_s
        n = int((now - self.bucket_start) // bs)
        if n <= 0:
            return
        if n > 2000 and (self.absent or self.cur_absent):
            self._skip_absent_buckets(n - 1)
        while now >= self.bucket_start + bs:
            start, end = self.bucket_start, self.bucket_start + bs
            dk = day_key(start, self.P.day_start_min)
            if dk != self.day:
                self._rollover(dk)
            if li_new is not None and li_new < end and (self.last_input_t is None or li_new > self.last_input_t):
                self.last_input_t = li_new          # 新输入发生在这一桶（或更早）：可以提交了
            li = self.last_input_t
            had = self.cur_input or (li is not None and start <= li < end)
            overlap = self.cur_absent or self.absent
            res = self.eff.close_bucket(start, end, had, overlap, self._idle_ref(),
                                        self._audio_playing, self._fullscreen_now)
            self._apply_minute(res, end)
            self.hist.add_bucket(start, had)
            self.bucket_start = end
            nxt = li_new if li_new is not None else li
            self.cur_input = nxt is not None and end <= nxt < end + bs
            self.cur_absent = self.absent
            dk = day_key(end, self.P.day_start_min)     # 新的一分钟属于新的一天：立刻换日
            if dk != self.day:
                self._rollover(dk)

    def _skip_absent_buckets(self, n: int) -> None:
        """长时间离开后一次跳过大量锁屏分钟（只影响性能，不影响结果）。"""
        bs = self.P.bucket_s
        end = self.bucket_start + n * bs
        dk = day_key(end - bs, self.P.day_start_min)
        if dk != self.day:
            self._rollover(dk)
        self.eff.reset_run()
        self.ledger.confirm()
        for i in range(min(n, 64)):
            self.hist.add_bucket(end - (min(n, 64) - i) * bs, False)
        self.bucket_start = end
        self.cur_input = False
        self.cur_absent = True

    def _apply_minute(self, res: MinuteResult, end: float) -> None:
        L = self.ledger
        if res.kind in (INPUT, AUDIO):
            L.confirm()
            L.add_minute()
        elif res.kind == IDLE_PROV:
            L.add_minute(provisional=True)
        elif res.kind == LOCKED:
            L.confirm()
        if res.long_idle:
            retracted = L.retract()
            ch = L.apply_long_idle()
            if retracted or ch.sitting_before:     # 启动时“从没见过输入”这种无变化的不记
                self.log.event("absence", kind="idle",
                               duration_s=round(self.P.grace_idle_buckets * self.P.bucket_s),
                               retracted_min=retracted, change=ch.as_dict())

    def _audio_playing(self) -> bool:
        try:
            return bool(self.sig.audio.is_playing())
        except Exception:  # noqa: BLE001
            self.log.app("音频检测失败", exc=True)
            return False

    def _fullscreen_now(self) -> bool:
        try:
            return bool(self.sig.notify.query().fullscreen)
        except Exception:  # noqa: BLE001
            return False

    def _rollover(self, new_day: str) -> None:
        self.log.daily(self.day_summary())
        self.log.rotate(new_day)
        self.day = new_day
        self.eff.new_day()
        if self.P.reset_on_new_day:
            self.ledger.reset()
        self.counts = {}
        self.flash_seq = 0
        self.log.event("app", what="new_day")

    # ════════════════════════════════════════════════════════════════════
    # 事件
    # ════════════════════════════════════════════════════════════════════
    def on_lock(self) -> None:
        self._absence_begin("lock")

    def on_unlock(self) -> None:
        self._absence_end("lock")

    def on_suspend(self) -> None:
        self._absence_begin("sleep")

    def on_resume(self) -> None:
        self._absence_end("sleep")

    def on_foreground(self, category: str | None) -> None:
        now = self.clock.now()
        if category is None:
            return
        if self.absent:
            self.hist.category = category
            return
        self._advance(now)
        self._record_foreground(now, category)

    def on_window_closed(self, t: float | None = None) -> None:
        now = self.clock.now()
        if self.absent:
            return
        self._advance(now)
        self.hist.record_close(t if t is not None else now)
        self._maybe_decide_quick(now, "close")

    def _record_foreground(self, now: float, category: str) -> None:
        sw = self.hist.record_foreground(now, category)
        if sw and sw.frm == PRODUCTIVITY and sw.to in LEAVE_PRODUCTIVITY_TO:
            self._maybe_decide_quick(now, "category_switch")

    # ── 锁屏 / 睡眠 ──────────────────────────────────────────────────────
    def _absence_begin(self, kind: str, t: float | None = None) -> None:
        t = self.clock.now() if t is None else t
        if not self.absent:
            self._advance(t)
        was = self.absent
        self.absent_flags.add(kind)
        if was:
            return
        self.absent_since = t
        self.absent_kind = kind
        self.cur_absent = True
        self.eff.confirm()
        self.ledger.confirm()
        self.pending_unlock, self.pending_unlock_due = None, None
        for r in list(self.responses):
            self._respond(r, "lock" if kind == "lock" else "sleep", t)

    def _absence_end(self, kind: str, t: float | None = None) -> None:
        t = self.clock.now() if t is None else t
        if kind not in self.absent_flags:
            return
        self.absent_flags.discard(kind)
        if self.absent:
            return
        self.absent_flags.add("_closing")     # 结算离开期间的分钟桶时仍视为离开
        self._close_buckets(t)
        self.absent_flags.discard("_closing")
        since = self.absent_since if self.absent_since is not None else t
        dur = max(0.0, t - since)
        akind = self.absent_kind or kind
        self.absent_since, self.absent_kind = None, None
        self.eff.reset_run()
        ch = self.ledger.apply_lock(dur, self.P)
        if dur >= self.P.long_absence_s:
            self.hist.clear_recent()
        self.log.event("absence", kind=akind, duration_s=round(dur, 1),
                       change=ch.as_dict() if ch else None)
        # 解锁后的空闲从解锁时刻算起（不把锁屏期间算成“无输入”，也不伪造一次输入）
        self.idle_origin_t = t
        self.idle_s = 0.0
        self.next_idle_t = t
        if akind in ("lock", "sleep") and dur >= self.P.a_min_lock_s and self.ledger.water >= self.P.water_threshold:
            self.pending_unlock = UnlockInfo(t, dur, akind)
            self.pending_unlock_due = t + self.P.a_delay_s

    # ════════════════════════════════════════════════════════════════════
    # 响应判定（第 10 节：不依赖用户互动）
    # ════════════════════════════════════════════════════════════════════
    def _check_responses(self, now: float) -> None:
        ref = self._idle_ref()
        for r in list(self.responses):
            base = r["t"] if ref is None else max(ref, r["t"])
            if not self.absent and now - base >= self.P.response_idle_s - 1e-6 and \
                    base + self.P.response_idle_s <= r["deadline"] + 1e-6:
                self._respond(r, "idle", now)
            elif now > r["deadline"]:
                self.responses.remove(r)
                self.log.event("outcome", ref=r["id"], scene=r["scene"], result="ignored",
                               after_s=round(now - r["t"], 1))

    def _respond(self, r: dict, how: str, now: float) -> None:
        if r not in self.responses:
            return
        self.responses.remove(r)
        changes = [self.ledger.clear(acct, f"response_{r['scene']}").as_dict() for acct in r["ledgers"]]
        self._count(r["scene"])["responded"] += 1
        self.log.event("outcome", ref=r["id"], scene=r["scene"], result="responded", how=how,
                       after_s=round(now - r["t"], 1), changes=changes)

    # ════════════════════════════════════════════════════════════════════
    # 决策
    # ════════════════════════════════════════════════════════════════════
    def _blockers(self, now: float) -> C.Blockers:
        b = C.Blockers()
        try:
            mc = self.sig.miccam.status(now)
            if mc.in_use:
                b.meeting, b.meeting_why = True, mc.why or "麦克风/摄像头使用中"
            elif mc.last_stop_t is not None and 0 <= now - mc.last_stop_t < self.P.meeting_cooldown_s:
                b.meeting, b.meeting_why = True, "会议刚结束"
        except Exception:  # noqa: BLE001
            self.log.app("麦克风/摄像头检测失败", exc=True)
        try:
            ns = self.sig.notify.query()
            if ns.fullscreen:
                b.fullscreen, b.fullscreen_why = True, ns.fullscreen_why or "全屏"
            if ns.dnd:
                b.dnd, b.dnd_why = True, ns.dnd_why or "勿扰"
        except Exception:  # noqa: BLE001
            self.log.app("通知状态检测失败", exc=True)
        return b

    def classify_now(self, now: float | None = None) -> C.Classification:
        now = self.clock.now() if now is None else now
        idle = self.idle_at(now)
        return C.classify(now, self.P, self.hist, idle, self.cur_input, self._blockers(now))

    def _maybe_decide_quick(self, now: float, why: str) -> None:
        """事件触发的即时决策：只有“可能出场”时才去查会议/全屏等系统信号。"""
        P = self.P
        if self.ledger.sitting < P.sitting_soft:
            return
        idle = self.idle_at(now)
        moment, sig, _, _ = C.classify_moment(now, P, self.hist, idle, self.cur_input)
        trig_b = self.policy.get("B")
        deferred = bool(getattr(trig_b, "hard_deferred", False))
        if moment in C.GOOD_MOMENTS or (deferred and sig) or self.ledger.sitting >= P.sitting_hard:
            self._decide(now, why)

    def _ctx(self, now: float, cls: C.Classification, unlock: UnlockInfo | None) -> Ctx:
        return Ctx(now=now, P=self.P, day=self.day, water=self.ledger.water, sitting=self.ledger.sitting,
                   effective_today=self.eff.today_buckets, cls=cls, last_flash_t=self.last_flash_t,
                   flash_times=self.flash_times, paused_until=self.paused_until, unlock=unlock,
                   present=not self.absent and not self.eff.away_mode)

    def _decide(self, now: float, why: str, unlock: UnlockInfo | None = None) -> None:
        cls = self.classify_now(now)
        self.last_cls = cls
        ctx = self._ctx(now, cls, unlock)
        dec = self.policy.evaluate(ctx)
        for cand, reason in dec.blocked:
            self._log_blocked(now, cand, reason, cls, abandoned=not cand.trigger.retry_when_blocked)
        if dec.fire is not None:
            self._flash(now, dec.fire, cls, ctx, why)

    def _log_blocked(self, now, cand, reason, cls, abandoned=False) -> None:
        if reason == "min_gap" and self.last_flash_t is not None and now - self.last_flash_t < self.P.bucket_s:
            return      # 刚闪现完的同一分钟里，“离上次闪现太近”是废话，不记
        key = (cand.scene, reason)
        last = self._blocked_seen.get(key)
        if not abandoned and last is not None and now - last < self.P.blocked_log_dedupe_s:
            return
        self._blocked_seen[key] = now
        cnt = self._count(cand.scene)
        if reason not in WAIT_REASONS:      # “心流中/等断点”是在等时机，不算被屏蔽
            cnt["blocked"] += 1
        cnt.setdefault("blocked_by", {})
        cnt["blocked_by"][reason] = cnt["blocked_by"].get(reason, 0) + 1
        self.log.event("blocked", scene=cand.scene, line=cand.line_key, **self._numbers(),
                       state=cls.state, basis=cand.basis, blocked=True, block_reason=reason,
                       hard=cand.hard, result="abandoned" if abandoned else "deferred",
                       facts=cls.facts)

    def _flash(self, now, cand, cls, ctx, why) -> None:
        trig = cand.trigger
        idx, text = (self.lines.pick(cand.line_key) if self.lines else (0, cand.line_key))
        show_s, fade_s = self.cfg.scene_timing(trig.name)
        req = FlashRequest(scene=trig.scene, name=trig.name, pose=trig.pose, line_key=cand.line_key,
                           line_idx=idx, text=text, anchor=trig.anchor, show_s=show_s, fade_s=fade_s)
        try:
            ok = bool(self.display.show(req))
        except Exception:  # noqa: BLE001
            self.log.app("闪现失败", exc=True)
            ok = False
        if not ok:
            self._log_blocked(now, cand, "display_failed", cls)
            return
        self.flash_seq += 1
        fid = f"{self.day}-{self.flash_seq:03d}-{trig.scene}"
        self.last_flash_t = now
        times = self.flash_times.setdefault(trig.scene, [])
        times.append(now)
        del times[:-10]
        self._count(trig.scene)["shown"] += 1
        trig.on_fired(ctx, cand)
        if cand.ledgers:
            self.responses.append({"id": fid, "scene": trig.scene, "ledgers": cand.ledgers,
                                   "t": now, "deadline": now + self.P.response_window_s})
        self.log.event("flash", id=fid, scene=trig.scene, line=cand.line_key, line_idx=idx,
                       **self._numbers(), state=cls.state, basis=cand.basis, trigger=why,
                       blocked=False, block_reason=None, hard=cand.hard,
                       result="pending" if cand.ledgers else "n/a", facts=cls.facts)
        self.save_runtime(now)

    def _numbers(self) -> dict:
        return {"water": round(self.ledger.water, 2), "sitting": round(self.ledger.sitting, 2),
                "effective_today_min": self.eff.today_buckets}

    def _count(self, scene: str) -> dict:
        return self.counts.setdefault(scene, {"shown": 0, "responded": 0, "blocked": 0})

    # ════════════════════════════════════════════════════════════════════
    # 托盘命令
    # ════════════════════════════════════════════════════════════════════
    def pause(self, seconds: float) -> None:
        now = self.clock.now()
        self.paused_until = now + seconds
        self.log.event("app", what="pause", until=iso(self.paused_until))
        self.save_runtime(now)

    def pause_until_tomorrow(self) -> None:
        now = self.clock.now()
        self.paused_until = next_day_start(now, self.P.day_start_min)
        self.log.event("app", what="pause", until=iso(self.paused_until))
        self.save_runtime(now)

    def resume(self) -> None:
        self.paused_until = None
        self.log.event("app", what="resume")
        self.save_runtime(self.clock.now())

    @property
    def paused(self) -> bool:
        return self.paused_until is not None and self.clock.now() < self.paused_until

    def demo_all(self) -> int:
        """立即依次播放全部场景（用于自查）。不受任何规则限制，不计入统计。"""
        n = 0
        for trig in self.policy.triggers:
            keys = [trig.name] + (["side_peek_water"] if trig.name == "side_peek" else [])
            key = keys[0]
            idx, text = (self.lines.pick(key) if self.lines else (0, key))
            show_s, fade_s = self.cfg.scene_timing(trig.name)
            req = FlashRequest(trig.scene, trig.name, trig.pose, key, idx, text, trig.anchor,
                               show_s, fade_s, demo=True)
            try:
                if self.display.show(req):
                    n += 1
            except Exception:  # noqa: BLE001
                self.log.app("演示闪现失败", exc=True)
        self.log.event("app", what="demo", count=n)
        return n

    def reload(self, cfg, lines=None) -> None:
        """配置变了：换参数，保留账本（切换演示模式时清零，因为分钟的长度变了）。"""
        demo_changed = cfg.P.demo != self.P.demo
        self.cfg, self.P = cfg, cfg.P
        self.eff.P = cfg.P
        self.hist.P = cfg.P
        if lines is not None:
            self.lines = lines
        now = self.clock.now()
        if demo_changed:
            self.ledger.reset()
            self.eff = EffectiveTime(cfg.P)
            self.bucket_start = math.floor(now / cfg.P.bucket_s) * cfg.P.bucket_s
            self.cur_input = False
        self.next_idle_t = now
        self.next_decision_t = self.bucket_start + cfg.P.bucket_s + EPS
        self.log.event("app", what="reload", demo=cfg.P.demo, demo_changed=demo_changed)

    def stats_today(self) -> dict:
        return {"day": self.day, "effective_min": self.eff.today_buckets,
                "water": round(self.ledger.water, 1), "sitting": round(self.ledger.sitting, 1),
                "state": self.last_cls.state if self.last_cls else None,
                "paused_until": self.paused_until if self.paused else None,
                "scenes": {k: dict(v) for k, v in self.counts.items()}}

    def day_summary(self) -> dict:
        scenes = {}
        for trig in self.policy.triggers:
            c = self.counts.get(trig.scene, {})
            scenes[trig.scene] = {"shown": c.get("shown", 0), "responded": c.get("responded", 0),
                                  "blocked": c.get("blocked", 0), "blocked_by": c.get("blocked_by", {})}
        return {"day": self.day, "effective_min": self.eff.today_buckets, "scenes": scenes}

    def snapshot(self) -> dict:
        return {"day": self.day, "water": round(self.ledger.water, 2), "sitting": round(self.ledger.sitting, 2),
                "effective": self.eff.today_buckets, "absent": self.absent,
                "state": self.last_cls.state if self.last_cls else None}

    # ════════════════════════════════════════════════════════════════════
    # 持久化
    # ════════════════════════════════════════════════════════════════════
    def write_state(self, now: float | None = None) -> None:
        now = self.clock.now() if now is None else now
        if self.state_path:
            state = "away" if self.absent else (self.last_cls.state if self.last_cls else "normal")
            atomic_write_json(self.state_path, {
                "v": STATE_VERSION, "updated": iso(now), "day": self.day, "state": state,
                "water_min": round(self.ledger.water, 1), "sitting_min": round(self.ledger.sitting, 1),
                "effective_today_min": self.eff.today_buckets,
                "thresholds": {"water": self.P.water_threshold, "sitting_soft": self.P.sitting_soft,
                               "sitting_hard": self.P.sitting_hard},
                "paused_until": iso(self.paused_until) if self.paused else None,
                "scenes_today": {k: {kk: vv for kk, vv in v.items() if kk != "blocked_by"}
                                 for k, v in self.counts.items()},
                "demo_mode": self.P.demo,
                "diag": {"ticks": self.ticks, "uptime_s": round(now - self.started_at)},
            })
        self.save_runtime(now)

    def save_runtime(self, now: float | None = None) -> None:
        if not self.runtime_path:
            return
        now = self.clock.now() if now is None else now
        atomic_write_json(self.runtime_path, {
            "v": RUNTIME_VERSION, "saved": now, "day": self.day, "demo": self.P.demo,
            "water": self.ledger.water, "sitting": self.ledger.sitting,
            "effective": self.eff.today_buckets, "counts": self.counts, "flash_seq": self.flash_seq,
            "last_flash_t": self.last_flash_t, "flash_times": self.flash_times,
            "paused_until": self.paused_until,
            "triggers": {t.scene: t.dump() for t in self.policy.triggers},
        })

    def _restore(self, now: float) -> None:
        d = read_json(self.runtime_path)
        if not d or d.get("v") != RUNTIME_VERSION:
            return
        try:
            self.last_flash_t = d.get("last_flash_t")
            self.flash_times = {k: list(v) for k, v in (d.get("flash_times") or {}).items()}
            pu = d.get("paused_until")
            self.paused_until = pu if pu and pu > now else None
            same_day = d.get("day") == self.day and bool(d.get("demo")) == self.P.demo
            for t in self.policy.triggers:
                td = (d.get("triggers") or {}).get(t.scene) or {}
                if same_day or t.scene == "C":
                    t.load(td)
            if same_day:
                self.ledger.water = float(d.get("water", 0))
                self.ledger.sitting = float(d.get("sitting", 0))
                self.eff.today_buckets = int(d.get("effective", 0))
                self.counts = d.get("counts") or {}
                self.flash_seq = int(d.get("flash_seq", 0))
                gap = now - float(d.get("saved", now))
                if gap > self.P.bucket_s:
                    ch = self.ledger.apply_lock(gap, self.P)
                    self.log.event("absence", kind="offline", duration_s=round(gap, 1),
                                   change=ch.as_dict() if ch else None)
            self.log.app(f"已恢复运行状态（同一天：{same_day}）")
        except (TypeError, ValueError):
            self.log.app("runtime.json 格式不对，已忽略", exc=True)
