# test_warm_visibility_dev45.py -- dev#45 残件2点(WP wp_45b_warm_visibility)の
# 受入試験。
#
# 対象:
#   ① warm_cache()完了後への自動GC呼び出しの配線
#      (app_py\warm_startup.py::warm_shared_cache_on_startup ->
#       _run_shared_cache_gc_after_warm() -> devtools\disk_guard.py::
#       gc_shared_cache_after_warm())。
#   ② GUIステータスバーへのwarm状態表示
#      (app_py\ui\main_window.py::WarmCacheStatus状態オブジェクト+
#       _poll_warm_cache_status()/_maybe_log_warm_cache_first_run_notice())。
#
# 方針(共通契約どおり、tkの実ウィンドウは一切開かない):
# ②はtest_button_gates.py等と同じ「フェイクself + 束縛前メソッド呼び出し」
# 方式で検証する。①はtest_warm_startup.pyと同じDI(popen差し替え)方式に
# 加え、GCフック自体はmonkeypatchで観測する(モックで呼び出しを観測、
# 受入条件どおり)。「現行版数を消さない」の負の対照だけは、実際の
# devtools\disk_guard.py(このworktree自身、tests\shipcheck\test_disk_guard.py
# が既に保持ポリシー自体を広く検査済みなので、ここでは配線経路が実際に
# 現行世代を守ることの統合確認に絞る)を経由させる。
#
# --- dev#45b追記(WP wp_45b_followup、2026-08-02、書き込み許可: 追記のみ) ---
# 上記①の呼び出し先は devtools\disk_guard.py::gc_shared_cache_after_warm() で
# はなく app_py\shared_cache_gc.py::gc_shared_cache_after_warm() へ変更された
# (WP wp_45b_followup 指示書「穴2」: devtools\は配布zipに同梱されないため、
# 旧配線はエンドユーザーの配布版で常にスキップされていた=実質未達。
# devtools\disk_guard.pyは今もCLI/release.py/relgate.py向けの薄い後方互換
# shimとして残るが、warm_startup.py自身はもう経由しない)。
#
# この変更に伴い、本ファイル内で唯一
# test_dev45_2c_gc_hook_skips_silently_when_devtools_absent だけは、
# 「app_root配下にdevtools\が無ければGCがスキップされる」という**旧(バグ)
# 挙動そのもの**を正としてassertしていたため、書き換えが不可避だった
# (この1関数のみ、本WPが例外的に書き換えている。他の13関数は完全に無改変)。
# 理由: devtools\の有無に関わらずGCが実際に走るようにすることこそが
# 本WPの主目的であり、旧assertionを温存すると「バグを直したのにバグを
# 証明するテストが緑のまま」という矛盾した状態になる
# (CLAUDE.md「実装したと効いているは別」の精神に反する)。新しい
# assertionは「devtools不在でもGCが実際に実行される(=work_root配下の
# _shared_cacheを見に行っている)」ことを検証する形に置き換えた。
# ---------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, List, Optional

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

_REPO_ROOT = os.path.dirname(_APP_PY_DIR)

import i18n  # noqa: E402
import warm_startup  # noqa: E402
from ui import main_window as mw  # noqa: E402


def _read(work_root: str, name: str) -> str:
    path = Path(work_root) / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _wait_until(predicate, timeout_sec: float = 5.0, step: float = 0.05) -> bool:
    """完了ログ/GC呼び出しはバックグラウンドスレッドで非同期に起きるため、
    test_warm_startup.pyと同じ短間隔ポーリングで待つ。"""
    waited = 0.0
    while waited < timeout_sec:
        if predicate():
            return True
        time.sleep(step)
        waited += step
    return predicate()


class _FakeProc:
    """subprocess.Popen互換の最小フェイク(test_warm_startup.pyと同じ)。"""

    def __init__(self, lines: Optional[List[str]] = None, returncode: int = 0, delay: float = 0.0):
        self.stdout = iter(lines or [])
        self._returncode = returncode
        self._delay = delay
        self.returncode: Optional[int] = None

    def wait(self) -> int:
        if self._delay:
            time.sleep(self._delay)
        self.returncode = self._returncode
        return self.returncode


