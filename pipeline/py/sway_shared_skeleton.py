# -*- coding: utf-8 -*-
"""sway_shared_skeleton.py -- 共有Skeleton(SK_PalHuman_Skeleton)のRefSkeleton
配列を「内容だけ」書き換えるための低レベルプリミティブ(dev#1508 W2a 第2段
「汎用ハブ配線」、issue https://github.com/pandrabox/DiveToPalworld-dev/issues/1508)。

正本仕様: `.devonly\\docs\\sway\\sway_wrapup\\SPEC.md` §5「工事項目」(ハブ設計規則)。設計・
実装の出所: `work\\rd_1423_extend\\scripts\\extend_shared_skeleton.py`
(`find_large_refskeleton`、共有Skeleton専用のRefSkeletonスキャナ)/
`work\\rd_1423_reparent\\scripts\\reparent_shared_skeleton.py`(`reparent_bone`、
内容だけの親子書き換え)の実装をロジック無改変で製品コードへ移設したもの。
研究レーンでは実機playtestまで検収済み(`work\\rd_1423_sleeve3\\RUN.md`、
2026-08-16: 「評価root骨の引っ越し(reparent、ABPバイト無改変)」単独では実機
クラッシュを起こさないこと、reparent後もPHYSICS判定(第1関節)を確認)。

## なぜ vp_core.find_refskeleton() を使わないか

`vp_core.find_refskeleton()`は装備単体メッシュ(数十〜数百骨)向けの安全域
(count<=400程度)を持つ。共有Skeleton(SK_PalHuman_Skeleton)は4079骨で
この上限を超えるため、誤検出を避けた専用スキャナ(本モジュールの
`scan_full_refskeleton()`)が要る——NameToIndexMap配列の全件整合性まで
確認できた候補だけを採用する点は`vp_core.find_refskeleton()`と同じ設計
(過検出防止)。

## 内容だけ書き換える理由(トポロジ不変条件)

UEのFReferenceSkeletonは親が常に子より前の配列インデックスを持つ
(RawRefBoneInfo配列の並び自体がこの不変条件を前提にしている)。本モジュールは
配列長・NameMap・exportテーブルを一切変えず、対象ボーン1件のparent_idx
フィールド(+任意でFTransform)だけをin-placeで上書きする——新規ボーン追加
(骨の総数を増やす、`vp_refskel_extend.py`系統)とは全く別の操作。
`new_parent_idx < target_idx` を要求し、満たさなければ拒否する(この不変条件
を壊す新しい親は許可しない安全策)。

## refskel問題の解決方式(dev#1508 W2a-2、選択理由)

full3(flatHaori 35鎖)は家系ごとに個別抽出したrefskel_{suffix}_{gender}.json
(6〜16家系ぶん)にBlender側の初期bindpose解決を依存させていた。ハブ設計は
「予約68本を除く自由骨プール(pak内約4079本)」からどの骨でも donor に選べる
必要があり、家系ごとの個別抽出ファイルを増やし続ける方式(full3のPlan A)は
本質的にスケールしない(新しい家系を使うたびに抽出作業が要る)。

本モジュールの`full_skeleton_catalog()`は、SK_PalHuman_Skeleton自身から
**全4079骨のrest transform(親子構造込み)を一度に取得する**——「ドナー骨単位の
rest情報をpakから直接得る」(より一般的な解決)を選んだ実装。任意の自由骨を
donorに選んでも、この関数の戻り値から直接rest transform(ローカル
quat/pos/scale)と親子構造を引ける。個別家系ごとの追加抽出ファイルは今後
不要になる(既存6家系分の`refskel_{suffix}_{gender}.json`は後方互換のため
当面併存させてよい——本モジュールはその廃止を強制しない)。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

TAG = "sway_shared_skeleton"

# 共有Skeleton(SK_PalHuman_Skeleton、実測4079骨)向けのRefSkeletonスキャナが
# 探す骨数レンジ。実データの安全マージンを持たせた値
# (work\rd_1423_extend\scripts\extend_shared_skeleton.pyの既定と同一)。
DEFAULT_MIN_BONES = 1000
DEFAULT_MAX_BONES = 6000


class SharedSkeletonError(RuntimeError):
    """共有Skeletonのスキャン・パッチに関する想定外エラー。黙って握り潰さず
    呼び出し側(build_pak_from_avatar.py等)を止めるためのシグナル
    (sway_abp_build.SwayAbpBuildErrorと同じ設計方針)。"""


@dataclass(frozen=True)
class RefSkeletonLocation:
    """共有Skeleton1体ぶんのRefSkeleton位置情報(uexpバイト列内オフセット群)。
    `reparent_bone_content_only()`/`full_skeleton_catalog()`が共有する内部形式。"""

    bones: Tuple[Tuple[str, int], ...]  # (name, parent_idx) 配列順
    tsize: int                          # FTransform 1件のバイト数(80=double)
    data: bytes                         # uexp全体(スキャン時点のスナップショット)
    bi_count_pos: int
    tpos: int
    map_count_pos: int
    map_data: int
    map_end: int


def scan_full_refskeleton(
    uexp_path_or_bytes,
    names: Sequence[str],
    min_bones: int = DEFAULT_MIN_BONES,
    max_bones: int = DEFAULT_MAX_BONES,
) -> RefSkeletonLocation:
    """共有Skeleton(数千骨規模)のRefSkeleton(RawRefBoneInfo+RawRefBonePose+
    RawNameToIndexMapの3配列)をuexpバイト列内から発見する。フィンガープリント
    スキャン方式——3配列の相互整合性(件数一致・NameToIndexMapの全件一致)まで
    確認できた候補だけを採用するため、`min_bones<=count<=max_bones`の範囲に
    別の配列が偶然存在しても誤検出しない(実データ4079骨での検証: 唯一の
    候補がヒットする、`work\\rd_1423_extend`のself-testで確認済み)。

    見つからなければ`SharedSkeletonError`。"""
    if isinstance(uexp_path_or_bytes, (bytes, bytearray)):
        data = bytes(uexp_path_or_bytes)
    else:
        with open(uexp_path_or_bytes, "rb") as f:
            data = f.read()
    n_names = len(names)

    for off in range(0, len(data) - 16):
        (count,) = struct.unpack_from("<i", data, off)
        if not (min_bones <= count <= max_bones):
            continue
        pos = off + 4
        if pos + count * 12 > len(data):
            continue
        ok = True
        bones: List[Tuple[str, int]] = []
        for i in range(count):
            idx, num, parent = struct.unpack_from("<iii", data, pos + i * 12)
            if not (0 <= idx < n_names) or not (0 <= num < 100000):
                ok = False
                break
            if i == 0 and parent != -1:
                ok = False
                break
            if i > 0 and not (0 <= parent < i):
                ok = False
                break
            name = names[idx] if num == 0 else f"{names[idx]}_{num - 1}"
            bones.append((name, parent))
        if not ok:
            continue
        tpos_count = pos + count * 12
        (tcount,) = struct.unpack_from("<i", data, tpos_count)
        if tcount != count:
            continue
        tpos = tpos_count + 4
        tsize: Optional[int] = None
        for fmt, size in (("<10d", 80), ("<10f", 40)):
            if tpos + count * size > len(data):
                continue
            vals0 = struct.unpack_from(fmt, data, tpos)
            qn = sum(v * v for v in vals0[0:4])
            if 0.99 < qn < 1.01:
                tsize = size
                break
        if tsize is None:
            continue
        tf_end = tpos + count * tsize

        map_count_pos = tf_end
        (map_count,) = struct.unpack_from("<i", data, map_count_pos)
        if map_count != count:
            continue
        map_data = map_count_pos + 4
        if map_data + count * 12 > len(data):
            continue
        map_ok = True
        for i in range(count):
            idx, num, val = struct.unpack_from("<iii", data, map_data + i * 12)
            nm = names[idx] if num == 0 else f"{names[idx]}_{num - 1}"
            if val != i or nm != bones[i][0]:
                map_ok = False
                break
        if not map_ok:
            continue
        map_end = map_data + count * 12
        return RefSkeletonLocation(
            bones=tuple(bones), tsize=tsize, data=data,
            bi_count_pos=off, tpos=tpos,
            map_count_pos=map_count_pos, map_data=map_data, map_end=map_end,
        )
    raise SharedSkeletonError(
        f"large RefSkeleton not found (min_bones={min_bones}, max_bones={max_bones})")


def full_skeleton_catalog(
    uasset_path: str, uexp_path: str,
    min_bones: int = DEFAULT_MIN_BONES, max_bones: int = DEFAULT_MAX_BONES,
) -> Dict[str, object]:
    """共有Skeleton(SK_PalHuman_Skeleton)から**全骨のrest transform**を
    抽出する(refskel問題の一般解、モジュールdocstring参照)。

    戻り値の形は`work\\rd_19_donorcatalog\\sk_palhuman_full.json`と同一
    ({"bone_count": int, "bones": [{"name","parent_idx","quat","pos","scale"},...]})
    ——既存の研究成果物と同じ契約を持たせることで、過去の検証済みスクリプト
    (`compute_umbrella_transforms.py`等)をそのまま流用できる。

    呼び出し元は`vp_core.read_names(uasset_path)`同等の処理を要するため、
    ここでは遅延importする(product coreとの循環import回避、
    `pipeline\\py\\vp_core.py`は本モジュールをimportしない一方通行)。
    """
    import os
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import vp_core  # noqa: E402

    names = vp_core.read_names(uasset_path)
    loc = scan_full_refskeleton(uexp_path, names, min_bones=min_bones, max_bones=max_bones)
    bones = []
    for i, (name, parent_idx) in enumerate(loc.bones):
        if loc.tsize == 80:
            vals = struct.unpack_from("<10d", loc.data, loc.tpos + i * 80)
        else:
            vals = struct.unpack_from("<10f", loc.data, loc.tpos + i * 40)
        quat = list(vals[0:4])
        pos = list(vals[4:7])
        scale = list(vals[7:10])
        bones.append({"name": name, "parent_idx": parent_idx,
                       "quat": quat, "pos": pos, "scale": scale})
    return {"source_uasset": uasset_path, "source_uexp": uexp_path,
            "bone_count": len(bones), "bones": bones}


# =====================================================================
# 内容だけの親子書き換え(reparent、配列長不変)
# =====================================================================

def reparent_bone_content_only(
    uexp_path_or_bytes,
    names: Sequence[str],
    target_name: str,
    new_parent_name: str,
    new_local_transform: Optional[Tuple[Sequence[float], Sequence[float], Sequence[float]]] = None,
    min_bones: int = DEFAULT_MIN_BONES,
    max_bones: int = DEFAULT_MAX_BONES,
) -> Tuple[bytes, Dict[str, object]]:
    """target_nameの親をnew_parent_nameへ「内容だけ」書き換えた新しいuexp
    バイト列を返す。戻り値: (new_uexp_bytes, info)。

    uasset側は一切変更不要(NameMapへの追加が無いため、呼び出し側はuassetを
    そのままコピーしてよい)。

    new_local_transform: (quat[4], pos[3], scale[3])。指定するとtarget_name
    のFTransform(80B、倍精度)も内容だけ上書きする。Noneなら親だけ変更し
    既存のローカル変換値をそのまま残す(旧親からの相対値を新親下でそのまま
    維持するため、ワールド位置は一般に変わる)。

    トポロジ不変条件(new_parent_idx < target_idx)を満たさない場合は
    `SharedSkeletonError`(親は常に子より前の配列インデックス、モジュール
    docstring参照)。ボーン0番(root、parent=-1固定)を対象にすることもできない。
    """
    loc = scan_full_refskeleton(uexp_path_or_bytes, names, min_bones=min_bones, max_bones=max_bones)
    ux = bytearray(loc.data)
    bones = loc.bones
    n = len(bones)
    bone_names = [b for b, _p in bones]

    if target_name not in bone_names:
        raise SharedSkeletonError(f"target bone not found in shared skeleton: {target_name!r}")
    if new_parent_name not in bone_names:
        raise SharedSkeletonError(f"new parent bone not found in shared skeleton: {new_parent_name!r}")

    target_idx = bone_names.index(target_name)
    new_parent_idx = bone_names.index(new_parent_name)
    old_parent_idx = bones[target_idx][1]

    if target_idx == 0:
        raise SharedSkeletonError("cannot reparent bone index 0 (root, parent must stay -1)")
    if not (0 <= new_parent_idx < target_idx):
        raise SharedSkeletonError(
            f"topology violation: new_parent_idx({new_parent_idx}) must be "
            f"< target_idx({target_idx}) for {target_name!r} -> {new_parent_name!r} "
            "(parents must precede children in the array)")

    bi_pos = loc.bi_count_pos + 4
    entry_off = bi_pos + target_idx * 12
    name_idx, name_num, cur_parent = struct.unpack_from("<iii", ux, entry_off)
    if cur_parent != old_parent_idx:
        raise SharedSkeletonError("internal consistency check failed (parent field readback mismatch)")

    # ---- content-only overwrite: parent_idx field (3rd int32 of the 12B entry) ----
    struct.pack_into("<iii", ux, entry_off, name_idx, name_num, new_parent_idx)

    tf_changed = False
    tf_off = None
    if new_local_transform is not None:
        if loc.tsize != 80:
            raise SharedSkeletonError(
                f"new_local_transform requires double-precision (80B) transforms, got {loc.tsize}B")
        if len(new_local_transform) != 3:
            raise SharedSkeletonError(f"new_local_transform malformed: {new_local_transform!r}")
        quat, pos, scale = new_local_transform
        vals = list(quat) + list(pos) + list(scale)
        if len(vals) != 10:
            raise SharedSkeletonError(f"new_local_transform malformed: {new_local_transform!r}")
        tf_off = loc.tpos + target_idx * 80
        struct.pack_into("<10d", ux, tf_off, *vals)
        tf_changed = True

    if len(ux) != len(loc.data):
        raise SharedSkeletonError("internal error: array length changed (must not happen)")

    # ---- full byte-diff accounting (paranoid self-check、reparent_shared_skeleton.py踏襲) ----
    orig = loc.data
    diff_offsets = [i for i in range(len(orig)) if orig[i] != ux[i]]
    expected_diff_positions = set(range(entry_off + 8, entry_off + 12))  # parent_idx field only
    if tf_changed:
        expected_diff_positions |= set(range(tf_off, tf_off + 80))
    unexpected = [off for off in diff_offsets if off not in expected_diff_positions]
    if unexpected:
        raise SharedSkeletonError(
            f"unexpected byte diffs outside the intended field(s): "
            f"{len(unexpected)} bytes, first few offsets={unexpected[:10]}")

    info = {
        "target_name": target_name, "target_idx": target_idx,
        "old_parent_idx": old_parent_idx, "old_parent_name": bone_names[old_parent_idx],
        "new_parent_idx": new_parent_idx, "new_parent_name": new_parent_name,
        "n_bones": n, "transform_changed": tf_changed,
        "n_bytes_diff": len(diff_offsets),
        "orig_size": len(orig), "new_size": len(ux),
    }
    return bytes(ux), info


@dataclass(frozen=True)
class ReparentStep:
    """`apply_reparent_chain()`が逐次適用する1件の書き換え指示。
    target/new_parentはボーン名(既存の共有Skeleton上の名前、新規追加はしない)。
    new_local_transform省略時(None)は親のみ変更(モジュールdocstring参照)。
    tagは診断ログ・報告用の自由文字列(必須では無いが空文字は避ける)。"""

    target: str
    new_parent: str
    new_local_transform: Optional[Tuple[Sequence[float], Sequence[float], Sequence[float]]] = None
    tag: str = ""


def apply_reparent_chain(
    uasset_path: str, uexp_path: str,
    steps: Sequence[ReparentStep],
    min_bones: int = DEFAULT_MIN_BONES, max_bones: int = DEFAULT_MAX_BONES,
) -> Tuple[bytes, bytes, List[Dict[str, object]]]:
    """`steps`を順番に適用し、最終的な(uasset_bytes, uexp_bytes, per-step info)
    を返す(ファイル書き出しはしない——呼び出し側がpakステージングへ書く)。

    各ステップは内容だけの書き換え(配列長不変)なので、最終uassetは元の
    uassetとバイト完全一致になる(NameMapへの追加が無いため、呼び出し側は
    そのままコピーしてよい——`build_sleeve3_pak.py`の検証と同じ不変条件)。
    """
    import os
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import vp_core  # noqa: E402

    names = vp_core.read_names(uasset_path)
    with open(uexp_path, "rb") as f:
        cur_uexp = f.read()

    step_infos: List[Dict[str, object]] = []
    seen_targets = set()
    for step in steps:
        if step.target in seen_targets:
            raise SharedSkeletonError(
                f"duplicate reparent target in one apply_reparent_chain() call: {step.target!r}")
        seen_targets.add(step.target)
        cur_uexp, info = reparent_bone_content_only(
            cur_uexp, names, step.target, step.new_parent,
            new_local_transform=step.new_local_transform,
            min_bones=min_bones, max_bones=max_bones)
        step_infos.append({"tag": step.tag, **info})

    with open(uasset_path, "rb") as f:
        uasset_bytes = f.read()
    return uasset_bytes, cur_uexp, step_infos
