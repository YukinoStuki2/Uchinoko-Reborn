# -*- coding: utf-8 -*-
r"""dev#702 第3弾WP-3受入試験: main_window.py の prefab入力ハンドラ
(_on_prefab_selected/_on_unity_export_exit)。

正本: C:\P\Work\DiveToPalworld\work\rd_702\PROPOSAL.md 「WP-3」節。

確認したい契約は2つ:
  1. GUI表示(vrmBox、job.jsonのvrm_path)は輸出成功後・キャッシュヒット後の
     どちらでもprefabパスのまま維持される(fbxへ差し替えない)。
  2. キャッシュ(lu_export.is_export_cache_fresh)が新鮮ならUnity再起動
     (pipeline_runner.run_unity_export)そのものを省略する。輸出が実行された
     場合は成功時にsig(lu_export.save_export_sig)を保存し、次回の判定に使う。

tkの実ウィンドウは一切開かない(既存test_guard_dialogs.py/test_unity_export_heartbeat.py
と同じ流儀: mw.MainWindow.__new__()で束縛前selfを作り、必要な属性だけ後付けする)。
実Unity・実pwshは呼ばない(pipeline_runner.run_unity_exportをfakeへ差し替える)。

実行: python -m pytest app_py\tests\test_prefab_gui_cache.py -v
"""
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import lu_export  # noqa: E402
import pipeline_runner as pr  # noqa: E402
from ui import main_window as mw  # noqa: E402


def _bare_window():
    """__init__を通さずMainWindowインスタンスだけ得る(既存test_guard_dialogs.pyと
    同じ手筋)。テストごとに必要な属性だけ後付けする。"""
    fake = mw.MainWindow.__new__(mw.MainWindow)
    fake._pending_prefab_export_path = None
    # dev#1056: 既定はBlender準備済み(ほとんどのテストはBlender待機ロジック
    # 自体を検査対象にしていないため、ここでTrueにしておかないと本WPで追加した
    # ゲートに阻まれて全テストが赤くなる)。待機ロジックを検査するテストだけ
    # 明示的にFalseへ上書きする。
    fake._blender_ready = True
    fake._pending_prefab_drop_path = None
    return fake


class _FakeLabel:
    def __init__(self) -> None:
        self.text: str | None = None

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]


class _FakeRoot:
    def after(self, ms, fn) -> None:
        pass


def _write(path, content=b"prefab-bytes-v1"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def _make_fake(tmp_path, monkeypatch, *, script_exists: bool = True):
    fake = _bare_window()
    fake.widgets = {"statusLabel": _FakeLabel()}
    fake.work_root = str(tmp_path / "work_root")
    os.makedirs(fake.work_root, exist_ok=True)
    fake.app_root = str(tmp_path / "app_root")
    os.makedirs(fake.app_root, exist_ok=True)
    fake._active_handle = None
    fake.root = _FakeRoot()
    fake._POLL_INTERVAL_MS = 80

    set_vrm_calls = []
    fake._set_vrm_path = lambda path: set_vrm_calls.append(path)
    fake._clear_log = lambda: None
    fake._set_running_ui_state = lambda *a, **k: None

    log_calls = []
    fake._log = lambda text, **_k: log_calls.append(text)
    ensure_blender_calls = []
    fake._ensure_blender_ready_on_startup = lambda: ensure_blender_calls.append(True)
    fake._log_calls = log_calls
    fake._ensure_blender_calls = ensure_blender_calls

    error_calls = []
    info_calls = []
    monkeypatch.setattr(mw.messagebox, "showerror", lambda *a: error_calls.append(a))
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))

    # Unity輸出スクリプトの実在チェックを通す(実体は使わない、パスの存在確認のみ)
    script_path = os.path.join(fake.app_root, "pipeline", "cli", "export_from_unity.ps1")
    if script_exists:
        _write(script_path, b"# fake export_from_unity.ps1")
    monkeypatch.setattr(
        pr, "build_unity_export_script_path", lambda app_root: script_path
    )

    return fake, set_vrm_calls, error_calls, info_calls


# ===========================================================================
# 1) キャッシュ新鮮: Unity再起動を省略し、prefabパスをそのまま表示に使う
# ===========================================================================


