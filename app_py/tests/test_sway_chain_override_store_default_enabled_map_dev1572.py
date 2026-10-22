# test_sway_chain_override_store_default_enabled_map_dev1572.py -- dev#1572
# 第3便(issue #1572「チェインの揺れ設定問題1・2」)の
# sway_chain_override_store.py単体テスト。実tk.Tk()は使わない
# (store.pyはtkinter非依存の純粋モジュール)。
#
# 背景: 旧_is_default_entry()は名前ベース(sway_identify.default_sway_
# enabled())で「既定enabled」を判定していたため、偏向していて実際には
# 既定OFFの鎖が尻尾/耳と紛らわしい名前を持つ場合、ユーザーが明示的にONへ
# 上書きしても「名前的にはもう既定と同じ」と誤判定され、保存対象から
# 落ちてしまう不具合があった(逆方向も同様)。本テストは新しい
# default_enabled_map引数がこの誤判定を正しく回避することを固定する。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import sway_chain_override_store as store  # noqa: E402

# 名前は尻尾トークンに一致する(名前ベース既定=True)が、偏向しているため
# 真の既定(偏向判定ベース)はFalseという想定のbones。
_TAIL_NAMED_BUT_BIASED = ["Hips", "Tail_01", "Tail_02"]
# 名前は尻尾/耳に一切一致しない(名前ベース既定=False)が、非偏向のため
# 真の既定(偏向判定ベース)はTrueという想定のbones(例: スカート)。
_UNNAMED_BUT_UNBIASED = ["Hips", "Skirt_01", "Skirt_02"]


def test_without_default_enabled_map_keeps_legacy_name_based_behavior(tmp_path):
    """後方互換: default_enabled_map省略時は旧来どおり名前ベース
    (sway_identify.default_sway_enabled())で判定される(凍結UIui\\
    sway_chain_dialog.pyからの呼び出しを壊さない)。"""
    app_root = str(tmp_path)
    avatar = "C:\\fake.vrm"
    store.save_config(app_root, avatar, [
        {"bones": _TAIL_NAMED_BUT_BIASED, "enabled": True, "hardness": "follow",
         "manual": False, "safety_margin": 1},
    ])
    # 名前ベースでは"Tail"トークン一致=既定True。enabled=Trueも既定一致
    # なので、default_enabled_map無しでは(誤って)間引かれる。
    assert store.load_config(app_root, avatar) == []


def test_with_default_enabled_map_true_forcing_biased_chain_on_is_persisted(tmp_path):
    """dev#1572の核心: 偏向判定ベースの真の既定(False)をdefault_enabled_map
    で渡すと、enabled=True(ユーザーの明示的なON上書き)が正しく「既定からの
    逸脱」として保存される(旧バグの直接固定)。"""
    app_root = str(tmp_path)
    avatar = "C:\\fake.vrm"
    key = tuple(_TAIL_NAMED_BUT_BIASED)
    default_map = {key: False}  # 偏向判定ベースの真の既定
    store.save_config(
        app_root, avatar,
        [{"bones": _TAIL_NAMED_BUT_BIASED, "enabled": True, "hardness": "follow",
          "manual": False, "safety_margin": 1}],
        default_enabled_map=default_map,
    )
    loaded = store.load_config(app_root, avatar, default_enabled_map=default_map)
    assert len(loaded) == 1
    assert loaded[0]["enabled"] is True


def test_with_default_enabled_map_true_matching_true_is_omitted(tmp_path):
    """default_enabled_mapが示す真の既定と一致する行は、引き続き保存対象
    から間引かれる(ラボ憲章④は維持)。"""
    app_root = str(tmp_path)
    avatar = "C:\\fake.vrm"
    key = tuple(_UNNAMED_BUT_UNBIASED)
    default_map = {key: True}  # 偏向判定ベースの真の既定(非偏向=True)
    store.save_config(
        app_root, avatar,
        [{"bones": _UNNAMED_BUT_UNBIASED, "enabled": True, "hardness": "follow",
          "manual": False, "safety_margin": 1}],
        default_enabled_map=default_map,
    )
    assert store.load_config(app_root, avatar, default_enabled_map=default_map) == []


def test_with_default_enabled_map_false_forcing_unbiased_chain_off_is_persisted(tmp_path):
    """逆方向: 非偏向(真の既定True)の鎖をenabled=Falseで明示OFFにすると、
    default_enabled_map経由で正しく「既定からの逸脱」として保存される。"""
    app_root = str(tmp_path)
    avatar = "C:\\fake.vrm"
    key = tuple(_UNNAMED_BUT_UNBIASED)
    default_map = {key: True}
    store.save_config(
        app_root, avatar,
        [{"bones": _UNNAMED_BUT_UNBIASED, "enabled": False, "hardness": "follow",
          "manual": False, "safety_margin": 1}],
        default_enabled_map=default_map,
    )
    loaded = store.load_config(app_root, avatar, default_enabled_map=default_map)
    assert len(loaded) == 1
    assert loaded[0]["enabled"] is False


def test_bones_not_in_default_enabled_map_falls_back_to_name_based(tmp_path):
    """default_enabled_mapに載っていないbones(mapが不完全/別の鎖)は、
    名前ベースフォールバックへ安全に倒れる(KeyError等を起こさない)。"""
    app_root = str(tmp_path)
    avatar = "C:\\fake.vrm"
    store.save_config(
        app_root, avatar,
        [{"bones": _TAIL_NAMED_BUT_BIASED, "enabled": True, "hardness": "follow",
          "manual": False, "safety_margin": 1}],
        default_enabled_map={},  # 空map: このbonesは載っていない
    )
    # mapに無いので名前ベースへフォールバック=True(既定一致)=間引かれる。
    assert store.load_config(app_root, avatar, default_enabled_map={}) == []


def test_manual_entries_always_non_default_regardless_of_map(tmp_path):
    """manual=Trueの行は、default_enabled_mapがどんな値を示していても
    常に非既定(既存の不変規則、モジュールdocstring参照)。"""
    app_root = str(tmp_path)
    avatar = "C:\\fake.vrm"
    key = ("CustomManualBone",)
    default_map = {key: True}
    store.save_config(
        app_root, avatar,
        [{"bones": ["CustomManualBone"], "enabled": True, "hardness": "follow",
          "manual": True, "safety_margin": 1}],
        default_enabled_map=default_map,
    )
    loaded = store.load_config(app_root, avatar, default_enabled_map=default_map)
    assert len(loaded) == 1
    assert loaded[0]["manual"] is True
