# -*- coding: utf-8 -*-
"""渲染缓存的“版本键”与 .pbgra 文件格式。只用标准库：哨兵和渲染器共用。

.pbgra = 8 字节魔数 b"PBGRA1\\0\\0" + 宽、高（各 4 字节小端）+ zlib 压缩的“预乘 alpha 的 BGRA”像素（自上而下）。
哨兵读它只需要 zlib 解压，然后直接拷进 DIB 交给 UpdateLayeredWindow，不需要任何图像库。
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib

RENDER_VERSION = 4
MAGIC = b"PBGRA1\0\0"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")


def variant_key(persona, cfg) -> str:
    """角色包内容 + 外观设置 + 语言 + 显示参数 → 键。任何一项变了，缓存就要重建。"""
    from persona.lines import lines_for_config
    ap = cfg.raw.get("appearance", {})
    disp = cfg.raw.get("display", {})
    blob = json.dumps({
        "r": RENDER_VERSION, "persona": persona.name, "fp": persona.fingerprint(),
        "hair": str(ap.get("hair_color", "")).lower(), "character": persona.character(ap.get("character")).id,
        "lang": cfg.language, "ratio": disp.get("figure_height_ratio"), "font": disp.get("font_scale"),
        "lines": lines_for_config(persona, cfg),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def pack(width: int, height: int, premul_bgra: bytes) -> bytes:
    return MAGIC + struct.pack("<II", width, height) + zlib.compress(premul_bgra, 6)


def unpack(blob: bytes) -> tuple[int, int, bytes]:
    if blob[:8] != MAGIC:
        raise ValueError("不是 .pbgra 文件")
    w, h = struct.unpack("<II", blob[8:16])
    data = zlib.decompress(blob[16:])
    if len(data) != w * h * 4:
        raise ValueError(".pbgra 像素长度不对")
    return w, h, data


def read_manifest(variant_dir: str) -> dict | None:
    try:
        with open(os.path.join(variant_dir, "manifest.json"), "r", encoding="utf-8") as fh:
            m = json.load(fh)
        return m if isinstance(m, dict) else None
    except (OSError, ValueError):
        return None


def list_variants(cache_dir: str = CACHE_DIR) -> list[tuple[str, dict]]:
    out = []
    if not os.path.isdir(cache_dir):
        return out
    for name in os.listdir(cache_dir):
        d = os.path.join(cache_dir, name)
        m = read_manifest(d) if os.path.isdir(d) else None
        if m:
            out.append((d, m))
    out.sort(key=lambda x: x[1].get("created", 0), reverse=True)
    return out
