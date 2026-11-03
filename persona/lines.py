# -*- coding: utf-8 -*-
"""台词：选哪套（角色 + 语言 + 用户自定义），以及每次闪现选哪一条（随机、不连续重复）。"""

from __future__ import annotations

import random


class LinePicker:
    def __init__(self, lines: dict[str, list[str]], rng: random.Random | None = None):
        self.lines = {k: [str(x) for x in v if str(x).strip()] for k, v in (lines or {}).items()}
        self.rng = rng or random.Random()
        self._last: dict[str, int] = {}

    def has(self, key: str) -> bool:
        return bool(self.lines.get(key))

    def pick(self, key: str) -> tuple[int, str]:
        arr = self.lines.get(key) or []
        if not arr:
            return 0, key
        if len(arr) == 1:
            idx = 0
        else:
            last = self._last.get(key)
            choices = [i for i in range(len(arr)) if i != last]
            idx = self.rng.choice(choices)
        self._last[key] = idx
        return idx, arr[idx]


CUSTOM_KEYS = ("unlock_scold", "side_peek", "side_peek_water", "overtime_care")


def custom_text(custom: dict | None, key: str) -> str:
    return " ".join(str((custom or {}).get(key) or "").split())


def custom_active(custom: dict | None, key: str) -> bool:
    """这条台词是否用用户自定义的版本：写了内容，且开关是“自定义”。"""
    return bool(custom_text(custom, key)) and bool((custom or {}).get(f"use_{key}", True))


def effective_lines(persona, lang: str, character: str | None, custom: dict | None) -> dict:
    """实际要说的台词：角色包里（角色 + 语言）的默认台词，再用用户自定义的覆盖。
    自定义是按场景存的，与角色、语言无关——换了肤色或语言，自定义的台词照样保留。"""
    out = dict(persona.lines_for(lang, character))
    for key in CUSTOM_KEYS:
        if custom_active(custom, key):
            out[key] = [custom_text(custom, key)]
    return out


def lines_for_config(persona, cfg) -> dict:
    ap = cfg.raw.get("appearance", {})
    return effective_lines(persona, cfg.language, ap.get("character"), cfg.raw.get("custom_lines"))
