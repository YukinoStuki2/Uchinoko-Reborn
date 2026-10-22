# test_palworld_not_found_auto_fallback_dev1394.py -- dev#1394: 自動プレビュー
# (auto=True)経路がPhase 0の「Palworld本体が見つからない」FATALで死んだとき、
# 既存の手動指定フォールバック(Apply/Remove・明示的な「変換開始」と共用)へ
# 一切到達しなかった欠落の修理(実報告ATXSKRLB/ZJSU5FWD/7TXW783Q)。
#
# 原因(コード確認済み): _start_pipeline()のauto=True時はダイアログ抑止方針
# (dev#229続報「二重起動中/ファイル未指定と同じ理由」)のもと
# _ensure_palworld_located()自体を呼ばない。Palworld未検出のままパイプラインが
# 起動され、Phase 0(pipeline\py\convert_noue.py::resolve_vanilla_source())が
# 単純なdie() FATALで終了する。この終了はGUI復旧導線を一切持たず、
# _on_pipeline_exit()は汎用の「問い合わせますか」オファーのみで終わっていた。
#
# 修理: Phase 0のdie()が出す既存の固定診断文言(2種、内部診断文言自体は
# CLAUDE.md方針どおり変更しない。pipeline\py側はこのWPの書き込み許可範囲外
# のため##AVATAR_FATAL##マーカーは追加していない)を
# pipeline_runner.parse_palworld_not_found_fatal()で検出し、既存の
# _pipeline_fatal_cause機構(dev#1260/#1261と共通)へ乗せる。
# _on_pipeline_exit()のcode!=0分岐で、このコードのときだけ
# _resolve_paks_dir_interactive()(Apply/Removeと完全共用)を直接呼ぶ。
#
# 方針(共通契約どおり、tkの実ウィンドウは一切開かない):
# test_no_mesh_fatal_dev1261.py/test_palworld_manual_fallback_dev229.pyと
# 同じ「フェイクself+束縛前メソッド呼び出し」方式。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pipeline_runner as pr  # noqa: E402
from ui import main_window as mw  # noqa: E402

EXPECTED_LANGS = ["ja", "en", "ko", "zhTW", "zhCN"]

# 実際にconvert_noue.py::resolve_vanilla_source()のdie()が出す行の実例
# (die()は`[<TAG>][FATAL] {msg}`形式。msgの1行目だけが同じ行に乗る)。
_SEARCH_FAILURE_LINE = "[convert_noue][FATAL] Palworld was not found. Locations searched:"
_STALE_PATH_LINE = (
    r"[convert_noue][FATAL] Palworld's pak was not found: "
    r"D:\old\Palworld\Pal\Content\Paks\Pal-Windows.pak"
)


# ---------------------------------------------------------------------------
# 1. pipeline_runner: マーカー検出・翻訳の単体テスト(##AVATAR_FATAL##系と同型)
# ---------------------------------------------------------------------------


def test_parse_palworld_not_found_fatal_detects_search_failure_line():
    assert (
        pr.parse_palworld_not_found_fatal(_SEARCH_FAILURE_LINE)
        == pr.PALWORLD_NOT_FOUND_FATAL_CODE
    )


def test_parse_palworld_not_found_fatal_detects_stale_path_line():
    assert (
        pr.parse_palworld_not_found_fatal(_STALE_PATH_LINE)
        == pr.PALWORLD_NOT_FOUND_FATAL_CODE
    )


def test_parse_palworld_not_found_fatal_negative_control_normal_line():
    # 負の対照: 通常の進捗行・無関係な行・別種のFATALには反応しない
    assert pr.parse_palworld_not_found_fatal("normal progress line") is None
    assert pr.parse_palworld_not_found_fatal("##AVATAR_FATAL## no_mesh") is None
    assert (
        pr.parse_palworld_not_found_fatal(
            "[convert_noue][FATAL] avatar has no meshes at all"
        )
        is None
    )


def test_parse_palworld_not_found_fatal_requires_fatal_tag():
    # 負の対照: 固定文言と一致していても[FATAL]タグが無ければ誤検出しない
    # (例: ログ欄への案内文やヘルプ文言に同じ語が偶然含まれるケースへの防御)
    assert pr.parse_palworld_not_found_fatal("Palworld was not found. Locations searched:") is None


