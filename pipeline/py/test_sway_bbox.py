# -*- coding: utf-8 -*-
"""test_sway_bbox.py -- sway_bbox.pyの単体テスト(dev#bbox_sanity 2026-08-16)。
実機・pak・Blenderに一切依存しない(bpy非依存、純粋関数のみ)。
"""
import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_bbox as bb  # noqa: E402


# ---------------------------------------------------------------------------
# bbox_from_points / bbox_from_bones
# ---------------------------------------------------------------------------

def test_bbox_from_points_basic():
    pts = [(0, 0, 0), (1, 2, 3), (-1, 0, 0)]
    r = bb.bbox_from_points(pts)
    assert r["min"] == (-1, 0, 0)
    assert r["max"] == (1, 2, 3)
    assert r["size"] == pytest.approx((2, 2, 3))
    assert r["S"] == pytest.approx(7.0)
    assert r["count"] == 3


def test_bbox_from_points_too_few_raises():
    with pytest.raises(bb.BBoxError):
        bb.bbox_from_points([(0, 0, 0)])
    with pytest.raises(bb.BBoxError):
        bb.bbox_from_points([])


def test_bbox_from_bones_wraps_dict():
    bones = {"a": (0, 0, 0), "b": (10, 0, 0), "c": (0, 5, 0)}
    r = bb.bbox_from_bones(bones)
    assert r["S"] == pytest.approx(15.0)


def test_bbox_from_bones_empty_raises():
    with pytest.raises(bb.BBoxError):
        bb.bbox_from_bones({})


def test_bbox_translation_invariant():
    """世界座標オフセット(キャラクターのワールド位置)を足してもSは変わらない
    (実機ダンプは絶対ワールド座標なので、この不変性が指標の前提になっている)。"""
    bones = {"a": (0, 0, 0), "b": (10, 0, 0), "c": (0, 5, 2)}
    r0 = bb.bbox_from_bones(bones)
    offset = (-359078.7952, 268112.8608, 7905.1403)
    shifted = {k: (v[0] + offset[0], v[1] + offset[1], v[2] + offset[2])
               for k, v in bones.items()}
    r1 = bb.bbox_from_bones(shifted)
    assert r1["S"] == pytest.approx(r0["S"], rel=1e-9)


# ---------------------------------------------------------------------------
# 原点張り付き骨の検出・除外
# ---------------------------------------------------------------------------

def test_split_origin_bones_detects_zero():
    bones = {"root": (100, 200, 300), "ear": (0.0, 0.0, 0.0), "hip": (105, 205, 295)}
    normal, origin = bb.split_origin_bones(bones)
    assert origin == ["ear"]
    assert set(normal) == {"root", "hip"}


def test_split_origin_bones_respects_eps():
    bones = {"a": (0.5, 0.5, 0.5), "b": (100, 0, 0)}
    # eps=1.0(既定)なら a は原点(半径0.87)扱いになる
    normal, origin = bb.split_origin_bones(bones, eps=1.0)
    assert origin == ["a"]
    # epsを下げれば原点扱いされなくなる
    normal2, origin2 = bb.split_origin_bones(bones, eps=0.1)
    assert origin2 == []


def test_frame_bbox_with_origin_filter_excludes_and_reports():
    bones = {
        "a": (100, 100, 100), "b": (110, 100, 100), "c": (100, 110, 100),
        "d": (100, 100, 110), "origin_bug": (0.0, 0.0, 0.0),
    }
    r = bb.frame_bbox_with_origin_filter(bones, min_bones=3)
    assert r["origin_count"] == 1
    assert r["origin_bones"] == ["origin_bug"]
    assert r["total_count"] == 5
    assert r["insufficient"] is False
    assert r["bbox"]["S"] == pytest.approx(30.0)  # a,b,c,dのみ(origin_bug除外)


def test_frame_bbox_with_origin_filter_insufficient():
    # 3骨中2骨が原点 -> 残り1骨だけではbbox不能(min_bones=3既定)
    bones = {"a": (10, 10, 10), "b": (0, 0, 0), "c": (0.0, 0.0, 0.0)}
    r = bb.frame_bbox_with_origin_filter(bones, min_bones=3)
    assert r["insufficient"] is True
    assert r["bbox"] is None
    assert r["origin_count"] == 2


# ---------------------------------------------------------------------------
# 分類(3値)
# ---------------------------------------------------------------------------

