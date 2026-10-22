# test_main_window_work_root_wiring.py -- dev#23監査の回帰試験。
#
# 発見した欠落: main_window.MainWindow は __init__ で
# self.work_root = self._resolve_work_root() を呼び、appRoot\work が書き込み
# 不可な環境(例: Program Filesへのインストール)では %LOCALAPPDATA%\Uchinoko\work
# へ自動フォールバックする(CLAUDE.md「外部依存パスの原則」の①②、
# path_health.resolve_work_root 相当、dev#621/WP-A6)。
#
# ところが pak一覧更新(_on_refresh_pak_list)・完成pak特定
# (_resolve_completed_pak_path)・削除対象解決(_on_delete_selected 内の
# resolve_delete_targets呼び出し)・warm startup(_warm_startup_after_blender_ready)
# の4箇所は、self.work_root ではなく別メソッド _work_root()(WP-A6着手前の
# 暫定スタブ、常に os.path.join(app_root, "work") を返すだけ)を呼んでいた。
# フォールバックが実際に発動した環境では、変換ジョブは self.work_root
# (フォールバック先)配下に書かれるのに、pak一覧/削除/warm startupは常に
# appRoot\work だけを見るため、ビルド済みpakが一覧に出ない・削除できない、
# という「解決済みのはずの手動/自動フォールバックが一部経路だけ迂回される」
# 欠落だった(dev#229と同型: 設定はあるのに一部の呼び出し元だけ無効化される
# パターン)。
#
# 本試験は _work_root() スタブを復元せず、self.work_root を直接使う現在の
# 実装が「app_root\work には無く、work_root(フォールバック想定)にだけ
# ビルド済み成果物がある」状況でも正しく見つけられることを示す(正の対照)。
# 併せて、app_root\work だけに紛れ込んだ成果物が誤って拾われない(=
# self.work_root 以外を見ていない)ことも確認する(負の対照: 実装を
# `os.path.join(self.app_root, "work")` に戻すと最初のテストが即座に落ちる)。
#
# 実tkウィンドウは一切開かない(test_guard_dialogs.py と同じ流儀:
# mw.MainWindow.__new__(mw.MainWindow) でフェイクselfを作り、必要な属性だけ
# 後付けする。messagebox は monkeypatch で置き換え、実ダイアログを出さない)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pak_manager  # noqa: E402
from ui import main_window as mw  # noqa: E402


def _bare_window() -> mw.MainWindow:
    """__init__を通さずMainWindowインスタンスだけ得る(test_guard_dialogs.pyと
    同じ手筋)。テストごとに必要な属性だけ後付けする。"""
    return mw.MainWindow.__new__(mw.MainWindow)


class _FakePakList:
    """ttk.Treeview互換の最小フェイク(_on_refresh_pak_list/_on_delete_selectedが
    使う範囲のみ: delete/get_children/insert/selection/item)。"""

    def __init__(self, selected_iid: str | None = None, values_by_iid: dict | None = None) -> None:
        self._items: list[str] = []
        self._selected_iid = selected_iid
        self._values_by_iid = values_by_iid or {}

    def get_children(self):
        return tuple(self._items)

    def delete(self, *_iids) -> None:
        self._items = []

    def insert(self, _parent, _index, values=()):
        iid = f"iid{len(self._items)}"
        self._items.append(iid)
        self._values_by_iid[iid] = values
        return iid

    def selection(self):
        return [self._selected_iid] if self._selected_iid else []

    def item(self, iid, key):
        assert key == "values"
        return self._values_by_iid[iid]


def _make_built_pak(work_root: str, avatar_name: str) -> str:
    """pak_manager.list_built_paks()が拾う形(<work_root>\\<avatar>\\build\\
    <name>_PlayerSwap_P.pak)で最小限のビルド成果物を作る。"""
    build_dir = os.path.join(work_root, avatar_name, "build")
    os.makedirs(build_dir, exist_ok=True)
    pak_path = os.path.join(build_dir, f"{avatar_name}_PlayerSwap_P.pak")
    with open(pak_path, "wb") as f:
        f.write(b"stub")
    return pak_path


# ---------------------------------------------------------------------------
# _resolve_completed_pak_path: self.work_root が app_root\work と異なる
# (フォールバック発動)状況でも正しく見つけられること
# ---------------------------------------------------------------------------


