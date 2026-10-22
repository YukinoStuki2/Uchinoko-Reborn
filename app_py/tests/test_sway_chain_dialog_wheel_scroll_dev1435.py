# test_sway_chain_dialog_wheel_scroll_dev1435.py -- dev#1435の回帰テスト
# (WP wp_labdlg_fix)。
#
# オーナー実機報告: ラボ「揺れもの詳細設定」ダイアログで、ボーン名・
# チェックボックス等の項目にマウスオン中、ホイールスクロールが効かない。
#
# 根本原因: tkinterの<MouseWheel>はポインタ直下のウィジェットにしか配送
# されず、親へ自動で伝播しない。旧実装はcanvas/rows_frame(行の隙間)にしか
# bindしておらず、行の中身(チェックボタン・かたさCombobox)の上では
# イベントがそこで止まっていた。
#
# 修正方式は兄弟ダイアログequipment_select_dialog.py(dev#165第2弾補修、
# test_equipment_select_dialog_dev165.py参照)と同じ「各子ウィジェットへ
# 個別にbind」パターンを踏襲(bind_allは他ダイアログへの影響・解除漏れ
# リスクがあるため見送った、work\wp_labdlg_fix\NOTES.md参照)。
#
# sway_chain_dialog.py固有の追加検証: 一覧行のかたさ選択はttk.Comboboxで、
# 'TCombobox'クラスバインドタグに既定の<MouseWheel>ハンドラ(ホイールで
# 選択値を送る動作)が登録されている(実測確認済み、bindtags順序は
# インスタンス→クラス→トップレベル→all)。インスタンスレベルの個別bindが
# "break"を返すことで、この既定動作を意図せず起動せずに済むこと(=ホイール
# を回してもコンボボックスの選択値が変わらないこと)も確認する。
#
# 実tk.Tk()は作らない(conftest.pyの共有hidden_root、既存慣例踏襲)。
from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import sway_chain_dialog as scd  # noqa: E402


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


def _find_canvas(dlg) -> tk.Canvas:
    for w in _walk_widgets(dlg):
        if isinstance(w, tk.Canvas):
            return w
    raise AssertionError("canvas not found")


def _row_checkbuttons(dlg) -> list[tk.Checkbutton]:
    return [w for w in _walk_widgets(dlg) if isinstance(w, tk.Checkbutton)]


def _row_comboboxes(dlg) -> list[ttk.Combobox]:
    # manual_hardness_combo(親がtk.LabelFrame)を除いた、一覧行のかたさ
    # Combobox群のみを返す(test_sway_chain_dialog_dev19.pyの
    # _manual_and_row_combos()と同じ判別方法)。
    return [
        w for w in _walk_widgets(dlg)
        if isinstance(w, ttk.Combobox) and not isinstance(w.master, tk.LabelFrame)
    ]


def _open_sample_dialog(hidden_root, tmp_path):
    i18n.set_language("ja")
    ctx = scd.SwayChainContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm",
        sample_mode=True,
    )
    return scd.show_sway_chain_dialog(hidden_root, ctx)


def test_mousewheel_scrolls_canvas_when_over_canvas(hidden_root, monkeypatch, tmp_path):
    dlg = _open_sample_dialog(hidden_root, tmp_path)
    try:
        canvas = _find_canvas(dlg)
        dlg.update_idletasks()
        dlg.update()
        calls = []
        monkeypatch.setattr(canvas, "yview_scroll",
                             lambda n, what: calls.append((n, what)))

        canvas.event_generate("<MouseWheel>", delta=-120)
        dlg.update()
        assert calls[-1] == (1, "units")

        calls.clear()
        canvas.event_generate("<MouseWheel>", delta=120)
        dlg.update()
        assert calls[-1] == (-1, "units")
    finally:
        dlg.destroy()


def test_mousewheel_scrolls_canvas_when_over_row_checkbutton(hidden_root, monkeypatch, tmp_path):
    """dev#1435の本題: ボーン名+チェックボックスが統合されたtk.Checkbutton
    (canvas上に重なる別ウィジェット)の上でホイールを回してもスクロールが
    効くこと。"""
    dlg = _open_sample_dialog(hidden_root, tmp_path)
    try:
        canvas = _find_canvas(dlg)
        cbs = _row_checkbuttons(dlg)
        assert cbs, "SAMPLE_CHAINSが反映されていない(--sample未反映?)"
        dlg.update_idletasks()
        dlg.update()
        calls = []
        monkeypatch.setattr(canvas, "yview_scroll",
                             lambda n, what: calls.append((n, what)))

        cbs[0].event_generate("<MouseWheel>", delta=-120)
        dlg.update()
        assert calls, "wheel over a row checkbutton should still scroll the list"
        assert calls[-1] == (1, "units")
    finally:
        dlg.destroy()


def test_mousewheel_scrolls_canvas_when_over_hardness_combobox(hidden_root, monkeypatch, tmp_path):
    """dev#1435: かたさCombobox上でも同様にスクロールが効くこと。"""
    dlg = _open_sample_dialog(hidden_root, tmp_path)
    try:
        canvas = _find_canvas(dlg)
        combos = _row_comboboxes(dlg)
        assert combos, "一覧行のComboboxが見つからない"
        dlg.update_idletasks()
        dlg.update()
        calls = []
        monkeypatch.setattr(canvas, "yview_scroll",
                             lambda n, what: calls.append((n, what)))

        combos[0].event_generate("<MouseWheel>", delta=-120)
        dlg.update()
        assert calls, "wheel over the hardness combobox should still scroll the list"
        assert calls[-1] == (1, "units")
    finally:
        dlg.destroy()


def test_mousewheel_over_combobox_does_not_change_its_own_value(hidden_root, tmp_path):
    """dev#1435副次確認: ttk.Comboboxは'TCombobox'クラスバインドタグに
    既定で<MouseWheel>ハンドラ(選択値をホイールで送る動作)を持つ
    (bindtags順序: インスタンス→クラス→トップレベル→all、実測確認済み)。
    行への個別bindが"break"を返すことで、この既定動作が意図せず起動して
    選択中のかたさが変わってしまう副作用を防げていることを確認する。"""
    dlg = _open_sample_dialog(hidden_root, tmp_path)
    try:
        combos = _row_comboboxes(dlg)
        assert combos
        combo = combos[0]
        dlg.update_idletasks()
        dlg.update()
        before = combo.get()

        combo.event_generate("<MouseWheel>", delta=-120)
        dlg.update()
        combo.event_generate("<MouseWheel>", delta=120)
        dlg.update()

        assert combo.get() == before, (
            "hovering the hardness combobox with the wheel must not change its "
            "own selected value (only scroll the list)"
        )
    finally:
        dlg.destroy()


def test_negative_control_no_mousewheel_binding_means_no_scroll_call(hidden_root):
    """負の対照: <MouseWheel>のbindが無ければ、event_generateしても
    yview_scrollは一切呼ばれない(=このテストの検出力そのものの確認、
    test_equipment_select_dialog_dev165.pyの同名テストと同じ手法)。
    tk.Tk()は新規生成しない(dev#672契約、共有hidden_rootを使う)。"""
    c = tk.Canvas(hidden_root)
    c.pack()
    calls = []
    c.yview_scroll = lambda n, what: calls.append((n, what))  # bind未設定
    c.event_generate("<MouseWheel>", delta=-120)
    hidden_root.update()
    c.destroy()
    assert calls == []