def test_classify_frame_ok():
    cls = bb.classify_frame(base_S=100.0, candidate_S=110.0, origin_count=0)
    assert cls["verdict"] == "OK"
    assert cls["severity"] is None
    assert cls["ratio"] == pytest.approx(1.1)


def test_classify_frame_warn():
    cls = bb.classify_frame(base_S=100.0, candidate_S=160.0, origin_count=0)
    assert cls["severity"] == "WARN"
    assert cls["verdict"] == "SPATIAL_ANOMALY"


def test_classify_frame_bad():
    cls = bb.classify_frame(base_S=100.0, candidate_S=350.0, origin_count=0)
    assert cls["severity"] == "BAD"
    assert cls["verdict"] == "SPATIAL_ANOMALY"
    assert cls["log10_ratio"] == pytest.approx(math.log10(3.5))


def test_classify_frame_dump_artifact_when_origin_present_but_ratio_ok():
    """原点骨があっても、除外後の比率が正常なら DUMP_ARTIFACT
    (SPATIAL_ANOMALYにしない=症状であって害ではない、という2026-08-16裁定の核心)。"""
    cls = bb.classify_frame(base_S=100.0, candidate_S=105.0, origin_count=1)
    assert cls["verdict"] == "DUMP_ARTIFACT"
    assert cls["severity"] is None


def test_classify_frame_invalid_base_raises():
    with pytest.raises(bb.BBoxError):
        bb.classify_frame(base_S=0.0, candidate_S=10.0, origin_count=0)
    with pytest.raises(bb.BBoxError):
        bb.classify_frame(base_S=None, candidate_S=10.0, origin_count=0)


# ---------------------------------------------------------------------------
# evaluate_dump_frames: 負の対照(コーディネーター追加裁定の核心)
# ---------------------------------------------------------------------------

def _healthy_frame(jitter=0.0):
    """正常な小さめの人型骨格1フレーム分(S=70)。実機ダンプは絶対ワールド座標
    (キャラクター位置オフセット込み)なので、原点(0,0,0)ちょうどに来る骨は
    無い、という実データの性質を模して基準点を(1000,1000,1000)に置く
    (原点に置くと"正常な骨"自体が誤って原点張り付き扱いされてしまう)。"""
    ox, oy, oz = 1000.0, 1000.0, 1000.0
    return {
        "root": (ox, oy, oz), "pelvis": (ox, oy, oz + 10 + jitter),
        "spine": (ox, oy, oz + 20), "head": (ox, oy, oz + 30),
        "hand_l": (ox + 20, oy, oz + 15), "hand_r": (ox - 20, oy, oz + 15),
        "foot_l": (ox + 5, oy, oz), "foot_r": (ox - 5, oy, oz),
    }


def test_evaluate_dump_frames_all_ok_no_origin():
    frames = {i: _healthy_frame(jitter=i * 0.01) for i in range(5)}
    base_S = bb.bbox_from_bones(_healthy_frame())["S"]
    r = bb.evaluate_dump_frames(frames, base_S)
    assert r["worst_classification"]["verdict"] == "OK"
    assert r["origin_bone_total_occurrences"] == 0
    assert r["insufficient_frames"] == []


def test_evaluate_dump_frames_injected_origin_bone_is_dump_artifact_not_anomaly():
    """コーディネーター追加裁定の負の対照:
    原点骨を人工的に混ぜても SPATIAL_ANOMALY にならず DUMP_ARTIFACT になる。
    (除外しない素朴なbboxなら、"ear"が原点に飛ぶことで一気に基準比数倍へ
    膨らみ、SPATIAL_ANOMALYと誤判定してしまうはずの入力を用意している)"""
    base_frame = _healthy_frame()
    base_S = bb.bbox_from_bones(base_frame)["S"]
    assert base_S == pytest.approx(70.0)

    frames = {}
    for i in range(3):
        f = dict(base_frame)
        f["ear"] = (0.0, 0.0, 0.0)  # ダンプの写り損ね(原点張り付き)
        frames[i] = f

    r = bb.evaluate_dump_frames(frames, base_S)
    assert r["origin_bone_total_occurrences"] == 3
    assert r["origin_bone_names"] == ["ear"]
    assert r["origin_bone_frames"] == [0, 1, 2]
    cls = r["worst_classification"]
    assert cls["verdict"] == "DUMP_ARTIFACT"
    assert cls["severity"] is None
    assert cls["ratio"] == pytest.approx(1.0)  # 除外後は基準と完全一致


