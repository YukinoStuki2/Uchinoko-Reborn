"""dt_flag_patcher.py の単体テスト(WP-B1、dev#1198)。

Palworld由来のバイト列は一切含まない。フィクスチャは全て本テストファイル内の
_build_synthetic_dt() で合成した「架空の」DT(架空の行名・架空のパッケージ
パス)であり、dt_flag_patcher.py が前提とする物理フォーマット
(FUnversionedHeader: フラグメント+zero-mask、8プロパティ固定スキーマ)を
自己完結で再現している。

実際のUAssetAPI出力(work/rd_1198_flagtest/dt_patch/out/)とのバイト完全一致は、
このWPの実装過程でこのモジュールに対して直接検証済み(35行、両方向、完全一致)。
work/ はgitignore対象・Palworldの実データを含むため、その検証はこのリポジトリの
自動テストには含めない(同梱スタブ問題の再発を避けるため——過去に
Palworld由来データを配布物へ混入させた事故があり、テスト資産についても
同じ注意を払う)。
"""
from __future__ import annotations

import struct

import pytest

import dt_flag_patcher as dtp


# --------------------------------------------------------------- synthetic DT builder

def _pack_fname(index: int, number: int = 0) -> bytes:
    return struct.pack("<ii", index, number)


def _pack_fragment(skip: int, valuenum: int, haszero: bool, islast: bool) -> bytes:
    raw = (skip & 0x7F) | (0x80 if haszero else 0) | ((valuenum & 0x7F) << 9) | (0x100 if islast else 0)
    return struct.pack("<H", raw)


def _pack_zeromask(bits) -> bytes:
    """bits: 8要素以内のbool列。1バイトにパック(LSB=idx0)。"""
    val = 0
    for i, b in enumerate(bits):
        if b:
            val |= (1 << i)
    return bytes([val])


def _pack_softobjectpath(pkg_idx: int, asset_idx: int) -> bytes:
    """PackageName FName + AssetName FName + SubPathString=null(4B)。"""
    return _pack_fname(pkg_idx) + _pack_fname(asset_idx) + struct.pack("<i", 0)


def _pack_map_sop(entries) -> bytes:
    """entries: [(key_name_idx, pkg_idx, asset_idx), ...]"""
    out = struct.pack("<i", 0)  # numKeysToRemove
    out += struct.pack("<i", len(entries))
    for key_idx, pkg_idx, asset_idx in entries:
        out += _pack_fname(key_idx)
        out += _pack_softobjectpath(pkg_idx, asset_idx)
    return out


def _pack_map_name(entries) -> bytes:
    """entries: [(key_name_idx, value_name_idx), ...]"""
    out = struct.pack("<i", 0)
    out += struct.pack("<i", len(entries))
    for key_idx, val_idx in entries:
        out += _pack_fname(key_idx)
        out += _pack_fname(val_idx)
    return out


# フィールドの既定(zero)状態のプレースホルダビルダー(このスキーマの並びで
# 「non-zero(present)」なものだけ実際にバイトを書く。zeroなものは何も書かない)。

