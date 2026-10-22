# -*- coding: utf-8 -*-
"""dev#19(揺れABPのUE非依存生成、WP-B相当): 事前生成テンプレABP(cooked
.uexp)の KawaiiPhysics ノードに埋め込まれた float 値だけを、UEを一切起動
せずに書き換える最小バイナリパッチャ(dt_flag_patcher.py の流儀を踏襲)。

## スコープ(2026-08-12 指揮者裁定「スコープ縮小方針」)

現行specは全カーブ2点固定形(work/rd_19_hardset/abp/specs/、
work/rd_19_hardset/abp/gen_specs.py 参照)。このモジュールが前提とする
不変条件:

  - ノード構成(ノード数)・各ノードの root_bone・カーブの点数(2点)は
    テンプレ側で既に固定されている。本モジュールは値だけを書き換え、
    ノードの追加・削除・root_bone の差し替えは一切行わない
    (root_bone差し替え=WP-C、可変長カーブ=WP-D、いずれもスコープ外)。
  - パッチ対象は float 値のみ: params 7項目
    (stiffness/damping/wdl/wdr/limit_angle/gravity_z/radius)+
    カーブ4本×2点×(time,value) の計23値/ノード。バイト長は不変。

## 構造の実測根拠(2026-08-12、work/rd_19_abp_patcher/calib/ で実施)

正本テンプレは work/rd_19_hardset/abp/cooked/ の20 ABP(10家系×F/M、
d2p_build_implementation_abp_from_spec で著作・cook済み、UAssetGUI
tojsonで解読検証済み=work/rd_19_hardset/abp/inspect/verify_report_hardset.txt
OVERALL PASS)。本モジュールのオフセット表は、この実績テンプレのうち
ABP_F_OldCloth001_Implimentation.uexp を対象に、UAssetGUI(work/配下の
開発機ローカルツール、本モジュールは一切依存しない――後述)の
tojson→(23個の対象floatだけをユニークな見張り値へ書き換え)→fromjson
round-tripで生成した「1箇所だけ変えた」バリアントと、元のバイト列を
全バイト突合して機械的に特定した(値合わせではなく、突合による位置の
特定=dt_flag_patcher.py の .uasset SerialSize パッチ部分と同じ手法)。

見つかったオフセットは RootBone.BoneName の FName 実体(8バイト:
NameMap index int32 + number int32)からの相対位置として記録している。
理由: ノードごとに root_bone 文字列は変わるが FName 自体は常に固定8
バイトなので、相対位置は文字列長に左右されない。この相対位置表が
「同一テンプレ内の別ノード」「別家系テンプレ」の両方で完全に一致する
ことを実測で確認済み(3ノード家系〈OldCloth001〉・9ノード家系
〈Ancient001〉の両方、futsuu/kata/yawa 全3プリセットの実測値で検算)。
値だけでなく、各カーブキー構造体の直前3バイト(InterpMode/TangentMode/
TangentWeightMode、実測は常に0,0,0=RCIM_Linear相当)も「見張りバイト」
として本モジュールが読み取り検証に使う(§ `_CANARY_OFFSET` 参照)。

Gravity.Z のみ他のfloatと異なり8バイトdouble(UE5 LWCのFVectorはdouble
精度)であることも実測で確認済み(他のPhysicsSettings系floatは全て
4バイトfloat)。

## UAssetGUI/.NET非依存(CLAUDE.md言語方針・既存流儀の踏襲)

このモジュール自体はUAssetGUI/UAssetAPI/.NETに一切依存しない
(vp_dt_row_select.py・vp_matparam.py と同じ方針:
「UAssetAPI/.NETは出荷物に含めない、エンドユーザーに.NETを要求しない」)。
UAssetGUIは上記オフセット表を*導出する*ためだけに開発機で使った
オフラインツールであり、本モジュールの実行時には一切呼び出さない。
"""
from __future__ import annotations

import re
import struct
from typing import Dict, List, Sequence, Tuple

_SUFFIX_RE = re.compile(r"^(.*)_(\d+)$")


class AbpStructureError(ValueError):
    """ABPのバイト構造が想定(実測ベース)と食い違ったときの例外。
    書き換えを黙ってスキップせず、変換全体を止めるためのシグナル
    (dt_flag_patcher.py と同じ設計方針)。"""


# ---------------------------------------------------------------- FName resolution

