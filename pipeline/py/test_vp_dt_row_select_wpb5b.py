# -*- coding: utf-8 -*-
"""WP-B5b(dev#1198): 本番のDT行読み取り経路(vp_dt_row_select.load_dt_rows_from_uexp)
の単体テスト。

test_dt_flag_patcher.py(WP-B1)と同じ流儀: Palworld由来のバイト列は一切含まない。
架空のNameMap・架空のパッケージパスのみで構成した合成uexpバイト列を、
本テストファイル内で組み立てる。dt_flag_patcher.parse_rows()が
SkeletalMeshMapのPackageNameを実際にデコードするようになったこと
(WP-B5b追記)を、その先頭から末尾まで(実DT抽出 -> パース -> 行選定)の
配線として検証する。

実行: python -m pytest pipeline\\py\\test_vp_dt_row_select_wpb5b.py -q
"""
from __future__ import annotations

import struct

import pytest

import dt_flag_patcher as dtp
import vp_dt_row_select as rowsel


# --------------------------------------------------------------- synthetic DT builder
# (test_dt_flag_patcher.py と同型の最小バイナリビルダー。本テストファイル単体で
# 完結させるため、架空のNameMapとして"/Game/..."形式のフルパッケージパスを
# 直接NameMapエントリに持たせる——UEのFNameは文字列そのものをname table
# エントリとして持つため、フルパスがそのまま1エントリになりうる)

def _pack_fname(index: int, number: int = 0) -> bytes:
    return struct.pack("<ii", index, number)


def _pack_fragment(skip: int, valuenum: int, haszero: bool, islast: bool) -> bytes:
    raw = (skip & 0x7F) | (0x80 if haszero else 0) | ((valuenum & 0x7F) << 9) | (0x100 if islast else 0)
    return struct.pack("<H", raw)


def _pack_zeromask(bits) -> bytes:
    val = 0
    for i, b in enumerate(bits):
        if b:
            val |= (1 << i)
    return bytes([val])


def _pack_softobjectpath(pkg_idx: int, asset_idx: int) -> bytes:
    return _pack_fname(pkg_idx) + _pack_fname(asset_idx) + struct.pack("<i", 0)


def _pack_map_sop(entries) -> bytes:
    """entries: [(key_name_idx, pkg_idx, asset_idx), ...]"""
    out = struct.pack("<i", 0)  # numKeysToRemove
    out += struct.pack("<i", len(entries))
    for key_idx, pkg_idx, asset_idx in entries:
        out += _pack_fname(key_idx)
        out += _pack_softobjectpath(pkg_idx, asset_idx)
    return out


def _build_row_bytes(row_name_idx, *, sk_map_entries, full_body_equipment) -> bytes:
    """1行分。SkeletalMeshMap/ABPAssetMap/HairAttachSocketNameMapは常にnon-zero
    (空マップでも書く)、IsHairAttachAccessory/bUseCustomDepthPassはzero、
    OverrideBodyType/BodyShapeはzero -- dt_flag_patcher._SCHEMA の並びに揃える。"""
    fields_zero = [False, False, True, False, True,
                   full_body_equipment is None, True, True]
    row_name = _pack_fname(row_name_idx)
    fragment = _pack_fragment(0, 8, True, True)
    zeromask = _pack_zeromask(fields_zero)
    body = b""
    body += _pack_map_sop(sk_map_entries)       # SkeletalMeshMap
    body += _pack_map_sop([])                   # ABPAssetMap(空)
    body += _pack_map_sop([])                   # HairAttachSocketNameMap
    # (map_name型だがpack_map_sopと同じ物理レイアウト=numKeysToRemove+numEntries)
    if not fields_zero[5]:
        body += struct.pack("<?", bool(full_body_equipment))
    return row_name + fragment + zeromask + body


def _build_synthetic_dt(rows_spec) -> bytes:
    prefix = _pack_fragment(0, 1, False, True)
    prefix += struct.pack("<i", -3)
    prefix += struct.pack("<i", 0)
    prefix += struct.pack("<i", len(rows_spec))
    rows_bytes = b"".join(_build_row_bytes(idx, **kw) for idx, kw in rows_spec)
    return prefix + rows_bytes + b"\xDE\xAD\xBE\xEF"


