# test_progress_eta_wiring.py -- dev#137: 進捗ETA化のGUI配線検証。
#
# progress_eta.py の純関数自体はtest_progress_eta.pyで検証済み。本ファイルは
# 「推定した数字が実際にstatusLabelの表示文字列へ入ること」(配線の実証。
# 関数を作っただけで画面に出ない、が本プロジェクトの頻発事故)と、
# 「履歴が無い/不足のときは現行の%表示のままフォールバックすること」を、
# main_window.MainWindowの未束縛メソッドをフェイクselfへ直接束縛する方式
# (test_busy_bar_progress.py/test_unity_export_heartbeat.pyと同型)で検証する。
#
# tkの実ウィンドウは一切開かない。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pipeline_runner as pr  # noqa: E402
import progress_eta as eta  # noqa: E402
from ui import main_window as mw  # noqa: E402


# ---------------------------------------------------------------------------
# フェイク部品(test_busy_bar_progress.py/test_unity_export_heartbeat.pyと同型)
# ---------------------------------------------------------------------------


class _FakeLabel:
    def __init__(self) -> None:
        self.text: str | None = None

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]


class _FakeSelfForPipelineLine:
    """_on_pipeline_line/_record_eta_checkpoint_and_estimateを束縛せずに
    呼ぶための最小self。app_root/_eta_*系のrun状態は各テストが個別に設定する
    (_start_pipeline()を経ていない状態=既存の他テストと同じ最小構成にも
    対応できることを別テストで確認する)。"""

    def __init__(self) -> None:
        self.widgets = {
            "busyBar": {},
            "statusLabel": _FakeLabel(),
        }
        self._active_handle = None
        self._early_preview_loaded_this_run = False
        self._pipeline_warnings: list[str] = []
        self.logged: list[str] = []

    def _log(self, text: str) -> None:
        self.logged.append(text)

    def _set_busy_bar_mode(self, _mode: str) -> None:
        pass

    _on_pipeline_line = mw.MainWindow._on_pipeline_line
    _record_eta_checkpoint_and_estimate = mw.MainWindow._record_eta_checkpoint_and_estimate
    _record_eta_run_on_success = mw.MainWindow._record_eta_run_on_success
    # dev#897: statusLabel設定がself._set_status()経由に変わったための追加束縛。
    _set_status = mw.MainWindow._set_status


def _set_now(monkeypatch, seconds: float) -> None:
    monkeypatch.setattr(mw.time, "monotonic", lambda: seconds)


def setup_function(_fn) -> None:
    # "en"を使う: PROGRESS_LABELS辞書の英訳は原文(raw label)と同一なので、
    # テスト内のアサーションで生ラベル文字列とそのまま比較できる
    # (翻訳の有無自体はi18n.py側の既存テストの担当、本ファイルの関心事は
    # ETA配線のみ)。
    i18n.set_language("en")


def teardown_function(_fn) -> None:
    i18n.set_language("ja")


# ---------------------------------------------------------------------------
# 配線の実証: 履歴が十分なとき、ETAが実際にstatusLabelへ入ること
# ---------------------------------------------------------------------------


def test_eta_appears_in_status_label_when_history_is_sufficient(monkeypatch, tmp_path):
    """履歴あり(2件、いずれも50%地点で50秒・100%地点で100秒)+今回も
    50%地点でちょうど50秒経過(履歴と同じペース)という条件で、
    statusLabelに「残り約 00:50」が実際に現れること。"""
    app_root = str(tmp_path)
    eta.save_history(
        app_root,
        {
            eta.MODE_FULL: [
                [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],
                [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],
            ]
        },
    )
    fake_self = _FakeSelfForPipelineLine()
    fake_self.app_root = app_root
    fake_self._eta_mode = eta.MODE_FULL
    fake_self._eta_run_started_at = 1000.0
    fake_self._eta_checkpoints = []
    _set_now(monkeypatch, 1050.0)  # 経過50秒

    fake_self._on_pipeline_line("##PROGRESS## 50 Halfway there")

    status_text = fake_self.widgets["statusLabel"].text
    assert status_text is not None
    expected_suffix = i18n.F("StatusEtaSuffixFormat", "00:50")
    assert expected_suffix in status_text, (
        f"ETA suffix not found in status label text: {status_text!r}"
    )
    # 進捗ラベル・%表示自体も従来どおり残っていること(ETA追加が既存表示を
    # 壊していないことの確認)
    assert "(50%)" in status_text


def test_eta_checkpoints_are_recorded_across_multiple_markers(monkeypatch, tmp_path):
    """マーカー到着のたびに(pct, 経過秒)が_eta_checkpointsへ積まれること
    (record_run()が使う母材そのもの)。"""
    fake_self = _FakeSelfForPipelineLine()
    fake_self.app_root = str(tmp_path)
    fake_self._eta_mode = eta.MODE_FULL
    fake_self._eta_run_started_at = 1000.0
    fake_self._eta_checkpoints = []

    _set_now(monkeypatch, 1002.0)
    fake_self._on_pipeline_line("##PROGRESS## 2 Preparing")
    _set_now(monkeypatch, 1055.0)
    fake_self._on_pipeline_line("##PROGRESS## 55 Generating MOD files")

    assert fake_self._eta_checkpoints == [(2, 2.0), (55, 55.0)]


