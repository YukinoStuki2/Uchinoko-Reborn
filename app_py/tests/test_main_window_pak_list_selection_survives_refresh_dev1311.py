# test_main_window_pak_list_selection_survives_refresh_dev1311.py -- dev#1311
# 「作成済みMOD一覧」の行を選択できない(選択した瞬間に解除される)回帰の
# 単体試験。
#
# 原因(オーナー実機報告「fusion(マルチアバターPAK)が一覧に出るが選択
# できない」の調査結果、詳細はdev#1311本文参照):
#   1. 行クリック → <<TreeviewSelect>> → _on_pak_list_selected()
#      (app_py\ui\main_window.py) → _apply_restored_settings(job_dir, ...)
#   2. _apply_restored_settings() はjob.jsonがあれば毎回 _refresh_lab_warning()
#      を呼ぶ(dev#1186のラボ警告表示のため)
#   3. dev#1170のコミットcecbf70が _refresh_lab_warning() の末尾に
#      _on_refresh_pak_list() を追加していた(合成ダイアログclose後に一覧へ
#      反映させる目的だったが、行選択からも辿り着いてしまっていた)
#   4. _on_refresh_pak_list() は全行delete→再構築するため、行をクリックした
#      瞬間に選択が消える
#
# 修正: 一覧再読込を_refresh_lab_warning()からlab_window.pyのrefresh()
# (ダイアログ<Destroy>経由専用)へ移設(方式A)+_on_refresh_pak_list()自体に
# 選択復元の多重防御を追加(方式B)。
#
# 本ファイルは受入ゲート①「一覧の行を選択→選択イベントハンドラ一式が
# 走った後も選択が維持されている」を、通常品・マルチアバターPAK品の両方で
# 固定する。実際のクリック操作(_on_pak_list_selected)の呼び出し経路を
# そのまま辿る——実tkウィジェット(ttk.Treeview)を使い、job.json復元
# (_apply_restored_settings → _refresh_lab_warning)まで一気通貫で走らせる
# ことが本試験の要(モックで_refresh_lab_warningを差し替えると回帰を
# 再現できない)。
#
# 実tkウィンドウは一切表示しない(hidden_root共有フィクスチャ+
# _build_widgets()だけを束縛前のまま呼ぶ、既存のラボ試験群と同じ慣例)。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402


def _make_fake_self(root, app_root: str, work_root: str) -> mw.MainWindow:
    """_apply_restored_settings()/_apply_previews()が参照する属性一式
    (main_window.py __init__のL.461-496相当)を、__init__を経由せず
    手動で揃える。他のラボ試験群と同じくMainWindow.__new__ +
    _build_widgets()の慣例(実tkウィジェットは使うが実MainWindowの
    起動シーケンス全体は通さない)。"""
    self = mw.MainWindow.__new__(mw.MainWindow)
    self.root = root
    self.app_root = app_root
    self.work_root = work_root
    self.widgets = {}
    self._tooltips = []
    self._pak_paths: dict[str, str] = {}
    self._pak_candidates = []
    self._on_update_applied_status = lambda: None
    # __init__のL.461-496相当(_apply_restored_settings/_apply_previewsが
    # 読み書きする内部状態)。
    self._shoulder_offset_deg = 0
    self._merge_fingers = False
    self._unlit = False
    self._force_two_sided = True
    self._license_confirmed = False
    self._preview_images = {}
    return self


