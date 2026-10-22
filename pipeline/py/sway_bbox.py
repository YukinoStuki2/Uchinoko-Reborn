# -*- coding: utf-8 -*-
"""骨格バウンディングボックス(bbox)による安い健全性指標(2026-08-16 オーナー裁定)。

目的: O(骨数)で計算できる安価な健全性指標を使って、揺れもの試験の実機ダンプに
「空間的な破綻」(骨が異常な位置へ飛ぶ・潰れる)が起きていないかを機械判定する。

## 指標定義

骨集合の全ワールド座標のbboxの**辺長合計** S = Δx + Δy + Δz。
Blender/bpy等の重い依存を必要とせず、bone名->(x,y,z)の辞書さえあれば計算できる
純粋関数のみで構成する(このファイルはbpy非依存、実機・pak・Blenderに一切依存しない)。

## 計測点

  1. step01(基準値): 変換元アバターのarmature(VRMインポート直後のクリーン骨格。
     Blenderネイティブ単位=概ねメートル系)。
  2. step02: リターゲット後のPalworld骨格(pal_arm。chibi_fit_armature()適用後、
     既にPalworld cm相当のスケールに揃え済み。既存の
     converted/chibi_bone_world_head_{gender}.json から直接読める)。
  3. ダンプ全フレーム: 実機ボーンダンプ(cm系、ワールド絶対座標)。

## 単位正規化(2026-08-16裁定「単位正規化必須」への対応)

step01はBlenderのメートル系、step02・ダンプ・pakはPalworld cm系であり、素朴な
比較はできない。この変換係数は固定の100倍ではない(pipeline\\blender\\step02_retarget.py
の global_scale_and_place() が「体幹長(hips→head)の比」でアバターごとに個別の
スケール係数を算出しており、標準的な体型でだいたい100前後になるが、体型に応じて
変動する。2026-08-16実測で実際のアバター1件はs≈80.76だった——固定100倍を仮定すると
約24%もずれる)。

この係数は step02_retarget_{Gender}.log の "scale basis: av_hips=... av_head=...
av_len=... pal_pelvis=... pal_head=..." という常時出力行(dev#1074由来の常時ログ)に
そのまま残っているので、**再計算せず、そのログから読み取る**(step02_retarget.pyは
並走中の別レーン(wp_rootbone_fix)の担当領域につき本WPでは触らない・再委任もしない。
同一の定義式だけを独立に再実装している——`derive_scale_from_log_fields()`)。
ログが無い/一致しない場合は理由付きでNoneを返し、呼び出し側はUNKNOWNとして扱う
(偽値を作らない)。

## ダンプ品質の落とし穴: 原点張り付き骨(2026-08-16オーナー実地知見の追加裁定)

UEダンプは骨をうまく取れないとき原点(0,0,0)に位置・(0,0,0,0)という無効な四元数を
書く癖がある(2026-08-16実測: work\\rd_1423_dumpfix\\dump\\bonedump_20260816_172242.csv
167580行中4104行がこの厳密な0値パターンだった。frame=718、CharacterMesh0コンポーネント
の複数骨が同時に0落ちしていた)。正常な骨座標はキャラクターのワールド位置オフセット込みで
十万台のオーダー(root相対でも十〜百のオーダー)になるため、原点から半径1.0以内に来ることは
実質ない。この実測に基づき既定epsilon=1.0を採用する(閾値を実測値に寄せて合わせたのではなく、
「異常値=厳密ゼロ」という構造的シグネチャの検出半径として、実測されたマージンの範囲内で
選んだもの)。

素朴なbbox判定(原点骨を除外しない)は、この「写り損ね」由来の誤検知だらけになる
(骨1本が原点に飛ぶだけで全体bboxが桁違いに膨らむため)。そこで判定を3値に分ける:

  - **OK**: 原点張り付き骨なし・bbox正常(比率<=WARN_RATIO)
  - **DUMP_ARTIFACT**: 原点張り付き骨あり・除外後のbboxは正常
    (=ダンプの写り損ねが原因。実機の骨格自体はおおむね無事——症状であって害ではない)
  - **SPATIAL_ANOMALY**: 原点骨を除外した後もbboxが基準比1.5倍/3倍超
    (=本物の空間破綻の疑い。実機側の異常)

原点骨の本数・骨名リストは呼び出し側(devtools\\sway_run.py)がresult.json/MANIFESTへ
記録し、ダンプ品質の経時観察材料にする(本ファイルは検出・分離のロジックのみを提供する)。
"""
import math
import re

