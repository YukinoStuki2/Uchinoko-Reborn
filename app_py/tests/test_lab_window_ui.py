# test_lab_window_ui.py -- dev#1186受入条件のウィジェット層。
#
# ui\lab_window.py の open_drop_bones_dialog()/open_lab_window() が
# 実際にウィジェットを正しく組み立て・配線することを検証する。
#
# 実tkウィンドウは一切表示しない(conftest.pyの共有hidden_root、withdraw済み、
# test_support_dialog_full_log_attachment.py等の既存の慣例を踏襲)。
from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import lab_window  # noqa: E402


class _FakeSelf:
    """lab_window.pyの関数群が要求する最小のself。main_window.pyの
    _on_drop_bones_changed/_refresh_lab_warningはあえて持たせない
    (getattrガードで安全に呼ばれないことも本ファイルの検証対象)。

    app_root: dev#165(装備限定)結線後、open_lab_window()のrefresh()が
    equipment_filter機能のstatus_summaryも呼ぶため必要になった
    (test_lab_window_logic.py の同名フィールドと同じ理由)。"""

    def __init__(self, root: tk.Misc, drop_bones_text: str = "") -> None:
        self.root = root
        box = tk.Entry(root)
        if drop_bones_text:
            box.insert(0, drop_bones_text)
        self.widgets = {"dropBonesBox": box}
        self.app_root = tempfile.mkdtemp(prefix="d2p_lab_test_")
        # dev#1277: ui/drop_bones_dialog.pyへの切り出し後、query_bone_catalog()
        # がwork_root(prefabキャッシュ解決に使う)を要求するようになった
        # (mesh_delete_dialog.py/shapekey_select_dialog.pyの既存アダプタと
        # 同型)。widgets["vrmBox"]は意図的に持たせない(avatar_path=""扱いと
        # なり、本ファイルの各テストはカタログ取得失敗→カンマ区切り手入力
        # フォールバックUI経由になる。フォールバックUIは旧実装と構造的に同じ
        # ため、多くのアサーションはそのまま通る設計)。
        self.work_root = tempfile.mkdtemp(prefix="d2p_lab_test_work_")


def _find_children(widget, cls):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_find_children(child, cls))
    return found


def _find_button(widget, text: str):
    for btn in _find_children(widget, tk.Button):
        if btn.cget("text") == text:
            return btn
    return None


def _find_entry(widget):
    entries = _find_children(widget, tk.Entry)
    return entries[0] if entries else None


# ---------------------------------------------------------------------------
# open_drop_bones_dialog
# ---------------------------------------------------------------------------


def test_drop_bones_dialog_prefills_entry_from_backing_store(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "Bone_L, Bone_R")
    dlg = lab_window.open_drop_bones_dialog(self, hidden_root, lambda: None)
    try:
        entry = _find_entry(dlg)
        assert entry is not None
        assert entry.get() == "Bone_L, Bone_R"
    finally:
        dlg.destroy()


def test_drop_bones_dialog_shows_hint_label_dev1186_owner_20260808(hidden_root):
    """2026-08-08 オーナー指示: ボーン削除ダイアログには機能説明が無かった
    (装備限定・頭装備切替ダイアログには既にあった)。同じ流儀(dlg直下に
    Label、i18n.register()で言語切替追従)で新設した説明ラベルの存在と、
    言語切替への追従を確認する。"""
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    dlg = lab_window.open_drop_bones_dialog(self, hidden_root, lambda: None)
    try:
        labels = [lbl.cget("text") for lbl in _find_children(dlg, tk.Label)]
        assert i18n.S("LabDropBonesHint", "ja") in labels
        i18n.apply_language("en")
        try:
            labels_en = [lbl.cget("text") for lbl in _find_children(dlg, tk.Label)]
            assert i18n.S("LabDropBonesHint", "en") in labels_en
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()


