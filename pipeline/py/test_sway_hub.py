# -*- coding: utf-8 -*-
"""test_sway_hub.py -- sway_hub.pyの単体テスト(dev#1508 W2a-2、汎用ハブ配線)。
実機・pak・Blenderに一切依存しない(bpy非依存、純粋関数のみ)。
"""
import json
import os
import re
import sys
from dataclasses import replace

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_allocator  # noqa: E402
import sway_hub as hub  # noqa: E402
import sway_hub_placement as shp  # noqa: E402

# リポジトリルート配下、work\は.gitignore対象(実データキャッシュ・研究成果物)。
# 開発機には存在するがクリーン環境には無いことがあるため、無ければskip
# (このリポジトリの既存慣習、tests/shipcheck等のskipifパターンを踏襲)。
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_DONOR_CATALOG_CACHE = os.path.join(
    _REPO_ROOT, "work", "rd_19_donorcatalog", "sk_palhuman_full.json")
_RESERVED_BONES_MD = os.path.join(
    _REPO_ROOT, "work", "rd_1423_kpledger", "RESERVED_BONES.md")


def _load_static_reserved_bones_md():
    with open(_RESERVED_BONES_MD, encoding="utf-8") as f:
        text = f.read()
    return set(re.findall(r"^- `([^`]+)`", text, re.MULTILINE))


# =====================================================================
# discover_hub_slots (実物のsway_abp_templates/specs/*.jsonを使う)
# =====================================================================

def test_discover_hub_slots_matches_known_production_layout():
    """dev#1551 Lane P4(服骨root6本の非アニメ骨差し替え、work\\run_1551\\
    laneP4_notes\\NOTES.md §2)で6スロットのroot_boneを更新した。旧F_/M_
    服骨(bivariant、アニメ駆動でintegI実測により条件1未解消)を、共有Skeleton
    上の非服骨(univariant、gendered=False、既存HeadEquip062_ear/
    NPC_GrassBoss…tailと同じ流儀)へ差し替え済み。スロット順・本数
    (F系9/M系10、M_Hunter001_17恒久予備)は不変。"""
    slots = hub.discover_hub_slots()
    assert len(slots.female) == 9
    assert len(slots.male) == 9
    assert slots.female == (
        "NPC_SnowBoss_belt_01_l", "HeadEquip062_ear_01_l", "HeadEquip062_ear_01_r",
        "NPC_SnowBoss_belt_01_r", "HeadEquip046_hairA_01_l", "HeadEquip046_hairA_01_r",
        "NPC_WorldTreeBoss001_skirtD_01_l", "NPC_GrassBoss001_Skin001_hat_cone_01",
        "NPC_GrassBoss001_Skin001_tail_01")
    # 同じスロット順でM側が対応する(男性専用の10本目M_Hunter001_17は含まない)
    assert slots.male[0] == "NPC_SnowBoss_belt_01_l"
    assert "M_Hunter001_17" not in slots.male
    # 新root6本はgendered=False(F/M共通の非服骨)のためF/M同名になる
    assert slots.both_names_at(0) == ("NPC_SnowBoss_belt_01_l", "NPC_SnowBoss_belt_01_l")
    assert slots.both_names_at(1) == ("HeadEquip062_ear_01_l", "HeadEquip062_ear_01_l")


def test_discover_hub_slots_rejects_disagreeing_templates(tmp_path):
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    (specs_dir / "spec_F_A.json").write_text(json.dumps({
        "target_abp": "/Game/Pal/Blueprint/Character/Player/Imp_Cloth/ABP_F_A_Implimentation",
        "nodes": [{"root_bone": "bone1"}],
    }), encoding="utf-8")
    (specs_dir / "spec_F_B.json").write_text(json.dumps({
        "target_abp": "/Game/Pal/Blueprint/Character/Player/Imp_Cloth/ABP_F_B_Implimentation",
        "nodes": [{"root_bone": "bone2"}],  # different root_bones -> disagreement
    }), encoding="utf-8")
    (specs_dir / "spec_M_A.json").write_text(json.dumps({
        "target_abp": "/Game/Pal/Blueprint/Character/Player/Imp_Cloth/ABP_M_A_Implimentation",
        "nodes": [{"root_bone": "bone1"}],
    }), encoding="utf-8")
    with pytest.raises(hub.SwayHubError, match="disagree"):
        hub.discover_hub_slots(templates_dir=str(tmp_path))


def test_all_kp_node_root_names_includes_permanent_reserve():
    """discover_hub_slots()が割当スロットから意図的にトリムする男性10本目
    (M_Hunter001_17、恒久予備)は、それでも実在するKPノード(scarf_2)の
    root骨であり、all_kp_node_root_names()には含まれなければならない
    (予約集合計算の正しい入力、モジュールdocstring「予約骨」節参照)。

    dev#1551 Lane P4: 服骨root6本を非服骨(gendered=False、F/M共通名)へ
    差し替えたため、ユニーク名の総数は16(女9本のうちF_/M_専用6本×2+
    共有3本+M_Hunter001_17)から10(新root6本は共有名のため6+共有3本+
    M_Hunter001_17)へ減った(NOTES.md §4参照、意図した設計変更)。"""
    names = hub.all_kp_node_root_names()
    assert len(names) == 10  # 新root6本(F/M共通)+旧共有3本+M_Hunter001_17恒久予備
    assert "M_Hunter001_17" in names
    slots = hub.discover_hub_slots()
    assert "M_Hunter001_17" not in slots.male  # スロットからは意図的にトリムされたまま


def test_discover_hub_slots_rejects_missing_male_counterpart(tmp_path):
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    (specs_dir / "spec_F_A.json").write_text(json.dumps({
        "target_abp": "/Game/Pal/Blueprint/Character/Player/Imp_Cloth/ABP_F_A_Implimentation",
        "nodes": [{"root_bone": "F_Unique_01"}],
    }), encoding="utf-8")
    (specs_dir / "spec_M_A.json").write_text(json.dumps({
        "target_abp": "/Game/Pal/Blueprint/Character/Player/Imp_Cloth/ABP_M_A_Implimentation",
        "nodes": [{"root_bone": "M_Other_01"}],  # slot key mismatch
    }), encoding="utf-8")
    with pytest.raises(hub.SwayHubError, match="missing counterparts"):
        hub.discover_hub_slots(templates_dir=str(tmp_path))


# =====================================================================
# 合成SkeletonCatalog
# =====================================================================

def _synthetic_bones():
    """root -> hub1 -> (hub1_child1, hub1_child2) 、root -> hub2 -> hub2_child1、
    root -> free1..free6 の小さな合成骨格(indexは配列順)。"""
    defs = [
        ("root", -1),
        ("hub1", 0),
        ("hub1_child1", 1),
        ("hub1_child2", 1),
        ("hub2", 0),
        ("hub2_child1", 4),
        ("free1", 0), ("free2", 0), ("free3", 0),
        ("free4", 0), ("free5", 0), ("free6", 0),
    ]
    return [{"name": n, "parent_idx": p, "quat": [0, 0, 0, 1],
             "pos": [0, 0, 0], "scale": [1, 1, 1]} for n, p in defs]


def test_reserved_descendants_of_covers_hub_subtree():
    bones = _synthetic_bones()
    reserved = hub.reserved_descendants_of(["hub1"], bones)
    assert reserved == frozenset({"hub1", "hub1_child1", "hub1_child2"})
    assert "hub2" not in reserved
    assert "free1" not in reserved


@pytest.mark.skipif(
    not os.path.exists(_DONOR_CATALOG_CACHE) or not os.path.exists(_RESERVED_BONES_MD),
    reason="real donor catalog cache / RESERVED_BONES.md not present on this machine")
def test_reserved_descendants_of_matches_static_reserved_bones_md():
    """実測データ固定テスト(指揮者指示: 前任がキャッシュに対して手動確認した
    だけだった4079骨検証を自動テストへ昇格)。`all_kp_node_root_names()`
    (全16本、恒久予備込み)を入力にした`reserved_descendants_of()`が、
    `work\\rd_1423_kpledger\\RESERVED_BONES.md`の静的68本リストと完全一致
    することを検証する。"""
    with open(_DONOR_CATALOG_CACHE, encoding="utf-8") as f:
        catalog = json.load(f)
    assert catalog["bone_count"] == 4079

    hub_names = hub.all_kp_node_root_names()
    reserved = hub.reserved_descendants_of(hub_names, catalog["bones"])
    static = _load_static_reserved_bones_md()
    assert len(static) == 68
    assert reserved == static


@pytest.mark.skipif(
    not os.path.exists(_DONOR_CATALOG_CACHE),
    reason="real donor catalog cache not present on this machine")
def test_reserved_descendants_of_with_hub_slots_only_misses_two_bones():
    """負の対照: discover_hub_slots()の9(女)+9(男、恒久予備トリム済み)を
    入力にすると、恒久予備M_Hunter001_17の子孫2本(M_Hunter001_17自身/
    M_Hunter001_19)が予約から漏れる——これが本WPで修正したバグそのもの
    (`work\\master_writer_progress.md`のPR #1528レビュー記録、指揮者指示の
    最初に直す2件・項目1)。修正後のAPI(`all_kp_node_root_names()`)を
    使わなければ今も再現することを示す回帰の証拠。"""
    with open(_DONOR_CATALOG_CACHE, encoding="utf-8") as f:
        catalog = json.load(f)
    slots = hub.discover_hub_slots()
    buggy_input = list(slots.female) + list(slots.male)  # 9+9=18本(旧実装相当)
    reserved_buggy = hub.reserved_descendants_of(buggy_input, catalog["bones"])
    assert len(reserved_buggy) == 66  # 68本のはずが2本漏れる
    assert "M_Hunter001_17" not in reserved_buggy
    assert "M_Hunter001_19" not in reserved_buggy

    correct_input = hub.all_kp_node_root_names()
    reserved_correct = hub.reserved_descendants_of(correct_input, catalog["bones"])
    assert len(reserved_correct) == 68
    assert "M_Hunter001_17" in reserved_correct
    assert "M_Hunter001_19" in reserved_correct


def test_free_donor_pool_excludes_reserved_and_hub_roots_and_root():
    bones = _synthetic_bones()
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    reserved = hub.reserved_descendants_of(["hub1"], bones)
    pool = hub.free_donor_pool(catalog, reserved, hub_root_names=["hub1", "hub2"])
    assert "root" not in pool  # index 0
    assert "hub1" not in pool
    assert "hub1_child1" not in pool  # reserved (hub1's descendant)
    assert "hub2" not in pool  # excluded as a hub root name itself
    assert "hub2_child1" in pool  # NOT reserved (only hub1's subtree was reserved)
    assert pool == ["hub2_child1", "free1", "free2", "free3", "free4", "free5", "free6"]
    # 元のインデックス昇順で並んでいる(トポロジ制約を満たすための契約)
    idxs = [catalog.index_of(n) for n in pool]
    assert idxs == sorted(idxs)


def _synthetic_bones_with_core_rig():
    """`_synthetic_bones()`に、KPノードのどの子孫でもない基幹人型ボーン
    (pelvis/spine_01/head)を混ぜた合成骨格。free_donor_pool()の
    `protected`引数が無いと、これらもdonor候補として選ばれてしまうこと
    (=本WPで発見・修正した安全上の欠落)を負の対照として固定する。"""
    defs = [
        ("root", -1),
        ("pelvis", 0), ("spine_01", 1), ("head", 2),  # 基幹人型リグ(どのKPノードroot骨の子孫でもない)
        ("hub1", 0),
        ("hub1_child1", 4),
        ("free1", 0), ("free2", 0),
    ]
    return [{"name": n, "parent_idx": p, "quat": [0, 0, 0, 1],
             "pos": [0, 0, 0], "scale": [1, 1, 1]} for n, p in defs]


def test_free_donor_pool_without_protected_leaks_core_rig_bones():
    """負の対照(2026-08-16実データ調査で発見した安全上の欠落): `protected`
    を渡さないと、基幹人型リグ(pelvis/spine_01/head)がdonorプールへ
    紛れ込む——本物の共有Skeletonでは`reserved_descendants_of()`がこれらを
    捕捉しない(どのKPノードroot骨の子孫でもないため)。これが
    `free_donor_pool()`に`protected`引数を追加した理由そのもの。"""
    bones = _synthetic_bones_with_core_rig()
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    reserved = hub.reserved_descendants_of(["hub1"], bones)
    pool = hub.free_donor_pool(catalog, reserved, hub_root_names=["hub1"])
    assert "pelvis" in pool  # BUG(修正前の挙動): 基幹ボーンが混入する
    assert "spine_01" in pool
    assert "head" in pool


def test_free_donor_pool_with_protected_excludes_core_rig_bones():
    """`protected`(実運用では`vanilla\\common_bones.json`の`"common"`
    リスト)を渡すと、基幹人型リグがdonorプールから正しく除外される。"""
    bones = _synthetic_bones_with_core_rig()
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    reserved = hub.reserved_descendants_of(["hub1"], bones)
    protected = frozenset({"root", "pelvis", "spine_01", "head"})
    pool = hub.free_donor_pool(
        catalog, reserved, hub_root_names=["hub1"], protected=protected)
    assert pool == ["free1", "free2"]


_COMMON_BONES_SAMPLE = os.path.join(
    _REPO_ROOT, "work", "comodo", "vanilla", "common_bones.json")


@pytest.mark.skipif(
    not os.path.exists(_DONOR_CATALOG_CACHE) or not os.path.exists(_COMMON_BONES_SAMPLE),
    reason="real donor catalog cache / common_bones.json sample not present on this machine")
def test_free_donor_pool_with_real_common_bones_excludes_core_rig():
    """実データ固定テスト: 実測4079骨カタログ+実際のcommon_bones.json
    (基幹人型リグ、実測65本)を使い、自由骨プールにpelvis/head/spine系が
    一切残らないことを検証する(本WPが追加した安全策の実データ裏取り)。"""
    with open(_DONOR_CATALOG_CACHE, encoding="utf-8") as f:
        catalog_json = json.load(f)
    with open(_COMMON_BONES_SAMPLE, encoding="utf-8") as f:
        common = set(json.load(f)["common"])
    assert "pelvis" in common and "head" in common  # サンプルの前提確認

    catalog = hub.SkeletonCatalog.from_bones_list(catalog_json["bones"])
    hub_names = hub.all_kp_node_root_names()
    reserved = hub.reserved_descendants_of(hub_names, catalog_json["bones"])
    slots = hub.discover_hub_slots()
    pool = hub.free_donor_pool(
        catalog, reserved, list(slots.female) + list(slots.male), protected=common)
    pool_set = set(pool)
    assert not (pool_set & common), (
        f"core rig bones leaked into free donor pool: {sorted(pool_set & common)[:10]}")


# =====================================================================
# plan_hub_wiring / node_overrides_from_wiring_plan
# =====================================================================

def _make_physbones_json(entries):
    """entries: [(anchor, [chain_bones], pull, spring), ...] -> physbones.json風dict"""
    return {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": anchor, "chains": [list(chain)],
         "params": {"limit_type": "None", "pull": pull, "spring": spring}}
        for anchor, chain, pull, spring in entries
    ]}


def _all_donor_names(wiring):
    """`wiring`全体が消費する全donor骨名(女性向け+男性向け)をフラットな
    リストで返す(dev#1551性別またぎdedup漏れ修正: `ChainDonorPlan.
    donor_chain`という単一フィールドがfemale/maleペアに分かれたため、旧来の
    `cp.donor_chain`直読みができなくなった——このヘルパーが後継)。
    univariant(donor_chain_female is donor_chain_male、値も完全に同一)な
    chainは1回だけ数える——女性向け/男性向けが意図的に同じ骨を共有する
    設計であり、二重カウントすると「重複消費なし」検査が誤検知する。"""
    names = []
    for gp in wiring.group_plans:
        for cp in gp.chain_plans:
            names.extend(cp.donor_chain_female)
            if cp.donor_chain_male != cp.donor_chain_female:
                names.extend(cp.donor_chain_male)
    return names


