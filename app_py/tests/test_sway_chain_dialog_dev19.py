# test_sway_chain_dialog_dev19.py -- dev#19揺れものUI(ラボ「揺れもの詳細
# 設定」ダイアログ)の言語切替追従の回帰テスト。
#
# 経緯: オーナー実機評価#4(work\rd_19_flight\briefs\uimock2_fixes.md)
# 「言語切替後も旧言語のまま残っていた」は、修正イテレーション2で
# i18n.register()の追加(ヘッダー3ラベル)と、rows_frame/manual_hardness_combo
# 向けの専用再描画トリガー登録で直したはずだが、「直した」ことを検証する
# 専用テストが無かった(2026-08-11 Masterライター統合レビューで発覚)。
#
# 兄弟機能 test_mesh_delete_dialog_dev1168.py::test_dialog_follows_language_switch
# のパターン(ダイアログを開いたまま i18n.apply_language() → 実表示の更新を
# 直接検証)を踏襲する。本ファイルはsway_chain_dialog固有の4要素を確認する:
#   1. ヘッダー3ラベル(on/名前/かたさ)のテキスト
#   2. 一覧行のかたさComboboxの選択肢(値そのものが新言語へ差し替わること)
#   3. 手動追加エリア(ラベル・かたさComboboxの選択肢)
#   4. 手動行の名前ラベルに付く「(手動)」タグの文言
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


def _label_texts(dlg) -> list[str]:
    """dev#1437(WP wp_labdlg_fix)で一覧行のon/名前列がtk.Checkbutton
    (text=name)へ統合された(旧: チェックボックス+別Labelの2ウィジェット)。
    行の名前文言(「(手動)」タグを含む)はもうtk.Labelには現れないため、
    tk.Checkbuttonのtextも合わせて収集する。"""
    texts = []
    for w in _walk_widgets(dlg):
        if isinstance(w, (tk.Label, tk.LabelFrame, tk.Checkbutton)):
            try:
                texts.append(w.cget("text"))
            except tk.TclError:
                pass
    return texts


def _comboboxes(dlg) -> list[ttk.Combobox]:
    return [w for w in _walk_widgets(dlg) if isinstance(w, ttk.Combobox)]


def _manual_and_row_combos(dlg) -> tuple[ttk.Combobox, list[ttk.Combobox]]:
    """manual_hardness_combo(親がtk.LabelFrameの`manual`枠)と、一覧行の
    かたさCombobox群(親がrows_frame配下のtk.Frame行)を区別して返す。
    言語切替のたび一覧行は`_rebuild_rows()`で作り直される(=古い参照は
    破棄済みウィジェットになる)ため、呼び出しごとに毎回ツリーを引き直す
    必要がある点に注意(このヘルパーを都度呼び直す設計にしている理由)。"""
    manual_combo = None
    row_combos: list[ttk.Combobox] = []
    for cb in _comboboxes(dlg):
        if isinstance(cb.master, tk.LabelFrame):
            manual_combo = cb
        else:
            row_combos.append(cb)
    return manual_combo, row_combos


def _hardness_display(lang: str) -> list[str]:
    return [i18n.S(scd._HARDNESS_KEYS[h], lang) for h in scd.HARDNESS_CHOICES]


