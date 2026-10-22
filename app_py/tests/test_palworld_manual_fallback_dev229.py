# test_palworld_manual_fallback_dev229.py -- dev#229続報(2026-08-07 第2次問い合わせ
# 掃引、実報告5件: D522GGSF/GMLCCCDJ/MPQBWHXS/KRFU5DVL/KTU5A3BQ)。
#
# 症状: これら5件はいずれも「既定Steamパス以外の環境でPalworld本体パスの自動発見に
# 失敗し、手動指定への誘導が一切無いまま、変換開始のたびに同一の
# PalworldNotFoundError(Phase 0: バニラ参照データ準備)で落ちる」という同型だった。
#
# 原因(コード確認済み): CLAUDE.md「外部依存パスの原則」の三点セット
# (①自動発見→②失敗時の手動指定UI+設定保存→③探索ログ)自体は
# pak_manager.resolve_paks_dir()に既に実装済みで、Apply/Remove(既存の
# _resolve_paks_dir_interactive())には正しく配線されていた。しかし「変換開始」
# (Start Conversion/materials/preview全ボタン共通の_start_pipeline())だけは
# ダイアログを出さない静かな版(pipeline_runner.write_job()内部のpaks_dir_quiet())
# しか呼んでおらず、自動発見が失敗すると手動指定の機会を一度も与えられないまま
# job.jsonへpaths.palworld_pakが省略され、Phase 0がFATALで落ちていた。
#
# 修理: main_window.py に _ensure_palworld_located() を新設し、_start_pipeline()
# 冒頭(auto=False時のみ、_ensure_license_confirmed()と同じ位置づけ)で呼ぶ。
# 中身は既存の_resolve_paks_dir_interactive()(Apply/Removeと完全共用)を
# そのまま再利用するだけ(二重実装しない、新規GUI部品も追加しない)。
#
# 方針(共通契約どおり、tkの実ウィンドウは一切開かない):
# test_button_gates.py/test_preview_freshness.pyと同じ「フェイクself+束縛前
# メソッド呼び出し」方式。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import main_window as mw  # noqa: E402


# ---------------------------------------------------------------------------
# _ensure_palworld_located() 単体(_resolve_paks_dir_interactive()への委譲)
# ---------------------------------------------------------------------------


class _FakeSelfForEnsurePalworldLocated:
    """_ensure_palworld_located()は_resolve_paks_dir_interactive()の戻り値
    (str|None)をbool化して返すだけの薄い関数のため、フェイクselfは
    その1メソッドだけを持てば足りる。"""

    def __init__(self, resolved_dir: str | None) -> None:
        self._resolved_dir = resolved_dir
        self.calls = 0

    def _resolve_paks_dir_interactive(self) -> str | None:
        self.calls += 1
        return self._resolved_dir


def test_ensure_palworld_located_true_when_resolved():
    fake_self = _FakeSelfForEnsurePalworldLocated(resolved_dir=r"D:\steam\steamapps\common\Palworld\Pal\Content\Paks")
    assert mw.MainWindow._ensure_palworld_located(fake_self) is True
    assert fake_self.calls == 1


def test_ensure_palworld_located_false_when_unresolved():
    # 負の対照: 自動発見も手動指定キャンセルも失敗(_resolve_paks_dir_interactive()
    # がNoneを返す = D522GGSF等5件が実際に踏んだ状態)なら False。
    fake_self = _FakeSelfForEnsurePalworldLocated(resolved_dir=None)
    assert mw.MainWindow._ensure_palworld_located(fake_self) is False
    assert fake_self.calls == 1


def test_ensure_palworld_located_delegates_to_shared_apply_remove_resolver():
    # _ensure_palworld_located()が独自の探索ロジックを持たず、Apply/Removeと
    # 完全に同じ_resolve_paks_dir_interactive()を呼んでいることの確認
    # (二重実装していないことの検証)。
    import inspect

    body = mw.MainWindow._ensure_palworld_located.__code__
    # docstring(ソース文字列全体)ではなくバイトコードの外部参照名だけを見る
    # (docstring中の説明文に"pak_manager"という単語が出るのは問題ないため)。
    assert "_resolve_paks_dir_interactive" in body.co_names
    assert "pak_manager" not in body.co_names, (
        "pak_managerを直接呼び出して独自解決を始めていないか"
        "(_resolve_paks_dir_interactive()経由の共用を維持すること)"
    )
    src = inspect.getsource(mw.MainWindow._ensure_palworld_located)
    assert "_resolve_paks_dir_interactive" in src


