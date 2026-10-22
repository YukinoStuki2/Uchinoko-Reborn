# test_forbidden_words_dev1263.py -- dev#1263: GUI・ユーザー向け文言の禁止語
# テスト。オーナー恒久指示(2026-08-09、複数回目の指摘): 「輸出」は誤り、
# 正しくは「エクスポート」。記憶ベースでは再発しているため、仕組み(テスト)
# で構造的に禁止する。
#
# 対象(issue本文どおり):
#   1. i18n辞書(app_py\i18n_data.json)のユーザー向け文字列
#   2. GUIソース(app_py\ui\*.py、および app_py 直下のユーザー向け文言/診断ログ
#      文言を組み立てるモジュール)の文字列リテラル
# 対象外: 開発者向け内部文書・コード内コメント・docstring・devtools・.devonly。
#
# 実装上の解釈(2026-08-09、本WP実装者による解釈。曖昧点として完了報告にも明記):
#   「輸出」は日本語では貿易の意味で誤用だが、繁体字/簡体字中国語では
#   「輸出/输出」がexport/outputの正当な訳語として現に使われている
#   (i18n_data.json の LogUnityExportHeartbeatFormat/MsgUnityExportNoFbxFormat
#   zhTW実測)。したがってi18n辞書側の禁止語検査は "ja" 言語のみを対象にする
#   (他言語まで一律に禁止すると中国語の正当な訳語を誤検出する)。
#
#   GUIソース側は、コメント/docstringは開発者向け(issueの対象外)、それ以外の
#   文字列リテラルはast経由でユーザー向けの可能性がある文言として扱う
#   (現状の監査では該当ゼロ。将来の直書き文言の混入を検出する安全網)。
from __future__ import annotations

import ast
import glob
import os
import sys

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402

# 禁止語リスト(将来の追加に備えて定数リスト化。dev#1263時点は「輸出」1語)。
# 正しい語形は CORRECT_FORM_HINT にだけ記録する(assert文言用、判定には使わない)。
#
# 2026-08-09追加(オーナー裁定): ラボダイアログの個別但し書きに「実験的機能」
# 「サポート対象外」と書くこと自体を禁止(温度感はダイアログの機能説明のみに
# 統一し、実験的である旨はラボ窓/メイン窓の共通警告[LabWarningActive]が
# 一括で担う)。同日、ユーザーに意味の通じない開発者語彙として「旧」「従来」も
# 追加(「旧方式」「DTフラグ方式」等、ユーザー視点では「何が変わるか」が
# 分かる動作の言葉に置き換える)。
#
# 「旧」「従来」は1文字/2文字で誤ヒットしうるため、追加前にi18n_data.jsonの
# ja全エントリを実走査した(本WP実装時点)。結果は「旧」2件・「従来」2件の
# 計4件のみで、いずれもLabDtFlagHeadHideCheckboxLabel/Summary(旧方式表記)・
# LabDtFlagHeadHideHint/LabHeadEquipToggleHint(従来方式/従来どおり表記)という
# 本物の該当だった(誤検知ゼロ)。したがって「旧方式」のような複合語限定に
# 絞る必要はなく、単独文字/単語のまま登録する(誤ヒットが多ければ複合語へ
# 絞る判断だったが、今回は不要だった)。
#
# 2026-08-11追加(オーナーUX評価#3/#4、work\rd_19_flight\briefs\
# uimock2_fixes.md「構造化」節): 「検体」(開発者語彙、ユーザーUIには
# 「アバター」を使う)と「骨の名前」(3D/リギング文脈では「ボーンの名前」が
# ユーザーに馴染む語、既存のLabDropBonesCatalogUnavailableNotice等も
# 「ボーン」表記で統一済み)を追加する。
#
# 「骨の名前」は複合語限定にした(単独の「骨」は「骨格」(Armature、
# i18n_data.json内に複数の正当な用例あり――dev#906の複数骨格説明・
# LabDropBonesAllSelectedWarningの「骨格が全損」等)を誤検知するため、
# 「旧」「従来」のときと違い実測で複合語限定が必要と判明した実例)。
# 追加前にi18n_data.jsonのja全エントリを実走査(本WP実装時点)し、
# 「検体」2件・「骨の名前」3件の計5件のみで、いずれも本WPが
# 「アバター」/「ボーンの名前」へ修正済みの箇所だった(誤検知ゼロ)。
FORBIDDEN_WORDS: list[str] = [
    "輸出", "サポート対象外", "実験的機能", "旧", "従来", "検体", "骨の名前",
]
CORRECT_FORM_HINT: dict[str, str] = {
    "輸出": "エクスポート",
    "サポート対象外": "(書かない。機能説明のみにする)",
    "実験的機能": "(書かない。ラボ共通警告[LabWarningActive]が一括で担う)",
    "旧": "(「〜のとき」「これまでは」等、動作の言葉で説明する)",
    "従来": "(「これまでと同じく」等でも基本禁止。動作を直接説明する)",
    "検体": "アバター",
    "骨の名前": "ボーンの名前",
}