def _make_recording_popen(fake_proc_factory):
    calls: List[Any] = []

    def _popen(*args: Any, **kwargs: Any):
        calls.append((args, kwargs))
        return fake_proc_factory()

    return _popen, calls


def _setup_warm_cache_fixture(tmp_path):
    """test_warm_startup.py::test_case3_warm_shared_cache_launches_when_all_
    guards_passと同じ、warm_shared_cache_on_startup()の全ガードを通す最小
    構成を作る(app_root/work_root/blender_exe/pak_path/convert_noue.py)。"""
    app_root = str(tmp_path)
    work_root = str(tmp_path / "work")
    blender_exe = str(tmp_path / "assets" / "tools" / "blender-9.9.9-windows-x64" / "blender.exe")
    os.makedirs(os.path.dirname(blender_exe), exist_ok=True)
    Path(blender_exe).write_text("stub")
    bpython_dir = os.path.join(os.path.dirname(blender_exe), "9.9", "python", "bin")
    os.makedirs(bpython_dir, exist_ok=True)
    Path(os.path.join(bpython_dir, "python.exe")).write_text("stub")
    pak_path = str(tmp_path / "Pal-Windows.pak")
    Path(pak_path).write_text("stub")
    script_dir = os.path.join(app_root, "pipeline", "py")
    os.makedirs(script_dir, exist_ok=True)
    Path(os.path.join(script_dir, "convert_noue.py")).write_text("# stub")
    return app_root, work_root, blender_exe, pak_path


# ---------------------------------------------------------------------------
# ① GC呼び出しの配線(モックで観測)
# ---------------------------------------------------------------------------


def test_dev45_1_gc_hook_called_after_successful_warm_cache_exit(tmp_path, monkeypatch):
    """受入条件1: warm_cache()完了後にGCが呼ばれることをモックで観測する。"""
    calls: List[tuple] = []

    def _fake_gc(app_root: str, work_root: str) -> None:
        calls.append((app_root, work_root))

    monkeypatch.setattr(warm_startup, "_run_shared_cache_gc_after_warm", _fake_gc)

    app_root, work_root, blender_exe, pak_path = _setup_warm_cache_fixture(tmp_path)
    popen, popen_calls = _make_recording_popen(lambda: _FakeProc(returncode=0))

    warm_startup.warm_shared_cache_on_startup(
        app_root, work_root, blender_ready=True, blender_exe=blender_exe,
        pak_path=pak_path, popen=popen,
    )

    assert _wait_until(lambda: len(calls) == 1), (
        "warm_cache()完了(exit code=0)後もGCフックが呼ばれなかった"
        f"(popen呼び出し回数={len(popen_calls)}, log={_read(work_root, 'warm_startup.log')})"
    )
    assert calls == [(app_root, work_root)]


def test_dev45_1b_gc_hook_not_called_when_warm_cache_exits_nonzero(tmp_path, monkeypatch):
    """exit code!=0(失敗終了)ではGCを呼ばない(壊れた/未完成のビルド成果物を
    正常世代として扱わないための安全側)。"""
    calls: List[tuple] = []
    monkeypatch.setattr(
        warm_startup, "_run_shared_cache_gc_after_warm",
        lambda app_root, work_root: calls.append((app_root, work_root)),
    )

    app_root, work_root, blender_exe, pak_path = _setup_warm_cache_fixture(tmp_path)
    popen, _popen_calls = _make_recording_popen(lambda: _FakeProc(returncode=1))

    warm_startup.warm_shared_cache_on_startup(
        app_root, work_root, blender_ready=True, blender_exe=blender_exe,
        pak_path=pak_path, popen=popen,
    )

    assert _wait_until(lambda: "warm-cache: exited code=1" in _read(work_root, "warm_startup.log"))
    assert calls == [], "exit code!=0なのにGCフックが呼ばれた"


def test_dev45_1c_gc_hook_not_called_when_popen_raises(tmp_path, monkeypatch):
    """popen()自体が例外を投げた(起動失敗)場合もGCを呼ばない、かつ例外は
    外へ伝播しない(既存の「失敗は無視」方針との整合)。"""
    calls: List[tuple] = []
    monkeypatch.setattr(
        warm_startup, "_run_shared_cache_gc_after_warm",
        lambda app_root, work_root: calls.append((app_root, work_root)),
    )

    app_root, work_root, blender_exe, pak_path = _setup_warm_cache_fixture(tmp_path)

    def _raising_popen(*args, **kwargs):
        raise OSError("simulated launch failure")

    threw = False
    try:
        warm_startup.warm_shared_cache_on_startup(
            app_root, work_root, blender_ready=True, blender_exe=blender_exe,
            pak_path=pak_path, popen=_raising_popen,
        )
    except Exception:  # noqa: BLE001
        threw = True

    assert threw is False
    assert calls == []


