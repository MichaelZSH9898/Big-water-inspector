# -*- coding: utf-8 -*-
"""设置界面的数据与动作（不含任何 tkinter 代码，可单独测试）。"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime

from core import config as config_mod
from core.state_file import read_json
from persona import render
from persona.lines import CUSTOM_KEYS, custom_text, lines_for_config
from persona.loader import load_with_fallback

from .config_writer import update_file

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
SCENES = ("unlock_scold", "side_peek", "overtime_care")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "state.json")


PREVIEW_KEYS = ("unlock_scold", "side_peek", "side_peek_water", "overtime_care")
KEY_SCENE = {"unlock_scold": "unlock_scold", "side_peek": "side_peek", "side_peek_water": "side_peek",
             "overtime_care": "overtime_care"}


class SettingsModel:
    def __init__(self, config_path: str | None = None):
        self.path = config_path or config_mod.CONFIG_PATH
        self.cfg = config_mod.load(self.path)
        self.persona, self.persona_error = load_with_fallback(self.cfg.persona)
        ap = self.cfg.raw["appearance"]
        self.lang = self.cfg.language
        self.hair = str(ap.get("hair_color") or self.presets("hair")[0][1]).upper()
        self.character = self.persona.character(ap.get("character")).id
        cl = self.cfg.raw.get("custom_lines") or {}
        self.custom = {k: custom_text(cl, k) for k in CUSTOM_KEYS}
        self.use_custom = {k: bool(cl.get(f"use_{k}", False)) and bool(self.custom[k]) for k in CUSTOM_KEYS}
        self.dirty = False

    # ── 选项 ─────────────────────────────────────────────────────────────
    def presets(self, kind: str) -> list[tuple[str, str]]:
        """hair：[(名称, #hex)]；skin：[(角色名, 色块 #hex)]——换肤色就是换角色。"""
        lang = getattr(self, "lang", None) or self.cfg.language
        if kind == "skin":
            return [(c.label(lang), c.skin) for c in self.persona.characters.values()]
        out = []
        for item in self.persona.colors.get(kind, [])[:8]:
            name = item.get("name", {})
            label = (name.get(lang) or name.get("zh") or item["hex"]) if isinstance(name, dict) else str(name)
            out.append((label, item["hex"].upper()))
        return out

    def characters(self) -> list[tuple[str, str, str]]:
        """[(角色 id, 名称, 肤色色块)]"""
        return [(c.id, c.label(self.lang), c.skin) for c in self.persona.characters.values()]

    def _localized(self, v, default):
        if isinstance(v, dict):
            return v.get(self.lang) or v.get("zh") or default
        return v or default

    def display_name(self) -> str:
        ch = self.persona.character(self.character)
        return str(self._localized(ch.display_name, None) or self._localized(self.persona.meta.get("display_name"),
                                                                           self.persona.name))

    def card_name(self) -> str:
        """角色卡和气泡名牌上的称呼：角色自己的（Mama、Mummy……）优先，否则用角色包的。"""
        ch = self.persona.character(self.character)
        own = (ch.bubble_name or {}).get(self.lang)
        base = ((self.persona.meta.get("bubble") or {}).get("name") or {})
        return str(own or base.get(self.lang) or base.get("zh") or "")

    def traits(self) -> list[str]:
        """角色卡上的性格标签（persona.json 里角色的 traits，可不写）。"""
        ch = self.persona.character(self.character)
        t = self._localized(ch.traits, None) or self._localized(self.persona.meta.get("traits"), [])
        return [str(x) for x in t] if isinstance(t, list) else []

    def figure(self, pose: str | None = None):
        """角色卡立绘：默认用加班关怀（全身）那个姿势，按当前角色、发色着色。"""
        pose = pose or self.persona.scene_pose("overtime_care") or next(iter(self.persona.poses))
        return render.compose_pose(self.persona, pose, self.hair, self.character)

    @staticmethod
    def stats(path: str = STATE_PATH, max_age_s: float = 180) -> dict | None:
        """哨兵每分钟写的 state.json；超过 3 分钟没更新就当作没在运行。"""
        d = read_json(path)
        if not d:
            return None
        try:
            ts = datetime.fromisoformat(str(d.get("updated"))).timestamp()
        except (TypeError, ValueError):
            return None
        return d if time.time() - ts <= max_age_s else None

    def set_hair(self, hex_color: str) -> bool:
        """发色：8 个预设 + 自由取色。"""
        if not HEX.match(hex_color or ""):
            return False
        self.hair, self.dirty = hex_color.upper(), True
        return True

    def set_character(self, cid: str) -> bool:
        """肤色 = 角色（每个角色有自己的一套图和台词）。"""
        if cid not in self.persona.characters:
            return False
        self.character, self.dirty = cid, True
        return True

    def set_skin(self, hex_or_id: str) -> bool:
        """兼容：传色块颜色或角色 id 都行。"""
        for c in self.persona.characters.values():
            if (hex_or_id or "").upper() == c.skin.upper() or hex_or_id == c.id:
                return self.set_character(c.id)
        return False

    def set_lang(self, lang: str) -> bool:
        if lang not in ("zh", "en") or lang not in self.persona.languages:
            return False
        self.lang, self.dirty = lang, True
        return True

    # ── 台词：默认 / 自定义 ──────────────────────────────────────────────
    def default_line(self, key: str) -> str:
        arr = self.persona.lines_for(self.lang, self.character).get(key) or [""]
        return arr[0]

    def line(self, key: str) -> str:
        """预览里显示、实际闪现会说的那一句。"""
        return self.custom[key] if self.is_custom(key) else self.default_line(key)

    def is_custom(self, key: str) -> bool:
        return bool(self.custom.get(key)) and self.use_custom.get(key, False)

    def has_custom(self, key: str) -> bool:
        return bool(self.custom.get(key))

    def set_custom(self, key: str, text: str) -> bool:
        """在气泡里改完台词：保存为自定义并切到“自定义”。改成和默认一模一样、或清空，就回到默认。"""
        if key not in CUSTOM_KEYS:
            return False
        text = " ".join(str(text or "").split())[:200]
        if not text or text == self.default_line(key):
            self.custom[key], self.use_custom[key] = (self.custom[key] if text else ""), False
        else:
            self.custom[key], self.use_custom[key] = text, True
        self.dirty = True
        return True

    def use_default(self, key: str, default: bool) -> bool:
        """角落里的“默认 / 自定义”切换。自定义的内容一直保留，只是暂时不用。"""
        if key not in CUSTOM_KEYS or (not default and not self.custom.get(key)):
            return False
        self.use_custom[key], self.dirty = not default, True
        return True

    def custom_config(self) -> dict:
        out = {}
        for k in CUSTOM_KEYS:
            out[k] = self.custom.get(k, "")
            out[f"use_{k}"] = bool(self.use_custom.get(k)) and bool(self.custom.get(k))
        return out

    # ── 渲染 ─────────────────────────────────────────────────────────────
    def updates(self) -> dict:
        up = {"general.language": self.lang, "appearance.hair_color": self.hair,
              "appearance.character": self.character}
        up.update({f"custom_lines.{k}": v for k, v in self.custom_config().items()})
        return up

    def pending_config(self):
        over = config_mod.deep_merge(self.cfg.raw, {"general": {"language": self.lang},
                                                    "appearance": {"hair_color": self.hair,
                                                                   "character": self.character},
                                                    "custom_lines": self.custom_config()})
        return config_mod.from_dict(over, self.path)

    def preview(self, mon_h: int = 1080, dpi: int = 96, keys=PREVIEW_KEYS) -> dict:
        """各场景（含侧边探头的喝水版）的预览图——与实际闪现同一条渲染管线、同一套参数，只是显示器尺寸不同。"""
        cfg = self.pending_config()
        disp = cfg.raw["display"]
        lines = lines_for_config(self.persona, cfg)
        out = {}
        for key in keys:
            out[key] = render.render_flash(self.persona, KEY_SCENE[key], lines[key][0], self.lang, self.hair,
                                           self.character, mon_h, dpi, float(disp.get("figure_height_ratio", 0.22)),
                                           float(disp.get("font_scale", 1.0)), line_key=key)
        return out

    def save(self, monitor_sizes: list[tuple[int, int]], notify=None) -> dict:
        """写配置 → 重新渲染缓存 → 通知哨兵。返回 {"cache": 目录, "notified": bool}。"""
        update_file(self.path, self.updates())
        self.cfg = config_mod.load(self.path)
        vdir = render.ensure(self.cfg, monitor_sizes or [(1080, 96)], self.persona, log=None)
        notified = bool(notify()) if notify else False
        self.dirty = False
        return {"cache": vdir, "notified": notified}