def test_prefab_selected_skips_unity_export_when_cache_fresh(tmp_path, monkeypatch):
    fake, set_vrm_calls, _, _ = _make_fake(tmp_path, monkeypatch)
    prefab = str(tmp_path / "avatar.prefab")
    _write(prefab)

    out_dir = pr.resolve_unity_export_out_dir(fake.work_root, prefab)
    os.makedirs(out_dir, exist_ok=True)
    _write(os.path.join(out_dir, "avatar.fbx"), b"cached-fbx")
    lu_export.save_export_sig(out_dir, prefab)
    # dev#1551 laneG5修理: is_export_cache_fresh()はエクスポータ指紋も要求する
    # ようになったため、真に新鮮なキャッシュを模すにはこれも書く必要がある。
    lu_export.save_exporter_schema_sig(out_dir)

    def _fail_if_called(*_a, **_k):
        raise AssertionError("run_unity_export must not be called when cache is fresh")

    monkeypatch.setattr(pr, "run_unity_export", _fail_if_called)

    mw.MainWindow._on_prefab_selected(fake, prefab)

    assert set_vrm_calls == [prefab], (
        "キャッシュヒット時もGUI表示はprefabパスのまま(fbxへ差し替えない)"
    )


def test_prefab_selected_forwards_log_to_run_unity_export(tmp_path, monkeypatch):
    """dev#1242申し送り②: pipeline_runner.run_unity_export()へself._logが
    log=として渡されること(find_pwsh()の探索ログが実GUI経路で失われないこと
    の直接検査)。"""
    fake, _, _, _ = _make_fake(tmp_path, monkeypatch)
    prefab = str(tmp_path / "avatar.prefab")
    _write(prefab)

    captured_kwargs = {}

    class _FakeHandle:
        def __init__(self, out_dir):
            self.out_dir = out_dir

    def fake_run_unity_export(app_root, work_root, prefab_path, *, on_line, on_exit, log=None):
        captured_kwargs["log"] = log
        return _FakeHandle(pr.resolve_unity_export_out_dir(work_root, prefab_path))

    monkeypatch.setattr(pr, "run_unity_export", fake_run_unity_export)

    mw.MainWindow._on_prefab_selected(fake, prefab)

    assert captured_kwargs.get("log") is fake._log, (
        "run_unity_export()へfake._log(=main_window.pyのself._log)が"
        "そのまま渡されていない(結線漏れ)"
    )
    # 実際に呼べば探索ログがログ欄(fake._log_calls、「ログをコピー」相当)へ
    # 届くこと自体も確認する。
    captured_kwargs["log"]("[blender_setup] auto PATH pwsh.exe -> found, selected: X")
    assert "[blender_setup] auto PATH pwsh.exe -> found, selected: X" in fake._log_calls


def test_prefab_selected_runs_unity_export_when_cache_missing(tmp_path, monkeypatch):
    """負の対照: 初回(sig無し)はキャッシュ新鮮ではないため、通常どおり
    Unity輸出を起動する。"""
    fake, set_vrm_calls, _, _ = _make_fake(tmp_path, monkeypatch)
    prefab = str(tmp_path / "avatar.prefab")
    _write(prefab)

    class _FakeHandle:
        def __init__(self, out_dir):
            self.out_dir = out_dir

    run_calls = []

    def fake_run_unity_export(app_root, work_root, prefab_path, *, on_line, on_exit, log=None):
        run_calls.append((app_root, work_root, prefab_path))
        return _FakeHandle(pr.resolve_unity_export_out_dir(work_root, prefab_path))

    monkeypatch.setattr(pr, "run_unity_export", fake_run_unity_export)

    mw.MainWindow._on_prefab_selected(fake, prefab)

    assert len(run_calls) == 1
    assert run_calls[0][2] == prefab
    assert set_vrm_calls == [], "輸出完了(on_exit)前はまだ_set_vrm_pathを呼ばない"
    assert fake._pending_prefab_export_path == prefab


# ===========================================================================
# 1.5) dev#1056: Blender初回セットアップ(DL)完了前にprefabが投入された場合、
#      Unity輸出を起動せず保留し、セットアップ成功後に自動的に続行する。
#      旧実装はBlender準備状態を一切見ずにUnity輸出(_active_handle/busyBar
#      書き換え)を即座に開始しており、Blenderセットアップ側の進捗表示
#      (_on_blender_progress、同じbusyBarを書き換える)と競合して
#      フリーズ/クラッシュしていた(#915は同じ引き金による表示混在の軽症状)。
# ===========================================================================