# 架空のNameMap。0..2=行名、3..4=フル装備パッケージパス(Outfitの命名規約を
# 模した架空の値)、5=Male、6=Female。
_PKG_CLOAK_M = "/Game/Pal/Model/Character/Player/Outfit/SK_Player_Male_Outfit_Fictional001/SK_Player_Male_Outfit_Fictional001"
_PKG_CLOAK_F = "/Game/Pal/Model/Character/Player/Outfit/SK_Player_Female_Outfit_Fictional001/SK_Player_Female_Outfit_Fictional001"
_NAMES = [
    "FictionalCloak",   # 0: 選定対象になる行
    "UnrelatedArmor",   # 1: 選定対象にならない行
    "AlreadyTrueArmor", # 2: 既にTrueな無関係行(負の対照)
    _PKG_CLOAK_M,        # 3
    _PKG_CLOAK_F,        # 4
    "Male",             # 5
    "Female",           # 6
    "/Game/Pal/Model/Character/Player/Outfit/SK_Player_Male_Outfit_Other001/SK_Player_Male_Outfit_Other001",  # 7
]


def _make_dt():
    rows_spec = [
        (0, dict(sk_map_entries=[(5, 3, 3), (6, 4, 4)], full_body_equipment=None)),
        (1, dict(sk_map_entries=[(5, 7, 7)], full_body_equipment=None)),
        (2, dict(sk_map_entries=[(5, 7, 7)], full_body_equipment=True)),
    ]
    return _build_synthetic_dt(rows_spec), _NAMES


# --------------------------------------------------------------------- tests

def test_load_dt_rows_from_uexp_decodes_package_names():
    """dt_flag_patcher.parse_rows()がSkeletalMeshMapのPackageNameを実際に
    デコードし、load_dt_rows_from_uexp()がそれを正規化してDtEquipmentRowへ
    組み立てることを確認する(WP-B5b本番配線)。"""
    buf, names = _make_dt()
    rows = rowsel.load_dt_rows_from_uexp(buf, names)
    by_name = {r.name: r for r in rows}
    assert set(by_name) == {"FictionalCloak", "UnrelatedArmor", "AlreadyTrueArmor"}
    assert by_name["FictionalCloak"].sk_rel_paths == {
        "Player/Outfit/SK_Player_Male_Outfit_Fictional001/SK_Player_Male_Outfit_Fictional001",
        "Player/Outfit/SK_Player_Female_Outfit_Fictional001/SK_Player_Female_Outfit_Fictional001",
    }
    assert by_name["UnrelatedArmor"].sk_rel_paths == {
        "Player/Outfit/SK_Player_Male_Outfit_Other001/SK_Player_Male_Outfit_Other001",
    }


def test_end_to_end_selection_matches_injected_targets():
    """正の対照: 実際に注入されたSK(targets_rel)集合と一致する行だけが
    選定される、という一気通貫(バイト列 -> parse -> normalize -> select)。"""
    buf, names = _make_dt()
    rows = rowsel.load_dt_rows_from_uexp(buf, names)
    targets_rel = [
        "Player/Outfit/SK_Player_Male_Outfit_Fictional001/SK_Player_Male_Outfit_Fictional001.uexp",
        "Player/Outfit/SK_Player_Female_Outfit_Fictional001/SK_Player_Female_Outfit_Fictional001.uexp",
    ]
    selected = rowsel.select_full_body_equipment_rows(rows, targets_rel)
    assert selected == ["FictionalCloak"]


def test_negative_control_unrelated_targets_select_nothing():
    """負の対照: どの行のSkeletalMeshMapとも一致しないSKパスを渡すと、
    何も選ばれない。"""
    buf, names = _make_dt()
    rows = rowsel.load_dt_rows_from_uexp(buf, names)
    selected = rowsel.select_full_body_equipment_rows(
        rows, ["Player/Outfit/SK_Player_Male_Outfit_NoSuchThing/SK_Player_Male_Outfit_NoSuchThing.uexp"])
    assert selected == []


def test_corrupted_structure_raises_dtstructureerror_negative_control():
    """負の対照: 破損したバイト構造は、行選定の入口(load_dt_rows_from_uexp)
    でも黙って読み飛ばさず即座に例外送出する(§2.3の規律をこの経路にも適用)。"""
    buf, names = _make_dt()
    truncated = buf[:20]
    with pytest.raises(dtp.DtStructureError):
        rowsel.load_dt_rows_from_uexp(truncated, names)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
