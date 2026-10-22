# -*- coding: utf-8 -*-
"""test_sway_hub_tuft_merge.py -- 房Merge(dev#1572「房Mergeの機構」第3便、
配線層(sway_hub.py)での同深度枝畳み)の単体テスト。

背景: `work\\run_1551\\laneB1_notes\\NOTES.md`(前任レーン停止報告)が
実証した非両立——挿入点を`sway_allocator.py`(`ChainUnit.chains`を代表
1本へ畳む)に置くと、`ChainUnit.chains`を生データのまま読む別消費者
`sway_source_bones.py`(受入ゲートの対象骨集合の独立導出、SPEC §5)を
壊す。本WPは`ChainUnit.chains`を一切変更せず、畳みを配線層
(`sway_hub.plan_hub_wiring()`)へ移した再設計版。

方針(dev#1572追記): 幾何(フィット・donor配置)の代表=最長枝(同着は
入力順先頭)。ウェイト対応=全枝を深さ対応でdonorへ写像(片枝だけだと
猫又の他方の枝が剛体になり「正しく模擬」を満たさない)。安全域・節数
Mergeの母集団は代表枝(最長枝)基準でよい(おまけ機能、KISS)。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_allocator  # noqa: E402
import sway_hub as hub  # noqa: E402
import sway_source_bones  # noqa: E402


# =====================================================================
# select_tuft_representative() -- 純関数の単体テスト
# =====================================================================

def test_select_tuft_representative_no_chains_returns_empty():
    representative, others = hub.select_tuft_representative([])
    assert representative == ()
    assert others == ()


def test_select_tuft_representative_single_chain_is_identity():
    """房でない通常の直列鎖(chains長さ1)は完全に無変更(恒等)。"""
    representative, others = hub.select_tuft_representative([["a", "b", "c"]])
    assert representative == ("a", "b", "c")
    assert others == ()


def test_select_tuft_representative_picks_longest_branch():
    representative, others = hub.select_tuft_representative(
        [["b1", "b2"], ["a1", "a2", "a3"]])
    assert representative == ("a1", "a2", "a3")
    assert others == (("b1", "b2"),)


def test_select_tuft_representative_tie_break_picks_first_input_order():
    """同着(枝の長さが等しい)は入力順先頭を代表にする(dev#1572確定仕様)。"""
    representative, others = hub.select_tuft_representative(
        [["x1", "x2"], ["y1", "y2"]])
    assert representative == ("x1", "x2")
    assert others == (("y1", "y2"),)


def test_select_tuft_representative_three_branches_keeps_two_others():
    representative, others = hub.select_tuft_representative(
        [["a1"], ["b1", "b2", "b3"], ["c1", "c2"]])
    assert representative == ("b1", "b2", "b3")
    assert others == (("a1",), ("c1", "c2"))


# =====================================================================
# expand_tuft_weight_mapping() -- 純関数の単体テスト
# =====================================================================

def test_expand_tuft_weight_mapping_identity_when_no_other_branches():
    expansion = {"anchor": "anchor", "a1": "a1", "a2": "a2"}
    out = hub.expand_tuft_weight_mapping(("a1", "a2"), expansion, ())
    assert out == expansion
    assert out is not expansion  # コピーを返す(呼び出し元のexpansionを破壊しない)


def test_expand_tuft_weight_mapping_maps_other_branch_by_depth():
    """代表枝以外の枝の各骨は、同じ深さ(anchorからの位置)の代表枝の骨が
    対応するdonor代表へ写る。"""
    expansion = {"anchor": "anchor", "a1": "a1", "a2": "a2", "a3": "a3"}
    out = hub.expand_tuft_weight_mapping(
        ("a1", "a2", "a3"), expansion, (("b1", "b2"),))
    # 代表枝自身のエントリは無変更で残る。
    assert out["a1"] == "a1"
    assert out["a2"] == "a2"
    assert out["a3"] == "a3"
    # 非代表枝: 深さ0(b1)はa1と同じdonor代表、深さ1(b2)はa2と同じ。
    assert out["b1"] == "a1"
    assert out["b2"] == "a2"


def test_expand_tuft_weight_mapping_composes_with_within_chain_merge():
    """代表枝自身が`fit_chain_to_length()`で既に縮退(安全域/節数Merge)して
    いる場合、非代表枝はその縮退後の代表(donor側の実際の対応先)へ正しく
    追従する。"""
    # a2,a3が既にa3へ縮退済み(fit_chain_to_lengthの出力を模擬)。
    expansion = {"anchor": "anchor", "a1": "a1", "a2": "a3", "a3": "a3"}
    out = hub.expand_tuft_weight_mapping(
        ("a1", "a2", "a3"), expansion, (("b1", "b2"),))
    assert out["b1"] == "a1"   # 深さ0はa1(未縮退)に追従
    assert out["b2"] == "a3"  # 深さ1はa2の縮退先(a3)に追従、a2自身ではない


def test_expand_tuft_weight_mapping_ignores_branch_deeper_than_representative():
    """代表枝より深い(想定外の)非代表枝要素は、対応先が無いため安全側で
    無視する(このWPは「多段・複雑分岐は同じコードを通るだけの成り行き
    (保証なし)」——例外を投げず黙って無視するのが安全側)。"""
    expansion = {"anchor": "anchor", "a1": "a1"}
    out = hub.expand_tuft_weight_mapping(("a1",), expansion, (("b1", "b2"),))
    assert out["b1"] == "a1"  # 深さ0は対応先あり
    assert "b2" not in out    # 深さ1は代表枝に対応する深さが無い->無視


def test_expand_tuft_weight_mapping_multiple_other_branches():
    expansion = {"anchor": "anchor", "a1": "a1", "a2": "a2"}
    out = hub.expand_tuft_weight_mapping(
        ("a1", "a2"), expansion, (("b1", "b2"), ("c1",)))
    assert out["b1"] == "a1"
    assert out["b2"] == "a2"
    assert out["c1"] == "a1"


# =====================================================================
# donor_group_members() -- representative_source絞り込みの単体テスト
# =====================================================================

def test_donor_group_members_representative_source_filters_tuft_members():
    """`representative_source`が設定されていれば、その集合に含まれない
    weight_expansionメンバー(房Mergeで合流された非代表枝の骨)を幾何用
    グルーピングから除外する。"""
    weight_expansion = {
        "anchor": "anchor", "a1": "a1", "a2": "a2",
        "b1": "a1", "b2": "a2",  # 房Mergeで合流された非代表枝
    }
    cp = hub.ChainDonorPlan(
        source_chain=("anchor", "a1", "a2"),
        donor_chain_female=("d0", "d1"), donor_chain_male=("d0", "d1"),
        weight_expansion=weight_expansion,
        representative_source=("anchor", "a1", "a2"))
    groups = hub.donor_group_members(cp)
    assert groups["a1"] == ("a1",)  # b1は含まれない
    assert groups["a2"] == ("a2",)  # b2は含まれない
    assert "b1" not in groups
    assert "b2" not in groups


def test_donor_group_members_representative_source_empty_is_unfiltered():
    """`representative_source`が既定(空タプル)なら無フィルタ(既存挙動、
    本フィールドを知らない既存の直接構築テストと完全に無退行)。"""
    weight_expansion = {
        "anchor": "anchor", "a1": "a1", "a2": "a2",
        "b1": "a1", "b2": "a2",
    }
    cp = hub.ChainDonorPlan(
        source_chain=("anchor", "a1", "a2"),
        donor_chain_female=("d0", "d1"), donor_chain_male=("d0", "d1"),
        weight_expansion=weight_expansion)  # representative_source省略(既定())
    groups = hub.donor_group_members(cp)
    assert groups["a1"] == ("a1", "b1")  # フィルタ無し、挿入順のまま
    assert groups["a2"] == ("a2", "b2")


# =====================================================================
# plan_hub_wiring() 統合テスト -- Y字分岐(房)の合成入力
# =====================================================================

def _y_fork_hub_environment():
    """1スロットぶんのハブroot("hubA"、女性/男性側とも同名=univariant)+
    豊富な自由骨プールを持つ合成環境。native子孫は持たせない(全て
    "root"の直接の子として並べる)ため、free-pool経路(leaf hub)を通る
    ——房Merge自体の検証に無関係な複雑さ(native chain経路)を避けるため
    の意図的な選択。"""
    defs = [("root", -1), ("hubA", 0)]
    defs += [(f"free{i:02d}", 0) for i in range(1, 11)]
    bones = [{"name": n, "parent_idx": p, "quat": [0, 0, 0, 1],
              "pos": [0, 0, 0], "scale": [1, 1, 1]} for n, p in defs]
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    hub_slots = hub.HubSlots(female=("hubA",), male=("hubA",))
    reserved = frozenset()
    return catalog, hub_slots, reserved


def _y_fork_physbones():
    """猫又しっぽを模した合成PBコンポーネント: 1つのanchorから2本の枝
    (長さ3の"a"枝、長さ2の"b"枝)が分岐する房(Y字分岐)。"""
    return {
        "format": sway_allocator.PHYSBONES_FORMAT,
        "physbones": [
            {"anchor": "TailRoot",
             "chains": [
                 ["Tail_1a", "Tail_2a", "Tail_3a"],
                 ["Tail_1b", "Tail_2b"],
             ],
             "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        ],
    }


def test_plan_hub_wiring_tuft_merge_y_fork_collapses_to_single_chain_plan():
    """受入1: Y字2枝(長さ違い)が1つのChainDonorPlanへ畳まれる(房Merge前は
    2本の独立したchain_plansだった——issue #1572追記2「v2.11の猫又は2枝が
    別々のdonor家系へ独立割当されて両方揺れていた」の解消)。"""
    physbones = _y_fork_physbones()
    plan = sway_allocator.allocate(physbones_json=physbones)
    assert len(plan.accepted) == 1
    assert len(plan.accepted[0].units[0].chains) == 2  # ChainUnit.chainsは無改変(生のまま2本)

    catalog, hub_slots, reserved = _y_fork_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    assert len(wiring.group_plans) == 1
    gp = wiring.group_plans[0]
    assert len(gp.chain_plans) == 1  # 房Merge: 2枝が1つのChainDonorPlanへ畳まれる
    cp = gp.chain_plans[0]

    # 幾何の代表=最長枝(TailRoot,Tail_1a,Tail_2a,Tail_3a)。
    assert cp.source_chain == ("TailRoot", "Tail_1a", "Tail_2a", "Tail_3a")


def test_plan_hub_wiring_tuft_merge_weight_expansion_covers_both_branches():
    """受入1続き: ウェイト対応表に両枝の骨が深さ対応で入る(片枝だけだと
    他方の枝が剛体になるため、issue #1572追記の要求どおり全枝を含む)。"""
    physbones = _y_fork_physbones()
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _y_fork_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    cp = wiring.group_plans[0].chain_plans[0]

    # 代表枝(a)自身は恒等(容量に余裕がありwithin-chain mergeは発生しない)。
    assert cp.weight_expansion["TailRoot"] == "TailRoot"
    assert cp.weight_expansion["Tail_1a"] == "Tail_1a"
    assert cp.weight_expansion["Tail_2a"] == "Tail_2a"
    assert cp.weight_expansion["Tail_3a"] == "Tail_3a"
    # 非代表枝(b)は深さ対応で代表枝と同じ代表(=同じdonor)へ写る。
    assert cp.weight_expansion["Tail_1b"] == "Tail_1a"
    assert cp.weight_expansion["Tail_2b"] == "Tail_2a"


def test_plan_hub_wiring_tuft_merge_source_to_donor_map_shares_donor_across_branches():
    """受入1続き(実使用経路): `sway_hub_wire.source_to_donor_bone_map()`
    経由で見ても、両枝の同じ深さの骨が同じdonor骨へ写ること(=物理的に
    連動して動く=「猫又を正しく模擬」)。"""
    import sway_hub_wire

    physbones = _y_fork_physbones()
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _y_fork_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    donor_map = sway_hub_wire.source_to_donor_bone_map(wiring, "Female")
    assert donor_map["Tail_1a"] == donor_map["Tail_1b"]
    assert donor_map["Tail_2a"] == donor_map["Tail_2b"]
    # 幾何代表(a枝)は実際にdonorへ写っている(未配線ではない)ことも確認。
    assert donor_map["Tail_1a"] != donor_map["TailRoot"]


def test_plan_hub_wiring_tuft_merge_geometry_follows_representative_branch_only():
    """受入1続き: donor配置(幾何)は代表枝(最長枝)のみを見る——非代表枝の
    骨は`donor_group_members()`のグループに一切現れない(混ざると幾何が
    非代表枝側へ歪む、`ChainDonorPlan.representative_source`docstring
    参照)。"""
    physbones = _y_fork_physbones()
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _y_fork_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    cp = wiring.group_plans[0].chain_plans[0]

    groups = hub.donor_group_members(cp)
    all_members = {m for members in groups.values() for m in members}
    assert "Tail_1b" not in all_members
    assert "Tail_2b" not in all_members
    assert all_members == {"TailRoot", "Tail_1a", "Tail_2a", "Tail_3a"}


def test_plan_hub_wiring_tuft_merge_downstream_treated_as_serial_chain():
    """受入1続き: マージ後は直列鎖として通常ルール(偏向判定・安全域・
    節数Merge)に乗ることの最小確認——安全域1を与えると、代表枝(4節: root+
    3骨)がtip側から1本縮む、房でない直列鎖と同じ式(`target_len_with_
    safety_margin()`)がそのまま適用される。"""
    physbones = _y_fork_physbones()
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _y_fork_hub_environment()
    wiring = hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved, default_safety_margin=1)
    cp = wiring.group_plans[0].chain_plans[0]

    # n_ext=4(TailRoot+3骨)、自由プール経路はdonor_capacity=n_ext扱いなので
    # target_len=4-1=3。代表枝がtip(Tail_3a)側から1本縮む=[TailRoot,Tail_1a,
    # (Tail_2a,Tail_3a)->Tail_3a]。
    assert cp.source_chain == ("TailRoot", "Tail_1a", "Tail_3a")
    assert cp.weight_expansion["Tail_2a"] == "Tail_3a"
    # 非代表枝(b)も深さ1(Tail_2b)は縮退後の代表(Tail_3a)へ正しく追従する。
    assert cp.weight_expansion["Tail_2b"] == "Tail_3a"
    assert cp.weight_expansion["Tail_1b"] == "Tail_1a"


# =====================================================================
# 負の対照1: 枝の無い直列鎖は房Merge導入前と完全に不変
# =====================================================================

def test_plan_hub_wiring_negative_control_no_fork_chain_plan_unchanged():
    """負の対照: 房(2枝以上)を持たない通常の直列鎖の配線計画・対応表は
    房Merge導入前と完全に不変(既存挙動一致)。"""
    physbones = {
        "format": sway_allocator.PHYSBONES_FORMAT,
        "physbones": [
            {"anchor": "Hips", "chains": [["tail_01", "tail_02", "tail_03"]],
             "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
        ],
    }
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _y_fork_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    assert len(wiring.group_plans) == 1
    gp = wiring.group_plans[0]
    assert len(gp.chain_plans) == 1
    cp = gp.chain_plans[0]

    assert cp.source_chain == ("Hips", "tail_01", "tail_02", "tail_03")
    # weight_expansionは純粋な恒等写像(房Mergeで追加されたキーが1つも無い)。
    assert cp.weight_expansion == {
        "Hips": "Hips", "tail_01": "tail_01",
        "tail_02": "tail_02", "tail_03": "tail_03"}
    # donor_group_membersも全メンバーが単独グループ(混合なし)。
    groups = hub.donor_group_members(cp)
    assert groups == {
        "Hips": ("Hips",), "tail_01": ("tail_01",),
        "tail_02": ("tail_02",), "tail_03": ("tail_03",)}


# =====================================================================
# 負の対照2: sway_source_bones.py(受入ゲートの骨集合)は無改修で無関係
# =====================================================================

def test_negative_control_sway_source_bones_unaffected_by_tuft_merge():
    """負の対照(laneB1停止報告の再発防止本体): `sway_source_bones.py`は
    `sway_allocator.ChainUnit.chains`を生データのまま読む独立実装であり、
    房Merge(配線層=sway_hub.pyだけの変更)を一切importしない——Y字分岐の
    `ChainUnit`を渡しても、両枝の骨が(配線層でどう畳まれるかに関係なく)
    そのまま全部返ることを確認する(=`sway_hub.py`側の変更がこのモジュール
    の出力に一切波及していないことの直接証拠)。"""
    physbones = _y_fork_physbones()
    plan = sway_allocator.allocate(physbones_json=physbones)
    unit = plan.accepted[0].units[0]
    assert len(unit.chains) == 2  # ChainUnit.chainsは無改変(生のまま2本)

    names = sway_source_bones.expand_unit_source_bones(unit)
    # anchor + 両枝の骨が全部含まれる(房Mergeで片方が消えていない)。
    assert names == frozenset({
        "TailRoot", "Tail_1a", "Tail_2a", "Tail_3a", "Tail_1b", "Tail_2b"})
