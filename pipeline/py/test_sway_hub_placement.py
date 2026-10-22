# -*- coding: utf-8 -*-
"""test_sway_hub_placement.py -- sway_hub_placement.pyの単体テスト
(dev#1508 W2a-2、汎用ハブ配線の座標配置)。実機・pak・Blenderに一切依存しない
(bpy非依存、純粋関数のみ)。
"""
import math
import os
import sys
from dataclasses import replace

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_allocator  # noqa: E402
import sway_hub  # noqa: E402
import sway_hub_placement as shp  # noqa: E402


def _catalog_and_hub_slots():
    """1ハブ(hubA/hubA_m)+基幹リグ(pelvis/head/chestPal)+自由骨6本
    (free01..free06)の合成共有Skeleton。座標は単純化のため一直線
    (+Z軸)に配置(quat=恒等)し、手計算で検証できるようにしてある。

    pal_pelvis world=(0,0,10)、pal_head world=(0,0,60) -> pal_len=50。
    chestPal world=(0,0,30)(pelvisの子、anchor_pal_name_ofの写像先)。

    free03までは2026-08-16のanchorオフバイワン修正(`sway_hub.
    plan_hub_wiring()`が各チェーンに`group.anchor`ぶんのdonorを追加で1本
    要求するようになった)に伴い追加(旧2本→3本、`ChestAnchor`donorぶん)。
    free04-06は2026-08-17のdev#1551性別またぎdedup漏れ修正
    (`hubA`/`hubA_m`はbivariantなので女性向け/男性向けで互いに素な
    donor骨集合が要る、`ChainDonorPlan.donor_chain_for()`docstring参照)に
    伴い追加——女性向けは常に自由プール先頭の3本(free01-03、貪欲消費の
    順序どおり)を得るため、既存の"Female"向け期待値(座標・ステップ列)は
    無変更のまま成立する。男性向けは残りの3本(free04-06)を得る。"""
    defs = [
        ("root", -1, (0.0, 0.0, 0.0)),
        ("pelvis", 0, (0.0, 0.0, 10.0)),
        ("head", 1, (0.0, 0.0, 50.0)),
        ("chestPal", 1, (0.0, 0.0, 20.0)),
        ("hubA", 0, (5.0, 0.0, 0.0)),      # vanilla位置(reparentで上書きされる)
        ("hubA_m", 0, (6.0, 0.0, 0.0)),
        ("free01", 0, (1.0, 0.0, 0.0)),
        ("free02", 0, (2.0, 0.0, 0.0)),
        ("free03", 0, (3.0, 0.0, 0.0)),
        ("free04", 0, (4.0, 0.0, 0.0)),
        ("free05", 0, (5.5, 0.0, 0.0)),
        ("free06", 0, (6.5, 0.0, 0.0)),
    ]
    bones = [{"name": n, "parent_idx": p, "quat": [0.0, 0.0, 0.0, 1.0],
              "pos": list(pos), "scale": [1.0, 1.0, 1.0]} for n, p, pos in defs]
    catalog = sway_hub.SkeletonCatalog.from_bones_list(bones)
    hub_slots = sway_hub.HubSlots(female=("hubA",), male=("hubA_m",))
    return catalog, hub_slots


def _one_chain_wiring(catalog, hub_slots, chain=("tail_01", "tail_02")):
    protected = frozenset({"pelvis", "head", "chestPal"})
    reserved = frozenset()
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "ChestAnchor", "chains": [list(chain)],
         "params": {"limit_type": "None", "pull": 0.5, "spring": 0.5}},
    ]}
    plan = sway_allocator.allocate(physbones_json=physbones)
    return sway_hub.plan_hub_wiring(plan, catalog, hub_slots, reserved, protected=protected)


# 相似変換: av_len=|Head-Hips|=5.0(生値) -> pal_len(50)/av_len(5)=10倍スケール
_AVATAR_DUMP = {
    "Hips": {"head": [0.0, 0.0, 1.0], "tail": [0.0, 0.0, 1.0]},
    "Head": {"head": [0.0, 0.0, 6.0], "tail": [0.0, 0.0, 6.0]},
    "ChestAnchor": {"head": [0.0, 0.0, 3.0], "tail": [0.0, 0.0, 3.0]},
    "tail_01": {"head": [0.0, 0.0, 4.0], "tail": [0.0, 0.0, 4.0]},
    "tail_02": {"head": [0.0, 0.0, 5.0], "tail": [0.0, 0.0, 5.5]},
}
_ANCHOR_MAP = {"ChestAnchor": "chestPal"}

# dev#1551(ゼロ長root廃止修理): `_AVATAR_DUMP`はChestAnchor(anchor自身)が
# 偶然anchor_pal(chestPal)と同座標(0,0,30)になるよう選ばれているため、
# 「hub rootがanchor自身の位置に来る」ことと「hub rootが恒等(anchor_pal
# 位置)のまま」ことが数値上区別できない。ChestAnchorをchestPalとは異なる
# 座標に置いた変種で、hub rootの新しい位置(anchor自身の実位置)が
# 恒等とも旧「鎖始点(tail_01)」位置とも異なることを明確に区別できるように
# する。ChestAnchor raw(0,0,2.5) -> world (2.5-1)*10+10=(0,0,25.0)
# (anchor_pal(0,0,30)ともtail_01(0,0,40)とも異なる値)。
_AVATAR_DUMP_ANCHOR_OFFSET = dict(_AVATAR_DUMP)
_AVATAR_DUMP_ANCHOR_OFFSET["ChestAnchor"] = {
    "head": [0.0, 0.0, 2.5], "tail": [0.0, 0.0, 2.5]}


# =====================================================================
# compute_similarity / av_world
# =====================================================================

def test_compute_similarity_scale_and_pelvis_anchor():
    catalog, hub_slots = _catalog_and_hub_slots()
    fk = shp.build_catalog_fk(catalog)
    sim = shp.compute_similarity(_AVATAR_DUMP, catalog, fk)
    assert sim.scale == pytest.approx(10.0)
    assert sim.pal_pelvis_world == (0.0, 0.0, 10.0)


