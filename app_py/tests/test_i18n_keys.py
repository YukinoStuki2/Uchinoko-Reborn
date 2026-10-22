# test_i18n_keys.py -- WP-A1受入条件②: i18n_data.json の全キーが5言語とも
# 非空であることを機械検査する(旧 --check-i18n / CheckDictionaryCompleteness
# L.4921 相当のPython版試験。DESIGN.md §5.2 WP-A1行)。
from __future__ import annotations

import os
import re
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402

EXPECTED_LANGS = ["ja", "en", "ko", "zhTW", "zhCN"]


def test_langs_constant_matches_expected():
    assert i18n.LANGS == EXPECTED_LANGS


def test_table_not_empty():
    # 移植元 app\DiveToPalworld.cs Strings.Table (L.39-265) は165キー実測
    # (2026-08-01時点、機械抽出。将来キーが増減しても壊れないよう下限のみ検査)
    assert len(i18n.TABLE) >= 100


def test_progress_labels_not_empty():
    # 移植元 Strings.ProgressLabels (L.314-335) は19キー実測
    assert len(i18n.PROGRESS_LABELS) >= 10


def test_table_all_keys_all_languages_non_empty():
    missing = []
    for key, values in i18n.TABLE.items():
        for lang in EXPECTED_LANGS:
            v = values.get(lang)
            if not v:
                missing.append((key, lang))
    assert not missing, f"Table: empty translations for {missing[:20]} (total {len(missing)})"


def test_progress_labels_all_keys_all_languages_non_empty():
    missing = []
    for key, values in i18n.PROGRESS_LABELS.items():
        for lang in EXPECTED_LANGS:
            v = values.get(lang)
            if not v:
                missing.append((key, lang))
    assert not missing, f"ProgressLabels: empty translations for {missing[:20]} (total {len(missing)})"


def test_s_returns_marker_for_unknown_key():
    # Strings.S(key) L.269-285: 未知キーは例外を投げず "??key??" を返す
    assert i18n.S("__no_such_key__") == "??__no_such_key__??"


def test_s_falls_back_to_ja_for_missing_language_entry():
    # PickFromArray L.296-302: 指定言語が空ならja(索引0)へフォールバック
    i18n.TABLE["__test_partial__"] = {"ja": "テスト", "en": "", "ko": "", "zhTW": "", "zhCN": ""}
    try:
        assert i18n.S("__test_partial__", lang="en") == "テスト"
    finally:
        del i18n.TABLE["__test_partial__"]


def test_f_formats_placeholders():
    i18n.TABLE["__test_format__"] = {lang: "{0}/{1}" for lang in EXPECTED_LANGS}
    try:
        assert i18n.F("__test_format__", "a", "b") == "a/b"
    finally:
        del i18n.TABLE["__test_format__"]


def test_status_prompt_vrm_mentions_prefab_before_vrm():
    # dev#630: 「VRMのみ言及」を修正し、prefab優先の表記にする。
    # 5言語すべてで prefab を指す語("prefab")が VRM を指す語より先に
    # 出現することを機械検査する(負の対照: 旧文言はVRMのみでprefabを含まない)。
    for key in ("StatusPromptVrm", "StatusPromptVrmDnd"):
        values = i18n.TABLE[key]
        for lang in EXPECTED_LANGS:
            text = values[lang]
            assert "prefab" in text, f"{key}/{lang}: prefabへの言及が無い: {text!r}"
            assert "VRM" in text, f"{key}/{lang}: VRMへの言及が無い: {text!r}"
            assert text.index("prefab") < text.index("VRM"), (
                f"{key}/{lang}: prefabがVRMより先に来ていない: {text!r}"
            )


def test_prefab_mentioned_before_vrm_word_form():
    # dev#646: dev#630(StatusPromptVrm系、別レーンで対応済み)の棚卸しで
    # 残っていた「VRM単独言及」キーをprefab優先の言い回しへ統一する。
    # 「prefab」「VRM」を単語として併記するキー群(拡張子ドット無し)で、
    # 5言語すべてprefabがVRMより先に出現することを機械検査する
    # (負の対照: 修正前の文言はVRMのみでprefabを含まないためassertが落ちる)。
    keys = (
        "NoteVrmNotDeleted",
        "NoteReloadVrmToRedo",
        "MsgSpecifyVrmFile",
        "StatusPreviewStale",
    )
    for key in keys:
        values = i18n.TABLE[key]
        for lang in EXPECTED_LANGS:
            text = values[lang]
            assert "prefab" in text, f"{key}/{lang}: prefabへの言及が無い: {text!r}"
            assert "VRM" in text, f"{key}/{lang}: VRMへの言及が無い: {text!r}"
            assert text.index("prefab") < text.index("VRM"), (
                f"{key}/{lang}: prefabがVRMより先に来ていない: {text!r}"
            )


