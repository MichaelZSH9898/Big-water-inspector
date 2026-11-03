# -*- coding: utf-8 -*-
"""应用分类表：进程名 → 类别；浏览器再按标题关键词细分。纯逻辑，不碰 Windows。

分类表在 config.toml 的 [categories] 里，用户可自行编辑。标题只在内存里用于分类，用完即弃。
"""

from __future__ import annotations

CATS = ("productivity", "communication", "browser", "entertainment", "meeting")


class CategoryTable:
    def __init__(self, raw_categories: dict):
        c = raw_categories or {}
        self.default = str(c.get("default", "other"))
        self.by_proc: dict[str, str] = {}
        for cat in CATS:
            for name in c.get(cat, []) or []:
                self.by_proc[str(name).lower()] = cat
        bt = c.get("browser_title", {}) or {}
        self.title_rules = [(cat, [str(k).lower() for k in (bt.get(cat) or [])])
                            for cat in ("entertainment", "communication", "meeting", "productivity")]

    def is_browser(self, proc: str) -> bool:
        return self.by_proc.get((proc or "").lower()) == "browser"

    def classify(self, proc: str | None, title: str | None = None) -> str:
        cat = self.by_proc.get((proc or "").lower(), self.default)
        if cat == "browser" and title:
            low = title.lower()
            for sub, words in self.title_rules:
                if any(w and w in low for w in words):
                    return sub
        return cat