# ---------------------------------------------------------------------------
# 定数(実データ根拠つき。「値を寄せて合わせる」閾値ではなく、実測された構造的な
# シグネチャ・マージンから選んだもの)
# ---------------------------------------------------------------------------

# 原点張り付き骨の検出半径。根拠は本ファイルdocstring参照(2026-08-16実測)。
ORIGIN_EPS_DEFAULT = 1.0

# ダンプ比較(step01比)の2段閾値。2026-08-16オーナー裁定「1.5倍超=警告、
# 3倍超=明確異常」をそのまま定数化。
WARN_RATIO = 1.5
BAD_RATIO = 3.0

# step01<->step02の「厳格一致」許容誤差(相対)。2026-08-16実測(検体
# work\\wp_w2a2d_comodo、性別female): 単位変換後のstep01由来S=404.06 に対し
# step02実測S=416.56(相対差3.1%)。この差はchibi_fit_armature()が各関節を
# アバター実測位置へ個別に動かすことに由来する小さな揺らぎであり、単位変換の
# 取り違え(2倍・100倍等の構造的誤り)とは桁が違う。5%はこの実測差分(3.1%)に
# 安全マージンを載せた値であり、構造的誤りは確実に弾ける一方、chibi_fitの
# 正常な揺らぎは通す閾値として選んだ(値を実測に完全一致させて誤魔化す設計
# ではない——実測はあくまで「妥当な閾値の桁を決める」ために使っている)。
STRICT_REL_TOL_DEFAULT = 0.05

# frame_bbox_with_origin_filter(): 原点骨を除いた後、bboxを定義するのに
# 最低限必要な骨数。1〜2本では「箱」として意味を持たない(実質1点扱いになり
# うる)ため3本を下限とする。
MIN_BONES_DEFAULT = 3


class BBoxError(ValueError):
    """bbox計算が不能・入力が不正なときに送出する(偽値を返さない)。"""


# ---------------------------------------------------------------------------
# 基礎: bbox計算
# ---------------------------------------------------------------------------

def bbox_from_points(points):
    """points: (x,y,z)の反復可能オブジェクト。

    戻り値: {"min":(x,y,z), "max":(x,y,z), "size":(dx,dy,dz), "S":float, "count":int}
    2点未満はBBoxErrorを送出する(bboxが定義できないため)。
    """
    pts = [tuple(p) for p in points]
    if len(pts) < 2:
        raise BBoxError("bbox requires at least 2 points, got {}".format(len(pts)))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    lo = (min(xs), min(ys), min(zs))
    hi = (max(xs), max(ys), max(zs))
    size = tuple(h - l for h, l in zip(hi, lo))
    return {"min": lo, "max": hi, "size": size, "S": sum(size), "count": len(pts)}


def bbox_from_bones(bone_coords):
    """bone_coords: dict[bone_name] -> (x,y,z)。bbox_from_points()の薄いラッパー。"""
    if not bone_coords:
        raise BBoxError("no bones given")
    return bbox_from_points(bone_coords.values())


def vec_norm(p):
    return math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2])


# ---------------------------------------------------------------------------
# 原点張り付き骨の検出・除外
# ---------------------------------------------------------------------------

def split_origin_bones(bone_coords, eps=ORIGIN_EPS_DEFAULT):
    """原点張り付き骨(||pos||<eps)を検出して分離する。

    戻り値: (normal_dict, origin_names_list)
    """
    normal = {}
    origin = []
    for name, p in bone_coords.items():
        if vec_norm(p) < eps:
            origin.append(name)
        else:
            normal[name] = p
    return normal, origin


def frame_bbox_with_origin_filter(bone_coords, eps=ORIGIN_EPS_DEFAULT,
                                   min_bones=MIN_BONES_DEFAULT):
    """1フレーム分のbone_coordsから、原点張り付き骨を除いたbboxを計算する。

    戻り値: {
      "bbox": bbox_dict または None(除外後min_bones未満で計算不能),
      "origin_bones": [...], "origin_count": int,
      "total_count": int, "insufficient": bool,
    }
    """
    normal, origin = split_origin_bones(bone_coords, eps=eps)
    total = len(bone_coords)
    if len(normal) < min_bones:
        return {"bbox": None, "origin_bones": origin, "origin_count": len(origin),
                "total_count": total, "insufficient": True}
    bbox = bbox_from_bones(normal)
    return {"bbox": bbox, "origin_bones": origin, "origin_count": len(origin),
            "total_count": total, "insufficient": False}


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------

