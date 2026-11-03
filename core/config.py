# -*- coding: utf-8 -*-
"""读取 config.toml，合并默认值，算出内核用的参数（统一换算成秒 / 分钟桶）。

演示模式：所有“阈值类”时长 ×1/60（分钟变秒）。哪些缩放、哪些不缩放见 DECISIONS.md D-12。
配置文件写坏时不抛异常：返回默认值，并把错误放在 Config.errors 里由调用方写日志。
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None

from .clock import parse_hhmm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.toml")

DEFAULTS: dict[str, Any] = {
    "general": {"demo_mode": False, "language": "zh", "persona": "default_mom", "day_start": "04:00"},
    "appearance": {"hair_color": "#4F3F3B", "character": "east_asian"},
    "custom_lines": {"unlock_scold": "", "use_unlock_scold": False, "side_peek": "", "use_side_peek": False,
                     "side_peek_water": "", "use_side_peek_water": False,
                     "overtime_care": "", "use_overtime_care": False},
    "effective": {"grace_idle_min": 5, "count_short_idle": True, "audio_recent_input_min": 20},
    "ledger": {
        "long_absence_min": 5, "short_absence_min": 1,
        "short_lock_water_cut": 0.5, "short_lock_sitting_cut": 0.3,
        "response_window_min": 10, "response_idle_min": 2, "reset_on_new_day": True,
    },
    "classifier": {
        "window_min": 10, "flow_input_min": 8, "flow_max_switches": 2,
        "wander_window_min": 5, "wander_min_switches": 6, "sparse_input_max_min": 2,
        "burst_input_min": 5, "pause_min_s": 20, "pause_max_s": 90,
        "category_switch_window_s": 60, "close_window_s": 10,
        "meeting_cooldown_min": 2, "meeting_stale_hours": 12, "switch_debounce_s": 1.5,
        "fullscreen_check_foreground": True,
    },
    "policy": {
        "water_threshold_min": 60, "sitting_soft_min": 50, "sitting_hard_min": 100,
        "min_gap_min": 20, "scene_a_min_lock_min": 5, "scene_a_delay_s": 3, "scene_a_cap_min": 120,
        "scene_c_effective_hours": 8, "scene_c_after": "17:30", "decision_interval_s": 60,
        "quiet_hours": [],
    },
    "sampling": {"idle_far_s": 30, "idle_near_s": 5, "near_margin_min": 2},
    "display": {"figure_height_ratio": 0.22, "font_scale": 1.0},
    "scenes": {
        "unlock_scold": {"show_s": 1.5, "fade_s": 0.5},
        "side_peek": {"show_s": 1.5, "fade_s": 0.5},
        "overtime_care": {"show_s": 1.5, "fade_s": 0.5},
    },
    "categories": {
        "default": "other",
        "productivity": [], "communication": [], "browser": [], "entertainment": [], "meeting": [],
        "browser_title": {"entertainment": [], "communication": []},
    },
}

CATEGORIES = ("productivity", "communication", "browser", "entertainment", "meeting", "other")


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


@dataclass
class Params:
    """内核实际使用的参数。时长单位一律是秒（已按演示模式缩放）；*_buckets 是“分钟桶”个数。"""

    scale: float
    demo: bool
    bucket_s: float
    day_start_min: float
    # 6.1
    grace_idle_buckets: int
    count_short_idle: bool
    audio_recent_input_s: float
    # 6.2
    long_absence_s: float
    short_absence_s: float
    short_lock_water_cut: float
    short_lock_sitting_cut: float
    response_window_s: float
    response_idle_s: float
    reset_on_new_day: bool
    # 6.3
    window_buckets: int
    window_s: float
    flow_input_buckets: int
    flow_max_switches: int
    wander_window_buckets: int
    wander_window_s: float
    wander_min_switches: int
    sparse_input_max: int
    burst_input_buckets: int
    pause_min_s: float
    pause_max_s: float
    category_switch_window_s: float
    close_window_s: float
    meeting_cooldown_s: float
    meeting_stale_s: float
    switch_debounce_s: float
    fullscreen_check_foreground: bool
    # 6.4
    water_threshold: float
    sitting_soft: float
    sitting_hard: float
    min_gap_s: float
    a_min_lock_s: float
    a_delay_s: float
    a_cap_s: float
    c_effective_buckets: int
    c_after_min: float
    decision_interval_s: float
    quiet_hours: list = field(default_factory=list)
    # 5
    idle_far_s: float = 30.0
    idle_near_s: float = 5.0
    near_margin: float = 2.0
    blocked_log_dedupe_s: float = 600.0
    state_write_s: float = 60.0


@dataclass
class Config:
    raw: dict
    P: Params
    path: str | None = None
    errors: list = field(default_factory=list)

    @property
    def language(self) -> str:
        lang = str(self.raw["general"].get("language", "zh")).lower()
        return lang if lang in ("zh", "en") else "zh"

    @property
    def persona(self) -> str:
        return str(self.raw["general"].get("persona", "default_mom"))

    def scene_timing(self, scene_name: str) -> tuple[float, float]:
        s = self.raw.get("scenes", {}).get(scene_name, {})
        show = float(s.get("show_s", 1.5))
        fade = float(s.get("fade_s", 0.5))
        return max(0.1, show), max(0.0, fade)


def _num(d: dict, key: str, lo: float = 0.0) -> float:
    v = float(d[key])
    if v < lo:
        raise ValueError(f"{key} 不能小于 {lo}")
    return v


def build_params(raw: dict) -> Params:
    g, e, l, c, p, s = (raw[k] for k in ("general", "effective", "ledger", "classifier", "policy", "sampling"))
    demo = bool(g.get("demo_mode", False))
    scale = 1.0 / 60.0 if demo else 1.0
    M = 60.0 * scale          # 一“分钟”有多少秒
    S = scale                 # 一“秒”有多少秒
    floor = 0.2               # 演示模式下采样间隔的下限

    quiet = []
    for pair in p.get("quiet_hours", []) or []:
        a, b = pair
        quiet.append((parse_hhmm(a), parse_hhmm(b)))

    return Params(
        scale=scale, demo=demo, bucket_s=M, day_start_min=parse_hhmm(g.get("day_start", "04:00")),
        grace_idle_buckets=max(1, int(e["grace_idle_min"])),
        count_short_idle=bool(e["count_short_idle"]),
        audio_recent_input_s=_num(e, "audio_recent_input_min") * M,
        long_absence_s=_num(l, "long_absence_min") * M,
        short_absence_s=_num(l, "short_absence_min") * M,
        short_lock_water_cut=min(1.0, _num(l, "short_lock_water_cut")),
        short_lock_sitting_cut=min(1.0, _num(l, "short_lock_sitting_cut")),
        response_window_s=_num(l, "response_window_min") * M,
        response_idle_s=_num(l, "response_idle_min") * M,
        reset_on_new_day=bool(l.get("reset_on_new_day", True)),
        window_buckets=max(1, int(c["window_min"])),
        window_s=_num(c, "window_min") * M,
        flow_input_buckets=int(c["flow_input_min"]),
        flow_max_switches=int(c["flow_max_switches"]),
        wander_window_buckets=max(1, int(c["wander_window_min"])),
        wander_window_s=_num(c, "wander_window_min") * M,
        wander_min_switches=int(c["wander_min_switches"]),
        sparse_input_max=int(c["sparse_input_max_min"]),
        burst_input_buckets=int(c["burst_input_min"]),
        pause_min_s=_num(c, "pause_min_s") * S,
        pause_max_s=_num(c, "pause_max_s") * S,
        category_switch_window_s=_num(c, "category_switch_window_s") * S,
        close_window_s=_num(c, "close_window_s") * S,
        meeting_cooldown_s=_num(c, "meeting_cooldown_min") * M,
        meeting_stale_s=_num(c, "meeting_stale_hours") * 3600.0,
        switch_debounce_s=max(0.05, _num(c, "switch_debounce_s") * S),
        fullscreen_check_foreground=bool(c.get("fullscreen_check_foreground", True)),
        water_threshold=_num(p, "water_threshold_min", 1),
        sitting_soft=_num(p, "sitting_soft_min", 1),
        sitting_hard=_num(p, "sitting_hard_min", 1),
        min_gap_s=_num(p, "min_gap_min") * M,
        a_min_lock_s=_num(p, "scene_a_min_lock_min") * M,
        a_delay_s=_num(p, "scene_a_delay_s"),
        a_cap_s=_num(p, "scene_a_cap_min") * M,
        c_effective_buckets=int(round(_num(p, "scene_c_effective_hours") * 60)),
        c_after_min=parse_hhmm(p.get("scene_c_after", "17:30")),
        decision_interval_s=max(floor, _num(p, "decision_interval_s") * S),
        quiet_hours=quiet,
        idle_far_s=max(floor, _num(s, "idle_far_s") * S),
        idle_near_s=max(floor, _num(s, "idle_near_s") * S),
        near_margin=_num(s, "near_margin_min"),
        blocked_log_dedupe_s=600.0 * scale,
    )


def from_dict(over: dict | None = None, path: str | None = None) -> Config:
    raw = deep_merge(DEFAULTS, over or {})
    return Config(raw=raw, P=build_params(raw), path=path)


def load(path: str | None = None, overrides: dict | None = None) -> Config:
    """读取配置。出错时回退默认值，错误信息放进 errors。"""
    path = path or CONFIG_PATH
    errors: list[str] = []
    user: dict = {}
    if tomllib is None:
        errors.append("需要 Python 3.11+（tomllib），已使用默认配置")
    elif os.path.exists(path):
        try:
            with open(path, "rb") as fh:
                user = tomllib.load(fh)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"config.toml 解析失败，已使用默认配置：{exc}")
            user = {}
    else:
        errors.append(f"找不到 {path}，已使用默认配置")
    if overrides:
        user = deep_merge(user, overrides)
    try:
        cfg = from_dict(user, path)
    except Exception as exc:  # noqa: BLE001  参数值非法
        errors.append(f"config.toml 参数非法，已使用默认配置：{exc}")
        cfg = from_dict(overrides or {}, path)
    cfg.errors = errors
    return cfg


def set_dotted(d: dict, dotted: str, value: Any) -> None:
    """set_dotted(d, 'general.demo_mode', True)。模拟器脚本里的 config 行用它。"""
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value
