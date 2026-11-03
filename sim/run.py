# -*- coding: utf-8 -*-
"""模拟器：回放脚本化的一天，驱动与真实哨兵完全相同的 Engine。

用法：
    python -m sim.run sim/scripts/typical_day.sim          # 打印时间线并核对预期
    python -m sim.run sim/scripts/typical_day.sim --quiet  # 只打印结论
    python -m sim.run sim/scripts/*.sim                    # 一次跑多个

脚本格式（一行一条，# 后为注释）：
    title   典型的一天
    date    2026-11-02
    start   08:50                       模拟开始时刻（此时哨兵启动，默认已解锁）
    end     23:00
    config  policy.min_gap_min=20       覆盖 config.toml 的任意参数（值按 TOML 语法）

  时间段动作（HH:MM 或 HH:MM:SS）：
    09:00-10:20  type     cat=productivity    持续输入；cat= 同时切换前台类别
    10:20-10:22  idle                         明确无输入
    13:00-13:30  video    fullscreen          无输入 + 有声音（+ 全屏）
    13:30-14:00  music                        无输入 + 有声音
    14:00-15:00  meeting  [type]              麦克风占用（可同时打字）
    15:00-15:10  present / dnd                全屏演示 / 系统勿扰

  时刻动作：
    lock / unlock / sleep / wake
    switch cat=browser                        前台切换到某类别的窗口
    close  cat=productivity                   关闭前台窗口（前台落到 cat 类别）
    tab    cat=entertainment                  浏览器里换标签页（等哨兵下次采样时发现）
    input                                     一次输入
    pause  60                                 托盘“暂停 60 分钟”；resume 取消暂停

  预期（不满足则退出码为 1）：
    expect 10:20 water=80 sitting=80 effective=80 state=flow
    expect_flash B 10:20-10:25                这段时间内应出现 B
    expect_no_flash 09:00-10:00 [B]           这段时间内不应出现（指定场景或任意）
    expect_total A=1 B=2 C=1                  全程各场景出现次数
    demo_skip 原因                            --demo 压缩回放时跳过本脚本（如跨天）
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import heapq
import io
import itertools
import os
import sys

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import config as config_mod  # noqa: E402
from core.clock import FakeClock  # noqa: E402
from core.engine import Engine  # noqa: E402
from core.eventlog import EventLog  # noqa: E402
from persona.lines import LinePicker  # noqa: E402
from signals.fake import FakeWorld  # noqa: E402

SCENE_NAMES = {"A": "解锁训话", "B": "侧边探头", "C": "加班关怀"}
DEFAULT_LINES = {
    "unlock_scold": ["多大人了，水都不知道喝？一天天就知道折腾你那个电脑！"],
    "side_peek": ["坐这多久了你，腰还要不要了！"],
    "side_peek_water": ["杯子都空了多久了，接水去！"],
    "overtime_care": ["今天又加班吗？要是来不及回家吃就点个外卖，辛苦一天别饿着自己"],
}


class SimDisplay:
    def __init__(self, clock):
        self.clock = clock
        self.shown: list[tuple[float, object]] = []

    def show(self, req) -> bool:
        self.shown.append((self.clock.now(), req))
        return True


class ScriptError(ValueError):
    pass


def _parse_time(base: dt.date, s: str) -> float:
    parts = [int(x) for x in s.split(":")]
    if len(parts) == 2:
        parts.append(0)
    h, m, sec = parts
    day = base + dt.timedelta(days=h // 24)
    return dt.datetime(day.year, day.month, day.day, h % 24, m, sec).timestamp()


def _fmt(t: float) -> str:
    return dt.datetime.fromtimestamp(t).strftime("%H:%M:%S")


def _kv(tokens):
    out, flags = {}, set()
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
        else:
            flags.add(tok)
    return out, flags


class Scenario:
    def __init__(self, path: str, extra_config: dict | None = None):
        self.path = path
        self.title = os.path.basename(path)
        self.date = dt.date(2026, 11, 2)
        self.start = None
        self.end = None
        self.config: dict = {}
        self.actions: list[tuple[float, int, str, dict, set]] = []
        self.expects: list = []
        self.extra_config = extra_config or {}
        self.demo_skip = ""
        self._seq = itertools.count()
        self._parse()

    def _parse(self):
        with open(self.path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        pending = []
        for no, raw in enumerate(lines, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            tok = line.split()
            head = tok[0]
            try:
                if head == "title":
                    self.title = line[len("title"):].strip()
                elif head == "date":
                    self.date = dt.date.fromisoformat(tok[1])
                elif head in ("start", "end"):
                    pending.append((head, tok[1]))
                elif head == "demo_skip":
                    self.demo_skip = line[len("demo_skip"):].strip() or "不适用"
                elif head == "config":
                    k, v = line[len("config"):].strip().split("=", 1)
                    val = tomllib.loads(f"x = {v.strip()}")["x"]
                    config_mod.set_dotted(self.config, k.strip(), val)
                elif head.startswith("expect"):
                    self.expects.append((no, head, tok[1:]))
                else:
                    self._parse_action(no, tok)
            except ScriptError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ScriptError(f"{self.path}:{no}: 看不懂这一行：{raw.strip()}（{exc}）") from exc
        for head, val in pending:
            setattr(self, head, _parse_time(self.date, val))
        if self.start is None or self.end is None:
            raise ScriptError(f"{self.path}: 缺少 start / end")

    def _add(self, t, kind, kv, flags):
        self.actions.append((t, next(self._seq), kind, kv, flags))

    def _parse_action(self, no, tok):
        when, kind, rest = tok[0], tok[1], tok[2:]
        kv, flags = _kv(rest)
        if "-" in when:
            a, b = when.split("-")
            ta, tb = _parse_time(self.date, a), _parse_time(self.date, b)
            if tb < ta:
                tb = _parse_time(self.date + dt.timedelta(days=1), b)
            self._add(ta, f"{kind}+", kv, flags)
            self._add(tb, f"{kind}-", kv, flags)
        else:
            self._add(_parse_time(self.date, when), kind, kv, flags)


class Simulator:
    """compress=True：演示模式回放——脚本里的时刻相对 start 压缩为 1/60（分钟变秒），
    同时打开 demo_mode，并把 scene_c_after 这类“时刻”参数按同样方式换算。"""

    def __init__(self, sc: Scenario, out=sys.stdout, verbose=True, compress=False):
        self.sc = sc
        self.out = out
        self.verbose = verbose
        self.compress = compress
        over = config_mod.deep_merge(sc.config, sc.extra_config)
        if compress:
            over = config_mod.deep_merge(over, {"general": {"demo_mode": True}})
            pol = over.setdefault("policy", {})
            c_after = pol.get("scene_c_after", config_mod.DEFAULTS["policy"]["scene_c_after"])
            pol["scene_c_after"] = self._compress_clock(c_after)
            pol["quiet_hours"] = [[self._compress_clock(a), self._compress_clock(b)]
                                  for a, b in pol.get("quiet_hours", [])]
        self.cfg = config_mod.from_dict(over)
        self.clock = FakeClock(sc.start)
        self.world = FakeWorld(self.clock, input_lag=0.5 * self.cfg.P.scale)
        self.display = SimDisplay(self.clock)
        self.log = EventLog(None, self.clock)
        self.engine = Engine(self.cfg, self.clock, self.world.signals(), display=self.display,
                             log=self.log, lines=LinePicker(DEFAULT_LINES), restore=False)
        self.failures: list[str] = []
        self.passes = 0

    @property
    def check_offset(self) -> float:
        """state 预期在该时刻之后多久核对（等这一分钟的桶结算完）。"""
        return max(1.0 * self.cfg.P.scale, 0.1)

    def T(self, t: float) -> float:
        """脚本时刻 → 模拟时刻。"""
        if not self.compress:
            return t
        return self.sc.start + (t - self.sc.start) / 60.0

    def _compress_clock(self, hhmm: str) -> str:
        base = dt.datetime.fromtimestamp(self.sc.start)
        h, m = (int(x) for x in hhmm.split(":")[:2])
        target = base.replace(hour=h, minute=m, second=0, microsecond=0)
        if target < base:
            target += dt.timedelta(days=1)
        t = self.T(target.timestamp())
        d = dt.datetime.fromtimestamp(t)
        return f"{d.hour:02d}:{d.minute:02d}:{d.second + d.microsecond / 1e6:06.3f}"

    # ── 动作 ─────────────────────────────────────────────────────────────
    def apply(self, kind: str, kv: dict, flags: set):
        w, e = self.world, self.engine
        cat = kv.get("cat")
        if kind == "type+":
            w.start_typing()
        elif kind == "type-":
            w.stop_typing()
        elif kind in ("idle+", "idle-"):
            w.stop_typing()
        elif kind == "video+":
            w.stop_typing()
            w.audio = True
            w.fullscreen = "fullscreen" in flags
        elif kind == "video-":
            w.audio = False
            w.fullscreen = False
        elif kind == "music+":
            w.stop_typing()
            w.audio = True
        elif kind == "music-":
            w.audio = False
        elif kind == "meeting+":
            w.set_mic(True)
            if "type" in flags:
                w.start_typing()
        elif kind == "meeting-":
            w.set_mic(False)
            w.stop_typing()
        elif kind == "present+":
            w.fullscreen = True
        elif kind == "present-":
            w.fullscreen = False
        elif kind == "dnd+":
            w.dnd = True
        elif kind == "dnd-":
            w.dnd = False
        elif kind == "lock":
            w.stop_typing()
            e.on_lock()
        elif kind == "unlock":
            e.on_unlock()
        elif kind == "sleep":
            w.stop_typing()
            e.on_suspend()
        elif kind == "wake":
            e.on_resume()
        elif kind == "switch":
            w.input_once()
            w.category = cat
            e.on_foreground(cat)
        elif kind == "close":
            w.input_once()
            if cat:
                w.category = cat
                e.on_foreground(cat)
            e.on_window_closed()
        elif kind == "tab":
            w.input_once()
            w.set_tab_category(cat)
        elif kind == "input":
            w.input_once()
        elif kind == "pause":
            e.pause(float(next(iter(flags))) * 60 * self.cfg.P.scale)
        elif kind == "resume":
            e.resume()
        else:
            raise ScriptError(f"未知动作：{kind}")
        if kind.endswith("+") and cat:          # 时间段动作带 cat=：世界状态就绪后再切换前台
            w.category = cat
            e.on_foreground(cat)

    # ── 主循环 ───────────────────────────────────────────────────────────
    def run(self) -> bool:
        sc = self.sc
        heap = [(self.T(t), seq, kind, kv, flags) for t, seq, kind, kv, flags in sc.actions]
        for no, head, args in sc.expects:
            if head == "expect":
                t = self.T(_parse_time(sc.date, args[0])) + self.check_offset
                heap.append((t, 10 ** 9 + no, "__expect__", {"no": no, "args": args[1:]}, set()))
        heapq.heapify(heap)
        end = self.T(sc.end)
        stuck = 0
        while True:
            tw = self.engine.next_wake()
            te = heap[0][0] if heap else float("inf")
            t = min(tw, te)
            if t > end:
                break
            if te > tw and tw <= self.clock.now():
                stuck += 1
                if stuck > 50:      # 内核要求“立刻再醒”却没有进展：报告并跳过，防止死循环
                    self._fail(f"内核在 {_fmt(self.clock.now())} 反复要求立即唤醒（可能的死循环）")
                    t = self.clock.now() + 0.01
                    stuck = 0
            else:
                stuck = 0
            self.clock.set(max(t, self.clock.now()))
            if te <= tw:
                _, _, kind, kv, flags = heapq.heappop(heap)
                if kind == "__expect__":
                    self.engine.tick()
                    self._check_state(kv["no"], kv["args"])
                else:
                    self.apply(kind, kv, flags)
            else:
                self.engine.tick()
        self.clock.set(end)
        self.engine.tick()
        self._check_flashes()
        return not self.failures

    # ── 核对 ─────────────────────────────────────────────────────────────
    def _ok(self, msg):
        self.passes += 1
        if self.verbose:
            print(f"  ✓ {msg}", file=self.out)

    def _fail(self, msg):
        self.failures.append(msg)
        print(f"  ✗ {msg}", file=self.out)

    def _check_state(self, no, args):
        snap = self.engine.snapshot()
        if any(a.startswith("state=") for a in args):
            cls = self.engine.classify_now()
            snap["state"] = cls.state
        when = _fmt(self.clock.now() - self.check_offset) + ("（压缩）" if self.compress else "")
        for a in args:
            k, v = a.split("=", 1)
            got = snap.get(k)
            if k in ("water", "sitting", "effective"):
                ok = got is not None and abs(float(got) - float(v)) <= 0.51
            else:
                ok = str(got) == v
            (self._ok if ok else self._fail)(f"[行{no}] {when} {k} 预期 {v}，实际 {got}")

    def _check_flashes(self):
        shown = [(t, r) for t, r in self.display.shown if not r.demo]
        for no, head, args in self.sc.expects:
            if head == "expect_flash":
                scene, rng = args[0], args[1]
                a, b = (self.T(_parse_time(self.sc.date, x)) for x in rng.split("-"))
                hit = [t for t, r in shown if r.scene == scene and a <= t <= b]
                (self._ok if hit else self._fail)(
                    f"[行{no}] {rng} 内应出现 {scene}：{'出现于 ' + _fmt(hit[0]) if hit else '没有出现'}")
            elif head == "expect_no_flash":
                rng = args[0]
                scenes = set(args[1:])
                a, b = (self.T(_parse_time(self.sc.date, x)) for x in rng.split("-"))
                hit = [(t, r.scene) for t, r in shown if a <= t <= b and (not scenes or r.scene in scenes)]
                (self._fail if hit else self._ok)(
                    f"[行{no}] {rng} 内不应出现 {'/'.join(sorted(scenes)) or '任何场景'}："
                    f"{'却在 ' + ', '.join(_fmt(t) + ' ' + s for t, s in hit) + ' 出现' if hit else '确实没有'}")
            elif head == "expect_total":
                for a in args:
                    k, v = a.split("=")
                    n = sum(1 for _, r in shown if r.scene == k)
                    (self._ok if n == int(v) else self._fail)(f"[行{no}] 全程 {k} 出现 {v} 次：实际 {n} 次")

    # ── 报告 ─────────────────────────────────────────────────────────────
    def report_timeline(self):
        out = self.out
        print(f"\n── 时间线：{self.sc.title} ──", file=out)
        for rec in self.log.memory:
            typ = rec.get("type")
            ts = rec.get("ts", "")[11:19]
            if typ == "flash":
                print(f"  {ts}  ★ 闪现 {rec['scene']} {SCENE_NAMES.get(rec['scene'], '')}"
                      f"（{rec['line']}）饮水 {rec['water']:.0f} / 久坐 {rec['sitting']:.0f} / "
                      f"有效 {rec['effective_today_min']} 分；状态 {rec['state']}；依据：{rec['basis']}", file=out)
            elif typ == "outcome":
                how = f"（{rec.get('how')}，{rec['after_s']:.0f} 秒后）" if rec.get("how") else ""
                print(f"  {ts}    ↳ {rec['ref']} {'响应' if rec['result'] == 'responded' else '未响应'}{how}",
                      file=out)
            elif typ == "blocked" and self.verbose:
                print(f"  {ts}  · 候选 {rec['scene']} 被挡：{rec['block_reason']}（{rec['basis']}）", file=out)
            elif typ == "absence":
                ch = rec.get("change") or {}
                tail = (f"饮水 {ch['water_before']:.0f}→{ch['water_after']:.0f}，"
                        f"久坐 {ch['sitting_before']:.0f}→{ch['sitting_after']:.0f}") if ch else "账本不变"
                print(f"  {ts}  ○ 离开 {rec['kind']} {rec['duration_s'] / 60:.1f} 分钟：{tail}", file=out)
            elif typ == "day_summary":
                print(f"  ── 日结 {rec['day']}：有效 {rec['effective_min']} 分钟 {rec['scenes']}", file=out)
        snap = self.engine.snapshot()
        print(f"  结束：饮水 {snap['water']:.0f} / 久坐 {snap['sitting']:.0f} / 今日有效 {snap['effective']} 分钟",
              file=out)


def run_file(path: str, verbose=True, out=sys.stdout, extra_config=None, compress=False):
    sc = Scenario(path, extra_config)
    if compress and sc.demo_skip:
        print(f"【演示模式 ×1/60】【{sc.title}】跳过：{sc.demo_skip}", file=out)
        return None
    sim = Simulator(sc, out=out, verbose=verbose, compress=compress)
    ok = sim.run()
    if verbose:
        sim.report_timeline()
    status = "通过" if ok else f"失败 {len(sim.failures)} 项"
    mode = "【演示模式 ×1/60】" if compress else ""
    print(f"{mode}【{sc.title}】核对 {sim.passes + len(sim.failures)} 项：{status}", file=out)
    return sim


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="回放脚本化的一天")
    ap.add_argument("scripts", nargs="+")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--demo", action="store_true",
                    help="演示模式回放：打开 demo_mode，脚本时间压缩为 1/60（分钟变秒）")
    a = ap.parse_args(argv)
    files = []
    for p in a.scripts:
        files.extend(sorted(glob.glob(p)) or [p])
    bad = 0
    for f in files:
        sim = run_file(f, verbose=not a.quiet, compress=a.demo)
        bad += bool(sim and sim.failures)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
