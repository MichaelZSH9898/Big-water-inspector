# -*- coding: utf-8 -*-
"""从角色设定图（character sheet）生成角色包图层。只在开发时用，运行督察员不需要它。

    pip install "rembg[cpu]" opencv-contrib-python-headless pillow numpy
    python tools/art_pipeline/build_from_sheet.py east_asian=华裔.png white=白人.png black=黑人.png south_asian=印度裔.png
    （加 --cache 目录 可以缓存抠图结果，调参时不用每次重新超分、抠图）

四张设定图版式相同（1448×1086 左右）：左边张开双臂的大立绘，右下两排表情小格。每个角色取三个姿势：
  A scold = “训斥教育”（竖手指）  B peek = “烦躁不满”（镜像成朝左看）  C care = 张开双臂的大立绘（取到大腿）

流程（每个姿势）：
  1. 裁出这个姿势（小格子先用 EDSR ×4 超分，模型首次运行自动下载）；小格子把头顶切平了，按椭圆拱形补圆
  2. 抠图：rembg（isnet）与“背景色差”两种蒙版取并集；被主体包围的小洞、轮廓上的窄缺口补实
  3. 去背景色污染（边缘半透明像素按已知背景色反解出前景色）
  4. 分层（换肤色 = 换角色，所以皮肤不着色，只有头发要能换色）：
     · 20_body：头发以外的一切，原样（脸、五官、腮红、眉毛、耳环、衣服都保留原画）
     · 30_hair：头发，存成灰度明暗图，运行时乘以所选发色
     · 90_line：养成系游戏常见的白色描边（贴纸感）
     两层按“叠起来与原图一致”的公式算 alpha
  5. 写回角色包：persona.json 里每个角色的 tint_adjust（发色通道倍数，使第一个发色预设 = 原画）和肤色色块
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PERSONA_DIR = os.path.join(ROOT, "persona", "default_mom")
MODEL_DIR = os.path.join(os.path.expanduser("~"), ".cache", "water-inspector")
EDSR_URL = "https://raw.githubusercontent.com/Saafke/EDSR_Tensorflow/master/models/EDSR_x4.pb"

HAIR_NORM = 165.0       # 头发中位亮度归一化到这里（留出高光余量）

# 设定图里三个姿势的位置（按 1448×1086 的像素坐标；dy 是各张图表情格子的上下偏移）
POSES = {
    "scold": {  # 场景 A：训斥教育（竖手指）
        "box": (1087, 756, 1252, 874), "sr": True, "tile_bg": True, "dome_top": True,
        "hl_y": 0.65, "hair_max_y": 0.92,
    },
    "peek": {   # 场景 B：烦躁不满（斜眼）。镜像成朝左看，后脑勺被屏幕右缘挡住一截
        "box": (1257, 756, 1428, 874), "sr": True, "tile_bg": True, "dome_top": True, "flip": True,
        "hl_y": 0.65, "hair_max_y": 0.97, "cut_right": 0.86,
    },
    "care": {   # 场景 C：张开双臂的大立绘，取到大腿
        "box": (0, 0, 520, 1000), "sr": False, "tile_bg": False, "fixed_box": True,
        "hl_y": 0.08, "hair_max_y": 0.195, "crop_bottom": 0.66,
    },
}

# 每个角色：输出到哪、表情格的偏移、个别参数
CHARACTERS = {
    "east_asian": {"dir": "", "dy": 0},
    "white": {"dir": "characters/white", "dy": -2},
    "black": {"dir": "characters/black", "dy": -7, "skin_L_min": 10,
              "pose": {"scold": {"hair_max_y": 0.72}, "peek": {"hair_max_y": 0.75}, "care": {"hair_max_y": 0.17}}},
    "south_asian": {"dir": "characters/south_asian", "dy": -1, "skin_L_min": 30},
}


def pose_spec(char: str, pose: str) -> dict:
    c = CHARACTERS[char]
    spec = dict(POSES[pose])
    spec.update((c.get("pose") or {}).get(pose, {}))
    if not spec.get("fixed_box"):
        x0, y0, x1, y1 = spec["box"]
        spec["box"] = (x0, y0 + c.get("dy", 0), x1, y1 + c.get("dy", 0))
    spec["skin_L_min"] = c.get("skin_L_min", 45)
    return spec


def edsr():
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, "EDSR_x4.pb")
    if not os.path.exists(path):
        print("下载 EDSR 超分模型……")
        urllib.request.urlretrieve(EDSR_URL, path)
    sr = cv2.dnn_superres.DnnSuperResImpl_create()
    sr.readModel(path)
    sr.setModel("edsr", 4)
    return sr


def border_bg_colors(rgb: np.ndarray) -> np.ndarray:
    """从图像四周估计背景色（取边缘像素聚成 2 类）。只看上边和左右两边的上半截——
    人物在下边被裁断（衣服、手贴着下边），把那里也算进来，深色的手就会被当成“背景色”而抠掉。"""
    h = rgb.shape[0]
    edge = np.concatenate([rgb[:6].reshape(-1, 3), rgb[:h // 2, :6].reshape(-1, 3),
                           rgb[:h // 2, -6:].reshape(-1, 3)]).astype(np.float32)
    _, _, centers = cv2.kmeans(edge, 2, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0),
                               3, cv2.KMEANS_PP_CENTERS)
    return centers


def matte(rgb: np.ndarray, session, use_color: bool) -> np.ndarray:
    from rembg import remove
    a = np.asarray(remove(Image.fromarray(rgb), session=session)).astype(np.float32)[..., 3] / 255.0
    if not use_color:
        return a
    bgs = border_bg_colors(rgb)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    blab = cv2.cvtColor(bgs.reshape(1, -1, 3).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)[0]
    d = np.min(np.stack([np.linalg.norm(lab - b, axis=2) for b in blab]), axis=0)
    ac = np.clip((d - 8.0) / 22.0, 0, 1)
    # 只保留与主体相连的色差区域（救回手指、发梢），去掉孤立噪点
    seed = (a > 0.5).astype(np.uint8)
    cand = (ac > 0.5).astype(np.uint8) | seed
    n, lbl = cv2.connectedComponents(cand)
    keep = np.isin(lbl, np.unique(lbl[seed > 0]))
    keep &= lbl > 0
    ac = ac * keep
    return np.maximum(a, ac)


def decontaminate(rgb: np.ndarray, a: np.ndarray, bg: np.ndarray) -> np.ndarray:
    f = rgb.astype(np.float32)
    aa = a[..., None]
    out = np.where(aa > 0.05, (f - (1 - aa) * bg) / np.maximum(aa, 0.05), f)
    return np.clip(out, 0, 255)


def _components(mask: np.ndarray, min_frac: float) -> np.ndarray:
    h, w = mask.shape
    n, lbl, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    big = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > min_frac * h * w]
    return np.isin(lbl, big)


def segment(rgb: np.ndarray, a: np.ndarray, spec: dict):
    """返回 (皮肤权重, 头发权重, 腮红强度)。规则（Lab 颜色 + 位置）：
    · 皮肤种子：橙调（b > 0.7a），排除粉色碎花（a≫b）与米白（彩度低）；取大连通块，填满轮廓 = 脸/手
    · 轮廓内：深色低彩度（眉、睫毛、瞳孔）、红粉色（嘴）、亮白（眼白、牙）是五官，其余都归皮肤
      （耳朵里的阴影、法令纹也跟着换肤色，避免换色后出现原色补丁）
    · 眉毛：脸上半部、下面有眼睛的深色块 → 不算头发（换发色时眉毛保持原画）
    · 头发：轮廓外、低彩度灰棕色；头顶区（hl_y 以上）连半透明的高光也算，往下只算较暗的部分
      （避免把米白衬衫、豆沙色针织衫算进去）"""
    lab = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    L, A, B = lab[..., 0] * 100 / 255, lab[..., 1] - 128, lab[..., 2] - 128
    chroma = np.hypot(A, B)
    h, w = a.shape
    fg = a > 0.35
    anyfg = a > 0.04
    rows = np.arange(h)[:, None].repeat(w, 1)
    seed = _components(fg & (A > 9) & (B > 11) & (B > 0.7 * A) & (L > spec.get("skin_L_min", 45)) & (A < 40), 0.003)
    # 先做一次闭运算再填轮廓：眉毛、靠近脸边的眼睛、深色皮肤上的阴影都会在皮肤种子里留下“缺口”，不补上就会被当成头发
    k = max(9, int(min(h, w) * 0.07)) | 1
    closed = cv2.morphologyEx(seed.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    face = np.zeros((h, w), np.uint8)
    cv2.drawContours(face, cnts, -1, 1, thickness=-1)
    # 脸大体是凸的：凸包里、离皮肤不远的地方也算脸（脸边上的眼睛、阴影里的脸颊），离皮肤远的凸包部分仍归头发
    if cnts:
        hull = np.zeros((h, w), np.uint8)
        cv2.drawContours(hull, [cv2.convexHull(max(cnts, key=cv2.contourArea))], -1, 1, thickness=-1)
        r = max(5, int(min(h, w) * 0.035))
        near = cv2.dilate(seed.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1,) * 2))
        face |= hull & near
    face = (face > 0) & anyfg
    l_med = float(np.median(L[seed]))
    a_med = float(np.median(A[seed]))
    dark = (L < l_med - 22) & (chroma < 22)
    mouth = (A > 1.3 * B + 6) & (A > 16)
    white = (L > 84) & (chroma < 13)
    feature = face & (dark | mouth | white | (L < 25))
    skin = face & ~feature
    # 眉毛：脸上半部、正下方不远处还有另一个深色块（眼睛）、上方没有深色块的横向深色块
    brow = np.zeros_like(face)
    fy0, fy1 = np.where(seed.any(1))[0][[0, -1]] if seed.any() else (0, h)
    fh = fy1 - fy0
    n, lbl, st, cen = cv2.connectedComponentsWithStats((face & dark).astype(np.uint8))
    comps = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > 0.0004 * h * w]

    def overlap_x(i, j):
        a0, a1 = st[i, 0], st[i, 0] + st[i, 2]
        b0, b1 = st[j, 0], st[j, 0] + st[j, 2]
        return max(0, min(a1, b1) - max(a0, b0)) > 0.3 * min(st[i, 2], st[j, 2])

    for i in comps:
        top_i, bot_i = st[i, 1], st[i, 1] + st[i, 3]
        if cen[i][1] > fy0 + 0.5 * fh or st[i, 2] < 0.8 * st[i, 3]:
            continue
        below = [j for j in comps if j != i and overlap_x(i, j) and st[j, 1] > top_i + 0.5 * st[i, 3]
                 and st[j, 1] - bot_i < 0.15 * fh]
        above = [j for j in comps if j != i and overlap_x(i, j) and st[j, 1] + st[j, 3] < bot_i - 0.5 * st[i, 3]
                 and top_i - (st[j, 1] + st[j, 3]) < 0.15 * fh]
        if below and not above:
            brow |= lbl == i
    brow = (cv2.dilate(brow.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & face & (L < l_med - 8)
    feature &= ~brow
    # 贴着脸部轮廓边缘的“五官”其实是耳朵里、下巴下的阴影 → 皮肤
    edge = face & ~(cv2.erode(face.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)
    n, lbl = cv2.connectedComponents(feature.astype(np.uint8))
    touching = np.unique(lbl[edge & feature])
    rim = np.isin(lbl, touching[touching > 0]) & ~white & ~brow
    feature &= ~rim
    skin = (skin | rim) & ~brow
    # 轮廓外、和脸相连的橙褐色阴影（耳朵里、下巴下）也是皮肤
    shade = anyfg & ~face & (A > 12) & (B > 12) & (B > 0.75 * A) & (L < 55) & (rows < spec["hair_max_y"] * h)
    n, lbl = cv2.connectedComponents(shade.astype(np.uint8))
    touch = np.unique(lbl[(cv2.dilate(face.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & shade])
    shade = np.isin(lbl, touch[touch > 0])
    skin |= shade
    hairish = (chroma < 20) & (A < 13) & ((A - B) < 8)
    top = rows < spec["hl_y"] * h
    low = (rows < spec["hair_max_y"] * h) & (L < 72) & (A < 10) & ((A - B) < 5) & fg
    hair = ~face & ~shade & hairish & ((top & anyfg) | low)
    hair = _components(hair, 0.002)
    hair = (cv2.morphologyEx(hair.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)) > 0) & anyfg & ~face
    hair |= top & anyfg & ~face & ~shade                # 头顶区里脸以外的都是头发（含半透明的发梢）
    brow_d = cv2.dilate(brow.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    hair &= ~shade & ~brow_d                            # 眉毛保持原画颜色（伸出脸部轮廓的那半截也是）
    # 皮肤/头发交界带：未归类的像素按最近类别分配
    band = anyfg & ~skin & ~hair & ~feature & (rows < spec["hair_max_y"] * h)
    ds = cv2.distanceTransform((~skin).astype(np.uint8), cv2.DIST_L2, 3)
    dh = cv2.distanceTransform((~hair).astype(np.uint8), cv2.DIST_L2, 3)
    near = band & (np.minimum(ds, dh) <= 3)
    skin = skin | (near & (ds <= dh))
    hair = hair | (near & (dh < ds))
    ws = cv2.GaussianBlur(skin.astype(np.float32), (0, 0), 0.6)
    wh = cv2.GaussianBlur(hair.astype(np.float32), (0, 0), 0.6)
    tot = ws + wh
    over = tot > 1
    ws[over] /= tot[over]
    wh[over] /= tot[over]
    blush = np.clip((A - a_med - 2.0) / 16.0, 0, 0.45) * (skin & ~feature)
    blush = cv2.GaussianBlur(blush.astype(np.float32), (0, 0), 2.0)
    return ws, wh, blush


def luminance(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def crop_and_matte(spec: dict, sheet: Image.Image, sr, session):
    x0, y0, x1, y1 = spec["box"]
    rgb = np.asarray(sheet.crop((x0, y0, x1, y1)).convert("RGB"))
    if spec["sr"]:
        rgb = cv2.cvtColor(sr.upsample(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)), cv2.COLOR_BGR2RGB)
    return rgb, matte(rgb, session, spec["tile_bg"])


def dome_top(rgb: np.ndarray, a: np.ndarray):
    """设定图的小格子把头顶切平了：去掉格子上方的页面，再把头顶一截按椭圆拱形往上“拉”出来，补成圆润的头顶。"""
    h, w = a.shape
    top = 0
    while top < h // 4 and a[top, : int(w * 0.05)].mean() > 0.5:   # 格子上沿以外的页面也被当成了前景
        top += 1
    rgb, a = rgb[top + 4:], a[top + 4:].copy()                       # 再多去掉几行：格子自己的边框线
    h = a.shape[0]
    row = a[1] > 0.5
    if row.sum() < 0.1 * w:
        return rgb, a
    xs = np.where(row)[0]
    x0, x1 = xs[0], xs[-1]
    M = int(h * 0.03)                                      # 头顶上方留白，给白色描边留位置
    P, Bh = int(h * 0.05) + M, int(h * 0.16)
    xc, r = (x0 + x1) / 2, (x1 - x0) / 2 + 2
    X = np.arange(w, dtype=np.float32)
    d = np.where((X >= x0) & (X <= x1), (P - M) * np.sqrt(np.clip(1 - ((X - xc) / r) ** 2, 0, 1)), 0)
    s = (P - d)[None, :]                                   # 每列新的头顶位置
    Y = np.arange(h + P, dtype=np.float32)[:, None]
    in_cap = (Y < P + Bh) & (d[None, :] > 0)
    a = np.where(np.arange(h)[:, None] < 3, np.minimum(a, a[3:4]), a)    # 最上面几行常有残边，取下一行
    map_y = np.where(in_cap, (Y - s) * Bh / np.maximum(P + Bh - s, 1), Y - P).astype(np.float32)
    map_x = np.repeat(X[None, :], h + P, 0).astype(np.float32)
    rgb2 = cv2.remap(rgb, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    a2 = cv2.remap(a.astype(np.float32), map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a2 = np.where(in_cap | (Y < P), a2 * np.clip(Y - s + 0.5, 0, 1), a2)
    return rgb2, a2


def build(name: str, spec: dict, rgb: np.ndarray, a: np.ndarray, outdir: str):
    a = a.copy()
    if spec.get("dome_top"):
        rgb, a = dome_top(rgb, a)
    if spec.get("flip"):                      # 探头：镜像成脸朝左（朝屏幕里面），后脑勺那边被屏幕右缘挡住
        rgb, a = np.ascontiguousarray(rgb[:, ::-1]), np.ascontiguousarray(a[:, ::-1])
    bg = border_bg_colors(rgb)
    bgc = bg[np.argmin(np.linalg.norm(bg - np.median(rgb[:8].reshape(-1, 3), 0), axis=1))]
    col = decontaminate(rgb, a, bgc)
    h, w = a.shape
    if spec["tile_bg"]:                       # 去掉格子底边（以及格子外的页面）
        bottom = h
        for y in range(h - 1, h // 2, -1):
            if a[y, int(w * 0.3):int(w * 0.7)].mean() > 0.8:
                bottom = y - 2
                break
        a[bottom:] = 0
    # 补洞：发丝高光和背景颜色接近，抠图时会被当成半透明的“洞”；被主体包围的小洞一律补成不透明、用原色
    solid = (a > 0.5).astype(np.uint8)
    n, lbl = cv2.connectedComponents(1 - solid)
    outside = np.unique(np.concatenate([lbl[0], lbl[-1], lbl[:, 0], lbl[:, -1]]))
    holes = np.zeros((h, w), bool)
    for i in range(1, n):
        if i in outside:
            continue
        comp = lbl == i
        if comp.sum() < 0.006 * h * w:
            holes |= comp
    # 轮廓上的窄缺口（发丝之间半透明的高光）同样补实，免得换发色后露出一块块背景色
    k = max(5, int(round(min(h, w) * 0.02)) | 1)
    closed = cv2.morphologyEx(solid, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    holes |= closed & (solid == 0) & (a > 0.08)
    if holes.any():
        hm = cv2.GaussianBlur(cv2.dilate(holes.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32), (0, 0), 1.0)
        col = col * (1 - hm[..., None]) + rgb.astype(np.float32) * hm[..., None]
        a = np.maximum(a, hm)
    ws, wh, _ = segment(col, a, spec)
    # ── 分层：20_body（原样）< 30_hair（灰度，运行时着色）。叠起来 = 原图 ──────────
    lum = luminance(col)
    skin_px = (ws > 0.9) & (a > 0.9)
    hair_px = (wh > 0.9) & (a > 0.9)
    med_h = float(np.median(lum[hair_px]))
    skin_rgb = np.median(col[skin_px], axis=0)
    hair_rgb = np.median(col[hair_px], axis=0)
    # 中位亮度归一化到 N；N 取“最亮 0.5% 的像素也不超过 250”的上限，亮部细节不被截掉
    n_h = min(HAIR_NORM, 250.0 / max(1.0, float(np.percentile(lum[hair_px] / med_h, 99.5))))
    gray_h = np.clip(lum / med_h * n_h, 0, 255)
    a_hair = np.clip(a * wh, 0, 1)
    a_body = np.clip(a * (1 - wh) / np.maximum(1 - a_hair, 1e-4), 0, 1)
    layers = {
        "20_body.png": np.dstack([col, a_body * 255]),
        "30_hair.png": np.dstack([gray_h] * 3 + [a_hair * 255]),
    }
    # ── 裁切（屏幕边缘挡住的部分、大立绘取到大腿）──────────────────────
    cut_r = int(w * spec.get("cut_right", 1.0))
    cut_b = int(h * spec.get("crop_bottom", 1.0))
    total_a = a.copy()
    total_a[:, cut_r:] = 0
    total_a[cut_b:] = 0
    # 白色描边：先把裁切边“延伸出去”再膨胀，这样裁切边（底边、被屏幕挡住的右边）上不会出现白线
    pad = 40
    ext = np.pad(total_a[:cut_b, :cut_r], ((pad, pad), (pad, pad)), mode="constant")
    ext[pad + cut_b:, :] = ext[pad + cut_b - 1:pad + cut_b, :]
    if spec.get("cut_right"):
        ext[:, pad + cut_r:] = ext[:, pad + cut_r - 1:pad + cut_r]
    rad = max(3, int(round(min(h, w) * 0.012)))
    ring = cv2.dilate((ext > 0.5).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rad + 1,) * 2))
    ring = cv2.GaussianBlur(ring.astype(np.float32), (0, 0), 0.8)
    ring = np.clip(ring - ext, 0, 1)[pad:pad + cut_b, pad:pad + cut_r]
    os.makedirs(outdir, exist_ok=True)
    for fn in os.listdir(outdir):                 # 旧版的 10_skin / 20_clothes / 40_face 等不再使用
        if fn.endswith(".png") and fn not in layers and fn != "90_line.png":
            os.remove(os.path.join(outdir, fn))
    for fn, arr in layers.items():
        arr = arr[:cut_b, :cut_r].copy()
        Image.fromarray(arr.astype(np.uint8), "RGBA").save(os.path.join(outdir, fn), optimize=True)
    line = np.dstack([np.full_like(ring, 255)] * 3 + [ring * 255])
    Image.fromarray(line.astype(np.uint8), "RGBA").save(os.path.join(outdir, "90_line.png"), optimize=True)
    # 灰度层 × c / 255 = 原图颜色（c 可以超过 255，所以存成倍数而不是颜色）
    return {"size": (cut_r, cut_b),
            "hair_c": [round(float(v), 1) for v in hair_rgb * 255 / n_h],
            "skin_seen": [int(v) for v in skin_rgb], "hair_seen": [int(v) for v in hair_rgb]}


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="从角色设定图生成角色包图层")
    ap.add_argument("sheets", nargs="+", help="角色=设定图路径，如 east_asian=a.png（角色见 CHARACTERS）")
    ap.add_argument("--cache", help="缓存抠图结果的文件夹（调参时省时间）")
    ap.add_argument("--only", help="只生成这些姿势，逗号分隔")
    a = ap.parse_args(argv)
    session = sr = None
    results = {}
    for item in a.sheets:
        char, path = item.split("=", 1)
        if char not in CHARACTERS:
            raise SystemExit(f"未知角色 {char}，可选：{', '.join(CHARACTERS)}")
        sheet = Image.open(path).convert("RGB")
        results[char] = {}
        for pose in POSES:
            if a.only and pose not in a.only.split(","):
                continue
            spec = pose_spec(char, pose)
            cache = os.path.join(a.cache, f"{char}-{pose}.npz") if a.cache else None
            if cache and os.path.exists(cache):
                z = np.load(cache)
                rgb, alpha = z["rgb"], z["a"]
            else:
                if session is None:
                    from rembg import new_session
                    session, sr = new_session("isnet-general-use"), edsr()
                rgb, alpha = crop_and_matte(spec, sheet, sr, session)
                if cache:
                    os.makedirs(a.cache, exist_ok=True)
                    np.savez_compressed(cache, rgb=rgb, a=alpha)
            out = os.path.join(PERSONA_DIR, CHARACTERS[char]["dir"], "poses", pose)
            results[char][pose] = build(pose, spec, rgb, alpha, out)
            print(char, pose, results[char][pose])
    write_back(results)


def write_back(results: dict, pdir: str | None = None):
    """写回角色包 persona.json：
    · 每个角色每个姿势的 tint_adjust（发色通道倍数）：实际着色 = 所选发色 × 倍数，
      所以选第一个发色预设时和原画一致；选别的发色时，几个姿势之间的光线、色调差异也保留。
    · 每个角色的肤色色块（设置界面里显示）= 大立绘脸部皮肤的中位色。"""
    pdir = pdir or PERSONA_DIR
    with open(os.path.join(pdir, "colors.json"), encoding="utf-8") as fh:
        base_hex = json.load(fh)["hair"][0]["hex"]
    base = [int(base_hex[i:i + 2], 16) for i in (1, 3, 5)]
    pj = os.path.join(pdir, "persona.json")
    with open(pj, encoding="utf-8") as fh:
        meta = json.load(fh)
    for char, poses in results.items():
        adj = {pose: {"hair": [round(c / max(1, b), 3) for c, b in zip(v["hair_c"], base)]} for pose, v in poses.items()}
        entry = meta.setdefault("characters", {}).setdefault(char, {})
        entry.setdefault("tint_adjust", {}).update(adj)
        if "care" in poses:                       # 只在没有手工指定时才写（色块要让四个角色一眼能分开）
            entry.setdefault("skin", "#%02X%02X%02X" % tuple(poses["care"]["skin_seen"]))
        print(char, "肤色", entry.get("skin"), "发色倍数", json.dumps(adj))
    with open(pj, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


if __name__ == "__main__":
    main(sys.argv[1:])
