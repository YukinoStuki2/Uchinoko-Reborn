# test_dialog_resize_no_clip_dev1367.py -- dev#1367(2026-08-15、実報告
# B5357788): 固定サイズ・リサイズ不可ダイアログのテキスト見切れ修正の受入試験。
#
# 対象: preflight_warning_dialog.py / support_dialog.py / gender_select_dialog.py
# / dt_flag_head_hide_dialog.py(WP指示書の書き込み許可範囲。lab_window.pyは
# 並行レーンが触るため対象外)。
#
# 検証方針: 「実際の最長級のi18n文言」(5言語中の最長=英語版が多くの場合最長)
# で本文を生成した上で、①resizable(True, True)であること②本文ラベルが
# tk.place(height=固定値)ではなくpack管理下(=高さが内容量に応じて自動計算)
# であること③フォントサイズを実測より大きくして(DPIスケーリング相当の
# 環境差を模した負荷)ウィンドウの要求サイズ(winfo_reqheight)が追従して
# 伸びることを確認する。
#
# 負の対照: 旧実装相当(resizable(False,False)+dlg.geometry()固定+
# label.place(height=旧定数)) をこのテスト内にミニ再現し、同じ大フォント条件
# でラベルの要求高さが固定height枠を超える(=見切れが起きる)ことを示す。
# 実機の全フォント環境で実文言だけでは超過しないケースもある(実測: 本WPの
# 開発機では既定フォントで旧定数を超えなかった)ため、大フォント条件を
# 「DPI要因」の代理として使う(実文言の長さ自体は「実際の最長級のi18n文言」
# の使用で担保する)。
#
# 実tkウィンドウはhidden_root(session-scoped、withdraw済み)のみ使用し、
# 一切deiconify/表示しない(ホスト画面へ干渉しない)。
from __future__ import annotations

import os
import sys
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import dt_flag_head_hide_dialog as dfd  # noqa: E402
from ui import gender_select_dialog as gsd  # noqa: E402
from ui import preflight_warning_dialog as pwd  # noqa: E402
from ui import support_dialog  # noqa: E402

# DPIスケーリング相当の負荷を掛けるための大フォント(実測: 本WPの開発機では
# 既定フォント+実文言だけでは旧固定heightを超過しないケースがあったため、
# 「環境差(DPI)」の代理としてフォントを大きくして再現する)。
_BIG_FONT = ("Segoe UI", 20)


def _find_widget(widget, cls, text=None):
    for child in widget.winfo_children():
        if isinstance(child, cls) and (text is None or child.cget("text") == text):
            return child
        found = _find_widget(child, cls, text)
        if found is not None:
            return found
    return None


def _find_all(widget, cls):
    out = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            out.append(child)
        out.extend(_find_all(child, cls))
    return out


def _resizable(dlg: tk.Toplevel) -> tuple:
    return dlg.tk.call("wm", "resizable", dlg._w)


def _is_visible_via_pack_chain(widget, root: tk.Misc) -> bool:
    """widgetからrootまでの祖先チェーンを遡り、各段がpack管理下で実際に
    表示中(pack_forgetされていない)かを確認する。support_dialog.py は
    段(stage1/2/3)の切替をpack_forget/packで行うため、非表示の段の内部
    ウィジェットはpack_info()自体は成功する(自分の直接の親には依然pack
    されている)——祖先を辿って初めて「forgetされた段の子孫」だと判別できる。"""
    w = widget
    while w is not root:
        try:
            w.pack_info()
        except tk.TclError:
            return False
        w = w.master
    return True


def _assert_reqheight_tracks_font(dlg: tk.Toplevel, label: tk.Label) -> None:
    """新実装の中核受入条件: 本文ラベルがplace(height=固定値)で天井に
    貼られていない(=pack管理下で、フォント/文言が大きくなればウィンドウの
    要求サイズもそれに追従して伸びる)ことを、実測で証明する。"""
    assert label.winfo_manager() == "pack", (
        "本文ラベルがpack管理下にない(place(height=固定値)が復活した疑い)"
    )
    dlg.update_idletasks()
    baseline_h = dlg.winfo_reqheight()
    original_font = label.cget("font")
    try:
        label.configure(font=_BIG_FONT)
        dlg.update_idletasks()
        grown_h = dlg.winfo_reqheight()
        # ダイアログ全体の要求サイズが、ラベルの要求サイズを下回って
        # 切り詰めていないこと(=見切れない)。
        assert dlg.winfo_reqheight() >= label.winfo_reqheight(), (
            f"ダイアログの要求高さ({dlg.winfo_reqheight()})がラベルの要求高さ"
            f"({label.winfo_reqheight()})を下回っている=見切れる構造が残っている"
        )
        assert grown_h > baseline_h, (
            "フォントを大きくしてもダイアログの要求サイズが伸びなかった"
            "(固定ジオメトリのまま=DPI/長文で見切れる構造が残っている)"
        )
    finally:
        label.configure(font=original_font)