def test_sway_chain_dialog_follows_language_switch(hidden_root, tmp_path):
    avatar_path = "C:\\fake.vrm"
    # 手動追加行(「(手動)」タグの実表示チェック用)を1件、あらかじめ保存
    # しておく。sample_mode=Trueのカタログ行と合わせて働作業セットへ合成される。
    scd.save_config(str(tmp_path), avatar_path, [
        {"bones": ["ManualBoneX"], "enabled": True, "hardness": "hard", "manual": True},
    ])

    i18n.set_language("ja")
    ctx = scd.SwayChainContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path=avatar_path,
        sample_mode=True,
    )
    dlg = scd.show_sway_chain_dialog(hidden_root, ctx)
    try:
        # ---- ja(開いた直後)のベースライン ----
        assert dlg.title() == i18n.S("LabSwayChainDialogTitle", "ja")
        ja_texts = _label_texts(dlg)
        assert i18n.S("LabSwayChainColOn", "ja") in ja_texts
        assert i18n.S("LabSwayChainColName", "ja") in ja_texts
        assert i18n.S("LabSwayChainColHardness", "ja") in ja_texts
        assert i18n.S("LabSwayChainManualLabel", "ja") in ja_texts

        ja_manual_combo, ja_row_combos = _manual_and_row_combos(dlg)
        assert ja_manual_combo is not None
        assert ja_row_combos, "検証には一覧行が最低1行必要(--sample未反映?)"
        ja_display = _hardness_display("ja")
        assert list(ja_manual_combo.cget("values")) == ja_display
        for cb in ja_row_combos:
            assert list(cb.cget("values")) == ja_display

        ja_manual_tag = i18n.S("LabSwayChainManualTag", "ja")
        assert any(ja_manual_tag in t for t in ja_texts), (
            "手動行の「(手動)」タグがja表示で見つからない"
        )

        # ---- ダイアログを開いたまま英語へ切り替え ----
        i18n.apply_language("en")
        try:
            assert dlg.title() == i18n.S("LabSwayChainDialogTitle", "en")
            en_texts = _label_texts(dlg)
            assert i18n.S("LabSwayChainColOn", "en") in en_texts
            assert i18n.S("LabSwayChainColName", "en") in en_texts
            assert i18n.S("LabSwayChainColHardness", "en") in en_texts
            assert i18n.S("LabSwayChainManualLabel", "en") in en_texts

            en_manual_combo, en_row_combos = _manual_and_row_combos(dlg)
            assert en_manual_combo is not None
            assert en_row_combos, "言語切替後に一覧行が消えている(再描画の破損)"
            en_display = _hardness_display("en")
            assert list(en_manual_combo.cget("values")) == en_display
            for cb in en_row_combos:
                assert list(cb.cget("values")) == en_display

            en_manual_tag = i18n.S("LabSwayChainManualTag", "en")
            assert any(en_manual_tag in t for t in en_texts), (
                "手動行の「(手動)」相当タグが言語切替後(en)で見つからない"
            )
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()


def test_language_switch_regression_scanner_catches_missing_register(monkeypatch, hidden_root, tmp_path):
    # 負の対照: header の3ラベルへのi18n.register()呼び出しをこのテスト内で
    # 無効化した状態で本テストの検証ロジックを再現し、実際に検出できる
    # (=このテストが「直っていないのに緑」にならない)ことを確認する。
    orig_register = i18n.register

    def _register_but_skip_headers(widget, key, setter=i18n.default_text_setter):
        if key in ("LabSwayChainColOn", "LabSwayChainColName", "LabSwayChainColHardness"):
            # 初期テキストだけ設定し、登録簿には加えない
            # (=以後のapply_language()で更新されなくなる、旧不具合の再現)
            setter(widget, i18n.S(key))
            return
        orig_register(widget, key, setter)

    monkeypatch.setattr(scd, "i18n", i18n)  # noop, keeps reference explicit
    monkeypatch.setattr(i18n, "register", _register_but_skip_headers)

    i18n.set_language("ja")
    ctx = scd.SwayChainContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm",
        sample_mode=True,
    )
    dlg = scd.show_sway_chain_dialog(hidden_root, ctx)
    try:
        i18n.apply_language("en")
        try:
            en_texts = _label_texts(dlg)
            # register()が壊れている状態では、ヘッダーの英語文言が反映されない
            # (旧ja文言が残ったまま)ことを確認する = このテストのロジックは
            # 実際に不具合を検出できる。
            assert i18n.S("LabSwayChainColOn", "en") not in en_texts
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()
