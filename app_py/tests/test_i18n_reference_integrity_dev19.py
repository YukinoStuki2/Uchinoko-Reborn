# test_i18n_reference_integrity_dev19.py -- work\rd_19_flight\briefs\
# uimock2_fixes.md 評価#6(オーナー実機確認: 「英語時にラボpopupの翻訳が
# 混在(訳されたり・されなかったり)」)の恒久化テスト。
#
# 経緯: 実機(WSB)確認の結果、揺れものUI自体(標準スライダー・ラボ
# 「揺れもの詳細設定」ダイアログ)には翻訳漏れが無かった(全キー5言語完備・
# 英語モードでのCJK残留ゼロを本ファイルのテストで再現・確認済み)。実際に
# 混在して見えた原因は、無関係の別経路
# (blender_setup.do_ensure_blender_ready()のDEV_NOT_FOUND_NO_SCRIPT分岐)が
# i18n_data.jsonを一切経由しない生の日本語文字列をPython側から直接返して
# いたこと(blender_setup.py側で修正済み、test_untranslated_gui_dev939.py
# に負の対照込みの回帰テストを追加済み)。
#
# なぜ既存のtest_i18n_keys.py::test_table_all_keys_all_languages_non_empty
# が緑のまま見逃したか: あのテストは「i18n.TABLEに**登録済みの**キー」を
# 全走査して5言語完備を確認するものであり、①ソースコードがTABLEに**存在
# しないキー名**を参照した場合(タイプミス等、i18n.S()は"??key??"マーカーを
# 返すだけで例外にならない)と、②i18n.TABLEを一切経由しない生の
# ハードコード文字列(今回の実例)の2種類の穴を構造的に検出できない
# (「走査範囲の狭さが繰り返しの穴」というこのプロジェクトの既知の教訓、
# CLAUDE.md「検証の作法」節)。
#
# 本ファイルはこの2種類の穴を、揺れものUI(dev#19)を中心に機械的に塞ぐ:
#   1. app_py/*.py + app_py/ui/*.py 全体で、i18n.S()/F()/register()へ
#      リテラルで渡されたキー名が実際にi18n.TABLEへ存在すること(①の穴)。
#   2. 揺れものUI固有のキー定数リスト(dev#1508 W2bで「ゆらす」トグル用
#      LabelSwayEnable/TipSwayEnableへ差し替え。旧SWAY_INTENSITY_I18N_KEYSは
#      main_window.pyから削除済み/_HARDNESS_KEYS。ループ変数経由でi18n.S()へ
#      渡されるため上記1のリテラル走査では拾えない)が5言語とも完備している
#      こと。
#   3. ラボ「揺れもの詳細設定」ダイアログを実際に(hidden_root配下、画面には
#      一切表示しない)構築し、英語モードでCJK(ひらがな・カタカナ・漢字)
#      文字列が1つも残っていないことを検証する(②の穴。「このダイアログ
#      経路がテストの走査対象外だった」を実際に塞ぐ)。
from __future__ import annotations

import ast
import glob
import os
import re
import sys
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import sway_chain_dialog  # noqa: E402

_CJK = re.compile(r"[぀-ヿ一-鿿]")


# ---------------------------------------------------------------------------
# 1. リテラルキー参照の存在確認(app_py全体、揺れものUIに限らない汎用網)
# ---------------------------------------------------------------------------

def _referenced_i18n_keys(path: str) -> set[str]:
    """i18n.S("Key")/i18n.F("Key", ...)/i18n.register(widget, "Key", ...)の
    ように、キー名が文字列リテラルで直接渡されている呼び出しだけを拾う
    (変数経由の間接参照は対象外――静的解析の限界、docstringに明記のとおり
    リテラル参照網羅だけでも既存の「登録済みキーの完全性検査」と対になる
    実質的なカバレッジ拡大になる)。"""
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src, filename=path)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr in ("S", "F", "register")
            and isinstance(func.value, ast.Name)
            and func.value.id == "i18n"
        ):
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(
            node.args[0].value, str
        ):
            keys.add(node.args[0].value)
    return keys


def _all_gui_and_toplevel_source_files() -> list[str]:
    files = sorted(glob.glob(os.path.join(_APP_PY_DIR, "*.py")))
    files += sorted(glob.glob(os.path.join(_APP_PY_DIR, "ui", "*.py")))
    return files


def test_all_literal_i18n_key_references_exist_in_table():
    missing: list[tuple[str, str]] = []
    for path in _all_gui_and_toplevel_source_files():
        for key in _referenced_i18n_keys(path):
            if key not in i18n.TABLE:
                missing.append((os.path.relpath(path, _APP_PY_DIR), key))
    assert not missing, (
        f"存在しないi18nキーを参照している(タイプミスの可能性): {missing}"
    )