def _negative_control_old_pattern_clips(
    hidden_root: tk.Misc, text: str, wraplength: int, old_fixed_height: int
) -> None:
    """修正前ロジック相当(resizable(False,False)+geometry固定+
    label.place(height=old_fixed_height))をミニ再現し、同じ大フォント条件で
    ラベルの要求高さが固定枠を超えること(=見切れが起きること)を示す。"""
    dlg = tk.Toplevel(hidden_root)
    try:
        dlg.resizable(False, False)
        dlg.geometry("440x260")
        label = tk.Label(
            dlg, text=text, anchor="nw", justify="left", wraplength=wraplength,
            font=_BIG_FONT,
        )
        label.place(x=12, y=12, width=wraplength + 4, height=old_fixed_height)
        dlg.update_idletasks()
        assert label.winfo_reqheight() > old_fixed_height, (
            "負の対照が成立しない: 大フォント条件でも旧固定heightを"
            f"超過しなかった(reqheight={label.winfo_reqheight()}, "
            f"old_fixed_height={old_fixed_height})"
        )
        # place(height=old_fixed_height)は要求サイズに関係なく指定値のまま
        # (=中身がreqheightを超えても表示枠は伸びない、見切れの実体)。
        assert label.winfo_reqheight() != old_fixed_height  # 前提: 固定値と一致していない
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 1. preflight_warning_dialog.py
# ---------------------------------------------------------------------------


def test_preflight_warning_dialog_resizable_and_body_not_clipped(hidden_root):
    ctx = pwd.PreflightWarningContext(on_remove_mod=lambda: None, on_open_inquiry=lambda: None)
    dlg = pwd.show_preflight_warning_dialog(hidden_root, ctx)
    try:
        assert _resizable(dlg) == (1, 1), "リサイズ不可のまま(dev#1367未修正)"
        body = _find_widget(dlg, tk.Label, i18n.S("MsgPreflightWarningBody"))
        assert body is not None
        _assert_reqheight_tracks_font(dlg, body)
    finally:
        if dlg.winfo_exists():
            dlg.destroy()


def test_preflight_warning_dialog_negative_control_old_pattern_clips(hidden_root):
    _negative_control_old_pattern_clips(
        hidden_root, i18n.S("MsgPreflightWarningBody", "en"), wraplength=412, old_fixed_height=190,
    )


# ---------------------------------------------------------------------------
# 2. support_dialog.py(3段。stage1のinfo_label・stage2のconfirm_labelを検証。
#    ログ本文log_edit_boxはScrollbarが付いていること=③の「スクロール可能」を
#    満たすことを確認)
# ---------------------------------------------------------------------------


def _make_support_ctx(**overrides):
    base = dict(
        tool_version="test",
        lang="en",
        channel="dev",
        get_os_description=lambda: "Windows 11",
        get_avatar_name=lambda: "a.vrm",
        get_status_text=lambda: "idle",
        build_diagnostics_text=lambda: "diag text",
    )
    base.update(overrides)
    return support_dialog.SupportContext(**base)


def test_support_dialog_resizable_and_stage1_info_not_clipped(hidden_root):
    # i18n.S()はダイアログ構築時点のi18n.current_lang(グローバル状態)を
    # 使う(ctx.langは送信payload用のメタデータで、表示文言には影響しない)。
    # 「実際の最長級のi18n文言」(英語)で構築するため、構築前にcurrent_langを
    # 明示的に切り替える。
    i18n.set_language("en")
    try:
        ctx = _make_support_ctx()
        state = support_dialog.SupportDialogState()
        dlg = support_dialog.show_support_dialog(hidden_root, state, ctx)
    finally:
        i18n.set_language("ja")
    try:
        assert _resizable(dlg) == (1, 1), "リサイズ不可のまま(dev#1367未修正)"
        info_label = _find_widget(dlg, tk.Label, i18n.S("SupportStage1Info", "en"))
        assert info_label is not None
        _assert_reqheight_tracks_font(dlg, info_label)
    finally:
        dlg.destroy()


