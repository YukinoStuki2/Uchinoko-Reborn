# test_unity_export_heartbeat.py -- dev#602追補: Unity輸出フェーズの無音解消
#
# 背景: 問い合わせ Z5S945NP(韓国語「더이상 진행 안 됨」= これ以上進まない)で
# ユーザーが離脱した実例。根因は pipeline\cli\export_from_unity.ps1 L.301-302
# の子プロセス同期呼び出しがUnity終了まで一切stdoutへ出力しないこと(Unity自身の
# 出力は -logFile 指定のファイルにのみ書かれる)。
#
# 対応(このWPで追加): main_window.py側だけで完結するハートビート機構。
# 既存の_poll_active_handle()(80msポーリングループ、handle.is_running()の間
# 回り続ける)に相乗りし、一定間隔(pipeline_runner.UNITY_EXPORT_HEARTBEAT_
# INTERVAL_SEC=15秒)ごとに経過時間つきの合成メッセージをstatusLabel/ログ欄へ
# 出す。export_from_unity.ps1は無改変(輸出処理そのもの・Unityへの引数・
# FBX結果は不変)。
#
# 負の対照(重要、受入条件2): ハートビートは「実行中である」以上のことを
# 一切主張しない(成功文言を含まない)。実プロセスが失敗した場合の表示
# (StatusUnityExportFailed等)はon_exit(既存コード、_on_unity_export_exit)が
# 従来どおり担当し、ハートビートの有無に影響されない。
#
# tkの実ウィンドウは一切開かない(test_busy_bar_progress.pyと同じ、フェイク
# ウィジェット+フェイクselfに対してMainWindowの未束縛メソッドを直接呼ぶ方式)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pipeline_runner as pr  # noqa: E402
from ui import main_window as mw  # noqa: E402


# ---------------------------------------------------------------------------
# フェイク部品(test_busy_bar_progress.pyと同型)
# ---------------------------------------------------------------------------


class _FakeLabel:
    def __init__(self) -> None:
        self.text: str | None = None

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]


class _FakeProcessHandle:
    """pipeline_runner.ProcessHandle互換の最小フェイク。poll()は何もしない
    (実キュー処理は本ファイルの関心事ではない、_poll_active_handleの
    ハートビート配線のみを検証する)。"""

    def __init__(self, running: bool = True) -> None:
        self._running = running
        self.poll_calls = 0

    def poll(self) -> None:
        self.poll_calls += 1

    def is_running(self) -> bool:
        return self._running


class _FakeSelf:
    """_maybe_emit_unity_export_heartbeat/_poll_active_handle/_on_pipeline_line
    を束縛せずに呼ぶための最小self。"""

    _POLL_INTERVAL_MS = 80

    def __init__(self) -> None:
        self.widgets = {"statusLabel": _FakeLabel()}
        self.logged: list[str] = []
        self._active_handle: _FakeProcessHandle | None = None
        self._active_phase = pr.PHASE_UNITY_EXPORT
        self._unity_export_started_at: float | None = None
        self._unity_export_last_output_at: float | None = None
        self._early_preview_loaded_this_run = False
        self._pipeline_warnings: list[str] = []
        self.after_calls: list[tuple[int, object]] = []

    def _log(self, text: str) -> None:
        self.logged.append(text)

    def _set_busy_bar_mode(self, mode: str) -> None:
        # 本ファイルの関心事はハートビートの発火タイミングのみ。
        # busyBarモード遷移自体はtest_busy_bar_progress.pyの担当。
        pass

    @property
    def root(self):
        return self

    def after(self, ms, fn) -> None:
        self.after_calls.append((ms, fn))

    _maybe_emit_unity_export_heartbeat = mw.MainWindow._maybe_emit_unity_export_heartbeat
    _poll_active_handle = mw.MainWindow._poll_active_handle
    _on_pipeline_line = mw.MainWindow._on_pipeline_line
    # dev#897: statusLabel設定がself._set_status()経由に変わったための追加束縛。
    _set_status = mw.MainWindow._set_status


def _set_now(monkeypatch, seconds: float) -> None:
    monkeypatch.setattr(mw.time, "monotonic", lambda: seconds)


# ---------------------------------------------------------------------------
# _maybe_emit_unity_export_heartbeat
# ---------------------------------------------------------------------------


def test_heartbeat_does_not_fire_before_interval(monkeypatch):
    fake_self = _FakeSelf()
    fake_self._unity_export_started_at = 1000.0
    fake_self._unity_export_last_output_at = 1000.0
    _set_now(monkeypatch, 1010.0)  # 10秒経過 < 15秒間隔
    fake_self._maybe_emit_unity_export_heartbeat()
    assert fake_self.logged == []
    assert fake_self.widgets["statusLabel"].text is None


def test_heartbeat_fires_after_interval_with_elapsed_time(monkeypatch):
    import i18n

    i18n.set_language("ja")
    fake_self = _FakeSelf()
    fake_self._unity_export_started_at = 1000.0
    fake_self._unity_export_last_output_at = 1000.0
    _set_now(monkeypatch, 1017.0)  # 17秒経過 >= 15秒間隔
    fake_self._maybe_emit_unity_export_heartbeat()
    assert len(fake_self.logged) == 1
    assert "00:17" in fake_self.logged[0]
    status_text = fake_self.widgets["statusLabel"].text
    assert "00:17" in status_text
    # statusLabelは元の案内文(所要時間の目安込み)を維持したまま経過時間を付記する
    assert i18n.S("StatusUnityExporting") in status_text


