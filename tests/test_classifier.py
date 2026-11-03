# -*- coding: utf-8 -*-
"""第 6.3 节：状态识别与断点信号。"""

import unittest

from helpers import Rig, at

from core import classifier as C
from core import config as config_mod
from core.history import History

P = config_mod.from_dict().P
T0 = 1_000_000.0


def hist(inputs, cat="productivity", switches=()):
    """inputs：最近若干个已结束分钟是否有输入（从旧到新）。switches：[(距现在秒数, from, to)]"""
    h = History(P)
    for i, had in enumerate(inputs):
        h.add_bucket(T0 - (len(inputs) - i) * 60, had)
    h.category = cat
    for ago, frm, to in switches:
        h.category = frm
        h.record_foreground(T0 - ago, to)
    h.category = cat
    return h


class Moments(unittest.TestCase):
    def m(self, h, idle=0.0, cur=True):
        return C.classify_moment(T0, P, h, idle, cur)[:2]

    def test_flow(self):
        self.assertEqual(self.m(hist([True] * 9))[0], C.FLOW)

    def test_flow_needs_productivity(self):
        self.assertNotEqual(self.m(hist([True] * 9, cat="browser"))[0], C.FLOW)

    def test_flow_broken_by_switches(self):
        h = hist([True] * 9, switches=[(100, "productivity", "browser"), (90, "browser", "productivity"),
                                       (80, "productivity", "communication")])
        h.category = "productivity"
        self.assertNotEqual(self.m(h)[0], C.FLOW)

    def test_flow_needs_8_input_minutes(self):
        self.assertNotEqual(self.m(hist([True] * 6 + [False] * 3))[0], C.FLOW)

    def test_wander_by_switches(self):
        sw = [(250 - i * 40, "browser" if i % 2 else "communication", "communication" if i % 2 else "browser")
              for i in range(6)]
        self.assertEqual(self.m(hist([True] * 9, cat="browser", switches=sw))[0], C.WANDER)

    def test_wander_entertainment_sparse(self):
        self.assertEqual(self.m(hist([False] * 8 + [True], cat="entertainment"), cur=False)[0], C.WANDER)

    def test_entertainment_with_dense_input_is_not_wander(self):
        self.assertNotEqual(self.m(hist([True] * 9, cat="entertainment"))[0], C.WANDER)

    def test_burst_pause_break(self):
        h = hist([True] * 5 + [False] * 4, cat="other")
        self.assertEqual(self.m(h, idle=30, cur=False), (C.BREAK, "burst_pause"))
        self.assertEqual(self.m(h, idle=10, cur=False)[0], C.NORMAL)      # 停顿太短
        self.assertEqual(self.m(h, idle=100, cur=False)[0], C.NORMAL)     # 停顿太长
        h2 = hist([True] * 3 + [False] * 6, cat="other")
        self.assertEqual(self.m(h2, idle=30, cur=False)[0], C.NORMAL)     # 之前不够“爆发”

    def test_category_switch_break(self):
        h = hist([True] * 4, cat="browser", switches=[(30, "productivity", "browser")])
        self.assertEqual(self.m(h), (C.BREAK, "category_switch"))
        h = hist([True] * 4, cat="browser", switches=[(90, "productivity", "browser")])
        self.assertEqual(self.m(h)[0], C.NORMAL)                          # 超过 60 秒
        h = hist([True] * 4, cat="productivity", switches=[(30, "browser", "productivity")])
        self.assertEqual(self.m(h)[0], C.NORMAL)                          # 反方向不算

    def test_close_break(self):
        h = hist([True] * 4, cat="other")
        h.record_close(T0 - 5)
        self.assertEqual(self.m(h), (C.BREAK, "close"))
        h = hist([True] * 4, cat="other")
        h.record_close(T0 - 15)
        self.assertEqual(self.m(h)[0], C.NORMAL)

    def test_flow_hides_break_but_keeps_raw_signal(self):
        h = hist([True] * 9)
        moment, sig = self.m(h, idle=30, cur=False)
        self.assertEqual((moment, sig), (C.FLOW, "burst_pause"))


class Blockers(unittest.TestCase):
    def test_priority(self):
        h = hist([True] * 9)
        b = C.Blockers(meeting=True, fullscreen=True, dnd=True)
        self.assertEqual(C.classify(T0, P, h, 0, True, b).state, C.MEETING)
        b = C.Blockers(fullscreen=True, dnd=True)
        self.assertEqual(C.classify(T0, P, h, 0, True, b).state, C.FULLSCREEN)
        b = C.Blockers(dnd=True)
        self.assertEqual(C.classify(T0, P, h, 0, True, b).state, C.DND)
        self.assertEqual(C.classify(T0, P, h, 0, True, C.Blockers()).state, C.FLOW)

    def test_meeting_cooldown_2min(self):
        r = Rig()
        r.type("09:00", "09:10")
        r.world.set_mic(True)
        r.to("09:20")
        self.assertEqual(r.e.classify_now().state, C.MEETING)
        r.world.set_mic(False)
        r.to("09:21:59")
        self.assertEqual(r.e.classify_now().state, C.MEETING)
        r.to("09:22:01")
        self.assertNotEqual(r.e.classify_now().state, C.MEETING)


class Debounce(unittest.TestCase):
    def test_alt_tab_passes_merge(self):
        h = History(P)
        h.category = "productivity"
        h.record_foreground(T0, "browser")
        h.record_foreground(T0 + 0.5, "communication")
        h.record_foreground(T0 + 1.0, "entertainment")
        self.assertEqual(h.switch_count(T0 + 2, 600), 1)
        self.assertEqual((h.switches[-1].frm, h.switches[-1].to), ("productivity", "entertainment"))

    def test_round_trip_cancels(self):
        h = History(P)
        h.category = "productivity"
        h.record_foreground(T0, "browser")
        h.record_foreground(T0 + 0.5, "productivity")
        self.assertEqual(h.switch_count(T0 + 2, 600), 0)


if __name__ == "__main__":
    unittest.main()