def test_compute_similarity_rejects_missing_anchor_bones():
    catalog, _hub_slots = _catalog_and_hub_slots()
    fk = shp.build_catalog_fk(catalog)
    with pytest.raises(shp.SwayHubPlacementError, match="missing required anchor"):
        shp.compute_similarity({}, catalog, fk)


# =====================================================================
# select_first_resolved_hub_segment -- 制御構造の単一ソース化
# (dev#1551ゼロ長root廃止修理、issue #1551、正本
# work\run_1551\laneR1_rootfix\RESULT.md)
# =====================================================================

class _FakeChainPlan:
    """`select_first_resolved_hub_segment()`テスト用の最小フェイク
    (`.source_chain`属性のみ持つ、`sway_hub.ChainDonorPlan`の代替)。"""
    def __init__(self, source_chain):
        self.source_chain = tuple(source_chain)


def test_select_first_resolved_hub_segment_uses_resolve_callback():
    """`resolve(cp)`が呼ばれ、その戻り値(head/tailペア)がそのまま返る
    ——`av_point(source_chain[0])`/`av_point(source_chain[1])`相当の
    呼び出しを最小フェイクで検証する(bpy非依存)。"""
    calls = []

    def resolve(cp):
        calls.append(cp.source_chain)
        return (cp.source_chain[0], cp.source_chain[1])

    plans = [_FakeChainPlan(("anchor", "tail_01", "tail_02"))]
    result = shp.select_first_resolved_hub_segment(plans, resolve)
    assert calls == [("anchor", "tail_01", "tail_02")]
    assert result == ("anchor", "tail_01")


def test_select_first_resolved_hub_segment_falls_through_to_next_plan_when_unresolved():
    """最初の`chain_plans`要素が`resolve`でNone(解決不能)を返したら、
    次の要素を試す——`_hub_root_real_segment_transform()`の
    `for cp in gp.chain_plans: ... continue`相当のループと同じ制御構造。"""
    plans = [_FakeChainPlan(("anchor", "missing_01")),
             _FakeChainPlan(("anchor", "tail_01"))]

    def resolve(cp):
        if "missing_01" in cp.source_chain:
            return None
        return ("ok", cp.source_chain[1])

    result = shp.select_first_resolved_hub_segment(plans, resolve)
    assert result == ("ok", "tail_01")


def test_select_first_resolved_hub_segment_returns_none_when_all_unresolved_negative_control():
    """負の対照: 全`chain_plans`が解決不能なら`None`を返す(恒等
    フォールバックへ委ねるべき状態)——「常に何かを返してしまう」誤り
    (フォールバックが働かなくなり、恒等バグへ先祖返りする)を検出する。"""
    plans = [_FakeChainPlan(("anchor", "missing_01")),
             _FakeChainPlan(("anchor",))]
    result = shp.select_first_resolved_hub_segment(plans, lambda cp: None)
    assert result is None


def test_select_first_resolved_hub_segment_empty_plans_returns_none():
    """`chain_plans`が空なら即`None`(退化ケース、恒等フォールバック)。"""
    assert shp.select_first_resolved_hub_segment([], lambda cp: "unreachable") is None


def test_hub_root_real_segment_transform_positions_hub_at_anchor_not_chain_start():
    """dev#1551(ゼロ長root廃止修理)の核心: hub rootは「鎖始点
    (chain[0]=tail_01)」ではなく「source_chain[0](=anchor自身)」の実位置に
    置かれる。`_AVATAR_DUMP_ANCHOR_OFFSET`(ChestAnchor world=(0,0,25.0)、
    anchor_pal(chestPal)=(0,0,30.0)、旧「鎖始点」tail_01=(0,0,40.0)の
    3つが全て異なる値)を使い、結果が(0,0,25.0)相当(=anchor自身)に
    一致し、恒等((0,0,0))にも旧「鎖始点」相当((0,0,10))にも一致しない
    ことを確認する。"""
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots)
    steps = shp.plan_reparent_steps(
        wiring, catalog, "Female", _AVATAR_DUMP_ANCHOR_OFFSET, _ANCHOR_MAP)
    _lq, lp, _ls = steps[0].new_local_transform
    # anchor_pal(chestPal)world=(0,0,30.0)、ChestAnchor world=(0,0,25.0)。
    # ローカル位置=(0,0,25.0-30.0)=(0,0,-5.0)。
    assert lp == pytest.approx((0.0, 0.0, -5.0))
    assert lp != pytest.approx((0.0, 0.0, 0.0))       # 恒等でない
    assert lp != pytest.approx((0.0, 0.0, 10.0))      # 旧「鎖始点」でもない


# =====================================================================
# plan_reparent_steps -- ハブ本体
# =====================================================================

