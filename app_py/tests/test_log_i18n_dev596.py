# test_log_i18n_dev596.py -- dev#596残り(prefab変換時にGUIログ欄へ日本語行が
# 多数出る)の受入試験。
#
# 対応した2つの仕組みを検証する:
#   (1) MainWindow._log(text, gui=False) は log_box への表示を抑制する
#       (開発向け詳細行の「抑制」。ファイル/コンソールへの print() は維持)。
#       _stub() ハンドラ(pakList選択変更のたびに発火する高頻度ノイズ)が
#       これを使っていること。
#   (2) pipeline\cli\export_from_unity.ps1(prefab入力時のみ通るUnity輸出、
#       LU層)のWrite-Host/Write-Errorが日本語を含まないこと(convert.ps1の
#       既存の英語文言慣習に合わせた「出す側の英語化」)。
#
# tkの実ウィンドウは一切開かない。既存test_gui_log_robustness.pyと同じく
# フェイクself経由でMainWindow._log/_stubを未束縛メソッドとして直接呼ぶ。
from __future__ import annotations

import os
import re
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_PY_DIR = os.path.dirname(_TESTS_DIR)
_REPO_ROOT = os.path.dirname(_APP_PY_DIR)
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import main_window as mw  # noqa: E402

_JAPANESE_RE = re.compile(r"[぀-ヿ㐀-鿿]")


class _FakeLogBox:
    def __init__(self) -> None:
        self.inserted: list[str] = []

    def configure(self, **_kwargs) -> None:
        return None

    def insert(self, _index: str, text: str) -> None:
        self.inserted.append(text)

    def see(self, _index: str) -> None:
        return None


class _FakeSelfForLog:
    """MainWindow._log/_stubを未束縛メソッドとして直接呼ぶための最小self。
    _stub()が返すhandler内で`self._log(...)`を呼ぶため、本物の
    MainWindow._log をそのまま束縛しておく(test_gui_log_robustness.pyの
    _FakeSelfForPollと同じ手法)。"""

    _log = mw.MainWindow._log

    def __init__(self) -> None:
        self.log_box = _FakeLogBox()


# ---------------------------------------------------------------------------
# (1) _log(gui=False) がlog_box表示を抑制すること
# ---------------------------------------------------------------------------


def test_log_default_gui_true_still_shows_in_log_box():
    """負の対照: gui引数を省略した従来どおりの呼び出しは、これまでどおり
    log_boxへ反映されること(抑制がデフォルト挙動を壊していないこと)。"""
    fake_self = _FakeSelfForLog()
    mw.MainWindow._log(fake_self, "hello world")
    assert fake_self.log_box.inserted == ["hello world\n"]


def test_log_gui_false_suppresses_log_box_display():
    fake_self = _FakeSelfForLog()
    mw.MainWindow._log(fake_self, "[stub] PakListSelectedIndexChanged: not implemented", gui=False)
    assert fake_self.log_box.inserted == [], (
        "gui=Falseで呼んだのにlog_boxへ表示されている(抑制が効いていない)"
    )


def test_log_gui_false_still_prints_to_console(capsys):
    """抑制はGUI表示のみで、print()経由のコンソール/launch.log出力は
    維持されること(診断可能性を落とさない)。"""
    fake_self = _FakeSelfForLog()
    mw.MainWindow._log(fake_self, "dev-only diagnostic line", gui=False)
    captured = capsys.readouterr()
    assert "dev-only diagnostic line" in captured.out


# ---------------------------------------------------------------------------
# (2) _stub() ハンドラがgui=Falseで抑制済みの英語文言を出すこと
# ---------------------------------------------------------------------------


def test_stub_handler_suppresses_gui_and_uses_english():
    fake_self = _FakeSelfForLog()
    handler = mw.MainWindow._stub(fake_self, "PakListSelectedIndexChanged")
    handler()
    assert fake_self.log_box.inserted == [], (
        "dev#596b: _stub()の[stub]行はpakList選択のたびに発火する高頻度ノイズであり、"
        "GUIログ欄には出さない設計のはず"
    )


def test_stub_handler_negative_control_no_japanese_leftover():
    """負の対照: 過去の直書き文言「未実装」が復活していないことを、
    抑制を使わない生のprint()出力からも確認する。"""
    import io
    import contextlib

    fake_self = _FakeSelfForLog()
    handler = mw.MainWindow._stub(fake_self, "PakListSelectedIndexChanged")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        handler()
    assert not _JAPANESE_RE.search(buf.getvalue()), (
        f"[stub]の出力に日本語が残っている: {buf.getvalue()!r}"
    )
    assert "not implemented" in buf.getvalue()


