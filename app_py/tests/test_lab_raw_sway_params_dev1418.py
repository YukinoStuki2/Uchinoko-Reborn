# test_lab_raw_sway_params_dev1418.py -- dev#1418ラボ機能「揺れ物理の生
# パラメータ全解放パネル」(work\wp_1418_rawparam\BRIEF.md、2026-08-15)。
#
# app_py\ui\lab_raw_sway_params_dialog.py + app_py\lab_raw_sway_params_store.py
# + pipeline_runner.write_job()結線の単体テスト。dt_flag_head_hide_dialogの
# dev#1258テスト・lab_tip_stiffen_dialog(work\rd_19_labtipslider、未マージだが
# 同型)のdev#19テストと同じ骨格(実tk.Tk()は作らない、conftest.pyの共有
# hidden_root、既存慣例踏襲)。
from __future__ import annotations

import copy
import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import lab_raw_sway_params_store as store  # noqa: E402
import pipeline_runner as pr  # noqa: E402
from ui import lab_raw_sway_params_dialog as dlg_mod  # noqa: E402

FAMILIES = store.FAMILIES
PARAM_KEYS = store.PARAM_KEYS


# ---------------------------------------------------------------------------
# 1. 選択状態の永続化 + 状態サマリ(ラボ憲章④: 既定=DEFAULT_PARAMSと完全一致)
# ---------------------------------------------------------------------------

def test_default_params_is_f1_defaults_and_inactive(tmp_path):
    app_root = str(tmp_path)
    assert store.load_params(app_root) == store.DEFAULT_PARAMS
    assert store.is_active(app_root) is False
    assert store.state_summary(app_root) is None
    assert store.get_job_override(app_root) is None


def test_save_then_load_round_trip(tmp_path):
    app_root = str(tmp_path)
    params = copy.deepcopy(store.DEFAULT_PARAMS)
    params["tail"]["stiffness"] = 0.9
    store.save_params(app_root, params)
    loaded = store.load_params(app_root)
    assert loaded["tail"]["stiffness"] == 0.9
    # 他の値は既定のまま(部分保存でも他familyのデータが飛ばないこと)。
    assert loaded["ear"] == store.DEFAULT_PARAMS["ear"]
    assert store.is_active(app_root) is True
    assert store.state_summary(app_root) == i18n.S("LabRawSwayParamsSummary")


def test_reset_clears_to_defaults(tmp_path):
    app_root = str(tmp_path)
    params = copy.deepcopy(store.DEFAULT_PARAMS)
    params["ear"]["wd"] = 0.9
    store.save_params(app_root, params)
    assert store.is_active(app_root) is True
    store.reset(app_root)
    assert store.load_params(app_root) == store.DEFAULT_PARAMS
    assert store.is_active(app_root) is False


def test_corrupt_state_file_falls_back_to_defaults(tmp_path):
    app_root = str(tmp_path)
    with open(store._state_path(app_root), "w", encoding="utf-8") as f:  # noqa: SLF001
        f.write("{ this is not valid json")
    assert store.load_params(app_root) == store.DEFAULT_PARAMS


def test_non_numeric_value_falls_back_to_default_for_that_key(tmp_path):
    """負の対照: 壊れた個別値(文字列/bool)はそのキーだけ既定へフォール
    バックし、他の有効な値は活きる。"""
    app_root = str(tmp_path)
    with open(store._state_path(app_root), "w", encoding="utf-8") as f:  # noqa: SLF001
        json.dump({"params": {
            "tail": {"stiffness": "yes", "damping": 0.9},
            "ear": {"gravity_z": True},
        }}, f)
    loaded = store.load_params(app_root)
    assert loaded["tail"]["stiffness"] == store.DEFAULT_PARAMS["tail"]["stiffness"]
    assert loaded["tail"]["damping"] == 0.9
    assert loaded["ear"]["gravity_z"] == store.DEFAULT_PARAMS["ear"]["gravity_z"]


def test_save_params_clamps_out_of_range(tmp_path):
    app_root = str(tmp_path)
    params = copy.deepcopy(store.DEFAULT_PARAMS)
    params["tail"]["stiffness"] = 5.0
    params["tail"]["gravity_z"] = 999.0
    params["tail"]["limit_angle"] = -50.0
    store.save_params(app_root, params)
    loaded = store.load_params(app_root)
    assert loaded["tail"]["stiffness"] == 1.0
    assert loaded["tail"]["gravity_z"] == 0.0
    assert loaded["tail"]["limit_angle"] == 0.0


