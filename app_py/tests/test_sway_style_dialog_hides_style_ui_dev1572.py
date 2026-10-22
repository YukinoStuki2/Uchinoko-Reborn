# test_sway_style_dialog_hides_style_ui_dev1572.py -- dev#1572是正WP
# (第2便PR#1584の過修正の是正、2026-08-19)の受入条件3: 統合パネル
# (app_py\ui\sway_style_dialog.py)を製品既定(_SWAY_STYLE_PICKER_VISIBLE=
# False、上書きしない)で開いたとき、「ゆれかた」関連ウィジェット
# (スタイル一覧ピッカー・CRUD・生パラメータスライダー・「筆」機構・鎖ごとの
# スタイル表示[hardness列]・スロット数)が到達不能であること、かつ
# 「残す」と指定された要素(鎖一覧・安全域スピンボックス・OK/キャンセル)は
# 引き続き到達可能であることを固定する。
#
# 負の対照(ラボ憲章の作法どおり): _SWAY_STYLE_PICKER_VISIBLE をTrueへ
# 上書きすると同じウィジェットが出現することを示し、この試験が
# 「そもそも探し方が間違っていて常にfalseになる」壊れた検査でないことを
# 証明する(test_sway_style_dialog_wp_sway_panel.py/test_sway_style_dialog_
# pbunit_wp_w2c.py の同名フィクスチャが実際にこの上書きを使っている)。
#
# 実tk.Tk()は作らない(conftest.pyの共有hidden_root、既存慣例踏襲)。
from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import sway_style_dialog as dlg_mod  # noqa: E402

AVATAR = "C:\\fake.vrm"


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _find_all(root, cls):
    return [w for w in _walk(root) if isinstance(w, cls)]


def _button_texts(root):
    return [
        w.cget("text") for w in _walk(root)
        if isinstance(w, tk.Button) and hasattr(w, "cget")
    ]


def _make_ctx(app_root, sample_mode=True):
    return dlg_mod.SwayStyleContext(
        app_root=app_root, work_root=app_root, avatar_path=AVATAR, sample_mode=sample_mode,
    )


# ---------------------------------------------------------------------------
# 1. 製品既定(隠蔽中)での到達不能性。
# ---------------------------------------------------------------------------

def test_default_flag_is_hidden():
    """本試験群の前提: 製品としての既定値はFalse(隠蔽)であること自体を
    固定する(このテストファイルの他のテストは何もオーバーライドしない
    ため、この既定値が壊れると全テストが無意味になる)。"""
    assert dlg_mod._SWAY_STYLE_PICKER_VISIBLE is False


def test_no_raw_param_sliders_by_default(hidden_root, tmp_path):
    """生パラメータ編集(tk.Scale)は1個も生成されない。"""
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, _make_ctx(str(tmp_path)))
    try:
        assert _find_all(dlg, tk.Scale) == []
    finally:
        dlg.destroy()


def test_no_style_crud_buttons_by_default(hidden_root, tmp_path):
    """ゆれかた一覧の作成/改名/複製/削除ボタンが1つも生成されない。"""
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, _make_ctx(str(tmp_path)))
    try:
        texts = _button_texts(dlg)
        for key in (
            "BtnLabSwayStyleCreate", "BtnLabSwayStyleRename", "BtnLabSwayStyleDuplicate",
        ):
            assert i18n.S(key) not in texts, f"{key}のボタンが残っている"
    finally:
        dlg.destroy()


def test_no_brush_or_slot_or_force_setup_buttons_by_default(hidden_root, tmp_path):
    """「筆」系(全てに塗る)・スロット案内・「特殊ボーンを強制セットアップ」
    のいずれも生成されない。"""
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, _make_ctx(str(tmp_path)))
    try:
        texts = _button_texts(dlg)
        assert i18n.S("BtnLabSwayStyleBulkApply") not in texts
        assert i18n.S("BtnLabSwayStyleForceSetup") not in texts

        labels_text = [
            w.cget("text") for w in _find_all(dlg, tk.Label) if w.cget("text")
        ]
        assert i18n.S("LabSwayStyleSlotHint") not in labels_text
        assert i18n.S("LabSwayStyleStylesHint") not in labels_text
        assert i18n.S("LabSwayStyleChainsHint") not in labels_text
    finally:
        dlg.destroy()


def test_no_style_picker_entry_and_no_style_name_entry(hidden_root, tmp_path):
    """ゆれかた一覧の名前入力欄(Entry)が生成されない――手動追加欄の
    Entry(鎖一覧側、残す対象)だけが存在する(1個ちょうど)。"""
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, _make_ctx(str(tmp_path)))
    try:
        entries = [w for w in _walk(dlg) if type(w) is tk.Entry]
        assert len(entries) == 1, (
            f"Entryが{len(entries)}個ある(想定=手動追加欄1個のみ、"
            "ゆれかた一覧の名前入力欄が残っている可能性)")
    finally:
        dlg.destroy()


