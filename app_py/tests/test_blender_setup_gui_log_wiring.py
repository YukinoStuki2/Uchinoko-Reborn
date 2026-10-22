# test_blender_setup_gui_log_wiring.py -- dev#1242申し送り②の受入条件:
# 「実装した」ではなく「効いている」ことの検査。
#
# blender_setup.do_ensure_blender_ready()のlog=引数(find_blender()/find_pwsh()
# の探索ログを1行ずつ通知するコールバック)は、PR #1250時点では実GUI経路
# main_window.py の _blender_setup_worker() から結線されておらず、実際の
# GUI起動では探索ログが一切収集されていなかった(呼び出しがlog=無しの
# do_ensure_blender_ready(...)のまま)。
#
# 本WPで _blender_setup_worker() -> self._blender_queue(("log", line)) ->
# _poll_blender_queue() -> self._log(line) という、既存のon_progressと同じ
# queueマーシャリングパターンでの結線を追加した。tkの実ウィンドウは一切開かず
# (tk.Tk()を呼ばない)、既存test_preview_freshness.py等と同じ「フェイクself +
# unboundメソッド直接呼び出し」手法を踏襲する。
from __future__ import annotations

import os
import queue
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import main_window as mw  # noqa: E402


class _FakeRoot:
    def __init__(self) -> None:
        self.after_calls: list[tuple] = []

    def after(self, ms, fn) -> None:
        self.after_calls.append((ms, fn))


class _FakeSelfForBlenderWorkerLog:
    """_blender_setup_worker()/_poll_blender_queue()を素通りさせるための
    最小フェイクself。実プロセス起動・実tkウィジェットは一切使わない。"""

    _blender_setup_worker = mw.MainWindow._blender_setup_worker
    _poll_blender_queue = mw.MainWindow._poll_blender_queue

    def __init__(self) -> None:
        self.app_root = "dummy_app_root"
        self._blender_queue: "queue.Queue[tuple]" = queue.Queue()
        self._blender_setup_process_handle = None
        self.root = _FakeRoot()
        self.logs: list[str] = []
        self.progress_calls: list[tuple] = []
        self.done_calls: list[tuple] = []

    def _log(self, text: str, **_kwargs) -> None:
        self.logs.append(text)

    def _on_blender_progress(self, pct: int, phase: str) -> None:
        self.progress_calls.append((pct, phase))

    def _on_blender_setup_done(self, ok, fail_message, action) -> None:
        self.done_calls.append((ok, fail_message, action))


def test_blender_setup_worker_wires_search_log_to_main_thread_log(monkeypatch):
    """本丸(赤→緑): do_ensure_blender_ready()が受け取ったlog=コールバックへ
    実際に書き込んだ行が、_blender_setup_worker()(ワーカースレッド相当)→
    _blender_queue→_poll_blender_queue()(主スレッド相当)を経て、最終的に
    self._log()へ届くこと。届かなければ実GUIで探索ログが失われたまま
    (本WPが是正する不具合そのもの)。"""
    fake = _FakeSelfForBlenderWorkerLog()

    def fake_do_ensure_blender_ready(app_root, on_progress=None, process_handle=None, log=None):
        # 負の対照の核心: log引数が実際に渡されている(=結線されている)ことを
        # ここで検査する。Noneのままなら「実装したが効いていない」の再現になる。
        assert log is not None, (
            "log引数が渡されていない: _blender_setup_worker()の結線が外れている"
            "(dev#1242申し送り②の再発)"
        )
        assert callable(log)
        log("[blender_setup] manual-env D2P_BLENDER_EXE -> not set")
        log("[blender_setup] manual-env D2P_PWSH_EXE -> not set")
        if on_progress is not None:
            on_progress(50, "fake-phase")
        return True, None, mw.blender_setup.BlenderSetupAction.READY_NO_ACTION

    monkeypatch.setattr(
        mw.blender_setup, "do_ensure_blender_ready", fake_do_ensure_blender_ready
    )

    # ワーカースレッド相当(このテストでは同期呼び出し、スレッド自体の生成は
    # _ensure_blender_ready_on_startup()の責務でありここでは検査しない)。
    fake._blender_setup_worker()

    # このタイミングではまだ主スレッド側(_poll_blender_queue)を呼んでいない
    # ため、ログはまだself._logへ届いていない(queueに積まれているだけ)。
    assert fake.logs == [], (
        "poll前にlogsへ届いている: queueマーシャリングを経由せず直接tkに"
        "触れている疑いがある(バックグラウンドスレッドからの直接描画は禁止)"
    )

    fake._poll_blender_queue()

    assert fake.logs == [
        "[blender_setup] manual-env D2P_BLENDER_EXE -> not set",
        "[blender_setup] manual-env D2P_PWSH_EXE -> not set",
    ], f"探索ログがself._logへ届いていない(実際: {fake.logs})"
    assert fake.progress_calls == [(50, "fake-phase")]
    assert fake.done_calls == [(True, None, mw.blender_setup.BlenderSetupAction.READY_NO_ACTION)]


def test_blender_setup_worker_negative_control_no_log_lines_when_source_silent(monkeypatch):
    """負の対照: do_ensure_blender_ready()側が何もlog()しなければ、
    self._logへも何も届かない(=queue経由の結線が余計な行を捏造したり、
    無関係な既存ログ("done"等)を混入させたりしていないこと)。"""
    fake = _FakeSelfForBlenderWorkerLog()

    def silent_do_ensure_blender_ready(app_root, on_progress=None, process_handle=None, log=None):
        assert log is not None
        return True, None, mw.blender_setup.BlenderSetupAction.READY_NO_ACTION

    monkeypatch.setattr(
        mw.blender_setup, "do_ensure_blender_ready", silent_do_ensure_blender_ready
    )

    fake._blender_setup_worker()
    fake._poll_blender_queue()

    assert fake.logs == []
    assert fake.done_calls == [(True, None, mw.blender_setup.BlenderSetupAction.READY_NO_ACTION)]
