# test_main_window_pak_list_multi_avatar_mark_dev1170.py -- dev#1170 WP-5:
# 「作成済みMOD一覧」でマルチ品(合成PAK)が単体変換品と区別できる目印表示の
# 単体試験。
#
# 判定源はpak_manager.entry_is_multi_avatar()(WP-3で用意済み、
# job_dir/library/manifest.json の "multi_avatar": true を読む)。本WPは
# app_py\ui\main_window.py._on_refresh_pak_list() 側に、そのフラグを見て
# 一覧行の表示名へ地味な目印(i18nキー PakListMultiAvatarMarkFormat)を足す
# 配線を追加した(pak_manager.entry_is_multi_avatar()のdocstring「配線は
# 将来WPで1行差すだけ」の実行、詳細はモジュールdocstring参照)。
#
# ラボ憲章④(既定値不変): マルチ品が1件も存在しない場合の一覧表示は、
# 本WP適用前と完全に同一であること(目印を足す分岐そのものを通らない)。
#
# 実tkウィンドウは一切開かない(test_main_window_work_root_wiring.pyと同じ
# 流儀: mw.MainWindow.__new__(mw.MainWindow) でフェイクselfを作り、pakListも
# ttk.Treeview互換の最小フェイクに差し替える)。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import main_window as mw  # noqa: E402


def _bare_window() -> mw.MainWindow:
    """__init__を通さずMainWindowインスタンスだけ得る
    (test_main_window_work_root_wiring.pyと同じ手筋)。"""
    return mw.MainWindow.__new__(mw.MainWindow)


class _FakePakList:
    """ttk.Treeview互換の最小フェイク(_on_refresh_pak_list が使う範囲のみ:
    delete/get_children/insert)。test_main_window_work_root_wiring.pyの
    _FakePakListと同型(依存を増やさないためこのファイル内に複製)。"""

    def __init__(self) -> None:
        self._items: list[str] = []
        self._values_by_iid: dict[str, tuple] = {}

    def get_children(self):
        return tuple(self._items)

    def delete(self, *_iids) -> None:
        self._items = []

    def insert(self, _parent, _index, values=()):
        iid = f"iid{len(self._items)}"
        self._items.append(iid)
        self._values_by_iid[iid] = values
        return iid


def _make_built_pak(work_root: str, avatar_name: str) -> str:
    """pak_manager.list_built_paks()が拾う形(<work_root>\\<avatar>\\build\\
    <name>_PlayerSwap_P.pak)で最小限のビルド成果物を作る。"""
    build_dir = os.path.join(work_root, avatar_name, "build")
    os.makedirs(build_dir, exist_ok=True)
    pak_path = os.path.join(build_dir, f"{avatar_name}_PlayerSwap_P.pak")
    with open(pak_path, "wb") as f:
        f.write(b"stub")
    return pak_path


def _mark_multi_avatar(work_root: str, avatar_name: str) -> None:
    """vp_avatar_compose.compose()が書くのと同じ場所
    (job_dir/library/manifest.json、= vp_avatar_library.manifest_path())へ
    最小のmulti_avatar:trueマニフェストを直接書く(pipeline\\py本体は呼ばない
    ——本WPの書き込み許可外)。"""
    job_dir = os.path.join(work_root, avatar_name)
    lib_dir = os.path.join(job_dir, "library")
    os.makedirs(lib_dir, exist_ok=True)
    with open(os.path.join(lib_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"format_version": 1, "multi_avatar": True}, f)


def _bare_window_with_pak_list(work_root: str) -> tuple[mw.MainWindow, _FakePakList]:
    fake = _bare_window()
    fake.app_root = work_root  # 本試験の対象外(pak一覧の出所はwork_rootのみ)
    fake.work_root = work_root
    pak_list = _FakePakList()
    fake.widgets = {"pakList": pak_list}
    fake._pak_paths = {}
    fake._pak_candidates = []
    # _on_update_applied_status()相当は本試験の対象外(実PalworldのSteam探索
    # に触れないよう、no-opへ差し替える。test_main_window_work_root_wiring.py
    # と同じ割り切り)。
    fake._on_update_applied_status = lambda: None
    return fake, pak_list


