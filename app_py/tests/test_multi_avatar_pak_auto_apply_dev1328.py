# test_multi_avatar_pak_auto_apply_dev1328.py -- dev#1328: マルチアバターPAK
# 合成完了後の自動適用+統合済み完了メッセージの試験。
#
# 2段構え:
#   1) _apply_after_compose()(tkinter非依存の純粋関数、_on_create()から抽出)
#      の単体試験。ctx.apply_pak_pathの有無・戻り値・例外の各分岐を機械判定する。
#   2) 「作成」ボタン押下からdlg.after()経由でon_ok()が呼ばれるところまでの
#      結線を、実スレッド+実tkinterイベントループ(hidden_root.update()での
#      ポーリング、test_support_dialog_full_log_attachment.pyと同じ流儀)で
#      通しで確認する。messagebox.showinfo/showwarningは実モーダルを開かせない
#      ようmonkeypatchする(test_preflight_warning_dialog_wiring.pyと同じ手法)。
#
# 負の対照: ctx.apply_pak_path=None(未配線)なら「作成したが適用に失敗した」
# 文言が出ること(=「適用していないのに適用したと言う」ことが無い)を確認する。
from __future__ import annotations

import os
import sys
import tempfile
import time
from unittest import mock

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import multi_avatar_pak_store as store  # noqa: E402
from ui import multi_avatar_pak_dialog as mapd  # noqa: E402

_ROOT_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_ROOT_DIR, "pipeline", "py")
if _PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_PY_DIR)
import vp_avatar_library as val  # noqa: E402
import vp_equipment_avatar as vea  # noqa: E402


# ---------------------------------------------------------------------------
# 1) _apply_after_compose() 単体試験
# ---------------------------------------------------------------------------


def _make_ctx(**overrides):
    base = dict(app_root="X", work_root="Y", palworld_pak=None, lang="ja")
    base.update(overrides)
    return mapd.MultiAvatarPakContext(**base)


def test_apply_after_compose_success_calls_apply_pak_path_with_pak_path_and_name():
    calls: list[tuple] = []
    ctx = _make_ctx(apply_pak_path=lambda src, name: calls.append((src, name)) or True)

    result = mapd._apply_after_compose(ctx, "C:\\fake\\Fusion_PlayerSwap_P.pak", "Fusion")

    assert result is True
    assert calls == [("C:\\fake\\Fusion_PlayerSwap_P.pak", "Fusion")]


def test_apply_after_compose_returns_false_when_apply_pak_path_returns_false():
    ctx = _make_ctx(apply_pak_path=lambda src, name: False)

    result = mapd._apply_after_compose(ctx, "C:\\fake\\Fusion_PlayerSwap_P.pak", "Fusion")

    assert result is False


def test_apply_after_compose_negative_control_no_apply_mechanism_wired():
    """負の対照: ctx.apply_pak_path=None(未配線)のとき、適用を試みず
    Falseを返すこと(「適用していないのに適用した」と言わない安全側)。"""
    logs: list[str] = []
    ctx = _make_ctx(append_log=logs.append, apply_pak_path=None)

    result = mapd._apply_after_compose(ctx, "C:\\fake\\Fusion_PlayerSwap_P.pak", "Fusion")

    assert result is False
    assert any("no apply mechanism wired" in line for line in logs)


def test_apply_after_compose_no_pak_path_returns_false_without_calling_apply():
    calls: list[tuple] = []
    ctx = _make_ctx(apply_pak_path=lambda src, name: calls.append((src, name)) or True)

    result = mapd._apply_after_compose(ctx, None, "Fusion")

    assert result is False
    assert calls == []


def test_apply_after_compose_exception_is_caught_and_returns_false():
    logs: list[str] = []

    def _boom(src, name):
        raise RuntimeError("apply exploded")

    ctx = _make_ctx(append_log=logs.append, apply_pak_path=_boom)

    result = mapd._apply_after_compose(ctx, "C:\\fake\\Fusion_PlayerSwap_P.pak", "Fusion")

    assert result is False
    assert any("apply exploded" in line for line in logs)


# ---------------------------------------------------------------------------
# 2) ダイアログ結線の通し試験(実スレッド+実イベントループ)
# ---------------------------------------------------------------------------


def _fake_extract_atlas(pak_path, out_png_path):
    os.makedirs(os.path.dirname(out_png_path), exist_ok=True)
    with open(out_png_path, "wb") as f:
        f.write(b"FAKE_ATLAS")
    return out_png_path


def _make_saved_entry(work_root, entry_id="Alicia"):
    job_dir = os.path.join(work_root, entry_id)
    build_dir = os.path.join(job_dir, "build")
    outfit_dir = os.path.join(build_dir, "noue_work", "variant", "Player", "Outfit")
    base = "SK_Player_Female_Outfit_Cloth001"
    d = os.path.join(outfit_dir, base)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, base + ".uasset"), "wb") as f:
        f.write(b"UA")
    with open(os.path.join(d, base + ".uexp"), "wb") as f:
        f.write(b"UE")
    os.makedirs(build_dir, exist_ok=True)
    out_pak = os.path.join(build_dir, f"{entry_id}_PlayerSwap_P.pak")
    with open(out_pak, "wb") as f:
        f.write(b"PAK")
    job = {"vrm_path": "", "avatar_name": entry_id, "genders": ["Female", "Male"]}
    with mock.patch.object(vea, "extract_avatar_atlas_png", side_effect=_fake_extract_atlas):
        val.save_library(job, job_dir, out_pak, os.path.join(build_dir, "noue_work"))
    return job_dir


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


