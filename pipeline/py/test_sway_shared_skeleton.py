# -*- coding: utf-8 -*-
"""test_sway_shared_skeleton.py -- sway_shared_skeleton.pyの単体テスト
(dev#1508 W2a-2、汎用ハブ配線)。実際のPalworld pak/Blenderには一切依存せず、
`read_names()`/RefSkeletonスキャナが期待するバイナリ構造を最小合成データで
再現する(vp_core.read_names()の実装をそのまま踏襲した自作ビルダー)。
"""
import json
import os
import struct
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_shared_skeleton as sss  # noqa: E402

# リポジトリルート配下、work\は.gitignore対象(実データ・研究成果物)。開発機には
# 存在するがクリーン環境には無いことがあるため、無ければskip(既存慣習を踏襲)。
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_VANILLA_SK_DIR = os.path.join(
    _REPO_ROOT, "work", "rd_19_r1_vanilla", "extracted", "Pal", "Content", "Pal",
    "Model", "Character", "Skeleton", "Human")
_VANILLA_UASSET = os.path.join(_VANILLA_SK_DIR, "SK_PalHuman_Skeleton.uasset")
_VANILLA_UEXP = os.path.join(_VANILLA_SK_DIR, "SK_PalHuman_Skeleton.uexp")
_DONOR_CATALOG_CACHE = os.path.join(
    _REPO_ROOT, "work", "rd_19_donorcatalog", "sk_palhuman_full.json")


# =====================================================================
# 合成データビルダー(vp_core.read_names()が期待する最小uasset構造)
# =====================================================================

def _build_uasset_bytes(names):
    """vp_core.read_names()が読める最小のuassetバイト列を組み立てる。"""
    out = bytearray()
    out += struct.pack("<I", 0x9E2A83C1)          # magic
    out += struct.pack("<i", -7)                    # legacy_ver (!= -4, > -8)
    out += struct.pack("<i", 0)                     # LegacyUE3Version (filler)
    out += struct.pack("<i", 0)                     # FileVersionUE4 (filler)
    out += struct.pack("<i", 0)                     # FileVersionLicenseeUE (filler)
    out += struct.pack("<i", 0)                     # cv_count = 0
    out += struct.pack("<i", 0)                     # TotalHeaderSize (filler)
    out += struct.pack("<i", 0)                     # folder name slen = 0 (empty)
    out += struct.pack("<i", 0)                     # PackageFlags (filler)
    name_count_pos = len(out)
    out += struct.pack("<i", len(names))             # name_count
    name_offset_pos = len(out)
    name_offset = name_offset_pos + 4
    out += struct.pack("<i", name_offset)            # name_offset
    assert len(out) == name_offset
    for nm in names:
        raw = nm.encode("ascii") + b"\x00"
        out += struct.pack("<i", len(raw))
        out += raw
        out += struct.pack("<i", 0)  # precalc hash filler
    return bytes(out)


def _build_refskeleton_uexp_bytes(bone_defs, pad_before=37, pad_after=53):
    """bone_defs: [(name_idx, parent_idx, quat4, pos3, scale3), ...]
    (index 0 must have parent_idx == -1)。3配列(RawRefBoneInfo/
    RawRefBonePose/RawNameToIndexMap)+件数フィールドを、スキャナが要求する
    連続レイアウトで作る。前後にパディングを挟み、スキャナがオフセット走査で
    正しく発見できることも検証する。"""
    count = len(bone_defs)
    body = bytearray()
    body += struct.pack("<i", count)
    for name_idx, parent_idx, _q, _p, _s in bone_defs:
        body += struct.pack("<iii", name_idx, 0, parent_idx)
    body += struct.pack("<i", count)  # transform count
    for _name_idx, _parent_idx, q, p, s in bone_defs:
        vals = list(q) + list(p) + list(s)
        body += struct.pack("<10d", *vals)
    body += struct.pack("<i", count)  # map count
    for i, (name_idx, _parent_idx, _q, _p, _s) in enumerate(bone_defs):
        body += struct.pack("<iii", name_idx, 0, i)
    return (b"\x00" * pad_before) + bytes(body) + (b"\x00" * pad_after)


IDENTITY_Q = (0.0, 0.0, 0.0, 1.0)


