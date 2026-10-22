# test_no_mesh_fatal_dev1261.py -- dev#1261: メッシュ0個検出時の専用エラー
# メッセージ(実報告DLK66VBE、20KB破損VRM疑い)。
#
# オーナー指示(dev#1261コメント、2026-08-09、これが仕様):
#   「メッシュが見つかりませんでした。入力ファイルが壊れていないかご確認
#   ください」を実装してください
#
# アーキテクチャ(既存の##AVATAR_WARNING##系に倣う、dev#939/dev#690と同型):
#   1. pipeline\blender\step01_import_vrm.py::cleanup_objects() が
#      keep_meshesが空のとき、内部診断die()(英語、変更しない)の直前に
#      `##AVATAR_FATAL## no_mesh` マーカーを追加で出す。
#   2. app_py\pipeline_runner.py の parse_avatar_fatal()/translate_avatar_fatal()
#      がマーカーを拾い、i18n key "MsgNoMeshFatal"(5言語)へ翻訳する。
#   3. app_py\ui\main_window.py の _on_pipeline_line() がマーカーを検出して
#      self._pipeline_fatal_cause(生コード)へ保持、_on_pipeline_exit() の
#      code!=0分岐が汎用のStatusFailedOrCancelledより優先して使う。
#
# pipeline\blender\step01_import_vrm.py自体はmain()をimport時に無条件実行する
# ため通常のpython/pytest環境では単体importできない
# (tests\coverage\test_bone_error_message.pyの既存注記と同じ制約)。そのため
# マーカー行の存在はソーステキストレベルで検査し(test_i18n_keys.py の
# test_browse_dialog_filetypes_list_prefab_before_vrm_in_source と同型の手法)、
# 「マーカー検出→翻訳→GUI表示」の実際の発火はpipeline_runner/main_window側の
# 単体テスト(_on_pipeline_line/_on_pipeline_exitに合成ログ行を直接与える)で
# 検証する。test_avatar_warning_diagnostics.py/test_error_next_action.pyと同じ
# fake-self方式(実tkウィンドウは開かない)。
from __future__ import annotations

import os
import sys

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_APP_PY_DIR)
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pipeline_runner as pr  # noqa: E402
from ui import main_window as mw  # noqa: E402

EXPECTED_LANGS = ["ja", "en", "ko", "zhTW", "zhCN"]
STEP01_PATH = os.path.join(_REPO_ROOT, "pipeline", "blender", "step01_import_vrm.py")


# ---------------------------------------------------------------------------
# 1. ソーステキストレベル: マーカー行がdie()の直前に置かれていること
# ---------------------------------------------------------------------------


def test_step01_emits_marker_immediately_before_no_mesh_die():
    with open(STEP01_PATH, "r", encoding="utf-8") as f:
        source = f.read()
    marker_line = '        print("##AVATAR_FATAL## no_mesh")'
    die_line = '        core.die(TAG, "avatar has no meshes at all")'
    assert marker_line in source, "##AVATAR_FATAL## no_meshマーカーが見つからない"
    assert die_line in source, "既存のdie()呼び出し自体が変更されている(内部診断文言は不変のはず)"
    marker_idx = source.index(marker_line)
    die_idx = source.index(die_line)
    # マーカーはdie()より前(die()はsys.exitするため、後では出力されない)
    assert marker_idx < die_idx
    # 間に他のdie()呼び出しが挟まっていない(直前であることの確認)
    between = source[marker_idx:die_idx]
    assert between.count("core.die(") == 0


def test_step01_no_mesh_die_message_unchanged():
    """負の対照(内部診断文言側): 本WPは英語の内部診断メッセージ自体は
    変更しない(問い合わせデバッグの作法どおり)。誤ってdie()の第2引数を
    書き換えていないことを確認する。"""
    with open(STEP01_PATH, "r", encoding="utf-8") as f:
        source = f.read()
    assert '"avatar has no meshes at all"' in source


# ---------------------------------------------------------------------------
# 2. i18n辞書: MsgNoMeshFatalキー(オーナー指定文言そのまま+5言語)
# ---------------------------------------------------------------------------


def test_msg_no_mesh_fatal_key_exists_all_languages_non_empty():
    assert "MsgNoMeshFatal" in i18n.TABLE
    for lang in EXPECTED_LANGS:
        assert i18n.TABLE["MsgNoMeshFatal"].get(lang), f"MsgNoMeshFatal/{lang} が空"