def test_plan_reparent_steps_hub_gets_anchor_real_segment_under_anchor_pal():
    """dev#1551(ゼロ長root廃止修理、issue #1551、正本
    work\\run_1551\\laneR1_rootfix\\RESULT.md): hub root自身の配置は、
    もはや`anchor_pal`と恒等(=完全同位置)ではなく、「source_chain[0]
    (=anchor自身)」のアバター実rest位置・向きへ配置される。

    手計算(モジュールdocstring/`_AVATAR_DUMP`参照):
    anchor_pal(chestPal)world=(0,0,30)、ChestAnchor(anchor自身)world=
    (0,0,30)(このフィクスチャでは偶然anchor_palと同座標——位置の区別は
    `test_hub_root_real_segment_transform_positions_hub_at_anchor_not_
    chain_start`が`_AVATAR_DUMP_ANCHOR_OFFSET`で別途証明済み)。
    ローカル位置=(0,0,0)。
    ローカル回転=anchorからsource_chain[1](=tail_01)への方向((0,0,1))へ、
    ローカル+X軸を向けるquat(`q_find_between()`と同じ規約、下で直接
    計算し二重実装しない)。"""
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots)
    steps = shp.plan_reparent_steps(
        wiring, catalog, "Female", _AVATAR_DUMP, _ANCHOR_MAP)
    hub_step = steps[0]
    assert hub_step.target == "hubA"
    assert hub_step.new_parent == "chestPal"

    expected_quat = shp.q_find_between((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    lq, lp, ls = hub_step.new_local_transform
    assert lp == pytest.approx((0.0, 0.0, 0.0))
    assert lq == pytest.approx(expected_quat)
    assert ls == (1.0, 1.0, 1.0)


def test_plan_reparent_steps_hub_natural_transform_is_not_identity_dev1551_negative_control():
    """負の対照(dev#1551受入条件②): hub rootの向きは、anchorから
    source_chain[1]方向を向くquatを持つ——位置は`_AVATAR_DUMP`では偶然
    anchor_palと一致するが、`new_local_transform`全体(quat込み)としては
    `IDENTITY_TRANSFORM`(quat恒等)には一致しない。旧「常に恒等
    (quat/pos両方)」バグが再発すれば、このアサーションが検出する。"""
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots)
    steps = shp.plan_reparent_steps(
        wiring, catalog, "Female", _AVATAR_DUMP, _ANCHOR_MAP)
    assert steps[0].new_local_transform != shp.IDENTITY_TRANSFORM


def test_plan_reparent_steps_hub_falls_back_to_anchor_position_when_chain_empty():
    """鎖が空(anchor自身のみ、`source_chain`長1)の場合でも、hub root自身は
    引き続きsource_chain[0](=anchor自身)の位置に置かれる——`_hub_root_
    real_segment_transform()`docstring参照。このフィクスチャでは偶然
    anchor(ChestAnchor world=(0,0,30))がanchor_pal(chestPal world=
    (0,0,30))と同座標のため、結果は恒等と数値的に一致する(これは
    「常に恒等」への先祖返りではなく、たまたまこのフィクスチャでanchor
    自身がanchor_pal位置にある、という独立した理由による一致——上の
    `_AVATAR_DUMP_ANCHOR_OFFSET`を使うテストが恒等でないことを別途
    証明している)。"""
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots, chain=())
    steps = shp.plan_reparent_steps(
        wiring, catalog, "Female", _AVATAR_DUMP, _ANCHOR_MAP)
    hub_step = steps[0]
    assert hub_step.target == "hubA"
    lq, lp, _ls = hub_step.new_local_transform
    assert lp == pytest.approx((0.0, 0.0, 0.0))


def test_plan_reparent_steps_hub_natural_transform_uses_exact_donor_world_when_available():
    """`exact_donor_world`(2026-08-16実機実測バグ修正)にhub root自身の
    骨名(`hubA`)があれば、近似計算ではなくその値をそのまま使う——
    dev#1551(ゼロ長root廃止修理)により、hub自身が`exact_donor_world`の
    直接のキーになった(旧実装は`donor_chain[start_idx]`経由で間接的に
    引いていた)。"""
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots)
    exact_quat = (0.0, 0.0, 0.0, 1.0)
    exact_pos = (7.0, 8.0, 9.0)  # 近似結果(0,0,30)とは全く異なる値
    steps = shp.plan_reparent_steps(
        wiring, catalog, "Female", _AVATAR_DUMP, _ANCHOR_MAP,
        exact_donor_world={"hubA": (exact_quat, exact_pos)})
    hub_step = steps[0]
    lq, lp, _ls = hub_step.new_local_transform
    # anchor_pal(chestPal)world=(0,0,30)、anchor_pal quatは恒等なので
    # ローカル位置=exact_pos - anchor_pal_world そのもの。
    assert lp == pytest.approx((7.0, 8.0, -21.0))
    assert lq == pytest.approx(exact_quat)


def test_plan_reparent_steps_selects_male_hub_when_gender_male():
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots)
    steps = shp.plan_reparent_steps(
        wiring, catalog, "Male", _AVATAR_DUMP, _ANCHOR_MAP)
    assert steps[0].target == "hubA_m"


# =====================================================================
# plan_reparent_steps -- donor鎖(exact-bone-copy)
# =====================================================================

def test_plan_reparent_steps_donor_chain_world_positions_match_avatar_geometry():
    """donor鎖の各節が、アバター側実座標(相似変換後)へ正しく配置される
    ことを、ローカル変換からworld座標を再構成して検証する。

    dev#1551(ゼロ長root廃止修理)により、hub root自身が`ChestAnchor`
    (anchor自身)ぶんの実節を担うようになったため、donor鎖(free01-03)は
    内容写像を1つ繰り上げて`tail_01`/`tail_02`/(延長分)を持つ。

    期待world位置(手計算、モジュールdocstring/テストヘルパー参照):
    ChestAnchor raw(0,0,3) -> world (0,0,30)(hub root自身が持つ、偶然
    chestPalと同座標、フィクスチャの選び方)
    tail_01 head raw(0,0,4) -> world (0,0,40)(free01)
    tail_02 head raw(0,0,5) -> world (0,0,50)(free02)
    tail_02 tail raw(0,0,5.5) -> world (0,0,55)(tip、free03=延長分は
    tipそのものに一致——余剰donor1本ぶんの延長が丁度tip止まり)
    """
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots)
    steps = shp.plan_reparent_steps(
        wiring, catalog, "Female", _AVATAR_DUMP, _ANCHOR_MAP)

    assert [s.target for s in steps] == ["hubA", "free01", "free02", "free03"]
    assert [s.new_parent for s in steps] == ["chestPal", "hubA", "free01", "free02"]

    # world座標を再構成(dev#1551: ハブ自身の位置はもう恒等=chestPal位置では
    # ない——`steps[0]`のnew_local_transformからハブの実worldを逆算する。
    # anchor_pal(chestPal)自身のworld/quatはフィクスチャの既知値(恒等quat))。
    anchor_pal_world = (0.0, 0.0, 30.0)
    anchor_pal_quat = (0.0, 0.0, 0.0, 1.0)
    hub_lq, hub_lp, _hub_ls = steps[0].new_local_transform
    hub_world = shp.v_add(anchor_pal_world, shp.q_rotate(anchor_pal_quat, hub_lp))
    hub_quat = shp.q_mul(anchor_pal_quat, hub_lq)
    assert hub_world == pytest.approx((0.0, 0.0, 30.0))  # ChestAnchor自身

    free01_step = steps[1]  # tail_01 donor(内容写像が1つ繰り上がった)
    lq, lp, _ls = free01_step.new_local_transform
    free01_world = shp.v_add(hub_world, shp.q_rotate(hub_quat, lp))
    free01_quat = shp.q_mul(hub_quat, lq)
    assert free01_world == pytest.approx((0.0, 0.0, 40.0))

    free02_step = steps[2]  # tail_02 donor
    lq2, lp2, _ls2 = free02_step.new_local_transform
    free02_world = shp.v_add(free01_world, shp.q_rotate(free01_quat, lp2))
    free02_quat = shp.q_mul(free01_quat, lq2)
    assert free02_world == pytest.approx((0.0, 0.0, 50.0))

    free03_step = steps[3]  # 余剰donor(tail_02のtail=tip方向へ延長)
    lq3, lp3, _ls3 = free03_step.new_local_transform
    free03_world = shp.v_add(free02_world, shp.q_rotate(free02_quat, lp3))
    assert free03_world == pytest.approx((0.0, 0.0, 55.0))


