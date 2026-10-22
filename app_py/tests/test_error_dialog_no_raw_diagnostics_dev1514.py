# test_error_dialog_no_raw_diagnostics_dev1514.py -- dev#1514: オーナー実見
# (2026-08-16)「Blenderセットアップ失敗ダイアログに生の英語例外文
# ("Reason: Patch materials not found: <絶対パス> ...")と[D2P_PATH_SHAPE]
# 診断行2行がそのまま出た。非エンジニアにこれを見せる可能性があるのは
# 馬鹿すぎる」の受入試験。
#
# 洗い出した同型4箇所(main_window.py::_on_blender_setup_done/
# _show_delete_failure、ui\multi_avatar_pak_dialog.py::on_fail、
# ui\output_folder_dialog.py::_open_and_report)を、それぞれ
# 「ダイアログ表示文字列に生の技術情報が含まれない」+「ログ側には引き続き
# 全文が残る(診断能力を落とさない)」の正・負の対照で固定する。
from __future__ import annotations

import os
import sys
import tempfile

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402
from ui import multi_avatar_pak_dialog as mapd  # noqa: E402
from ui import output_folder_dialog as ofd  # noqa: E402

# ---------------------------------------------------------------------------
# 0. 共通サンプル(test_untranslated_gui_dev939.py::_FAIL_MESSAGE_SAMPLE と同じ
#    形。ensure_blender.ps1 Show-D2PFailureGuidance の実出力を模す)。
# ---------------------------------------------------------------------------

_FAIL_MESSAGE_SAMPLE = (
    '[D2P_BLENDER_SETUP_FAIL] Blender setup failed.\n'
    'Reason: Patch materials not found: '
    'C:\\Users\\SECRET_USER\\AppData\\Local\\Temp\\.tmp_ensure_blender_XXXX\\'
    'patch_materials (the distribution may be corrupted)\n'
    '\n'
    'What to try:\n'
    '  1. Check your internet connection, then press "Full Convert (Create MOD)" '
    'or "Update Preview" again.\n'
    '  2. If automatic download keeps failing, you can also set it up manually:\n'
    '       (1) Download the Windows x64 Portable (zip) build of Blender 4.3.2 '
    'from https://www.blender.org/download/\n'
    '       (2) Extract it, then copy the contents of the folder containing '
    'blender.exe directly into:\n'
    '           C:\\P\\Work\\DiveToPalworld\\assets\\tools\\blender-4.3.2-windows-x64\n'
    '\n'
    'Diagnostic info (path structure only, no folder names included):\n'
    '  [D2P_PATH_SHAPE] step=AppRoot(received as argument) len=25 seg=5\n'
    '  [D2P_PATH_SHAPE] step=TargetDir(built from AppRoot) len=60 seg=8'
)


# ---------------------------------------------------------------------------
# 1. strip_blender_setup_fail_diagnostics() 単体
# ---------------------------------------------------------------------------


def test_strip_removes_reason_line_and_diagnostic_block():
    result = mw.strip_blender_setup_fail_diagnostics(_FAIL_MESSAGE_SAMPLE)
    assert "Reason:" not in result
    assert "Patch materials not found" not in result
    assert "SECRET_USER" not in result
    assert "[D2P_PATH_SHAPE]" not in result
    assert "Diagnostic info" not in result
    # 実行可能な手順(お試しください1/2)と$TargetDirの実パスは残る
    assert "What to try:" in result
    assert "Download the Windows x64 Portable" in result
    assert r"C:\P\Work\DiveToPalworld\assets\tools\blender-4.3.2-windows-x64" in result
    assert "[D2P_BLENDER_SETUP_FAIL] Blender setup failed." in result


def test_strip_negative_control_message_without_markers_is_unchanged():
    """負の対照: Reason:/D2P_PATH_SHAPEが無い(=フィルタが空振りするはずの)
    入力は一切変更されない。"""
    plain = "Blender not found"
    assert mw.strip_blender_setup_fail_diagnostics(plain) == plain


def test_strip_empty_returns_empty():
    assert mw.strip_blender_setup_fail_diagnostics("") == ""


def test_strip_launch_fail_header_reason_only_keeps_header_drops_reason():
    """dev#1242 LAUNCH_FAIL_HEADERの形(ヘッダ+Reason:のみ、What to try以降
    無し)でも、生例外(WinError等)はダイアログへ出ない。"""
    raw = "[D2P_BLENDER_SETUP_FAIL] Failed to launch ensure_blender.ps1.\nReason: [WinError 2] SECRET_DETAIL"
    result = mw.strip_blender_setup_fail_diagnostics(raw)
    assert "SECRET_DETAIL" not in result
    assert "Reason:" not in result
    assert "[D2P_BLENDER_SETUP_FAIL] Failed to launch ensure_blender.ps1." in result


# ---------------------------------------------------------------------------
# 2. _on_blender_setup_done(): ダイアログ導線(_offer_report_after_failure)
#    へ渡る文字列 + ログの両方を検査する
# ---------------------------------------------------------------------------


