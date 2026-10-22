# -*- coding: utf-8 -*-
"""dev#1198 WP-B3 -> dev#1258 WP-E(2026-08-09)の単体試験:
Head/Hair系スタブ生成の既定挙動反転(常時空スタブへ復帰)+ラボ機能
「差替え中装備のみ頭OFF」(dt_flag_head_hide)によるv2.6.0互換切替。

設計正本: work\\rd_1258\\PROPOSAL.md(特に§0結論・§4.1実装点・§4.3
ラボ憲章④整合・§4.4受入ゲート)。

**背景(このファイルが再定義する前提)**: WP-B3(dev#1198、コミット
dece1e5)はHead/Hairの常時空スタブ生成を無条件廃止し、可視性を注入装備行の
bIsFullBodyEquipmentフラグに担わせる方式(以下「DTフラグ方式」)へ移行
した。しかしこの方式は、未装備フォールバック描画(丸腰・初期装備状態)が
DTフラグを見ないため、バニラHead/Hairの重複を引き起こすことが確定した
(dev#1258、オーナー実機確認)。オーナー裁定(2026-08-09)「開始10分の
全員の重複より、稀な衣装の首なしの方が軽い」により、**既定を再び常時空
スタブ方式へ戻し**(WP-B3以前の挙動の復活)、DTフラグ方式はラボ機能
「差替え中装備のみ頭OFF」(job["dt_flag_head_hide"]=True)としてのみ
選べるようにした。

このファイルの「新既定」= dt_flag_head_hide未指定/False(WP-Eが定める
新しい既定=スタブ方式)。「ラボON」= dt_flag_head_hide=True(v2.6.0までの
既定=DTフラグ方式)。

対象:
  1. live_template._is_head_or_hair_stub_rel / _project_stub_sk_rels
     (トグル対応後の判定。HeadEquip/Outfitは無改変で通す純粋関数)
  2. noue_template_manifest.json の "project" リストそのもの
     (Head/Hair 178件が新既定で常時収録されていること=WP-B3以前の状態への復元。
     HeadEquip 128件・Outfit系が不変であること)
  3. preflight_pak._manifest_sk_counts / _filter_inv_for_g10_coverage
     (トグル対応後の判定。新既定はHeadEquipと同じ扱い、ラボONはWP-B3当時と同じ扱い)

pak変換・実機は一切不要(stdlib+pytestのみで完結)。
実行: python -m pytest pipeline\\py\\test_wp_b3_head_hair_stub.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_template  # noqa: E402
import preflight_pak  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(HERE, "noue_template_manifest.json")


# ============================================================================
# 1. live_template._is_head_or_hair_stub_rel(トグル対応)
# ============================================================================

def test_is_head_or_hair_stub_rel_default_false_for_head():
    """新既定(dt_flag_head_hide省略=False): Head/Hairはスタブ生成対象に
    「含まれる」側(=この関数はFalseを返す=除外しない)。"""
    assert not live_template._is_head_or_hair_stub_rel(
        "Player/Head/Head001/SK_Player_Male_Head001.uasset")


def test_is_head_or_hair_stub_rel_default_false_for_hair():
    assert not live_template._is_head_or_hair_stub_rel(
        "Player/Hair/Hair001/SK_Player_Hair001.uexp")


def test_is_head_or_hair_stub_rel_explicit_false_matches_default():
    """④既定値不変: dt_flag_head_hide=False明示指定とキー省略(既定引数)が
    完全に同じ結果になること。"""
    rel = "Player/Head/Head001/SK_Player_Male_Head001.uasset"
    assert (live_template._is_head_or_hair_stub_rel(rel)
            == live_template._is_head_or_hair_stub_rel(rel, dt_flag_head_hide=False))


def test_is_head_or_hair_stub_rel_lab_on_true_for_head():
    """ラボ機能ON(dt_flag_head_hide=True): v2.6.0までと同じくHead/Hairを
    スタブ生成対象から除外する(=DTフラグ方式に戻す)。"""
    assert live_template._is_head_or_hair_stub_rel(
        "Player/Head/Head001/SK_Player_Male_Head001.uasset", dt_flag_head_hide=True)


def test_is_head_or_hair_stub_rel_lab_on_true_for_hair():
    assert live_template._is_head_or_hair_stub_rel(
        "Player/Hair/Hair001/SK_Player_Hair001.uexp", dt_flag_head_hide=True)


def test_is_head_or_hair_stub_rel_normalizes_backslash():
    """Windows形式の区切り(バックスラッシュ)でも判定できること(ラボON側で確認)。"""
    assert live_template._is_head_or_hair_stub_rel(
        "Player\\Head\\Head001\\SK_Player_Male_Head001.uasset", dt_flag_head_hide=True)


def test_is_head_or_hair_stub_rel_false_for_headequip():
    """負の対照(最重要): HeadEquip(帽子)はdt_flag_head_hideの値に関わらず
    常にFalse(=Head/Hairと紛れて除外されない)ことを保証する。"""
    assert not live_template._is_head_or_hair_stub_rel(
        "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset")
    assert not live_template._is_head_or_hair_stub_rel(
        "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset", dt_flag_head_hide=True)


def test_is_head_or_hair_stub_rel_false_for_outfit():
    assert not live_template._is_head_or_hair_stub_rel(
        "Player/Outfit/SK_Player_Male_Outfit_Hunter001/SK_Player_Male_Outfit_Hunter001.uasset")


def test_is_head_or_hair_stub_rel_false_for_unrelated_project_asset():
    assert not live_template._is_head_or_hair_stub_rel(
        "Player/ModelMaterials/MainShader/M_VP_m00.uasset")


# ============================================================================
# 2. live_template._project_stub_sk_rels(トグル対応)
# ============================================================================

_FAKE_PROJECT_RELS = [
    "Player/Head/Head001/SK_Player_Male_Head001.uasset",
    "Player/Head/Head001/SK_Player_Male_Head001.uexp",
    "Player/Hair/Hair001/SK_Player_Hair001.uasset",
    "Player/Hair/Hair001/SK_Player_Hair001.uexp",
    "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset",
    "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uexp",
    "Player/ModelMaterials/MainShader/M_VP_m00.uasset",  # SK_を含まない=元から対象外
]


def test_project_stub_sk_rels_default_includes_head_and_hair():
    """新既定(dt_flag_head_hide省略): Head/HairもHeadEquipと同じくスタブ
    生成対象に含まれること(WP-B3以前の挙動への復帰)。"""
    out = live_template._project_stub_sk_rels(_FAKE_PROJECT_RELS)
    assert "Player/Head/Head001/SK_Player_Male_Head001.uasset" in out
    assert "Player/Hair/Hair001/SK_Player_Hair001.uasset" in out
    assert "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset" in out


def test_project_stub_sk_rels_default_matches_keyword_false():
    """④既定値不変: 引数省略とdt_flag_head_hide=False明示が同じ結果になること。"""
    assert (live_template._project_stub_sk_rels(_FAKE_PROJECT_RELS)
            == live_template._project_stub_sk_rels(_FAKE_PROJECT_RELS, dt_flag_head_hide=False))


def test_project_stub_sk_rels_lab_on_excludes_head_and_hair():
    """ラボ機能ON: Head/Hairはスタブ生成対象から除外される(v2.6.0までと同じ)。"""
    out = live_template._project_stub_sk_rels(_FAKE_PROJECT_RELS, dt_flag_head_hide=True)
    assert not any(live_template._is_head_or_hair_stub_rel(r, True) for r in out)
    assert "Player/Head/Head001/SK_Player_Male_Head001.uasset" not in out
    assert "Player/Hair/Hair001/SK_Player_Hair001.uasset" not in out


def test_project_stub_sk_rels_keeps_headequip_both_modes():
    """負の対照: HeadEquipはdt_flag_head_hideの値に関わらずスタブ生成対象に
    残ること(トグルの影響範囲がHead/Hairだけであることの確認)。"""
    for flag in (False, True):
        out = live_template._project_stub_sk_rels(_FAKE_PROJECT_RELS, dt_flag_head_hide=flag)
        assert "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset" in out
        assert "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uexp" in out


def test_project_stub_sk_rels_ignores_non_sk_assets():
    out = live_template._project_stub_sk_rels(_FAKE_PROJECT_RELS)
    assert "Player/ModelMaterials/MainShader/M_VP_m00.uasset" not in out


# ============================================================================
# 3. noue_template_manifest.json 本体(実データ、pakへ実際に書き出される一覧)
# ============================================================================

def _load_manifest_project():
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)["project"]


def test_manifest_project_has_178_head_hair_sk_stub_entries():
    """受入条件(dev#1258 WP-E、④既定値不変の裏付け): 生成pak相当の
    エントリ一覧にHead/Hair 178件が復元されていること(dece1e5で削除された
    work\\rd_1258\\head_hair_stub_rels_removed.jsonの全件)。"""
    project = _load_manifest_project()

    def norm(r):
        return r.replace("\\", "/")
    head_hair = [r for r in project
                 if norm(r).startswith("Player/Head/") or norm(r).startswith("Player/Hair/")]
    assert len(head_hair) == 178, (
        f"Head/Hairエントリ数が復元済みの178件と一致しない: {len(head_hair)}")
    # 全件SK_始まりの.uasset/.uexpであること(異物混入が無いこと)
    assert all(os.path.basename(norm(r)).startswith("SK_") for r in head_hair)


def test_manifest_project_head_hair_matches_removed_list():
    """負の対照: 復元された178件が、dece1e5で削除されたリスト
    (work\\rd_1258\\head_hair_stub_rels_removed.json)と1件残らず一致すること
    (取りこぼし・余剰混入の検出)。"""
    project = _load_manifest_project()

    def norm(r):
        return r.replace("\\", "/")
    head_hair = {norm(r) for r in project
                 if norm(r).startswith("Player/Head/") or norm(r).startswith("Player/Hair/")}
    removed_list_path = os.path.join(
        HERE, "..", "..", "work", "rd_1258", "head_hair_stub_rels_removed.json")
    removed_list_path = os.path.normpath(removed_list_path)
    if not os.path.exists(removed_list_path):
        # devワークスペース外(配布物等)で実行された場合は静かにスキップ
        # (このファイル自体は本WPの調査成果物であり出荷物ではないため)。
        return
    with open(removed_list_path, encoding="utf-8") as f:
        expected = {norm(r) for r in json.load(f)}
    assert head_hair == expected


def test_manifest_project_headequip_stub_count_unchanged():
    """負の対照: HeadEquipスタブが不変であること(64論理アセット×
    uasset/uexp=128ファイル、WP着手前の実測値に固定)。"""
    project = _load_manifest_project()

    def norm(r):
        return r.replace("\\", "/")
    headequip = [r for r in project if norm(r).startswith("Player/HeadEquip/")]
    assert len(headequip) == 128, (
        f"HeadEquipエントリ数が変化した(不変であるべき): {len(headequip)}")
    assert all(os.path.basename(norm(r)).startswith("SK_") for r in headequip)


def test_manifest_project_outfit_and_other_assets_unaffected():
    """Head/Hair以外(Outfit系SK・M_VP_*等の恒久資産)の件数はこのWPで
    変化しないこと(スコープ外への波及が無いことの確認)。"""
    project = _load_manifest_project()

    def norm(r):
        return r.replace("\\", "/")
    outfit = [r for r in project if norm(r).startswith("Player/Outfit/")]
    non_sk = [r for r in project if "/SK_" not in norm(r)]
    assert outfit == []
    # WP着手前(WP-B3後)の実測値145件からHead/Hair 178件が復元されて323件に
    # なった。非SK資産(M_VP_*/t00/t01/anchor等)自体の件数はWP-B3以前から
    # 不変(145-128=17件)。
    assert len(non_sk) == 145 - 128, (
        f"非SK資産(M_VP_*/t00/t01/anchor等)の件数が変化した: {len(non_sk)}")


def test_manifest_vanilla_list_unaffected():
    """vanilla区分(バニラpakからのその場抽出対象)にHead/Hairの言及が
    無いこと(元々無かったことの確認、退行チェック)。"""
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)
    vanilla = manifest["vanilla"]

    def norm(r):
        return r.replace("\\", "/")
    hh = [r for r in vanilla if "/Head/" in norm(r) or "/Hair/" in norm(r)]
    assert hh == []


# ============================================================================
# 4. preflight_pak._manifest_sk_counts(トグル対応、G4のmanifest由来フォールバック)
# ============================================================================

def test_manifest_sk_counts_default_head_and_hair_are_nonzero():
    """新既定(dt_flag_head_hide省略): manifestにHead/Hairが常時含まれる
    ようになったため、`_manifest_sk_counts()`はHeadEquipと同じく非ゼロを
    返す(=WP-B3以前の状態への復帰)。"""
    counts = preflight_pak._manifest_sk_counts()
    assert counts is not None
    outfit, head, hair, headequip = counts
    assert head == 52, f"Head uasset数(26論理アセット×男女2)が変化した: {head}"
    assert hair == 37, f"Hair uasset数(37論理アセット)が変化した: {hair}"
    assert headequip == 64, f"HeadEquip論理アセット数が変化した(不変であるべき): {headequip}"
    assert outfit > 0


def test_manifest_sk_counts_lab_on_head_and_hair_are_zero():
    """ラボ機能ON(dt_flag_head_hide=True): v2.6.0までと同じくHead/Hairは
    出力pakから完全に除外されるため、期待値も0へ落ちること。"""
    counts = preflight_pak._manifest_sk_counts(dt_flag_head_hide=True)
    assert counts is not None
    outfit, head, hair, headequip = counts
    assert head == 0
    assert hair == 0
    assert headequip == 64, f"HeadEquip論理アセット数が変化した(不変であるべき): {headequip}"
    assert outfit > 0


# ============================================================================
# 5. preflight_pak._filter_inv_for_g10_coverage(トグル対応)
# ============================================================================

_FAKE_INV = {
    "outfit": ["Player/Outfit/x.uasset"],
    "head": ["Player/Head/Head001/SK_Player_Male_Head001.uasset"],
    "hair": ["Player/Hair/Hair001/SK_Player_Hair001.uasset"],
    "headequip": ["Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset"],
}


def test_filter_inv_for_g10_coverage_default_keeps_head_and_hair():
    """新既定(dt_flag_head_hide省略): Head/HairはHeadEquipと同じく常時
    スタブ生成され出力pakに存在するため、G10のカバレッジ検査対象に残る
    (=除外しない)。"""
    out = preflight_pak._filter_inv_for_g10_coverage(_FAKE_INV)
    assert "head" in out
    assert "hair" in out
    assert out["head"] == _FAKE_INV["head"]
    assert out["hair"] == _FAKE_INV["hair"]


def test_filter_inv_for_g10_coverage_lab_on_removes_head_and_hair():
    """ラボ機能ON(dt_flag_head_hide=True): v2.6.0までと同じくHead/Hairは
    出力pakに存在しないため、G10のカバレッジ検査対象から除外する
    (WP-B3当時の挙動そのもの)。"""
    out = preflight_pak._filter_inv_for_g10_coverage(_FAKE_INV, dt_flag_head_hide=True)
    assert "head" not in out
    assert "hair" not in out


def test_filter_inv_for_g10_coverage_keeps_headequip_and_outfit_both_modes():
    """負の対照: HeadEquip/Outfitはdt_flag_head_hideの値に関わらず引き続き
    G10のカバレッジ検査対象に残ること。"""
    for flag in (False, True):
        out = preflight_pak._filter_inv_for_g10_coverage(_FAKE_INV, dt_flag_head_hide=flag)
        assert out["headequip"] == _FAKE_INV["headequip"]
        assert out["outfit"] == _FAKE_INV["outfit"]


def test_filter_inv_for_g10_coverage_does_not_mutate_input():
    before = json.dumps(_FAKE_INV, sort_keys=True)
    preflight_pak._filter_inv_for_g10_coverage(_FAKE_INV)
    preflight_pak._filter_inv_for_g10_coverage(_FAKE_INV, dt_flag_head_hide=True)
    after = json.dumps(_FAKE_INV, sort_keys=True)
    assert before == after


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