def test_plan_reparent_steps_exact_donor_world_overrides_approximation():
    """dev#1508 実機実測バグ修正(2026-08-16): `exact_donor_world`に骨名が
    あれば、`avatar_dump`+相似変換による近似計算(chibi-fit後の非一様な
    関節移動を反映できず、Blenderの実配置と最大約35cm級でズレていた)を
    使わず、指定した値をそのまま採用する。ここでは近似結果
    ((0,0,50)、上のテストで確認済み)とは明確に異なる値を与え、その値が
    そのまま再構成されることを確認する(=exact_donor_worldが確実に優先
    されている証拠)。"""
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots)
    exact_quat = (0.0, 0.0, 0.0, 1.0)
    exact_pos = (99.0, 5.0, 12.0)  # 近似結果(0,0,50)とは全く異なる値
    steps = shp.plan_reparent_steps(
        wiring, catalog, "Female", _AVATAR_DUMP, _ANCHOR_MAP,
        exact_donor_world={"free02": (exact_quat, exact_pos)})

    # dev#1551(ゼロ長root廃止修理): hub自身は"hubA"という別キーで
    # exact_donor_worldを引く(このテストでは未指定のため近似計算のまま)。
    # "free02"(tail_02のdonor)だけがexact override対象。
    anchor_pal_world = (0.0, 0.0, 30.0)
    anchor_pal_quat = (0.0, 0.0, 0.0, 1.0)
    hub_lq, hub_lp, _hub_ls = steps[0].new_local_transform
    hub_world = shp.v_add(anchor_pal_world, shp.q_rotate(anchor_pal_quat, hub_lp))
    hub_quat = shp.q_mul(anchor_pal_quat, hub_lq)
    free01_step = steps[1]
    lq, lp, _ls = free01_step.new_local_transform
    free01_world = shp.v_add(hub_world, shp.q_rotate(hub_quat, lp))
    free01_quat = shp.q_mul(hub_quat, lq)

    free02_step = steps[2]
    assert free02_step.tag.endswith(":exact")
    lq2, lp2, _ls2 = free02_step.new_local_transform
    free02_world = shp.v_add(free01_world, shp.q_rotate(free01_quat, lp2))
    assert free02_world == pytest.approx(exact_pos)

    # free03(override無し)は引き続き近似計算にフォールバックする
    free03_step = steps[3]
    assert not free03_step.tag.endswith(":exact")


def test_plan_reparent_steps_donor_chain_length_matches_source():
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots)
    steps = shp.plan_reparent_steps(
        wiring, catalog, "Female", _AVATAR_DUMP, _ANCHOR_MAP)
    donor_steps = [s for s in steps if s.tag.startswith("donor:")]
    # dev#1551(ゼロ長root廃止修理): ChestAnchor(anchor自身)は今やhub root
    # 自身が担う。donor鎖(free01/free02/free03)はtail_01/tail_02/延長分。
    assert len(donor_steps) == 3


def test_plan_reparent_steps_empty_wiring_is_noop():
    catalog, hub_slots = _catalog_and_hub_slots()
    empty = sway_hub.HubWiringPlan(group_plans=(), unassignable=())
    steps = shp.plan_reparent_steps(empty, catalog, "Female", {}, {})
    assert steps == []


# ---- 負の対照(意図的に壊すと検出されることの証明) ----

def test_plan_reparent_steps_rejects_missing_anchor_pal_mapping():
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots)
    with pytest.raises(shp.SwayHubPlacementError, match="no PAL-side retarget mapping"):
        shp.plan_reparent_steps(wiring, catalog, "Female", _AVATAR_DUMP, {})


def test_plan_reparent_steps_rejects_unresolved_avatar_chain():
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots, chain=("ghost_01", "ghost_02"))
    avatar_dump_no_chain = {
        "Hips": _AVATAR_DUMP["Hips"], "Head": _AVATAR_DUMP["Head"],
        # ChestAnchor自身も無い -> 退化フォールバックも不可能、確実に失敗する
    }
    with pytest.raises(shp.SwayHubPlacementError, match="unresolved avatar bone"):
        shp.plan_reparent_steps(
            wiring, catalog, "Female", avatar_dump_no_chain, _ANCHOR_MAP)


def test_plan_reparent_steps_rejects_unknown_anchor_pal_bone():
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots)
    with pytest.raises(shp.SwayHubPlacementError, match="anchor PAL bone not found"):
        shp.plan_reparent_steps(
            wiring, catalog, "Female", _AVATAR_DUMP,
            {"ChestAnchor": "no_such_pal_bone"})


# =====================================================================
# resolve_source_chain -- 退化ケース(anchorフォールバック)
# =====================================================================

