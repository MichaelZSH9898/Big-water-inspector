# 大水理论最严厉的母亲 · MVP 实施计划

> 本文件是开工第一步的产物：模块拆分、依赖选型、主要风险、里程碑执行方式。
> 细节决定（含理由与备选方案）记录在 `DECISIONS.md`。

## 1. 总体思路

- **哨兵进程只用标准库 + ctypes**。不引入 pywin32、pystray、Pillow、comtypes 到常驻进程：
  它们各自会带来 5–15 MB 的常驻内存，而 Python 3.11 本体就要 ~10 MB，40 MB 预算经不起叠加。
- **图像在设置进程里预渲染**（Pillow），哨兵运行时只读取预乘 alpha 的原始 BGRA 缓存（zlib 压缩），
  用 `CreateDIBSection` + `UpdateLayeredWindow` 直接贴图——哨兵里没有任何图像解码库。
- **单线程、事件驱动**：一个隐藏的顶层窗口 + `GetMessageW` 消息循环。没有消息时线程阻塞在内核里，CPU 为 0。
  所有定时都用 `SetTimer`，下一次唤醒时间由逻辑内核自己算（自适应采样）。
- **逻辑内核与 Windows 完全解耦**：`core/` 不 import 任何 Windows 模块，时钟和信号全部注入。
  同一套内核既跑在真实哨兵里，也跑在模拟器和单元测试里（Linux 上也能跑）。

## 2. 模块拆分

```
water-inspector/
├─ main.py                  入口：单实例、DPI 感知、消息循环、把内核的“下次唤醒时间”映射到 SetTimer
├─ config.toml              全部可调参数（带中文注释）
├─ signals/                 每个信号一个文件；统一接口；Windows 实现 + 假数据实现（signals/fake.py）
│  ├─ base.py               接口定义（Protocol）
│  ├─ idle.py               GetLastInputInfo（32 位 tick 回绕处理）
│  ├─ foreground.py         SetWinEventHook(EVENT_SYSTEM_FOREGROUND) + 进程名/标题 → 类别（标题用完即弃）
│  ├─ notify_state.py       SHQueryUserNotificationState + 前台铺满显示器 + 勿扰/专注检测
│  ├─ mic_cam.py            CapabilityAccessManager 注册表（含 NonPackaged，含 LastUsedTimeStop 时间戳）
│  ├─ session.py            WTSRegisterSessionNotification + WM_POWERBROADCAST（事件翻译）
│  └─ audio.py              WASAPI 端点 IAudioMeterInformation（纯 ctypes COM，不用 comtypes/pycaw）
├─ core/
│  ├─ clock.py              可注入时钟（RealClock / FakeClock），统一提供“本地日”（04:00 换日）
│  ├─ config.py             读取 config.toml（tomllib）、默认值、演示模式 ×1/60 缩放
│  ├─ effective_time.py     分钟级有效时长：输入分钟、音频/全屏补判、5 分钟回溯、锁屏不计
│  ├─ ledger.py             饮水账、久坐账：累加、离开削减表、响应清零
│  ├─ history.py            最近 10 分钟的输入分钟、前台切换记录、断点信号
│  ├─ classifier.py         状态识别：会议 / 全屏 / 勿扰 / 心流 / 游离 / 断点 / 普通
│  ├─ policy.py             场景触发器注册表（A/B/C）、全局约束（间隔、频率、静默、暂停）
│  ├─ engine.py             编排：接收事件与定时唤醒，驱动以上模块，输出闪现请求与日志
│  ├─ eventlog.py           logs/events.jsonl、每日摘要、按天轮转、30 天/20 MB 上限
│  └─ state_file.py         每分钟写 state.json（原子替换），供每日一题以后读取
├─ overlay/
│  ├─ layered_window.py     WS_EX_LAYERED|TRANSPARENT|TOPMOST|TOOLWINDOW|NOACTIVATE，SW_SHOWNOACTIVATE
│  └─ image_cache.py        读取 persona/cache 里的 .pbgra（预乘 BGRA）；按显示器尺寸挑选
├─ winapi/                  ctypes 声明与小工具（哨兵、设置进程共用）
│  ├─ user32.py …           函数原型（显式 argtypes/restype，避免 64 位句柄截断）
│  ├─ msgwindow.py          隐藏顶层窗口 + WndProc 分发
│  ├─ tray.py               Shell_NotifyIconW 托盘、右键菜单（含“今日统计”子菜单）
│  ├─ monitors.py           显示器枚举、工作区、每显示器 DPI
│  └─ autostart.py          HKCU\…\Run 开机自启开关
├─ persona/
│  ├─ README.md             如何做你自己的角色包（不需要读主程序）
│  ├─ loader.py             校验 persona.json / 台词 / 图层；损坏时给可读报错并回退默认包
│  ├─ render.py             Pillow 叠图、灰度明暗图 × 颜色着色、养成系对话框气泡、输出缓存
│  ├─ lines.py              台词随机选取、不连续重复
│  ├─ default_mom/          默认角色包（占位立绘，图层结构完全符合规范）
│  └─ cache/                渲染结果，可随时删除重建
├─ settings_ui/             设置界面（独立进程，关闭即退出）：ui_render.py 用 Pillow 画养成系界面，app.py 用 tkinter 贴图、处理点击
├─ sim/                     模拟器：脚本化的一天（文本 DSL）→ 驱动同一个 engine
├─ tools/                   Windows 实测脚本（API 探针、闪现验收、资源测量）；art_pipeline/ 从角色设定图生成立绘、生成托盘图标
├─ assets/tray/             5 档水位小水杯图标（.ico，多尺寸）
├─ logs/  tests/
└─ README.md  PLAN.md  DECISIONS.md
```

