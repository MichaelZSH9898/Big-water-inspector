# -*- coding: utf-8 -*-
"""闪现窗口：在哨兵进程内用 Win32 分层窗口贴一张预乘 alpha 的图，1.5 秒后 0.5 秒线性淡出，随后销毁。

窗口样式（全部必需）：WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
  · 分层 + 透明：逐像素 alpha，鼠标完全穿透
  · 置顶、不进任务栏和 Alt+Tab、不抢焦点
  · SW_SHOWNOACTIVATE 显示，全程不调用 SetForegroundWindow
  · 窗口过程直接用 DefWindowProcW：这个窗口的消息一条都不经过 Python
时间线：0–show_s 完全不透明；show_s 起按约 30 帧/秒降低 SourceConstantAlpha；结束后销毁窗口、
释放 DIB 和像素缓冲。平时没有任何定时器，只有淡出的 0.5 秒里才有 30 帧/秒的唤醒。
"""

from __future__ import annotations

import ctypes
import time
from collections import deque
from ctypes import byref, c_void_p, sizeof

from winapi import monitors as mon_mod
from winapi.win32 import (AC_SRC_ALPHA, AC_SRC_OVER, BI_RGB, BITMAPINFO, BLENDFUNCTION, DIB_RGB_COLORS,
                          HWND_TOPMOST, IS_WINDOWS, POINT, SIZE, SW_SHOWNOACTIVATE, SWP_NOACTIVATE, SWP_NOMOVE,
                          SWP_NOSIZE, SWP_SHOWWINDOW, ULW_ALPHA, WNDCLASSEXW, WS_EX_LAYERED, WS_EX_NOACTIVATE,
                          WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_POPUP, defwindowproc_ptr, gdi32,
                          kernel32, user32)

FLASH_CLASS = "WaterInspector.Flash"
EX_STYLE = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
FRAME_MS = 33

_class_registered = False
_wndproc_ref = None


def _register_class():
    global _class_registered, _wndproc_ref
    if _class_registered:
        return
    _wndproc_ref = defwindowproc_ptr()
    wc = WNDCLASSEXW()
    wc.cbSize = sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = _wndproc_ref
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.lpszClassName = FLASH_CLASS
    user32.RegisterClassExW(byref(wc))
    _class_registered = True


def place(anchor: str, w: int, h: int, m) -> tuple[int, int]:
    """按场景锚点算窗口左上角（物理像素）。m：winapi.monitors.Monitor。"""
    if anchor == "top_center":                       # A：屏幕中央偏上
        x = m.left + (m.width - w) // 2
        y = m.top + round(m.height * 0.12)
    elif anchor == "right_edge":                     # B：贴右侧边缘探出半身
        x = m.right - w
        y = m.work_top + round((m.work_bottom - m.work_top) * 0.46 - h / 2)
    else:                                            # C：右下角（工作区内，站在任务栏上）
        x = m.work_right - w - round(16 * m.scale)
        y = m.work_bottom - h
    x = max(m.left, min(x, m.right - w))
    y = max(m.top, min(y, m.bottom - h))
    return x, y


class _Flash:
    """一次闪现占用的全部 GDI 资源。"""

    def __init__(self, x, y, w, h, pixels: bytes):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.hwnd = self.hdc_mem = self.hbmp = self.old = None
        hdc_screen = user32.GetDC(None)
        try:
            self.hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            bmi = BITMAPINFO()
            bh = bmi.bmiHeader
            bh.biSize = sizeof(bh)
            bh.biWidth, bh.biHeight = w, -h          # 负高度 = 自上而下
            bh.biPlanes, bh.biBitCount, bh.biCompression = 1, 32, BI_RGB
            bits = c_void_p()
            self.hbmp = gdi32.CreateDIBSection(hdc_screen, byref(bmi), DIB_RGB_COLORS, byref(bits), None, 0)
            if not self.hbmp or not bits:
                raise OSError("CreateDIBSection 失败")
            ctypes.memmove(bits, pixels, w * h * 4)
            self.old = gdi32.SelectObject(self.hdc_mem, self.hbmp)
            self.hwnd = user32.CreateWindowExW(EX_STYLE, FLASH_CLASS, None, WS_POPUP, x, y, w, h,
                                               None, None, kernel32.GetModuleHandleW(None), None)
            if not self.hwnd:
                raise OSError(f"CreateWindowExW 失败（{ctypes.get_last_error()}）")
            self.update(255, hdc_screen)
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        except Exception:
            self.destroy()
            raise
        finally:
            user32.ReleaseDC(None, hdc_screen)

    def update(self, alpha: int, hdc_screen=None) -> bool:
        own = hdc_screen is None
        if own:
            hdc_screen = user32.GetDC(None)
        try:
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, max(0, min(255, int(alpha))), AC_SRC_ALPHA)
            return bool(user32.UpdateLayeredWindow(self.hwnd, hdc_screen, byref(POINT(self.x, self.y)),
                                                   byref(SIZE(self.w, self.h)), self.hdc_mem, byref(POINT(0, 0)),
                                                   0, byref(blend), ULW_ALPHA))
        finally:
            if own:
                user32.ReleaseDC(None, hdc_screen)

    def destroy(self) -> None:
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.hdc_mem and self.old:
            gdi32.SelectObject(self.hdc_mem, self.old)
            self.old = None
        if self.hbmp:
            gdi32.DeleteObject(self.hbmp)
            self.hbmp = None
        if self.hdc_mem:
            gdi32.DeleteDC(self.hdc_mem)
            self.hdc_mem = None