# ---------------------------------------------------------------------------
# フォールバック(推定不能): 履歴が無い/不足のときは現行の%表示のまま
# ---------------------------------------------------------------------------


def test_status_label_falls_back_to_plain_percent_when_history_dir_is_empty(
    monkeypatch, tmp_path
):
    """履歴ファイルが存在しない(初回実行相当)場合、ETA suffixを一切追加せず、
    従来どおり `ラベル... (pct%)` のままであること(でっち上げ禁止の核心)。"""
    fake_self = _FakeSelfForPipelineLine()
    fake_self.app_root = str(tmp_path)  # progress_history.jsonが存在しない空dir
    fake_self._eta_mode = eta.MODE_FULL
    fake_self._eta_run_started_at = 1000.0
    fake_self._eta_checkpoints = []
    _set_now(monkeypatch, 1010.0)

    fake_self._on_pipeline_line("##PROGRESS## 10 Loading avatar")

    status_text = fake_self.widgets["statusLabel"].text
    assert status_text == "Loading avatar... (10%)"


def test_status_label_falls_back_when_history_has_only_one_run(monkeypatch, tmp_path):
    """境界: 履歴が1件だけの場合もMIN_HISTORY_RUNS未満のためNone扱いとなり、
    フォールバック表示のままであること。"""
    app_root = str(tmp_path)
    eta.save_history(
        app_root,
        {eta.MODE_FULL: [[[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]]]},
    )
    fake_self = _FakeSelfForPipelineLine()
    fake_self.app_root = app_root
    fake_self._eta_mode = eta.MODE_FULL
    fake_self._eta_run_started_at = 1000.0
    fake_self._eta_checkpoints = []
    _set_now(monkeypatch, 1050.0)

    fake_self._on_pipeline_line("##PROGRESS## 50 Halfway there")

    status_text = fake_self.widgets["statusLabel"].text
    assert status_text == "Halfway there... (50%)"


def test_status_label_falls_back_when_run_state_is_absent():
    """_start_pipeline()を経ていない呼び出し(run状態が一切無い)でも、
    ETA計算をスキップして安全にフォールバックすること(既存の他テストの
    最小フェイクselfと同じ状況の再現)。"""
    fake_self = _FakeSelfForPipelineLine()
    # app_root/_eta_mode/_eta_run_started_at のいずれも設定しない

    fake_self._on_pipeline_line("##PROGRESS## 42 Retargeting skeleton")

    status_text = fake_self.widgets["statusLabel"].text
    assert status_text == "Retargeting skeleton... (42%)"


# ---------------------------------------------------------------------------
# 負の対照(必須): 外れ値混入時、statusLabelに表示される数字も中央値ベースの
# ままで、外れ値1件に引きずられないこと(GUI配線を通した実証)
# ---------------------------------------------------------------------------


def test_status_label_eta_is_not_skewed_by_a_single_outlier_run(monkeypatch, tmp_path):
    app_root = str(tmp_path)
    eta.save_history(
        app_root,
        {
            eta.MODE_FULL: [
                [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],  # 残り50秒
                [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],  # 残り50秒
                [[0.0, 0.0], [50.0, 50.0], [100.0, 550.0]],  # 外れ値: 残り500秒
            ]
        },
    )
    fake_self = _FakeSelfForPipelineLine()
    fake_self.app_root = app_root
    fake_self._eta_mode = eta.MODE_FULL
    fake_self._eta_run_started_at = 1000.0
    fake_self._eta_checkpoints = []
    _set_now(monkeypatch, 1050.0)

    fake_self._on_pipeline_line("##PROGRESS## 50 Halfway there")

    status_text = fake_self.widgets["statusLabel"].text
    expected_suffix = i18n.F("StatusEtaSuffixFormat", "00:50")
    assert expected_suffix in status_text, (
        f"外れ値に引きずられた表示になっている疑い: {status_text!r}"
    )


# ---------------------------------------------------------------------------
# _record_eta_run_on_success: 成功終了時の恒常履歴への確定保存
# ---------------------------------------------------------------------------


def test_record_eta_run_on_success_persists_checkpoints_and_total_duration(
    monkeypatch, tmp_path
):
    app_root = str(tmp_path)
    fake_self = _FakeSelfForPipelineLine()
    fake_self.app_root = app_root
    fake_self._eta_mode = eta.MODE_FULL
    fake_self._eta_run_started_at = 1000.0
    fake_self._eta_checkpoints = [(2, 1.0), (55, 30.0), (96, 58.0)]
    _set_now(monkeypatch, 1060.0)  # 経過60秒でプロセス終了

    fake_self._record_eta_run_on_success()

    history = eta.load_history(app_root)
    runs = history[eta.MODE_FULL]
    assert len(runs) == 1
    assert runs[0][0] == [2.0, 1.0]
    assert runs[0][-1] == [100.0, 60.0]  # 96%止まりの実測値をtotal_durationで補完


def test_record_eta_run_on_success_noop_when_run_state_absent(tmp_path):
    """_start_pipeline()を経ていない場合(run状態が無い)は何も保存しない
    (でっち上げの元になる不完全なrunを履歴に残さない)。"""
    fake_self = _FakeSelfForPipelineLine()
    fake_self.app_root = str(tmp_path)
    # _eta_mode/_eta_run_started_at/_eta_checkpointsのいずれも設定しない

    fake_self._record_eta_run_on_success()

    assert eta.load_history(str(tmp_path)) == {}
