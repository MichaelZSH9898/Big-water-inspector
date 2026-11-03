# 验证范围 · 2026-11-03

## 本次检查

| 项目 | 结果与边界 |
|---|---|
| 单元测试 | 137 项通过，包含原有规则、角色与配置测试，以及便携版子进程分发、自启命令回归检查 |
| 脚本模拟 | 正常模式 10 个脚本通过；演示模式 9 个脚本通过，跨天脚本按原有标记跳过 |
| Windows x64 打包 | Python 3.11.2、PyInstaller 6.21.0、Pillow 12.2.0；无需外部 Python 的目录式便携包 |
| 便携包离屏检查 | 成功加载四套妈妈外观预设并渲染十二个场景；导入设置界面与 Windows 绑定，不打开原生窗口 |
| 展示素材 | 绘制的虚构桌面；妈妈形象与气泡使用原生渲染函数，位置使用原生计算函数；没有读取真实桌面 |
| 页面排版 | 无窗口浏览器检查 1440 px 桌面与 390 px 手机宽度，无横向溢出，图片正常加载；这是本地 Markdown 预览，GitHub 上线后仍需检查实际渲染 |
| 发布压缩包 | 源码与 Windows ZIP 完整性通过，未包含个人日志和运行状态；含中文与空格路径下的解压版自检与渲染子进程通过 |
| 页面链接 | 本次检查 36 个本地文件链接，无缺失；新增文档后可用验证脚本再次检查 |

离屏检查与导入检查不能替代完整实机验收。未在本次操作中运行桌面闪现、切换勿扰或会议、抢焦点验收、多显示器巡检及一小时便携包资源实测。

## 已有测量

项目原有报告记录了 2026-11-02 的 Windows 11 / Python 源码版测试：

- 一小时空闲测试：RSS 峰值 30.46 MB、平均 23.03 MB；16 核总口径平均 CPU 0.0005%。
- 提醒期间测试记录显示 102/102 个输入字符一致、焦点保持、鼠标穿透。
- 原有单机为 2880 × 1800、200% 缩放；125% / 150% 和多显示器未做实机验证。

这些是项目附带的既有记录，本次没有独立重跑。便携包包含运行时，其资源表现不能直接套用源码版结果。
更完整的历史测试环境与限制见 [DECISIONS.md](../DECISIONS.md)。

## 如何复核

```bash
python -m unittest discover -s tests
python -m sim.run sim/scripts/*.sim --quiet
python -m sim.run sim/scripts/*.sim --quiet --demo
python -m tools.build_release
python -m tools.verify_release
```

`verify_release` 检查压缩包、页面本地链接、素材尺寸，并在包含中文和空格的路径下运行解压后的便携包自检与渲染子进程。
生成的检查记录位于本地 `outputs/verification/`，不随源码发布。

## English

137 unit tests passed. All 10 normal-mode simulation scripts passed; 9 demo-mode scripts passed and the cross-day script was intentionally skipped. The portable executable was checked offscreen with four appearance presets for Mom and twelve rendered scenes, without creating native windows.

The illustrated desktop is synthetic. Current checks do not validate live overlay focus/click-through, meeting and DND detection, actual multi-monitor/DPI behavior, or long-running portable-build resource use. The historical source-build measurements above are not guarantees for the portable executable.