def resolve_bone_fname(bone_name: str, names: Sequence[str]) -> Tuple[int, int]:
    """ボーン名文字列を FName エンコーディング (NameMap index, number) へ
    解決する。まず NameMap への完全一致(number=0)を試し、無ければ末尾の
    "_<数字>" を切り出してベース名+number(=数字+1)として解決する
    (UE の FName 表示規約 "{base}_{number-1}" の逆変換。
    dt_flag_patcher.py の _decode_fname と対になる符号化側)。

    実データでの実例(work/rd_19_hardset実測): "M_Hunter001_06" はNameMapに
    そのまま存在する(number=0)一方、"M_Hunter001_14"/"M_Hunter001_17" は
    NameMapには存在せず、ベース"M_Hunter001"+number=15/18として解決する
    必要がある(性別間で節数が非対称な自動命名ボーンの実例)。
    """
    if bone_name in names:
        return names.index(bone_name), 0
    m = _SUFFIX_RE.match(bone_name)
    if m:
        base, suffix = m.group(1), int(m.group(2))
        if base in names:
            return names.index(base), suffix + 1
    raise AbpStructureError(
        f"bone name not resolvable against this asset's NameMap: {bone_name!r} "
        "(neither a literal NameMap entry nor a <base>_<n> suffix form)")


def _fname_bytes(idx: int, number: int) -> bytes:
    return struct.pack("<ii", idx, number)


# ------------------------------------------------------------- node anchor location

def find_node_anchors(
    uexp_bytes: bytes, names: Sequence[str], root_bones: Sequence[str],
) -> Tuple[List[int], int]:
    """各ノードの RootBone.BoneName の FName 実体(8バイト)の絶対バイト
    位置を、ノード出現順(spec の nodes 配列順=ファイル内の出現順という
    実測不変条件)に沿って特定する。

    アルゴリズム(オフセット決め打ちを避けるための構造的手順):
      1. 各 root_bone のFNameパターンをファイル全体から検索する。
      2. 出現がちょうど1回だけの root_bone を最低2つ見つけ、その位置差分
         からノード1個分のブロック長(block_size、実測では家系・性別に
         依らず一定)を算出する(2個未満なら AbpStructureError)。
      3. 残りの全ノード(出現が1回のものも含む)について、
         base_anchor + i*block_size の予測位置を計算し、その位置の8バイト
         が実際に期待する FName にデコードされることを検証する
         (別ノードの ExcludeBones 配列等からの同名参照との衝突——
         実測: Kigurumi001_tail_01——が単純な「直近の出現」選択を誤らせる
         ケースをこの予測位置検証で構造的に排除する)。

    戻り値: (各ノードのRootBone.BoneNameアンカー絶対位置のリスト, block_size)。
    想定外の構造(出現ゼロ、ブロック長が割り切れない、予測位置が
    デコードと不一致等)に遭遇したら即 AbpStructureError で停止する。
    """
    resolved = [resolve_bone_fname(rb, names) for rb in root_bones]
    patterns = [_fname_bytes(idx, num) for idx, num in resolved]

    all_hits: List[List[int]] = []
    for i, pat in enumerate(patterns):
        hits: List[int] = []
        start = 0
        while True:
            pos = uexp_bytes.find(pat, start)
            if pos == -1:
                break
            hits.append(pos)
            start = pos + 1
        if not hits:
            raise AbpStructureError(
                f"node[{i}] root_bone {root_bones[i]!r}: FName not found anywhere in uexp")
        all_hits.append(hits)

    single_hit_indices = [i for i, h in enumerate(all_hits) if len(h) == 1]
    if len(single_hit_indices) < 2:
        raise AbpStructureError(
            "cannot establish node block spacing: fewer than 2 unambiguous "
            "(single-occurrence) root-bone anchors among the spec's nodes")

    i0, i1 = single_hit_indices[0], single_hit_indices[1]
    a0, a1 = all_hits[i0][0], all_hits[i1][0]
    span = i1 - i0
    delta = a1 - a0
    if delta <= 0 or delta % span != 0:
        raise AbpStructureError(
            f"node block spacing is not a clean multiple: node[{i0}]={a0}, "
            f"node[{i1}]={a1}, delta={delta}, span={span}")
    block_size = delta // span
    base_anchor = a0 - i0 * block_size
    if base_anchor < 0:
        raise AbpStructureError(f"computed base anchor is negative: {base_anchor}")

    anchors: List[int] = []
    for i, (idx, num) in enumerate(resolved):
        predicted = base_anchor + i * block_size
        if predicted < 0 or predicted + 8 > len(uexp_bytes):
            raise AbpStructureError(
                f"node[{i}] {root_bones[i]!r}: predicted anchor {predicted} is out of range "
                f"(buffer length {len(uexp_bytes)})")
        got_idx, got_num = struct.unpack_from("<ii", uexp_bytes, predicted)
        if (got_idx, got_num) != (idx, num):
            raise AbpStructureError(
                f"node[{i}] {root_bones[i]!r}: predicted anchor {predicted} does not decode "
                f"to the expected FName (got idx={got_idx} num={got_num}, "
                f"want idx={idx} num={num}) -- refusing to guess a nearby position")
        anchors.append(predicted)

    for i in range(1, len(anchors)):
        if anchors[i] <= anchors[i - 1]:
            raise AbpStructureError(
                f"node anchors are not strictly increasing at index {i}: "
                f"{anchors[i - 1]} -> {anchors[i]}")

    return anchors, block_size