# ---------------------------------------------------------------------------
# ① 負の対照(必須): 現行版数のキャッシュ世代は絶対に消さない
#    (配線経路=_run_shared_cache_gc_after_warm()を実際に通す統合確認。
#    保持ポリシー自体の網羅的検査はtests\shipcheck\test_disk_guard.py担当)
# ---------------------------------------------------------------------------


def _make_generation(shared_cache_root: str, kind: str, fp12: str, mtime: float,
                      size_bytes: int = 64) -> tuple[str, str]:
    """work\\_shared_cache\\<kind>\\<fp12>\\ の世代1件を模擬構築する。
    戻り値: (gen_dir, marker_path)"""
    kind_dir = os.path.join(shared_cache_root, kind)
    gen_dir = os.path.join(kind_dir, fp12)
    os.makedirs(gen_dir, exist_ok=True)
    with open(os.path.join(gen_dir, "payload.bin"), "wb") as f:
        f.write(b"x" * size_bytes)
    marker = gen_dir.rstrip("\\/") + ".fingerprint.json"
    with open(marker, "w", encoding="utf-8") as f:
        f.write("{}")
    os.utime(marker, (mtime, mtime))
    return gen_dir, marker


def test_dev45_2_wired_gc_never_deletes_current_generation(tmp_path, monkeypatch):
    """受入条件2(負の対照、必須): 現行版数を含む状況を作り、①の配線経路
    (warm_startup._run_shared_cache_gc_after_warm、実devtools\\disk_guard.py
    経由)がそれを削除対象に含めないことを示す。

    app_root には本テストファイルが属するworktree自身のリポジトリルート
    (_REPO_ROOT、devtools\\disk_guard.pyが実在する)を渡す——dev環境で
    実行する限り①の配線が実際にdisk_guardへ到達することの確認も兼ねる
    (配布版ではdevtools\\が存在せずスキップされる、_run_shared_cache_gc_
    after_warm()のdocstring/本WPの完了報告に明記した既知の制約)。"""
    monkeypatch.delenv("D2P_SHARED_CACHE", raising=False)

    work_root = str(tmp_path / "work")
    shared_cache_root = os.path.join(work_root, "_shared_cache")
    now = time.time()
    day = 24 * 60 * 60

    # kind="live_template" に3世代: 最新(現行)/1つ前(安全マージン)/
    # 2日前(keep_n=2の範囲外・ロック無し・grace(既定1時間)超過=削除対象)。
    current_dir, current_marker = _make_generation(
        shared_cache_root, "live_template", "aaaaaaaaaaaa", now
    )
    margin_dir, _margin_marker = _make_generation(
        shared_cache_root, "live_template", "bbbbbbbbbbbb", now - day
    )
    stale_dir, stale_marker = _make_generation(
        shared_cache_root, "live_template", "cccccccccccc", now - 2 * day
    )

    warm_startup._run_shared_cache_gc_after_warm(_REPO_ROOT, work_root)

    assert os.path.isdir(current_dir), "現行世代(最新)が削除された(致命的)"
    assert os.path.isfile(current_marker), "現行世代のマーカーが削除された(致命的)"
    assert os.path.isdir(margin_dir), "安全マージン世代(2番目に新しい)が削除された"
    # 2日前(keep_n=2の範囲外、grace超過、ロック無し)は実際に削除される
    # ことも合わせて確認する(①が本当に「効いている」ことの積極的証拠、
    # dry-runのまま何も消えていないだけの偽陽性を排除するため)。
    assert not os.path.isdir(stale_dir), (
        "2日前・keep_n範囲外・grace超過の旧世代が削除されなかった"
        "(GCが実際には何も消していない=dry-runのまま、の疑い)"
    )
    assert not os.path.isfile(stale_marker)