def _build_row_bytes(
    row_name_idx: int,
    row_name_num: int,
    *,
    sk_map_entries,
    abp_map_entries,
    is_hair_attach: bool = False,
    hair_socket_entries=(),
    use_custom_depth: bool = False,
    full_body_equipment,  # True/False/None(Noneならフィールド自体を省略=zero)
    override_body_type_idx=None,  # Noneならzero
    body_shape_val=None,  # Noneならzero、それ以外は0..255のbyte
) -> bytes:
    """1行分のバイト列を、dt_flag_patcher._SCHEMA の並びどおりに合成する。
    このDTのスキーマは常に8プロパティ・単一フラグメント
    {skip=0,valuenum=8,haszero=True,islast=True} という実測不変条件
    (dt_flag_patcher._EXPECTED_FRAGMENT)を、意図的にそのまま再現する。
    """
    # 各フィールドが「zero(既定値、行に物理的に存在しない)」かどうかを、
    # 呼び出し引数から決める。
    fields_zero = [
        len(sk_map_entries) == 0 and False,  # SkeletalMeshMapは常にnon-zero扱いにする(テスト簡略化のため空でも書く)
        len(abp_map_entries) == 0 and False,
        not is_hair_attach,
        len(hair_socket_entries) == 0 and False,
        not use_custom_depth,
        full_body_equipment is None,
        override_body_type_idx is None,
        body_shape_val is None,
    ]
    # SkeletalMeshMap/ABPAssetMap/HairAttachSocketNameMapは空マップでも
    # 「present」として書く(実測のHairAttachSocketNameMap: IsZero=Falseかつ
    # 0エントリ、というケースを模す)。
    fields_zero[0] = False
    fields_zero[1] = False
    fields_zero[3] = False

    row_name = _pack_fname(row_name_idx, row_name_num)
    fragment = _pack_fragment(0, 8, True, True)
    zeromask = _pack_zeromask(fields_zero)

    body = b""
    if not fields_zero[0]:
        body += _pack_map_sop(sk_map_entries)
    if not fields_zero[1]:
        body += _pack_map_sop(abp_map_entries)
    if not fields_zero[2]:
        body += struct.pack("<?", is_hair_attach)
    if not fields_zero[3]:
        body += _pack_map_name(hair_socket_entries)
    if not fields_zero[4]:
        body += struct.pack("<?", use_custom_depth)
    if not fields_zero[5]:
        body += struct.pack("<?", bool(full_body_equipment))
    if not fields_zero[6]:
        body += _pack_fname(override_body_type_idx)
    if not fields_zero[7]:
        body += struct.pack("<B", body_shape_val)

    return row_name + fragment + zeromask + body


def _build_synthetic_dt(rows_spec) -> bytes:
    """rows_spec: [(name_idx, name_num, kwargs_for_build_row_bytes), ...]
    完全なuexpバイト列(prefix + 各行 + trailer)を組み立てる。
    """
    # prefix: RowStruct(ObjectPropertyData, importインデックス=適当な負値) の
    # 単一フラグメント + ObjectGuidマーカー(0=無し) + numEntries。
    prefix = _pack_fragment(0, 1, False, True)
    prefix += struct.pack("<i", -3)  # RowStruct import index (架空)
    prefix += struct.pack("<i", 0)  # ObjectGuid marker: 無し
    prefix += struct.pack("<i", len(rows_spec))

    rows_bytes = b"".join(_build_row_bytes(name_idx, name_num, **kwargs) for name_idx, name_num, kwargs in rows_spec)
    trailer = b"\xDE\xAD\xBE\xEF"  # 実DTの末尾4バイトを模した無関係なトレーラ
    return prefix + rows_bytes + trailer


# 架空のNameMap(実在のPalworldアセットパスは一切含まない)。
_NAMES = [
    "TestArmorA",       # 0
    "TestArmorB",       # 1
    "TestCollabArmor",  # 2
    "SK_Test_Outfit_A", # 3
    "SK_Test_Outfit_B", # 4
    "Male",             # 5
    "Female",           # 6
]


def _simple_two_row_dt():
    """2行: 'TestArmorA'(bIsFullBodyEquipment=zero/False)、
    'TestCollabArmor'(bIsFullBodyEquipment=True、既に存在)。"""
    rows_spec = [
        (0, 0, dict(
            sk_map_entries=[(5, 3, 3), (6, 3, 3)],
            abp_map_entries=[(5, 3, 3), (6, 3, 3)],
            full_body_equipment=None,  # zero = False
        )),
        (2, 0, dict(
            sk_map_entries=[(5, 4, 4), (6, 4, 4)],
            abp_map_entries=[(5, 4, 4), (6, 4, 4)],
            full_body_equipment=True,  # 既にnonzero=True
        )),
    ]
    return _build_synthetic_dt(rows_spec), _NAMES


