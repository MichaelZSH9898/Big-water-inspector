# -*- coding: utf-8 -*-
"""资源实测（第 3 节验收，M5）：对正在运行的哨兵进程采样，给出 RSS / CPU / 唤醒次数 / 日志占用。

    python tools/measure.py --label idle   --minutes 60     空闲 1 小时（人离开、别锁屏，或锁屏都行）
    python tools/measure.py --label office --minutes 60     正常办公 1 小时
    python tools/measure.py --flash                         演示一次三个场景，看闪现结束后 1 秒内是否回落

哨兵没在运行时会自动用 pythonw 启动它。需要 pip install psutil（只有本脚本用，哨兵不用）。
结果：tools/reports/measure-<label>-<时间>.csv（逐次采样）和 .json（汇总与是否达标）。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import psutil
except ImportError:
    print("需要 psutil：pip install psutil")
    sys.exit(2)

from winapi import autostart, ipc  # noqa: E402

REPORT_DIR = os.path.join(ROOT, "tools", "reports")
MAIN = os.path.join(ROOT, "main.py")
BUDGET = {"rss_mb": 40.0, "cpu_idle_pct": 0.3, "cpu_office_pct": 0.5, "log_mb": 20.0}


def find_sentinel():
    target = os.path.normcase(os.path.abspath(MAIN))
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = p.info["cmdline"] or []
            if any(os.path.normcase(os.path.abspath(c)) == target for c in cmd if c.endswith("main.py")):
                return p
        except (psutil.Error, OSError, ValueError):
            continue
    return None


def ensure_running():
    p = find_sentinel()
    if p:
        return p, False
    subprocess.Popen([autostart.pythonw(), MAIN], cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(40):
        time.sleep(0.25)
        p = find_sentinel()
        if p:
            time.sleep(5)          # 等它初始化完
            return p, True
    raise SystemExit("启动哨兵失败")


def read_ticks():
    try:
        with open(os.path.join(ROOT, "state.json"), encoding="utf-8") as fh:
            return json.load(fh).get("diag", {}).get("ticks")
    except (OSError, ValueError):
        return None


def dir_mb(d):
    total = 0
    for r, _, fs in os.walk(d):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return total / 1024 / 1024


def cpu_s(p):
    t = p.cpu_times()
    return t.user + t.system


def sample_period(p, minutes, interval, writer):
    ncpu = psutil.cpu_count() or 1
    t0, c0, k0 = time.time(), cpu_s(p), read_ticks()
    rss = []
    last_t, last_c = t0, c0
    end = t0 + minutes * 60
    while time.time() < end:
        time.sleep(interval)
        now, c = time.time(), cpu_s(p)
        mem = p.memory_info()
        r = mem.rss / 1024 / 1024
        rss.append(r)
        pct = (c - last_c) / max(1e-6, now - last_t) * 100
        writer.writerow([dt.datetime.now().strftime("%H:%M:%S"), round(r, 2), round(pct / ncpu, 4), round(pct, 4),
                         p.num_threads(), getattr(p, "num_handles", lambda: "")()])
        last_t, last_c = now, c
        print(f"\r{dt.datetime.now():%H:%M:%S}  RSS {r:6.2f} MB  CPU {pct / ncpu:6.3f}%（单核 {pct:6.3f}%）"
              f"  剩余 {int(end - now):5d} 秒", end="", flush=True)
    print()
    t1, c1, k1 = time.time(), cpu_s(p), read_ticks()
    wall = t1 - t0
    return {"minutes": round(wall / 60, 2), "rss_mb_max": round(max(rss), 2), "rss_mb_avg": round(sum(rss) / len(rss), 2),
            "cpu_pct_total_avg": round((c1 - c0) / wall * 100 / ncpu, 4),
            "cpu_pct_one_core_avg": round((c1 - c0) / wall * 100, 4), "cpu_count": ncpu,
            "wakeups_per_min": round((k1 - k0) / (wall / 60), 2) if k0 is not None and k1 is not None else None}


def analyze_flash(series, base_rss):
    """series: [(秒, rss_mb, cpu%)]。闪现期间 RSS 会因为图像缓冲上升；找最后一段“高于基线”的区间，
    看它结束后 1 秒内 RSS 是否回到基线（+0.5 MB 以内）、CPU 是否回到 0 附近。"""
    high = [t for t, r, _ in series if r > base_rss + 1.0]
    if not high:
        return {"flash_detected": False}
    last_high = max(high)
    after = [(t, r, c) for t, r, c in series if last_high < t <= last_high + 1.0]
    back = next((t for t, r, _ in after if r <= base_rss + 0.5), None)
    later_cpu = [c for t, _, c in series if last_high + 1.0 < t <= last_high + 4.0]
    return {"flash_detected": True, "last_flash_end_s": round(last_high, 2),
            "back_to_baseline_after_s": round(back - last_high, 2) if back is not None else None,
            "cpu_pct_1_4s_after_max": round(max(later_cpu), 3) if later_cpu else None,
            "back_to_idle_within_1s": back is not None and (max(later_cpu) if later_cpu else 0) < 0.5}


def flash_test(p, writer):
    """演示三个场景，50 ms 采样，看闪现结束后 1 秒内 RSS / CPU 是否回落。"""
    ncpu = psutil.cpu_count() or 1
    base = []
    for _ in range(5):
        time.sleep(0.2)
        base.append(p.memory_info().rss / 1024 / 1024)
    base_rss = sum(base) / len(base)
    ipc.request_demo()
    series = []
    t0 = time.time()
    last_c, last_t = cpu_s(p), t0
    while time.time() - t0 < 14:
        time.sleep(0.05)
        now, c = time.time(), cpu_s(p)
        r = p.memory_info().rss / 1024 / 1024
        pct = (c - last_c) / max(1e-6, now - last_t) * 100 / ncpu
        series.append((round(now - t0, 3), r, pct))
        writer.writerow([f"+{now - t0:.2f}s", round(r, 2), round(pct, 3), "", "", ""])
        last_c, last_t = c, now
    res = {"rss_baseline_mb": round(base_rss, 2), "rss_peak_mb": round(max(r for _, r, _ in series), 2),
           "rss_end_mb": round(series[-1][1], 2)}
    res.update(analyze_flash(series, base_rss))
    return res


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="idle", help="idle / office / 任意标签")
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--interval", type=float, default=5)
    ap.add_argument("--flash", action="store_true", help="只做闪现回落测试")
    a = ap.parse_args(argv)
    p, started = ensure_running()
    os.makedirs(REPORT_DIR, exist_ok=True)
    stamp = f"{dt.datetime.now():%Y%m%d-%H%M%S}"
    label = "flash" if a.flash else a.label
    csv_path = os.path.join(REPORT_DIR, f"measure-{label}-{stamp}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "rss_mb", "cpu_pct_total", "cpu_pct_one_core", "threads", "handles"])
        res = flash_test(p, w) if a.flash else sample_period(p, a.minutes, a.interval, w)
    res.update({"label": label, "pid": p.pid, "started_by_script": started, "log_dir_mb": round(dir_mb(os.path.join(ROOT, "logs")), 3),
                "time": stamp})
    if not a.flash:
        cpu_budget = BUDGET["cpu_office_pct"] if label == "office" else BUDGET["cpu_idle_pct"]
        res["pass"] = {"rss": res["rss_mb_max"] <= BUDGET["rss_mb"],
                       "cpu": res["cpu_pct_total_avg"] <= cpu_budget,
                       "log": res["log_dir_mb"] <= BUDGET["log_mb"]}
        res["budget"] = {"rss_mb": BUDGET["rss_mb"], "cpu_pct": cpu_budget, "log_mb": BUDGET["log_mb"]}
    json_path = csv_path[:-4] + ".json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    print("明细：", csv_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
