# test_gender_select_dialog_dev336.py -- dev#336(性別限定)ラボ機能。
#
# app_py\ui\gender_select_dialog.py の単体テスト。equipment_select_dialog.pyの
# テスト慣例(hidden_root経由の実Toplevel、withdraw済み)を踏襲するが、
# パルワールド側カタログ解決(subprocess/pak)が無いぶん大幅に単純。
from __future__ import annotations

import os
import sys
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import gender_select_dialog as gsd  # noqa: E402


def _find_radiobuttons(widget):
    out = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Radiobutton):
            out.append(child)
        out.extend(_find_radiobuttons(child))
    return out


def _find_button_by_text(widget, text):
    for child in widget.winfo_children():
        if isinstance(child, tk.Button) and child.cget("text") == text:
            return child
        found = _find_button_by_text(child, text)
        if found is not None:
            return found
    return None


# ---------------------------------------------------------------------------
# 1. レジストリ記述子
# ---------------------------------------------------------------------------

def test_registry_descriptor_shape():
    d = gsd.LAB_REGISTRY_DESCRIPTOR
    assert d["id"] == "gender_filter"
    assert isinstance(d["name_key"], str)
    for lang in i18n.LANGS:
        assert i18n.S(d["name_key"], lang) and not i18n.S(d["name_key"], lang).startswith("??")
    assert callable(d["state_summary"])
    assert callable(d["open_dialog"])
    assert callable(d["reset"])


# ---------------------------------------------------------------------------
# 2. ダイアログ本体の配線(実Toplevel、hidden_root経由)
# ---------------------------------------------------------------------------

def test_dialog_builds_three_radio_options(hidden_root, tmp_path):
    ctx = gsd.GenderSelectContext(app_root=str(tmp_path))
    dlg = gsd.show_gender_select_dialog(hidden_root, ctx)
    try:
        radios = _find_radiobuttons(dlg)
        assert len(radios) == 3
        texts = {r.cget("text") for r in radios}
        assert texts == {
            i18n.S("LabGenderFilterOptionBoth"),
            i18n.S("LabGenderFilterOptionMaleOnly"),
            i18n.S("LabGenderFilterOptionFemaleOnly"),
        }
    finally:
        dlg.destroy()


def test_dialog_defaults_to_both_when_unset(hidden_root, tmp_path):
    ctx = gsd.GenderSelectContext(app_root=str(tmp_path))
    dlg = gsd.show_gender_select_dialog(hidden_root, ctx)
    try:
        ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    finally:
        pass
    # 既定(未変更)のままOKを押しても、保存される値は既定(None=両方)。
    assert gsd.load_selected_gender(str(tmp_path)) is None


def test_dialog_preselects_previously_saved_male(hidden_root, tmp_path):
    gsd.save_selected_gender(str(tmp_path), "Male")
    ctx = gsd.GenderSelectContext(app_root=str(tmp_path))
    dlg = gsd.show_gender_select_dialog(hidden_root, ctx)
    try:
        ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    finally:
        pass
    # プリセレクトされたMaleのままOKを押すと、Maleのまま保存され続ける
    # (=正しくプリセレクトされていたことの間接証拠)。
    assert gsd.load_selected_gender(str(tmp_path)) == "Male"


def test_negative_control_selecting_male_only_saves_male(hidden_root, tmp_path):
    """負の対照: 既定(両方)から男のみへ切り替えてOKすると、Maleとして
    保存される(=job["genders"]=["Male"]の唯一の入力になる)。"""
    ctx = gsd.GenderSelectContext(app_root=str(tmp_path))
    dlg = gsd.show_gender_select_dialog(hidden_root, ctx)
    radios = _find_radiobuttons(dlg)
    male_radio = next(r for r in radios if r.cget("text") == i18n.S("LabGenderFilterOptionMaleOnly"))
    male_radio.invoke()

    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert gsd.load_selected_gender(str(tmp_path)) == "Male"
    assert gsd.is_active(str(tmp_path)) is True


def test_negative_control_selecting_female_only_saves_female(hidden_root, tmp_path):
    ctx = gsd.GenderSelectContext(app_root=str(tmp_path))
    dlg = gsd.show_gender_select_dialog(hidden_root, ctx)
    radios = _find_radiobuttons(dlg)
    female_radio = next(
        r for r in radios if r.cget("text") == i18n.S("LabGenderFilterOptionFemaleOnly"))
    female_radio.invoke()

    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert gsd.load_selected_gender(str(tmp_path)) == "Female"
    assert gsd.is_active(str(tmp_path)) is True


def test_switching_back_to_both_resets_to_default(hidden_root, tmp_path):
    gsd.save_selected_gender(str(tmp_path), "Female")
    ctx = gsd.GenderSelectContext(app_root=str(tmp_path))
    dlg = gsd.show_gender_select_dialog(hidden_root, ctx)
    radios = _find_radiobuttons(dlg)
    both_radio = next(r for r in radios if r.cget("text") == i18n.S("LabGenderFilterOptionBoth"))
    both_radio.invoke()

    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert gsd.load_selected_gender(str(tmp_path)) is None
    assert gsd.is_active(str(tmp_path)) is False


def test_dialog_cancel_does_not_save(hidden_root, tmp_path):
    ctx = gsd.GenderSelectContext(app_root=str(tmp_path))
    dlg = gsd.show_gender_select_dialog(hidden_root, ctx)
    radios = _find_radiobuttons(dlg)
    male_radio = next(r for r in radios if r.cget("text") == i18n.S("LabGenderFilterOptionMaleOnly"))
    male_radio.invoke()
    # ×で閉じる(OKを押さない、equipment_select_dialog.pyにはCancelボタンが
    # あるがgender_select_dialog.pyはOK+×のみの最小実装。ラボ憲章②)。
    dlg.destroy()

    assert gsd.load_selected_gender(str(tmp_path)) is None


def test_dialog_follows_language_switch(hidden_root, tmp_path):
    i18n.set_language("ja")
    ctx = gsd.GenderSelectContext(app_root=str(tmp_path))
    dlg = gsd.show_gender_select_dialog(hidden_root, ctx)
    try:
        assert dlg.title() == i18n.S("LabGenderFilterDialogTitle", "ja")
        i18n.apply_language("en")
        try:
            assert dlg.title() == i18n.S("LabGenderFilterDialogTitle", "en")
            assert _find_button_by_text(dlg, i18n.S("BtnOk", "en")) is not None
            radios = _find_radiobuttons(dlg)
            texts = {r.cget("text") for r in radios}
            assert i18n.S("LabGenderFilterOptionMaleOnly", "en") in texts
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()


def test_append_log_called_on_save(hidden_root, tmp_path):
    logs = []
    ctx = gsd.GenderSelectContext(app_root=str(tmp_path), append_log=logs.append)
    dlg = gsd.show_gender_select_dialog(hidden_root, ctx)
    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()
    assert logs
    assert "gender_filter" in logs[-1]