def test_resolve_completed_pak_path_finds_pak_under_active_fallback_work_root(tmp_path):
    app_root = str(tmp_path / "app")
    fallback_work_root = str(tmp_path / "fallback_work")  # app_root\work とは別物
    os.makedirs(app_root, exist_ok=True)

    real_pak = _make_built_pak(fallback_work_root, "RealAvatar")

    fake = _bare_window()
    fake.app_root = app_root
    fake.work_root = fallback_work_root  # __init__のself.work_root相当

    job_dir = os.path.join(fallback_work_root, "RealAvatar")
    result = mw.MainWindow._resolve_completed_pak_path(fake, job_dir)

    assert result == real_pak


def test_resolve_completed_pak_path_negative_control_ignores_app_root_work(tmp_path):
    """負の対照: 同名アバターのビルド成果物が app_root\\work 側にしか無ければ
    (self.work_root=フォールバック側には無い)、見つからずNoneになること。
    もし実装が self.work_root ではなく os.path.join(app_root, "work") を
    見るよう退行すれば、このテストは失敗せずにpakを"見つけてしまう"側に
    倒れる。対になる上のテスト(app_root\\work には何も無い)と合わせて、
    「self.work_root だけを見ている」ことを両方向から締める。"""
    app_root = str(tmp_path / "app")
    fallback_work_root = str(tmp_path / "fallback_work")
    os.makedirs(fallback_work_root, exist_ok=True)

    # app_root\work 側にだけ同名の成果物を紛れ込ませる(退行時に拾われる餌)
    _make_built_pak(os.path.join(app_root, "work"), "RealAvatar")

    fake = _bare_window()
    fake.app_root = app_root
    fake.work_root = fallback_work_root

    job_dir = os.path.join(fallback_work_root, "RealAvatar")
    result = mw.MainWindow._resolve_completed_pak_path(fake, job_dir)

    assert result is None


# ---------------------------------------------------------------------------
# _on_refresh_pak_list: pak一覧が self.work_root から作られること
# ---------------------------------------------------------------------------


def test_on_refresh_pak_list_lists_paks_from_active_fallback_work_root(tmp_path):
    app_root = str(tmp_path / "app")
    fallback_work_root = str(tmp_path / "fallback_work")
    os.makedirs(app_root, exist_ok=True)
    real_pak = _make_built_pak(fallback_work_root, "RealAvatar")

    fake = _bare_window()
    fake.app_root = app_root
    fake.work_root = fallback_work_root
    fake.widgets = {"pakList": _FakePakList()}
    fake._pak_paths = {}
    fake._pak_candidates = []
    # _on_update_applied_status()相当は本試験の対象外(pak一覧の出所だけを見る)。
    # 実PalworldのSteam探索に触れないよう、no-opへ差し替える。
    fake._on_update_applied_status = lambda: None

    mw.MainWindow._on_refresh_pak_list(fake)

    assert fake._pak_candidates == [(real_pak, "RealAvatar")]
    assert list(fake._pak_paths.values()) == [real_pak]


# ---------------------------------------------------------------------------
# _on_delete_selected: 削除対象の解決(pak_manager.resolve_delete_targets)に
# 渡す work_root が self.work_root であること(実削除は行わせない)
# ---------------------------------------------------------------------------


def test_on_delete_selected_resolves_targets_against_active_fallback_work_root(monkeypatch, tmp_path):
    app_root = str(tmp_path / "app")
    fallback_work_root = str(tmp_path / "fallback_work")
    os.makedirs(app_root, exist_ok=True)
    os.makedirs(fallback_work_root, exist_ok=True)
    pak_path = os.path.join(fallback_work_root, "RealAvatar", "build", "RealAvatar_PlayerSwap_P.pak")

    fake = _bare_window()
    fake.app_root = app_root
    fake.work_root = fallback_work_root
    fake.widgets = {
        "pakList": _FakePakList(
            selected_iid="iid0",
            values_by_iid={"iid0": ("RealAvatar", "RealAvatar_PlayerSwap_P.pak", "0.0 MB", "")},
        )
    }
    fake._pak_paths = {"iid0": pak_path}

    captured_args: list[tuple] = []
    real_resolve = pak_manager.resolve_delete_targets

    def _spy_resolve_delete_targets(work_root, app_root_arg, pak_path_arg):
        captured_args.append((work_root, app_root_arg, pak_path_arg))
        return real_resolve(work_root, app_root_arg, pak_path_arg)

    monkeypatch.setattr(mw.pak_manager, "resolve_delete_targets", _spy_resolve_delete_targets)
    # 確認ダイアログはNoを返すことで、以降の実削除(delete_avatar_artifacts)へ
    # 進ませない(実tk窓は一切開かない、既存test_guard_dialogs.pyと同じ流儀)。
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a: False)

    mw.MainWindow._on_delete_selected(fake)

    assert captured_args == [(fallback_work_root, app_root, pak_path)]
