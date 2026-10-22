# test_pipeline_runner_sway_fallback_dev1649.py -- dev#1649
# 「揺れ起因エラーの自動フォールバック: 失敗を検知したら揺れ無しで変換し直して
# 完走+GUI警告」の回帰テスト。
#
# オーナー裁定(issue #1649本文): 「エラーを検知して揺れなしに自動フォール
# バックする」(殆どの揺れの問題を蓋する)。実tk.Tk()は使わない
# (pipeline_runner.pyはtkinter非依存)。実プロセス(convert.ps1/Blender等)も
# 一切起動しない——pipeline_runner.ProcessHandleをFakeProcessHandleへ
# monkeypatchし、on_line/on_exitを手動で発火させる「失敗注入のモック」方式
# (CLAUDE.md「個別タスクの受入で変換を伴う試験を課してはならない」に沿う)。
#
# 発動条件(pipeline_runner._sway_fallback_eligible参照): 揺れ有効
# (sway_intensityがsoft/normal/hardのいずれか)かつフル変換
# (preview_only/materials_onlyいずれもFalse)。段階の分類はせず「全体失敗→
# 全体リトライ」という素朴な形(指示書の「判断の少なさを優先」を踏襲)。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pipeline_runner as pr  # noqa: E402

VRM_PATH = "C:\\fake_avatar.vrm"  # 実在しないパスでよい(write_job()の
# springbone抽出はfail-open、CatalogFromVrm失敗時もWARNログのみで続行する
# 既存設計、pipeline_runner.write_job()のdocstring参照)。


class FakeProcessHandle:
    """テスト専用: 実プロセスを一切起動しない、ProcessHandleと同じ形の
    最小スタブ。start()は状態フラグを立てるだけ、poll()は何もしない
    (テストがfire_line/fire_exitで手動駆動する)。"""

    instances: list["FakeProcessHandle"] = []

    def __init__(self, shell, args, on_line, on_exit):
        self.shell = shell
        self.args = args
        self._on_line = on_line
        self._on_exit = on_exit
        self.job_dir = None
        self.out_dir = None
        self.exit_code = None
        self.started = False
        self.killed = False
        FakeProcessHandle.instances.append(self)

    def start(self):
        self.started = True

    def poll(self):  # pragma: no cover - テストではfire_*を直接使う
        pass

    def is_running(self):
        return self.started and self.exit_code is None

    def kill(self):
        self.killed = True

    def fire_line(self, line: str) -> None:
        self._on_line(line)

    def fire_exit(self, code: int) -> None:
        self.exit_code = code
        self._on_exit(code)


def _reset_instances():
    FakeProcessHandle.instances = []


def _run(monkeypatch, tmp_path, *, sway_intensity="normal", preview_only=False,
          materials_only=False):
    """run_pipeline()を、on_line収集リスト・on_exit結果セル・work_rootと
    ともに起動する共通セットアップ。"""
    _reset_instances()
    monkeypatch.setattr(pr, "ProcessHandle", FakeProcessHandle)
    work_root = str(tmp_path / "work")
    app_root = str(tmp_path / "app")
    os.makedirs(work_root, exist_ok=True)
    os.makedirs(app_root, exist_ok=True)

    lines: list[str] = []
    exits: list[int] = []
    handle = pr.run_pipeline(
        app_root, work_root, VRM_PATH,
        preview_only=preview_only, materials_only=materials_only,
        on_line=lines.append, on_exit=exits.append,
        sway_intensity=sway_intensity,
    )
    return handle, lines, exits, work_root


def _job_json_path(work_root: str) -> str:
    return os.path.join(work_root, "fakeavatar", "job.json")


def test_sway_success_no_fallback(tmp_path, monkeypatch):
    """受入基準④: 揺れ有効+成功時はフォールバックが発動しない
    (=既存の成功経路と1:1で同じ、instanceが1つだけ・on_exit(0)のみ)。"""
    handle, lines, exits, work_root = _run(monkeypatch, tmp_path, sway_intensity="normal")
    FakeProcessHandle.instances[0].fire_exit(0)

    assert len(FakeProcessHandle.instances) == 1, "成功時に2回目のプロセスが起動されている"
    assert exits == [0]
    assert not any("AVATAR_WARNING" in ln for ln in lines)
    assert not any("dev#1649" in ln for ln in lines)


def test_sway_disabled_failure_no_fallback(tmp_path, monkeypatch):
    """受入基準③: 揺れ無効時は発動しない(失敗してもそのまま元コードで報告)。"""
    handle, lines, exits, work_root = _run(monkeypatch, tmp_path, sway_intensity="none")
    FakeProcessHandle.instances[0].fire_exit(5)

    assert len(FakeProcessHandle.instances) == 1, "揺れ無効なのに2回目のプロセスが起動されている"
    assert exits == [5]
    assert not any("dev#1649" in ln for ln in lines)