# i18n辞書側の許可リスト(EXE_MENTION_ALLOWLIST/VRM_PREFAB_ORDER_ALLOWLISTと
# 同型)。
#
# LabWarningActive: 「ラボ機能がONになっています！実験的機能なので、思わぬ
# 不具合がおきるかもしれません！！」。dev#1186でオーナーが承認済みの
# ラボ共通警告文言そのもの(メイン窓/ラボ窓に1箇所ずつ表示、個別ダイアログの
# 但し書きではない)。2026-08-09オーナー指示「唯一の例外」により許可リストへ
# 登録する。
FORBIDDEN_WORD_I18N_ALLOWLIST: set[str] = {"LabWarningActive"}


def _iter_ja_forbidden_violations(table: dict, forbidden_words: list[str], allowlist: set[str]):
    """table({key: {lang: text}} 形式、TABLE/PROGRESS_LABELS共通)の "ja" エントリ
    のみを走査し、禁止語を含むものを列挙する。戻り値: [(key, word, text)]。
    """
    violations = []
    for key, values in table.items():
        if key in allowlist:
            continue
        text = values.get("ja") if isinstance(values, dict) else None
        if not isinstance(text, str):
            continue
        for word in forbidden_words:
            if word in text:
                violations.append((key, word, text))
    return violations


def test_no_forbidden_words_in_i18n_table_ja():
    violations = _iter_ja_forbidden_violations(i18n.TABLE, FORBIDDEN_WORDS, FORBIDDEN_WORD_I18N_ALLOWLIST)
    assert not violations, (
        f"Table(ja): 禁止語を含む文言(正: {CORRECT_FORM_HINT}): "
        f"{violations[:20]} (total {len(violations)})"
    )


def test_no_forbidden_words_in_progress_labels_ja():
    violations = _iter_ja_forbidden_violations(
        i18n.PROGRESS_LABELS, FORBIDDEN_WORDS, FORBIDDEN_WORD_I18N_ALLOWLIST
    )
    assert not violations, (
        f"ProgressLabels(ja): 禁止語を含む文言(正: {CORRECT_FORM_HINT}): "
        f"{violations[:20]} (total {len(violations)})"
    )


def test_forbidden_word_i18n_lint_catches_ja_injection():
    # 負の対照: 辞書のjaエントリに禁止語を一時混入させると検出されることの証明。
    i18n.TABLE["__test_forbidden_word_ja__"] = {
        "ja": "輸出フォルダを選択してください",
        "en": "x", "ko": "x", "zhTW": "x", "zhCN": "x",
    }
    try:
        violations = _iter_ja_forbidden_violations(
            i18n.TABLE, FORBIDDEN_WORDS, FORBIDDEN_WORD_I18N_ALLOWLIST
        )
        keys_hit = {v[0] for v in violations}
        assert "__test_forbidden_word_ja__" in keys_hit
    finally:
        del i18n.TABLE["__test_forbidden_word_ja__"]


def test_forbidden_word_i18n_lint_ignores_non_ja_language():
    # 中国語(zhTW/zhCN)の「輸出/输出」はexport/outputの正当な訳語であり
    # 誤用ではない(i18n_data.json実測: LogUnityExportHeartbeatFormat等)。
    # ja以外に禁止語を含めても検出対象にならないことを確認する
    # (このテスト自体が「ja限定」という設計判断を機械的に固定する)。
    i18n.TABLE["__test_forbidden_word_nonja__"] = {
        "ja": "x", "en": "x", "ko": "x",
        "zhTW": "輸出資料夾", "zhCN": "输出文件夹",
    }
    try:
        violations = _iter_ja_forbidden_violations(
            i18n.TABLE, FORBIDDEN_WORDS, FORBIDDEN_WORD_I18N_ALLOWLIST
        )
        keys_hit = {v[0] for v in violations}
        assert "__test_forbidden_word_nonja__" not in keys_hit
    finally:
        del i18n.TABLE["__test_forbidden_word_nonja__"]


