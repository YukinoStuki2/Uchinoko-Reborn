# Uchinoko Reborn

基于 pandrabox 的 MIT 许可 Uchinoko，独立维护的本地修复版。原作者及第三方版权保留；本项目不是原作者发布的官方版本。

当前开发版本：`2.13.0-reborn.12`。本工具负责模型转换；PAM 继续负责模型库、梳妆台选择和工坊包生成。

尺寸匹配：新模型默认启用“匹配原版人物尺寸”，以原版骨架的头部到两脚踝平均高度为基准，对整个模型等比例拟合；帽子、耳朵、头发和尾巴不会拉高测量结果。原有身高百分比仍可微调。旧模型保留原设置，需要启用此项并完整转换才能应用。它不修改游戏角色碰撞胶囊或武器本体大小。自动 PhysBone 的骨链、半径和拟合重力随尺寸换算；原 Unity 的方向碰撞约束仍受转换器原有近似限制。详见 `repair/REBORN_12_SIZE_FIT.md`。

Reborn.11 修复 Unity 插件合并骨架后残留失效 Transform 引用的兼容问题。
读取“忽略其他 PhysBone”边界时，现在按 Unity 的对象存活规则解析根节点，
避免一个已删除的引用导致整份动骨参数无法导出；异常日志也保留原始调用位置。

本版在相同纹理尺寸、BC1/BC3 格式和 mip 数量下提高颜色贴图保真度：
适度缩小时保留更多可分辨细线，透明补色区域继续使用保守滤波；
压缩器按实际解码误差选择更好的端点；远距离 mip 在线性光照空间生成。
这些工作发生在转换时，不增加游戏内材质、着色器操作或纹理预算。
原始小贴图缺少的细节无法凭空恢复。已有模型需重新转换并重新生成工坊包。
说明见 [相同显存下的贴图质量](docs/TEXTURE_FIDELITY.md)。

新转换默认选择“自动（按 PhysBone）”：从 Unity 导出版本、积分方式和逐节曲线，
连续换算回弹、阻尼和移动惯性，并在可用骨骼容量内自动保留链节。
没有针对模型名称或头发、尾巴类别写入固定调参。旧任务恢复原设置；显式逐部件手调优先。
不同物理求解器仍有差异，碰撞器、分叉独立模拟等不能完整移植，诊断报告会说明近似和损失。
技术依据：[自动参数转换](docs/PHYSBONE_RESPONSE_MAPPING.md)。

新转换也默认使用环境光（阴影强度 100%、无贴图自发光）。旧任务若仍使用阴影强度 30%，
会保留原先的 70% 自发光补亮；需要正常受光时将阴影强度设为 100%，关闭“无阴影”，再转换或快速重打包。

长尾可在组件的动态参数窗口勾选“保留骨链节数（实验）”，然后重新转换。
它保留主链的各节关节，补足可用骨骼和无权重末端；不会增加独立物理组件数量。
手动预设下默认关闭；自动模式在容量允许时自动保留。当前适用于男女共用且带原生子链的物理槽；
库存不足或不支持的槽会在诊断中说明。分叉仍沿用代表主链，不能等同于完整复现 VRC PhysBone。

## 本次修复

- “输出目录…”可以设置版本无关的模型库，供 PAM 直接扫描；源码更新复用已有安装，不再复制一套 Python、Blender。
- 长曲骨链的姿态检查改用实际合并跨度；完整嵌套的子动态随父运行，避免尾尖独立固定在骨盆。独立子参数不在此兼容模式中生效。
- 完成提示显示部件、原因、男女受影响范围及最终检查，并生成 `converted/动态骨骼诊断报告.txt`，不再把同一源部件按男女重复计数。
- 分叉骨链使用真实根骨静止方向，避免侧发、头饰被错误的姿态检查剔除；旋转 Angle 转换为安全内接角范围。
- 动态详细设置增加逐部件幅度、阻尼、下垂力；参数会进入生成的物理蓝图，快速材质重打包也保留。
- 同一 Unity 工程已经打开时，复用当前 Editor 导出已保存的 prefab；首次需要切回 Unity 载入三个小脚本，不复制 Unity 或整个工程。
- FBX 只导入静态绑定数据，避免源动画反复覆盖已应用的缩放、旋转，修复带缩放动画的模型尺寸失真和顶点越界。
- 动态重试保持首次实际分配的范围，避免把没有对应物理骨骼的候选链重新纳入检查；正常链可保留。
- 全部动态被排除时清空对应映射，避免残留文件使后续骨架检查失败。
- 修复版有独立标题和版本；不向原作者的更新或报告服务发起默认请求。

没有放宽模型尺寸或物理姿态检查。超出原有容量、姿态不兼容或无法定位的动态链仍可能保持静态；本版不保证所有模型的全部物理效果都能移植。

