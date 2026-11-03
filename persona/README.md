# 做一个你自己的角色包

本项目对用户展示的角色是妈妈；此处“角色包”是技术名称，用于组织妈妈的形象、外观预设和台词。配置中的 `characters` 代表妈妈的外观预设，不表示多个不同身份。

角色包就是 `persona/` 下的一个文件夹。**不需要读主程序代码，也不需要改任何代码**：复制一份、换图、改字即可。

## 1. 三步上手

1. 复制 `persona/default_mom/`，改名为比如 `persona/my_mom/`。
2. 改 `persona.json` 里的 `name`（与文件夹同名）、`display_name`、`version`；换 `poses/` 里的图、改 `lines/` 里的台词。
3. 在 `config.toml` 里把 `[general] persona` 改成 `"my_mom"`，保存。哨兵一分钟内会自动加载（或在托盘“设置”里点保存）。

先自查效果（会出一张三个场景的预览图）：

```bash
python -m persona.render --preview my_mom_preview.png
python -m persona.render --preview my_mom_preview.png --size 2160x144     # 模拟 4K 150% 屏
```

角色包有任何问题，哨兵都**不会崩溃**：它会在 `logs/app.log` 里写一句看得懂的报错（哪个文件、哪一项、该怎么改），
然后回退到默认角色包继续工作。

## 2. 文件夹结构

```
my_mom/
├─ persona.json          名称、版本、语言、姿势、场景、图层着色规则、气泡样式、角色列表
├─ lines/zh.json         默认角色的台词（场景 → 台词数组）
├─ lines/en.json
├─ colors.json           发色预设（设置界面里的 8 个色块；第一个是默认色）
├─ fonts/                气泡用的字体（可选；默认包带的是 OFL 授权的站酷快乐体和 Nunito）
├─ poses/                默认角色的三个姿势
│  ├─ scold/             场景 A：训话（竖手指）
│  ├─ peek/              场景 B：探头（脸朝左看向屏幕内侧，右缘会贴着屏幕右边）
│  └─ care/              场景 C：关怀（张开双臂）
│     ├─ 20_body.png     头发以外的一切，彩色原样
│     ├─ 30_hair.png     灰度明暗图 + 透明，运行时乘以发色
│     └─ 90_line.png     白色描边（贴纸感），原样使用
└─ characters/           其他妈妈外观预设（设置界面里“换肤色”= 调整妈妈形象），每个一套自己的图和台词
   └─ white/
      ├─ poses/scold|peek|care/…   同上
      └─ lines/en.json              这个角色自己的英文台词；没有的语言用根目录 lines/ 里的
```

默认包有妈妈的四套外观预设：`east_asian`（华裔，用根目录的 poses/、lines/）、`white`、`black`、`south_asian`。
这些外观的图是从四张形象设定图自动拆出来的（`tools/art_pipeline/build_from_sheet.py`，见 DECISIONS D-33、D-37）。

## 3. 图层规则

- **文件名**：`两位数字_小写名称.png`。数字决定叠放顺序（小的在下）。名称对应 `persona.json` 里 `layers` 的键。
- **着色层**（`layers` 里写了 `"tint": "skin"` 或 `"tint": "hair"` 的）：画成**灰度**明暗图——亮部浅、阴影深。
  程序把每个像素的灰度乘以所选颜色（再乘以 `tint_adjust` 里这个姿势的倍数，见下），所以阴影会保留下来。不要涂成纯色。
- **其他层**原样使用，可以是彩色。
- 同一个姿势里的所有图层**尺寸必须一样**，透明背景，建议高 500–700px（程序会按屏幕高度缩放）。
- 层的顺序固定，所以“手在衣服前面”这种情况，要在衣服层把手的位置挖空，让下面的皮肤层露出来。
- 想加一层（比如 `50_glasses.png` 眼镜）：直接放进去即可；想让它跟着发色变，就在 `layers` 里写 `"glasses": {"tint": "hair"}`。
- `peek` 姿势的人物要贴着图片**右边缘**（场景里写 `"flush_right": true`，和屏幕右边缘对齐）。

## 4. persona.json 字段

