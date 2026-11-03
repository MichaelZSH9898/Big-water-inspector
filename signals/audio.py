# -*- coding: utf-8 -*-
"""音频是否在播放：WASAPI 默认输出端点的 IAudioMeterInformation 峰值。

纯 ctypes 调 COM 虚表，不依赖 comtypes / pycaw（comtypes 一导入就要十几 MB 常驻内存）。
只在“某一分钟没有键鼠输入”时才查一次（第 5 节）：每次现建现放，不常驻任何音频对象。
只读一个峰值数字，不录音、不读任何音频内容。
"""

from __future__ import annotations

import time
from ctypes import POINTER, byref, c_float, c_uint, c_void_p, cast

from winapi.win32 import CLSCTX_ALL, COINIT_APARTMENTTHREADED, GUID, HRESULT, IS_WINDOWS, WINFUNCTYPE, ole32

CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
IID_IAudioMeterInformation = "{C02216F6-8C67-4B5B-9D00-D008E73E0064}"
E_RENDER, E_CONSOLE = 0, 0
PEAK_THRESHOLD = 1e-4


def _method(ptr: c_void_p, index: int, restype, *argtypes):
    vtbl = cast(ptr, POINTER(POINTER(c_void_p)))[0]
    return WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[index])


def _release(ptr) -> None:
    if ptr:
        try:
            _method(ptr, 2, c_uint)(ptr)
        except OSError:
            pass


_com_ready = False


def com_init() -> None:
    """主线程调用一次（单线程套间）。"""
    global _com_ready
    if IS_WINDOWS and not _com_ready:
        ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        _com_ready = True


def peak_samples(n: int = 5, interval: float = 0.03) -> list[float]:
    """读 n 次默认输出设备的峰值（0–1）。没有输出设备时返回 []。"""
    if not IS_WINDOWS:
        return []
    com_init()
    enum, dev, meter = c_void_p(), c_void_p(), c_void_p()
    out: list[float] = []
    try:
        hr = ole32.CoCreateInstance(byref(GUID.parse(CLSID_MMDeviceEnumerator)), None, CLSCTX_ALL,
                                    byref(GUID.parse(IID_IMMDeviceEnumerator)), byref(enum))
        if hr != 0 or not enum:
            return []
        # IMMDeviceEnumerator::GetDefaultAudioEndpoint（第 4 个方法）
        hr = _method(enum, 4, HRESULT, c_uint, c_uint, POINTER(c_void_p))(enum, E_RENDER, E_CONSOLE, byref(dev))
        if hr != 0 or not dev:
            return []
        # IMMDevice::Activate（第 3 个方法）
        hr = _method(dev, 3, HRESULT, POINTER(GUID), c_uint, c_void_p, POINTER(c_void_p))(
            dev, byref(GUID.parse(IID_IAudioMeterInformation)), CLSCTX_ALL, None, byref(meter))
        if hr != 0 or not meter:
            return []
        get_peak = _method(meter, 3, HRESULT, POINTER(c_float))   # IAudioMeterInformation::GetPeakValue
        v = c_float(0.0)
        for i in range(n):
            if get_peak(meter, byref(v)) == 0:
                out.append(float(v.value))
            if i + 1 < n:
                time.sleep(interval)
        return out
    except OSError:
        return out
    finally:
        _release(meter)
        _release(dev)
        _release(enum)


class WinAudio:
    def __init__(self, samples: int = 5, interval: float = 0.03):
        self.samples, self.interval = samples, interval

    def is_playing(self) -> bool:
        return any(p > PEAK_THRESHOLD for p in peak_samples(self.samples, self.interval))
