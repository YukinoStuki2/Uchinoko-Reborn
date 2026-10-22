# -*- coding: utf-8 -*-
"""test_sway_hub_wire.py -- sway_hub_wire.pyの単体テスト(dev#1508 W2a-2c、
汎用ハブ配線の高レベル入口)。実機・pak・Blenderに一切依存しない
(bpy非依存、純粋関数のみ)。合成環境は`test_sway_hub.py`の
`_two_slot_hub_environment()`と同型のものをここで再構築する
(実物のsway_abp_templates/specs/*.jsonを使う経路は
`test_wire_and_diagnose_hub_uses_real_templates_end_to_end`が担当)。
"""
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_allocator  # noqa: E402
import sway_hub as hub  # noqa: E402
import sway_hub_wire as hw  # noqa: E402


def _make_physbones_json(entries):
    return {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": anchor, "chains": [list(chain)],
         "params": {"limit_type": "None", "pull": pull, "spring": spring}}
        for anchor, chain, pull, spring in entries
    ]}


def _real_template_catalog(free_bone_count=200):
    """実物のsway_abp_templates(discover_hub_slots()の9+9スロット、恒久予備
    込みで16本の予約対象root)を使いつつ、reservedをfrozenset()で無効化した
    合成カタログ(自由骨は"free00".."free{n}"として大量に用意、既存
    テストの_two_slot_hub_environment()を実物テンプレへ一般化)。"""
    slots = hub.discover_hub_slots()
    names = list(slots.female) + list(slots.male)
    defs = [("root", -1)] + [(n, 0) for n in names]
    defs += [(f"free{i:03d}", 0) for i in range(free_bone_count)]
    bones = [{"name": n, "parent_idx": p, "quat": [0, 0, 0, 1],
              "pos": [0, 0, 0], "scale": [1, 1, 1]} for n, p in defs]
    return hub.SkeletonCatalog.from_bones_list(bones), slots


def test_wire_and_diagnose_hub_end_to_end_no_op_when_no_candidates():
    catalog, _slots = _real_template_catalog()
    result = hw.wire_and_diagnose_hub(
        physbone_entries=[], springbone_entries=[], gender="Female",
        catalog=catalog, common_bones=frozenset())
    assert result.wiring.group_plans == ()
    assert result.node_overrides == {}
    assert result.refskel_dict == {}
    assert result.diagnostics_lines == ()


def test_wire_and_diagnose_hub_uses_real_templates_end_to_end():
    catalog, slots = _real_template_catalog()
    physbones = _make_physbones_json([
        ("Hips", ["Tail Root", "Tail.001", "Tail.002"], 0.5, 0.5),
    ])
    physbones["physbones"][0]["params"]  # sanity
    result = hw.wire_and_diagnose_hub(
        physbone_entries=physbones["physbones"], springbone_entries=[],
        gender="Female", catalog=catalog, common_bones=frozenset())

    assert len(result.wiring.group_plans) == 1
    gp = result.wiring.group_plans[0]
    assert gp.hub_root_female in slots.female
    assert set(result.node_overrides) == {gp.hub_root_female, gp.hub_root_male}
    assert len(result.diagnostics_lines) == 1
    record = json.loads(result.diagnostics_lines[0])
    assert record["wiring"][0]["donor_root_bone"] == gp.hub_root_female

    donor_names = [d for cp in gp.chain_plans for d in cp.donor_chain_for("Female")]
    assert set(result.refskel_dict) == {gp.hub_root_female, *donor_names}


def test_wire_and_diagnose_hub_dev1551_each_chain_gets_its_own_hub():
    """hub前提だった箇所の追従(dev#1551、2026-08-17オーナー裁定「hubを
    廃止し1chainあたり1KPノードへ移行する」): 旧`anchor_group_of`引数
    (耳L(Head_L.001)/R(Head_R.001)を親="head"経由で1ハブへ統合する仕組み)
    は完全に廃止された——引数自体が無くなり、`wire_and_diagnose_hub()`は
    常に1 ChainUnit=1ハブとして配線する(耳L/Rは常に2スロット消費)。"""
    catalog, slots = _real_template_catalog()
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002"], 0.5, 0.5),
        ("Head_R.001", ["Head_R.002"], 0.5, 0.5),
    ])
    result = hw.wire_and_diagnose_hub(
        physbone_entries=physbones["physbones"], springbone_entries=[],
        gender="Female", catalog=catalog, common_bones=frozenset())

    assert len(result.wiring.group_plans) == 2  # dev#1551: 別々のハブ、統合されない
    hub_roots_used = set()
    for gp in result.wiring.group_plans:
        assert len(gp.chain_plans) == 1
        hub_roots_used.add(gp.hub_root_female)
    assert len(hub_roots_used) == 2  # 2本とも別々のハブroot骨(共有なし)
    assert len(result.diagnostics_lines) == 2
    donor_roots_reported = set()
    for line in result.diagnostics_lines:
        record = json.loads(line)
        donor_root = record["wiring"][0]["donor_root_bone"]
        assert donor_root is not None, f"{record['anchor']}: 配線されていない"
        donor_roots_reported.add(donor_root)
    assert donor_roots_reported == hub_roots_used


