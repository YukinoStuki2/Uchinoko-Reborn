# Reborn 发布源码检查

日期：2026-10-22。版本：`2.13.0-reborn.1`。

本轮从既有本地修复版的 Git tracked tree 创建独立源码准备目录，不包括 `.git`、用户模型、安装运行时、转换缓存或未追踪的本机调查笔记。上游 README 原文保存在 `README.upstream.md`，许可证原文未修改。

产品变更仅涉及展示名称、启动器、本地构建元数据、项目说明和 fork 的审查/联系配置；转换管线未修改。`TOOL_VERSION` 仍是 `v2.13.0`，供既有兼容性逻辑使用。此外补充公开合成测试数据，修复上游测试依赖缺失的私人模型 fixture；CI 增加 Reborn 修复回归及 NumPy 测试依赖，不启用私有模型整合。

## 执行结果

本机为 Python 3.12.4、pytest 7.4.4、NumPy 1.26.4；公开 CI 配置为 Python 3.11、pytest 9.0.3、NumPy 1.26.4。两者不是同一验证环境。

| 检查 | 结果 |
| --- | --- |
| 253 份 `app_py` Python 文件语法解析 | 通过 |
| `python -m pytest tests/repair -q -p no:cacheprovider` | 12 通过，1 跳过 |
| 首次完整 `app_py/tests` | 1597 通过，11 跳过，5 失败（缺失上游 fixture） |
| 补充合成 fixture 后，两个相关测试文件 | 37 通过（包含修复的 5 项） |
| `tests/shipcheck/test_dist_shipped_docs_content.py` | 13 通过，6 跳过 |
| 合成 fixture 后完整 `app_py/tests` 重跑 | 150 秒限时终止，未得完整通过结果 |
| 单独复测原有 `test_dialog_close_time_dev1448.py` | 11 通过，2 个关闭耗时断言失败 |

修复测试跳过的是显式要求私有 rurune/Blender 数据的整合测试。其此前本机验证记录见 `VALIDATION.md`，本轮没有重复执行真实模型转换。

## 缺失的上游测试数据

首次 5 个失败均因公开源树缺少 `pipeline/py/testdata/sway_allocator/physbones_flathaori.json`，发生在 `test_sway_pb_catalog_wp_w2c.py`（3 项）及 `test_sway_style_dialog_pbunit_wp_w2c.py`（2 项）。在更名前原源码的同两个测试文件中复测，也得到相同的 5 失败、32 通过。

现使用完全人工生成、无第三方模型数据的 `app_py/tests/fixtures/physbones_synthetic_35.json`，测试命名和说明明确标注 synthetic。保留 35 组件、26 偏向组件、超过 9 槽仍全部生成样式、参数转换和 GUI 保存的原有断言，并增加多链组件不能拆成多行以及具体偏向组件身份的断言。转换逻辑没有改动。此替代验证公开 JSON 格式下的既有逻辑，不代表原 flatHaori 模型已重新验证；来源说明见 fixture 目录 README。

## 时序测试限制

第二次全套在 150 秒时限终止。此前出现的两个失败已定位到既有 `test_dialog_close_time_dev1448.py`：`test_sway_chain_dialog_close_time_dev1448` 和 `test_shapekey_select_dialog_close_time_dev1448`。单独复测关闭时间分别为 3.013 秒、3.229 秒，超过原有 2 秒阈值；第一次完整检查中它们通过。原源码的这两个测试也再次失败（2.576 秒、2.966 秒），证明并非 Reborn 改名独有。相关生产代码没有改动，本轮没有提高阈值或跳过测试，不能宣称最后一次完整 CI 全绿。

另有原有 `pipeline/py/vp_tex.py` 的 Python 无效转义字符语法警告；未修改该转换模块。

## 未执行

本轮没有创建新的完整运行安装，没有进行游戏实机或异机测试。新启动器与构建/烟测使用同一 `launcher_text()` 定义，名称为 `UchinokoReborn.bat`。后续公开完整运行包仍需要核验依赖再分发材料和构建流程。GitHub/工坊发布状态应以仓库与发布记录为准，此文仅记录本地源码检查。
