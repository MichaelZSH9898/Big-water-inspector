# -*- coding: utf-8 -*-
"""事件日志（第 10 节）。

· logs/events.jsonl      当天（04:00 换日）的事件，一行一条 JSON；换日时改名为 events-YYYY-MM-DD.jsonl
· logs/daily.jsonl       每日摘要，一天一行
· logs/app.log           程序运行日志（报错、启动、重载），按大小轮转 1 MB × 2
· 保留 30 天；logs/ 总量 > 20 MB 时从最旧的归档开始删

隐私：日志里只出现应用“类别”，绝不出现窗口标题、进程名或任何窗口内容。
字段稳定、带版本号 v，供以后调参和训练简单模型。字段说明见 README。
"""

from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import traceback

from .clock import iso

SCHEMA_VERSION = 1
KEEP_DAYS = 30
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_DAY_BYTES = 4 * 1024 * 1024      # 单日上限：防止程序出 bug 时把磁盘写满
APP_LOG_BYTES = 1 * 1024 * 1024


class EventLog:
    def __init__(self, log_dir: str | None, clock, enabled: bool = True):
        self.dir = log_dir
        self.clock = clock
        self.enabled = enabled and log_dir is not None
        self.day: str | None = None
        self.memory: list[dict] = []     # 测试 / 模拟器里可直接检查
        self.keep_memory = log_dir is None
        if self.enabled:
            os.makedirs(self.dir, exist_ok=True)

    # ── 路径 ─────────────────────────────────────────────────────────────
    @property
    def events_path(self) -> str:
        return os.path.join(self.dir, "events.jsonl")

    @property
    def daily_path(self) -> str:
        return os.path.join(self.dir, "daily.jsonl")

    @property
    def app_path(self) -> str:
        return os.path.join(self.dir, "app.log")

    # ── 写事件 ───────────────────────────────────────────────────────────
    def event(self, etype: str, **fields) -> dict:
        rec = {"v": SCHEMA_VERSION, "ts": iso(self.clock.now()), "day": self.day, "type": etype}
        rec.update(fields)
        if self.keep_memory:
            self.memory.append(rec)
        if self.enabled:
            self._append(self.events_path, rec, guard=True)
        return rec

    def daily(self, summary: dict) -> None:
        rec = {"v": SCHEMA_VERSION, "type": "day_summary"}
        rec.update(summary)
        if self.keep_memory:
            self.memory.append(rec)
        if self.enabled:
            self._append(self.daily_path, rec, guard=False)

    def _append(self, path: str, rec: dict, guard: bool) -> None:
        try:
            if guard and os.path.exists(path) and os.path.getsize(path) > MAX_DAY_BYTES \
                    and rec.get("type") not in ("flash", "outcome", "app"):
                return
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            pass

    # ── 程序日志 ─────────────────────────────────────────────────────────
    def app(self, msg: str, exc: bool = False) -> None:
        line = f"{_dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
        if exc:
            line += "\n" + traceback.format_exc()
        if self.keep_memory:
            self.memory.append({"type": "app_log", "msg": line})
        if not self.enabled:
            return
        try:
            p = self.app_path
            if os.path.exists(p) and os.path.getsize(p) > APP_LOG_BYTES:
                os.replace(p, p + ".1")
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    # ── 轮转 ─────────────────────────────────────────────────────────────
    def rotate(self, new_day: str) -> None:
        """换日：把 events.jsonl 归档为前一天的文件，并清理过期 / 超量日志。"""
        old = self.day
        self.day = new_day
        if not self.enabled:
            return
        try:
            p = self.events_path
            if os.path.exists(p) and os.path.getsize(p) > 0 and old and old != new_day:
                dst = os.path.join(self.dir, f"events-{old}.jsonl")
                if os.path.exists(dst):            # 同一天重启过：追加
                    with open(p, "r", encoding="utf-8") as src, open(dst, "a", encoding="utf-8") as out:
                        out.write(src.read())
                    os.remove(p)
                else:
                    os.replace(p, dst)
            self.cleanup()
        except OSError:
            pass

    def adopt_day(self, day: str) -> None:
        """启动时：如果 events.jsonl 是更早某天留下的，先归档。"""
        if not self.enabled:
            self.day = day
            return
        p = self.events_path
        file_day = None
        try:
            if os.path.exists(p) and os.path.getsize(p) > 0:
                with open(p, "r", encoding="utf-8") as fh:
                    first = fh.readline()
                file_day = json.loads(first).get("day")
        except (OSError, ValueError):
            file_day = None
        if file_day and file_day != day:
            self.day = file_day
            self.rotate(day)
        else:
            self.day = day
            self.cleanup()

    def cleanup(self, today: _dt.date | None = None) -> None:
        if not self.enabled:
            return
        today = today or _dt.date.today()
        files = sorted(glob.glob(os.path.join(self.dir, "events-*.jsonl")))
        keep = []
        for f in files:
            stem = os.path.basename(f)[7:-6]
            try:
                d = _dt.date.fromisoformat(stem)
            except ValueError:
                continue
            if (today - d).days > KEEP_DAYS:
                _rm(f)
            else:
                keep.append(f)
        # 总量控制：从最旧的归档开始删
        total = _dir_size(self.dir)
        for f in keep:
            if total <= MAX_TOTAL_BYTES:
                break
            sz = _size(f)
            _rm(f)
            total -= sz
        # daily.jsonl 只留最近 400 行
        try:
            if os.path.exists(self.daily_path) and _size(self.daily_path) > 256 * 1024:
                with open(self.daily_path, "r", encoding="utf-8") as fh:
                    lines = fh.readlines()[-400:]
                with open(self.daily_path, "w", encoding="utf-8") as fh:
                    fh.writelines(lines)
        except OSError:
            pass


def _size(p: str) -> int:
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def _rm(p: str) -> None:
    try:
        os.remove(p)
    except OSError:
        pass


def _dir_size(d: str) -> int:
    total = 0
    for name in os.listdir(d):
        total += _size(os.path.join(d, name))
    return total
