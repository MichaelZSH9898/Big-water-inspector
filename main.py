# -*- coding: utf-8 -*-
"""大水理论最严厉的母亲 · 哨兵进程（常驻）。

    pythonw main.py            正常运行（托盘里一个粉色小水杯）
    python  main.py --demo     演示模式：所有时间阈值 ×1/60（分钟变秒），用于快速自查
    python  main.py --console  在控制台打印运行日志（调试用）

单线程、事件驱动：一个隐藏顶层窗口 + GetMessageW 消息循环。内核（core/engine.py）算出“下次什么时候
需要醒”，这里用 SetTimer 定一个闹钟；系统事件（锁屏、睡眠、前台切换）直接调用内核。
只用标准库 + ctypes：不 import Pillow / pywin32 / pystray / comtypes。
"""

from __future__ import annotations

import argparse
import faulthandler
import importlib.util
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import config as config_mod  # noqa: E402
from core.clock import RealClock  # noqa: E402
from core.engine import Engine  # noqa: E402
from core.eventlog import EventLog  # noqa: E402
from overlay.image_cache import ImageCache  # noqa: E402
from overlay.layered_window import Overlay  # noqa: E402
from persona import cachekey  # noqa: E402
from persona.lines import LinePicker, lines_for_config  # noqa: E402
from persona.loader import load_with_fallback  # noqa: E402
from signals import session  # noqa: E402
from signals.audio import WinAudio, com_init  # noqa: E402
from signals.base import Signals  # noqa: E402
from signals.foreground import WinForeground  # noqa: E402
from signals.idle import WinIdle  # noqa: E402
from signals.mic_cam import WinMicCam  # noqa: E402
from signals.notify_state import WinNotify  # noqa: E402
from winapi import autostart, ipc  # noqa: E402
from winapi import monitors as mon_mod  # noqa: E402
from winapi.msgwindow import MessageWindow  # noqa: E402
from winapi.tray import CALLBACK_MSG, Tray, water_level  # noqa: E402
from winapi.win32 import (IS_WINDOWS, WM_CLOSE, WM_DESTROY, WM_DISPLAYCHANGE, WM_ENDSESSION, WM_POWERBROADCAST,  # noqa: E402
                          WM_QUERYENDSESSION, WM_WTSSESSION_CHANGE, set_dpi_awareness, single_instance, user32)

MUTEX = "Local\\WaterInspector.Sentinel"
ENGINE_TIMER = 1
LOG_DIR = os.path.join(ROOT, "logs")
STATE_PATH = os.path.join(ROOT, "state.json")
RUNTIME_PATH = os.path.join(ROOT, "data", "runtime.json")
ICON_DIR = os.path.join(ROOT, "assets", "tray")

# 菜单命令
CMD_PAUSE_1H, CMD_PAUSE_TOMORROW, CMD_RESUME = 10, 11, 12
CMD_SETTINGS, CMD_DEMO, CMD_AUTOSTART, CMD_OPEN_LOGS, CMD_QUIT = 20, 21, 22, 23, 99

TEXT = {
    "zh": {"title": "大水理论最严厉的母亲", "pause1h": "暂停 1 小时", "pause_tm": "暂停到明天", "resume": "恢复提醒",
           "stats": "今日统计", "settings": "设置…", "demo": "演示一次", "autostart": "开机自启",
           "logs": "打开日志文件夹", "quit": "退出", "paused_until": "已暂停至 {t}",
           "status": "饮水 {w:.0f} · 久坐 {s:.0f} 分钟", "eff": "有效使用 {h} 小时 {m} 分",
           "scene": "{name}：出现 {shown} · 响应 {resp} · 屏蔽 {blk}", "scene_c": "{name}：出现 {shown} · 屏蔽 {blk}",
           "A": "解锁训话", "B": "侧边探头", "C": "加班关怀", "demo_mode": "（演示模式）"},
    "en": {"title": "大水理论最严厉的母亲", "pause1h": "Pause for 1 hour", "pause_tm": "Pause until tomorrow",
           "resume": "Resume", "stats": "Today", "settings": "Settings…", "demo": "Play demo",
           "autostart": "Start with Windows", "logs": "Open log folder", "quit": "Quit",
           "paused_until": "Paused until {t}", "status": "Water {w:.0f} · Sitting {s:.0f} min",
           "eff": "Active time {h} h {m} min", "scene": "{name}: shown {shown} · responded {resp} · blocked {blk}",
           "scene_c": "{name}: shown {shown} · blocked {blk}", "A": "Unlock scolding", "B": "Side peek",
           "C": "Overtime care", "demo_mode": " (demo mode)"},
}


