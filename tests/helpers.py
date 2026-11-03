# -*- coding: utf-8 -*-
"""测试用的小工具：用假时钟 + 假世界搭一个 Engine，并按“下次唤醒时间”推进。"""

from __future__ import annotations

import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import config as config_mod  # noqa: E402
from core.clock import FakeClock  # noqa: E402
from core.engine import Engine  # noqa: E402
from core.eventlog import EventLog  # noqa: E402
from persona.lines import LinePicker  # noqa: E402
from signals.fake import FakeWorld  # noqa: E402

def read_text(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
        return fh.read()


def write_text(path, data, mode="w"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
        fh.write(data)


def read_json(path):
    import json
    return json.loads(read_text(path))


def write_json(path, data):
    import json
    write_text(path, json.dumps(data, ensure_ascii=False))


LINES = {"unlock_scold": ["A1"], "side_peek": ["B1"], "side_peek_water": ["BW"], "overtime_care": ["C1"]}


def at(hhmm: str, day: int = 2) -> float:
    """2026-11-<day> 的本地时刻 → epoch 秒。"""
    parts = [int(x) for x in hhmm.split(":")] + [0]
    return dt.datetime(2026, 11, day, parts[0], parts[1], parts[2]).timestamp()


class Display:
    def __init__(self, clock):
        self.clock = clock
        self.shown = []
        self.ok = True

    def show(self, req):
        if self.ok:
            self.shown.append((self.clock.now(), req))
        return self.ok

    def scenes(self):
        return [r.scene for _, r in self.shown if not r.demo]


class Rig:
    def __init__(self, start="08:59", over=None, log_dir=None, state_dir=None, restore=False, day=2):
        self.cfg = config_mod.from_dict(over or {})
        self.P = self.cfg.P
        self.day = day
        self.clock = FakeClock(at(start, day))
        self.world = FakeWorld(self.clock, input_lag=0.5 * self.P.scale)
        self.display = Display(self.clock)
        self.log = EventLog(log_dir, self.clock)
        self.log.keep_memory = True
        sp = os.path.join(state_dir, "state.json") if state_dir else None
        rp = os.path.join(state_dir, "data", "runtime.json") if state_dir else None
        self.e = Engine(self.cfg, self.clock, self.world.signals(), display=self.display, log=self.log,
                        lines=LinePicker(LINES), state_path=sp, runtime_path=rp, restore=restore)

    # ── 推进时间 ─────────────────────────────────────────────────────────
    def run_until(self, t: float):
        guard = 0
        while True:
            w = self.e.next_wake()
            if w >= t:          # 与 sim 一致：同一时刻先执行动作，再让内核醒来
                break
            self.clock.set(max(w, self.clock.now()))
            self.e.tick()
            guard += 1
            assert guard < 500000, "死循环？"
        self.clock.set(t)

    def to(self, hhmm: str, day: int | None = None):
        self.run_until(at(hhmm, self.day if day is None else day))

    # ── 动作 ─────────────────────────────────────────────────────────────
    def type(self, a: str, b: str, cat="productivity"):
        self.to(a)
        self.world.category = cat
        self.world.start_typing()
        self.e.on_foreground(cat)
        self.to(b)
        self.world.stop_typing()

    def lock(self, a: str, b: str):
        self.to(a)
        self.world.stop_typing()
        self.e.on_lock()
        self.to(b)
        self.e.on_unlock()

    def events(self, etype):
        return [r for r in self.log.memory if r.get("type") == etype]
