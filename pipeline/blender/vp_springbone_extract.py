# -*- coding: utf-8 -*-
r"""dev#1508 W1b(VRM SpringBone→sway_allocator配線)のスキーマ変換ロジック
(bpy非依存)。

背景(work\night_20260817\laneE\SMOKE.md、2026-08-17夜間自走で確定した発見):
VRM入力でsway_enable:trueを指定しても、step01_import_vrm.pyの
extract_spring_roots()はSpringBoneのroot骨名だけ(揺れ髪機構向けの軽量版)を
返しており、pipeline\py\sway_allocator.py が期待する完全なスキーマ
({"anchor":..., "chains":[[...]], "params": {"stiffness":...,
"gravity_power":..., "drag_force":...}})へは一度も変換されていなかった
(sway_allocator.py モジュールdocstring「springbones.json の想定スキーマ」
節が「W1b未実装」と明記していた欠落そのもの)。

本モジュールは、そのスキーマ変換ロジックだけを切り出したもの
(vp_mesh_drop.py/vp_dup_armature.py/vp_flatten_pin.pyと同じ設計方針:
ダックタイピング、bpy非依存、tests\coverage\selftestから直接検証可能)。
呼び出し元(step01_import_vrm.py extract_springbone_components())は、
bpy(`arm.data.vrm_addon_extension`/`arm.data.bones`)から素のPython辞書へ
変換するだけの薄いglueに留め、本モジュールへ委譲する。

## VRM1(spring_bone1.springs)

1 spring = 1 エントリ。`anchor` = joints[0](有効な最初の関節、
bone_nameが設定されておりアーマチュアに実在するもの)の親骨。
`chains` = そのjoints全体の骨名リスト1本(VRM1のjointsは元々1本の
順序付きチェーンのため、分岐はしない)。`params` はjoints[0]の値を代表値
として採用する(VRM1は関節ごとに独立した値を持てるが、本スキーマは
PhysBoneと同じ「1コンポーネント=1パラメータ組」という粗い表現のため、
先頭関節の値で近似する——量子化(sway_quantize.quantize_sb)自体が
やわ/ふつう/かための3値へ丸める設計であり、詳細な逐関節値は元々失われる
前提)。

## VRM0(secondary_animation.bone_groups)

1つのbone_groupは`bones`(揺れの起点となる複数のroot骨)を一括で保持でき、
各rootの実際の親骨は互いに異なりうる(例: 左右の耳、髪と装飾が同じ
bone_groupに同居)。sway_allocatorの`ChainUnit`は`anchor`を1つしか
持てないため、1つのbone_groupを1エントリに束ねることができない
——`bones`の各rootを**独立したエントリへ展開**する(anchor=root自身の
親骨)。これによって見た目のグループ化(耳L/Rの統合等)が失われることは
ない: 後段の`sway_allocator.build_groups()`が`(親humanoid骨, style)`で
再統合するため、同じ親に解決される複数エントリは最終的に1つの
`SwayGroup`へまとまる。

`chains`はrootのサブツリーを`linear_chains_from_root()`で分岐ごとに
線形化したもの(root自身を含む、葉が複数あれば複数チェーン)。
`params`はbone_group共通の値(stiffness/gravity_power/drag_force)。
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence


def linear_chains_from_root(
    root: str, children_of: Mapping[str, Sequence[str]]
) -> List[List[str]]:
    """`root`(骨名)から子孫方向へ辿った線形チェーンを全て列挙する
    (root自身を含む)。枝分かれがあれば葉ごとに1本、複数チェーンとして
    返す(登場順は`children_of`に格納された子の順序に従う、決定論的)。

    `children_of`: {親骨名: [子骨名, ...]}(親を持たない/子が無い骨は
    キー自体が無くてよい、`.get()`で空扱い)。"""
    chains: List[List[str]] = []

    def walk(name: str, path: List[str]) -> None:
        path = path + [name]
        children = children_of.get(name) or []
        if not children:
            chains.append(path)
            return
        for child in children:
            walk(child, path)

    walk(root, [])
    return chains


def _spring_params(joint: Mapping[str, object]) -> Dict[str, float]:
    return {
        "stiffness": float(joint.get("stiffness", 1.0)),
        "gravity_power": float(joint.get("gravity_power", 0.0)),
        "drag_force": float(joint.get("drag_force", 0.4)),
    }


def _bone_group_params(bg: Mapping[str, object]) -> Dict[str, float]:
    return {
        "stiffness": float(bg.get("stiffness", 1.0)),
        "gravity_power": float(bg.get("gravity_power", 0.0)),
        "drag_force": float(bg.get("drag_force", 0.4)),
    }


def build_springbone_components(
    vrm1_springs: Optional[Sequence[Mapping[str, object]]],
    vrm0_bone_groups: Optional[Sequence[Mapping[str, object]]],
    parent_of: Mapping[str, Optional[str]],
    children_of: Mapping[str, Sequence[str]],
    bone_names: Sequence[str],
) -> List[Dict[str, object]]:
    """VRM1/VRM0の生のSpringBone定義(bpy抽出済みの素のPython辞書)から、
    `sway_allocator.parse_springbones()`が期待するフラットlist
    (`job["springbones"]`にそのまま代入できる形。各要素は
    `{"anchor": str, "chains": [[str,...],...], "params": {...}}`)を作る。

    引数:
      vrm1_springs: [{"joints": [{"bone_name": str, "stiffness": float,
        "gravity_power": float, "drag_force": float}, ...]}, ...]
        (`arm.data.vrm_addon_extension.spring_bone1.springs`から1:1変換)。
      vrm0_bone_groups: [{"stiffness": float, "gravity_power": float,
        "drag_force": float, "bones": [str, ...]}, ...]
        (`arm.data.vrm_addon_extension.vrm0.secondary_animation.bone_groups`
        から1:1変換。キー名"stiffness"はアドオン側の実プロパティ名
        `stiffiness`(原文ママtypo)を呼び出し元が正しい綴りへ変換して
        渡す前提)。
      parent_of: {骨名: 親骨名 または None}(アーマチュアルートはNone)。
      children_of: {骨名: [子骨名, ...]}(VRM0のサブツリー線形化に使う)。
      bone_names: アーマチュアに実在する骨名の列(VRMのSpringBone定義が
        実際にはインポートされなかった骨を参照している場合の防御用)。

    どちらの形式も、anchorが解決できない(親骨が無い/アーマチュアルート
    直下)エントリ、または有効な骨が1つも無いエントリは黙ってスキップ
    する(極端な編集ミス以外では発生しない構成のため、警告なしでよい
    ——step01側のログ`springbone components extracted: N`件数で
    間接的に確認できる)。

    **重複排除(dev#1508 W1b実データ検証、work\\night_20260817\\laneG、
    AliciaSolid_vrm-0.51.vrmで発見)**: VRM Addon for Blenderは、VRM0.0
    ファイルをインポートすると`vrm0.secondary_animation.bone_groups`
    (本来の一次データ)に加えて、`spring_bone1.springs`(VRM1.0互換ビュー)
    にも**同じ揺れ物データを自動移植した「影」を同時に生成する**(実測:
    AliciaSolid_vrm-0.51.vrm(VRM0.0)は`vrm0.bone_groups`3件(計18 root)
    かつ`spring_bone1.springs`にも同じ18件が現れる——本モジュールの
    docstring執筆時点までの理解だった「VRM1ファイルはspring_bone1のみ・
    VRM0ファイルはvrm0.bone_groupsのみが埋まる」という前提は誤りだった。
    逆方向(VRM1ファイルをvrm0.bone_groupsへ逆移植)は発生しない、
    Seed-san.vrm(純VRM1.0)実測で確認済み: `vrm0.bone_groups`は常に空)。
    対処として、`(anchor, chains)`が完全一致するエントリは2件目以降を
    捨てる(旧`extract_spring_roots()`が`sorted({...})`という集合演算で
    暗黙に行っていたのと同じ重複排除を、こちらでも明示的に行う)。
    VRM0由来(直接データ)をVRM1由来(移植ビュー)より優先するため、
    VRM0を先に処理してから未出現のVRM1分だけ追加する——値は移植で
    保持される前提のため実害は無いはずだが、より直接的なソースを
    優先するほうが将来の移植ロジック変更に対して頑健。"""
    names = set(bone_names)
    components: List[Dict[str, object]] = []
    seen: set = set()

    def _dedup_key(anchor, chains):
        return (anchor, tuple(tuple(c) for c in chains))

    for bg in vrm0_bone_groups or []:
        params = _bone_group_params(bg)
        for root in bg.get("bones") or []:
            if not root or root not in names:
                continue
            anchor = parent_of.get(root)
            if not anchor:
                continue
            chains = linear_chains_from_root(root, children_of)
            if not chains:
                continue
            key = _dedup_key(anchor, chains)
            if key in seen:
                continue
            seen.add(key)
            components.append({
                "anchor": anchor,
                "chains": chains,
                "params": dict(params),
            })

    for spring in vrm1_springs or []:
        raw_joints = spring.get("joints") or []
        joints = [j for j in raw_joints
                  if j.get("bone_name") and j["bone_name"] in names]
        if not joints:
            continue
        root = joints[0]["bone_name"]
        anchor = parent_of.get(root)
        if not anchor:
            continue
        chain = [j["bone_name"] for j in joints]
        key = _dedup_key(anchor, [chain])
        if key in seen:
            continue
        seen.add(key)
        components.append({
            "anchor": anchor,
            "chains": [chain],
            "params": _spring_params(joints[0]),
        })

    return components
