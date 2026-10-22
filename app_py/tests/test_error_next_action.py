# test_error_next_action.py -- dev#138: エラー時の次アクション導線(問い合わせ勧誘)。
#
# 背景(dev#138 issue本文): 「ログをコピー」ボタンを核に、主要なエラーパス
# (Blender未検出/変換失敗/pak適用失敗)でエラー表示時に次アクション
# (問い合わせフォームへの導線)を追加する。既存の「ログをコピー」
# (support_dialog.pyのcopy_log_btn)・問い合わせフォーム開始(同open_form_btn、
# 送信先は inquiry.get_report_base_url() の正本定数)は一切再実装せず、
# 既存のreportButton経路(_on_show_support_dialog、C#版ShowSupportDialog相当)を
# Yesの場合だけ呼ぶ薄い導線(main_window._offer_report_after_failure)として
# main_window.py 側にのみ実装した(新規URL・新規ウィジェット配置は無し=
# workarea.pyのクランプ計算には一切影響しないため、本ファイルではレイアウト
# 試験を行わない。新規 .place() 呼び出しをゼロにしたことはPR側で明記)。
#
# 実tkウィンドウは開かない: 主経路のテストはtest_guard_dialogs.py等と同じ
# fake-self方式(mw.MainWindow.__new__(mw.MainWindow))。support_dialog.pyの
# 「ログをコピー」退行検査のみ、conftest.pyの共有hidden_root(withdraw済み、
# 画面には一切表示しない)を使って実物のtk.Buttonを直接invoke()する。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402
from ui import support_dialog  # noqa: E402


def _bare_window() -> mw.MainWindow:
    """__init__を通さずMainWindowインスタンスだけ得る(既存test_guard_dialogs.py
    等と同じ手筋)。テストごとに必要な属性だけ後付けする。"""
    return mw.MainWindow.__new__(mw.MainWindow)


class _FakeButton:
    """tkinter.Button/Label互換の最小フェイク(config(text=...)/place()/
    place_forget()のみ)。"""

    def __init__(self) -> None:
        self.text: str | None = None
        self.geometry: dict | None = None
        self.forgot = False

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]

    def cget(self, key: str) -> str:
        assert key == "text"
        return self.text or ""

    def place(self, **kwargs) -> None:
        self.geometry = kwargs
        self.forgot = False

    def place_forget(self) -> None:
        self.forgot = True


class _DictLikeBusyBar(_FakeButton):
    """busyBar["value"]=0代入を許容する最小フェイク(ttk.Progressbar互換)。"""

    def __setitem__(self, _key, _value) -> None:
        return None


# ---------------------------------------------------------------------------
# _offer_report_after_failure: 3経路が共通で使う核ヘルパー単体
# ---------------------------------------------------------------------------


def test_offer_report_after_failure_opens_support_dialog_on_yes(monkeypatch):
    fake = _bare_window()
    opened: list[bool] = []
    fake._on_show_support_dialog = lambda: opened.append(True)
    asked: list[tuple] = []

    def fake_askyesno(title, message):
        asked.append((title, message))
        return True

    monkeypatch.setattr(mw.messagebox, "askyesno", fake_askyesno)

    mw.MainWindow._offer_report_after_failure(fake, "boom happened")

    assert opened == [True]
    assert len(asked) == 1
    title, message = asked[0]
    # 新規Titleキーを増やさず、既存のBtnReport("問合せ"/"Contact"等)をそのまま使う
    assert title == i18n.S("BtnReport")
    assert "boom happened" in message
    assert i18n.S("BtnReport") in message


def test_offer_report_after_failure_negative_control_no_answer_does_not_open(monkeypatch):
    """負の対照: Noを選んだら支援ダイアログは開かれない(askyesnoの戻り値を
    無視して常に開いてしまう退行があれば、この試験が落ちて検出する)。"""
    fake = _bare_window()
    opened: list[bool] = []
    fake._on_show_support_dialog = lambda: opened.append(True)
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a: False)

    mw.MainWindow._offer_report_after_failure(fake, "boom happened")

    assert opened == []


