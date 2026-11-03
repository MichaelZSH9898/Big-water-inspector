# -*- coding: utf-8 -*-
"""改写 config.toml 里的个别键，保留其余内容和全部注释（标准库没有 TOML 写入器，也不需要）。"""

from __future__ import annotations

import os
import re

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

_SECTION = re.compile(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$")


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def update_text(text: str, updates: dict) -> str:
    """updates: {"general.language": "en", "appearance.hair_color": "#112233"}"""
    lines = text.splitlines(keepends=True)
    pending = {}
    for dotted, v in updates.items():
        sec, key = dotted.rsplit(".", 1)
        pending.setdefault(sec, {})[key] = v
    section = None
    done: set[tuple[str, str]] = set()
    section_end: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = _SECTION.match(line)
        if m:
            section = m.group(1).strip()
            section_end[section] = i + 1
            continue
        if section is not None and line.strip():
            section_end[section] = i + 1
        if section in pending:
            for key, v in pending[section].items():
                km = re.match(rf"^(\s*{re.escape(key)}\s*=\s*)(\"(?:[^\"\\\\]|\\\\.)*\"|[^#\n]*?)(\s*(#.*)?)(\r?\n)?$", line)
                if km:
                    nl = km.group(5) or ""
                    lines[i] = f"{km.group(1)}{_fmt(v)}{km.group(3) or ''}{nl}"
                    done.add((section, key))
    # 文件里没有的键：插到对应 section 末尾；没有的 section：追加
    inserts: list[tuple[int, str]] = []
    tail = []
    for sec, kv in pending.items():
        missing = {k: v for k, v in kv.items() if (sec, k) not in done}
        if not missing:
            continue
        block = "".join(f"{k} = {_fmt(v)}\n" for k, v in missing.items())
        if sec in section_end:
            inserts.append((section_end[sec], block))
        else:
            tail.append(f"\n[{sec}]\n{block}")
    for idx, block in sorted(inserts, reverse=True):
        lines.insert(idx, block)
    out = "".join(lines)
    if tail:
        if not out.endswith("\n"):
            out += "\n"
        out += "".join(tail)
    return out


def update_file(path: str, updates: dict) -> None:
    """改写并校验；新内容解析失败就不落盘。"""
    with open(path, "r", encoding="utf-8") as fh:
        old = fh.read()
    new = update_text(old, updates)
    if tomllib is not None:
        tomllib.loads(new)              # 写坏了直接抛异常，原文件不动
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(new)
    os.replace(tmp, path)