def test_heartbeat_message_never_claims_success():
    """負の対照(受入条件2の核心): ハートビート文言は「実行中」の域を出ない。
    完了/成功を示す既存キーの文言(StatusUnityExportDone)を一切含まない。"""
    import i18n

    for lang in i18n.LANGS:
        i18n.set_language(lang)
        heartbeat_text = i18n.F("LogUnityExportHeartbeatFormat", "00:30")
        done_text = i18n.S("StatusUnityExportDone")
        assert done_text not in heartbeat_text
        # 完了語彙("完了"/"finished"/"완료"/"已完成")を含まないことも確認する
        for done_word in ("完了", "finished", "완료", "已完成"):
            assert done_word not in heartbeat_text, (
                f"heartbeat text for lang={lang} contains completion wording "
                f"'{done_word}': {heartbeat_text!r}"
            )
    i18n.set_language("ja")


def test_heartbeat_resets_after_real_output_line(monkeypatch):
    """_on_pipeline_line()で実際の行を受け取ると、最終出力時刻がリセットされ、
    直後にはハートビートが発火しないこと(重複メッセージの抑止)。"""
    fake_self = _FakeSelf()
    fake_self._unity_export_started_at = 1000.0
    fake_self._unity_export_last_output_at = 1000.0
    _set_now(monkeypatch, 1020.0)  # 20秒経過(本来なら発火するタイミング)
    fake_self._on_pipeline_line("Launching Unity in headless mode...")
    # 実行中の行が来た時点でタイマーがリセットされている
    assert fake_self._unity_export_last_output_at == 1020.0
    # _on_pipeline_line自体が受け取った行をログへ転記する(既存AppendLog相当の
    # 挙動)ため、ここまでのログ件数を基準にする
    logged_count_after_line = len(fake_self.logged)
    fake_self._maybe_emit_unity_export_heartbeat()
    # リセット直後(経過0秒)なのでハートビートは追加で発火しない
    assert len(fake_self.logged) == logged_count_after_line


def test_on_pipeline_line_does_not_reset_timer_outside_unity_export_phase():
    """負の対照: フル変換フェーズ(PHASE_PIPELINE)では、このリセットが
    無関係な副作用を起こさないこと(_unity_export_last_output_atは触られない)。"""
    fake_self = _FakeSelf()
    fake_self._active_phase = pr.PHASE_PIPELINE
    fake_self._unity_export_last_output_at = None
    fake_self._on_pipeline_line("plain log line")
    assert fake_self._unity_export_last_output_at is None


# ---------------------------------------------------------------------------
# _poll_active_handle: ハートビート配線
# ---------------------------------------------------------------------------


def test_poll_active_handle_emits_heartbeat_during_unity_export(monkeypatch):
    fake_self = _FakeSelf()
    fake_self._active_handle = _FakeProcessHandle(running=True)
    fake_self._active_phase = pr.PHASE_UNITY_EXPORT
    fake_self._unity_export_started_at = 1000.0
    fake_self._unity_export_last_output_at = 1000.0
    _set_now(monkeypatch, 1020.0)
    fake_self._poll_active_handle()
    assert len(fake_self.logged) == 1
    assert "00:20" in fake_self.logged[0]
    # is_running()がTrueな間は次回ポーリングを予約し続ける(受入条件1:
    # 一定間隔で出力が届き続けるためには、ポーリング自体が止まってはならない)
    assert len(fake_self.after_calls) == 1


def test_poll_active_handle_does_not_emit_heartbeat_for_pipeline_phase(monkeypatch):
    """負の対照: フル変換(PHASE_PIPELINE)では##PROGRESS##マーカーが
    高頻度で来る前提のため、このハートビートは発火させない
    (無関係な合成メッセージでログを埋めない)。"""
    fake_self = _FakeSelf()
    fake_self._active_handle = _FakeProcessHandle(running=True)
    fake_self._active_phase = pr.PHASE_PIPELINE
    fake_self._unity_export_started_at = 1000.0
    fake_self._unity_export_last_output_at = 1000.0
    _set_now(monkeypatch, 1020.0)
    fake_self._poll_active_handle()
    assert fake_self.logged == []


def test_poll_active_handle_stops_heartbeat_once_process_exited(monkeypatch):
    """負の対照(受入条件2): プロセスが終了済み(is_running()=False、実際の
    失敗/成功はon_exit経由で別途処理される)なら、ハートビートは発火せず、
    次回ポーリングの予約も行われない(無限に「実行中」を主張し続けない)。"""
    fake_self = _FakeSelf()
    fake_self._active_handle = _FakeProcessHandle(running=False)
    fake_self._active_phase = pr.PHASE_UNITY_EXPORT
    fake_self._unity_export_started_at = 1000.0
    fake_self._unity_export_last_output_at = 1000.0
    _set_now(monkeypatch, 1999.0)  # 大幅に経過していても
    fake_self._poll_active_handle()
    assert fake_self.logged == []
    assert fake_self.after_calls == []
