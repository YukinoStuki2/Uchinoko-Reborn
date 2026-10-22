# gender_filter_store.py -- dev#336(2026-08-08 性別限定)ラボ機能の選択状態
# 永続化ロジック(tkinter非依存)。
#
# equipment_filter_store.py/headequip_filter_store.pyと同型の分離方針
# (2026-08-08緊急修正の教訓踏襲): app_py\ui\gender_select_dialog.py が
# モジュール冒頭で `import tkinter as tk` するため、pipeline_runner.py
# (ヘッドレスのパイプライン起動経路。lu_export.py 等 tkinter の無い
# python環境からも読み込まれる)が ui\gender_select_dialog.py を直接
# importすると ModuleNotFoundError で即死する。
#
# 本モジュールは load_selected_gender()/save_selected_gender() など
# 「選択状態の保存・読み出しロジック」のみを tkinter 非依存の形で
# 切り出したもの。ui\gender_select_dialog.py はこちらを import して
# 使う(UI層 → store層の一方向依存)。pipeline_runner.py は本モジュール
# のみを import する(ui\gender_select_dialog.py を import しない)。
#
# **他の2機能(equipment_filter/headequip_show)と違い、選択は「コードの
# リスト」ではなく「単一の性別文字列 or None(両方)」**。UIは複数選択
# チェックリストではなく3択ラジオボタン(work\rd_1198_wpb\PROPOSAL.md
# §7.3「無効/女のみ/男のみ、ラボ窓の1行+専用ダイアログ」)。
from __future__ import annotations

import json
import os
from typing import Optional

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))

import sys  # noqa: E402

if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402

LAB_FEATURE_ID = "gender_filter"
_STATE_FILENAME = "settings_lab_gender_filter.json"

_VALID_GENDERS = ("Male", "Female")


# ---------------------------------------------------------------------------
# 選択状態の永続化(app_root直下の平文JSON、equipment_filter_store.pyと同じ
# 流儀。未選択(gender=null/ファイル不在)=ラボ憲章④の既定値=従来どおり
# 両性別、job.jsonにgendersキーを一切書かない=既存のconvert_noue.py側
# 既定解決(job.get("genders") or ["Male","Female"])と一致する)。
# ---------------------------------------------------------------------------

def _state_path(app_root: str) -> str:
    return os.path.join(app_root, _STATE_FILENAME)


def load_selected_gender(app_root: str) -> Optional[str]:
    """保存済みの限定性別("Male"/"Female")を返す。未設定/ファイル不在/
    壊れている/不正値の場合は常に None(=両方=既定、安全側)。"""
    path = _state_path(app_root)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        gender = data.get("gender")
        if gender in _VALID_GENDERS:
            return gender
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        pass
    return None


def save_selected_gender(app_root: str, gender: Optional[str]) -> None:
    """gender は None(両方=既定)/"Male"/"Female" のいずれか。それ以外の
    値はNoneとして保存する(壊れた保存を作らない、安全側)。書き込み失敗は
    握りつぶす(equipment_filter_store.pyと同じ方針、設定保存の失敗で
    画面を止めない)。"""
    if gender not in _VALID_GENDERS:
        gender = None
    path = _state_path(app_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"gender": gender}, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def reset(app_root: str) -> None:
    """dev#1186レジストリ記述子の「既定値リセット関数」。ラボ窓の
    『全てのラボ機能を無効化』ボタンから呼ばれる想定。既定値=両方
    (gender=None)。"""
    save_selected_gender(app_root, None)


def is_active(app_root: str) -> bool:
    """ラボ機能が既定から変更されているか(=片性別が選択済みか)。"""
    return load_selected_gender(app_root) is not None


def state_summary(app_root: str, lang: Optional[str] = None) -> Optional[str]:
    """dev#1186レジストリ記述子の「状態サマリ関数」。無効(両方=既定)なら
    None、有効なら短い概要(lab_window.py側が『有効: <この文字列>』へ
    整形する想定)。"""
    gender = load_selected_gender(app_root)
    if gender is None:
        return None
    key = ("LabGenderFilterSummaryMaleOnly" if gender == "Male"
           else "LabGenderFilterSummaryFemaleOnly")
    return i18n.S(key, lang)