def test_evaluate_dump_frames_naive_bbox_without_exclusion_would_misfire():
    """比較用: 原点骨を除外せずに素朴なbboxを取ると、実際に基準比3倍超へ
    膨らんでしまうことを示す(=exclusion機構が無いと本当に誤検知することの証明)。"""
    base_frame = _healthy_frame()
    base_S = bb.bbox_from_bones(base_frame)["S"]
    f = dict(base_frame)
    f["ear"] = (0.0, 0.0, 0.0)
    naive_S = bb.bbox_from_bones(f)["S"]  # 除外せずに計算
    naive_ratio = naive_S / base_S
    # 素朴計算では実際に基準比1.5倍を超えて誤検知することを示す(参照用)
    assert naive_ratio > bb.WARN_RATIO


def test_evaluate_dump_frames_real_spatial_anomaly_still_detected():
    """負の対照(逆方向): 原点ではない本物の空間破綻(骨が遠くへ飛ぶ)は、
    origin_countに関わらずSPATIAL_ANOMALYのまま検出される。"""
    base_frame = _healthy_frame()
    base_S = bb.bbox_from_bones(base_frame)["S"]
    frames = {}
    for i in range(2):
        f = dict(base_frame)
        f["exploded_bone"] = (100000.0, 0.0, 0.0)  # 原点ではない、本物の異常
        frames[i] = f
    r = bb.evaluate_dump_frames(frames, base_S)
    assert r["origin_bone_total_occurrences"] == 0
    cls = r["worst_classification"]
    assert cls["verdict"] == "SPATIAL_ANOMALY"
    assert cls["severity"] == "BAD"


def test_evaluate_dump_frames_insufficient_after_exclusion_is_recorded_not_crashed():
    frames = {0: {"a": (0.0, 0.0, 0.0), "b": (0.0, 0.0, 0.0), "c": (10, 10, 10)}}
    r = bb.evaluate_dump_frames(frames, base_S=100.0, min_bones=3)
    assert r["insufficient_frames"] == [0]
    assert r["evaluated_frame_count"] == 0
    assert r["worst_frame"] is None
    assert r["origin_bone_total_occurrences"] == 2


def test_evaluate_dump_frames_unknown_base_still_reports_origin_stats():
    """base_S取得不能(UNKNOWN)でも偽の合否は作らず、原点骨の集計だけは続ける。"""
    frames = {0: dict(_healthy_frame(), ear=(0.0, 0.0, 0.0))}
    r = bb.evaluate_dump_frames(frames, base_S=None)
    assert r["worst_classification"]["verdict"] == "UNKNOWN"
    assert r["origin_bone_total_occurrences"] == 1


# ---------------------------------------------------------------------------
# ratio_severity: 成長方向のみを見る設計の確認
# ---------------------------------------------------------------------------

def test_ratio_severity_thresholds():
    assert bb.ratio_severity(1.0) is None
    assert bb.ratio_severity(1.5) is None  # ちょうど境界は超過ではない
    assert bb.ratio_severity(1.6) == "WARN"
    assert bb.ratio_severity(3.0) == "WARN"  # ちょうど境界は超過ではない
    assert bb.ratio_severity(3.1) == "BAD"


def test_ratio_severity_shrink_direction_is_not_flagged():
    """縮小方向(ratio<1)は今回のスコープ外(実データ検証で確認済み: 骨の
    被覆範囲の違いによる縮小はよく起きる正常事象で、異常成長とは別物)。"""
    assert bb.ratio_severity(0.01) is None


# ---------------------------------------------------------------------------
# 単位正規化: ログ解析とスケール導出
# ---------------------------------------------------------------------------

_SAMPLE_LOG_LINE = (
    "[step02] scale basis: av_hips=(0.0, -0.011353749781847, 0.7265966534614563) "
    "av_head=(6.145716724859085e-06, -0.015250102616846561, 1.3606680631637573) "
    "av_len=0.634083 "
    "pal_pelvis=(1.9451552191185328e-07, 0.2720119059085846, 95.03085327148438) "
    "pal_head=(-0.00014524081780109555, 1.4963464736938477, 146.22467041015625)\n"
)


