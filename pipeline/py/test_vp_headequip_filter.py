# -*- coding: utf-8 -*-
"""dev#277第1弾④(頭装備切り替え)の単体試験: vp_headequip_filter.py。

設計正本: work\\rd_1198_wpb\\PROPOSAL.md §8。
実測値(2026-08-08、本WPで確認): noue_template_manifest.jsonのHeadEquip
128エントリ(uasset+uexp)は64コードへまとまる(=64論理アセット、
WP-B3のtest_wp_b3_head_hair_stub.pyが固定する数値と一致)。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_headequip_filter as hef  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(HERE, "noue_template_manifest.json")


# ============================================================================
# headequip_code
# ============================================================================

def test_headequip_code_basic():
    assert hef.headequip_code("Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset") == "HeadEquip001"


def test_headequip_code_variant_suffix():
    assert hef.headequip_code("SK_HeadEquip001_purple.uexp") == "HeadEquip001_purple"
    assert hef.headequip_code("SK_HeadEquip019_v01.uasset") == "HeadEquip019_v01"


def test_headequip_code_normalizes_backslash():
    assert hef.headequip_code("Player\\HeadEquip\\HeadEquip001\\SK_HeadEquip001.uasset") == "HeadEquip001"


def test_headequip_code_none_for_head():
    """負の対照: Head(頭本体)はHeadEquip(帽子)と紛れて拾われない。"""
    assert hef.headequip_code("Player/Head/Head001/SK_Player_Male_Head001.uasset") is None


def test_headequip_code_none_for_outfit():
    """負の対照: Outfit(装備限定の対象)とは別の名前空間であること。"""
    assert hef.headequip_code("SK_Player_Male_Outfit_Bronze001.uasset") is None


def test_headequip_code_none_for_non_sk_asset():
    assert hef.headequip_code("Player/ModelMaterials/MainShader/M_VP_m00.uasset") is None


# ============================================================================
# headequip_rels_from_manifest / known_headequip_codes
# ============================================================================

_FAKE_MANIFEST = {
    "project": [
        "Player/Head/Head001/SK_Player_Male_Head001.uasset",
        "Player/Head/Head001/SK_Player_Male_Head001.uexp",
        "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset",
        "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uexp",
        "Player/HeadEquip/HeadEquip002/SK_HeadEquip002.uasset",
        "Player/HeadEquip/HeadEquip002/SK_HeadEquip002.uexp",
        "Player/ModelMaterials/MainShader/M_VP_m00.uasset",
    ],
    "vanilla": [],
}


def test_headequip_rels_from_manifest_only_headequip():
    rels = hef.headequip_rels_from_manifest(_FAKE_MANIFEST)
    assert len(rels) == 4
    assert all("/HeadEquip/" in r for r in rels)


def test_known_headequip_codes_from_fake_manifest():
    rels = hef.headequip_rels_from_manifest(_FAKE_MANIFEST)
    codes = hef.known_headequip_codes(rels)
    assert codes == {"HeadEquip001", "HeadEquip002"}


def test_known_headequip_codes_real_manifest_count():
    """実データでの受入条件(§8.2実測): 64コード・128rel。"""
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)
    rels = hef.headequip_rels_from_manifest(manifest)
    codes = hef.known_headequip_codes(rels)
    assert len(rels) == 128
    assert len(codes) == 64


# ============================================================================
# normalize_headequip_selection
# ============================================================================

def test_normalize_none_input():
    assert hef.normalize_headequip_selection(None) is None


def test_normalize_empty_list():
    assert hef.normalize_headequip_selection([]) is None


def test_normalize_filters_falsy_entries():
    assert hef.normalize_headequip_selection(["HeadEquip001", "", None]) == {"HeadEquip001"}


def test_normalize_all_falsy_returns_none():
    assert hef.normalize_headequip_selection(["", None]) is None


# ============================================================================
# shown_headequip_rels(受入の柱: 既定=空集合、非既定=負の対照)
# ============================================================================

_FAKE_HEADEQUIP_RELS = [
    "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset",
    "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uexp",
    "Player/HeadEquip/HeadEquip002/SK_HeadEquip002.uasset",
    "Player/HeadEquip/HeadEquip002/SK_HeadEquip002.uexp",
]


def test_shown_headequip_rels_default_is_empty_none():
    """受入の柱(ラボ憲章④): headequip_show未設定(None)は必ず空集合。"""
    assert hef.shown_headequip_rels(_FAKE_HEADEQUIP_RELS, None) == set()


def test_shown_headequip_rels_default_is_empty_list():
    """受入の柱(ラボ憲章④): headequip_show=空リストも必ず空集合。"""
    assert hef.shown_headequip_rels(_FAKE_HEADEQUIP_RELS, []) == set()


def test_shown_headequip_rels_negative_control_one_selected():
    """負の対照: 1コード選択したとき、そのコードのrel(uasset+uexp)だけが
    返り、他コードは含まれないこと。"""
    out = hef.shown_headequip_rels(_FAKE_HEADEQUIP_RELS, ["HeadEquip001"])
    assert out == {
        "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset",
        "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uexp",
    }


def test_shown_headequip_rels_unknown_code_yields_nothing():
    out = hef.shown_headequip_rels(_FAKE_HEADEQUIP_RELS, ["NoSuchCode"])
    assert out == set()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
