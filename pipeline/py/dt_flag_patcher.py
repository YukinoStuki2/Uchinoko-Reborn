"""WP-B1(dev#1198): DT_CharacterCreationMeshPresetTable_Equipments の
bIsFullBodyEquipment フラグをその場で書き換える、この1資産専用の
最小バイナリパッチャ(UAssetAPI/.NET不使用、CLAUDE.md言語方針どおりPython)。

設計の正本: work/rd_1198_wpb/PROPOSAL.md §2(DT編集のランタイム手段)。

## 背景(§2.1のバイト解剖の要点)

Palworldのcooked DataTableは "unversioned property serialization"
(UE5のFUnversionedHeader方式)で書かれている。boolフィールドが型の
既定値(false)のときは行の中で物理的に省略され、既定値と異なる値の
ときだけ「フィールドが存在する」形になる。したがって

  - False→True: フィールドが行に存在しない状態から存在する状態への
    遷移であり、①zero-maskビットのクリア(1バイト置換)②値バイト
    0x01の挿入(1バイト挿入)という、2箇所の可変長編集になる。
  - True→False: 対象行は元々「フィールドが存在する状態」なので、
    zero-maskビットは変化させず、値バイトをその場で0x01→0x00に
    書き換えるだけで済む(1バイト置換のみ、長さ不変)。

この非対称性は本調査でUAssetAPI本体のソース
(.devonly/research/uassetapi_roundtrip/UAssetAPI/UAssetAPI/
Unversioned/FUnversionedHeader.cs・FFragment.cs・MainSerializer.cs・
PropertyTypes/Objects/PropertyData.cs)を読み、`IsZero` フラグが
パース時に読み取った値のまま保持され(`.Value` の書き換えだけでは
自動更新されない)、書き込み時は `GenerateUnversionedHeader()` が
`CanBeZero() && IsZero` の両方が真の場合のみそのプロパティを
zero-mask対象にする、という実装から導出した。

## 実証(work/rd_1198_flagtest/dt_patch/out/との突合、本WPで実施)

本モジュールのロジックで計算した書き換え位置は、実際にUAssetAPIで
生成された work/rd_1198_flagtest/dt_patch/out/
DT_CharacterCreationMeshPresetTable_Equipments.uexp
(15行Cloth001系 + 16行IronArmor系のFalse→True、4行Octavia系の
True→False、バニラ work/rd_1198/extract/…uexp との実差分)と
**全31+4行についてバイト位置が完全一致**することを確認済み
(このリポジトリの `work/` はgitignore対象のため、実ファイルは
this WPのdevセッションログにのみ残る。本モジュールのテストは
Palworld由来のバイト列を一切含まない合成フィクスチャで同じ
アルゴリズムを検証する — 同梱スタブ問題(過去のPalworldアセット
混入事故)を再発させないため)。

## PalPlayerEquipmentMeshDataRow の物理スキーマ(本モジュールが前提とする不変条件)

行構造は "RowName(FName, 8B)" + "FUnversionedHeader" +
"プロパティ値(スキーマ順、touched かつ non-zero のものだけ)"。
このDTの全330行を実測した結果、ヘッダは**例外なく単一フラグメント**
`{SkipNum=0, ValueNum=8, HasAnyZeroes=True, IsLast=True}` + 1バイトの
zero-mask(8プロパティ全部がこのフラグメントに属するため)であり、
スキーマは常に8プロパティ固定:

    idx0 SkeletalMeshMap          Map<Name, SoftObjectPath>
    idx1 ABPAssetMap              Map<Name, SoftObjectPath>
    idx2 IsHairAttachAccessory    Bool
    idx3 HairAttachSocketNameMap  Map<Name, Name>
    idx4 bUseCustomDepthPass      Bool
    idx5 bIsFullBodyEquipment     Bool  ← 本モジュールが書き換える対象
    idx6 OverrideBodyType         Name
    idx7 BodyShape                Enum(ByteProperty, 1B)

このモジュールはidx0〜4の値を「読み飛ばす」ためだけにMap/Bool型の
バイト長計算を実装しており、内容は一切解釈・変更しない。想定外の
構造(フラグメント数が1でない、ValueNumが8でない等)に出会ったら
即座にValueErrorで停止する(§2.3: 黙ってスキップしない)。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

# ---------------------------------------------------------------- schema

TARGET_FIELD_NAME = "bIsFullBodyEquipment"

# (フィールド名, 型タグ) 。型タグは _SKIP_FN のキーと対応する。
_SCHEMA: Tuple[Tuple[str, str], ...] = (
    ("SkeletalMeshMap", "map_sop"),
    ("ABPAssetMap", "map_sop"),
    ("IsHairAttachAccessory", "bool"),
    ("HairAttachSocketNameMap", "map_name"),
    ("bUseCustomDepthPass", "bool"),
    (TARGET_FIELD_NAME, "bool"),
    ("OverrideBodyType", "name"),
    ("BodyShape", "enum_byte"),
)
_TARGET_FIELD_INDEX = [n for n, _ in _SCHEMA].index(TARGET_FIELD_NAME)
_SCHEMA_LEN = len(_SCHEMA)

# 実測で確認した唯一の想定フラグメント形状(330/330行で一致)。
_EXPECTED_FRAGMENT = (0, _SCHEMA_LEN, True, True, 0)  # skip,valuenum,haszero,islast,firstnum


class DtStructureError(ValueError):
    """DTのバイト構造が想定(実測ベース)と食い違ったときの例外。
    フラグ書き込みを黙ってスキップせず、変換全体を止めるためのシグナル
    (PROPOSAL §2.3「想定外なら変換全体を停止する」)。"""


# ------------------------------------------------------------ low-level IO

def _read_i32(buf: bytes, pos: int) -> Tuple[int, int]:
    if pos + 4 > len(buf):
        raise DtStructureError(f"unexpected end of buffer reading int32 at {pos}")
    return struct.unpack_from("<i", buf, pos)[0], pos + 4


def _read_u16(buf: bytes, pos: int) -> Tuple[int, int]:
    if pos + 2 > len(buf):
        raise DtStructureError(f"unexpected end of buffer reading uint16 at {pos}")
    return struct.unpack_from("<H", buf, pos)[0], pos + 2


def _read_u32(buf: bytes, pos: int) -> Tuple[int, int]:
    if pos + 4 > len(buf):
        raise DtStructureError(f"unexpected end of buffer reading uint32 at {pos}")
    return struct.unpack_from("<I", buf, pos)[0], pos + 4


def _read_i64(buf: bytes, pos: int) -> Tuple[int, int]:
    if pos + 8 > len(buf):
        raise DtStructureError(f"unexpected end of buffer reading int64 at {pos}")
    return struct.unpack_from("<q", buf, pos)[0], pos + 8


def _skip_fstring_header(buf: bytes, pos: int) -> int:
    """FString(FPackageFileSummary側のフィールド用。DT行データのSubPathString
    と同じエンコードだが、こちらはヘッダ解析専用の別名で持つ)。"""
    n, pos = _read_i32(buf, pos)
    if n == 0:
        return pos
    nbytes = (-n * 2) if n < 0 else n
    if pos + nbytes > len(buf):
        raise DtStructureError(f"FString overruns buffer at {pos}")
    return pos + nbytes


def _skip_fname(buf: bytes, pos: int) -> int:
    """FName(index:int32, number:int32) = 8バイト。内容は解釈しない。"""
    if pos + 8 > len(buf):
        raise DtStructureError(f"unexpected end of buffer reading FName at {pos}")
    return pos + 8


def _decode_fname(buf: bytes, pos: int, names: List[str]) -> Tuple[str, int]:
    if pos + 8 > len(buf):
        raise DtStructureError(f"unexpected end of buffer reading FName at {pos}")
    idx, number = struct.unpack_from("<ii", buf, pos)
    if not (0 <= idx < len(names)):
        raise DtStructureError(f"FName index {idx} out of range (namemap has {len(names)} entries) at {pos}")
    s = names[idx]
    if number > 0:
        s = f"{s}_{number - 1}"
    return s, pos + 8


def _skip_softobjectpath(buf: bytes, pos: int) -> int:
    """FSoftObjectPath(SoftObjectPathListが空のとき): PackageName(FName,8B)
    + AssetName(FName,8B) + SubPathString(FString/UTF8String, int32長+本文。
    長さ0ならnull=4バイトのみ、負なら-len*2バイトのUTF16、正ならlenバイト)。"""
    p = pos + 16
    slen, p2 = _read_i32(buf, p)
    if slen < 0:
        nbytes = -slen * 2
    elif slen > 0:
        nbytes = slen
    else:
        nbytes = 0
    p3 = p2 + nbytes
    if p3 > len(buf):
        raise DtStructureError(f"SoftObjectPath subpath overruns buffer at {pos}")
    return p3


def _decode_softobjectpath(buf: bytes, pos: int, names: List[str]) -> Tuple[str, int]:
    """dev#1198 WP-B5b(本番のDT行読み取り経路): _skip_softobjectpath()と同じ
    バイト長計算をしながら、PackageName(FName)を実際にデコードして返す。
    AssetName/SubPathStringは読み飛ばすだけ(行選定に不要、
    work/rd_1198_wpb/PROPOSAL.md §3の選定式はPackageNameのみを使う)。
    戻り値: (package_name_str, 新しいpos)。"""
    pkg_name, p = _decode_fname(buf, pos, names)
    p = _skip_fname(buf, p)  # AssetName(内容不使用)
    slen, p2 = _read_i32(buf, p)
    if slen < 0:
        nbytes = -slen * 2
    elif slen > 0:
        nbytes = slen
    else:
        nbytes = 0
    p3 = p2 + nbytes
    if p3 > len(buf):
        raise DtStructureError(f"SoftObjectPath subpath overruns buffer at {pos}")
    return pkg_name, p3


def _skip_map(buf: bytes, pos: int, value_skip_fn) -> int:
    """TMap: numKeysToRemove(int32)+その分のキー + numEntries(int32)+その分の
    (キー,値)ペア。キー型はこのDTの全マップでName固定(実測)。"""
    num_keys_to_remove, p = _read_i32(buf, pos)
    if num_keys_to_remove < 0:
        raise DtStructureError(f"negative numKeysToRemove at {pos}")
    for _ in range(num_keys_to_remove):
        p = _skip_fname(buf, p)
    num_entries, p = _read_i32(buf, p)
    if num_entries < 0:
        raise DtStructureError(f"negative map numEntries at {pos}")
    for _ in range(num_entries):
        p = _skip_fname(buf, p)  # key
        p = value_skip_fn(buf, p)  # value
    return p


def _skip_map_sop(buf: bytes, pos: int) -> int:
    return _skip_map(buf, pos, _skip_softobjectpath)


def _skip_map_name(buf: bytes, pos: int) -> int:
    return _skip_map(buf, pos, _skip_fname)


def _decode_map_sop(buf: bytes, pos: int, names: List[str]) -> Tuple[List[str], int]:
    """dev#1198 WP-B5b: TMap<Name, SoftObjectPath>(SkeletalMeshMapフィールド)を、
    _skip_map()と同じ構造(numKeysToRemove + numEntries×(キー,値))で歩きながら、
    各エントリの値(SoftObjectPath)のPackageNameを実際にデコードして集める。
    キー(性別FName、"Male"/"Female")は読み飛ばすだけ(選定ロジックは性別を
    区別しない、work/rd_1198_wpb/PROPOSAL.md §3)。
    戻り値: (このフィールドが参照する全PackageNameのリスト, 新しいpos)。"""
    num_keys_to_remove, p = _read_i32(buf, pos)
    if num_keys_to_remove < 0:
        raise DtStructureError(f"negative numKeysToRemove at {pos}")
    for _ in range(num_keys_to_remove):
        p = _skip_fname(buf, p)
    num_entries, p = _read_i32(buf, p)
    if num_entries < 0:
        raise DtStructureError(f"negative map numEntries at {pos}")
    pkgs: List[str] = []
    for _ in range(num_entries):
        p = _skip_fname(buf, p)  # key(gender)、内容不使用
        pkg, p = _decode_softobjectpath(buf, p, names)
        pkgs.append(pkg)
    return pkgs, p


_SKIP_FN = {
    "map_sop": _skip_map_sop,
    "map_name": _skip_map_name,
    "bool": lambda buf, pos: pos + 1,
    "name": _skip_fname,
    "enum_byte": lambda buf, pos: pos + 1,
}


# ------------------------------------------------------------ header parse

@dataclass(frozen=True)
class _Fragment:
    skip: int
    valuenum: int
    haszero: bool
    islast: bool
    firstnum: int


def _parse_header(buf: bytes, pos: int) -> Tuple[List[_Fragment], List[bool], int]:
    """FUnversionedHeader: フラグメント列(bIsLastまで) + zero-maskビット列。
    戻り値: (fragments, zero_mask_bits, ヘッダ末尾=最初のプロパティ値の位置)。
    """
    fragments: List[_Fragment] = []
    first_num = 0
    zero_mask_num = 0
    while True:
        raw, pos = _read_u16(buf, pos)
        skip = raw & 0x7F
        haszero = bool(raw & 0x80)
        valuenum = (raw >> 9) & 0x7F
        islast = bool(raw & 0x100)
        firstnum = first_num + skip
        fragments.append(_Fragment(skip, valuenum, haszero, islast, firstnum))
        first_num = firstnum + valuenum
        if haszero:
            zero_mask_num += valuenum
        if islast:
            break
        if len(fragments) > 64:
            raise DtStructureError("too many unversioned header fragments (possible corrupt data)")

    zero_mask_bits: List[bool] = []
    if zero_mask_num > 0:
        if zero_mask_num <= 8:
            nbytes = 1
        elif zero_mask_num <= 16:
            nbytes = 2
        else:
            nbytes = ((zero_mask_num + 31) // 32) * 4
        if pos + nbytes > len(buf):
            raise DtStructureError(f"zero-mask overruns buffer at {pos}")
        maskbytes = buf[pos:pos + nbytes]
        pos += nbytes
        bits: List[bool] = []
        for byte in maskbytes:
            for bit in range(8):
                bits.append(bool(byte & (1 << bit)))
        zero_mask_bits = bits[:zero_mask_num]
    return fragments, zero_mask_bits, pos


# ------------------------------------------------------------------ rows

@dataclass
class _RowInfo:
    name: str
    row_start: int
    row_end: int
    # 対象フィールド(bIsFullBodyEquipment)の現況:
    #   state == "zero":    フィールドは行に存在しない(False)。
    #                        zeromask_byte_pos, zeromask_bit に加え、
    #                        値バイトを新規挿入すべき絶対位置を
    #                        insert_pos に持つ(パース時に一度だけ計算、
    #                        使う側では再計算しない)。
    #   state == "nonzero": フィールドは行に存在する。value_byte_pos に
    #                        1バイトの実値(0 or 1)がある。
    state: str
    zeromask_byte_pos: Optional[int] = None
    zeromask_bit: Optional[int] = None
    insert_pos: Optional[int] = None
    value_byte_pos: Optional[int] = None
    # dev#1198 WP-B5b(本番のDT行読み取り経路): SkeletalMeshMapフィールド
    # (schema idx0)がこの行で参照する全SoftObjectPath.PackageNameのデコード
    # 結果。フィールド自体がzero(空マップ扱い)の行では空集合になる。
    # vp_dt_row_select.load_dt_rows_from_uexp()がこれを読み、
    # normalize_dt_package_path()を適用してDtEquipmentRowを組み立てる。
    sk_package_names: FrozenSet[str] = field(default_factory=frozenset)


def _parse_prefix(buf: bytes) -> Tuple[int, int]:
    """DataTableExport本体の手前にある、NormalExport自身のプロパティ
    リスト("RowStruct" 1件)+ ObjectGuid有無マーカー + 行数(numEntries)
    を読み飛ばす。戻り値: (行データ開始位置, numEntries)。

    実測(work/rd_1198/extract/…、47,357B): [フラグメント2B+RowStruct
    ObjectPropertyData値4B] + [ObjectGuid有無マーカー4B、常に0=無し] +
    [numEntries int32] = 14B。本関数は値は固定長で決め打ちせず、
    フラグメント自体をパースして構造検証する。
    """
    fragments, zero_mask_bits, pos = _parse_header(buf, 0)
    if len(fragments) != 1:
        raise DtStructureError(
            f"export-level property header: expected 1 fragment, got {len(fragments)}")
    frag = fragments[0]
    if frag.valuenum != 1 or frag.haszero:
        raise DtStructureError(
            f"export-level property header: expected exactly 1 always-present property "
            f"(RowStruct), got valuenum={frag.valuenum} haszero={frag.haszero}")
    # RowStructはObjectPropertyData(常にnon-zero、4バイトのimport/export index)。
    pos += 4
    # ObjectGuid有無マーカー(4バイトのbool-int)。
    has_guid, pos = _read_i32(buf, pos)
    if has_guid not in (0, 1):
        raise DtStructureError(f"unexpected ObjectGuid marker value {has_guid} at prefix")
    if has_guid:
        pos += 16  # GUID本体(未観測の分岐。安全側に16B消費してから続行)
    num_entries, pos = _read_i32(buf, pos)
    if not (0 <= num_entries <= 100000):
        raise DtStructureError(f"implausible DataTable row count: {num_entries}")
    return pos, num_entries


def _parse_row(buf: bytes, pos: int, names: List[str]) -> _RowInfo:
    row_start = pos
    name, pos = _decode_fname(buf, pos, names)
    fragments, zero_mask_bits, pos = _parse_header(buf, pos)

    if len(fragments) != 1 or (
        fragments[0].skip, fragments[0].valuenum, fragments[0].haszero,
        fragments[0].islast, fragments[0].firstnum
    ) != _EXPECTED_FRAGMENT:
        raise DtStructureError(
            f"row '{name}': unexpected unversioned header shape {fragments} "
            f"(expected single fragment {_EXPECTED_FRAGMENT}; this asset's row schema may "
            f"have changed, e.g. after a Palworld update -- refusing to guess)")

    # touched(=このフラグメントに属する)インデックスを順に消費する。
    zmi = 0
    target_state: Optional[str] = None
    target_zeromask_pos: Optional[int] = None
    target_zeromask_bit: Optional[int] = None
    target_insert_pos: Optional[int] = None
    target_value_pos: Optional[int] = None
    sk_pkgs: List[str] = []
    frag = fragments[0]
    zeromask_nbytes = 1 if len(zero_mask_bits) <= 8 else (2 if len(zero_mask_bits) <= 16 else ((len(zero_mask_bits) + 31) // 32) * 4)
    zeromask_start = pos - zeromask_nbytes

    for i in range(frag.valuenum):
        idx = frag.firstnum + i
        field_name, field_type = _SCHEMA[idx]
        is_zero = zero_mask_bits[zmi]
        bit_index = zmi
        zmi += 1
        if idx == _TARGET_FIELD_INDEX:
            if is_zero:
                target_state = "zero"
                target_zeromask_pos = zeromask_start
                target_zeromask_bit = bit_index
                # 挿入位置 = ここまでに読み飛ばしたnon-zeroプロパティの直後
                # (idx5自身はzeroなので、まだ何も消費していないposがそれ)。
                target_insert_pos = pos
            else:
                target_state = "nonzero"
                target_value_pos = pos
        if not is_zero:
            if field_name == "SkeletalMeshMap":
                # dev#1198 WP-B5b: 本番のDT行読み取り経路。単に読み飛ばす
                # のではなく、参照先PackageNameを実際にデコードする。
                pkgs, pos = _decode_map_sop(buf, pos, names)
                sk_pkgs.extend(pkgs)
            else:
                pos = _SKIP_FN[field_type](buf, pos)

    if target_state is None:
        raise DtStructureError(
            f"row '{name}': target field '{TARGET_FIELD_NAME}' (schema idx {_TARGET_FIELD_INDEX}) "
            f"was not covered by the parsed header at all -- unsupported row structure")

    row = _RowInfo(name=name, row_start=row_start, row_end=pos, state=target_state,
                    sk_package_names=frozenset(sk_pkgs))
    if target_state == "zero":
        row.zeromask_byte_pos = target_zeromask_pos
        row.zeromask_bit = target_zeromask_bit
        row.insert_pos = target_insert_pos
        if row.zeromask_byte_pos < 0 or row.zeromask_byte_pos >= len(buf):
            raise DtStructureError(f"row '{name}': zero-mask byte position out of range")
    else:
        row.value_byte_pos = target_value_pos
        if row.value_byte_pos >= len(buf):
            raise DtStructureError(f"row '{name}': value byte position overruns buffer")
    return row


def parse_rows(uexp_bytes: bytes, names: List[str]) -> List[_RowInfo]:
    """DTのuexp全体を先頭から順に解析し、各行のbIsFullBodyEquipment状態を
    集めて返す。想定外の構造に出会ったら DtStructureError で即停止する。
    """
    pos, num_entries = _parse_prefix(uexp_bytes)
    rows: List[_RowInfo] = []
    for _ in range(num_entries):
        row = _parse_row(uexp_bytes, pos, names)
        rows.append(row)
        pos = row.row_end
    if pos > len(uexp_bytes):
        raise DtStructureError("row parsing overran the buffer")
    return rows


# --------------------------------------------------------------- patching

def _current_bool_value(uexp_bytes: bytes, row: _RowInfo) -> bool:
    if row.state == "zero":
        return False
    return uexp_bytes[row.value_byte_pos] != 0


def patch_full_body_equipment_flags(
    uexp_bytes: bytes,
    names: List[str],
    edits: Dict[str, bool],
) -> bytes:
    """DT_CharacterCreationMeshPresetTable_Equipments のuexpバイト列を受け取り、
    edits で指定した行名の bIsFullBodyEquipment を指定の真偽値へ書き換えた
    新しいバイト列を返す。

    Args:
        uexp_bytes: パッチ前のuexp全体。
        names: 対応する.uassetのNameMap(vp_core.read_names()の戻り値と同じ
            並び)。行名解決(§2.3「名前ベース」)に使う。
        edits: {行名: 望む真偽値}。1件でも解決できない行名があれば
            何も書き換えずValueErrorを送出する(部分適用しない)。

    Returns:
        パッチ後のuexpバイト列(新しいbytesオブジェクト)。edits に無い
        行・フィールドは一切変更されない。

    Raises:
        DtStructureError: 想定外のバイト構造に遭遇した場合(書き込み前・
            書き込み後どちらの検証でも)。フラグ書き込みを黙ってスキップ
            して変換を続行することはしない。
        ValueError: edits に無効な行名が含まれる場合。
    """
    if not edits:
        raise ValueError("edits must not be empty")

    rows = parse_rows(uexp_bytes, names)
    by_name: Dict[str, List[_RowInfo]] = {}
    for row in rows:
        by_name.setdefault(row.name, []).append(row)

    missing = [n for n in edits if n not in by_name]
    if missing:
        raise ValueError(f"row name(s) not found in DataTable: {missing}")
    ambiguous = [n for n in edits if len(by_name[n]) > 1]
    if ambiguous:
        raise DtStructureError(f"row name(s) matched more than once (ambiguous FName): {ambiguous}")

    # 書き換え前の全行の現況(negative control用ベースライン)。
    original_values: Dict[str, bool] = {row.name: _current_bool_value(uexp_bytes, row) for row in rows}

    ops: List[Tuple[str, int, int]] = []  # (kind, pos, byte_value)
    for row_name, desired in edits.items():
        row = by_name[row_name][0]
        current = original_values[row_name]
        if current == desired:
            continue  # 既に望む値: 無変更
        if row.state == "zero":
            # False -> True: zero-maskビットをクリア + 値バイト0x01を挿入。
            assert desired is True
            orig_mask_byte = uexp_bytes[row.zeromask_byte_pos]
            new_mask_byte = orig_mask_byte & ~(1 << row.zeromask_bit) & 0xFF
            ops.append(("replace", row.zeromask_byte_pos, new_mask_byte))
            ops.append(("insert", row.insert_pos, 0x01))
        else:
            # フィールドは既に存在する(True<->Falseの単純な値置換のみ、
            # ヘッダ・zero-maskは不変)。True->Falseは実測で確認済み、
            # 「値0のまま存在する」行からTrue化する対称ケースは本DTの
            # 実データでは未観測だが、同じ「既に存在する」前提で安全に
            # 類推できる(§12不確実点1、完了報告に明記)。
            ops.append(("replace", row.value_byte_pos, 0x01 if desired else 0x00))

    if not ops:
        return uexp_bytes  # 何も変更が要らない

    patched = _apply_ops(uexp_bytes, ops)

    # ---- 書き込み後の構造検証(§2.3: 前後両方で検証) ----
    new_rows = parse_rows(patched, names)
    if len(new_rows) != len(rows):
        raise DtStructureError(
            f"post-write verification failed: row count changed {len(rows)} -> {len(new_rows)}")
    new_by_name: Dict[str, _RowInfo] = {}
    for row in new_rows:
        new_by_name.setdefault(row.name, []).append(row)
    for i, (old_row, new_row) in enumerate(zip(rows, new_rows)):
        if old_row.name != new_row.name:
            raise DtStructureError(
                f"post-write verification failed: row order/name changed at index {i}: "
                f"{old_row.name!r} -> {new_row.name!r}")

    for row_name, desired in edits.items():
        actual = _current_bool_value(patched, new_by_name[row_name][0])
        if actual != desired:
            raise DtStructureError(
                f"post-write verification failed: row '{row_name}' expected "
                f"{TARGET_FIELD_NAME}={desired}, got {actual}")

    # negative control: 対象外の全行が不変であること。
    for row in new_rows:
        if row.name in edits:
            continue
        actual = _current_bool_value(patched, row)
        expected = original_values[row.name]
        if actual != expected:
            raise DtStructureError(
                f"post-write verification failed: untouched row '{row.name}' changed "
                f"{TARGET_FIELD_NAME} {expected} -> {actual} (unexpected side effect)")

    return patched


def _apply_ops(buf: bytes, ops: List[Tuple[str, int, int]]) -> bytes:
    """('replace', pos, byte) と ('insert', pos, byte) の操作列を、元の
    バッファに対して位置順に適用し、新しいbytesを組み立てる。"""
    ops_sorted = sorted(ops, key=lambda o: o[1])
    out = bytearray()
    cursor = 0
    for kind, pos, value in ops_sorted:
        if pos < cursor:
            raise DtStructureError(f"internal error: overlapping edits at {pos} (cursor={cursor})")
        out += buf[cursor:pos]
        out.append(value)
        if kind == "replace":
            cursor = pos + 1
        elif kind == "insert":
            cursor = pos
        else:
            raise AssertionError(f"unknown op kind {kind!r}")
    out += buf[cursor:]
    return bytes(out)


# --------------------------------------------------------- .uasset SerialSize
# dev#1198 WP-B5b-fix: 起動即死クラッシュの根治(.uasset側の追随)。
#
# ## 背景
#
# patch_full_body_equipment_flags() は .uexp を可変長編集する(False->True
# 1行につき+1バイト挿入)。一方 build_pak_from_avatar.py の _run_dt_patch()
# は .uasset をバニラのまま無変更で書き出していた。UEはロード時に
# .uasset のエクスポートテーブル(FObjectExport)の SerialSize と .uexp の
# 実サイズを照合するため、不一致だと
#   LowLevelFatalError ... Serial size mismatch: Got 47358, Expected 47353
#   (AsyncLoading.cpp:3558)
# で起動直後に即死する(shapellビルドで5行挿入 -> 差ちょうど5、実測一致。
# 解析全容: work/lab1_crash_triage/parse_export_table.py)。
#
# ## 実測で確認したFPackageFileSummaryのレイアウト
#
# Palworld 5.1 cooked (PKG_FilterEditorOnly設定・単一export) の
# DT_CharacterCreationMeshPresetTable_Equipments.uasset を、work/rd_1198/
# extract/(バニラ)と work/rd_1198_flagtest/dt_patch/out/(UAssetAPIが35行
# 編集して再直列化した実物、.uexpは+31バイト)とで全バイト突合したところ、
# **差分はちょうど2箇所・3バイトだけ**だった:
#   - オフセット260: BulkDataStartOffset(int64)の下位バイトが+31
#   - オフセット29872-29873: 単一exportのSerialSize(int64)の下位2バイトが+31
# これは「BulkDataStartOffset == 該当exportのSerialOffset + SerialSize」と
# いう不変条件(このDTには実bulk dataが無く、単一exportが.uexpの終端まで
# 占有するため)から導かれる自然な帰結であり、他のヘッダフィールド
# (NameOffset/ExportOffset/ImportOffset/DependsOffset等、いずれも.uasset内
# の位置を指すだけで.uexpの内容に依存しない)は一切変化しない。
#
# 本モジュールはこの2フィールドだけをuexpサイズ差分から機械的に再計算する
# (UAssetAPIのような汎用シリアライザは使わず、対象1資産専用の最小パッチ、
# dt_flag_patcher.py全体の設計方針を踏襲)。想定外の構造(FilterEditorOnly
# 未設定、export_count!=1、BulkDataStartOffsetの不変条件が崩れている等)に
# 出会ったら即DtStructureErrorで停止する。

_PACKAGE_TAG = 0x9E2A83C1
_PKG_FILTER_EDITOR_ONLY = 0x80000000


@dataclass(frozen=True)
class _UassetPatchPoints:
    serial_size_pos: int       # 単一exportのSerialSizeフィールドの絶対位置(int64)
    serial_offset_value: int   # 同exportのSerialOffset(参考値、本パッチでは不変)
    old_serial_size: int
    bulk_data_start_pos: int   # パッケージレベルBulkDataStartOffsetの絶対位置(int64)
    old_bulk_data_start: int


def _locate_uasset_patch_points(buf: bytes) -> _UassetPatchPoints:
    """FPackageFileSummary を先頭から順に歩き、単一exportのSerialSize
    フィールドと、パッケージレベルBulkDataStartOffsetフィールドの絶対
    バイト位置・現在値を求める。上のモジュール注記のとおり、この2箇所が
    .uexpサイズ変化に追随してパッチすべき唯一の場所(実測突合で確認済み)。

    想定外の構造(このDTの実測条件から外れるもの)に出会ったら
    DtStructureError で即座に停止する(黙って誤った位置を返さない)。
    """
    pos = 0
    tag, pos = _read_u32(buf, pos)
    if tag != _PACKAGE_TAG:
        raise DtStructureError(f".uasset: bad package tag {tag:#x} (expected {_PACKAGE_TAG:#x})")
    legacy_ver, pos = _read_i32(buf, pos)
    if legacy_ver != -8:
        raise DtStructureError(
            f".uasset: unsupported LegacyFileVersion {legacy_ver} (this parser is "
            "tuned for -8 / UE5.1 cooked Palworld packages; refusing to guess at a "
            "different on-disk layout)")
    _ue3_ver, pos = _read_i32(buf, pos)
    _file_ver_ue4, pos = _read_i32(buf, pos)
    _file_ver_ue5, pos = _read_i32(buf, pos)  # legacy_ver <= -8 なので必ず存在
    _file_ver_licensee, pos = _read_i32(buf, pos)
    num_cv, pos = _read_i32(buf, pos)
    if num_cv < 0:
        raise DtStructureError(f".uasset: negative CustomVersion count at header (pos={pos})")
    pos += num_cv * 20  # FGuid(16B) + int32 version
    _total_header_size, pos = _read_i32(buf, pos)
    pos = _skip_fstring_header(buf, pos)  # FolderName
    package_flags, pos = _read_u32(buf, pos)
    _name_count, pos = _read_i32(buf, pos)
    _name_offset, pos = _read_i32(buf, pos)
    if not (package_flags & _PKG_FILTER_EDITOR_ONLY):
        raise DtStructureError(
            ".uasset: PKG_FilterEditorOnly is not set on this package "
            f"(PackageFlags={package_flags:#x}) -- this parser only supports cooked "
            "(editor-only-data-stripped) packages, refusing to guess at the "
            "non-cooked field layout (which additionally serializes LocalizationId/"
            "PersistentGuid/OwnerPersistentGuid)")
    _soft_obj_paths_count, pos = _read_i32(buf, pos)
    _soft_obj_paths_offset, pos = _read_i32(buf, pos)
    # LocalizationId(FString) はPKG_FilterEditorOnly設定時は非直列化(スキップ)。
    _gatherable_text_count, pos = _read_i32(buf, pos)
    _gatherable_text_offset, pos = _read_i32(buf, pos)
    export_count, pos = _read_i32(buf, pos)
    export_offset, pos = _read_i32(buf, pos)
    _import_count, pos = _read_i32(buf, pos)
    _import_offset, pos = _read_i32(buf, pos)
    _depends_offset, pos = _read_i32(buf, pos)
    _soft_pkg_refs_count, pos = _read_i32(buf, pos)
    _soft_pkg_refs_offset, pos = _read_i32(buf, pos)
    _searchable_names_offset, pos = _read_i32(buf, pos)
    _thumbnail_table_offset, pos = _read_i32(buf, pos)
    if pos + 16 > len(buf):
        raise DtStructureError(f".uasset: PackageGuid overruns buffer at {pos}")
    pos += 16  # PackageGuid
    # PersistentGuid/OwnerPersistentGuid はPKG_FilterEditorOnly設定時は非直列化。
    gen_count, pos = _read_i32(buf, pos)
    if not (0 <= gen_count <= 64):
        raise DtStructureError(f".uasset: implausible Generations count {gen_count}")
    for _ in range(gen_count):
        if pos + 8 > len(buf):
            raise DtStructureError(f".uasset: FGenerationInfo overruns buffer at {pos}")
        pos += 8  # FGenerationInfo: ExportCount(i32) + NameCount(i32)
    for _label in ("SavedByEngineVersion", "CompatibleWithEngineVersion"):
        if pos + 10 > len(buf):
            raise DtStructureError(f".uasset: {_label} overruns buffer at {pos}")
        pos += 6  # Major/Minor/Patch (uint16 x3)
        pos += 4  # Changelist (uint32)
        pos = _skip_fstring_header(buf, pos)  # Branch
    _compression_flags, pos = _read_u32(buf, pos)
    num_compressed_chunks, pos = _read_i32(buf, pos)
    if num_compressed_chunks != 0:
        raise DtStructureError(
            f".uasset: non-zero CompressedChunks count {num_compressed_chunks} -- "
            "not observed in any Palworld DT asset used by this pipeline, refusing "
            "to guess at FCompressedChunk's field layout")
    _package_source, pos = _read_u32(buf, pos)
    num_additional_pkgs, pos = _read_i32(buf, pos)
    if num_additional_pkgs < 0:
        raise DtStructureError(f".uasset: negative AdditionalPackagesToCook count at {pos}")
    for _ in range(num_additional_pkgs):
        pos = _skip_fstring_header(buf, pos)
    _asset_registry_data_offset, pos = _read_i32(buf, pos)
    bulk_data_start_pos = pos
    old_bulk_data_start, pos = _read_i64(buf, pos)

    if export_count != 1:
        raise DtStructureError(
            f".uasset: expected exactly 1 export in this DataTable package, got "
            f"{export_count} -- unsupported structure, refusing to guess")
    if not (0 < export_offset < len(buf)):
        raise DtStructureError(f".uasset: implausible ExportOffset {export_offset}")

    # FObjectExport: ClassIndex/SuperIndex/TemplateIndex/OuterIndex(各int32) +
    # ObjectName(FName, 8B) + ObjectFlags(uint32) の後にSerialSize(int64)、
    # 続いてSerialOffset(int64)。本パッチはSerialSize/SerialOffsetの手前
    # フィールドの内容自体を解釈しないので固定長で読み飛ばしてよい。
    epos = export_offset + (4 * 4) + 8 + 4
    if epos + 16 > len(buf):
        raise DtStructureError(f".uasset: export entry overruns buffer at {epos}")
    serial_size_pos = epos
    old_serial_size, epos = _read_i64(buf, epos)
    serial_offset_value, epos = _read_i64(buf, epos)

    if old_bulk_data_start != serial_offset_value + old_serial_size:
        raise DtStructureError(
            ".uasset: BulkDataStartOffset does not equal SerialOffset+SerialSize of "
            f"the single export ({old_bulk_data_start} != {serial_offset_value} + "
            f"{old_serial_size}) -- unexpected structure (extra bulk data chunk?), "
            "refusing to guess how to patch it")

    return _UassetPatchPoints(
        serial_size_pos=serial_size_pos,
        serial_offset_value=serial_offset_value,
        old_serial_size=old_serial_size,
        bulk_data_start_pos=bulk_data_start_pos,
        old_bulk_data_start=old_bulk_data_start,
    )


def patch_uasset_serial_size(uasset_bytes: bytes, uexp_size_delta: int) -> bytes:
    """dev#1198 WP-B5b-fix: patch_full_body_equipment_flags() が .uexp に
    加えた可変長編集のサイズ差分(uexp_size_delta、正=増加/0=無変更)を、
    対応する .uasset のエクスポートテーブルSerialSizeと、そこから導出
    される BulkDataStartOffset に機械的に反映する。

    Args:
        uasset_bytes: パッチ前(バニラ)の .uasset 全体。
        uexp_size_delta: len(patched_uexp) - len(original_uexp)。0なら
            uasset_bytes をそのまま返す(無変更のuexpに対応する場合)。

    Returns:
        パッチ後の .uasset バイト列(新しいbytesオブジェクト)。
        SerialSize/BulkDataStartOffset 以外は一切変更されない。

    Raises:
        DtStructureError: 想定外のバイト構造に遭遇した場合(書き込み前・
            書き込み後どちらの検証でも)。
    """
    if uexp_size_delta == 0:
        return uasset_bytes

    points = _locate_uasset_patch_points(uasset_bytes)
    new_serial_size = points.old_serial_size + uexp_size_delta
    if new_serial_size <= 0:
        raise DtStructureError(
            f".uasset: computed new SerialSize is not positive: {new_serial_size} "
            f"(old={points.old_serial_size}, delta={uexp_size_delta})")
    new_bulk_data_start = points.old_bulk_data_start + uexp_size_delta

    out = bytearray(uasset_bytes)
    struct.pack_into("<q", out, points.serial_size_pos, new_serial_size)
    struct.pack_into("<q", out, points.bulk_data_start_pos, new_bulk_data_start)
    patched = bytes(out)

    # ---- 書き込み後の構造検証(dt_flag_patcher.py全体の流儀どおり) ----
    verify = _locate_uasset_patch_points(patched)
    if verify.old_serial_size != new_serial_size:
        raise DtStructureError(
            "post-write verification failed: .uasset SerialSize expected "
            f"{new_serial_size}, got {verify.old_serial_size}")
    if verify.old_bulk_data_start != new_bulk_data_start:
        raise DtStructureError(
            "post-write verification failed: .uasset BulkDataStartOffset expected "
            f"{new_bulk_data_start}, got {verify.old_bulk_data_start}")
    # negative control: SerialSize/BulkDataStartOffset以外の全バイトが不変。
    if len(patched) != len(uasset_bytes):
        raise DtStructureError(
            "post-write verification failed: .uasset length changed "
            f"{len(uasset_bytes)} -> {len(patched)} (this patch must never resize "
            "the .uasset)")
    changed = [
        i for i in range(len(uasset_bytes))
        if uasset_bytes[i] != patched[i]
        and not (points.serial_size_pos <= i < points.serial_size_pos + 8)
        and not (points.bulk_data_start_pos <= i < points.bulk_data_start_pos + 8)
    ]
    if changed:
        raise DtStructureError(
            "post-write verification failed: unexpected byte(s) changed outside "
            f"SerialSize/BulkDataStartOffset at offsets {changed[:10]}"
            f"{', ...' if len(changed) > 10 else ''}")

    return patched


def read_export_serial_size(uasset_bytes: bytes) -> int:
    """dev#1198 WP-B5b-fix: 外部呼び出し元(preflight_pak.pyの検品ゲート等)
    向けの読み取り専用API。.uasset の単一exportに宣言されたSerialSizeを
    返す(_locate_uasset_patch_points()と同じ構造検証を経て取得する — 想定外
    の構造ならDtStructureErrorを送出する)。パッチは一切行わない。"""
    return _locate_uasset_patch_points(uasset_bytes).old_serial_size