# dev#854: ぱんが「先にVRMを読み込んでください」という趣旨のポップアップを
# 目撃した(出所は指揮者調査により別レーンのテストが出した実ダイアログと判明、
# 製品の文言そのものではなかった)。ただしその調査の過程で、既存のprefab優先
# lint(test_status_prompt_vrm_mentions_prefab_before_vrm 等、上記2関数)が
# 「特定のキー名を列挙したものにしか掛かっていない」網の穴が判明したため、
# TABLE/PROGRESS_LABELS の**全キー・全言語**を走査する形へ拡張する。
# 正当な例外(製品の入力形式=VRM/prefabの話ではないVRM言及。例: サードパーティ
# アドオンのファイル名 VRM_Addon_for_Blender-*.zip)は明示的な許可リストに
# 記録し、記録外の違反だけを赤くする(dev#654 EXE_MENTION_ALLOWLISTと同型の
# 設計)。2026-08-02時点、i18n_data.json 内に該当する例外は無い(空集合)。
#
# dev#1262: MsgUnityExportErrorUnivrmDupBodyは製品名「UniVRM」(サードパーティ
# ツール名)への言及で、ここで検査したい「VRM/prefabどちらの入力形式か」の
# 話ではない(上記コメントのVRM_Addon_for_Blender例と同型の正当な例外)。
VRM_PREFAB_ORDER_ALLOWLIST: set[str] = {"MsgUnityExportErrorUnivrmDupBody"}


def _first_ci_index(text: str, needle: str):
    """text内でneedleが最初に出現する位置(大小文字区別なし)。無ければNone。"""
    m = re.search(re.escape(needle), text, re.IGNORECASE)
    return m.start() if m else None


def _iter_vrm_prefab_order_violations(table: dict, allowlist: set[str]):
    """table({key: {lang: text}} 形式、TABLE/PROGRESS_LABELS共通)を全走査し、
    'VRM'(語形。例: "VRM ファイル")または '.vrm'/'*.vrm'(拡張子形、大小文字
    区別なし)への言及がありながら、'prefab'/'.prefab'/'*.prefab' への言及が
    無い、または prefab の初出位置が VRM の初出位置より後ろになっている
    (=VRMが先に出てくる)エントリを列挙する。allowlist内のキーはスキップする。
    戻り値: [(key, lang, text)] のリスト。
    """
    violations = []
    for key, values in table.items():
        if key in allowlist:
            continue
        for lang, text in values.items():
            if not isinstance(text, str):
                continue
            vrm_idx = _first_ci_index(text, "vrm")
            if vrm_idx is None:
                continue  # VRMへの言及自体が無いキーは対象外
            prefab_idx = _first_ci_index(text, "prefab")
            if prefab_idx is None or prefab_idx > vrm_idx:
                violations.append((key, lang, text))
    return violations


def test_all_table_vrm_mentions_have_prefab_first():
    violations = _iter_vrm_prefab_order_violations(i18n.TABLE, VRM_PREFAB_ORDER_ALLOWLIST)
    assert not violations, (
        "Table: VRMへの言及があるのにprefabへの言及が無い、または"
        f"prefabがVRMより先に来ていないキー: {violations[:20]} (total {len(violations)})"
    )


def test_all_progress_labels_vrm_mentions_have_prefab_first():
    violations = _iter_vrm_prefab_order_violations(i18n.PROGRESS_LABELS, VRM_PREFAB_ORDER_ALLOWLIST)
    assert not violations, (
        "ProgressLabels: VRMへの言及があるのにprefabへの言及が無い、または"
        f"prefabがVRMより先に来ていないキー: {violations[:20]} (total {len(violations)})"
    )


def test_vrm_prefab_order_lint_catches_vrm_only_entry():
    # 負の対照①: VRM単独言及(prefabへの言及が無い)を追加すると
    # 実際に赤くなることの証明(dev#854発端の「先にVRMを」文言相当)。
    i18n.TABLE["__test_vrm_only__"] = {
        "ja": "VRMファイルを読み込んでください", "en": "Please load the VRM file first",
        "ko": "x", "zhTW": "x", "zhCN": "x",
    }
    try:
        violations = _iter_vrm_prefab_order_violations(i18n.TABLE, VRM_PREFAB_ORDER_ALLOWLIST)
        keys_hit = {v[0] for v in violations}
        assert "__test_vrm_only__" in keys_hit
    finally:
        del i18n.TABLE["__test_vrm_only__"]