# --------------------------------------------------------------------- offset table
# RootBone.BoneName の FName実体(anchor)からの相対バイト位置。モジュール
# docstring 「構造の実測根拠」参照。fmt: "f"=float32(4B) / "d"=float64(8B)。

_PARAM_OFFSETS: Dict[str, Tuple[int, str]] = {
    "damping": (332, "f"),
    "stiffness": (361, "f"),
    "wdl": (390, "f"),
    "wdr": (419, "f"),
    "radius": (448, "f"),
    "limit_angle": (477, "f"),
}
_GRAVITY_Z_OFFSET: Tuple[int, str] = (4549, "d")

# curve key の物理レイアウト(実測、FRichCurveKey相当):
#   [InterpMode(1B), TangentMode(1B), TangentWeightMode(1B), Time(f4), Value(f4),
#    ArriveTangent(f4), ArriveTangentWeight(f4), LeaveTangent(f4), LeaveTangentWeight(f4)]
#   = 3 + 4*6 = 27バイト/キー。本モジュールが書き換えるのはTime/Valueのみ。
_CURVE_OFFSETS: Dict[str, Tuple[Tuple[int, int], Tuple[int, int]]] = {
    # curve_key -> ((k0_time_off, k0_value_off), (k1_time_off, k1_value_off))
    "stiffness": ((1352, 1356), (1379, 1383)),
    "wdl": ((1795, 1799), (1822, 1826)),
    "wdr": ((2238, 2242), (2265, 2269)),
    "limit_angle": ((3070, 3074), (3097, 3101)),
}
# 各キーのTimeオフセットの3バイト手前がcanary(InterpMode/TangentMode/
# TangentWeightMode、実測は常に0,0,0)。書き込み前後で不変であることの
# 検証にのみ使う(値は一切書き換えない)。
_CANARY_LEN = 3


def _canary_positions(anchor: int) -> List[int]:
    positions = []
    for k0, k1 in _CURVE_OFFSETS.values():
        for (t_off, _v_off) in (k0, k1):
            positions.append(anchor + t_off - _CANARY_LEN)
    return positions


def _check_canaries(buf: bytes, anchor: int, node_label: str) -> None:
    for pos in _canary_positions(anchor):
        got = buf[pos:pos + _CANARY_LEN]
        if got != b"\x00\x00\x00":
            raise AbpStructureError(
                f"node {node_label!r}: canary bytes at {pos} expected all-zero "
                f"(InterpMode/TangentMode/TangentWeightMode == RCIM_Linear), got {got!r} "
                "-- offset table assumption does not hold for this asset, refusing to patch")


# --------------------------------------------------------------------------- patch

