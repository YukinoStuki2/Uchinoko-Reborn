# test_sway_chain_dialog_safety_margin_dev1551.py -- dev#1551安全域WP
# (issue #1551「安全域」欄、2026-08-18オーナー最終裁定)のGUI回帰テスト。
#
# 「揺れもの詳細設定」ダイアログに追加した鎖ごとの「安全域」スピンボックスの
# 表示既定値・編集→OK→再オープンの往復・言語切替追従を、実際のダイアログ
# ウィジェット(ttk.Spinbox)で検証する。実tk.Tk()は作らない(conftest.pyの
# 共有hidden_root、既存慣例踏襲)。
from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import sway_chain_override_store as store  # noqa: E402
from ui import sway_chain_dialog as scd  # noqa: E402


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


def _row_spinboxes(dlg) -> list[ttk.Spinbox]:
    return [w for w in _walk_widgets(dlg) if isinstance(w, ttk.Spinbox)]


def _row_checkbuttons(dlg) -> list[tk.Checkbutton]:
    return [w for w in _walk_widgets(dlg) if isinstance(w, tk.Checkbutton)]


def _find_button(dlg, text: str) -> tk.Button:
    for w in _walk_widgets(dlg):
        if isinstance(w, tk.Button) and w.cget("text") == text:
            return w
    raise AssertionError(f"button not found: {text!r}")


def _label_texts(dlg) -> list[str]:
    texts = []
    for w in _walk_widgets(dlg):
        if isinstance(w, (tk.Label, tk.LabelFrame, tk.Checkbutton)):
            try:
                texts.append(w.cget("text"))
            except tk.TclError:
                pass
    return texts


_TAIL_DISPLAY = "J_Bip_C_Hips (Tail_01)"
_EARL_DISPLAY = "J_Bip_C_Head (EarL_01)"


def test_row_spinbox_default_value_is_product_default(hidden_root, tmp_path):
    """未編集のサンプル行はスピンボックス既定値=DEFAULT_SAFETY_MARGIN(1)。"""
    i18n.set_language("ja")
    ctx = scd.SwayChainContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm",
        sample_mode=True,
    )
    dlg = scd.show_sway_chain_dialog(hidden_root, ctx)
    try:
        spinboxes = _row_spinboxes(dlg)
        assert spinboxes, "検証には一覧行が最低1行必要(--sample未反映?)"
        for sb in spinboxes:
            assert int(sb.get()) == scd.DEFAULT_SAFETY_MARGIN
    finally:
        dlg.destroy()


def test_safety_margin_edit_ok_reopen_roundtrip(hidden_root, tmp_path):
    """スピンボックスで安全域を編集→OK→再オープンで値が保持されること
    (dev#1438の往復不具合と同じ形の回帰を、安全域フィールドで直接固定)。"""
    app_root = str(tmp_path)
    avatar_path = "C:\\fake.vrm"
    i18n.set_language("ja")

    ctx = scd.SwayChainContext(
        app_root=app_root, work_root=app_root, avatar_path=avatar_path, sample_mode=True)
    dlg = scd.show_sway_chain_dialog(hidden_root, ctx)
    checkboxes = {cb.cget("text"): cb for cb in _row_checkbuttons(dlg)}
    assert _TAIL_DISPLAY in checkboxes, "SAMPLE_CHAINSの構成が前提と違う"
    tail_idx = list(checkboxes.values()).index(checkboxes[_TAIL_DISPLAY])
    spinboxes = _row_spinboxes(dlg)
    spinboxes[tail_idx].delete(0, "end")
    spinboxes[tail_idx].insert(0, "3")
    spinboxes[tail_idx].event_generate("<KeyRelease>")
    # ttk.Spinbox手打ち編集はFocusOut/Enterで確定するのが通常操作だが、
    # textvariable.trace_add("write", ...)は直接のwidget.insert()でも
    # 即座に発火する(tkinterのStringVar/IntVar実装の仕様)。
    _find_button(dlg, i18n.S("BtnOk")).invoke()  # save_config + destroy

    ctx2 = scd.SwayChainContext(
        app_root=app_root, work_root=app_root, avatar_path=avatar_path, sample_mode=True)
    dlg2 = scd.show_sway_chain_dialog(hidden_root, ctx2)
    try:
        checkboxes2 = {cb.cget("text"): cb for cb in _row_checkbuttons(dlg2)}
        tail_idx2 = list(checkboxes2.values()).index(checkboxes2[_TAIL_DISPLAY])
        spinboxes2 = _row_spinboxes(dlg2)
        assert int(spinboxes2[tail_idx2].get()) == 3, (
            "編集した安全域が再オープンで反映されていない")
        # 触っていない行(耳L)は既定値のまま。
        earl_idx2 = list(checkboxes2.values()).index(checkboxes2[_EARL_DISPLAY])
        assert int(spinboxes2[earl_idx2].get()) == scd.DEFAULT_SAFETY_MARGIN
    finally:
        dlg2.destroy()

    # ストア側(ディスク)の内容もスピンボックス表示と完全一致すること。
    saved = store.load_config(app_root, avatar_path)
    saved_by_last_bone = {e["bones"][-1]: e.get("safety_margin") for e in saved}
    assert saved_by_last_bone.get("Tail_03") == 3
    # 触っていない行(既定のまま)はラボ憲章④により保存対象に含まれない。
    assert "EarL_02" not in saved_by_last_bone


def test_dialog_follows_language_switch_for_safety_margin_labels(hidden_root, tmp_path):
    """dev#1551で追加した列見出し・案内文もi18n.register()され、開いた
    まま言語切替すると追従することを確認する(dev#19 test_sway_chain_dialog_
    dev19.pyと同型のパターン)。"""
    i18n.set_language("ja")
    ctx = scd.SwayChainContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm",
        sample_mode=True,
    )
    dlg = scd.show_sway_chain_dialog(hidden_root, ctx)
    try:
        ja_texts = _label_texts(dlg)
        assert i18n.S("LabSwayChainColSafetyMargin", "ja") in ja_texts

        i18n.apply_language("en")
        try:
            en_texts = _label_texts(dlg)
            assert i18n.S("LabSwayChainColSafetyMargin", "en") in en_texts
            assert i18n.S("LabSwayChainColSafetyMargin", "ja") not in en_texts
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()