def test_dev45_2b_wired_gc_respects_lock_even_if_old(tmp_path, monkeypatch):
    """負の対照の補強: keep_n範囲外・grace超過でも、構築中ロック
    (<fp12>.lock)がある世代は現行世代同様に守られる
    (「直前に始まった長時間変換がまさにその世代を読み込んでいる最中」への
    レース対策、disk_guard.py本文の設計どおり)。"""
    monkeypatch.delenv("D2P_SHARED_CACHE", raising=False)

    work_root = str(tmp_path / "work")
    shared_cache_root = os.path.join(work_root, "_shared_cache")
    now = time.time()
    day = 24 * 60 * 60

    _make_generation(shared_cache_root, "vanilla_full", "dddddddddddd", now)
    _make_generation(shared_cache_root, "vanilla_full", "eeeeeeeeeeee", now - day)
    locked_dir, _locked_marker = _make_generation(
        shared_cache_root, "vanilla_full", "ffffffffffff", now - 3 * day
    )
    lock_path = locked_dir.rstrip("\\/") + ".lock"
    with open(lock_path, "w", encoding="utf-8") as f:
        f.write("")

    warm_startup._run_shared_cache_gc_after_warm(_REPO_ROOT, work_root)

    assert os.path.isdir(locked_dir), "構築中ロックのある世代が削除された(致命的)"


def test_dev45_2c_gc_hook_still_runs_when_devtools_absent(tmp_path):
    """dev#45b(2026-08-02、WP wp_45b_followup)で書き換えた唯一のテスト
    (本ファイル冒頭の追記コメント参照)。

    旧assertionは「app_root配下にdevtools\\が無ければGCがスキップされる」
    こと自体を正としていたが、これは配布版でGCが常にスキップされる
    バグそのものだった(devtools\\は配布zipに同梱されないため)。本WPは
    GC本体を app_py\\shared_cache_gc.py へ移設し、warm_startup.pyがそれを
    app_root非依存の通常import(app_py\\の兄弟モジュール)で直接呼ぶよう
    修正した——つまり app_root にdevtools\\が無くても(=配布版相当でも)
    GCは実際に実行されるようになった、というのが本WPの主目的そのもの。

    ここでは「devtools\\が無い状態でも、GCが実際に(work_root配下の
    _shared_cacheを見に行く形で)実行される」ことを確認する。世代を1つも
    作っていないtmp_path配下では「ディレクトリ無し、スキップ」という
    gc_shared_cache()自身の通常ログが出るだけで、旧来の
    「warm-cache-gc: skip (devtools not present, packaged build)」
    (=呼び出し自体を諦めるメッセージ)は二度と出ない。"""
    app_root = str(tmp_path)  # devtoolsディレクトリを作らない(配布版相当)
    work_root = str(tmp_path / "work")

    warm_startup._run_shared_cache_gc_after_warm(app_root, work_root)

    log = _read(work_root, "warm_startup.log")
    assert "warm-cache-gc: skip (devtools not present, packaged build)" not in log, (
        "devtools不在を理由に呼び出し自体を諦める旧(バグ)経路が復活している"
    )
    assert "shared_cache pruning: directory missing, skipping" in log, (
        "GCフック自体が実際には呼ばれていない(devtools不在でもGCが実行される、"
        "という本WPの主目的が満たされていない)"
    )


