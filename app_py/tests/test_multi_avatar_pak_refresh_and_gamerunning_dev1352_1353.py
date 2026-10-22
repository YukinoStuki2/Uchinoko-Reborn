# test_multi_avatar_pak_refresh_and_gamerunning_dev1352_1353.py -- dev#1352 /
# dev#1353: マルチアバターPAK不具合2件のオーナー実機報告(2026-08-11)への修正。
#
# dev#1352(不具合A): 変換完了後に作成済みMOD一覧(pakList)が更新されず、
#   GUI再起動が必要になっていた。原因: multi_avatar_pak_dialog.pyの合成成功
#   ハンドラ(on_ok())が、通常変換完了時に既に使われている一覧更新の仕組み
#   (main_window.py._on_refresh_pak_list、dev#601)を一度も呼んでいなかった
#   (ダイアログを閉じたとき(<Destroy>経由のlab_window.refresh())にしか
#   呼ばれておらず、ダイアログを開いたまま次の操作をすると反映されなかった)。
#   修正: _refresh_pak_list_after_compose()(新設、tkinter非依存の純粋関数)を
#   on_ok()から呼び、ctx.refresh_pak_list(lab_window.py側で_on_refresh_pak_list
#   をそのまま注入)を叩く。新規の更新機構は作らず、既存の仕組みを再利用する。
#
# dev#1353(不具合B): 合成後の自動適用がPalworld起動中で失敗しても、汎用の
#   「マルチアバターPAKを作成しましたが、適用に失敗しました」としか出ず、
#   原因と対処が伝わらなかった。修正: _apply_failure_message_key()(新設)が
#   既存のpak_manager.is_game_running()(main_window.py._apply_pak_path等で
#   既に使われているものと同一、tasklist CSV出力でIMAGENAME列25文字切り詰めを
#   回避済み)を呼び、起動中ならLabMultiAvatarPakCreateApplyFailureGameRunning
#   (新設i18nキー)を、そうでなければ従来どおりLabMultiAvatarPakCreateApplyFailure
#   を選ぶ。
#
# 各不具合とも「正(該当条件で新挙動)」「負の対照(非該当条件で従来挙動が
# 変わらないこと)」の2本立てで検証する。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pak_manager  # noqa: E402
from ui import multi_avatar_pak_dialog as mapd  # noqa: E402


def _make_ctx(**overrides):
    base = dict(app_root="X", work_root="Y", palworld_pak=None, lang="ja")
    base.update(overrides)
    return mapd.MultiAvatarPakContext(**base)


# ---------------------------------------------------------------------------
# dev#1352 (不具合A): 一覧更新
# ---------------------------------------------------------------------------


def test_refresh_pak_list_after_compose_calls_wired_mechanism():
    """正: refresh_pak_listが配線されていれば呼ばれること。"""
    calls: list[int] = []
    ctx = _make_ctx(refresh_pak_list=lambda: calls.append(1))

    result = mapd._refresh_pak_list_after_compose(ctx)

    assert result is True
    assert calls == [1]


def test_refresh_pak_list_after_compose_negative_control_no_mechanism_wired():
    """負の対照: refresh_pak_list=None(未配線)なら何も呼ばず、その旨をログへ
    記録するだけ(呼べないものを呼んだふりをしない)。"""
    logs: list[str] = []
    ctx = _make_ctx(append_log=logs.append, refresh_pak_list=None)

    result = mapd._refresh_pak_list_after_compose(ctx)

    assert result is False
    assert any("no refresh mechanism wired" in line for line in logs)


def test_refresh_pak_list_after_compose_exception_is_caught_and_returns_false():
    """一覧更新自体が例外を投げても、呼び出し元(on_ok())の後続の成功/失敗通知は
    止めない(例外を握って安全側へ倒す)。"""
    logs: list[str] = []

    def _boom():
        raise RuntimeError("refresh exploded")

    ctx = _make_ctx(append_log=logs.append, refresh_pak_list=_boom)

    result = mapd._refresh_pak_list_after_compose(ctx)

    assert result is False
    assert any("refresh exploded" in line for line in logs)


