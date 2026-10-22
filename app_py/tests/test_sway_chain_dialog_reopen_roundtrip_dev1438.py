# test_sway_chain_dialog_reopen_roundtrip_dev1438.py -- dev#1438(致命、
# WP wp_labdlg_fix)の回帰テスト。
#
# オーナー実機報告: ラボ「揺れもの詳細設定」ダイアログをOKで確定後、再度
# 開くと設定が保存されていないように見える(「有効: N件変更」の件数表示は
# 出るが、その件数と実際のチェックボックスの表示状態が一致しない)。
#
# 根本原因(work\wp_labdlg_fix\NOTES.md参照): sway_chain_override_store.py
# の_is_default_entry()が「既定enabledは常にTrue」と誤って決め打ちしていた
# (dev#19 native-donor-rule導入で、既定enabledがチェーンの同定結果
# (尻尾・耳=ON、その他=OFF)へ変わった際の追従漏れ)。この結果:
#   - 既定OFFのチェーン(スカート等)をユーザーがONへ変えても、表面上
#     「enabled=True・hardness=follow・manual=False」が旧・既定判定と
#     一致してしまい保存対象から誤って除外される(ユーザーの変更が消える)。
#   - 既定OFFのチェーンを一切触っていない場合(enabled=Falseのまま)は
#     逆に「既定と不一致」と誤判定され、無意味な上書きが大量に保存される
#     (state_summary件数が実際のチェックボックス表示と乖離する症状)。
#
# 本ファイルは「オーバーライドを設定→閉じる→再オープン→チェックボックス
# 表示状態がストア内容と完全一致」を実際のダイアログウィジェット(チェック
# ボタンの表示テキスト+関連付けられたBooleanVarの値)で検証する。負の対照
# (旧・buggy版の_is_default_entryへ差し替えると本テストが実際に赤くなる
# こと)も併せて確認する。
#
# データ源はscd.SAMPLE_CHAINS(--sample、sample_mode=True)を使う。内訳:
# 尻尾1(Tail_03、既定ON)・耳2(EarL_02/EarR_02、既定ON)・髪1
# (HairBack_04、既定OFF)・スカート2(Skirt_F_02/Skirt_B_02、既定OFF)
# (test_sway_chain_dialog_native_donor_dev19.pyが既に同じ前提で検証済み)。
# 実tk.Tk()は作らない(conftest.pyの共有hidden_root、既存慣例踏襲)。
#
# dev#1470(WP wp_chainname、オーナー要望2026-08-15「ボーン名が『揺れの
# 末端』になっていて気持ち悪い。始点側の名前であるべき」): チェックボックス
# の表示テキスト(text=name)は末端ボーン名(例: "Skirt_F_02")から始点
# (根本/anchor)ボーン名(例: "J_Bip_C_Hips")へ変わった。SAMPLE_CHAINSは
# 同じ始点を複数チェーンが共有する構成(Hips始点=尻尾/スカート前/スカート後、
# Head始点=耳L/耳R)を含むため、重複行は直後の最初のノードボーン名を括弧
# 書きで添えて区別される(sway_chain_dialog._display_name()参照)。本テストは
# チェックボックスの参照キーを新しい表示名へ更新した。ストア側(ディスク)の
# 検証は`bones[-1]`(末端名、内部データそのもの)をキーにしており表示に
# 依存しないため変更していない。
from __future__ import annotations

import os
import sys
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import sway_chain_override_store as store  # noqa: E402
from ui import sway_chain_dialog as scd  # noqa: E402


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


def _row_checkbuttons(dlg) -> list[tk.Checkbutton]:
    # dev#1437のWP wp_labdlg_fixで一覧行のon/名前列はtk.Checkbutton
    # (text=name)へ統合された。ダイアログ内で他にtk.Checkbuttonを使う箇所は
    # 無いため、これだけで一覧行を過不足なく拾える。
    return [w for w in _walk_widgets(dlg) if isinstance(w, tk.Checkbutton)]


def _checkbox_bool(cb: tk.Checkbutton) -> bool:
    varname = cb.cget("variable")
    return bool(int(cb.getvar(varname)))


def _states_by_name(dlg) -> dict[str, bool]:
    return {cb.cget("text"): _checkbox_bool(cb) for cb in _row_checkbuttons(dlg)}


def _find_button(dlg, text: str) -> tk.Button:
    for w in _walk_widgets(dlg):
        if isinstance(w, tk.Button) and w.cget("text") == text:
            return w
    raise AssertionError(f"button not found: {text!r}")


# dev#1470: 表示名は始点(anchor)ボーン名。SAMPLE_CHAINSはHips始点を
# 尻尾/スカート前/スカート後の3チェーンが共有するため、重複行は直後の
# 最初のノードボーン名を括弧書きで添えて区別される(sway_chain_dialog.
# _display_name()参照)。
_SKIRT_F_DISPLAY = "J_Bip_C_Hips (Skirt_F_01)"
_TAIL_DISPLAY = "J_Bip_C_Hips (Tail_01)"
_EARL_DISPLAY = "J_Bip_C_Head (EarL_01)"
_EARR_DISPLAY = "J_Bip_C_Head (EarR_01)"
_SKIRT_B_DISPLAY = "J_Bip_C_Hips (Skirt_B_01)"
_HAIRBACK_DISPLAY = "J_Bip_C_Spine2"  # Spine2始点は他に重複が無いので単独表示