# ---------------------------------------------------------------------------
# (3) main_window.py の他の直書きログ行(dev#596で残っていた5箇所)が
#     英語化されていること(静的スキャン、負の対照つき)
# ---------------------------------------------------------------------------


def _scan_log_call_lines_for_japanese(path: str) -> list[str]:
    """self._log(...) を呼んでいる行(コメント除く)のうち日本語を含むものを
    列挙する。"""
    hits = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "self._log(" in stripped and _JAPANESE_RE.search(stripped):
                hits.append(stripped)
    return hits


def test_main_window_log_calls_have_no_japanese_literal():
    main_window_path = os.path.join(_APP_PY_DIR, "ui", "main_window.py")
    hits = _scan_log_call_lines_for_japanese(main_window_path)
    assert hits == [], f"main_window.pyのself._log()呼び出しに日本語直書きが残っている: {hits}"


def test_scan_helper_negative_control_detects_injected_japanese(tmp_path):
    """負の対照: スキャン関数自体が日本語を検出できることを、意図的に
    日本語を含むダミーファイルで確認する(検査そのものが壊れていないこと)。"""
    dummy = tmp_path / "dummy_main_window.py"
    dummy.write_text(
        'def handler():\n    self._log(f"[stub] X: 未実装")\n',
        encoding="utf-8",
    )
    hits = _scan_log_call_lines_for_japanese(str(dummy))
    assert len(hits) == 1


# ---------------------------------------------------------------------------
# (4) export_from_unity.ps1 (prefab専用のUnity輸出、LU層) のWrite-Host/
#     Write-Errorが日本語を含まないこと
# ---------------------------------------------------------------------------

_PS1_PATH = os.path.join(_REPO_ROOT, "pipeline", "cli", "export_from_unity.ps1")


def _scan_ps1_write_lines_for_japanese(path: str) -> list[str]:
    hits = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if ("Write-Host" in stripped or "Write-Error" in stripped) and _JAPANESE_RE.search(
                stripped
            ):
                hits.append(stripped)
    return hits


def test_export_from_unity_ps1_write_lines_have_no_japanese():
    assert os.path.isfile(_PS1_PATH), f"not found: {_PS1_PATH}"
    hits = _scan_ps1_write_lines_for_japanese(_PS1_PATH)
    assert hits == [], (
        "export_from_unity.ps1のWrite-Host/Write-Errorに日本語が残っている"
        f"(prefab入力時にGUIログ欄へ混じるdev#596の再発): {hits}"
    )


def test_scan_ps1_helper_negative_control_detects_injected_japanese(tmp_path):
    """負の対照: ps1用スキャン関数もダミーファイルで検出できることを確認する。"""
    dummy = tmp_path / "dummy_export.ps1"
    dummy.write_text('Write-Host "プロジェクト: $proj"\n', encoding="utf-8")
    hits = _scan_ps1_write_lines_for_japanese(str(dummy))
    assert len(hits) == 1


# ---------------------------------------------------------------------------
# (5) dev#896: self._log(...) が i18n.F()/i18n.S() を経由して「現在のUI言語」
#     をそのまま実行ログ(console/launch.log。サポート問い合わせで「ログを
#     コピー」される診断ログ)へ流し込んでいないこと(静的スキャン、負の対照
#     つき)。
#
#     背景: 上の(3)は main_window.py の該当行に日本語が「直書き」されている
#     場合しか捕まえられない。dev#896で見つかった行
#     (self._log(i18n.F("LogUnityExportHeartbeatFormat", elapsed_str)))は
#     日本語が i18n_data.json 側にしかなく、ソース上は英数字のみの
#     i18n.F(...) 呼び出しだったため(3)の網をすり抜けた。「self._log(...)へ
#     渡す引数がi18n.F()/i18n.S()を呼んでいて、かつ現在のUI言語に追従して
#     しまう(lang="en"で固定されていない)」という構造そのものを検出する
#     ことで、ファイル単位の列挙を増やさずに同種の漏れを一般に捕まえる
#     (「ユーザー向けログ出力の共通経路」= self._log() の呼び出し形一般を
#     対象にする)。
#
#     例外: main_window.py の _check_work_root_failed_on_startup /
#     _check_path_health_on_startup (dev896-i18n-log-allow マーカー付き)は、
#     直後に同文言でmessagebox.show*を出す「画面表示中の警告ダイアログと
#     ログ欄の表示言語を一致させる」意図的設計(dev#596の受入条件「警告・
#     案内文言」に該当し、診断専用ログとは別枠)であり、行内マーカー
#     コメントで明示的に除外している。
# ---------------------------------------------------------------------------