def test_on_create_flow_calls_refresh_pak_list_on_success(hidden_root, monkeypatch, tmp_path):
    """ダイアログ結線の通し試験(実スレッド+実イベントループ): 「作成」ボタン
    →合成成功→on_ok()実行までの流れで、refresh_pak_listが実際に呼ばれること。
    負の対照(変換失敗時に呼ばれないこと)は
    test_on_create_flow_negative_control_refresh_not_called_on_compose_failure
    で確認する。"""
    monkeypatch.setattr(mapd.threading, "Thread", _SyncThread)
    app_root = str(tmp_path / "app_root")
    work_root = str(tmp_path / "work_root")
    os.makedirs(app_root, exist_ok=True)
    os.makedirs(work_root, exist_ok=True)
    import multi_avatar_pak_store as store
    store.save_assignments(app_root, {"Bronze001": "Alicia"})

    def _fake_run_compose(work_root_arg, job, log=print, python_exe=None):
        return {"job_dir": work_root_arg, "out_pak": None, "pak_path": None}

    monkeypatch.setattr(mapd.multi_avatar_pak_compose, "run_compose", _fake_run_compose)
    monkeypatch.setattr(mapd.simpledialog, "askstring", lambda *a, **k: "MyFusion")
    monkeypatch.setattr(mapd.messagebox, "showinfo", lambda *a: None)
    monkeypatch.setattr(mapd.messagebox, "showwarning", lambda *a: None)

    refresh_calls: list[int] = []
    ctx = mapd.MultiAvatarPakContext(
        app_root=app_root, work_root=work_root, palworld_pak=None, lang="ja",
        apply_pak_path=None, refresh_pak_list=lambda: refresh_calls.append(1),
    )
    dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, ctx)
    try:
        create_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate"))
        assert create_btn is not None
        create_btn.invoke()
        _pump_until(hidden_root, lambda: bool(refresh_calls))
    finally:
        dlg.destroy()

    assert refresh_calls == [1]


def test_on_create_flow_negative_control_refresh_not_called_on_compose_failure(
    hidden_root, monkeypatch, tmp_path
):
    """負の対照: 合成自体が失敗(例外)したときは、一覧更新を呼ばない(旧一覧の
    ままでよい、成功していないものを成功したかのように一覧へ反映しない)。"""
    monkeypatch.setattr(mapd.threading, "Thread", _SyncThread)
    app_root = str(tmp_path / "app_root")
    work_root = str(tmp_path / "work_root")
    os.makedirs(app_root, exist_ok=True)
    os.makedirs(work_root, exist_ok=True)
    import multi_avatar_pak_store as store
    store.save_assignments(app_root, {"Bronze001": "Alicia"})

    def _fake_run_compose_boom(work_root_arg, job, log=print, python_exe=None):
        raise RuntimeError("compose exploded")

    monkeypatch.setattr(mapd.multi_avatar_pak_compose, "run_compose", _fake_run_compose_boom)
    monkeypatch.setattr(mapd.simpledialog, "askstring", lambda *a, **k: "MyFusion")
    error_calls: list[tuple] = []
    monkeypatch.setattr(mapd.messagebox, "showerror", lambda *a: error_calls.append(a))

    refresh_calls: list[int] = []
    ctx = mapd.MultiAvatarPakContext(
        app_root=app_root, work_root=work_root, palworld_pak=None, lang="ja",
        apply_pak_path=None, refresh_pak_list=lambda: refresh_calls.append(1),
    )
    dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, ctx)
    try:
        create_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate"))
        assert create_btn is not None
        create_btn.invoke()
        _pump_until(hidden_root, lambda: bool(error_calls))
    finally:
        dlg.destroy()

    assert error_calls, "合成失敗時はshowerrorで通知されるはず"
    assert refresh_calls == [], "合成失敗時は一覧を更新しないこと(負の対照)"


# ---------------------------------------------------------------------------
# dev#1353 (不具合B): Palworld起動中の専用メッセージ
# ---------------------------------------------------------------------------


def test_apply_failure_message_key_game_running_selects_dedicated_message(monkeypatch):
    """正: pak_manager.is_game_running()がTrueなら専用メッセージキーを選ぶ
    (プロセス検出はモック)。"""
    monkeypatch.setattr(pak_manager, "is_game_running", lambda: True)
    ctx = _make_ctx()

    key = mapd._apply_failure_message_key(ctx)

    assert key == "LabMultiAvatarPakCreateApplyFailureGameRunning"