def test_dev45b_gc_hook_actually_deletes_stale_generation_when_devtools_absent(
    tmp_path, monkeypatch
):
    """test_dev45_2cの補強(dev#45b新規): 「ログにそれらしい文言が出た」
    だけでなく、devtools\\が無い状態でも実際に旧世代が削除される
    (=dry-runのまま何もしていないだけの偽陽性ではない)ことまで確認する。
    test_dev45_2/2bと同じ3世代構図(keep_n既定2件を超えた3世代目だけが
    削除対象になる)だが、app_root にリポジトリ(_REPO_ROOT)ではなく
    devtools\\を含まない tmp_path を渡す点が異なる——app_root の値に
    GCの実行が左右されなくなったことの直接証拠になる。"""
    monkeypatch.delenv("D2P_SHARED_CACHE", raising=False)

    app_root = str(tmp_path)  # devtoolsディレクトリを作らない(配布版相当)
    work_root = str(tmp_path / "work")
    shared_cache_root = os.path.join(work_root, "_shared_cache")
    now = time.time()
    day = 24 * 60 * 60

    current_dir, current_marker = _make_generation(
        shared_cache_root, "live_template", "111111111111", now
    )
    margin_dir, _margin_marker = _make_generation(
        shared_cache_root, "live_template", "222222222222", now - day
    )
    stale_dir, stale_marker = _make_generation(
        shared_cache_root, "live_template", "333333333333", now - 2 * day
    )

    warm_startup._run_shared_cache_gc_after_warm(app_root, work_root)

    assert os.path.isdir(current_dir), "現行世代が削除された(致命的)"
    assert os.path.isfile(current_marker)
    assert os.path.isdir(margin_dir), "安全マージン世代(2番目に新しい)が削除された"
    assert not os.path.isdir(stale_dir), (
        "devtools不在(配布版相当)でも旧世代が実際に削除されるはず"
        "(app_root非依存でGCが実行されることの直接証拠)"
    )
    assert not os.path.isfile(stale_marker)


# ---------------------------------------------------------------------------
# WarmCacheStatus 状態オブジェクト単体(tkinter非依存)
# ---------------------------------------------------------------------------


def test_dev45_status_object_state_machine():
    status = warm_startup.WarmCacheStatus()
    assert status.is_pending() is False
    assert status.is_incomplete() is True  # 未開始も「未完」扱い

    status.mark_started()
    assert status.is_pending() is True
    assert status.is_incomplete() is True

    status.mark_done(0)
    assert status.is_pending() is False
    assert status.is_incomplete() is False
    assert status.exit_code == 0


def test_dev45_status_object_mark_done_after_failure_clears_pending():
    """popen失敗等でexit_code=Noneのまま完了扱いにするケース
    (warm_shared_cache_on_startupの例外ハンドラが呼ぶ経路)。"""
    status = warm_startup.WarmCacheStatus()
    status.mark_started()
    status.mark_done(None)
    assert status.is_pending() is False
    assert status.is_incomplete() is False
    assert status.exit_code is None


# ---------------------------------------------------------------------------
# ② GUI状態遷移(tk窓を開かない、フェイクself経由)
# ---------------------------------------------------------------------------


class _FakeRootForWarmPoll:
    """root.after()相当の最小フェイク。ポーリングの再スケジュールは
    テストでは不要(1回呼んで結果だけ見る)なので記録だけして実行しない。"""

    def __init__(self) -> None:
        self.after_calls: List[tuple] = []

    def after(self, delay_ms: int, fn: Callable[[], None]) -> None:
        self.after_calls.append((delay_ms, fn))


class _FakeSelfForWarmPoll:
    """MainWindow._poll_warm_cache_status/_set_statusを束縛せずに呼ぶための
    最小self(test_button_gates.pyの「フェイクself + 束縛前メソッド呼び出し」
    方式を踏襲)。"""

    _poll_warm_cache_status = mw.MainWindow._poll_warm_cache_status

    def __init__(self, status: warm_startup.WarmCacheStatus, initial_text: str = "PREVIOUS") -> None:
        self._warm_cache_status = status
        self._warm_cache_status_pending_last = False
        self._status_before_warm_cache: Optional[Callable[[], str]] = None
        self._last_status_render: Optional[Callable[[], str]] = lambda: initial_text
        self.root = _FakeRootForWarmPoll()
        self.status_label_history: List[str] = []

    def _set_status(self, render: Callable[[], str]) -> None:
        self._last_status_render = render
        self.status_label_history.append(render())


def test_dev45_3_poll_shows_preparing_status_while_pending():
    status = warm_startup.WarmCacheStatus()
    fake = _FakeSelfForWarmPoll(status)

    # 未開始の間は何も変化しない(エッジ検出、既に「準備中」でないので
    # _set_status()を呼ばない)。
    mw.MainWindow._poll_warm_cache_status(fake)
    assert fake.status_label_history == []

    status.mark_started()
    mw.MainWindow._poll_warm_cache_status(fake)
    assert fake.status_label_history == [i18n.S("StatusWarmCachePreparing")]

    # pending状態のまま2回目のポーリングをしても、エッジ検出により
    # 再度_set_status()は呼ばれない(状態が変化していないため)。
    mw.MainWindow._poll_warm_cache_status(fake)
    assert fake.status_label_history == [i18n.S("StatusWarmCachePreparing")]


