# -*- coding: utf-8 -*-
"""sway_source_bones.py -- 揺れもの受入ゲート(dev#1508)の左辺(ソース基準の
対象骨集合)を、配線実装(`sway_hub.py`/`sway_hub_wire.py`)を一切経由せず
独立に導出する。

正本仕様: `.devonly\\docs\\sway\\sway_wrapup\\SPEC.md` §5「受入ゲートの正本」(オーナー制定、
2026-08-16)。「基準はソース側(PBのroot骨=揺れる最初の関節を含む全対象骨)。
計画(plan)を基準にした自己参照検査を受入の柱にしてはならない」——本モジュールは
この裁定を満たすための独立実装。

## なぜ独立でなければならないか(オーナー指摘2026-08-16)

`sway_hub.plan_hub_wiring()`/`sway_hub_wire.source_to_donor_bone_map()`
そのものにanchor骨欠落バグがあった(dev#1508、`work\\earshape_diag\\DIAG.md`)。
ゲートの対象骨集合をこれら配線側の関数から導出すると、同じ穴(anchorを
含め忘れる実装ミス)がゲート側にも継承され、「配線が対象集合そのものを
間違えている」ケースを原理的に検出できない(自己参照検査)。

本モジュールは`sway_allocator`(判定ロジックの正本、変更しない)の出力
(`ChainUnit.anchor`/`.chains`という生データ)だけを読み、`sway_hub`/
`sway_hub_wire`を一切importしない。
"""
from __future__ import annotations

import os
import sys
from typing import Dict, FrozenSet, Set

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_allocator  # noqa: E402


def expand_unit_source_bones(unit: sway_allocator.ChainUnit) -> FrozenSet[str]:
    """1つの`ChainUnit`(PB/SBコンポーネント1個)について、「揺れると判定
    された全ボーン」を独立に展開する: `anchor自身`+`全chainsに現れる
    骨名`の和集合。

    SPEC §5裁定「PBのroot骨(anchor)自身も揺れる最初の可動骨であり、ハブ
    直下のドナーに写す」に基づき、anchorを対象集合から除外しない
    (`sway_allocator.ChainUnit.chains`自体はanchorを含まない子孫のみ、
    というsway_allocatorの既存規約はそのまま——本関数がここでanchorを
    明示的に和集合へ足す)。"""
    names: Set[str] = {unit.anchor}
    for chain in unit.chains:
        names.update(chain)
    return frozenset(names)


def expand_accepted_source_bones(
    plan: sway_allocator.AllocationPlan,
) -> Dict[str, FrozenSet[str]]:
    """`plan.accepted`(採用グループ、優先順位降順)の全ユニットについて、
    `unit.key -> 独立展開した対象骨名集合`の辞書を返す(ゲートの左辺その
    もの、ユニット単位)。"""
    out: Dict[str, FrozenSet[str]] = {}
    for group in plan.accepted:
        for unit in group.units:
            out[unit.key] = expand_unit_source_bones(unit)
    return out


def all_accepted_source_bone_names(
    plan: sway_allocator.AllocationPlan,
) -> FrozenSet[str]:
    """`expand_accepted_source_bones()`の全ユニットぶんを1つのフラットな
    集合へまとめたもの(ゲートが「1本でも欠けたら即FAIL」で回す対象全体、
    採用グループ全部+それぞれのanchor+chains)。"""
    names: Set[str] = set()
    for bones in expand_accepted_source_bones(plan).values():
        names.update(bones)
    return frozenset(names)


def accepted_anchor_names(
    plan: sway_allocator.AllocationPlan,
) -> FrozenSet[str]:
    """`plan.accepted`(採用グループ)の全ユニットについて、`unit.anchor`
    (=支点、公理検査`sway_pivot_axiom.py`の対象)だけをフラットな集合で
    返す(`all_accepted_source_bone_names()`はanchor+chains全体を返すため、
    支点だけに絞りたい場合はこちらを使う)。"""
    return frozenset(unit.anchor for group in plan.accepted for unit in group.units)


def bone_group_keys(
    plan: sway_allocator.AllocationPlan,
) -> Dict[str, FrozenSet[str]]:
    """`plan.accepted`の各採用骨名について、それが属する`SwayGroup.
    group_key`(`(anchor, style)`をstr化した`"anchor|style"`)の集合を返す
    ({骨名 -> {group_key, ...}}、1骨が複数グループに現れることは実データ上
    想定しないが、念のため集合で持つ)。

    **用途(ゲート側の限定的な例外処理)**: `sway_allocator.allocate()`の
    「採用(accepted)」は、そのグループが実際に骨配線(donor prool/anchor
    のPAL解決)まで成功することまでは保証しない(容量9はallocate()自身が
    絞るが、donor在庫枯渇やanchorのPAL側retarget未解決は後続の
    `sway_hub.plan_hub_wiring()`/`filter_wiring_by_resolvable_anchor()`が
    判定する、既存の理由付きフォールバック=`wiring.unassignable`)。この
    「配線不能」はdev#1508のバグ(理由なき静かな欠落)とは別の、既存の
    正常フォールバック経路(容量・在庫制約、SPEC §3-1「同時に揺れるのは
    9グループまで」)であるため、ゲートはこれを理由付きで例外にしてよい
    ——ただし判定(呼び出し側がこの関数で得たgroup_keyを、実際に
    `wiring.unassignable`にあるgroup_keyと突き合わせる)は呼び出し側
    (`pipeline\\blender\\step02_retarget.py`)の責務とし、本関数自体は
    `sway_hub`を一切importしない(構造的独立性は崩さない)。"""
    out: Dict[str, Set[str]] = {}
    for group in plan.accepted:
        gk = f"{group.group_key[0]}|{group.group_key[1]}"
        for unit in group.units:
            for name in expand_unit_source_bones(unit):
                out.setdefault(name, set()).add(gk)
    return {k: frozenset(v) for k, v in out.items()}


def bone_unit_keys(
    plan: sway_allocator.AllocationPlan,
) -> Dict[str, FrozenSet[str]]:
    """`bone_group_keys()`より1段細かい粒度: `plan.accepted`の各採用骨名に
    ついて、それが属する`ChainUnit.key`(="pb:<anchor>#<idx>"/
    "sb:<anchor>#<idx>"、**1つのPB/SBコンポーネント=1つの「鎖」に対応する
    安定キー**)の集合を返す({骨名 -> {unit_key, ...}})。

    dev#1508 graceful-degrade(揺れ鎖の明示的縮退、night_20260817 laneI)用:
    `bone_group_keys()`は複数のunit(鎖)が1つの`SwayGroup`(親humanoid骨×
    ゆれかたで統合済み)へ束ねられた**後**の粒度しか返さないため、そのまま
    使うと「1鎖だけが受入ゲートFAILしても、同じグループへ統合された
    無関係な他の鎖まで道連れで除外してしまう」(必要以上に広い縮退)。
    本関数は統合**前**のunit粒度(`sway_allocator.LabAssignment`が受け付ける
    キーそのもの)を返すため、呼び出し側(`pipeline\\blender\\
    step02_retarget.py`)はFAILしたボーンが属するunit.keyだけを
    `apply_lab_overrides()`経由で無効化でき、それ以外の鎖は無傷のまま
    残せる。"""
    out: Dict[str, Set[str]] = {}
    for group in plan.accepted:
        for unit in group.units:
            for name in expand_unit_source_bones(unit):
                out.setdefault(name, set()).add(unit.key)
    return {k: frozenset(v) for k, v in out.items()}