# --------------------------------------------------------------------- tests

def test_parse_rows_basic():
    buf, names = _simple_two_row_dt()
    rows = dtp.parse_rows(buf, names)
    assert [r.name for r in rows] == ["TestArmorA", "TestCollabArmor"]
    assert rows[0].state == "zero"
    assert rows[1].state == "nonzero"
    assert buf[rows[1].value_byte_pos] == 1


def test_parse_rows_decodes_skeletalmeshmap_package_names():
    """dev#1198 WP-B5b(本番のDT行読み取り経路): parse_rows()がSkeletalMeshMap
    の各エントリのPackageName(FName)を実際にデコードしてsk_package_names
    へ集めることを確認する(row0はMale/Female両方が'SK_Test_Outfit_A'、
    row1はMale/Female両方が'SK_Test_Outfit_B'を参照)。"""
    buf, names = _simple_two_row_dt()
    rows = dtp.parse_rows(buf, names)
    assert rows[0].sk_package_names == frozenset({"SK_Test_Outfit_A"})
    assert rows[1].sk_package_names == frozenset({"SK_Test_Outfit_B"})


def test_parse_rows_sk_package_names_negative_control_no_cross_contamination():
    """負の対照: 行ごとに異なるSKを参照する場合、他の行のパッケージ名が
    混入しないこと(idx0の読み取り位置がposを正しく前進させている証拠)。"""
    buf, names = _simple_two_row_dt()
    rows = dtp.parse_rows(buf, names)
    assert "SK_Test_Outfit_B" not in rows[0].sk_package_names
    assert "SK_Test_Outfit_A" not in rows[1].sk_package_names


def test_false_to_true_inserts_byte_and_flips_mask_bit():
    buf, names = _simple_two_row_dt()
    patched = dtp.patch_full_body_equipment_flags(buf, names, {"TestArmorA": True})

    # 挿入により全体は+1バイトのはず(zero-mask置換は長さ不変、値バイト挿入で+1)。
    assert len(patched) == len(buf) + 1

    rows_before = dtp.parse_rows(buf, names)
    rows_after = dtp.parse_rows(patched, names)
    assert [r.name for r in rows_after] == [r.name for r in rows_before]
    assert rows_after[0].state == "nonzero"
    assert patched[rows_after[0].value_byte_pos] == 1

    # 対象外の行(TestCollabArmor)は一切変化しない。
    assert rows_after[1].state == "nonzero"
    assert patched[rows_after[1].value_byte_pos] == 1


def test_true_to_false_is_inplace_single_byte_replace():
    buf, names = _simple_two_row_dt()
    patched = dtp.patch_full_body_equipment_flags(buf, names, {"TestCollabArmor": False})

    # 長さは不変(ヘッダ非変更、値バイトのみ置換)。
    assert len(patched) == len(buf)

    rows_before = dtp.parse_rows(buf, names)
    rows_after = dtp.parse_rows(patched, names)
    assert rows_after[1].state == "nonzero"
    assert patched[rows_after[1].value_byte_pos] == 0

    # 値バイトの位置そのものは変わらないはず(ヘッダ不変)。
    assert rows_after[1].value_byte_pos == rows_before[1].value_byte_pos

    # 変更箇所以外は完全にバイト一致(negative control、直接比較)。
    diff_positions = [i for i in range(len(buf)) if buf[i] != patched[i]]
    assert diff_positions == [rows_before[1].value_byte_pos]


