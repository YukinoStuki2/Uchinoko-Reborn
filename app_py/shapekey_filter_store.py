# shapekey_filter_store.py -- dev#1168(シェイプキー)ラボ機能の設定永続化
# (tkinter非依存)。
#
# equipment_filter_store.py/headequip_filter_store.pyと同じ理由(pipeline_runner.py
# はヘッドレス経路(lu_export.py等)からもimportされるため、tkinterに依存する
# UI層と分離する。UI層 → store層の一方向依存)。
#
# 装備限定/頭装備切替(グローバルなPalworld装備コード)と違い、シェイプキーの
# メッシュ名・キー名はアバターごとに異なる。保存値をアバター非依存のまま
# 永続化すると、別アバターへ切り替えたときに偶然名前が一致するメッシュ/キーへ
# 誤爆しうる。そのため保存値は常に「直前に編集したavatar_pathとの組」として
# 1本だけ保持し、読み出し側(load_config/write_job)は現在のavatar_pathと
# 一致する場合のみ値を返す(不一致=別アバター編集時の残留=既定値として扱う、
# ラボ憲章④「デフォルト値のときは未実装状態と完全に同一」)。
from __future__ import annotations

import json
import os
import sys
from typing import Dict, Optional

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402

LAB_FEATURE_ID = "shape_keys"
_STATE_FILENAME = "settings_lab_shapekeys.json"

ShapeKeyValues = Dict[str, Dict[str, float]]


def _state_path(app_root: str) -> str:
    return os.path.join(app_root, _STATE_FILENAME)


def _norm_avatar_path(avatar_path: str) -> str:
    if not avatar_path:
        return ""
    try:
        return os.path.normcase(os.path.abspath(avatar_path))
    except (OSError, ValueError):
        return os.path.normcase(avatar_path)


def load_config(app_root: str, avatar_path: str) -> ShapeKeyValues:
    """保存済みの{mesh_name: {key_name: value}}(値>0のみ)。avatar_pathが
    保存時と一致しない(別アバターの残留設定)場合・ファイル不在・壊れている
    場合はいずれも空dict(=既定値、安全側)。"""
    path = _state_path(app_root)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if _norm_avatar_path(data.get("avatar_path", "")) != _norm_avatar_path(avatar_path):
        return {}
    values = data.get("values")
    if not isinstance(values, dict):
        return {}

    out: ShapeKeyValues = {}
    for mesh, kv in values.items():
        if not isinstance(kv, dict):
            continue
        cleaned = {}
        for key, v in kv.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv:
                cleaned[str(key)] = fv
        if cleaned:
            out[str(mesh)] = cleaned
    return out


def save_config(app_root: str, avatar_path: str, values: ShapeKeyValues) -> None:
    """values中の0(または非数値)は保存しない(既定=キー不在と等価)。
    どのメッシュも値を持たなくなった場合はavatar_pathも空にする(=完全に
    既定値へ戻った状態をファイル内容自体でも表現する)。書き込み失敗は
    握りつぶす(settings.py _write_text と同じ方針、設定保存の失敗で画面を
    止めない)。"""
    cleaned: ShapeKeyValues = {}
    for mesh, kv in (values or {}).items():
        if not isinstance(kv, dict):
            continue
        c = {}
        for k, v in kv.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv:
                c[str(k)] = fv
        if c:
            cleaned[str(mesh)] = c

    path = _state_path(app_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"avatar_path": _norm_avatar_path(avatar_path) if cleaned else "",
                 "values": cleaned},
                f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def reset(app_root: str) -> None:
    """dev#1186レジストリ記述子の「既定値リセット関数」。ラボ窓の
    『全てのラボ機能を無効化』ボタンから呼ばれる想定。avatar_path問わず
    全消去する(既定値=未設定)。"""
    path = _state_path(app_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"avatar_path": "", "values": {}}, f, ensure_ascii=False)
    except OSError:
        pass


def is_active(app_root: str, avatar_path: str) -> bool:
    """ラボ機能が既定から変更されているか(=現在のアバターに対して1件以上
    値が設定済みか)。dev#1186の警告文表示条件の判定に使う想定。"""
    return bool(load_config(app_root, avatar_path))


def state_summary(app_root: str, avatar_path: str, lang: Optional[str] = None) -> Optional[str]:
    """dev#1186レジストリ記述子の「状態サマリ関数」。無効(未設定/別アバター
    の残留)ならNone、有効なら短い概要(設定済みキー総数)を返す。"""
    cfg = load_config(app_root, avatar_path)
    n_keys = sum(len(kv) for kv in cfg.values())
    if n_keys == 0:
        return None
    return i18n.S("LabShapeKeysSummaryFormat", lang).format(n_keys)