def patch_kawaii_physics_nodes(
    uexp_bytes: bytes, names: Sequence[str], spec_nodes: Sequence[dict],
) -> bytes:
    """テンプレABPのuexp全体を受け取り、spec_nodes(spec["nodes"]と同じ形の
    リスト: 各要素が {"root_bone": str, "params": {...}, "curves": {...}})の
    値でKawaiiPhysicsノードのfloatフィールドを書き換えた新しいバイト列を
    返す。

    Args:
        uexp_bytes: パッチ前のテンプレuexp全体(このテンプレを著作した際の
            spec と、root_bone・ノード数・カーブ点数(2点)が完全一致して
            いる必要がある――このモジュールはそれらの構造を変更しない)。
        names: 対応する.uassetのNameMap(vp_core.read_names()の戻り値)。
        spec_nodes: 書き込みたい値を持つノード仕様のリスト。各ノードの
            "params" は _PARAM_OFFSETS のキー(+ "gravity_z")の部分集合、
            "curves" は _CURVE_OFFSETS のキーの部分集合(値は必ず2点
            [[time,value],[time,value]])。spec に無いキーはテンプレの
            既存値のまま変更しない。

    Returns:
        パッチ後のuexpバイト列(新しいbytesオブジェクト)。指定した値
        以外は一切変更されない(canary検証・長さ不変検証・書き込み後の
        読み戻し検証をすべて通過して初めて返る)。

    Raises:
        AbpStructureError: 想定外のバイト構造、またはスコープ外の入力
            (カーブが2点でない等)に遭遇した場合。
    """
    root_bones = [n["root_bone"] for n in spec_nodes]
    anchors, _block_size = find_node_anchors(uexp_bytes, names, root_bones)

    buf = bytearray(uexp_bytes)
    echo_checks: List[Tuple[int, str, float]] = []

    for anchor, node_spec in zip(anchors, spec_nodes):
        label = node_spec["root_bone"]
        _check_canaries(buf, anchor, label)

        params = node_spec.get("params", {})
        for key, (rel_off, fmt) in _PARAM_OFFSETS.items():
            if key not in params:
                continue
            val = float(params[key])
            struct.pack_into("<" + fmt, buf, anchor + rel_off, val)
            echo_checks.append((anchor + rel_off, fmt, val))
        if "gravity_z" in params:
            val = float(params["gravity_z"])
            rel_off, fmt = _GRAVITY_Z_OFFSET
            struct.pack_into("<" + fmt, buf, anchor + rel_off, val)
            echo_checks.append((anchor + rel_off, fmt, val))

        curves = node_spec.get("curves", {})
        for ckey, (k0_offs, k1_offs) in _CURVE_OFFSETS.items():
            if ckey not in curves:
                continue
            keys = curves[ckey]
            if len(keys) != 2:
                raise AbpStructureError(
                    f"node {label!r} curve {ckey!r}: expected exactly 2 points "
                    f"(this module's fixed-template scope), got {len(keys)}")
            for (t_off, v_off), (t_val, v_val) in zip((k0_offs, k1_offs), keys):
                struct.pack_into("<f", buf, anchor + t_off, float(t_val))
                struct.pack_into("<f", buf, anchor + v_off, float(v_val))
                echo_checks.append((anchor + t_off, "f", float(t_val)))
                echo_checks.append((anchor + v_off, "f", float(v_val)))

        _check_canaries(buf, anchor, label)

    if len(buf) != len(uexp_bytes):
        raise AbpStructureError(
            f"internal error: patched length {len(buf)} != original length {len(uexp_bytes)} "
            "(this module must never resize the uexp)")

    patched = bytes(buf)

    # ---- post-write echo verification (dt_flag_patcher.py と同じ流儀) ----
    for pos, fmt, want in echo_checks:
        got = struct.unpack_from("<" + fmt, patched, pos)[0]
        if abs(got - want) > 1e-4:
            raise AbpStructureError(
                f"post-write verification failed at {pos}: expected {want}, got {got}")

    # negative control: 書き込み対象外のバイトは一切変化しないこと。
    written_positions = set()
    for pos, fmt, _want in echo_checks:
        size = 4 if fmt == "f" else 8
        written_positions.update(range(pos, pos + size))
    changed = [i for i in range(len(uexp_bytes))
               if uexp_bytes[i] != patched[i] and i not in written_positions]
    if changed:
        raise AbpStructureError(
            "post-write verification failed: unexpected byte(s) changed outside the "
            f"intended float fields at offsets {changed[:10]}"
            f"{', ...' if len(changed) > 10 else ''}")

    return patched


def read_kawaii_physics_node_values(
    uexp_bytes: bytes, names: Sequence[str], spec_nodes: Sequence[dict],
) -> List[dict]:
    """テンプレABPのuexpから、spec_nodesが指す各ノードの現在値(params/
    curves)を読み取る(書き込みは一切行わない)。テスト・照合スクリプトが
    「パッチ前後の値」を比較するためのヘルパー。"""
    root_bones = [n["root_bone"] for n in spec_nodes]
    anchors, _block_size = find_node_anchors(uexp_bytes, names, root_bones)

    out: List[dict] = []
    for anchor, node_spec in zip(anchors, spec_nodes):
        params = {}
        for key, (rel_off, fmt) in _PARAM_OFFSETS.items():
            params[key] = struct.unpack_from("<" + fmt, uexp_bytes, anchor + rel_off)[0]
        gz_off, gz_fmt = _GRAVITY_Z_OFFSET
        params["gravity_z"] = struct.unpack_from("<" + gz_fmt, uexp_bytes, anchor + gz_off)[0]

        curves = {}
        for ckey, (k0_offs, k1_offs) in _CURVE_OFFSETS.items():
            pts = []
            for (t_off, v_off) in (k0_offs, k1_offs):
                t = struct.unpack_from("<f", uexp_bytes, anchor + t_off)[0]
                v = struct.unpack_from("<f", uexp_bytes, anchor + v_off)[0]
                pts.append([t, v])
            curves[ckey] = pts

        out.append({"root_bone": node_spec["root_bone"], "params": params, "curves": curves})
    return out
