# test_window_pos.py -- ui/window_pos.py の位置決めロジック。
#
# オーナー指摘(2026-08-08、官能検査中): 「ラボサブウィンドウが画面の左上に
# 出るのが使いにくい。メインに重なるように」。ラボ憲章②「ちょっとアクセス
# しにくい場所に置く」の対象は機能そのものであって、開いた後の使い勝手は
# 別の話――ここでは軽量な単体テストで固定する(GUI起動テストは不要、
# lab-devスキルの試験軽重ルールどおり)。
from __future__ import annotations

import os
import sys
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import window_pos  # noqa: E402


# ---------------------------------------------------------------------------
# offset_position() -- 純関数(GUI非依存)
# ---------------------------------------------------------------------------


def test_offset_position_adds_default_offset():
    assert window_pos.offset_position(100, 200) == (
        100 + window_pos.DEFAULT_OFFSET,
        200 + window_pos.DEFAULT_OFFSET,
    )


def test_offset_position_accepts_custom_offset():
    assert window_pos.offset_position(0, 0, offset=10) == (10, 10)


def test_offset_position_handles_negative_parent_coordinates():
    """マルチモニタで親窓が主モニタの左/上にある場合、winfo_rootx/rootyは
    負値になりうる。単純加算のままでよい(=メインへ寄せる意図を保つ)。"""
    assert window_pos.offset_position(-50, -30, offset=40) == (-10, 10)


# ---------------------------------------------------------------------------
# apply_offset_position() -- tk.Toplevel実物への配線(hidden_rootで検証)
# ---------------------------------------------------------------------------


def test_apply_offset_position_moves_dialog_relative_to_parent(hidden_root):
    hidden_root.update_idletasks()
    parent_x = hidden_root.winfo_rootx()
    parent_y = hidden_root.winfo_rooty()

    dlg = tk.Toplevel(hidden_root)
    try:
        window_pos.apply_offset_position(dlg, hidden_root)
        dlg.update_idletasks()
        assert dlg.winfo_x() == parent_x + window_pos.DEFAULT_OFFSET
        assert dlg.winfo_y() == parent_y + window_pos.DEFAULT_OFFSET
    finally:
        dlg.destroy()


def test_apply_offset_position_preserves_existing_size(hidden_root):
    """位置("+X+Y")だけを追加指定しても、先に指定したサイズ("WxH")が
    上書きされないこと(open_drop_bones_dialog/show_equipment_select_dialogの
    ように先にgeometry("WxH")してから呼ぶ実際の呼び出し順を模擬)。"""
    dlg = tk.Toplevel(hidden_root)
    try:
        dlg.geometry("440x180")
        window_pos.apply_offset_position(dlg, hidden_root)
        dlg.update_idletasks()
        assert dlg.winfo_width() == 440
        assert dlg.winfo_height() == 180
    finally:
        dlg.destroy()


def test_apply_offset_position_silently_ignores_destroyed_parent(hidden_root):
    """親が既に破棄済み(TclError)でも例外を送出せず、ダイアログ自体は
    そのまま使える状態を保つこと(ラボ機能の付随処理が本体を壊さない)。"""
    doomed_parent = tk.Toplevel(hidden_root)
    dlg = tk.Toplevel(hidden_root)
    try:
        doomed_parent.destroy()
        window_pos.apply_offset_position(dlg, doomed_parent)  # 例外を送出しない
    finally:
        dlg.destroy()
