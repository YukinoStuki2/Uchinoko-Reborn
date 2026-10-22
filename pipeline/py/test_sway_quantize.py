# -*- coding: utf-8 -*-
"""sway_quantize.py の単体テスト(dev#1508 W1c)。

`work\\sway_threshold\\quantize.py` の self-test(`_run_selftest()`、
`python quantize.py` で実行する形式だった)を、製品配置
(`pipeline\\py\\sway_quantize.py`)への移設に合わせて素直な pytest
テスト関数へ書き直したもの。検証内容そのものは変えていない
(導出根拠・出どころはTHRESHOLDS.md、このファイルでは複製しない)。
"""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sway_quantize as m  # noqa: E402

VALID_LABELS = {"yawa", "futsuu", "kata"}
SYNTHETIC_GRID = [i / 4.0 for i in range(5)]  # 0, .25, .5, .75, 1.0


# =====================================================================
# PB側
# =====================================================================

def test_baseline_flatver_is_kata():
    """baseline = flatverしっぽのPB実値(pull=0.348, spring=0.49、oracleの
    baseline条件そのもの)は "kata" に分類される(BRIEF §手順4の検算、
    最重要ケース)。"""
    assert m.quantize_pb(0.348, 0.49) == "kata"


def test_apron_real_pb_returns_valid_label_without_crashing():
    """エプロン実値(pull=0.1, spring=0.9、LimitType=Hinge)は、
    dev#1508基準では偏向鎖=量子化対象外のため期待ラベルを主張しない
    (官能アンカーがこの値を検証していないため)。有効なラベルを返し
    クラッシュしないことのみ確認する。"""
    result = m.quantize_pb(0.1, 0.9)
    assert result in VALID_LABELS


@pytest.mark.parametrize("name,expected", [
    ("pull_low", "kata"),
    ("baseline", "kata"),
    ("pull_high", "kata"),
    ("spring_low", "kata"),
    ("spring_high", "yawa"),
])
def test_oracle_points_reproduce_expected_labels(name, expected):
    """実測5点の分類結果(2026-08-16机上分析で確定、THRESHOLDS.md §3表と一致)。"""
    d = m._PB_ORACLE[name]  # noqa: SLF001 -- テストなので内部データへ直接アクセスする
    assert m.quantize_pb(d["pull"], d["spring"]) == expected


@pytest.mark.parametrize("name,expected_rate,expected_var", [
    ("baseline", 0.8030, 8.516),
    ("pull_low", 0.4461, 192.80),
    ("pull_high", 1.8402, 0.99883),
    ("spring_low", 0.5576, 6.2215),
    ("spring_high", 2.2974, 1113.455),
])
def test_pb_feature_reproduces_oracle_points(name, expected_rate, expected_var):
    d = m._PB_ORACLE[name]  # noqa: SLF001
    rate, var = m.pb_feature(d["pull"], d["spring"])
    assert math.isclose(rate, expected_rate, rel_tol=1e-3)
    assert math.isclose(var, expected_var, rel_tol=1e-3)


@pytest.mark.parametrize("pull", SYNTHETIC_GRID)
@pytest.mark.parametrize("spring", SYNTHETIC_GRID)
def test_pb_synthetic_grid_always_valid_label(pull, spring):
    """5x5格子の合成(pull,spring)点で、クラッシュせず正当なラベルが返る
    (BRIEF必須要件)。"""
    assert m.quantize_pb(pull, spring) in VALID_LABELS


def test_pb_out_of_range_input_is_clamped_not_crashed():
    """負の対照: 範囲外入力(負値・1超過)でも例外を出さずクランプして扱う。"""
    assert m.quantize_pb(-5.0, 10.0) in VALID_LABELS
    assert m.quantize_pb(2.0, -3.0) in VALID_LABELS


def _count_transitions(labels: list[str]) -> int:
    return sum(1 for a, b in zip(labels, labels[1:]) if a != b)


def test_pb_monotonic_along_pull_axis_at_baseline_spring():
    pull_sweep = [m.quantize_pb(p / 20.0, 0.49) for p in range(21)]
    assert _count_transitions(pull_sweep) <= 1


def test_pb_monotonic_along_spring_axis_at_baseline_pull():
    spring_sweep = [m.quantize_pb(0.348, s / 20.0) for s in range(21)]
    assert _count_transitions(spring_sweep) <= 1


# =====================================================================
# SB側
# =====================================================================

def test_sb_vrm_default_like_value_is_valid_label():
    """VRM既定値目安(stiffness=1.0, gravityPower=0.0, dragForce=0.4)は
    有効なラベルを返す(実測較正なし、極端でないことの目安チェックのみ)。"""
    result = m.quantize_sb(stiffness=1.0, gravity_power=0.0, drag_force=0.4)
    assert result in VALID_LABELS


_RANK = {"yawa": 0, "futsuu": 1, "kata": 2}


def test_sb_monotonic_nondecreasing_dragforce():
    ranks = [_RANK[m.quantize_sb(1.0, 0.0, d / 10.0)] for d in range(11)]
    assert ranks == sorted(ranks)


def test_sb_monotonic_nondecreasing_stiffness():
    ranks = [_RANK[m.quantize_sb(s * 4.0 / 10.0, 0.0, 0.0)] for s in range(11)]
    assert ranks == sorted(ranks)


def test_sb_monotonic_nonincreasing_gravity():
    """gravityPowerは増えるほど柔らかくなる=ランクは非増加のはず。"""
    ranks = [_RANK[m.quantize_sb(0.0, g * 2.0 / 10.0, 0.0)] for g in range(11)]
    assert ranks == sorted(ranks, reverse=True)


def test_sb_softest_extreme_is_yawa():
    result = m.quantize_sb(stiffness=0.0, gravity_power=m._SB_GRAVITY_MAX, drag_force=0.0)  # noqa: SLF001
    assert result == "yawa"


def test_sb_hardest_extreme_is_kata():
    result = m.quantize_sb(stiffness=m._SB_STIFFNESS_MAX, gravity_power=0.0, drag_force=m._SB_DRAG_MAX)  # noqa: SLF001
    assert result == "kata"


@pytest.mark.parametrize("s", SYNTHETIC_GRID)
@pytest.mark.parametrize("g", SYNTHETIC_GRID)
@pytest.mark.parametrize("d", SYNTHETIC_GRID)
def test_sb_synthetic_grid_always_valid_label(s, g, d):
    result = m.quantize_sb(s * m._SB_STIFFNESS_MAX, g * m._SB_GRAVITY_MAX, d * m._SB_DRAG_MAX)  # noqa: SLF001
    assert result in VALID_LABELS
