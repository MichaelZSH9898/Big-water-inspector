# -*- coding: utf-8 -*-
"""设置界面的“画面”：整张界面用 Pillow 画成一张图，再给出可点击的热区。

不含任何 tkinter 代码——界面长什么样、哪里能点，都可以在任何系统上渲染出来检查和测试。
app.py 只负责把图贴到窗口上、把鼠标点击对应到热区。

画风：养成系游戏的“角色设定 / 换装”界面——奶油粉底、圆角白卡片、丝带标题、糖果按钮、圆形色块、
角色卡（立绘 + 性格标签 + 今日状态条）。配色取自角色设定图：豆沙粉针织衫、奶油色衬衫、暖棕。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from persona import render
from persona.loader import BASE_DIR, DEFAULT_PERSONA

FONT_DIR = os.path.join(BASE_DIR, DEFAULT_PERSONA, "fonts")
FONT_ZH = os.path.join(FONT_DIR, "ZCOOLKuaiLe-Regular.ttf")
FONT_EN = os.path.join(FONT_DIR, "Nunito-Variable.ttf")

W, H = 1040, 660            # 逻辑像素（96 DPI 下的尺寸），实际按显示器缩放

# 配色
BG_TOP, BG_BOTTOM = "#FFF7F2", "#FBE4EB"
CARD = "#FFFFFF"
CARD_EDGE = "#F4D4DE"
ROSE, ROSE_DK, ROSE_LT = "#DD8AA3", "#C46F8A", "#F9DDE6"
MAUVE = "#A9788A"
INK = "#5B3A35"
MUTED = "#A08681"
WATER, SITTING, ACTIVE = "#78C1EC", "#F2B05A", "#8CCB8A"
PASTELS = ["#FBD3DF", "#FFE0C7", "#E5DAF6", "#D3EFDF"]
PASTEL_INK = ["#C25F7E", "#C9773F", "#7D62B5", "#3E9A6A"]

TEXT = {
    "zh": {"ribbon": "大水理论最严厉的母亲 · 设置", "card": "妈妈形象", "dress": "妈妈形象", "hair": "发色", "skin": "形象",
           "lang": "语言", "custom": "自选", "preview": "闪现预览", "today": "今日状态", "thirst": "口渴值",
           "sitting": "久坐值", "active": "今日有效", "min": "分钟", "off": "督察员还没在运行",
           "save": "保存", "demo": "保存并演示", "close": "关闭", "persona_err": "角色包有问题，已用默认角色包：",
           "scenes": {"unlock_scold": "解锁训话", "side_peek": "侧边探头", "overtime_care": "加班关怀"},
           "where": {"unlock_scold": "锁屏回来时 · 屏幕中央偏上", "side_peek": "久坐时 · 从右边缘探头",
                     "overtime_care": "加班时 · 右下角"},
           "hm": "{h} 小时 {m} 分",
           "variant": {"side_peek": "久坐版", "side_peek_water": "喝水版"}, "default": "默认", "customized": "自定义",
           "edit_hint": "点气泡就能改台词"},
    "en": {"ribbon": "大水理论最严厉的母亲 · Settings", "card": "Profile", "dress": "Dress-up", "hair": "Hair",
           "skin": "Appearance", "lang": "Language", "custom": "Custom", "preview": "Preview", "today": "Today",
           "thirst": "Thirst", "sitting": "Sitting", "active": "Active", "min": "min",
           "off": "The inspector isn't running", "save": "Save", "demo": "Save & demo", "close": "Close",
           "persona_err": "Persona pack broken, using default: ",
           "scenes": {"unlock_scold": "Unlock", "side_peek": "Side peek", "overtime_care": "Overtime"},
           "where": {"unlock_scold": "After unlock · upper center", "side_peek": "Sitting long · right edge",
                     "overtime_care": "Working late · bottom right"},
           "hm": "{h} h {m} min",
           "variant": {"side_peek": "Sitting", "side_peek_water": "Water"}, "default": "Default",
           "customized": "Custom", "edit_hint": "Click the bubble to edit"},
}
SCENES = ("unlock_scold", "side_peek", "overtime_care")
ANCHOR_BOX = {"unlock_scold": (0.30, 0.10, 0.70, 0.36), "side_peek": (0.62, 0.32, 1.0, 0.62),
              "overtime_care": (0.62, 0.60, 0.98, 0.92)}


@dataclass
class UiState:
    lang: str = "zh"
    hair: str = "#4F3F3B"
    character: str = "east_asian"
    hair_presets: list = field(default_factory=list)     # [(名称, hex)]
    characters: list = field(default_factory=list)       # [(角色 id, 名称, 肤色色块)]——换肤色 = 调整妈妈形象
    tab: str = "unlock_scold"
    variant: str = "side_peek"                            # 侧边探头的哪一版：side_peek（久坐）/ side_peek_water（喝水）
    previews: dict = field(default_factory=dict)          # 台词键 → 闪现图（PIL）
    line_state: dict = field(default_factory=dict)        # 台词键 → {"has": 有自定义, "custom": 正在用自定义}
    figure: Image.Image | None = None                     # 角色卡立绘（已着色）
    display_name: str = ""
    card_name: str = ""                                   # 名牌上的称呼（妈妈 / Mom / Mama / Mummy）
    traits: list = field(default_factory=list)
    stats: dict | None = None                             # state.json 内容（没在运行时为 None）
    status: str = ""
    status_error: bool = False
    persona_error: str | None = None
    busy: bool = False


@dataclass
class Hotspot:
    action: str              # hair / skin / custom / lang / tab / save / demo / close
    arg: str | None
    box: tuple               # (x0, y0, x1, y1) 实际像素


# ── 小工具 ───────────────────────────────────────────────────────────────────
def rgba(h: str, a: int = 255) -> tuple:
    return render.hex_rgb(h) + (a,)


_FONTS: dict = {}


def font(lang: str, px: int, bold: bool = True):
    key = (lang, px, bold)
    if key not in _FONTS:
        path = FONT_ZH if lang == "zh" else FONT_EN
        f = None
        if os.path.exists(path):
            try:
                f = ImageFont.truetype(path, px)
                if lang != "zh":
                    f.set_variation_by_axes([800 if bold else 600])
            except Exception:  # noqa: BLE001
                f = None
        _FONTS[key] = f or render.get_font(px)
    return _FONTS[key]


def mixed_font(text: str, px: int, lang: str):
    """中文界面里的中文用快乐体；纯英文/数字的片段在英文界面里用 Nunito。"""
    if lang == "zh" or any(render._is_cjk(c) for c in text):
        f = font("zh", px)
        return f if render.covers(f, text) else render.get_font(px)
    return font("en", px)


class Painter:
    def __init__(self, scale: float):
        self.S = scale
        self.img = Image.new("RGBA", (self.px(W), self.px(H)), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.hot: list[Hotspot] = []

    def px(self, v: float) -> int:
        return int(round(v * self.S))

    def box(self, x0, y0, x1, y1):
        return [self.px(x0), self.px(y0), self.px(x1), self.px(y1)]

    def shadow(self, box, radius, color=(196, 120, 146, 60), blur=12, dy=5):
        x0, y0, x1, y1 = self.box(*box)
        pad = self.px(blur * 2)
        sh = Image.new("L", (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad), 0)
        ImageDraw.Draw(sh).rounded_rectangle([pad, pad, pad + x1 - x0, pad + y1 - y0], self.px(radius), fill=255)
        sh = sh.filter(ImageFilter.GaussianBlur(self.px(blur) / 2))
        layer = Image.new("RGBA", sh.size, color[:3] + (0,))
        layer.putalpha(sh.point(lambda v: v * color[3] // 255))
        self.img.alpha_composite(layer, (x0 - pad, y0 - pad + self.px(dy)))

    def card(self, box, radius=22, fill=CARD, edge=CARD_EDGE, alpha=245):
        self.shadow(box, radius)
        self.d.rounded_rectangle(self.box(*box), self.px(radius), fill=rgba(fill, alpha), outline=rgba(edge),
                                 width=max(1, self.px(2)))

    def grad_rr(self, box, radius, top, bottom, outline=None, width=0):
        x0, y0, x1, y1 = self.box(*box)
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        g = render._vgrad((w, h), top, bottom).convert("RGBA")
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], self.px(radius), fill=255)
        self.img.paste(g, (x0, y0), m)
        if outline:
            self.d.rounded_rectangle([x0, y0, x1 - 1, y1 - 1], self.px(radius), outline=rgba(outline),
                                     width=max(1, self.px(width)))

    def text(self, xy, s, px, color=INK, lang="zh", anchor="la"):
        f = mixed_font(s, self.px(px), lang)
        self.d.text((self.px(xy[0]), self.px(xy[1])), s, font=f, fill=rgba(color) if isinstance(color, str) else color,
                    anchor=anchor)
        return f.getlength(s) / self.S

    def tlen(self, s, px, lang="zh") -> float:
        return mixed_font(s, self.px(px), lang).getlength(s) / self.S

    def hotspot(self, action, arg, box):
        self.hot.append(Hotspot(action, arg, tuple(self.box(*box))))

    def sparkle(self, cx, cy, r, color=(255, 255, 255, 230)):
        cx, cy, r = self.px(cx), self.px(cy), self.px(r)
        k = r * 0.28
        self.d.polygon([(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k), (cx, cy + r),
                        (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)], fill=color)

    def heart(self, cx, cy, s, color):
        render._heart(self.d, self.px(cx), self.px(cy), self.px(s), rgba(color) if isinstance(color, str) else color)


# ── 各个部件 ─────────────────────────────────────────────────────────────────
def _background(p: Painter):
    bg = render._vgrad((p.img.width, p.img.height), BG_TOP, BG_BOTTOM).convert("RGBA")
    p.img.alpha_composite(bg)
    # 淡淡的波点
    for row in range(0, H // 34 + 2):
        for col in range(0, W // 34 + 2):
            x = col * 34 + (17 if row % 2 else 0)
            y = row * 34
            r = 2.2
            p.d.ellipse(p.box(x - r, y - r, x + r, y + r), fill=(246, 206, 218, 120))


def _ribbon(p: Painter, text: str, lang: str):
    tw = p.tlen(text, 22, lang)
    w = tw + 80
    x0, x1 = (W - w) / 2, (W + w) / 2
    y0, y1 = 12, 54
    tail = 26
    for side in (-1, 1):                       # 丝带两端的燕尾
        bx = x0 - tail + 8 if side < 0 else x1 - 8
        pts = [(bx, y0 + 10), (bx + tail, y0 + 10), (bx + tail, y1 + 6), (bx, y1 + 6)]
        notch = (bx + 10, (y0 + y1) / 2 + 8) if side < 0 else (bx + tail - 10, (y0 + y1) / 2 + 8)
        poly = [pts[0], pts[1], pts[2], pts[3]]
        poly = poly[:3] + [pts[3]] if side > 0 else poly
        if side < 0:
            poly = [pts[0], pts[1], pts[2], pts[3], notch]
        else:
            poly = [pts[0], pts[1], notch, pts[2], pts[3]]
        p.d.polygon([(p.px(a), p.px(b)) for a, b in poly], fill=rgba(ROSE_DK))
    p.shadow((x0, y0, x1, y1), 14, blur=8, dy=3)
    p.grad_rr((x0, y0, x1, y1), 14, "#F2AFC2", ROSE, outline="#FFFFFF", width=3)
    p.d.line([p.px(x0 + 14), p.px(y0 + 7), p.px(x1 - 14), p.px(y0 + 7)], fill=(255, 255, 255, 110),
             width=max(1, p.px(2)))
    p.text((W / 2, (y0 + y1) / 2 + 1), text, 22, "#FFFFFF", lang, anchor="mm")
    p.heart(x0 + 24, (y0 + y1) / 2 + 1, 13, "#FFFFFF")
    p.heart(x1 - 24, (y0 + y1) / 2 + 1, 13, "#FFFFFF")


def _section_title(p: Painter, x, y, text, lang, icon_color=ROSE):
    p.heart(x + 7, y + 11, 13, icon_color)
    return p.text((x + 20, y), text, 17, INK, lang)


def _profile_card(p: Painter, st: UiState, T: dict):
    lang = st.lang
    box = (20, 74, 340, 640)
    p.card(box)
    # 舞台
    sx0, sy0, sx1, sy1 = 34, 88, 326, 408
    p.grad_rr((sx0, sy0, sx1, sy1), 18, "#FDF1F5", "#F6D3DF")
    glow = Image.new("L", (p.px(sx1 - sx0), p.px(sy1 - sy0)), 0)
    gw, gh = glow.size
    ImageDraw.Draw(glow).ellipse([gw * 0.12, gh * 0.08, gw * 0.88, gh * 0.82], fill=200)
    glow = glow.filter(ImageFilter.GaussianBlur(p.px(26)))
    white = Image.new("RGBA", glow.size, (255, 255, 255, 0))
    white.putalpha(glow)
    p.img.alpha_composite(white, (p.px(sx0), p.px(sy0)))
    # 舞台地面的椭圆光圈
    p.d.ellipse(p.box(90, 372, 270, 398), fill=(236, 170, 192, 110))
    for (x, y, r) in ((62, 120, 9), (300, 150, 6), (286, 112, 4), (70, 300, 5), (298, 330, 8), (52, 210, 4)):
        p.sparkle(x, y, r)
    if st.figure is not None:
        fig = st.figure
        bb = fig.getchannel("A").getbbox()
        if bb:
            fig = fig.crop(bb)
        maxh, maxw = p.px(300), p.px(sx1 - sx0 - 16)
        k = min(maxh / fig.height, maxw / fig.width)
        fig = fig.resize((max(1, int(fig.width * k)), max(1, int(fig.height * k))), Image.LANCZOS)
        fx = p.px((sx0 + sx1) / 2) - fig.width // 2
        fy = p.px(sy1 - 8) - fig.height
        mask = Image.new("L", fig.size, 0)                 # 舞台下缘之外不画
        mask.paste(255, (0, 0, fig.width, min(fig.height, p.px(sy1 - 2) - fy)))

        fig.putalpha(ImageChops.multiply(fig.getchannel("A"), mask))
        p.img.alpha_composite(fig, (fx, fy))
    # 名牌
    name = st.card_name or ("妈妈" if lang == "zh" else "Mom")
    nw = p.tlen(name, 22, lang) + 56
    nx0, ny0 = (sx0 + sx1) / 2 - nw / 2, sy1 - 20
    p.shadow((nx0, ny0, nx0 + nw, ny0 + 40), 20, blur=6, dy=3)
    p.grad_rr((nx0, ny0, nx0 + nw, ny0 + 40), 20, "#F2AFC2", ROSE_DK, outline="#FFFFFF", width=3)
    p.heart(nx0 + 20, ny0 + 20, 13, "#FFFFFF")
    p.text((nx0 + 32, ny0 + 20), name, 22, "#FFFFFF", lang, anchor="lm")
    p.text(((sx0 + sx1) / 2, ny0 + 52), st.display_name, 12.5, MUTED, lang, anchor="ma")
    # 性格标签
    traits = st.traits[:4]
    if traits:
        ws = [p.tlen(t, 13.5, lang) + 22 for t in traits]
        gap = 7
        total = sum(ws) + gap * (len(ws) - 1)
        x = (sx0 + sx1) / 2 - total / 2
        y = ny0 + 76
        for i, (t, w) in enumerate(zip(traits, ws)):
            p.d.rounded_rectangle(p.box(x, y, x + w, y + 26), p.px(13), fill=rgba(PASTELS[i % 4]))
            p.text((x + w / 2, y + 13), t, 13.5, PASTEL_INK[i % 4], lang, anchor="mm")
            x += w + gap
    # 今日状态
    y = 528
    _section_title(p, 36, y - 4, T["today"], lang, MAUVE)
    y += 26
    s = st.stats
    if not s:
        p.text((52, y + 14), T["off"], 14, MUTED, lang)
        return
    th = s.get("thresholds") or {}
    rows = [
        (T["thirst"], float(s.get("water_min") or 0), float(th.get("water") or 60), WATER, "drop"),
        (T["sitting"], float(s.get("sitting_min") or 0), float(th.get("sitting_soft") or 50), SITTING, "seat"),
    ]
    for label, v, mx, color, icon in rows:
        _bar(p, 36, y, label, v, mx, color, f"{int(v)} / {int(mx)} {T['min']}", lang)
        y += 28
    eff = int(s.get("effective_today_min") or 0)
    p.text((40, y + 2), T["active"], 13.5, INK, lang)
    p.text((322, y + 2), T["hm"].format(h=eff // 60, m=eff % 60), 13.5, ACTIVE if eff < 480 else ROSE_DK, lang,
           anchor="ra")


def _bar(p: Painter, x, y, label, v, mx, color, caption, lang):
    p.text((x + 4, y + 2), label, 13.5, INK, lang)
    bx0, bx1 = x + 74, 322
    p.d.rounded_rectangle(p.box(bx0, y + 4, bx1, y + 20), p.px(8), fill=(246, 230, 235, 255),
                          outline=rgba("#EFD3DC"), width=max(1, p.px(1)))
    frac = max(0.0, min(1.0, v / mx if mx else 0))
    if frac > 0:
        fx1 = bx0 + max(16, (bx1 - bx0) * frac)
        p.grad_rr((bx0, y + 4, fx1, y + 20), 8, _lighten(color, 0.35), color if frac < 1 else ROSE_DK)
        p.d.line([p.px(bx0 + 6), p.px(y + 8), p.px(fx1 - 6), p.px(y + 8)], fill=(255, 255, 255, 120),
                 width=max(1, p.px(2)))
    p.text(((bx0 + bx1) / 2, y + 12), caption, 11, "#7A5A55", lang, anchor="mm")


def _lighten(h: str, k: float) -> str:
    r, g, b = render.hex_rgb(h)
    return "#%02X%02X%02X" % tuple(round(c + (255 - c) * k) for c in (r, g, b))


def _swatch(p: Painter, cx, cy, d, color, selected, rainbow=False):
    r = d / 2
    p.shadow((cx - r, cy - r, cx + r, cy + r), r, color=(170, 110, 130, 70), blur=5, dy=2)
    if selected:
        p.d.ellipse(p.box(cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5), outline=rgba(ROSE_DK),
                    width=max(2, p.px(3)))
    p.d.ellipse(p.box(cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 255))
    ir = r - 3
    if rainbow:
        bb = p.box(cx - ir, cy - ir, cx + ir, cy + ir)
        hues = ["#F7A1A1", "#F7C59F", "#F5E49C", "#B8E3A6", "#9FD8E8", "#A9B8F2", "#D3A9F0", "#F2A6D2"]
        for i, hc in enumerate(hues):
            p.d.pieslice(bb, i * 45 - 90, (i + 1) * 45 - 90, fill=rgba(hc))
        p.d.ellipse(p.box(cx - ir * 0.45, cy - ir * 0.45, cx + ir * 0.45, cy + ir * 0.45), fill=(255, 255, 255, 255))
        p.d.line(p.box(cx - 4, cy, cx + 4, cy), fill=rgba(ROSE_DK), width=max(1, p.px(2)))
        p.d.line(p.box(cx, cy - 4, cx, cy + 4), fill=rgba(ROSE_DK), width=max(1, p.px(2)))
    else:
        p.d.ellipse(p.box(cx - ir, cy - ir, cx + ir, cy + ir), fill=rgba(color))
        p.d.ellipse(p.box(cx - ir * 0.62, cy - ir * 0.72, cx - ir * 0.02, cy - ir * 0.25), fill=(255, 255, 255, 70))
    if selected:                                  # 右下角小对勾
        bx, by = cx + r * 0.62, cy + r * 0.62
        p.d.ellipse(p.box(bx - 8, by - 8, bx + 8, by + 8), fill=rgba(ROSE_DK), outline=(255, 255, 255, 255),
                    width=max(1, p.px(2)))
        p.d.line([(p.px(bx - 4), p.px(by)), (p.px(bx - 1), p.px(by + 3)), (p.px(bx + 4), p.px(by - 3))],
                 fill=(255, 255, 255, 255), width=max(1, p.px(2)))


def _dress_card(p: Painter, st: UiState, T: dict):
    lang = st.lang
    box = (356, 74, 1020, 284)
    p.card(box)
    _section_title(p, 374, 86, T["dress"], lang)
    # 发色：8 个预设 + 自选
    y = 134
    p.text((382, y - 10), T["hair"], 16, INK, lang)
    names = {h.upper(): n for n, h in st.hair_presets}
    p.text((382, y + 12), names.get(st.hair.upper(), T["custom"] + " " + st.hair.upper()), 11.5, MUTED, lang)
    x = 488
    for name, hx in st.hair_presets[:8]:
        _swatch(p, x, y + 4, 34, hx, hx.upper() == st.hair.upper())
        p.hotspot("hair", hx, (x - 21, y - 17, x + 21, y + 25))
        x += 50
    is_custom = st.hair.upper() not in names
    _swatch(p, x + 8, y + 4, 34, st.hair if is_custom else "#FFFFFF", is_custom, rainbow=not is_custom)
    p.hotspot("custom", None, (x - 13, y - 17, x + 29, y + 25))
    p.text((x + 8, y + 26), T["custom"], 10.5, MUTED, lang, anchor="ma")
    # 肤色 = 角色：每个都是一位完整的妈妈（自己的立绘和台词）
    y = 190
    p.text((382, y - 10), T["skin"], 16, INK, lang)
    cur = {cid: name for cid, name, _ in st.characters}.get(st.character, "")
    p.text((382, y + 12), cur, 11.5, MUTED, lang)
    x = 488
    for cid, name, sw in st.characters[:8]:
        _swatch(p, x, y + 4, 34, sw, cid == st.character)
        p.hotspot("skin", cid, (x - 21, y - 17, x + 21, y + 25))
        x += 50
    # 语言
    p.text((382, 246 - 10), T["lang"], 16, INK, lang)
    seg_x0, seg_y0 = 470, 229
    opts = (("zh", "中文"), ("en", "English"))
    widths = [p.tlen(t, 14, "zh" if c == "zh" else "en") + 36 for c, t in opts]
    total = sum(widths) + 8
    p.d.rounded_rectangle(p.box(seg_x0, seg_y0, seg_x0 + total, seg_y0 + 34), p.px(17), fill=rgba(ROSE_LT))
    x = seg_x0 + 4
    for (code, t), w in zip(opts, widths):
        on = st.lang == code
        if on:
            p.grad_rr((x, seg_y0 + 4, x + w, seg_y0 + 30), 13, "#F2AFC2", ROSE_DK)
        p.text((x + w / 2, seg_y0 + 17), t, 14, "#FFFFFF" if on else ROSE_DK, "zh" if code == "zh" else "en",
               anchor="mm")
        p.hotspot("lang", code, (x, seg_y0, x + w, seg_y0 + 34))
        x += w


def _mini_screen(p: Painter, x, y, w, scene):
    h = w * 0.6
    p.d.rounded_rectangle(p.box(x, y, x + w, y + h), p.px(4), fill=rgba("#6E5A63"))
    p.d.rounded_rectangle(p.box(x + 3, y + 3, x + w - 3, y + h - 3), p.px(2), fill=rgba("#DCEAF6"))
    p.d.rectangle(p.box(x + 3, y + h - 7, x + w - 3, y + h - 3), fill=(255, 255, 255, 200))
    p.d.rectangle(p.box(x + w / 2 - 6, y + h, x + w / 2 + 6, y + h + 5), fill=rgba("#6E5A63"))
    p.d.rounded_rectangle(p.box(x + w / 2 - 14, y + h + 4, x + w / 2 + 14, y + h + 8), p.px(2),
                          fill=rgba("#6E5A63"))
    ax0, ay0, ax1, ay1 = ANCHOR_BOX[scene]
    iw, ih = w - 6, h - 6
    p.d.rounded_rectangle(p.box(x + 3 + iw * ax0, y + 3 + ih * ay0, x + 3 + iw * ax1, y + 3 + ih * ay1),
                          p.px(2), fill=rgba(ROSE))


def preview_key(st: UiState) -> str:
    return st.variant if st.tab == "side_peek" else st.tab


def _segmented(p: Painter, x0, y0, opts, current, action, lang, size=12.5, align="left"):
    """小号胶囊切换：opts = [(值, 文字)]。align="right" 时 x0 是右边缘。"""
    widths = [p.tlen(t, size, lang) + 22 for _, t in opts]
    total = sum(widths) + 6
    if align == "right":
        x0 -= total
    h = size + 15
    p.d.rounded_rectangle(p.box(x0, y0, x0 + total, y0 + h), p.px(h / 2), fill=(255, 255, 255, 235),
                          outline=rgba(ROSE_LT), width=max(1, p.px(1.5)))
    x = x0 + 3
    for (val, t), w in zip(opts, widths):
        on = val == current
        if on:
            p.grad_rr((x, y0 + 3, x + w, y0 + h - 3), (h - 6) / 2, "#F2AFC2", ROSE_DK)
        p.text((x + w / 2, y0 + h / 2), t, size, "#FFFFFF" if on else ROSE_DK, lang, anchor="mm")
        p.hotspot(action, val, (x, y0, x + w, y0 + h))
        x += w


def _pencil(p: Painter, cx, cy, r):
    p.d.ellipse(p.box(cx - r, cy - r, cx + r, cy + r), fill=rgba(ROSE_DK), outline=(255, 255, 255, 255),
                width=max(1, p.px(2)))
    k = r * 0.5
    p.d.line([(p.px(cx - k), p.px(cy + k)), (p.px(cx + k), p.px(cy - k))], fill=(255, 255, 255, 255),
             width=max(2, p.px(r * 0.38)))
    p.d.polygon([(p.px(cx - k - r * 0.18), p.px(cy + k + r * 0.18)), (p.px(cx - k + r * 0.12), p.px(cy + k + r * 0.02)),
                 (p.px(cx - k - r * 0.02), p.px(cy + k - r * 0.12))], fill=(255, 255, 255, 255))


def _preview_card(p: Painter, st: UiState, T: dict):
    lang = st.lang
    box = (356, 296, 1020, 578)
    p.card(box)
    _section_title(p, 374, 308, T["preview"], lang)
    # 场景标签（竖排）
    y = 340
    for sc in SCENES:
        on = st.tab == sc
        bx = (372, y, 500, y + 40)
        if on:
            p.shadow(bx, 20, blur=6, dy=3)
            p.grad_rr(bx, 20, "#F2AFC2", ROSE_DK, outline="#FFFFFF", width=2)
        else:
            p.d.rounded_rectangle(p.box(*bx), p.px(20), fill=(255, 255, 255, 255), outline=rgba(ROSE_LT),
                                  width=max(1, p.px(2)))
        p.text((436, y + 20), T["scenes"][sc], 15, "#FFFFFF" if on else ROSE_DK, lang, anchor="mm")
        p.hotspot("tab", sc, bx)
        y += 48
    _mini_screen(p, 396, 492, 80, st.tab)
    # 预览区
    ax0, ay0, ax1, ay1 = 514, 310, 1004, 564
    p.grad_rr((ax0, ay0, ax1, ay1), 16, "#E3EEF8", "#F3F0F8")
    for (x, yy, r) in ((980, 542, 6), (530, 545, 4)):
        p.sparkle(x, yy, r)
    p.text(((ax0 + ax1) / 2, ay1 - 14), T["where"][st.tab], 11.5, "#8C8FA8", lang, anchor="mm")
    key = preview_key(st)
    im = st.previews.get(key)
    if im is not None:
        top, bottom = 44, 26
        aw, ah = p.px(ax1 - ax0 - 24), p.px(ay1 - ay0 - top - bottom)
        k = min(aw / im.width, ah / im.height, 1.0 * p.S)
        im2 = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
        ox = p.px((ax0 + ax1) / 2) - im2.width // 2
        oy = p.px(ay0 + top) + (ah - im2.height) // 2
        p.img.alpha_composite(im2, (ox, oy))
        bb = im.info.get("bubble_box")
        if bb:                                          # 点气泡改台词：热区 + 右上角一支小铅笔
            x0, y0, x1, y1 = (ox + bb[0] * k, oy + bb[1] * k, ox + bb[2] * k, oy + bb[3] * k)
            p.hot.append(Hotspot("edit", key, (int(x0), int(y0), int(x1), int(y1))))
            _pencil(p, x1 / p.S - 2, y1 / p.S - 2, 9)
    elif st.busy:
        p.text(((ax0 + ax1) / 2, (ay0 + ay1) / 2), "…", 28, MUTED, lang, anchor="mm")
    # 左上：侧边探头的两个版本
    if st.tab == "side_peek":
        _segmented(p, ax0 + 10, ay0 + 9, [(k2, T["variant"][k2]) for k2 in ("side_peek", "side_peek_water")],
                   st.variant, "variant", lang)
    # 右上：默认 / 自定义（有自定义内容时才出现；没有就给一句提示）
    ls = st.line_state.get(key) or {}
    if ls.get("has"):
        _segmented(p, ax1 - 10, ay0 + 9, [("default", T["default"]), ("custom", T["customized"])],
                   "custom" if ls.get("custom") else "default", "line_mode", lang, align="right")
    else:
        hint = T["edit_hint"]
        w = p.tlen(hint, 11.5, lang) + 34
        x1 = ax1 - 10
        p.d.rounded_rectangle(p.box(x1 - w, ay0 + 10, x1, ay0 + 36), p.px(13), fill=(255, 255, 255, 200))
        _pencil(p, x1 - w + 13, ay0 + 23, 8)
        p.text((x1 - w + 26, ay0 + 23), hint, 11.5, ROSE_DK, lang, anchor="lm")


def _button(p: Painter, box, text, lang, primary):
    if primary:
        p.shadow(box, 22, color=(204, 110, 140, 90), blur=8, dy=4)
        p.grad_rr(box, 22, "#F4B3C6", ROSE_DK, outline="#FFFFFF", width=3)
        x0, y0, x1, y1 = box
        p.d.rounded_rectangle(p.box(x0 + 14, y0 + 5, x1 - 14, y0 + 12), p.px(4), fill=(255, 255, 255, 60))
        p.text(((x0 + x1) / 2, (y0 + y1) / 2 + 1), text, 17, "#FFFFFF", lang, anchor="mm")
    else:
        p.shadow(box, 22, blur=6, dy=3)
        p.d.rounded_rectangle(p.box(*box), p.px(22), fill=(255, 255, 255, 255), outline=rgba(ROSE),
                              width=max(2, p.px(2)))
        x0, y0, x1, y1 = box
        p.text(((x0 + x1) / 2, (y0 + y1) / 2 + 1), text, 16, ROSE_DK, lang, anchor="mm")


def _footer(p: Painter, st: UiState, T: dict):
    lang = st.lang
    y0, y1 = 592, 636
    x = 1020
    for action, primary in (("save", True), ("demo", False), ("close", False)):
        label = T[action]
        w = p.tlen(label, 17, lang) + (64 if primary else 44)
        if action == "close":
            w = p.tlen(label, 16, lang) + 36
        box = (x - w, y0, x, y1)
        _button(p, box, label, lang, primary)
        p.hotspot(action, None, box)
        x -= w + 12
    if st.status:
        color = "#D2475F" if st.status_error else MAUVE
        p.text((370, (y0 + y1) / 2), st.status, 13.5, color, lang, anchor="lm")


def render_ui(st: UiState, scale: float = 1.0) -> tuple[Image.Image, list[Hotspot]]:
    T = TEXT.get(st.lang, TEXT["zh"])
    p = Painter(scale)
    _background(p)
    _ribbon(p, T["ribbon"], st.lang)
    _profile_card(p, st, T)
    _dress_card(p, st, T)
    _preview_card(p, st, T)
    _footer(p, st, T)
    if st.persona_error:
        msg = T["persona_err"] + st.persona_error
        p.d.rounded_rectangle(p.box(356, 60, 1020, 72), p.px(6), fill=rgba("#FCE1E6"))
        p.text((364, 66), msg[:90], 10, "#D2475F", st.lang, anchor="lm")
    return p.img.convert("RGB"), p.hot


def hit(hotspots: list[Hotspot], x: float, y: float) -> Hotspot | None:
    for h in hotspots:
        x0, y0, x1, y1 = h.box
        if x0 <= x <= x1 and y0 <= y <= y1:
            return h
    return None
