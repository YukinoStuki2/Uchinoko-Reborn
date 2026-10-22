# test_preview_done_popup_removed.py -- オーナー指示(2026-08-09
# 「プレビュー完了のpopupいらない」)の単体テスト。
#
# 既存test_preflight_warning_dialog_wiring.pyと同じ流儀: tkの実ウィンドウは
# 一切開かない(tk.Tk()を呼ばない)。MainWindowの各メソッドは束縛前のまま
# 「フェイクself」(mw.MainWindow.__new__(mw.MainWindow)で生成し、必要な
# 属性だけ後付けする)に対して直接呼び出す。
#
# 検証する内容:
#   1) 正の対照: _on_pipeline_exit(0, True)(preview_only成功)は
#      messagebox.showinfoを一切呼ばないこと(silentPreview=Falseの手押し
#      プレビューでも抑止されること——旧実装はここで出していた)。
#   2) 負の対照①: _on_pipeline_exit(0, True, silent_preview=True)
#      (自動プレビュー)も同様に呼ばないこと(従来から抑止済みの経路が
#      今回の変更で壊れていないこと)。
#   3) 負の対照②: 通常変換の完了(_on_pipeline_exit(0, False))は
#      従来どおりmessagebox.showinfo(MsgConvertDoneBody)を出すこと
#      (preview_only以外は無変更)。
#   4) 負の対照③: preview失敗(_on_pipeline_exit(1, True))は従来どおり
#      失敗系の分岐(_offer_report_after_failure)を通り、
#      messagebox.showinfoは呼ばれないこと(この経路は元々showinfoを
#      呼ばないが、今回の変更で新たな副作用が生じていないことの確認)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402


def _bare_window() -> mw.MainWindow:
    return mw.MainWindow.__new__(mw.MainWindow)


class _FakeHandle:
    def __init__(self, job_dir: str) -> None:
        self.job_dir = job_dir


class _FakeAutoApplyVar:
    def get(self) -> bool:
        return False


class _FakeEntry:
    def __init__(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value


def _fake_window_for_pipeline_exit(job_dir: str, *, silent_preview: bool = False) -> mw.MainWindow:
    fake = _bare_window()
    fake._active_handle = _FakeHandle(job_dir)
    fake._pipeline_warnings = []
    fake._silent_preview = silent_preview
    fake._user_cancelled_current_run = False
    fake._auto_apply_var = _FakeAutoApplyVar()
    fake._log_calls: list[str] = []
    fake._log = lambda text, _fake=fake, **_kw: _fake._log_calls.append(text)  # type: ignore[method-assign]
    fake._set_running_ui_state = lambda *_a, **_kw: None  # type: ignore[method-assign]
    fake._set_status = lambda *_a, **_kw: None  # type: ignore[method-assign]
    fake._record_eta_run_on_success = lambda: None  # type: ignore[method-assign]
    fake._apply_previews = lambda *_a, **_kw: None  # type: ignore[method-assign]
    fake._finalize_fresh_preview = lambda *_a, **_kw: None  # type: ignore[method-assign]
    fake._on_refresh_pak_list = lambda: None  # type: ignore[method-assign]
    fake._resolve_completed_pak_path = lambda _job_dir: None  # type: ignore[method-assign]
    fake._pipeline_fatal_cause = None
    fake.root = object()
    fake.widgets = {"vrmBox": _FakeEntry(r"C:\avatars\MyAvatar.vrm")}
    return fake


def test_preview_only_success_shows_no_done_popup(tmp_path, monkeypatch):
    # 正の対照: 手押しプレビュー(silentPreview=False)の完了でも、
    # 従来出ていた「プレビュー完了」ポップアップがもう出ないこと。
    job_dir = str(tmp_path / "MyAvatar")
    os.makedirs(job_dir, exist_ok=True)
    fake = _fake_window_for_pipeline_exit(job_dir, silent_preview=False)

    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))

    mw.MainWindow._on_pipeline_exit(fake, 0, True)

    assert info_calls == []


def test_preview_only_success_silent_still_shows_no_popup_negative_control(tmp_path, monkeypatch):
    # 負の対照①: 自動プレビュー(silentPreview=True)側は元々抑止済み
    # だった経路。今回の変更で壊れていないことの確認。
    job_dir = str(tmp_path / "MyAvatar")
    os.makedirs(job_dir, exist_ok=True)
    fake = _fake_window_for_pipeline_exit(job_dir, silent_preview=True)

    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))

    mw.MainWindow._on_pipeline_exit(fake, 0, True)

    assert info_calls == []


def test_normal_convert_success_still_shows_done_popup_negative_control(tmp_path, monkeypatch):
    # 負の対照②: preview_only=Falseの通常変換完了は従来どおり
    # MsgConvertDoneBodyを出す(preview_only以外は無変更)。
    job_dir = str(tmp_path / "MyAvatar")
    os.makedirs(job_dir, exist_ok=True)
    fake = _fake_window_for_pipeline_exit(job_dir)

    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))

    mw.MainWindow._on_pipeline_exit(fake, 0, False)

    assert len(info_calls) == 1
    assert info_calls[0] == (i18n.S("TitleConvertDone"), i18n.S("MsgConvertDoneBody"))


def test_preview_failure_still_no_done_popup_negative_control(tmp_path, monkeypatch):
    # 負の対照③: preview失敗(code!=0)は元々失敗系分岐
    # (_offer_report_after_failure)を通り、完了ポップアップは呼ばれない。
    # 今回の変更がこの経路に副作用を与えていないことの確認。
    job_dir = str(tmp_path / "MyAvatar")
    os.makedirs(job_dir, exist_ok=True)
    fake = _fake_window_for_pipeline_exit(job_dir)
    fake._offer_report_after_failure = lambda *_a, **_kw: None  # type: ignore[method-assign]

    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))

    mw.MainWindow._on_pipeline_exit(fake, 1, True)

    assert info_calls == []
