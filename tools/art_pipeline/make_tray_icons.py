# -*- coding: utf-8 -*-
"""生成托盘图标 assets/tray/tea_0.ico … tea_4.ico（开发时用，运行督察员不需要）。

    python tools/art_pipeline/make_tray_icons.py

养成系画风的小水杯：奶油色杯身、豆沙粉粗描边、杯身一颗小爱心、浅蓝色的水。
0 = 满杯（刚喝过水）… 4 = 见底（饮水账超了，右上角冒一个红色感叹号）。
"""

from __future__ import annotations

import math
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRAY_DIR = os.path.join(ROOT, "assets", "tray")
SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64)]

CUP = (255, 249, 242, 255)
EDGE = (196, 104, 136, 255)
WATER = (120, 196, 238, 255)
WATER_DK = (88, 170, 222, 255)
HEART = (240, 120, 150, 255)
ALERT = (232, 72, 88, 255)


def cup_icon(level: int) -> Image.Image:
    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    body = [36, 58, 186, 226]                         # 杯身（圆角矩形，下宽上略窄的效果用圆角做）
    shape = Image.new("L", (S, S), 0)
    sd = ImageDraw.Draw(shape)
    sd.rounded_rectangle(body, 44, fill=255)
    # 把手
    handle = Image.new("L", (S, S), 0)
    hd = ImageDraw.Draw(handle)
    hd.ellipse([150, 96, 238, 190], fill=255)
    hd.ellipse([178, 122, 212, 164], fill=0)
    outline_w = 18
    full = ImageChops.lighter(shape, handle)
    # 白色外描边（深色任务栏上也看得清）
    halo = full.filter(ImageFilter.MaxFilter(13)).filter(ImageFilter.GaussianBlur(1.5))
    img.paste((255, 255, 255, 255), (0, 0), halo)
    img.paste(EDGE, (0, 0), full)
    inner = shape.filter(ImageFilter.MinFilter(outline_w * 2 + 1))
    img.paste(CUP, (0, 0), inner)
    # 水
    frac = [0.86, 0.66, 0.46, 0.26, 0.0][max(0, min(4, level))]
    if frac > 0:
        x0, y0, x1, y1 = inner.getbbox()
        top = y1 - (y1 - y0) * frac
        water = Image.new("L", (S, S), 0)
        wd = ImageDraw.Draw(water)
        pts = [(x, top + 6 * math.sin((x - x0) / (x1 - x0) * 2 * math.pi)) for x in range(x0, x1 + 1, 4)]
        wd.polygon(pts + [(x1, y1), (x0, y1)], fill=255)
        water = ImageChops.multiply(water, inner)
        img.paste(WATER, (0, 0), water)
        deep = Image.new("L", (S, S), 0)
        ImageDraw.Draw(deep).rectangle([x0, y1 - (y1 - y0) * frac * 0.35, x1, y1], fill=255)
        img.paste(WATER_DK, (0, 0), ImageChops.multiply(ImageChops.multiply(deep, water), Image.new("L", (S, S), 140)))
        # 水面高光
        ImageDraw.Draw(img).line([(x0 + 22, top + 14), (x0 + 60, top + 10)], fill=(255, 255, 255, 220), width=10)
    # 杯身高光 + 爱心
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([64, 84, 78, 150], 7, fill=(255, 255, 255, 200))
    hx, hy, hs = 112, 118 if level < 2 else 112, 46
    r = hs * 0.27
    heart = Image.new("L", (S, S), 0)
    hdd = ImageDraw.Draw(heart)
    hdd.ellipse([hx - hs * 0.5, hy - hs * 0.36, hx - hs * 0.5 + 2 * r, hy - hs * 0.36 + 2 * r], fill=255)
    hdd.ellipse([hx + hs * 0.5 - 2 * r, hy - hs * 0.36, hx + hs * 0.5, hy - hs * 0.36 + 2 * r], fill=255)
    hdd.polygon([(hx - hs * 0.49, hy - hs * 0.12), (hx + hs * 0.49, hy - hs * 0.12), (hx, hy + hs * 0.45)], fill=255)
    img.paste((255, 255, 255, 255), (0, 0), heart.filter(ImageFilter.MaxFilter(9)))
    img.paste(HEART, (0, 0), heart)
    if level >= 4:                                     # 见底：红色感叹号气泡
        d.ellipse([168, 6, 250, 88], fill=(255, 255, 255, 255))
        d.ellipse([176, 14, 242, 80], fill=ALERT)
        d.rounded_rectangle([202, 24, 216, 58], 7, fill=(255, 255, 255, 255))
        d.ellipse([202, 62, 216, 74], fill=(255, 255, 255, 255))
    return img


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    os.makedirs(TRAY_DIR, exist_ok=True)
    for lv in range(5):
        path = os.path.join(TRAY_DIR, f"tea_{lv}.ico")
        cup_icon(lv).save(path, sizes=SIZES)
        print("已生成", path)


if __name__ == "__main__":
    main()
