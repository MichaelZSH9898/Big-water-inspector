# -*- coding: utf-8 -*-
"""在 persona/cache 里为一次闪现挑图（只用标准库）。

查找顺序：当前设置对应的缓存（键完全一致）→ 同语言的其他缓存（比如刚改了发色、新图还没渲染完）
→ 任意语言。尺寸挑与目标显示器（高度像素、DPI）最接近的那张。
"""

from __future__ import annotations

import os

from persona import cachekey


class ImageCache:
    def __init__(self, cache_dir: str = cachekey.CACHE_DIR):
        self.dir = cache_dir
        self.key: str | None = None
        self.lang: str = "zh"

    def set_expected(self, key: str, lang: str) -> None:
        self.key, self.lang = key, lang

    def variants(self):
        vs = cachekey.list_variants(self.dir)
        exact = [v for v in vs if v[1].get("key") == self.key and v[1].get("lang") == self.lang]
        same_lang = [v for v in vs if v[1].get("lang") == self.lang and v not in exact]
        others = [v for v in vs if v not in exact and v not in same_lang]
        return exact, same_lang + others

    def has_exact(self, sizes: list[tuple[int, int]]) -> bool:
        exact, _ = self.variants()
        if not exact:
            return False
        have = {(e.get("mon_h"), e.get("dpi")) for e in exact[0][1].get("entries", [])}
        return all((h, d) in have for h, d in sizes)

    def lookup(self, line_key: str, idx: int, mon_h: int, dpi: int):
        """返回 (文件路径, 是否精确匹配)；完全找不到返回 None。"""
        exact, rest = self.variants()
        for group, is_exact in ((exact, True), (rest, False)):
            for d, m in group:
                es = m.get("entries", [])
                cands = [e for e in es if e.get("line_key") == line_key and e.get("idx") == idx] or \
                        [e for e in es if e.get("line_key") == line_key] or \
                        [e for e in es if e.get("line_key") == line_key.replace("_water", "")]
                if not cands:
                    continue
                best = min(cands, key=lambda e: abs(e["mon_h"] - mon_h) + 4 * abs(e["dpi"] - dpi))
                path = os.path.join(d, best["file"])
                if os.path.exists(path):
                    return path, is_exact and best["mon_h"] == mon_h and best["dpi"] == dpi
        return None

    @staticmethod
    def load(path: str) -> tuple[int, int, bytes]:
        with open(path, "rb") as fh:
            return cachekey.unpack(fh.read())