def pythonw() -> str:
    return autostart.pythonw()


class Sentinel:
    def __init__(self, args):
        self.args = args
        self.clock = RealClock()
        self.log = EventLog(LOG_DIR, self.clock)
        self.console = args.console
        self.cfg = self._load_config()
        self.persona, err = load_with_fallback(self.cfg.persona, log=self.log)
        if err:
            self._note(err)
        self.cache = ImageCache()
        self.cache.set_expected(cachekey.variant_key(self.persona, self.cfg), self.cfg.language)

        # 这几个要在建窗口之前准备好：建窗口时就会有消息进 _on_message
        self.reload_msg = ipc.reload_message_id()
        self.demo_msg = ipc.demo_message_id()
        self.taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self.engine = None
        self.tray = None
        self.win = MessageWindow(ipc.SENTINEL_CLASS, "WaterInspector", self._on_message, log=self.log)
        self.overlay = Overlay(self.win, self.cache, log=self.log)

        self.foreground = WinForeground(self.cfg.raw["categories"], on_change=self._on_foreground,
                                        on_close=self._on_window_closed, call_later=self.win.call_later, log=self.log)
        self.notify = WinNotify(self.cfg.P.fullscreen_check_foreground)
        sig = Signals(idle=WinIdle(), notify=self.notify,
                      miccam=WinMicCam(self.cfg.P.meeting_stale_s, log=self.log),
                      audio=WinAudio(), foreground=self.foreground)
        self.engine = Engine(self.cfg, self.clock, sig, display=self.overlay, log=self.log,
                             lines=LinePicker(lines_for_config(self.persona, self.cfg)),
                             state_path=STATE_PATH, runtime_path=RUNTIME_PATH)

        self.tray = Tray(self.win.hwnd, ICON_DIR, self._t("title"), log=self.log)
        self.tray.add()
        self.foreground.start()
        if self.foreground.category:
            self.engine.on_foreground(self.foreground.category)
        if not session.register(self.win.hwnd):
            self._note("WTSRegisterSessionNotification 失败：锁屏事件收不到，将依赖空闲时长判断")
        self._cfg_mtime = self._config_mtime()
        self._last_cfg_check = time.time()
        self._render_spawns: list[float] = []
        self._after_engine()
        self.win.call_later(2.0, self._ensure_render_cache)
        self._note(f"哨兵启动（pid {os.getpid()}，演示模式 {self.cfg.P.demo}）")

    # ── 工具 ─────────────────────────────────────────────────────────────
    def _note(self, msg: str) -> None:
        self.log.app(msg)
        if self.console:
            print(time.strftime("%H:%M:%S"), msg, flush=True)

    def _t(self, key: str) -> str:
        return TEXT.get(self.cfg.language, TEXT["zh"])[key]

    def _load_config(self):
        over = {"general": {"demo_mode": True}} if self.args.demo else None
        cfg = config_mod.load(overrides=over)
        for e in cfg.errors:
            self.log.app(e)
        return cfg

    @staticmethod
    def _config_mtime() -> float:
        try:
            return os.path.getmtime(config_mod.CONFIG_PATH)
        except OSError:
            return 0.0

    # ── 内核调度 ─────────────────────────────────────────────────────────
    def _schedule(self) -> None:
        delay = self.engine.next_wake() - self.clock.now()
        self.win.set_timer(ENGINE_TIMER, max(10, int(delay * 1000)), self._on_engine_timer)

    def _on_engine_timer(self) -> None:
        self.engine.tick()
        self._after_engine()

    def _after_engine(self) -> None:
        self._schedule()
        st = self.engine.stats_today()
        P = self.cfg.P
        tip = self._t("title") + (self._t("demo_mode") if P.demo else "") + "\n"
        if self.engine.paused:
            tip += self._t("paused_until").format(t=time.strftime("%H:%M", time.localtime(self.engine.paused_until)))
        else:
            tip += self._t("status").format(w=st["water"], s=st["sitting"])
        self.tray.set_state(water_level(self.engine.ledger.water, P.water_threshold), tip)
        now = time.time()
        if now - self._last_cfg_check >= 60:          # 兜底：有人直接改了 config.toml
            self._last_cfg_check = now
            m = self._config_mtime()
            if m != self._cfg_mtime:
                self._cfg_mtime = m
                self.reload()

    def _on_foreground(self, category: str) -> None:
        self.engine.on_foreground(category)
        self._after_engine()

    def _on_window_closed(self, t: float) -> None:
        self.engine.on_window_closed(t)
        self._after_engine()

    # ── 窗口消息 ─────────────────────────────────────────────────────────
    def _on_message(self, msg, wparam, lparam):
        if self.engine is None or self.tray is None:      # 还在初始化
            return None
        ev = session.translate(msg, wparam)
        if ev:
            {"lock": self.engine.on_lock, "unlock": self.engine.on_unlock,
             "suspend": self.engine.on_suspend, "resume": self.engine.on_resume}[ev]()
            if ev in ("unlock", "resume"):
                self.win.call_later(1.0, self._ensure_render_cache)
            self._after_engine()
            return 1 if msg == WM_POWERBROADCAST else 0
        if msg == WM_WTSSESSION_CHANGE:
            return 0
        if msg == CALLBACK_MSG:
            if self.tray.is_menu_request(lparam):
                self._menu()
            return 0
        if msg == self.reload_msg and self.reload_msg:
            self.reload()
            return 0
        if msg == self.demo_msg and self.demo_msg:
            self.engine.demo_all()
            return 0
        if msg == self.taskbar_created and self.taskbar_created:
            self.tray.added = False
            self.tray.add()
            return 0
        if msg == WM_DISPLAYCHANGE:
            self.win.call_later(3.0, self._ensure_render_cache)
            return None
        if msg == WM_QUERYENDSESSION:
            self.engine.write_state()
            return 1
        if msg == WM_ENDSESSION:
            if wparam:
                self.shutdown()
            return 0
        if msg == WM_CLOSE:          # 重启督察员.bat / 卸载时用：和托盘“退出”一样体面地收尾
            self.shutdown()
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return None

    # ── 托盘菜单 ─────────────────────────────────────────────────────────
    def _menu(self) -> None:
        st = self.engine.stats_today()
        T = TEXT.get(self.cfg.language, TEXT["zh"])
        head = T["title"] + (T["demo_mode"] if self.cfg.P.demo else "") + " · "
        if self.engine.paused:
            head += T["paused_until"].format(t=time.strftime("%H:%M", time.localtime(self.engine.paused_until)))
        else:
            head += T["status"].format(w=st["water"], s=st["sitting"])
        eff = st["effective_min"]
        stats = [(0, T["eff"].format(h=eff // 60, m=eff % 60), {"grayed": True})]
        for sc in ("A", "B", "C"):
            c = st["scenes"].get(sc, {})
            key = "scene_c" if sc == "C" else "scene"
            stats.append((0, T[key].format(name=T[sc], shown=c.get("shown", 0), resp=c.get("responded", 0),
                                           blk=c.get("blocked", 0)), {"grayed": True}))
        items = [(0, head, {"grayed": True}), ("-",)]
        if self.engine.paused:
            items.append((CMD_RESUME, T["resume"]))
        items += [(CMD_PAUSE_1H, T["pause1h"]), (CMD_PAUSE_TOMORROW, T["pause_tm"]),
                  ("sub", T["stats"], stats), ("-",),
                  (CMD_SETTINGS, T["settings"]), (CMD_DEMO, T["demo"]),
                  (CMD_AUTOSTART, T["autostart"], {"checked": autostart.is_enabled()}),
                  (CMD_OPEN_LOGS, T["logs"]), ("-",), (CMD_QUIT, T["quit"])]
        cmd = self.tray.popup(items)
        if cmd == CMD_PAUSE_1H:
            self.engine.pause(3600)
        elif cmd == CMD_PAUSE_TOMORROW:
            self.engine.pause_until_tomorrow()
        elif cmd == CMD_RESUME:
            self.engine.resume()
        elif cmd == CMD_SETTINGS:
            self._spawn(["-m", "settings_ui.app"])
        elif cmd == CMD_DEMO:
            self.engine.demo_all()
        elif cmd == CMD_AUTOSTART:
            autostart.set_enabled(not autostart.is_enabled(), os.path.join(ROOT, "main.py"))
        elif cmd == CMD_OPEN_LOGS:
            os.startfile(LOG_DIR)  # noqa: S606
        elif cmd == CMD_QUIT:
            self.shutdown()
            return
        self._after_engine()

    # ── 子进程：设置界面、渲染器 ─────────────────────────────────────────
    def _spawn(self, args: list[str]) -> bool:
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen([pythonw()] + args, cwd=ROOT, creationflags=flags, close_fds=True)
            return True
        except OSError:
            self.log.app(f"启动子进程失败：{args}", exc=True)
            return False

    def _ensure_render_cache(self, budget: int = 1) -> None:
        """当前设置 / 当前显示器的立绘缺了就在后台补画（Pillow 只在子进程里加载）。
        10 分钟内最多拉起 budget 次渲染器（配置刚变时给 3 次），避免任何原因的“画完还说缺”变成死循环。"""
        sizes = mon_mod.monitor_sizes()
        if not sizes or self.cache.has_exact(sizes):
            return
        now = time.time()
        self._render_spawns = [t for t in self._render_spawns if now - t < 600]
        if len(self._render_spawns) >= budget:
            return
        self._render_spawns.append(now)
        if importlib.util.find_spec("PIL") is None:
            self._note("缺少 Pillow，无法按当前显示器渲染立绘（将使用最接近的预置尺寸）：pip install pillow")
            return
        self._spawn(["-m", "persona.render", "--ensure", "--notify",
                     "--sizes", ",".join(f"{h}x{d}" for h, d in sizes)])
        self._note(f"后台渲染立绘：{sizes}")

    # ── 重新加载 / 退出 ──────────────────────────────────────────────────
    def reload(self) -> None:
        cfg = self._load_config()
        persona, err = load_with_fallback(cfg.persona, log=self.log)
        if err:
            self._note(err)
        self.cfg, self.persona = cfg, persona
        self.cache.set_expected(cachekey.variant_key(persona, cfg), cfg.language)
        self.foreground.reload(cfg.raw["categories"])
        self.notify.check_foreground = cfg.P.fullscreen_check_foreground
        self.engine.reload(cfg, LinePicker(lines_for_config(persona, cfg)))
        self._cfg_mtime = self._config_mtime()
        self.win.call_later(1.0, lambda: self._ensure_render_cache(budget=3))
        self._after_engine()
        self._note("已重新加载配置与角色包")

    def shutdown(self) -> None:
        try:
            self.engine.write_state()
            self.log.event("app", what="stop")
        finally:
            self.overlay.close()
            self.foreground.stop()
            session.unregister(self.win.hwnd)
            self.tray.destroy()
            self.win.destroy()

    def run(self) -> int:
        return self.win.run()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="大水理论最严厉的母亲（哨兵）")
    ap.add_argument("--demo", action="store_true", help="演示模式：时间阈值 ×1/60")
    ap.add_argument("--console", action="store_true", help="把运行日志同时打印到控制台")
    ap.add_argument("--try", dest="try_once", action="store_true", help="启动后演示三个场景，随后正常运行")
    args = ap.parse_args(argv)
    if args.console:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    if not IS_WINDOWS:
        print("哨兵只能在 Windows 上运行；逻辑可用 python -m sim.run 在任何系统上回放。")
        return 2
    mutex = single_instance(MUTEX)
    if mutex is None:          # 已经有一个哨兵在运行
        if args.try_once:
            ipc.request_demo()
        return 0
    os.makedirs(LOG_DIR, exist_ok=True)
    try:
        crash = open(os.path.join(LOG_DIR, "crash.log"), "a", encoding="utf-8")
        faulthandler.enable(file=crash, all_threads=True)
    except OSError:
        pass
    set_dpi_awareness()
    com_init()
    app = Sentinel(args)
    if args.try_once:
        app.win.call_later(3.0, app.engine.demo_all)
    try:
        return app.run()
    except KeyboardInterrupt:
        app.shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