def test_reference_integrity_scanner_catches_nonexistent_key_injection():
    # 負の対照: 存在しないキーへの参照を実際に埋め込んだ一時ファイルを
    # 走査させ、検出できることを確認する。
    import tempfile
    src = (
        'import i18n\n'
        'i18n.S("__this_key_definitely_does_not_exist_dev19__")\n'
    )
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(src)
        tmp_path = f.name
    try:
        keys = _referenced_i18n_keys(tmp_path)
        assert "__this_key_definitely_does_not_exist_dev19__" in keys
        assert "__this_key_definitely_does_not_exist_dev19__" not in i18n.TABLE
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# 2. 揺れものUI固有のキー定数リスト(ループ変数経由でi18n.S()へ渡るため
#    上記1のリテラル走査では拾えない)の5言語完備を明示的に確認する。
#
# dev#1508 W2b(2026-08-16裁定、.devonly\docs\sway\sway_wrapup\SPEC.md §1): 標準機能
# 「揺れの度合い」(4段、SWAY_INTENSITY_I18N_KEYS)はON/OFFトグルへ置換され、
# 定数自体がmain_window.pyから削除された(既存のSwayIntensity*キー自体は
# ラボ「揺れもの詳細」パネル側=sway_chain_dialog.py/sway_style_dialog.py
# が今も使うためi18n_data.jsonからは削除していない――下記
# test_sway_chain_hardness_i18n_keys_all_five_languages_completeが
# Hard/Normal/Softの3つはカバーする)。本テストは新トグル用キー
# (LabelSwayEnable/TipSwayEnable)の5言語完備確認へ差し替える。
# ---------------------------------------------------------------------------

def test_sway_enable_toggle_i18n_keys_all_five_languages_complete():
    for key in ("LabelSwayEnable", "TipSwayEnable"):
        assert key in i18n.TABLE, f"{key} が i18n.TABLE に無い"
        for lang in i18n.LANGS:
            assert i18n.TABLE[key].get(lang), f"{key}/{lang} が空"


def test_sway_chain_hardness_i18n_keys_all_five_languages_complete():
    for hardness, key in sway_chain_dialog._HARDNESS_KEYS.items():
        assert key in i18n.TABLE, f"hardness={hardness!r} のキー {key} が無い"
        for lang in i18n.LANGS:
            assert i18n.TABLE[key].get(lang), f"{key}/{lang} が空"


# ---------------------------------------------------------------------------
# 3. 実ダイアログを実際に構築し(hidden_root配下、画面には一切表示しない、
#    dev#672/dev#855契約どおり)、英語モードでCJK残留が無いことを検証する。
# ---------------------------------------------------------------------------

def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


def _cjk_offenders(widget) -> list[tuple[str, str]]:
    offenders = []
    for w in _walk_widgets(widget):
        try:
            txt = w.cget("text")
        except tk.TclError:
            continue
        if isinstance(txt, str) and _CJK.search(txt):
            offenders.append((str(w), txt))
    return offenders


def test_sway_chain_dialog_no_cjk_leak_under_english_mode(hidden_root):
    i18n.set_language("en")
    try:
        ctx = sway_chain_dialog.SwayChainContext(
            app_root=_APP_PY_DIR,
            work_root=os.path.join(_APP_PY_DIR, "work"),
            avatar_path="",
            sample_mode=True,
        )
        dlg = sway_chain_dialog.show_sway_chain_dialog(hidden_root, ctx)
        try:
            offenders = _cjk_offenders(dlg)
            assert not offenders, (
                "英語モードなのにラボ「揺れもの詳細設定」ダイアログへ"
                f"日本語(CJK)が残っている: {offenders}"
            )
        finally:
            dlg.destroy()
    finally:
        i18n.set_language("ja")


def test_sway_chain_dialog_no_cjk_leak_under_english_mode_empty_state(hidden_root):
    # --sample無し(空状態表示)の経路も別途確認する(評価#6「空状態文言含む」)。
    i18n.set_language("en")
    try:
        ctx = sway_chain_dialog.SwayChainContext(
            app_root=_APP_PY_DIR,
            work_root=os.path.join(_APP_PY_DIR, "work"),
            avatar_path="",
            sample_mode=False,
        )
        dlg = sway_chain_dialog.show_sway_chain_dialog(hidden_root, ctx)
        try:
            offenders = _cjk_offenders(dlg)
            assert not offenders, (
                "英語モードなのに空状態表示へ日本語(CJK)が残っている: "
                f"{offenders}"
            )
        finally:
            dlg.destroy()
    finally:
        i18n.set_language("ja")


def test_cjk_leak_scanner_catches_injected_japanese_negative_control(hidden_root):
    # 負の対照: ダイアログへ意図的に生の日本語ラベルを1個追加した状態で、
    # 上記スキャナ(_cjk_offenders)が実際に検出できることを確認する。
    i18n.set_language("en")
    try:
        ctx = sway_chain_dialog.SwayChainContext(
            app_root=_APP_PY_DIR,
            work_root=os.path.join(_APP_PY_DIR, "work"),
            avatar_path="",
            sample_mode=True,
        )
        dlg = sway_chain_dialog.show_sway_chain_dialog(hidden_root, ctx)
        try:
            tk.Label(dlg, text="意図的に混入した日本語").pack()
            offenders = _cjk_offenders(dlg)
            assert offenders, "意図的に混入した日本語がスキャナで検出されなかった"
        finally:
            dlg.destroy()
    finally:
        i18n.set_language("ja")