def test_prefab_selected_defers_and_does_not_start_unity_export_when_blender_not_ready(
    tmp_path, monkeypatch
):
    fake, set_vrm_calls, _, _ = _make_fake(tmp_path, monkeypatch)
    fake._blender_ready = False
    prefab = str(tmp_path / "avatar.prefab")
    _write(prefab)

    def _fail_if_called(*_a, **_k):
        raise AssertionError(
            "run_unity_export must not be called while Blender setup is in progress"
        )

    monkeypatch.setattr(pr, "run_unity_export", _fail_if_called)

    mw.MainWindow._on_prefab_selected(fake, prefab)

    assert fake._pending_prefab_drop_path == prefab, (
        "Blender未準備時はprefabパスを保留するだけで、Unity輸出を開始しない"
    )
    assert fake._active_handle is None, (
        "Unity輸出の非同期ハンドルが作られていないこと"
        "(#1056が実際に起きていた=busyBar/_active_handleへの同時書き込みの根)"
    )
    assert set_vrm_calls == []
    assert len(fake._ensure_blender_calls) == 1, (
        "Blenderセットアップの開始/継続を試みること(C#版EnsureBlenderReadyForConversion"
        "と同じ設計)"
    )


def test_prefab_selected_negative_control_proceeds_immediately_when_blender_ready(
    tmp_path, monkeypatch
):
    """負の対照: Blender準備済みなら従来どおり即座にUnity輸出を開始する
    (本WPのゲートが誤って常時ブロックする退行に転じていないことの実証)。"""
    fake, set_vrm_calls, _, _ = _make_fake(tmp_path, monkeypatch)
    fake._blender_ready = True
    prefab = str(tmp_path / "avatar.prefab")
    _write(prefab)

    run_calls = []

    class _FakeHandle:
        def __init__(self, out_dir):
            self.out_dir = out_dir

    def fake_run_unity_export(app_root, work_root, prefab_path, *, on_line, on_exit, log=None):
        run_calls.append(prefab_path)
        return _FakeHandle(pr.resolve_unity_export_out_dir(work_root, prefab_path))

    monkeypatch.setattr(pr, "run_unity_export", fake_run_unity_export)

    mw.MainWindow._on_prefab_selected(fake, prefab)

    assert run_calls == [prefab]
    assert fake._pending_prefab_drop_path is None
    assert fake._ensure_blender_calls == []


def _fake_window_for_blender_done():
    """_on_blender_setup_done()単体を検査するための最小フェイク
    (test_error_next_action.py::_fake_window_for_blender_done と同じ流儀)。"""
    fake = _bare_window()
    fake.widgets = {
        "busyBar": _FakeLabel(),
        "statusLabel": _FakeLabel(),
        "blenderRetryButton": _FakeLabel(),
    }
    fake.widgets["busyBar"].place_forget = lambda: None
    fake.widgets["blenderRetryButton"].place_forget = lambda: None
    fake.widgets["blenderRetryButton"].place = lambda **kw: None
    fake._update_button_states = lambda: None
    # dev#1239: _on_blender_setup_done()がconvertButtonのゲート再計算を明示的に
    # 呼ぶようになったため(本ファイルの対象外の関心事なのでno-opで済ませる)。
    fake._refresh_convert_button_freshness = lambda: None
    fake._warm_startup_after_blender_ready = lambda: None
    fake._offer_report_after_failure = lambda *_a, **_k: None
    log_calls = []
    fake._log = lambda text, **_k: log_calls.append(text)
    fake._log_calls = log_calls

    prefab_selected_calls = []
    fake._on_prefab_selected = lambda path: prefab_selected_calls.append(path)
    fake._prefab_selected_calls = prefab_selected_calls
    return fake


def test_blender_setup_done_success_resumes_deferred_prefab_drop(tmp_path):
    fake = _fake_window_for_blender_done()
    prefab = str(tmp_path / "avatar.prefab")
    fake._pending_prefab_drop_path = prefab

    mw.MainWindow._on_blender_setup_done(
        fake, True, None, mw.blender_setup.BlenderSetupAction.READY_NO_ACTION
    )

    assert fake._blender_ready is True
    assert fake._pending_prefab_drop_path is None, "保留は消費後にクリアされること"
    assert fake._prefab_selected_calls == [prefab], (
        "Blender準備完了後、保留していたprefabドロップを自動的に続行すること"
        "(ユーザー操作はドロップ1回で済む、C#版EnsureBlenderReadyForConversionと同じ設計)"
    )


