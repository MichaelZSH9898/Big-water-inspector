# -*- coding: utf-8 -*-
"""信号层的统一接口。

每个信号源都藏在这里定义的接口后面：真实的 Windows 实现在同目录的各个文件里，
假数据实现在 signals/fake.py（测试、模拟器用）。内核只依赖这些接口。

事件型信号（锁屏/解锁、睡眠/唤醒、前台切换、窗口关闭）不在这里轮询，
而是由 main.py（真实）或 sim（模拟）直接调用 Engine.on_xxx()。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class IdleSource(Protocol):
    def idle_seconds(self) -> float:
        """距上次键鼠输入过了多少秒。"""


@dataclass
class NotifyStatus:
    fullscreen: bool = False       # 全屏 / D3D 全屏 / 演示模式 / 前台铺满显示器
    fullscreen_why: str = ""
    dnd: bool = False              # 系统勿扰 / 专注模式
    dnd_why: str = ""
    raw: int | None = None         # SHQueryUserNotificationState 原始值


class NotifySource(Protocol):
    def query(self) -> NotifyStatus:
        ...


@dataclass
class MicCamStatus:
    in_use: bool = False
    last_stop_t: float | None = None   # 最近一次停止使用的时间（epoch 秒），用于“会议结束 2 分钟后才恢复”
    why: str = ""


class MicCamSource(Protocol):
    def status(self, now: float) -> MicCamStatus:
        ...


class AudioSource(Protocol):
    def is_playing(self) -> bool:
        """此刻是否有声音在播放（端点峰值 > 阈值）。"""


class ForegroundSource(Protocol):
    def current_category(self) -> str | None:
        ...

    def refresh(self) -> str | None:
        """前台是浏览器时重新看一次标题；类别变了返回新类别，否则 None。"""


@dataclass
class Signals:
    idle: IdleSource
    notify: NotifySource
    miccam: MicCamSource
    audio: AudioSource
    foreground: ForegroundSource | None = None


class NullForeground:
    def current_category(self):
        return None

    def refresh(self):
        return None