def test_parse_scale_basis_log_extracts_fields():
    fields = bb.parse_scale_basis_log(_SAMPLE_LOG_LINE)
    assert fields is not None
    assert fields["av_len"] == pytest.approx(0.634083)
    assert fields["pal_pelvis"] == pytest.approx(
        (1.9451552191185328e-07, 0.2720119059085846, 95.03085327148438))
    assert fields["pal_head"] == pytest.approx(
        (-0.00014524081780109555, 1.4963464736938477, 146.22467041015625))


def test_parse_scale_basis_log_missing_returns_none():
    assert bb.parse_scale_basis_log("nothing relevant here") is None
    assert bb.parse_scale_basis_log("") is None
    assert bb.parse_scale_basis_log(None) is None


def test_parse_scale_basis_log_uses_last_occurrence():
    text = _SAMPLE_LOG_LINE + _SAMPLE_LOG_LINE.replace("av_len=0.634083", "av_len=1.0")
    fields = bb.parse_scale_basis_log(text)
    assert fields["av_len"] == pytest.approx(1.0)


def test_derive_scale_from_log_fields_matches_real_measurement():
    """2026-08-16実測(work\\wp_w2a2d_comodo, female)の再現: s≈80.76。"""
    fields = bb.parse_scale_basis_log(_SAMPLE_LOG_LINE)
    s = bb.derive_scale_from_log_fields(fields["av_len"], fields["pal_pelvis"],
                                        fields["pal_head"])
    assert s == pytest.approx(80.75986178207414, rel=1e-6)


def test_derive_scale_from_log_fields_zero_av_len_raises():
    with pytest.raises(bb.BBoxError):
        bb.derive_scale_from_log_fields(0.0, (0, 0, 0), (0, 0, 1))


# ---------------------------------------------------------------------------
# strict_match: step01<->step02
# ---------------------------------------------------------------------------

def test_strict_match_within_tolerance_ok():
    # 2026-08-16実測: step01由来404.06 vs step02実測416.56(相対差3.1%)
    r = bb.strict_match(404.0633515565622, 416.5559139251709)
    assert r["ok"] is True
    assert r["rel_diff"] == pytest.approx(0.031, abs=0.002)


def test_strict_match_negative_control_unit_conversion_bug():
    """負の対照: 単位変換を取り違えた(例: ×100し忘れ)ケースは厳格一致で
    確実に弾かれる。"""
    step01_raw_meters_S = 5.003269478678703
    # ×100し忘れ(誤って生メートル値のままcmと比較してしまうバグを模擬)
    r = bb.strict_match(step01_raw_meters_S, 416.5559139251709)
    assert r["ok"] is False
    assert r["rel_diff"] > 1.0  # 桁違いに乖離する


def test_strict_match_unknown_input_returns_none_not_false():
    r = bb.strict_match(None, 100.0)
    assert r["ok"] is None
    assert r["reason"] == "unknown-input"
    r2 = bb.strict_match(100.0, None)
    assert r2["ok"] is None


def test_strict_match_invalid_base_raises():
    with pytest.raises(bb.BBoxError):
        bb.strict_match(0.0, 100.0)


# ---------------------------------------------------------------------------
# 実データ回帰(2026-08-16実測値の固定化。将来の意図しない変更を検出する)
# ---------------------------------------------------------------------------

def test_real_data_end_to_end_wp_w2a2d_comodo_female():
    """work\\wp_w2a2d_comodo(検体, female)の実測値を使ったエンドツーエンド確認。
    このWPの完了報告に記載した数値と一致することを固定する回帰テスト。"""
    fields = bb.parse_scale_basis_log(_SAMPLE_LOG_LINE)
    s = bb.derive_scale_from_log_fields(fields["av_len"], fields["pal_pelvis"],
                                        fields["pal_head"])
    step01_raw_S = 5.003269478678703  # step01_clean.blend実測(Blenderメートル系)
    step01_S_cm = step01_raw_S * s
    assert step01_S_cm == pytest.approx(404.0633515565622, rel=1e-9)

    step02_S = 416.5559139251709  # chibi_bone_world_head_female.json実測
    m = bb.strict_match(step01_S_cm, step02_S)
    assert m["ok"] is True

    dump_max_S = 307.2950999999957  # run_20260816_172217実測(CharacterMesh0, frame 400)
    cls = bb.classify_frame(step01_S_cm, dump_max_S, origin_count=0)
    assert cls["verdict"] == "OK"  # 実測run(健全なrun)は正常判定される
    assert cls["ratio"] < 1.0  # 被覆範囲の違いにより縮小方向(想定どおり)