class Overlay:
    """Engine 的 display：show(req) → bool。同一时刻只有一个闪现；演示模式的连播排队。"""

    def __init__(self, msgwin, cache, log=None, on_shown=None):
        self.win = msgwin            # 提供 call_later / every / cancel 的隐藏消息窗口
        self.cache = cache
        self.log = log
        self.on_shown = on_shown     # on_shown(req, info) 闪现结束后回调（测量工具用）
        self.active: _Flash | None = None
        self.queue: deque = deque()
        self._timer = None
        self._t_fade = 0.0
        self._req = None
        self.last_info: dict = {}
        if IS_WINDOWS:
            _register_class()

    def busy(self) -> bool:
        return self.active is not None

    def show(self, req) -> bool:
        if self.active is not None:
            if req.demo:
                self.queue.append(req)
                return True
            return False
        return self._start(req)

    def _start(self, req) -> bool:
        m = mon_mod.foreground_monitor()
        if m is None:
            return False
        found = self.cache.lookup(req.line_key, req.line_idx, m.height, m.dpi)
        if not found:
            if self.log:
                self.log.app(f"缺少闪现图片：{req.line_key}（显示器 {m.height}px / {m.dpi}dpi）")
            return False
        path, exact = found
        try:
            w, h, pixels = self.cache.load(path)
            x, y = place(req.anchor, w, h, m)
            self.active = _Flash(x, y, w, h, pixels)
        except Exception:  # noqa: BLE001
            if self.log:
                self.log.app("创建闪现窗口失败", exc=True)
            self.active = None
            return False
        finally:
            pixels = None                                    # noqa: F841  像素缓冲交给 DIB 后立即释放
        self._req = req
        self.last_info = {"x": x, "y": y, "w": w, "h": h, "exact_size": exact, "monitor": (m.height, m.dpi),
                          "t_show": time.time(), "hwnd": self.active.hwnd}
        self._timer = self.win.call_later(req.show_s, self._begin_fade)
        return True

    def _begin_fade(self) -> None:
        self._t_fade = time.perf_counter()
        fade = max(0.0, self._req.fade_s if self._req else 0.5)
        if fade <= 0:
            self._finish()
            return
        self._timer = self.win.every(FRAME_MS, self._frame)

    def _frame(self) -> None:
        if self.active is None:
            return
        fade = max(0.01, self._req.fade_s)
        t = (time.perf_counter() - self._t_fade) / fade
        if t >= 1.0:
            self._finish()
            return
        self.active.update(round(255 * (1.0 - t)))

    def _finish(self) -> None:
        if self._timer is not None:
            self.win.cancel(self._timer)
            self._timer = None
        if self.active is not None:
            self.active.destroy()
            self.active = None
        req, self._req = self._req, None
        self.last_info["t_end"] = time.time()
        if self.on_shown and req is not None:
            try:
                self.on_shown(req, dict(self.last_info))
            except Exception:  # noqa: BLE001
                pass
        if self.queue:
            nxt = self.queue.popleft()
            self.win.call_later(0.4, lambda: self._start(nxt))

    def close(self) -> None:
        self.queue.clear()
        self._finish()