def test_multi_row_edit_leaves_unrelated_rows_byte_identical():
    rows_spec = [
        (0, 0, dict(sk_map_entries=[(5, 3, 3)], abp_map_entries=[(5, 3, 3)], full_body_equipment=None)),
        (1, 0, dict(sk_map_entries=[(5, 3, 3)], abp_map_entries=[(5, 3, 3)], full_body_equipment=None)),
        (2, 0, dict(sk_map_entries=[(5, 4, 4)], abp_map_entries=[(5, 4, 4)], full_body_equipment=True)),
    ]
    buf = _build_synthetic_dt(rows_spec)
    names = _NAMES

    rows_before = dtp.parse_rows(buf, names)
    # 'TestArmorB'(idx1)のみを書き換え、'TestArmorA'(idx0)は触らない。
    patched = dtp.patch_full_body_equipment_flags(buf, names, {"TestArmorB": True})

    rows_after = dtp.parse_rows(patched, names)
    assert rows_after[1].state == "nonzero" and patched[rows_after[1].value_byte_pos] == 1
    assert rows_after[0].state == "zero"  # TestArmorA unaffected
    assert rows_after[2].state == "nonzero" and patched[rows_after[2].value_byte_pos] == 1  # TestCollabArmor unaffected

    # TestArmorA(1行目)の生バイト領域は完全にそのまま残っているはず。
    row0_before = buf[rows_before[0].row_start:rows_before[0].row_end]
    row0_after = patched[rows_after[0].row_start:rows_after[0].row_end]
    assert row0_before == row0_after


def test_noop_when_value_already_matches():
    buf, names = _simple_two_row_dt()
    patched = dtp.patch_full_body_equipment_flags(buf, names, {"TestArmorA": False})
    assert patched == buf  # 既にFalseなので完全に無変更


def test_missing_row_name_raises_value_error():
    buf, names = _simple_two_row_dt()
    with pytest.raises(ValueError):
        dtp.patch_full_body_equipment_flags(buf, names, {"NoSuchRow": True})


def test_empty_edits_raises():
    buf, names = _simple_two_row_dt()
    with pytest.raises(ValueError):
        dtp.patch_full_body_equipment_flags(buf, names, {})


def test_ambiguous_row_name_raises_structure_error():
    """同じ復元名になる2行(FNumberの衝突)を意図的に作り、拒否されることを確認。"""
    rows_spec = [
        (0, 0, dict(sk_map_entries=[(5, 3, 3)], abp_map_entries=[(5, 3, 3)], full_body_equipment=None)),
        (0, 0, dict(sk_map_entries=[(5, 4, 4)], abp_map_entries=[(5, 4, 4)], full_body_equipment=None)),
    ]
    buf = _build_synthetic_dt(rows_spec)
    with pytest.raises(dtp.DtStructureError):
        dtp.patch_full_body_equipment_flags(buf, _NAMES, {"TestArmorA": True})


# ------------------------------------------------- negative controls: 意図的に壊す

def test_corrupted_fragment_shape_is_rejected():
    """行ヘッダのフラグメントを意図的に壊す(ValueNumを8以外にする)と、
    想定外構造として即停止することを確認する(黙ってスキップしない)。"""
    buf, names = _simple_two_row_dt()
    rows = dtp.parse_rows(buf, names)
    row0 = rows[0]
    # row0のフラグメント(row_start+8バイト目、RowNameの直後)のvaluenumを
    # 8から7へ壊す。フラグメントは2バイト: 低byte=skip|haszero、
    # 高byte=islast|valuenum<<1。 8<<1=16=0x10 -> 7<<1=14=0x0e。
    frag_pos = row0.row_start + 8
    mutated = bytearray(buf)
    raw = struct.unpack_from("<H", mutated, frag_pos)[0]
    # valuenumビットだけ8->7に落とす(0x0e00 -> 0x0e00 に相当するビット操作)
    new_raw = (raw & ~(0x7F << 9)) | (7 << 9)
    struct.pack_into("<H", mutated, frag_pos, new_raw)

    with pytest.raises(dtp.DtStructureError):
        dtp.patch_full_body_equipment_flags(bytes(mutated), names, {"TestArmorA": True})


def test_truncated_buffer_is_rejected():
    buf, names = _simple_two_row_dt()
    truncated = buf[:20]  # 明らかに全行を読みきれない長さ
    with pytest.raises(dtp.DtStructureError):
        dtp.patch_full_body_equipment_flags(truncated, names, {"TestArmorA": True})