_ALLOW_MARKER = "dev896-i18n-log-allow"


def _find_matching_close_paren(text: str, open_idx: int) -> int:
    """text[open_idx]が'('であることを前提に、対応する')'のインデックスを
    返す(文字列リテラル内の括弧は無視する簡易パーサ)。見つからなければ-1。"""
    depth = 0
    i = open_idx
    in_str: str | None = None
    while i < len(text):
        ch = text[i]
        if in_str is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ("'", '"'):
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _scan_log_calls_for_unforced_i18n(source: str) -> list[str]:
    """self._log(...) の呼び出し全体(複数行にまたがる場合も含む)を走査し、
    引数がi18n.F(/i18n.S(を呼んでいるのに lang="en"(または lang='en')で
    固定していないものを列挙する(_ALLOW_MARKER付きの呼び出しはスキップ)。
    戻り値は該当呼び出しの内容(先頭行番号つき)のリスト。"""
    hits: list[str] = []
    marker = "self._log("
    search_from = 0
    while True:
        idx = source.find(marker, search_from)
        if idx == -1:
            break
        open_idx = idx + len(marker) - 1
        close_idx = _find_matching_close_paren(source, open_idx)
        if close_idx == -1:
            break
        call_text = source[idx : close_idx + 1]
        search_from = close_idx + 1

        # 呼び出し直前の連続するコメント/空行(マーカーが書かれる場所)+
        # 呼び出し全体に許可マーカーがあれば除外。連続するコメント行を
        # さかのぼれるだけさかのぼる(コメントが複数行に渡っていてもよい)。
        line_start = source.rfind("\n", 0, idx) + 1
        scan_start = line_start
        while scan_start > 0:
            prev_start = source.rfind("\n", 0, scan_start - 1) + 1
            prev_line = source[prev_start : scan_start - 1].strip()
            if prev_line.startswith("#") or prev_line == "":
                scan_start = prev_start
            else:
                break
        nearby = source[scan_start : close_idx + 1]
        if _ALLOW_MARKER in nearby:
            continue

        has_i18n_call = "i18n.F(" in call_text or "i18n.S(" in call_text
        forced_english = 'lang="en"' in call_text or "lang='en'" in call_text
        if has_i18n_call and not forced_english:
            line_no = source.count("\n", 0, idx) + 1
            hits.append(f"L{line_no}: {call_text.strip()}")
    return hits


def test_main_window_log_calls_do_not_leak_current_ui_language():
    main_window_path = os.path.join(_APP_PY_DIR, "ui", "main_window.py")
    with open(main_window_path, encoding="utf-8") as fh:
        source = fh.read()
    hits = _scan_log_calls_for_unforced_i18n(source)
    assert hits == [], (
        "main_window.pyのself._log()が、現在のUI言語に追従するi18n.F()/i18n.S()の"
        "結果をlang=\"en\"固定せずにそのまま渡している(dev#896: UI言語が日本語だと"
        f"実行ログにも日本語が混じる、意図的な例外は{_ALLOW_MARKER}マーカーで明示すること): "
        f"{hits}"
    )


def test_scan_unforced_i18n_negative_control_detects_original_bug():
    """負の対照: dev#896で見つかった修正前のコード
    (`self._log(i18n.F("LogUnityExportHeartbeatFormat", elapsed_str))`)を
    模したダミー行が、拡張後のスキャンで検出されることを確認する。"""
    dummy_source = (
        "def _maybe_emit_unity_export_heartbeat(self) -> None:\n"
        '    self._log(i18n.F("LogUnityExportHeartbeatFormat", elapsed_str))\n'
    )
    hits = _scan_log_calls_for_unforced_i18n(dummy_source)
    assert len(hits) == 1


def test_scan_unforced_i18n_negative_control_ignores_allow_marker():
    """許可マーカー付きの意図的な既存パターン(work root/path health相当)は
    誤検知しないことを確認する。"""
    dummy_source = (
        "def handler(self):\n"
        "    # dev896-i18n-log-allow: mirrors dialog language intentionally\n"
        '    self._log("[!] " + i18n.S("TitleWorkRootUnwritable"))\n'
    )
    hits = _scan_log_calls_for_unforced_i18n(dummy_source)
    assert hits == []


