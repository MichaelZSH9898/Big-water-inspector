# -*- coding: utf-8 -*-
"""把旧版本留下、新版本不再使用的文件挪到 _to_delete/ 文件夹（不删除，确认没问题后你可以整个删掉那个文件夹）。

为什么需要：角色包会把姿势文件夹里所有“两位数字_名称.png”都当作图层叠上去。立绘改版后，旧的
10_skin / 20_clothes / 40_face 三层不再使用，但更新程序时只能覆盖、不能删除文件，它们还留在你的文件夹里。
"""

from __future__ import annotations

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBSOLETE = [f"persona/default_mom/poses/{pose}/{layer}.png"
            for pose in ("scold", "peek", "care") for layer in ("10_skin", "20_clothes", "40_face")]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    moved = 0
    for rel in OBSOLETE:
        src = os.path.join(ROOT, *rel.split("/"))
        if not os.path.exists(src):
            continue
        dst = os.path.join(ROOT, "_to_delete", *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        moved += 1
        print("已挪走：", rel)
    print(f"共挪走 {moved} 个旧文件到 _to_delete\\（可以整个删掉）。" if moved else "没有需要整理的旧文件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