def test_forbidden_word_i18n_allowlist_suppresses_and_empty_allowlist_still_catches():
    # 負の対照: 許可リストに載せると見逃され、空にすると再び検出されることの証明
    # (dev#654 EXE_MENTION_ALLOWLISTの検証パターンと同型)。
    i18n.TABLE["__test_forbidden_word_allowlisted__"] = {
        "ja": "輸出フォルダを選択してください",
        "en": "x", "ko": "x", "zhTW": "x", "zhCN": "x",
    }
    try:
        without_allowlist = _iter_ja_forbidden_violations(i18n.TABLE, FORBIDDEN_WORDS, set())
        keys_hit = {v[0] for v in without_allowlist}
        assert "__test_forbidden_word_allowlisted__" in keys_hit, "許可リスト無しでは検出されるはず"

        with_allowlist = _iter_ja_forbidden_violations(
            i18n.TABLE, FORBIDDEN_WORDS, {"__test_forbidden_word_allowlisted__"}
        )
        keys_hit2 = {v[0] for v in with_allowlist}
        assert "__test_forbidden_word_allowlisted__" not in keys_hit2, "許可リストに載せたキーは除外されるはず"
    finally:
        del i18n.TABLE["__test_forbidden_word_allowlisted__"]


# -- 2026-08-09追加分(サポート対象外/実験的機能/旧/従来)の負の対照 --------
#
# 「輸出」1語のときの負の対照と同型のテストを、追加した4語それぞれについて
# 一時混入 -> 検出 -> 削除、の形で繰り返す(オーナー指示「負の対照も追加分で
# 確認」)。

@pytest.mark.parametrize(
    "word,sample",
    [
        ("サポート対象外", "この機能はサポート対象外です"),
        ("実験的機能", "これは実験的機能です"),
        ("旧", "旧方式に切り替えます"),
        ("従来", "従来どおり非表示のままです"),
    ],
)
def test_forbidden_word_i18n_lint_catches_new_2026_08_09_words(word, sample):
    key = f"__test_forbidden_word_2026_08_09_{word}__"
    i18n.TABLE[key] = {"ja": sample, "en": "x", "ko": "x", "zhTW": "x", "zhCN": "x"}
    try:
        violations = _iter_ja_forbidden_violations(
            i18n.TABLE, FORBIDDEN_WORDS, FORBIDDEN_WORD_I18N_ALLOWLIST
        )
        keys_hit = {v[0] for v in violations}
        assert key in keys_hit, f"{word!r}を含む文言が検出されなかった: {sample!r}"
    finally:
        del i18n.TABLE[key]


# -- 2026-08-11追加分(検体/骨の名前)の負の対照 ----------------------------
#
# work\rd_19_flight\briefs\uimock2_fixes.md「構造化」節: オーナーUX評価#3/#4
# (「検体」→「アバター」、「骨の名前」→「ボーンの名前」)の恒久化。
# 上記2026-08-09追加分と同型(一時混入 -> 検出 -> 削除)。

@pytest.mark.parametrize(
    "word,sample",
    [
        ("検体", "この検体の設定を既定値に戻す"),
        ("骨の名前", "骨の名前で手動追加"),
    ],
)
def test_forbidden_word_i18n_lint_catches_new_2026_08_11_words(word, sample):
    key = f"__test_forbidden_word_2026_08_11_{word}__"
    i18n.TABLE[key] = {"ja": sample, "en": "x", "ko": "x", "zhTW": "x", "zhCN": "x"}
    try:
        violations = _iter_ja_forbidden_violations(
            i18n.TABLE, FORBIDDEN_WORDS, FORBIDDEN_WORD_I18N_ALLOWLIST
        )
        keys_hit = {v[0] for v in violations}
        assert key in keys_hit, f"{word!r}を含む文言が検出されなかった: {sample!r}"
    finally:
        del i18n.TABLE[key]


def test_forbidden_word_lint_does_not_false_positive_on_skeleton_word():
    # 負の対照(誤検知しないことの確認): 「骨の名前」は複合語限定のため、
    # 正当な「骨格」(Armature)言及は禁止語に引っかからない
    # (i18n_data.jsonの既存の正当な用例そのもの、上のコメント参照)。
    key = "__test_forbidden_word_skeleton_ok__"
    i18n.TABLE[key] = {
        "ja": "すべてのボーンを削除対象にはできません(骨格が全損してしまいます)。",
        "en": "x", "ko": "x", "zhTW": "x", "zhCN": "x",
    }
    try:
        violations = _iter_ja_forbidden_violations(
            i18n.TABLE, FORBIDDEN_WORDS, FORBIDDEN_WORD_I18N_ALLOWLIST
        )
        keys_hit = {v[0] for v in violations}
        assert key not in keys_hit, "「骨格」を「骨の名前」の誤検知で拾ってしまっている"
    finally:
        del i18n.TABLE[key]