def test_drop_bones_dialog_ok_writes_back_and_calls_on_change(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    on_change_calls = []
    dlg = lab_window.open_drop_bones_dialog(
        self, hidden_root, lambda: on_change_calls.append(1)
    )
    try:
        entry = _find_entry(dlg)
        entry.delete(0, tk.END)
        entry.insert(0, "Tail")
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        assert ok_btn is not None
        ok_btn.invoke()
        assert self.widgets["dropBonesBox"].get() == "Tail"
        # dev#1277: open_drop_bones_dialog()をmesh_delete_dialog.py/
        # shapekey_select_dialog.pyと同じ`dlg.bind("<Destroy>", on_change)`
        # 配線へ揃えた(旧実装は_apply_and_close内でon_change()を1回だけ直接
        # 呼んでいた)。Tkinterのbindtags仕様上、Toplevelの<Destroy>束縛は
        # 破棄されるすべての子孫ウィジェットのDestroyイベントでも発火する
        # (実測確認済み、Toplevel単体destroyで子孫数+1回)ため、正確に1回とは
        # 限らない。on_change()自体は既存の他ダイアログ(equipment_select_
        # dialog.py等)と同じくrefresh()の再呼び出しに過ぎず、複数回でも副作用
        # は無い(ラボ憲章②)。ここでは「少なくとも1回は発火した」ことのみ
        # 検証する。
        assert on_change_calls, "OK押下後にon_changeが一度も呼ばれていない"
    finally:
        # ok_btn.invoke()がdlg.destroy()を呼んでいるはずなので二重destroyに
        # なっても例外を出さないよう安全側で囲む(既にdestroy済みなら無視)。
        try:
            dlg.destroy()
        except tk.TclError:
            pass


def test_drop_bones_dialog_closing_without_ok_discards_edits(hidden_root):
    """×で閉じた場合(WM_DELETE_WINDOW=destroyのみ)はバッキングストアへ
    書き戻さないこと。ここではdlg.destroy()を直接呼んで同じ経路を模擬する。
    on_change()自体は×閉じでも発火する(equipment_select_dialog.py等の既存
    ダイアログと同じ意図的な仕様——「状態の再読込に副作用は無いのでCancel/
    ×でも無害」、上のtest_drop_bones_dialog_ok_writes_back_and_calls_on_change
    のコメント参照)ため、ここでは検証しない。本テストの本体は
    「書き戻されないこと」。"""
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "Original")
    dlg = lab_window.open_drop_bones_dialog(self, hidden_root, lambda: None)
    entry = _find_entry(dlg)
    entry.delete(0, tk.END)
    entry.insert(0, "Edited but discarded")
    dlg.destroy()
    assert self.widgets["dropBonesBox"].get() == "Original"