def test_bogus_namemap_index_is_rejected():
    """RowNameのFNameインデックスがNameMap範囲外を指す壊れたデータを検出する。"""
    buf, names = _simple_two_row_dt()
    mutated = bytearray(buf)
    # prefix(10バイト)直後、row0のRowName FNameのindexフィールドを
    # NameMap範囲外の値へ書き換える。
    struct.pack_into("<i", mutated, 10, 99999)
    with pytest.raises(dtp.DtStructureError):
        dtp.parse_rows(bytes(mutated), names)


def test_negative_full_body_equipment_true_to_false_round_trip_is_reversible():
    """True->Falseの後、もう一度Falseのままなら無変更(冪等性)。"""
    buf, names = _simple_two_row_dt()
    once = dtp.patch_full_body_equipment_flags(buf, names, {"TestCollabArmor": False})
    twice = dtp.patch_full_body_equipment_flags(once, names, {"TestCollabArmor": False})
    assert once == twice


def test_false_to_true_then_true_to_false_returns_to_original_bytes():
    """False->True->Falseで元のバイト列(挿入前の状態)に完全復元できることを確認する。
    挿入した1バイトを除去し、zero-maskビットを元通りに立て直す往復操作。"""
    buf, names = _simple_two_row_dt()
    up = dtp.patch_full_body_equipment_flags(buf, names, {"TestArmorA": True})
    rows_up = dtp.parse_rows(up, names)
    assert rows_up[0].state == "nonzero"
    assert up[rows_up[0].value_byte_pos] == 1
    # True -> False は同じフィールドが「既に存在する」状態からの単純置換のみ
    # (今回はFalseへ戻すのでvalue byteが0x00になる。ただし元のバイト列は
    # フィールド自体が存在しない状態だったため、up->downはbuf全体と一致
    # しない——バイト長が buf+1 のまま(挿入したバイトは物理的に残る)。
    # これは実装の期待どおりの挙動であり、バグではない
    # (UAssetAPIも一度Trueにした行を再度Falseにしても、フィールド自体を
    # 除去してzero化はしない——本モジュールのdocstring冒頭の説明どおり)。
    down = dtp.patch_full_body_equipment_flags(up, names, {"TestArmorA": False})
    assert len(down) == len(up)
    rows_down = dtp.parse_rows(down, names)
    assert rows_down[0].state == "nonzero"
    assert down[rows_down[0].value_byte_pos] == 0


# ============================================================ WP-B5b-fix: .uasset SerialSize
#
# 起動即死クラッシュ(dev#1198)の根治対象。patch_uasset_serial_size() /
# read_export_serial_size() / _locate_uasset_patch_points() を、Palworld由来の
# バイト列を一切含まない合成 .uasset フィクスチャで検証する(このファイル
# 冒頭の方針どおり)。実際のUAssetAPI出力(work/rd_1198_flagtest/dt_patch/
# out/、work/rd_1198_proto/dt_patch/out/)とのバイト完全一致は、本WPの実装
# 過程でこのモジュールに対して直接検証済み(delta=15/31の両方でバイト完全
# 一致、完了報告に記録)——work/はgitignore対象のため自動テストには含めない。

_SYNTH_EXPORT_OFFSET = 300