def _make_built_pak_with_job(work_root: str, avatar_name: str, *, multi_avatar: bool) -> str:
    """pak_manager.list_built_paks()が拾う形のビルド成果物+
    _apply_restored_settings()が反応できる最小job.jsonを用意する。
    multi_avatar=Trueならjob_dir/library/manifest.jsonにmulti_avatar:true
    マニフェストも足す(vp_avatar_compose.compose()が書く場所と同じ規約、
    test_main_window_pak_list_multi_avatar_mark_dev1170.pyと同じ手筋)。"""
    job_dir = os.path.join(work_root, avatar_name)
    build_dir = os.path.join(job_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    pak_path = os.path.join(build_dir, f"{avatar_name}_PlayerSwap_P.pak")
    with open(pak_path, "wb") as f:
        f.write(b"stub")
    with open(os.path.join(job_dir, "job.json"), "w", encoding="utf-8") as f:
        json.dump({"avatar_name": avatar_name}, f)
    if multi_avatar:
        lib_dir = os.path.join(job_dir, "library")
        os.makedirs(lib_dir, exist_ok=True)
        with open(os.path.join(lib_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"format_version": 1, "multi_avatar": True}, f)
    return pak_path


def _select_row_and_fire_handler(self: mw.MainWindow, iid: str) -> None:
    """実際のユーザー操作(行クリック)を模す: Treeviewへ選択をセットし、
    <<TreeviewSelect>>ハンドラ本体(_on_pak_list_selected)を直接呼ぶ
    (実tk環境が無いテストでも同じイベントハンドラ本体を確実に通すため、
    イベント発火そのものではなくbind先の関数を直接呼ぶ既存の流儀に
    合わせる)。"""
    pak_list = self.widgets["pakList"]
    pak_list.selection_set(iid)
    mw.MainWindow._on_pak_list_selected(self)


# ---------------------------------------------------------------------------
# 正: 選択イベントハンドラ一式(_on_pak_list_selected →
# _apply_restored_settings → _refresh_lab_warning)が走った後も選択が
# 維持されていること
# ---------------------------------------------------------------------------


def test_selection_survives_select_handler_for_normal_entry(hidden_root, tmp_path):
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        work_root = str(tmp_path / "work")
        app_root = str(tmp_path / "app_root")
        os.makedirs(app_root, exist_ok=True)
        self = _make_fake_self(hidden_root, app_root, work_root)
        mw.MainWindow._build_widgets(self)

        _make_built_pak_with_job(work_root, "NormalAvatar", multi_avatar=False)
        mw.MainWindow._on_refresh_pak_list(self)

        pak_list = self.widgets["pakList"]
        (iid,) = pak_list.get_children()

        _select_row_and_fire_handler(self, iid)

        assert pak_list.selection() == (iid,), (
            "選択イベントハンドラの実行後に選択が解除された"
            "(_refresh_lab_warning経由でpakListが再構築され選択が消える回帰)"
        )
    finally:
        i18n.clear_registry()


def test_selection_survives_select_handler_for_multi_avatar_entry(hidden_root, tmp_path):
    """fusion相当(multi_avatar:trueのエントリ)でも同様に選択が消えないこと
    (オーナー実機報告そのものの再現条件)。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        work_root = str(tmp_path / "work")
        app_root = str(tmp_path / "app_root")
        os.makedirs(app_root, exist_ok=True)
        self = _make_fake_self(hidden_root, app_root, work_root)
        mw.MainWindow._build_widgets(self)

        _make_built_pak_with_job(work_root, "fusion", multi_avatar=True)
        mw.MainWindow._on_refresh_pak_list(self)

        pak_list = self.widgets["pakList"]
        (iid,) = pak_list.get_children()
        # マルチ品の目印が付いていること自体も確認しておく(退行時にこの
        # 前提が崩れていないかの副次確認)。
        assert pak_list.item(iid, "values")[0] != "fusion"

        _select_row_and_fire_handler(self, iid)

        assert pak_list.selection() == (iid,), (
            "マルチアバターPAKエントリで選択イベントハンドラ実行後に選択が"
            "解除された"
        )
    finally:
        i18n.clear_registry()


# ---------------------------------------------------------------------------
# 負の対照: 修正をrevertすると本試験群が落ちること(完了報告に手順記録)。
# ここでは「_on_refresh_pak_list()を直接呼ぶだけでも選択が復元される」
# (方式Bの多重防御)ことを確認する——万一_refresh_lab_warningの配線が
# 将来また崩れても、この防御だけで選択は残る。
# ---------------------------------------------------------------------------


def test_on_refresh_pak_list_alone_preserves_prior_selection(hidden_root, tmp_path):
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        work_root = str(tmp_path / "work")
        app_root = str(tmp_path / "app_root")
        os.makedirs(app_root, exist_ok=True)
        self = _make_fake_self(hidden_root, app_root, work_root)
        mw.MainWindow._build_widgets(self)

        _make_built_pak_with_job(work_root, "NormalAvatar", multi_avatar=False)
        mw.MainWindow._on_refresh_pak_list(self)

        pak_list = self.widgets["pakList"]
        (iid,) = pak_list.get_children()
        pak_list.selection_set(iid)
        old_path = self._pak_paths[iid]

        # 再構築を直接呼ぶ(iidそのものは作り直されるが、同じpak_pathの行に
        # 選択が復元されるはず)。
        mw.MainWindow._on_refresh_pak_list(self)

        (new_iid,) = pak_list.get_children()
        assert self._pak_paths[new_iid] == old_path
        assert pak_list.selection() == (new_iid,)
    finally:
        i18n.clear_registry()