def test_wire_and_diagnose_hub_protected_bones_never_selected_as_donor():
    """負の対照: `common_bones`(protected)に含めた自由骨は、在庫が
    ほぼゼロになるまで(=常に)ドナーとして選ばれない。"""
    catalog, slots = _real_template_catalog(free_bone_count=3)
    protected = frozenset({"free000", "free001"})  # free002だけ残す
    physbones = _make_physbones_json([("Hips", ["a", "b"], 0.5, 0.5)])
    result = hw.wire_and_diagnose_hub(
        physbone_entries=physbones["physbones"], springbone_entries=[],
        gender="Female", catalog=catalog, common_bones=protected)
    # 自由プールが1本(free002)しかないのに2本要求 -> 配線不能
    assert not result.wiring.group_plans
    assert result.wiring.unassignable


def test_source_to_donor_bone_map_flattens_all_chains():
    catalog, slots = _real_template_catalog()
    physbones = _make_physbones_json([
        ("Hips", ["Tail Root", "Tail.001"], 0.5, 0.5),
    ])
    result = hw.wire_and_diagnose_hub(
        physbone_entries=physbones["physbones"], springbone_entries=[],
        gender="Female", catalog=catalog, common_bones=frozenset())
    mapping = hw.source_to_donor_bone_map(result.wiring, "Female")
    # anchorオフバイワン修正(2026-08-16、dev#1508耳根元骨欠落バグ):
    # anchor("Hips")自身もsource_chainの先頭に含まれ、donorへ写る。
    # dev#1551(ゼロ長root廃止修理): anchor("Hips")は今やhub root自身が
    # 担う(内容写像が1つ繰り上がった)ため、donor_chainは
    # "Tail Root"/"Tail.001"に対応する。
    assert set(mapping) == {"Hips", "Tail Root", "Tail.001"}
    gp = result.wiring.group_plans[0]
    cp = gp.chain_plans[0]
    donor_chain = cp.donor_chain_for("Female")
    assert mapping["Hips"] == gp.hub_root_female
    assert mapping["Tail Root"] == donor_chain[0]
    assert mapping["Tail.001"] == donor_chain[1]


def test_source_to_donor_bone_map_includes_anchor_bone_dev1508():
    """回帰固定(dev#1508耳根元骨欠落バグ、DIAG.md確定根因): 修正前は
    `source_to_donor_bone_map()`の戻り値にPB root骨(anchor)自身のキーが
    一切存在しなかった(`group_targets[anchor]`が汎用祖先クライムのまま
    上書きされず、根元の頂点ウェイトが揺れないボーンへ迷子になっていた)。
    ここではcomodo実データに近い「1anchorから2房分岐」構成
    (`Head_L.002`が2チェーンで共有される)で、anchor自身が確実にキーへ
    含まれることを固定する。"""
    catalog, slots = _real_template_catalog()
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Head_L.001",
         "chains": [["Head_L.002", "Head_L.002_end"],
                    ["Head_L.002", "Head_L.003$guid"]],
         "params": {"limit_type": "None", "pull": 0.348, "spring": 0.49}},
    ]}
    result = hw.wire_and_diagnose_hub(
        physbone_entries=physbones["physbones"], springbone_entries=[],
        gender="Female", catalog=catalog, common_bones=frozenset())
    mapping = hw.source_to_donor_bone_map(result.wiring, "Female")
    assert "Head_L.001" in mapping, (
        "anchor bone missing from source_to_donor_bone_map() -- "
        "dev#1508 off-by-one regression")


def test_source_to_donor_bone_map_empty_when_no_groups():
    catalog, slots = _real_template_catalog()
    result = hw.wire_and_diagnose_hub(
        physbone_entries=[], springbone_entries=[], gender="Female",
        catalog=catalog, common_bones=frozenset())
    assert hw.source_to_donor_bone_map(result.wiring, "Female") == {}


# =====================================================================
# dev#1551 chain-length-fit: source_to_donor_bone_map()のweight_expansion展開
# =====================================================================