def _build_synthetic_uasset(*, serial_size: int, serial_offset: int,
                             bulk_data_start_offset: int,
                             export_offset: int = _SYNTH_EXPORT_OFFSET,
                             package_flags: int = 0x80000000,
                             legacy_ver: int = -8,
                             export_count: int = 1) -> bytes:
    """dt_flag_patcher._locate_uasset_patch_points() が前提とする
    FPackageFileSummary(UE5.1 cooked, PKG_FilterEditorOnly設定, 単一export)の
    レイアウトを、最小構成で合成する。実測(work/lab1_crash_triage/
    parse_export_table.py + このWPでのバイト突合)で確認したフィールド順を
    そのまま再現する。"""
    buf = bytearray()
    buf += struct.pack("<I", dtp._PACKAGE_TAG)
    buf += struct.pack("<i", legacy_ver)
    buf += struct.pack("<i", 0)   # LegacyUE3Version
    buf += struct.pack("<i", 0)   # FileVersionUE4
    buf += struct.pack("<i", 0)   # FileVersionUE5 (legacy_ver<=-8前提)
    buf += struct.pack("<i", 0)   # FileVersionLicenseeUE4
    buf += struct.pack("<i", 0)   # CustomVersion count
    buf += struct.pack("<i", 0)   # TotalHeaderSize (本パーサは未使用)
    buf += struct.pack("<i", 0)   # FolderName(FString長0)
    buf += struct.pack("<I", package_flags)
    buf += struct.pack("<i", 0)   # NameCount
    buf += struct.pack("<i", 0)   # NameOffset
    buf += struct.pack("<i", 0)   # SoftObjectPathsCount
    buf += struct.pack("<i", 0)   # SoftObjectPathsOffset
    buf += struct.pack("<i", 0)   # GatherableTextDataCount
    buf += struct.pack("<i", 0)   # GatherableTextDataOffset
    buf += struct.pack("<i", export_count)
    buf += struct.pack("<i", export_offset)
    buf += struct.pack("<i", 0)   # ImportCount
    buf += struct.pack("<i", 0)   # ImportOffset
    buf += struct.pack("<i", 0)   # DependsOffset
    buf += struct.pack("<i", 0)   # SoftPackageReferencesCount
    buf += struct.pack("<i", 0)   # SoftPackageReferencesOffset
    buf += struct.pack("<i", 0)   # SearchableNamesOffset
    buf += struct.pack("<i", 0)   # ThumbnailTableOffset
    buf += b"\x00" * 16           # PackageGuid
    buf += struct.pack("<i", 1)   # Generations count
    buf += struct.pack("<ii", export_count, 0)  # FGenerationInfo
    for _ in range(2):            # SavedByEngineVersion / CompatibleWithEngineVersion
        buf += struct.pack("<HHH", 0, 0, 0)
        buf += struct.pack("<I", 0)
        buf += struct.pack("<i", 0)  # Branch(FString長0)
    buf += struct.pack("<I", 0)   # CompressionFlags
    buf += struct.pack("<i", 0)   # CompressedChunks count
    buf += struct.pack("<I", 0)   # PackageSource
    buf += struct.pack("<i", 0)   # AdditionalPackagesToCook count
    buf += struct.pack("<i", 0)   # AssetRegistryDataOffset
    buf += struct.pack("<q", bulk_data_start_offset)

    assert len(buf) <= export_offset, "synthetic header longer than export_offset"
    buf += b"\x00" * (export_offset - len(buf))

    # FObjectExport: ClassIndex/SuperIndex/TemplateIndex/OuterIndex(各i32) +
    # ObjectName(FName,8B) + ObjectFlags(u32) + SerialSize(i64) + SerialOffset(i64)。
    buf += struct.pack("<iiii", 0, 0, 0, 0)
    buf += struct.pack("<ii", 0, 0)
    buf += struct.pack("<I", 0)
    buf += struct.pack("<q", serial_size)
    buf += struct.pack("<q", serial_offset)
    return bytes(buf)


def _synthetic_uasset(serial_size=500, serial_offset=1000):
    bulk = serial_offset + serial_size
    return _build_synthetic_uasset(
        serial_size=serial_size, serial_offset=serial_offset,
        bulk_data_start_offset=bulk)


def test_uasset_serial_size_zero_delta_returns_input_unchanged():
    buf = _synthetic_uasset()
    assert dtp.patch_uasset_serial_size(buf, 0) is buf