# ---------------------------------------------------------------------------
# 経路1: Blender未検出/セットアップ失敗(_on_blender_setup_done)
# ---------------------------------------------------------------------------


def _fake_window_for_blender_done() -> mw.MainWindow:
    fake = _bare_window()
    fake.widgets = {
        "busyBar": _DictLikeBusyBar(),
        "statusLabel": _FakeButton(),
        "blenderRetryButton": _FakeButton(),
    }
    fake._update_button_states = lambda: None
    # dev#1239: _on_blender_setup_done()がconvertButtonのゲート再計算を明示的に
    # 呼ぶようになったため(本ファイルの対象外の関心事なのでno-opで済ませる)。
    fake._refresh_convert_button_freshness = lambda: None
    fake._warm_startup_after_blender_ready = lambda: None
    fake._log_calls: list[str] = []
    fake._log = lambda text, **_k: fake._log_calls.append(text)
    return fake


def test_blender_setup_failure_offers_report():
    """dev#138 経路1(正): Blenderセットアップ失敗時、次アクション導線
    (_offer_report_after_failure)が失敗理由つきで呼ばれること。"""
    fake = _fake_window_for_blender_done()
    offers: list[str] = []
    fake._offer_report_after_failure = lambda cause: offers.append(cause)

    mw.MainWindow._on_blender_setup_done(
        fake,
        False,
        "Blender not found",
        mw.blender_setup.BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT,
    )

    assert offers == ["Blender not found"]
    # 既存の表示(ステータス欄+再試行ボタン)が壊れていないことも合わせて確認
    assert fake.widgets["statusLabel"].text == "Blender not found"
    assert fake.widgets["blenderRetryButton"].forgot is False


def test_blender_setup_success_negative_control_does_not_offer_report():
    """負の対照: 成功時は次アクション導線を出さない(成否に関わらず常に
    出してしまう退行があれば、この試験が落ちて検出する)。"""
    fake = _fake_window_for_blender_done()
    offers: list[str] = []
    fake._offer_report_after_failure = lambda cause: offers.append(cause)

    mw.MainWindow._on_blender_setup_done(
        fake, True, None, mw.blender_setup.BlenderSetupAction.READY_NO_ACTION
    )

    assert offers == []


# ---------------------------------------------------------------------------
# 経路2: 変換失敗(_on_pipeline_exit code!=0)
# ---------------------------------------------------------------------------


def _fake_window_for_pipeline_exit() -> mw.MainWindow:
    fake = _bare_window()
    fake.widgets = {"statusLabel": _FakeButton()}
    fake._set_running_ui_state = lambda _running: None
    fake._user_cancelled_current_run = False
    return fake


def test_pipeline_exit_failure_offers_report_when_not_user_cancelled():
    """dev#138 経路2(正): 変換失敗(ユーザーが中止したのではない)時、
    次アクション導線が呼ばれること。"""
    fake = _fake_window_for_pipeline_exit()
    offers: list[str] = []
    fake._offer_report_after_failure = lambda cause: offers.append(cause)

    mw.MainWindow._on_pipeline_exit(fake, 1, False)

    assert offers == [i18n.S("StatusFailedOrCancelled")]
    assert fake.widgets["statusLabel"].text == i18n.S("StatusFailedOrCancelled")
    assert fake._user_cancelled_current_run is False


def test_pipeline_exit_failure_negative_control_suppressed_when_user_cancelled():
    """負の対照: cancelButton経由でユーザー自身が中止した場合
    (_user_cancelled_current_run=True)は、中止確認ダイアログと二重に
    ならないよう問い合わせ勧誘を出さない。これが常に出てしまう退行が
    あれば、この試験が落ちて検出する。"""
    fake = _fake_window_for_pipeline_exit()
    fake._user_cancelled_current_run = True
    offers: list[str] = []
    fake._offer_report_after_failure = lambda cause: offers.append(cause)

    mw.MainWindow._on_pipeline_exit(fake, 1, False)

    assert offers == []
    # フラグは次回実行の誤爆を防ぐため、消費後に必ずFalseへ戻る
    assert fake._user_cancelled_current_run is False