def ratio_severity(ratio, warn_ratio=WARN_RATIO, bad_ratio=BAD_RATIO):
    """ratio(candidate_S/base_S)から severity(None/"WARN"/"BAD")を返す。
    2026-08-16オーナー裁定の「1.5倍超=警告、3倍超=明確異常」は成長方向のみを
    見る(縮小方向は別問題であり、この指標の対象外——2026-08-16実測run
    run_20260816_172217では逆にdumpのS(CharacterMesh0のみ、98骨)がstep01由来
    基準より縮む方向に出た(比率0.76)。これは骨の被覆範囲の違い(step01/step02は
    髪・指等を含む全骨格、ダンプは主要ボーンのみ)による構造差であり、
    「異常系で数千倍になる」という実績の対象=成長方向の破綻とは別物のため、
    成長方向だけを見る設計にしている)。
    """
    if ratio > bad_ratio:
        return "BAD"
    if ratio > warn_ratio:
        return "WARN"
    return None


def classify_frame(base_S, candidate_S, origin_count,
                    warn_ratio=WARN_RATIO, bad_ratio=BAD_RATIO):
    """1フレーム分の3値分類(2026-08-16オーナー追加裁定)。

    戻り値: {"ratio", "log10_ratio", "severity"(None/"WARN"/"BAD"),
             "verdict"("OK"/"DUMP_ARTIFACT"/"SPATIAL_ANOMALY"),
             "base_S", "candidate_S", "origin_count"}
    """
    if base_S is None or base_S <= 0:
        raise BBoxError("invalid base_S: {!r}".format(base_S))
    if candidate_S is None or candidate_S < 0:
        raise BBoxError("invalid candidate_S: {!r}".format(candidate_S))
    ratio = candidate_S / base_S
    log10_ratio = math.log10(ratio) if ratio > 0 else float("-inf")
    severity = ratio_severity(ratio, warn_ratio=warn_ratio, bad_ratio=bad_ratio)
    if severity is None:
        verdict = "DUMP_ARTIFACT" if origin_count > 0 else "OK"
    else:
        verdict = "SPATIAL_ANOMALY"
    return {"ratio": ratio, "log10_ratio": log10_ratio, "severity": severity,
            "verdict": verdict, "base_S": base_S, "candidate_S": candidate_S,
            "origin_count": origin_count}


def evaluate_dump_frames(frames, base_S, eps=ORIGIN_EPS_DEFAULT,
                          min_bones=MIN_BONES_DEFAULT,
                          warn_ratio=WARN_RATIO, bad_ratio=BAD_RATIO):
    """ダンプの全フレームを評価し、最悪フレーム(除外後S/base_S比が最大の
    フレーム)を代表値として返す(2026-08-16裁定: 異常は一部フレームにしか
    出ないことがあるため、平均でなく最大を見る)。

    frames: dict[frame_id] -> dict[bone_name] -> (x,y,z)

    base_S が None のとき(基準値取得不能)は判定を行わず verdict="UNKNOWN" で
    返す(偽値を作らない。それでも原点骨の集計はダンプ品質観察のため続ける)。

    戻り値: {
      "base_S", "worst_frame", "worst_classification"(dict または None),
      "evaluated_frame_count", "insufficient_frames": [frame_id...],
      "origin_bone_frames": [frame_id...](1本でも原点骨があったフレーム),
      "origin_bone_names": sorted list(出現した骨名の集合),
      "origin_bone_total_occurrences": int,
    }
    """
    origin_bone_frames = []
    origin_bone_names = set()
    origin_bone_total_occurrences = 0
    insufficient_frames = []
    worst = None  # (ratio_or_-1_if_no_base, frame_id, per_frame_result)

    for frame_id, bone_coords in frames.items():
        r = frame_bbox_with_origin_filter(bone_coords, eps=eps, min_bones=min_bones)
        if r["origin_count"] > 0:
            origin_bone_frames.append(frame_id)
            origin_bone_names.update(r["origin_bones"])
            origin_bone_total_occurrences += r["origin_count"]
        if r["insufficient"]:
            insufficient_frames.append(frame_id)
            continue
        candidate_S = r["bbox"]["S"]
        if base_S is not None and base_S > 0:
            cls = classify_frame(base_S, candidate_S, r["origin_count"],
                                  warn_ratio=warn_ratio, bad_ratio=bad_ratio)
            key = cls["ratio"]
        else:
            cls = {"ratio": None, "log10_ratio": None, "severity": None,
                   "verdict": "UNKNOWN", "base_S": base_S,
                   "candidate_S": candidate_S, "origin_count": r["origin_count"]}
            key = candidate_S  # base_S不明でも「一番大きいS」を代表に選ぶ
        if worst is None or key > worst[0]:
            worst = (key, frame_id, cls)

    return {
        "base_S": base_S,
        "worst_frame": worst[1] if worst else None,
        "worst_classification": worst[2] if worst else None,
        "evaluated_frame_count": len(frames) - len(insufficient_frames),
        "insufficient_frames": sorted(insufficient_frames),
        "origin_bone_frames": sorted(origin_bone_frames),
        "origin_bone_names": sorted(origin_bone_names),
        "origin_bone_total_occurrences": origin_bone_total_occurrences,
    }


