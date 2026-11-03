# -*- coding: utf-8 -*-
"""两本账：饮水账、久坐账（第 6.2 节）。

单位是“有效分钟”。两本账都按有效分钟累加；离开时按下表削减或清零：

| 事件                               | 饮水账 | 久坐账 |
|------------------------------------|--------|--------|
| 锁屏或睡眠 ≥ 5 分钟                | 不变   | 清零   |
| 未锁屏，无输入、无音频 ≥ 5 分钟    | 不变   | 清零   |
| 锁屏 1–5 分钟                      | −50%   | −30%   |
| 未锁屏，无输入 1–5 分钟            | 不变   | 不变   |
| 场景 A/B 出现后 10 分钟内被“响应”  | 该场景对应的账清零          |

“暂记”（provisional）：不满 5 分钟的无输入停顿先记入（见 effective_time.py），
一旦停顿满 5 分钟，就把这段暂记的分钟从两本账里撤回。
"""

from __future__ import annotations

from dataclasses import dataclass

ACCOUNTS = ("water", "sitting")


@dataclass
class Change:
    """一次削减/清零的记录，写日志用。"""
    rule: str
    water_before: float
    water_after: float
    sitting_before: float
    sitting_after: float

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "water_before": round(self.water_before, 2), "water_after": round(self.water_after, 2),
            "sitting_before": round(self.sitting_before, 2), "sitting_after": round(self.sitting_after, 2),
        }


class Ledger:
    def __init__(self, water: float = 0.0, sitting: float = 0.0):
        self.water = float(water)
        self.sitting = float(sitting)
        self._prov = {"water": 0.0, "sitting": 0.0}   # 暂记、可能被撤回的分钟

    # ── 累加 ──────────────────────────────────────────────────────────────
    def add_minute(self, provisional: bool = False) -> None:
        self.water += 1
        self.sitting += 1
        if provisional:
            self._prov["water"] += 1
            self._prov["sitting"] += 1

    def confirm(self) -> None:
        """停顿没满 5 分钟就恢复了：暂记的分钟转正。"""
        self._prov = {"water": 0.0, "sitting": 0.0}

    def retract(self) -> float:
        """停顿满 5 分钟：撤回暂记的分钟。返回撤回了多少分钟（按饮水账计）。"""
        n = self._prov["water"]
        self.water = max(0.0, self.water - self._prov["water"])
        self.sitting = max(0.0, self.sitting - self._prov["sitting"])
        self._prov = {"water": 0.0, "sitting": 0.0}
        return n

    @property
    def provisional(self) -> float:
        return self._prov["water"]

    # ── 削减 / 清零 ───────────────────────────────────────────────────────
    def _snap(self):
        return self.water, self.sitting

    def _change(self, rule, before) -> Change:
        return Change(rule, before[0], self.water, before[1], self.sitting)

    def clear(self, account: str, rule: str = "clear") -> Change:
        before = self._snap()
        if account not in ACCOUNTS:
            raise ValueError(account)
        setattr(self, account, 0.0)
        self._prov[account] = 0.0
        return self._change(rule, before)

    def apply_lock(self, duration_s: float, P) -> Change | None:
        """锁屏 / 睡眠结束时调用（睡眠视同锁屏）。"""
        self.confirm()
        before = self._snap()
        if duration_s >= P.long_absence_s:
            self.sitting = 0.0
            return self._change("lock_long", before)
        if duration_s >= P.short_absence_s:
            self.water *= (1.0 - P.short_lock_water_cut)
            self.sitting *= (1.0 - P.short_lock_sitting_cut)
            return self._change("lock_short", before)
        return None

    def apply_long_idle(self) -> Change:
        """未锁屏，无输入、无音频满 5 分钟（撤回暂记之后调用）。"""
        before = self._snap()
        self.sitting = 0.0
        self._prov["sitting"] = 0.0
        return self._change("idle_long", before)

    def reset(self) -> None:
        self.water = 0.0
        self.sitting = 0.0
        self.confirm()

    def snapshot(self) -> dict:
        return {"water": round(self.water, 2), "sitting": round(self.sitting, 2)}
