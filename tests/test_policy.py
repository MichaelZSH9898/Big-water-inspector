# -*- coding: utf-8 -*-
"""第 6.4、7 节：决策参数与三个场景的触发规则。"""

import unittest

from helpers import Rig, at

NO_B = {"sitting_soft_min": 10000, "sitting_hard_min": 20000}


class SceneA(unittest.TestCase):
    def rig(self, **pol):
        r = Rig(over={"policy": {**NO_B, **pol}})
        r.type("09:00", "10:05")          # 饮水 65
        return r

    def test_unlock_after_long_lock_fires_after_3s(self):
        r = self.rig()
        r.lock("10:05", "10:11")
        r.to("10:11:02")
        self.assertEqual(r.display.scenes(), [])
        r.to("10:11:04")
        self.assertEqual(r.display.scenes(), ["A"])
        t, req = r.display.shown[0]
        self.assertAlmostEqual(t - at("10:11"), 3.0, places=3)
        self.assertEqual((req.pose, req.anchor, req.text), ("scold", "top_center", "A1"))

    def test_short_lock_no_a(self):
        r = self.rig()
        r.lock("10:05", "10:09")
        r.to("10:20")
        self.assertEqual(r.display.scenes(), [])

    def test_water_below_threshold_no_a(self):
        r = self.rig(water_threshold_min=100)
        r.lock("10:05", "10:30")
        r.to("10:40")
        self.assertEqual(r.display.scenes(), [])

    def test_meeting_at_recheck_abandons(self):
        r = self.rig()
        r.lock("10:05", "10:11")
        r.to("10:11:01")
        r.world.set_mic(True)
        r.to("10:11:30")
        r.world.set_mic(False)
        r.to("11:00")
        self.assertEqual(r.display.scenes(), [])
        b = r.events("blocked")
        self.assertEqual((b[-1]["scene"], b[-1]["block_reason"], b[-1]["result"]), ("A", "meeting", "abandoned"))

    def test_fullscreen_at_recheck_abandons(self):
        r = self.rig()
        r.lock("10:05", "10:11")
        r.world.fullscreen = True
        r.to("10:12")
        r.world.fullscreen = False
        r.to("11:00")
        self.assertEqual(r.display.scenes(), [])

    def test_cap_once_per_2h(self):
        r = self.rig()
        r.lock("10:05", "10:11")
        r.type("10:11", "10:40")
        r.lock("10:40", "10:50")          # 距上次 A 不到 2 小时 → 挡住
        r.type("10:50", "12:00")
        r.lock("12:00", "12:12")          # 已过 2 小时 → 出现
        r.to("12:13")
        self.assertEqual(r.display.scenes(), ["A", "A"])
        reasons = [b["block_reason"] for b in r.events("blocked") if b["scene"] == "A"]
        self.assertIn("cap", reasons)

    def test_sleep_counts_as_lock(self):
        r = self.rig()
        r.e.on_suspend()
        r.to("10:20")
        r.e.on_resume()
        r.to("10:20:05")
        self.assertEqual(r.display.scenes(), ["A"])


class SceneB(unittest.TestCase):
    def test_soft_threshold_waits_for_break(self):
        r = Rig()
        r.type("09:00", "09:55", cat="other")   # 不是生产力类 → 不是心流，但也没有断点
        r.to("09:55:10")
        self.assertEqual(r.display.scenes(), [])
        r.to("09:55:25")                         # 爆发后停顿 20 秒
        self.assertEqual(r.display.scenes(), ["B"])

    def test_flow_blocks_soft_but_not_hard(self):
        r = Rig()
        r.type("09:00", "10:39:30")
        self.assertEqual(r.display.scenes(), [])
        r.type("10:39:30", "10:41")
        self.assertEqual(r.display.scenes(), ["B"])
        self.assertTrue(r.display.shown[0][1].scene == "B")
        flash = r.events("flash")[0]
        self.assertTrue(flash["hard"])
        self.assertEqual(flash["state"], "flow")

    def test_peek_anchor_and_pose(self):
        r = Rig()
        r.type("09:00", "10:41")
        req = r.display.shown[0][1]
        self.assertEqual((req.pose, req.anchor), ("peek", "right_edge"))

    def test_hard_cap_blocked_by_meeting_then_first_break(self):
        r = Rig()
        r.type("09:00", "09:30")
        r.world.set_mic(True)
        r.type("09:30", "10:50")               # 10:40 到硬上限，会议中
        r.world.set_mic(False)
        r.type("10:50", "10:55")
        self.assertEqual(r.display.scenes(), [])   # 屏蔽解除后没有断点 → 继续等
        r.to("10:55:25")                       # 爆发后停顿
        self.assertEqual(r.display.scenes(), ["B"])

    def test_min_gap_20min(self):
        r = Rig()
        r.type("09:00", "10:41")               # 10:40 B（硬上限）
        r.type("10:41", "11:05")
        times = [t for t, q in r.display.shown]
        self.assertEqual(len(times), 2)
        self.assertAlmostEqual(times[1] - times[0], 20 * 60, delta=1)

    def test_line_variant_rule(self):
        r = Rig()
        r.type("09:00", "10:00")
        r.e.ledger.water = 59                     # 饮水未超 → 久坐台词
        r.to("10:00:01")
        r.e.on_foreground("browser")
        self.assertEqual(r.display.shown[-1][1].line_key, "side_peek")