def _two_slot_hub_environment():
    """2スロットぶんのハブroot("hubA","hubB"、女性/男性側それぞれ)+豊富な
    自由骨プールを持つ合成環境。plan_hub_wiring()のテストで共有する。
    male側ハブroot("hubA_m"/"hubB_m")もfemale側と同じ低インデックスへ
    配置する(トポロジフィルタ——両性別ハブrootインデックスの大きい方より
    後ろのdonorだけを使う、plan_hub_wiring()docstring参照——が全freeを
    素通しするように、全frees(index 5+)がhubA/hubB/hubA_m/hubB_m
    (index 1-4)より確実に後ろになる配置)。"""
    defs = [("root", -1), ("hubA", 0), ("hubB", 0), ("hubA_m", 0), ("hubB_m", 0)]
    defs += [(f"free{i:02d}", 0) for i in range(1, 21)]
    bones = [{"name": n, "parent_idx": p, "quat": [0, 0, 0, 1],
              "pos": [0, 0, 0], "scale": [1, 1, 1]} for n, p in defs]
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    hub_slots = hub.HubSlots(female=("hubA", "hubB"), male=("hubA_m", "hubB_m"))
    reserved = frozenset()  # 合成環境では予約無し(free_donor_poolのテストは別途済み)
    return catalog, hub_slots, reserved