详细用法：[动态调节](repair/PHYSBONE_MOTION.md)、[尾链兼容](repair/TAIL_CHAIN_COMPATIBILITY.md)、[诊断报告](repair/PHYSBONE_DIAGNOSTICS.md)、[动态保留与限制](repair/PHYSBONE_PRESERVATION.md)、[Unity 保持打开时导出](repair/UNITY_OPEN_PROJECT.md)。

## 使用

运行独立安装目录中的 `UchinokoReborn.bat`。选择模型后，沿用原有预览与转换流程；新模型建议保持“自动（按 PhysBone）”，也可选择旧的手动强度。

本地修复版默认关闭转换后自动安装到游戏。生成的 `*_PlayerSwap_P.pak` 可导入 PAM，再由 PAM 构建工坊模型包。

点击“输出目录…”设置固定模型库。转换、Unity 导出、已有模型列表与恢复设置都会使用该目录；PAM 的“设置 → 模型输出目录”可以读取同一目录。路径偏好保存到 `%APPDATA%/UchinokoReborn/settings_workroot.txt`，更新版本后继续有效。显式设置失效时会提示并停用转换，不会悄悄写入另一处。尚未设置的安装保留旧 `res/work` 行为。

更改输出目录只改变后续读写位置，不自动搬动旧文件。迁移时应保留模型工作目录和相关 `_export` 源导出目录；同名不同版本要单独保留。不要将旧版针对单个模型的临时逐链关闭配置直接套进新版。

启动器固定使用本目录的 Blender、Python 和插件目录，并隔离转换缓存。请通过 `UchinokoReborn.bat` 启动，避免绕过这些环境配置。

## 源码与版本来源

维护仓库：https://github.com/YukinoStuki2/Uchinoko-Reborn

上游官方仓库：https://github.com/pandrabox/Uchinoko

公开 `v2.13.0` 标签指向 `b342e5b21faff537c331f60257c7e77e55838b4a`，但该源码的 GUI 版本仍为 `v2.3.1`，缺少发行版后续功能。因此本地 Git 历史分别保存：

1. GitHub 官方仓库的真实提交历史；Git 直连不可用时通过 GitHub API 恢复并逐项校验原有 Git 对象与提交哈希。
2. MIT 许可 2.13.0 发行包内的 Python、PowerShell、Unity 源码补齐记录。
3. 修复版自身修改。

`provenance/release-source.json` 记录发行包原始补齐源码的逐文件哈希，公开源码调整另见 `provenance/PUBLIC_SOURCE_ADJUSTMENTS.md`。用户模型、游戏资产二进制、工作记录和个人设置不进入源码仓库。上游提交身份与哈希保留；发行源码补齐和本 fork 修复以维护者的新提交记录，不伪装为原作者提交。

## 本地构建

现阶段提供本地构建器，复用已有 Uchinoko 安装中的合法运行依赖，复制到新的独立目录：

```powershell
python repair/build_local.py --installed 'C:/Tools/Uchinoko_for_Palworld' --output 'C:/Tools/UchinokoReborn'
```

目标目录必须不存在，也不能位于原安装目录内。构建器复制 Python、Blender 和本机已有的运行模板；不会复制 `work`、日志和用户模型。构建结果包含 `repair_build.json`，用于核对源码哈希。

后续更新请关闭程序，复用同一个安装目录：

```powershell
python repair/build_local.py --update --output 'C:/Tools/UchinokoReborn'
```

更新只替换受管理的源码与说明，保留依赖、模型和设置。旧源码备份位于安装目录的 `repair/source_backups/`；发现本地手改源码会停止更新，写入失败会回滚。不要为了更新重复构建新的版本目录。

构建后可运行 `python repair/smoke_local.py 'C:/Tools/UchinokoReborn'`。该检查会自动使用目标目录的嵌入式 Python，验证 Tcl/Tk 初始化、目录隔离、源码哈希和默认设置。

这是本地开发安装方式，尚不是公开发布包。公开打包前仍需整理运行模板和第三方组件的可再分发来源、构建脚本及独立机器验证。主程序 MIT 许可证见 `LICENSE`；第三方声明见 `provenance/licenses/` 与 `THIRD_PARTY_NOTICES.md`。

## 验证

本版尾链、诊断与测试限制见 [repair/REBORN_3_VALIDATION.md](repair/REBORN_3_VALIDATION.md)。此前动态对照、PAM 导入、Unity 实机导出见 [repair/REBORN_2_VALIDATION.md](repair/REBORN_2_VALIDATION.md)，更早的转换验证见 `repair/VALIDATION.md`。

- `tests/repair/`：修复版针对性回归。
- `tests/repair/blender_fbx_animation.py`：Blender 真实 FBX 导入与场景重载测试。
- 原有相关 GUI、诊断和动态测试继续使用。
- 私有模型只在本机外部目录验证，不随本项目发布。

游戏内走跑、换装和动态效果仍需实机验证；转换成功和静态预览通过不能代替这些检查。
