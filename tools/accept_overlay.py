# -*- coding: utf-8 -*-
"""M2 验收：闪现窗口不抢焦点、不丢字、鼠标穿透（第 8 节两条验收），外加样式与位置检查。

    python tools/accept_overlay.py           自动跑：打字测试 + 点击穿透测试 + 窗口样式检查
    python tools/accept_overlay.py --tour    在每块显示器上依次闪现 A/B/C，打印位置与尺寸（目测 DPI/多屏）
    python tools/accept_overlay.py --tour --hold 8    同上，每个场景停 8 秒，方便看清楚立绘和气泡

做法：开一个测试窗口（里面一个文本框、一个按钮），用 SendInput 模拟真实键盘/鼠标输入：
  · 打字：闪现出现前开始、结束后才停，逐字核对文本框里的内容；同时检查前台窗口始终是测试窗口。
  · 点击：把按钮放到闪现窗口正下方，闪现期间点击按钮中心，按钮必须收到点击。
运行期间请不要动键鼠（约 15 秒）。结果写到 tools/reports/。
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import json
import os
import sys
import threading
import time
import tkinter as tk
from ctypes import Structure, Union, byref, c_long, c_size_t, c_ulong, c_ushort, sizeof

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import config as config_mod  # noqa: E402
from core.engine import FlashRequest  # noqa: E402
from overlay.image_cache import ImageCache  # noqa: E402
from overlay.layered_window import EX_STYLE, Overlay, place  # noqa: E402
from persona import cachekey  # noqa: E402
from persona.loader import load_with_fallback  # noqa: E402
from winapi import monitors as mon_mod  # noqa: E402
from winapi.msgwindow import MessageWindow  # noqa: E402
from winapi.win32 import POINT, set_dpi_awareness, user32  # noqa: E402

REPORT_DIR = os.path.join(ROOT, "tools", "reports")
GWL_EXSTYLE = -20
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004


class MOUSEINPUT(Structure):
    _fields_ = [("dx", c_long), ("dy", c_long), ("mouseData", c_ulong), ("dwFlags", c_ulong),
                ("time", c_ulong), ("dwExtraInfo", c_size_t)]


class KEYBDINPUT(Structure):
    _fields_ = [("wVk", c_ushort), ("wScan", c_ushort), ("dwFlags", c_ulong), ("time", c_ulong),
                ("dwExtraInfo", c_size_t)]


class _U(Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", c_ulong), ("u", _U)]


user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = ctypes.c_uint
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.GetAncestor.restype = ctypes.c_void_p


def send_char(ch: str) -> None:
    arr = (INPUT * 2)()
    for i, flags in enumerate((KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)):
        arr[i].type = INPUT_KEYBOARD
        arr[i].ki = KEYBDINPUT(0, ord(ch), flags, 0, 0)
    user32.SendInput(2, arr, sizeof(INPUT))


def click_at(x: int, y: int) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    arr = (INPUT * 2)()
    for i, flags in enumerate((MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)):
        arr[i].type = INPUT_MOUSE
        arr[i].mi = MOUSEINPUT(0, 0, 0, flags, 0, 0)
    user32.SendInput(2, arr, sizeof(INPUT))


def ensure_cache(cfg) -> ImageCache:
    persona, _ = load_with_fallback(cfg.persona)
    cache = ImageCache()
    cache.set_expected(cachekey.variant_key(persona, cfg), cfg.language)
    sizes = mon_mod.monitor_sizes()
    if not cache.has_exact(sizes):
        try:
            from persona import render
            print("正在为当前显示器渲染立绘缓存……")
            render.ensure(cfg, sizes, persona)
        except ImportError:
            print("没有 Pillow，使用最接近的预置尺寸")
    return cache


HOLD_S = 1.5          # --hold 可以让每个场景多停一会儿，方便截图、目测


def req(scene: str) -> FlashRequest:
    spec = {"A": ("unlock_scold", "scold", "unlock_scold", "top_center"),
            "B": ("side_peek", "peek", "side_peek", "right_edge"),
            "C": ("overtime_care", "care", "overtime_care", "bottom_right")}[scene]
    return FlashRequest(scene, spec[0], spec[1], spec[2], 0, "", spec[3], HOLD_S, 0.5, demo=False)


class Acceptance:
    TEXT = "The quick brown fox jumps over the lazy dog 0123456789 " \
           "大水理论督察员不抢焦点也不丢字 ~!@#$%^&*()_+-=[]{};:,./<>? END"

    def __init__(self, root: tk.Tk, cache: ImageCache, report: dict):
        self.root = root
        self.report = report
        self.win = MessageWindow("WaterInspector.AcceptTest", "accept", lambda m, w, l: None)
        self.overlay = Overlay(self.win, cache)
        self.clicks = 0
        self.fg_samples = []

    def run(self):
        r = self.root
        r.title("大水理论督察员 · 闪现验收（请勿操作键鼠）")
        m = mon_mod.foreground_monitor() or mon_mod.all_monitors()[0]
        w, h = int(m.width * 0.5), int(m.height * 0.5)
        r.geometry(f"{w}x{h}+{m.left + (m.width - w) // 2}+{m.top + int(m.height * 0.08)}")
        self.text = tk.Text(r, font=("Consolas", 14), wrap="char")
        self.text.pack(fill="both", expand=True)
        r.after(800, self.start_typing)

    # ── 1. 打字不丢字、不抢焦点 ─────────────────────────────────────────
    def start_typing(self):
        self.root.lift()
        self.root.focus_force()
        self.text.focus_set()
        self.root_hwnd = user32.GetAncestor(self.text.winfo_id(), 2)   # GA_ROOT
        self.root.after(300, self._type_and_flash)

    def _type_and_flash(self):
        def typer():
            for ch in self.TEXT:
                send_char(ch)
                time.sleep(0.02)
        self.t_type0 = time.time()
        threading.Thread(target=typer, daemon=True).start()
        self.root.after(400, self._flash_for_typing)
        for k in range(1, 12):
            self.root.after(400 + k * 200, self._sample_fg)
        self.root.after(int(len(self.TEXT) * 21) + 1500, self._check_typing)

    def _flash_for_typing(self):
        ok = self.overlay.show(req("A"))
        info = dict(self.overlay.last_info)
        hwnd = info.get("hwnd")
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) if hwnd else 0
        self.report["flash_shown"] = ok
        self.report["flash_geometry"] = {k: info.get(k) for k in ("x", "y", "w", "h", "exact_size", "monitor")}
        self.report["ex_style_ok"] = bool(hwnd) and (style & EX_STYLE) == EX_STYLE
        self.report["ex_style"] = hex(style)

    def _sample_fg(self):
        self.fg_samples.append(user32.GetForegroundWindow() == self.root_hwnd)

    def _check_typing(self):
        got = self.text.get("1.0", "end-1c")
        self.report["typing"] = {"expected_len": len(self.TEXT), "got_len": len(got), "identical": got == self.TEXT,
                                 "focus_kept_all_samples": all(self.fg_samples), "samples": len(self.fg_samples)}
        if got != self.TEXT:
            self.report["typing"]["diff_at"] = next((i for i, (a, b) in enumerate(zip(got, self.TEXT)) if a != b),
                                                    min(len(got), len(self.TEXT)))
        self.root.after(800, self.start_click_test)

    # ── 2. 鼠标穿透 ─────────────────────────────────────────────────────
    def start_click_test(self):
        m = mon_mod.foreground_monitor()
        # 先算出闪现窗口会出现在哪里，再把按钮放到它的正中间
        path, _ = self.overlay.cache.lookup("unlock_scold", 0, m.height, m.dpi)
        w, h, _ = self.overlay.cache.load(path)
        x, y = place("top_center", w, h, m)
        self.target = (x + w // 2, y + h // 2)
        self.btn_win = tk.Toplevel(self.root)
        self.btn_win.overrideredirect(True)
        bw, bh = 220, 90
        self.btn_win.geometry(f"{bw}x{bh}+{self.target[0] - bw // 2}+{self.target[1] - bh // 2}")
        tk.Button(self.btn_win, text="点我（应能点到）", command=self._clicked).pack(fill="both", expand=True)
        self.btn_win.lift()
        self.root.after(500, self._flash_for_click)

    def _clicked(self):
        self.clicks += 1

    def _flash_for_click(self):
        pt = POINT()
        user32.GetCursorPos(byref(pt))
        self.cursor_was = (pt.x, pt.y)
        self.overlay.show(req("A"))
        self.root.after(700, self._do_click)

    def _do_click(self):
        hit = user32.WindowFromPoint(POINT(*self.target))
        flash = self.overlay.last_info.get("hwnd")
        self.report["window_from_point_is_flash"] = bool(hit) and hit == flash
        click_at(*self.target)
        self.root.after(1800, self._finish)

    def _finish(self):
        user32.SetCursorPos(*self.cursor_was)
        self.report["click_through"] = {"clicks_received": self.clicks, "ok": self.clicks == 1}
        t = self.report["typing"]
        self.report["PASS"] = bool(self.report.get("flash_shown") and self.report.get("ex_style_ok") and
                                   t["identical"] and t["focus_kept_all_samples"] and self.clicks == 1)
        self.root.destroy()


def tour(root: tk.Tk, cache: ImageCache, report: dict):
    """每块显示器 × 三个场景：把一个小窗口放到该显示器上当前台，闪现，记录位置。"""
    win = MessageWindow("WaterInspector.Tour", "tour", lambda m, w, l: None)
    ov = Overlay(win, cache)
    mons = mon_mod.all_monitors()
    steps = [(m, s) for m in mons for s in "ABC"]
    report["tour"] = []
    root.title("巡检中……")

    def step(i=0):
        if i >= len(steps):
            root.after(2500, root.destroy)
            return
        m, s = steps[i]
        root.geometry(f"360x120+{m.left + 40}+{m.top + 40}")
        root.lift()
        root.focus_force()

        def go():
            ov.show(req(s))
            info = dict(ov.last_info)
            info["monitor_rect"] = (m.left, m.top, m.right, m.bottom)
            info["monitor_dpi"] = m.dpi
            info["figure_ratio_approx"] = round(info.get("h", 0) / m.height, 3)
            info["inside_monitor"] = (m.left <= info.get("x", -1) and info.get("x", 0) + info.get("w", 0) <= m.right
                                      and m.top <= info.get("y", -1) and info.get("y", 0) + info.get("h", 0) <= m.bottom)
            info.pop("hwnd", None)
            report["tour"].append({"scene": s, **info})
            print(f"显示器 {m.width}x{m.height}@{m.dpi}dpi 场景 {s}：位置 ({info.get('x')},{info.get('y')}) "
                  f"尺寸 {info.get('w')}x{info.get('h')}（高度占屏 {info['figure_ratio_approx']:.0%}，"
                  f"精确尺寸 {info.get('exact_size')}，在屏内 {info['inside_monitor']}）", flush=True)
            root.after(int((HOLD_S + 1.1) * 1000), lambda: step(i + 1))
        root.after(400, go)
    step()


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--tour", action="store_true")
    ap.add_argument("--hold", type=float, default=1.5, help="巡检时每个场景停留的秒数")
    a = ap.parse_args(argv)
    global HOLD_S
    HOLD_S = max(0.5, a.hold) if a.tour else 1.5
    report = {"time": dt.datetime.now().isoformat(timespec="seconds"), "dpi_awareness": set_dpi_awareness()}
    cfg = config_mod.load()
    cache = ensure_cache(cfg)
    report["monitors"] = [m.__dict__ for m in mon_mod.all_monitors()]
    root = tk.Tk()
    if a.tour:
        tour(root, cache, report)
    else:
        Acceptance(root, cache, report).run()
    root.mainloop()
    os.makedirs(REPORT_DIR, exist_ok=True)
    name = "tour" if a.tour else "accept"
    path = os.path.join(REPORT_DIR, f"{name}-{dt.datetime.now():%Y%m%d-%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    if not a.tour:
        t = report.get("typing", {})
        print(f"闪现窗口样式（5 个扩展样式齐全）：{'通过' if report.get('ex_style_ok') else '失败'} {report.get('ex_style')}")
        print(f"打字 {t.get('got_len')}/{t.get('expected_len')} 字，逐字一致：{'通过' if t.get('identical') else '失败'}")
        print(f"闪现期间前台始终是测试窗口：{'通过' if t.get('focus_kept_all_samples') else '失败'}")
        print(f"点击穿透（按钮收到点击）：{'通过' if report.get('click_through', {}).get('ok') else '失败'}")
        print("总结：", "全部通过" if report.get("PASS") else "有失败项，见报告")
    print("报告：", path)
    return 0 if (a.tour or report.get("PASS")) else 1


if __name__ == "__main__":
    sys.exit(main())