与需求文档目录的差异：新增 `core/engine.py`、`core/history.py`、`core/config.py`、`core/eventlog.py`、
`core/state_file.py`、`winapi/`、`tools/`、`assets/`。原因见 DECISIONS.md D-01。

### 数据流（与需求一致）

```
signals ──事件/采样──▶ effective_time / ledger ──▶ classifier ──▶ policy ──▶ overlay
                              │                                        │
                              └──────────── eventlog (events.jsonl) ◀──┘
persona (预渲染缓存) ──▶ overlay
```

## 3. 依赖选型

| 用途 | 选择 | 进程 | 理由 |
|---|---|---|---|
| Win32 调用 | ctypes（标准库） | 哨兵/设置 | 零安装、内存最小；所有原型显式声明 |
| 托盘 | Win32 原生 Shell_NotifyIconW | 哨兵 | pystray 会把 Pillow 拉进常驻进程 |
| 配置读取 | tomllib（3.11 标准库） | 全部 | 零依赖 |
| 音频峰值 | ctypes 手写 COM vtable 调用 | 哨兵 | comtypes 导入就要 10 MB 以上 |
| 图像渲染 | Pillow | 仅设置进程/渲染子进程 | 叠图、着色、字体排版 |
| 设置界面 | tkinter | 仅设置进程 | 标准库，随 Python 安装 |
| 测试 | unittest（标准库） | — | 你电脑上不用装 pytest 也能跑；pytest 也兼容 |
| 资源实测 | psutil | 仅测量脚本 | 文档指定 |

运行时安装需求：`pip install pillow`（设置/渲染用），`pip install psutil`（只有测量脚本用）。

## 4. 主要风险与对策

| # | 风险 | 对策 |
|---|---|---|
| R1 | 40 MB 常驻内存 | 哨兵零第三方库；图像只在闪现的 2 秒内存在，结束后释放 DIB 与字节缓冲；M5 用 psutil 实测 |
| R2 | 勿扰/专注模式没有公开 API，各 Windows 版本行为不同 | 同时读 SHQueryUserNotificationState、WNF 专注助手状态、Win11 通知总开关注册表；写探针脚本实测，结论进 DECISIONS |
| R3 | ctypes 回调里的异常、慢回调 | 只挂 EVENT_SYSTEM_FOREGROUND（低频）；不挂低级键鼠钩子；所有回调 try/except 并写 app.log |
| R4 | 分层窗口抢焦点/挡点击 | 五个扩展样式 + SW_SHOWNOACTIVATE + 窗口过程直接用 DefWindowProcW；验收脚本用 SendInput 自动打字/点击核对 |
| R5 | GetWindowTextW 在目标程序卡死时会阻塞 | 沿用每日一题的经验：用 InternalGetWindowText（只读缓存，不发消息） |
| R6 | 麦克风注册表出现“永远在用”的残留项 | 同时看 LastUsedTimeStart，超过 12 小时仍未停止视为残留（可配置） |
| R7 | 多显示器 / 125%、150% 缩放 | 进程声明 Per-Monitor V2；按前台窗口所在显示器的物理像素和 DPI 选择预渲染尺寸 |
| R8 | 我无法直接在你的 Windows 上跑命令 | 纯逻辑在云端测透；Windows 相关做成 `tools/` 一键验证脚本，产出 JSON 报告供核对 |
| R9 | 需求文档中“5 分钟回溯”与“其余算离开”存在两种读法 | 采用“短暂停顿先计入，满 5 分钟回溯剔除”，并做成配置开关（DECISIONS D-10） |

## 5. 里程碑执行方式

| 里程碑 | 内容 | 在哪验证 |
|---|---|---|
| M1 | signals（含假实现）、clock、effective_time、ledger、eventlog、state_file、模拟器 | 云端：unittest + 模拟器回放一天 |
| M2 | overlay、tray、图标、monitors/DPI | Windows：`tools/accept_overlay.py`（自动打字/点击验收）+ 多显示器信息报告 |
| M3 | history、classifier、policy、engine、三个场景、演示模式 | 云端：手工测试清单逐条写成模拟器脚本；Windows：演示模式实跑 |
| M4 | persona 加载/校验/回退、渲染、占位立绘、设置界面、重载通知 | 云端：渲染与回退测试；Windows：设置界面实跑 |
| M5 | 资源实测、README | Windows：`tools/measure.py` 空闲 1 小时、办公 1 小时各一组 |

每个里程碑结束：跑测试 → 汇报 5 行以内（结果 + 下一步）。
