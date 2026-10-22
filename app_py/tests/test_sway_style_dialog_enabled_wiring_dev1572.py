# test_sway_style_dialog_enabled_wiring_dev1572.py -- dev#1572第3便(issue
# #1572追記「チェインの揺れ設定問題1・2」)のGUI回帰テスト。実tk.Tk()は
# 作らない(conftest.pyの共有hidden_root、既存慣例踏襲)。
#
# 問題1(既定表示ズレ): 名前が尻尾/耳トークンに一致しない鎖(例: エプロン)
# でも、偏向していなければ既定でチェック済み(揺れる)表示になること。逆に
# 名前が尻尾トークンに一致しても偏向していれば既定は未チェックであること。
# 問題2(enabled未結線): チェックボックスをOFF/ONへ操作しOKすると、
# sway_chain_override_store(→job["sway_chain_overrides"])のenabledが
# 実際に書き換わり、再オープンでも復元されること(+負の対照: 他行は無傷)。
from __future__ import annotations

import json
import os
import sys
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)
_ROOT_DIR = os.path.dirname(_APP_PY_DIR)

import i18n  # noqa: E402
import sway_chain_override_store as chain_store  # noqa: E402
from ui import sway_style_dialog as dlg_mod  # noqa: E402


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _find_button(root, text):
    for w in _walk(root):
        if isinstance(w, tk.Button) and w.cget("text") == text:
            return w
    raise AssertionError(f"button not found: {text!r}")


def _find_button_contains(root, substr):
    for w in _walk(root):
        if isinstance(w, tk.Button) and substr in w.cget("text"):
            return w
    raise AssertionError(f"button containing {substr!r} not found")


def _checkbuttons_in_row_order(root):
    """行順にCheckbutton(ON/OFFチェックボックス)を返す(rows_inner内、
    grid配置のためwinfo_children()の生成順=行順と一致する)。"""
    return [w for w in _walk(root) if isinstance(w, tk.Checkbutton)]


def _checkbox_bool(cb: tk.Checkbutton) -> bool:
    """test_sway_chain_dialog_select_all_dev1436.pyと同じ手法(tk.
    Checkbuttonはttk.instate()を持たないため、紐付いたBooleanVarの値を
    直接読む)。"""
    return bool(int(cb.getvar(cb.cget("variable"))))


def _write_prefab_sidecar(tmp_path, physbones_doc: dict) -> str:
    avatar_path = tmp_path / "myavatar.prefab"
    avatar_path.write_text("", encoding="utf-8")
    out_dir = tmp_path / "myavatar_export"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "physbones.json").write_text(
        json.dumps(physbones_doc, ensure_ascii=False), encoding="utf-8")
    return str(avatar_path)


def _make_ctx(app_root, work_root, avatar_path):
    return dlg_mod.SwayStyleContext(
        app_root=app_root, work_root=work_root, avatar_path=avatar_path,
        sample_mode=False,
    )


# dev#1595(issue #1595)以降、`chain_store.load_config()`は読込時の再間引きを
# 行わない(ファイルの中身をそのまま返す)ため、default_enabled_mapは省略しても
# 結果は変わらない。ここでは「実際のダイアログが保存時に使うのと同じ
# 偏向判定ベースmap」であることを明示するため、引き続き渡す
# (下記アサーションの意図を読みやすくする目的、省略しても等価)。
_DEFAULT_ENABLED_MAP = {
    ("Hips", "Apron_01", "Apron_02"): True,   # 非偏向=真の既定ON
    ("Hips", "Tail_01", "Tail_02"): False,    # 偏向=真の既定OFF
}


def _unbiased_params():
    return {"pull": 0.5, "spring": 0.5, "limit_type": "None",
            "max_angle_x": 45.0, "limit_rotation": [0, 0, 0]}


def _biased_params():
    return {"pull": 0.5, "spring": 0.5, "limit_type": "Hinge",
            "max_angle_x": 45.0, "limit_rotation": [0, 0, 0]}


_DOC = {
    "format": "divetopalworld-physbones-1",
    "physbones": [
        # 名前は尻尾/耳のいずれのトークンにも一致しない(旧sway_identify.
        # default_sway_enabled()なら既定OFF)が、偏向していないため真の
        # 既定(偏向判定ベース)はON。問題1の核心。
        {"anchor": "Hips", "pb_object_name": "Apron",
         "chains": [["Apron_01", "Apron_02"]], "params": _unbiased_params()},
        # 名前は尻尾トークンに一致する(旧なら既定ON)が、偏向しているため
        # 真の既定はOFF。
        {"anchor": "Hips", "pb_object_name": "Tail",
         "chains": [["Tail_01", "Tail_02"]], "params": _biased_params()},
    ],
}


