# -*- coding: utf-8 -*-
"""test_sway_source_bones.py -- sway_source_bones.pyの単体テスト
(dev#1508 受入ゲート正本化)。実機・pak・Blenderに一切依存しない
(bpy非依存、純粋関数のみ)。sway_hub/sway_hub_wireを一切importしない
(独立性そのものを検査する趣旨、モジュールdocstring参照)。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_allocator  # noqa: E402
import sway_source_bones as ssb  # noqa: E402


def test_module_does_not_import_wiring_implementation():
    """構造的独立性の検査そのもの: 本モジュールのソースコードに
    `sway_hub`/`sway_hub_wire`への参照が一切無いことを固定する
    (自己参照検査を防ぐという設計意図が将来のリファクタで崩れないための
    回帰テスト)。"""
    src_path = os.path.join(_HERE, "sway_source_bones.py")
    with open(src_path, encoding="utf-8") as f:
        lines = f.readlines()
    import_lines = [ln.strip() for ln in lines
                    if ln.strip().startswith(("import ", "from "))]
    assert not any("sway_hub" in ln for ln in import_lines), import_lines


def _comodo_like_physbones():
    """comodo実データに近い「1anchorから2房分岐」構成(DIAG.md/
    work\\wp_w2a2d_comodo\\convert_log.txt実測パターンの再現)。
    素体房: Head_L.001 -> Head_L.002 -> Head_L.002_end
    衣装房: Head_L.001 -> Head_L.002 -> Head_L.003$guid
    (Head_L.002が両房で共有される分岐)。"""
    return {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Head_L.001",
         "chains": [["Head_L.002", "Head_L.002_end"],
                    ["Head_L.002", "Head_L.003$guid"]],
         "params": {"limit_type": "None", "pull": 0.348, "spring": 0.49}},
    ]}


def test_expand_unit_source_bones_comodo_ear_matches_hand_written_expectation():
    """fixture手書き期待値による固定(指揮者指示: comodo耳=Head_L.001含む
    3骨×2房を突き合わせる)。2房はHead_L.002を共有するため、独立骨名の
    合計はanchor+Head_L.002+Head_L.002_end+Head_L.003$guidの4本。"""
    physbones = _comodo_like_physbones()
    plan = sway_allocator.allocate(physbones_json=physbones)
    assert len(plan.accepted) == 1
    unit = plan.accepted[0].units[0]

    bones = ssb.expand_unit_source_bones(unit)
    assert bones == frozenset({
        "Head_L.001", "Head_L.002", "Head_L.002_end", "Head_L.003$guid",
    })
    assert "Head_L.001" in bones  # anchor自身(3骨×2房のうち共通の1本)


def test_expand_accepted_source_bones_includes_anchor_for_all_accepted_units():
    """必須要件(指揮者指示): 全採用PB/SBについて anchor ∈ ゲート対象集合。
    しっぽ(単鎖)+耳(2房分岐)の2ユニットで検査する。"""
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Tail Root", "chains": [["Tail.001", "Tail.002"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        {"anchor": "Head_L.001",
         "chains": [["Head_L.002", "Head_L.002_end"],
                    ["Head_L.002", "Head_L.003$guid"]],
         "params": {"limit_type": "None", "pull": 0.348, "spring": 0.49}},
    ]}
    plan = sway_allocator.allocate(physbones_json=physbones)
    assert len(plan.accepted) == 2  # tail優先で先頭、耳が2番目

    by_unit = ssb.expand_accepted_source_bones(plan)
    assert len(by_unit) == 2

    all_units = [u for g in plan.accepted for u in g.units]
    for unit in all_units:
        bones = by_unit[unit.key]
        assert unit.anchor in bones, (
            f"anchor {unit.anchor!r} missing from independently-expanded "
            f"source bone set for accepted unit {unit.key!r}")


def test_all_accepted_source_bone_names_flattens_everything():
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Tail Root", "chains": [["Tail.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        {"anchor": "Head_L.001", "chains": [["Head_L.002"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
    ]}
    plan = sway_allocator.allocate(physbones_json=physbones)
    names = ssb.all_accepted_source_bone_names(plan)
    assert names == frozenset({"Tail Root", "Tail.001", "Head_L.001", "Head_L.002"})


def test_accepted_anchor_names_returns_only_anchors_not_chain_bones():
    """dev#1508 hubwire final(公理検査): accepted_anchor_names()は
    anchor自身だけを返し、chains内の骨は含まない(all_accepted_source_
    bone_names()との違いの直接検査)。"""
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Tail Root", "chains": [["Tail.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        {"anchor": "Head_L.001", "chains": [["Head_L.002"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
    ]}
    plan = sway_allocator.allocate(physbones_json=physbones)
    anchors = ssb.accepted_anchor_names(plan)
    assert anchors == frozenset({"Tail Root", "Head_L.001"})
    assert "Tail.001" not in anchors
    assert "Head_L.002" not in anchors


def test_accepted_anchor_names_empty_when_no_accepted():
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Chest", "chains": [["scarf_01"]],
         "params": {"limit_type": "Hinge", "pull": 0.5, "spring": 0.5}},
    ]}
    plan = sway_allocator.allocate(physbones_json=physbones)
    assert ssb.accepted_anchor_names(plan) == frozenset()


def test_expand_accepted_source_bones_empty_when_no_accepted():
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Chest", "chains": [["scarf_01"]],
         "params": {"limit_type": "Hinge", "pull": 0.5, "spring": 0.5}},
    ]}
    plan = sway_allocator.allocate(physbones_json=physbones)
    assert not plan.accepted  # Hinge -> biased -> excluded
    assert ssb.expand_accepted_source_bones(plan) == {}
    assert ssb.all_accepted_source_bone_names(plan) == frozenset()


# ---- 負の対照(意図的に壊すと検出されることの証明) ----

def test_bone_group_keys_maps_each_bone_to_its_group():
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Tail Root", "chains": [["Tail.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        {"anchor": "Head_L.001", "chains": [["Head_L.002"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
    ]}
    plan = sway_allocator.allocate(physbones_json=physbones)
    mapping = ssb.bone_group_keys(plan)
    tail_group = plan.accepted[0]
    ear_group = plan.accepted[1]
    tail_gk = f"{tail_group.group_key[0]}|{tail_group.group_key[1]}"
    ear_gk = f"{ear_group.group_key[0]}|{ear_group.group_key[1]}"
    assert mapping["Tail Root"] == frozenset({tail_gk})
    assert mapping["Tail.001"] == frozenset({tail_gk})
    assert mapping["Head_L.001"] == frozenset({ear_gk})
    assert mapping["Head_L.002"] == frozenset({ear_gk})
    assert tail_gk != ear_gk


def test_expand_unit_source_bones_would_miss_anchor_if_naively_flattening_chains_only():
    """負の対照: dev#1508バグの構造そのものを再現し、
    「chainsだけをflattenする(anchorを足し忘れる)」実装だと、この単体
    テストが検出する不整合を再現する——`expand_unit_source_bones()`が
    正しくanchorを含めていることの裏返しの証明。"""
    physbones = _comodo_like_physbones()
    plan = sway_allocator.allocate(physbones_json=physbones)
    unit = plan.accepted[0].units[0]

    buggy_bones = set()
    for chain in unit.chains:  # dev#1508と同型の欠陥: anchorを足し忘れる
        buggy_bones.update(chain)
    assert "Head_L.001" not in buggy_bones  # バグ動作の再現(anchor欠落)

    correct_bones = ssb.expand_unit_source_bones(unit)
    assert "Head_L.001" in correct_bones  # 修正後の正しい動作
