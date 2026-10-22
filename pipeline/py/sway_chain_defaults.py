# -*- coding: utf-8 -*-
"""sway_chain_defaults.py -- 「チェインの揺れ設定」の既定enabled判定+
enabled上書きの共有関数(dev#1572ロードマップ「チェインの揺れ設定問題1・2」
第3便、issue #1572追記)。

## 背景(2つの問題の共通原因)

問題1(既定で揺れる物が「揺れる」と表示されない)と問題2(ON/OFF UIが実際に
効かない)は、「この鎖は既定で揺れるか」の判定が2箇所で**別々に**計算されて
いたことが共通原因だった:

- 旧GUI表示(`app_py\\ui\\sway_chain_dialog.py._merge_working_set()`、
  `app_py\\ui\\sway_style_dialog.py._on_ok()`旧実装、`app_py\\
  sway_chain_override_store.py._default_enabled_for_bones()`):
  `pipeline\\py\\sway_identify.default_sway_enabled()` --
  尻尾/耳の名前トークン一致**のみ**。偏向(PB Limit Type等)は一切見ない。
- 実際にパイプラインが揺らす鎖(`sway_allocator.allocate()`、
  `lab_assignments`未指定時): 偏向判定(`_judge_pb_bias`/`_judge_sb_bias`)
  **のみ**。名前トークンは`is_tail`(優先順位のソートキー)にしか使わず、
  「候補として採用するか」には一切関与しない。

つまり実際にデフォルトで揺れるかどうかを決めているのは**偏向判定だけ**
であり、名前ベースの判定はGUI表示専用の別ロジックだった。この2つが食い違う
ため、「名前に尻尾/耳トークンが無い鎖(スカート・エプロン等)は、偏向して
いなければ実際には揺れているのに、GUIチェックボックスは既定OFF(未チェック)
で表示される」という食い違いが起きていた。

## 本モジュールの役割(唯一の真実の源)

`is_default_enabled(source, params)`が「既定enabled」を計算する**唯一**の
関数(2026-08-19オーナー裁定「実装方式=明示指定以外は存在しない」、issue
#1572追記): `sway_allocator._judge_pb_bias`/`_judge_sb_bias`(偏向判定の
唯一の真実の源、複製しない)をそのまま呼び、非偏向=既定enabledとする。

呼び出し元(いずれも本関数を直接呼ぶ。二重実装なし):
  - `app_py\\ui\\sway_style_dialog.py`: アバター読込時の行の既定enabled
    (チェックボックスの初期状態)、および保存時の
    `sway_chain_override_store.save_config()`/`load_config()`へ渡す
    `default_enabled_map`の算出元。
  - `lab_assignments_from_job()`(本モジュール、下記): job["sway_chain_overrides"]
    をsway_allocator.LabAssignment辞書へ変換する唯一の入口。

dev#1592(#1590取りこぼし修理、2026-08-19): `lab_assignments_from_job()`は
元々`pipeline\\blender\\step02_retarget.py::_lab_assignments_from_job()`だけが
持っていたロジックを本モジュールへ抽出したもの。抽出理由は、
`pipeline\\blender\\step01_import_vrm.py::compute_sway_source_bone_names()`
(dev#1508受入ゲートのground truthスナップショット対象骨を決める関数)も
**同じ**enabled解決結果を必要としたため——抽出前は`step01`が
`sway_allocator.allocate()`をlab_assignments無し(偏向判定のみ)で呼んでおり、
GUIでenabled:trueへ上書きした既定OFF鎖のウェイトがstep01スナップショットに
記録されず、step02側(#1590で正しく配線済み)とstep01側(旧#1590未追従)の
「対象骨集合」が食い違って`sway_source_gate`が誤FAILしていた
(issue #1592、オーナー実測)。`step02_retarget.py`の`_lab_assignments_from_job()`
は本関数への薄い委譲として残す(既存テスト`tests\\coverage\\
test_step02_sway_enabled_wiring_dev1572.py`のexec抽出互換のため関数名は維持)。

`sway_allocator.py`自体は変更しない(並行レーンlaneB1が房Mergeで改修中、
本WPの書き込み許可外)——本モジュールは`sway_allocator`の**公開API**
(`parse_physbones`/`parse_springbones`/`ChainUnit`/`LabAssignment`)と、
`test_sway_allocator.py`/`app_py\\ui\\sway_pb_catalog.is_unit_biased()`が
既に踏襲している「private偏向判定関数の直接再利用」慣例(`# noqa: SLF001`)
をそのまま使う。

`pipeline\\py\\sway_identify.py`(尻尾/耳の名前同定)は本モジュールの範囲外
のまま残る——`sway_allocator._is_tail_component()`が優先順位のソートキー
(`is_tail`)としてのみ引き続き使う。「既定enabled」の判定にはもう使わない
(旧`sway_identify.default_sway_enabled()`は非推奨、後方互換のため関数自体は
残すが新規呼び出し元を増やさない)。
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Mapping, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_allocator  # noqa: E402
import sway_quantize  # noqa: E402

# ChainUnit.source ("pb"/"sb") とGUI側("physbone"/"springbone")の両表記を
# 受け付ける(呼び出し元ごとに自然な語彙が違うため、ここで正規化を1箇所に
# 集約する)。
_SB_SOURCE_TOKENS = frozenset({"sb", "springbone", "spring_bone", "spring"})


def _normalize_source(source: Optional[str]) -> str:
    return "sb" if str(source or "").lower() in _SB_SOURCE_TOKENS else "pb"


def is_default_enabled(source: Optional[str], params: Optional[Mapping[str, object]]) -> bool:
    """1つのPB/SBコンポーネントの既定enabled(唯一の真実の源、モジュール
    docstring参照)。`source`は"pb"|"physbone"または"sb"|"springbone"|
    "spring_bone"(大小無視)。`params`は元のPB/SBパラメータ辞書
    (`sway_allocator.parse_physbones`/`parse_springbones`がChainUnitへ
    格納するものと同じ形)。

    判定ロジックは複製せず、`sway_allocator._judge_pb_bias`/`_judge_sb_bias`
    (偏向判定の唯一の真実の源)をそのまま呼ぶ——`app_py\\ui\\sway_pb_catalog.
    is_unit_biased()`と同じ「private関数の直接再利用」慣例
    (`test_sway_allocator.py`が同じ関数をテストから直接叩く既存パターン)。"""
    p = dict(params or {})
    if _normalize_source(source) == "sb":
        is_biased, _reason = sway_allocator._judge_sb_bias(p)  # noqa: SLF001
    else:
        is_biased, _reason = sway_allocator._judge_pb_bias(p)  # noqa: SLF001
    return not is_biased


def default_enabled_for_unit(unit: "sway_allocator.ChainUnit") -> bool:
    """`sway_allocator.ChainUnit`(`parse_physbones`/`parse_springbones`の
    戻り値)1件の既定enabled。`unit.is_biased`は`is_default_enabled()`と
    全く同じ判定関数(`_judge_pb_bias`/`_judge_sb_bias`)で既に計算済みだが、
    「GUI側とパイプライン側が同一関数を呼ぶ」構造を単体テストで機械的に
    示せるよう、ここでも`is_default_enabled()`を明示的に呼び直す
    (`unit.params`/`unit.source`から再計算——結果は数学的に`not unit.
    is_biased`と同一になる、`test_sway_chain_defaults.py`参照)。"""
    return is_default_enabled(unit.source, unit.params)


def compute_default_enabled_map(
    physbones_json: Optional[Mapping[str, object]] = None,
    springbones_json: Optional[Mapping[str, object]] = None,
) -> Dict[str, bool]:
    """{ChainUnit.key -> 既定enabled}。`sway_allocator.parse_physbones`/
    `parse_springbones`(パイプラインが実際に使う入力パーサそのもの)を
    そのまま呼ぶ(二重実装の禁止、モジュールdocstring参照)。"""
    units = list(sway_allocator.parse_physbones(physbones_json)) + \
        list(sway_allocator.parse_springbones(springbones_json))
    return {u.key: default_enabled_for_unit(u) for u in units}


def lab_assignment_for_unit(
    unit: "sway_allocator.ChainUnit", enabled: bool
) -> "sway_allocator.LabAssignment":
    """`enabled`上書き1件を`sway_allocator.LabAssignment`へ変換する
    (`sway_allocator.apply_lab_overrides()`へそのまま渡せる形)。

    enabled=False: `apply_lab_overrides()`はstyleをNoneへ強制上書きする
    ため、渡すstyleの値自体は使われない(空文字列で明示)。

    enabled=True: `unit.style`(偏向していなければ`parse_physbones`/
    `parse_springbones`が既に計算済み)をそのまま使う。偏向していた場合
    (`unit.style is None`、既定OFFの鎖を「自己責任」で明示的にONへ上書き
    するケース)は、`sway_quantize.quantize_pb`/`quantize_sb`(`parse_
    physbones`/`parse_springbones`が非偏向時に内部で呼ぶのと同じ公開関数)
    を`unit.params`から直接呼び、偏向していなかったなら得られていたはずの
    量子化プリセットをその場で再計算する——値を寄せて合わせるのではなく、
    製品の通常経路と同じ計算式をそのまま再利用する。limit_angleは上書き
    しない(Noneのまま渡し、`apply_lab_overrides()`に`unit.limit_angle`
    (偏向鎖は0=無制限)をそのまま使わせる——「自己責任でONにする」場合
    でも角度制限の再計算は本WPのスコープ外)。"""
    if not enabled:
        return sway_allocator.LabAssignment(style="", enabled=False)
    style = unit.style
    if style is None:
        if _normalize_source(unit.source) == "sb":
            style = sway_quantize.quantize_sb(
                float(unit.params.get("stiffness", 0.0)),
                float(unit.params.get("gravity_power", 0.0)),
                float(unit.params.get("drag_force", 0.0)))
        else:
            style = sway_quantize.quantize_pb(
                float(unit.params.get("pull", 0.0)),
                float(unit.params.get("spring", 0.0)))
    return sway_allocator.LabAssignment(style=style, enabled=True)


def lab_assignments_from_job(
    job: Mapping[str, object],
    physbone_entries,
    springbone_entries,
    weighted_bone_names=None,
) -> Dict[str, "sway_allocator.LabAssignment"]:
    """dev#1592(#1590取りこぼし修理)の共有入口: `job["sway_chain_overrides"]`
    (GUI保存分・CUI直書き分のどちらも同じ"bones"+"enabled"キー形式)を、
    `sway_allocator.allocate()`へそのまま渡せる{unit.key -> LabAssignment}へ
    変換する。元は`pipeline\\blender\\step02_retarget.py::
    _lab_assignments_from_job()`だけが持っていたロジック(dev#1572第3便)を
    本モジュールへ抽出したもの——`pipeline\\blender\\step01_import_vrm.py::
    compute_sway_source_bone_names()`(dev#1508受入ゲートのground truth
    スナップショット対象骨を決める関数)も同一の解決結果を必要とするため
    (モジュールdocstring「dev#1592」節参照)。

    **必ず全ユニットぶん**の既定値を`default_enabled_for_unit()`(本モジュール
    の唯一の真実の源)でまず敷き、job側のoverride(あれば)で上書きする。
    戻り値は常に全ユニットを覆う明示的な辞書になる——以後`sway_allocator.
    allocate()`側の暗黙fallback(`lab_assignments`未指定時の`is_biased`
    自動判定)は、本関数を通した呼び出しでは実質使われなくなる(構造上の
    安全網としてのみ残る)。

    override側の"bones"([anchor, node1, ...]、生catalog形式で`_end`等の
    無ウェイト骨を含みうる)は、`(unit.anchor,) + chain`(`extended_source`)と
    突き合わせる——unit.key(`"pb:<anchor>#<idx>"`、physbones.jsonの並び順に
    依存するindex込み)ではなく**鎖の内容(bones tuple)**でマッチさせるため、
    呼び出し元が用意したカタログと実際にパースされるphysbone_entries/
    springbone_entriesの並び順・件数が(フィルタ等で)多少ズレても正しく
    当たる。1つのunitが複数のchainsを持つ場合(房)、いずれか1本のchainが
    overrideと一致すればunit全体へその値を適用する(enabled/styleはChainUnit
    粒度でしか制御できない既存設計)。

    `weighted_bone_names`省略時(None)はoverride側のbonesを無変更で使う
    ——呼び出し元が渡す`physbone_entries`/`springbone_entries`自体が既に
    weighted-onlyへフィルタ済みでない場合(例: step01は生catalogのまま鎖を
    構築するため、この既定=Noneで正しく一致する)はこちらを使う。呼び出し元
    (step02)が事前にweighted-onlyへフィルタした`physbone_entries`を渡す
    場合は、override側の生bonesも同じ規約へ正規化する必要があるため
    `weighted_bone_names`を渡す。

    戻り値: 全ユニットが0件(physbone_entries/springbone_entriesが両方
    空)なら空dict。"""
    units = (
        list(sway_allocator.parse_physbones(
            {"physbones": list(physbone_entries or [])}))
        + list(sway_allocator.parse_springbones(
            {"springbones": list(springbone_entries or [])})))
    if not units:
        return {}

    enabled_overrides = {}
    for entry in (job.get("sway_chain_overrides") or []):
        bones = entry.get("bones")
        if not bones or "enabled" not in entry:
            continue
        if weighted_bone_names is not None:
            bones = [bones[0]] + [b for b in bones[1:] if b in weighted_bone_names]
        enabled_overrides[tuple(bones)] = bool(entry["enabled"])

    assignments = {}
    for unit in units:
        enabled = default_enabled_for_unit(unit)
        for chain in unit.chains:
            key = (unit.anchor,) + tuple(chain)
            if key in enabled_overrides:
                enabled = enabled_overrides[key]
                break
        assignments[unit.key] = lab_assignment_for_unit(unit, enabled)
    return assignments
