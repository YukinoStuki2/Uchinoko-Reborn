# test_preflight_warning_dialog_dev1230.py -- dev#1230(2026-08-08オーナー
# 裁定): app_py\ui\preflight_warning_dialog.py の単体テスト。
# hidden_root(conftest.py、実Toplevel・withdraw済み)経由で実ウィジェット
# 構造を検査する(gender_select_dialog.pyのテスト慣例を踏襲)。
from __future__ import annotations

import os
import sys
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import preflight_warning_dialog as pwd  # noqa: E402


def _find_button_by_text(widget, text):
    for child in widget.winfo_children():
        if isinstance(child, tk.Button) and child.cget("text") == text:
            return child
        found = _find_button_by_text(child, text)
        if found is not None:
            return found
    return None


def _find_label_with_text(widget, text):
    for child in widget.winfo_children():
        if isinstance(child, tk.Label) and child.cget("text") == text:
            return child
        found = _find_label_with_text(child, text)
        if found is not None:
            return found
    return None


def test_dialog_shows_message_body_and_two_buttons(hidden_root):
    calls = {"remove": 0, "inquiry": 0}
    ctx = pwd.PreflightWarningContext(
        on_remove_mod=lambda: calls.__setitem__("remove", calls["remove"] + 1),
        on_open_inquiry=lambda: calls.__setitem__("inquiry", calls["inquiry"] + 1),
    )
    dlg = pwd.show_preflight_warning_dialog(hidden_root, ctx)
    try:
        assert _find_label_with_text(dlg, i18n.S("MsgPreflightWarningBody")) is not None
        assert _find_button_by_text(dlg, i18n.S("LabelRemove")) is not None
        assert _find_button_by_text(dlg, i18n.S("BtnReport")) is not None
    finally:
        if dlg.winfo_exists():
            dlg.destroy()


def test_remove_button_closes_dialog_and_calls_on_remove_mod_only(hidden_root):
    calls = {"remove": 0, "inquiry": 0}
    ctx = pwd.PreflightWarningContext(
        on_remove_mod=lambda: calls.__setitem__("remove", calls["remove"] + 1),
        on_open_inquiry=lambda: calls.__setitem__("inquiry", calls["inquiry"] + 1),
    )
    dlg = pwd.show_preflight_warning_dialog(hidden_root, ctx)
    remove_btn = _find_button_by_text(dlg, i18n.S("LabelRemove"))
    remove_btn.invoke()

    assert calls == {"remove": 1, "inquiry": 0}
    assert not dlg.winfo_exists()


def test_inquiry_button_closes_dialog_and_calls_on_open_inquiry_only(hidden_root):
    calls = {"remove": 0, "inquiry": 0}
    ctx = pwd.PreflightWarningContext(
        on_remove_mod=lambda: calls.__setitem__("remove", calls["remove"] + 1),
        on_open_inquiry=lambda: calls.__setitem__("inquiry", calls["inquiry"] + 1),
    )
    dlg = pwd.show_preflight_warning_dialog(hidden_root, ctx)
    inquiry_btn = _find_button_by_text(dlg, i18n.S("BtnReport"))
    inquiry_btn.invoke()

    assert calls == {"remove": 0, "inquiry": 1}
    assert not dlg.winfo_exists()


def test_closing_via_window_protocol_calls_neither_callback(hidden_root):
    # 負の対照: ×で閉じた場合はどちらのコールバックも呼ばれないこと
    # (gender_select_dialog.py等の「未保存で閉じる」と同型の設計)。
    # dev#855契約: 実tk.Tk()はhidden_rootフィクスチャ経由の1回だけに絞る
    # (conftest.pyの_guarded_tk_init)ため、ここでも新規にtk.Tk()を作らず
    # hidden_rootの子としてToplevelを作る。
    calls = {"remove": 0, "inquiry": 0}
    ctx = pwd.PreflightWarningContext(
        on_remove_mod=lambda: calls.__setitem__("remove", calls["remove"] + 1),
        on_open_inquiry=lambda: calls.__setitem__("inquiry", calls["inquiry"] + 1),
    )
    dlg = pwd.show_preflight_warning_dialog(hidden_root, ctx)
    # dlg.protocol("WM_DELETE_WINDOW") はTclコマンド名(文字列)を返す
    # (Pythonの関数オブジェクトではない)ため、tk.call()経由で実際に叩く。
    dlg.tk.call(dlg.protocol("WM_DELETE_WINDOW"))
    assert calls == {"remove": 0, "inquiry": 0}
    assert not dlg.winfo_exists()
