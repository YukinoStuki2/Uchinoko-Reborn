# -*- coding: utf-8 -*-
"""dev#277第1弾④(頭装備切り替え)の単体試験: live_template.py側の配線。

設計正本: work\\rd_1198_wpb\\PROPOSAL.md §8。ラボ憲章④(既定値=未実装状態と
完全同一)の受入の柱を、`_project_stub_sk_rels`/`_project_skip_rels`の
純粋関数レベルで固定する(pak変換・実機は一切不要)。

対象:
  1. live_template._project_skip_rels (新規): 選択されたHeadEquipのrelを
     スタブ生成対象からもコピー対象からも除外する集合を返す。
  2. live_template._project_stub_sk_rels の headequip_show 拡張:
     既定(None/空)ではWP-B3までと完全に同じ出力(負の対照)。
  3. live_template._live_template_fingerprint: headequip_showがフィンガー
     プリントへ反映されること(既定=[]で安定)。

実行: python -m pytest pipeline\\py\\test_wp_f4_headequip_toggle.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_template  # noqa: E402

_FAKE_PROJECT_RELS = [
    "Player/Head/Head001/SK_Player_Male_Head001.uasset",
    "Player/Head/Head001/SK_Player_Male_Head001.uexp",
    "Player/Hair/Hair001/SK_Player_Hair001.uasset",
    "Player/Hair/Hair001/SK_Player_Hair001.uexp",
    "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset",
    "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uexp",
    "Player/HeadEquip/HeadEquip002/SK_HeadEquip002.uasset",
    "Player/HeadEquip/HeadEquip002/SK_HeadEquip002.uexp",
    "Player/ModelMaterials/MainShader/M_VP_m00.uasset",  # SK_を含まない=元から対象外
]


# ============================================================================
# 1. _project_skip_rels(新規)
# ============================================================================

def test_project_skip_rels_default_empty():
    """受入の柱(④): headequip_show未設定なら必ず空集合(=何もスキップ
    しない=全HeadEquipが従来どおりスタブ生成される)。"""
    assert live_template._project_skip_rels(_FAKE_PROJECT_RELS) == set()
    assert live_template._project_skip_rels(_FAKE_PROJECT_RELS, None) == set()
    assert live_template._project_skip_rels(_FAKE_PROJECT_RELS, []) == set()


def test_project_skip_rels_negative_control_one_selected():
    """負の対照: 1件ONにすると、そのコードのrel(uasset+uexp)だけが
    skip対象になり、他のHeadEquip/Head/Hair/非SK資産は含まれない。"""
    out = live_template._project_skip_rels(_FAKE_PROJECT_RELS, ["HeadEquip001"])
    assert out == {
        "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset",
        "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uexp",
    }


# ============================================================================
# 2. _project_stub_sk_rels の headequip_show 拡張
# ============================================================================

def test_project_stub_sk_rels_default_matches_headequip_baseline():
    """受入の柱(④、headequip_show軸のみ): headequip_show省略時は常に
    同じ出力になること(HeadEquip全件維持は不変)。

    dev#1258(WP-E、2026-08-09)でHead/Hairの既定は「スタブ生成対象に
    含まれる」側(HeadEquipと同じ扱い)へ反転した(work\\rd_1258\\
    PROPOSAL.md)。この試験の主眼はheadequip_show軸(このファイルの
    スコープ)なので、Head/Hair軸の詳細な受入は
    test_wp_b3_head_hair_stub.py(dev#1258 WP-E版)に譲り、ここでは
    「headequip_showを変えてもHead/Hairの扱いは変わらない」ことだけ
    確認する(dt_flag_head_hideは既定Falseのまま=このWPの対象外軸)。"""
    out_default = live_template._project_stub_sk_rels(_FAKE_PROJECT_RELS)
    out_explicit_none = live_template._project_stub_sk_rels(_FAKE_PROJECT_RELS, None)
    out_explicit_empty = live_template._project_stub_sk_rels(_FAKE_PROJECT_RELS, [])
    assert out_default == out_explicit_none == out_explicit_empty
    assert "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset" in out_default
    assert "Player/HeadEquip/HeadEquip002/SK_HeadEquip002.uasset" in out_default
    # dev#1258新既定: Head/Hairはスタブ生成対象に含まれる(HeadEquipと同じ)。
    assert "Player/Head/Head001/SK_Player_Male_Head001.uasset" in out_default
    assert "Player/Hair/Hair001/SK_Player_Hair001.uasset" in out_default


def test_project_stub_sk_rels_negative_control_selected_headequip_excluded():
    """負の対照: 1件ONにすると、そのHeadEquipだけスタブ生成対象から
    消え、他のHeadEquipは引き続き生成される(=表示されない)こと。"""
    out = live_template._project_stub_sk_rels(_FAKE_PROJECT_RELS, ["HeadEquip001"])
    assert "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset" not in out
    assert "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uexp" not in out
    assert "Player/HeadEquip/HeadEquip002/SK_HeadEquip002.uasset" in out
    assert "Player/HeadEquip/HeadEquip002/SK_HeadEquip002.uexp" in out


def test_project_stub_sk_rels_and_skip_rels_are_disjoint_and_cover_headequip():
    """stub対象とskip対象は排他であり、両者の和集合が元のHeadEquip全件と
    一致すること(assemble側のcopyループが二重に扱ったり漏らしたりしない
    ことの構造的な保証)。"""
    show = ["HeadEquip001"]
    stub = set(live_template._project_stub_sk_rels(_FAKE_PROJECT_RELS, show))
    skip = live_template._project_skip_rels(_FAKE_PROJECT_RELS, show)
    assert stub & skip == set()
    headequip_all = {r for r in _FAKE_PROJECT_RELS if "/HeadEquip/" in r}
    assert (stub | skip) & headequip_all == headequip_all


# ============================================================================
# 3. _live_template_fingerprint: headequip_show の反映
# ============================================================================

def _fake_pak_and_manifest():
    """_live_template_fingerprint()はos.path.getmtime/getsize(pak)と
    manifest["project"/"vanilla"]の存在だけを見るため、実物のPalworld pak
    は不要——このテストファイル自身をpak代わりのスタット対象として使う
    (中身は読まれない)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    fake_pak = os.path.abspath(__file__)
    manifest = {"vanilla": [], "project": []}
    return fake_pak, manifest


def test_fingerprint_headequip_show_default_is_empty_list():
    """受入の柱(④): job未設定/空ならheadequip_showキーは常に空リスト
    (equipment_filterと同じ流儀。フィンガープリントの"形"は増えるが、
    値は既定で安定=無条件で1回だけキャッシュキーが変わり、以後は安定)。"""
    fake_pak, manifest = _fake_pak_and_manifest()
    fp_no_job = live_template._live_template_fingerprint(fake_pak, manifest, {})
    fp_empty = live_template._live_template_fingerprint(
        fake_pak, manifest, {"headequip_show": []})
    assert fp_no_job["headequip_show"] == []
    assert fp_empty["headequip_show"] == []
    assert fp_no_job == fp_empty


def test_fingerprint_headequip_show_negative_control_changes_key():
    """負の対照: headequip_showを設定すると、フィンガープリントの当該
    キーが変わり(=キャッシュが別物として扱われ)、他のキーは不変。"""
    fake_pak, manifest = _fake_pak_and_manifest()
    fp_default = live_template._live_template_fingerprint(fake_pak, manifest, {})
    fp_selected = live_template._live_template_fingerprint(
        fake_pak, manifest, {"headequip_show": ["HeadEquip001"]})
    assert fp_default["headequip_show"] == []
    assert fp_selected["headequip_show"] == ["HeadEquip001"]
    assert fp_default != fp_selected
    other_keys = set(fp_default) - {"headequip_show"}
    for k in other_keys:
        assert fp_default[k] == fp_selected[k], f"unrelated key changed: {k}"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
