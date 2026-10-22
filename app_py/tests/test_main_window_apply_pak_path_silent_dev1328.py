# test_main_window_apply_pak_path_silent_dev1328.py -- dev#1328: マルチアバター
# PAK合成後の自動適用コア(MainWindow._apply_pak_path_silent)の単体試験。
#
# test_preflight_warning_dialog_wiring.pyと同じ流儀: tkの実ウィンドウは開かず、
# mw.MainWindow.__new__(mw.MainWindow)の「フェイクself」に必要な属性/メソッド
# だけ後付けしてメソッド本体を直接呼ぶ。_apply_pak_path(既存の「Palworldに
# 適用」ボタンの中核)とは異なり、この関数はmessageboxを一切出さない設計
# (呼び出し元のui\multi_avatar_pak_dialog.pyが統合済みの成功/失敗メッセージを
# 1個だけ出すため)。したがって受入の柱は「messageboxが一度も呼ばれないこと」+
# 「戻り値が実際の適用成否と一致すること」の両方。
from __future__ import annotations

import os
import sys
import tempfile

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import main_window as mw  # noqa: E402


def _bare_window() -> mw.MainWindow:
    return mw.MainWindow.__new__(mw.MainWindow)


def _fake_window(*, paks_dir=None) -> mw.MainWindow:
    fake = _bare_window()
    fake._log_calls: list[str] = []
    fake._log = lambda text, _fake=fake, **_kw: _fake._log_calls.append(text)  # type: ignore[method-assign]
    fake._resolve_paks_dir_interactive = lambda: paks_dir  # type: ignore[method-assign]
    fake._applied_status_calls = 0
    fake._status_calls: list = []

    def _bump_applied() -> None:
        fake._applied_status_calls += 1

    def _bump_status(fn) -> None:
        fake._status_calls.append(fn())

    fake._on_update_applied_status = _bump_applied  # type: ignore[method-assign]
    fake._set_status = _bump_status  # type: ignore[method-assign]
    return fake


def _make_src_pak(tmp_path) -> str:
    p = os.path.join(str(tmp_path), "Fusion_PlayerSwap_P.pak")
    with open(p, "wb") as f:
        f.write(b"PAK")
    return p


def test_success_calls_apply_pak_and_returns_true_without_messagebox(tmp_path, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(mw.pak_manager, "is_game_running", lambda: False)
    monkeypatch.setattr(
        mw.pak_manager, "apply_pak",
        lambda paks_dir, src: calls.append((paks_dir, src)) or os.path.join(paks_dir, "x.pak"),
    )
    info_calls: list[tuple] = []
    warn_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))
    monkeypatch.setattr(mw.messagebox, "showwarning", lambda *a: warn_calls.append(a))

    src = _make_src_pak(tmp_path)
    fake = _fake_window(paks_dir=str(tmp_path / "Paks"))

    result = mw.MainWindow._apply_pak_path_silent(fake, src, "Fusion")

    assert result is True
    assert calls == [(str(tmp_path / "Paks"), src)]
    assert fake._applied_status_calls == 1
    assert len(fake._status_calls) == 1
    assert "Fusion" in fake._status_calls[0]
    # messageboxは一切出ない(統合メッセージは呼び出し元の責務)
    assert info_calls == []
    assert warn_calls == []


def test_missing_src_file_returns_false_without_apply_pak_call(tmp_path, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(mw.pak_manager, "is_game_running", lambda: False)
    monkeypatch.setattr(mw.pak_manager, "apply_pak", lambda paks_dir, src: calls.append((paks_dir, src)))

    fake = _fake_window(paks_dir=str(tmp_path / "Paks"))
    missing_src = os.path.join(str(tmp_path), "does_not_exist.pak")

    result = mw.MainWindow._apply_pak_path_silent(fake, missing_src, "Fusion")

    assert result is False
    assert calls == []


def test_game_running_returns_false_without_apply_pak_call(tmp_path, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(mw.pak_manager, "is_game_running", lambda: True)
    monkeypatch.setattr(mw.pak_manager, "apply_pak", lambda paks_dir, src: calls.append((paks_dir, src)))

    src = _make_src_pak(tmp_path)
    fake = _fake_window(paks_dir=str(tmp_path / "Paks"))

    result = mw.MainWindow._apply_pak_path_silent(fake, src, "Fusion")

    assert result is False
    assert calls == []


def test_paks_dir_unresolved_returns_false(tmp_path, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(mw.pak_manager, "is_game_running", lambda: False)
    monkeypatch.setattr(mw.pak_manager, "apply_pak", lambda paks_dir, src: calls.append((paks_dir, src)))

    src = _make_src_pak(tmp_path)
    fake = _fake_window(paks_dir=None)

    result = mw.MainWindow._apply_pak_path_silent(fake, src, "Fusion")

    assert result is False
    assert calls == []


def test_apply_pak_exception_returns_false_and_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(mw.pak_manager, "is_game_running", lambda: False)

    def _boom(paks_dir, src):
        raise OSError("disk full")

    monkeypatch.setattr(mw.pak_manager, "apply_pak", _boom)
    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))
    monkeypatch.setattr(mw.messagebox, "showerror", lambda *a: info_calls.append(a))

    src = _make_src_pak(tmp_path)
    fake = _fake_window(paks_dir=str(tmp_path / "Paks"))

    result = mw.MainWindow._apply_pak_path_silent(fake, src, "Fusion")

    assert result is False
    # 詳細はログにのみ残る(messageboxは一切出ない)
    assert any("disk full" in line for line in fake._log_calls)
    assert info_calls == []