# ---------------------------------------------------------------------------
# _start_pipeline()への配線(「実装した」と「効いている」は別、CLAUDE.md方針の
# とおり実際にパイプライン起動をブロックすることまで確認する)
# ---------------------------------------------------------------------------


class _FakeEntry:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def get(self) -> str:
        return self._text


class _FakeRoot:
    def __init__(self) -> None:
        self.after_calls: list[tuple] = []

    def after(self, ms, fn) -> None:
        self.after_calls.append((ms, fn))


class _FakeSelfForStartPipeline:
    """_start_pipeline()を素通りさせるための最小フェイクself。
    pipeline_runner.run_pipeline()自体はmw.pipeline_runnerをmonkeypatchして
    差し替える(実プロセスは一切起動しない)。"""

    _start_pipeline = mw.MainWindow._start_pipeline
    _ensure_license_confirmed = mw.MainWindow._ensure_license_confirmed

    def __init__(self, *, vrm_path: str, palworld_located: bool) -> None:
        self._active_handle = None
        self._license_confirmed = True
        self._palworld_located = palworld_located
        self._palworld_located_calls = 0
        self.widgets = {
            "vrmBox": _FakeEntry(vrm_path),
            "dropBonesBox": _FakeEntry(""),
            "shadowBar": _FakeEntry("30"),
            "heightScaleBar": _FakeEntry("100"),  # dev#560 第③段
            # dev#1572(2026-08-18裁定、案C): 「揺れの度合い」4択の復元に伴い
            # widgets["swayIntensityBar"]相当の最小フェイクを復活(tk.Scaleの
            # `.get()`だけを模す。index 2="normal"、dev#19プロトタイプ時代の
            # `_FakeEntry("0")`と同じ「tk.Entry互換の.get()が文字列を返す」
            # パターンを踏襲)。
            "swayIntensityBar": _FakeEntry("2"),
        }
        self.app_root = "dummy_app_root"
        self.work_root = "dummy_work_root"
        self._shoulder_offset_deg = 0
        self._merge_fingers = False
        self._unlit = False
        self._force_two_sided = True
        self.root = _FakeRoot()
        self._POLL_INTERVAL_MS = 80

    def _ensure_palworld_located(self) -> bool:
        self._palworld_located_calls += 1
        return self._palworld_located

    def _clear_log(self) -> None:
        pass

    def _log(self, _text: str, *, gui: bool = True) -> None:
        # dev#1242申し送り②: _start_pipeline()がpipeline_runner.run_pipeline()へ
        # log=self._logを渡すようになったため、フェイクselfにも同名メソッドが
        # 要る(実際の描画はしない、素通りテストのため)。
        pass

    def _set_running_ui_state(self, _running: bool) -> None:
        pass

    def _set_status(self, _fn) -> None:
        pass

    def _maybe_log_warm_cache_first_run_notice(self) -> None:
        pass

    def _on_pipeline_line(self, _line: str) -> None:
        pass

    def _on_pipeline_exit(self, _code: int, _preview_only: bool) -> None:
        pass

    def _poll_active_handle(self) -> None:
        pass


def test_start_pipeline_blocks_when_palworld_unresolved(tmp_path, monkeypatch):
    """本丸(受入条件): _ensure_palworld_located()がFalseを返す(=手動指定を
    キャンセルした/そもそも見つからなかった)場合、_start_pipeline()は
    pipeline_runner.run_pipeline()を一切呼ばずに中断する
    (job.json書き出し・Phase 0行きの子プロセス起動が発生しない)。"""
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")

    run_calls = []
    monkeypatch.setattr(
        mw.pipeline_runner, "run_pipeline",
        lambda *a, **k: run_calls.append((a, k)) or None,
    )

    fake_self = _FakeSelfForStartPipeline(vrm_path=str(vrm), palworld_located=False)
    mw.MainWindow._start_pipeline(fake_self, preview_only=False, materials_only=False)

    assert fake_self._palworld_located_calls == 1
    assert run_calls == [], "Palworld未解決なのにpipeline_runner.run_pipeline()が呼ばれた"
    assert fake_self._active_handle is None