class _FakeButton:
    def __init__(self) -> None:
        self.forgot = False
        self.text: str | None = None

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]

    def place(self, **_kwargs) -> None:
        self.forgot = False

    def place_forget(self) -> None:
        self.forgot = True


class _DictLikeBusyBar(_FakeButton):
    def __setitem__(self, _key, _value) -> None:
        return None


def _fake_window_for_blender_done() -> mw.MainWindow:
    fake = mw.MainWindow.__new__(mw.MainWindow)
    fake.widgets = {
        "busyBar": _DictLikeBusyBar(),
        "statusLabel": _FakeButton(),
        "blenderRetryButton": _FakeButton(),
    }
    fake._update_button_states = lambda: None
    fake._refresh_convert_button_freshness = lambda: None
    fake._warm_startup_after_blender_ready = lambda: None
    fake._log_calls: list[str] = []
    fake._log = lambda text, **_k: fake._log_calls.append(text)
    return fake


def test_blender_setup_failure_dialog_text_has_no_raw_diagnostics():
    fake = _fake_window_for_blender_done()
    offers: list[str] = []
    fake._offer_report_after_failure = lambda cause: offers.append(cause)

    mw.MainWindow._on_blender_setup_done(
        fake, False, _FAIL_MESSAGE_SAMPLE,
        mw.blender_setup.BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT,
    )

    assert len(offers) == 1
    dialog_text = offers[0]
    assert "D2P_PATH_SHAPE" not in dialog_text
    assert "Patch materials not found" not in dialog_text
    assert "SECRET_USER" not in dialog_text
    # ステータス欄も同じ理由で生の診断情報を出さない
    assert "D2P_PATH_SHAPE" not in fake.widgets["statusLabel"].text
    assert "SECRET_USER" not in fake.widgets["statusLabel"].text


def test_blender_setup_failure_full_detail_is_still_logged():
    """負の対照: ダイアログから消しただけで、診断能力そのものを落として
    いないこと(問い合わせボタンが添付するlaunch.log経由でサポートへ届く
    経路がself._log()である)を確認する。"""
    fake = _fake_window_for_blender_done()
    fake._offer_report_after_failure = lambda cause: None

    mw.MainWindow._on_blender_setup_done(
        fake, False, _FAIL_MESSAGE_SAMPLE,
        mw.blender_setup.BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT,
    )

    logged = "\n".join(fake._log_calls)
    assert "SECRET_USER" in logged
    assert "D2P_PATH_SHAPE" in logged
    assert "Patch materials not found" in logged


def test_blender_setup_failure_negative_control_plain_message_unaffected():
    """負の対照2: 診断マーカーを含まないfail_message(既存回帰、
    test_error_next_action.pyと同じ入力)は今までどおり文面が変わらない。"""
    fake = _fake_window_for_blender_done()
    offers: list[str] = []
    fake._offer_report_after_failure = lambda cause: offers.append(cause)

    mw.MainWindow._on_blender_setup_done(
        fake, False, "Blender not found",
        mw.blender_setup.BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT,
    )

    assert offers == ["Blender not found"]


# ---------------------------------------------------------------------------
# 3. _show_delete_failure(): 削除失敗ダイアログ
# ---------------------------------------------------------------------------


def test_show_delete_failure_dialog_has_no_raw_exception_text(monkeypatch):
    fake = mw.MainWindow.__new__(mw.MainWindow)
    fake._log_calls: list[str] = []
    fake._log = lambda text, **_k: fake._log_calls.append(text)

    shown: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showerror", lambda title, msg: shown.append((title, msg)))

    ex = PermissionError("SECRET_RAW_DETAIL C:\\Users\\SECRET_USER\\job")
    mw.MainWindow._show_delete_failure(fake, "C:\\some\\job_dir", ex)

    assert len(shown) == 1
    _title, msg = shown[0]
    assert "SECRET_RAW_DETAIL" not in msg
    assert "SECRET_USER" not in msg
    # 分類済みi18n文言(cause)は残る
    assert i18n.S("CauseNoWritePermission") in msg


def test_show_delete_failure_negative_control_raw_exception_is_logged(monkeypatch):
    """負の対照: ダイアログから消しただけで、生例外はself._log()側に必ず
    残ること。"""
    fake = mw.MainWindow.__new__(mw.MainWindow)
    fake._log_calls: list[str] = []
    fake._log = lambda text, **_k: fake._log_calls.append(text)
    monkeypatch.setattr(mw.messagebox, "showerror", lambda *a: None)

    ex = PermissionError("SECRET_RAW_DETAIL")
    mw.MainWindow._show_delete_failure(fake, "C:\\some\\job_dir", ex)

    assert any("SECRET_RAW_DETAIL" in line for line in fake._log_calls)


# ---------------------------------------------------------------------------
# 4. multi_avatar_pak_dialog.py: 合成失敗ダイアログ(lab)
# ---------------------------------------------------------------------------