def test_support_dialog_stage2_confirm_label_not_clipped_and_log_scrollable(hidden_root):
    # show_confirm_stage()はconfirm_labelの文言をボタン押下時(invoke時点)に
    # i18n.S()で動的計算する(構築時ではない)ため、invokeまでずっと"en"の
    # ままにしておく必要がある(構築直後に"ja"へ戻すと、invoke時にja文言が
    # 入ってしまい「最長級のi18n文言」の検証にならない)。
    i18n.set_language("en")
    try:
        ctx = _make_support_ctx()
        state = support_dialog.SupportDialogState()
        dlg = support_dialog.show_support_dialog(hidden_root, state, ctx)
        try:
            open_btn = _find_widget(dlg, tk.Button, i18n.S("BtnOpenInquiryForm", "en"))
            assert open_btn is not None
            open_btn.invoke()  # -> show_confirm_stage(): confirm_labelにテキスト(en)が入る

            # stage1のinfo_labelはpack_forgetされても文字列は残ったままなので
            # 「非空文字のLabel」だけでは判別できない。pack祖先チェーンを
            # 遡って「今まさに表示されている段」の子孫だけに絞る。
            visible_labels_with_text = [
                lbl for lbl in _find_all(dlg, tk.Label)
                if lbl.cget("text") and _is_visible_via_pack_chain(lbl, dlg)
            ]
            assert len(visible_labels_with_text) == 1, (
                f"表示中のテキスト付きLabelが1個でない: {visible_labels_with_text}"
            )
            confirm_label = visible_labels_with_text[0]
            assert i18n.S("SupportConfirmNewBody", "en") in confirm_label.cget("text")
            _assert_reqheight_tracks_font(dlg, confirm_label)

            # ③の受入(スクロール可能): log_edit_box(Text)と対になるScrollbarが
            # 実在すること。
            texts = _find_all(dlg, tk.Text)
            scrollbars = _find_all(dlg, tk.Scrollbar)
            assert texts, "log_edit_box(Text)が見つからない"
            assert scrollbars, "log_edit_boxにScrollbarが付いていない"
        finally:
            dlg.destroy()
    finally:
        i18n.set_language("ja")


def test_support_dialog_negative_control_old_pattern_clips(hidden_root):
    text = i18n.S("SupportChangedNotice", "en") + i18n.S("SupportConfirmAppendBody", "en")
    _negative_control_old_pattern_clips(hidden_root, text, wraplength=464, old_fixed_height=72)


# ---------------------------------------------------------------------------
# 3. gender_select_dialog.py
# ---------------------------------------------------------------------------


def test_gender_select_dialog_resizable_and_hint_not_clipped(hidden_root, tmp_path):
    ctx = gsd.GenderSelectContext(app_root=str(tmp_path))
    dlg = gsd.show_gender_select_dialog(hidden_root, ctx)
    try:
        assert _resizable(dlg) == (1, 1), "リサイズ不可のまま(dev#1367未修正)"
        hint = _find_widget(dlg, tk.Label, i18n.S("LabGenderFilterHint"))
        assert hint is not None
        _assert_reqheight_tracks_font(dlg, hint)
    finally:
        dlg.destroy()


def test_gender_select_dialog_negative_control_old_pattern_clips(hidden_root):
    _negative_control_old_pattern_clips(
        hidden_root, i18n.S("LabGenderFilterHint", "en"), wraplength=336, old_fixed_height=56,
    )


# ---------------------------------------------------------------------------
# 4. dt_flag_head_hide_dialog.py
# ---------------------------------------------------------------------------


def test_dt_flag_head_hide_dialog_resizable_and_desc_not_clipped(hidden_root, tmp_path):
    ctx = dfd.DtFlagHeadHideContext(app_root=str(tmp_path))
    dlg = dfd.show_dt_flag_head_hide_dialog(hidden_root, ctx)
    try:
        assert _resizable(dlg) == (1, 1), "リサイズ不可のまま(dev#1367未修正)"
        desc = _find_widget(dlg, tk.Label, i18n.S("LabDtFlagHeadHideHint"))
        assert desc is not None
        _assert_reqheight_tracks_font(dlg, desc)
    finally:
        dlg.destroy()


def test_dt_flag_head_hide_dialog_negative_control_old_pattern_clips(hidden_root):
    _negative_control_old_pattern_clips(
        hidden_root, i18n.S("LabDtFlagHeadHideHint", "en"), wraplength=416, old_fixed_height=130,
    )