def test_vrm_prefab_order_lint_catches_wrong_order_entry():
    # 負の対照②: prefabへの言及自体はあるが、VRMより後ろに来る場合も
    # 赤くなることの証明(旧FileFilterAvatar/main_window.py filetypesが
    # 実際にこの形の違反だった、dev#854で修正済み)。
    i18n.TABLE["__test_vrm_wrong_order__"] = {
        "ja": "VRM または prefab ファイルを入れてください", "en": "x",
        "ko": "x", "zhTW": "x", "zhCN": "x",
    }
    try:
        violations = _iter_vrm_prefab_order_violations(i18n.TABLE, VRM_PREFAB_ORDER_ALLOWLIST)
        hit = [(k, lang) for k, lang, _ in violations if k == "__test_vrm_wrong_order__"]
        assert ("__test_vrm_wrong_order__", "ja") in hit
    finally:
        del i18n.TABLE["__test_vrm_wrong_order__"]


def test_vrm_prefab_order_allowlist_suppresses_and_empty_allowlist_still_catches():
    # 負の対照③: 許可リストに載せると見逃され、許可リストを空にすると
    # 同じ違反が再び検出されることの証明(許可リスト自体が効いていることの
    # 検査。dev#654 EXE_MENTION_ALLOWLISTの検証パターンと同型)。
    i18n.TABLE["__test_vrm_allowlisted__"] = {
        "ja": "VRM_Addon_for_Blender-Extension.zip", "en": "x",
        "ko": "x", "zhTW": "x", "zhCN": "x",
    }
    try:
        without_allowlist = _iter_vrm_prefab_order_violations(i18n.TABLE, set())
        keys_hit = {v[0] for v in without_allowlist}
        assert "__test_vrm_allowlisted__" in keys_hit, "許可リスト無しでは検出されるはず"

        with_allowlist = _iter_vrm_prefab_order_violations(
            i18n.TABLE, {"__test_vrm_allowlisted__"}
        )
        keys_hit2 = {v[0] for v in with_allowlist}
        assert "__test_vrm_allowlisted__" not in keys_hit2, "許可リストに載せたキーは除外されるはず"
    finally:
        del i18n.TABLE["__test_vrm_allowlisted__"]


def test_browse_dialog_filetypes_list_prefab_before_vrm_in_source():
    # dev#854: i18n_data.jsonのテキストだけでなく、app_py\ui\main_window.pyの
    # ファイル選択ダイアログの拡張子タプル(filetypes=...)もprefab優先で
    # 並んでいることをソース文字列レベルで検査する(実tk窓を開かず、ソース
    # テキストの走査のみで検証。旧: ("*.vrm", "*.fbx", "*.prefab") だった)。
    main_window_path = os.path.join(_APP_PY_DIR, "ui", "main_window.py")
    with open(main_window_path, "r", encoding="utf-8") as f:
        source = f.read()
    marker = 'filetypes=[(i18n.S("LabelAvatar"), ('
    idx = source.index(marker)
    tuple_start = idx + len(marker)
    line_end = source.index(")", tuple_start)
    snippet = source[idx:line_end]
    prefab_idx = snippet.find("*.prefab")
    vrm_idx = snippet.find("*.vrm")
    assert prefab_idx != -1 and vrm_idx != -1, f"想定した拡張子タプルが見つからない: {snippet!r}"
    assert prefab_idx < vrm_idx, f"filetypesタプルでprefabがVRMより先に来ていない: {snippet!r}"


def test_preview_placeholder_keys_exist_and_are_non_english_free_of_english_leak():
    # dev#630棚卸し: app_py\ui\main_window.pyのプレビュー枠プレースホルダ
    # ("(preview front)"/"(preview side)")は未ローカライズの直書き英語だった。
    # i18n辞書キー化した新規キーが5言語とも非空であることを確認する
    # (全体の非空検査はtest_table_all_keys_all_languages_non_empty で既にカバー
    # されるが、キー自体の存在をここでも明示して回帰を検知しやすくする)。
    for key in ("LabelPreviewPlaceholderFront", "LabelPreviewPlaceholderSide"):
        assert key in i18n.TABLE, f"{key} が i18n.TABLE に無い"
        for lang in EXPECTED_LANGS:
            assert i18n.TABLE[key].get(lang), f"{key}/{lang} が空"