class SceneC(unittest.TestCase):
    def rig(self):
        return Rig(start="07:59", over={"policy": {**NO_B, "water_threshold_min": 10000}})

    def test_needs_both_8h_and_1730(self):
        r = self.rig()
        r.type("08:00", "17:29")
        self.assertEqual(r.display.scenes(), [])
        r.type("17:29", "17:32")
        self.assertEqual(r.display.scenes(), ["C"])
        self.assertAlmostEqual(r.display.shown[0][0], at("17:30"), delta=1)
        req = r.display.shown[0][1]
        self.assertEqual((req.pose, req.anchor), ("care", "bottom_right"))

    def test_once_per_day(self):
        r = self.rig()
        r.type("08:00", "21:00")
        self.assertEqual(r.display.scenes(), ["C"])

    def test_blocked_then_made_up(self):
        r = self.rig()
        r.type("08:00", "17:20")
        r.world.dnd = True
        r.type("17:20", "18:00")
        self.assertEqual(r.display.scenes(), [])
        r.world.dnd = False
        r.type("18:00", "18:02")
        self.assertEqual(r.display.scenes(), ["C"])

    def test_not_shown_to_empty_chair(self):
        r = self.rig()
        r.type("08:00", "17:00")
        r.to("18:30")                              # 人走了（没锁屏）
        self.assertEqual(r.display.scenes(), [])
        r.type("18:30", "18:32")                   # 回来了 → 补上
        self.assertEqual(r.display.scenes(), ["C"])

    def test_after_midnight_still_same_day(self):
        r = Rig(start="15:59", over={"policy": {**NO_B, "water_threshold_min": 10000,
                                                "scene_c_after": "17:30"}})
        r.type("16:00", "23:00")
        self.assertEqual(r.display.scenes(), [])   # 只有 7 小时
        r.world.start_typing()
        r.run_until(at("01:05", 3))
        self.assertEqual(r.display.scenes(), ["C"])


class GlobalRules(unittest.TestCase):
    def test_quiet_hours(self):
        r = Rig(over={"policy": {"quiet_hours": [["10:30", "11:00"]]}})
        r.type("09:00", "11:05")
        t = [x for x, _ in r.display.shown]
        self.assertTrue(t and t[0] >= at("11:00"))

    def test_pause(self):
        r = Rig()
        r.type("09:00", "10:00")
        r.e.pause(3600)
        r.type("10:00", "11:00")
        self.assertEqual(r.display.scenes(), [])
        r.type("11:00", "11:02")
        self.assertEqual(r.display.scenes(), ["B"])

    def test_pause_until_tomorrow(self):
        r = Rig()
        r.e.pause_until_tomorrow()
        self.assertAlmostEqual(r.e.paused_until, at("04:00", 3))

    def test_dnd_blocks_everything(self):
        r = Rig()
        r.world.dnd = True
        r.type("09:00", "12:00")
        self.assertEqual(r.display.scenes(), [])

    def test_demo_all_ignores_rules_and_stats(self):
        r = Rig()
        r.world.dnd = True
        n = r.e.demo_all()
        self.assertEqual(n, 3)
        self.assertEqual([q.scene for _, q in r.display.shown], ["A", "B", "C"])
        self.assertEqual(r.e.counts, {})

    def test_new_trigger_registration(self):
        """新增场景 = 注册一个触发器 + 台词键。"""
        from core.policy import Candidate, Trigger

        class Stretch(Trigger):
            scene, name, pose, anchor, priority = "D", "stretch", "peek", "right_edge", 40

            def candidate(self, ctx):
                return Candidate(self, "每次决策都想出场", "stretch") if ctx.effective_today >= 3 else None

        r = Rig()
        r.e.policy.register(Stretch())
        r.e.lines.lines["stretch"] = ["伸个懒腰！"]
        r.type("09:00", "09:05")
        self.assertEqual(r.display.scenes(), ["D"])
        self.assertEqual(r.display.shown[0][1].text, "伸个懒腰！")


if __name__ == "__main__":
    unittest.main()
