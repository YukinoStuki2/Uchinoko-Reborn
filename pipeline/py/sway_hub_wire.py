# -*- coding: utf-8 -*-
"""sway_hub_wire.py -- 汎用ハブ配線の高レベル入口(dev#1508 W2a-2c、
issue https://github.com/pandrabox/DiveToPalworld-dev/issues/1508)。

`sway_allocator_wire.py`(旧family限定donor経路の高レベル入口)と対になる、
ハブ方式版のオーケストレーション。`pipeline\\blender\\step02_retarget.py`
(bpy依存)がPB/SBエントリの読み込み・avatar_dump/anchor_pal_name_ofの
組み立てのみを担い、本モジュールがそれ以外(アロケータ実行〜ハブ配線計画
〜node_overrides/診断ログ/refskel-dict生成)を一括して行う(bpy非依存、
単体テスト可能)。

## 本モジュールがカバーしない部分(呼び出し側の責務)

- `avatar_dump`/`anchor_pal_name_of`の組み立て(bpy依存、実アバターの
  ポーズ位置を読む必要がある——`pipeline\\py\\sway_hub_placement.py`
  モジュールdocstring参照)
- `sway_hub_placement.plan_reparent_steps()`の呼び出し(座標配置、
  avatar_dumpが要るため呼び出し側の責務)
- Blender pal_arm への実際のボーン追加・配置(bpy依存)

## SPEC.md §1「候補」との関係

`wire_and_diagnose_hub()`は自動割当(PB/SB由来の候補)専用。手動指定
(job["sway_manual"])はSPEC.mdの対象外(旧経路のsway_allocator_wire.py
+sway_assign.pyのfamily限定donor経路のまま存続する、指示書「旧経路の完全
置換」は自動割当のみを指す——本モジュールのdocstring・呼び出し側
step02_retarget.pyのコメントで明記)。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_abp_build  # noqa: E402
import sway_allocator  # noqa: E402
import sway_hub  # noqa: E402

TAG = "sway_hub_wire"

# dev#1508 laneA4(amplitude-root): wire_and_diagnose_hub()のamplitude_rank/
# known_moving引数の既定センチネル。「未指定」(=製品既定の実データを自動
# 読み込む)と「明示的に空(=旧enumerate順へ戻す)」を区別するために使う
# (Noneを既定にすると両者を区別できない——空dict/frozensetを渡された
# テストが誤って製品データへフォールバックしてしまう)。
_AUTO = object()


# =====================================================================
# dev#1572(積み荷A、issue #1572追記3、2026-08-18オーナー最終裁定
# 「無weightボーンには僕は興味がなく、ないものと扱ってます」)
# =====================================================================

def filter_entries_by_weighted_bones(
    entries: Sequence[Mapping[str, object]],
    weighted_bone_names: Optional[FrozenSet[str]],
) -> List[dict]:
    """physbone/springboneエントリ(`{"anchor":..., "chains": [[...], ...],
    "params": {...}}`形式)の各`chains`から、`weighted_bone_names`(頂点
    ウェイト>0の頂点グループを実際に持つ骨名の集合、
    `pipeline\\blender\\step02_retarget.py::collect_weighted_avatar_bone_
    names()`が計算する)に含まれない骨名を取り除いて詰める——「無weight
    ボーンには興味が無く、ないものと扱う」の実装。

    先端に限らず鎖の**途中**にあっても除外して後続を前へ詰める(素直な
    「ないものとして扱う」の解釈——例: [A,B,C]でBのみ無ウェイトなら
    [A,C]。呼び出し側`sway_hub.fit_chain_to_length()`は`chain`を単なる
    根元→先端の骨名列として扱うだけで隣接性を要求しないため、詰めても
    後続のdonor配置(`av_point(name)`が実boneの実位置を都度引く)は無傷)。
    全要素が除外されたチェーンはそのエントリの`"chains"`から丸ごと落とす
    (空チェーンを`sway_allocator.ChainUnit.chains`へ残さない)。

    `entry["anchor"]`自体はこの関数の対象外(常に維持する)——
    `sway_hub.fit_chain_to_length()`の「根本(anchor)は絶対にマージ
    しない」制約と対になる規約であり、issue #1572本文が指定する母集団は
    "chain"側のみ(anchorのウェイト有無は本WPのスコープ外)。

    `weighted_bone_names`が`None`なら無変更でそのまま返す(bpyメッシュ
    情報が使えない場面——単体テスト・呼び出し側が意図的にスキップする
    場合——の安全側フォールバック、既存呼び出し元は完全無退行)。

    **鎖抽出〜フィット入力までの母集団判定はこの1箇所に集約する**
    (`pipeline\\blender\\step02_retarget.py::main()`が`physbone_entries`/
    `job["springbones"]`の両方へこの関数を1回ずつ適用してから、
    `wire_sway_hub_auto()`(→`wire_and_diagnose_hub()`)と
    `sway_gate_compute_source_bone_names()`(独立再導出、gate用)の
    **両方**へ同じ既フィルタ済みの値を渡す——二重実装を避ける設計。
    後者にも同じ入力を渡さないと、ゲートが「配線されなかった無ウェイト
    骨」を誤ってsourceとして期待し続け、誤検知FAILになる)。"""
    if weighted_bone_names is None:
        return [dict(e) for e in entries]
    out: List[dict] = []
    for entry in entries:
        new_entry = dict(entry)
        chains = entry.get("chains", []) or []
        filtered_chains = []
        for chain in chains:
            filtered = [b for b in chain if b in weighted_bone_names]
            if filtered:
                filtered_chains.append(filtered)
        new_entry["chains"] = filtered_chains
        out.append(new_entry)
    return out


@dataclass(frozen=True)
class HubWireResult:
    """`wire_and_diagnose_hub()`の戻り値一式。

    `plan`(`sway_allocator.AllocationPlan`)を公開するのは、呼び出し側
    (`step02_retarget.py`)が`sway_hub.filter_wiring_by_resolvable_anchor()`で
    `wiring`をグループ単位フィルタした**後**に`sway_hub.
    build_diagnostics_lines(plan, filtered_wiring, gender)`を再計算できる
    ようにするため(フィルタ前のdiagnostics_linesをそのまま使うと、
    anchor未解決で実際には配線されなかったグループが「採用」と誤表示
    される)。"""

    plan: sway_allocator.AllocationPlan
    wiring: sway_hub.HubWiringPlan
    node_overrides: Dict[str, Dict[str, object]]
    diagnostics_lines: Tuple[str, ...]
    refskel_dict: Dict[str, Dict[str, object]]


def wire_and_diagnose_hub(
    *,
    physbone_entries: Sequence[dict] = (),
    springbone_entries: Sequence[dict] = (),
    gender: str,
    catalog: sway_hub.SkeletonCatalog,
    common_bones: FrozenSet[str],
    lab_assignments=None,
    capacity: int = sway_allocator.DEFAULT_CAPACITY,
    templates_dir: str = sway_abp_build.TEMPLATES_DIR,
    amplitude_rank=_AUTO,
    known_moving=_AUTO,
    default_safety_margin: int = 0,
    safety_margin_by_chain: Optional[Mapping[Tuple[str, ...], int]] = None,
) -> HubWireResult:
    """入力アダプタ+アロケータ実行+ハブ配線計画+診断ログ+refskel-dict生成を
    1本化した高レベル入口(`sway_allocator_wire.wire_and_diagnose()`の
    ハブ版)。

    `catalog`: `sway_hub.load_skeleton_catalog()`(`vanilla\\
    sk_palhuman_full.json`)の戻り値。`common_bones`: `vanilla\\
    common_bones.json`の`"common"`リスト(`free_donor_pool()`の`protected`、
    予約骨とは別に基幹人型ボディリグを自由プールから除外する安全策——
    `sway_hub.py`モジュールdocstring「予約骨」節参照。**呼び出し側が
    これを渡し忘れると基幹ボーンがdonorに漏れる**、本関数はこれを常に
    `plan_hub_wiring()`へ配線する)。

    dev#1551(2026-08-17オーナー裁定、issue #1551「hubを廃止し1chainあたり
    1KPノードへ移行する」): `anchor_group_of`引数は削除済み。旧dev#1508
    hubwire final(耳L/R等、異なるanchorでも親humanoid骨が同じなら1グループへ
    統合する仕組み)はハブ構造(1スロット=複数鎖共有)の実機不具合容疑を
    受けて廃止し、`sway_allocator.allocate()`は常にChainUnit単位(1鎖=1グループ)
    で割り当てる(`sway_allocator.build_groups()`docstring参照)。

    候補がゼロ(physbone_entries/springbone_entries が両方空、または
    全鎖が偏向/容量超過)なら`wiring.group_plans`が空になり、以降の
    node_overrides/refskel_dictも空dictになる(完全no-op、既定出力不変)。

    `amplitude_rank`/`known_moving`(dev#1508 laneA4、amplitude-root):
    省略時(既定)は製品同梱データ(`sway_hub.load_root_amplitude_rank()`/
    `load_known_moving_chain_bones()`、`sway_root_amplitude.json`/
    `sway_known_moving_bones.json`)を自動的に読み込み、可視性tier×振幅
    昇順のroot割当(`sway_hub.plan_hub_wiring()`docstring参照)を**常に
    有効化する**——呼び出し側(`step02_retarget.py`)の変更は不要。明示的に
    `{}`/`frozenset()`を渡せば旧enumerate順(振幅無視)へ戻せる(単体テスト
    やデバッグ用の脱出口)。

    `default_safety_margin`/`safety_margin_by_chain`(dev#1551安全域WP、
    issue #1551「安全域」欄、2026-08-18オーナー最終裁定): そのまま
    `sway_hub.plan_hub_wiring()`へ渡す(`sway_hub.py`docstring参照)。
    両方とも既定は0(=無効化、既存呼び出し元・既存テストは無退行)。
    **製品既定値(1)は本関数の既定引数ではなく、呼び出し側
    (`pipeline\\blender\\step02_retarget.py::wire_sway_hub_auto()`)が
    明示的に渡す**(本モジュール・本関数を直接叩く既存の単体テスト群
    (`test_sway_hub_wire.py`)が意図せず巻き込まれて赤くならないための
    設計判断——RESULT.md「設計判断2」、work\\run_1551\\laneR2_safety\\
    RESULT.md参照)。"""
    physbones_raw = {"physbones": list(physbone_entries or [])}
    springbones_raw = {"springbones": list(springbone_entries or [])}
    plan = sway_allocator.allocate(
        physbones_json=physbones_raw, springbones_json=springbones_raw,
        lab_assignments=lab_assignments, capacity=capacity)

    resolved_amplitude_rank = (
        sway_hub.load_root_amplitude_rank() if amplitude_rank is _AUTO else amplitude_rank)
    resolved_known_moving = (
        sway_hub.load_known_moving_chain_bones() if known_moving is _AUTO else known_moving)

    hub_slots = sway_hub.discover_hub_slots(templates_dir)
    all_roots = sway_hub.all_kp_node_root_names(templates_dir)
    reserved = sway_hub.reserved_descendants_of(all_roots, catalog.bones)
    wiring = sway_hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved, protected=common_bones,
        known_moving=resolved_known_moving, amplitude_rank=resolved_amplitude_rank,
        default_safety_margin=default_safety_margin,
        safety_margin_by_chain=safety_margin_by_chain)

    node_overrides = sway_hub.node_overrides_from_wiring_plan(wiring)
    diagnostics_lines = tuple(sway_hub.build_diagnostics_lines(plan, wiring, gender))
    refskel_dict = sway_hub.refskel_dict_for_wiring(wiring, gender)

    return HubWireResult(
        plan=plan, wiring=wiring, node_overrides=node_overrides,
        diagnostics_lines=diagnostics_lines, refskel_dict=refskel_dict)


def source_to_donor_bone_map(wiring: sway_hub.HubWiringPlan, gender: str) -> Dict[str, str]:
    """`wiring`全体の(source骨名 -> donor骨名)対応をフラットな1つの辞書に
    まとめる(`step02_retarget.py`の`group_targets[av] = donor`書き込みへ
    そのまま使える形。`sway_hub.plan_hub_wiring()`はハブ経路が常に
    n_donor==n_source(donorをsourceと同数だけ払い出す設計、`sway_hub.py`
    `plan_hub_wiring()`docstring参照)を保証するため、比例配分・アンカー
    畳み込み等のフォールバックを経由しない単純な1対1zipで足りる)。

    `gender`(dev#1551性別またぎdedup漏れ修正で新規追加、必須引数):
    bivariantなハブスロット(`ChainDonorPlan.donor_chain_for()`docstring
    参照)では女性向け/男性向けで異なる(互いに素な)donor骨集合を持つため、
    呼び出し側(step02_retarget.pyの性別ごとのBlenderプロセス)が処理中の
    gender向けの対応表だけを返す。この対応表はそのgenderのメッシュの
    頂点グループ書き換え先(`group_targets`)に使われるため、gender取り違え
    はそのままメッシュのウェイトが誤ったdonor骨へ向く実害になる。

    dev#1551(chain-length-fit WP): `cp.source_chain`は節数フィット発動時
    (`sway_hub.fit_chain_to_length()`)には**マージ後の代表骨名だけ**を
    持つ縮退版になるため、まず代表->donorの対応をzipで作り、
    `cp.weight_expansion`(元の全アバター骨名 -> 代表骨名)経由で元の
    全アバター骨名へ展開する。節数フィット未発動なら`weight_expansion`は
    恒等写像(`{b: b for b in source_chain}`)なので、この経由は従来の
    単純zipと完全に同じ結果を返す(無退行)。

    dev#1551(ゼロ長root廃止修理): `source_chain[0]`(=anchor自身)は今や
    hub root自身(`gp.hub_root_male`/`hub_root_female`)がexact geometryを
    担う(`sway_hub_placement._hub_root_real_segment_transform()`参照)。
    `source_chain[1:]`が`donor_chain_for(gender)`の各要素へ1つ繰り上がって
    対応する——代表->donor対応は`(hub_name,) + donor_chain`を
    `source_chain`とzipすることで組み立てる(`zip()`は短い方
    (`source_chain`、常に`len(donor_chain)`と同じ長さ)で止まるため、
    余剰donor(`donor_chain`の最後の1本、内容写像の繰り上げで対応する
    source要素が無い延長donor)は自動的に対応表から除外される)。"""
    out: Dict[str, str] = {}
    for gp in wiring.group_plans:
        hub_name = gp.hub_root_male if gender == "Male" else gp.hub_root_female
        for cp in gp.chain_plans:
            shifted_targets = (hub_name,) + tuple(cp.donor_chain_for(gender))
            rep_to_donor = dict(zip(cp.source_chain, shifted_targets))
            for original, rep in cp.weight_expansion.items():
                donor = rep_to_donor.get(rep)
                if donor is not None:
                    out[original] = donor
    return out
