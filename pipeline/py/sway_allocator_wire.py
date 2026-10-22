# -*- coding: utf-8 -*-
"""sway_allocator_wire.py -- 揺れもの自動アロケータの実結線(dev#1508 W2a
第1段、issue https://github.com/pandrabox/DiveToPalworld-dev/issues/1508)。

正本仕様: `.devonly\\docs\\sway\\sway_wrapup\\SPEC.md` §1 / 列車計画: `.devonly\\docs\\sway\\sway_wrapup\\TRAIN.md`
Wave2 W2a。オーナー追加指示(2026-08-16、診断ログ要件強化)も本モジュールの
`build_diagnostics_lines()` で反映済み。

## 本モジュールの役割

`pipeline\\py\\sway_allocator.py`(候補判定・無偏向判定・量子化・グループ化・
容量、W1c純ロジック)と `pipeline\\py\\sway_assign.py`(donor骨への実配線
エンジン、region分類+節数優先、既存のまま無改変)の間を橋渡しする。

**本WPのスコープ**(TRAIN.md Wave2 W2a第1段): 「既存ドナー配線は既存経路の
まま」——耳=耳専用ノードという特別扱いは廃止したが、実際の骨配線
(donor動的発見・比例配分)はsway_assign.pyの既存エンジンをそのまま使う。
新設ののは「どの鎖を候補として渡すか(名前ヒューリスティックの代わりに
アロケータのaccepted結果を使う)」と「配線結果をKPノード単位の値
(style/limit_angle)へ変換する」の2点のみ。ハブroot生成・鎖の再親化等の
汎用配線はW2a-2(次段)の仕事。

## データフロー

1. `load_physbones_json()`: job["physbones_json"]のファイルパスから、
   sway_allocator.parse_physbones()がそのまま食べられる生JSON(dict、
   キー"physbones")を読む(physbone_catalog.pyのcatalog_from_sidecar()は
   params等を読み捨てる搬送専用パーサのため経由しない——生JSONのキー名は
   sway_allocator.pyが期待するキー名と完全一致することを確認済み:
   limit_type/limit_rotation/max_angle_x/pull/spring、W1a実装
   unity\\DiveToPalworldExporter.cs ExtractPhysBoneChains()参照)。
2. `wrap_springbones()`: job["springbones"](#1523実装、フラットlist)を
   `{"springbones": [...]}`へラップする(sway_allocator.parse_springbones()の
   想定形へ合わせるだけ、値自体は無変更)。
3. `sway_allocator.allocate()`: 候補判定・無偏向判定・量子化・グループ化・
   容量9・優先順位(既存W1c実装、無改変)。
4. `build_source_entries()`: plan.acceptedの全チェーンを、
   sway_assign.assign_avatar_sway()が食べられる形
   ({"anchor":str,"chains":[[...]]}のリスト)へ展開する。**1チェーン=
   1エントリ**に分解して渡す(sway_assign.source_chains_from_physbone_catalog()
   のid採番("{anchor}#{entry内index}")が、同一anchorの複数エントリで衝突
   しうる既存の癖があるため、1entry=1chainにしておけば常にidx=0で安全。
   ただし本モジュールは配線結果の追跡にsway_assign側のid文字列そのものには
   依存せず、(anchor, chain)というより頑健なキーで結果を突き合わせる
   ——同一(anchor,chain)ペアが複数回登場しない実データの前提、後述)。
5. `sway_assign.assign_avatar_sway()`(無改変)で実配線。
6. `compute_node_overrides()`: 配線結果(donor.chain_root、実際に骨が乗った
   donorのroot_bone名)ごとに、そのチェーンの由来元グループ/ユニットの
   style・limit_angleを対応付ける({root_bone: {"style":str,
   "limit_angle":float}}、sway_abp_build.build_spec_nodes()のnode_overrides
   引数そのもの)。
7. `build_diagnostics_lines()`: 全ユニット(採用/非採用問わず)について、
   元設定原値・判定過程・配線結果を1行の機械可読JSONとして出す
   (オーナー追加指示2026-08-16「成功時にも全部出す」「コライダー参照の
   1行」を含む)。

## job_dirを跨いだ受け渡し(step02→build_pak_from_avatar.py)

`compute_node_overrides()`の結果はBlenderプロセス(step02_retarget.py)内で
計算されるが、KPノードへのパッチ適用はUE非依存の別プロセス
(build_pak_from_avatar.py Phase 3.6)が行う。両者はjob.json以外の共有手段が
無いため、呼び出し側(step02_retarget.py)がこの結果を
`job_dir/converted/sway_node_overrides.json`へ書き出し、
build_pak_from_avatar.py側が読み込む(`_chibi_bone_world_head`等の既存
「job_dir配下への副ファイル書き出し」流儀を踏襲、本モジュール自体は
ファイルI/Oを持たない純関数群)。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_allocator  # noqa: E402
import sway_assign  # noqa: E402

# job_dir配下の副ファイル名(step02_retarget.py/build_pak_from_avatar.py両方が
# この定数を参照する)。
NODE_OVERRIDES_FILENAME = "sway_node_overrides.json"


# =====================================================================
# 1-2. 入力アダプタ
# =====================================================================

def load_physbones_json(physbones_json_path: Optional[str]) -> Optional[dict]:
    """job["physbones_json"](ファイルパス)から生JSONを読む。パス未指定/
    ファイル不在/壊れたJSONはNone(=候補ゼロとして安全側フォールバック、
    sway_allocator.allocate()はphysbones_json=Noneを正しく空扱いする)。"""
    if not physbones_json_path or not os.path.isfile(physbones_json_path):
        return None
    try:
        with open(physbones_json_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def wrap_springbones(springbones_list: Optional[Sequence[dict]]) -> dict:
    """job["springbones"](フラットlist)を sway_allocator.parse_springbones()
    が期待する{"springbones": [...]}へラップする。"""
    return {"springbones": list(springbones_list or [])}


# =====================================================================
# 4. sway_assign入力への変換 + 配線結果の逆引きキー
# =====================================================================

def build_source_entries(
    plan: sway_allocator.AllocationPlan,
) -> Tuple[List[dict], List[dict], Dict[Tuple[str, Tuple[str, ...]],
                                          Tuple[sway_allocator.SwayGroup, sway_allocator.ChainUnit]]]:
    """plan.acceptedの全チェーンを、sway_assign.assign_avatar_sway()の
    physbone_entries/springbone_entries引数形式(1チェーン=1エントリ)へ
    展開する。

    戻り値: (pb_entries, sb_entries, chain_lookup)。
    chain_lookup: {(anchor, chain_tuple): (group, unit)} -- 配線結果
    (sway_assign.Assignment.source.anchor/.chain)から、どのグループ/ユニット
    由来だったかを逆引きするためのキー。同一(anchor, chain)ペアが複数の
    ユニットに重複登場することは実データ上想定しない(1つのPB/SBコンポーネント
    が同じ骨列を複数回申告することはない)——万一重複しても後勝ちで安全側
    (どちらのstyleを使っても採用グループ内の値であることに変わりはない)。
    """
    pb_entries: List[dict] = []
    sb_entries: List[dict] = []
    chain_lookup: Dict[Tuple[str, Tuple[str, ...]],
                        Tuple[sway_allocator.SwayGroup, sway_allocator.ChainUnit]] = {}
    for group in plan.accepted:
        for unit in group.units:
            for chain in unit.chains:
                entry = {"anchor": unit.anchor, "chains": [list(chain)]}
                if unit.source == "pb":
                    pb_entries.append(entry)
                else:
                    sb_entries.append(entry)
                chain_lookup[(unit.anchor, chain)] = (group, unit)
    return pb_entries, sb_entries, chain_lookup


# =====================================================================
# 6. 配線結果 -> ノード単位override
# =====================================================================

def compute_node_overrides(
    assign_result: sway_assign.AssignmentResult,
    chain_lookup: Mapping[Tuple[str, Tuple[str, ...]],
                           Tuple[sway_allocator.SwayGroup, sway_allocator.ChainUnit]],
) -> Dict[str, Dict[str, object]]:
    """sway_assign配線結果(donor.chain_root、実際にウェイトが乗るdonor骨の
    先頭)ごとに、そのチェーンの由来グループのstyleと由来ユニットの
    limit_angleを対応付ける。sway_abp_build.build_spec_nodes()の
    node_overrides引数としてそのまま渡せる形
    ({root_bone: {"style": str, "limit_angle": float}})。

    chain_lookupに無いAssignment(理論上起きないはずだが、手動指定
    (job["sway_manual"])経由のAssignment等は本モジュールの管理外なので
    chain_lookupに載らない)は安全側で無視する(そのroot_boneには
    node_overridesが付かず、build_spec_nodes()側で従来どおりの一律
    hardness_keyが使われる——実害なし)。
    """
    overrides: Dict[str, Dict[str, object]] = {}
    for a in assign_result.assigned:
        hit = chain_lookup.get((a.source.anchor, a.source.chain))
        if hit is None:
            continue
        group, unit = hit
        overrides[a.donor.chain_root] = {
            "style": group.style,
            "limit_angle": unit.limit_angle,
        }
    return overrides


# =====================================================================
# 7. 診断ログ(オーナー追加指示2026-08-16対応)
# =====================================================================

def _original_settings_for(unit: sway_allocator.ChainUnit) -> Dict[str, object]:
    """診断ログ「元設定の原値」節。source(pb/sb)ごとにキー構成が異なる
    (SPEC.md §5参照: PBはpull/spring/limit系/integration_type、SBは
    stiffness/gravity_power/drag_force・角度制限機構自体が無い)。"""
    base: Dict[str, object] = {
        "type": unit.source,
        "pb_object_name": unit.pb_object_name,
        "collider_count": unit.collider_count,
    }
    p = unit.params
    if unit.source == "pb":
        base.update({
            "limit_type": p.get("limit_type"),
            "limit_rotation": p.get("limit_rotation"),
            "max_angle_x": p.get("max_angle_x"),
            "pull": p.get("pull"),
            "spring": p.get("spring"),
            "integration_type": p.get("integration_type"),
        })
    else:
        base.update({
            "stiffness": p.get("stiffness"),
            "gravity_power": p.get("gravity_power"),
            "drag_force": p.get("drag_force"),
        })
    return base


def build_diagnostics_lines(
    plan: sway_allocator.AllocationPlan,
    assign_result: Optional[sway_assign.AssignmentResult] = None,
    chain_lookup: Optional[Mapping[Tuple[str, Tuple[str, ...]],
                                    Tuple[sway_allocator.SwayGroup,
                                          sway_allocator.ChainUnit]]] = None,
) -> List[str]:
    """全PB/SBユニット(plan.all_units、採用/非採用問わず)について、
    「元設定の原値」「判定の全過程」「採用/除外」「配線結果」を1行の機械可読
    JSON文字列として出す(オーナー追加指示2026-08-16の4要件をすべて満たす)。

    1. 元設定の原値: type/pb_object_name/limitType/limitRotation/maxAngle/
       pull・spring(SBならstiffness/gravity_power/drag_force)/
       integration_type/コライダー参照数 -- `_original_settings_for()`。
    2. 判定の全過程: candidate(この時点で常にTrue、all_unitsはPB/SB付き
       鎖のみ)→is_biased/bias_reason(無偏向判定の分岐)→style(量子化結果)
       →limit_angle(写し値)→group_key(親×ゆれかた)→excluded_reason
       (Noneなら採用、それ以外は偏向/容量超過/ラボOFF等の理由文字列)。
    3. **成功時にも全部出す**: plan.all_unitsを無条件に全件出力する
       (採用ユニットもここに含まれる。「成功したのに結果が変」の診断に
       必須)。
    4. コライダー参照: collider_count>0のユニットには"collider_note"を
       追加(「元はコライダーN個で保護、変換後は保護なし」)。

    assign_result/chain_lookup省略時(まだ骨配線を実行していない場合、
    または骨配線自体が無効/donor在庫ゼロの場合)は"wiring"節を空扱いにする
    (候補判定・量子化までの診断は独立して意味を持つため、配線結果の有無は
    ログ出力全体をブロックしない)。
    """
    donor_by_chain: Dict[Tuple[str, Tuple[str, ...]], str] = {}
    lost_by_chain: Dict[Tuple[str, Tuple[str, ...]], str] = {}
    if assign_result is not None:
        for a in assign_result.assigned:
            donor_by_chain[(a.source.anchor, a.source.chain)] = a.donor.chain_root
        for u in assign_result.unassigned:
            lost_by_chain[(u.source.anchor, u.source.chain)] = u.reason

    lines: List[str] = []
    for unit in plan.all_units:
        judged = {
            "candidate": True,
            "is_biased": unit.is_biased,
            "bias_reason": unit.bias_reason,
            "style": unit.style,
            "limit_angle": unit.limit_angle,
            "is_tail": unit.is_tail,
            "group_key": [unit.anchor, unit.style] if unit.style else None,
        }
        wiring = []
        for chain in unit.chains:
            key = (unit.anchor, chain)
            if key in donor_by_chain:
                wiring.append({"chain": list(chain), "donor_root_bone": donor_by_chain[key]})
            elif key in lost_by_chain:
                wiring.append({
                    "chain": list(chain), "donor_root_bone": None,
                    "wiring_lost_reason": lost_by_chain[key],
                })
            else:
                wiring.append({"chain": list(chain), "donor_root_bone": None})

        record: Dict[str, object] = {
            "sway_diag": True,
            "key": unit.key,
            "anchor": unit.anchor,
            "original": _original_settings_for(unit),
            "judged": judged,
            "excluded_reason": unit.excluded_reason,
            "wiring": wiring,
        }
        if unit.collider_count > 0:
            record["collider_note"] = (
                f"元はコライダー{unit.collider_count}個で保護、変換後は保護なし"
                "(dev#1508 SPEC.md §2 コライダー放棄確定)")
        lines.append(json.dumps(record, ensure_ascii=False))
    return lines


# =====================================================================
# 高レベル入口(pipeline\blender\step02_retarget.pyから呼ぶ想定)
# =====================================================================

def wire_and_diagnose(
    *,
    physbone_entries: Sequence[dict] = (),
    springbone_entries: Sequence[dict] = (),
    donor_bone_pairs: Sequence[Tuple[str, Optional[str]]],
    source_parent_of: Dict[str, Optional[str]],
    gender: str,
    manual_chains: Sequence[dict] = (),
    chibi_candidates=None,
    symbols: Optional[Dict] = None,
    registered_families: Optional[Sequence[str]] = None,
    lab_assignments=None,
    capacity: int = sway_allocator.DEFAULT_CAPACITY,
) -> Tuple[List[dict], Dict[str, Dict[str, object]], List[str], dict]:
    """入力アダプタ+アロケータ実行+sway_assign配線+診断ログ生成を1本化した
    高レベル入口。

    physbone_entries: 既にパース済みのPBエントリリスト(呼び出し側=
      pipeline\\blender\\step02_retarget.py main()が`job["physbones_json"]`
      ファイルを読んで渡す想定、既存の呼び出し規約を踏襲——`params`キーを
      含む生entryのリストであること。ファイルI/O自体が必要な場合は
      `load_physbones_json()`を呼び出し側で使う)。
    springbone_entries: job["springbones"](フラットlist、既存)。

    manual_chains(job["sway_manual"]、既存の手動指定経路)はアロケータの
    候補判定を経由せず、常にそのままsway_assign.assign_avatar_sway()へ渡す
    (既存仕様どおり——手動指定は「候補」概念の対象外)。

    戻り値: (job_fragments, node_overrides, diagnostics_lines, sway_report)。
    - job_fragments: sway_assign.AssignmentResult.assignedのjob_fragment
      リスト(resolve_sway_chain_entries()がそのまま消費できる形、既存踏襲)。
    - node_overrides: compute_node_overrides()の戻り値
      (job_dir/converted/sway_node_overrides.jsonへ書き出す想定)。
    - diagnostics_lines: build_diagnostics_lines()の戻り値
      (変換ログへ1行ずつprintする想定)。
    - sway_report: sway_assign.build_sway_lost_report()の戻り値(既存踏襲)。

    donor_bone_pairsが空(共有骨格の骨在庫が未抽出)の場合は、アロケータ自体は
    実行する(診断ログは出す)が配線は行わない(job_fragments=[]、
    node_overrides={})——候補判定・量子化とdonor骨配線は独立した処理段
    という設計を診断ログの完全性でも守る。
    """
    physbones_raw = {"physbones": list(physbone_entries or [])}
    springbones_raw = wrap_springbones(springbone_entries)
    plan = sway_allocator.allocate(
        physbones_json=physbones_raw, springbones_json=springbones_raw,
        lab_assignments=lab_assignments, capacity=capacity)

    pb_entries, sb_entries, chain_lookup = build_source_entries(plan)

    assign_result = sway_assign.AssignmentResult()
    if donor_bone_pairs and (pb_entries or sb_entries or manual_chains):
        assign_result = sway_assign.assign_avatar_sway(
            physbone_entries=pb_entries, springbone_entries=sb_entries,
            manual_chains=manual_chains, donor_bone_pairs=donor_bone_pairs,
            source_parent_of=source_parent_of, gender=gender,
            chibi_candidates=chibi_candidates, symbols=symbols,
            registered_families=registered_families,
        )

    node_overrides = compute_node_overrides(assign_result, chain_lookup)
    diagnostics_lines = build_diagnostics_lines(plan, assign_result, chain_lookup)
    sway_report = sway_assign.build_sway_lost_report(assign_result)
    job_fragments = [a.job_fragment for a in assign_result.assigned]
    return job_fragments, node_overrides, diagnostics_lines, sway_report