def test_dev45_3_poll_restores_previous_status_on_completion():
    status = warm_startup.WarmCacheStatus()
    fake = _FakeSelfForWarmPoll(status, initial_text="StatusPromptVrm的な何か")

    status.mark_started()
    mw.MainWindow._poll_warm_cache_status(fake)  # -> 「準備中」表示、PREVIOUSを退避

    status.mark_done(0)
    mw.MainWindow._poll_warm_cache_status(fake)  # -> 完了、退避した文言へ復元(消える)

    assert fake.status_label_history == [
        i18n.S("StatusWarmCachePreparing"),
        "StatusPromptVrm的な何か",
    ]
    assert fake._status_before_warm_cache is None  # 復元後は退避を手放す


def test_dev45_3_poll_never_shown_when_warm_cache_completes_without_ever_pending():
    """warm_shared_cache_on_startup()自身がガードでskipし、一度も
    mark_started()が呼ばれないまま(=is_pending()が常にFalse)のケース。
    「準備中」表示が一度も出ない(=出しようがないので消しようもない)ことを
    確認する——mark_done()も呼ばれていないためis_incomplete()はTrueのまま
    (①③のfirst-run notice側の対象にはなり得る、②の表示だけは出ない)。"""
    status = warm_startup.WarmCacheStatus()
    fake = _FakeSelfForWarmPoll(status)

    for _ in range(3):
        mw.MainWindow._poll_warm_cache_status(fake)

    assert fake.status_label_history == []
    assert status.is_incomplete() is True


# ---------------------------------------------------------------------------
# ② 変換開始時の「初回準備のため数分かかります」相当(ログ欄経由)
# ---------------------------------------------------------------------------


class _FakeSelfForWarmNotice:
    _maybe_log_warm_cache_first_run_notice = mw.MainWindow._maybe_log_warm_cache_first_run_notice

    def __init__(self, status: warm_startup.WarmCacheStatus) -> None:
        self._warm_cache_status = status
        self.logged: List[str] = []

    def _log(self, text: str) -> None:
        self.logged.append(text)


def test_dev45_first_run_notice_logged_when_warm_cache_incomplete():
    status = warm_startup.WarmCacheStatus()  # 未開始 = is_incomplete()=True
    fake = _FakeSelfForWarmNotice(status)

    mw.MainWindow._maybe_log_warm_cache_first_run_notice(fake)

    assert len(fake.logged) == 1
    assert i18n.S("StatusWarmCacheFirstRunNotice", lang="en") in fake.logged[0]


def test_dev45_first_run_notice_not_logged_when_warm_cache_complete():
    status = warm_startup.WarmCacheStatus()
    status.mark_started()
    status.mark_done(0)
    fake = _FakeSelfForWarmNotice(status)

    mw.MainWindow._maybe_log_warm_cache_first_run_notice(fake)

    assert fake.logged == []


def test_dev45_first_run_notice_uses_english_forced_lang_for_log_panel():
    """診断ログはUI言語に追従しない既定方針(dev#596/#897、
    test_log_i18n_dev596.pyが静的スキャンで強制)を守っていること。
    UI言語をjaに切り替えても、ログへ出す文言はlang="en"固定のままである
    ことを直接確認する(静的スキャンの意図を動的にも裏取りする)。"""
    prev_lang = i18n.current_lang
    try:
        i18n.set_language("ja")
        status = warm_startup.WarmCacheStatus()
        fake = _FakeSelfForWarmNotice(status)
        mw.MainWindow._maybe_log_warm_cache_first_run_notice(fake)
        assert len(fake.logged) == 1
        assert fake.logged[0] == (
            f"[warm_startup] {i18n.S('StatusWarmCacheFirstRunNotice', lang='en')}"
        )
        # 未知キーの場合は "??key??" プレースホルダなので、jaとenで文言が
        # 一致してしまい得る(意図しない偽陽性回避のため、キーが将来追加
        # された前提でも崩れないよう、lang="en"呼び出しの結果と一致する
        # ことだけを主張する。ja文言との非一致までは主張しない)。
    finally:
        i18n.set_language(prev_lang)


