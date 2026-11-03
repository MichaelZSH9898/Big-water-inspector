# 下载与开始使用

## Windows 免安装试用包

[下载 Windows x64 试用包](https://github.com/MichaelZSH9898/Big-water-inspector/releases/download/v0.1.0-preview/Big-water-inspector-0.1.0-preview-Windows-x64.zip) · [发布页与校验和](https://github.com/MichaelZSH9898/Big-water-inspector/releases/tag/v0.1.0-preview)

在 GitHub 仓库页面右侧的 **Releases** 中，选择最新试用版本，下载名字以 **`Windows-x64.zip`** 结尾的附件。
请下载发布者提供的 Windows 包；GitHub 自动生成的 “Source code” 是源码，需要另行安装 Python。

如果仓库还没有 Release，表示维护者尚未上传试用包，请使用下面的源码运行方式。

1. 将 ZIP **完整解压**到有写入权限的文件夹，保留其中全部文件。
2. 双击 `1-先看演示.cmd`：启动并主动预览三个场景，随后进入正常提醒。
3. 双击 `2-打开设置.cmd`：调整妈妈形象、发色、语言，点击预览里的气泡修改台词。
4. 以后直接运行 `大水理论最严厉的母亲.exe` 即可；托盘里出现粉色小水杯表示已启动。
5. 托盘右键可暂停、设置、开关自启或退出；也可以用 `3-退出程序.cmd` 退出。

当前提供 Windows x64 未签名试用包。首次打开若遇到系统来源提示，请先核对发布来源与附件的 `SHA256SUMS.txt`，不要关闭系统保护。
开机自启默认不开启，只有你主动选择后才会设置。

## 从源码运行

需要 Windows 和 Python 3.11+（包含 tkinter）。将源码解压后，在项目目录执行：

```bash
python -m pip install -r requirements.txt
python main.py --try
```

`--try` 只主动演示三个场景，随后按正常阈值运行；`--demo` 才会把等待阈值缩短。

也可以双击 `启动督察员.bat`。打开设置：

```bash
python -m settings_ui.app
```

## 常见问题

- **找不到窗口？**正常运行时只有托盘图标，可能位于任务栏的隐藏图标区。
- **演示没有出现？**确认已完整解压，查看 `logs/app.log` 或 `logs/launcher-error.log`；正常提醒可能被会议、全屏或勿扰挡住。
- **台词来不及读？**在 `config.toml` 对应场景下调大 `show_s`，例如改为 `4.0`。
- **卸载？**先取消开机自启并退出，再删除解压文件夹。

[完整说明](USER_GUIDE.md) · [验证范围](VALIDATION.md)

## English

On the GitHub repository page, open **Releases** and download the attachment ending in **`Windows-x64.zip`**. GitHub's automatically generated “Source code” archives require Python. If there is no release yet, use the source instructions below.

Extract the whole portable ZIP into a writable folder. Keep all files together. Open the numbered launchers:

1. `1-先看演示.cmd`: start the app, preview three scenes, then run normally.
2. `2-打开设置.cmd`: open settings; choose English there.
3. `3-退出程序.cmd`: quit the reminder process.

For later starts, open `大水理论最严厉的母亲.exe`. The pink cup is in the system tray, possibly under hidden icons. Startup with Windows is off until you enable it.

This is an unsigned Windows x64 preview. Verify the publisher and release checksum if Windows asks about the download. Do not disable system protection.

From source: install Python 3.11+ with tkinter, run `python -m pip install -r requirements.txt`, then `python main.py --try`. Open settings with `python -m settings_ui.app`.