def test_on_cancel_convert_sets_user_cancelled_flag_on_confirm(monkeypatch):
    """_on_cancel_convert()がYes確認後に_user_cancelled_current_runを立てる
    ことの確認(上記の抑止が実際に発火する経路そのもの)。"""
    fake = _bare_window()
    fake._user_cancelled_current_run = False

    class _FakeHandle:
        def __init__(self) -> None:
            self.killed = False

        def is_running(self) -> bool:
            return True

        def kill(self) -> None:
            self.killed = True

    handle = _FakeHandle()
    fake._active_handle = handle
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a: True)

    mw.MainWindow._on_cancel_convert(fake)

    assert fake._user_cancelled_current_run is True
    assert handle.killed is True


def test_on_cancel_convert_negative_control_decline_leaves_flag_unset(monkeypatch):
    """負の対照: 中止確認でNoを選んだ場合はフラグを立てない・killもしない。"""
    fake = _bare_window()
    fake._user_cancelled_current_run = False

    class _FakeHandle:
        def __init__(self) -> None:
            self.killed = False

        def is_running(self) -> bool:
            return True

        def kill(self) -> None:
            self.killed = True

    handle = _FakeHandle()
    fake._active_handle = handle
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a: False)

    mw.MainWindow._on_cancel_convert(fake)

    assert fake._user_cancelled_current_run is False
    assert handle.killed is False


# ---------------------------------------------------------------------------
# 経路3: pak適用失敗(_show_apply_failure)
# ---------------------------------------------------------------------------


def test_apply_failure_offers_report(monkeypatch):
    """dev#138 経路3(正): pak適用失敗時、既存のcause/action付き
    showerror(退行させていないことも同時に確認)に加え、次アクション導線が
    呼ばれること。"""
    fake = _bare_window()
    fake._log_calls: list[str] = []
    fake._log = lambda text, **_k: fake._log_calls.append(text)
    error_calls: list[tuple] = []
    monkeypatch.setattr(
        mw.messagebox, "showerror", lambda title, msg: error_calls.append((title, msg))
    )
    offers: list[str] = []
    fake._offer_report_after_failure = lambda cause: offers.append(cause)

    mw.MainWindow._show_apply_failure(
        fake, "Apply", "C:\\Pal\\Content\\Paks\\Uchinoko_P.pak", OSError("locked")
    )

    # 既存のcause/action付きエラーダイアログ(退行の負の対照)
    assert len(error_calls) == 1
    title, msg = error_calls[0]
    assert title == i18n.F("MsgApplyFailureTitleFormat", "Apply")
    assert i18n.S("CauseFileInUse") in msg
    # 新規: 次アクション導線
    assert offers == [i18n.F("MsgApplyFailureTitleFormat", "Apply")]


def test_apply_failure_negative_control_permission_error_still_classified(monkeypatch):
    """負の対照: 原因分類(_classify_apply_failure)自体は本WPで変更していない
    ことの確認。PermissionErrorなら従来どおりCauseNoWritePermissionになる
    (次アクション導線の追加が既存分類ロジックを壊していないこと)。"""
    fake = _bare_window()
    fake._log_calls: list[str] = []
    fake._log = lambda text, **_k: fake._log_calls.append(text)
    error_calls: list[tuple] = []
    monkeypatch.setattr(
        mw.messagebox, "showerror", lambda title, msg: error_calls.append((title, msg))
    )
    fake._offer_report_after_failure = lambda cause: None

    mw.MainWindow._show_apply_failure(fake, "Remove", "C:\\some\\path", PermissionError("denied"))

    title, msg = error_calls[0]
    assert i18n.S("CauseNoWritePermission") in msg
    assert i18n.S("CauseFileInUse") not in msg