def test_forbidden_word_lab_warning_active_allowlisted():
    # LabWarningActive(ラボ共通警告、dev#1186オーナー承認済み文言)は
    # 「実験的機能」を含む唯一の例外として許可リストに登録済み。許可リスト
    # 込みでは検出されず、許可リストを外すと(素の禁止語検査としては)
    # 検出される、の両方を確認する(許可リストが実際に効いていることの証明)。
    assert "LabWarningActive" in i18n.TABLE
    ja_text = i18n.TABLE["LabWarningActive"]["ja"]
    assert "実験的機能" in ja_text  # 前提: この語を含む文言であること自体の確認

    with_allowlist = _iter_ja_forbidden_violations(
        i18n.TABLE, FORBIDDEN_WORDS, FORBIDDEN_WORD_I18N_ALLOWLIST
    )
    assert "LabWarningActive" not in {v[0] for v in with_allowlist}

    without_allowlist = _iter_ja_forbidden_violations(i18n.TABLE, FORBIDDEN_WORDS, set())
    assert "LabWarningActive" in {v[0] for v in without_allowlist}


# -- GUIソースの文字列リテラル走査 -----------------------------------------
#
# コメント(#...)はPythonのトークナイザ上そもそも文字列リテラルにならないため
# ast走査には現れない。docstring(モジュール/関数/クラス本体先頭のExpr文字列)
# だけは開発者向けとして明示的に除外する。


def _iter_non_docstring_string_constants(source: str, filename: str):
    """source中の文字列リテラル(ast.Constant, f-string内の定数部分含む)を、
    モジュール/関数/クラスのdocstringを除いて列挙する。
    戻り値: [(value, lineno)]。構文エラー時は空リスト(呼び出し側でパス毎に
    明示的にエラー扱いする設計にはしない -- 対象は全て実行中の現行ソース)。
    """
    tree = ast.parse(source, filename=filename)
    docstring_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if body:
                first = body[0]
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstring_ids.add(id(first.value))
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_ids:
                continue
            results.append((node.value, getattr(node, "lineno", -1)))
    return results


def _scan_source_for_forbidden_words(source: str, filename: str, forbidden_words: list[str]):
    hits = []
    for value, lineno in _iter_non_docstring_string_constants(source, filename):
        for word in forbidden_words:
            if word in value:
                hits.append((word, lineno, value))
    return hits


def _scan_file_for_forbidden_words(path: str, forbidden_words: list[str]):
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    return _scan_source_for_forbidden_words(source, path, forbidden_words)


def _gui_source_files():
    """GUIソース: app_py直下のユーザー向け文言/診断ログ文言を組み立てる
    モジュール群(tests/devtools等のサブディレクトリは含めない) + app_py\\ui
    配下全モジュール。"""
    files = sorted(glob.glob(os.path.join(_APP_PY_DIR, "*.py")))
    files += sorted(glob.glob(os.path.join(_APP_PY_DIR, "ui", "*.py")))
    return files


def test_no_forbidden_words_in_gui_source_literals():
    offenders = []
    for path in _gui_source_files():
        for word, lineno, value in _scan_file_for_forbidden_words(path, FORBIDDEN_WORDS):
            offenders.append((os.path.relpath(path, _APP_PY_DIR), lineno, word, value))
    assert not offenders, (
        f"GUIソースの文字列リテラルに禁止語(正: {CORRECT_FORM_HINT}): {offenders}"
    )


def test_forbidden_word_source_scanner_catches_literal_but_not_docstring_or_comment():
    # 負の対照: モジュール/関数docstringとコメント中の禁止語は検出せず、
    # 通常の文字列リテラル(f-string含む)中の禁止語だけを検出することの証明。
    source = '''"""module docstring 輸出 should not be flagged"""


def f():
    """func docstring 輸出 also not flagged"""
    # comment 輸出 not flagged (not a string literal)
    x = "輸出 flagged literal"
    y = f"prefix 輸出 flagged fstring {x}"
    return x, y
'''
    hits = _scan_source_for_forbidden_words(source, "<test>", FORBIDDEN_WORDS)
    flagged_values = {value for _word, _lineno, value in hits}
    assert any("flagged literal" in v for v in flagged_values)
    assert any("flagged fstring" in v for v in flagged_values)
    assert not any("should not be flagged" in v for v in flagged_values)
    assert not any("also not flagged" in v for v in flagged_values)
    assert len(hits) == 2


def test_forbidden_word_source_scanner_ignores_clean_source():
    source = '''"""module docstring, no forbidden words."""


def f():
    """docstring"""
    return "エクスポートフォルダを選択してください"
'''
    hits = _scan_source_for_forbidden_words(source, "<test>", FORBIDDEN_WORDS)
    assert hits == []