def test_drop_bones_dialog_calls_optional_on_drop_bones_changed_hook(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    self.drop_bones_changed_calls = 0

    def _hook():
        self.drop_bones_changed_calls += 1

    self._on_drop_bones_changed = _hook

    dlg = lab_window.open_drop_bones_dialog(self, hidden_root, lambda: None)
    try:
        entry = _find_entry(dlg)
        entry.insert(0, "Hip")
        _find_button(dlg, i18n.S("BtnOk")).invoke()
        assert self.drop_bones_changed_calls == 1
    finally:
        try:
            dlg.destroy()
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# open_lab_window -- グリッド構成+警告表示の配線
# ---------------------------------------------------------------------------


def test_lab_window_shows_one_row_per_registered_feature(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        feature_names = {i18n.S(f.name_key) for f in lab_window.LAB_FEATURES}
        labels = {lbl.cget("text") for lbl in _find_children(dlg, tk.Label)}
        for name in feature_names:
            assert name in labels, f"機能名ラベルが見つからない: {name!r}"
        # 「設定...」ボタンが機能の数だけ存在すること(1機能=1行の一部)。
        configure_buttons = [
            b for b in _find_children(dlg, tk.Button)
            if b.cget("text") == i18n.S("BtnLabConfigure")
        ]
        assert len(configure_buttons) == len(lab_window.LAB_FEATURES)
    finally:
        dlg.destroy()


def test_lab_window_status_shows_disabled_when_default(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        labels = [lbl.cget("text") for lbl in _find_children(dlg, tk.Label)]
        assert i18n.S("LabStatusDisabled") in labels
    finally:
        dlg.destroy()


def test_lab_window_status_shows_active_summary_when_non_default(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "Bone_L, Bone_R")
    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        expected = i18n.F(
            "LabStatusActiveFormat",
            i18n.F("LabStatusDropBonesCountFormat", 2),
        )
        labels = [lbl.cget("text") for lbl in _find_children(dlg, tk.Label)]
        assert expected in labels
    finally:
        dlg.destroy()


def test_lab_window_warning_hidden_when_default_shown_when_active(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        warning_label = next(
            lbl for lbl in _find_children(dlg, tk.Label)
            if lbl.cget("text") == i18n.S("LabWarningActive")
        )
        assert warning_label.grid_info() == {}, "既定状態で警告が表示されている"

        # 設定ダイアログ経由で非既定へ変更→ラボ窓の警告が出ること。
        configure_btn = _find_button(dlg, i18n.S("BtnLabConfigure"))
        configure_btn.invoke()
        # open_drop_bones_dialog()はラボ窓(dlg)をparentに開く(モーダル的な
        # 親子関係のため)。
        sub_dlg = next(
            child for child in dlg.winfo_children()
            if isinstance(child, tk.Toplevel)
        )
        try:
            entry = _find_entry(sub_dlg)
            entry.insert(0, "Bone_L")
            _find_button(sub_dlg, i18n.S("BtnOk")).invoke()
        finally:
            try:
                sub_dlg.destroy()
            except tk.TclError:
                pass

        assert warning_label.grid_info() != {}, "非既定になっても警告が出ていない"
    finally:
        dlg.destroy()


def test_lab_window_disable_all_button_hides_warning_again(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "Bone_L")
    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        warning_label = next(
            lbl for lbl in _find_children(dlg, tk.Label)
            if lbl.cget("text") == i18n.S("LabWarningActive")
        )
        assert warning_label.grid_info() != {}, "非既定なのに最初から警告が出ていない"

        disable_all_btn = _find_button(dlg, i18n.S("BtnLabDisableAll"))
        assert disable_all_btn is not None
        disable_all_btn.invoke()

        assert self.widgets["dropBonesBox"].get() == ""
        assert warning_label.grid_info() == {}, "全無効化ボタンを押しても警告が消えない"
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 2026-08-08 第3弾「言語切替のobserver化」: 開いているラボ窓・drop_bones
# ダイアログの表示文字列が i18n.apply_language() の呼び出しに追従すること
# (既存のi18n.register()/apply_language()仕組みへ相乗りする最小の仕掛け、
# main_window.py._on_language_selected()と同じ経路)。
# ---------------------------------------------------------------------------


def test_lab_window_follows_language_switch(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        assert dlg.title() == i18n.S("LabWindowTitle", "ja")
        disable_all_btn = _find_button(dlg, i18n.S("BtnLabDisableAll", "ja"))
        assert disable_all_btn is not None

        i18n.apply_language("en")
        try:
            assert dlg.title() == i18n.S("LabWindowTitle", "en")
            # ボタン・ラベルはすべてconfig(text=...)経由で再適用されている
            assert _find_button(dlg, i18n.S("BtnLabDisableAll", "en")) is not None
            assert _find_button(dlg, i18n.S("BtnLabDisableAll", "ja")) is None
            labels = [lbl.cget("text") for lbl in _find_children(dlg, tk.Label)]
            assert i18n.S("LabColFeatureName", "en") in labels
            assert i18n.S("LabColStatus", "en") in labels
            assert i18n.S("LabWarningActive", "en") in labels
            feature_names_en = {i18n.S(f.name_key, "en") for f in lab_window.LAB_FEATURES}
            for name in feature_names_en:
                assert name in labels
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()


def test_lab_window_status_label_follows_language_switch(hidden_root):
    """dynamic文言(status_label、LabStatusDisabled等)もrefresh()の再呼び出し
    経由で追従すること(単純な単一key登録では乗らないため、専用の配線)。"""
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "Bone_L, Bone_R")
    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        expected_ja = i18n.F(
            "LabStatusActiveFormat",
            i18n.F("LabStatusDropBonesCountFormat", 2),
        )
        labels_ja = [lbl.cget("text") for lbl in _find_children(dlg, tk.Label)]
        assert expected_ja in labels_ja

        i18n.apply_language("en")
        try:
            expected_en = i18n.F(
                "LabStatusActiveFormat",
                i18n.F("LabStatusDropBonesCountFormat", 2),
            )
            labels_en = [lbl.cget("text") for lbl in _find_children(dlg, tk.Label)]
            assert expected_en in labels_en
            assert expected_ja not in labels_en
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()


def test_drop_bones_dialog_follows_language_switch(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    dlg = lab_window.open_drop_bones_dialog(self, hidden_root, lambda: None)
    try:
        assert dlg.title() == i18n.S("LabFeatureDropBones", "ja")
        i18n.apply_language("en")
        try:
            assert dlg.title() == i18n.S("LabFeatureDropBones", "en")
            assert _find_button(dlg, i18n.S("BtnOk", "en")) is not None
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()


def test_lab_window_refresh_calls_optional_main_window_hook(hidden_root):
    """dev#1186「メイン窓側が本命」: ラボ窓の状態が変わるたび、
    self._refresh_lab_warning() が存在すれば必ず呼ばれること。"""
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    calls = []
    self._refresh_lab_warning = lambda: calls.append(1)

    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        # open_lab_window()自体が最初のrefresh()を呼ぶため、開いた時点で
        # 最低1回は呼ばれていること。
        assert len(calls) >= 1
        before = len(calls)

        disable_all_btn = _find_button(dlg, i18n.S("BtnLabDisableAll"))
        disable_all_btn.invoke()
        assert len(calls) > before
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# dev#1279(2026-08-09 オーナー報告「Labウィンドウが2つ開ける不具合」):
# open_lab_window()のシングルトンガード。BtnLabを連打しても窓は1つだけ、
# 既存窓が生きていれば前面化するだけに留まること。
# ---------------------------------------------------------------------------


def _lab_toplevels(hidden_root):
    return [
        c for c in hidden_root.winfo_children()
        if isinstance(c, tk.Toplevel) and c.title() == i18n.S("LabWindowTitle")
    ]


def test_open_lab_window_repeated_calls_reuse_same_toplevel_dev1279(hidden_root):
    """本題: 同じselfで2回呼んでも同一インスタンスが返り、ラボ窓は1つしか
    存在しないこと(修正前は毎回tk.Toplevel()が新規生成されていた)。"""
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    dlg1 = lab_window.open_lab_window(self, hidden_root)
    try:
        dlg2 = lab_window.open_lab_window(self, hidden_root)
        assert dlg1 is dlg2
        assert len(_lab_toplevels(hidden_root)) == 1
    finally:
        dlg1.destroy()


def test_open_lab_window_second_call_lifts_and_focuses_existing_window_dev1279(hidden_root):
    """2回目の呼び出しは新規生成せず、既存窓のlift()/focus_force()
    (前面化)だけを呼ぶこと。"""
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    dlg1 = lab_window.open_lab_window(self, hidden_root)
    try:
        calls = []
        dlg1.lift = lambda: calls.append("lift")
        dlg1.focus_force = lambda: calls.append("focus_force")

        dlg2 = lab_window.open_lab_window(self, hidden_root)
        assert dlg2 is dlg1
        assert calls == ["lift", "focus_force"]
    finally:
        dlg1.destroy()


def test_open_lab_window_reopens_fresh_after_previous_one_closed_dev1279(hidden_root):
    """既存窓が×(WM_DELETE_WINDOW=destroy)で閉じられていれば、次の呼び
    出しは通常どおり新規のToplevelを開き直すこと(ガードが閉じた窓を
    掴んだままにしない)。"""
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    dlg1 = lab_window.open_lab_window(self, hidden_root)
    dlg1.destroy()

    dlg2 = lab_window.open_lab_window(self, hidden_root)
    try:
        assert dlg2 is not dlg1
        assert dlg2.winfo_exists()
        assert len(_lab_toplevels(hidden_root)) == 1
    finally:
        dlg2.destroy()


def test_open_lab_window_negative_control_without_guard_creates_duplicate_dev1279(hidden_root):
    """負の対照: シングルトンガードが記憶している`_lab_window_toplevel`を
    人為的に消して(=ガード無効化を模擬して)呼び出すと、案の定ラボ窓が
    2つ存在してしまうことを示す。これによりこのテスト群が実際に
    「重複生成」を検出できる感度を持つことを確認する。"""
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root, "")
    dlg1 = lab_window.open_lab_window(self, hidden_root)
    try:
        self._lab_window_toplevel = None  # ガードが効いていない状態を模擬
        dlg2 = lab_window.open_lab_window(self, hidden_root)
        try:
            assert dlg1 is not dlg2
            assert len(_lab_toplevels(hidden_root)) == 2
        finally:
            dlg2.destroy()
    finally:
        dlg1.destroy()
