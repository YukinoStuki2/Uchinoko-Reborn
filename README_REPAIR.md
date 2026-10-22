# Uchinoko Reborn

基于 pandrabox 的 MIT 许可 Uchinoko，独立维护的本地修复版。原作者及第三方版权保留；本项目不是原作者发布的官方版本。

当前开发版本：`2.13.0-reborn.1`。本工具负责模型转换；PAM 继续负责模型库、梳妆台选择和工坊包生成。

## 本次修复

- FBX 只导入静态绑定数据，避免源动画反复覆盖已应用的缩放、旋转，修复 rurune 的尺寸失真和顶点越界。
- 动态重试保持首次实际分配的范围，避免把没有对应物理骨骼的候选链重新纳入检查；正常链可保留。
- 全部动态被排除时清空对应映射，避免残留文件使后续骨架检查失败。
- 修复版有独立标题和版本；不向原作者的更新或报告服务发起默认请求。

没有放宽模型尺寸或物理姿态检查。超出原有容量、姿态不兼容或无法定位的动态链仍可能保持静态；本版不保证所有模型的全部物理效果都能移植。

## 使用

运行独立安装目录中的 `UchinokoReborn.bat`。选择模型后，沿用原有预览与转换流程；需要动态时选择“普通”等动态强度。

本地修复版默认关闭转换后自动安装到游戏。生成的 `*_PlayerSwap_P.pak` 可导入 PAM，再由 PAM 构建工坊模型包。

修复版使用自己的 `res/work`、设置和日志。旧 Uchinoko 的模型和设置不会自动搬入。不要将旧版针对 rurune 的临时逐链关闭配置直接套进新版；新版的通用回退修复需要按原始物理设置验证。

启动器固定使用本目录的 Blender、Python 和插件目录，并隔离转换缓存。请通过 `UchinokoReborn.bat` 启动，避免绕过这些环境配置。

## 源码与版本来源

维护仓库：https://github.com/YukinoStuki2/Uchinoko-Reborn

上游官方仓库：https://github.com/pandrabox/Uchinoko

公开 `v2.13.0` 标签指向 `b342e5b21faff537c331f60257c7e77e55838b4a`，但该源码的 GUI 版本仍为 `v2.3.1`，缺少发行版后续功能。因此本地 Git 历史分别保存：

1. GitHub 官方源码快照；Git 传输不可用时通过 GitHub API 下载同一提交的源码归档。
2. MIT 许可 2.13.0 发行包内的 Python、PowerShell、Unity 源码补齐记录。
3. 修复版自身修改。

`provenance/release-source.json` 记录补齐源码的逐文件哈希。用户模型、游戏资产二进制、工作记录和个人设置不进入源码仓库。下载归档不包含 Git 历史，因此本地提交不伪装为原作者提交。

## 本地构建

现阶段提供本地构建器，复用已有 Uchinoko 安装中的合法运行依赖，复制到新的独立目录：

```powershell
python repair/build_local.py --installed 'C:/Tools/Uchinoko_for_Palworld' --output 'C:/Tools/UchinokoReborn'
```

目标目录必须不存在，也不能位于原安装目录内。构建器复制 Python、Blender 和本机已有的运行模板；不会复制 `work`、日志和用户模型。构建结果包含 `repair_build.json`，用于核对源码哈希。

构建后可运行 `python repair/smoke_local.py 'C:/Tools/UchinokoReborn'`。该检查会自动使用目标目录的嵌入式 Python，验证 Tcl/Tk 初始化、目录隔离、源码哈希和默认设置。

这是本地开发安装方式，尚不是公开发布包。公开打包前仍需整理运行模板和第三方组件的可再分发来源、构建脚本及独立机器验证。主程序 MIT 许可证见 `LICENSE`；第三方声明见 `provenance/licenses/` 与 `THIRD_PARTY_NOTICES.md`。

## 验证

已完成的本机验证结果见 `repair/VALIDATION.md`：rurune 普通动态完整转换、最终 PAK 检查与 PAM 导入均通过。

- `tests/repair/`：修复版针对性回归。
- `tests/repair/blender_fbx_animation.py`：Blender 真实 FBX 导入与场景重载测试。
- 原有相关 GUI、诊断和动态测试继续使用。
- 私有模型只在本机外部目录验证，不随本项目发布。

游戏内走跑、换装和动态效果仍需实机验证；转换成功和静态预览通过不能代替这些检查。
