# -*- coding: utf-8 -*-
"""第 10 节：日志轮转、保留 30 天、总量 ≤ 20 MB、每日摘要。"""

import datetime as dt
import json
import os
import tempfile
import unittest

from helpers import Rig, at, read_text, write_text

from core import eventlog
from core.clock import FakeClock
from core.eventlog import EventLog


class Rotation(unittest.TestCase):
    def test_rotate_archives_previous_day(self):
        with tempfile.TemporaryDirectory() as d:
            log = EventLog(d, FakeClock(at("10:00")))
            log.adopt_day("2026-11-02")
            log.event("flash", scene="B")
            log.rotate("2026-11-03")
            self.assertTrue(os.path.exists(os.path.join(d, "events-2026-11-02.jsonl")))
            self.assertFalse(os.path.exists(os.path.join(d, "events.jsonl")))

    def test_adopt_stale_file_on_startup(self):
        with tempfile.TemporaryDirectory() as d:
            log = EventLog(d, FakeClock(at("10:00")))
            log.adopt_day("2026-11-01")
            log.event("app", what="start")
            log2 = EventLog(d, FakeClock(at("10:00")))
            log2.adopt_day("2026-11-02")
            self.assertTrue(os.path.exists(os.path.join(d, "events-2026-11-01.jsonl")))

    def test_keep_30_days(self):
        with tempfile.TemporaryDirectory() as d:
            today = dt.date(2026, 11, 2)
            for i in range(40):
                day = today - dt.timedelta(days=i)
                write_text(os.path.join(d, f"events-{day}.jsonl"), "{}\n")
            log = EventLog(d, FakeClock(at("10:00")))
            log.cleanup(today)
            left = sorted(f for f in os.listdir(d) if f.startswith("events-"))
            self.assertEqual(len(left), 31)
            self.assertEqual(left[0], f"events-{today - dt.timedelta(days=30)}.jsonl")

    def test_total_size_cap(self):
        with tempfile.TemporaryDirectory() as d:
            today = dt.date(2026, 11, 2)
            old_cap = eventlog.MAX_TOTAL_BYTES
            eventlog.MAX_TOTAL_BYTES = 50_000
            try:
                for i in range(10):
                    day = today - dt.timedelta(days=i)
                    write_text(os.path.join(d, f"events-{day}.jsonl"), "x" * 10_000)
                EventLog(d, FakeClock(at("10:00"))).cleanup(today)
                total = sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d))
                self.assertLessEqual(total, 50_000)
                self.assertTrue(os.path.exists(os.path.join(d, f"events-{today}.jsonl")))
            finally:
                eventlog.MAX_TOTAL_BYTES = old_cap

    def test_app_log_rotates_by_size(self):
        with tempfile.TemporaryDirectory() as d:
            log = EventLog(d, FakeClock(at("10:00")))
            old = eventlog.APP_LOG_BYTES
            eventlog.APP_LOG_BYTES = 1000
            try:
                for i in range(100):
                    log.app("x" * 50)
                self.assertTrue(os.path.exists(os.path.join(d, "app.log.1")))
                self.assertLess(os.path.getsize(os.path.join(d, "app.log")), 2000)
            finally:
                eventlog.APP_LOG_BYTES = old


class DailySummary(unittest.TestCase):
    def test_summary_written_on_rollover(self):
        with tempfile.TemporaryDirectory() as d:
            r = Rig(start="16:59", log_dir=d)
            r.type("17:00", "19:00")
            r.lock("19:00", "19:01")
            r.run_until(at("04:01", 3))
            lines = read_text(os.path.join(d, "daily.jsonl")).splitlines()
            s = json.loads(lines[-1])
            self.assertEqual((s["day"], s["effective_min"], s["v"]), ("2026-11-02", 120, 1))
            self.assertIn("B", s["scenes"])
            for k in ("shown", "responded", "blocked"):
                self.assertIn(k, s["scenes"]["B"])
            self.assertTrue(os.path.exists(os.path.join(d, "events-2026-11-02.jsonl")))
            first = json.loads(read_text(os.path.join(d, "events.jsonl")).splitlines()[0])
            self.assertEqual(first["day"], "2026-11-03")


if __name__ == "__main__":
    unittest.main()
