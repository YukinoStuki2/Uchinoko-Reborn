# test_dt_flag_head_hide_dialog_dev1258.py -- dev#1258 WP-E(2026-08-09
# オーナー裁定)ラボ機能「差替え中装備のみ頭OFF」。
#
# app_py\ui\dt_flag_head_hide_dialog.py + app_py\dt_flag_head_hide_store.py
# の単体テスト。equipment_select_dialog/headequip_select_dialogのdev165/
# dev#277テストと同じ骨格(実tk.Tk()は作らない、conftest.pyの共有
# hidden_root、既存慣例踏襲)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import dt_flag_head_hide_store as store  # noqa: E402
from ui import dt_flag_head_hide_dialog as dlg_mod  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 選択状態の永続化 + 状態サマリ(ラボ憲章④: 既定=OFF)
# ---------------------------------------------------------------------------

def test_default_state_is_off_and_inactive(tmp_path):
    app_root = str(tmp_path)
    assert store.load_enabled(app_root) is False
    assert store.is_active(app_root) is False
    assert store.state_summary(app_root) is None


def test_save_then_load_round_trip(tmp_path):
    app_root = str(tmp_path)
    store.save_enabled(app_root, True)
    assert store.load_enabled(app_root) is True
    assert store.is_active(app_root) is True
    assert store.state_summary(app_root) is not None


def test_reset_clears_to_off(tmp_path):
    app_root = str(tmp_path)
    store.save_enabled(app_root, True)
    assert store.is_active(app_root) is True
    store.reset(app_root)
    assert store.load_enabled(app_root) is False
    assert store.is_active(app_root) is False


def test_corrupt_state_file_falls_back_to_off(tmp_path):
    app_root = str(tmp_path)
    with open(store._state_path(app_root), "w", encoding="utf-8") as f:
        f.write("{ this is not valid json")
    assert store.load_enabled(app_root) is False


def test_non_bool_enabled_value_falls_back_to_off(tmp_path):
    """負の対照: 壊れた形式(enabledが文字列等)は既定Falseへフォールバックすること。"""
    app_root = str(tmp_path)
    import json
    with open(store._state_path(app_root), "w", encoding="utf-8") as f:
        json.dump({"enabled": "yes"}, f)
    assert store.load_enabled(app_root) is False


def test_registry_descriptor_shape():
    d = dlg_mod.LAB_REGISTRY_DESCRIPTOR
    assert d["id"] == "dt_flag_head_hide"
    assert isinstance(d["name_key"], str)
    for lang in i18n.LANGS:
        assert i18n.S(d["name_key"], lang) and not i18n.S(d["name_key"], lang).startswith("??")
    assert callable(d["state_summary"])
    assert callable(d["open_dialog"])
    assert callable(d["reset"])


def test_all_i18n_keys_present_in_all_languages():
    """i18nキー漏れ試験: このWPが追加した全キーが5言語で埋まっていること。"""
    keys = [
        "LabFeatureDtFlagHeadHide",
        "LabDtFlagHeadHideDialogTitle",
        "LabDtFlagHeadHideHint",
        "LabDtFlagHeadHideCheckboxLabel",
        "LabDtFlagHeadHideSummary",
    ]
    for key in keys:
        for lang in i18n.LANGS:
            text = i18n.S(key, lang)
            assert text and not text.startswith("??"), (
                f"i18nキー欠落: {key} / {lang}")


# ---------------------------------------------------------------------------
# 2. ダイアログ本体の配線(実Toplevel、hidden_root経由)
# ---------------------------------------------------------------------------

def test_dialog_default_checkbox_is_unchecked(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = dlg_mod.DtFlagHeadHideContext(app_root=app_root)
    dlg = dlg_mod.show_dt_flag_head_hide_dialog(hidden_root, ctx)
    try:
        checks = [w for w in dlg.winfo_children() if isinstance(w, __import__("tkinter").Checkbutton)]
        assert len(checks) == 1
        var = checks[0].cget("variable")
        assert int(dlg.getvar(var)) == 0  # tk boolean var, unchecked
    finally:
        dlg.destroy()


def test_dialog_ok_without_change_keeps_default_off(hidden_root, tmp_path):
    """④無退行: デフォルト(未チェック)のままOKを押しても、保存後の状態は
    やはりOFF(=既定と完全一致)であること。"""
    import tkinter as tk
    app_root = str(tmp_path)
    ctx = dlg_mod.DtFlagHeadHideContext(app_root=app_root)
    dlg = dlg_mod.show_dt_flag_head_hide_dialog(hidden_root, ctx)
    try:
        ok_btn = [w for w in dlg.winfo_children()
                  if isinstance(w, tk.Button) and w.cget("text") == i18n.S("BtnOk")][0]
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    assert store.load_enabled(app_root) is False


def test_negative_control_checking_produces_non_default_state(hidden_root, tmp_path):
    """負の対照: チェックを入れてOKを押すと、既定から外れた状態(ON)が
    保存されること。"""
    import tkinter as tk
    app_root = str(tmp_path)
    ctx = dlg_mod.DtFlagHeadHideContext(app_root=app_root)
    dlg = dlg_mod.show_dt_flag_head_hide_dialog(hidden_root, ctx)
    try:
        check = [w for w in dlg.winfo_children() if isinstance(w, tk.Checkbutton)][0]
        check.invoke()  # チェックON
        ok_btn = [w for w in dlg.winfo_children()
                  if isinstance(w, tk.Button) and w.cget("text") == i18n.S("BtnOk")][0]
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    assert store.load_enabled(app_root) is True


def test_dialog_cancel_close_does_not_save(hidden_root, tmp_path):
    """×で閉じた場合は何も書き込まれない(drop_bonesダイアログと同じ
    「OKで適用、破棄で何もしない」流儀)。"""
    app_root = str(tmp_path)
    ctx = dlg_mod.DtFlagHeadHideContext(app_root=app_root)
    dlg = dlg_mod.show_dt_flag_head_hide_dialog(hidden_root, ctx)
    dlg.destroy()
    assert store.load_enabled(app_root) is False
    assert not os.path.exists(store._state_path(app_root))


def test_dialog_reflects_existing_saved_state(hidden_root, tmp_path):
    """既にON保存済みの状態でダイアログを開くと、チェックが入った状態で
    表示されること。"""
    import tkinter as tk
    app_root = str(tmp_path)
    store.save_enabled(app_root, True)
    ctx = dlg_mod.DtFlagHeadHideContext(app_root=app_root)
    dlg = dlg_mod.show_dt_flag_head_hide_dialog(hidden_root, ctx)
    try:
        check = [w for w in dlg.winfo_children() if isinstance(w, tk.Checkbutton)][0]
        var = check.cget("variable")
        assert int(dlg.getvar(var)) == 1
    finally:
        dlg.destroy()
