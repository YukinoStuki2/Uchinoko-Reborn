# -*- coding: utf-8 -*-
"""sway_pivot_axiom.py の単体テスト(dev#1508 hubwire final、オーナー制定
公理2026-08-16「揺れものの支点は、その親humanoidボーンに対して相対位置が
一切変わらない」の検査ロジック)。"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sway_pivot_axiom as m  # noqa: E402


# =====================================================================
# relative_vector / check_pivot_invariant
# =====================================================================

def test_relative_vector_identity_rotation_is_plain_difference():
    v = m.relative_vector((5.0, 2.0, 1.0), (1.0, 1.0, 1.0))
    assert v == pytest.approx((4.0, 1.0, 0.0))


def test_relative_vector_undoes_parent_rotation():
    """親が90度Z回転していても、相対ベクトルは親から見て常に同じ値になる
    (=剛体固定なら親が回転しても相対ベクトルは不変、という公理の核心)。"""
    # 90度Z回転quat (x,y,z,w)
    half = math.radians(90) / 2.0
    q90z = (0.0, 0.0, math.sin(half), math.cos(half))
    # 親位置(0,0,0)・回転無しのとき、pivotが(1,0,0)にあれば相対ベクトルは(1,0,0)
    v0 = m.relative_vector((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0, 0, 0, 1))
    assert v0 == pytest.approx((1.0, 0.0, 0.0))
    # 親が90度Z回転すると、剛体固定のpivotはワールド座標で(0,1,0)へ移動する
    # (親ローカル(1,0,0)を90度Z回転)。相対ベクトルを計算するとやはり(1,0,0)
    # に戻るはず。
    v1 = m.relative_vector((0.0, 1.0, 0.0), (0.0, 0.0, 0.0), q90z)
    assert v1 == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)


def test_check_pivot_invariant_pass_within_epsilon():
    r = m.check_pivot_invariant("ear", "head", (1.0, 0.0, 0.0),
                                 (1.0 + 1e-6, 0.0, 0.0), eps=1e-4)
    assert r.ok
    assert r.reason == ""


def test_check_pivot_invariant_fail_reports_distance_and_reason():
    """負の対照: 相対ベクトルが動くとFAILし、理由文字列に骨名・親名・
    数値が含まれる。"""
    r = m.check_pivot_invariant("ear", "head", (1.0, 0.0, 0.0),
                                 (1.0, 0.05, 0.0), eps=1e-4)
    assert not r.ok
    assert r.distance == pytest.approx(0.05)
    assert "ear" in r.reason
    assert "head" in r.reason


# =====================================================================
# resolve_anchor_parent_avatar_names
# =====================================================================

def test_resolve_anchor_parent_climbs_to_nearest_standard_ancestor():
    """pal_mapは`vp_bl.humanoid_map_from_json()`と同じ契約
    ({パル名 -> アバター側の実名}、キーとバリューが**別の文字列**である
    のが通常——2026-08-16実データ検証(flatHaori再変換)で、pal_map
    自身をキー側と誤って照合する実装ミスにより実際に0件しか解決できない
    退行が起きた。本テストのfixtureはその方向を取り違えると必ず失敗する
    よう、パル名("head")とアバター側の実名("Head")をあえて別文字列にする。"""
    pal_map = {"head": "Head"}  # パル名"head" -> アバター側の実名"Head"
    avatar_bone_parent = {
        "Head_L.001": "Head",  # 耳anchorの親は直接Head(アバター側の実名)
        "Head": "Neck",
    }
    out = m.resolve_anchor_parent_avatar_names(
        ["Head_L.001"], pal_map, avatar_bone_parent)
    assert out == {"Head_L.001": "Head"}


def test_resolve_anchor_parent_climbs_through_multiple_non_standard_ancestors():
    """支点の直接の親がまだ標準骨でなくても、祖先をさらに辿って解決する。"""
    pal_map = {"chest": "Chest"}
    avatar_bone_parent = {
        "Shoulder.L.001": "Shoulder.L",   # 非標準
        "Shoulder.L": "Chest",            # 標準(pal_mapの値=アバター側実名)
        "Chest": "Spine",
    }
    out = m.resolve_anchor_parent_avatar_names(
        ["Shoulder.L.001"], pal_map, avatar_bone_parent)
    assert out == {"Shoulder.L.001": "Chest"}


def test_resolve_anchor_parent_unresolvable_is_omitted():
    """負の対照: 祖先を辿ってもpal_map(の値=アバター側実名)に到達
    できないanchorは戻り値から除外される(FAILにしない、既存のsway_hub
    「anchor未解決」設計と同型)。"""
    pal_map = {"head": "Head"}
    avatar_bone_parent = {"Orphan.001": "OrphanParent", "OrphanParent": None}
    out = m.resolve_anchor_parent_avatar_names(
        ["Orphan.001"], pal_map, avatar_bone_parent)
    assert out == {}


def test_resolve_anchor_parent_missing_from_dict_is_omitted():
    pal_map = {"head": "Head"}
    avatar_bone_parent = {}  # anchor自体が辞書に無い(bpy側で存在しない等)
    out = m.resolve_anchor_parent_avatar_names(
        ["Nope.001"], pal_map, avatar_bone_parent)
    assert out == {}


def test_resolve_anchor_parent_rejects_naive_key_lookup_direction():
    """負の対照(2026-08-16実データ検証で発見した実装ミスの直接反証):
    pal_mapのキー側(パル名)だけをアバター側の実ボーン名として誤って
    照合する実装だと、アバター側の生名("Head"等)がパル名の文字列と
    たまたま一致しない限り一切解決できない——本テストのfixtureは
    パル名("head", 小文字)とアバター側実名("Head", 大文字始まり)を
    意図的に違う大文字小文字にして、キー側照合(誤り)では絶対に
    ヒットしないが値側照合(正しい実装)では解決できることを示す。"""
    pal_map = {"head": "Head"}
    avatar_bone_parent = {"Head_L.001": "Head", "Head": None}
    out = m.resolve_anchor_parent_avatar_names(
        ["Head_L.001"], pal_map, avatar_bone_parent)
    assert out == {"Head_L.001": "Head"}


def test_resolve_anchor_parent_guards_against_cycles():
    """安全側防御: 循環参照があっても無限ループしない(構造的に起きない
    はずだが、安全弁の直接検査)。"""
    pal_map = {}  # 解決先が無い
    avatar_bone_parent = {"A": "B", "B": "A"}
    out = m.resolve_anchor_parent_avatar_names(["A"], pal_map, avatar_bone_parent)
    assert out == {}


# =====================================================================
# run_pivot_axiom_gate (end-to-end pure logic)
# =====================================================================

def test_run_pivot_axiom_gate_passes_for_rigid_pivot():
    """正: 支点(ear)が親(head)に対して剛体固定されている(headが移動・回転
    しても相対ベクトルが不変)なら全件PASS。"""
    anchor_parent_of = {"ear": "head"}
    baseline_positions = {"ear": (1.0, 0.0, 0.0), "head": (0.0, 0.0, 0.0)}
    baseline_rotations = {"head": (0.0, 0.0, 0.0, 1.0)}
    # observed: headが(10,10,10)へ平行移動しただけ(回転無し)、
    # earも剛体的に追従して(11,10,10)にいる -> 相対ベクトルは不変のはず
    observed_positions = {"ear": (11.0, 10.0, 10.0), "head": (10.0, 10.0, 10.0)}
    observed_rotations = {"head": (0.0, 0.0, 0.0, 1.0)}

    report = m.run_pivot_axiom_gate(
        anchor_parent_of, baseline_positions, baseline_rotations,
        observed_positions, observed_rotations)
    assert report.ok
    assert len(report.results) == 1


def test_run_pivot_axiom_gate_fails_when_pivot_drifts_from_parent():
    """負の対照: 支点が親から離れて動く(揺れものが親から千切れて漂う
    ようなバグ相当)場合はFAILし、report.failedに理由付きで載る。"""
    anchor_parent_of = {"ear": "head"}
    baseline_positions = {"ear": (1.0, 0.0, 0.0), "head": (0.0, 0.0, 0.0)}
    baseline_rotations = {"head": (0.0, 0.0, 0.0, 1.0)}
    # observed: headは動いていないが、earだけ大きくズレている(剛体崩壊)
    observed_positions = {"ear": (5.0, 5.0, 5.0), "head": (0.0, 0.0, 0.0)}
    observed_rotations = {"head": (0.0, 0.0, 0.0, 1.0)}

    report = m.run_pivot_axiom_gate(
        anchor_parent_of, baseline_positions, baseline_rotations,
        observed_positions, observed_rotations)
    assert not report.ok
    assert len(report.failed) == 1
    assert "ear" in report.failed[0].reason


def test_run_pivot_axiom_gate_survives_parent_rotation():
    """正: 親が回転(姿勢変化)しても、支点が剛体的に追従していればPASS
    (「あらゆる揺れや姿勢の影響に関係なく」の直接検査)。"""
    half = math.radians(45) / 2.0
    q45z = (0.0, 0.0, math.sin(half), math.cos(half))
    anchor_parent_of = {"ear": "head"}
    baseline_positions = {"ear": (1.0, 0.0, 0.0), "head": (0.0, 0.0, 0.0)}
    baseline_rotations = {"head": (0.0, 0.0, 0.0, 1.0)}

    # observed: headが45度Z回転。剛体固定のearはworld座標で
    # rotate(q45z, (1,0,0)) だけ移動しているはず。
    from sway_pivot_axiom import _q_rotate
    ear_world = _q_rotate(q45z, (1.0, 0.0, 0.0))
    observed_positions = {"ear": ear_world, "head": (0.0, 0.0, 0.0)}
    observed_rotations = {"head": q45z}

    report = m.run_pivot_axiom_gate(
        anchor_parent_of, baseline_positions, baseline_rotations,
        observed_positions, observed_rotations)
    assert report.ok


def test_run_pivot_axiom_gate_skips_pivots_with_missing_data():
    """データ欠落(例: ダンプにハブが記録されない、または対象骨がまだ
    出現していないフレーム)はスキップする(FAILにしない、モジュール
    docstring参照)。"""
    anchor_parent_of = {"ear": "head", "tail": "hips"}
    baseline_positions = {"ear": (1.0, 0.0, 0.0), "head": (0.0, 0.0, 0.0),
                           "tail": (0.0, -1.0, 0.0), "hips": (0.0, 0.0, 0.0)}
    baseline_rotations = {}
    observed_positions = {"ear": (1.0, 0.0, 0.0), "head": (0.0, 0.0, 0.0)}
    # "tail"/"hips"はobserved側に無い(欠測) -> スキップされ、報告対象は
    # earの1件のみ
    observed_rotations = {}

    report = m.run_pivot_axiom_gate(
        anchor_parent_of, baseline_positions, baseline_rotations,
        observed_positions, observed_rotations)
    assert len(report.results) == 1
    assert report.results[0].pivot == "ear"
    assert report.ok


def test_summary_lines_report_failed_count():
    anchor_parent_of = {"ear": "head"}
    baseline_positions = {"ear": (1.0, 0.0, 0.0), "head": (0.0, 0.0, 0.0)}
    baseline_rotations = {}
    observed_positions = {"ear": (9.0, 9.0, 9.0), "head": (0.0, 0.0, 0.0)}
    observed_rotations = {}
    report = m.run_pivot_axiom_gate(
        anchor_parent_of, baseline_positions, baseline_rotations,
        observed_positions, observed_rotations)
    lines = report.summary_lines()
    assert "1 pivot(s) checked, 1 FAILED" in lines[0]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
