# -*- coding: utf-8 -*-
"""sway_allocator.py の単体テスト(dev#1508 W1c)。

受入3検体(flatHaori実物流用、comodo/flatapronはオーナー確認済み実値の
手書きfixture、`pipeline\\py\\testdata\\sway_allocator\\`)での仕様全分岐
固定テストと、境界条件を単純化した合成データでの負の対照を両方持つ。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sway_allocator as m  # noqa: E402
import sway_quantize  # noqa: E402

_FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "testdata", "sway_allocator")


def _load_fixture(name: str) -> dict:
    with open(os.path.join(_FIXTURE_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _pb(anchor, bone_count, *, pull=0.5, spring=0.5, limit_type="None",
        max_angle_x=45.0, limit_rotation=(0, 0, 0), n_chains=1):
    chains = [[f"{anchor}_b{i}_{k}" for i in range(bone_count)] for k in range(n_chains)]
    return {
        "anchor": anchor,
        "chains": chains,
        "params": {
            "pull": pull, "spring": spring, "stiffness": 0.2, "gravity": 0,
            "gravity_falloff": 0, "immobile": 0, "immobile_type": "AllMotion",
            "limit_type": limit_type, "max_angle_x": max_angle_x,
            "max_angle_z": max_angle_x, "limit_rotation": list(limit_rotation),
            "radius": 0,
        },
    }


def _physbones(*entries) -> dict:
    return {"format": m.PHYSBONES_FORMAT, "physbones": list(entries)}


# =====================================================================
# 1. 候補判定(パース) -- 名前は一切見ない
# =====================================================================

def test_parse_physbones_ignores_names_entirely():
    """奇妙な名前(尻尾/耳のトークンを一切含まない)でも、PB付きである
    以上は普通に候補として拾われる(候補判定は名前非依存)。"""
    pbj = _physbones(_pb("XyzUnrelatedName99", 3))
    units = m.parse_physbones(pbj)
    assert len(units) == 1
    assert units[0].anchor == "XyzUnrelatedName99"
    assert units[0].excluded_reason is None or not units[0].is_biased


def test_parse_physbones_empty_or_none_is_empty_list():
    assert m.parse_physbones(None) == []
    assert m.parse_physbones({"format": m.PHYSBONES_FORMAT, "physbones": []}) == []


# =====================================================================
# 2. 無偏向判定(全分岐)
# =====================================================================

def test_bias_none_type_is_unbiased_even_with_nonzero_rotation_leftover():
    """limit_type=None時はlimit_rotationが残っていても死データとして無視
    (2026-08-16訂正版)。"""
    is_biased, reason = m._judge_pb_bias(  # noqa: SLF001
        {"limit_type": "None", "limit_rotation": [99, 99, 99]})
    assert is_biased is False
    assert reason == ""


def test_bias_angle_zero_rotation_is_unbiased():
    is_biased, reason = m._judge_pb_bias(  # noqa: SLF001
        {"limit_type": "Angle", "limit_rotation": [0, 0, 0]})
    assert is_biased is False
    assert reason == ""


def test_bias_angle_nonzero_rotation_is_biased():
    is_biased, reason = m._judge_pb_bias(  # noqa: SLF001
        {"limit_type": "Angle", "limit_rotation": [30, 0, 0]})
    assert is_biased is True
    assert "Angle" in reason


def test_bias_hinge_is_biased():
    is_biased, reason = m._judge_pb_bias({"limit_type": "Hinge"})  # noqa: SLF001
    assert is_biased is True
    assert "Hinge" in reason


def test_bias_polar_is_biased():
    is_biased, reason = m._judge_pb_bias({"limit_type": "Polar"})  # noqa: SLF001
    assert is_biased is True
    assert "Polar" in reason


def test_bias_unknown_limit_type_falls_safe_side_biased():
    """未知のlimit_typeは安全側(偏向)に倒す(構造検査の一環、値を寄せて
    合わせない)。"""
    is_biased, reason = m._judge_pb_bias({"limit_type": "SomeFutureType"})  # noqa: SLF001
    assert is_biased is True
    assert "SomeFutureType" in reason


def test_sb_is_always_unbiased():
    is_biased, reason = m._judge_sb_bias({})  # noqa: SLF001
    assert is_biased is False
    assert reason == ""


# =====================================================================
# 3. 量子化 / 3b. 角度制限写し
# =====================================================================

def test_style_matches_quantize_pb_output():
    pbj = _physbones(_pb("A", 3, pull=0.348, spring=0.49, limit_type="None"))
    units = m.parse_physbones(pbj)
    assert units[0].style == sway_quantize.quantize_pb(0.348, 0.49)


def test_limit_angle_angle_type_copies_max_angle_x():
    pbj = _physbones(_pb("A", 3, limit_type="Angle", max_angle_x=30.0,
                          limit_rotation=(0, 0, 0)))
    units = m.parse_physbones(pbj)
    assert units[0].is_biased is False
    assert units[0].limit_angle == pytest.approx(30.0)


def test_limit_angle_none_type_is_zero():
    pbj = _physbones(_pb("A", 3, limit_type="None"))
    units = m.parse_physbones(pbj)
    assert units[0].limit_angle == pytest.approx(0.0)


def test_limit_angle_biased_chain_is_zero():
    pbj = _physbones(_pb("A", 3, limit_type="Hinge", max_angle_x=30.0,
                          limit_rotation=(30, 0, 0)))
    units = m.parse_physbones(pbj)
    assert units[0].is_biased is True
    assert units[0].limit_angle == pytest.approx(0.0)


def test_sb_limit_angle_is_always_zero():
    sbj = {"format": m.SPRINGBONES_FORMAT, "springbones": [
        {"anchor": "A", "chains": [["A_b0", "A_b1"]],
         "params": {"stiffness": 1.0, "gravity_power": 0.0, "drag_force": 0.4}},
    ]}
    units = m.parse_springbones(sbj)
    assert units[0].is_biased is False
    assert units[0].limit_angle == pytest.approx(0.0)
    assert units[0].style in ("yawa", "futsuu", "kata")


# =====================================================================
# 4. グループ化(dev#1551、2026-08-17オーナー裁定でdev#1508の(親骨×ゆれかた)
#    束ねを完全廃止——1 ChainUnit = 1 SwayGroup = 1 KPノード。ハブ構造
#    (1スロット=複数鎖共有)が実機不具合(付け根ずれ)容疑だったため。
# =====================================================================

def test_grouping_never_merges_same_anchor_and_style():
    """hub前提だった箇所の追従(dev#1551): 旧仕様は同じanchor+styleの
    2つのChainUnitを1グループへ統合していたが、dev#1551で統合機構自体を
    廃止したため、同じanchorを共有していても常に2グループ(=2 KPノード)
    のまま分離される。"""
    pbj = _physbones(
        _pb("Same.001", 3, pull=0.348, spring=0.49, limit_type="None"),
        _pb("Same.001", 4, pull=0.348, spring=0.49, limit_type="None"),
    )
    plan = m.allocate(physbones_json=pbj)
    assert len(plan.accepted) == 2
    for g in plan.accepted:
        assert g.anchor == "Same.001"
        assert len(g.units) == 1  # dev#1551: 常に単一unit


def test_grouping_keeps_different_anchors_separate():
    pbj = _physbones(
        _pb("A", 3, limit_type="None"),
        _pb("B", 3, limit_type="None"),
    )
    plan = m.allocate(physbones_json=pbj)
    assert len(plan.accepted) == 2
    anchors = {g.anchor for g in plan.accepted}
    assert anchors == {"A", "B"}


# --- dev#1551(2026-08-17オーナー裁定「hubを廃止し1chainあたり1KPノードへ
#     移行する」): 旧dev#1508「グループ化は(親骨×ゆれかた)」統合の廃止 ----

def test_grouping_no_longer_merges_different_anchors_with_same_parent():
    """hub前提だった箇所の追従(dev#1551): 旧仕様(anchor_group_of経由で
    親humanoid骨が同じなら統合)は完全に廃止された。耳L(Head_L.001)/
    R(Head_R.001)は常に別グループ(=別KPノード、別スロット消費)になる
    ——`anchor_group_of`引数自体が削除されているため、渡す手段も無い。"""
    pbj = _physbones(
        _pb("Head_L.001", 2, pull=0.348, spring=0.49, limit_type="None"),
        _pb("Head_R.001", 2, pull=0.348, spring=0.49, limit_type="None"),
    )
    plan = m.allocate(physbones_json=pbj)
    assert len(plan.accepted) == 2
    anchors = {g.anchor for g in plan.accepted}
    assert anchors == {"Head_L.001", "Head_R.001"}
    for g in plan.accepted:
        assert len(g.units) == 1
        assert g.bone_count == 2


def test_grouping_slot_count_reflects_one_unit_per_group():
    """dev#1551: 容量勘定はChainUnit単位(1鎖=1スロット)。耳L/Rは
    dev#1508時代なら1グループ(容量1で両方採用)だったが、統合が
    廃止された今は2グループ(=2スロット)を消費するため、capacity=1では
    片方(骨数タイなので辞書順=Head_L.001)だけが採用され、もう片方
    (Head_R.001)は容量超過で非採用になる。"""
    pbj = _physbones(
        _pb("Head_L.001", 2, pull=0.5, spring=0.5, limit_type="None"),
        _pb("Head_R.001", 2, pull=0.5, spring=0.5, limit_type="None"),
    )
    plan = m.allocate(physbones_json=pbj, capacity=1)
    assert len(plan.accepted) == 1
    assert plan.accepted[0].anchor == "Head_L.001"
    assert len(plan.accepted[0].units) == 1
    assert len(plan.rejected_units) == 1
    rejected = plan.rejected_units[0]
    assert rejected.anchor == "Head_R.001"
    assert "容量超過で非採用" in rejected.excluded_reason


# =====================================================================
# 5. 容量9・優先順位・非採用ログ
# =====================================================================

def test_priority_bone_count_descending_when_no_tail():
    pbj = _physbones(
        _pb("Small", 2, limit_type="None"),
        _pb("Big", 8, limit_type="None"),
        _pb("Mid", 5, limit_type="None"),
    )
    plan = m.allocate(physbones_json=pbj)
    order = [g.anchor for g in plan.accepted]
    assert order == ["Big", "Mid", "Small"]


def test_priority_tiebreak_is_anchor_dict_order():
    pbj = _physbones(
        _pb("Zeta", 4, limit_type="None"),
        _pb("Alpha", 4, limit_type="None"),
    )
    plan = m.allocate(physbones_json=pbj)
    order = [g.anchor for g in plan.accepted]
    assert order == ["Alpha", "Zeta"]


def test_priority_tail_beats_bone_count():
    pbj = _physbones(
        _pb("HeadTailBone", 2, limit_type="None"),  # "Tail"を含む→尻尾同定
        _pb("Bigger", 20, limit_type="None"),
    )
    plan = m.allocate(physbones_json=pbj)
    order = [g.anchor for g in plan.accepted]
    assert order == ["HeadTailBone", "Bigger"]
    assert plan.accepted[0].is_tail is True


# --- 負の対照: 容量超過で10個目が落ちる -----------------------------------

def test_capacity_tenth_group_is_dropped():
    entries = [_pb(f"G{10 - i}", 10 - i, limit_type="None") for i in range(10)]
    pbj = _physbones(*entries)
    plan = m.allocate(physbones_json=pbj)
    assert len(plan.accepted) == 9
    accepted_anchors = {g.anchor for g in plan.accepted}
    assert "G1" not in accepted_anchors  # 骨数最小(1本)の群が10番目として落ちる
    rejected_anchors = {u.anchor: u.excluded_reason for u in plan.rejected_units}
    assert "G1" in rejected_anchors
    assert "容量超過で非採用" in rejected_anchors["G1"]


# --- 負の対照: しっぽは骨数で負けても採用される ----------------------------

def test_tail_survives_capacity_even_with_fewest_bones():
    non_tail = [_pb(f"Cloth{i}", 10 - i, limit_type="None") for i in range(9)]  # bone_count 10..2
    tail = _pb("TailRoot", 1, limit_type="None")  # 最小の骨数だが尻尾
    pbj = _physbones(*non_tail, tail)
    plan = m.allocate(physbones_json=pbj)
    assert len(plan.accepted) == 9
    accepted_anchors = {g.anchor for g in plan.accepted}
    assert "TailRoot" in accepted_anchors
    # 尻尾が割り込んだ分、非尻尾の最小(bone_count=2, Cloth8)が押し出される
    assert "Cloth8" not in accepted_anchors
    rejected_anchors = {u.anchor for u in plan.rejected_units}
    assert "Cloth8" in rejected_anchors


# --- dev#1551 受入ゲート2-①: しっぽ(絶対枠)は容量1でも必ず入る ------------

def test_tail_is_accepted_even_with_capacity_one():
    """issue #1551「対象条件: しっぽは絶対揺らす」の直接検査:
    骨数で圧倒的に負けていても、容量が1つしか無ければ、しっぽ以外は
    全員あふれてもしっぽだけは必ず採用される(絶対枠)。"""
    non_tail = [_pb(f"Cloth{i}", 50, limit_type="None") for i in range(5)]  # 骨数50、圧倒的
    tail = _pb("TailRoot", 1, limit_type="None")  # 骨数1、最小
    pbj = _physbones(*non_tail, tail)
    plan = m.allocate(physbones_json=pbj, capacity=1)
    assert len(plan.accepted) == 1
    assert plan.accepted[0].anchor == "TailRoot"
    assert plan.accepted[0].is_tail is True
    assert len(plan.rejected_units) == 5  # non_tail全員があふれる


# --- dev#1551 受入ゲート2-②: 容量あふれ鎖は完全に無傷で残る ----------------

def test_overflow_chain_is_left_completely_untouched():
    """issue #1551 受入ゲート「容量あふれ鎖: 完全に無傷で残す(配線しない・
    削除しない・座標を動かさない)」の直接検査: 非採用になったunitでも、
    `sway_allocator`自体はそのunitのanchor/chains/bone_countを一切改変
    しない(削除も座標変更もしない、`excluded_reason`だけが追加される)。
    座標(head/tail transform)はこのモジュールの管轄外(bpy非依存の
    純関数のため元データを持たない)——ここで検証できるのは「参照している
    骨名の集合が入力と1バイトも変わらないこと」までであり、座標不変の
    保証は呼び出し側(`pipeline\\blender\\step02_retarget.py`が非採用unitの
    donor骨を一切reparentしないこと)が担う(モジュールレベルの契約:
    `sway_hub.plan_hub_wiring()`は`plan.accepted`だけを読み、
    `plan.rejected_units`を一切参照しない、`sway_hub.py`本体の実装参照)。"""
    entries = [_pb(f"G{10 - i}", 10 - i, limit_type="None") for i in range(10)]
    pbj = _physbones(*entries)
    original_chains = {e["anchor"]: tuple(tuple(c) for c in e["chains"]) for e in entries}
    plan = m.allocate(physbones_json=pbj)
    assert len(plan.rejected_units) == 1
    overflow_unit = plan.rejected_units[0]
    assert overflow_unit.anchor == "G1"
    # chains自体(骨名・順序)は入力と1バイトも変わらない(削除も並び替えも無い)。
    assert overflow_unit.chains == original_chains["G1"]
    assert overflow_unit.bone_count == 1
    # 非採用の唯一の痕跡はexcluded_reasonだけ(座標・骨構造は無傷)。
    assert overflow_unit.excluded_reason is not None
    assert "容量超過で非採用" in overflow_unit.excluded_reason


# --- dev#1551 受入ゲート2-④: マルチアバター容量合算 ------------------------
#
# SPEC.md(dev#1508)§1-5「マルチアバターは合算(同性で分け合う)」の仕様は
# dev#1551でも維持される(BRIEF「MaxAngle→limit_angle写し・マルチアバター
# 容量合算の仕様(dev#1508)は維持」)。実際の複数アバター合成(複数の
# job_dirを1つのpakへ束ねる処理)はSPEC.md §5「複数アバターのドナー分配
# スパイク(未実証)」のとおり本レーンのスコープ外・別レーン後続工事の
# ままだが、`sway_allocator.allocate()`の`capacity`引数は元々「呼び出し側が
# 残り予算を渡す」形の素朴な仕組みであり、1chain=1KP化によって
# 「1 accepted group = 1 KPスロット消費」が厳密に1:1になったことで、
# 複数アバターの呼び出し側が`capacity`引数を単純に減算するだけで合算
# できることが保証される(dev#1508時代は同一アバター内で複数unitが
# 1グループへ統合されることがあり、「accepted件数」と「実際に消費される
# KPスロット数」が食い違いうる=合算の暗黙の前提が崩れるリスクがあった。
# 1chain=1KPでその前提の崩れが構造的に無くなったことの回帰検査)。

def test_multi_avatar_capacity_budget_is_shared_via_capacity_argument():
    """2アバター目の`allocate()`呼び出しに「1アバター目が消費した後の
    残り予算」をそのまま`capacity`として渡せば、2アバター分の合計採用数が
    決して9を超えないことを検査する(1chain=1KPで1 accepted==1スロット
    消費が保証されているため、この単純な引き算だけで合算が正しく成立する)。"""
    avatar_a_pbj = _physbones(*[
        _pb(f"A{i}", 10 - i, limit_type="None") for i in range(6)])  # 6鎖
    avatar_b_pbj = _physbones(*[
        _pb(f"B{i}", 10 - i, limit_type="None") for i in range(6)])  # 6鎖(単独なら6採用)

    plan_a = m.allocate(physbones_json=avatar_a_pbj, capacity=9)
    assert len(plan_a.accepted) == 6  # アバターA単独では6本とも容量内

    remaining_budget = 9 - len(plan_a.accepted)  # 呼び出し側が合算を行う想定の計算
    assert remaining_budget == 3
    plan_b = m.allocate(physbones_json=avatar_b_pbj, capacity=remaining_budget)
    assert len(plan_b.accepted) == 3  # 残り予算ぶんだけ採用され、残り3本はあふれる
    assert len(plan_b.rejected_units) == 3

    total_accepted = len(plan_a.accepted) + len(plan_b.accepted)
    assert total_accepted == 9  # 2アバター合計で9スロットちょうど(超過しない)
    # 1chain=1KPなので「accepted件数」がそのままKPスロット消費数と一致する
    # (dev#1508時代のグループ統合が無いため、この等号が常に成立する)。
    for g in plan_a.accepted:
        assert len(g.units) == 1
    for g in plan_b.accepted:
        assert len(g.units) == 1


# --- 負の対照: 偏向鎖は採用されない ----------------------------------------

def test_biased_chain_never_accepted():
    pbj = _physbones(
        _pb("Hinged", 5, limit_type="Hinge", max_angle_x=30.0, limit_rotation=(30, 0, 0)),
        _pb("Polared", 5, limit_type="Polar"),
        _pb("OffAxisAngle", 5, limit_type="Angle", limit_rotation=(10, 0, 0)),
    )
    plan = m.allocate(physbones_json=pbj)
    assert plan.accepted == ()
    reasons = {u.anchor: u.excluded_reason for u in plan.rejected_units}
    assert "偏向のため既定OFF" in reasons["Hinged"]
    assert "偏向のため既定OFF" in reasons["Polared"]
    assert "偏向のため既定OFF" in reasons["OffAxisAngle"]


# =====================================================================
# 6. ラボ割当上書きの入口
# =====================================================================

def test_lab_assignments_absent_is_pure_automatic():
    pbj = _load_fixture("physbones_flatapron.json")
    plan_without = m.allocate(physbones_json=pbj)
    plan_with_none = m.allocate(physbones_json=pbj, lab_assignments=None)
    plan_with_empty = m.allocate(physbones_json=pbj, lab_assignments={})
    assert plan_without.accepted == plan_with_none.accepted == plan_with_empty.accepted
    assert plan_without.accepted == ()  # apronはHingeなので既定は非採用


def test_lab_override_can_force_exclude():
    pbj = _load_fixture("physbones_comodo.json")
    units = m.parse_physbones(pbj)
    key = next(u.key for u in units if u.anchor == "Head_L.001")
    plan = m.allocate(physbones_json=pbj,
                       lab_assignments={key: m.LabAssignment(style="kata", enabled=False)})
    accepted_anchors = {g.anchor for g in plan.accepted}
    assert "Head_L.001" not in accepted_anchors
    reasons = {u.key: u.excluded_reason for u in plan.rejected_units}
    assert "ラボ割当でOFF" in reasons[key]


def test_lab_override_can_force_include_biased_chain():
    pbj = _load_fixture("physbones_flatapron.json")
    units = m.parse_physbones(pbj)
    key = units[0].key
    assert units[0].is_biased is True  # 前提: 自動判定では偏向除外
    plan = m.allocate(physbones_json=pbj,
                       lab_assignments={key: m.LabAssignment(style="yawa")})
    assert len(plan.accepted) == 1
    g = plan.accepted[0]
    assert g.style == "yawa"
    assert g.units[0].lab_override is True


# =====================================================================
# 受入3検体(SPEC.md 5b / TRAIN.md記載どおりの仕様全分岐固定)
# =====================================================================

def test_acceptance_comodo_ear_included_by_default_and_quantized():
    """comodoの耳(骨名にear/mimiトークンが無い=耳名なし)が、PBが付いている
    という理由だけで既定採用されること(候補判定が名前非依存=PB尊重に
    なった証拠、SPEC.md 5b)。"""
    pbj = _load_fixture("physbones_comodo.json")
    plan = m.allocate(physbones_json=pbj)
    accepted_anchors = {g.anchor for g in plan.accepted}
    assert "Head_L.001" in accepted_anchors
    assert "Head_R.001" in accepted_anchors
    assert "Tail Root" in accepted_anchors
    for g in plan.accepted:
        assert g.style == sway_quantize.quantize_pb(0.348, 0.49)
        assert g.style == "kata"
    assert plan.rejected_units == ()
    # 尻尾が最優先に来ていること(3件とも採用されるので直接の押し出しは
    # 発生しないが、優先順位キー自体は検証する)
    tail_group = next(g for g in plan.accepted if g.anchor == "Tail Root")
    assert tail_group.is_tail is True


def test_acceptance_flathaori_hinge_excluded_angle_and_none_included():
    """flatHaori(35鎖): 袴(Hinge)26鎖は偏向除外、袖(Angle,rotation=0)6鎖+
    耳2+尻尾1=9鎖は無偏向採用。全採用鎖はちょうど容量9に収まる。"""
    pbj = _load_fixture("physbones_flathaori.json")
    plan = m.allocate(physbones_json=pbj)

    assert len(plan.accepted) == 9
    accepted_anchors = {g.anchor for g in plan.accepted}
    biased_anchor_fragments = ("Spine", "Hips.004$", "Hips_L.", "Hips_R.")
    for anchor in accepted_anchors:
        assert not anchor.startswith(biased_anchor_fragments), anchor

    assert len(plan.rejected_units) == 26
    for u in plan.rejected_units:
        assert u.is_biased is True
        assert "Hinge" in u.bias_reason

    # 袖(Angle型、rotation=0)はmax_angle_x=30がそのままlimit_angleへ写る
    sleeve_groups = [g for g in plan.accepted if "Arm" in g.anchor or "Shoulder" in g.anchor]
    assert len(sleeve_groups) == 6
    for g in sleeve_groups:
        assert g.units[0].limit_angle == pytest.approx(30.0)

    # 耳・尻尾(None型)はlimit_angle=0
    none_groups = [g for g in plan.accepted if g.anchor in ("Head_L.001", "Head_R.001", "Tail Root")]
    assert len(none_groups) == 3
    for g in none_groups:
        assert g.units[0].limit_angle == pytest.approx(0.0)


def test_acceptance_flatapron_hinge_apron_excluded():
    """flatapron: エプロン紐(Hinge, Pitch30)は偏向除外され、既定では
    一切採用されない。"""
    pbj = _load_fixture("physbones_flatapron.json")
    plan = m.allocate(physbones_json=pbj)
    assert plan.accepted == ()
    assert len(plan.rejected_units) == 1
    u = plan.rejected_units[0]
    assert u.is_biased is True
    assert "Hinge" in u.bias_reason
    assert "偏向のため既定OFF" in u.excluded_reason