# ---------------------------------------------------------------------------
# dev#45b新規(WP wp_45b_followup): i18n辞書キーが実在し "??key??" を
# 返さないことの直接証明(穴1: 先行WPはi18n_data.jsonへ書き込み許可が無く、
# コード側からキーを参照するだけで辞書登録していなかった)。
# ---------------------------------------------------------------------------

_DEV45B_I18N_KEYS = ("StatusWarmCachePreparing", "StatusWarmCacheFirstRunNotice")
_DEV45B_I18N_LANGS = ("ja", "en", "ko", "zhTW", "zhCN")


def test_dev45b_new_i18n_keys_resolve_to_real_text_not_placeholder():
    """受入ゲート2: 新規2キーについて、5言語すべてで i18n.S(key) が
    "??key??" プレースホルダ(i18n.py::Sの未知キー時の戻り値)を返さない
    ことを直接確認する。既存のtest_dev45_3_*/test_dev45_first_run_notice_*
    は`i18n.S(...)`の戻り値どうしを比較するだけの自己参照的な検証で、
    キーが辞書に存在しなくても(両辺とも"??key??"になり)偽陽性で緑に
    なり得た。本テストは実際の文字列を見て判定するため、その穴を塞ぐ。"""
    for key in _DEV45B_I18N_KEYS:
        for lang in _DEV45B_I18N_LANGS:
            text = i18n.S(key, lang=lang)
            assert text != f"??{key}??", (
                f"{key}/{lang}: i18n_data.jsonにキーが登録されておらず"
                f"プレースホルダが表示される: {text!r}"
            )
            assert text, f"{key}/{lang}: 空文字列が返された"


def test_dev45b_i18n_placeholder_check_catches_missing_key():
    """負の対照(必須): 実際に未登録のキーを渡すと、上と同じ判定ロジックが
    プレースホルダを検出できることの証明(検査自体が空振りでないこと)。"""
    text = i18n.S("__dev45b_no_such_key__", lang="en")
    assert text == "??__dev45b_no_such_key__??"


# ---------------------------------------------------------------------------
# dev#45b新規(WP wp_45b_followup): GCモジュールが配布zipの同梱対象に
# 入ることの機械的証明(受入ゲート3、穴2)。app_py\build.py::
# _copy_app_sources()はネットワークアクセスを行わずapp_py\の実ファイルを
# tmp_path配下へコピーするだけなので、ここで直接呼んで検査できる。
# ---------------------------------------------------------------------------


def test_dev45b_shared_cache_gc_module_is_included_in_dist_payload(tmp_path):
    """移設後: app_py\\shared_cache_gc.py が実際に配布物(res\\app\\配下)へ
    コピーされることを確認する(「移設した」だけでなく「同梱されている」
    ところまで機械判定する、受入ゲート3)。"""
    import build  # noqa: PLC0415 -- このテストだけで使う重い依存(hashlib等)を遅延import

    res_dir = tmp_path / "res"
    res_dir.mkdir()
    build._copy_app_sources(res_dir, fixture=False)

    assert (res_dir / "app" / "shared_cache_gc.py").is_file(), (
        "shared_cache_gc.py が配布物(res\\app\\配下)に含まれていない"
        "(GC本体を配布zipへ同梱する、という本WPの目的が達成されていない)"
    )


def test_dev45b_devtools_dir_is_never_part_of_dist_payload(tmp_path):
    """負の対照(必須・穴が実在した証明): devtools\\ディレクトリ自体は
    配布物の組み立て過程で一度もコピーされない(app_py\\build.pyの
    コピー対象はapp_py\\/pipeline\\/unity\\のみ)。これは「移設前、GCの
    実体がdevtools\\disk_guard.pyにしか無かった間は、配布物にGCロジックが
    一切含まれていなかった」ことの直接証拠になる——本WPが移設した理由
    そのもの。"""
    import build  # noqa: PLC0415

    res_dir = tmp_path / "res"
    res_dir.mkdir()
    build._copy_app_sources(res_dir, fixture=False)
    build._copy_pipeline_and_unity(res_dir, fixture=False)

    assert not (res_dir / "devtools").exists(), (
        "devtools\\が配布物へ含まれるようになっている(想定外の変更。"
        "devtools\\に置いたままではGCが配布版で動かない、という穴の前提が崩れている)"
    )
