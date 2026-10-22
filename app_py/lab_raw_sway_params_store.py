# lab_raw_sway_params_store.py -- dev#1418ラボ機能「揺れ物理の生パラメータ
# 全解放パネル」(work\wp_1418_rawparam\BRIEF.md、2026-08-15)の設定値
# 永続化ロジック(tkinter非依存)。
#
# lab_tip_stiffen_store.py(work\rd_19_labtipslider、未マージだが同型)や
# dt_flag_head_hide_store.pyと同じ理由・同じ最小構成(pipeline_runner.pyが
# ヘッドレス経路からもimportできるよう、tkinterをimportするui\側とは分離する)。
#
# **UI案の所在**: work\rd_19_labgui\kp_tuner.py(2026-08-14夜、オーナーが
# 実機で使って気に入った開発用GUI)。paramモデル(family="tail"/"ear" ×
# キー stiffness/damping/wd(=wdl・wdr共通値)/gravity_z/limit_angle)を
# そのまま踏襲する(NOTES.md参照)。
#
# **意味論**: 保存値がDEFAULT_PARAMS(kp_tuner.py DEFAULT_PARAMSと同一の
# F1既定値)と完全一致するときのみ「既定(job未配線)」とみなす
# ——lab_tip_stiffen_store(値0.0が既定)と同型の「連続値が既定点に一致する
# ときのみ無効」方式。個別の有効/無効トグルは持たない(トグルを別途持つと
# 「トグルON・値は既定のまま」という中間状態が生まれ、ラボ憲章④の判定が
# 曖昧になるため、値そのものが唯一の判定軸になるようにした)。
from __future__ import annotations

import copy
import json
import math
import os
import sys
from typing import Dict, Optional

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402

LAB_FEATURE_ID = "lab_raw_sway_params"
_STATE_FILENAME = "settings_lab_raw_sway_params.json"

FAMILIES = ("tail", "ear")
PARAM_KEYS = ("stiffness", "damping", "wd", "gravity_z", "limit_angle")

PARAM_RANGES: Dict[str, tuple] = {
    "stiffness": (0.0, 1.0),
    "damping": (0.0, 1.0),
    "wd": (0.0, 1.0),
    "gravity_z": (-100.0, 0.0),
    "limit_angle": (0.0, 180.0),
}

# F1既定値(work\rd_19_labgui\kp_tuner.py DEFAULT_PARAMSと同一の値)。
DEFAULT_PARAMS: Dict[str, Dict[str, float]] = {
    "tail": {"stiffness": 0.05, "damping": 0.25, "wd": 0.0, "gravity_z": 0.0, "limit_angle": 0.0},
    "ear": {"stiffness": 0.1, "damping": 0.3, "wd": 0.2, "gravity_z": 0.0, "limit_angle": 0.0},
}


def _state_path(app_root: str) -> str:
    return os.path.join(app_root, _STATE_FILENAME)


def _clamp(key: str, value: float) -> float:
    lo, hi = PARAM_RANGES[key]
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def load_params(app_root: str) -> Dict[str, Dict[str, float]]:
    """保存済みのパラメータ(family -> {5キー: float})。ファイル不在/
    壊れている/形式が違う/個別値が非数値・範囲外の場合は、その値だけ
    DEFAULT_PARAMSへ安全側フォールバックする(家系・キー単位のフォール
    バック、apply時と対称)。戻り値は常にFAMILIES全件・PARAM_KEYS全件を
    持つ完全なdict。"""
    result = copy.deepcopy(DEFAULT_PARAMS)
    path = _state_path(app_root)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return result
    if not isinstance(data, dict):
        return result
    saved_params = data.get("params")
    if not isinstance(saved_params, dict):
        return result
    for family in FAMILIES:
        fam = saved_params.get(family)
        if not isinstance(fam, dict):
            continue
        for key in PARAM_KEYS:
            if key not in fam:
                continue
            v = fam[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            result[family][key] = _clamp(key, float(v))
    return result


def save_params(app_root: str, params: Dict[str, Dict[str, float]]) -> None:
    """書き込み失敗は握りつぶす(dt_flag_head_hide_store.save_enabledと同じ
    方針)。保存前に範囲外値をクランプする(多重防御)。"""
    to_save = copy.deepcopy(DEFAULT_PARAMS)
    for family in FAMILIES:
        fam = params.get(family) if isinstance(params, dict) else None
        if not isinstance(fam, dict):
            continue
        for key in PARAM_KEYS:
            if key not in fam:
                continue
            v = fam[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            to_save[family][key] = _clamp(key, float(v))
    path = _state_path(app_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"params": to_save}, f, ensure_ascii=False, indent=1)
    except (OSError, TypeError, ValueError):
        pass


def reset(app_root: str) -> None:
    """dev#1186レジストリ記述子の「既定値リセット関数」。既定値=DEFAULT_PARAMS。"""
    save_params(app_root, copy.deepcopy(DEFAULT_PARAMS))


def is_active(app_root: str) -> bool:
    """保存値がDEFAULT_PARAMSと完全一致しないか(=ラボ機能が既定から
    変更されているか)。"""
    current = load_params(app_root)
    for family in FAMILIES:
        for key in PARAM_KEYS:
            if not math.isclose(
                current[family][key], DEFAULT_PARAMS[family][key], abs_tol=1e-9,
            ):
                return True
    return False


def state_summary(app_root: str, lang: Optional[str] = None) -> Optional[str]:
    """dev#1186レジストリ記述子の「状態サマリ関数」。既定なら None、
    非既定なら短い定型文字列(値のダンプはダイアログ本体で行う)。"""
    if not is_active(app_root):
        return None
    # i18n.F()はlang引数を持たない(常にcurrent_langを使う、i18n.py参照)ため、
    # 指定言語対応が要る本関数はi18n.S()を直接使う
    # (lab_tip_stiffen_store.state_summary等、他ラボstoreと同型)。
    return i18n.S("LabRawSwayParamsSummary", lang)


def get_job_override(app_root: str) -> Optional[Dict[str, Dict[str, float]]]:
    """pipeline_runner.write_job()向け: 既定なら None(job.jsonへキー自体を
    書かせない)、非既定なら保存済みの完全なparams dict(family x 5キー)。"""
    if not is_active(app_root):
        return None
    return load_params(app_root)