def test_resolve_source_chain_falls_back_to_anchor_when_chain_unresolved():
    sim = shp.Similarity(scale=1.0, avatar_hips_raw=(0.0, 0.0, 0.0),
                          pal_pelvis_world=(0.0, 0.0, 0.0))
    avatar_dump = {"MyAnchor": {"head": [1.0, 2.0, 3.0], "tail": [1.0, 2.0, 3.0]}}
    points, tip, used = shp.resolve_source_chain(
        avatar_dump, sim, ["MyAnchor_end"], anchor_name="MyAnchor")
    assert points == [(1.0, 2.0, 3.0)]
    assert tip == (1.0, 2.0, 5.0)  # +Z 2cm延長
    assert "degenerate chain" in used[0]


def test_resolve_source_chain_trims_unresolved_end_marker():
    sim = shp.Similarity(scale=1.0, avatar_hips_raw=(0.0, 0.0, 0.0),
                          pal_pelvis_world=(0.0, 0.0, 0.0))
    avatar_dump = {
        "bone1": {"head": [0.0, 0.0, 0.0], "tail": [0.0, 0.0, 1.0]},
    }
    points, tip, used = shp.resolve_source_chain(
        avatar_dump, sim, ["bone1", "bone1_end"], anchor_name="bone1")
    assert used == ["bone1"]  # "_end"は実在しないためtrimされる
    assert points == [(0.0, 0.0, 0.0)]
    assert tip == (0.0, 0.0, 1.0)  # bone1自身のtail


def test_resolve_source_chain_returns_none_when_fully_unresolved():
    sim = shp.Similarity(scale=1.0, avatar_hips_raw=(0.0, 0.0, 0.0),
                          pal_pelvis_world=(0.0, 0.0, 0.0))
    points, tip, used = shp.resolve_source_chain({}, sim, ["ghost"], anchor_name="also_ghost")
    assert points is None
    assert tip is None


# =====================================================================
# place_chain -- 負の対照
# =====================================================================

def test_place_chain_rejects_donor_shorter_than_source():
    with pytest.raises(shp.SwayHubPlacementError, match="shorter than source"):
        shp.place_chain([(0.0, 0.0, 0.0), (0.0, 0.0, 1.0)], (0.0, 0.0, 2.0), ["only_one_donor"])


# =====================================================================
# resolve_grouped_chain -- dev#1572(夜間便2、issue #1572追記「フィット
# 計画を単一ソースに」): 幾何(donor rest配置)がウェイト側
# (`sway_hub.donor_group_members()`/`sway_hub_wire.
# source_to_donor_bone_map()`)と同じグループ境界(塊の先頭骨head〜
# 末尾骨tail)を使うことの検査+負の対照。
# =====================================================================

_IDENTITY_SIM = shp.Similarity(
    scale=1.0, avatar_hips_raw=(0.0, 0.0, 0.0), pal_pelvis_world=(0.0, 0.0, 0.0))

# 4骨(anchor,m1,m2,m3)を+Z方向へ1mずつ並べた合成avatar_dump
# (identity similarity=raw座標そのまま読める)。
_GROUPED_CHAIN_AVATAR_DUMP = {
    "anchor": {"head": (0.0, 0.0, 0.0), "tail": (0.0, 0.0, 1.0)},
    "m1": {"head": (0.0, 0.0, 1.0), "tail": (0.0, 0.0, 2.0)},
    "m2": {"head": (0.0, 0.0, 2.0), "tail": (0.0, 0.0, 3.0)},
    "m3": {"head": (0.0, 0.0, 3.0), "tail": (0.0, 0.0, 4.0)},
}


def _grouped_chain_donor_plan():
    # fit_chain_to_length(("anchor","m1","m2","m3"), 3): root=anchor単独、
    # rest=[m1,m2,m3]をn_groups_rest=2へ分配(sizes=[1,2]、余りは先端側)
    # -> group1=[m1](代表m1)、group2=[m2,m3](代表m3)。
    fitted, expansion = sway_hub.fit_chain_to_length(
        ("anchor", "m1", "m2", "m3"), 3)
    assert fitted == ("anchor", "m1", "m3")
    return sway_hub.ChainDonorPlan(
        source_chain=fitted,
        donor_chain_female=("d0", "d1"), donor_chain_male=("d0", "d1"),
        weight_expansion=expansion)


def test_resolve_grouped_chain_uses_group_first_member_head_and_last_member_tail():
    cp = _grouped_chain_donor_plan()

    anchor_pt, heads, tails, _used = shp.resolve_grouped_chain(
        _GROUPED_CHAIN_AVATAR_DUMP, _IDENTITY_SIM, cp,
        anchor_name="anchor", donor_chain=("d0", "d1"))

    assert anchor_pt == (0.0, 0.0, 0.0)
    # d0 <- group{m1}(単独): head/tailともm1自身のexactコピー。
    assert heads[0] == (0.0, 0.0, 1.0)
    assert tails[0] == (0.0, 0.0, 2.0)
    # d1 <- group{m2,m3}(マージ): head=先頭骨m2のhead、tail=末尾骨m3のtail
    # (m3=代表自身の短い区間(3.0->4.0)ではなく、m2からの全スパン)。
    assert heads[1] == (0.0, 0.0, 2.0)
    assert tails[1] == (0.0, 0.0, 4.0)