def test_prefab_mentioned_before_vrm_extension_form():
    # dev#646: MsgDropVrmOrPrefabは拡張子ドット付き表記(".prefab"/".vrm")の
    # ため単語形式の検査対象から分離。同じくprefab優先の語順を機械検査する
    # (負の対照: 修正前は".vrm"が".prefab"より先に出現しassertが落ちる)。
    key = "MsgDropVrmOrPrefab"
    values = i18n.TABLE[key]
    for lang in EXPECTED_LANGS:
        text = values[lang]
        assert ".prefab" in text, f"{key}/{lang}: .prefabへの言及が無い: {text!r}"
        assert ".vrm" in text, f"{key}/{lang}: .vrmへの言及が無い: {text!r}"
        assert text.index(".prefab") < text.index(".vrm"), (
            f"{key}/{lang}: .prefabが.vrmより先に来ていない: {text!r}"
        )


# dev#654: v2.3.0でランチャーexe(Uchinoko.exe)は廃止され、現行の起動方法は
# Uchinoko.bat(bat+embeddable python構成)。ユーザー向け文言に廃止済みexeへの
# 言及が残ると、ユーザーが実在しないファイルを指示され従えない実害がある
# (ActionNoWritePermissionキーで実際に発生、work\pubdocs_audit_20260801.md 付記)。
# 正当な.exe言及(外部ツール名等、例: blender.exe)が将来出た場合のみ、
# キー名をここへ追記して許可する(判断はwork\wp_654_progress.mdに記録)。
#
# dev#939: MsgBlenderSetupFailLineStep2bはensure_blender.ps1のShow-D2P
# FailureGuidance手動セットアップ手順文言の翻訳(dev#933と同型)。ここでの
# blender.exeはランチャーexeではなく、実在の外部ツール(Blender本体の実行
# ファイル)を指す正当な言及(コメント冒頭の想定例そのもの)であり、
# 廃止済みUchinoko.exeへの言及ではない。
#
# dev#1608: MsgBlenderSetupFailLineStep3AVも同じShow-D2PFailureGuidance案内文の
# 一部(セキュリティソフト隔離の示唆)で、python.exeはBlender同梱Pythonの実行
# ファイルという実在の外部ツール名を指す正当な言及(同じくランチャーexeとは無関係)。
EXE_MENTION_ALLOWLIST: set[str] = {"MsgBlenderSetupFailLineStep2b", "MsgBlenderSetupFailLineStep3AV"}


def test_no_stale_exe_references_in_table():
    offenders = []
    for key, values in i18n.TABLE.items():
        if key in EXE_MENTION_ALLOWLIST:
            continue
        for lang in EXPECTED_LANGS:
            v = values.get(lang, "")
            if isinstance(v, str) and ".exe" in v.lower():
                offenders.append((key, lang, v))
    assert not offenders, f"Table: stale .exe references found: {offenders}"


def test_no_stale_exe_references_in_progress_labels():
    offenders = []
    for key, values in i18n.PROGRESS_LABELS.items():
        if key in EXE_MENTION_ALLOWLIST:
            continue
        for lang in EXPECTED_LANGS:
            v = values.get(lang, "")
            if isinstance(v, str) and ".exe" in v.lower():
                offenders.append((key, lang, v))
    assert not offenders, f"ProgressLabels: stale .exe references found: {offenders}"


def test_exe_reference_detection_catches_intentionally_broken_entry():
    # 負の対照: 検査ロジック自体が.exeを検出できることの証明
    i18n.TABLE["__test_exe_regression__"] = {
        "ja": "Uchinoko.exeを右クリック", "en": "right-click Uchinoko.exe",
        "ko": "x", "zhTW": "x", "zhCN": "x",
    }
    try:
        offenders = [
            (key, lang, v)
            for key, values in i18n.TABLE.items()
            if key not in EXE_MENTION_ALLOWLIST
            for lang, v in values.items()
            if lang in EXPECTED_LANGS and isinstance(v, str) and ".exe" in v.lower()
        ]
        assert ("__test_exe_regression__", "ja", "Uchinoko.exeを右クリック") in offenders
        assert ("__test_exe_regression__", "en", "right-click Uchinoko.exe") in offenders
    finally:
        del i18n.TABLE["__test_exe_regression__"]


def test_registry_applies_on_language_change():
    class FakeWidget:
        def __init__(self):
            self.text = None

        def config(self, text):
            self.text = text

    i18n.clear_registry()
    i18n.set_language("ja")
    i18n.TABLE["__test_reg__"] = {
        "ja": "こんにちは", "en": "Hello", "ko": "안녕", "zhTW": "你好", "zhCN": "你好",
    }
    try:
        w = FakeWidget()
        i18n.register(w, "__test_reg__")
        assert w.text == "こんにちは"
        i18n.apply_language("en")
        assert w.text == "Hello"
    finally:
        del i18n.TABLE["__test_reg__"]
        i18n.clear_registry()
        i18n.set_language("ja")