def test_blender_setup_done_failure_negative_control_keeps_pending_for_next_retry(tmp_path):
    """負の対照: セットアップ失敗時は保留を消費・消去しない
    (「Blenderを再取得」ボタンでの次回成功時に持ち越す、C#版
    DoEnsureBlenderReady() L.2091-2096の`if (ok && pendingBlenderReadyAction != null)`
    と同じ契約——okがfalseならこの分岐自体を通らない)。"""
    fake = _fake_window_for_blender_done()
    prefab = str(tmp_path / "avatar.prefab")
    fake._pending_prefab_drop_path = prefab

    mw.MainWindow._on_blender_setup_done(
        fake, False, "boom", mw.blender_setup.BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT
    )

    assert fake._blender_ready is False
    assert fake._pending_prefab_drop_path == prefab, (
        "失敗時は保留を消さない(次回リトライ成功時に自動続行させるため)"
    )
    assert fake._prefab_selected_calls == []


def test_blender_setup_done_success_negative_control_no_pending_does_nothing_extra():
    """負の対照: 保留が無い(通常の起動時セットアップ)場合は、成功しても
    _on_prefab_selectedを余計に呼ばない。"""
    fake = _fake_window_for_blender_done()
    fake._pending_prefab_drop_path = None

    mw.MainWindow._on_blender_setup_done(
        fake, True, None, mw.blender_setup.BlenderSetupAction.READY_NO_ACTION
    )

    assert fake._prefab_selected_calls == []


# ===========================================================================
# 2) _on_unity_export_exit: 成功時はprefabパスを表示・sigを保存
# ===========================================================================


class _FakeHandleWithOutDir:
    def __init__(self, out_dir):
        self.out_dir = out_dir


def test_unity_export_exit_success_sets_prefab_path_and_saves_sig(tmp_path, monkeypatch):
    fake, set_vrm_calls, error_calls, info_calls = _make_fake(tmp_path, monkeypatch)
    prefab = str(tmp_path / "avatar.prefab")
    _write(prefab)
    out_dir = pr.resolve_unity_export_out_dir(fake.work_root, prefab)
    os.makedirs(out_dir, exist_ok=True)
    _write(os.path.join(out_dir, "avatar.fbx"), b"freshly-exported-fbx")

    fake._active_handle = _FakeHandleWithOutDir(out_dir)
    fake._pending_prefab_export_path = prefab

    mw.MainWindow._on_unity_export_exit(fake, 0)

    assert set_vrm_calls == [prefab], (
        "輸出成功後もGUI表示はprefabパスのまま(fbxへ差し替えない、WP-3の核心)"
    )
    assert error_calls == [] and info_calls == []
    assert lu_export.is_export_cache_fresh(out_dir, prefab) is True, (
        "輸出成功後はsigが保存され、次回呼び出しでキャッシュ新鮮と判定されるはず"
    )


def test_unity_export_exit_failure_does_not_set_vrm_path_or_save_sig(tmp_path, monkeypatch):
    """負の対照: 輸出失敗(code!=0)時はGUI表示を変更せず、sigも保存しない。"""
    fake, set_vrm_calls, error_calls, info_calls = _make_fake(tmp_path, monkeypatch)
    prefab = str(tmp_path / "avatar.prefab")
    _write(prefab)
    out_dir = pr.resolve_unity_export_out_dir(fake.work_root, prefab)
    fake._active_handle = _FakeHandleWithOutDir(out_dir)
    fake._pending_prefab_export_path = prefab

    mw.MainWindow._on_unity_export_exit(fake, 1)

    assert set_vrm_calls == []
    assert len(error_calls) == 1
    assert not os.path.isdir(out_dir) or not os.path.isfile(
        lu_export.prefab_export_sig_path(out_dir)
    )


def test_unity_export_exit_no_fbx_does_not_set_vrm_path_or_save_sig(tmp_path, monkeypatch):
    """負の対照: exit=0でもfbxが見つからない異常ケースではGUI表示・sig保存の
    どちらも行わない。"""
    fake, set_vrm_calls, error_calls, info_calls = _make_fake(tmp_path, monkeypatch)
    prefab = str(tmp_path / "avatar.prefab")
    _write(prefab)
    out_dir = pr.resolve_unity_export_out_dir(fake.work_root, prefab)
    os.makedirs(out_dir, exist_ok=True)  # fbxは書かない
    fake._active_handle = _FakeHandleWithOutDir(out_dir)
    fake._pending_prefab_export_path = prefab

    mw.MainWindow._on_unity_export_exit(fake, 0)

    assert set_vrm_calls == []
    assert len(info_calls) == 1
    assert not os.path.isfile(lu_export.prefab_export_sig_path(out_dir))


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
