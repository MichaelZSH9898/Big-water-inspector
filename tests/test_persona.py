# -*- coding: utf-8 -*-
"""第 9.3 节：角色包——加载校验、损坏回退、着色保留明暗、缓存与挑图、设置界面的数据层。"""

import json
import os
import shutil
import tempfile
import unittest

from helpers import ROOT, read_json, read_text, write_json, write_text

from core import config as config_mod
from overlay.image_cache import ImageCache
from overlay.layered_window import place
from persona import cachekey
from persona.loader import DEFAULT_PERSONA, PersonaError, load, load_with_fallback

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False

BASE = os.path.join(ROOT, "persona")


class Loader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copytree(os.path.join(BASE, DEFAULT_PERSONA), os.path.join(self.tmp, DEFAULT_PERSONA))
        shutil.copytree(os.path.join(BASE, DEFAULT_PERSONA), os.path.join(self.tmp, "my_mom"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def p(self, *parts):
        return os.path.join(self.tmp, "my_mom", *parts)

    def test_default_pack_is_valid(self):
        per = load(DEFAULT_PERSONA, BASE)
        self.assertEqual(list(per.characters), ["east_asian", "white", "black", "south_asian"])
        for cid, ch in per.characters.items():
            self.assertEqual(set(ch.poses), {"scold", "peek", "care"}, cid)
            for pose, layers in ch.poses.items():
                self.assertEqual([ly.name for ly in layers], ["body", "hair", "line"], (cid, pose))
                self.assertEqual({ly.name: ly.tint for ly in layers}["hair"], "hair")
                self.assertEqual(set(ch.tint_adjust[pose]), {"hair"})          # 只有头发着色，皮肤是原画
        self.assertEqual(len(per.colors["hair"]), 8)
        self.assertEqual(per.lines_for("zh")["unlock_scold"][0], "多大人了，水都不知道喝？一天天就知道折腾你那个电脑！")
        self.assertTrue(per.lines_for("en")["overtime_care"][0].startswith("Working late again?"))

    def test_lines_follow_character_and_language(self):
        """中文 = 华裔妈妈的台词（不管选哪个角色）；英文按角色各有一套。"""
        per = load(DEFAULT_PERSONA, BASE)
        zh = per.lines_for("zh", "east_asian")
        for cid in per.characters:
            self.assertEqual(per.lines_for("zh", cid), zh)
        en = {cid: per.lines_for("en", cid)["unlock_scold"][0] for cid in per.characters}
        self.assertEqual(len(set(en.values())), 4)
        self.assertIn("Aiya", en["east_asian"])
        self.assertIn("Sweetie", en["white"])
        self.assertIn("Child", en["black"])
        self.assertIn("beta", en["south_asian"])
        for cid in per.characters:                     # 四个台词键都齐（喝水版不靠回退）
            self.assertEqual(set(per.lines_for("en", cid)), {"unlock_scold", "side_peek", "side_peek_water",
                                                             "overtime_care"})

    def test_custom_lines_survive_character_and_language(self):
        from persona.lines import effective_lines
        per = load(DEFAULT_PERSONA, BASE)
        custom = {"side_peek": "起来走走！", "use_side_peek": True, "overtime_care": "早点回家", "use_overtime_care": False}
        for lang in ("zh", "en"):
            for cid in per.characters:
                lines = effective_lines(per, lang, cid, custom)
                self.assertEqual(lines["side_peek"], ["起来走走！"])                       # 自定义保留
                self.assertEqual(lines["overtime_care"], per.lines_for(lang, cid)["overtime_care"])   # 开关在“默认”
        self.assertEqual(effective_lines(per, "zh", None, {"side_peek": "  ", "use_side_peek": True})["side_peek"],
                         per.lines_for("zh")["side_peek"])                                  # 空白 = 没有自定义

    def test_old_style_pack_without_characters(self):
        """旧格式（没有 characters）：每个肤色预设算一个角色，共用同一套图，皮肤层按肤色着色。"""
        d = self.p("persona.json")
        meta = read_json(d)
        del meta["characters"]
        meta.pop("default_character")
        write_json(d, meta)
        c = read_json(self.p("colors.json"))
        c["skin"] = [{"name": {"zh": "自然"}, "hex": "#F1C7A1"}, {"name": {"zh": "小麦"}, "hex": "#D29B6A"}]
        write_json(self.p("colors.json"), c)
        per = load("my_mom", self.tmp)
        self.assertEqual(list(per.characters), ["skin0", "skin1"])
        self.assertEqual(per.character("skin1").skin, "#D29B6A")
        self.assertIs(per.character("skin1").poses, per.poses)

    def test_copied_pack_loads(self):
        self.assertEqual(load("my_mom", self.tmp).name, "my_mom")

    def broken(self, mutate, expect):
        mutate()
        with self.assertRaises(PersonaError) as cm:
            load("my_mom", self.tmp)
        self.assertIn(expect, str(cm.exception))
        per, err = load_with_fallback("my_mom", self.tmp)
        self.assertEqual(per.name, DEFAULT_PERSONA)
        self.assertIn("已回退到默认角色包", err)

    def test_bad_json(self):
        self.broken(lambda: write_text(self.p("persona.json"), "{oops"), "不是合法的 JSON")

    def test_missing_pose_folder(self):
        self.broken(lambda: shutil.rmtree(self.p("poses", "peek")), "找不到文件夹")

    def test_bad_layer_name(self):
        self.broken(lambda: os.rename(self.p("poses", "care", "30_hair.png"), self.p("poses", "care", "Hair.png")),
                    "文件名不合规范")

    def test_not_png(self):
        self.broken(lambda: write_text(self.p("poses", "care", "30_hair.png"), b"not a png", "wb"), "不是 PNG")

    def test_missing_line(self):
        def mut():
            d = read_json(self.p("lines", "en.json"))
            d["side_peek"] = []
            write_json(self.p("lines", "en.json"), d)
        self.broken(mut, "至少要有一条台词")

    def test_bad_color(self):
        def mut():
            d = read_json(self.p("colors.json"))
            d["hair"][0]["hex"] = "red"
            write_json(self.p("colors.json"), d)
        self.broken(mut, "#RRGGBB")

    def test_bad_character(self):
        def mut():
            d = read_json(self.p("persona.json"))
            d["characters"]["white"]["skin"] = "pink"
            write_json(self.p("persona.json"), d)
        self.broken(mut, "characters.white.skin")

    def test_character_missing_pose(self):
        self.broken(lambda: shutil.rmtree(self.p("characters", "black", "poses", "care")), "找不到文件夹")

    def test_missing_scene(self):
        def mut():
            d = read_json(self.p("persona.json"))
            del d["scenes"]["overtime_care"]
            write_json(self.p("persona.json"), d)
        self.broken(mut, "缺少场景")

    def test_bad_tint_adjust(self):
        def mut():
            d = read_json(self.p("persona.json"))
            d["characters"]["white"]["tint_adjust"] = {"care": {"hair": [1, 2]}}
            write_json(self.p("persona.json"), d)
        self.broken(mut, "tint_adjust")

    def test_missing_folder_entirely(self):
        per, err = load_with_fallback("nope", self.tmp)
        self.assertEqual(per.name, DEFAULT_PERSONA)
        self.assertIn("找不到角色包文件夹", err)

    def test_extra_lines_supported(self):
        def mut():
            d = read_json(self.p("lines", "zh.json"))
            d["side_peek"] = ["一", "二", "三"]
            write_json(self.p("lines", "zh.json"), d)
        mut()
        self.assertEqual(len(load("my_mom", self.tmp).lines_for("zh")["side_peek"]), 3)


@unittest.skipUnless(HAVE_PIL, "需要 Pillow")
class Render(unittest.TestCase):
    def test_tint_keeps_shading(self):
        from persona.render import tint
        img = Image.new("RGBA", (2, 1))
        img.putpixel((0, 0), (240, 240, 240, 255))
        img.putpixel((1, 0), (160, 160, 160, 255))
        out = tint(img, "#C08040")
        light, dark = out.getpixel((0, 0)), out.getpixel((1, 0))
        self.assertGreater(light[0], dark[0])                        # 阴影保留
        self.assertAlmostEqual(light[0] / light[2], 0xC0 / 0x40, delta=0.2)   # 色相是所选颜色

    def test_tint_multiplier_and_clip(self):
        from persona.render import tint
        img = Image.new("RGBA", (1, 1), (200, 200, 200, 255))
        r, g, b, _ = tint(img, "#808080", (1.0, 2.0, 4.0)).getpixel((0, 0))
        self.assertAlmostEqual(r, 200 * 128 / 255, delta=1)
        self.assertAlmostEqual(g, 200 * 256 / 255, delta=1)
        self.assertEqual(b, 255)                                      # 超过 255 截断

    def test_default_hair_reproduces_art_for_every_character(self):
        """第一个发色预设 × tint_adjust：每个角色每个姿势的头发中位色都和原画一致（误差很小）。"""
        from persona.render import tint
        per = load(DEFAULT_PERSONA, BASE)
        base = per.colors["hair"][0]["hex"]
        for cid, ch in per.characters.items():
            for pose, layers in ch.poses.items():
                ly = next(x for x in layers if x.tint == "hair")
                with Image.open(ly.path) as im:
                    im = im.convert("RGBA")
                t = tint(im, base, ch.tint_adjust[pose]["hair"])
                a = im.getchannel("A")
                px = sorted((t.getpixel((x, y))[:3] for x in range(0, im.width, 2) for y in range(0, im.height, 2)
                             if a.getpixel((x, y)) > 240), key=sum)
                self.assertGreater(len(px), 100, (cid, pose))
                med = px[len(px) // 2]
                self.assertTrue(40 <= sum(med) / 3 <= 140, (cid, pose, med))       # 灰黑发，不会变成白发或纯黑

    def test_bubble_font_falls_back_for_missing_glyphs(self):
        from persona import render
        per = load(DEFAULT_PERSONA, BASE)
        style = per.meta["bubble"]
        f = render.text_font(per, style, "zh", 20, "多喝水")
        self.assertIn("ZCOOL", " ".join(f.getname()))
        self.assertTrue(render.covers(f, "多喝水"))
        self.assertFalse(render.covers(f, "\U0002A6A5"))                # 生僻字：角色包字体里没有
        f2 = render.text_font(per, style, "zh", 20, "多喝水\U0002A6A5")
        self.assertNotIn("ZCOOL", " ".join(f2.getname()))

    def test_emotes_and_bubble_parts(self):
        from persona import render
        for kind in ("anger", "sweat", "drop", "heart"):
            st = render.emote_sticker(kind, 40)
            self.assertEqual(st.size, (40, 40))
            self.assertGreater(st.getchannel("A").getbbox()[2], 20)
        self.assertIsNone(render.emote_sticker("nope", 40))
        per = load(DEFAULT_PERSONA, BASE)
        img, tip_y = render.bubble("坐这多久了你，腰还要不要了！", "zh", 1.0, per.meta["bubble"], "right",
                                   persona=per, emote="sweat")
        self.assertTrue(0 < tip_y < img.height)
        self.assertEqual(img.getpixel((img.width // 2, img.height // 2))[3], 255)   # 气泡中间不透明

    def test_flash_size_follows_monitor_and_ratio(self):
        from persona.render import render_flash
        per = load(DEFAULT_PERSONA, BASE)
        for mon_h, dpi in ((1080, 96), (1440, 120), (2160, 144)):
            im = render_flash(per, "side_peek", "坐这多久了你，腰还要不要了！", "zh", "#4F3F3B", "black", mon_h, dpi)
            self.assertGreaterEqual(im.height, round(mon_h * 0.22))
            self.assertLess(im.height, mon_h * 0.3)

    def test_pbgra_roundtrip_premultiplied(self):
        from persona.render import to_pbgra
        img = Image.new("RGBA", (3, 1), (0, 0, 0, 0))
        img.putpixel((0, 0), (200, 100, 50, 128))
        w, h, data = cachekey.unpack(to_pbgra(img))
        self.assertEqual((w, h, len(data)), (3, 1, 12))
        b, g, r, a = data[0:4]
        self.assertEqual(a, 128)
        self.assertAlmostEqual(r, 200 * 128 / 255, delta=1.5)           # 预乘 alpha
        self.assertAlmostEqual(b, 50 * 128 / 255, delta=1.5)

    def test_ensure_and_lookup(self):
        from persona import render
        with tempfile.TemporaryDirectory() as d:
            cfg = config_mod.from_dict()
            per = load(DEFAULT_PERSONA, BASE)
            vdir = render.ensure(cfg, [(1080, 96), (2160, 144)], per, cache_dir=d, log=None)
            m = cachekey.read_manifest(vdir)
            keys = {e["line_key"] for e in m["entries"]}
            self.assertEqual(keys, {"unlock_scold", "side_peek", "side_peek_water", "overtime_care"})
            self.assertEqual(len(m["entries"]), 8)
            cache = ImageCache(d)
            cache.set_expected(cachekey.variant_key(per, cfg), "zh")
            self.assertTrue(cache.has_exact([(1080, 96), (2160, 144)]))
            self.assertFalse(cache.has_exact([(1440, 120)]))
            path, exact = cache.lookup("side_peek", 0, 2160, 144)
            self.assertTrue(exact and path.endswith("h2160-d144.pbgra"))
            path, exact = cache.lookup("side_peek", 0, 1200, 96)            # 没有精确尺寸 → 最接近的
            self.assertFalse(exact)
            self.assertTrue(path.endswith("h1080-d96.pbgra"))
            # 改了发色：新键找不到 → 回退到同语言的旧缓存，不会没图可用
            cfg2 = config_mod.from_dict({"appearance": {"hair_color": "#FF0000"}})
            cache.set_expected(cachekey.variant_key(per, cfg2), "zh")
            self.assertIsNotNone(cache.lookup("unlock_scold", 0, 1080, 96))
            self.assertFalse(cache.has_exact([(1080, 96)]))

    def test_settings_model_and_preview_match_flash(self):
        from persona import render
        from settings_ui.model import SettingsModel
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.toml")
            shutil.copy(os.path.join(ROOT, "config.toml"), path)
            m = SettingsModel(path)
            self.assertFalse(m.set_skin("#123456"))           # 肤色 = 角色，只有四个
            self.assertFalse(m.set_character("martian"))
            self.assertTrue(m.set_character("south_asian"))
            self.assertTrue(m.set_hair("#ABCDEF"))            # 发色可自由取色
            self.assertTrue(m.set_lang("en"))
            self.assertIn("Beta", m.line("side_peek"))
            # 在气泡里改台词 → 自定义；换角色、换语言后保留；可切回默认，内容不丢
            self.assertTrue(m.set_custom("side_peek", "Get up and   stretch,\n now!"))
            self.assertEqual(m.line("side_peek"), "Get up and stretch, now!")
            m.set_character("white")
            m.set_lang("zh")
            self.assertEqual(m.line("side_peek"), "Get up and stretch, now!")
            self.assertTrue(m.use_default("side_peek", True))
            self.assertEqual(m.line("side_peek"), "坐这多久了你，腰还要不要了！")
            self.assertTrue(m.has_custom("side_peek"))
            self.assertTrue(m.use_default("side_peek", False))
            self.assertFalse(m.use_default("overtime_care", False))        # 没有自定义内容时不能切到“自定义”
            m.set_custom("overtime_care", m.default_line("overtime_care"))  # 改回原样 = 默认
            self.assertFalse(m.is_custom("overtime_care"))
            m.set_lang("en")
            m.set_character("south_asian")
            prev = m.preview(1080, 96)["side_peek"]
            cache_dir = os.path.join(d, "cache")
            orig = cachekey.CACHE_DIR
            try:
                res = None
                old_ensure = render.ensure
                render.ensure = lambda cfg, sizes, persona=None, **kw: old_ensure(cfg, sizes, persona,
                                                                                     cache_dir=cache_dir, log=None)
                res = m.save([(1080, 96)], notify=lambda: True)
            finally:
                render.ensure = old_ensure
                cachekey.CACHE_DIR = orig
            self.assertTrue(res["notified"])
            saved = config_mod.load(path)
            self.assertEqual(saved.language, "en")
            self.assertEqual(saved.raw["appearance"]["hair_color"], "#ABCDEF")
            self.assertEqual(saved.raw["appearance"]["character"], "south_asian")
            self.assertEqual(saved.raw["custom_lines"]["side_peek"], "Get up and stretch, now!")
            self.assertTrue(saved.raw["custom_lines"]["use_side_peek"])
            m2 = SettingsModel(path)                                          # 重新打开设置：自定义还在
            self.assertEqual(m2.line("side_peek"), "Get up and stretch, now!")
            self.assertIn("beta", m2.line("unlock_scold"))
            self.assertIn("# zh / en", read_text(path))      # 注释保留
            # 预览与实际闪现用的是同一张图（同参数、同尺寸时逐像素一致）
            w, h, data = cachekey.unpack(read_text(os.path.join(res["cache"], "side_peek-0-h1080-d96.pbgra"), "rb"))
            from persona.render import to_pbgra
            self.assertEqual(data, cachekey.unpack(to_pbgra(prev))[2])


@unittest.skipUnless(HAVE_PIL, "需要 Pillow")
class SettingsUi(unittest.TestCase):
    """设置界面：整张画面用 Pillow 画，热区可点——在任何系统上都能测。"""

    def state(self, lang="zh", previews=False):
        from settings_ui.ui_render import UiState
        per = load(DEFAULT_PERSONA, BASE)
        pre = [(i["name"][lang], i["hex"]) for i in per.colors["hair"]]
        chars = [(c.id, c.label(lang), c.skin) for c in per.characters.values()]
        st = UiState(lang=lang, hair=pre[0][1], character="east_asian", hair_presets=pre, characters=chars,
                     traits=per.characters["east_asian"].traits[lang], display_name="x",
                     stats={"water_min": 31, "sitting_min": 3, "effective_today_min": 125,
                            "thresholds": {"water": 60, "sitting_soft": 50}})
        if previews:
            from persona.render import render_flash
            st.previews = {k: render_flash(per, "side_peek" if k.startswith("side") else k, "测试台词", lang,
                                           pre[0][1], "east_asian", 1080, 96, line_key=k)
                           for k in ("unlock_scold", "side_peek", "side_peek_water", "overtime_care")}
        return st

    def test_hotspots_cover_every_control(self):
        from settings_ui.ui_render import H, W, hit, render_ui
        for scale in (1.0, 1.5):
            img, hot = render_ui(self.state(), scale)
            self.assertEqual(img.size, (round(W * scale), round(H * scale)))
            kinds = [h.action for h in hot]
            self.assertEqual(kinds.count("hair"), 8)
            self.assertEqual(kinds.count("skin"), 4)
            self.assertEqual(kinds.count("lang"), 2)
            self.assertEqual(kinds.count("tab"), 3)
            for k in ("custom", "save", "demo", "close"):
                self.assertEqual(kinds.count(k), 1, k)
            for h in hot:                                         # 每个热区中心都点得到它自己，且在窗口内
                x0, y0, x1, y1 = h.box
                self.assertIs(hit(hot, (x0 + x1) / 2, (y0 + y1) / 2), h)
                self.assertTrue(0 <= x0 < x1 <= img.width and 0 <= y0 < y1 <= img.height)
            self.assertIsNone(hit(hot, 2, 2))

    def test_english_and_not_running(self):
        from settings_ui.ui_render import render_ui
        st = self.state("en")
        st.stats = None
        img, hot = render_ui(st)
        self.assertEqual(len(hot), 21)

    def test_bubble_is_clickable_and_toggles_appear(self):
        """预览里的气泡可以点（热区正好盖住气泡）；侧边探头有 久坐/喝水 两版；有自定义时角落出现 默认/自定义 切换。"""
        from settings_ui.ui_render import render_ui
        st = self.state("zh", previews=True)
        _, hot = render_ui(st)
        edit = [h for h in hot if h.action == "edit"]
        self.assertEqual([h.arg for h in edit], ["unlock_scold"])
        x0, y0, x1, y1 = edit[0].box
        self.assertTrue(x1 - x0 > 100 and y1 - y0 > 30)
        self.assertFalse([h for h in hot if h.action in ("variant", "line_mode")])
        st.tab, st.variant = "side_peek", "side_peek_water"
        st.line_state = {"side_peek_water": {"has": True, "custom": True}}
        _, hot = render_ui(st, 1.5)
        self.assertEqual([h.arg for h in hot if h.action == "edit"], ["side_peek_water"])
        self.assertEqual([h.arg for h in hot if h.action == "variant"], ["side_peek", "side_peek_water"])
        self.assertEqual([h.arg for h in hot if h.action == "line_mode"], ["default", "custom"])

    def test_model_stats_freshness(self):
        from core.clock import iso
        from settings_ui.model import SettingsModel
        import time as _t
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            write_json(path, {"updated": iso(_t.time() - 30), "water_min": 12})
            self.assertEqual(SettingsModel.stats(path)["water_min"], 12)
            write_json(path, {"updated": iso(_t.time() - 3600), "water_min": 12})
            self.assertIsNone(SettingsModel.stats(path))
            self.assertIsNone(SettingsModel.stats(os.path.join(d, "missing.json")))


class Placement(unittest.TestCase):
    def mon(self, **kw):
        from winapi.monitors import Monitor
        d = dict(left=0, top=0, right=1920, bottom=1080, work_left=0, work_top=0, work_right=1920, work_bottom=1040,
                 dpi=96, primary=True)
        d.update(kw)
        return Monitor(**d)

    def test_anchors(self):
        m = self.mon()
        x, y = place("top_center", 500, 240, m)
        self.assertEqual((x, round(y)), (710, 130))
        x, y = place("right_edge", 400, 240, m)
        self.assertEqual(x + 400, 1920)                       # 贴右边缘
        x, y = place("bottom_right", 500, 240, m)
        self.assertEqual(y + 240, 1040)                       # 站在任务栏上
        self.assertEqual(x + 500 + 16, 1920)

    def test_second_monitor_with_negative_coords_and_150pct(self):
        m = self.mon(left=-2560, top=-200, right=0, bottom=1240, work_left=-2560, work_top=-200, work_right=0,
                     work_bottom=1180, dpi=144, primary=False)
        for anchor in ("top_center", "right_edge", "bottom_right"):
            x, y = place(anchor, 700, 330, m)
            self.assertTrue(m.left <= x and x + 700 <= m.right and m.top <= y and y + 330 <= m.bottom, anchor)
        x, _ = place("bottom_right", 700, 330, m)
        self.assertEqual(x + 700 + 24, 0)                     # 边距按 150% 缩放


if __name__ == "__main__":
    unittest.main()
