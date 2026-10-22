# lab_raw_sway_params_dialog.py -- dev#1418ラボ機能「揺れ物理の生パラメータ
# 全解放パネル」(work\wp_1418_rawparam\BRIEF.md、2026-08-15)のダイアログ。
#
# dt_flag_head_hide_dialog.py/lab_tip_stiffen_dialog.py(work\rd_19_labtipslider、
# 未マージだが同型)と同じ「lab_window.pyには薄いアダプタだけを置き、実UIは
# ここに閉じ込める」構成(WP指示書の書き込み許可からlab_window.py/
# main_window.py本体を外す規約に従う——結線(LabFeature記述子の追加)は
# マージ時に指揮者が1行だけ足す)。
#
# UI案の所在: work\rd_19_labgui\kp_tuner.py(2026-08-14夜、オーナーが実機で
# 使って気に入った開発用GUI)。2家系(しっぽ・耳)×5パラメータのスライダー
# レイアウトをそのまま踏襲する。kp_tuner.pyはtkinter非依存/i18n非対応の
# 開発ツールのため、本ダイアログはその構成をi18n対応・製品ダイアログの
# 流儀(tk.Scale + Entry表示、OKで保存)へ書き直したもの。
from __future__ import annotations

import os
import sys
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import window_pos  # noqa: E402

# 選択状態の保存・読み出しロジックはtkinter非依存のlab_raw_sway_params_store.py
# にある(dt_flag_head_hide_store.py等と同じ理由)。
import lab_raw_sway_params_store as _store  # noqa: E402

LAB_FEATURE_ID = _store.LAB_FEATURE_ID
FAMILIES = _store.FAMILIES
PARAM_KEYS = _store.PARAM_KEYS
PARAM_RANGES = _store.PARAM_RANGES
DEFAULT_PARAMS = _store.DEFAULT_PARAMS
load_params = _store.load_params
save_params = _store.save_params
reset = _store.reset
is_active = _store.is_active
state_summary = _store.state_summary

_FAMILY_NAME_KEYS = {"tail": "LabRawSwayParamsFamilyTail", "ear": "LabRawSwayParamsFamilyEar"}
_PARAM_NAME_KEYS = {
    "stiffness": "LabRawSwayParamsParamStiffness",
    "damping": "LabRawSwayParamsParamDamping",
    "wd": "LabRawSwayParamsParamWd",
    "gravity_z": "LabRawSwayParamsParamGravityZ",
    "limit_angle": "LabRawSwayParamsParamLimitAngle",
}


@dataclass
class LabRawSwayParamsContext:
    app_root: str
    append_log: Callable[[str], None] = field(default=lambda msg: None)


def show_lab_raw_sway_params_dialog(
    parent: tk.Misc, ctx: LabRawSwayParamsContext,
) -> tk.Toplevel:
    """dev#1418「生パラメータ全解放パネル」設定ダイアログ本体。

    `(parent, ctx) -> tk.Toplevel` の呼び出し規約(on_changeは呼び出し側が
    `<Destroy>`イベントへbindする、lab_window.py._open_equipment_filter_dialog
    と同じ結線パターン)。OK押下時のみバッキングストアへ保存する(drop_bones/
    dt_flag_head_hideダイアログと同じ「OKで適用、×/キャンセルは破棄」の
    流儀)。GUI内に機能説明を必ず置く(lab-devスキル「ドキュメントが不要で
    あるように」)。"""
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("LabRawSwayParamsDialogTitle"))
    dlg.resizable(False, False)
    dlg.geometry("620x520")
    dlg.transient(parent)
    i18n.register(dlg, "LabRawSwayParamsDialogTitle", lambda w, t: w.title(t))
    window_pos.apply_offset_position(dlg, parent)

    desc = tk.Label(dlg, text=i18n.S("LabRawSwayParamsHint"),
                     wraplength=596, justify="left", anchor="nw")
    desc.place(x=12, y=8, width=596, height=110)
    i18n.register(desc, "LabRawSwayParamsHint")

    initial = load_params(ctx.app_root)
    scale_vars: dict = {family: {} for family in FAMILIES}
    value_labels: dict = {family: {} for family in FAMILIES}

    col_width = 296
    frame_top = 122
    row_height = 62

    def _format_value(key: str, value: float) -> str:
        if key == "limit_angle":
            return f"{value:.1f}"
        if key == "gravity_z":
            return f"{value:.1f}"
        return f"{value:.2f}"

    for col, family in enumerate(FAMILIES):
        x0 = 12 + col * (col_width + 8)
        family_label = tk.Label(dlg, text=i18n.S(_FAMILY_NAME_KEYS[family]),
                                 font=("", 10, "bold"), anchor="w")
        family_label.place(x=x0, y=frame_top, width=col_width, height=22)
        i18n.register(family_label, _FAMILY_NAME_KEYS[family])

        for row, key in enumerate(PARAM_KEYS):
            y0 = frame_top + 26 + row * row_height
            lo, hi = PARAM_RANGES[key]
            resolution = 0.01 if key in ("stiffness", "damping", "wd") else 1.0

            name_label = tk.Label(dlg, text=i18n.S(_PARAM_NAME_KEYS[key]), anchor="w")
            name_label.place(x=x0, y=y0, width=col_width - 60, height=18)
            i18n.register(name_label, _PARAM_NAME_KEYS[key])

            value_label = tk.Label(dlg, anchor="e")
            value_label.place(x=x0 + col_width - 56, y=y0, width=56, height=18)
            value_labels[family][key] = value_label

            initial_value = initial[family][key]

            def _on_move(raw: str, family=family, key=key) -> None:
                value_labels[family][key].config(text=_format_value(key, float(raw)))

            scale = tk.Scale(
                dlg, from_=lo, to=hi, resolution=resolution, orient="horizontal",
                showvalue=False, command=_on_move, length=col_width,
            )
            scale.set(initial_value)
            value_label.config(text=_format_value(key, initial_value))
            scale.place(x=x0, y=y0 + 18, width=col_width, height=36)
            scale_vars[family][key] = scale

    def _current_params() -> dict:
        return {
            family: {key: float(scale_vars[family][key].get()) for key in PARAM_KEYS}
            for family in FAMILIES
        }

    def _reset_sliders() -> None:
        for family in FAMILIES:
            for key in PARAM_KEYS:
                value = DEFAULT_PARAMS[family][key]
                scale_vars[family][key].set(value)
                value_labels[family][key].config(text=_format_value(key, value))

    reset_btn = tk.Button(dlg, text=i18n.S("LabRawSwayParamsResetButton"),
                           command=_reset_sliders)
    reset_btn.place(x=12, y=480, width=160, height=28)
    i18n.register(reset_btn, "LabRawSwayParamsResetButton")

    def _apply_and_close() -> None:
        params = _current_params()
        save_params(ctx.app_root, params)
        ctx.append_log(f"[lab][lab_raw_sway_params] setting saved: {params}")
        dlg.destroy()

    ok_btn = tk.Button(dlg, text=i18n.S("BtnOk"), command=_apply_and_close)
    ok_btn.place(x=508, y=480, width=100, height=28)
    i18n.register(ok_btn, "BtnOk")

    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    return dlg


# ---------------------------------------------------------------------------
# dev#1186 ラボ機能レジストリ記述子(lab_window.py側が結線する)。
# ---------------------------------------------------------------------------

LAB_REGISTRY_DESCRIPTOR = {
    "id": LAB_FEATURE_ID,
    "name_key": "LabFeatureRawSwayParams",
    "state_summary": state_summary,
    "open_dialog": show_lab_raw_sway_params_dialog,
    "reset": reset,
}
