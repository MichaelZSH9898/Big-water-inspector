# -*- coding: utf-8 -*-
"""内核的其余部分：演示模式、持久化、睡眠推断、自适应采样、日志字段与隐私、state.json。"""

import json
import os
import tempfile
import unittest

from helpers import LINES, Rig, at, read_json, read_text

from core import config as config_mod
from persona.lines import LinePicker


class DemoMode(unittest.TestCase):
    def test_thresholds_scaled(self):
        P = config_mod.from_dict({"general": {"demo_mode": True}}).P
        self.assertAlmostEqual(P.bucket_s, 1.0)
        self.assertAlmostEqual(P.min_gap_s, 20.0)
        self.assertAlmostEqual(P.long_absence_s, 5.0)
        self.assertAlmostEqual(P.pause_min_s, 20 / 60)
        self.assertAlmostEqual(P.a_delay_s, 3.0)             # 体验类时长不缩放
        self.assertEqual(P.water_threshold, 60)              # 阈值按“分钟桶”计，桶变成 1 秒
        self.assertGreaterEqual(P.idle_near_s, 0.2)

    def test_demo_day_in_seconds(self):
        r = Rig(over={"general": {"demo_mode": True}})
        r.type("09:00", "09:01:10", cat="other")           # 70 个“分钟” = 70 秒；非生产力类 → 不是心流
        r.to("09:01:10")
        self.assertEqual(r.e.eff.today_minutes, 69)          # 第 70 个桶在 09:01:10.05 才结算
        self.assertEqual(r.display.scenes(), [])             # 久坐 70 ≥ 50，但还没有断点
        r.to("09:01:12")                                     # 停手 0.33–1.5 秒 = “爆发后停顿”
        self.assertEqual(r.display.scenes(), ["B"])


class Sampling(unittest.TestCase):
    def test_far_and_near_intervals(self):
        r = Rig()
        r.type("09:00", "09:10")
        self.assertAlmostEqual(r.e.idle_interval(), 30)
        r.type("09:10", "09:49")
        self.assertAlmostEqual(r.e.idle_interval(), 5)      # 久坐 49 ≥ 50-2

    def test_wakeups_per_hour_when_far(self):
        r = Rig(over={"policy": {"sitting_soft_min": 1000, "sitting_hard_min": 2000}})
        r.world.start_typing()
        r.to("09:00")
        n = 0
        orig = r.e.tick

        def counted():
            nonlocal n
            n += 1
            orig()
        r.e.tick = counted
        r.to("10:00")
        self.assertLessEqual(n, 125)        # 每分钟 2 次：桶边界（结算+决策+写状态）、半分钟采样

    def test_expensive_signals_only_on_decisions(self):
        r = Rig(over={"policy": {"sitting_soft_min": 1000, "sitting_hard_min": 2000}})
        r.type("09:00", "10:00")
        self.assertEqual(r.world.calls["audio"], 1)         # 只有启动后第一个无输入的分钟
        self.assertLessEqual(r.world.calls["miccam"], 62)   # 每分钟一次定时决策


class SleepInference(unittest.TestCase):
    def test_gap_without_power_event_treated_as_sleep(self):
        r = Rig()
        r.type("09:00", "09:30")
        r.clock.set(at("10:30"))           # 进程被挂起一小时，没收到任何事件
        r.e.tick()
        self.assertEqual(r.e.ledger.sitting, 0)
        self.assertEqual(r.e.eff.today_minutes, 30)
        ab = r.events("absence")
        self.assertEqual(ab[-1]["kind"], "gap")


class Persistence(unittest.TestCase):
    def test_restore_same_day_and_offline_gap(self):
        with tempfile.TemporaryDirectory() as d:
            r = Rig(state_dir=d)
            r.type("09:00", "10:00")
            r.to("10:00:30")
            r.e.write_state()
            st = read_json(os.path.join(d, "state.json"))
            self.assertEqual((st["water_min"], st["effective_today_min"], st["v"]), (60, 60, 1))
            # 3 分钟后重启 → 视同锁屏 3 分钟
            r2 = Rig(start="10:03", state_dir=d, restore=True)
            self.assertAlmostEqual(r2.e.ledger.water, 30)
            self.assertAlmostEqual(r2.e.ledger.sitting, 42)
            self.assertEqual(r2.e.eff.today_minutes, 60)

    def test_restore_other_day_resets(self):
        with tempfile.TemporaryDirectory() as d:
            r = Rig(state_dir=d)
            r.type("09:00", "10:41")                          # 10:40 出现过 B
            r.e.save_runtime()
            r2 = Rig(start="09:00", day=3, state_dir=d, restore=True)
            self.assertEqual((r2.e.ledger.water, r2.e.eff.today_minutes, r2.e.counts), (0, 0, {}))
            self.assertIsNotNone(r2.e.last_flash_t)           # 最小间隔、A 的频率上限跨天仍有效

    def test_state_json_has_no_titles_or_process_names(self):
        with tempfile.TemporaryDirectory() as d:
            r = Rig(state_dir=d)
            r.type("09:00", "10:00")
            r.e.write_state()
            txt = read_text(os.path.join(d, "state.json"))
            for bad in ("title", "exe", "process"):
                self.assertNotIn(bad, txt)


class EventFields(unittest.TestCase):
    def test_flash_event_fields(self):
        r = Rig()
        r.type("09:00", "10:41")
        f = r.events("flash")[0]
        for k in ("v", "ts", "day", "type", "id", "scene", "water", "sitting", "effective_today_min",
                  "state", "basis", "blocked", "block_reason", "result"):
            self.assertIn(k, f)
        self.assertEqual(f["v"], 1)
        self.assertEqual(f["result"], "pending")

    def test_blocked_candidates_logged_and_deduped(self):
        r = Rig()
        r.world.dnd = True
        r.type("09:00", "11:00")
        b = [x for x in r.events("blocked") if x["block_reason"] == "dnd"]
        self.assertTrue(1 <= len(b) <= 8)   # 60 分钟持续被挡，按 10 分钟去重

    def test_only_categories_in_logs(self):
        r = Rig()
        r.type("09:00", "10:41")
        blob = json.dumps(r.log.memory, ensure_ascii=False)
        self.assertNotIn(".exe", blob)
        self.assertNotIn("title", blob)


class Lines(unittest.TestCase):
    def test_no_consecutive_repeat(self):
        lp = LinePicker({"k": ["a", "b", "c"]})
        prev = None
        for _ in range(200):
            i, _ = lp.pick("k")
            self.assertNotEqual(i, prev)
            prev = i

    def test_single_line(self):
        lp = LinePicker(LINES)
        self.assertEqual(lp.pick("unlock_scold"), (0, "A1"))
        self.assertEqual(lp.pick("unlock_scold"), (0, "A1"))


class Reload(unittest.TestCase):
    def test_reload_keeps_ledger(self):
        r = Rig()
        r.type("09:00", "09:30")
        r.to("09:30:01")
        cfg = config_mod.from_dict({"policy": {"min_gap_min": 5}})
        r.e.reload(cfg)
        self.assertEqual(r.e.ledger.water, 30)
        self.assertAlmostEqual(r.e.P.min_gap_s, 300)

    def test_reload_into_demo_resets(self):
        r = Rig()
        r.type("09:00", "09:30")
        r.e.reload(config_mod.from_dict({"general": {"demo_mode": True}}))
        self.assertEqual(r.e.ledger.water, 0)


if __name__ == "__main__":
    unittest.main()