def test_resolve_grouped_chain_geometry_boundary_matches_weight_group_boundary():
    """本WPの主眼: 幾何(`resolve_grouped_chain()`)が返すグループ境界が、
    ウェイト側の実際のグループ境界(`sway_hub.donor_group_members()`、
    `source_to_donor_bone_map()`が使うのと同じ関数)と一致することを直接
    比較する。"""
    cp = _grouped_chain_donor_plan()
    weight_groups = sway_hub.donor_group_members(cp)  # {"anchor": (...), "m1": (...), "m3": (...)}

    _anchor_pt, heads, tails, _used = shp.resolve_grouped_chain(
        _GROUPED_CHAIN_AVATAR_DUMP, _IDENTITY_SIM, cp,
        anchor_name="anchor", donor_chain=("d0", "d1"))

    # source_chain[1]="m1" -> donor d0 -> weight_groups["m1"]=("m1",)
    m1_members = weight_groups["m1"]
    assert heads[0] == _GROUPED_CHAIN_AVATAR_DUMP[m1_members[0]]["head"]
    assert tails[0] == _GROUPED_CHAIN_AVATAR_DUMP[m1_members[-1]]["tail"]

    # source_chain[2]="m3" -> donor d1 -> weight_groups["m3"]=("m2","m3")
    m3_members = weight_groups["m3"]
    assert heads[1] == _GROUPED_CHAIN_AVATAR_DUMP[m3_members[0]]["head"]
    assert tails[1] == _GROUPED_CHAIN_AVATAR_DUMP[m3_members[-1]]["tail"]


def test_resolve_grouped_chain_negative_control_representative_point_alone_is_wrong():
    """負の対照: 旧実装(代表骨名を単なる1点としてav_worldする)がやって
    いたことを再現し、修理後の値と食い違うことを示す——「修理」が実際に
    何か変えていることの証明(no-opでないことの確認)。"""
    cp = _grouped_chain_donor_plan()

    _anchor_pt, heads, _tails, _used = shp.resolve_grouped_chain(
        _GROUPED_CHAIN_AVATAR_DUMP, _IDENTITY_SIM, cp,
        anchor_name="anchor", donor_chain=("d0", "d1"))

    # 旧バグ相当: 代表名(cp.source_chain[2]="m3")自身をそのままav_worldした
    # 場合のhead(=m3自身のhead、マージ区間の末尾側)。
    rep = cp.source_chain[2]
    assert rep == "m3"
    buggy_head = shp.av_world(_GROUPED_CHAIN_AVATAR_DUMP, _IDENTITY_SIM, rep)
    assert buggy_head == (0.0, 0.0, 3.0)

    # 修理後は塊の先頭骨(m2)のheadを使うため、旧バグの値とは異なる。
    assert heads[1] != buggy_head
    assert heads[1] == (0.0, 0.0, 2.0)


def test_resolve_grouped_chain_extension_donors_continue_straight_no_gap():
    """dev#1572(2026-08-19朝追加裁定「余剰donorの先端延長を全donor登録へ
    訂正」): `donor_chain`が`cp.source_chain`の内容写像(`len(src)-1`)より
    長い場合(=`sway_hub.plan_hub_wiring()`が付ける無ウェイト延長donor)、
    延長分は「最後の内容セグメントと同じseg_vec方向・同長」で直線継続し、
    (a) 内容とのあいだに空隙が無い(前donorのtail==次donorのhead)、
    (b) 延長donor同士も同じ理由で連結、(c) 各延長segmentの長さ・方向が
    最後の内容segmentのseg_vecと一致することを確認する
    (`sway_hub.fit_chain_to_length()`docstring「マージ塊のdonorノード
    幾何」の「余剰donor」規約、モジュールの既存「余剰donor」分岐
    (`src_idx >= len(src): continue`)が実際に発動する初のテスト——
    従来donor_chainは常に`len(src)-1`ぴったりだったため、この分岐は
    死んでいた)。"""
    cp = _grouped_chain_donor_plan()  # source_chain=("anchor","m1","m3")、len(src)=3

    # 内容2本(d0,d1)+延長2本(d2,d3)——sway_hub.plan_hub_wiring()が
    # native_chainの残り全部を付ける形と同じ規約。
    _anchor_pt, heads, tails, _used = shp.resolve_grouped_chain(
        _GROUPED_CHAIN_AVATAR_DUMP, _IDENTITY_SIM, cp,
        anchor_name="anchor", donor_chain=("d0", "d1", "d2", "d3"))

    # 内容側(既存挙動と無変更)。
    assert heads[0] == (0.0, 0.0, 1.0) and tails[0] == (0.0, 0.0, 2.0)
    assert heads[1] == (0.0, 0.0, 2.0) and tails[1] == (0.0, 0.0, 4.0)

    last_content_seg_vec = tuple(t - h for t, h in zip(tails[1], heads[1]))
    assert last_content_seg_vec == (0.0, 0.0, 2.0)

    # (a) 空隙なし: 内容の末尾tailが延長1本目のheadと一致。
    assert heads[2] == tails[1]
    # (b) 延長donor同士も空隙なし。
    assert heads[3] == tails[2]
    # (c) 各延長segmentが最後の内容segmentと同じ方向・同じ長さ(直線継続)。
    ext_seg_2 = tuple(t - h for t, h in zip(tails[2], heads[2]))
    ext_seg_3 = tuple(t - h for t, h in zip(tails[3], heads[3]))
    assert ext_seg_2 == last_content_seg_vec
    assert ext_seg_3 == last_content_seg_vec
    # 実座標そのもの(直線を素直に伸ばした値であることの直接確認)。
    assert heads[2] == (0.0, 0.0, 4.0) and tails[2] == (0.0, 0.0, 6.0)
    assert heads[3] == (0.0, 0.0, 6.0) and tails[3] == (0.0, 0.0, 8.0)


# =====================================================================
# dev#1572(第2便、issue #1572第2報「安全域による節数マージ(特に全結合=
# 内容1本)経路でウェイト消失・フィット崩れが起きる」): 実効節数1の全結合
# (`fit_chain_to_length(chain, 1)`、根本anchorも含めた全要素が単一代表
# ——グループ内で最も先端側=chain[-1]——へマージされる唯一の例外規則)が
# 発動したとき、`resolve_grouped_chain()`/`_hub_root_real_segment_
# transform()`が`cp.source_chain[0]`(=fit後の唯一の代表、この場合は
# **先端**でありanchorではない)をそのままav_worldしていたため、hub root
# 自身のexact geometryと延長donorのseg_vecが「代表自身のごく短い局所区間」
# 基準の異常値になっていた不具合の回帰固定。
#
# オーナー実測(flatapron、Head_L鎖 safety_margin=3、耳容量root込み4・
# ウェイト骨3=n_ext4→target_len=1で全結合発動): (1) 左耳donor根本ボーンが
# 消えたように見える、(2) donorが変な位置(別の骨と同じzになる等)、
# (4) 実機で耳が揺れない——いずれも本節の修理対象。(3)「donor鎖に耳
# ウェイトが無い」は全結合(donor_needed=0)の設計どおりの挙動であり、
# バグではない(全ウェイトはhub root自身へ載る、weight側=`sway_hub_wire.
# source_to_donor_bone_map()`は元から正しい——本節はgeometry側のみを扱う)。
# =====================================================================