def test_start_pipeline_proceeds_when_palworld_resolved(tmp_path, monkeypatch):
    """正の対照: _ensure_palworld_located()がTrueを返せば、従来どおり
    pipeline_runner.run_pipeline()が呼ばれる(新しいゲートが正常系を
    巻き込んで止めていないことの確認)。"""
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")

    run_calls = []

    class _FakeHandle:
        pass

    def _fake_run_pipeline(*a, **k):
        run_calls.append((a, k))
        return _FakeHandle()

    monkeypatch.setattr(mw.pipeline_runner, "run_pipeline", _fake_run_pipeline)

    fake_self = _FakeSelfForStartPipeline(vrm_path=str(vrm), palworld_located=True)
    mw.MainWindow._start_pipeline(fake_self, preview_only=False, materials_only=False)

    assert fake_self._palworld_located_calls == 1
    assert len(run_calls) == 1, "Palworld解決済みなのにpipeline_runner.run_pipeline()が呼ばれなかった"
    assert isinstance(fake_self._active_handle, _FakeHandle)


def test_start_pipeline_auto_mode_skips_palworld_dialog_gate(tmp_path, monkeypatch):
    """auto=True(dev#611のアバター登録時自動プレビュー)はダイアログを一切
    出さない既存方針(_ensure_license_confirmed同様)を、Palworld手動指定にも
    適用したことの確認: auto時は_ensure_palworld_located()自体を呼ばず、
    (未解決でも)そのままpipeline_runner.run_pipeline()まで進む
    (=既存のauto-preview挙動を変えない、という設計判断の実装)。"""
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")

    run_calls = []

    class _FakeHandle:
        pass

    monkeypatch.setattr(
        mw.pipeline_runner, "run_pipeline",
        lambda *a, **k: run_calls.append((a, k)) or _FakeHandle(),
    )

    fake_self = _FakeSelfForStartPipeline(vrm_path=str(vrm), palworld_located=False)
    mw.MainWindow._start_pipeline(
        fake_self, preview_only=True, materials_only=False, auto=True
    )

    assert fake_self._palworld_located_calls == 0, (
        "auto=Trueなのに_ensure_palworld_located()(ダイアログ経路)が呼ばれた"
    )
    assert len(run_calls) == 1


def test_start_pipeline_forwards_log_to_run_pipeline(tmp_path, monkeypatch):
    """dev#1242申し送り②: pipeline_runner.run_pipeline()へself._logがlog=
    として渡されること(find_pwsh()の探索ログが実GUI経路で失われないことの
    直接検査。test_prefab_gui_cache.pyのUnity輸出側と対になる検査)。"""
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")

    captured_kwargs = {}

    class _FakeHandle:
        pass

    def _fake_run_pipeline(*a, **k):
        captured_kwargs.update(k)
        return _FakeHandle()

    monkeypatch.setattr(mw.pipeline_runner, "run_pipeline", _fake_run_pipeline)

    fake_self = _FakeSelfForStartPipeline(vrm_path=str(vrm), palworld_located=True)
    mw.MainWindow._start_pipeline(fake_self, preview_only=False, materials_only=False)

    # dev229既存フェイクselfの_logはクラスメソッド(束縛のたびに新しい
    # boundメソッドオブジェクトになるためisではなく==で同一性を確認する。
    # bound method の __eq__ は __self__/__func__ の一致で判定される)。
    assert captured_kwargs.get("log") == fake_self._log, (
        "run_pipeline()へfake_self._log(=main_window.pyのself._log)が"
        "そのまま渡されていない(結線漏れ)"
    )
    # 実際に呼べば例外にならないこと(no-opの検査、実描画はtest_blender_setup_
    # gui_log_wiring.py側で別途確認済み)。
    captured_kwargs["log"]("[blender_setup] dummy search line")
