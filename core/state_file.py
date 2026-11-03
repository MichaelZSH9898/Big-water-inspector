# -*- coding: utf-8 -*-
"""两个状态文件。

· state.json        对外接口（第 4 节预留）：每分钟写一次当前状态、两本账、今日有效时长，
                    供以后的“每日一题”读取。哨兵只写不读。字段带版本号，保持稳定。
· data/runtime.json 哨兵自己的持久化：重启后恢复当天的账本、场景计数、暂停状态等。

都用“写临时文件 + os.replace”原子替换，读的一方永远不会读到半个文件。
"""

from __future__ import annotations

import json
import os

STATE_VERSION = 1


def atomic_write_json(path: str, data: dict) -> bool:
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def read_json(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None