def test_resolve_grouped_chain_full_merge_root_included_uses_true_anchor_head():
    """実効節数1の全結合が発動すると、`cp.source_chain`は代表1要素だけの
    タプル(`fitted == ("m3",)`、代表は先端でありanchorではない)になる。
    修理後は`sway_hub.donor_group_members(cp)`経由でグループの**先頭骨**
    (=真のanchor自身)のheadを`anchor_pt`に使う——代表(m3)自身のhead
    (0,0,3、マージ区間のごく一部)ではない。延長donor(内容写像の対応が
    無い、`donor_needed=0`なので3本とも延長)のseg_vecも、真のanchor
    (0,0,0)から代表m3のtail(0,0,4)までの**全スパン**(長さ4.0)を基準に
    直線継続する。"""
    fitted, expansion = sway_hub.fit_chain_to_length(
        ("anchor", "m1", "m2", "m3"), 1)
    assert fitted == ("m3",)  # 代表は先端(m3)——anchorではない
    cp = sway_hub.ChainDonorPlan(
        source_chain=fitted,
        donor_chain_female=("d0", "d1", "d2"), donor_chain_male=("d0", "d1", "d2"),
        weight_expansion=expansion)

    anchor_pt, heads, tails, used = shp.resolve_grouped_chain(
        _GROUPED_CHAIN_AVATAR_DUMP, _IDENTITY_SIM, cp,
        anchor_name="anchor", donor_chain=("d0", "d1", "d2"))

    assert anchor_pt == (0.0, 0.0, 0.0)
    assert used == "source_chain[0] group head"

    assert heads[0] == (0.0, 0.0, 4.0) and tails[0] == (0.0, 0.0, 8.0)
    assert heads[1] == (0.0, 0.0, 8.0) and tails[1] == (0.0, 0.0, 12.0)
    assert heads[2] == (0.0, 0.0, 12.0) and tails[2] == (0.0, 0.0, 16.0)


def test_resolve_grouped_chain_full_merge_negative_control_representative_own_head_is_wrong():
    """負の対照: 旧実装(代表(chain[-1])自身をそのままav_worldして
    anchor_ptとする)が返していた値を再現し、修理後の値と食い違うことを
    示す(「修理」が実際に何か変えていることの証明、no-opでないことの
    確認)。"""
    fitted, expansion = sway_hub.fit_chain_to_length(
        ("anchor", "m1", "m2", "m3"), 1)
    cp = sway_hub.ChainDonorPlan(
        source_chain=fitted,
        donor_chain_female=("d0", "d1", "d2"), donor_chain_male=("d0", "d1", "d2"),
        weight_expansion=expansion)

    anchor_pt, _heads, _tails, _used = shp.resolve_grouped_chain(
        _GROUPED_CHAIN_AVATAR_DUMP, _IDENTITY_SIM, cp,
        anchor_name="anchor", donor_chain=("d0", "d1", "d2"))

    buggy_anchor_pt = shp.av_world(
        _GROUPED_CHAIN_AVATAR_DUMP, _IDENTITY_SIM, cp.source_chain[0])
    assert buggy_anchor_pt == (0.0, 0.0, 3.0)
    assert anchor_pt != buggy_anchor_pt
    assert anchor_pt == (0.0, 0.0, 0.0)