class _SyncThread:
    """threading.Threadの最小フェイク(test_multi_avatar_pak_auto_apply_dev1328.py
    と同じ手法): start()でtargetを同期実行する。"""

    def __init__(self, target=None, daemon=None, **_kwargs):
        self._target = target

    def start(self) -> None:
        self._target()


def _find_children(widget, cls):
    import tkinter as tk

    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_find_children(child, cls))
    return found


def _find_button(widget, text: str):
    import tkinter as tk

    for btn in _find_children(widget, tk.Button):
        if btn.cget("text") == text:
            return btn
    return None


def test_multi_avatar_pak_compose_failure_dialog_has_no_raw_exception_text(
    hidden_root, monkeypatch
):
    monkeypatch.setattr(mapd.threading, "Thread", _SyncThread)

    def _boom(work_root_arg, job, log=print, python_exe=None):
        raise RuntimeError("SECRET_COMPOSE_DETAIL")

    monkeypatch.setattr(mapd.multi_avatar_pak_compose, "run_compose", _boom)
    monkeypatch.setattr(mapd.simpledialog, "askstring", lambda *a, **k: "MyFusion")

    shown: list[tuple] = []
    monkeypatch.setattr(mapd.messagebox, "showerror", lambda *a: shown.append(a))

    app_root = tempfile.mkdtemp(prefix="d2p_map_dialog_test_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_dialog_test_work_")
    # show_multi_avatar_pak_dialog()はassignmentsが空だと設定開始画面
    # (_render_setup)を出し、作成ボタン(_render_main側)へ到達しない。
    # run_compose自体は下でモック済みのため、割当の中身自体は実在の
    # entry_idである必要はない(空でないことだけが重要)。
    mapd.save_assignments(app_root, {"Bronze001": "Alicia"})
    logs: list[str] = []
    ctx = mapd.MultiAvatarPakContext(
        app_root=app_root, work_root=work_root, palworld_pak=None, lang="ja",
        append_log=logs.append,
    )
    dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, ctx)
    try:
        create_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate"))
        assert create_btn is not None
        create_btn.invoke()

        # on_fail()はdlg.after(0, on_fail)経由(_SyncThreadでworker自体は
        # 同期実行済みだが、通知はafterキュー経由のまま)。イベントループを
        # 回して届かせる(test_multi_avatar_pak_auto_apply_dev1328.pyと同じ
        # ポーリング流儀)。
        import time

        deadline = time.time() + 5.0
        while not shown and time.time() < deadline:
            hidden_root.update()
            time.sleep(0.01)
    finally:
        dlg.destroy()

    assert len(shown) == 1
    _title, msg = shown[0]
    assert "SECRET_COMPOSE_DETAIL" not in msg
    # 負の対照: 生例外はappend_log側には引き続き残る(診断能力を落とさない)
    assert any("SECRET_COMPOSE_DETAIL" in line for line in logs)


# ---------------------------------------------------------------------------
# 5. output_folder_dialog.py: フォルダを開けなかった場合のダイアログ(lab)
# ---------------------------------------------------------------------------


def test_output_folder_open_failure_dialog_has_no_raw_exception_text(
    hidden_root, monkeypatch
):
    from tkinter import messagebox

    work_root = tempfile.mkdtemp(prefix="d2p_outfolder_test_")

    shown: list[tuple] = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, msg: shown.append((title, msg)))

    logs: list[str] = []

    def _boom(path):
        raise OSError("SECRET_FOLDER_DETAIL")

    ctx = ofd.OutputFolderContext(
        work_root=work_root, open_folder=_boom, append_log=logs.append,
    )
    dlg = ofd.show_output_folder_dialog(hidden_root, ctx)
    try:
        btn = _find_button(dlg, i18n.S("BtnLabOutputFolderOpen"))
        assert btn is not None
        btn.invoke()
    finally:
        dlg.destroy()

    assert len(shown) == 1
    _title, msg = shown[0]
    assert "SECRET_FOLDER_DETAIL" not in msg
    assert work_root in msg  # 実行可能な手がかり(実パス)は残る
    # 負の対照: 生例外はappend_log側には引き続き残る
    assert any("SECRET_FOLDER_DETAIL" in line for line in logs)


# ---------------------------------------------------------------------------
# 6. i18n: 本WPで変更/新規追加したキーの5言語完備
# ---------------------------------------------------------------------------


def test_i18n_keys_present_in_all_languages():
    keys = [
        "MsgDeleteFailedFormat",
        "LabMultiAvatarPakCreateFailureBody",
        "MsgLabOutputFolderOpenFailedFormat",
        "MsgReportOfferFormat",
        "MsgBlenderSetupFailedShort",
    ]
    for key in keys:
        for lang in i18n.LANGS:
            text = i18n.S(key, lang)
            assert text and not text.startswith("??"), f"i18nキー欠落: {key} / {lang}"


def test_i18n_old_format_key_removed():
    """dev#1514: {0}枠に生例外を直接渡していた旧キーは使われなくなった
    (再導入されていないことの負の対照)。"""
    assert "LabMultiAvatarPakCreateFailureFormat" not in i18n.TABLE
