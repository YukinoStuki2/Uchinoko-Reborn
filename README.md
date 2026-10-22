# Uchinoko Reborn

Uchinoko Reborn 是面向 Palworld（幻兽帕鲁）的独立社区维护版模型转换工具，基于 [pandrabox/Uchinoko](https://github.com/pandrabox/Uchinoko) 的 MIT 许可源码及其 2.13.0 发行包内源码继续开发。本项目不是原作者发布的官方版本，也不代表原作者提供支持。

源码与问题反馈：[YukinoStuki2/Uchinoko-Reborn](https://github.com/YukinoStuki2/Uchinoko-Reborn)。

当前开发版本：**2.13.0-reborn.1**。模型兼容性判定仍沿用 `TOOL_VERSION = v2.13.0`；界面显示独立的 Reborn 版本。

## 当前修复

- FBX 导入仅读取静态绑定数据，避免源动画覆盖应用后的缩放和旋转，修复 rurune 的尺寸失真及顶点越界。
- 动态重试保留初次实际分配范围，避免把没有对应物理骨骼的候选链重新纳入检查。
- 所有动态被排除时清理对应映射，避免残留数据导致后续骨架验证失败。
- 独立名称、启动器、运行目录与缓存；默认关闭自动安装到游戏及原作者的在线更新、报告服务。

转换中的大小、骨架、姿态和 PAK 检查仍保留。容量溢出或姿态不兼容的动态链可能降级为静态；转换成功不代表所有模型的每一项物理效果都能移植。

## 与 Pal Avatar Manager 的分工

Uchinoko Reborn 负责将已有授权的模型转换为 Palworld 模型资源。[**Pal Avatar Manager（PAM）**](https://github.com/YukinoStuki2/PalAvatarManager) 负责模型库、多个模型包共存、游戏内梳妆台切换和工坊上传工程生成。两者分别维护，Reborn 的源代码包不包含 PAM、玩家模型或私人转换产物。

在 Reborn 中转换得到 `*_PlayerSwap_P.pak` 后，可导入 PAM，再由 PAM 生成工坊模型包。发布模型前需要确认该模型自身的分发许可；本工具的 MIT 许可不会改变模型许可。

## 从源码构建本地开发安装

当前提供的是源码和本地构建器，**尚未提供经过独立机器验证的完整 Reborn 发行包**。构建器需要 Windows、Python 3.11+，以及一份合法取得的完整 Uchinoko 2.13.0 安装，用其中的 Blender、嵌入式 Python 和运行模板生成新的独立目录。

下面的路径只是示例，请替换为自己的目录：

```powershell
python repair/build_local.py --installed 'C:/Tools/Uchinoko_for_Palworld' --output 'C:/Tools/UchinokoReborn'
python repair/smoke_local.py 'C:/Tools/UchinokoReborn'
```

目标目录必须不存在，且不能与原安装目录互相包含。构建器不复制模型、工作目录、日志或个人设置。完成后通过 `UchinokoReborn.bat` 启动，保持 Python、Blender、插件及缓存环境隔离。

当前维护入口是 **Python/Tk 的 `app_py/main.py`**，本地构建入口是 `repair/build_local.py`。`app/` 中的 C# 程序和部分旧打包文档属于保留的历史源码，不是本版维护入口。原始上游说明保存在 [README.upstream.md](README.upstream.md) 和 [README.en.md](README.en.md)，其中下载地址、维护联系和发行流程仅用于了解上游，不能作为本 fork 的发布说明。

## 验证与贡献

```powershell
python -m pip install "pytest==9.0.3" "numpy==1.26.4"
python -m pytest tests/repair -q
python -m pytest app_py/tests -q
```

`tests/repair/test_sway_rurune_integration.py` 需要另行提供私有模型和 Blender 测试数据，默认跳过，不随源码分发。真实 FBX 回归入口见 `tests/repair/blender_fbx_animation.py`。已有本机验证、覆盖范围和限制见 [repair/VALIDATION.md](repair/VALIDATION.md)；本轮发布源码检查见 [repair/REBORN_SOURCE_VALIDATION.md](repair/REBORN_SOURCE_VALIDATION.md)。游戏内动画、换装和多人兼容性需要另外进行实机验证。

提交问题时请在 [本 fork 的 Issues](https://github.com/YukinoStuki2/Uchinoko-Reborn/issues) 中说明版本、输入格式、复现步骤和已脱敏日志。请勿向原作者的支持渠道提交本 fork 的专属问题，不要提交私人模型、账号信息或游戏资源。

## 来源与许可

原作者版权及 [MIT 许可证](LICENSE) 保留。上游公开 `v2.13.0` 标签对应 `b342e5b21faff537c331f60257c7e77e55838b4a`；公开源码与发行版后续源码有差异，补齐的发行源码及逐文件哈希记录在 [provenance/release-source.json](provenance/release-source.json)。本地修复提交没有伪装为上游作者提交。

第三方组件保留各自许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、[provenance/licenses/](provenance/licenses/) 和 [third_party/SOURCES.md](third_party/SOURCES.md)。完整运行包中的 Blender、pyooz 等组件不能统一视为 MIT；公开二进制发行前还需要完成依赖来源、再分发材料和构建流程核验。