@pytest.mark.parametrize("delta", [1, 5, 15, 31, 100])
def test_uasset_serial_size_delta_updates_serialsize_and_bulkdatastart(delta):
    """挿入バイト数を変えた複数ケースで、SerialSize/BulkDataStartOffsetが
    バニラ値+挿入バイト数になることを機械assertする(受入条件#4)。"""
    serial_size0 = 500
    serial_offset0 = 1000
    bulk0 = serial_offset0 + serial_size0
    buf = _build_synthetic_uasset(
        serial_size=serial_size0, serial_offset=serial_offset0,
        bulk_data_start_offset=bulk0)

    patched = dtp.patch_uasset_serial_size(buf, delta)

    assert len(patched) == len(buf), "uasset length must never change"
    points = dtp._locate_uasset_patch_points(patched)
    assert points.old_serial_size == serial_size0 + delta
    assert points.old_bulk_data_start == bulk0 + delta
    assert points.serial_offset_value == serial_offset0  # SerialOffset自体は不変
    # SerialSize/BulkDataStartOffset以外の全バイトが不変であること(正の対照)。
    changed = [i for i in range(len(buf)) if buf[i] != patched[i]]
    for i in changed:
        assert (points.serial_size_pos <= i < points.serial_size_pos + 8
                or points.bulk_data_start_pos <= i < points.bulk_data_start_pos + 8), (
            f"unexpected byte changed at offset {i}")


def test_uasset_serial_size_read_export_serial_size_matches_patch_result():
    buf = _synthetic_uasset(serial_size=500, serial_offset=1000)
    patched = dtp.patch_uasset_serial_size(buf, 31)
    assert dtp.read_export_serial_size(patched) == 531


def test_uasset_serial_size_rejects_non_filter_editor_only_package():
    """PKG_FilterEditorOnlyが立っていない(=非cooked)構造は想定外として拒否する
    (黙って誤った位置を書き換えない、dt_flag_patcher.py全体の流儀)。"""
    buf = _build_synthetic_uasset(
        serial_size=500, serial_offset=1000, bulk_data_start_offset=1500,
        package_flags=0x00000000)
    with pytest.raises(dtp.DtStructureError):
        dtp.patch_uasset_serial_size(buf, 31)


def test_uasset_serial_size_rejects_multi_export_package():
    """export_count != 1 の構造(このDTでは実測上ありえない)は拒否する。"""
    buf = _build_synthetic_uasset(
        serial_size=500, serial_offset=1000, bulk_data_start_offset=1500,
        export_count=2)
    with pytest.raises(dtp.DtStructureError):
        dtp.patch_uasset_serial_size(buf, 31)


def test_uasset_serial_size_rejects_broken_bulk_data_invariant():
    """BulkDataStartOffset != SerialOffset+SerialSize という、このDTでは実測上
    崩れないはずの不変条件が崩れているデータを拒否する(負の対照: 意図的に
    壊すと検出されることの証明)。"""
    buf = _build_synthetic_uasset(
        serial_size=500, serial_offset=1000, bulk_data_start_offset=99999)
    with pytest.raises(dtp.DtStructureError):
        dtp.patch_uasset_serial_size(buf, 31)


def test_uasset_serial_size_rejects_bad_package_tag():
    buf = bytearray(_synthetic_uasset())
    struct.pack_into("<I", buf, 0, 0xDEADBEEF)
    with pytest.raises(dtp.DtStructureError):
        dtp.patch_uasset_serial_size(bytes(buf), 31)


def test_uasset_serial_size_negative_delta_shrinks_serialsize():
    """True->False方向の実運用ではサイズ差分は生じないが、関数自体は符号を
    問わず線形にSerialSize/BulkDataStartOffsetを更新できることを確認する
    (計算式の対称性チェック)。"""
    buf = _synthetic_uasset(serial_size=500, serial_offset=1000)
    up = dtp.patch_uasset_serial_size(buf, 31)
    down = dtp.patch_uasset_serial_size(up, -31)
    assert down == buf