def test_msg_no_mesh_fatal_ja_matches_owner_wording_exactly():
    # オーナー指示の文言を一字一句変えない(dev#1261コメント原文)
    expected = "メッシュが見つかりませんでした。入力ファイルが壊れていないかご確認ください"
    assert i18n.S("MsgNoMeshFatal", lang="ja") == expected


def test_msg_no_mesh_fatal_en_does_not_use_forbidden_export_wording():
    # 制約: 「輸出」という語は使用禁止、「エクスポート」(このメッセージは
    # そもそもexport/輸出概念を含まないため、"export"という語自体が
    # 出現しないことを機械検査する)
    en_text = i18n.S("MsgNoMeshFatal", lang="en")
    assert "export" not in en_text.lower()


# ---------------------------------------------------------------------------
# 3. pipeline_runner: マーカー解析・翻訳の単体テスト(##AVATAR_WARNING##系と同型)
# ---------------------------------------------------------------------------


def test_parse_avatar_fatal_basic():
    assert pr.parse_avatar_fatal("##AVATAR_FATAL## no_mesh") == "no_mesh"


def test_parse_avatar_fatal_none_when_not_matching():
    # 負の対照: 通常行や別マーカー(##AVATAR_WARNING##)には反応しない
    assert pr.parse_avatar_fatal("normal line") is None
    assert pr.parse_avatar_fatal("##AVATAR_WARNING## something looks off") is None


def test_translate_avatar_fatal_no_mesh_ja():
    assert pr.translate_avatar_fatal("no_mesh", lang="ja") == (
        "メッシュが見つかりませんでした。入力ファイルが壊れていないかご確認ください"
    )


def test_translate_avatar_fatal_no_mesh_en():
    assert pr.translate_avatar_fatal("no_mesh", lang="en") == (
        "No mesh was found. Please check whether the input file is corrupted."
    )


def test_translate_avatar_fatal_unknown_code_falls_back_to_code_itself():
    # 負の対照: 未知コードは情報を落とさず原文(コード文字列)のまま返す
    # (##AVATAR_WARNING##系の「未一致なら原文のまま」と同じ方針)
    assert pr.translate_avatar_fatal("__no_such_code__", lang="ja") == "__no_such_code__"


# ---------------------------------------------------------------------------
# 4. main_window統合: _on_pipeline_line/_on_pipeline_exit(fake-self、実tk不使用)
# ---------------------------------------------------------------------------


class _FakeWidget:
    def __init__(self, value: str = "") -> None:
        self._value = value
        self.text = value

    def get(self) -> str:
        return self._value

    def cget(self, key: str) -> str:
        return self.text

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]


class _DictLikeBusyBar(_FakeWidget):
    def __setitem__(self, _key, _value) -> None:
        return None


def _fake_window_for_pipeline_line() -> mw.MainWindow:
    """_on_pipeline_line()単体を呼ぶための最小フェイク
    (test_avatar_warning_diagnostics.pyのfake_selfと同型だがtk.Textは
    使わない — 本テストの関心は_pipeline_fatal_cause/_pipeline_warningsへの
    反映であり、実tk.Textでのログ蓄積確認は別ファイルの担当のため)。"""
    fake = mw.MainWindow.__new__(mw.MainWindow)
    fake.widgets = {"busyBar": _DictLikeBusyBar()}
    fake._pipeline_warnings = []
    fake._pipeline_fatal_cause = None
    fake._active_handle = None
    fake._early_preview_loaded_this_run = False
    fake._log_calls: list[str] = []
    fake._log = lambda text, **_k: fake._log_calls.append(text)
    fake._on_pipeline_line = mw.MainWindow._on_pipeline_line.__get__(fake, mw.MainWindow)
    return fake


def test_on_pipeline_line_detects_no_mesh_fatal_marker():
    """正: ##AVATAR_FATAL## no_mesh 行を受け取ると _pipeline_fatal_cause に
    生コードが積まれる。"""
    fake = _fake_window_for_pipeline_line()
    fake._on_pipeline_line("##AVATAR_FATAL## no_mesh")
    assert fake._pipeline_fatal_cause == "no_mesh"