| 字段 | 说明 |
|---|---|
| `schema` | 固定为 1 |
| `name` | 与文件夹同名 |
| `display_name` | `{"zh": "…", "en": "…"}`，设置界面角色卡上显示 |
| `traits` | 可选。`{"zh": ["亲切", …], "en": [...]}`，角色卡上的性格标签（最多 4 个） |
| `version` | 你自己的版本号，改了图记得加一，缓存会自动重建 |
| `default_language` | `zh` 或 `en` |
| `languages` | 提供了哪些台词文件，如 `["zh", "en"]` |
| `poses` | 姿势文件夹列表 |
| `scenes` | 场景 → `{"pose": 姿势, "bubble": "left"/"right"（气泡在人物哪边）, "figure_scale": 人物高度倍数（默认 1）, "fade_bottom": 0–0.5（下缘渐隐比例）, "flush_right": true/false（右缘贴屏幕边）, "bubble_top": 气泡离人物顶端的比例}` |
| `layers` | 图层名 → `{"tint": "skin"/"hair"}`，不写 tint 就原样使用 |
| `tint_adjust` | 可选。`{姿势: {"hair": [r, g, b]}}`：着色时每个通道再乘的倍数（0–8），让第一个发色预设 = 原画；手画灰度图的话不用写 |
| `characters` | 可选。角色 id → 见下表。不写的话，`colors.json` 里的每个肤色预设算一个角色（共用同一套图，只给皮肤层换色，和旧版一样） |
| `default_character` | 默认角色 id |
| `bubble` | 气泡样式，见下 |

`characters` 里每个角色：

| 键 | 说明 |
|---|---|
| `name` | `{"zh": "黑人妈妈", "en": "Black mom"}`，设置界面里显示 |
| `skin` | `#RRGGBB`，设置界面里的肤色色块（有皮肤着色层时也按它着色） |
| `dir` | 角色文件夹，如 `characters/black`；写空字符串 = 用角色包根目录的 poses/、lines/ |
| `display_name` / `traits` | 角色卡上的一句介绍、性格标签（最多 4 个） |
| `bubble_name` | 可选，气泡名牌上的称呼，如 `{"en": "Mama"}` |
| `tint_adjust` | 可选，同上，按这个角色的图算 |

`bubble` 里可以写（都可省略，省略就用默认的养成系配色）：

| 键 | 说明 |
|---|---|
| `fill_top` / `fill_bottom` | 气泡底色（上下渐变） |
| `border` / `stitch` | 粗描边颜色 / 内侧缝线颜色 |
| `ink` | 字色 |
| `tag_top` / `tag_bottom` / `tag_ink` | 名牌的渐变色和字色 |
| `name` | 名牌上的名字 `{"zh": "妈妈", "en": "Mom"}`，写空字符串就不画名牌 |
| `font` | `{"zh": "fonts/xxx.ttf", "en": {"file": "fonts/yyy.ttf", "weight": 800}}`，相对角色包文件夹；缺字时自动回退系统字体 |
| `emotes` | 场景（或台词键）→ 表情贴纸：`anger` 怒气符号 / `sweat` 汗滴 / `drop` 水滴 / `heart` 爱心，不写就不贴 |

必须有的三个场景：`unlock_scold`（A）、`side_peek`（B）、`overtime_care`（C）。

## 5. 台词

`lines/zh.json`：

```json
{
  "unlock_scold":   ["多大人了，水都不知道喝？一天天就知道折腾你那个电脑！"],
  "side_peek":      ["坐这多久了你，腰还要不要了！", "再坐下去要长根了！"],
  "side_peek_water":["杯子都空了多久了，接水去！"],
  "overtime_care":  ["今天又加班吗？要是来不及回家吃就点个外卖，辛苦一天别饿着自己"]
}
```

- 每个场景是一个数组，可以写多条：每次随机选一条，不会连续两次一样。
- `side_peek_water` 是 B 的饮水版（饮水账超得比久坐账多时用），不写就用 `side_peek` 的。
- 台词长度建议中文 40 字以内、英文 140 字符以内，气泡会自动断行。
- 选哪套：先找所选角色自己的 `characters/<id>/lines/<语言>.json`，没有就用根目录 `lines/<语言>.json`。
  默认包里中文只有一套（华裔妈妈），英文妈妈的四套外观预设各一套。
- 用户在设置界面里改过的台词存在 `config.toml` 的 `[custom_lines]`，优先于角色包里的台词；与角色、语言无关。

## 6. 颜色预设

`colors.json` 里 `hair` 8 个（多写只显示前 8 个），每个是 `{"name": {"zh": "…", "en": "…"}, "hex": "#RRGGBB"}`。
**第一个是默认色**：配合 `tint_adjust`，选它时立绘和原画一样。发色在设置界面里还能自由取色。
有 `characters` 时肤色由角色决定（换肤色 = 换一套图）；没有时 `skin` 列表里的每个颜色算一个角色。

## 7. 新增一个场景（需要一点代码）

1. 在 `core/policy.py` 里写一个 `Trigger` 子类，实现 `candidate(ctx)`（什么时候想出场），然后 `policy.register(...)`。
   单元测试 `tests/test_policy.py::test_new_trigger_registration` 是一个 10 行的例子。
2. 在每个台词文件里加一个同名的键；在 `persona.json` 的 `scenes` 里写这个场景用哪个姿势。

## 8. 缓存

立绘只在“保存设置”或哨兵发现缺图时渲染一次，结果放在 `persona/cache/`，**随时可以整个删掉**，会自动重建。