# ---------------------------------------------------------------------------
# 正: マルチ品エントリの表示名に目印が付くこと
# ---------------------------------------------------------------------------


def test_refresh_pak_list_marks_multi_avatar_entry(tmp_path):
    work_root = str(tmp_path / "work")
    _make_built_pak(work_root, "MyMultiOutfit")
    _mark_multi_avatar(work_root, "MyMultiOutfit")

    fake, pak_list = _bare_window_with_pak_list(work_root)
    mw.MainWindow._on_refresh_pak_list(fake)

    assert len(pak_list._items) == 1
    values = pak_list._values_by_iid[pak_list._items[0]]
    displayed_avatar_name = values[0]
    assert displayed_avatar_name != "MyMultiOutfit"  # 素の名前のままではない(目印が付いた)
    assert "MyMultiOutfit" in displayed_avatar_name  # 元の名前は保持されている


# ---------------------------------------------------------------------------
# ラボ憲章④: マルチ品が存在しない場合、一覧表示は本WP適用前と完全に同一
# ---------------------------------------------------------------------------


def test_refresh_pak_list_leaves_normal_entry_display_name_unchanged(tmp_path):
    work_root = str(tmp_path / "work")
    _make_built_pak(work_root, "NormalAvatar")
    # multi_avatarマニフェストは書かない(通常の単体変換エントリ、または
    # library/manifest.json自体が無いエントリ)。

    fake, pak_list = _bare_window_with_pak_list(work_root)
    mw.MainWindow._on_refresh_pak_list(fake)

    assert len(pak_list._items) == 1
    values = pak_list._values_by_iid[pak_list._items[0]]
    assert values[0] == "NormalAvatar"  # 目印なし、素の名前のまま(既定値不変)


def test_refresh_pak_list_negative_control_manifest_without_multi_avatar_flag_is_unmarked(
    tmp_path,
):
    """負の対照: library/manifest.json自体は存在するが multi_avatar:true が
    無い(WP-1の通常中間物保存で作られるmanifest)場合は目印を付けないこと
    (pak_manager.entry_is_multi_avatar()の既存契約どおり)。"""
    work_root = str(tmp_path / "work")
    _make_built_pak(work_root, "SavedButNotMulti")
    job_dir = os.path.join(work_root, "SavedButNotMulti")
    lib_dir = os.path.join(job_dir, "library")
    os.makedirs(lib_dir, exist_ok=True)
    with open(os.path.join(lib_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"format_version": 1}, f)  # multi_avatarキー無し

    fake, pak_list = _bare_window_with_pak_list(work_root)
    mw.MainWindow._on_refresh_pak_list(fake)

    values = pak_list._values_by_iid[pak_list._items[0]]
    assert values[0] == "SavedButNotMulti"


# ---------------------------------------------------------------------------
# 混在: マルチ品と通常品が両方ある一覧で、マルチ品だけに目印が付くこと
# ---------------------------------------------------------------------------


def test_refresh_pak_list_marks_only_multi_avatar_entries_in_mixed_list(tmp_path):
    work_root = str(tmp_path / "work")
    _make_built_pak(work_root, "Multi1")
    _mark_multi_avatar(work_root, "Multi1")
    _make_built_pak(work_root, "Normal1")

    fake, pak_list = _bare_window_with_pak_list(work_root)
    mw.MainWindow._on_refresh_pak_list(fake)

    display_names = {values[0] for values in pak_list._values_by_iid.values()}
    assert "Normal1" in display_names
    assert "Multi1" not in display_names  # 素の名前ではなく目印付きの名前になっている
    assert any("Multi1" in name for name in display_names)