def test_apply_failure_message_key_negative_control_not_running_keeps_generic_message(monkeypatch):
    """負の対照: プロセス非検出(起動していない)の失敗では、従来の汎用メッセージ
    キーのままであること。"""
    monkeypatch.setattr(pak_manager, "is_game_running", lambda: False)
    ctx = _make_ctx()

    key = mapd._apply_failure_message_key(ctx)

    assert key == "LabMultiAvatarPakCreateApplyFailure"


def test_apply_failure_message_key_detection_exception_falls_back_to_generic_message(monkeypatch):
    """検出自体が例外を投げても、汎用メッセージへ安全側に倒れること(専用
    メッセージを誤って出さない)。"""
    logs: list[str] = []

    def _boom():
        raise RuntimeError("tasklist exploded")

    monkeypatch.setattr(pak_manager, "is_game_running", _boom)
    ctx = _make_ctx(append_log=logs.append)

    key = mapd._apply_failure_message_key(ctx)

    assert key == "LabMultiAvatarPakCreateApplyFailure"
    assert any("tasklist exploded" in line for line in logs)


def test_dedicated_game_running_message_i18n_key_exists_in_all_languages():
    assert "LabMultiAvatarPakCreateApplyFailureGameRunning" in i18n.TABLE
    entry = i18n.TABLE["LabMultiAvatarPakCreateApplyFailureGameRunning"]
    for lang in i18n.LANGS:
        assert lang in entry and entry[lang], f"missing lang={lang}"


def test_on_create_flow_shows_dedicated_message_when_game_running(hidden_root, monkeypatch, tmp_path):
    """ダイアログ結線の通し試験: 適用がPalworld起動中で失敗したとき、専用
    メッセージがshowwarningへ渡されること。"""
    monkeypatch.setattr(mapd.threading, "Thread", _SyncThread)
    monkeypatch.setattr(pak_manager, "is_game_running", lambda: True)
    app_root = str(tmp_path / "app_root")
    work_root = str(tmp_path / "work_root")
    os.makedirs(app_root, exist_ok=True)
    os.makedirs(work_root, exist_ok=True)
    import multi_avatar_pak_store as store
    store.save_assignments(app_root, {"Bronze001": "Alicia"})

    def _fake_run_compose(work_root_arg, job, log=print, python_exe=None):
        return {"job_dir": work_root_arg, "out_pak": "C:\\fake\\Fusion_PlayerSwap_P.pak",
                "pak_path": "C:\\fake\\Fusion_PlayerSwap_P.pak"}

    monkeypatch.setattr(mapd.multi_avatar_pak_compose, "run_compose", _fake_run_compose)
    monkeypatch.setattr(mapd.simpledialog, "askstring", lambda *a, **k: "MyFusion")
    warn_calls: list[tuple] = []
    monkeypatch.setattr(mapd.messagebox, "showwarning", lambda *a: warn_calls.append(a))
    monkeypatch.setattr(mapd.messagebox, "showinfo", lambda *a: None)

    def _apply_fails_because_game_running(pak_path, avatar_name):
        return False  # main_window._apply_pak_path_silent相当: 起動中はFalseを返す

    ctx = mapd.MultiAvatarPakContext(
        app_root=app_root, work_root=work_root, palworld_pak=None, lang="ja",
        apply_pak_path=_apply_fails_because_game_running,
    )
    dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, ctx)
    try:
        create_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate"))
        assert create_btn is not None
        create_btn.invoke()
        _pump_until(hidden_root, lambda: bool(warn_calls))
    finally:
        dlg.destroy()

    assert warn_calls, "適用失敗時はshowwarningで通知されるはず"
    assert warn_calls[0][1] == i18n.S("LabMultiAvatarPakCreateApplyFailureGameRunning")


# ---------------------------------------------------------------------------
# 補助(test_multi_avatar_pak_auto_apply_dev1328.pyと同じ流儀)
# ---------------------------------------------------------------------------


class _SyncThread:
    """threading.Threadの最小フェイク。start()でtarget()を呼び出し元スレッド上で
    同期実行する(test_multi_avatar_pak_auto_apply_dev1328.py._SyncThreadと同型)。"""

    def __init__(self, target=None, daemon=None, **_kwargs):
        self._target = target

    def start(self) -> None:
        self._target()


def _find_children(widget, cls):
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


def _pump_until(hidden_root, predicate, timeout: float = 5.0) -> None:
    import time

    deadline = time.time() + timeout
    while not predicate() and time.time() < deadline:
        hidden_root.update()
        time.sleep(0.01)
