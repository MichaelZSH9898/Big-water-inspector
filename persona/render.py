# -*- coding: utf-8 -*-
"""立绘渲染（Pillow）：叠图 → 着色 → 台词气泡 → 预乘 BGRA 缓存。

只在设置进程 / 渲染子进程里运行，哨兵进程不 import Pillow。
  · 叠图：按文件名顺序；skin / hair 层是灰度明暗图，乘以所选颜色（保留阴影，不是纯色填充）。
    persona.json 的 tint_adjust 给每个姿势一组通道倍数，让“默认色”在三个姿势上都还原原画。
  · 气泡：养成系游戏对话框——奶油色底、豆沙粉粗描边 + 内侧缝线、白色外描边和柔和投影，
    左上角挂一块“妈妈”名牌，右上角贴一枚表情贴纸（怒气符号 / 汗滴 / 水滴 / 爱心），右下角一个 ▼。
    字体用角色包自带的 OFL 字体（中文站酷快乐体、英文 Nunito），缺字时回退到系统字体。
  · 尺寸：立绘高度 = 显示器高度 × figure_height_ratio（默认 22%）× 场景的 figure_scale；字号按 DPI 缩放。

命令行：
    python -m persona.render --ensure            按当前设置和当前显示器重建缓存（哨兵发现缺图时会自动调用）
    python -m persona.render --preview out.png   出一张三个场景的预览图
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import shutil
import sys
import time

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from persona import cachekey  # noqa: E402
from persona.lines import lines_for_config  # noqa: E402
from persona.loader import Persona, load_with_fallback  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 系统字体回退（角色包没带字体或缺字时）：圆体 → 雅黑 → 思源
FONT_CANDIDATES = [
    "SIMYOU.TTF", "msyhbd.ttc", "msyh.ttc",
    "NotoSansCJK-Bold.ttc", "NotoSansCJKsc-Bold.otf", "NotoSansSC-Bold.otf", "NotoSansCJK-Regular.ttc",
    "NotoSerifCJK-Bold.ttc", "SourceHanSansSC-Bold.otf", "wqy-microhei.ttc",
]


def _font_dirs() -> list[str]:
    dirs = []
    if os.name == "nt":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(os.path.join(windir, "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]
    return dirs


def find_font() -> tuple[str | None, int]:
    """系统字体：返回 (字体文件, ttc 内的序号)。.ttc 里挑简体中文那一款。"""
    files: dict[str, str] = {}
    for d in _font_dirs():
        for p in glob.glob(os.path.join(d, "**", "*.*"), recursive=True):
            files.setdefault(os.path.basename(p).lower(), p)
    for cand in FONT_CANDIDATES:
        p = files.get(cand.lower())
        if not p:
            continue
        if p.lower().endswith(".ttc"):
            for i in range(12):
                try:
                    f = ImageFont.truetype(p, 20, index=i)
                except OSError:
                    break
                fam = " ".join(f.getname())
                if " SC" in fam or "SC " in fam or "YaHei" in fam or "雅黑" in fam or "Micro Hei" in fam:
                    return p, i
            return p, 0
        return p, 0
    return None, 0


_FONT_CACHE: dict = {}


def get_font(px: int, path: str | None = None, weight: int | None = None):
    """path 为角色包字体（可为空）；weight 用于可变字体（如 Nunito 的 800 = ExtraBold）。"""
    if path:
        try:
            f = ImageFont.truetype(path, px)
            if weight:
                try:
                    f.set_variation_by_axes([weight])
                except Exception:  # noqa: BLE001 — 不是可变字体 / FreeType 不支持
                    pass
            return f
        except OSError:
            pass
    sys_path, idx = _FONT_CACHE.get("path") or find_font()
    _FONT_CACHE["path"] = (sys_path, idx)
    if sys_path is None:
        return ImageFont.load_default(size=px)
    return ImageFont.truetype(sys_path, px, index=idx)


def covers(font, text: str) -> bool:
    """字体里是否每个字都有（没有的字会画成豆腐块）。"""
    key = ("notdef", getattr(font, "path", None), getattr(font, "size", None))
    tofu = _FONT_CACHE.get(key)
    if tofu is None:
        m = font.getmask("\U0010FFFD")
        tofu = _FONT_CACHE[key] = (m.size, bytes(m))
    for ch in set(text):
        if ch.isspace():
            continue
        m = font.getmask(ch)
        if (m.size, bytes(m)) == tofu:
            return False
    return True


def text_font(persona: Persona | None, style: dict, lang: str, px: int, text: str = ""):
    """气泡正文字体：角色包字体（覆盖全部字时）→ 系统字体。按台词本身的文字选：英文界面里写了中文台词也用中文字体。"""
    if text:                                       # 按台词本身的文字选字体：中文用中文字体，纯英文用英文字体
        lang = "zh" if any(_is_cjk(ch) for ch in text) else "en"
    spec = (style.get("font") or {}).get(lang) if isinstance(style.get("font"), dict) else None
    path, weight = None, None
    if spec and persona is not None:
        if isinstance(spec, dict):
            path, weight = spec.get("file"), spec.get("weight")
        else:
            path = spec
        path = os.path.join(persona.dir, path) if path else None
    if path and os.path.exists(path):
        f = get_font(px, path, weight)
        if not text or covers(f, text):
            return f
    return get_font(px)


# ── 着色与叠图 ───────────────────────────────────────────────────────────────
def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def tint(layer: Image.Image, color: str, mult=None) -> Image.Image:
    """灰度明暗图 × 颜色：亮处接近所选颜色，暗处按比例变深，阴影保留。
    mult：每个通道再乘的倍数（来自 tint_adjust，可大于 1），结果截到 255。"""
    layer = layer.convert("RGBA")
    gray = layer.convert("L")
    rgb = hex_rgb(color)
    mult = mult or (1.0, 1.0, 1.0)
    chans = []
    for c, m in zip(rgb, mult):
        k = c * float(m) / 255.0
        chans.append(gray.point([min(255, int(v * k + 0.5)) for v in range(256)]))
    out = Image.merge("RGB", chans)
    out.putalpha(layer.getchannel("A"))
    return out


def compose_pose(persona: Persona, pose: str, hair: str, character: str | None = None) -> Image.Image:
    """叠图：character = 角色 id（肤色）。皮肤层（如有）按角色的肤色着色，头发层按所选发色 × 该角色该姿势的倍数着色。"""
    ch = persona.character(character)
    layers = ch.poses[pose]
    adj = (ch.tint_adjust or {}).get(pose) or {}
    skin = ch.skin
    base = None
    for ly in sorted(layers, key=lambda x: (x.order, x.name)):
        img = Image.open(ly.path).convert("RGBA")
        if ly.tint == "hair":
            img = tint(img, hair, adj.get("hair"))
        elif ly.tint == "skin":
            img = tint(img, skin, adj.get("skin"))
        if base is None:
            base = Image.new("RGBA", img.size, (0, 0, 0, 0))
        if img.size != base.size:
            img = img.resize(base.size, Image.LANCZOS)
        base = Image.alpha_composite(base, img)
    return base


# ── 气泡 ─────────────────────────────────────────────────────────────────────
def _is_cjk(ch: str) -> bool:
    return "\u2e80" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff" or "\uff00" <= ch <= "\uffef" or \
        "\u3000" <= ch <= "\u303f"


NO_LINE_START = set("，。！？、；：”’）》」』…—!?,.;:)")


def wrap(text: str, font, max_w: float) -> list[str]:
    return wrap_ex(text, font, max_w)[0]


def wrap_ex(text: str, font, max_w: float) -> tuple[list[str], int]:
    """断行：中文先按标点切成短句再装行（短句太长才按字拆，且标点不出现在行首），英文按词装行。
    返回 (各行, 被迫按字拆开的短句数)。"""
    if any(_is_cjk(ch) for ch in text):
        units = [u for u in re.findall(r"[^，。！？；：、]*[，。！？；：、]*", text) if u]
    else:
        units = re.findall(r"\S+\s*", text)
    lines: list[str] = []
    cur = ""
    forced = 0
    for u in units:
        cand = (cur + u) if cur else u.lstrip()
        if font.getlength(cand.rstrip()) <= max_w:
            cur = cand
            continue
        if cur:
            lines.append(cur.rstrip())
            cur = ""
        u = u.lstrip()
        if font.getlength(u.rstrip()) <= max_w:
            cur = u
            continue
        forced += 1
        for ch in u:                               # 单个短句也放不下：按字拆
            trial = cur + ch
            if cur and font.getlength(trial.rstrip()) > max_w and ch not in NO_LINE_START:
                lines.append(cur.rstrip())
                cur = ch
            else:
                cur = trial
    if cur.strip():
        lines.append(cur.rstrip())
    return lines, forced


def balanced_lines(text: str, font, fpx: int, max_w: float) -> list[str]:
    """均衡断行：行数不变、也不多拆短句的前提下把宽度收到最小，避免最后一行只剩一两个字。"""
    lines, forced = wrap_ex(text, font, max_w)
    lo, hi = fpx * 4.0, max_w
    while hi - lo > fpx * 0.25 and len(lines) > 1:
        mid = (lo + hi) / 2
        ln2, f2 = wrap_ex(text, font, mid)
        if len(ln2) == len(lines) and f2 <= forced:
            hi = mid
        else:
            lo = mid
    return wrap(text, font, hi)


def _rgba(h: str, a: int = 255) -> tuple[int, int, int, int]:
    return hex_rgb(h) + (a,)


def _vgrad(size, top: str, bottom: str) -> Image.Image:
    w, h = size
    t, b = hex_rgb(top), hex_rgb(bottom)
    col = Image.new("RGB", (1, h))
    col.putdata([tuple(round(t[i] + (b[i] - t[i]) * y / max(1, h - 1)) for i in range(3)) for y in range(h)])
    return col.resize((w, h))


def _grow(mask: Image.Image, r: float) -> Image.Image:
    """把蒙版向外长 r 像素（圆角，抗锯齿）。"""
    if r <= 0:
        return mask
    k = int(math.ceil(r))
    big = mask.filter(ImageFilter.MaxFilter(2 * k + 1)) if k <= 6 else \
        mask.filter(ImageFilter.GaussianBlur(r * 0.6)).point(lambda v: 255 if v > 18 else v * 255 // 18)
    return big.filter(ImageFilter.GaussianBlur(0.6))


def _shrink(mask: Image.Image, r: float) -> Image.Image:
    k = max(1, int(round(r)))
    return mask.filter(ImageFilter.MinFilter(2 * k + 1))


def _rr_points(x0, y0, x1, y1, r, step):
    """圆角矩形周长上等距的点（画缝线用）。"""
    pts = []
    segs = []
    r = max(1.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    segs.append(("l", (x0 + r, y0), (x1 - r, y0)))
    segs.append(("a", (x1 - r, y0 + r), -90, 0))
    segs.append(("l", (x1, y0 + r), (x1, y1 - r)))
    segs.append(("a", (x1 - r, y1 - r), 0, 90))
    segs.append(("l", (x1 - r, y1), (x0 + r, y1)))
    segs.append(("a", (x0 + r, y1 - r), 90, 180))
    segs.append(("l", (x0, y1 - r), (x0, y0 + r)))
    segs.append(("a", (x0 + r, y0 + r), 180, 270))
    path = []
    for s in segs:
        if s[0] == "l":
            (ax, ay), (bx, by) = s[1], s[2]
            n = max(1, int(math.hypot(bx - ax, by - ay)))
            path += [(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n)]
        else:
            (cx, cy), a0, a1 = s[1], s[2], s[3]
            n = max(2, int(r * math.pi / 2))
            path += [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
                      cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n)]
    acc = 0.0
    for i in range(1, len(path)):
        acc += math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1])
        if acc >= step:
            pts.append(path[i])
            acc = 0.0
    return pts


def _heart(d: ImageDraw.ImageDraw, cx, cy, s, fill):
    r = s * 0.27
    d.ellipse([cx - s * 0.5, cy - s * 0.36, cx - s * 0.5 + 2 * r, cy - s * 0.36 + 2 * r], fill=fill)
    d.ellipse([cx + s * 0.5 - 2 * r, cy - s * 0.36, cx + s * 0.5, cy - s * 0.36 + 2 * r], fill=fill)
    d.polygon([(cx - s * 0.49, cy - s * 0.12), (cx + s * 0.49, cy - s * 0.12), (cx, cy + s * 0.45)], fill=fill)


def _drop(d: ImageDraw.ImageDraw, cx, cy, s, fill, tilt=0.0):
    """水滴：下圆上尖。"""
    r = s * 0.32
    pts = []
    for i in range(60):
        t = i / 59 * 2 * math.pi
        x = math.sin(t) * r
        y = -math.cos(t) * r
        if -math.cos(t) < 0:                      # 上半部收成尖
            k = (math.cos(t)) ** 1.6
            x *= 1 - 0.85 * k
            y -= k * s * 0.32
        pts.append((x, y + s * 0.12))
    ca, sa = math.cos(tilt), math.sin(tilt)
    d.polygon([(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts], fill=fill)


def emote_sticker(kind: str, size: int) -> Image.Image | None:
    """表情贴纸（白色描边）：anger 怒气符号 / sweat 汗滴 / drop 水滴 / heart 爱心。"""
    if kind not in ("anger", "sweat", "drop", "heart"):
        return None
    S = size * 4
    shape = Image.new("L", (S, S), 0)
    color = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(color)
    ds = ImageDraw.Draw(shape)
    c = S / 2
    if kind == "anger":                             # 💢：四段朝中心鼓起的弧
        red = (232, 72, 88, 255)
        w = round(S * 0.085)
        k, r = S * 0.37, S * 0.30
        for (sx, sy), start in (((-1, -1), 0), ((1, -1), 90), ((1, 1), 180), ((-1, 1), 270)):
            ox, oy = c + sx * k, c + sy * k
            bb = [ox - r, oy - r, ox + r, oy + r]
            ds.arc(bb, start + 8, start + 82, fill=255, width=w)
            d.arc(bb, start + 8, start + 82, fill=red, width=w)
    elif kind == "heart":
        _heart(ds, c, c, S * 0.78, 255)
        _heart(d, c, c, S * 0.78, (240, 112, 146, 255))
        d.ellipse([c - S * 0.26, c - S * 0.2, c - S * 0.14, c - S * 0.08], fill=(255, 255, 255, 220))
    else:
        tilt = -0.35 if kind == "sweat" else 0.0
        fill = (126, 196, 238, 255) if kind == "drop" else (150, 210, 240, 255)
        _drop(ds, c, c, S * 0.9, 255, tilt)
        _drop(d, c, c, S * 0.9, fill, tilt)
        d.ellipse([c - S * 0.13, c - S * 0.02, c - S * 0.03, c + S * 0.12], fill=(255, 255, 255, 230))
    outline = shape.filter(ImageFilter.MaxFilter(2 * round(S * 0.05) + 1)).filter(ImageFilter.GaussianBlur(1.5))
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste((255, 255, 255, 255), (0, 0), outline)
    out.alpha_composite(color)
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow.paste((150, 90, 110, 80), (0, round(S * 0.03)), outline)
    shadow = shadow.filter(ImageFilter.GaussianBlur(S * 0.03))
    shadow.alpha_composite(out)
    return shadow.resize((size, size), Image.LANCZOS)


DEFAULT_STYLE = {
    "fill_top": "#FFFDF8", "fill_bottom": "#FFF0E3", "border": "#C9849B", "stitch": "#F1C3D0",
    "ink": "#5B3A35", "tag_top": "#E9A3B8", "tag_bottom": "#CC7893", "tag_ink": "#FFFFFF",
    "name": {"zh": "妈妈", "en": "Mom"}, "emotes": {},
}


def bubble(text: str, lang: str, scale: float, style: dict, tail: str, tail_y_frac: float = 0.55,
           persona: Persona | None = None, emote: str | None = None):
    """画一个养成系游戏风格的对话框。tail = "left"/"right"：尾巴朝哪边（指向人物）。
    返回 (图, 尾巴尖的 y)。"""
    st = dict(DEFAULT_STYLE)
    st.update({k: v for k, v in (style or {}).items() if v not in (None, "")})
    if "paper" in (style or {}) and "fill_top" not in style:      # 兼容旧角色包的配色字段
        st["fill_top"] = st["fill_bottom"] = style["paper"]
    cjk = any(_is_cjk(ch) for ch in text)
    fpx = max(12, round((20 if cjk else 19) * scale))
    font = text_font(persona, st, lang, fpx, text)
    max_w = fpx * (13 if cjk else 17)
    lines = balanced_lines(text, font, fpx, max_w)
    lh = round(fpx * 1.46)
    text_w = max(font.getlength(ln) for ln in lines)
    asc = font.getbbox("国Ag")[1]

    bw_ = max(1, round(fpx * 0.17))                # 描边粗细
    white = max(2, round(fpx * 0.2))               # 白色外描边
    pad_x, pad_t, pad_b = round(fpx * 1.05), round(fpx * 1.0), round(fpx * 0.95)
    bw = round(max(text_w, fpx * 5) + pad_x * 2)
    bh = round(lh * (len(lines) - 1) + fpx * 1.12 + pad_t + pad_b)
    rad = round(min(fpx * 1.0, bh / 2))
    tail_len = round(fpx * 1.0)
    tag_px = max(10, round(fpx * 0.72))
    tag_font = text_font(persona, st, lang, tag_px, str((st.get("name") or {}).get(lang, "")))
    tag_h = round(tag_px * 1.75)
    emo = round(fpx * 2.0) if emote else 0
    m = white + round(fpx * 0.5)                   # 四周留白（投影、白描边）
    top_extra = max(tag_h // 2, emo // 2)
    W = bw + tail_len + 2 * m + emo // 3
    H = bh + 2 * m + top_extra
    bx = m + (tail_len if tail == "left" else 0)
    by = m + top_extra

    # 形状：圆角矩形 + 小尾巴（尾巴略向下，像从人物那边说出来）
    shape = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(shape)
    d.rounded_rectangle([bx, by, bx + bw, by + bh], rad, fill=255)
    ty = by + max(rad, min(bh - rad, bh * tail_y_frac))
    half = tail_len * 0.55
    if tail == "left":
        d.polygon([(bx + rad * 0.3, ty - half), (bx - tail_len, ty + half * 0.9), (bx + rad * 0.3, ty + half)], fill=255)
        tip = (bx - tail_len, ty + half * 0.9)
    else:
        x1 = bx + bw
        d.polygon([(x1 - rad * 0.3, ty - half), (x1 + tail_len, ty + half * 0.9), (x1 - rad * 0.3, ty + half)], fill=255)
        tip = (x1 + tail_len, ty + half * 0.9)
    shape = shape.filter(ImageFilter.GaussianBlur(0.5))

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    outer = _grow(shape, white)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh.paste((150, 88, 110, 90), (0, round(fpx * 0.22)), outer)
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(fpx * 0.28)))
    img.paste((255, 255, 255, 255), (0, 0), outer)
    img.paste(_rgba(st["border"]), (0, 0), shape)
    inner = _shrink(shape, bw_).filter(ImageFilter.GaussianBlur(0.5))
    img.paste(_vgrad((W, H), st["fill_top"], st["fill_bottom"]), (0, 0), inner)

    # 内侧缝线（虚线），养成游戏的布艺感
    dd = ImageDraw.Draw(img)
    ins = bw_ + round(fpx * 0.3)
    dot = max(1.0, fpx * 0.075)
    for (x, y) in _rr_points(bx + ins, by + ins, bx + bw - ins, by + bh - ins, rad - ins, fpx * 0.42):
        dd.ellipse([x - dot, y - dot, x + dot, y + dot], fill=_rgba(st["stitch"]))

    # 正文
    y = by + pad_t - asc + round(fpx * 0.05)
    for ln in lines:
        dd.text((bx + pad_x, y), ln, font=font, fill=_rgba(st["ink"]))
        y += lh

    # ▼ 继续提示
    s = fpx * 0.36
    cx, cy = bx + bw - pad_x * 0.62, by + bh - pad_b * 0.55
    dd.polygon([(cx - s, cy - s * 0.55), (cx + s, cy - s * 0.55), (cx, cy + s * 0.6)], fill=_rgba(st["tag_bottom"]))

    # 名牌
    name = (st.get("name") or {}).get(lang) or (st.get("name") or {}).get("zh") or ""
    if name:
        icon = round(tag_px * 0.9)
        tw = tag_font.getlength(name)
        tagw = round(tw + icon + tag_px * 1.6)
        tx = bx + round(fpx * 0.8) if tail != "left" else bx + round(fpx * 0.9)
        tyy = by - tag_h // 2
        tag = Image.new("L", (W, H), 0)
        ImageDraw.Draw(tag).rounded_rectangle([tx, tyy, tx + tagw, tyy + tag_h], tag_h // 2, fill=255)
        img.paste((255, 255, 255, 255), (0, 0), _grow(tag, max(2, round(white * 0.8))))
        img.paste(_vgrad((W, H), st["tag_top"], st["tag_bottom"]), (0, 0), tag)
        td = ImageDraw.Draw(img)
        _heart(td, tx + tag_px * 0.75 + icon / 2 - icon * 0.1, tyy + tag_h / 2, icon * 0.9, _rgba(st["tag_ink"]))
        tasc = tag_font.getbbox(name)
        td.text((tx + tag_px * 0.75 + icon + tag_px * 0.25, tyy + (tag_h - (tasc[3] - tasc[1])) / 2 - tasc[1]),
                name, font=tag_font, fill=_rgba(st["tag_ink"]))

    # 表情贴纸（右上角；尾巴在右时放左上角之外的另一侧，避免挡名牌）
    if emote:
        stk = emote_sticker(emote, emo)
        if stk is not None:
            ex = bx + bw - emo + emo // 3 if tail != "right" else bx + bw - emo - round(fpx * 0.2)
            img.alpha_composite(stk, (max(0, int(ex)), max(0, by - emo // 2 - round(fpx * 0.15))))
    img.info["body"] = (bx, by, bx + bw, by + bh)          # 气泡正文区域（设置界面点它来改台词）
    return img, tip[1]


def fpx_gap(dpi: int, font_scale: float) -> float:
    return 4 * dpi / 96.0 * font_scale


def render_flash(persona: Persona, scene_name: str, text: str, lang: str, hair: str, character: str | None,
                 mon_h: int, dpi: int, ratio: float = 0.22, font_scale: float = 1.0,
                 line_key: str | None = None) -> Image.Image:
    spec = persona.scene(scene_name)
    pose = spec.get("pose")
    side = spec.get("bubble", "left")
    fig = compose_pose(persona, pose, hair, character)
    bbox = fig.getchannel("A").getbbox()
    if bbox:                                       # 去掉四周的透明留白（探头姿势的右缘要贴屏幕边，保留）
        right = fig.width if spec.get("flush_right") else bbox[2]
        fig = fig.crop((bbox[0], bbox[1], right, fig.height))
    fh = max(60, round(mon_h * ratio * float(spec.get("figure_scale", 1.0) or 1.0)))
    fw = max(1, round(fig.width * fh / fig.height))
    fig = fig.resize((fw, fh), Image.LANCZOS)
    fade = float(spec.get("fade_bottom", 0) or 0)
    if fade > 0:                                   # 半身像下缘淡出，不留一刀切的硬边
        n = max(1, round(fh * fade))
        grad = Image.linear_gradient("L").resize((1, n)).transpose(Image.FLIP_TOP_BOTTOM)
        mask = Image.new("L", (fw, fh), 255)
        mask.paste(grad.resize((fw, n)), (0, fh - n))
        fig.putalpha(ImageChops.multiply(fig.getchannel("A"), mask))
    scale = dpi / 96.0 * font_scale
    tail = "left" if side == "right" else "right"
    style = dict(persona.meta.get("bubble", {}) or {})
    own_name = persona.character(character).bubble_name
    if own_name:                                   # 每个角色可以有自己的称呼（Mama、Mummy……）
        style["name"] = {**(style.get("name") or {}), **own_name}
    emotes = style.get("emotes") or {}
    emote = emotes.get(line_key or scene_name) or emotes.get(scene_name)
    bub, _ = bubble(text, lang, scale, style, tail, persona=persona, emote=emote)
    gap = round(fpx_gap(dpi, font_scale))         # 气泡尾巴与立绘之间留一点空
    overlap = round(fw * float(spec.get("bubble_overlap", 0.0) or 0.0))
    W = fw + gap + bub.width - overlap
    top = round(fh * float(spec.get("bubble_top", 0.04)))
    H = max(fh, top + bub.height)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fy = H - fh
    by = fy + top if fy + top + bub.height <= H else 0
    bx = fw + gap - overlap if side == "right" else 0
    if side == "right":
        out.alpha_composite(fig, (0, fy))
        out.alpha_composite(bub, (bx, by))
    else:
        out.alpha_composite(bub, (0, by))
        out.alpha_composite(fig, (bub.width + gap - overlap, fy))
    b = bub.info.get("body")
    if b:
        out.info["bubble_box"] = (bx + b[0], by + b[1], bx + b[2], by + b[3])
    return out


def to_pbgra(img: Image.Image) -> bytes:
    img = img.convert("RGBA")
    pm = img.convert("RGBa")                    # 预乘 alpha
    r, g, b, a = pm.split()
    raw = Image.merge("RGBA", (b, g, r, a)).tobytes()
    return cachekey.pack(img.width, img.height, raw)


# ── 缓存 ─────────────────────────────────────────────────────────────────────
def scene_line_keys(persona: Persona, lines: dict) -> list[tuple[str, str, int, str]]:
    """[(场景名, 台词键, 序号, 台词)]。side_peek 额外渲染饮水变体。lines = 实际要用的台词（见 lines_for_config）。"""
    out = []
    for sc in persona.meta.get("scenes", {}):
        keys = [sc] + (["side_peek_water"] if sc == "side_peek" else [])
        for k in keys:
            for i, t in enumerate(lines.get(k, [])):
                out.append((sc, k, i, t))
    return out


def ensure(cfg, monitors: list[tuple[int, int]], persona: Persona | None = None, force: bool = False,
           cache_dir: str = cachekey.CACHE_DIR, log=print) -> str:
    """按当前设置为每块显示器（高度像素, DPI）渲染全部台词图。返回缓存目录。"""
    persona = persona or load_with_fallback(cfg.persona)[0]
    key = cachekey.variant_key(persona, cfg)
    lang = cfg.language
    vdir = os.path.join(cache_dir, f"{lang}-{key}")
    old = cachekey.read_manifest(vdir) if os.path.isdir(vdir) else None
    have = {(e["line_key"], e["idx"], e["mon_h"], e["dpi"]) for e in (old or {}).get("entries", [])}
    ap, disp = cfg.raw["appearance"], cfg.raw["display"]
    ratio, fscale = float(disp.get("figure_height_ratio", 0.22)), float(disp.get("font_scale", 1.0))
    entries = list((old or {}).get("entries", [])) if not force else []
    os.makedirs(vdir, exist_ok=True)
    mons = sorted(set((int(h), int(d)) for h, d in monitors))
    made = 0
    for sc, k, i, text in scene_line_keys(persona, lines_for_config(persona, cfg)):
        for mon_h, dpi in mons:
            if not force and (k, i, mon_h, dpi) in have:
                continue
            img = render_flash(persona, sc, text, lang, ap["hair_color"], ap.get("character"), mon_h, dpi, ratio,
                               fscale, line_key=k)
            fn = f"{k}-{i}-h{mon_h}-d{dpi}.pbgra"
            with open(os.path.join(vdir, fn), "wb") as fh:
                fh.write(to_pbgra(img))
            entries.append({"scene": sc, "line_key": k, "idx": i, "mon_h": mon_h, "dpi": dpi, "file": fn,
                            "w": img.width, "h": img.height})
            made += 1
    manifest = {"v": 1, "key": key, "persona": persona.name, "lang": lang, "created": time.time(),
                "hair": ap["hair_color"], "character": persona.character(ap.get("character")).id, "entries": entries}
    tmp = os.path.join(vdir, "manifest.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(vdir, "manifest.json"))
    _prune(cache_dir, keep=vdir)
    if log:
        log(f"渲染缓存：{vdir}（新画 {made} 张，共 {len(entries)} 张）")
    return vdir


def _prune(cache_dir: str, keep: str, max_variants: int = 4) -> None:
    """只保留最近的几个变体（以及预置的 prebuilt-*）。"""
    variants = [v for v in cachekey.list_variants(cache_dir) if not os.path.basename(v[0]).startswith("prebuilt")]
    for d, _ in variants[max_variants:]:
        if os.path.abspath(d) != os.path.abspath(keep):
            shutil.rmtree(d, ignore_errors=True)


def preview_sheet(cfg, persona: Persona | None = None, mon_h: int = 1080, dpi: int = 96) -> Image.Image:
    persona = persona or load_with_fallback(cfg.persona)[0]
    ap, disp = cfg.raw["appearance"], cfg.raw["display"]
    lines = lines_for_config(persona, cfg)
    imgs = [render_flash(persona, sc, lines[sc][0], cfg.language, ap["hair_color"], ap.get("character"), mon_h, dpi,
                         float(disp.get("figure_height_ratio", 0.22)), float(disp.get("font_scale", 1.0)),
                         line_key=sc)
            for sc in ("unlock_scold", "side_peek", "overtime_care")]
    pad = 24
    W = max(i.width for i in imgs) + pad * 2
    H = sum(i.height for i in imgs) + pad * (len(imgs) + 1)
    sheet = Image.new("RGBA", (W, H), (226, 232, 236, 255))
    y = pad
    for im in imgs:
        sheet.alpha_composite(im, (pad, y))
        y += im.height + pad
    return sheet


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    from core import config as config_mod
    ap = argparse.ArgumentParser(description="渲染角色立绘缓存")
    ap.add_argument("--ensure", action="store_true", help="按当前显示器补齐缓存")
    ap.add_argument("--force", action="store_true", help="全部重画")
    ap.add_argument("--preview", metavar="PNG", help="输出三个场景的预览图")
    ap.add_argument("--size", default="1080x96", help="预览用的 显示器高度x DPI，如 1440x120")
    ap.add_argument("--notify", action="store_true", help="完成后通知哨兵重新加载")
    ap.add_argument("--sizes", help="要渲染的显示器尺寸，如 1800x192,1080x96（哨兵会传入；不传就自己查）")
    a = ap.parse_args(argv)
    cfg = config_mod.load()
    for e in cfg.errors:
        print(e)
    persona, err = load_with_fallback(cfg.persona)
    if err:
        print(err)
    if a.preview:
        h, d = (int(x) for x in a.size.lower().split("x"))
        preview_sheet(cfg, persona, h, d).save(a.preview)
        print("预览：", a.preview)
    if a.ensure or a.force:
        if a.sizes:
            sizes = [tuple(int(v) for v in x.lower().split("x")) for x in a.sizes.split(",") if "x" in x]
        else:
            from winapi import monitors as mon
            from winapi.win32 import set_dpi_awareness
            set_dpi_awareness()                    # 不声明的话 Windows 会按 96 DPI 虚拟化，查到的屏幕尺寸是错的
            sizes = mon.monitor_sizes()
        sizes = sizes or [(1080, 96)]
        ensure(cfg, sizes, persona, force=a.force)
        if a.notify:
            from winapi import ipc
            ipc.notify_reload()
    return 0


if __name__ == "__main__":
    sys.exit(main())
