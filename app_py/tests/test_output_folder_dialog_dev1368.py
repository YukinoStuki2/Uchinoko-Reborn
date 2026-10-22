# test_output_folder_dialog_dev1368.py -- dev#1368(2026-08-15オーナー裁定)
# ラボ機能「出力先フォルダを開く」。
#
# app_py\ui\output_folder_dialog.py + lab_window.pyへの結線(OUTPUT_FOLDER_
# FEATURE)の単体テスト。dt_flag_head_hide/equipment_selectの既存テストと
# 同じ骨格(実tk.Tk()は作らない、conftest.pyの共有hidden_root)。
#
# 本機能はjob設定に一切触れないアクションのみのラボ機能のため、ラボ憲章④
# (既定値=未実装状態と完全一致)は「保存する状態自体が存在しない」ことで
# 自明に満たす——state_summary/resetが常にNone/no-opであることを固定する
# テストが、その④相当の検証を兼ねる。
from __future__ import annotations

import os
import sys
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import lab_window  # noqa: E402
from ui import output_folder_dialog as dlg_mod  # noqa: E402


def _find_children(widget, cls):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_find_children(child, cls))
    return found


def _find_button(widget, text: str):
    for btn in _find_children(widget, tk.Button):
        if btn.cget("text") == text:
            return btn
    return None


# ---------------------------------------------------------------------------
# 1. state_summary/reset(ラボ憲章④相当: 設定を持たないため常に既定)
# ---------------------------------------------------------------------------


def test_state_summary_always_none(tmp_path):
    assert dlg_mod.state_summary(str(tmp_path)) is None


def test_reset_is_noop(tmp_path):
    # 例外を出さず、何も作らない/消さないことだけを確認する。
    dlg_mod.reset(str(tmp_path))
    assert list(os.listdir(str(tmp_path))) == []


def test_registry_descriptor_shape():
    d = dlg_mod.LAB_REGISTRY_DESCRIPTOR
    assert d["id"] == "output_folder"
    assert isinstance(d["name_key"], str)
    for lang in i18n.LANGS:
        assert i18n.S(d["name_key"], lang) and not i18n.S(d["name_key"], lang).startswith("??")
    assert callable(d["state_summary"])
    assert callable(d["open_dialog"])
    assert callable(d["reset"])


def test_all_i18n_keys_present_in_all_languages():
    """i18nキー漏れ試験: このWPが追加した全キーが5言語で埋まっていること。"""
    keys = [
        "LabFeatureOutputFolder",
        "LabOutputFolderDialogTitle",
        "LabOutputFolderHint",
        "LabOutputFolderMissingNotice",
        "BtnLabOutputFolderOpen",
        "MsgLabOutputFolderOpenFailedFormat",
    ]
    for key in keys:
        for lang in i18n.LANGS:
            text = i18n.S(key, lang)
            assert text and not text.startswith("??"), (
                f"i18nキー欠落: {key} / {lang}")


# ---------------------------------------------------------------------------
# 2. パス解決: 既存コードが実際に使う値(work_root)をそのまま表示すること
# ---------------------------------------------------------------------------


def test_dialog_shows_work_root_path_unmodified(hidden_root, tmp_path):
    """ダイアログに表示されるパスは、渡したwork_rootそのもの(自前で
    別のパスを組み立てていないこと)を確認する。"""
    work_root = str(tmp_path)
    os.makedirs(work_root, exist_ok=True)
    ctx = dlg_mod.OutputFolderContext(work_root=work_root, open_folder=lambda p: None)
    dlg = dlg_mod.show_output_folder_dialog(hidden_root, ctx)
    try:
        labels = [lbl.cget("text") for lbl in _find_children(dlg, tk.Label)]
        assert work_root in labels
    finally:
        dlg.destroy()


def test_lab_window_adapter_passes_self_work_root_unmodified(hidden_root, tmp_path):
    """lab_window.py側のアダプタ(_open_output_folder_dialog)が、
    MainWindowが実際に使う self.work_root をそのままダイアログへ渡す
    (既存経路と同一値、自前でパスを組まない)ことを確認する。"""
    class _FakeSelf:
        def __init__(self, root):
            self.root = root
            self.widgets = {}
            self.work_root = str(tmp_path)

    self = _FakeSelf(hidden_root)
    # open_output_folder_dialogという名の公開関数は無く、LabFeature.open_dialog
    # (=lab_window._open_output_folder_dialog)経由で結線されている。
    feature = next(f for f in lab_window.LAB_FEATURES if f.feature_id == "output_folder")
    sub_dlg = feature.open_dialog(self, hidden_root, lambda: None)
    try:
        labels = [lbl.cget("text") for lbl in _find_children(sub_dlg, tk.Label)]
        assert self.work_root in labels
    finally:
        sub_dlg.destroy()


