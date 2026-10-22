# test_apply_pak_notify_survives_status_update_failure_dev1320.py --
# dev#1320追記実測の受入試験。
#
# 症状(2026-08-10 オーナー実機+指揮者確認): 「合成実行中に言語変更」した
# 同じセッションで、「適用」実行後の適用済み表示(appliedLabel/statusLabel
# 更新+完了msgbox)が出なかった。ファイル実体(Uchinoko_P.pak)は正しく
# 更新されており、適用処理(pak_manager.apply_pak)自体は成功していた。
# つまり失われたのは通知系のみ。
#
# 前任セッションの調査(work\wp_1320\NOTES.md)では、appliedLabel/statusLabel
# はmain_window起動時に1回だけ生成される常設ウィジェットで、multi_avatar_
# pak_dialog.pyのような「言語切替のたびに全部destroy()して作り直す」型の
# 機序は特定できなかった。issueの明示指示
# (「進行中処理からのUI更新経路全般を同じ機序として扱うこと」)に従い、
# _apply_pak_path()の付随的な状態更新(_on_update_applied_status/
# _set_status)がどんな理由であれ例外を投げても、ユーザー可視の完了通知
# (messagebox.showinfo)だけは独立して必ず届くよう防御的に分離した。
#
# 本ファイルはその構造(付随更新の失敗が通知を道連れにしないこと)を、
# 実tkウィンドウを開かずに「フェイクself」(test_preflight_warning_dialog_
# wiring.pyと同じ流儀)で検証する。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pak_manager  # noqa: E402
from ui import main_window as mw  # noqa: E402


def _bare_window() -> mw.MainWindow:
    return mw.MainWindow.__new__(mw.MainWindow)


def _fake_window_for_apply(
    *, on_update_applied_status_raises: bool, set_status_raises: bool
) -> mw.MainWindow:
    fake = _bare_window()
    fake._log_calls: list[str] = []
    fake._log = lambda text, _fake=fake, **_kw: _fake._log_calls.append(text)  # type: ignore[method-assign]
    fake._resolve_paks_dir_interactive = lambda: "C:\\FakePaksDir"  # type: ignore[method-assign]

    def _raise_update_applied() -> None:
        raise RuntimeError("simulated appliedLabel update failure (dev#1320)")

    def _raise_set_status(_render) -> None:
        raise RuntimeError("simulated statusLabel update failure (dev#1320)")

    fake._on_update_applied_status = (  # type: ignore[method-assign]
        _raise_update_applied if on_update_applied_status_raises else (lambda: None)
    )
    fake._set_status = (  # type: ignore[method-assign]
        _raise_set_status if set_status_raises else (lambda _render: None)
    )
    return fake


def test_apply_success_notice_survives_applied_label_update_failure_dev1320(
    tmp_path, monkeypatch
):
    """本丸①: appliedLabel更新(_on_update_applied_status)が例外を投げても、
    適用成功msgboxは必ず表示される。"""
    src = str(tmp_path / "MyAvatar_PlayerSwap_P.pak")
    with open(src, "wb") as f:
        f.write(b"PAK")

    fake = _fake_window_for_apply(
        on_update_applied_status_raises=True, set_status_raises=False
    )

    monkeypatch.setattr(pak_manager, "is_game_running", lambda: False)
    monkeypatch.setattr(pak_manager, "apply_pak", lambda paks_dir, src_pak_path: src_pak_path)

    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))
    monkeypatch.setattr(mw.messagebox, "showwarning", lambda *a: (_ for _ in ()).throw(
        AssertionError(f"unexpected showwarning: {a}")))

    result = mw.MainWindow._apply_pak_path(fake, src, "MyAvatar")

    assert result is True
    assert len(info_calls) == 1, (
        "dev#1320再発: appliedLabel更新の失敗で適用完了msgboxまで消えた"
    )
    assert info_calls[0] == (
        i18n.S("TitleApplySuccess"), i18n.F("MsgApplySuccessFormat", "MyAvatar"))
    # 例外は握りつぶさず、ログには残す(サイレントに消さない)。
    assert any("appliedLabel update failed" in line for line in fake._log_calls)


def test_apply_success_notice_survives_status_label_update_failure_dev1320(
    tmp_path, monkeypatch
):
    """本丸②: statusLabel更新(_set_status)が例外を投げても、
    適用成功msgboxは必ず表示される。"""
    src = str(tmp_path / "MyAvatar_PlayerSwap_P.pak")
    with open(src, "wb") as f:
        f.write(b"PAK")

    fake = _fake_window_for_apply(
        on_update_applied_status_raises=False, set_status_raises=True
    )

    monkeypatch.setattr(pak_manager, "is_game_running", lambda: False)
    monkeypatch.setattr(pak_manager, "apply_pak", lambda paks_dir, src_pak_path: src_pak_path)

    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))

    result = mw.MainWindow._apply_pak_path(fake, src, "MyAvatar")

    assert result is True
    assert len(info_calls) == 1, (
        "dev#1320再発: statusLabel更新の失敗で適用完了msgboxまで消えた"
    )
    assert any("statusLabel update failed" in line for line in fake._log_calls)


def test_negative_control_apply_success_notice_shown_without_update_failure_dev1320(
    tmp_path, monkeypatch
):
    """負の対照: 付随更新が失敗しない通常経路でも、修正前後を問わず適用完了
    msgboxが表示されること(このアサーションが崩れていたら上2つのテストは
    このハーネス自体の前提が壊れている)。"""
    src = str(tmp_path / "MyAvatar_PlayerSwap_P.pak")
    with open(src, "wb") as f:
        f.write(b"PAK")

    fake = _fake_window_for_apply(
        on_update_applied_status_raises=False, set_status_raises=False
    )

    monkeypatch.setattr(pak_manager, "is_game_running", lambda: False)
    monkeypatch.setattr(pak_manager, "apply_pak", lambda paks_dir, src_pak_path: src_pak_path)

    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))

    result = mw.MainWindow._apply_pak_path(fake, src, "MyAvatar")

    assert result is True
    assert len(info_calls) == 1
    assert fake._log_calls == []
