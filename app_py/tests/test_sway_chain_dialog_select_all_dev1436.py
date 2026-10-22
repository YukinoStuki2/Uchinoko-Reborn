# test_sway_chain_dialog_select_all_dev1436.py -- dev#1436(改善要望、
# WP wp_labdlg_fix)の単体テスト。
#
# オーナー要望: ラボ「揺れもの詳細設定」ダイアログに「全てON」「全てOFF」
# ボタンを追加する。
#
# 実tk.Tk()は作らない(conftest.pyの共有hidden_root、既存慣例踏襲)。
from __future__ import annotations

import os
import sys
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import sway_chain_dialog as scd  # noqa: E402


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


def _row_checkbuttons(dlg) -> list[tk.Checkbutton]:
    return [w for w in _walk_widgets(dlg) if isinstance(w, tk.Checkbutton)]


def _checkbox_bool(cb: tk.Checkbutton) -> bool:
    return bool(int(cb.getvar(cb.cget("variable"))))


def _find_button(dlg, text: str) -> tk.Button:
    for w in _walk_widgets(dlg):
        if isinstance(w, tk.Button) and w.cget("text") == text:
            return w
    raise AssertionError(f"button not found: {text!r}")


def _open_sample_dialog(hidden_root, tmp_path):
    i18n.set_language("ja")
    ctx = scd.SwayChainContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm",
        sample_mode=True,
    )
    return scd.show_sway_chain_dialog(hidden_root, ctx)


def test_select_all_turns_every_row_on(hidden_root, tmp_path):
    dlg = _open_sample_dialog(hidden_root, tmp_path)
    try:
        # SAMPLE_CHAINSは既定OFFの行を含む(スカート・髪)ので、全部ONに
        # なっていない状態からスタートすることを前提に確認する。
        before = [_checkbox_bool(cb) for cb in _row_checkbuttons(dlg)]
        assert not all(before), "前提が崩れている(SAMPLE_CHAINSに既定OFF行が無い?)"

        _find_button(dlg, i18n.S("BtnLabSwayChainSelectAll")).invoke()

        after = [_checkbox_bool(cb) for cb in _row_checkbuttons(dlg)]
        assert after, "全てONボタン後に行が消えている"
        assert all(after), "全てONボタンを押しても一部がOFFのまま"
    finally:
        dlg.destroy()


def test_select_none_turns_every_row_off(hidden_root, tmp_path):
    dlg = _open_sample_dialog(hidden_root, tmp_path)
    try:
        before = [_checkbox_bool(cb) for cb in _row_checkbuttons(dlg)]
        assert any(before), "前提が崩れている(SAMPLE_CHAINSに既定ON行が無い?)"

        _find_button(dlg, i18n.S("BtnLabSwayChainSelectNone")).invoke()

        after = [_checkbox_bool(cb) for cb in _row_checkbuttons(dlg)]
        assert after, "全てOFFボタン後に行が消えている"
        assert not any(after), "全てOFFボタンを押しても一部がONのまま"
    finally:
        dlg.destroy()


def test_select_all_then_ok_then_reopen_persists(hidden_root, tmp_path):
    """全てON→OK→再オープンでも全行ONのままであること(dev#1438の修正と
    組み合わさって初めて成立する、統合的な確認)。"""
    app_root = str(tmp_path)
    avatar_path = "C:\\fake.vrm"
    dlg = _open_sample_dialog(hidden_root, tmp_path)
    _find_button(dlg, i18n.S("BtnLabSwayChainSelectAll")).invoke()
    _find_button(dlg, i18n.S("BtnOk")).invoke()  # save + destroy

    dlg2 = _open_sample_dialog(hidden_root, tmp_path)
    try:
        after = [_checkbox_bool(cb) for cb in _row_checkbuttons(dlg2)]
        assert after and all(after), (
            "全てON->OK->再オープンで一部がOFFへ巻き戻っている"
        )
    finally:
        dlg2.destroy()