# ---------------------------------------------------------------------------
# 既存の「ログをコピー」機能の退行検査(support_dialog.py、hidden_root使用)
# ---------------------------------------------------------------------------


def _find_button(widget, text: str):
    for child in widget.winfo_children():
        if isinstance(child, mw.tk.Button) and child.cget("text") == text:
            return child
        found = _find_button(child, text)
        if found is not None:
            return found
    return None


def test_copy_log_button_still_copies_sanitized_diagnostics_text(hidden_root, monkeypatch):
    """既存の「ログをコピー」機能の退行検査(正): USERPROFILE配下のパスを
    含む診断テキストが、マスクされた状態でcopy_to_clipboardへ渡ること
    (本WPはsupport_dialog.pyに一切手を入れていないが、dev#138の受入条件
    「既存の『ログをコピー』機能を壊さないこと」を明示的に実証する)。"""
    fake_userprofile = "C:\\Users\\TestUser123"
    monkeypatch.setenv("USERPROFILE", fake_userprofile)
    diag_text = f"avatar path: {fake_userprofile}\\avatars\\a.vrm"

    copied: list[str] = []
    ctx = support_dialog.SupportContext(
        tool_version="test",
        lang="ja",
        channel="dev",
        get_os_description=lambda: "Windows 11",
        get_avatar_name=lambda: "a.vrm",
        get_status_text=lambda: "idle",
        build_diagnostics_text=lambda: diag_text,
        copy_to_clipboard=lambda text: copied.append(text),
    )
    state = support_dialog.SupportDialogState()
    dlg = support_dialog.show_support_dialog(hidden_root, state, ctx)
    try:
        btn = _find_button(dlg, i18n.S("BtnCopyLogManually"))
        assert btn is not None
        btn.invoke()

        assert len(copied) == 1
        assert fake_userprofile not in copied[0]
        assert "%USERPROFILE%" in copied[0]
    finally:
        dlg.destroy()


def test_copy_log_button_negative_control_masking_disabled_would_leak(hidden_root, monkeypatch):
    """負の対照: マスク処理(inquiry.sanitize_for_clipboard)が壊れた
    (恒等関数に退行した)状態を模擬すると、上のテストと同じ操作で生の
    ユーザー名が漏れることを示す。上のテストがこの壊れた状態を検出できる
    (=緑から赤へ転じる)ことの実測。"""
    fake_userprofile = "C:\\Users\\TestUser123"
    monkeypatch.setenv("USERPROFILE", fake_userprofile)
    diag_text = f"avatar path: {fake_userprofile}\\avatars\\a.vrm"

    monkeypatch.setattr(support_dialog.inquiry, "sanitize_for_clipboard", lambda text: text)

    copied: list[str] = []
    ctx = support_dialog.SupportContext(
        tool_version="test",
        lang="ja",
        channel="dev",
        get_os_description=lambda: "Windows 11",
        get_avatar_name=lambda: "a.vrm",
        get_status_text=lambda: "idle",
        build_diagnostics_text=lambda: diag_text,
        copy_to_clipboard=lambda text: copied.append(text),
    )
    state = support_dialog.SupportDialogState()
    dlg = support_dialog.show_support_dialog(hidden_root, state, ctx)
    try:
        btn = _find_button(dlg, i18n.S("BtnCopyLogManually"))
        btn.invoke()

        # マスクが壊れていれば生のユーザー名がそのまま漏れる
        # (=test_copy_log_button_still_copies_sanitized_diagnostics_text の
        # `assert fake_userprofile not in copied[0]` はこの状態で失敗するはず、
        # という検出力を本テストで実測する)
        assert fake_userprofile in copied[0]
    finally:
        dlg.destroy()
