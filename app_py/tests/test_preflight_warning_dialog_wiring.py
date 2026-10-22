# test_preflight_warning_dialog_wiring.py -- dev#1230(2026-08-08オーナー
# 裁定): ユーザーサイドpreflight非ブロック化のGUI結線単体テスト。
#
# 既存test_guard_dialogs.py/test_gui_log_robustness.pyと同じ流儀: tkの実
# ウィンドウは一切開かない(tk.Tk()を呼ばない)。MainWindowの各メソッドは
# 束縛前のまま「フェイクself」(mw.MainWindow.__new__(mw.MainWindow)で生成し、
# 必要な属性だけ後付けする)に対して直接呼び出す。
#
# 検証する内容:
#   1) 正の対照: preflight_result.json(status=FAIL)がjob_dir\build配下に
#      あるとき、_on_pipeline_exit(0, False)は通常の完了ダイアログ
#      (messagebox.showinfo)の代わりに警告ダイアログ
#      (preflight_warning_dialog.show_preflight_warning_dialog)を呼ぶこと。
#   2) 警告ダイアログへ渡すコールバックが、既存の_on_remove_applied/
#      _on_show_support_dialogそのもの(二重実装していない)であること。
#   3) 負の対照①: preflight_result.jsonが無い(従来どおりのジョブ)場合は
#      警告ダイアログを一切呼ばず、従来どおりmessagebox.showinfo
#      (MsgConvertDoneBody)を出すこと(PASS時挙動不変、受入条件⑤)。
#   4) 負の対照②: preflight_result.jsonのstatusがPASSの場合も同様に
#      従来どおりの完了ダイアログのままであること。
#   5) auto_applied済みのときは、preflight FAILでも警告ダイアログを
#      抑制しない(自動適用の成否と無関係に、preflight FAILの周知は必ず
#      ユーザーへ届く)ことの確認。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402
from ui import preflight_warning_dialog  # noqa: E402


def _bare_window() -> mw.MainWindow:
    return mw.MainWindow.__new__(mw.MainWindow)


class _FakeHandle:
    def __init__(self, job_dir: str) -> None:
        self.job_dir = job_dir


class _FakeAutoApplyVar:
    def __init__(self, value: bool) -> None:
        self._value = value

    def get(self) -> bool:
        return self._value


def _fake_window_for_pipeline_exit(job_dir: str, *, auto_apply: bool = False) -> mw.MainWindow:
    fake = _bare_window()
    fake._active_handle = _FakeHandle(job_dir)
    fake._pipeline_warnings = []
    fake._silent_preview = False
    fake._user_cancelled_current_run = False
    fake._auto_apply_var = _FakeAutoApplyVar(auto_apply)
    fake._log_calls: list[str] = []
    fake._log = lambda text, _fake=fake, **_kw: _fake._log_calls.append(text)  # type: ignore[method-assign]
    fake._set_running_ui_state = lambda *_a, **_kw: None  # type: ignore[method-assign]
    fake._set_status = lambda *_a, **_kw: None  # type: ignore[method-assign]
    fake._record_eta_run_on_success = lambda: None  # type: ignore[method-assign]
    fake._apply_previews = lambda *_a, **_kw: None  # type: ignore[method-assign]
    fake._on_refresh_pak_list = lambda: None  # type: ignore[method-assign]
    fake._resolve_completed_pak_path = lambda _job_dir: None  # type: ignore[method-assign]
    fake._on_remove_applied = lambda: None  # type: ignore[method-assign]
    fake._on_show_support_dialog = lambda: None  # type: ignore[method-assign]
    fake.root = object()
    fake.widgets = {}
    return fake