class _SyncThread:
    """threading.Threadの最小フェイク。start()でtarget()を呼び出し元スレッド
    (=pytestのメインスレッド)上で同期実行する。dlg.after()はtkinterの実装上
    「登録済みのメインスレッド」から呼ばないとRuntimeErrorになる
    (Python 3.13、mainloop()を回していないpytest環境で実測)。本番コードは
    実スレッドで動く設計のまま(このフェイクはテストにのみ適用)であり、
    worker()内のロジック(dlg.after(0, on_ok)呼び出しを含む)自体は変更しない
    ——「呼ばれ方」だけをテストの都合で同期化している。"""

    def __init__(self, target=None, daemon=None, **_kwargs):
        self._target = target

    def start(self) -> None:
        self._target()


def _run_create_flow(hidden_root, monkeypatch, *, apply_pak_path, game_running=False):
    """「作成」ボタン→合成完了→on_ok()実行までを通しで駆動する共通セットアップ。
    合成エンジン本体(vp_avatar_compose.compose)は本WPのスコープ外(WP-2の担当)
    のためフェイクへ差し替え、pak_pathを返すことだけを保証する。

    dev#1361: 適用失敗時に表示されるメッセージのi18nキーは
    _apply_failure_message_key()(dev#1353)がpak_manager.is_game_running()の
    実プロセス検出結果で分岐する。開発機でPalworldが実際に起動しているかどうかで
    テスト結果が変わってしまっていた(#1361)ため、ここで決定的にモックする。
    既定はFalse(非起動)——既存の全アサーションが前提にしていた分岐。
    game_running=Trueを渡すテスト(下記)でTrue分岐も個別に固定検証する。"""
    monkeypatch.setattr(mapd.threading, "Thread", _SyncThread)
    monkeypatch.setattr(mapd.pak_manager, "is_game_running", lambda: game_running)
    app_root = tempfile.mkdtemp(prefix="d2p_map_apply_test_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_apply_test_work_")
    job_dir = _make_saved_entry(work_root, entry_id="Alicia")
    store.save_assignments(app_root, {"Bronze001": "Alicia"})

    fake_pak_path = os.path.join(job_dir, "build", "Alicia_PlayerSwap_P.pak")

    def _fake_run_compose(work_root_arg, job, log=print, python_exe=None):
        return {"job_dir": job_dir, "out_pak": fake_pak_path, "pak_path": fake_pak_path}

    monkeypatch.setattr(mapd.multi_avatar_pak_compose, "run_compose", _fake_run_compose)
    monkeypatch.setattr(mapd.simpledialog, "askstring", lambda *a, **k: "MyFusion")

    info_calls: list[tuple] = []
    warn_calls: list[tuple] = []
    monkeypatch.setattr(mapd.messagebox, "showinfo", lambda *a: info_calls.append(a))
    monkeypatch.setattr(mapd.messagebox, "showwarning", lambda *a: warn_calls.append(a))

    ctx = mapd.MultiAvatarPakContext(
        app_root=app_root, work_root=work_root, palworld_pak=None, lang="ja",
        apply_pak_path=apply_pak_path,
    )
    dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, ctx)
    try:
        create_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate"))
        assert create_btn is not None
        create_btn.invoke()

        deadline = time.time() + 5.0
        while not info_calls and not warn_calls and time.time() < deadline:
            hidden_root.update()
            time.sleep(0.01)
    finally:
        dlg.destroy()
    return info_calls, warn_calls


def test_create_then_apply_success_shows_combined_success_message(hidden_root, monkeypatch):
    apply_calls: list[tuple] = []

    def _fake_apply(pak_path, avatar_name):
        apply_calls.append((pak_path, avatar_name))
        return True

    info_calls, warn_calls = _run_create_flow(hidden_root, monkeypatch, apply_pak_path=_fake_apply)

    assert apply_calls and apply_calls[0][1] == "MyFusion"
    assert warn_calls == []
    assert info_calls, "成功時はshowinfoで通知されるはず"
    assert info_calls[0][1] == i18n.S("LabMultiAvatarPakCreateAndApplySuccess")


def test_create_then_apply_failure_shows_combined_failure_message(hidden_root, monkeypatch):
    def _fake_apply(pak_path, avatar_name):
        return False

    info_calls, warn_calls = _run_create_flow(hidden_root, monkeypatch, apply_pak_path=_fake_apply)

    assert info_calls == []
    assert warn_calls, "適用失敗時はshowwarningで通知されるはず"
    assert warn_calls[0][1] == i18n.S("LabMultiAvatarPakCreateApplyFailure")


def test_negative_control_no_apply_mechanism_wired_shows_failure_not_success(hidden_root, monkeypatch):
    """負の対照(ダイアログ結線レベル): ctx.apply_pak_path=None(main_window.py
    側の配線漏れを模す)でも、成功メッセージが誤って出ないこと。"""
    info_calls, warn_calls = _run_create_flow(hidden_root, monkeypatch, apply_pak_path=None)

    assert info_calls == []
    assert warn_calls, "未配線でも適用失敗として扱われ、成功を偽装しないこと"
    assert warn_calls[0][1] == i18n.S("LabMultiAvatarPakCreateApplyFailure")


def test_create_then_apply_failure_when_game_running_shows_dedicated_message(hidden_root, monkeypatch):
    """dev#1361: is_game_running=Trueの分岐も本ファイル内で決定的に固定する
    (dev#1353の専用メッセージがこの結線でも正しく選ばれること)。"""
    def _fake_apply(pak_path, avatar_name):
        return False

    info_calls, warn_calls = _run_create_flow(
        hidden_root, monkeypatch, apply_pak_path=_fake_apply, game_running=True)

    assert info_calls == []
    assert warn_calls, "適用失敗時はshowwarningで通知されるはず"
    assert warn_calls[0][1] == i18n.S("LabMultiAvatarPakCreateApplyFailureGameRunning")
