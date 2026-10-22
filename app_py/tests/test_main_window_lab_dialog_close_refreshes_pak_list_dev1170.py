# test_main_window_lab_dialog_close_refreshes_pak_list_dev1170.py -- dev#1170
# 「マルチアバターPAKの作成物が『作成済みMOD一覧』に表示されない」バグの
# 直し方の単体試験(dev#1311で配線位置を訂正、本ファイルもそれに追従)。
#
# 現物調査で判明した原因: 合成出力の構造(<work_root>\<job_dir>\build\
# *_PlayerSwap_P.pak + job_dir\library\manifest.json の multi_avatar:true)も
# pak_manager.list_built_paks()/entry_is_multi_avatar()の検出条件も既に
# 一致していた(test_main_window_pak_list_multi_avatar_mark_dev1170.py が
# 実証済み)。欠けていたのは「合成ダイアログを閉じた後に一覧
# (pakList/_on_refresh_pak_list)を再読込する配線」だけ。
#
# dev#1311訂正: 当初(cecbf70)は main_window.py._refresh_lab_warning() の
# 末尾に一覧再読込を足す形で直したが、_refresh_lab_warning()はpak一覧の
# 行選択(_on_pak_list_selected → _apply_restored_settings)からも毎回
# 呼ばれるため、行をクリックした瞬間に一覧が作り直されて選択が即座に
# 解除される回帰を招いた(オーナー実機報告「fusionが選択できない」)。
# 一覧再読込は lab_window.py の open_lab_window() 内 refresh()
# (ラボ機能ダイアログの<Destroy>・「全てのラボ機能を無効化」・言語切替
# からしか呼ばれず、行選択とは無縁の経路)へ移設した。
# _refresh_lab_warning()は「単独では」もう一覧を再読込しない(下の負の
# 対照で固定する)。
#
# 実tkウィンドウは一切表示しない(hidden_root共有フィクスチャ+
# _build_widgets()だけを束縛前のまま呼ぶ、test_main_window_lab_ui.pyと
# 同じ慣例)。ダイアログclose自体はlab_window.open_lab_window()経由で
# 「ラボ窓を開く→先頭行(ドロップボーン機能)の設定ダイアログを開く→
# 閉じる」という実際のユーザー操作の経路をそのまま辿る。
from __future__ import annotations

import json
import os
import sys
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import lab_window  # noqa: E402
from ui import main_window as mw  # noqa: E402