def _apply_user_edits_and_ok(hidden_root, app_root: str, avatar_path: str) -> None:
    """dev#19 SAMPLE_CHAINSに対し、既定OFFの1件をON・既定ONの1件をOFFへ
    ユーザー操作(チェックボックスinvoke)で変更してOKを押す。"""
    ctx = scd.SwayChainContext(
        app_root=app_root, work_root=app_root, avatar_path=avatar_path, sample_mode=True)
    dlg = scd.show_sway_chain_dialog(hidden_root, ctx)
    checkboxes = {cb.cget("text"): cb for cb in _row_checkbuttons(dlg)}
    assert _SKIRT_F_DISPLAY in checkboxes, "SAMPLE_CHAINSの構成が前提と違う"
    assert _TAIL_DISPLAY in checkboxes, "SAMPLE_CHAINSの構成が前提と違う"
    checkboxes[_SKIRT_F_DISPLAY].invoke()  # 既定OFF -> ON
    checkboxes[_TAIL_DISPLAY].invoke()  # 既定ON -> OFF
    _find_button(dlg, i18n.S("BtnOk")).invoke()  # save_config + destroy


def test_reopen_checkbox_states_match_saved_overrides(hidden_root, tmp_path):
    app_root = str(tmp_path)
    avatar_path = "C:\\fake.vrm"
    i18n.set_language("ja")

    _apply_user_edits_and_ok(hidden_root, app_root, avatar_path)

    ctx2 = scd.SwayChainContext(
        app_root=app_root, work_root=app_root, avatar_path=avatar_path, sample_mode=True)
    dlg2 = scd.show_sway_chain_dialog(hidden_root, ctx2)
    try:
        states = _states_by_name(dlg2)
        # ユーザーが変更した2件は、再オープン後もその変更が反映されている
        # こと(#1438の中心症状)。
        assert states[_SKIRT_F_DISPLAY] is True, (
            "既定OFFから明示的にONへ変えたチェーンが再オープンで反映されていない"
        )
        assert states[_TAIL_DISPLAY] is False, (
            "既定ONから明示的にOFFへ変えたチェーンが再オープンで反映されていない"
        )
        # 触っていない行は同定結果どおりの既定のまま。
        assert states[_EARL_DISPLAY] is True
        assert states[_EARR_DISPLAY] is True
        assert states[_SKIRT_B_DISPLAY] is False
        assert states[_HAIRBACK_DISPLAY] is False
    finally:
        dlg2.destroy()

    # ストア側(ディスク)の内容もチェックボックス表示と完全一致すること。
    saved = store.load_config(app_root, avatar_path)
    saved_by_last_bone = {e["bones"][-1]: e["enabled"] for e in saved}
    assert saved_by_last_bone.get("Skirt_F_02") is True
    assert saved_by_last_bone.get("Tail_03") is False
    # 触っていない行(既定のまま)はラボ憲章④により保存対象に含まれない。
    assert "EarL_02" not in saved_by_last_bone
    assert "Skirt_B_02" not in saved_by_last_bone


def test_negative_control_pre_fix_default_assumption_breaks_roundtrip(
    monkeypatch, hidden_root, tmp_path
):
    """負の対照(dev#1438): 修正前の_is_default_entry(既定enabledを常に
    Trueと決め打ち)へ差し替えると、上のシナリオが実際に食い違うことを
    確認する——このテストが「直っていないのに緑」にならないことの証拠。"""

    def _buggy_is_default_entry(entry):
        return (
            bool(entry.get("enabled", True))
            and entry.get("hardness", "follow") == "follow"
            and not entry.get("manual", False)
        )

    monkeypatch.setattr(store, "_is_default_entry", _buggy_is_default_entry)

    app_root = str(tmp_path)
    avatar_path = "C:\\fake.vrm"
    i18n.set_language("ja")

    _apply_user_edits_and_ok(hidden_root, app_root, avatar_path)

    ctx2 = scd.SwayChainContext(
        app_root=app_root, work_root=app_root, avatar_path=avatar_path, sample_mode=True)
    dlg2 = scd.show_sway_chain_dialog(hidden_root, ctx2)
    try:
        states = _states_by_name(dlg2)
        # 修正前ロジックでは、既定OFFから明示的にONへ変えたSkirt_F_02が
        # 「enabled=True・hardness=follow・manual=False」=旧既定と表面上
        # 一致するため保存対象から除外され、再オープン時に既定(False)へ
        # 巻き戻る。これが#1438の症状そのもの。
        assert states[_SKIRT_F_DISPLAY] is False, (
            "負の対照が機能していない: 旧ロジックでも巻き戻りが再現できていない"
        )
    finally:
        dlg2.destroy()