def test_sway_enabled_failure_then_fallback_success(tmp_path, monkeypatch):
    """受入基準①: 揺れ有効+失敗→無効リトライ→警告付き成功。"""
    handle, lines, exits, work_root = _run(monkeypatch, tmp_path, sway_intensity="normal")

    # job_dir に「1回目の汚染された中間状態」を模したファイルを置く。
    job_dir = FakeProcessHandle.instances[0].job_dir
    contamination = os.path.join(job_dir, "converted", "leftover.blend")
    os.makedirs(os.path.dirname(contamination), exist_ok=True)
    with open(contamination, "w", encoding="utf-8") as f:
        f.write("stale")

    FakeProcessHandle.instances[0].fire_exit(1)

    assert len(FakeProcessHandle.instances) == 2, "揺れ有効の失敗でリトライが起動されていない"
    # 3. リトライは汚染された中間状態を引き継がない(job_dirがクリーンに
    # 作り直されている=leftover.blendは消えている)。
    assert not os.path.exists(contamination), "job_dirがクリーンにされずリトライされた"

    # リトライ先job.jsonは揺れ無効(sway_intensity/sway_enableどちらも
    # 省略、write_job()のドキュメント通り)。
    with open(_job_json_path(work_root), encoding="utf-8") as f:
        retry_job = json.load(f)
    assert "sway_intensity" not in retry_job
    assert "sway_enable" not in retry_job

    FakeProcessHandle.instances[1].fire_exit(0)

    assert exits == [0], "フォールバック成功後の最終結果はexit=0であるべき"
    assert any("##AVATAR_WARNING##" in ln for ln in lines), "GUI警告マーカーが出ていない"
    assert any("Sway (jiggle) physics processing caused an error" in ln for ln in lines)


def test_sway_enabled_failure_then_fallback_also_fails(tmp_path, monkeypatch):
    """受入基準②: リトライも失敗→元エラーで報告(フォールバック自身の
    exitコードではなく、1回目の元エラーコードで最終報告する)。"""
    handle, lines, exits, work_root = _run(monkeypatch, tmp_path, sway_intensity="normal")

    FakeProcessHandle.instances[0].fire_exit(7)
    assert len(FakeProcessHandle.instances) == 2

    # フォールバック実行(2回目)自身の生ログは、GUIのon_lineへ中継されない
    # (main_windowの_pipeline_fatal_causeを2回目の別エラーで上書きさせない
    # ため——指示書「リトライも失敗→元エラーで報告」)。
    FakeProcessHandle.instances[1].fire_line("##AVATAR_FATAL## unrelated_second_failure")
    FakeProcessHandle.instances[1].fire_exit(3)

    assert exits == [7], f"最終報告は元のexitコード(7)であるべきだが実際は{exits}"
    assert not any("unrelated_second_failure" in ln for ln in lines), (
        "2回目の生ログがon_lineへ中継されてしまっている(元エラー上書きの危険)")
    assert not any("##AVATAR_WARNING##" in ln for ln in lines), "失敗時に成功用の警告が出ている"
    assert any("dev#1649" in ln and "also failed" in ln for ln in lines), (
        "リトライも失敗した旨の要約ログが出ていない")


def test_preview_only_not_eligible(tmp_path, monkeypatch):
    """フル変換以外(プレビューのみ)は対象外(材料補給が軽量パスの前提を
    壊さないため)。"""
    handle, lines, exits, work_root = _run(
        monkeypatch, tmp_path, sway_intensity="normal", preview_only=True)
    FakeProcessHandle.instances[0].fire_exit(2)

    assert len(FakeProcessHandle.instances) == 1
    assert exits == [2]


def test_materials_only_not_eligible(tmp_path, monkeypatch):
    """フル変換以外(影のみ更新)も対象外。"""
    handle, lines, exits, work_root = _run(
        monkeypatch, tmp_path, sway_intensity="hard", materials_only=True)
    FakeProcessHandle.instances[0].fire_exit(2)

    assert len(FakeProcessHandle.instances) == 1
    assert exits == [2]


def test_user_cancel_does_not_trigger_fallback(tmp_path, monkeypatch):
    """ユーザー自身のCancel(handle.kill())は失敗ではないため、フォール
    バックを発動しない(main_window.pyは無改修でhandle.kill()を呼ぶだけ)。"""
    handle, lines, exits, work_root = _run(monkeypatch, tmp_path, sway_intensity="normal")
    handle.kill()
    FakeProcessHandle.instances[0].fire_exit(-1)

    assert len(FakeProcessHandle.instances) == 1, "ユーザー中止なのにリトライが起動されている"
    assert exits == [-1]


def test_sway_fallback_eligible_matrix():
    """_sway_fallback_eligible()の純関数マトリクス(境界値を直接固定)。"""
    for intensity in ("soft", "normal", "hard"):
        assert pr._sway_fallback_eligible(intensity, False, False) is True
    assert pr._sway_fallback_eligible("none", False, False) is False
    assert pr._sway_fallback_eligible("normal", True, False) is False
    assert pr._sway_fallback_eligible("normal", False, True) is False


def test_clean_job_dir_for_retry_removes_contents(tmp_path):
    job_dir = tmp_path / "job"
    (job_dir / "converted").mkdir(parents=True)
    (job_dir / "converted" / "x.blend").write_text("x", encoding="utf-8")

    pr._clean_job_dir_for_retry(str(job_dir))

    assert not job_dir.exists()


def test_clean_job_dir_for_retry_tolerates_missing_dir(tmp_path):
    """存在しないjob_dirを渡しても例外を投げない(fail-open)。"""
    missing = str(tmp_path / "does_not_exist")
    pr._clean_job_dir_for_retry(missing)  # 例外が出なければOK
    pr._clean_job_dir_for_retry(None)  # Noneも同様