def _write_preflight_result(job_dir: str, status: str) -> None:
    build_dir = os.path.join(job_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    with open(os.path.join(build_dir, "preflight_result.json"), "w", encoding="utf-8") as f:
        json.dump({"status": status, "returncode": 0 if status == "PASS" else 1,
                    "failed_gates": [] if status == "PASS" else ["G13 mismatch"]}, f)


def test_preflight_fail_shows_warning_dialog_instead_of_done_dialog(tmp_path, monkeypatch):
    job_dir = str(tmp_path / "MyAvatar")
    _write_preflight_result(job_dir, "FAIL")
    fake = _fake_window_for_pipeline_exit(job_dir)

    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))
    dialog_calls: list[tuple] = []
    monkeypatch.setattr(
        preflight_warning_dialog, "show_preflight_warning_dialog",
        lambda parent, ctx: dialog_calls.append((parent, ctx)),
    )

    mw.MainWindow._on_pipeline_exit(fake, 0, False)

    assert len(dialog_calls) == 1
    parent, ctx = dialog_calls[0]
    assert parent is fake.root
    # 二重実装していないこと: 既存ハンドラそのものが渡されていること
    assert ctx.on_remove_mod == fake._on_remove_applied
    assert ctx.on_open_inquiry == fake._on_show_support_dialog
    # 通常の完了ダイアログ(MsgConvertDoneBody)は出ていないこと
    assert info_calls == []


def test_preflight_result_missing_keeps_normal_done_dialog_negative_control(tmp_path, monkeypatch):
    # 負の対照①: preflight_result.json自体が無い(従来どおりのジョブ、
    # PASS時挙動不変の根拠)。
    job_dir = str(tmp_path / "MyAvatar")
    os.makedirs(job_dir, exist_ok=True)
    fake = _fake_window_for_pipeline_exit(job_dir)

    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))
    dialog_calls: list[tuple] = []
    monkeypatch.setattr(
        preflight_warning_dialog, "show_preflight_warning_dialog",
        lambda parent, ctx: dialog_calls.append((parent, ctx)),
    )

    mw.MainWindow._on_pipeline_exit(fake, 0, False)

    assert dialog_calls == []
    assert len(info_calls) == 1
    assert info_calls[0] == (i18n.S("TitleConvertDone"), i18n.S("MsgConvertDoneBody"))


def test_preflight_result_pass_keeps_normal_done_dialog_negative_control(tmp_path, monkeypatch):
    # 負の対照②: preflight_result.jsonがあってもstatus=PASSなら従来どおり。
    job_dir = str(tmp_path / "MyAvatar")
    _write_preflight_result(job_dir, "PASS")
    fake = _fake_window_for_pipeline_exit(job_dir)

    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))
    dialog_calls: list[tuple] = []
    monkeypatch.setattr(
        preflight_warning_dialog, "show_preflight_warning_dialog",
        lambda parent, ctx: dialog_calls.append((parent, ctx)),
    )

    mw.MainWindow._on_pipeline_exit(fake, 0, False)

    assert dialog_calls == []
    assert len(info_calls) == 1


def test_preflight_fail_shows_warning_even_when_auto_applied(tmp_path, monkeypatch):
    # auto_applied=Trueでも、preflight FAILの周知(警告ダイアログ)は
    # 抑制されない(自動適用の成否と無関係に必ずユーザーへ届く)。
    job_dir = str(tmp_path / "MyAvatar")
    _write_preflight_result(job_dir, "FAIL")
    fake = _fake_window_for_pipeline_exit(job_dir, auto_apply=True)
    pak_path = str(tmp_path / "MyAvatar" / "build" / "MyAvatar_PlayerSwap_P.pak")
    fake._resolve_completed_pak_path = lambda _job_dir: pak_path  # type: ignore[method-assign]
    fake._apply_pak_path = lambda _src, _name: True  # type: ignore[method-assign]

    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))
    dialog_calls: list[tuple] = []
    monkeypatch.setattr(
        preflight_warning_dialog, "show_preflight_warning_dialog",
        lambda parent, ctx: dialog_calls.append((parent, ctx)),
    )

    mw.MainWindow._on_pipeline_exit(fake, 0, False)

    assert len(dialog_calls) == 1
    assert info_calls == []
