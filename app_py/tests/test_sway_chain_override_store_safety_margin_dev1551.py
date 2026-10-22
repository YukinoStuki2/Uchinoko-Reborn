# test_sway_chain_override_store_safety_margin_dev1551.py -- dev#1551
# 安全域WP(issue #1551「安全域」欄、2026-08-18オーナー最終裁定)の
# sway_chain_override_store.py単体テスト。実tk.Tk()は使わない
# (store.pyはtkinter非依存の純粋モジュール)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import sway_chain_override_store as store  # noqa: E402

_BONES = ["J_Bip_C_Head", "EarL_01", "EarL_02"]


def test_default_safety_margin_constant_is_one():
    """オーナー確定仕様の製品既定値そのもの。"""
    assert store.DEFAULT_SAFETY_MARGIN == 1


def test_save_config_omits_entry_when_only_safety_margin_is_default(tmp_path):
    """ラボ憲章④: safety_margin=1(既定)・他フィールドも既定なら、保存対象
    から除外される(既定値のときは未実装状態と完全に同一)。"""
    app_root = str(tmp_path)
    avatar = "C:\\fake.vrm"
    store.save_config(app_root, avatar, [
        {"bones": _BONES, "enabled": True, "hardness": "follow",
         "manual": False, "safety_margin": 1},
    ])
    assert store.load_config(app_root, avatar) == []


def test_save_config_persists_entry_when_safety_margin_differs_from_default(tmp_path):
    """安全域だけが既定から変わっている(他は全既定)行でも、その一点の
    ために保存されること——旧_is_default_entry(dev#1438修正前と同型の
    見落とし)がここで再発しないことの直接固定。"""
    app_root = str(tmp_path)
    avatar = "C:\\fake.vrm"
    store.save_config(app_root, avatar, [
        {"bones": _BONES, "enabled": True, "hardness": "follow",
         "manual": False, "safety_margin": 2},
    ])
    loaded = store.load_config(app_root, avatar)
    assert len(loaded) == 1
    assert loaded[0]["safety_margin"] == 2


def test_load_config_roundtrip_safety_margin_zero(tmp_path):
    """安全域0(=先端マージを無効化するユーザー選択)も既定(1)からの逸脱
    として正しく保存・復元される。"""
    app_root = str(tmp_path)
    avatar = "C:\\fake.vrm"
    store.save_config(app_root, avatar, [
        {"bones": _BONES, "enabled": True, "hardness": "follow",
         "manual": False, "safety_margin": 0},
    ])
    loaded = store.load_config(app_root, avatar)
    assert len(loaded) == 1
    assert loaded[0]["safety_margin"] == 0


def test_sanitize_clamps_out_of_range_and_invalid_values(tmp_path):
    """負の対照: 壊れた値(文字列・負数・上限超過)は例外を投げず既定値へ
    丸める(既存catalog群の三点セット方針と同じ安全側フォールバック)。"""
    app_root = str(tmp_path)
    avatar = "C:\\fake.vrm"
    store.save_config(app_root, avatar, [
        {"bones": ["a"], "enabled": True, "hardness": "follow",
         "manual": False, "safety_margin": "not-a-number"},
        {"bones": ["b"], "enabled": True, "hardness": "follow",
         "manual": False, "safety_margin": -5},
        {"bones": ["c"], "enabled": True, "hardness": "follow",
         "manual": False, "safety_margin": 999},
    ])
    loaded = {tuple(e["bones"]): e["safety_margin"] for e in store.load_config(app_root, avatar)}
    assert loaded[("a",)] == store.DEFAULT_SAFETY_MARGIN  # 壊れた値は既定へ
    assert loaded[("b",)] == 0  # 負値は0へクランプ(store.pyのマージ無効化と一致)
    assert loaded[("c",)] == store.MAX_SAFETY_MARGIN  # 上限でクランプ


def test_missing_safety_margin_key_defaults_to_one(tmp_path):
    """旧バージョン(本WP以前)が保存したエントリにはsafety_marginキーが
    無い——読み込み時に既定値1へフォールバックし、KeyError等を起こさない
    ことを確認する(スキーマ前方互換)。"""
    app_root = str(tmp_path)
    avatar = "C:\\fake.vrm"
    store.save_config(app_root, avatar, [
        {"bones": _BONES, "enabled": False, "hardness": "hard", "manual": False},
    ])
    loaded = store.load_config(app_root, avatar)
    assert len(loaded) == 1
    assert loaded[0]["safety_margin"] == 1
