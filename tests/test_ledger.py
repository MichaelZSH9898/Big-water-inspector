# -*- coding: utf-8 -*-
"""第 6.2 节：两本账的每一条规则。"""

import unittest

from helpers import Rig

from core import config as config_mod
from core.ledger import Ledger

P = config_mod.from_dict().P


class LedgerUnit(unittest.TestCase):
    def filled(self, w=80, s=80):
        L = Ledger()
        L.water, L.sitting = float(w), float(s)
        return L

    def test_lock_5min_or_more_clears_sitting_keeps_water(self):
        L = self.filled()
        ch = L.apply_lock(5 * 60, P)
        self.assertEqual((L.water, L.sitting, ch.rule), (80, 0, "lock_long"))

    def test_lock_1_to_5min_cuts(self):
        L = self.filled()
        ch = L.apply_lock(3 * 60, P)
        self.assertAlmostEqual(L.water, 40)
        self.assertAlmostEqual(L.sitting, 56)
        self.assertEqual(ch.rule, "lock_short")
        L = self.filled()
        L.apply_lock(60, P)                       # 恰好 1 分钟也算
        self.assertAlmostEqual(L.water, 40)

    def test_lock_under_1min_no_change(self):
        L = self.filled()
        self.assertIsNone(L.apply_lock(59, P))
        self.assertEqual((L.water, L.sitting), (80, 80))

    def test_long_idle_clears_sitting_only(self):
        L = self.filled()
        L.apply_long_idle()
        self.assertEqual((L.water, L.sitting), (80, 0))

    def test_provisional_retract_and_confirm(self):
        L = self.filled(10, 10)
        L.add_minute(provisional=True)
        L.add_minute(provisional=True)
        self.assertEqual(L.retract(), 2)
        self.assertEqual((L.water, L.sitting), (10, 10))
        L.add_minute(provisional=True)
        L.confirm()
        self.assertEqual(L.retract(), 0)
        self.assertEqual(L.water, 11)

    def test_clear_after_provisional_only_retracts_new_minutes(self):
        L = self.filled(10, 10)
        L.add_minute(provisional=True)
        L.clear("sitting")
        L.add_minute(provisional=True)
        L.retract()
        self.assertEqual((L.water, L.sitting), (10, 0))


class LedgerEngine(unittest.TestCase):
    """在完整的 engine 里核对：表格每一行。"""

    def setUp(self):
        self.r = Rig(over={"policy": {"sitting_soft_min": 1000, "sitting_hard_min": 2000,
                                      "water_threshold_min": 1000}})
        self.r.type("09:00", "10:00")
        self.r.to("10:00:01")
        self.assertEqual((self.r.e.ledger.water, self.r.e.ledger.sitting), (60, 60))

    def test_row1_lock_6min(self):
        self.r.lock("10:00:01", "10:06:01")
        self.assertEqual((self.r.e.ledger.water, self.r.e.ledger.sitting), (60, 0))

    def test_row1_sleep_6min_same_as_lock(self):
        r = self.r
        r.e.on_suspend()
        r.to("10:06:01")
        r.e.on_resume()
        self.assertEqual((r.e.ledger.water, r.e.ledger.sitting), (60, 0))

    def test_row2_unlocked_silent_5min(self):
        self.r.to("10:05:01")
        self.assertEqual((self.r.e.ledger.water, self.r.e.ledger.sitting), (60, 0))

    def test_row3_lock_3min(self):
        self.r.lock("10:00:01", "10:03:01")
        self.assertAlmostEqual(self.r.e.ledger.water, 30)
        self.assertAlmostEqual(self.r.e.ledger.sitting, 42)

    def test_row4_unlocked_idle_3min_no_cut(self):
        r = self.r
        r.to("10:03:01")
        self.assertEqual((r.e.ledger.water, r.e.ledger.sitting), (63, 63))   # 暂记的 3 分钟
        r.type("10:03:01", "10:10")
        r.to("10:10:01")
        self.assertEqual((r.e.ledger.water, r.e.ledger.sitting), (70, 70))

    def test_lock_and_sleep_overlap_counted_once(self):
        r = self.r
        r.e.on_lock()
        r.to("10:01:00")
        r.e.on_suspend()
        r.to("10:30:00")
        r.e.on_resume()
        self.assertEqual(r.e.ledger.sitting, 60)     # 仍锁着：还没结算
        r.e.on_unlock()
        self.assertEqual((r.e.ledger.water, r.e.ledger.sitting), (60, 0))
        self.assertEqual(len(r.events("absence")), 1)


class ResponseRule(unittest.TestCase):
    """场景 A/B 出现后 10 分钟内锁屏或 ≥ 2 分钟无输入 → 响应，对应的账清零。"""

    def rig(self):
        r = Rig(over={"policy": {"sitting_hard_min": 2000}})
        r.type("09:00", "10:00")
        r.world.category = "productivity"
        r.to("10:00:01")
        r.world.input_once()
        r.e.on_foreground("browser")       # 类别切换 → B
        self.assertEqual(r.display.scenes(), ["B"])
        return r

    def test_lock_within_10min_is_response(self):
        r = self.rig()
        r.type("10:00:02", "10:04")
        r.lock("10:04", "10:04:30")
        out = r.events("outcome")
        self.assertEqual(out[-1]["result"], "responded")
        self.assertEqual(out[-1]["how"], "lock")
        self.assertEqual(r.e.ledger.sitting, 0)
        self.assertEqual(r.e.ledger.water, 64)

    def test_two_minutes_idle_is_response(self):
        r = self.rig()
        r.type("10:00:02", "10:03")
        r.to("10:05:10")
        out = r.events("outcome")
        self.assertEqual((out[-1]["result"], out[-1]["how"]), ("responded", "idle"))
        self.assertLess(r.e.ledger.sitting, 3)

    def test_no_response_within_10min(self):
        r = self.rig()
        r.type("10:00:02", "10:20")
        out = r.events("outcome")
        self.assertEqual(out[-1]["result"], "ignored")
        self.assertGreater(r.e.ledger.sitting, 70)

    def test_water_variant_clears_water(self):
        r = Rig(over={"policy": {"sitting_hard_min": 2000}})
        r.type("09:00", "10:00")
        r.e.ledger.water = 200                 # 饮水超得比久坐多 → 饮水台词
        r.to("10:00:01")
        r.e.on_foreground("browser")
        self.assertEqual(r.display.shown[-1][1].line_key, "side_peek_water")
        r.lock("10:01", "10:01:30")
        self.assertEqual(r.e.ledger.water, 0)
        self.assertEqual(r.e.ledger.sitting, 61)


if __name__ == "__main__":
    unittest.main()
