# 2.13.0-pam.1 本机验证记录

日期：2026-10-22。验证对象为更名前的独立本地安装（下文以 `<installation>` 代称），未安装到游戏、未上传。

## 已验证

1. 相关修复、GUI、诊断与服务边界测试：105 项通过。
2. 真实 Blender FBX 回归：自行生成包含对象缩放动画的双骨骼模型。原版基线 `7bd7130` 保存、重开后，预期 0.5 m 的骨距变为 0.00005 m；修复后第 1、5、10 帧均约 0.50000006 m，无残留动作和缩放。
3. 独立安装烟测：293 份源码哈希一致；使用本目录嵌入式 Python，Tcl/Tk 8.6.12 实际初始化通过；Blender、插件、缓存目录隔离；默认关闭自动安装和原作者在线报告服务。
4. rurune：从原始导出 FBX 运行独立安装版完整 `convert.ps1`，普通动态开启，未使用模型专用覆盖，`preflight_nonblocking=false`。转换耗时约 211 秒，男、女两套均通过骨架结构检查、35 根动态骨骼检查和 6 条动态链支点检查。
5. 最终 PAK 的 17 项内置检查全部通过，包括 G15；另以真实解析器复核全部 58 份服装模型资产、顶点和索引边界，58/58 通过。
6. 使用 PAM 1.0.25 真实导入器导入隔离验证库成功：男女资源、12 个包、24 个资源文件、独立骨架和 Uchinoko 正面头像均识别正常。实际模型库未改动。

## 结果与证据

- 可运行入口：`<installation>/UchinokoRepair.bat`（更名前入口；新构建为 `UchinokoReborn.bat`）
- rurune 输出：`<installation>/res/work/rurune_repair/build/rurune_PlayerSwap_P.pak`
- PAK 大小：1,133,764,709 字节。
- PAK SHA256：`8acff262e2caad790ac904622568231cc744e90a350f353802d029fe4ae07e73`
- 过程日志：上述任务目录的 `conversion.log`；汇总及资产结果：`asset_validation.json`。
- 自动生成的 FBX 对照证据位于源码目录 `.local/validation/fbx-baseline-dimensions*` 和 `fbx-repair-dimensions*`。
- 私有模型与生成产物不纳入源码仓库。

## 可重复检查

```powershell
python -m pytest tests/repair/test_sway_degrade_retry.py tests/repair/test_fork_ui_services.py app_py/tests/test_support_dialog_ended_dev1641.py app_py/tests/test_inquiry.py app_py/tests/test_diagnostics.py app_py/tests/test_main_window_diagnostics_wiring.py -q
python repair/smoke_local.py 'C:/Tools/UchinokoReborn'
```

Blender 小型回归用法见 `tests/repair/blender_fbx_animation.py`。指定 `--baseline 7bd7130` 可验证原版确实失败。

## 未覆盖与限制

未进行游戏内走跑、换装、战斗和多人环境测试；PAM 的运行验证状态保持“待游戏验证”。此次从已导出的 FBX 开始，没有重新调用 Unity 导出 prefab。没有验证所有模型或 VRM 插件的首次安装。

rurune 两套骨架各保留 6 条有效动态链；容量溢出或姿态不兼容部分仍按原有规则降级为静态，并记录于 `sway_exclusions_*.json`。没有放宽姿态、模型大小或最终 PAK 检查。完整转换产物及此处计数不代表所有源 PhysBone 都可移植。

本地构建器依赖现有安装提供运行时；此版本尚未完成独立公开发行包与异机验证。
