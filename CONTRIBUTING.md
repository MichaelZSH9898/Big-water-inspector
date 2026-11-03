# 一起添一句熟悉的唠叨

欢迎使用反馈、台词建议、翻译、测试和新的妈妈形象预设。

## 不写代码也能参与

- 提交一句提醒，并注明适合喝水、久坐、解锁还是加班场景。
- 描述第一次使用时哪里不清楚、哪里打扰了你。
- 分享自己有权使用的妈妈形象作品，附上作者与授权说明。

请避免发布你或他人的桌面截图、个人日志内容；复现问题可以使用虚构文字和演示素材。
台词尽量短、清楚，中文建议 40 字以内；默认显示时间较短。

## 报告问题

说明 Windows 版本、显示器分辨率与缩放、源码版或便携包版本，以及复现步骤。
如需附日志，先检查并删除路径、用户名和自定义台词等不想公开的信息。

## 修改代码或妈妈形象包

开发入口见 [使用说明](docs/USER_GUIDE.md#目录结构)，角色包格式见 [角色包说明](persona/README.md)。

```bash
python -m unittest discover -s tests
python -m sim.run sim/scripts/*.sim
python -m sim.run sim/scripts/*.sim --demo
```

请描述改动解决的问题及验证结果。不要把 `logs/`、`state.json`、`data/`、本机渲染缓存或打包目录加入提交。
不要求为了贡献而制作真实桌面截图。

代码贡献采用项目 MIT 授权；图片与字体必须单独说明来源及许可。

## English

You can contribute reminder lines, translations, bug reports, tests or original appearance packs for Mom. Include artwork attribution and permission. Use fictional data in examples; do not post personal desktop captures or unreviewed logs.

For bugs, include Windows version, display scale, app version, reproduction steps and expected behavior. Run the core tests and simulator commands above for code changes.