def test_on_pipeline_line_fatal_marker_still_reaches_log():
    """##AVATAR_WARNING##と同型: マーカー行はログ欄(=「ログをコピー」の
    材料)からも消えない(fall throughしてself._log(clean)が呼ばれる)。"""
    fake = _fake_window_for_pipeline_line()
    fake._on_pipeline_line("##AVATAR_FATAL## no_mesh")
    assert "##AVATAR_FATAL## no_mesh" in fake._log_calls


def test_on_pipeline_line_negative_control_normal_line_does_not_set_fatal_cause():
    """負の対照: 通常の進捗行・無関係な行では_pipeline_fatal_causeが
    Noneのまま(誤検出しない)。"""
    fake = _fake_window_for_pipeline_line()
    fake._on_pipeline_line("normal progress line, nothing unusual")
    assert fake._pipeline_fatal_cause is None
    fake._on_pipeline_line("##AVATAR_WARNING## something looks off")
    assert fake._pipeline_fatal_cause is None


def _fake_window_for_pipeline_exit() -> mw.MainWindow:
    fake = mw.MainWindow.__new__(mw.MainWindow)
    fake.widgets = {"statusLabel": _FakeWidget()}
    fake._set_running_ui_state = lambda _running: None
    fake._user_cancelled_current_run = False
    fake._pipeline_fatal_cause = None
    fake._set_status = mw.MainWindow._set_status.__get__(fake, mw.MainWindow)
    return fake


def test_on_pipeline_exit_uses_no_mesh_fatal_message_when_marker_was_seen():
    """正(受入条件の核心): メッシュ0個検出済みの状態でパイプラインが
    失敗終了すると、statusLabelと問い合わせ導線の理由文言に
    オーナー指定の専用メッセージが使われる。"""
    fake = _fake_window_for_pipeline_exit()
    fake._pipeline_fatal_cause = "no_mesh"
    offers: list[str] = []
    fake._offer_report_after_failure = lambda cause: offers.append(cause)
    i18n.set_language("ja")

    mw.MainWindow._on_pipeline_exit(fake, 1, False)

    expected = "メッシュが見つかりませんでした。入力ファイルが壊れていないかご確認ください"
    assert fake.widgets["statusLabel"].text == expected
    assert offers == [expected]
    # run単位でリセットされ、次回runへ持ち越さない
    assert fake._pipeline_fatal_cause is None


def test_on_pipeline_exit_negative_control_normal_failure_uses_generic_status():
    """負の対照: マーカーを検出していない通常の失敗では、従来どおり
    StatusFailedOrCancelledが使われる(本WPが既存の失敗表示を壊していない
    ことの証明)。"""
    fake = _fake_window_for_pipeline_exit()
    offers: list[str] = []
    fake._offer_report_after_failure = lambda cause: offers.append(cause)
    i18n.set_language("ja")

    mw.MainWindow._on_pipeline_exit(fake, 1, False)

    expected = i18n.S("StatusFailedOrCancelled")
    assert fake.widgets["statusLabel"].text == expected
    assert offers == [expected]
    assert "メッシュ" not in expected


def test_on_pipeline_exit_negative_control_success_path_does_not_reset_fatal_cause():
    """負の対照: 本WPが変更したのは`code != 0`分岐のみであり、成功分岐
    (code==0)には一切手を入れていない。_pipeline_fatal_causeのリセットは
    code!=0分岐の冒頭でのみ起きる設計のため、code==0を渡した場合はその
    リセット処理自体に到達しない(=values残存)ことを、_on_pipeline_exit
    本体を完走させずソースの分岐構造で確認する(preview_only等の後続処理を
    フェイクで全部埋めるのは本WPのスコープ外の結線を大量に模擬することに
    なり過剰なため、ここでは行わない)。"""
    with open(
        os.path.join(_APP_PY_DIR, "ui", "main_window.py"), "r", encoding="utf-8"
    ) as f:
        source = f.read()
    start = source.index("def _on_pipeline_exit(")
    end = source.index("\n    def ", start + 1)
    body = source[start:end]
    reset_idx = body.index("self._pipeline_fatal_cause = None")
    if_idx = body.index("if code != 0:")
    # リセット行が `if code != 0:` ブロックの中(=それより後)にあること
    assert if_idx < reset_idx
