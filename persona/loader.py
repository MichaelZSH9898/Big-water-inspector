# -*- coding: utf-8 -*-
"""角色包加载与校验（只用标准库，哨兵进程里也能用）。

角色包 = persona/ 下的一个文件夹，结构见 persona/README.md。加载时逐项校验，
出错给出可读的中文报错（哪个文件、哪一项、怎么改），并回退到默认角色包，绝不崩溃。

一个角色包里可以有几个“角色”（characters，比如华裔、白人、黑人、印度裔妈妈）：各有一套姿势图和台词，
设置界面里“换肤色”就是换角色。没写 characters 的旧角色包，colors.json 里的每个肤色预设算一个角色（共用同一套图，
只是皮肤层换个颜色），行为和以前一样。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PERSONA = "default_mom"
SCHEMA = 1
LAYER_RE = re.compile(r"^(\d{2})_([a-z0-9]+)\.png$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
REQUIRED_SCENES = ("unlock_scold", "side_peek", "overtime_care")
LINE_FALLBACK = {"side_peek_water": "side_peek"}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class PersonaError(Exception):
    """角色包有问题。message 是给人看的中文说明。"""


@dataclass
class Layer:
    order: int
    name: str
    path: str
    tint: str | None      # None / "hair" / "skin"


SCENE_LINE_KEYS = ("unlock_scold", "side_peek", "side_peek_water", "overtime_care")


@dataclass
class Character:
    id: str
    name: dict            # {"zh": "华裔妈妈", "en": "Chinese mom"}
    skin: str             # 设置界面里的肤色色块；皮肤层（如有）也按它着色
    dir: str              # 这个角色的文件夹（poses/、lines/ 在它下面）
    poses: dict           # pose -> [Layer]
    lines: dict           # lang -> key -> [str]（可以为空，空就用角色包根目录的台词）
    tint_adjust: dict = field(default_factory=dict)
    display_name: dict = field(default_factory=dict)
    traits: dict = field(default_factory=dict)
    bubble_name: dict = field(default_factory=dict)   # 气泡名牌上的称呼，如 {"en": "Mama"}；不写就用 bubble.name

    def label(self, lang: str) -> str:
        return str(self.name.get(lang) or self.name.get("zh") or self.id) if isinstance(self.name, dict) \
            else str(self.name or self.id)


@dataclass
class Persona:
    name: str
    dir: str
    meta: dict
    lines: dict           # lang -> key -> [str]
    colors: dict          # "hair"/"skin" -> [{"name": {...}, "hex": "#..."}]
    poses: dict = field(default_factory=dict)   # pose -> [Layer]（默认角色的）
    characters: dict = field(default_factory=dict)   # id -> Character（按 persona.json 里的顺序）
    default_character: str = ""

    @property
    def version(self) -> str:
        return str(self.meta.get("version", "0"))

    @property
    def languages(self) -> list:
        return list(self.lines.keys())

    def scene(self, scene_name: str) -> dict:
        return (self.meta.get("scenes") or {}).get(scene_name) or {}

    def scene_pose(self, scene_name: str, default: str | None = None) -> str | None:
        return self.scene(scene_name).get("pose", default)

    def character(self, cid: str | None = None) -> Character:
        return self.characters.get(cid or "") or self.characters[self.default_character]

    def lines_for(self, lang: str, character: str | None = None) -> dict:
        """台词：先找这个角色自己的（characters/<id>/lines/<lang>.json），没有就用角色包根目录的。
        默认包里中文台词只有一套（华裔妈妈），所以中文下换角色台词不变；英文每个角色各有一套。"""
        lang = lang if lang in self.lines else self.meta.get("default_language", "zh")
        own = self.characters[character].lines.get(lang) if character in self.characters else None
        d = dict(own or self.lines.get(lang) or next(iter(self.lines.values())))
        for k, fb in LINE_FALLBACK.items():
            if not d.get(k) and d.get(fb):
                d[k] = d[fb]
        return d

    def fingerprint(self) -> str:
        """角色包内容指纹：文件大小 + 修改时间。换图改字后缓存自动失效。"""
        h = hashlib.sha1()
        for root, _, files in os.walk(self.dir):
            for f in sorted(files):
                p = os.path.join(root, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                h.update(f"{os.path.relpath(p, self.dir)}:{st.st_size}:{int(st.st_mtime)}".encode())
        return h.hexdigest()[:12]


def _read_json(path: str, what: str) -> object:
    if not os.path.exists(path):
        raise PersonaError(f"缺少{what}：{path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as exc:
        raise PersonaError(f"{what}不是合法的 JSON（{path}）：{exc}") from exc
    except OSError as exc:
        raise PersonaError(f"读不了{what}（{path}）：{exc}") from exc


def _check_png(path: str) -> None:
    try:
        with open(path, "rb") as fh:
            if fh.read(8) != PNG_MAGIC:
                raise PersonaError(f"图层不是 PNG 文件：{path}")
    except OSError as exc:
        raise PersonaError(f"读不了图层 {path}：{exc}") from exc


def load(name: str, base_dir: str = BASE_DIR) -> Persona:
    d = os.path.join(base_dir, name)
    if not os.path.isdir(d):
        raise PersonaError(f"找不到角色包文件夹：{d}")
    meta = _read_json(os.path.join(d, "persona.json"), "persona.json")
    if not isinstance(meta, dict):
        raise PersonaError("persona.json 顶层应该是一个对象 {…}")
    if int(meta.get("schema", 0)) != SCHEMA:
        raise PersonaError(f"persona.json 的 schema 应为 {SCHEMA}，现在是 {meta.get('schema')!r}")
    for key in ("name", "version", "poses", "scenes", "languages"):
        if key not in meta:
            raise PersonaError(f"persona.json 缺少字段 \"{key}\"")

    layer_rules = meta.get("layers") or {}
    poses = _load_poses(d, meta["poses"], layer_rules)
    adj = meta.get("tint_adjust")
    _check_tint_adjust(adj, poses, "tint_adjust")

    scenes = meta["scenes"]
    for sc in REQUIRED_SCENES:
        if sc not in scenes:
            raise PersonaError(f"persona.json 的 scenes 里缺少场景 \"{sc}\"")
    for sc, spec in scenes.items():
        pose = (spec or {}).get("pose")
        if pose not in poses:
            raise PersonaError(f"场景 \"{sc}\" 用的姿势 \"{pose}\" 不在 poses 列表里")

    # 台词
    lines = {lang: _load_lines(os.path.join(d, "lines", f"{lang}.json"), lang, scenes, required=True)
             for lang in meta["languages"]}

    # 颜色预设
    colors = _read_json(os.path.join(d, "colors.json"), "colors.json")
    if not isinstance(colors, dict):
        raise PersonaError("colors.json 顶层应该是 {\"hair\": [...], \"skin\": [...]}")
    chars_meta = meta.get("characters")
    for k in ("hair",) + (() if chars_meta else ("skin",)):
        arr = colors.get(k)
        if not isinstance(arr, list) or not arr:
            raise PersonaError(f"colors.json 缺少 \"{k}\" 预设列表")
    for k in ("hair", "skin"):
        for item in colors.get(k) or []:
            if not isinstance(item, dict) or not HEX_RE.match(str(item.get("hex", ""))):
                raise PersonaError(f"colors.json 的 {k} 里有一项颜色不是 #RRGGBB：{item!r}")

    # 角色
    characters: dict[str, Character] = {}
    if chars_meta:
        if not isinstance(chars_meta, dict):
            raise PersonaError("persona.json 的 characters 应该是 {角色id: {...}}")
        for cid, c in chars_meta.items():
            if not re.match(r"^[a-z0-9_]+$", cid) or not isinstance(c, dict):
                raise PersonaError(f"persona.json 的 characters 里 \"{cid}\" 写法不对（id 只能用小写字母、数字、下划线）")
            if not HEX_RE.match(str(c.get("skin", ""))):
                raise PersonaError(f"persona.json 的 characters.{cid}.skin 应该是 #RRGGBB（设置界面里的肤色色块）")
            cdir = os.path.normpath(os.path.join(d, c.get("dir") or ""))
            if not cdir.startswith(os.path.normpath(d)):
                raise PersonaError(f"persona.json 的 characters.{cid}.dir 必须在角色包文件夹里面")
            cposes = poses if cdir == os.path.normpath(d) else _load_poses(cdir, meta["poses"], layer_rules)
            _check_tint_adjust(c.get("tint_adjust"), cposes, f"characters.{cid}.tint_adjust")
            clines = {}
            for lang in meta["languages"]:
                lp = os.path.join(cdir, "lines", f"{lang}.json")
                if cdir != os.path.normpath(d) and os.path.exists(lp):
                    clines[lang] = _load_lines(lp, lang, scenes, required=True)
            characters[cid] = Character(cid, c.get("name") or {}, str(c["skin"]).upper(), cdir, cposes, clines,
                                        c.get("tint_adjust") or {}, c.get("display_name") or {},
                                        c.get("traits") or {}, c.get("bubble_name") or {})
    else:                                       # 旧格式：每个肤色预设算一个角色，共用同一套图
        for i, item in enumerate(colors.get("skin") or [{"hex": "#E7A690", "name": {}}]):
            characters[f"skin{i}"] = Character(f"skin{i}", item.get("name") or {}, str(item["hex"]).upper(), d, poses,
                                               {}, adj or {}, meta.get("display_name") or {},
                                               meta.get("traits") or {})
    default_char = meta.get("default_character") or next(iter(characters))
    if default_char not in characters:
        raise PersonaError(f"persona.json 的 default_character \"{default_char}\" 不在 characters 里")
    return Persona(name=name, dir=d, meta=meta, lines=lines, colors=colors, poses=characters[default_char].poses,
                   characters=characters, default_character=default_char)


def _load_poses(d: str, pose_names: list, layer_rules: dict) -> dict:
    poses: dict[str, list[Layer]] = {}
    for pose in pose_names:
        pd = os.path.join(d, "poses", pose)
        if not os.path.isdir(pd):
            raise PersonaError(f"persona.json 声明了姿势 \"{pose}\"，但找不到文件夹 {pd}")
        layers = []
        for f in sorted(os.listdir(pd)):
            m = LAYER_RE.match(f)
            if not m:
                if f.lower().endswith(".png"):
                    raise PersonaError(f"图层文件名不合规范：{pd}\\{f}（应为“两位数字_小写名称.png”，如 30_hair.png）")
                continue
            path = os.path.join(pd, f)
            _check_png(path)
            rule = layer_rules.get(m.group(2)) or {}
            tint = rule.get("tint")
            if tint not in (None, "hair", "skin"):
                raise PersonaError(f"persona.json layers.{m.group(2)}.tint 只能是 \"hair\"、\"skin\" 或不写")
            layers.append(Layer(int(m.group(1)), m.group(2), path, tint))
        if not layers:
            raise PersonaError(f"姿势文件夹里没有任何图层：{pd}")
        poses[pose] = layers
    return poses


def _check_tint_adjust(adj, poses: dict, where: str) -> None:
    if adj is None:
        return
    if not isinstance(adj, dict):
        raise PersonaError(f"persona.json 的 {where} 应该是 {{姿势: {{\"skin\": [r, g, b], \"hair\": [r, g, b]}}}}")
    for pose, rule in adj.items():
        if pose not in poses or not isinstance(rule, dict):
            raise PersonaError(f"persona.json 的 {where} 里 \"{pose}\" 不是已声明的姿势，或写法不对")
        for k, v in rule.items():
            if k not in ("skin", "hair") or not isinstance(v, list) or len(v) != 3 or \
                    not all(isinstance(x, (int, float)) and 0 < x <= 8 for x in v):
                raise PersonaError(f"persona.json 的 {where}.{pose}.{k} 应该是三个 0–8 之间的数（各通道倍数）")


def _load_lines(path: str, lang: str, scenes: dict, required: bool) -> dict:
    rel = os.path.join(os.path.basename(os.path.dirname(os.path.dirname(path))), "lines", f"{lang}.json")
    data = _read_json(path, f"{lang} 台词文件")
    if not isinstance(data, dict):
        raise PersonaError(f"{rel} 顶层应该是 {{\"场景名\": [\"台词\", …]}}")
    for sc in scenes:
        arr = data.get(sc)
        if not isinstance(arr, list) or not [x for x in arr if isinstance(x, str) and x.strip()]:
            raise PersonaError(f"lines/{lang}.json 里场景 \"{sc}\" 至少要有一条台词（字符串数组）（{path}）")
    for k, v in data.items():
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise PersonaError(f"lines/{lang}.json 里 \"{k}\" 应该是字符串数组（{path}）")
    return data


def load_with_fallback(name: str, base_dir: str = BASE_DIR, log=None) -> tuple[Persona, str | None]:
    """加载指定角色包；失败时回退默认包。返回 (角色包, 报错说明或 None)。"""
    try:
        return load(name, base_dir), None
    except PersonaError as exc:
        msg = f"角色包“{name}”加载失败：{exc}。已回退到默认角色包。"
        if log:
            log.app(msg)
        if name == DEFAULT_PERSONA:
            raise
        return load(DEFAULT_PERSONA, base_dir), msg


def list_personas(base_dir: str = BASE_DIR) -> list[str]:
    out = []
    for f in sorted(os.listdir(base_dir)):
        if os.path.isfile(os.path.join(base_dir, f, "persona.json")):
            out.append(f)
    return out