def test_plan_hub_wiring_assigns_slots_in_priority_order():
    physbones = _make_physbones_json([
        ("Head", ["ear_l_01", "ear_l_02"], 0.5, 0.5),   # small group -> lower priority
        ("Hips", ["tail_01", "tail_02", "tail_03"], 0.5, 0.5),  # tail -> highest priority
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    assert len(plan.accepted) == 2

    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    assert len(wiring.group_plans) == 2
    assert not wiring.unassignable
    # 優先順位1位(しっぽ)がスロット0(hubA)を得る
    assert wiring.group_plans[0].group.is_tail
    assert wiring.group_plans[0].hub_root_female == "hubA"
    assert wiring.group_plans[1].hub_root_female == "hubB"

    # donor骨は自由プールの先頭から重複なく貪欲に消費される(このフィクスチャは
    # 全スロットbivariantなので女性向け/男性向けも互いに素、_all_donor_names()
    # docstring参照)
    all_donors = _all_donor_names(wiring)
    assert len(all_donors) == len(set(all_donors))  # 重複なし(在庫排他)
    assert all(d.startswith("free") for d in all_donors)


def test_plan_hub_wiring_chain_donor_length_matches_source():
    physbones = _make_physbones_json([
        ("Hips", ["tail_01", "tail_02", "tail_03", "tail_04"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    cp = wiring.group_plans[0].chain_plans[0]
    # anchorオフバイワン修正(2026-08-16、SPEC §5): source_chainはanchor
    # ("Hips")自身を先頭に含む拡張版のため、元の鎖長4+1=5になる。
    # dev#1551: bivariantなこのスロットは女性向け/男性向けそれぞれ独立に
    # 同じ長さのdonor鎖を持つ(骨集合自体は互いに素)。
    assert len(cp.donor_chain_female) == len(cp.donor_chain_male) == len(cp.source_chain) == 5
    assert cp.source_chain[0] == "Hips"


def test_plan_hub_wiring_source_chain_includes_anchor_as_first_element():
    """負の対照が確認済みの回帰固定(dev#1508耳根元骨欠落バグ):
    修正前は`cp.source_chain`が`group.anchor`を一切含まず(chains配列の
    まま)、`source_to_donor_bone_map()`の対応表にanchorのキーが無かった
    (`DIAG.md`実データ確認、`test_sway_hub_wire.py`
    `test_source_to_donor_bone_map_includes_anchor_bone_dev1508`が
    高レベル入口側の同型固定)。SPEC §5裁定「PBのroot骨(anchor)自身も
    揺れる最初の可動骨であり、ハブ直下のドナーに写す(chains配列だけを
    写すオフバイワン禁止)」の直接検査。"""
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.002_end"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    cp = wiring.group_plans[0].chain_plans[0]
    assert "Head_L.001" in cp.source_chain
    assert cp.source_chain[0] == "Head_L.001"  # ハブ直下(先頭)に来ること


def test_plan_hub_wiring_dev1551_each_unit_gets_its_own_hub_and_anchor():
    """hub前提だった箇所の追従(dev#1551、2026-08-17オーナー裁定「hubを
    廃止し1chainあたり1KPノードへ移行する」): 旧仕様は耳L(Head_L.001)/
    R(Head_R.001)をanchor_group_of経由で1グループ(1ハブ)へ統合していたが、
    その統合機構自体が廃止された——`sway_allocator.allocate()`はもう
    `anchor_group_of`引数を受け付けず、耳L/Rは常に2グループ(=2ハブ、
    2スロット消費)になる。各グループのsource_chainには、そのグループ
    唯一のunit自身のanchorが先頭に付く(dev#1508耳根元骨欠落バグ修正の
    「anchor自身も揺れる最初の可動骨」規約は1グループ=1unitになっても
    変わらず維持される)。"""
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002"], 0.5, 0.5),
        ("Head_R.001", ["Head_R.002"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    assert len(plan.accepted) == 2  # dev#1551: もう統合されない
    for group in plan.accepted:
        assert len(group.units) == 1

    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert len(wiring.group_plans) == 2  # 2ハブを消費(1グループ=1ハブ)
    for gp in wiring.group_plans:
        assert len(gp.chain_plans) == 1

    source_firsts = {gp.chain_plans[0].source_chain[0] for gp in wiring.group_plans}
    assert source_firsts == {"Head_L.001", "Head_R.001"}
    # L側chainのsource_chainにR側anchorが紛れ込んでいない(逆も同様)
    for gp in wiring.group_plans:
        cp = gp.chain_plans[0]
        if cp.source_chain[0] == "Head_L.001":
            assert "Head_L.002" in cp.source_chain
            assert "Head_R.002" not in cp.source_chain
        else:
            assert "Head_R.002" in cp.source_chain
            assert "Head_L.002" not in cp.source_chain
    # donor骨は在庫排他(重複消費なし)のまま、2ハブ間でも共有されない
    all_donors = _all_donor_names(wiring)
    assert len(all_donors) == len(set(all_donors))


def test_plan_hub_wiring_marks_unassignable_when_pool_exhausted():
    physbones = _make_physbones_json([
        ("Hips", [f"tail_{i:02d}" for i in range(1, 25)], 0.5, 0.5),  # 24 bones needed
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()  # only 20 free bones
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert not wiring.group_plans
    assert len(wiring.unassignable) == 1
    assert "exhausted" in wiring.unassignable[0][1]


def test_plan_hub_wiring_rejects_more_accepted_groups_than_slots():
    physbones = _make_physbones_json([
        ("Hips", ["tail_01"], 0.5, 0.5),
        ("Head", ["ear_01"], 0.5, 0.5),
        ("Chest", ["scarf_01"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    assert len(plan.accepted) == 3
    catalog, hub_slots, reserved = _two_slot_hub_environment()  # only 2 slots
    with pytest.raises(hub.SwayHubError, match="hub slots"):
        hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)


def _hub_environment_with_low_index_donors():
    """低インデックスドナーが存在する環境(dev#1508 W2a-2d、実データバグ
    (PR #1533マージレビューで発見、master_writer_progress.md参照)の再現
    用フィクスチャ)。root(idx0)の直後に低インデックスの自由骨2本
    (low_free_01/02、idx1-2)を配置し、ハブroot(hubA/hubA_m、idx3-4)は
    それより後ろ、さらに後ろに高インデックスの自由骨6本(high_free_01..06、
    idx5-10)を配置する。

    実際のバグはこの逆(donor候補
    `NPC_Female_SorajimaPeople01_tassel_01_l`のindex=27が、ハブroot
    `M_OldCloth001_04`のindex=355より小さかった)と同型の配置——修正前の
    `plan_hub_wiring()`は「自由プールを元のインデックス昇順で貪欲消費すれば
    トポロジ制約を満たせる」という誤った前提で実装されていたため、
    low_free_01/02(ハブrootより低インデックス)を先に選んでしまい、
    `sway_shared_skeleton.reparent_bone_content_only()`のトポロジ制約
    (`new_parent_idx<target_idx`)に違反していた。

    `_two_slot_hub_environment()`(既存フィクスチャ)は全freeがhub root群
    より確実に後ろ(index 5+ vs hub 1-4)に配置されているため、この
    トポロジフィルタが常に自明に全通過してしまい、修正が実際に何かを
    除外することを検証できない(PR #1533レビュー時に指摘された欠落、
    本関数はその穴を埋める)。

    dev#1551(性別またぎdedup漏れ修正): hubA/hubA_mはbivariant(名前が
    異なる)なので、女性向け/男性向けで互いに素なdonor骨集合が要る
    (`ChainDonorPlan.donor_chain_for()`docstring参照)——high_freeを
    3本から6本(女性向け3本+男性向け3本)へ倍増した。"""
    defs = [("root", -1), ("low_free_01", 0), ("low_free_02", 0),
            ("hubA", 0), ("hubA_m", 0)]
    defs += [(f"high_free_{i:02d}", 0) for i in range(1, 7)]
    bones = [{"name": n, "parent_idx": p, "quat": [0, 0, 0, 1],
              "pos": [0, 0, 0], "scale": [1, 1, 1]} for n, p in defs]
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    hub_slots = hub.HubSlots(female=("hubA",), male=("hubA_m",))
    reserved = frozenset()
    return catalog, hub_slots, reserved


def test_plan_hub_wiring_excludes_low_index_donors_below_hub_root():
    """負の対照(dev#1508 W2a-2d、実データバグの再現): 自由プールに
    ハブrootより低いインデックスのdonor候補(low_free_01/02)が含まれて
    いても、それらは採用されず、ハブrootより後ろのdonor(high_free_01..06)
    だけが使われる。旧実装(元インデックス昇順で無条件に貪欲消費)なら
    low_free_01/02が選ばれ、実際にPhase 3.7で
    `SharedSkeletonError: topology violation`を起こしていた
    (PR #1533実データ実測、master_writer_progress.md参照)。

    dev#1551追記: bivariantなhubA/hubA_mは女性向け/男性向けで互いに素な
    donor骨集合を持つ(女性=high_free_01-03、男性=high_free_04-06、
    貪欲消費の順序どおり)——これも合わせて検査する。"""
    physbones = _make_physbones_json([
        ("Hips", ["tail_01", "tail_02"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _hub_environment_with_low_index_donors()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    assert len(wiring.group_plans) == 1
    assert not wiring.unassignable
    cp = wiring.group_plans[0].chain_plans[0]
    donors_f = cp.donor_chain_female
    donors_m = cp.donor_chain_male
    # anchorオフバイワン修正により先頭はanchor("Hips")ぶんのdonor
    # (high_free_01)、続いてtail_01/tail_02(high_free_02/03)。
    assert donors_f == ("high_free_01", "high_free_02", "high_free_03")
    # dev#1551: 男性向けは女性向けと互いに素な次のブロックを消費する。
    assert donors_m == ("high_free_04", "high_free_05", "high_free_06")
    assert set(donors_f).isdisjoint(donors_m)
    for donors in (donors_f, donors_m):
        assert "low_free_01" not in donors
        assert "low_free_02" not in donors
    # トポロジ不変条件そのものも直接確認する(catalogインデックスで検算)
    hub_idx = catalog.index_of("hubA")
    for d in (*donors_f, *donors_m):
        assert catalog.index_of(d) > hub_idx


def test_plan_hub_wiring_marks_unassignable_when_only_low_index_donors_available():
    """負の対照: ハブrootより後ろの(=トポロジ的に使える)donorが不足して
    いる場合、低インデックスdonor(low_free_01/02)で頭数だけ揃えて採用
    してしまう退行が無いことを確認する——unassignableへ正しく回される。
    dev#1551: bivariantなので必要数は女性/男性ぶん2倍(4本x2=8本)、
    利用可能な高indexは6本のみなので依然として不足する。"""
    physbones = _make_physbones_json([
        # anchor("Hips")+tail_01/02/03 = 4本必要(x2=8本、bivariant)、
        # 高indexは6本(high_free_01-06)のみで不足する。
        ("Hips", ["tail_01", "tail_02", "tail_03"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _hub_environment_with_low_index_donors()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    assert not wiring.group_plans
    assert len(wiring.unassignable) == 1
    assert "exhausted" in wiring.unassignable[0][1]


def test_node_overrides_from_wiring_plan_writes_both_genders():
    physbones = _make_physbones_json([
        ("Hips", ["tail_01", "tail_02"], 0.9, 0.9),  # kata-ish (high pull/spring)
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    overrides = hub.node_overrides_from_wiring_plan(wiring)

    assert set(overrides) == {"hubA", "hubA_m"}
    assert overrides["hubA"] == overrides["hubA_m"]
    assert overrides["hubA"]["style"] == plan.accepted[0].style
    assert overrides["hubA"]["limit_angle"] == 0.0  # limit_type=None -> no limit


def test_node_overrides_from_wiring_plan_one_key_pair_per_chain_dev1551():
    """dev#1551受入ゲート2-③「1chain=1KPのnode_overrides生成」の直接検査:
    3つの独立したChainUnit(anchorも全部別)を投入すると、
    node_overridesは3組(female/male)=6キー、それぞれ別々のハブroot骨
    (1chain=1KPノード)を指す——1つの鎖が他の鎖のノードと共有されない。"""
    physbones = _make_physbones_json([
        ("Hips", ["tail_01"], 0.5, 0.5),
        ("Head", ["ear_01"], 0.5, 0.5),
        ("Chest", ["scarf_01"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    assert len(plan.accepted) == 3
    catalog, hub_slots, reserved = _three_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert len(wiring.group_plans) == 3  # 1chain=1KP: 3本とも独立したハブ

    overrides = hub.node_overrides_from_wiring_plan(wiring)
    assert len(overrides) == 6  # 3グループ x (female, male) = 6キー
    hub_roots_used = {gp.hub_root_female for gp in wiring.group_plans}
    assert len(hub_roots_used) == 3  # 3本とも別々のハブroot骨(共有なし)
    for gp in wiring.group_plans:
        assert overrides[gp.hub_root_female] == overrides[gp.hub_root_male]
        assert overrides[gp.hub_root_female]["style"] == gp.group.style


def test_node_overrides_limit_angle_uses_each_units_own_value_dev1551():
    """hub前提だった箇所の追従(dev#1551、2026-08-17オーナー裁定): 旧
    テストは同じanchorを共有する2ユニットが1グループへ統合され、統合
    グループ内の最小値(最も厳しい制限)が採用されることを検査していたが、
    統合機構自体が廃止されたため、2ユニットは別々のグループ(=別々の
    ハブ)になり、それぞれ自分自身のlimit_angleをそのまま持つ(dev#1551
    受入ゲート「1chain=1KPのnode_overrides生成」の直接検査)。"""
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Hips", "chains": [["tail_01"]],
         "params": {"limit_type": "Angle", "limit_rotation": [0, 0, 0],
                     "max_angle_x": 40.0, "pull": 0.5, "spring": 0.5}},
        {"anchor": "Hips", "chains": [["tail_02"]],
         "params": {"limit_type": "Angle", "limit_rotation": [0, 0, 0],
                     "max_angle_x": 20.0, "pull": 0.5, "spring": 0.5}},
    ]}
    plan = sway_allocator.allocate(physbones_json=physbones)
    # dev#1551: 同じanchorを共有していても、もはや統合されず2グループ。
    assert len(plan.accepted) == 2
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert len(wiring.group_plans) == 2  # 1chain=1KP: 2つの別ハブへ配線
    overrides = hub.node_overrides_from_wiring_plan(wiring)

    per_group_angles = sorted(gp.group.units[0].limit_angle for gp in wiring.group_plans)
    assert per_group_angles == [20.0, 40.0]  # 統合されず双方の値が独立に残る
    for gp in wiring.group_plans:
        expected = gp.group.units[0].limit_angle
        assert overrides[gp.hub_root_female]["limit_angle"] == expected
        assert overrides[gp.hub_root_male]["limit_angle"] == expected


# =====================================================================
# filter_wiring_by_resolvable_anchor (dev#1508 W2a-2c)
# =====================================================================

def test_filter_wiring_by_resolvable_anchor_keeps_resolvable_groups():
    physbones = _make_physbones_json([
        ("Hips", ["tail_01", "tail_02"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert len(wiring.group_plans) == 1

    filtered = hub.filter_wiring_by_resolvable_anchor(wiring, {"Hips": "pelvis"})
    assert filtered.group_plans == wiring.group_plans
    assert filtered.unassignable == wiring.unassignable


def test_filter_wiring_by_resolvable_anchor_drops_unresolvable_groups():
    """負の対照: anchor_pal_name_ofに載っていないanchorを持つグループは
    unassignableへ理由付きで移り、group_plansから消える(die()しない)。"""
    physbones = _make_physbones_json([
        ("Hips", ["tail_01", "tail_02"], 0.5, 0.5),
        ("Chest$guid123", ["scarf_01"], 0.9, 0.9),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert len(wiring.group_plans) == 2

    # "Hips" resolves, "Chest$guid123" does not (not in the map)
    filtered = hub.filter_wiring_by_resolvable_anchor(wiring, {"Hips": "pelvis"})
    assert len(filtered.group_plans) == 1
    assert filtered.group_plans[0].group.anchor == "Hips"
    assert len(filtered.unassignable) == len(wiring.unassignable) + 1
    reasons = [r for _g, r in filtered.unassignable]
    assert any("Chest$guid123" in r for r in reasons)


def test_filter_wiring_by_resolvable_anchor_empty_input_is_noop():
    empty = hub.HubWiringPlan(group_plans=(), unassignable=())
    filtered = hub.filter_wiring_by_resolvable_anchor(empty, {})
    assert filtered.group_plans == ()
    assert filtered.unassignable == ()


# =====================================================================
# filter_wiring_excluding_units (dev#1551 Lane V: VRM経路step02
# KeyError修理、issue #1551)
#
# 実バグ: test\vrm\Seed-san.vrm(VRM 1.0)の変換で、`run_sway_degrade_loop()`
# のリトライが`sway_hub.plan_hub_wiring()`を(除外集合を変えて)**再実行**
# していたため、以前は使われなかった女性用donor骨`F_Bronze001_bag_01`が
# 新規に割り当たり、attempt0で構築済みのpal_arm(Blender armature)に
# 存在しない骨を`place_hub_donor_chains()`が`eb[name]`で参照して
# `KeyError`が発生していた(`pipeline\\blender\\step02_retarget.py`
# `run_sway_degrade_loop()`のdocstring参照)。
# =====================================================================

def _three_slot_topology_hub_environment():
    """3スロットぶんのハブroot(hubA/hubB/hubC、女性/男性側)+40本の自由骨
    プール(free01..free40、ハブroot群より確実に後ろのindex)を持つ合成
    環境(`_two_slot_hub_environment()`の3スロット版)。

    dev#1551(性別またぎdedup漏れ修正)で自由骨を20本から40本へ倍増した
    ——全スロットbivariantなので、女性向け/男性向けそれぞれ独立にdonorを
    消費する(必要数が単純に2倍になる、`_degrade_repro_environment()`
    docstring参照)。相対的な余剰/枯渇の関係(Small=枯渇、Big+T=充足)は
    倍増後も同じ比率で保たれるよう全体を2倍にしてある。"""
    defs = [("root", -1), ("hubA", 0), ("hubB", 0), ("hubC", 0),
            ("hubA_m", 0), ("hubB_m", 0), ("hubC_m", 0)]
    defs += [(f"free{i:02d}", 0) for i in range(1, 41)]
    bones = [{"name": n, "parent_idx": p, "quat": [0, 0, 0, 1],
              "pos": [0, 0, 0], "scale": [1, 1, 1]} for n, p in defs]
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    hub_slots = hub.HubSlots(female=("hubA", "hubB", "hubC"),
                              male=("hubA_m", "hubB_m", "hubC_m"))
    reserved = frozenset()
    return catalog, hub_slots, reserved


def _degrade_repro_environment():
    """dev#1551実バグの最小再現環境: 3グループ(T=しっぽ・優先1位、
    Big=骨数9・優先2位、Small=骨数7・優先3位)+自由プール40本。

    全スロットbivariant(hubA/hubB/hubCがそれぞれhubA_m/hubB_m/hubC_mと
    異なる名前)なので、必要数は女性向け/男性向けの2倍になる(dev#1551
    性別またぎdedup漏れ修正、`ChainDonorPlan.donor_chain_for()`docstring
    参照)。

    attempt0(3グループとも`plan.accepted`)では: T(4本必要、anchor込み、
    x2=8本)がfree01-08、Big(10本必要、x2=20本)がfree09-28を消費し、
    Small(8本必要、x2=16本)は残り12本("free29-40"のうち12本)しかなく
    `wiring.unassignable`へ回る(pool exhausted)——つまりattempt0の
    pal_arm(=`refskel_dict_for_wiring()`が返す骨集合)には**Smallの骨は
    一切含まれない**(T+Bigのfree01-28のみ)。

    Tを縮退除外した状態で`plan_hub_wiring()`を**再実行**すると、Bigが
    先頭からfree01-20を消費し、Small(16本)はfree21-36を新規に確保できて
    しまう——free29-36(8本)はattempt0のpal_armに一度も存在しない、
    実バグと同型の「新規donor骨」。"""
    physbones = _make_physbones_json([
        ("Hips", ["tail_01", "tail_02", "tail_03"], 0.5, 0.5),  # T: is_tail, bone_count=3
        ("Second", [f"big_{i:02d}" for i in range(1, 10)], 0.5, 0.5),  # Big: bone_count=9
        ("Third", [f"small_{i:02d}" for i in range(1, 8)], 0.5, 0.5),  # Small: bone_count=7
    ])
    catalog, hub_slots, reserved = _three_slot_topology_hub_environment()
    return physbones, catalog, hub_slots, reserved


def test_naive_replan_after_excluding_group_produces_donor_bones_outside_original_wiring_dev1551():
    """根本原因の再現(dev#1551): `plan_hub_wiring()`を除外集合を変えて
    再実行すると、生き残ったグループへ**attempt0のpal_armに存在しない**
    donor骨が新規に割り当たりうる——`run_sway_degrade_loop()`の旧実装
    (`wire_sway_hub_auto()`をリトライのたびに再実行)がこの構造的な穴を
    踏んでいたことの証明。"""
    physbones, catalog, hub_slots, reserved = _degrade_repro_environment()

    plan0 = sway_allocator.allocate(physbones_json=physbones)
    wiring0 = hub.plan_hub_wiring(plan0, catalog, hub_slots, reserved)
    assert [gp.group.anchor for gp in wiring0.group_plans] == ["Hips", "Second"]
    assert len(wiring0.unassignable) == 1
    assert wiring0.unassignable[0][0].anchor == "Third"

    # attempt0時点でpal_armへ実際に構築される骨集合(refskel_dict_for_wiring()
    # と同じ「wiring.group_plansが参照する全donor名」の集合)。
    attempt0_donor_names = set(_all_donor_names(wiring0))
    assert "free29" not in attempt0_donor_names  # Smallは未配線=free29以降は未使用

    # Hips(T)を縮退除外して`plan_hub_wiring()`を素朴に再実行(旧実装の再現)。
    hips_key = plan0.accepted[0].units[0].key
    lab_overrides = {hips_key: sway_allocator.LabAssignment(style="", enabled=False)}
    plan_retry = sway_allocator.allocate(physbones_json=physbones, lab_assignments=lab_overrides)
    wiring_retry_naive = hub.plan_hub_wiring(plan_retry, catalog, hub_slots, reserved)

    # SmallがattempT0では配線されなかったのに、素朴な再実行では配線されて
    # しまい、しかもattempt0のpal_armには存在しなかった骨を使う。
    retry_donor_names = set(_all_donor_names(wiring_retry_naive))
    new_bones = retry_donor_names - attempt0_donor_names
    assert new_bones, (
        "regression fixture drifted: naive re-plan no longer introduces bones "
        "outside attempt0's wiring -- update the bone-count constants above")
    assert "free29" in new_bones or "free30" in new_bones or "free31" in new_bones


def test_filter_wiring_excluding_units_is_literal_subset_dev1551():
    """本修理の核心: `filter_wiring_excluding_units()`は`plan_hub_wiring()`
    を一切再実行しないため、生き残るグループのdonor骨は常にattempt0と
    文字どおり同一(=attempt0のpal_armに必ず存在する)。"""
    physbones, catalog, hub_slots, reserved = _degrade_repro_environment()
    plan0 = sway_allocator.allocate(physbones_json=physbones)
    wiring0 = hub.plan_hub_wiring(plan0, catalog, hub_slots, reserved)
    hips_key = plan0.accepted[0].units[0].key

    filtered = hub.filter_wiring_excluding_units(wiring0, frozenset({hips_key}))

    # Hips(T)のグループだけが消え、Big("Second")は無傷で残る。
    assert [gp.group.anchor for gp in filtered.group_plans] == ["Second"]
    big_gp_before = next(gp for gp in wiring0.group_plans if gp.group.anchor == "Second")
    big_gp_after = filtered.group_plans[0]
    assert big_gp_after.chain_plans == big_gp_before.chain_plans  # 一字一句不変
    assert big_gp_after.hub_root_female == big_gp_before.hub_root_female

    # 除外したHipsはunassignableへ理由付きで移る。既存(Third=pool exhausted)
    # は保持されたまま追加される。
    assert len(filtered.unassignable) == len(wiring0.unassignable) + 1
    anchors_unassignable = {g.anchor for g, _r in filtered.unassignable}
    assert anchors_unassignable == {"Hips", "Third"}

    # 決定的な検査: フィルタ後のdonor骨集合は、attempt0のdonor骨集合の
    # 部分集合を一歩も出ない(新規donor骨=KeyErrorの温床が絶対に現れない)。
    attempt0_donor_names = set(_all_donor_names(wiring0))
    filtered_donor_names = set(_all_donor_names(filtered))
    assert filtered_donor_names <= attempt0_donor_names
    # Smallが(素朴な再実行なら)新規に確保しうる範囲(free29+)がフィルタ後にも
    # 一切現れない(filter_wiring_excluding_units()は再実行しないため構造的に
    # 混入し得ない、docstring参照)。
    assert "free29" not in filtered_donor_names
    assert "free30" not in filtered_donor_names


def test_filter_wiring_excluding_units_empty_exclusion_is_noop_dev1551():
    """負の対照: 除外集合が空なら、group_plans/unassignableとも一切
    変化しない(誤って何かを削ってしまわないことの確認)。"""
    physbones, catalog, hub_slots, reserved = _degrade_repro_environment()
    plan0 = sway_allocator.allocate(physbones_json=physbones)
    wiring0 = hub.plan_hub_wiring(plan0, catalog, hub_slots, reserved)

    filtered = hub.filter_wiring_excluding_units(wiring0, frozenset())
    assert filtered.group_plans == wiring0.group_plans
    assert filtered.unassignable == wiring0.unassignable


def test_filter_wiring_excluding_units_all_excluded_gives_empty_group_plans_dev1551():
    """`run_sway_degrade_loop()`のfail-closed全OFF縮退(dev#1508 laneI
    「3. fail-closedの維持」)が使う形: 生き残っている全unitを除外集合へ
    入れると、group_plansが完全に空になる(=以後`place_hub_donor_chains()`
    が即no-op returnする、`sway_hub.py`モジュールの契約どおり)。"""
    physbones, catalog, hub_slots, reserved = _degrade_repro_environment()
    plan0 = sway_allocator.allocate(physbones_json=physbones)
    wiring0 = hub.plan_hub_wiring(plan0, catalog, hub_slots, reserved)
    all_keys = frozenset(
        u.key for gp in wiring0.group_plans for u in gp.group.units)

    filtered = hub.filter_wiring_excluding_units(wiring0, all_keys)
    assert filtered.group_plans == ()


def test_filter_wiring_excluding_units_dev1551_each_unit_gets_its_own_hub_and_anchor():
    """dev#1551の1unit=1group=1KP前提でも`filter_wiring_excluding_units()`
    がグループ単位で正しく機能することの確認(小さい合成環境、`_two_slot_
    hub_environment()`)。1つのunitを除外すると、その1グループだけが
    消え、他方のグループのanchor/donor_chainは無傷。"""
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002"], 0.5, 0.5),
        ("Head_R.001", ["Head_R.002"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert len(wiring.group_plans) == 2

    left_gp = next(gp for gp in wiring.group_plans
                   if gp.group.anchor == "Head_L.001")
    left_key = left_gp.group.units[0].key

    filtered = hub.filter_wiring_excluding_units(wiring, frozenset({left_key}))
    assert len(filtered.group_plans) == 1
    remaining = filtered.group_plans[0]
    assert remaining.group.anchor == "Head_R.001"
    original_right_gp = next(gp for gp in wiring.group_plans
                              if gp.group.anchor == "Head_R.001")
    assert remaining.chain_plans == original_right_gp.chain_plans


# =====================================================================
# build_diagnostics_lines (dev#1508 W2a-2c)
# =====================================================================

def test_build_diagnostics_lines_accepted_unit_reports_hub_root():
    physbones = _make_physbones_json([
        ("Hips", ["tail_01", "tail_02"], 0.9, 0.9),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    lines = hub.build_diagnostics_lines(plan, wiring, gender="Female")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["sway_diag"] is True
    assert record["excluded_reason"] is None
    assert record["wiring"][0]["donor_root_bone"] == "hubA"
    assert record["wiring"][0]["chain"] == ["tail_01", "tail_02"]


def test_build_diagnostics_lines_male_gender_reports_male_hub_root():
    physbones = _make_physbones_json([("Hips", ["tail_01", "tail_02"], 0.9, 0.9)])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    lines = hub.build_diagnostics_lines(plan, wiring, gender="Male")
    record = json.loads(lines[0])
    assert record["wiring"][0]["donor_root_bone"] == "hubA_m"


def test_build_diagnostics_lines_biased_unit_has_no_donor_and_reason():
    """負の対照: 偏向除外されたユニットはハブへ配線されず、
    donor_root_bone=None・excluded_reasonが理由付きで残る。"""
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": [
        {"anchor": "Chest", "chains": [["scarf_01"]],
         "params": {"limit_type": "Hinge", "pull": 0.5, "spring": 0.5}},
    ]}
    plan = sway_allocator.allocate(physbones_json=physbones)
    assert not plan.accepted  # Hinge -> biased -> excluded
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert not wiring.group_plans

    lines = hub.build_diagnostics_lines(plan, wiring, gender="Female")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["judged"]["is_biased"] is True
    assert record["excluded_reason"] is not None
    assert record["wiring"][0]["donor_root_bone"] is None


def test_build_diagnostics_lines_dev1551_each_unit_reports_its_own_hub():
    """hub前提だった箇所の追従(dev#1551): 旧テストは統合グループ(耳L/R、
    親="head")の両方のunitが同じハブroot骨を報告することを検査していたが、
    統合機構自体が廃止されたため、耳L/Rは別々のグループ=別々のハブroot骨
    (hubA/hubB)をそれぞれ報告するのが正しい(1グループ=1unit=1ハブ)。"""
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002"], 0.5, 0.5),
        ("Head_R.001", ["Head_R.002"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    lines = hub.build_diagnostics_lines(plan, wiring, gender="Female")
    assert len(lines) == 2
    records = {json.loads(line)["anchor"]: json.loads(line) for line in lines}
    assert set(records) == {"Head_L.001", "Head_R.001"}
    hub_names_used = set()
    for anchor, record in records.items():
        assert record["excluded_reason"] is None, anchor
        donor_root = record["wiring"][0]["donor_root_bone"]
        assert donor_root is not None, f"{anchor}: 配線されていない"
        hub_names_used.add(donor_root)
    assert len(hub_names_used) == 2  # dev#1551: 別々のハブに配線される


def test_build_diagnostics_lines_pool_exhausted_reports_lost_reason():
    physbones = _make_physbones_json([
        ("Hips", [f"tail_{i:02d}" for i in range(1, 25)], 0.5, 0.5),  # 24 > 20 free bones
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert not wiring.group_plans and wiring.unassignable

    lines = hub.build_diagnostics_lines(plan, wiring, gender="Female")
    record = json.loads(lines[0])
    assert record["wiring"][0]["donor_root_bone"] is None
    assert "exhausted" in record["wiring"][0]["wiring_lost_reason"]


# =====================================================================
# refskel_dict_for_wiring (dev#1508 W2a-2c)
# =====================================================================

def test_refskel_dict_for_wiring_topology_and_placeholder_values():
    physbones = _make_physbones_json([
        ("Hips", ["tail_01", "tail_02", "tail_03"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    refskel = hub.refskel_dict_for_wiring(wiring, gender="Female")
    cp = wiring.group_plans[0].chain_plans[0]
    donor_chain = cp.donor_chain_for("Female")
    assert set(refskel) == {"hubA", *donor_chain}
    assert refskel["hubA"]["parent"] == hub.PLACEHOLDER_STRUCTURAL_PARENT
    assert refskel[donor_chain[0]]["parent"] == "hubA"
    for i in range(1, len(donor_chain)):
        assert refskel[donor_chain[i]]["parent"] == donor_chain[i - 1]
    # 全エントリが非退化の構造placeholder(quat正規化・非ゼロpos)を持つ
    for entry in refskel.values():
        assert entry["quat"] == [0.0, 0.0, 0.0, 1.0]
        assert entry["pos"] != [0.0, 0.0, 0.0]
        assert entry["scale"] == [1.0, 1.0, 1.0]


def test_refskel_dict_for_wiring_empty_when_no_groups():
    physbones = {"format": sway_allocator.PHYSBONES_FORMAT, "physbones": []}
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert hub.refskel_dict_for_wiring(wiring, gender="Female") == {}


def test_refskel_dict_for_wiring_custom_placeholder_parent():
    physbones = _make_physbones_json([("Hips", ["tail_01"], 0.5, 0.5)])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    refskel = hub.refskel_dict_for_wiring(wiring, gender="Female", placeholder_parent="custom_root")
    assert refskel["hubA"]["parent"] == "custom_root"


# =====================================================================
# refskel_dict_for_wiring: anchor_pal_of (dev#1551 integ14メッシュ側
# RefSkeleton reparent欠落の修正)
# =====================================================================

def test_refskel_dict_for_wiring_anchor_pal_of_overrides_hub_parent():
    """anchor_pal_ofが引ければ、ハブroot骨の親はplaceholder("pelvis")ではなく
    実アンカー(anchor_pal_ofの値、ここではHead)になる(integ13実機測定で
    判明したメッシュ側RefSkeleton reparent欠落の修正本体)。"""
    physbones = _make_physbones_json([("Hips", ["tail_01", "tail_02"], 0.5, 0.5)])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    gp = wiring.group_plans[0]
    assert gp.anchor_target == "Hips"

    refskel = hub.refskel_dict_for_wiring(
        wiring, gender="Female", anchor_pal_of={"Hips": "Head"})
    assert refskel["hubA"]["parent"] == "Head"
    # donor鎖のトポロジ自体はanchor_pal_ofの有無で変化しない
    donor_chain = gp.chain_plans[0].donor_chain_for("Female")
    assert refskel[donor_chain[0]]["parent"] == "hubA"


def test_refskel_dict_for_wiring_anchor_pal_of_missing_key_falls_back_to_placeholder():
    """anchor_pal_ofが渡されても、そのグループのanchor_targetがキーに無ければ
    placeholder_parentへフォールバックする(fail-safe、モジュールdocstring
    「解決できないグループはplaceholder_parentへフォールバック」節)。"""
    physbones = _make_physbones_json([("Hips", ["tail_01"], 0.5, 0.5)])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    refskel = hub.refskel_dict_for_wiring(
        wiring, gender="Female", anchor_pal_of={"SomeOtherAnchor": "Head"})
    assert refskel["hubA"]["parent"] == hub.PLACEHOLDER_STRUCTURAL_PARENT


def test_refskel_dict_for_wiring_anchor_pal_of_none_value_falls_back_to_placeholder():
    """anchor_pal_ofの値自体がNone(辞書にキーはあるが値が空)の場合も
    placeholder_parentへフォールバックする(`.get(...) or placeholder_parent`の
    `or`分岐、辞書キーが引けてもNoneだと構造登録に使えないため)。"""
    physbones = _make_physbones_json([("Hips", ["tail_01"], 0.5, 0.5)])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    refskel = hub.refskel_dict_for_wiring(
        wiring, gender="Female", anchor_pal_of={"Hips": None})
    assert refskel["hubA"]["parent"] == hub.PLACEHOLDER_STRUCTURAL_PARENT


def test_refskel_dict_for_wiring_anchor_pal_of_omitted_keeps_backward_compat():
    """anchor_pal_of省略(既定None)なら、従来どおりplaceholder_parentが
    ハブroot親になる(既存呼び出し元・既存テストへの無影響を保証する
    後方互換の負の対照: 呼び出し元が引数を渡し忘れても壊れない)。"""
    physbones = _make_physbones_json([("Hips", ["tail_01"], 0.5, 0.5)])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)

    refskel = hub.refskel_dict_for_wiring(wiring, gender="Female")
    assert refskel["hubA"]["parent"] == hub.PLACEHOLDER_STRUCTURAL_PARENT


def test_refskel_dict_for_wiring_anchor_pal_of_resolved_placeholder_absent_from_output():
    """負の対照: anchor_pal_ofが解決できた場合、出力にplaceholder値
    ("pelvis"、PLACEHOLDER_STRUCTURAL_PARENT)が一切現れないことを確認する
    (integ13実機不具合の再発検出——修正が半端で旧placeholderへ静かに
    フォールバックし続けるケースを検出する)。"""
    physbones = _make_physbones_json([
        ("Hips", ["tail_01", "tail_02"], 0.5, 0.5),
        ("Head", ["ear_01"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert len(wiring.group_plans) == 2

    refskel = hub.refskel_dict_for_wiring(
        wiring, gender="Female",
        anchor_pal_of={"Hips": "pelvis_pal", "Head": "head_pal"})
    hub_names = {gp.hub_root_female for gp in wiring.group_plans}
    for name in hub_names:
        assert refskel[name]["parent"] != hub.PLACEHOLDER_STRUCTURAL_PARENT
    assert {refskel[n]["parent"] for n in hub_names} == {"pelvis_pal", "head_pal"}


# =====================================================================
# load_skeleton_catalog (dev#1508 W2a-2c)
# =====================================================================

def test_load_skeleton_catalog_round_trips_bones_list(tmp_path):
    bones = [{"name": "root", "parent_idx": -1, "quat": [0, 0, 0, 1],
              "pos": [0, 0, 0], "scale": [1, 1, 1]},
             {"name": "child", "parent_idx": 0, "quat": [0, 0, 0, 1],
              "pos": [0, 0, 1], "scale": [1, 1, 1]}]
    path = tmp_path / "sk_palhuman_full.json"
    path.write_text(json.dumps({"bone_count": 2, "bones": bones}), encoding="utf-8")

    catalog = hub.load_skeleton_catalog(str(path))
    assert catalog.index_of("root") == 0
    assert catalog.index_of("child") == 1
    assert len(catalog.bones) == 2


# =====================================================================
# 振幅ランクによるroot割当(dev#1508 laneA4、amplitude-root)
# work\night_20260817\briefs\laneA4_amplitude_assign.md
# =====================================================================

def _three_slot_hub_environment():
    """3スロット(hubEar/hubMid/hubTail、女性/男性側それぞれ)+豊富な自由
    骨プールを持つ合成環境。振幅ランクによるスロット再割当のテスト専用
    (_two_slot_hub_environment()の3スロット版)。"""
    defs = [("root", -1),
            ("hubEar", 0), ("hubMid", 0), ("hubTail", 0),
            ("hubEar_m", 0), ("hubMid_m", 0), ("hubTail_m", 0)]
    defs += [(f"free{i:02d}", 0) for i in range(1, 31)]
    bones = [{"name": n, "parent_idx": p, "quat": [0, 0, 0, 1],
              "pos": [0, 0, 0], "scale": [1, 1, 1]} for n, p in defs]
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    hub_slots = hub.HubSlots(female=("hubEar", "hubMid", "hubTail"),
                              male=("hubEar_m", "hubMid_m", "hubTail_m"))
    reserved = frozenset()
    return catalog, hub_slots, reserved


def test_group_visibility_tier_ear_head_tail_other():
    physbones = _make_physbones_json([
        ("Head_L.001", ["ear_l_01"], 0.5, 0.5),          # ear token -> tier 0
        ("head", ["head_ornament_01"], 0.5, 0.5),        # "head" token -> tier 0
        ("Chest", ["scarf_01"], 0.5, 0.5),                # no token -> tier 1 (default)
        ("Hips", ["tail_01", "tail_02"], 0.5, 0.5),       # tail -> tier 2
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    by_anchor = {g.anchor: g for g in plan.accepted}
    assert hub._group_visibility_tier(by_anchor["Head_L.001"]) == 0
    assert hub._group_visibility_tier(by_anchor["head"]) == 0
    assert hub._group_visibility_tier(by_anchor["Chest"]) == 1
    assert hub._group_visibility_tier(by_anchor["Hips"]) == 2


def test_assign_slots_by_visibility_amplitude_ear_gets_quietest_slot():
    """brief item2の核心: 耳(tier0)がしっぽ(tier2)より優先順位で下位
    (骨数が少ない)でも、振幅昇順スロットの先頭(=最も静かなroot)を得る。

    dev#1551(耳donorの横取り防止、issue #1551)で"hubMid"(tier1)への
    フォールバックは廃止——各グループはまず**自分と同じtierのスロット**を
    振幅昇順で得る(耳=tier0の"hubEar"、しっぽ=tier2の"hubTail")。tier1の
    "hubMid"はこのシナリオに対応するtier1グループが存在しないため未消費の
    まま余る(下のバケツ内訳アサーションで確認)。"""
    physbones = _make_physbones_json([
        ("Hips", [f"tail_{i:02d}" for i in range(1, 6)], 0.5, 0.5),  # tail, 5 bones -> highest raw priority
        ("Head_L.001", ["ear_01"], 0.5, 0.5),                        # ear, 1 bone -> lowest raw priority
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    assert plan.accepted[0].is_tail  # 生の優先順位ではしっぽが1位のまま(変更しない)
    assert plan.accepted[1].anchor == "Head_L.001"

    hub_names = ("hubEar", "hubMid", "hubTail")
    amplitude_rank = {"hubEar": 10.0, "hubMid": 50.0, "hubTail": 90.0}
    slot_indices = hub._assign_slots_by_visibility_amplitude(
        plan.accepted, hub_names, amplitude_rank)
    # 耳(accepted[1])は自tier(0)内で唯一のスロット"hubEar"を得て、
    # しっぽ(accepted[0])は自tier(2)内で唯一のスロット"hubTail"を得る
    # ("hubMid"=tier1に対応するグループが無いため未消費のまま余る)。
    assert hub_names[slot_indices[1]] == "hubEar"
    assert hub_names[slot_indices[0]] == "hubTail"
    assert "hubMid" not in {hub_names[i] for i in slot_indices}


def test_assign_slots_by_visibility_amplitude_is_deterministic():
    physbones = _make_physbones_json([
        ("Hips", ["tail_01"], 0.5, 0.5),
        ("Head_L.001", ["ear_01"], 0.5, 0.5),
        ("Chest", ["scarf_01"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    hub_names = ("hubEar", "hubMid", "hubTail")
    amplitude_rank = {"hubEar": 10.0, "hubMid": 50.0, "hubTail": 90.0}
    r1 = hub._assign_slots_by_visibility_amplitude(plan.accepted, hub_names, amplitude_rank)
    r2 = hub._assign_slots_by_visibility_amplitude(plan.accepted, hub_names, amplitude_rank)
    assert r1 == r2


def test_assign_slots_by_visibility_amplitude_reversed_rank_still_keeps_ear_in_its_own_tier_dev1551():
    """dev#1551(耳donorの横取り防止、issue #1551)による訂正:
    本テストは元々「スロットの文字列名は無視され、`amplitude_rank`の数値
    だけに従う」ことの負の対照だったが、その前提そのものが
    work\\run_1551\\integL\\RESULT.md実測の「耳系ハブスロットが無関係な
    グループに横取りされ、耳飾り等のPAL側装備メッシュごと無関係な部位へ
    reparentされる」不具合の直接原因だった(#1551バグ2)。

    新設計では、耳グループ(tier0)は**自tier内**でのみ振幅昇順を使う——
    ランク表を逆順にしても、tier0スロットが"hubEar"の1本しか無いこの
    フィクスチャでは、耳グループは常に"hubEar"を得る(他tierのスロットへ
    絶対に漏れ出さない)。旧テストが検証していた「名前ではなく数値に従う」
    という性質は、`test_assign_slots_by_visibility_amplitude_ear_gets_
    quietest_slot`が別途(tier内の振幅昇順として)引き続き検証している。"""
    physbones = _make_physbones_json([
        ("Hips", ["tail_01"], 0.5, 0.5),
        ("Head_L.001", ["ear_01"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    hub_names = ("hubEar", "hubMid", "hubTail")
    reversed_rank = {"hubEar": 90.0, "hubMid": 50.0, "hubTail": 10.0}
    slot_indices = hub._assign_slots_by_visibility_amplitude(
        plan.accepted, hub_names, reversed_rank)
    ear_group_pos = [i for i, g in enumerate(plan.accepted) if g.anchor == "Head_L.001"][0]
    tail_group_pos = [i for i, g in enumerate(plan.accepted) if g.is_tail][0]
    assert hub_names[slot_indices[ear_group_pos]] == "hubEar"
    assert hub_names[slot_indices[tail_group_pos]] == "hubTail"


def test_assign_slots_by_visibility_amplitude_prevents_unrelated_group_from_stealing_ear_slot_dev1551():
    """dev#1551受入条件③「耳donorが耳anchorに割り当たる(横取り再現の負の
    対照つき)」の本体。正本: work\\run_1551\\integL\\RESULT.md バグ2
    (`HeadEquip062_ear_01_r`が無関係な"Upper Arm.L.001"鎖に横取りされた
    実データ)。

    フィクスチャ: tier0スロットが2本("hubEarL"=amp5、"hubEarR"=amp6)、
    tier1スロットが1本("hubMid"=amp20)。tier0グループ(耳)は1つしか無い
    (=1本しか消費しない)。

    **横取り再現(負の対照、旧アルゴリズムの直接再現)**: 旧実装は
    tierをまたいだフラットな振幅昇順1本のキューへ、tier昇順の処理順で
    グループを対応させていた——耳グループがamp5("hubEarL")を得た後、
    次点(tier1の"Chest"グループ)は**tierを問わず**次に安い
    amp6("hubEarR")を得ていた。この「フラットな1本のキュー」実装を
    ここで直接再現し、実際に耳系スロットが盗まれることを示す(=このバグが
    実在したことの直接証拠)。

    **新実装**: 同じ入力に対し、"Chest"(tier1)は自tier内の"hubMid"
    (amp20)を得て、"hubEarR"はどのtier0グループも要求しないため未消費の
    まま残る——耳系スロットが無関係なグループへ渡らないことの証明。"""
    physbones = _make_physbones_json([
        ("Head_L.001", ["ear_01"], 0.5, 0.5),   # ear -> tier0, 1 group only
        ("Chest", ["scarf_01"], 0.5, 0.5),       # generic -> tier1
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    hub_names = ("hubEarL", "hubEarR", "hubMid")
    amplitude_rank = {"hubEarL": 5.0, "hubEarR": 6.0, "hubMid": 20.0}

    # ---- 横取り再現(旧アルゴリズムの再実装、負の対照) ----
    n = len(plan.accepted)
    old_slot_order_by_amplitude = sorted(
        range(len(hub_names)),
        key=lambda i: (amplitude_rank.get(hub_names[i], float("inf")), i))
    old_claim_order = sorted(
        range(n), key=lambda i: (hub._group_visibility_tier(plan.accepted[i]), i))
    old_slot_for_group_index = {}
    for rank_pos, group_idx in enumerate(old_claim_order):
        old_slot_for_group_index[group_idx] = old_slot_order_by_amplitude[rank_pos]
    old_result = [old_slot_for_group_index[i] for i in range(n)]
    chest_pos = [i for i, g in enumerate(plan.accepted) if g.anchor == "Chest"][0]
    assert hub_names[old_result[chest_pos]] == "hubEarR", (
        "sanity check: 旧アルゴリズムの再現が実際に横取りを起こすことを確認 "
        "(このアサーションが失敗する場合は再現自体が不正確)")

    # ---- 新実装: 横取りされない ----
    new_result = hub._assign_slots_by_visibility_amplitude(
        plan.accepted, hub_names, amplitude_rank)
    ear_pos = [i for i, g in enumerate(plan.accepted) if g.anchor == "Head_L.001"][0]
    assert hub_names[new_result[ear_pos]] == "hubEarL"
    assert hub_names[new_result[chest_pos]] == "hubMid"
    assert "hubEarR" not in {hub_names[i] for i in new_result}


def test_plan_hub_wiring_prevents_unrelated_group_from_stealing_ear_slot_dev1551():
    """上のテストの統合版: `plan_hub_wiring()`経由でも、耳系donorが
    実際に耳anchorへ割り当たり、無関係なグループの`hub_root_female`には
    ならないことを確認する(dev#1551受入条件③)。"""
    defs = [("root", -1),
            ("hubEarL", 0), ("hubEarR", 0), ("hubMid", 0),
            ("hubEarL_m", 0), ("hubEarR_m", 0), ("hubMid_m", 0)]
    defs += [(f"free{i:02d}", 0) for i in range(1, 31)]
    bones = [{"name": n, "parent_idx": p, "quat": [0, 0, 0, 1],
              "pos": [0, 0, 0], "scale": [1, 1, 1]} for n, p in defs]
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    hub_slots = hub.HubSlots(female=("hubEarL", "hubEarR", "hubMid"),
                              male=("hubEarL_m", "hubEarR_m", "hubMid_m"))
    reserved = frozenset()

    physbones = _make_physbones_json([
        ("Head_L.001", ["ear_01"], 0.5, 0.5),
        ("Chest", ["scarf_01"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    amplitude_rank = {"hubEarL": 5.0, "hubEarL_m": 5.0,
                       "hubEarR": 6.0, "hubEarR_m": 6.0,
                       "hubMid": 20.0, "hubMid_m": 20.0}

    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved,
                                  amplitude_rank=amplitude_rank)
    by_anchor = {gp.group.anchor: gp for gp in wiring.group_plans}
    assert by_anchor["Head_L.001"].hub_root_female == "hubEarL"
    assert by_anchor["Chest"].hub_root_female == "hubMid"
    assert by_anchor["Chest"].hub_root_female != "hubEarR"


def test_plan_hub_wiring_amplitude_rank_routes_ear_to_quiet_root():
    """統合テスト: plan_hub_wiring()にamplitude_rankを渡すと、耳グループが
    実際に最も静かなhub root名を得る(旧enumerate順なら優先順位1位の
    しっぽがslot0=hubEarを得ていたはずの構成)。

    dev#1551(耳donorの横取り防止): しっぽは自tier(2)内の"hubTail"を得る
    ("hubMid"はtier1向けで対応するグループが無いため未消費のまま残る、
    `test_assign_slots_by_visibility_amplitude_ear_gets_quietest_slot`の
    tier内訳と整合)。"""
    physbones = _make_physbones_json([
        ("Hips", [f"tail_{i:02d}" for i in range(1, 6)], 0.5, 0.5),  # tail, priority 1st
        ("Head_L.001", ["ear_01"], 0.5, 0.5),                        # ear, priority 2nd
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _three_slot_hub_environment()
    amplitude_rank = {"hubEar": 10.0, "hubEar_m": 10.0,
                       "hubMid": 50.0, "hubMid_m": 50.0,
                       "hubTail": 90.0, "hubTail_m": 90.0}

    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved,
                                  amplitude_rank=amplitude_rank)
    by_anchor = {gp.group.anchor: gp for gp in wiring.group_plans}
    assert by_anchor["Head_L.001"].hub_root_female == "hubEar"
    # しっぽ(tier2)は自tier内で唯一のスロット"hubTail"を得る。
    assert by_anchor["Hips"].hub_root_female == "hubTail"


def test_plan_hub_wiring_without_amplitude_rank_keeps_legacy_enumerate_order():
    """4既定値不変: amplitude_rank省略時は従来どおり優先順位=スロット順
    そのまま(しっぽが1位ならslot0=hubEarを得る、旧`test_plan_hub_wiring_
    assigns_slots_in_priority_order`と同じ挙動)。"""
    physbones = _make_physbones_json([
        ("Hips", [f"tail_{i:02d}" for i in range(1, 6)], 0.5, 0.5),
        ("Head_L.001", ["ear_01"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    catalog, hub_slots, reserved = _three_slot_hub_environment()
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    by_anchor = {gp.group.anchor: gp for gp in wiring.group_plans}
    assert by_anchor["Hips"].hub_root_female == "hubEar"  # 優先順位1位がslot0のまま


def test_free_donor_pool_excludes_known_moving_bones():
    bones = _synthetic_bones()
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    reserved = hub.reserved_descendants_of(["hub1"], bones)
    pool_without = hub.free_donor_pool(catalog, reserved, hub_root_names=["hub1", "hub2"])
    assert "free1" in pool_without
    pool_with = hub.free_donor_pool(
        catalog, reserved, hub_root_names=["hub1", "hub2"],
        known_moving=frozenset({"free1", "free2"}))
    assert "free1" not in pool_with
    assert "free2" not in pool_with
    assert "free3" in pool_with  # 指定していない骨は引き続き利用可能


def test_load_root_amplitude_rank_reads_packaged_data():
    """dev#1551 Lane P4: sway_root_amplitude.json(laneA4実測データ)は旧6服骨
    root名をキーに持つ実測値だが、本WPはそれらを非服骨6本へ差し替えた
    (NOTES.md §2/§4)。実測値は当時のroot名に対する測定であり、新root名への
    転記は未実測の値を捏造することになるため行わない(値を寄せて合わせない
    原則)。load_root_amplitude_rank()は新root名に対応するエントリが無い場合
    自動的にamplitude-aware割当を無効化し従来順にフォールバックする設計
    (モジュールdocstring「安全側フォールバック」節)であり機能上の欠陥は無い
    ——本テストは「旧共有3root(不変)の実測データが引き続き読める」ことのみ
    検証する。新root6本の実測(振幅ランク再取得)は別途の実機計測レーンの
    フォローアップ対象(NOTES.md記載)。"""
    rank = hub.load_root_amplitude_rank()
    # 旧sway_root_amplitude.jsonの16キー全てが引き続き読める(ファイル自体は
    # 本WPで変更していないため無退行)。全キーがall_kp_node_root_names()の
    # 部分集合である必要はもう無い(新root6本のデータは未取得)。
    assert len(rank) == 16
    unchanged_shared_roots = {
        "HeadEquip062_ear_01_l", "HeadEquip062_ear_01_r",
        "NPC_GrassBoss001_Skin001_tail_01"}
    assert unchanged_shared_roots <= set(rank)
    assert unchanged_shared_roots <= set(hub.all_kp_node_root_names())
    # 新root6本は現時点でamplitude未実測(データ欠落=安全側フォールバック対象)
    new_roots = {
        "NPC_SnowBoss_belt_01_l", "NPC_SnowBoss_belt_01_r",
        "HeadEquip046_hairA_01_l", "HeadEquip046_hairA_01_r",
        "NPC_WorldTreeBoss001_skirtD_01_l", "NPC_GrassBoss001_Skin001_hat_cone_01"}
    assert new_roots <= set(hub.all_kp_node_root_names())
    assert not (new_roots & set(rank))
    # 耳(HeadEquip062_ear_01_l/_r)は現行flatHaori実測でしっぽ系よりも静か
    # (laneA4 FINDINGS.md 1節、実測値そのものへの依存を避けるため大小関係のみ検査)
    assert rank["HeadEquip062_ear_01_l"] < rank["F_Hunter001_14"]
    assert rank["HeadEquip062_ear_01_r"] < rank["F_OldCloth001_01"]


def test_load_root_amplitude_rank_missing_file_returns_empty_dict(tmp_path):
    rank = hub.load_root_amplitude_rank(path=str(tmp_path / "does_not_exist.json"))
    assert rank == {}


def test_load_known_moving_chain_bones_reads_packaged_data():
    moving = hub.load_known_moving_chain_bones()
    assert isinstance(moving, frozenset)
    assert len(moving) > 0
    # hub root自身(16本)はこのリストの対象外(reservedで別途処理される)
    assert not (moving & hub.all_kp_node_root_names())


def test_load_known_moving_chain_bones_missing_file_returns_empty_frozenset(tmp_path):
    moving = hub.load_known_moving_chain_bones(path=str(tmp_path / "does_not_exist.json"))
    assert moving == frozenset()


# =====================================================================
# dev#1551 chain-length-fit(先端マージ・native chain優先)
# =====================================================================

def _linear_native_chain_environment(native_len, hub_female="hubA", hub_male=None,
                                      free_bone_count=20):
    """`hub_female`(univariant時はhub_maleも同じ名前)自身の直系子孫を
    `native_len`本、一本道でぶら下げた合成環境。豊富な自由骨プール
    ("free01".."freeNN")も併設する(hub_femaleより後ろのインデックス)。

    戻り値: (catalog, hub_slots, reserved, native_names)。"""
    hub_male = hub_male or hub_female
    names_parents = [("root", -1), (hub_female, 0)]
    if hub_male != hub_female:
        names_parents.append((hub_male, 0))
    hub_idx = 1  # hub_femaleの索引(rootの直後)
    parent_idx = hub_idx
    native_names = []
    for i in range(1, native_len + 1):
        name = f"{hub_female}_native_{i:02d}"
        names_parents.append((name, parent_idx))
        native_names.append(name)
        parent_idx = len(names_parents) - 1
    for i in range(1, free_bone_count + 1):
        names_parents.append((f"free{i:02d}", 0))
    bones = [{"name": n, "parent_idx": p, "quat": [0, 0, 0, 1],
              "pos": [0, 0, 0], "scale": [1, 1, 1]} for n, p in names_parents]
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    hub_slots = hub.HubSlots(female=(hub_female,), male=(hub_male,))
    reserved = frozenset()
    return catalog, hub_slots, reserved, tuple(native_names)


# ---- fit_chain_to_length() 純粋関数 ----

def test_fit_chain_to_length_no_merge_when_fits():
    """負の対照: donorが十分にあるとき(max_len>=len(chain))は無変形
    (恒等写像、マージ発生ゼロ)——「donor十分時は無変形」の受入条件その
    もの。"""
    chain = ("anchor", "a1", "a2", "a3")
    fitted, expansion = hub.fit_chain_to_length(chain, 4)
    assert fitted == chain
    assert expansion == {b: b for b in chain}

    fitted2, expansion2 = hub.fit_chain_to_length(chain, 10)
    assert fitted2 == chain
    assert expansion2 == {b: b for b in chain}


def test_fit_chain_to_length_merges_from_tip_root_untouched():
    """分配マージ(dev#1572)で根本(chain[0])は単独グループのまま残ることを
    確認する。6要素を3スロットへ縮退: 根本1+残り5要素を2グループへ均等
    分配(2,3)、余りは先端側の塊へ。"""
    chain = ("anchor", "a1", "a2", "a3", "a4", "a5")
    fitted, expansion = hub.fit_chain_to_length(chain, 3)
    assert len(fitted) == 3
    assert fitted[0] == "anchor"  # 根本は単独グループのまま、代表=自分自身
    assert expansion["anchor"] == "anchor"  # 根本は他要素とマージされない
    # 6要素・3スロット: [anchor],[a1,a2],[a3,a4,a5]
    assert fitted == ("anchor", "a2", "a5")
    assert expansion["a1"] == "a2" and expansion["a2"] == "a2"
    assert expansion["a3"] == "a5" and expansion["a4"] == "a5" and expansion["a5"] == "a5"


def test_fit_chain_to_length_merge_order_is_strictly_tip_first():
    """分配マージの均等割りが単一ペアに収束するケース: 5要素を4スロット
    (根本1+残り4要素を3グループへ均等分配)へ縮退させると、余り1本が
    先端側の塊に付き「最後の2要素だけ」が併合される——中間や根本寄りの
    要素は絶対にマージされないことを確認する。"""
    chain = ("anchor", "b1", "b2", "b3", "b4")
    fitted, expansion = hub.fit_chain_to_length(chain, 4)
    assert fitted == ("anchor", "b1", "b2", "b4")
    assert expansion["b3"] == "b4" and expansion["b4"] == "b4"
    for solo in ("anchor", "b1", "b2"):
        assert expansion[solo] == solo


def test_fit_chain_to_length_max_len_one_merges_everything_including_root():
    """dev#1572(2026-08-18訂正): 実効節数1は根本も含めた全結合が
    唯一の例外規則(「実効1のときだけ全結合」)。旧仕様(根本は絶対に
    マージしない→max_len=1はChainFitError)を上書きする回帰固定。"""
    chain = ("anchor", "a1", "a2")
    fitted, expansion = hub.fit_chain_to_length(chain, 1)
    assert fitted == ("a2",)
    assert expansion == {"anchor": "a2", "a1": "a2", "a2": "a2"}


def test_fit_chain_to_length_negative_control_zero_capacity_still_errors():
    """負の対照: donor容量が0本(max_len<=0)なら、実効節数1の全結合
    例外をもってしても収まる先が無いため、引き続き`ChainFitError`を
    送出することを確認する。"""
    chain = ("anchor", "a1", "a2")
    with pytest.raises(hub.ChainFitError):
        hub.fit_chain_to_length(chain, 0)
    with pytest.raises(hub.ChainFitError):
        hub.fit_chain_to_length(chain, -1)


def test_fit_chain_to_length_owner_distribution_table_five_bones():
    """オーナー確定の分配表そのもの(dev#1572、2026-08-18裁定): 5骨
    ABCDE(Aが根本)、実効節数n=1..5すべてを固定する。
    1:(ABCDE) / 2:A(BCDE) / 3:A(BC)(DE) / 4:ABC(DE) / 5:ABCDE。"""
    chain = ("A", "B", "C", "D", "E")

    fitted1, exp1 = hub.fit_chain_to_length(chain, 1)
    assert fitted1 == ("E",)
    assert exp1 == {"A": "E", "B": "E", "C": "E", "D": "E", "E": "E"}

    fitted2, exp2 = hub.fit_chain_to_length(chain, 2)
    assert fitted2 == ("A", "E")
    assert exp2 == {"A": "A", "B": "E", "C": "E", "D": "E", "E": "E"}

    fitted3, exp3 = hub.fit_chain_to_length(chain, 3)
    assert fitted3 == ("A", "C", "E")
    assert exp3 == {"A": "A", "B": "C", "C": "C", "D": "E", "E": "E"}

    fitted4, exp4 = hub.fit_chain_to_length(chain, 4)
    assert fitted4 == ("A", "B", "C", "E")
    assert exp4 == {"A": "A", "B": "B", "C": "C", "D": "E", "E": "E"}

    fitted5, exp5 = hub.fit_chain_to_length(chain, 5)
    assert fitted5 == chain
    assert exp5 == {b: b for b in chain}


def test_fit_chain_to_length_owner_general_rule_six_bones_effective_three():
    """一般則の確認(dev#1572): 6骨実効3なら A(BC)(DEF)——残りノード数2へ
    残り5要素を均等分配(2,3)、余り1本は先端側の塊へ。"""
    chain = ("A", "B", "C", "D", "E", "F")
    fitted, expansion = hub.fit_chain_to_length(chain, 3)
    assert fitted == ("A", "C", "F")
    assert expansion == {
        "A": "A", "B": "C", "C": "C", "D": "F", "E": "F", "F": "F",
    }


def test_fit_chain_to_length_single_element_chain():
    fitted, expansion = hub.fit_chain_to_length(("anchor",), 1)
    assert fitted == ("anchor",)
    assert expansion == {"anchor": "anchor"}


def test_fit_chain_to_length_empty_chain():
    assert hub.fit_chain_to_length((), 5) == ((), {})


# ---- donor_group_members() 純粋関数(dev#1572夜間便2: 幾何とウェイトの
# グルーピング単一ソース化) ----

def test_donor_group_members_matches_fit_chain_to_length_grouping():
    """`donor_group_members()`が`fit_chain_to_length()`の実際のグループ
    分割(根元→先端順・境界)をそのまま再現することを、
    `ChainDonorPlan.weight_expansion`経由で確認する——`sway_hub_wire.
    source_to_donor_bone_map()`(ウェイト側)が使うのと同じ`weight_
    expansion`から、幾何側(`place_hub_donor_chains()`/
    `sway_hub_placement.resolve_grouped_chain()`)が引く関数。"""
    fitted, expansion = hub.fit_chain_to_length(("anchor", "m1", "m2", "m3"), 3)
    assert fitted == ("anchor", "m1", "m3")
    cp = hub.ChainDonorPlan(
        source_chain=fitted,
        donor_chain_female=("d0", "d1"), donor_chain_male=("d0", "d1"),
        weight_expansion=expansion)

    groups = hub.donor_group_members(cp)

    assert groups["anchor"] == ("anchor",)
    assert groups["m1"] == ("m1",)
    # 代表m3のグループは[m2,m3](根元->先端順)——m3単独ではない。
    assert groups["m3"] == ("m2", "m3")


def test_donor_group_members_negative_control_detects_wrong_expansion():
    """負の対照: `weight_expansion`が(バグを再現して)誤った境界を持てば、
    `donor_group_members()`はその誤った境界をそのまま反映する——つまり
    本関数は固定のグルーピングを返す独自ロジックではなく、渡された
    `weight_expansion`(フィット計画の実際の出力)に忠実であることの確認。"""
    # 正しい境界: [m1]|[m2,m3](fit_chain_to_length(4骨,3)の実際の出力)。
    correct_expansion = {"anchor": "anchor", "m1": "m1", "m2": "m3", "m3": "m3"}
    # 誤った境界(旧幾何バグが実質やっていたのと同じ、境界が1個ずれた版):
    # [m1,m2]|[m3]。
    wrong_expansion = {"anchor": "anchor", "m1": "m2", "m2": "m2", "m3": "m3"}

    cp_correct = hub.ChainDonorPlan(
        source_chain=("anchor", "m1", "m3"),
        donor_chain_female=("d0", "d1"), donor_chain_male=("d0", "d1"),
        weight_expansion=correct_expansion)
    cp_wrong = hub.ChainDonorPlan(
        source_chain=("anchor", "m2", "m3"),
        donor_chain_female=("d0", "d1"), donor_chain_male=("d0", "d1"),
        weight_expansion=wrong_expansion)

    groups_correct = hub.donor_group_members(cp_correct)
    groups_wrong = hub.donor_group_members(cp_wrong)

    assert groups_correct["m3"] == ("m2", "m3")
    assert groups_wrong["m2"] == ("m1", "m2")  # 境界が1個ずれて検出される
    assert groups_correct["m3"] != groups_wrong["m2"]


# ---- hub_native_descendant_chain() 純粋関数 ----

def test_hub_native_descendant_chain_walks_linear_descendants():
    catalog, _hub_slots, _reserved, native_names = _linear_native_chain_environment(4)
    walked = hub.hub_native_descendant_chain("hubA", catalog, frozenset())
    assert walked == native_names


def test_hub_native_descendant_chain_stops_at_branch():
    """分岐(子が2本以上)に達したら、その手前で打ち切ることを確認する。"""
    bones = [
        {"name": "root", "parent_idx": -1, "quat": [0, 0, 0, 1], "pos": [0, 0, 0], "scale": [1, 1, 1]},
        {"name": "hubA", "parent_idx": 0, "quat": [0, 0, 0, 1], "pos": [0, 0, 0], "scale": [1, 1, 1]},
        {"name": "hubA_n1", "parent_idx": 1, "quat": [0, 0, 0, 1], "pos": [0, 0, 0], "scale": [1, 1, 1]},
        {"name": "hubA_branch_l", "parent_idx": 2, "quat": [0, 0, 0, 1], "pos": [0, 0, 0], "scale": [1, 1, 1]},
        {"name": "hubA_branch_r", "parent_idx": 2, "quat": [0, 0, 0, 1], "pos": [0, 0, 0], "scale": [1, 1, 1]},
    ]
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    walked = hub.hub_native_descendant_chain("hubA", catalog, frozenset())
    assert walked == ("hubA_n1",)  # 分岐(branch_l/branch_r)の手前で停止


def test_hub_native_descendant_chain_stops_at_other_hub_root():
    catalog, _hub_slots, _reserved, native_names = _linear_native_chain_environment(4)
    # native_names[2](3本目)を「他ハブのroot」として停止集合に加える
    stop_at = frozenset({native_names[2]})
    walked = hub.hub_native_descendant_chain("hubA", catalog, stop_at)
    assert walked == native_names[:2]


def test_hub_native_descendant_chain_missing_hub_returns_empty():
    catalog, _hub_slots, _reserved, _native_names = _linear_native_chain_environment(4)
    assert hub.hub_native_descendant_chain("does_not_exist", catalog, frozenset()) == ()


def test_hub_native_descendant_chain_leaf_hub_returns_empty():
    """子孫が無い(葉)ハブは空タプル(既存の自由プール経路への安全な
    フォールバックに使われることの前提条件)。"""
    catalog, _hub_slots, _reserved, _native_names = _linear_native_chain_environment(0)
    assert hub.hub_native_descendant_chain("hubA", catalog, frozenset()) == ()


# ---- plan_hub_wiring()への結線(統合テスト) ----

def test_plan_hub_wiring_prefers_native_chain_over_free_pool():
    """native chainが要求本数を満たすとき、donorはnative chainからそのまま
    (先端マージ無し)割り当てられ、自由骨プールは一切消費されないことを
    確認する(dev#1551 chain-length-fit、flatHaori耳バグの直接固定)。

    dev#1572(2026-08-19朝裁定、容量root込み訂正): hub root自身が
    anchor(Head_L.001)の実donorを担うため(PR #1569)、内容として実際に
    ウェイトを持つのはanchorを除いた残り2本(Head_L.002/003)ぶんの2本
    だけ。**同日朝の追加裁定(余剰donorの先端延長を全donor登録へ訂正)**:
    それでも`donor_chain_female`自体はnative_chain全4本を登録する
    ——残り2本(native_names[2:])は内容写像の無い無ウェイト延長donor
    として付く(donor*登録*本数は常に全capacity、旧裁定の復元)。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(4)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003"], 0.5, 0.5),  # anchor+2=3本
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert not wiring.unassignable
    cp = wiring.group_plans[0].chain_plans[0]
    assert cp.donor_chain_female == native_names  # 内容2本+延長2本=native全4本
    assert cp.source_chain == ("Head_L.001", "Head_L.002", "Head_L.003")
    assert cp.weight_expansion == {b: b for b in cp.source_chain}
    # 延長donor(native_names[2:])はweight_expansionのどの値にも現れない
    # (=無ウェイト、source_to_donor_bone_map()のzip()が自動的に除外)。
    assert set(native_names[2:]).isdisjoint(cp.weight_expansion.values())
    assert not wiring.chain_fit_events  # 節数フィットは発動していない
    # 自由プール("free..")は一切使われていない
    assert all(not d.startswith("free") for d in cp.donor_chain_female)


def test_plan_hub_wiring_negative_control_sufficient_donor_no_deformation():
    """負の対照: native chainがソース鎖より長い(容量に余裕がある)場合も
    先端マージは起きない——内容として実ウェイトを持つのはn_ext-1(=2)本
    (`native_names[:2]`)。**同日朝の追加裁定**により`donor_chain_female`
    自体はnative8本全部を登録する(残り6本は無ウェイト延長)——「容量に
    余裕がある=延長が長くなる」だけで、donor登録本数がsafety_margin/
    充足度に応じて変わることはない(常にnative_chain全長)。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(8)
    physbones = _make_physbones_json([
        ("Hips", ["tail_01", "tail_02"], 0.5, 0.5),  # anchor+2=3本
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    cp = wiring.group_plans[0].chain_plans[0]
    assert len(cp.donor_chain_female) == 8  # native全長(内容2本+延長6本)
    assert cp.donor_chain_female == native_names
    assert cp.weight_expansion == {b: b for b in cp.source_chain}
    assert set(native_names[2:]).isdisjoint(cp.weight_expansion.values())
    assert not wiring.chain_fit_events


def test_plan_hub_wiring_chain_length_fit_merges_from_tip_when_native_short():
    """native chainが要求本数に足りないとき、節数フィット(先端マージ)が
    発動し、(a) 根本(anchor)は無傷、(b) donorはnative chain全本を使い切る、
    (c) weight_expansionが末尾要素を先端側代表へまとめる、(d) 診断ログ
    (`chain_fit_events`)が英語で記録されることを確認する。

    dev#1572(容量root込み訂正): native3本+hub root自身1本=容量4
    (旧式は容量3のみだった)。target_len=min(4,6)=4(anchor+3グループ)。
    分配マージ(fit_chain_to_length、根本1+残り5要素を3グループへ均等
    分配、余りは先端側): [Head_L.001],[Head_L.002],[Head_L.003,Head_L.004],
    [Head_L.005,Head_L.006]。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(3)
    physbones = _make_physbones_json([
        # anchor+5=6本要求、native chain(root抜き)は3本しか無い
        # -> root込み容量4でもフィット必須
        ("Head_L.001", ["Head_L.002", "Head_L.003", "Head_L.004",
                         "Head_L.005", "Head_L.006"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert not wiring.unassignable
    cp = wiring.group_plans[0].chain_plans[0]
    assert cp.donor_chain_female == native_names  # native全3本を使い切る
    assert len(cp.source_chain) == 4
    assert cp.source_chain == ("Head_L.001", "Head_L.002", "Head_L.004", "Head_L.006")
    assert cp.source_chain[0] == "Head_L.001"  # 根本は無傷
    assert cp.weight_expansion["Head_L.001"] == "Head_L.001"
    assert cp.weight_expansion["Head_L.002"] == "Head_L.002"  # 単独グループ
    # [Head_L.003,Head_L.004]グループ(先端寄り代表=004)
    assert cp.weight_expansion["Head_L.003"] == "Head_L.004"
    assert cp.weight_expansion["Head_L.004"] == "Head_L.004"
    # [Head_L.005,Head_L.006]グループ(先端寄り代表=006)
    assert cp.weight_expansion["Head_L.005"] == "Head_L.006"
    assert cp.weight_expansion["Head_L.006"] == "Head_L.006"
    # 診断ログに「何節→何節」が英語で明示される
    assert wiring.chain_fit_events
    msg = wiring.chain_fit_events[0]
    assert "merged from tip" in msg
    assert "6" in msg and "4" in msg
    assert "Head_L.001" in msg


def test_plan_hub_wiring_falls_back_to_free_pool_when_no_native_chain():
    """native chainが存在しない(ハブが葉)場合、既存の自由プール経路へ
    完全にフォールバックする(無退行、旧来の全テストが緑のままなことの
    直接固定)。"""
    catalog, hub_slots, reserved, _native_names = _linear_native_chain_environment(0)
    physbones = _make_physbones_json([
        ("Hips", ["tail_01", "tail_02"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    cp = wiring.group_plans[0].chain_plans[0]
    assert all(d.startswith("free") for d in cp.donor_chain_female)
    assert not wiring.chain_fit_events


def test_plan_hub_wiring_bivariant_slot_never_uses_native_chain():
    """bivariant(女性/男性で別名ハブ)スロットは、native chainが存在しても
    使わず、既存の自由プール経路のまま(スコープ限定の明示的固定)。
    native descendants(hubA_native_*)は本番同様`reserved_descendants_of()`
    で自由プールから予約済みとし、万一bivariant経路が誤ってnative chainを
    使ってしまえば「free」始まり以外のdonorが出て検出できるようにする。"""
    catalog, hub_slots, _reserved, native_names = _linear_native_chain_environment(
        4, hub_female="hubA", hub_male="hubA_m")
    reserved = hub.reserved_descendants_of(("hubA",), catalog.bones)
    assert set(native_names) <= reserved  # 前提(本番同様に予約されていること)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    cp = wiring.group_plans[0].chain_plans[0]
    assert all(d.startswith("free") for d in cp.donor_chain_female)
    assert all(d.startswith("free") for d in cp.donor_chain_male)
    assert not wiring.chain_fit_events



# =====================================================================
# dev#1572(2026-08-19朝追加裁定「余剰donorの先端延長を全donor登録へ訂正」)
# 受入表そのもの(耳相当・しっぽ相当)+登録総数不変の負の対照。
# =====================================================================

def test_plan_hub_wiring_extension_owner_table_ear_capacity_root_included_four():
    """dev#1572(2026-08-19朝追加裁定)の受入表(耳相当、容量root込み4=
    hub root自身1本+native descendant3本、アバター鎖長3=anchor+子2本)を
    そのまま`plan_hub_wiring()`統合で検証する
    (`test_target_len_with_safety_margin_owner_table_ear_capacity_root_
    included_four`の統合版): 安全域0→内容3+延長1 / 2→内容2+延長2 /
    3以上→内容1+延長3(内容=反映骨数target_len(root込み)、延長=
    capacity_root_included-target_len)。**donor*登録*総数
    (`len(cp.donor_chain_female)`)はどの安全域でもnative全3本のまま不変**
    ——これが本WPの中心受入条件。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(3)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003"], 0.5, 0.5),  # anchor+2=3本(n_ext=3)
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    capacity_root_included = 4
    expected = {0: (3, 1), 2: (2, 2), 3: (1, 3), 5: (1, 3)}  # margin -> (内容target_len, 延長)
    for margin, (want_target_len, want_extension) in expected.items():
        wiring = hub.plan_hub_wiring(
            plan, catalog, hub_slots, reserved, default_safety_margin=margin)
        cp = wiring.group_plans[0].chain_plans[0]
        got_target_len = len(cp.source_chain)
        assert got_target_len == want_target_len, f"margin={margin}"
        got_extension = capacity_root_included - got_target_len
        assert got_extension == want_extension, f"margin={margin}"
        # 登録総数(=native全長)は安全域と無関係に常に3本で不変。
        assert cp.donor_chain_female == native_names
        assert len(cp.donor_chain_female) == 3


def test_plan_hub_wiring_extension_owner_table_tail_capacity_root_included_six():
    """dev#1572(2026-08-19朝追加裁定)の受入表(しっぽ相当、容量root込み6=
    hub root自身1本+native descendant5本、アバター鎖長6=anchor+子5本):
    安全域0→内容6+延長0 / 5→内容1+延長5。**donor登録総数はnative全5本の
    まま不変**。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(5)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003", "Head_L.004",
                         "Head_L.005", "Head_L.006"], 0.5, 0.5),  # anchor+5=6本(n_ext=6)
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    capacity_root_included = 6
    expected = {0: (6, 0), 5: (1, 5)}
    for margin, (want_target_len, want_extension) in expected.items():
        wiring = hub.plan_hub_wiring(
            plan, catalog, hub_slots, reserved, default_safety_margin=margin)
        cp = wiring.group_plans[0].chain_plans[0]
        got_target_len = len(cp.source_chain)
        assert got_target_len == want_target_len, f"margin={margin}"
        got_extension = capacity_root_included - got_target_len
        assert got_extension == want_extension, f"margin={margin}"
        assert cp.donor_chain_female == native_names
        assert len(cp.donor_chain_female) == 5


def test_plan_hub_wiring_extension_negative_control_registration_count_would_vary_without_it():
    """負の対照(gate #4): 「延長を付けない」旧実装(内容本数ぶんだけ登録、
    dev#1572のPR #1577がやっていたこと)を`donor_chain_female[:donor_needed
    相当]`で再現し、その場合はdonor登録本数が安全域ごとに変わってしまう
    ことを直接示す——本WP実装(登録は常に`native_names`全体)がこの退行を
    構造的に防いでいることの証明。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(3)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)

    lengths_without_extension = set()
    lengths_with_extension = set()
    for margin in (0, 2, 3):
        wiring = hub.plan_hub_wiring(
            plan, catalog, hub_slots, reserved, default_safety_margin=margin)
        cp = wiring.group_plans[0].chain_plans[0]
        content_only_len = len(cp.source_chain) - 1  # 旧実装が登録していたであろう本数(donor_needed)
        lengths_without_extension.add(content_only_len)
        lengths_with_extension.add(len(cp.donor_chain_female))

    # 旧(内容のみ)実装なら安全域ごとに登録本数が変わっていた(2,1,0 -> 3種)。
    assert lengths_without_extension == {2, 1, 0}
    # 本WP実装は登録本数が常に1種類(native全長3)に固定される。
    assert lengths_with_extension == {3}


def test_merged_weight_groups_extracts_merge_sets():
    """dev#1572(2026-08-19朝裁定、容量root込み訂正): native chain3本+
    hub root自身1本=容量4、ソース鎖6本(anchor+5)なのでtarget_len=4。
    分配規則により根本1+残り5要素を3グループへ均等分配(1,2,2)、余りは
    先端側——[Head_L.001],[002],[003,004],[005,006]となり、2要素以上の
    **2つ**の合流グループが検出される(旧式は容量3(root抜き)しか
    見えず、target_len=3(合流グループ1つ)だった——本WPで容量root込みへ
    訂正した結果、合流グループの境界も変わる)。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(3)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003", "Head_L.004",
                         "Head_L.005", "Head_L.006"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    groups = hub.merged_weight_groups(wiring)
    assert groups == frozenset({
        frozenset({"Head_L.003", "Head_L.004"}),
        frozenset({"Head_L.005", "Head_L.006"}),
    })
    all_merged = set().union(*groups)
    assert "Head_L.001" not in all_merged  # 根本は絶対に混ざらない


def test_merged_weight_groups_empty_when_no_merges_occurred():
    catalog, hub_slots, reserved, _native_names = _linear_native_chain_environment(4)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    assert hub.merged_weight_groups(wiring) == frozenset()


def test_representative_of_map_identity_when_no_merges():
    catalog, hub_slots, reserved, _native_names = _linear_native_chain_environment(4)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    rep = hub.representative_of_map(wiring)
    assert rep == {"Head_L.001": "Head_L.001", "Head_L.002": "Head_L.002"}


def test_representative_of_map_dev1551_maps_merged_tip_to_representative():
    """dev#1551実機検証で判明した回帰固定(dev#1572容量root込み訂正後の
    数値に更新): native chainが要求本数に足りず先端マージが発動したとき、
    `representative_of_map()`はマージされた**非代表**要素(根元寄り、
    例: Head_L.003)を先端側の代表(例: Head_L.004)へ正しく写す
    ——ジオメトリ比較のスキップ判定に使われる核心データ。容量root込みで
    target_len=4になったため、[Head_L.003,Head_L.004]と[Head_L.005,
    Head_L.006]の**2つ**の合流グループに分かれる
    (`test_merged_weight_groups_extracts_merge_sets`と同一セットアップ)。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(3)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003", "Head_L.004",
                         "Head_L.005", "Head_L.006"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    rep = hub.representative_of_map(wiring)
    assert rep["Head_L.001"] == "Head_L.001"  # 根本は常に代表=自分自身
    assert rep["Head_L.002"] == "Head_L.002"  # 単独グループ(恒等)
    tip_rep_1 = rep["Head_L.004"]
    assert rep["Head_L.004"] == tip_rep_1  # 代表自身は恒等
    assert rep["Head_L.003"] == tip_rep_1  # 非代表は代表へ写る
    tip_rep_2 = rep["Head_L.006"]
    assert rep["Head_L.006"] == tip_rep_2
    assert rep["Head_L.005"] == tip_rep_2


# =====================================================================
# dev#1551 安全域(issue #1551「安全域」欄、2026-08-18オーナー最終裁定)
# =====================================================================

# ---- target_len_with_safety_margin() / resolve_safety_margin() 純粋関数 ----

def test_target_len_with_safety_margin_basic_subtraction():
    """オーナー確定式そのもの(2026-08-18訂正): min(donor容量 - 安全域,
    アバター鎖長)——安全域はdonor容量だけを削る(min先行ではない)。"""
    assert hub.target_len_with_safety_margin(n_ext=4, donor_capacity=4, margin=1) == 3
    assert hub.target_len_with_safety_margin(n_ext=4, donor_capacity=4, margin=2) == 2
    # donorが潤沢(6)なら、安全域1を引いても(5)まだアバター鎖長(4)を
    # 上回るため無変形——旧式(min先行)なら誤って3に削っていたケース。
    assert hub.target_len_with_safety_margin(n_ext=4, donor_capacity=6, margin=1) == 4


def test_target_len_with_safety_margin_owner_table_ear_capacity_root_included_four():
    """dev#1572(2026-08-19朝オーナー裁定)の受入表そのもの(耳相当、
    容量root込み4=hub root自身1本+native descendant3本、
    アバター鎖長3=anchor+子2本): 反映骨数 = max(1, min(容量-安全域,
    鎖長))。安全域0→3/1→3/2→2/3→1/4→1/5→1。"""
    n_ext = 3
    capacity_root_included = 4
    expected = {0: 3, 1: 3, 2: 2, 3: 1, 4: 1, 5: 1}
    for margin, want in expected.items():
        got = hub.target_len_with_safety_margin(
            n_ext=n_ext, donor_capacity=capacity_root_included, margin=margin)
        assert got == want, f"margin={margin}: expected {want}, got {got}"


def test_target_len_with_safety_margin_owner_table_tail_capacity_root_included_six():
    """dev#1572(2026-08-19朝オーナー裁定)の受入表そのもの(しっぽ相当、
    容量root込み6=hub root自身1本+native descendant5本、
    アバター鎖長6=anchor+子5本): 安全域0→6/1→5/2→4/3→3/4→2/5→1。"""
    n_ext = 6
    capacity_root_included = 6
    expected = {0: 6, 1: 5, 2: 4, 3: 3, 4: 2, 5: 1}
    for margin, want in expected.items():
        got = hub.target_len_with_safety_margin(
            n_ext=n_ext, donor_capacity=capacity_root_included, margin=margin)
        assert got == want, f"margin={margin}: expected {want}, got {got}"


def test_target_len_with_safety_margin_owner_worked_example():
    """オーナー検算表そのもの(donor5節・avatar3節、2026-08-18裁定):
    安全域0〜2は全く同じ結果(3節、donor潤沢分が安全域を吸収)、
    安全域3で初めてavatar2節へ減る境界を確認する。"""
    n_ext = 3  # アバター鎖長3節(anchor込みのn_ext規約と一致させる)
    assert hub.target_len_with_safety_margin(n_ext=n_ext, donor_capacity=5, margin=0) == 3
    assert hub.target_len_with_safety_margin(n_ext=n_ext, donor_capacity=5, margin=1) == 3
    assert hub.target_len_with_safety_margin(n_ext=n_ext, donor_capacity=5, margin=2) == 3
    assert hub.target_len_with_safety_margin(n_ext=n_ext, donor_capacity=5, margin=3) == 2


def test_target_len_with_safety_margin_floor_is_one_child_or_anchor_only():
    """反映骨数の下限は1(2026-08-19朝オーナー裁定で2から緩和)——安全域が
    鎖長以上でも0や負値にはならず、必ず1(=hub root自身1本へ全結合)に
    収束する。旧裁定(下限2、anchor+子1本を死守)は容量勘定がroot抜き
    だった旧式に合わせた保守的な下限で、本WPの容量root込み訂正により
    不要になった(root込み容量1(=root自身のみ)でも`n=1`という有効な
    解が存在するため、`fit_chain_to_length()`の「実効節数1のときだけ
    全結合」規則がそのまま使える)。"""
    assert hub.target_len_with_safety_margin(n_ext=4, donor_capacity=4, margin=99) == 1
    assert hub.target_len_with_safety_margin(n_ext=2, donor_capacity=2, margin=99) == 1
    assert hub.target_len_with_safety_margin(n_ext=1, donor_capacity=1, margin=5) == 1


def test_target_len_with_safety_margin_zero_is_identity():
    """負の対照: 安全域0は無変形(min(donor容量,鎖長)そのまま)。"""
    assert hub.target_len_with_safety_margin(n_ext=4, donor_capacity=4, margin=0) == 4
    assert hub.target_len_with_safety_margin(n_ext=4, donor_capacity=3, margin=0) == 3


def test_resolve_safety_margin_uses_default_when_no_override():
    assert hub.resolve_safety_margin(("anchor", "a1"), None, 1) == 1
    assert hub.resolve_safety_margin(("anchor", "a1"), {}, 1) == 1


def test_resolve_safety_margin_override_by_exact_chain_key():
    overrides = {("anchor", "a1", "a2"): 2, ("other",): 0}
    assert hub.resolve_safety_margin(("anchor", "a1", "a2"), overrides, 1) == 2
    assert hub.resolve_safety_margin(("other",), overrides, 1) == 0
    # 未一致のキーはdefault_safety_marginへフォールバック
    assert hub.resolve_safety_margin(("unmatched",), overrides, 1) == 1


def test_resolve_safety_margin_negative_clamped_to_zero():
    assert hub.resolve_safety_margin(("anchor",), {("anchor",): -3}, 1) == 0
    assert hub.resolve_safety_margin(("anchor",), None, -3) == 0


# ---- plan_hub_wiring()統合: default_safety_margin/safety_margin_by_chain ----

def test_plan_hub_wiring_default_safety_margin_zero_is_unchanged():
    """負の対照: default_safety_margin省略(既定0)は「内容」(実ウェイト)を
    一切削らない(margin=0は容量に余裕があればどんな容量でもno-op)。
    dev#1572(容量root込み訂正)によりhub root自身がanchorの実donorを
    担うため、内容として実際にウェイトを持つnative消費はn_ext-1(=2)本
    ——n_ext(=3)本ではない(`test_plan_hub_wiring_prefers_native_chain_
    over_free_pool`と同じ訂正)。**同日朝の追加裁定**: `donor_chain_female`
    自体はnative全4本を登録する(残り2本は無ウェイト延長、内容の縮退
    (margin>0)とは独立に常に全長)。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(4)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003"], 0.5, 0.5),  # anchor+2=3本
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(plan, catalog, hub_slots, reserved)
    cp = wiring.group_plans[0].chain_plans[0]
    assert cp.donor_chain_female == native_names  # 内容2本+延長2本
    assert len(cp.source_chain) == 3
    assert not wiring.chain_fit_events


def test_plan_hub_wiring_default_safety_margin_one_trims_one_tip_bone():
    """本WPの中心仕様: default_safety_margin=1を渡すと、内容(実ウェイト)の
    反映骨数がdonor容量ぎりぎり(native2本+hub root1本=容量3、ソース鎖も
    n_ext=3)のとき3-1=2へ縮む(先端マージ発動)。dev#1572(容量root込み
    訂正、2026-08-19朝裁定): 容量に余裕がある場合(native本数がn_ext以上)は
    安全域1がdonor容量の余剰分に吸収されて縮退が起きない
    (`target_len_with_safety_margin()`のオーナー確定式そのもの)ため、
    ここでは意図的にnative本数をn_ext-1=2本まで絞り、容量ちょうど
    (root込み3=n_ext)のケースで検証する。**同日朝の追加裁定**: 内容が
    1本(target_len(2)-1)へ縮んでも、`donor_chain_female`自体はnative
    全2本を登録する(残り1本は無ウェイト延長)——登録本数は安全域と無関係に
    常にnative_chain全長。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(2)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003"], 0.5, 0.5),  # anchor+2=3本
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved, default_safety_margin=1)
    cp = wiring.group_plans[0].chain_plans[0]
    assert len(cp.source_chain) == 2  # 3-1
    assert len(cp.donor_chain_female) == 2  # native全長(内容1本+延長1本)
    assert cp.source_chain[0] == "Head_L.001"  # 根本は無傷
    assert cp.donor_chain_female == native_names  # 登録本数は容量root込みとは無関係に全長
    # 内容(実ウェイト)は先頭1本だけ——延長(native_names[1:])はweight_expansionに現れない
    assert set(native_names[1:]).isdisjoint(cp.weight_expansion.values())
    assert wiring.chain_fit_events  # 安全域マージが診断ログへ記録される
    assert "safety_margin=1" in wiring.chain_fit_events[0]


def test_plan_hub_wiring_default_safety_margin_two_trims_further():
    """安全域2は安全域1よりさらに1本少なくなる(単調性の確認、内容=実ウェイト
    donor本数について)。dev#1572(2026-08-19朝裁定)のオーナー検算表
    (しっぽ相当、容量root込み6・アバター鎖長6)をそのまま使う: native5本+
    hub root1本=容量6、ソース鎖anchor+5=6本。安全域0→6/1→5/2→4/3→3/4→2/
    5→1の表のうち1と2を検証する。**同日朝の追加裁定**: 安全域1・2いずれも
    `donor_chain_female`自体はnative全5本を登録する(内容の本数だけが
    安全域で変わり、登録総数は容量と無関係に常にnative_chain全長で不変)。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(5)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003", "Head_L.004",
                         "Head_L.005", "Head_L.006"], 0.5, 0.5),  # anchor+5=6本
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring1 = hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved, default_safety_margin=1)
    cp1 = wiring1.group_plans[0].chain_plans[0]
    assert len(cp1.source_chain) == 5  # 6-1
    assert len(cp1.donor_chain_female) == 5  # native全長(内容4本+延長1本)
    assert cp1.donor_chain_female == native_names

    wiring2 = hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved, default_safety_margin=2)
    cp2 = wiring2.group_plans[0].chain_plans[0]
    assert len(cp2.source_chain) == 4  # 6-2、安全域1よりさらに1本少ない
    assert cp2.source_chain[0] == "Head_L.001"  # 根本は無傷
    assert len(cp2.donor_chain_female) == 5  # native全長(内容3本+延長2本)、安全域と無関係に不変
    assert cp2.donor_chain_female == native_names
    # 安全域が増えるほど無ウェイト延長が増える(内容3本のみ実ウェイト)
    assert set(native_names[3:]).isdisjoint(cp2.weight_expansion.values())


def test_plan_hub_wiring_safety_margin_by_chain_overrides_default():
    """GUI「揺れもの詳細」の鎖ごとの上書き相当: safety_margin_by_chainに
    完全一致するキーがあれば、default_safety_marginより優先される。
    容量ちょうど(root込み3=n_ext、`_one_trims_one_tip_bone`と同じ
    セットアップ)で検証——容量に余裕があると安全域1自体が無効化される
    ため、上書きの効果(1->0)を検出できない。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(2)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003"], 0.5, 0.5),  # anchor+2=3本
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    overrides = {("Head_L.001", "Head_L.002", "Head_L.003"): 0}
    wiring = hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved,
        default_safety_margin=1, safety_margin_by_chain=overrides)
    cp = wiring.group_plans[0].chain_plans[0]
    # このチェーンだけ上書きで安全域0 -> 縮退なし(既定1の効果を打ち消す)
    assert len(cp.source_chain) == 3
    assert not wiring.chain_fit_events


def test_plan_hub_wiring_safety_margin_applies_in_free_pool_fallback():
    """native chainが無い(自由プールへフォールバックする)経路でも安全域が
    効くことを確認する(3経路のうち唯一未検証だった経路)。"""
    catalog, hub_slots, reserved, _native_names = _linear_native_chain_environment(0)
    physbones = _make_physbones_json([
        ("Hips", ["tail_01", "tail_02", "tail_03"], 0.5, 0.5),  # anchor+3=4本
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved, default_safety_margin=1)
    cp = wiring.group_plans[0].chain_plans[0]
    assert len(cp.source_chain) == 3  # 4-1
    assert len(cp.donor_chain_female) == 3
    assert all(d.startswith("free") for d in cp.donor_chain_female)
    assert wiring.chain_fit_events


def test_plan_hub_wiring_safety_margin_extreme_margin_fully_merges_to_root_alone():
    """dev#1572(2026-08-19朝オーナー裁定、下限1許可)の中心受入ケース:
    鎖長2(anchor+1)に安全域99を渡すと、容量root込みでも(4+1=5-99は
    大幅に負)反映骨数は下限1に張り付き、**hub root自身1本へ全節が
    全結合**する——`fit_chain_to_length()`の「実効節数1のときだけ
    根本も含めて全結合」規則どおり。

    (a) `source_chain`は単一代表(chain[-1]、つまりHead_L.002)へ縮退、
    (b) `weight_expansion`は元の全節(Head_L.001/Head_L.002)を単一代表へ
    写す(マージ後のウェイト母集団が全節分であることの直接固定)——
    実ウェイトを持つ子孫donor(native/free)は1本も無い。

    **同日朝の追加裁定(余剰donorの先端延長を全donor登録へ訂正)**:
    (旧)「子孫donorは1本も登録されない(`donor_chain_female == ()`)」は
    本WPで訂正された——内容が0本(全結合)でも、`donor_chain_female`は
    native全4本を無ウェイト延長として登録する(登録本数は安全域と無関係に
    常にnative_chain全長、`test_target_len_with_safety_margin_floor_is_
    one_child_or_anchor_only`(純関数レベル)の統合版だが、donor*登録*
    本数はこのWPにより不変固定へ上書きされた)。

    旧裁定(下限2、根本は絶対にマージしない)は容量勘定がroot抜きだった
    旧式に合わせた保守的な下限で、既に置き換え済み。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(4)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002"], 0.5, 0.5),  # anchor+1=2本
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved, default_safety_margin=99)
    cp = wiring.group_plans[0].chain_plans[0]
    assert cp.source_chain == ("Head_L.002",)  # 全節が代表(先端)1本へ全結合
    assert cp.donor_chain_female == native_names  # native全4本が無ウェイト延長として登録される
    assert cp.donor_chain_male == native_names
    # ウェイト母集団は全節分(root自身含む)——両方とも唯一の代表へ写る
    assert cp.weight_expansion == {"Head_L.001": "Head_L.002", "Head_L.002": "Head_L.002"}
    # 延長donor(native全4本)はweight_expansionのどの値にも現れない(完全無ウェイト)
    assert set(native_names).isdisjoint(cp.weight_expansion.values())


def test_plan_hub_wiring_safety_margin_negative_control_root_excluded_capacity_would_differ():
    """負の対照(gate #3): `hub_native_descendant_chain()`の戻り(root抜き)
    をそのまま`donor_capacity`として渡す**旧式**の容量勘定だと、本WPが
    修理した表(耳相当・容量root込み4)にならないことを直接示す。native3本
    (root抜き)を旧式のまま渡すと、安全域1でも即座に反映骨数が3->2へ
    縮む(容量に1本の余裕もない)が、正しい(root込み)容量4を渡せば
    安全域1は無傷のまま(3のまま不変、`test_target_len_with_safety_margin_
    owner_worked_example`と同じ「donor潤沢分が安全域を吸収する」効果)。"""
    n_ext = 3
    native_descendant_count = 3  # root抜き(hub_native_descendant_chain()の戻り本数)
    # 旧式(バグ): 容量をroot抜きのまま渡す
    old_wrong = hub.target_len_with_safety_margin(
        n_ext=n_ext, donor_capacity=native_descendant_count, margin=1)
    assert old_wrong == 2  # 旧式は誤って1本分早く縮退させてしまう
    # 新式(本WP): 容量をroot込み(+1)で渡す
    new_correct = hub.target_len_with_safety_margin(
        n_ext=n_ext, donor_capacity=native_descendant_count + 1, margin=1)
    assert new_correct == 3  # 正しくは無変形のまま(容量に余裕がある)
    assert old_wrong != new_correct  # 容量勘定の訂正が結果を変えたことの直接証明


# =====================================================================
# dev#1572(第2便、issue #1572第2報): 安全域による節数マージの梯子テスト
# (margin=0..5、容量root込み4・ウェイト母集団3(anchor+2))。
# `test_target_len_with_safety_margin_owner_table_ear_capacity_root_
# included_four`(純関数レベル、既存)が反映骨数の数列3,3,2,1,1,1を既に
# 固定しているため、ここでは`plan_hub_wiring()`統合レベルで「各段の
# マージ塊のスパン(ウェイト対応)」を1本の梯子として固定する。
# =====================================================================

def test_plan_hub_wiring_safety_margin_ladder_margin_0_to_5_merge_group_spans():
    """margin=0..5それぞれで、内容(実ウェイト)donor本数・`source_chain`・
    各マージ塊のメンバー(`sway_hub.donor_group_members()`)を固定する。
    容量root込み4(native3本+hub root1本)・ウェイト母集団3
    (Head_L.001=anchor+Head_L.002+Head_L.003)。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(3)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003"], 0.5, 0.5),  # anchor+2=3本
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)

    def _wire(margin):
        wiring = hub.plan_hub_wiring(
            plan, catalog, hub_slots, reserved, default_safety_margin=margin)
        return wiring.group_plans[0].chain_plans[0]

    # margin=0,1: 反映骨数3(no-op、フィット未発動)——source_chainは
    # anchor+2本のまま、全てが自分自身の代表(マージ無し)。
    for margin in (0, 1):
        cp = _wire(margin)
        assert cp.source_chain == ("Head_L.001", "Head_L.002", "Head_L.003")
        assert cp.weight_expansion == {
            "Head_L.001": "Head_L.001", "Head_L.002": "Head_L.002",
            "Head_L.003": "Head_L.003"}
        assert cp.donor_chain_female == native_names  # 登録本数は常に全長(3本)

    # margin=2: 反映骨数2——根本(Head_L.001)は単独、残り2本
    # (Head_L.002,003)が1グループへマージ(代表=Head_L.003)。
    cp2 = _wire(2)
    assert cp2.source_chain == ("Head_L.001", "Head_L.003")
    assert cp2.weight_expansion == {
        "Head_L.001": "Head_L.001", "Head_L.002": "Head_L.003",
        "Head_L.003": "Head_L.003"}
    groups2 = hub.donor_group_members(cp2)
    assert groups2["Head_L.001"] == ("Head_L.001",)
    assert groups2["Head_L.003"] == ("Head_L.002", "Head_L.003")  # 塊の先頭〜末尾
    assert cp2.donor_chain_female == native_names  # 登録本数は不変(内容1本+延長2本)

    # margin=3,4,5: 反映骨数1(下限)——根本も含めた全3本が単一代表
    # (Head_L.003、先端)へ全結合。フロア到達後は margin を増やしても
    # 結果は不変(3,4,5すべて同一)。
    for margin in (3, 4, 5):
        cp = _wire(margin)
        assert cp.source_chain == ("Head_L.003",)
        assert cp.weight_expansion == {
            "Head_L.001": "Head_L.003", "Head_L.002": "Head_L.003",
            "Head_L.003": "Head_L.003"}
        groups = hub.donor_group_members(cp)
        assert groups["Head_L.003"] == ("Head_L.001", "Head_L.002", "Head_L.003")
        assert cp.donor_chain_female == native_names  # 登録本数は不変(内容0本+延長3本、全て無ウェイト)
        assert set(native_names).isdisjoint(cp.weight_expansion.values())


def test_plan_hub_wiring_safety_margin_ladder_full_merge_geometry_spans_true_anchor_to_tip():
    """梯子の末端(margin=3、実効節数1の全結合)を`sway_hub_placement.
    resolve_grouped_chain()`まで通し、hub root配下の延長donorが「真の
    anchor(Head_L.001)からマージ塊の末尾(Head_L.003)tail」までの全
    スパンを基準に直線延長することを確認する(issue #1572第2報の
    geometry回帰の統合版、bpy非依存)。"""
    catalog, hub_slots, reserved, native_names = _linear_native_chain_environment(3)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved, default_safety_margin=3)
    cp = wiring.group_plans[0].chain_plans[0]
    assert cp.source_chain == ("Head_L.003",)  # 全結合発動済み

    avatar_dump = {
        "Head_L.001": {"head": (0.0, 0.0, 0.0), "tail": (0.0, 0.0, 1.0)},
        "Head_L.002": {"head": (0.0, 0.0, 1.0), "tail": (0.0, 0.0, 2.0)},
        "Head_L.003": {"head": (0.0, 0.0, 2.0), "tail": (0.0, 0.0, 3.0)},
    }
    sim = shp.Similarity(
        scale=1.0, avatar_hips_raw=(0.0, 0.0, 0.0), pal_pelvis_world=(0.0, 0.0, 0.0))
    anchor_pt, heads, _tails, _used = shp.resolve_grouped_chain(
        avatar_dump, sim, cp, anchor_name="Head_L.001",
        donor_chain=cp.donor_chain_female)
    # 真のanchor(Head_L.001のhead)——マージ代表(Head_L.003)自身のhead
    # (0,0,2)ではない。
    assert anchor_pt == (0.0, 0.0, 0.0)
    # 延長donor1本目のheadは、真のanchorからマージ塊末尾(Head_L.003)の
    # tail(0,0,3)までの全スパン(長さ3.0)の先——代表自身の局所区間
    # (長さ1.0)を基準にした(0,0,3)+(0,0,1)ではない。
    assert heads[0] == (0.0, 0.0, 3.0)


def test_plan_hub_wiring_safety_margin_ladder_margin3_and_margin4_are_byte_identical():
    """オーナー追加観測(2026-08-19、flatapron左耳の実機比較): safety_
    margin=3と=4で壊れ方(ウェイト消失・01_l位置異常・揺れない)が全く
    同じだった——式では両方とも反映骨数1(全結合)に落ちる
    (`max(1,min(4-3,3))=max(1,min(4-4,3))=1`)ため、「全結合=内容1本の
    経路そのものが壊れている」仮説の直接証拠。本テストはmargin=3と
    margin=4が(容量root込み4・ウェイト母集団3の条件で)`source_chain`/
    `weight_expansion`/`donor_chain_female`のすべてにおいて完全に同一の
    計画を生むことを固定する(オーナー観測どおり「境界に達した後は margin
    を増やしても壊れ方が変わらない」の直接確認、gate #4)。"""
    catalog, hub_slots, reserved, _native_names = _linear_native_chain_environment(3)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)

    cp3 = hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved, default_safety_margin=3,
    ).group_plans[0].chain_plans[0]
    cp4 = hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved, default_safety_margin=4,
    ).group_plans[0].chain_plans[0]

    assert cp3.source_chain == cp4.source_chain == ("Head_L.003",)
    assert cp3.weight_expansion == cp4.weight_expansion
    assert cp3.donor_chain_female == cp4.donor_chain_female
    assert cp3.donor_chain_male == cp4.donor_chain_male


def test_plan_hub_wiring_safety_margin_ladder_margin2_geometry_was_already_correct():
    """切り分けの鍵(オーナー指示): margin=2(反映骨数2、**部分**マージ
    ——根本Head_L.001は単独のまま、Head_L.002+003だけがマージ)は
    `resolve_grouped_chain()`の`src_idx>=1`側(既存実装、本WPで変更して
    いない)を通るため、本WPの修理前から幾何は正しい。margin=3(反映骨数
    1、根本も含めた**全結合**)とは異なるコード経路であることを、
    `anchor_pt`が代表(Head_L.003)自身のheadと一致してしまわない
    (=壊れていない)ことで直接示し、境界(2と3の間)が「部分マージ/全結合」
    の切り替わりそのものであることを固定する。"""
    catalog, hub_slots, reserved, _native_names = _linear_native_chain_environment(3)
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    wiring = hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved, default_safety_margin=2)
    cp = wiring.group_plans[0].chain_plans[0]
    assert cp.source_chain == ("Head_L.001", "Head_L.003")  # 部分マージ(根本は単独のまま)

    avatar_dump = {
        "Head_L.001": {"head": (0.0, 0.0, 0.0), "tail": (0.0, 0.0, 1.0)},
        "Head_L.002": {"head": (0.0, 0.0, 1.0), "tail": (0.0, 0.0, 2.0)},
        "Head_L.003": {"head": (0.0, 0.0, 2.0), "tail": (0.0, 0.0, 3.0)},
    }
    sim = shp.Similarity(
        scale=1.0, avatar_hips_raw=(0.0, 0.0, 0.0), pal_pelvis_world=(0.0, 0.0, 0.0))
    anchor_pt, heads, tails, _used = shp.resolve_grouped_chain(
        avatar_dump, sim, cp, anchor_name="Head_L.001",
        donor_chain=cp.donor_chain_female)
    # 根本は単独グループのまま(anchor_pt=Head_L.001自身のhead、hub root
    # 自身が担う——これは全結合ではないので修理の前後で不変)。
    assert anchor_pt == (0.0, 0.0, 0.0)
    # donor_chain[0](=source_chain[1]="Head_L.003"の代表グループ
    # {Head_L.002,Head_L.003}、内容1本)は塊の先頭head(1.0)〜末尾tail(3.0)。
    assert heads[0] == (0.0, 0.0, 1.0) and tails[0] == (0.0, 0.0, 3.0)
    # donor_chain[1:](延長、native全3本のうち残り2本)は無ウェイトの
    # 直線継続——空隙なく内容セグメントのtailから始まる。
    assert heads[1] == tails[0]


def test_plan_hub_wiring_safety_margin_ladder_negative_control_head_l_override_does_not_affect_head_r():
    """負の対照: `safety_margin_by_chain`でHead_L鎖だけに安全域を上書き
    しても、別チェーン(Head_R)は既定値のまま(default_safety_margin)で
    影響を受けない——GUI「揺れもの詳細」の鎖ごと上書きが他鎖へ漏れない
    ことの直接確認。"""
    catalog, hub_slots, reserved = _two_slot_hub_environment()
    physbones = _make_physbones_json([
        ("Head_L.001", ["Head_L.002", "Head_L.003"], 0.5, 0.5),
        ("Head_R.001", ["Head_R.002", "Head_R.003"], 0.5, 0.5),
    ])
    plan = sway_allocator.allocate(physbones_json=physbones)
    overrides = {("Head_L.001", "Head_L.002", "Head_L.003"): 3}
    wiring = hub.plan_hub_wiring(
        plan, catalog, hub_slots, reserved,
        default_safety_margin=0, safety_margin_by_chain=overrides)

    cps = [cp for gp in wiring.group_plans for cp in gp.chain_plans]
    left = next(cp for cp in cps if "Head_L.001" in cp.weight_expansion)
    right = next(cp for cp in cps if "Head_R.001" in cp.weight_expansion)

    # Head_L: 上書き安全域3(自由プール経路、容量無制限扱いのためtarget_len
    # =n_ext-margin=3-3=0->下限1)で全結合。
    assert left.source_chain == ("Head_L.003",)
    # Head_R: 上書きが無いのでdefault_safety_margin=0のまま無変形。
    assert right.source_chain == ("Head_R.001", "Head_R.002", "Head_R.003")
    assert right.weight_expansion == {
        "Head_R.001": "Head_R.001", "Head_R.002": "Head_R.002",
        "Head_R.003": "Head_R.003"}