def _linear_native_chain_catalog(native_len, hub_name="hubA"):
    """`test_sway_hub.py`の`_linear_native_chain_environment()`と同型
    (univariant、hub_name自身の直系子孫native_len本)。"""
    names_parents = [("root", -1), (hub_name, 0)]
    parent_idx = 1
    for i in range(1, native_len + 1):
        names_parents.append((f"{hub_name}_native_{i:02d}", parent_idx))
        parent_idx = len(names_parents) - 1
    for i in range(1, 21):
        names_parents.append((f"free{i:02d}", 0))
    bones = [{"name": n, "parent_idx": p, "quat": [0, 0, 0, 1],
              "pos": [0, 0, 0], "scale": [1, 1, 1]} for n, p in names_parents]
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    hub_slots = hub.HubSlots(female=(hub_name,), male=(hub_name,))
    return catalog, hub_slots


def test_source_to_donor_bone_map_expands_merged_bones_to_shared_donor():
    """dev#1551 chain-length-fit: 節数フィット(先端マージ)が発動した鎖で、
    マージされた**全ての**元アバター骨名(先端側の複数本)が同じdonor骨名へ
    写ることを確認する(ウェイトのADD合算が正しく起きる前提条件)。"""
    catalog, hub_slots = _linear_native_chain_catalog(3, hub_name="hubA")
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003", "Head_L.004",
                         "Head_L.005", "Head_L.006"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, frozenset())
    mapping = hw.source_to_donor_bone_map(wiring, "Female")
    # 全6要素(anchor含む)が対応表に含まれる(取りこぼしなし)
    assert set(mapping) == {"Head_L.001", "Head_L.002", "Head_L.003",
                             "Head_L.004", "Head_L.005", "Head_L.006"}
    # 根本(anchor)は独自のdonorを持つ(他要素と共有しない)
    root_donor = mapping["Head_L.001"]
    assert root_donor not in (mapping["Head_L.005"], mapping["Head_L.006"])
    # 先端側(005/006)は同じdonorへ集約(マージ)されている
    assert mapping["Head_L.005"] == mapping["Head_L.006"]


# =====================================================================
# dev#1551 安全域: wire_and_diagnose_hub()引数のsway_hub.plan_hub_wiring()への貫通
# =====================================================================

def test_wire_and_diagnose_hub_default_safety_margin_zero_is_unchanged():
    """負の対照: 引数省略(既定0)は無退行——既存の全テストと同じ
    (anchor+2本=3本がそのまま配線される)。"""
    catalog, slots = _real_template_catalog()
    physbones = _make_physbones_json([
        ("Hips", ["Tail Root", "Tail.001"], 0.5, 0.5),
    ])
    result = hw.wire_and_diagnose_hub(
        physbone_entries=physbones["physbones"], springbone_entries=[],
        gender="Female", catalog=catalog, common_bones=frozenset())
    cp = result.wiring.group_plans[0].chain_plans[0]
    assert len(cp.source_chain) == 3
    assert not result.wiring.chain_fit_events


def test_wire_and_diagnose_hub_default_safety_margin_threads_through():
    """default_safety_margin引数がsway_hub.plan_hub_wiring()まで貫通する
    ことを確認する(GUI→job.json→本関数→plan_hub_wiring()の配線経路の
    うち、本関数が担う区間の実測)。"""
    catalog, slots = _real_template_catalog()
    physbones = _make_physbones_json([
        ("Hips", ["Tail Root", "Tail.001"], 0.5, 0.5),  # anchor+2=3本
    ])
    result = hw.wire_and_diagnose_hub(
        physbone_entries=physbones["physbones"], springbone_entries=[],
        gender="Female", catalog=catalog, common_bones=frozenset(),
        default_safety_margin=1)
    cp = result.wiring.group_plans[0].chain_plans[0]
    assert len(cp.source_chain) == 2  # 3-1
    assert cp.source_chain[0] == "Hips"  # anchorは無傷
    assert result.wiring.chain_fit_events


def test_wire_and_diagnose_hub_safety_margin_by_chain_threads_through():
    """safety_margin_by_chain引数(GUI「揺れもの詳細」の鎖ごと上書き相当)が
    貫通し、default_safety_marginより優先されることを確認する。"""
    catalog, slots = _real_template_catalog()
    physbones = _make_physbones_json([
        ("Hips", ["Tail Root", "Tail.001"], 0.5, 0.5),  # anchor+2=3本
    ])
    overrides = {("Hips", "Tail Root", "Tail.001"): 0}
    result = hw.wire_and_diagnose_hub(
        physbone_entries=physbones["physbones"], springbone_entries=[],
        gender="Female", catalog=catalog, common_bones=frozenset(),
        default_safety_margin=1, safety_margin_by_chain=overrides)
    cp = result.wiring.group_plans[0].chain_plans[0]
    assert len(cp.source_chain) == 3  # 上書きで安全域0、無変形


