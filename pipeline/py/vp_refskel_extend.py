# -*- coding: utf-8 -*-
"""vp_refskel_extend.py -- cooked装備SKのRefSkeletonへの追加骨登録(dev#19)。

「共有骨格(SK_PalHuman)には実在するが、その装備SKのRefSkeletonに未登録の骨」
を、cooked SK(uasset+uexp)へ静的バイナリ操作だけで追加登録する。
実証: work\\rd_19_refskel\\(2026-08-11、静的検証38/38+注入試作9/9 PASS)。

用途(dev#19 R3統合): sway donorファミリー(例: Kigurumi001尻尾8節)の骨を
全装備SKのテンプレートへ一律に事前登録し、装備に依らず同一donorチェーンへ
ウェイトを載せられるようにする(「全装備一律」原則の充足)。R2b-3の
試着室pak実験が持っていた「donor骨が元々あるSKにしか注入できない」制約を
これで撤廃する。

変更するもの(完全列挙):
  uexp: FReferenceSkeletonの3配列(RawRefBoneInfo/RawRefBonePose/
        RawNameToIndexMap)の末尾追記+count、LOD0 RequiredBonesの末尾追記+count
  uasset: NameMap末尾へのFNameEntrySerialized追記(実測一致済みハッシュ)、
        FPackageFileSummaryの絶対オフセット群・NameCount・Generations、
        ExportMapのSerialSize/SerialOffset
変更しないもの:
  Import Table / PreloadDependencies(U22-U39の毒=Import Table追加は
  本手法に含まれない)、NamesReferencedFromExportDataCount(legacy
  FLinkerLoadは全NameMap先読みのため未使用)、頂点/ウェイト/マテリアル全域。

追加骨のバインドFTransformは refskel_{family}_{gender}.json(extract_vanilla.py
"sway_extra_family" の出力。donorexp WP(2026-08-11、issue#19)で家系ごとの
一意名へ変更、旧固定名refskel_extra_{gender}.jsonは廃止済み)の倍精度値を
そのまま '<d' で再パックする。
Pythonのjson<->floatはIEEE binary64を往復保存するため、バニラdonor SKの
生バイトと完全一致する(rd_19_refskelでraw copy版とのバイト同値を実証済み)。

標準ライブラリのみ使用(pip禁止)。
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core as core            # noqa: E402
import parse_sk_structure as sks  # noqa: E402
import parse_uasset_header as uh  # noqa: E402
import sway_shared_skeleton as sss  # noqa: E402 (dev#1508 hubwire final: 既存donor骨の親上書き)

TAG = "vp_refskel_extend"


class RefskelExtendError(RuntimeError):
    pass


# ---------------------------------------------------------------- FName hash
# FNameEntrySerializedの末尾4バイト = NonCasePreservingHash(uint16) +
# CasePreservingHash(uint16)。UE5.1のロード側は読み捨てる(実挙動に影響なし)
# が、cooker出力と見分けが付かない形で追記するため正確に計算する。
# 実装はUE5.1 FCrc::Strihash_DEPRECATED(ANSI特殊化、1文字1ラウンド)と
# FCrc::StrCrc32。バニラOldCloth001 M/F全213名で実バイト一致を確認済み
# (work\rd_19_refskel\verify_name_hashes.py)。

_CRC32_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0xEDB88320 if (_c & 1) else (_c >> 1)
    _CRC32_TABLE.append(_c)

_CRC_DEP_TABLE = []
for _i in range(256):
    _c = _i << 24
    for _ in range(8):
        _c = ((_c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if (_c & 0x80000000) \
            else (_c << 1) & 0xFFFFFFFF
    _CRC_DEP_TABLE.append(_c)


def str_crc32(s):
    """FCrc::StrCrc32(文字を4バイトとして処理する標準CRC-32変種)。"""
    crc = 0xFFFFFFFF
    for ch in s:
        v = ord(ch)
        for _ in range(4):
            crc = (crc >> 8) ^ _CRC32_TABLE[(crc ^ v) & 0xFF]
            v >>= 8
    return crc ^ 0xFFFFFFFF


def strihash_deprecated(s):
    """FCrc::Strihash_DEPRECATED(ANSI特殊化、大文字化+1文字1ラウンド)。"""
    h = 0
    for ch in s:
        b = ord(ch.upper()) & 0xFF
        h = ((h >> 8) & 0x00FFFFFF) ^ _CRC_DEP_TABLE[(h ^ b) & 0xFF]
    return h


def name_entry_bytes(s):
    """FNameEntrySerialized 1件のバイト列(ASCII名前提)。"""
    if not s or any(ord(c) > 127 for c in s):
        raise RefskelExtendError(f"non-ASCII/empty name unsupported: {s!r}")
    b = s.encode("ascii") + b"\x00"
    return (struct.pack("<i", len(b)) + b
            + struct.pack("<HH", strihash_deprecated(s) & 0xFFFF,
                          str_crc32(s) & 0xFFFF))


# ------------------------------------------------------- package summary(全域)

def parse_full_summary(data):
    """FPackageFileSummary全フィールド(名前->{pos,val})を前方パースする。

    UE5.1 cooked・FilterEditorOnly・unversioned前提(parse_uasset_header.pyと
    同じ前提)。前提が崩れたら例外で停止する(安全側)。バイト会計は
    summary終端==NameOffset、TotalHeaderSize==ファイルサイズの2点で自己検証。
    """
    r = uh._Reader(data, 0)
    f = {}

    def rec(name, kind):
        pos = r.off
        v = {"i32": r.i32, "u32": r.u32, "i64": r.i64}[kind]()
        f[name] = {"pos": pos, "val": v, "kind": kind}
        return v

    if rec("magic", "u32") != 0x9E2A83C1:
        raise RefskelExtendError("uasset magic mismatch")
    if rec("legacy_file_version", "i32") != -8:
        raise RefskelExtendError("legacy file version != -8 (UE5系cooked前提)")
    rec("legacy_ue3_version", "i32")
    rec("file_version_ue4", "i32")
    rec("file_version_ue5", "i32")
    rec("file_version_licensee", "i32")
    if rec("custom_version_count", "i32") != 0:
        raise RefskelExtendError("custom versions unsupported")
    rec("total_header_size", "i32")
    r.fstring()  # PackageName
    if not (rec("package_flags", "u32") & uh.PKG_FILTER_EDITOR_ONLY):
        raise RefskelExtendError("not FilterEditorOnly")
    rec("name_count", "i32")
    rec("name_offset", "i32")
    rec("soft_object_paths_count", "i32")
    rec("soft_object_paths_offset", "i32")
    rec("gatherable_text_count", "i32")
    rec("gatherable_text_offset", "i32")
    rec("export_count", "i32")
    rec("export_offset", "i32")
    rec("import_count", "i32")
    rec("import_offset", "i32")
    rec("depends_offset", "i32")
    rec("soft_package_references_count", "i32")
    rec("soft_package_references_offset", "i32")
    rec("searchable_names_offset", "i32")
    rec("thumbnail_table_offset", "i32")
    r.bytes(16)  # Guid
    gen_count = rec("generations_count", "i32")
    gens = []
    for _ in range(gen_count):
        p = r.off
        ec = r.i32()
        nc = r.i32()
        gens.append({"pos": p, "export_count": ec, "name_count": nc})
    f["_generations"] = gens
    for _tag in ("saved_by", "compatible_with"):  # FEngineVersion x2
        r.bytes(10)   # u16 major/minor/patch + u32 changelist
        r.fstring()   # branch
    rec("compression_flags", "u32")
    if rec("compressed_chunks_count", "i32") != 0:
        raise RefskelExtendError("compressed chunks unsupported")
    rec("package_source", "u32")
    if rec("additional_packages_to_cook_count", "i32") != 0:
        raise RefskelExtendError("additional packages unsupported")
    rec("asset_registry_data_offset", "i32")
    rec("bulk_data_start_offset", "i64")
    rec("world_tile_info_offset", "i32")
    if rec("chunk_ids_count", "i32") != 0:
        raise RefskelExtendError("chunk ids unsupported")
    rec("preload_dependency_count", "i32")
    rec("preload_dependency_offset", "i32")
    rec("names_referenced_from_export_data_count", "i32")
    rec("payload_toc_offset", "i64")
    f["_summary_end"] = r.off
    if f["_summary_end"] != f["name_offset"]["val"]:
        raise RefskelExtendError(
            f"summary end ({f['_summary_end']}) != NameOffset "
            f"({f['name_offset']['val']})")
    if f["total_header_size"]["val"] != len(data):
        raise RefskelExtendError("TotalHeaderSize != uasset size")
    return f


def _name_block_end(data, name_offset, name_count):
    off = name_offset
    for _ in range(name_count):
        (slen,) = struct.unpack_from("<i", data, off)
        off += 4
        off += slen if slen >= 0 else -slen * 2
        off += 4
    return off


# ------------------------------------------------------------------- 拡張本体

def pack_transform80(bone):
    """refskel形式の1骨({quat,pos,scale}、各倍精度)を80Bにパックする。"""
    vals = list(bone["quat"]) + list(bone["pos"]) + list(bone["scale"])
    if len(vals) != 10:
        raise RefskelExtendError(f"bone transform malformed: {bone}")
    return struct.pack("<10d", *vals)


def extend_sk_refskeleton(uasset_path, uexp_path, new_bones,
                          out_uasset_path, out_uexp_path):
    """cooked SK 1体のRefSkeletonへnew_bonesを追加登録して書き出す。

    new_bones: [{"name","parent","quat","pos","scale"}, ...](チェーン順。
    parentは対象SKの既存骨名、または列内の先行する骨名)。
    戻り値: 会計dict(delta等)。既に登録済みの名前があれば例外(呼び出し側で
    冪等化したい場合は先にRefSkeletonを読んで差分だけ渡すこと)。
    """
    with open(uasset_path, "rb") as f:
        ua = f.read()
    with open(uexp_path, "rb") as f:
        ux = f.read()

    names = core.read_names(uasset_path)
    base_name_count = len(names)
    add_n = len(new_bones)
    if add_n == 0:
        raise RefskelExtendError("new_bones is empty")
    new_names = [b["name"] for b in new_bones]
    for nm in new_names:
        if nm in names:
            raise RefskelExtendError(f"name already present in NameMap: {nm}")

    # ---- uexp: RefSkeleton 3配列の位置確定(全数整合検査つき) ----
    bones, _transforms, tsize, _data, tpos = core.find_refskeleton(
        uexp_path, names, with_offset=True)
    if tsize != 80:
        raise RefskelExtendError(f"transform size != 80 (doubles): {tsize}")
    n = len(bones)
    bone_names = [b for b, _p in bones]
    for nm in new_names:
        if nm in bone_names:
            raise RefskelExtendError(f"bone already registered: {nm}")

    # 親解決(既存骨 or 先行する追加骨)
    parent_idx = []
    for k, b in enumerate(new_bones):
        p = b["parent"]
        if p in bone_names:
            parent_idx.append(bone_names.index(p))
        elif p in new_names[:k]:
            parent_idx.append(n + new_names.index(p))
        else:
            raise RefskelExtendError(
                f"parent {p!r} of {b['name']!r} not found "
                "(must be an existing bone or an earlier new bone)")

    bi_count_pos = tpos - 4 - n * 12 - 4
    if struct.unpack_from("<i", ux, bi_count_pos)[0] != n:
        raise RefskelExtendError("bone info count field mismatch")
    bi_end = bi_count_pos + 4 + n * 12
    if struct.unpack_from("<i", ux, bi_end)[0] != n:
        raise RefskelExtendError("transform count field mismatch")
    tf_end = tpos + n * 80
    if struct.unpack_from("<i", ux, tf_end)[0] != n:
        raise RefskelExtendError("NameToIndexMap count field mismatch")
    map_data = tf_end + 4
    for i in range(n):
        idx, num, val = struct.unpack_from("<iii", ux, map_data + i * 12)
        nm = names[idx] if num == 0 else f"{names[idx]}_{num - 1}"
        if val != i or nm != bone_names[i]:
            raise RefskelExtendError(f"NameToIndexMap[{i}] mismatch")
    map_end = map_data + n * 12

    s = sks.parse_sk_structure(uexp_path, uasset_path)
    rb_off = s["required_bones_offset"]
    rb_vals = s["required_bones"]
    if rb_vals != list(range(n)):
        raise RefskelExtendError(
            "RequiredBones is not the full contiguous list (バニラ前提が崩れた)")
    rb_end = rb_off + 4 + len(rb_vals) * 2

    ins_bi = b"".join(
        struct.pack("<iii", base_name_count + k, 0, parent_idx[k])
        for k in range(add_n))
    ins_tf = b"".join(pack_transform80(b) for b in new_bones)
    ins_map = b"".join(
        struct.pack("<iii", base_name_count + k, 0, n + k)
        for k in range(add_n))
    ins_rb = struct.pack(f"<{add_n}H", *range(n, n + add_n))

    new_ux = bytearray()
    new_ux += ux[:bi_count_pos]
    new_ux += struct.pack("<i", n + add_n)
    new_ux += ux[bi_count_pos + 4:bi_end]
    new_ux += ins_bi
    new_ux += struct.pack("<i", n + add_n)
    new_ux += ux[tpos:tf_end]
    new_ux += ins_tf
    new_ux += struct.pack("<i", n + add_n)
    new_ux += ux[map_data:map_end]
    new_ux += ins_map
    new_ux += ux[map_end:rb_off]
    new_ux += struct.pack("<i", n + add_n)
    new_ux += ux[rb_off + 4:rb_end]
    new_ux += ins_rb
    new_ux += ux[rb_end:]
    delta_uexp = len(new_ux) - len(ux)
    if delta_uexp != add_n * (12 + 80 + 12 + 2):
        raise RefskelExtendError("delta_uexp accounting mismatch")

    # ---- uasset ----
    f_sum = parse_full_summary(ua)
    names_end = _name_block_end(ua, f_sum["name_offset"]["val"], base_name_count)
    ins_names = b"".join(name_entry_bytes(nm) for nm in new_names)
    delta_n = len(ins_names)

    new_ua = bytearray(ua[:names_end] + ins_names + ua[names_end:])
    struct.pack_into("<i", new_ua, f_sum["name_count"]["pos"],
                     base_name_count + add_n)
    struct.pack_into("<i", new_ua, f_sum["total_header_size"]["pos"],
                     f_sum["total_header_size"]["val"] + delta_n)
    for gen in f_sum["_generations"]:
        struct.pack_into("<i", new_ua, gen["pos"] + 4,
                         gen["name_count"] + add_n)
    for key in ("soft_object_paths_offset", "gatherable_text_offset",
                "export_offset", "import_offset", "depends_offset",
                "soft_package_references_offset", "searchable_names_offset",
                "thumbnail_table_offset", "asset_registry_data_offset",
                "world_tile_info_offset", "preload_dependency_offset"):
        v = f_sum[key]["val"]
        if v > 0 and v >= names_end:
            struct.pack_into("<i", new_ua, f_sum[key]["pos"], v + delta_n)
        elif v > 0:
            raise RefskelExtendError(f"{key}={v} points before NameMap end")
    struct.pack_into("<q", new_ua, f_sum["bulk_data_start_offset"]["pos"],
                     f_sum["bulk_data_start_offset"]["val"]
                     + delta_n + delta_uexp)
    # dev#19 R3統合(rd_19_refskel PROPOSAL リスクR4): NamesReferencedFrom
    # ExportDataCount(legacy FLinkerLoad::SerializeNameMapは全NameMap先読み
    # のため実際には未使用の値、IoStore/ALT2系最適化専用)を追加名数だけ
    # 引き上げておく。過大方向は安全(「全部先読み」に退化するだけ)なので、
    # 追加名は常にこの値未満のインデックスにも来ないため厳密対応は不要だが、
    # 据え置きより一貫性が高い1行対策。
    struct.pack_into("<i", new_ua,
                     f_sum["names_referenced_from_export_data_count"]["pos"],
                     f_sum["names_referenced_from_export_data_count"]["val"]
                     + add_n)

    _summary0, exports = uh.parse_uasset_exports(uasset_path)
    asset_exports = [e for e in exports if e["b_is_asset"]]
    if len(asset_exports) != 1:
        raise RefskelExtendError("bIsAsset export not unique")
    main_export = asset_exports[0]
    main_end_abs = main_export["serial_offset"] + main_export["serial_size"]
    for e in exports:
        size_pos = e["serial_size_offset"] + delta_n
        off_pos = size_pos + 8
        new_size = e["serial_size"]
        new_off = e["serial_offset"] + delta_n
        if e is main_export:
            new_size += delta_uexp
        elif e["serial_offset"] >= main_end_abs:
            new_off += delta_uexp
        struct.pack_into("<q", new_ua, size_pos, new_size)
        struct.pack_into("<q", new_ua, off_pos, new_off)

    os.makedirs(os.path.dirname(out_uasset_path) or ".", exist_ok=True)
    with open(out_uasset_path, "wb") as fo:
        fo.write(new_ua)
    with open(out_uexp_path, "wb") as fo:
        fo.write(bytes(new_ux))
    return {"delta_n": delta_n, "delta_uexp": delta_uexp,
            "n_bones_before": n, "n_bones_after": n + add_n,
            "new_uasset_size": len(new_ua), "new_uexp_size": len(new_ux)}


def family_bones_from_refskel(refskel, chain_names):
    """refskel_{family}_{gender}.json(vp_core.load_refskel形式。呼び出し側が
    複数家系分をマージ済みのdictを渡してもよい)から、chain_names
    (チェーン順の骨名列)の追加骨仕様リストを組み立てる。"""
    out = []
    for nm in chain_names:
        b = refskel.get(nm)
        if b is None:
            raise RefskelExtendError(f"bone {nm!r} not in refskel_extra")
        out.append({"name": nm, "parent": b["parent"],
                    "quat": b["quat"], "pos": b["pos"], "scale": b["scale"]})
    return out


def resolve_missing_bone_chain(refskel_extra, missing_names, existing_bone_names):
    """dev#19 R3統合(rd_19_refskel PROPOSAL手順4の本流化配線が使う解決器)。

    対象SK自身のRefSkeletonに無い骨名の集合(missing_names、順不同でよい)を、
    refskel_extra(vp_core.load_refskel形式、{bone: {parent,quat,pos,scale}})の
    親ポインタだけを頼りに、extend_sk_refskeleton()が要求する「親が先」順の
    骨名リストへ**決定的に**組み立てる。

    missing_namesの親がexisting_bone_namesに無い場合は、その親自身も
    refskel_extraから辿って自動的に追加する(sway assignがチェーンの
    途中ボーンだけを要求していても、途中で切れた骨無し状態を作らない)。
    ソート順で解決を進めるため、同じ入力からは常に同じ出力順になる
    (pakバイト決定性の要件、docs参照)。

    戻り値: family_bones_from_refskel(refskel_extra, 戻り値)にそのまま
    渡せる骨名の順序付きリスト。missing_namesの祖先を辿ってもrefskel_extra/
    existing_bone_namesのどちらにも到達できない骨があれば RefskelExtendError。
    """
    resolved = set(existing_bone_names)
    needed = set()
    to_visit = list(missing_names)
    while to_visit:
        nm = to_visit.pop()
        if nm in needed or nm in resolved:
            continue
        b = refskel_extra.get(nm)
        if b is None:
            raise RefskelExtendError(f"bone {nm!r} not in refskel_extra")
        needed.add(nm)
        parent = b["parent"]
        if parent is not None and parent not in resolved:
            to_visit.append(parent)

    ordered = []
    remaining = set(needed)
    while remaining:
        progressed = False
        for nm in sorted(remaining):
            parent = refskel_extra[nm]["parent"]
            if parent is None or parent in resolved:
                ordered.append(nm)
                resolved.add(nm)
                remaining.discard(nm)
                progressed = True
        if not progressed:
            raise RefskelExtendError(
                f"cannot resolve parent chain for bone(s): {sorted(remaining)}")
    return ordered


def reparent_existing_bone(uexp_bytes, uasset_path, target_name, new_parent_name,
                            min_bones=40, max_bones=400):
    """dev#1508 hubwire final(未解決1修正): mesh SK(装備単体、数十〜数百骨)
    自身のRefSkeletonについて、**既に登録済みの**骨target_nameの親フィールド
    だけをnew_parent_nameへ内容だけ書き換える(配列長・NameMap不変、
    FTransform値は変更しない——実位置は`build_avatar_variant.
    compute_patched_local_positions()`がchibi_bone_world_head機構で
    reparent後にこのSKを再読込して別途パッチするため、ここではparentのみで
    十分。docstring: `build_pak_from_avatar._refskel_extend_overrides()`
    「既存donor骨の親上書き」節参照)。

    `sway_shared_skeleton.reparent_bone_content_only()`と全く同じアルゴリズム
    (scan_full_refskeleton()自体はボーン数レンジに依存しない汎用実装)だが、
    対象範囲が共有Skeleton(数千骨、既定min/max=1000/6000)ではなくmesh SK
    (vp_core.find_refskeleton()と同じ既定min/max=40/400)である点だけが違う
    ため、重複実装せずそちらへ委譲する。

    戻り値: (new_uexp_bytes, info)。トポロジ制約(親は常に子より前の配列
    インデックス)に違反する場合はRefskelExtendError(共有Skeleton側の
    SharedSkeletonErrorをこのモジュールの例外型へ変換して送出——このモジュール
    のAPI利用者はRefskelExtendErrorだけを捕まえればよい設計を維持する)。
    ボーン0番(root)を対象にすることもできない(同上の制約)。"""
    names = core.read_names(uasset_path)
    try:
        new_uexp, info = sss.reparent_bone_content_only(
            uexp_bytes, names, target_name, new_parent_name,
            new_local_transform=None,
            min_bones=min_bones, max_bones=max_bones)
    except sss.SharedSkeletonError as e:
        raise RefskelExtendError(str(e)) from e
    return new_uexp, info


def main():
    """CLI: 単体SKの拡張。
    使い方: python vp_refskel_extend.py <uasset> <refskel_extra.json>
            <chain_bone1,chain_bone2,...> <out_uasset>
    """
    if len(sys.argv) != 5:
        print(main.__doc__)
        sys.exit(2)
    uasset, refskel_json, chain_csv, out_uasset = sys.argv[1:5]
    with open(refskel_json, encoding="utf-8") as f:
        refskel = json.load(f)
    chain = chain_csv.split(",")
    new_bones = family_bones_from_refskel(refskel, chain)
    info = extend_sk_refskeleton(
        uasset, uasset[:-7] + ".uexp", new_bones,
        out_uasset, out_uasset[:-7] + ".uexp")
    print(f"[{TAG}] {os.path.basename(uasset)}: "
          f"{info['n_bones_before']} -> {info['n_bones_after']} bones "
          f"(delta uasset={info['delta_n']}B, uexp={info['delta_uexp']}B)")


if __name__ == "__main__":
    main()
