# -*- coding: utf-8 -*-
"""sway_allocator_wire.py の単体テスト(dev#1508 W2a、候補判定・量子化の
実結線)。

sway_allocator.py(W1c、候補判定・無偏向判定・量子化・グループ化)と
sway_assign.py(既存donor動的発見エンジン、無改変)を橋渡しする本モジュールの
純ロジック部分を、bpy非依存・実donor発見エンジンを絡めた統合形の両方で検証する。
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sway_allocator as sa  # noqa: E402
import sway_allocator_wire as m  # noqa: E402
import sway_assign  # noqa: E402

_FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "testdata", "sway_allocator")


def _load_fixture(name: str) -> dict:
    with open(os.path.join(_FIXTURE_DIR, name), encoding="utf-8") as f:
        return json.load(f)


# =====================================================================
# 入力アダプタ
# =====================================================================

def test_load_physbones_json_missing_path_returns_none():
    assert m.load_physbones_json(None) is None
    assert m.load_physbones_json("") is None
    assert m.load_physbones_json("C:/nonexistent/physbones.json") is None


def test_load_physbones_json_reads_file(tmp_path):
    p = tmp_path / "physbones.json"
    payload = {"format": sa.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Head", "chains": [["Ear.001"]], "params": {}},
    ]}
    p.write_text(json.dumps(payload), encoding="utf-8")
    result = m.load_physbones_json(str(p))
    assert result == payload


def test_load_physbones_json_malformed_returns_none(tmp_path):
    p = tmp_path / "physbones.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert m.load_physbones_json(str(p)) is None


def test_wrap_springbones_none_or_empty():
    assert m.wrap_springbones(None) == {"springbones": []}
    assert m.wrap_springbones([]) == {"springbones": []}


def test_wrap_springbones_preserves_entries():
    entries = [{"anchor": "Head", "chains": [["Hair.001"]], "params": {}}]
    assert m.wrap_springbones(entries) == {"springbones": entries}


# =====================================================================
# build_source_entries / compute_node_overrides
# =====================================================================

def _pb_entry(anchor, chain, pull=0.5, spring=0.5):
    return {
        "anchor": anchor, "chains": [chain],
        "params": {"pull": pull, "spring": spring, "limit_type": "None"},
    }


def _synthetic_donor_pairs():
    """1ノードだけの単純なpelvis系donor在庫(GrassBoss相当)。"""
    pairs = [("root", None), ("pelvis", "root")]
    for i in range(1, 4):
        parent = "pelvis" if i == 1 else f"NPC_GrassBoss001_Skin001_tail_{i-1:02d}"
        pairs.append((f"NPC_GrassBoss001_Skin001_tail_{i:02d}", parent))
    return pairs


def test_build_source_entries_splits_one_chain_per_entry():
    plan = sa.allocate(physbones_json={"physbones": [
        _pb_entry("Hips", ["Tail.001", "Tail.002"]),
    ]})
    pb_entries, sb_entries, chain_lookup = m.build_source_entries(plan)
    assert sb_entries == []
    assert len(pb_entries) == 1
    assert pb_entries[0] == {"anchor": "Hips", "chains": [["Tail.001", "Tail.002"]]}
    assert ("Hips", ("Tail.001", "Tail.002")) in chain_lookup


def test_build_source_entries_only_uses_accepted_groups():
    """負の対照: 偏向(除外)ユニットのチェーンはsource_entriesに現れない。"""
    biased_entry = {
        "anchor": "Hips", "chains": [["Scarf.001"]],
        "params": {"limit_type": "Hinge", "pull": 0.5, "spring": 0.5},
    }
    plan = sa.allocate(physbones_json={"physbones": [biased_entry]})
    pb_entries, sb_entries, chain_lookup = m.build_source_entries(plan)
    assert pb_entries == []
    assert sb_entries == []
    assert chain_lookup == {}


def test_compute_node_overrides_maps_donor_root_to_style_and_limit_angle():
    plan = sa.allocate(physbones_json={"physbones": [
        _pb_entry("Hips", ["Tail.001", "Tail.002", "Tail.003"]),
    ]})
    pb_entries, sb_entries, chain_lookup = m.build_source_entries(plan)
    result = sway_assign.assign_avatar_sway(
        physbone_entries=pb_entries, springbone_entries=sb_entries,
        donor_bone_pairs=_synthetic_donor_pairs(),
        source_parent_of={"Hips": None}, gender="Female",
        chibi_candidates=[],
    )
    assert len(result.assigned) == 1
    overrides = m.compute_node_overrides(result, chain_lookup)
    donor_root = result.assigned[0].donor.chain_root
    assert donor_root in overrides
    group = plan.accepted[0]
    assert overrides[donor_root]["style"] == group.style
    unit = group.units[0]
    assert overrides[donor_root]["limit_angle"] == unit.limit_angle


def test_compute_node_overrides_empty_when_nothing_assigned():
    plan = sa.allocate(physbones_json=None, springbones_json=None)
    pb_entries, sb_entries, chain_lookup = m.build_source_entries(plan)
    result = sway_assign.AssignmentResult()
    assert m.compute_node_overrides(result, chain_lookup) == {}


# =====================================================================
# 診断ログ(オーナー追加指示2026-08-16: 元設定原値+判定過程+成功時も+コライダー)
# =====================================================================

def test_diagnostics_lines_cover_all_units_including_accepted():
    """成功時にも全部出す: 採用ユニットもall_unitsに含まれ、ログに出る。"""
    plan = sa.allocate(physbones_json={"physbones": [
        _pb_entry("Hips", ["Tail.001", "Tail.002", "Tail.003"]),
    ]})
    lines = m.build_diagnostics_lines(plan)
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["sway_diag"] is True
    assert record["excluded_reason"] is None
    assert record["judged"]["style"] is not None
    assert record["original"]["type"] == "pb"
    assert record["original"]["pull"] == 0.5
    assert record["original"]["spring"] == 0.5


def test_diagnostics_lines_include_original_raw_values_pb():
    """元設定の原値(limitType/limitRotation/maxAngle/pull/spring/
    integration_type/pb_object_name/collider_count)が全部載る。"""
    entry = {
        "anchor": "Chest", "pb_object_name": "Scarf",
        "chains": [["Scarf.001", "Scarf.002"]],
        "params": {
            "pull": 0.3, "spring": 0.4, "limit_type": "Angle",
            "limit_rotation": [0, 0, 0], "max_angle_x": 45.0,
            "integration_type": "Simplified",
            "colliders": ["col:Chest#0", "col:Chest#1"],
        },
    }
    plan = sa.allocate(physbones_json={"physbones": [entry]})
    lines = m.build_diagnostics_lines(plan)
    record = json.loads(lines[0])
    orig = record["original"]
    assert orig["pb_object_name"] == "Scarf"
    assert orig["limit_type"] == "Angle"
    assert orig["limit_rotation"] == [0, 0, 0]
    assert orig["max_angle_x"] == 45.0
    assert orig["pull"] == 0.3
    assert orig["spring"] == 0.4
    assert orig["integration_type"] == "Simplified"
    assert orig["collider_count"] == 2
    # judged節: 無偏向(Angle+rotation全0)→採用→limit_angleがmax_angle_xの写し。
    assert record["judged"]["is_biased"] is False
    assert record["judged"]["limit_angle"] == 45.0
    # コライダー参照があった鎖には保護喪失の1行が付く。
    assert "collider_note" in record
    assert "2個" in record["collider_note"]


def test_diagnostics_lines_no_collider_note_when_zero_colliders():
    entry = _pb_entry("Hips", ["Tail.001"])
    plan = sa.allocate(physbones_json={"physbones": [entry]})
    lines = m.build_diagnostics_lines(plan)
    record = json.loads(lines[0])
    assert "collider_note" not in record


def test_diagnostics_lines_show_bias_exclusion_reason():
    """除外理由(偏向)が判定過程に残る。"""
    biased_entry = {
        "anchor": "Hips", "chains": [["Scarf.001"]],
        "params": {"limit_type": "Hinge", "pull": 0.5, "spring": 0.5},
    }
    plan = sa.allocate(physbones_json={"physbones": [biased_entry]})
    lines = m.build_diagnostics_lines(plan)
    record = json.loads(lines[0])
    assert record["excluded_reason"] is not None
    assert "偏向" in record["excluded_reason"]
    assert record["judged"]["is_biased"] is True


def test_diagnostics_lines_wiring_reflects_assignment_result():
    plan = sa.allocate(physbones_json={"physbones": [
        _pb_entry("Hips", ["Tail.001", "Tail.002", "Tail.003"]),
    ]})
    pb_entries, sb_entries, chain_lookup = m.build_source_entries(plan)
    result = sway_assign.assign_avatar_sway(
        physbone_entries=pb_entries, springbone_entries=sb_entries,
        donor_bone_pairs=_synthetic_donor_pairs(),
        source_parent_of={"Hips": None}, gender="Female",
        chibi_candidates=[],
    )
    lines = m.build_diagnostics_lines(plan, result, chain_lookup)
    record = json.loads(lines[0])
    assert len(record["wiring"]) == 1
    assert record["wiring"][0]["donor_root_bone"] is not None


def test_diagnostics_lines_wiring_shows_lost_reason_when_unwired():
    """配線待ち(donor在庫ゼロ)の場合、wiring_lost_reasonが載る。"""
    plan = sa.allocate(physbones_json={"physbones": [
        _pb_entry("UnknownRegionBone", ["Tail.001"]),
    ]})
    pb_entries, sb_entries, chain_lookup = m.build_source_entries(plan)
    result = sway_assign.assign_avatar_sway(
        physbone_entries=pb_entries, springbone_entries=sb_entries,
        donor_bone_pairs=_synthetic_donor_pairs(),
        source_parent_of={"UnknownRegionBone": None}, gender="Female",
        chibi_candidates=[],
    )
    lines = m.build_diagnostics_lines(plan, result, chain_lookup)
    record = json.loads(lines[0])
    assert record["wiring"][0]["donor_root_bone"] is None
    assert "wiring_lost_reason" in record["wiring"][0]


def test_diagnostics_lines_sb_uses_sb_specific_original_fields():
    entry = {
        "anchor": "Head", "pb_object_name": "TailHair", "chains": [["Hair.001"]],
        "params": {"stiffness": 0.5, "gravity_power": 0.1, "drag_force": 0.4},
    }
    plan = sa.allocate(springbones_json={"springbones": [entry]})
    lines = m.build_diagnostics_lines(plan)
    record = json.loads(lines[0])
    orig = record["original"]
    assert orig["type"] == "sb"
    assert orig["stiffness"] == 0.5
    assert orig["gravity_power"] == 0.1
    assert orig["drag_force"] == 0.4
    assert "limit_type" not in orig  # SB専用フィールドのみ(PB専用キーは載らない)


# =====================================================================
# wire_and_diagnose (高レベル入口)
# =====================================================================

def test_wire_and_diagnose_end_to_end():
    job_fragments, node_overrides, diagnostics_lines, report = m.wire_and_diagnose(
        physbone_entries=[_pb_entry("Hips", ["Tail.001", "Tail.002", "Tail.003"])],
        springbone_entries=[],
        donor_bone_pairs=_synthetic_donor_pairs(),
        source_parent_of={"Hips": None},
        gender="Female",
    )
    assert len(job_fragments) == 1
    assert len(node_overrides) == 1
    assert len(diagnostics_lines) == 1
    assert report["assigned_chains"] == 1
    assert report["lost_chains"] == 0


def test_wire_and_diagnose_empty_donor_pairs_skips_wiring_but_still_diagnoses():
    """donor_bone_pairsが空でも診断ログは出る(候補判定・量子化は独立した
    処理段)。配線結果だけが空になる。"""
    job_fragments, node_overrides, diagnostics_lines, report = m.wire_and_diagnose(
        physbone_entries=[_pb_entry("Hips", ["Tail.001"])],
        springbone_entries=[],
        donor_bone_pairs=[],
        source_parent_of={"Hips": None},
        gender="Female",
    )
    assert job_fragments == []
    assert node_overrides == {}
    assert len(diagnostics_lines) == 1
    record = json.loads(diagnostics_lines[0])
    assert record["excluded_reason"] is None  # 候補判定・量子化自体は独立して成功


# =====================================================================
# 受入3検体fixture(.devonly\docs\sway\sway_wrapup\SPEC.md §5b) -- comodo/flatapron
# =====================================================================

def _head_and_pelvis_donor_pairs():
    """comodo(耳名なしPBあり)受入検体用のdonor在庫。耳donor(head系)+
    尻尾donor(pelvis系)の両方を持つ。"""
    pairs = [("root", None), ("pelvis", "root"), ("head", "pelvis")]
    for i in range(1, 4):
        parent = "pelvis" if i == 1 else f"NPC_GrassBoss001_Skin001_tail_{i-1:02d}"
        pairs.append((f"NPC_GrassBoss001_Skin001_tail_{i:02d}", parent))
    pairs += [
        ("HeadEquip062_ear_01_l", "head"), ("HeadEquip062_ear_02_l", "HeadEquip062_ear_01_l"),
        ("HeadEquip062_ear_01_r", "head"), ("HeadEquip062_ear_02_r", "HeadEquip062_ear_01_r"),
    ]
    return pairs


def test_comodo_fixture_ears_are_wired_and_quantized():
    """dev#1508受入検体(SPEC.md §5b): comodo(耳名なし・PBあり、耳骨名=
    Head_L.001/Head_R.001)。旧仕様(名前ヒューリスティック)では耳名が無い
    ため既定なしに落ちていた——新仕様(候補=PB付きのみ、名前非依存)では
    耳が候補になり、無偏向・量子化されて実配線されることの機械実証。"""
    fixture = _load_fixture("physbones_comodo.json")
    job_fragments, node_overrides, diagnostics_lines, report = m.wire_and_diagnose(
        physbone_entries=fixture["physbones"], springbone_entries=[],
        donor_bone_pairs=_head_and_pelvis_donor_pairs(),
        source_parent_of={"Head_L.001": "Head", "Head_R.001": "Head", "Tail Root": "Hips"},
        gender="Female",
    )
    # 3ユニット(耳L/耳R/尻尾)すべてPB付き・無偏向(limit_type="None")のため
    # 候補になり、容量9以内で全て採用される。
    assert report["declared_chains"] == 3
    assert report["assigned_chains"] == 3
    assert len(diagnostics_lines) == 3
    for line in diagnostics_lines:
        record = json.loads(line)
        assert record["excluded_reason"] is None
        assert record["judged"]["is_biased"] is False
        assert record["judged"]["style"] is not None

    # 「comodoの耳が既定で揺れる」の機械実証: 実際に耳donor(HeadEquip062_ear系)
    # へウェイトが乗っている(=node_overridesに耳donorのroot_boneが含まれる)。
    ear_donors_used = [root for root in node_overrides if "ear" in root.lower()]
    assert ear_donors_used, f"耳が実配線されていない: node_overrides={node_overrides}"
    for root in ear_donors_used:
        assert node_overrides[root]["style"] in ("yawa", "futsuu", "kata")


def test_flatapron_fixture_hinge_biased_excluded():
    """dev#1508受入検体(SPEC.md §5b): flatapron(別Object+rootTransform
    指しPB、Hinge偏向の代表例)は無条件で偏向除外され、診断ログに理由が出る
    こと(負の対照——素のKPで揺らすとエプロン式の系統的めり込みが起きるため
    既定OFF)。"""
    fixture = _load_fixture("physbones_flatapron.json")
    job_fragments, node_overrides, diagnostics_lines, report = m.wire_and_diagnose(
        physbone_entries=fixture["physbones"], springbone_entries=[],
        donor_bone_pairs=_head_and_pelvis_donor_pairs(),
        source_parent_of={}, gender="Female",
    )
    assert job_fragments == []
    assert node_overrides == {}
    assert len(diagnostics_lines) == 1
    record = json.loads(diagnostics_lines[0])
    assert record["excluded_reason"] is not None
    assert "偏向" in record["excluded_reason"]
    assert record["judged"]["is_biased"] is True


def test_wire_and_diagnose_no_candidates_is_noop():
    job_fragments, node_overrides, diagnostics_lines, report = m.wire_and_diagnose(
        physbone_entries=[], springbone_entries=[],
        donor_bone_pairs=_synthetic_donor_pairs(),
        source_parent_of={}, gender="Female",
    )
    assert job_fragments == []
    assert node_overrides == {}
    assert diagnostics_lines == []
    assert report == {"declared_chains": 0, "assigned_chains": 0, "lost_chains": 0, "lost": []}