# =====================================================================
# dev#1572(積み荷A、issue #1572追記3): filter_entries_by_weighted_bones()
# =====================================================================

def test_filter_entries_by_weighted_bones_trims_unweighted_tip():
    """「4骨中先端1本無ウェイト→母集団3」(issue #1572本文の受入例)。"""
    entries = [{"anchor": "Head_L", "chains": [
        ["Head_L.001", "Head_L.002", "Head_L.003", "Head_L.003_end"]]}]
    weighted = frozenset({"Head_L.001", "Head_L.002", "Head_L.003"})
    out = hw.filter_entries_by_weighted_bones(entries, weighted)
    assert out[0]["chains"] == [["Head_L.001", "Head_L.002", "Head_L.003"]]
    # anchorはこの関数の対象外(常に維持、weighted集合に無くても消えない)
    assert out[0]["anchor"] == "Head_L"


def test_filter_entries_by_weighted_bones_compacts_interior_gap():
    """鎖の途中(先端でなく)が無ウェイトでも、スキップして前へ詰める。"""
    entries = [{"anchor": "A", "chains": [["B", "C", "D"]]}]
    weighted = frozenset({"B", "D"})  # Cだけ無ウェイト
    out = hw.filter_entries_by_weighted_bones(entries, weighted)
    assert out[0]["chains"] == [["B", "D"]]


def test_filter_entries_by_weighted_bones_drops_fully_unweighted_chain():
    """チェーン全体が無ウェイトなら、そのチェーンごと落とす(空リストを
    残さない)。"""
    entries = [{"anchor": "A", "chains": [["X", "Y"], ["B", "C"]]}]
    weighted = frozenset({"B", "C"})
    out = hw.filter_entries_by_weighted_bones(entries, weighted)
    assert out[0]["chains"] == [["B", "C"]]


def test_filter_entries_by_weighted_bones_none_is_passthrough():
    """weighted_bone_names=None(bpyメッシュ情報が無い場面)は無変更で
    そのまま返す——無退行の安全側フォールバック。"""
    entries = [{"anchor": "A", "chains": [["B", "C", "D"]]}]
    out = hw.filter_entries_by_weighted_bones(entries, None)
    assert out[0]["chains"] == [["B", "C", "D"]]


def test_filter_entries_by_weighted_bones_negative_control_without_filter():
    """負の対照: フィルタを適用しない(None)場合、無ウェイト骨は消えず
    母集団に残ったままであることを示す——フィルタが実際に効いている
    ことの証明(適用した場合との差分)。"""
    entries = [{"anchor": "Head_L", "chains": [
        ["Head_L.001", "Head_L.002", "Head_L.003", "Head_L.003_end"]]}]
    weighted = frozenset({"Head_L.001", "Head_L.002", "Head_L.003"})
    filtered = hw.filter_entries_by_weighted_bones(entries, weighted)
    unfiltered = hw.filter_entries_by_weighted_bones(entries, None)
    assert len(filtered[0]["chains"][0]) == 3
    assert len(unfiltered[0]["chains"][0]) == 4  # 無ウェイト骨がまだ残っている


def test_filter_entries_by_weighted_bones_end_to_end_reduces_population():
    """フィルタ後のentriesをwire_and_diagnose_hub()へ通すと、n_extが
    実際に縮み(anchor+3=4)、安全域0(margin=0)なら節数フィット不発動で
    3骨1:1のまま配線されることを確認する(積み荷Aの効果が実際の配線結果
    へ伝わることのend-to-end確認)。"""
    catalog, slots = _real_template_catalog()
    entries = [{"anchor": "Hips", "chains": [
        ["Tail Root", "Tail.001", "Tail.002", "Tail.002_end"]],
        "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}}]
    weighted = frozenset({"Tail Root", "Tail.001", "Tail.002"})
    filtered = hw.filter_entries_by_weighted_bones(entries, weighted)
    result = hw.wire_and_diagnose_hub(
        physbone_entries=filtered, springbone_entries=[],
        gender="Female", catalog=catalog, common_bones=frozenset())
    cp = result.wiring.group_plans[0].chain_plans[0]
    assert len(cp.source_chain) == 4  # anchor(Hips)+3(無ウェイト先端を含まない)
    assert not result.wiring.chain_fit_events  # マージ不発動(容量200なので余裕)
