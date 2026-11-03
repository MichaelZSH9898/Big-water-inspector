# -*- coding: utf-8 -*-
"""Windows 信号探针：把每个信号源此刻读到的值打印出来，并写一份 JSON 报告。

    python tools/probe_signals.py              读一次
    python tools/probe_signals.py --watch 90   每 2 秒读一次、持续 90 秒——期间去开关“勿扰/专注”、
                                               进出全屏视频、开个会议、放段音乐，看哪些值跟着变

用途：第 1 节要求“不确定的 Windows API 行为，先写最小验证脚本实测”。报告里只有数值和类别，
不含窗口标题；麦克风/摄像头只报数量，不报程序名。报告存到 tools/reports/。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import config as config_mod  # noqa: E402
from signals import audio, foreground, mic_cam, notify_state  # noqa: E402
from signals.categories import CategoryTable  # noqa: E402
from signals.idle import WinIdle  # noqa: E402
from winapi import monitors  # noqa: E402
from winapi.win32 import IS_WINDOWS, set_dpi_awareness, user32  # noqa: E402

REPORT_DIR = os.path.join(ROOT, "tools", "reports")


def toasts_registry():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings") as k:
            v, _ = winreg.QueryValueEx(k, "NOC_GLOBAL_SETTING_TOASTS_ENABLED")
            return int(v)
    except (OSError, ImportError):
        return None


def timed(fn):
    t = time.perf_counter()
    try:
        v = fn()
    except Exception as exc:  # noqa: BLE001
        v = f"ERROR: {exc!r}"
    return v, round((time.perf_counter() - t) * 1000, 2)


def snapshot(table: CategoryTable) -> dict:
    out, ms = {}, {}
    out["idle_s"], ms["idle"] = timed(lambda: round(WinIdle().idle_seconds(), 2))
    q, ms["quns"] = timed(notify_state.query_quns)
    out["quns"] = q
    out["quns_name"] = notify_state.QUNS.get(q) if isinstance(q, int) else None
    out["focus_assist_wnf"], ms["focus_wnf"] = timed(notify_state.focus_assist_profile)
    out["toasts_enabled_reg"], ms["toasts_reg"] = timed(toasts_registry)
    out["fg_covers_monitor"], ms["fg_fullscreen"] = timed(lambda: notify_state.foreground_covers_monitor() is not None)

    def fg_cat():
        h = user32.GetForegroundWindow()
        if not h:
            return None
        pid = foreground.DWORD(0)
        user32.GetWindowThreadProcessId(h, foreground.byref(pid))
        name = foreground.process_name(pid.value)
        title = foreground.window_title(h) if table.is_browser(name) else None
        cat = table.classify(name, title)
        del title
        return {"category": cat, "class": foreground.window_class(h),
                "ignored": foreground.window_class(h) in foreground.IGNORE_CLASSES}
    out["foreground"], ms["foreground"] = timed(fg_cat)

    def mc():
        in_use, last_stop, stale = mic_cam.scan()
        return {"in_use": len(in_use), "in_use_devices": sorted({c for c, _ in in_use}),
                "last_stop_ago_s": round(time.time() - last_stop, 1) if last_stop else None, "stale": len(stale)}
    out["mic_cam"], ms["mic_cam"] = timed(mc)
    peaks, ms["audio"] = timed(lambda: audio.peak_samples(5, 0.03))
    out["audio_peaks"] = [round(p, 5) for p in peaks] if isinstance(peaks, list) else peaks
    out["audio_playing"] = isinstance(peaks, list) and any(p > audio.PEAK_THRESHOLD for p in peaks)
    out["cost_ms"] = ms
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=0, help="持续观察多少秒（每 2 秒一次）")
    a = ap.parse_args(argv)
    if not IS_WINDOWS:
        print("只能在 Windows 上运行")
        return 2
    report = {"time": dt.datetime.now().isoformat(timespec="seconds"), "python": sys.version,
              "platform": platform.platform(), "windows_build": sys.getwindowsversion().build,
              "dpi_awareness": set_dpi_awareness()}
    audio.com_init()
    report["monitors"] = [m.__dict__ for m in monitors.all_monitors()]
    table = CategoryTable(config_mod.load().raw["categories"])
    first = snapshot(table)
    report["snapshot"] = first
    print(json.dumps(report, ensure_ascii=False, indent=1))
    samples = []
    if a.watch:
        print("\n时间      空闲s  QUNS               专注WNF  通知开关 前台铺满  前台类别        麦/摄 音频")
        end = time.time() + a.watch
        while time.time() < end:
            s = snapshot(table)
            s["t"] = dt.datetime.now().strftime("%H:%M:%S")
            samples.append(s)
            fg = s["foreground"] or {}
            print(f"{s['t']}  {s['idle_s']:>6}  {str(s['quns']) + ' ' + str(s['quns_name']):<18} "
                  f"{str(s['focus_assist_wnf']):<8} {str(s['toasts_enabled_reg']):<8} "
                  f"{str(s['fg_covers_monitor']):<9} {str(fg.get('category')):<15} "
                  f"{s['mic_cam']['in_use'] if isinstance(s['mic_cam'], dict) else s['mic_cam']:<5} "
                  f"{'有' if s['audio_playing'] else '无'}", flush=True)
            time.sleep(2)
        report["watch"] = samples
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"probe-{dt.datetime.now():%Y%m%d-%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("\n报告：", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