def test_get_job_override_returns_full_params_when_active(tmp_path):
    app_root = str(tmp_path)
    params = copy.deepcopy(store.DEFAULT_PARAMS)
    params["tail"]["stiffness"] = 0.7
    store.save_params(app_root, params)
    override = store.get_job_override(app_root)
    assert override is not None
    assert override["tail"]["stiffness"] == 0.7
    assert set(override.keys()) == set(FAMILIES)
    for family in FAMILIES:
        assert set(override[family].keys()) == set(PARAM_KEYS)


def test_registry_descriptor_shape():
    d = dlg_mod.LAB_REGISTRY_DESCRIPTOR
    assert d["id"] == "lab_raw_sway_params"
    assert isinstance(d["name_key"], str)
    for lang in i18n.LANGS:
        assert i18n.S(d["name_key"], lang) and not i18n.S(d["name_key"], lang).startswith("??")
    assert callable(d["state_summary"])
    assert callable(d["open_dialog"])
    assert callable(d["reset"])


def test_all_i18n_keys_present_in_all_languages():
    """i18nキー漏れ試験: このWPが追加した全キーが5言語で埋まっていること。"""
    keys = [
        "LabFeatureRawSwayParams",
        "LabRawSwayParamsDialogTitle",
        "LabRawSwayParamsHint",
        "LabRawSwayParamsFamilyTail",
        "LabRawSwayParamsFamilyEar",
        "LabRawSwayParamsParamStiffness",
        "LabRawSwayParamsParamDamping",
        "LabRawSwayParamsParamWd",
        "LabRawSwayParamsParamGravityZ",
        "LabRawSwayParamsParamLimitAngle",
        "LabRawSwayParamsSummary",
        "LabRawSwayParamsResetButton",
    ]
    for key in keys:
        for lang in i18n.LANGS:
            text = i18n.S(key, lang)
            assert text and not text.startswith("??"), (
                f"i18nキー欠落: {key} / {lang}")


# ---------------------------------------------------------------------------
# 2. ダイアログ本体の配線(実Toplevel、hidden_root経由)
# ---------------------------------------------------------------------------

def _all_scales(dlg):
    import tkinter as tk
    return [w for w in dlg.winfo_children() if isinstance(w, tk.Scale)]


def test_dialog_default_sliders_match_defaults(hidden_root, tmp_path):
    """スライダーの生成順は show_lab_raw_sway_params_dialog() 内の
    `for family in FAMILIES: for key in PARAM_KEYS:` ネストループ順と一致する
    (place()配置だがdlg直下への追加順=winfo_children()の返す順、実測で確認
    済みのtkinterの既定挙動)。"""
    app_root = str(tmp_path)
    ctx = dlg_mod.LabRawSwayParamsContext(app_root=app_root)
    dlg = dlg_mod.show_lab_raw_sway_params_dialog(hidden_root, ctx)
    try:
        scales = _all_scales(dlg)
        assert len(scales) == len(FAMILIES) * len(PARAM_KEYS)
        i = 0
        for family in FAMILIES:
            for key in PARAM_KEYS:
                assert float(scales[i].get()) == store.DEFAULT_PARAMS[family][key], (
                    f"{family}.{key}: スライダー初期値が既定値と不一致")
                i += 1
    finally:
        dlg.destroy()


def test_dialog_ok_without_change_keeps_defaults(hidden_root, tmp_path):
    """④無退行: デフォルトのままOKを押しても、保存後の状態はやはり
    DEFAULT_PARAMSと完全一致すること。"""
    import tkinter as tk
    app_root = str(tmp_path)
    ctx = dlg_mod.LabRawSwayParamsContext(app_root=app_root)
    dlg = dlg_mod.show_lab_raw_sway_params_dialog(hidden_root, ctx)
    try:
        ok_btn = [w for w in dlg.winfo_children()
                  if isinstance(w, tk.Button) and w.cget("text") == i18n.S("BtnOk")][0]
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    assert store.load_params(app_root) == store.DEFAULT_PARAMS
    assert store.is_active(app_root) is False


def test_negative_control_moving_slider_produces_non_default_state(hidden_root, tmp_path):
    """負の対照: いずれか1本のスライダーを動かしてOKを押すと、既定から
    外れた状態が保存されること。"""
    import tkinter as tk
    app_root = str(tmp_path)
    ctx = dlg_mod.LabRawSwayParamsContext(app_root=app_root)
    dlg = dlg_mod.show_lab_raw_sway_params_dialog(hidden_root, ctx)
    try:
        scales = _all_scales(dlg)
        scales[0].set(scales[0].cget("to"))  # 最大値へ動かす
        ok_btn = [w for w in dlg.winfo_children()
                  if isinstance(w, tk.Button) and w.cget("text") == i18n.S("BtnOk")][0]
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    assert store.is_active(app_root) is True
    assert store.get_job_override(app_root) is not None


