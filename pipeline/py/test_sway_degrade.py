# -*- coding: utf-8 -*-
"""test_sway_degrade.py -- sway_degrade.pyの単体テスト(dev#1508
graceful-degrade、night_20260817 laneI)。実機・pak・Blenderに一切依存
しない(bpy非依存、純粋関数のみ)。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_allocator  # noqa: E402
import sway_degrade as sd  # noqa: E402
import sway_source_bones as ssb  # noqa: E402
import sway_source_gate  # noqa: E402


def _seedsan_like_physbones(n_hair=7):
    """Seed-san実データに近い構成の縮小版: しっぽ1本+複数の類似2骨ヘア
    チェーン(laneG_PROGRESS.mdの「hair_A〜hair_G、7本、ほぼ同一トポロジ
    2骨チェーン」を模したsynthetic fixture)。"""
    entries = [
        {"anchor": "Tail Root", "chains": [["Tail.001", "Tail.002"]],
         "params": {"stiffness": 0.8, "gravity_power": 0.0, "drag_force": 0.4}},
    ]
    for i in range(n_hair):
        letter = chr(ord("A") + i)
        entries.append({
            "anchor": f"hair_{letter}",
            "chains": [[f"hair_{letter}.001", f"hair_{letter}.002"]],
            "params": {"stiffness": 0.8, "gravity_power": 0.0, "drag_force": 0.4},
        })
    return {"format": sway_allocator.SPRINGBONES_FORMAT, "springbones": entries}


# ---------------------------------------------------------------------
# attribute_bones_to_units
# ---------------------------------------------------------------------

def test_attribute_bones_to_units_maps_failed_bone_to_its_own_unit_only():
    """1鎖だけFAILしたとき、そのunit.keyだけが返り、無関係な他の鎖の
    unit.keyは含まれない(グループ粒度への道連れが起きないことの検査)。"""
    springbones = _seedsan_like_physbones(n_hair=3)
    plan = sway_allocator.allocate(springbones_json=springbones)
    bone_unit_keys = ssb.bone_unit_keys(plan)

    attributable, unattributed = sd.attribute_bones_to_units(
        ["hair_B.001"], bone_unit_keys)

    assert not unattributed
    assert len(attributable) == 1
    (only_key,) = attributable
    assert "hair_B" in only_key
    assert "hair_A" not in only_key
    assert "hair_C" not in only_key


def test_attribute_bones_to_units_unattributed_when_bone_unknown():
    """負の対照: bone_unit_keys_mapに存在しないボーン名(構造的異常)は
    unattributedへ回る(=個別除外ではなく「帰属できない」扱いになる)。"""
    attributable, unattributed = sd.attribute_bones_to_units(
        ["not_a_real_bone"], {"hair_A.001": frozenset({"sb:hair_A#0"})})
    assert not attributable
    assert unattributed == frozenset({"not_a_real_bone"})


# ---------------------------------------------------------------------
# detect_weight_collisions
# ---------------------------------------------------------------------

def test_detect_weight_collisions_flags_many_to_one_mapping():
    donor_of = {"hair_A.001": "donor_X", "hair_B.001": "donor_X", "hair_C.001": "donor_Y"}
    weighted = {"hair_A.001", "hair_B.001", "hair_C.001"}
    collisions = sd.detect_weight_collisions(donor_of, weighted)
    assert collisions == {"donor_X": ["hair_A.001", "hair_B.001"]}


def test_detect_weight_collisions_ignores_unweighted_bones():
    """負の対照: 同じdonorへ2本写像されていても、片方が実weightを持たない
    (weighted集合に無い)なら衝突として検出しない(実害なし)。"""
    donor_of = {"hair_A.001": "donor_X", "hair_B.001": "donor_X"}
    weighted = {"hair_A.001"}  # hair_B.001は無weight
    collisions = sd.detect_weight_collisions(donor_of, weighted)
    assert collisions == {}


def test_detect_weight_collisions_no_false_positive_on_clean_1to1_mapping():
    donor_of = {"hair_A.001": "donor_X", "hair_B.001": "donor_Y"}
    weighted = {"hair_A.001", "hair_B.001"}
    assert sd.detect_weight_collisions(donor_of, weighted) == {}


def test_detect_weight_collisions_exempts_expected_merge_groups_dev1551():
    """dev#1551 chain-length-fit WP: 節数フィット(先端マージ)が意図的に
    作った衝突は、`expected_merge_groups`に一致すればFAILしない
    (ADD合算は仕様であり縮退の対象ではない)。"""
    donor_of = {"tail_04": "donor_X", "tail_05": "donor_X"}
    weighted = {"tail_04", "tail_05"}
    expected = frozenset({frozenset({"tail_04", "tail_05"})})
    assert sd.detect_weight_collisions(donor_of, weighted, expected) == {}


def test_detect_weight_collisions_exempts_subset_of_larger_merge_group_dev1551():
    """dev#1551実機検証で判明した実ケース: マージグループに無ウェイトの
    元要素(`_end`合成マーカー)が混ざっていると、`weighted_bones`フィルタ
    後に実際衝突として現れる集合はマージグループ本体より**小さい**
    (部分集合)。`expected_merge_groups`は3要素([tail_04, tail_05,
    tail_05_end])だが、実際の衝突検出は無ウェイトのtail_05_endを含まない
    2要素だけになる——それでも部分集合として正しく除外されることを
    確認する。"""
    donor_of = {"tail_04": "donor_X", "tail_05": "donor_X", "tail_05_end": "donor_X"}
    weighted = {"tail_04", "tail_05"}  # tail_05_endは無ウェイト
    expected = frozenset({frozenset({"tail_04", "tail_05", "tail_05_end"})})
    assert sd.detect_weight_collisions(donor_of, weighted, expected) == {}


def test_detect_weight_collisions_negative_control_unexpected_merge_still_flagged():
    """負の対照: `expected_merge_groups`に載っていない衝突は、たとえ他の
    グループが除外指定されていても従来どおり検出されることを確認する。"""
    donor_of = {"tail_04": "donor_X", "tail_05": "donor_X", "hair_A": "donor_Y", "hair_B": "donor_Y"}
    weighted = {"tail_04", "tail_05", "hair_A", "hair_B"}
    expected = frozenset({frozenset({"tail_04", "tail_05"})})  # hair_A/Bは含まない
    collisions = sd.detect_weight_collisions(donor_of, weighted, expected)
    assert collisions == {"donor_Y": ["hair_A", "hair_B"]}


# ---------------------------------------------------------------------
# build_lab_overrides
# ---------------------------------------------------------------------

def test_build_lab_overrides_disables_given_keys_and_accumulates():
    first = sd.build_lab_overrides({"sb:hair_B#1"})
    assert first["sb:hair_B#1"].enabled is False

    second = sd.build_lab_overrides({"sb:hair_C#2"}, existing=first)
    assert set(second) == {"sb:hair_B#1", "sb:hair_C#2"}
    assert second["sb:hair_B#1"].enabled is False
    assert second["sb:hair_C#2"].enabled is False


def test_lab_overrides_actually_excludes_the_unit_from_allocate():
    """統合検査: build_lab_overrides()の出力をsway_allocator.allocate()へ
    実際に渡すと、対象unitがrejected_unitsへ回り、他のunitは無傷のまま
    accepted扱いになることを確認する(「鎖単位の除外」がsway_allocator側の
    実際の挙動として機能することの証明)。"""
    springbones = _seedsan_like_physbones(n_hair=3)
    plan0 = sway_allocator.allocate(springbones_json=springbones)
    bone_unit_keys = ssb.bone_unit_keys(plan0)
    target_key = next(iter(bone_unit_keys["hair_B.001"]))

    excl = sd.build_lab_overrides({target_key})
    plan1 = sway_allocator.allocate(springbones_json=springbones, lab_assignments=excl)

    accepted_keys = {u.key for g in plan1.accepted for u in g.units}
    assert target_key not in accepted_keys
    # 他の鎖(しっぽ+hair_A+hair_C)は無傷で採用され続ける
    assert len(accepted_keys) == len(plan0.all_units) - 1


# ---------------------------------------------------------------------
# ExclusionEntry / ExclusionReport
# ---------------------------------------------------------------------

def test_make_exclusion_entry_parses_unit_key():
    e = sd.make_exclusion_entry("sb:hair_E#4", sd.STAGE_GATE_TRANSFORM, "scale mismatch")
    assert e.source == "sb"
    assert e.anchor == "hair_E"
    assert e.stage == sd.STAGE_GATE_TRANSFORM
    assert e.unit_key == "sb:hair_E#4"


def test_make_exclusion_entry_handles_malformed_key_safely():
    """負の対照: 想定外の形式でもdie()せず、安全側の表示になる。"""
    e = sd.make_exclusion_entry("garbage", sd.STAGE_SYSTEMIC_DISABLE, "x")
    assert e.source == "?"
    assert e.anchor == "garbage"


def test_exclusion_report_to_dict_schema():
    entries = (sd.make_exclusion_entry("sb:hair_E#4", sd.STAGE_GATE_TRANSFORM, "reason1"),)
    report = sd.ExclusionReport(gender="male", total_units=9, fully_disabled=False,
                                 excluded=entries)
    d = report.to_dict()
    assert d["format"] == sd.FORMAT
    assert d["gender"] == "male"
    assert d["total_units"] == 9
    assert d["fully_disabled"] is False
    assert len(d["excluded"]) == 1
    assert d["excluded"][0]["unit_key"] == "sb:hair_E#4"


def test_exclusion_report_empty_still_serializes_with_empty_list():
    """laneI指示書「除外ゼロでも空で書く」の直接検査。"""
    report = sd.ExclusionReport(gender="female", total_units=0, fully_disabled=False)
    d = report.to_dict()
    assert d["excluded"] == []


# ---------------------------------------------------------------------
# explains_zero_chains(preflightの縮退認識ヘルパー)
# ---------------------------------------------------------------------

def test_explains_zero_chains_true_when_fully_disabled():
    report = {"total_units": 9, "fully_disabled": True, "excluded": []}
    assert sd.explains_zero_chains(report) is True


def test_explains_zero_chains_false_when_partial_exclusion_not_fully_disabled():
    """負の対照(最重要): 「一部だけ除外し、まだ鎖が残っている」ケースで
    0鎖になるのはおかしい(バグ)ため、fully_disabled=Falseなら
    explains_zero_chainsはFalseのまま=fail-closedを維持する。"""
    report = {"total_units": 9, "fully_disabled": False,
              "excluded": [{"unit_key": "sb:hair_E#4"}]}
    assert sd.explains_zero_chains(report) is False


def test_explains_zero_chains_false_when_report_missing():
    """負の対照: sway_exclusions.json自体が存在しない(=旧バージョンの
    step02、または本レーンの縮退ロジックが実際には走らなかった)場合は、
    0鎖を正当化しない(fail-closed維持)。"""
    assert sd.explains_zero_chains(None) is False
    assert sd.explains_zero_chains({}) is False


def test_explains_zero_chains_true_when_no_units_at_all():
    report = {"total_units": 0, "fully_disabled": False, "excluded": []}
    assert sd.explains_zero_chains(report) is True


# ---------------------------------------------------------------------
# WARN文言
# ---------------------------------------------------------------------

def test_warn_line_uses_non_blaming_wording():
    e = sd.make_exclusion_entry("sb:hair_E#4", sd.STAGE_GATE_TRANSFORM, "scale mismatch")
    line = sd.format_warn_line(e)
    assert "will not sway this time" in line
    for banned in ("excess", "invalid", "broken", "corrupt"):
        assert banned not in line.lower()


def test_warn_line_is_ascii_only_diagnostic_log_policy_dev29():
    """診断ログ英語固定(dev#29、tests\\diag_log_lint参照)の直接検査:
    WARN文言に非ASCII文字(日本語含む)が混入しないことを固定する。"""
    e = sd.make_exclusion_entry("sb:hair_E#4", sd.STAGE_GATE_TRANSFORM, "scale mismatch")
    line = sd.format_warn_line(e)
    assert line.isascii(), line


def test_warn_lines_one_per_entry():
    entries = [
        sd.make_exclusion_entry("sb:hair_E#4", sd.STAGE_GATE_TRANSFORM, "r1"),
        sd.make_exclusion_entry("sb:hair_F#5", sd.STAGE_GATE_AXIOM, "r2"),
    ]
    lines = sd.format_warn_lines(entries)
    assert len(lines) == 2
    assert "hair_E" in lines[0]
    assert "hair_F" in lines[1]


# ---------------------------------------------------------------------
# all_unit_keys
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# 負の対照(統合、laneI指示書4d「意図的に配線を壊した入力で除外+完走に
# なり、壊れた配線のまま出荷にならないこと」): 縮退ループが使う一連の
# 汎用純関数(bone_unit_keys/attribute_bones_to_units/build_lab_overrides/
# sway_allocator.allocate)を、Blenderなしで直接つないで再現する。
#
# dev#1551(断言ゲート警告格下げ、2026-08-18オーナー裁定確定)以降、
# step02_retarget.py `_sway_degrade_precheck()`は`check_bone_transform()`の
# 不一致(位置/向き/スケール)をもう`failed_bone_reasons`(=この除外機構への
# 入力)に積まない——`check_bone_transform()`は本テストでは「除外機構
# そのものが正しく動く」ことを示すための**合成FAILトリガー**として
# 引き続き使う(この関数自体はdev#1551で変更していない)だけであり、
# 実際のパイプラインでtransform不一致がこの経路を通ることを主張しない。
# 実データでの同型実証(hair_Eが同じ仕組みで除外され他8鎖は無傷で完走)は
# 支点公理違反/ウェイト衝突/donor欠落などdev#1551後も除外対象のままの
# FAIL種別で今も成立する——本テストはその除外機構自体を固定する回帰テスト。
# ---------------------------------------------------------------------

def test_negative_control_broken_chain_excluded_others_survive_intact():
    """3鎖(しっぽ+hair_A+hair_B)のうち、hair_Bのdonor配置だけを意図的に
    破壊(位置を10m吹き飛ばす)する。縮退ループの1attemptぶんの判定
    (FAIL検出 -> 帰属 -> 除外、ここでは`check_bone_transform()`を合成FAIL
    トリガーとして流用)を再現し、
    - hair_Bのunit.keyだけがlab_overridesへ入る(他の2鎖は無傷)
    - 除外後にsway_allocator.allocate()を再実行すると、hair_Bだけが
      非採用(rejected_units)へ回り、しっぽ+hair_Aは無傷でaccepted
      に残る(「壊れた配線のまま出荷」にならないことの直接証明——
      壊れたunitはaccepted集合に一切現れない)
    ことを検証する。"""
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Tail Root", "chains": [["Tail.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        {"anchor": "hair_A", "chains": [["hair_A.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        {"anchor": "hair_B", "chains": [["hair_B.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
    ]}
    plan0 = sway_allocator.allocate(physbones_json=physbones)
    assert {u.key for g in plan0.accepted for u in g.units} == {
        "pb:Tail Root#0", "pb:hair_A#1", "pb:hair_B#2"}

    # donor配置が破壊されたケースの再現: hair_B系統だけ位置が10m吹き飛ぶ
    # (`check_bone_transform`の位置epsilon=1e-4mを大きく超える、
    # sway_source_gate.pyのEPS_POS参照)。他2鎖は完全一致(正常)。
    def _transform_fail(bone):
        broken = bone.startswith("hair_B")
        src = ([0.0, 0.0, 1.0], [0.0, 0.0, 1.1], [1.0, 1.0, 1.0])
        dst = ([10.0, 0.0, 1.0], [10.0, 0.0, 1.1], [1.0, 1.0, 1.0]) if broken else src
        return sway_source_gate.check_bone_transform(*src, *dst)

    all_bones = ["Tail Root", "Tail.001", "hair_A", "hair_A.001", "hair_B", "hair_B.001"]
    failed_bones = [b for b in all_bones if _transform_fail(b)]
    assert failed_bones == ["hair_B", "hair_B.001"]  # 破壊した鎖だけがFAIL

    bone_unit_keys = ssb.bone_unit_keys(plan0)
    attributable, unattributed = sd.attribute_bones_to_units(failed_bones, bone_unit_keys)
    assert not unattributed  # 帰属できないボーンは無い(正常に特定できた)
    assert attributable == frozenset({"pb:hair_B#2"})  # 破壊した鎖だけ帰属

    lab_overrides = sd.build_lab_overrides(attributable)
    plan1 = sway_allocator.allocate(physbones_json=physbones, lab_assignments=lab_overrides)

    accepted_keys = {u.key for g in plan1.accepted for u in g.units}
    assert "pb:hair_B#2" not in accepted_keys  # 壊れた鎖は出荷対象から消えている
    assert accepted_keys == {"pb:Tail Root#0", "pb:hair_A#1"}  # 他2鎖は無傷で残る

    rejected_keys = {u.key: u.excluded_reason for u in plan1.rejected_units}
    assert "pb:hair_B#2" in rejected_keys  # 除外理由つきで記録される(黙って消えない)


def test_negative_control_unattributed_failure_triggers_systemic_disable_signal():
    """負の対照(帰属できないケース): FAILしたボーン名がbone_unit_keys_map
    に見つからない(構造的異常、通常起きないはずのケース)場合、
    `attribute_bones_to_units()`はunattributedへ回し、個別除外ではなく
    「sway全OFFへ倒すべき」という判定材料(unattributed非空)を呼び出し側
    (`run_sway_degrade_loop()`)へ正しく伝える——個別除外を試みて誤って
    「たぶん直った」ことにしない。"""
    bone_unit_keys = {"Tail Root": frozenset({"pb:Tail Root#0"}),
                       "Tail.001": frozenset({"pb:Tail Root#0"})}
    failed_bones = ["Tail Root", "ghost_bone_not_in_any_unit"]
    attributable, unattributed = sd.attribute_bones_to_units(failed_bones, bone_unit_keys)
    assert unattributed == frozenset({"ghost_bone_not_in_any_unit"})
    # 呼び出し側はunattributedが非空ならリトライではなく即座にsway全OFFへ
    # 倒す(run_sway_degrade_loop()の分岐と同じ判定式)。
    should_go_systemic = bool(unattributed)
    assert should_go_systemic is True


# ---------------------------------------------------------------------
# dev#1625(2026-08-21 オーナー裁定): 姿勢不一致ハブの最小切除。
#
# `sway_source_gate.bones_exceeding_posture_cull_threshold()`が実際に
# 検出した「切除すべきボーン」を、既存の除外機構(attribute_bones_to_units
# -> build_lab_overrides -> sway_allocator.allocate())へそのまま流し込み、
# `_sway_degrade_precheck()`/`run_sway_degrade_loop()`が実プロダクション
# コードで行うのと同じ配線をBlenderなしで再現する(上の
# test_negative_control_broken_chain_excluded_others_survive_intact()の
# 「合成FAILトリガー」パターンをdev#1625の実トリガーに差し替えたもの)。
# ---------------------------------------------------------------------

def _t(pos, tail=None):
    if tail is None:
        tail = (pos[0], pos[1], pos[2] + 1.0)
    return {"pos": list(pos), "tail": list(tail), "scale": [1.0, 1.0, 1.0]}


def test_dev1625_posture_mismatch_excludes_only_the_broken_hub():
    """3鎖(しっぽ+hair_A+hair_B)のうち、hair_Bのdonor配置だけを意図的に
    大きく傾ける(dev#1625実報告のAvatarSample_A.vrmを模した45.86度)。
    posture cull閾値超えの骨だけが除外対象unit.keyへ帰属し、他2鎖は無傷で
    accepted集合に残ることを確認する。"""
    import math
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Tail Root", "chains": [["Tail.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        {"anchor": "hair_A", "chains": [["hair_A.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        {"anchor": "hair_B", "chains": [["hair_B.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
    ]}
    plan0 = sway_allocator.allocate(physbones_json=physbones)
    assert {u.key for g in plan0.accepted for u in g.units} == {
        "pb:Tail Root#0", "pb:hair_A#1", "pb:hair_B#2"}

    all_bones = ["Tail Root", "Tail.001", "hair_A", "hair_A.001", "hair_B", "hair_B.001"]
    group_targets = {b: f"donor_{b}" for b in all_bones}
    src_t = {b: _t((0, 0, 0), tail=(0, 0, 1)) for b in all_bones}
    dst_t = {f"donor_{b}": _t((0, 0, 0), tail=(0, 0, 1)) for b in all_bones}
    # hair_B系統だけ、donorの向きを45.86度傾ける(実報告値そのもの)。
    angle_rad = math.radians(45.86)
    for b in ("hair_B", "hair_B.001"):
        dst_t[f"donor_{b}"] = _t(
            (0, 0, 0), tail=(math.sin(angle_rad), 0, math.cos(angle_rad)))

    culled = sway_source_gate.bones_exceeding_posture_cull_threshold(
        all_bones, src_t, dst_t, group_targets)
    assert set(culled.keys()) == {"hair_B", "hair_B.001"}

    bone_unit_keys = ssb.bone_unit_keys(plan0)
    attributable, unattributed = sd.attribute_bones_to_units(culled.keys(), bone_unit_keys)
    assert not unattributed
    assert attributable == frozenset({"pb:hair_B#2"})

    lab_overrides = sd.build_lab_overrides(attributable)
    plan1 = sway_allocator.allocate(physbones_json=physbones, lab_assignments=lab_overrides)
    accepted_keys = {u.key for g in plan1.accepted for u in g.units}
    assert "pb:hair_B#2" not in accepted_keys
    assert accepted_keys == {"pb:Tail Root#0", "pb:hair_A#1"}  # 他2鎖は無傷


def test_dev1625_negative_control_small_mismatch_culls_nothing():
    """負の対照: 全鎖のdonor向きが較正済み白検体の実測最大値(13.68度、
    prefab_flatapron)相当以下であれば、1本も切除されない
    (=「白検体の変換で切除0件」の直接検証)。"""
    import math
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Tail Root", "chains": [["Tail.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        {"anchor": "hair_A", "chains": [["hair_A.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
    ]}
    all_bones = ["Tail Root", "Tail.001", "hair_A", "hair_A.001"]
    group_targets = {b: f"donor_{b}" for b in all_bones}
    src_t = {b: _t((0, 0, 0), tail=(0, 0, 1)) for b in all_bones}
    angle_rad = math.radians(13.68)
    dst_t = {f"donor_{b}": _t(
        (0, 0, 0), tail=(math.sin(angle_rad), 0, math.cos(angle_rad)))
        for b in all_bones}

    culled = sway_source_gate.bones_exceeding_posture_cull_threshold(
        all_bones, src_t, dst_t, group_targets)
    assert culled == {}


def test_all_unit_keys_returns_every_unit_regardless_of_acceptance():
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Tail Root", "chains": [["Tail.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        {"anchor": "Chest", "chains": [["scarf_01"]],
         "params": {"limit_type": "Hinge", "pull": 0.5, "spring": 0.5}},  # 偏向で非採用
    ]}
    plan = sway_allocator.allocate(physbones_json=physbones)
    keys = sd.all_unit_keys(plan)
    assert len(keys) == 2  # 採用/非採用問わず全unit


# ---------------------------------------------------------------------
# exclusion_entries_for_capacity_overflow (dev#1551 受入ゲート3:
# 「容量あふれ鎖は完全に無傷で残す...sway_degradeの帰属記録に載せる」)
# ---------------------------------------------------------------------

def _n_unbiased_units(n, bone_count=3):
    entries = [
        {"anchor": f"G{i}", "chains": [[f"G{i}_b0"] * bone_count],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}}
        for i in range(n)
    ]
    return {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": entries}


def test_exclusion_entries_for_capacity_overflow_reports_only_overflowed_units():
    """容量9超過で非採用になったunitだけがSTAGE_CAPACITY_OVERFLOWで
    記録され、採用されたunitは記録されない。"""
    plan = sway_allocator.allocate(physbones_json=_n_unbiased_units(11))
    assert len(plan.accepted) == 9
    assert len(plan.rejected_units) == 2

    entries = sd.exclusion_entries_for_capacity_overflow(plan)
    assert len(entries) == 2
    overflow_keys = {u.key for u in plan.rejected_units}
    assert {e.unit_key for e in entries} == overflow_keys
    for e in entries:
        assert e.stage == sd.STAGE_CAPACITY_OVERFLOW
        assert "容量超過で非採用" in e.reason


def test_exclusion_entries_for_capacity_overflow_empty_when_no_overflow():
    """負の対照: 容量内に収まっていれば空リスト(偏向除外があっても、
    それは容量超過ではないので対象外)。"""
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Tail Root", "chains": [["Tail.001"]],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        {"anchor": "Chest", "chains": [["scarf_01"]],
         "params": {"limit_type": "Hinge", "pull": 0.5, "spring": 0.5}},  # 偏向、容量超過ではない
    ]}
    plan = sway_allocator.allocate(physbones_json=physbones)
    assert plan.rejected_units  # 偏向除外は起きている(前提)
    entries = sd.exclusion_entries_for_capacity_overflow(plan)
    assert entries == []  # 偏向除外はcapacity_overflowとして報告しない
