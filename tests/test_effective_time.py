# -*- coding: utf-8 -*-
"""第 6.1 节：有效使用时长。"""

import unittest

from helpers import Rig, at

from core import config as config_mod
from core.effective_time import AUDIO, AWAY, IDLE_PROV, INPUT, LOCKED, EffectiveTime


def ET(**over):
    return EffectiveTime(config_mod.from_dict(over).P)


class EffectiveTimeUnit(unittest.TestCase):
    def close(self, et, i, had=False, absent=False, ref=None, audio=False, fs=False):
        start = i * 60.0
        return et.close_bucket(start, start + 60, had, absent, ref, lambda: audio, lambda: fs)

    def test_input_minute_counts(self):
        et = ET()
        r = self.close(et, 0, had=True, ref=10)
        self.assertEqual((r.kind, r.counted), (INPUT, True))
        self.assertEqual(et.today_minutes, 1)

    def test_audio_with_recent_input_counts(self):
        et = ET()
        r = self.close(et, 10, ref=11 * 60 - 19 * 60, audio=True)   # 这一分钟结束时距上次输入 19 分钟
        self.assertEqual(r.kind, AUDIO)

    def test_audio_without_recent_input_needs_fullscreen(self):
        et = ET()
        ref = 0.0
        r = self.close(et, 30, ref=ref, audio=True, fs=False)        # 距上次输入 31 分钟、未全屏
        self.assertNotEqual(r.kind, AUDIO)
        r = self.close(et, 31, ref=ref, audio=True, fs=True)         # 全屏看视频
        self.assertEqual(r.kind, AUDIO)

    def test_short_idle_provisional_then_confirmed(self):
        et = ET()
        self.close(et, 0, had=True, ref=59)
        for i in range(1, 5):                                         # 4 分钟无输入
            r = self.close(et, i, ref=59)
            self.assertEqual(r.kind, IDLE_PROV)
        self.assertEqual(et.today_minutes, 5)
        self.close(et, 5, had=True, ref=5 * 60 + 1)                   # 恢复输入：暂记转正
        self.assertEqual(et.today_minutes, 6)
        self.assertEqual(et.prov_buckets, 0)

    def test_five_idle_minutes_retracted(self):
        et = ET()
        self.close(et, 0, had=True, ref=59)
        for i in range(1, 5):
            self.close(et, i, ref=59)
        r = self.close(et, 5, ref=59)                                 # 第 5 分钟：回溯
        self.assertTrue(r.long_idle)
        self.assertEqual(r.retracted, 4)
        self.assertEqual(r.kind, AWAY)
        self.assertEqual(et.today_minutes, 1)
        r = self.close(et, 6, ref=59)                                 # 之后直接记离开
        self.assertEqual((r.kind, r.counted, r.long_idle), (AWAY, False, False))

    def test_strict_mode_idle_is_away_immediately(self):
        et = ET(effective={"count_short_idle": False})
        self.close(et, 0, had=True, ref=59)
        r = self.close(et, 1, ref=59)
        self.assertEqual((r.kind, r.counted), (AWAY, False))
        for i in range(2, 6):
            r = self.close(et, i, ref=59)
        self.assertTrue(r.long_idle)

    def test_locked_minutes_never_count(self):
        et = ET()
        r = self.close(et, 0, absent=True, audio=True, fs=True)
        self.assertEqual((r.kind, r.counted), (LOCKED, False))

    def test_audio_only_queried_without_input(self):
        et = ET()
        calls = []
        et.close_bucket(0, 60, True, False, 30, lambda: calls.append(1) or True, lambda: False)
        self.assertEqual(calls, [])
        et.close_bucket(60, 120, False, False, 30, lambda: calls.append(1) or False, lambda: False)
        self.assertEqual(calls, [1])

    def test_never_seen_input_is_away(self):
        et = ET()
        r = self.close(et, 0, ref=None)
        self.assertEqual(r.kind, AWAY)


class EffectiveTimeEngine(unittest.TestCase):
    def test_minutes_with_input_are_exact(self):
        r = Rig()
        r.type("09:00", "09:30")
        r.to("09:30:01")
        self.assertEqual(r.e.eff.today_minutes, 30)

    def test_unlocked_nap_not_counted(self):
        r = Rig()
        r.type("09:00", "10:00")
        r.to("12:00")
        self.assertEqual(r.e.eff.today_minutes, 60)

    def test_lock_period_not_counted(self):
        r = Rig()
        r.type("09:00", "09:10")
        r.lock("09:10", "09:40")
        r.to("09:40:01")
        self.assertEqual(r.e.eff.today_minutes, 10)

    def test_fullscreen_video_counts(self):
        r = Rig()
        r.type("09:00", "09:10")
        r.world.audio = True
        r.world.fullscreen = True
        r.to("10:10")
        r.to("10:10:01")
        self.assertEqual(r.e.eff.today_minutes, 70)

    def test_background_music_after_20min_not_counted(self):
        r = Rig()
        r.type("09:00", "09:10")
        r.world.audio = True                     # 只开着音乐、人走了
        r.to("10:10:01")
        # 09:10–09:28 有声音且距上次输入 < 20 分钟 → 计入（19 分钟）；之后不计，
        # 且此时距上次输入已满 5 分钟 → 直接按“长时间离开”处理（DECISIONS D-10）
        self.assertEqual(r.e.eff.today_minutes, 29)
        self.assertEqual(r.e.ledger.sitting, 0)

    def test_daily_reset_at_4am(self):
        r = Rig(start="23:00")
        r.type("23:01", "23:31")
        r.to("23:31:01")
        self.assertEqual(r.e.eff.today_minutes, 30)
        r.world.start_typing()
        r.run_until(at("03:59:30", 3))
        self.assertGreater(r.e.eff.today_minutes, 200)
        r.run_until(at("04:00:30", 3))
        self.assertEqual(r.e.day, "2026-11-03")
        self.assertLessEqual(r.e.eff.today_minutes, 1)
        self.assertEqual(len(r.events("day_summary")), 1)


if __name__ == "__main__":
    unittest.main()