def test_dialog_cancel_close_does_not_save(hidden_root, tmp_path):
    """×で閉じた場合は何も書き込まれない(drop_bones/dt_flag_head_hideダイアログと
    同じ「OKで適用、破棄で何もしない」流儀)。"""
    app_root = str(tmp_path)
    ctx = dlg_mod.LabRawSwayParamsContext(app_root=app_root)
    dlg = dlg_mod.show_lab_raw_sway_params_dialog(hidden_root, ctx)
    dlg.destroy()
    assert store.load_params(app_root) == store.DEFAULT_PARAMS
    assert not os.path.exists(store._state_path(app_root))  # noqa: SLF001


def test_dialog_reset_button_restores_defaults_on_sliders(hidden_root, tmp_path):
    """ダイアログ内「既定値に戻す」ボタン: スライダーを動かした後に押すと、
    OK押下前でも表示上デフォルトへ戻り、そのままOKすればDEFAULT_PARAMSが
    保存される。"""
    import tkinter as tk
    app_root = str(tmp_path)
    ctx = dlg_mod.LabRawSwayParamsContext(app_root=app_root)
    dlg = dlg_mod.show_lab_raw_sway_params_dialog(hidden_root, ctx)
    try:
        scales = _all_scales(dlg)
        scales[0].set(scales[0].cget("to"))
        reset_btn = [w for w in dlg.winfo_children()
                     if isinstance(w, tk.Button)
                     and w.cget("text") == i18n.S("LabRawSwayParamsResetButton")][0]
        reset_btn.invoke()
        ok_btn = [w for w in dlg.winfo_children()
                  if isinstance(w, tk.Button) and w.cget("text") == i18n.S("BtnOk")][0]
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    assert store.load_params(app_root) == store.DEFAULT_PARAMS


def test_dialog_reflects_existing_saved_state(hidden_root, tmp_path):
    """既に非既定値が保存済みの状態でダイアログを開くと、その値でスライダーが
    初期化されること。"""
    app_root = str(tmp_path)
    params = copy.deepcopy(store.DEFAULT_PARAMS)
    params["tail"]["stiffness"] = 0.42
    store.save_params(app_root, params)
    ctx = dlg_mod.LabRawSwayParamsContext(app_root=app_root)
    dlg = dlg_mod.show_lab_raw_sway_params_dialog(hidden_root, ctx)
    try:
        scales = _all_scales(dlg)
        # 家系tailの先頭パラメータ(stiffness)は列0・行0の最初のScaleに対応
        # (show_lab_raw_sway_params_dialogの構築順: FAMILIES[0]の
        # PARAM_KEYS順、両者ともstore.FAMILIES/PARAM_KEYSのタプル順と一致)。
        assert float(scales[0].get()) == 0.42
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 3. pipeline_runner.write_job() 結線(ラボ憲章④: job.jsonキー不在=
#    従来動作と完全同一)
# ---------------------------------------------------------------------------

def _make_app_root(tmp_path):
    app_root = tmp_path / "app_root"
    app_root.mkdir()
    blender_dir = app_root / "tools" / "blender-4.3.2-windows-x64"
    blender_dir.mkdir(parents=True)
    (blender_dir / "blender.exe").write_bytes(b"")
    (app_root / "third_party").mkdir()
    (app_root / "third_party" / "VRM_Addon_for_Blender-Extension-4_4_0.zip").write_bytes(b"")
    return str(app_root)


def _make_vrm(tmp_path, name="MyAvatar.vrm"):
    vrm = tmp_path / name
    vrm.write_bytes(b"")
    return str(vrm)


def test_write_job_default_omits_lab_raw_sway_params_key(tmp_path):
    """負の対照込み④無退行: ストア未設定(既定)のときはjob.jsonに
    "lab_raw_sway_params"キー自体が現れない(このラボ機能追加前のjob.jsonと
    完全一致)。"""
    app_root = _make_app_root(tmp_path)
    job_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    assert "lab_raw_sway_params" not in job


def test_write_job_nondefault_store_value_is_written(tmp_path):
    app_root = _make_app_root(tmp_path)
    params = copy.deepcopy(store.DEFAULT_PARAMS)
    params["ear"]["limit_angle"] = 45.0
    store.save_params(app_root, params)
    job_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["lab_raw_sway_params"]["ear"]["limit_angle"] == 45.0
    assert job["lab_raw_sway_params"]["tail"] == store.DEFAULT_PARAMS["tail"]


def test_write_job_explicit_default_store_value_omits_key(tmp_path):
    """負の対照: 明示的にstoreへDEFAULT_PARAMSを保存した場合もキー不在
    (既定と同一挙動)。"""
    app_root = _make_app_root(tmp_path)
    store.save_params(app_root, copy.deepcopy(store.DEFAULT_PARAMS))
    job_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    assert "lab_raw_sway_params" not in job
