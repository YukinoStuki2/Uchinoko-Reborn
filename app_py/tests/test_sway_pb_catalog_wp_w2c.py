# test_sway_pb_catalog_wp_w2c.py -- dev#1508 列車計画W2c(揺れもの一覧の
# PB単位表示化・段1)。app_py\ui\sway_pb_catalog.py の単体テスト
# (tkinter非依存、実tk窓は開かない)。
#
# 正本: .devonly\docs\sway\sway_pbunit_design\DESIGN.md §4-5 / .devonly\docs\sway\sway_wrapup\SPEC.md §2。
from __future__ import annotations

import json
import os
import sys

HERE_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_PY_DIR = os.path.dirname(HERE_DIR)
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)
_ROOT_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_ROOT_DIR, "pipeline", "py")
if _PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_PY_DIR)

from ui import sway_pb_catalog as m  # noqa: E402

_SYNTHETIC_FIXTURE = os.path.join(
    _APP_PY_DIR, "tests", "fixtures", "physbones_synthetic_35.json")


def _load_synthetic_doc() -> dict:
    with open(_SYNTHETIC_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. $GUID尾の表示用削り(正の対照+負の対照)。
# ---------------------------------------------------------------------------

def test_strip_guid_tail_removes_standard_uuid_suffix():
    name = "Lower Arm.L.001$8aba0be2-2624-4628-8e98-ee7c23bd55fc"
    assert m.strip_guid_tail(name) == "Lower Arm.L.001"


def test_strip_guid_tail_negative_non_guid_dollar_suffix_untouched():
    """負の対照: $の後がGUID形式でなければ削らない(保守的な正規表現)。"""
    assert m.strip_guid_tail("$notarealguid") == "$notarealguid"
    assert m.strip_guid_tail("Weapon$Slot1") == "Weapon$Slot1"


def test_strip_guid_tail_negative_one_char_short_guid_untouched():
    """負の対照: 1文字短いだけの疑似GUID(12桁の最後の群が11桁)は削らない
    (正規表現の精度確認)。"""
    almost = "Bone$12345678-1234-1234-1234-1234567890"  # 最後の群が11桁
    assert m.strip_guid_tail(almost) == almost


def test_strip_guid_tail_plain_name_and_empty_untouched():
    assert m.strip_guid_tail("PlainBoneName") == "PlainBoneName"
    assert m.strip_guid_tail("") == ""
    assert m.strip_guid_tail(None) == ""


# ---------------------------------------------------------------------------
# 2. flatten_physbone_units: 1コンポーネント=1行(核心)。
# ---------------------------------------------------------------------------

def test_multi_chain_pb_becomes_a_single_unit_not_two_rows():
    """スカート等の多房PB(旧粒度なら2行に割れていた)が1行にまとまること。"""
    entries = [{
        "anchor": "Hips", "pb_object_name": "Skirt",
        "chains": [["Skirt_F_01", "Skirt_F_02"], ["Skirt_B_01", "Skirt_B_02"]],
    }]
    units = m.flatten_physbone_units(entries)
    assert len(units) == 1
    u = units[0]
    assert u["chain_count"] == 2
    assert u["bone_count"] == 4
    assert u["display_name"] == "Skirt"


def test_display_name_falls_back_to_guid_stripped_anchor_when_no_pb_object_name():
    """旧検体(pb_object_nameが無い)はanchorへフォールバックする
    (DESIGN.md §5段1「旧検体はフォールバックで動く」)。GUID尾も削られる。"""
    entries = [{
        "anchor": "Lower Arm.L.001$8aba0be2-2624-4628-8e98-ee7c23bd55fc",
        "chains": [["a", "b"]],
    }]
    units = m.flatten_physbone_units(entries)
    assert units[0]["display_name"] == "Lower Arm.L.001"
    assert units[0]["anchor"] == "Lower Arm.L.001$8aba0be2-2624-4628-8e98-ee7c23bd55fc"


def test_type_field_defaults_to_physbone_and_passes_through_springbone():
    pb_entries = [{"anchor": "A", "chains": [["b"]]}]
    sb_entries = [{"anchor": "A", "chains": [["b"]], "type": "springbone"}]
    assert m.flatten_physbone_units(pb_entries)[0]["type"] == "physbone"
    assert m.flatten_physbone_units(sb_entries)[0]["type"] == "springbone"


def test_entries_missing_anchor_or_chains_are_skipped():
    entries = [
        {"chains": [["b"]]},                # anchor欠落
        {"anchor": "A", "chains": []},       # chains空
        {"anchor": "A", "chains": [[]]},     # 空チェーンのみ
        {"anchor": "A", "chains": [["b"]]},  # 正常
    ]
    units = m.flatten_physbone_units(entries)
    assert len(units) == 1
    assert units[0]["anchor"] == "A"


def test_params_are_carried_through_when_present():
    entries = [{"anchor": "A", "chains": [["b"]], "params": {"pull": 0.5}}]
    assert m.flatten_physbone_units(entries)[0]["params"] == {"pull": 0.5}


def test_flatten_physbone_units_on_synthetic_fixture_yields_35_units():
    """Public artificial data retain 35 rows despite mixed chain counts.

    The missing upstream private-model fixture is not claimed as revalidated.
    """
    doc = _load_synthetic_doc()
    units = m.flatten_physbone_units(doc["physbones"])
    assert len(units) == 35
    assert sum(u["chain_count"] for u in units) > 35


# ---------------------------------------------------------------------------
# 3. unit_base_label: 曖昧解消。
# ---------------------------------------------------------------------------

def test_unit_base_label_disambiguates_when_display_name_collides():
    unit_a = {"display_name": "Hips", "chains": [["Tail_01", "Tail_02"]]}
    unit_b = {"display_name": "Hips", "chains": [["Skirt_F_01"]]}
    counts = {"Hips": 2}
    assert m.unit_base_label(unit_a, counts) == "Hips (Tail_01)"
    assert m.unit_base_label(unit_b, counts) == "Hips (Skirt_F_01)"


def test_unit_base_label_no_disambiguation_when_unique():
    unit = {"display_name": "Scarf", "chains": [["Scarf_01"]]}
    assert m.unit_base_label(unit, {"Scarf": 1}) == "Scarf"


# ---------------------------------------------------------------------------
# 4. resolve_unit_style / fanout_unit_assignments: 鎖単位ストアとの往復
#    (段1の核――旧スキーマとの等価性)。
# ---------------------------------------------------------------------------

def test_fanout_then_resolve_roundtrip_single_chain():
    """1房PBの往復: fan-outで作った鎖単位assignmentsをsaved_by_bones化して
    resolve_unit_styleに通すと、同じstyleが復元される(等価性の核)。"""
    anchor, chains, style = "Hips", [["Tail_01", "Tail_02"]], "hard"
    assignments = m.fanout_unit_assignments(anchor, chains, style)
    assert assignments == [{"bones": ["Hips", "Tail_01", "Tail_02"], "style": "hard"}]
    saved_by_bones = {tuple(a["bones"]): a["style"] for a in assignments}
    resolved_style, conflict = m.resolve_unit_style(anchor, chains, saved_by_bones, "none")
    assert resolved_style == "hard"
    assert conflict is False


def test_fanout_then_resolve_roundtrip_multi_chain_no_conflict():
    """多房PBの往復: 全房が同じstyleで塗られている(段1が常に行う塗り方)
    なら、conflict=Falseで単一styleへ復元される。"""
    anchor = "Hips"
    chains = [["Skirt_F_01", "Skirt_F_02"], ["Skirt_B_01", "Skirt_B_02"]]
    assignments = m.fanout_unit_assignments(anchor, chains, "soft")
    assert len(assignments) == 2
    saved_by_bones = {tuple(a["bones"]): a["style"] for a in assignments}
    resolved_style, conflict = m.resolve_unit_style(anchor, chains, saved_by_bones, "none")
    assert resolved_style == "soft"
    assert conflict is False


def test_resolve_unit_style_detects_conflict_and_uses_first_chain():
    """差異があるケース(DESIGN.md §4.3「先頭優先+差異ログ」): 房ごとに
    別styleが保存されている(旧データ・手編集等)場合、カタログ順で最初の
    房の値を採用し、conflict=Trueで異常を報告できること。"""
    anchor = "Hips"
    chains = [["Skirt_F_01"], ["Skirt_B_01"]]
    saved_by_bones = {
        ("Hips", "Skirt_F_01"): "hard",
        ("Hips", "Skirt_B_01"): "soft",
    }
    resolved_style, conflict = m.resolve_unit_style(anchor, chains, saved_by_bones, "none")
    assert resolved_style == "hard"  # 先頭(chains[0])優先
    assert conflict is True


def test_resolve_unit_style_no_saved_assignment_returns_none_style():
    resolved_style, conflict = m.resolve_unit_style("Hips", [["Tail_01"]], {}, "none")
    assert resolved_style == "none"
    assert conflict is False


def test_fanout_manual_row_has_no_anchor_prefix():
    """手動行(anchor=None)は旧sway_style_dialog._on_manual_add()と同じく、
    bones配列がanchorプレフィックス無しのchainそのものになる。"""
    assignments = m.fanout_unit_assignments(None, [["MyManualBone"]], "soft")
    assert assignments == [{"bones": ["MyManualBone"], "style": "soft"}]


# ---------------------------------------------------------------------------
# 5. sample_pb_units: 開発確認用サンプルが旧SAMPLE_CHAINSと1:1対応。
# ---------------------------------------------------------------------------

def test_sample_pb_units_matches_legacy_sample_chains_count_and_anchors():
    from ui import sway_chain_dialog as legacy
    units = m.sample_pb_units()
    assert len(units) == len(legacy.SAMPLE_CHAINS)
    for u, c in zip(units, legacy.SAMPLE_CHAINS):
        assert u["anchor"] == c["anchor"]
        assert u["chain_count"] == 1
        assert u["chains"][0] == c["bones"][1:]


# ---------------------------------------------------------------------------
# 6. is_unit_biased: sway_allocator._judge_pb_bias()の再利用(重複実装しない)。
# ---------------------------------------------------------------------------

def test_is_unit_biased_matches_sway_allocator_on_synthetic_fixture():
    """Catalog and allocator agree on 26 artificial biased components."""
    import sway_allocator

    doc = _load_synthetic_doc()
    units = m.flatten_physbone_units(doc["physbones"])
    biased_via_new_module = sum(1 for u in units if m.is_unit_biased(u)[0])

    allocator_units = sway_allocator.parse_physbones(doc)
    biased_via_allocator = sum(1 for u in allocator_units if u.is_biased)

    assert biased_via_new_module == biased_via_allocator == 26
    expected_anchors = (
        {f"hinge_{i:02}" for i in range(10)}
        | {f"polar_{i:02}" for i in range(8)}
        | {f"offset_{i:02}" for i in range(8)}
    )
    assert {u["anchor"] for u in units if m.is_unit_biased(u)[0]} == expected_anchors
    assert {u.anchor for u in allocator_units if u.is_biased} == expected_anchors


def test_is_unit_biased_none_type_is_unbiased():
    unit = {"type": "physbone", "params": {"limit_type": "None", "limit_rotation": [9, 9, 9]}}
    is_biased, reason = m.is_unit_biased(unit)
    assert is_biased is False
    assert reason == ""


def test_is_unit_biased_hinge_type_is_biased():
    unit = {"type": "physbone", "params": {"limit_type": "Hinge"}}
    assert m.is_unit_biased(unit)[0] is True


def test_is_unit_biased_springbone_is_always_unbiased():
    """SpringBoneは角度制限機構が無いため常に無偏向(SPEC.md §1)。"""
    unit = {"type": "springbone", "params": {"limit_type": "Hinge"}}  # 通常は
    # あり得ない値だが、type=="springbone"なら見ないことを確認する。
    assert m.is_unit_biased(unit)[0] is False


# ---------------------------------------------------------------------------
# 7. compute_forced_style_params: 「特殊ボーンを強制セットアップ」の値生成。
# ---------------------------------------------------------------------------

def test_compute_forced_style_params_maps_pb_values_on_synthetic_fixture():
    doc = _load_synthetic_doc()
    units = m.flatten_physbone_units(doc["physbones"])
    biased = [u for u in units if m.is_unit_biased(u)[0]]
    assert biased  # 前提: 偏向ユニットが存在すること
    u = biased[0]
    result = m.compute_forced_style_params(u["params"])
    assert set(result.keys()) == set(
        ["stiffness", "damping", "wdl", "wdr", "gravity_z", "limit_angle",
         "fake_pitch", "fake_roll", "fake_yaw"])
    # limit_angleは元のmax_angle_xそのまま。
    assert result["limit_angle"] == float(u["params"]["max_angle_x"])
    # fake_pitch/roll/yawは元のlimit_rotation[0]/[1]/[2]そのまま。
    rot = u["params"]["limit_rotation"]
    assert result["fake_pitch"] == float(rot[0])
    assert result["fake_roll"] == float(rot[1])
    assert result["fake_yaw"] == float(rot[2])


def test_compute_forced_style_params_base_values_come_from_quantized_builtin_preset():
    import sway_quantize
    import sway_styles_store

    params = {"pull": 0.348, "spring": 0.49, "limit_type": "Hinge",
              "limit_rotation": [0.0, 0.0, 0.0], "max_angle_x": 0.0}
    quant = sway_quantize.quantize_pb(0.348, 0.49)
    builtin_name = m._QUANT_TO_BUILTIN[quant]  # noqa: SLF001
    expected_base = sway_styles_store.BUILTIN_STYLE_PARAMS[builtin_name]
    result = m.compute_forced_style_params(params)
    assert result["stiffness"] == expected_base["stiffness"]
    assert result["damping"] == expected_base["damping"]
    assert result["wdl"] == expected_base["wdl"]
    assert result["wdr"] == expected_base["wdr"]


def test_compute_forced_style_params_clamps_out_of_range_values():
    params = {"pull": 0.5, "spring": 0.5, "max_angle_x": 999.0,
              "limit_rotation": [999.0, -999.0, 0.0]}
    result = m.compute_forced_style_params(params)
    assert result["limit_angle"] == 180.0  # PARAM_RANGES上限
    assert result["fake_pitch"] == 180.0
    assert result["fake_roll"] == -180.0


def test_compute_forced_style_params_missing_fields_use_base_preset_only():
    """max_angle_x/limit_rotationが無い(壊れた/未確認フィールドの)入力でも
    例外を投げず、ベースプリセットのみが返ること。"""
    result = m.compute_forced_style_params({"pull": 0.0, "spring": 0.0})
    assert result["limit_angle"] == 0.0
    assert result["fake_pitch"] == 0.0