def _simple_fixture():
    """6骨の小さな鎖: root -> a -> b -> c、root -> x -> y(枝分かれ)。"""
    names = ["root", "a", "b", "c", "x", "y"]
    bone_defs = [
        (0, -1, IDENTITY_Q, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        (1, 0, IDENTITY_Q, (1.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        (2, 1, IDENTITY_Q, (2.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        (3, 2, IDENTITY_Q, (3.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        (4, 0, IDENTITY_Q, (0.0, 1.0, 0.0), (1.0, 1.0, 1.0)),
        (5, 4, IDENTITY_Q, (0.0, 2.0, 0.0), (1.0, 1.0, 1.0)),
    ]
    uasset = _build_uasset_bytes(names)
    uexp = _build_refskeleton_uexp_bytes(bone_defs)
    return names, uasset, uexp


# =====================================================================
# scan_full_refskeleton
# =====================================================================

def test_scan_finds_bones_and_offsets_via_padding():
    names, _uasset, uexp = _simple_fixture()
    loc = sss.scan_full_refskeleton(uexp, names, min_bones=3, max_bones=20)
    assert loc.bones == (
        ("root", -1), ("a", 0), ("b", 1), ("c", 2), ("x", 0), ("y", 4))
    assert loc.tsize == 80


def test_scan_rejects_out_of_range_bone_count():
    names, _uasset, uexp = _simple_fixture()
    with pytest.raises(sss.SharedSkeletonError):
        sss.scan_full_refskeleton(uexp, names, min_bones=100, max_bones=200)


# =====================================================================
# full_skeleton_catalog
# =====================================================================

def test_full_skeleton_catalog_roundtrip(tmp_path):
    names, uasset, uexp = _simple_fixture()
    uasset_path = tmp_path / "SK.uasset"
    uexp_path = tmp_path / "SK.uexp"
    uasset_path.write_bytes(uasset)
    uexp_path.write_bytes(uexp)

    catalog = sss.full_skeleton_catalog(
        str(uasset_path), str(uexp_path), min_bones=3, max_bones=20)
    assert catalog["bone_count"] == 6
    by_name = {b["name"]: b for b in catalog["bones"]}
    assert by_name["b"]["parent_idx"] == 1  # b's parent is 'a' (idx 1)
    assert by_name["b"]["pos"] == [2.0, 0.0, 0.0]
    assert by_name["root"]["parent_idx"] == -1


# =====================================================================
# full_skeleton_catalog -- 実測データ固定テスト
# =====================================================================

@pytest.mark.skipif(
    not (os.path.exists(_VANILLA_UASSET) and os.path.exists(_VANILLA_UEXP)
         and os.path.exists(_DONOR_CATALOG_CACHE)),
    reason="real vanilla SK_PalHuman_Skeleton.uasset/uexp or donor catalog "
           "cache not present on this machine")
def test_full_skeleton_catalog_matches_real_4079_bone_donor_catalog():
    """実測データ固定テスト(指揮者指示: 前任がキャッシュに対して手動確認した
    だけで自動テストに固定していなかった「4079骨・既知の値と完全一致」を
    自動テストへ昇格)。実際のバニラ抽出物(共有Skeleton)へ
    `full_skeleton_catalog()`を適用した結果が、研究レーンの既知実測キャッシュ
    (`work\\rd_19_donorcatalog\\sk_palhuman_full.json`)と骨数・名前列・親子
    構造・全rest transform数値まで完全一致することを検証する。"""
    catalog = sss.full_skeleton_catalog(_VANILLA_UASSET, _VANILLA_UEXP)
    assert catalog["bone_count"] == 4079

    with open(_DONOR_CATALOG_CACHE, encoding="utf-8") as f:
        cached = json.load(f)
    assert cached["bone_count"] == 4079

    got = catalog["bones"]
    want = cached["bones"]
    assert len(got) == len(want)
    assert [b["name"] for b in got] == [b["name"] for b in want]
    assert [b["parent_idx"] for b in got] == [b["parent_idx"] for b in want]
    for a, b in zip(got, want):
        for key in ("quat", "pos", "scale"):
            assert a[key] == b[key], f"{a['name']} field {key} mismatch"

    # 既知アンカー(モジュールdocstring/前任の手動確認と同じ骨)がpelvis/head系
    # 直下の位置に実在することも直接確認(単なる配列一致だけでなく意味のある骨で
    # あることの裏取り)。
    by_name = {b["name"]: b for b in got}
    assert "F_OldCloth001_04" in by_name
    assert by_name["F_OldCloth001_04"]["parent_idx"] >= 0


# =====================================================================
# reparent_bone_content_only
# =====================================================================

def test_reparent_moves_only_parent_field():
    names, _uasset, uexp = _simple_fixture()
    new_uexp, info = sss.reparent_bone_content_only(
        uexp, names, "y", "a", min_bones=3, max_bones=20)
    assert info["old_parent_name"] == "x"
    assert info["new_parent_name"] == "a"
    # 実際に変化するバイト数はold/new parent_idxの値次第(リトルエンディアンで
    # 一致する上位バイトは差分に出ない)。上限4B(parent_idxフィールドのみ)を
    # 超えないことだけを機械的に保証する(実装側のparanoid self-checkが
    # 「意図した範囲外のバイトは一切変わらない」ことを別途強制している)。
    assert 0 < info["n_bytes_diff"] <= 4
    assert not info["transform_changed"]

    loc2 = sss.scan_full_refskeleton(new_uexp, names, min_bones=3, max_bones=20)
    assert dict(loc2.bones)["y"] == 1  # 'a' is bone index 1


def test_reparent_with_transform_overwrites_only_parent_and_transform():
    names, _uasset, uexp = _simple_fixture()
    new_local = ((0.0, 0.0, 0.0, 1.0), (9.0, 8.0, 7.0), (1.0, 1.0, 1.0))
    new_uexp, info = sss.reparent_bone_content_only(
        uexp, names, "c", "root", new_local_transform=new_local,
        min_bones=3, max_bones=20)
    assert info["transform_changed"]
    assert 0 < info["n_bytes_diff"] <= 4 + 80

    loc2 = sss.scan_full_refskeleton(new_uexp, names, min_bones=3, max_bones=20)
    idx_c = [n for n, _p in loc2.bones].index("c")
    assert loc2.bones[idx_c][1] == 0  # reparented to root (idx 0)
    vals = struct.unpack_from("<10d", loc2.data, loc2.tpos + idx_c * 80)
    assert list(vals[4:7]) == [9.0, 8.0, 7.0]


# ---- 負の対照(意図的に壊すと検出されることの証明) ----

def test_reparent_rejects_topology_violation():
    """'a'(idx1)を自分の子孫'c'(idx3)の下へ付け替えようとする=トポロジ違反
    (new_parent_idx(3) は target_idx(1) より小さくない)。"""
    names, _uasset, uexp = _simple_fixture()
    with pytest.raises(sss.SharedSkeletonError, match="topology violation"):
        sss.reparent_bone_content_only(uexp, names, "a", "c", min_bones=3, max_bones=20)


def test_reparent_rejects_root_bone():
    names, _uasset, uexp = _simple_fixture()
    with pytest.raises(sss.SharedSkeletonError, match="index 0"):
        sss.reparent_bone_content_only(uexp, names, "root", "a", min_bones=3, max_bones=20)


def test_reparent_rejects_unknown_target():
    names, _uasset, uexp = _simple_fixture()
    with pytest.raises(sss.SharedSkeletonError, match="target bone not found"):
        sss.reparent_bone_content_only(uexp, names, "nope", "a", min_bones=3, max_bones=20)


def test_reparent_rejects_unknown_new_parent():
    names, _uasset, uexp = _simple_fixture()
    with pytest.raises(sss.SharedSkeletonError, match="new parent bone not found"):
        sss.reparent_bone_content_only(uexp, names, "y", "nope", min_bones=3, max_bones=20)


def test_reparent_rejects_malformed_transform():
    names, _uasset, uexp = _simple_fixture()
    with pytest.raises(sss.SharedSkeletonError, match="malformed"):
        sss.reparent_bone_content_only(
            uexp, names, "y", "a",
            new_local_transform=((0, 0, 0, 1), (0, 0, 0)),  # missing scale
            min_bones=3, max_bones=20)


# =====================================================================
# apply_reparent_chain
# =====================================================================

def test_apply_reparent_chain_sequential(tmp_path):
    names, uasset, uexp = _simple_fixture()
    uasset_path = tmp_path / "SK.uasset"
    uexp_path = tmp_path / "SK.uexp"
    uasset_path.write_bytes(uasset)
    uexp_path.write_bytes(uexp)

    steps = [
        sss.ReparentStep(target="x", new_parent="c", tag="hub->tail"),
        sss.ReparentStep(target="y", new_parent="x", tag="donor1->hub"),
    ]
    out_uasset, out_uexp, infos = sss.apply_reparent_chain(
        str(uasset_path), str(uexp_path), steps, min_bones=3, max_bones=20)

    assert out_uasset == uasset  # content-only: uasset byte-identical
    assert len(out_uexp) == len(uexp)  # length unchanged
    assert [i["tag"] for i in infos] == ["hub->tail", "donor1->hub"]

    loc = sss.scan_full_refskeleton(out_uexp, names, min_bones=3, max_bones=20)
    d = dict(loc.bones)
    assert d["x"] == 3  # 'c' is bone index 3
    assert d["y"] == 4  # 'x' is still bone index 4 (unmoved in the array)


def test_apply_reparent_chain_rejects_duplicate_target(tmp_path):
    names, uasset, uexp = _simple_fixture()
    uasset_path = tmp_path / "SK.uasset"
    uexp_path = tmp_path / "SK.uexp"
    uasset_path.write_bytes(uasset)
    uexp_path.write_bytes(uexp)

    steps = [
        sss.ReparentStep(target="y", new_parent="a"),
        sss.ReparentStep(target="y", new_parent="b"),
    ]
    with pytest.raises(sss.SharedSkeletonError, match="duplicate"):
        sss.apply_reparent_chain(str(uasset_path), str(uexp_path), steps,
                                  min_bones=3, max_bones=20)
