# -*- coding: utf-8 -*-
"""设置界面（独立进程，从托盘菜单打开，关闭即退出；不计入常驻内存预算）。

    pythonw -m settings_ui.app

养成系游戏画风的“角色设定 / 换装”界面。整张界面由 ui_render.py 用 Pillow 画好，这里只负责：
把图贴到窗口上、把点击对应到热区、在后台线程里渲染预览、保存。
保存 = 写入 config.toml → 重新渲染立绘缓存 → 通知哨兵重新加载。
"""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from tkinter import colorchooser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PIL import ImageTk  # noqa: E402

from settings_ui import ui_render  # noqa: E402
from settings_ui.model import SettingsModel  # noqa: E402
from winapi import ipc  # noqa: E402
from winapi import monitors as mon_mod  # noqa: E402
from winapi.win32 import set_dpi_awareness  # noqa: E402

MSG = {
    "zh": {"saving": "正在保存并渲染立绘……", "saved": "已保存，督察员已更新。",
           "saved_off": "已保存（督察员没在运行，下次启动生效）。", "error": "保存失败：", "rendering": "正在换装……",
           "edited": "台词已改成自定义版本，点“保存”生效。", "done": "完成", "cancel": "取消",
           "edit_tip": "回车完成 · Esc 取消 · 清空或改回原样 = 用默认台词"},
    "en": {"saving": "Saving and rendering…", "saved": "Saved. The inspector has been updated.",
           "saved_off": "Saved (the inspector isn't running; takes effect next start).", "error": "Save failed: ",
           "rendering": "Dressing up…", "edited": "Line customized. Click Save to apply.", "done": "Done",
           "cancel": "Cancel", "edit_tip": "Enter = done · Esc = cancel · empty or unchanged = default line"},
}
INK, PAPER, ROSE = "#5B3A35", "#FFF8EF", "#C46F8A"


def register_fonts() -> str:
    """把角色包自带的站酷快乐体临时注册给本进程用（不安装到系统），编辑框里的字和气泡一致。"""
    try:
        import ctypes
        path = ui_render.FONT_ZH
        if os.name == "nt" and os.path.exists(path):
            if ctypes.windll.gdi32.AddFontResourceExW(path, 0x10, 0):      # FR_PRIVATE
                return "ZCOOL KuaiLe"
    except Exception:  # noqa: BLE001
        pass
    return "Microsoft YaHei UI"


class SettingsApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.m = SettingsModel()
        dpi_scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        fit = min(root.winfo_screenwidth() * 0.96 / ui_render.W, (root.winfo_screenheight() - 80) / ui_render.H)
        self.S = max(0.75, min(dpi_scale, fit))
        self.st = ui_render.UiState(persona_error=self.m.persona_error)
        self.hot: list = []
        self._photo = None
        self._gen = 0
        self.editor = None
        self.font_family = register_fonts()
        root.title(ui_render.TEXT[self.m.lang]["ribbon"])
        root.resizable(False, False)
        root.configure(bg=ui_render.BG_TOP)
        self.canvas = tk.Canvas(root, width=int(ui_render.W * self.S), height=int(ui_render.H * self.S),
                                highlightthickness=0, bd=0, bg=ui_render.BG_TOP)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Motion>", self.on_motion)
        self.sync()
        self.refresh_previews()
        self.poll_stats()

    # ── 状态 → 画面 ─────────────────────────────────────────────────────
    def sync(self):
        m, st = self.m, self.st
        st.lang, st.hair, st.character = m.lang, m.hair, m.character
        st.hair_presets, st.characters = m.presets("hair"), m.characters()
        st.display_name, st.traits, st.card_name = m.display_name(), m.traits(), m.card_name()
        st.line_state = {k: {"has": m.has_custom(k), "custom": m.is_custom(k)} for k in m.custom}

    def redraw(self):
        img, self.hot = ui_render.render_ui(self.st, self.S)
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("ui")                    # 只换底图，正在编辑的台词框（嵌入的窗口）不动
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw", tags="ui")
        self.root.title(ui_render.TEXT[self.m.lang]["ribbon"])

    def set_status(self, text: str, error: bool = False):
        self.st.status, self.st.status_error = text, error
        self.redraw()

    def refresh_previews(self):
        """立绘着色 + 三个场景的闪现图，后台线程渲染（与实际闪现同一条管线）。"""
        self._gen += 1
        gen = self._gen
        self.st.busy = True
        self.st.figure = self.m.figure()
        if not self.st.status or self.st.status in (MSG["zh"]["rendering"], MSG["en"]["rendering"]):
            self.st.status, self.st.status_error = MSG[self.m.lang]["rendering"], False
        self.redraw()

        def work():
            try:
                imgs = self.m.preview(mon_h=1080, dpi=96)
            except Exception as exc:  # noqa: BLE001
                imgs = exc
            self.root.after(0, lambda: self._previews_done(gen, imgs))

        threading.Thread(target=work, daemon=True).start()

    def _previews_done(self, gen, imgs):
        if gen != self._gen:
            return
        self.st.busy = False
        if isinstance(imgs, Exception):
            self.set_status(str(imgs), True)
            return
        self.st.previews = imgs
        if self.st.status == MSG[self.m.lang]["rendering"]:
            self.st.status = ""
        self.redraw()

    def poll_stats(self):
        self.st.stats = self.m.stats()
        self.redraw()
        self.root.after(30_000, self.poll_stats)

    # ── 交互 ─────────────────────────────────────────────────────────────
    def on_motion(self, e):
        h = ui_render.hit(self.hot, e.x, e.y)
        self.canvas.configure(cursor="hand2" if h else "")

    def on_click(self, e):
        if self.editor:                      # 正在改台词时点别处 = 完成
            self.finish_edit(commit=True)
            return
        h = ui_render.hit(self.hot, e.x, e.y)
        if not h:
            return
        if h.action in ("hair", "skin", "lang"):
            ok = {"hair": self.m.set_hair, "skin": self.m.set_character, "lang": self.m.set_lang}[h.action](h.arg)
            if ok:
                if h.action == "lang":
                    self.st.status = ""             # 提示语跟着界面语言走，切换后不留另一种语言的旧提示
                self.sync()
                self.refresh_previews()
        elif h.action == "variant":
            self.st.variant = h.arg
            self.redraw()
        elif h.action == "line_mode":
            if self.m.use_default(ui_render.preview_key(self.st), default=(h.arg == "default")):
                self.sync()
                self.refresh_previews()
        elif h.action == "edit":
            self.start_edit(h.arg, h.box)
        elif h.action == "custom":
            res = colorchooser.askcolor(color=self.m.hair, parent=self.root,
                                        title=ui_render.TEXT[self.m.lang]["hair"])
            if res and res[1] and self.m.set_hair(res[1]):
                self.sync()
                self.refresh_previews()
        elif h.action == "tab":
            self.st.tab = h.arg
            self.redraw()
        elif h.action == "save":
            self.save()
        elif h.action == "demo":
            self.save(demo=True)
        elif h.action == "close":
            self.root.destroy()

    # ── 在气泡里直接改台词 ───────────────────────────────────────────────
    def start_edit(self, key: str, box):
        x0, y0, x1, y1 = box
        T = MSG[self.m.lang]
        px = max(10, int(13 * self.S))
        frame = tk.Frame(self.canvas, bg=ROSE, bd=0)
        family = self.font_family if self.m.lang == "zh" else "Segoe UI Semibold"
        text = tk.Text(frame, wrap="word", font=(family, -px), bg=PAPER, fg=INK, insertbackground=ROSE,
                       relief="flat", bd=0, padx=int(8 * self.S), pady=int(6 * self.S), undo=True,
                       height=1, width=1)
        text.pack(fill="both", expand=True, padx=max(2, int(2 * self.S)), pady=max(2, int(2 * self.S)))
        text.insert("1.0", self.m.line(key))
        text.tag_add("sel", "1.0", "end-1c")
        bar = tk.Frame(self.canvas, bg=PAPER)
        for label, commit in ((T["done"], True), (T["cancel"], False)):
            tk.Button(bar, text=label, font=(self.font_family, -max(9, int(11 * self.S))), relief="flat", bd=0,
                      bg=ROSE if commit else PAPER, fg="#FFFFFF" if commit else ROSE, cursor="hand2",
                      activebackground=ROSE, activeforeground="#FFFFFF", padx=int(10 * self.S), pady=int(2 * self.S),
                      command=lambda c=commit: self.finish_edit(c)).pack(side="left", padx=(0, int(4 * self.S)))
        tk.Label(bar, text=T["edit_tip"], font=(self.font_family, -max(8, int(10 * self.S))), bg=PAPER,
                 fg="#A08681").pack(side="left", padx=int(4 * self.S))
        h = max(y1 - y0, int(64 * self.S))
        w = max(x1 - x0, int(240 * self.S))
        self.editor = {"key": key, "text": text, "items": [
            self.canvas.create_window(x0, y0, window=frame, anchor="nw", width=w, height=h),
            self.canvas.create_window(x0, y0 + h + int(4 * self.S), window=bar, anchor="nw")]}
        text.bind("<Return>", lambda e: (self.finish_edit(True), "break")[1])
        text.bind("<KP_Enter>", lambda e: (self.finish_edit(True), "break")[1])
        text.bind("<Escape>", lambda e: (self.finish_edit(False), "break")[1])
        text.focus_set()

    def finish_edit(self, commit: bool):
        ed, self.editor = self.editor, None
        if not ed:
            return
        new = ed["text"].get("1.0", "end-1c")
        for item in ed["items"]:
            self.canvas.delete(item)
        if commit and " ".join(new.split()) != self.m.line(ed["key"]):
            self.m.set_custom(ed["key"], new)
            self.sync()
            self.refresh_previews()
            self.st.status = MSG[self.m.lang]["edited"]
        self.redraw()

    def save(self, demo=False):
        if self.editor:
            self.finish_edit(commit=True)
        T = MSG[self.m.lang]
        self.set_status(T["saving"])
        self.root.update_idletasks()

        def work():
            try:
                res = self.m.save(mon_mod.monitor_sizes(), notify=ipc.notify_reload)
                if demo and res["notified"]:
                    self.root.after(1500, ipc.request_demo)
                msg, err = (T["saved"] if res["notified"] else T["saved_off"]), False
            except Exception as exc:  # noqa: BLE001
                msg, err = T["error"] + str(exc), True
            self.root.after(0, lambda: self.set_status(msg, err))

        threading.Thread(target=work, daemon=True).start()


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="大水理论最严厉的母亲 · 设置")
    ap.add_argument("--tab", choices=ui_render.SCENES, help="打开时显示哪个场景的预览")
    ap.add_argument("--close-after", type=float, default=0, help="N 秒后自动关闭（自查截图用）")
    a = ap.parse_args(argv)
    set_dpi_awareness()
    root = tk.Tk()
    app = SettingsApp(root)
    if a.tab:
        app.st.tab = a.tab
        app.redraw()
    if a.close_after > 0:
        root.after(int(a.close_after * 1000), root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