def test_translate_avatar_fatal_palworld_not_found_ja():
    assert pr.translate_avatar_fatal(pr.PALWORLD_NOT_FOUND_FATAL_CODE, lang="ja") == (
        "Palworld本体が見つかりませんでした。Paksフォルダを選択してください"
    )


def test_translate_avatar_fatal_palworld_not_found_en():
    assert pr.translate_avatar_fatal(pr.PALWORLD_NOT_FOUND_FATAL_CODE, lang="en") == (
        "Palworld could not be found. Please select the Paks folder."
    )


# ---------------------------------------------------------------------------
# 2. i18n辞書: MsgPalworldNotFoundFatalキー(5言語)
# ---------------------------------------------------------------------------


def test_msg_palworld_not_found_fatal_key_exists_all_languages_non_empty():
    assert "MsgPalworldNotFoundFatal" in i18n.TABLE
    for lang in EXPECTED_LANGS:
        assert i18n.TABLE["MsgPalworldNotFoundFatal"].get(lang), (
            f"MsgPalworldNotFoundFatal/{lang} が空"
        )


def test_msg_palworld_not_found_fatal_en_does_not_use_forbidden_export_wording():
    en_text = i18n.S("MsgPalworldNotFoundFatal", lang="en")
    assert "export" not in en_text.lower()


# ---------------------------------------------------------------------------
# 3. main_window統合: _on_pipeline_line(fake-self、実tk不使用)
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


def test_on_pipeline_line_detects_palworld_not_found_fatal_from_search_failure():
    """正: Phase 0のdie()が出す実際の行(探索完全失敗)を受け取ると、
    ##AVATAR_FATAL##マーカーを経由せず_pipeline_fatal_causeへ反映される。"""
    fake = _fake_window_for_pipeline_line()
    fake._on_pipeline_line(_SEARCH_FAILURE_LINE)
    assert fake._pipeline_fatal_cause == pr.PALWORLD_NOT_FOUND_FATAL_CODE


def test_on_pipeline_line_detects_palworld_not_found_fatal_from_stale_path():
    """正: job.jsonの明示パスが実在しなかった場合の別文言でも同様に検出。"""
    fake = _fake_window_for_pipeline_line()
    fake._on_pipeline_line(_STALE_PATH_LINE)
    assert fake._pipeline_fatal_cause == pr.PALWORLD_NOT_FOUND_FATAL_CODE


def test_on_pipeline_line_fatal_marker_still_reaches_log():
    # ##AVATAR_WARNING##/##AVATAR_FATAL##と同型: 検出行はログ欄
    # (=「ログをコピー」の材料)からも消えない
    fake = _fake_window_for_pipeline_line()
    fake._on_pipeline_line(_SEARCH_FAILURE_LINE)
    assert _SEARCH_FAILURE_LINE in fake._log_calls


def test_on_pipeline_line_negative_control_avatar_fatal_marker_still_wins():
    # 負の対照: 既存の##AVATAR_FATAL##マーカー検出(dev#1260/#1261)は
    # 本WPの追加検出より優先される(parse_avatar_fatal()を先に試す実装の
    # ため、Palworld文言と同時一致することはそもそも無いが、優先順位が
    # 崩れていないことを明示的に確認する)。
    fake = _fake_window_for_pipeline_line()
    fake._on_pipeline_line("##AVATAR_FATAL## no_mesh")
    assert fake._pipeline_fatal_cause == "no_mesh"


def test_on_pipeline_line_negative_control_normal_line_does_not_set_fatal_cause():
    fake = _fake_window_for_pipeline_line()
    fake._on_pipeline_line("normal progress line, nothing unusual")
    assert fake._pipeline_fatal_cause is None


# ---------------------------------------------------------------------------
# 4. main_window統合: _on_pipeline_exit(受入条件の核心)
# ---------------------------------------------------------------------------


def _fake_window_for_pipeline_exit() -> mw.MainWindow:
    fake = mw.MainWindow.__new__(mw.MainWindow)
    fake.widgets = {"statusLabel": _FakeWidget()}
    fake._set_running_ui_state = lambda _running: None
    fake._user_cancelled_current_run = False
    fake._pipeline_fatal_cause = None
    fake._set_status = mw.MainWindow._set_status.__get__(fake, mw.MainWindow)
    fake._resolve_paks_dir_interactive_calls = 0
    fake._resolve_paks_dir_interactive = (
        lambda: fake.__setattr__(
            "_resolve_paks_dir_interactive_calls",
            fake._resolve_paks_dir_interactive_calls + 1,
        )
        or r"D:\steam\steamapps\common\Palworld\Pal\Content\Paks"
    )
    return fake


