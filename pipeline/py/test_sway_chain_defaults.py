# -*- coding: utf-8 -*-
"""sway_chain_defaults.py の単体テスト(dev#1572 第3便「チェイン設定の
実体化」)。

`is_default_enabled()`が偏向判定(`sway_allocator._judge_pb_bias`/
`_judge_sb_bias`)のみに基づき、名前(尻尾/耳)を一切見ないことを固定する
(問題1の根治=「実際にデフォルトで揺れるかどうかは偏向判定だけで決まる」)。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sway_allocator  # noqa: E402
import sway_chain_defaults as m  # noqa: E402


def _pb_params(limit_type="None", max_angle_x=45.0, limit_rotation=(0, 0, 0),
                pull=0.5, spring=0.5):
    return {
        "pull": pull, "spring": spring, "limit_type": limit_type,
        "max_angle_x": max_angle_x, "limit_rotation": list(limit_rotation),
    }


# --------------------------------------------------------------------- 核心

def test_unbiased_pb_default_enabled_regardless_of_name():
    """名前が尻尾/耳トークンに一切一致しなくても(例: スカート・エプロン)、
    偏向していなければ既定enabled=True(問題1の核心)。"""
    assert m.is_default_enabled("pb", _pb_params(limit_type="None")) is True


def test_biased_pb_default_disabled_even_if_tail_named():
    """逆に、名前が尻尾トークンに一致しても、偏向していれば既定enabled=
    False(旧sway_identify.default_sway_enabled()は名前だけで既定ONを判定
    していたため、この組み合わせで食い違いが起きていた)。"""
    assert m.is_default_enabled(
        "pb", _pb_params(limit_type="Hinge")) is False


def test_biased_angle_offset_default_disabled():
    assert m.is_default_enabled(
        "pb", _pb_params(limit_type="Angle", limit_rotation=(5, 0, 0))) is False


def test_unbiased_angle_zero_offset_default_enabled():
    assert m.is_default_enabled(
        "pb", _pb_params(limit_type="Angle", limit_rotation=(0, 0, 0))) is True


def test_springbone_always_default_enabled():
    """SpringBoneは角度制限機構が無いので常に無偏向=既定enabled(source
    は"sb"/"springbone"のどちらの表記でも同じ結果になること)。"""
    assert m.is_default_enabled("sb", {}) is True
    assert m.is_default_enabled("springbone", {}) is True


def test_none_params_treated_as_unbiased_pb():
    assert m.is_default_enabled("pb", None) is True


# --------------------------------------------------------------------- ChainUnit連携

def _unit(source="pb", is_biased=False, style="futsuu", params=None):
    return sway_allocator.ChainUnit(
        key="pb:Anchor#0", source=source, anchor="Anchor", chains=(("A", "B"),),
        bone_count=2, params=params or {}, is_biased=is_biased, bias_reason="",
        is_tail=False, style=style, limit_angle=0.0,
    )


def test_default_enabled_for_unit_matches_is_default_enabled():
    """`default_enabled_for_unit()`(ChainUnit経由)と`is_default_enabled()`
    (生params経由)が同一結果を返すこと(=同じ関数を呼んでいることの
    構造的な固定)。"""
    biased_params = _pb_params(limit_type="Hinge")
    unbiased_params = _pb_params(limit_type="None")
    biased_unit = _unit(is_biased=True, style=None, params=biased_params)
    unbiased_unit = _unit(is_biased=False, style="futsuu", params=unbiased_params)
    assert m.default_enabled_for_unit(biased_unit) == m.is_default_enabled(
        "pb", biased_params) is False
    assert m.default_enabled_for_unit(unbiased_unit) == m.is_default_enabled(
        "pb", unbiased_params) is True


def test_compute_default_enabled_map_keys_by_unit_key():
    physbones_json = {"physbones": [
        {"anchor": "A", "chains": [["A1", "A2"]], "params": _pb_params(limit_type="None")},
        {"anchor": "B", "chains": [["B1", "B2"]], "params": _pb_params(limit_type="Hinge")},
    ]}
    out = m.compute_default_enabled_map(physbones_json=physbones_json)
    assert out == {"pb:A#0": True, "pb:B#1": False}


# --------------------------------------------------------------------- LabAssignment変換

def test_lab_assignment_for_unit_disabled_ignores_style():
    la = m.lab_assignment_for_unit(_unit(style="futsuu"), enabled=False)
    assert la.enabled is False


def test_lab_assignment_for_unit_enabled_keeps_existing_style():
    la = m.lab_assignment_for_unit(_unit(style="kata"), enabled=True)
    assert la.enabled is True
    assert la.style == "kata"


def test_lab_assignment_for_unit_force_enable_recomputes_style_from_params():
    """偏向していたユニット(style=None)を強制ONにする場合、`unit.params`
    から`sway_quantize.quantize_pb`で再計算した値が使われること(空文字列
    や壊れた値にならない)。"""
    unit = _unit(is_biased=True, style=None,
                  params=_pb_params(limit_type="Hinge", pull=0.9, spring=0.9))
    la = m.lab_assignment_for_unit(unit, enabled=True)
    assert la.enabled is True
    assert la.style in ("yawa", "futsuu", "kata")


def test_lab_assignment_for_unit_force_enable_sb_uses_quantize_sb():
    unit = _unit(source="sb", is_biased=False, style=None,
                  params={"stiffness": 0.3, "gravity_power": 0.3, "drag_force": 0.3})
    la = m.lab_assignment_for_unit(unit, enabled=True)
    assert la.enabled is True
    assert la.style in ("yawa", "futsuu", "kata")
