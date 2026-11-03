# -*- coding: utf-8 -*-
"""config.toml：键与默认值一致、写坏时回退、演示模式缩放。"""

import os
import tempfile
import tomllib
import unittest

from helpers import ROOT, write_text

from core import config as config_mod


def flat(d, prefix=""):
    out = set()
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out |= flat(v, key + ".")
        else:
            out.add(key)
    return out


class ConfigFile(unittest.TestCase):
    def test_shipped_config_parses_and_matches_defaults(self):
        with open(os.path.join(ROOT, "config.toml"), "rb") as fh:
            user = tomllib.load(fh)
        self.assertEqual(flat(user), flat(config_mod.DEFAULTS))
        cfg = config_mod.load(os.path.join(ROOT, "config.toml"))
        self.assertEqual(cfg.errors, [])
        self.assertEqual(cfg.P.water_threshold, 60)
        self.assertEqual(cfg.P.sitting_soft, 50)
        self.assertEqual(cfg.P.sitting_hard, 100)
        self.assertEqual(cfg.P.min_gap_s, 1200)
        self.assertEqual(cfg.P.a_cap_s, 7200)
        self.assertEqual(cfg.P.c_effective_buckets, 480)
        self.assertEqual(cfg.P.c_after_min, 17 * 60 + 30)
        self.assertEqual(cfg.scene_timing("unlock_scold"), (1.5, 0.5))

    def test_broken_file_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.toml")
            write_text(p, "[policy\nwater = ")
            cfg = config_mod.load(p)
            self.assertTrue(cfg.errors)
            self.assertEqual(cfg.P.water_threshold, 60)

    def test_illegal_value_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.toml")
            write_text(p, '[policy]\nscene_c_after = "25:99"\n')
            cfg = config_mod.load(p)
            self.assertTrue(cfg.errors)
            self.assertEqual(cfg.P.c_after_min, 17 * 60 + 30)

    def test_language(self):
        self.assertEqual(config_mod.from_dict({"general": {"language": "EN"}}).language, "en")
        self.assertEqual(config_mod.from_dict({"general": {"language": "fr"}}).language, "zh")


if __name__ == "__main__":
    unittest.main()


class CustomLinesInToml(unittest.TestCase):
    def test_custom_line_with_quotes_roundtrips_and_keeps_comments(self):
        """自定义台词写进 config.toml：引号、反斜杠、# 都要能原样读回，注释不丢，相似的键名不串。"""
        from settings_ui.config_writer import update_text
        with open(os.path.join(ROOT, "config.toml"), encoding="utf-8") as fh:
            text = fh.read()
        v = 'Now, not "in a minute." C:\\temp 50% #不是注释'
        out = update_text(text, {"custom_lines.side_peek_water": v, "custom_lines.use_side_peek_water": True,
                                 "custom_lines.side_peek": "起来！"})
        d = tomllib.loads(out)["custom_lines"]
        self.assertEqual(d["side_peek_water"], v)
        self.assertTrue(d["use_side_peek_water"])
        self.assertEqual(d["side_peek"], "起来！")
        self.assertFalse(d["use_side_peek"])
        self.assertIn("# 自定义台词", out)