def test_scan_unforced_i18n_accepts_lang_en_forced_calls():
    """本WPの修正後パターン(lang="en"固定)は誤検知しないことを確認する。"""
    dummy_source = (
        "def handler(self):\n"
        '    self._log(i18n.S("LogUnityExportHeartbeatFormat", lang="en").format(elapsed_str))\n'
    )
    hits = _scan_log_calls_for_unforced_i18n(dummy_source)
    assert hits == []


# ---------------------------------------------------------------------------
# (6) dev#896: 実行時の確認。UI言語を日本語に切り替えた状態でもUnityエクス
#     ポートのハートビート行が英語で出ること(静的スキャンだけでなく、実際の
#     出力でも確認する)。
# ---------------------------------------------------------------------------


class _FakeLabelForHeartbeat:
    def __init__(self) -> None:
        self.text = None

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]


class _FakeSelfForHeartbeat:
    """_maybe_emit_unity_export_heartbeatを未束縛メソッドとして直接呼ぶための
    最小self(test_unity_export_heartbeat.pyの_FakeSelfと同型、本ファイル内で
    完結させるため独立に定義)。"""

    def __init__(self) -> None:
        import pipeline_runner as pr

        self.widgets = {"statusLabel": _FakeLabelForHeartbeat()}
        self.logged: list[str] = []
        self._active_phase = pr.PHASE_UNITY_EXPORT
        self._unity_export_started_at = 1000.0
        self._unity_export_last_output_at = 1000.0

    def _log(self, text: str) -> None:
        self.logged.append(text)

    _maybe_emit_unity_export_heartbeat = mw.MainWindow._maybe_emit_unity_export_heartbeat
    # dev#897: statusLabel設定がself._set_status()経由に変わったための追加束縛
    # (PR #904がtest_unity_export_heartbeat.py側の同型フィクスチャは更新済み
    # だったが、本ファイル内の独立フィクスチャは対象外だったため、
    # #904マージ後の統合作業で追随。CIには一切触れない運用のためローカル
    # pytestで検知、master直コミットで解消)。
    _set_status = mw.MainWindow._set_status


def test_unity_export_heartbeat_log_is_english_when_ui_language_is_japanese(monkeypatch):
    """dev#896の再現+修正確認: UI表示言語が日本語でも、ハートビートの
    self._log()行には日本語が出ないこと。"""
    import i18n

    original_lang = i18n.current_lang
    try:
        i18n.set_language("ja")
        fake_self = _FakeSelfForHeartbeat()
        monkeypatch.setattr(mw.time, "monotonic", lambda: 1017.0)  # 17秒経過
        fake_self._maybe_emit_unity_export_heartbeat()
        assert len(fake_self.logged) == 1
        logged_text = fake_self.logged[0]
        assert not _JAPANESE_RE.search(logged_text), (
            f"UI言語が日本語のときハートビートのログ行に日本語が残っている: {logged_text!r}"
        )
        assert "00:17" in logged_text
        assert "Still running" in logged_text
        # statusLabel(画面表示)は従来どおりUI言語に追従してよい(ここは
        # ユーザーが見る画面表示であり、診断ログとは別枠)
        assert i18n.S("StatusUnityExporting", lang="ja") in fake_self.widgets["statusLabel"].text
    finally:
        i18n.set_language(original_lang)


def test_unity_export_heartbeat_log_negative_control_detects_unforced_regression(monkeypatch):
    """負の対照: もし将来lang="en"固定が外れて元のi18n.F()呼び出しに戻ったら、
    このテスト自身が再現できることを確認する(_scan_log_calls_for_unforced_i18n
    と同じ土俵で、実行時にも検出可能なことの裏付け)。"""
    import i18n

    original_lang = i18n.current_lang
    try:
        i18n.set_language("ja")
        # dev#896修正前と同じ組み立て方をここで再現する
        regressed_text = i18n.F("LogUnityExportHeartbeatFormat", "00:17")
        assert _JAPANESE_RE.search(regressed_text), (
            "この負の対照は、修正前と同じ組み立て方(i18n.F()を現在言語のまま使う)が"
            "日本語UIのとき日本語を出すこと自体を確認するためのもの"
        )
    finally:
        i18n.set_language(original_lang)