def test_on_pipeline_exit_palworld_not_found_reaches_manual_fallback_dialog():
    """受入条件の核心(正): auto=True経路由来の実行でも、fatal_code=
    palworld_not_foundが立っていればpreview_only=Trueのまま
    _on_pipeline_exit()に届き、既存の手動指定フォールバック
    (_resolve_paks_dir_interactive、モックで到達確認)が直接呼ばれる。
    _start_pipeline()自体のauto=True引数は_on_pipeline_exit()に渡らない
    設計(既存シグネチャ)のため、auto経路の唯一の見分け材料である
    fatal_code(auto時にしか到達しえない検出結果)で検証する。"""
    fake = _fake_window_for_pipeline_exit()
    fake._pipeline_fatal_cause = pr.PALWORLD_NOT_FOUND_FATAL_CODE
    offers: list[str] = []
    fake._offer_report_after_failure = lambda cause: offers.append(cause)
    i18n.set_language("ja")

    mw.MainWindow._on_pipeline_exit(fake, 1, True)

    assert fake._resolve_paks_dir_interactive_calls == 1, (
        "palworld_not_found FATALなのに手動指定フォールバックへ到達しなかった"
    )
    assert offers == [], "自己解決可能な原因なのに一般的な問い合わせオファーも出た"
    # run単位でリセットされ、次回runへ持ち越さない(dev#1260/#1261と同じ契約)
    assert fake._pipeline_fatal_cause is None


def test_on_pipeline_exit_negative_control_generic_failure_does_not_open_fallback():
    """負の対照(その1): マーカー未検出の通常失敗では、従来どおり
    _offer_report_after_failure()だけが呼ばれ、手動指定フォールバックは
    一切開かない(本WPが既存の失敗表示を壊していないことの証明)。"""
    fake = _fake_window_for_pipeline_exit()
    offers: list[str] = []
    fake._offer_report_after_failure = lambda cause: offers.append(cause)
    i18n.set_language("ja")

    mw.MainWindow._on_pipeline_exit(fake, 1, True)

    assert fake._resolve_paks_dir_interactive_calls == 0
    assert len(offers) == 1


def test_on_pipeline_exit_negative_control_no_mesh_fatal_does_not_open_fallback():
    """負の対照(その2): 別種の##AVATAR_FATAL##(no_mesh等)では、従来どおり
    専用文言のオファーのみで、Palworld手動指定フォールバックは開かない
    (fatal_codeの分岐がpalworld_not_foundだけに限定されていることの確認)。"""
    fake = _fake_window_for_pipeline_exit()
    fake._pipeline_fatal_cause = "no_mesh"
    offers: list[str] = []
    fake._offer_report_after_failure = lambda cause: offers.append(cause)
    i18n.set_language("ja")

    mw.MainWindow._on_pipeline_exit(fake, 1, True)

    assert fake._resolve_paks_dir_interactive_calls == 0
    assert len(offers) == 1


def test_on_pipeline_exit_negative_control_success_does_not_open_fallback():
    """負の対照(その3、自動発見成功時): code==0(成功)ではcode!=0分岐自体に
    到達しないため、fatal_causeが立っていても手動指定フォールバックは
    絶対に開かない、という構造をソースレベルで確認する
    (既存test_no_mesh_fatal_dev1261.pyの
    test_on_pipeline_exit_negative_control_success_path_does_not_reset_fatal_cause
    と同型の理由: preview_only成功時の後続処理を全部フェイクで埋めるのは
    本WPのスコープ外の結線を大量に模擬することになり過剰なため)。"""
    with open(
        os.path.join(_APP_PY_DIR, "ui", "main_window.py"), "r", encoding="utf-8"
    ) as f:
        source = f.read()
    start = source.index("def _on_pipeline_exit(")
    end = source.index("\n    def ", start + 1)
    body = source[start:end]
    fallback_idx = body.index("self._resolve_paks_dir_interactive()")
    if_idx = body.index("if code != 0:")
    # 手動指定フォールバック呼び出しは `if code != 0:` ブロックの中
    # (=それより後)にあり、code==0では絶対に実行されない
    assert if_idx < fallback_idx
