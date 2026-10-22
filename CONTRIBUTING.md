# Contributing to Uchinoko Reborn

Uchinoko Reborn 由本 fork 的维护者继续开发，基于 pandrabox 的 MIT 许可 Uchinoko。原作者及第三方版权保留；原作者不负责本 fork 的问题处理。

## 问题与贡献

- 在 [本仓库 Issues](https://github.com/YukinoStuki2/Uchinoko-Reborn/issues) 搜索已有问题；报告时说明 Reborn 版本、输入格式、复现步骤和已脱敏日志。
- Reborn 已关闭原作者的在线报告服务，应用内原有 Contact／問合せ入口不能作为本 fork 的报告渠道。Issues 是公开的，不要提交私人模型、账号信息、未脱敏日志或其他敏感材料。
- 较大的功能或行为变更建议先开 Issue 讨论。当前转换流程仍沿用上游的 VRM 0.0、VRM 1.0 和 Modular Avatar prefab 输入支持；其他 NDMF 插件不在既有兼容范围内。转换成功不能代替游戏内验证。
- 开发入口、依赖和限制以 [README.md](README.md) 为准。当前维护 Python/Tk 的 `app_py/main.py`，使用 `repair/build_local.py` 从合法的 Uchinoko 2.13.0 安装生成独立本地开发安装；`BUILD.md` 保留的是上游历史打包说明。
- 请随修改运行相关测试。公开回归入口为 `python -m pytest tests/repair -q` 和 `python -m pytest app_py/tests -q`；依赖版本、私有整合测试限制及已知耗时测试问题见 README 和 [发布源码检查](repair/REBORN_SOURCE_VALIDATION.md)。如有跳过或失败，请如实说明。
- 不要提交游戏资源、玩家模型、个人配置、运行日志或安装运行时。对需私有模型的复现，尽量提供可公开的最小合成测试。
- 提交自有代码即同意按本仓库 [MIT 许可证](LICENSE) 授权；保留原有版权和第三方许可。涉及独立 GPL 工作进程或其他第三方组件时，遵守其各自许可，不能统一改为 MIT。

参与讨论请遵守 [行为准则](CODE_OF_CONDUCT.md)。

## English

Uchinoko Reborn is maintained by this fork's maintainers and builds on pandrabox's MIT-licensed Uchinoko. Retain upstream attribution and third-party notices; upstream does not provide support for this fork.

Report reproducible problems in [this fork's Issues](https://github.com/YukinoStuki2/Uchinoko-Reborn/issues), including the Reborn version, input format, steps and sanitized logs. The upstream online report service is disabled. GitHub Issues are public: do not post private models, credentials or sensitive reports.

Use [README.md](README.md) for the maintained Python/Tk entry point and local build process (`repair/build_local.py`). `BUILD.md` is historical upstream packaging documentation. Discuss substantial changes first, run relevant public tests, and state failures, skips and validation limits. Private avatar integrations are opt-in; they are not part of the public source test data.

Contributions to the project's own code are licensed under MIT. Preserve attribution and each third-party component's license, including the separate GPL worker. Do not commit game assets, private models, personal configuration, logs or installed runtimes. Follow the [Code of Conduct](CODE_OF_CONDUCT.md).