# ---------------------------------------------------------------------------
# step01<->step02 厳格一致(単位正規化込み)
# ---------------------------------------------------------------------------

_SCALE_BASIS_RE = re.compile(
    r"scale basis: av_hips=\(([^)]+)\) av_head=\(([^)]+)\) av_len=([0-9.eE+\-]+) "
    r"pal_pelvis=\(([^)]+)\) pal_head=\(([^)]+)\)"
)


def parse_scale_basis_log(text):
    """step02_retarget_{Gender}.log の 'scale basis: ...' 常時出力行(dev#1074)
    から av_len / pal_pelvis / pal_head を取り出す(pipeline\\blender\\step02_retarget.py
    の global_scale_and_place() を再実行せず、そのログをそのまま読むだけ——
    当該ファイルは並走レーンの担当領域につき本WPでは触らない)。

    複数回出力されていた場合は最後の一致を使う(die()等で仕切り直された場合、
    最後の値が実際に使われた値であるため)。

    戻り値: dict {"av_hips","av_head","av_len","pal_pelvis","pal_head"} または
    見つからなければ None(取得不能。呼び出し側でUNKNOWN扱いにする。偽値を作らない)。
    """
    matches = list(_SCALE_BASIS_RE.finditer(text or ""))
    if not matches:
        return None
    m = matches[-1]

    def _tuple3(s):
        parts = [v.strip() for v in s.split(",")]
        if len(parts) != 3:
            raise BBoxError("expected 3 components, got {!r}".format(s))
        return tuple(float(v) for v in parts)

    return {
        "av_hips": _tuple3(m.group(1)),
        "av_head": _tuple3(m.group(2)),
        "av_len": float(m.group(3)),
        "pal_pelvis": _tuple3(m.group(4)),
        "pal_head": _tuple3(m.group(5)),
    }


def derive_scale_from_log_fields(av_len, pal_pelvis, pal_head):
    """global_scale_and_place()と同一の定義(体幹長(hips->head)比)でスケール
    係数を独立に再計算する(pipeline\\blender\\step02_retarget.py の
    `s = (pal_head - pal_pelvis).length / av_len` と同じ式)。

    av_len<=0はBBoxError(体幹長ゼロは元コード側でもfail-fast対象の異常値)。
    """
    if av_len is None or av_len <= 0:
        raise BBoxError("invalid av_len: {!r}".format(av_len))
    d = tuple(h - p for h, p in zip(pal_head, pal_pelvis))
    seg_len = math.sqrt(sum(c * c for c in d))
    return seg_len / av_len


def strict_match(step01_S_cm, step02_S, rel_tol=STRICT_REL_TOL_DEFAULT):
    """step01(単位正規化済み、cm相当)とstep02(実測S、cm)の厳格一致判定。

    入力のどちらかがNone(取得不能)のときは判定不能として ok=None を返す
    (偽の合格/不合格を作らない)。
    """
    if step01_S_cm is None or step02_S is None:
        return {"ok": None, "reason": "unknown-input", "step01_S": step01_S_cm,
                "step02_S": step02_S, "diff": None, "rel_diff": None,
                "rel_tol": rel_tol}
    if step01_S_cm <= 0:
        raise BBoxError("invalid step01_S_cm: {!r}".format(step01_S_cm))
    diff = step02_S - step01_S_cm
    rel_diff = abs(diff) / step01_S_cm
    return {"ok": rel_diff <= rel_tol, "reason": None, "step01_S": step01_S_cm,
            "step02_S": step02_S, "diff": diff, "rel_diff": rel_diff,
            "rel_tol": rel_tol}