# ---------------------------------------------------------------------------
# 3. フォルダ有無に応じた「フォルダを開く」ボタンの活性/非活性
# ---------------------------------------------------------------------------


def test_open_button_enabled_when_folder_exists(hidden_root, tmp_path):
    work_root = str(tmp_path)
    os.makedirs(work_root, exist_ok=True)
    ctx = dlg_mod.OutputFolderContext(work_root=work_root, open_folder=lambda p: None)
    dlg = dlg_mod.show_output_folder_dialog(hidden_root, ctx)
    try:
        btn = _find_button(dlg, i18n.S("BtnLabOutputFolderOpen"))
        assert btn is not None
        assert str(btn.cget("state")) == "normal"
    finally:
        dlg.destroy()


def test_open_button_disabled_when_folder_missing(hidden_root, tmp_path):
    """負の対照: work_rootがまだ存在しない(未変換の新規インストール直後)
    場合、黙って失敗せずボタンを無効化し、案内文言を出すこと。"""
    missing = os.path.join(str(tmp_path), "not_created_yet")
    ctx = dlg_mod.OutputFolderContext(work_root=missing, open_folder=lambda p: None)
    dlg = dlg_mod.show_output_folder_dialog(hidden_root, ctx)
    try:
        btn = _find_button(dlg, i18n.S("BtnLabOutputFolderOpen"))
        assert btn is not None
        assert str(btn.cget("state")) == "disabled"
        labels = [lbl.cget("text") for lbl in _find_children(dlg, tk.Label)]
        assert i18n.S("LabOutputFolderMissingNotice") in labels
    finally:
        dlg.destroy()


def test_missing_notice_not_shown_when_folder_exists(hidden_root, tmp_path):
    work_root = str(tmp_path)
    os.makedirs(work_root, exist_ok=True)
    ctx = dlg_mod.OutputFolderContext(work_root=work_root, open_folder=lambda p: None)
    dlg = dlg_mod.show_output_folder_dialog(hidden_root, ctx)
    try:
        labels = [lbl.cget("text") for lbl in _find_children(dlg, tk.Label)]
        assert i18n.S("LabOutputFolderMissingNotice") not in labels
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 4. 「フォルダを開く」クリック時の配線(os.startfile自体はモック)
# ---------------------------------------------------------------------------


def test_open_button_invokes_open_folder_callback_with_work_root(hidden_root, tmp_path):
    work_root = str(tmp_path)
    os.makedirs(work_root, exist_ok=True)
    calls = []
    ctx = dlg_mod.OutputFolderContext(
        work_root=work_root, open_folder=lambda p: calls.append(p),
    )
    dlg = dlg_mod.show_output_folder_dialog(hidden_root, ctx)
    try:
        btn = _find_button(dlg, i18n.S("BtnLabOutputFolderOpen"))
        btn.invoke()
        assert calls == [work_root]
    finally:
        dlg.destroy()


def test_open_folder_failure_shows_error_and_does_not_raise(hidden_root, tmp_path, monkeypatch):
    """負の対照: open_folder自体が失敗(OSError)しても、例外を上に投げず
    エラーダイアログで知らせる(黙って失敗しない)。"""
    from tkinter import messagebox
    work_root = str(tmp_path)
    os.makedirs(work_root, exist_ok=True)

    shown = []
    monkeypatch.setattr(
        messagebox, "showerror", lambda title, msg: shown.append((title, msg))
    )

    def _boom(path):
        raise OSError("boom")

    ctx = dlg_mod.OutputFolderContext(work_root=work_root, open_folder=_boom)
    dlg = dlg_mod.show_output_folder_dialog(hidden_root, ctx)
    try:
        btn = _find_button(dlg, i18n.S("BtnLabOutputFolderOpen"))
        btn.invoke()
        assert len(shown) == 1
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 5. lab_window.pyへの結線(LAB_FEATURES登録)
# ---------------------------------------------------------------------------


def test_output_folder_registered_in_lab_features():
    feature_ids = {f.feature_id for f in lab_window.LAB_FEATURES}
    assert "output_folder" in feature_ids


def test_output_folder_feature_affects_conversion_false():
    feature = next(f for f in lab_window.LAB_FEATURES if f.feature_id == "output_folder")
    assert feature.affects_conversion is False


def test_open_lab_window_includes_output_folder_row(hidden_root, tmp_path):
    class _FakeSelf:
        def __init__(self, root):
            self.root = root
            self.widgets = {}
            self.app_root = str(tmp_path)
            self.work_root = str(tmp_path)

    i18n.set_language("ja")
    self = _FakeSelf(hidden_root)
    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        labels = [lbl.cget("text") for lbl in _find_children(dlg, tk.Label)]
        assert i18n.S("LabFeatureOutputFolder") in labels
    finally:
        dlg.destroy()