def _make_fake_self_with_work_root(root, app_root: str, work_root: str) -> mw.MainWindow:
    """test_main_window_lab_ui.py._make_fake_selfと同じ慣例に、本試験が
    必要とするwork_root/_pak_paths/_pak_candidates(_on_refresh_pak_listが
    要求する属性、main_window.py __init__のL.505/L.649相当)を足しただけ。
    _on_update_applied_status()は実PalworldのSteam探索に触れないよう
    no-opへ差し替える(test_main_window_pak_list_multi_avatar_mark_dev1170.py
    と同じ割り切り)。"""
    self = mw.MainWindow.__new__(mw.MainWindow)
    self.root = root
    self.app_root = app_root
    self.work_root = work_root
    self.widgets = {}
    self._tooltips = []
    self._pak_paths: dict[str, str] = {}
    self._pak_candidates = []
    self._on_update_applied_status = lambda: None
    return self


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
    (job_dir/library/manifest.json)へ最小のmulti_avatar:trueマニフェストを
    直接書く(pipeline\\py本体は呼ばない——本WPの書き込み許可外)。"""
    job_dir = os.path.join(work_root, avatar_name)
    lib_dir = os.path.join(job_dir, "library")
    os.makedirs(lib_dir, exist_ok=True)
    with open(os.path.join(lib_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"format_version": 1, "multi_avatar": True}, f)


def _pak_list_display_names(self: mw.MainWindow) -> list[str]:
    pak_list = self.widgets["pakList"]
    names = []
    for iid in pak_list.get_children():
        names.append(pak_list.item(iid, "values")[0])
    return names


def _find_buttons(widget, text: str):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Button) and child.cget("text") == text:
            found.append(child)
        found.extend(_find_buttons(child, text))
    return found


def _open_and_close_first_lab_dialog(self: mw.MainWindow, root: tk.Misc) -> None:
    """ラボ窓を開く→先頭行(DROP_BONES_FEATURE)の「設定」ボタンでダイアログを
    開く→destroy()で閉じる、という実際のユーザー操作の経路をそのまま辿る。
    ドロップボーン機能を使うのは、他のラボ機能(装備限定・頭装備等)と違って
    バニラpak解決やカタログ取得の外部依存が無く、最も軽量に<Destroy>経路を
    再現できるため(feature自体の中身は本試験の関心事ではない)。"""
    lab_dlg = lab_window.open_lab_window(self, root)
    try:
        configure_buttons = _find_buttons(lab_dlg, i18n.S("BtnLabConfigure"))
        assert configure_buttons, "設定ボタンが見つからない"
        configure_buttons[0].invoke()  # 先頭行=DROP_BONES_FEATURE
        # invoke()が開いた子ダイアログ(open_drop_bones_dialog())をToplevel
        # 子孫から見つけて閉じる。lab_dlgの直接の子として生成される
        # (dlg = tk.Toplevel(parent)、parent=lab_dlg)。
        child_dialogs = [
            c for c in lab_dlg.winfo_children() if isinstance(c, tk.Toplevel)
        ]
        assert child_dialogs, "設定ダイアログが開かなかった"
        child_dialogs[0].destroy()
    finally:
        lab_dlg.destroy()


# ---------------------------------------------------------------------------
# 正: ラボダイアログを閉じると(_refresh_lab_warning()単独ではなく
# lab_window.refresh()経由で)一覧に反映されること
# ---------------------------------------------------------------------------


def test_lab_dialog_close_reloads_pak_list_for_newly_built_pak(hidden_root, tmp_path):
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        work_root = str(tmp_path / "work")
        app_root = str(tmp_path / "app_root")
        os.makedirs(app_root, exist_ok=True)
        self = _make_fake_self_with_work_root(hidden_root, app_root, work_root)
        mw.MainWindow._build_widgets(self)

        # ダイアログを開く前(=合成前)は一覧は空。
        assert _pak_list_display_names(self) == []

        # 合成ダイアログの「作成」が完了した後の状態を模す(ダイアログ自体は
        # 本WPの書き込み許可外なので、その出力構造だけを直接作る)。
        _make_built_pak(work_root, "MyMultiOutfit")
        _mark_multi_avatar(work_root, "MyMultiOutfit")

        _open_and_close_first_lab_dialog(self, hidden_root)

        names = _pak_list_display_names(self)
        assert len(names) == 1
        assert "MyMultiOutfit" in names[0]
        assert names[0] != "MyMultiOutfit"  # マルチ品の目印も引き続き付く
    finally:
        i18n.clear_registry()


def test_lab_dialog_close_reloads_normal_entry_without_multi_avatar_mark(
    hidden_root, tmp_path
):
    """マルチ品専用の分岐ではなく通常品にも同様に効くこと(=通常品の表示に
    影響しないことの確認を兼ねる)。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        work_root = str(tmp_path / "work")
        app_root = str(tmp_path / "app_root")
        os.makedirs(app_root, exist_ok=True)
        self = _make_fake_self_with_work_root(hidden_root, app_root, work_root)
        mw.MainWindow._build_widgets(self)

        _make_built_pak(work_root, "NormalAvatar")

        _open_and_close_first_lab_dialog(self, hidden_root)

        assert _pak_list_display_names(self) == ["NormalAvatar"]  # 目印なし、素の名前のまま
    finally:
        i18n.clear_registry()


# ---------------------------------------------------------------------------
# 負の対照(dev#1311): _refresh_lab_warning()を単独で呼んでも、もう一覧は
# 再読込されないこと。これが本WPの直し方そのもの(選択解除の回帰は
# _refresh_lab_warning()がpak一覧選択からも呼ばれることが原因だったため、
# そこから一覧再読込を切り離した)。
# ---------------------------------------------------------------------------


def test_refresh_lab_warning_alone_no_longer_reloads_pak_list_dev1311(
    hidden_root, tmp_path
):
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        work_root = str(tmp_path / "work")
        app_root = str(tmp_path / "app_root")
        os.makedirs(app_root, exist_ok=True)
        self = _make_fake_self_with_work_root(hidden_root, app_root, work_root)
        mw.MainWindow._build_widgets(self)

        assert _pak_list_display_names(self) == []

        _make_built_pak(work_root, "MyMultiOutfit")
        _mark_multi_avatar(work_root, "MyMultiOutfit")

        # _refresh_lab_warning()だけを呼ぶ(ダイアログを開かない=lab_window.
        # refresh()を経由しない)。もし一覧再読込がまだ_refresh_lab_warning()
        # 側に残っていれば、ここで一覧が更新されてしまう(=退行)。
        mw.MainWindow._refresh_lab_warning(self)

        assert _pak_list_display_names(self) == []
    finally:
        i18n.clear_registry()


# ---------------------------------------------------------------------------
# 負の対照: work_root未設定のフェイクself(既存の他ラボ試験の流儀)を
# 壊さないこと
# ---------------------------------------------------------------------------


def test_refresh_lab_warning_negative_control_does_not_require_work_root(
    hidden_root, tmp_path
):
    """既存のtest_main_window_lab_ui.py._make_fake_self相当
    (work_root/_pak_paths未設定)へ本メソッドを直接bindして呼んでも
    例外にならないこと。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = mw.MainWindow.__new__(mw.MainWindow)
        self.root = hidden_root
        self.app_root = str(tmp_path)
        self.widgets = {}
        self._tooltips = []
        mw.MainWindow._build_widgets(self)

        assert not hasattr(self, "work_root")
        # 例外を出さず完走することそのものが検証対象。
        mw.MainWindow._refresh_lab_warning(self)
    finally:
        i18n.clear_registry()