def test_hub_root_real_segment_transform_full_merge_spans_true_anchor_to_tip():
    """`_hub_root_real_segment_transform()`側の同型バグの回帰固定。実効
    節数1の全結合が発動しても、hub root自身のexact geometryは「代表
    (先端)自身の局所区間」ではなく「真のanchorのhead -> 代表(先端)の
    tail」の全スパンになる。"""
    fitted, expansion = sway_hub.fit_chain_to_length(
        ("anchor", "m1", "m2", "m3"), 1)
    cp = sway_hub.ChainDonorPlan(
        source_chain=fitted,
        donor_chain_female=("d0", "d1", "d2"), donor_chain_male=("d0", "d1", "d2"),
        weight_expansion=expansion)

    class _FakeGroup:
        anchor = "anchor"

    gp = sway_hub.GroupHubPlan(
        group=_FakeGroup(), hub_root_female="hubA", hub_root_male="hubA",
        anchor_target="anchor", chain_plans=(cp,))

    _transform, hub_world_pos, hub_world_quat = shp._hub_root_real_segment_transform(
        "hubA", gp, _IDENTITY_SIM, _GROUPED_CHAIN_AVATAR_DUMP,
        anchor_pal_world_pos=(0.0, 0.0, 0.0), anchor_pal_world_quat=(0.0, 0.0, 0.0, 1.0),
        exact_donor_world={})

    # hub root自身のheadは真のanchor(0,0,0)——代表(m3)自身のhead(0,0,3)ではない。
    assert hub_world_pos == pytest.approx((0.0, 0.0, 0.0))
    # 向きはanchor(0,0,0)->m3のtail(0,0,4)方向((1,0,0)->(0,0,1)相当のquat)。
    expected_quat = shp.q_find_between((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert hub_world_quat == pytest.approx(expected_quat)


# =====================================================================
# dev#1551 性別またぎdedup漏れ修正の回帰テスト(正本
# work\run_1551\integG\RESULT.md)。
#
# 根因: pipeline\blender\step02_retarget.pyのsway_hub_reparent.json性別
# マージが`target`名の単純dedupで行われており(素直な追記マージ、既存
# targetは後着で上書きしない)、donor鎖続き骨の絶対名が性別非依存の
# 単一フィールドで払い出されていたため、Male先行処理(既定genders順)で
# Female側のdonor鎖続き骨が丸ごとdedupで落ちていた(実測: 両検体・全
# bivariantタグでFemale側donor鎖0件)。修正は`sway_hub.plan_hub_wiring()`
# 側でbivariantなハブスロットのdonor鎖続き骨を女性向け/男性向けで
# 互いに素な骨集合として払い出すこと(`ChainDonorPlan.donor_chain_for()`)
# ——この結果、素直な追記マージ自体は無変更のまま安全になる。
# =====================================================================

def _merge_reparent_json_steps(existing_steps, new_steps):
    """`pipeline\\blender\\step02_retarget.py`のsway_hub_reparent.json性別
    マージロジック(bpy依存のため単体importできない箇所)をテスト用に
    再現する——「既存targetは後着で上書きしない、素直な追記マージ」その
    ものを1行1行そのまま写した最小再現(本体の該当コメント「性別ごとに
    1回ずつ実行されるこのstep02が...」節参照)。"""
    existing_targets = {s.target for s in existing_steps}
    return list(existing_steps) + [s for s in new_steps if s.target not in existing_targets]


def test_plan_reparent_steps_dev1551_bivariant_donor_chains_survive_gender_merge():
    """dev#1551回帰テスト: bivariantなハブスロット(hubA/hubA_m)で、
    Male→Femaleの順(既定genders順)に`plan_reparent_steps()`を実行し、
    step02_retarget.pyと同じ素直な追記マージ(target名dedup)を適用しても、
    Female側のdonor鎖続き骨が1本も失われないことを確認する(修正前は
    同名donorをMaleが先取りし、Female側の鎖が丸ごとdedupで落ちていた
    ——integG RESULT.md 1-5節)。"""
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots)

    male_steps = shp.plan_reparent_steps(wiring, catalog, "Male", _AVATAR_DUMP, _ANCHOR_MAP)
    female_steps = shp.plan_reparent_steps(wiring, catalog, "Female", _AVATAR_DUMP, _ANCHOR_MAP)
    merged = _merge_reparent_json_steps(male_steps, female_steps)

    male_targets = {s.target for s in male_steps}
    female_targets = {s.target for s in female_steps}
    # 修正の核心: 男女のtargetが完全に互いに素(hub root自身も、donor鎖
    # 続き骨も)——衝突が構造的に起きないため、dedupしても何も失われない。
    assert male_targets.isdisjoint(female_targets)

    merged_targets = {s.target for s in merged}
    assert female_targets <= merged_targets  # Female側が一切dedupで落ちていない
    assert male_targets <= merged_targets

    female_donor_targets = {s.target for s in female_steps if s.tag.startswith("donor:")}
    assert female_donor_targets, "test fixture regressed: no donor steps to check"
    assert female_donor_targets <= merged_targets


def test_plan_reparent_steps_dev1551_negative_control_shared_donor_chain_drops_female_on_merge():
    """負の対照(dev#1551): 修正前の挙動(donor鎖続き骨がfemale/maleで
    **同じ**骨名を共有する、旧`ChainDonorPlan.donor_chain`単一フィールド
    相当)を`ChainDonorPlan`を手動で書き換えて再現すると、同じ素直な
    追記マージ(Male先行)がFemale側のdonor鎖続き骨を丸ごと落とすことを
    示す——本修正が無かったら踏んでいた壊れ方を、このテストが検出できる
    ことの証明。"""
    catalog, hub_slots = _catalog_and_hub_slots()
    wiring = _one_chain_wiring(catalog, hub_slots)
    gp = wiring.group_plans[0]
    cp = gp.chain_plans[0]
    # 修正前の(バグのある)状態を模擬: donor_chain_maleをdonor_chain_female
    # と同じ骨列に強制的に揃える(hub root名だけはbivariantのまま)。
    broken_cp = replace(cp, donor_chain_male=cp.donor_chain_female)
    broken_gp = replace(gp, chain_plans=(broken_cp,))
    broken_wiring = sway_hub.HubWiringPlan(
        group_plans=(broken_gp,), unassignable=wiring.unassignable)

    male_steps = shp.plan_reparent_steps(
        broken_wiring, catalog, "Male", _AVATAR_DUMP, _ANCHOR_MAP)
    female_steps = shp.plan_reparent_steps(
        broken_wiring, catalog, "Female", _AVATAR_DUMP, _ANCHOR_MAP)
    merged = _merge_reparent_json_steps(male_steps, female_steps)
    merged_by_target = {s.target: s for s in merged}  # dedup済みのためtargetごとに1件のみ

    # 鎖の先頭donor(i==0、new_parent=ハブroot名)が判定に最適: 続き骨同士は
    # 同名衝突のせいでnew_parentの値自体は男女で偶然一致する(前の要素の骨名を
    # 指すだけなので)、鎖の先頭だけがnew_parentにhub_root_female/maleという
    # 実際に異なる値を持つ——女性ドナーの実際の親が何になったかを直接検査
    # できる。
    female_head_donor = next(
        s for s in female_steps if s.tag.startswith("donor:") and s.new_parent == gp.hub_root_female)
    merged_entry = merged_by_target[female_head_donor.target]
    # 旧バグの再現: Female側の鎖先頭donorがMale側と同名のため、Male先行
    # マージでdedupにより上書きされず、mergedに残るのは実はMaleが書いた
    # (new_parent=hubA_m の)エントリ——Female向けに実際に使われるはずの
    # new_parent=hubA が失われている。
    assert merged_entry.new_parent != gp.hub_root_female, (
        "negative control failed to reproduce the dev#1551 bug -- the merged "
        "step should have kept Male's new_parent (hub root corruption) when "
        "donor chains are shared across genders")
    assert merged_entry.new_parent == gp.hub_root_male
    # hub root自身(bivariant、常にfemale != male)は引き続き失われない。
    assert gp.hub_root_female in merged_by_target
    assert gp.hub_root_male in merged_by_target