# --------------------------------------------------------------------- 問題1: 表示

def test_unbiased_non_tail_named_chain_is_checked_by_default(hidden_root, tmp_path):
    """既定で揺れる(非偏向)チェーンが、名前に尻尾/耳トークンが無くても
    「揺れる」(チェック済み)表示になること。"""
    avatar_path = _write_prefab_sidecar(tmp_path, _DOC)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        apron_row = _find_button_contains(dlg, "Apron")
        assert apron_row is not None
        cbs = _checkbuttons_in_row_order(dlg)
        assert len(cbs) == 2
        # Apronは1件目(physbonesリストの並び順どおり)。
        assert _checkbox_bool(cbs[0]) is True
    finally:
        dlg.destroy()


def test_biased_tail_named_chain_is_unchecked_by_default(hidden_root, tmp_path):
    """逆に、名前が尻尾トークンに一致していても偏向していれば既定は
    未チェック(揺れない)表示になること(旧名前ベース判定との食い違いの
    もう一方)。"""
    avatar_path = _write_prefab_sidecar(tmp_path, _DOC)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        cbs = _checkbuttons_in_row_order(dlg)
        assert len(cbs) == 2
        # Tailは2件目。
        assert _checkbox_bool(cbs[1]) is False
    finally:
        dlg.destroy()


# --------------------------------------------------------------------- 問題2: 双方向結線

def test_unchecking_default_on_row_persists_as_disabled_override(hidden_root, tmp_path):
    """既定ONの鎖(Apron)のチェックを外してOKすると、enabled=Falseの
    上書きとして保存される(問題2「既定ONの鎖をOFF」方向)。"""
    avatar_path = _write_prefab_sidecar(tmp_path, _DOC)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    cbs = _checkbuttons_in_row_order(dlg)
    cbs[0].invoke()  # Apronの行をOFFへ
    _find_button(dlg, i18n.S("BtnOk")).invoke()

    saved = chain_store.load_config(
        str(tmp_path), avatar_path, default_enabled_map=_DEFAULT_ENABLED_MAP)
    by_last_bone = {tuple(e["bones"])[-1]: e for e in saved}
    assert by_last_bone["Apron_02"]["enabled"] is False
    # 負の対照: 触っていないTail行は保存対象に現れない(既定=OFFのまま
    # なので、ラボ憲章④によりエントリ自体が保存されない)。
    assert "Tail_02" not in by_last_bone


def test_checking_default_off_biased_row_persists_as_enabled_override(hidden_root, tmp_path):
    """既定OFF(偏向)の鎖(Tail)のチェックを入れてOKすると、enabled=Trueの
    上書きとして保存される(問題2「既定OFFの鎖をON」方向、自己責任)。"""
    avatar_path = _write_prefab_sidecar(tmp_path, _DOC)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    cbs = _checkbuttons_in_row_order(dlg)
    cbs[1].invoke()  # Tailの行をONへ
    _find_button(dlg, i18n.S("BtnOk")).invoke()

    saved = chain_store.load_config(
        str(tmp_path), avatar_path, default_enabled_map=_DEFAULT_ENABLED_MAP)
    by_last_bone = {tuple(e["bones"])[-1]: e for e in saved}
    assert by_last_bone["Tail_02"]["enabled"] is True
    # 負の対照: 触っていないApron行は保存対象に現れない。
    assert "Apron_02" not in by_last_bone


def test_toggle_roundtrip_survives_reopen(hidden_root, tmp_path):
    """OFF/ON操作した状態でOKし、ダイアログを再オープンするとチェック
    状態が復元されること(往復の確認)。"""
    avatar_path = _write_prefab_sidecar(tmp_path, _DOC)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    cbs = _checkbuttons_in_row_order(dlg)
    cbs[0].invoke()  # ApronをOFFへ
    cbs[1].invoke()  # TailをONへ
    _find_button(dlg, i18n.S("BtnOk")).invoke()

    ctx2 = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    dlg2 = dlg_mod.show_sway_style_dialog(hidden_root, ctx2)
    try:
        cbs2 = _checkbuttons_in_row_order(dlg2)
        assert _checkbox_bool(cbs2[0]) is False  # Apron
        assert _checkbox_bool(cbs2[1]) is True   # Tail
    finally:
        dlg2.destroy()


def test_untouched_dialog_ok_does_not_write_enabled_overrides(hidden_root, tmp_path):
    """負の対照: 何も編集せずOKしても保存対象は空のまま(真の既定と
    チェック状態が一致しているため、ラボ憲章④により保存されない)。"""
    avatar_path = _write_prefab_sidecar(tmp_path, _DOC)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    _find_button(dlg, i18n.S("BtnOk")).invoke()
    assert chain_store.load_config(str(tmp_path), avatar_path) == []