def test_row_label_has_no_style_suffix_by_default(hidden_root, tmp_path):
    """鎖ごとの「ゆれかた」列(" -> スタイル名"のsuffix・色分け)が
    行ラベルに現れない(隠蔽対象)。"""
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, _make_ctx(str(tmp_path)))
    try:
        row_buttons = [
            w for w in _find_all(dlg, tk.Button)
            if i18n.S("BtnOk") != w.cget("text") and i18n.S("BtnCancel") != w.cget("text")
            and i18n.S("BtnLabSwayChainReset") != w.cget("text")
            and i18n.S("BtnSwayChainManualAdd") != w.cget("text")
        ]
        assert row_buttons, "検証には一覧行が最低1行必要(--sample未反映?)"
        for btn in row_buttons:
            assert " -> " not in btn.cget("text"), (
                f"行ラベルにゆれかたsuffixが残っている: {btn.cget('text')!r}")
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 2. 「残す」対象は引き続き到達可能であること。
# ---------------------------------------------------------------------------

def test_chain_list_rows_and_safety_margin_spinboxes_remain(hidden_root, tmp_path):
    """鎖一覧(行ボタン)・安全域スピンボックスは引き続き生成・操作できる。"""
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, _make_ctx(str(tmp_path)))
    try:
        spinboxes = _find_all(dlg, ttk.Spinbox)
        assert spinboxes, "安全域スピンボックスが1つも無い(残す対象のはず)"
        for sb in spinboxes:
            assert int(sb.get()) == dlg_mod.DEFAULT_SAFETY_MARGIN
    finally:
        dlg.destroy()


def test_ok_and_cancel_buttons_remain(hidden_root, tmp_path):
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, _make_ctx(str(tmp_path)))
    try:
        texts = _button_texts(dlg)
        assert i18n.S("BtnOk") in texts
        assert i18n.S("BtnCancel") in texts
    finally:
        dlg.destroy()


def test_row_click_is_inert_without_wired_enabled_field(hidden_root, tmp_path):
    """「残す: ON/OFFチェック(現状どおり未結線の見た目でよい。結線するな)」
    の実装者解釈: 鎖一覧の行(クリック可能なtk.Button、旧「筆で塗る」
    ハンドラのまま)は、ゆれかたピッカーが無いため「筆」を持つ手段が
    存在せず、クリックしても行のstyleが変化しない(=見た目は残るが
    未結線)。既存のenabledフィールド(sway_chain_override_store)にも
    一切触れない(第3便=laneG2の領分、本WPでは結線しない)。"""
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, _make_ctx(str(tmp_path)))
    try:
        row_buttons = [
            w for w in _find_all(dlg, tk.Button)
            if i18n.S("BtnOk") != w.cget("text") and i18n.S("BtnCancel") != w.cget("text")
            and i18n.S("BtnLabSwayChainReset") != w.cget("text")
            and i18n.S("BtnSwayChainManualAdd") != w.cget("text")
        ]
        assert row_buttons
        before = row_buttons[0].cget("text")
        row_buttons[0].invoke()
        after = row_buttons[0].cget("text")
        assert before == after, "行クリックで表示が変化した(意図せず結線されている)"
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 3. 負の対照: フラグをTrueへ上書きすると同じウィジェットが出現すること。
# ---------------------------------------------------------------------------

def test_negative_control_flag_true_reveals_style_ui(hidden_root, tmp_path):
    """このテストファイルの検査方法自体が壊れていないことの証明:
    _SWAY_STYLE_PICKER_VISIBLE=Trueへ切り替えると、上のテストで
    「無い」ことを確認したボタン・スライダーが実際に出現する。"""
    original = dlg_mod._SWAY_STYLE_PICKER_VISIBLE
    dlg_mod._SWAY_STYLE_PICKER_VISIBLE = True
    try:
        dlg = dlg_mod.show_sway_style_dialog(hidden_root, _make_ctx(str(tmp_path)))
        try:
            texts = _button_texts(dlg)
            assert i18n.S("BtnLabSwayStyleCreate") in texts
            assert i18n.S("BtnLabSwayStyleBulkApply") in texts
            assert i18n.S("BtnLabSwayStyleForceSetup") in texts
            assert _find_all(dlg, tk.Scale), "Trueなのにスライダーが1個も無い"
        finally:
            dlg.destroy()
    finally:
        dlg_mod._SWAY_STYLE_PICKER_VISIBLE = original
