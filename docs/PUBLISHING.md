# 发布准备

## 本地成品

在项目目录运行 `python -m tools.build_release`，可生成：

- `release/Big-water-inspector-0.1.0-preview-source.zip`：用于上传仓库的源码，按明确的文件清单打包，排除个人日志、状态、旧素材和构建缓存。
- `release/Big-water-inspector-0.1.0-preview-Windows-x64.zip`：Windows 便携包，无需安装 Python。
- `release/SHA256SUMS.txt`：校验和。

附件文件名用英文：GitHub 会删掉 Release 附件名里的中文字符（例如“源码”会消失），中文名会让下载链接和校验和对不上。
压缩包里的文件夹、程序和启动脚本仍是中文名，不受影响。

构建工具使用 PyInstaller；先在 Windows 安装 `pyinstaller` 和项目依赖。便携包保留 Python、Pillow、PyInstaller 及字体许可证。
安装和构建工具是维护者操作，普通用户无需执行。

## GitHub 页面

1. 将源码压缩包解压后的**内容**放到仓库根目录，确保最外层直接能看到 README.md。
2. About 描述建议：**大水理论最严厉的母亲：把妈妈请进电脑，催你喝水、起身。妈妈的形象、发色和台词由你自定义。**
3. Topics 建议：`windows`、`desktop-app`、`reminder`、`hydration`、`python`、`desktop-companion`。
4. Settings → Social preview：上传 `docs/media/social-preview.jpg`，尺寸 1280 × 640，文件小于 1 MB。
5. 创建预发布版本 `v0.1.0-preview`，上传 Windows ZIP 与 `SHA256SUMS.txt`，标记为 pre-release。
6. 发布说明使用下文。发布后，可将 README 的下载入口直接链接到这个 Release。

当前 README 的下载入口指向仓库内的说明页，尚无仓库地址时也不会产生虚假的下载链接。
仓库源文件和 Release 附件分开上传，避免将整个打包目录加入 Git 历史。

## 发布说明

大水理论最严厉的母亲的第一个 Windows x64 试用版。

妈妈会从桌面边缘探头，提醒你喝水、起身，也会在长时间工作后送来一句关心。你可以自定义妈妈的形象、肤色、发色和台词，界面与台词支持中英文。

下载 `Big-water-inspector-0.1.0-preview-Windows-x64.zip`，完整解压后双击 `1-先看演示.cmd`。无需安装 Python。

这是未签名的试用版。请核对附件校验和。测试范围与未覆盖项目见 `docs/VALIDATION.md`。
展示中的桌面为绘制的示意场景，并非实机录屏。

欢迎反馈首次使用体验，或提交一句你想听到的提醒。

## 发布后观察

先观察真实使用反馈：用户是否能理解项目、顺利启动、找到自定义台词和退出方式。
GitHub Traffic 的访问和克隆可以帮助判断传播来源；它们不等于安装数或持续使用人数。

参考：[GitHub 分享预览说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview)、[Topics 说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics)、[Traffic 说明](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/viewing-traffic-to-a-repository)。

## 名称与发布状态

对外项目名统一为「大水理论最严厉的母亲」。GitHub 仓库地址为 `MichaelZSH9898/Big-water-inspector`；
早先的拼音地址 `da-shui-li-lun-zui-yan-li-de-mu-qin` 已改名，GitHub 会自动跳转。

`v0.1.0-preview` 已作为预发布（Pre-release）发布，附件为 Windows x64 便携包、源码压缩包和 `SHA256SUMS.txt`：
[发布页](https://github.com/MichaelZSH9898/Big-water-inspector/releases/tag/v0.1.0-preview)。
旧版文件在本地 `release/旧版-请勿发布/`，不要上传。
