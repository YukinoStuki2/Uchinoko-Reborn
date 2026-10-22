# test_untranslated_gui_dev939.py -- dev#939: 外部プロセスの生文字列がGUIへ
# 未翻訳で到達する経路のうち、①Blenderセットアップ失敗案内・②AVATAR_WARNING
# の2箇所を、dev#933(##PROGRESS##phase)で確立した「識別子→i18nキーへの
# 写像+未知の値は生文字列へフォールバック」方式へ揃える修理を検証する。
#
# 背景:
#   ① app_py\ui\main_window.py::_on_blender_setup_done() の fail_message は、
#      pipeline\cli\ensure_blender.ps1(dev#21で純ASCII化。本WPでは書き換え
#      禁止)のShow-D2PFailureGuidanceが出す[D2P_BLENDER_SETUP_FAIL]案内文
#      (複数行、常に英語)を未翻訳のまま_set_status()/messagebox.askyesno()
#      へ渡していた(dev#897で一度スコープ外として自己申告された点)。
#   ② pipeline\py\convert_noue.py が出す##AVATAR_WARNING##(固定英語
#      テンプレート3種+可変部)が、messagebox.showwarning()のモーダルへ
#      未翻訳で到達していた。
#
# tkの実ウィンドウは一切開かない(test_blender_phase_i18n_dev933.pyと同型の
# フェイクself方式。禁止領域「ホスト画面への干渉禁止」を厳守)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pipeline_runner as pr  # noqa: E402
from ui import main_window as mw  # noqa: E402


def setup_function(_fn) -> None:
    i18n.set_language("ja")


def teardown_function(_fn) -> None:
    i18n.set_language("ja")


# ---------------------------------------------------------------------------
# ② pipeline_runner.translate_avatar_warning() 単体
# ---------------------------------------------------------------------------

_AVATAR_WARNING_SAMPLES = [
    (
        "Color information for some materials could not be retrieved, so they "
        "may not display correctly (material=Body)",
        "一部のマテリアルの色情報を取得できなかったため、正しく表示されない"
        "可能性があります(material=Body)",
    ),
    (
        "This avatar has an unusual UV structure and may not display correctly "
        "(affected material: male body(overshoot=0.120))",
        "このアバターは特殊なUV構造を持っているため、正しく表示されない"
        "可能性があります(影響を受けるマテリアル: male body(overshoot=0.120))",
    ),
    (
        "The post-atlas visual check could not be run (male: no comparison "
        "material available). Conversion continues, but broken visuals will "
        "not be automatically detected",
        "アトラス化後の見た目チェックを実行できませんでした(male: no "
        "comparison material available)。変換は続行しますが、見た目の破損は"
        "自動検出されません",
    ),
    # dev#1417: テクスチャ既定柄フォールバックのfail-loud化(pipeline\py\
    # vp_tex.py::tex_fallback_diagnostics()が新規に出す2種)。
    (
        "Texture file 't00.png' has a .png extension but is not a valid PNG, "
        "so the template's default texture is used instead",
        "テクスチャファイル『t00.png』は拡張子が.pngですが実際のPNGでは"
        "ないため、テンプレートの既定テクスチャを使用します",
    ),
    (
        "Texture file 't01.jpg' is not a PNG file, so the template's default "
        "texture is used instead",
        "テクスチャファイル『t01.jpg』はPNGファイルではないため、"
        "テンプレートの既定テクスチャを使用します",
    ),
    (
        # dev#1468: アトラス視覚チェックFAILがdie()から警告降格したことに伴う
        # 新テンプレート(pipeline_runner.py::_AVATAR_WARNING_TEMPLATES)。
        "The post-atlas visual check detected a possible mismatch (female: "
        "tile_min_ncc=0.6957 < 0.70 (patch=64, worst_tile=(320, 128))). "
        "Conversion continues, but please check the appearance of the "
        "converted avatar",
        "アトラス化後の見た目チェックで差異を検出しました(female: "
        "tile_min_ncc=0.6957 < 0.70 (patch=64, worst_tile=(320, 128)))。"
        "変換は続行しますが、変換結果の見た目をご確認ください",
    ),
]


def test_all_avatar_warning_templates_translate_to_japanese():
    for raw, expected_ja in _AVATAR_WARNING_SAMPLES:
        assert pr.translate_avatar_warning(raw, lang="ja") == expected_ja, raw


def test_all_avatar_warning_templates_translate_to_english_identity():
    # 原文(convert_noue.pyが出す文字列そのもの)は英語文言でもあるため、
    # en訳は原文と一致する。
    for raw, _expected_ja in _AVATAR_WARNING_SAMPLES:
        assert pr.translate_avatar_warning(raw, lang="en") == raw, raw


def test_all_five_languages_present_and_distinct_for_every_avatar_warning():
    for raw, _expected_ja in _AVATAR_WARNING_SAMPLES:
        for lang in i18n.LANGS:
            text = pr.translate_avatar_warning(raw, lang=lang)
            assert text, f"{raw}/{lang} が空(未実装/データ欠落)"
            if lang != "en":
                assert text != raw, f"{raw}/{lang}: 翻訳されず原文のまま(退行)"


def test_unknown_avatar_warning_falls_back_to_raw_text_not_blank_not_marker():
    # 負の対照1: convert_noue.py側に将来テンプレートが増えた/文言が変わった
    # ケースを模す。無言の空欄にも "??key??" にもならず、原文が残ること。
    mutated = "Something entirely new went wrong (detail=xyz)"
    result = pr.translate_avatar_warning(mutated, lang="ja")
    assert result == mutated
    assert result != ""
    assert "??" not in result


def test_empty_avatar_warning_returns_empty_not_marker():
    assert pr.translate_avatar_warning("", lang="ja") == ""


# ---------------------------------------------------------------------------
# ② 配線の実証: _on_pipeline_line()経由で_pipeline_warningsへ翻訳済み文言が
# 積まれ、ログ欄(_log)には引き続き英語の生行が残ること(dev#690の教訓
# =色診断に必要な原文情報を落とさない、と両立させる)。
# ---------------------------------------------------------------------------


class _FakeBusyBarDict(dict):
    pass


class _FakeSelfForPipelineLine:
    def __init__(self) -> None:
        self.widgets = {
            "busyBar": _FakeBusyBarDict({"mode": "indeterminate", "value": 0}),
            "statusLabel": type("L", (), {"config": lambda self, **kw: None})(),
        }
        self._active_handle = None
        self._early_preview_loaded_this_run = False
        self._pipeline_warnings: list[str] = []
        self.logged: list[str] = []

    def _log(self, text: str) -> None:
        self.logged.append(text)

    _set_busy_bar_mode = mw.MainWindow._set_busy_bar_mode
    _on_pipeline_line = mw.MainWindow._on_pipeline_line
    _set_status = mw.MainWindow._set_status


def test_on_pipeline_line_translates_avatar_warning_for_popup_list():
    i18n.set_language("ja")
    fake_self = _FakeSelfForPipelineLine()
    fake_self._on_pipeline_line(
        "##AVATAR_WARNING## Color information for some materials could not be "
        "retrieved, so they may not display correctly (material=Body)"
    )
    assert fake_self._pipeline_warnings == [
        "一部のマテリアルの色情報を取得できなかったため、正しく表示されない"
        "可能性があります(material=Body)"
    ]
    # ログ欄は引き続き英語の生行(##AVATAR_WARNING##つき)のまま
    assert fake_self.logged == [
        "##AVATAR_WARNING## Color information for some materials could not be "
        "retrieved, so they may not display correctly (material=Body)"
    ]


def test_on_pipeline_line_unknown_avatar_warning_still_reaches_popup_list():
    # 負の対照の配線版: どのテンプレートにも一致しない警告文でも、
    # ポップアップ用リストから消えたり空文字になったりしないこと。
    i18n.set_language("ja")
    fake_self = _FakeSelfForPipelineLine()
    fake_self._on_pipeline_line("##AVATAR_WARNING## brand new warning text")
    assert fake_self._pipeline_warnings == ["brand new warning text"]


# ---------------------------------------------------------------------------
# ① main_window.translate_blender_setup_fail_message() 単体
# ---------------------------------------------------------------------------

_FAIL_MESSAGE_SAMPLE = (
    '[D2P_BLENDER_SETUP_FAIL] Blender setup failed.\n'
    'Reason: The remote server returned an error: (404) Not Found.\n'
    '\n'
    'What to try:\n'
    '  1. Check your internet connection, then press "Full Convert (Create MOD)" '
    'or "Update Preview" again.\n'
    '  2. If automatic download keeps failing, you can also set it up manually:\n'
    '       (1) Download the Windows x64 Portable (zip) build of Blender 4.3.2 '
    'from https://www.blender.org/download/\n'
    '       (2) Extract it, then copy the contents of the folder containing '
    'blender.exe directly into:\n'
    '           C:\\P\\Work\\DiveToPalworld\\assets\\tools\\blender-4.3.2-windows-x64\n'
    '\n'
    'Diagnostic info (path structure only, no folder names included):\n'
    '  [D2P_PATH_SHAPE] step=AppRoot(received as argument) len=25 seg=5\n'
    '  [D2P_PATH_SHAPE] step=TargetDir(built from AppRoot) len=60 seg=8'
)


def test_fail_message_translates_fixed_lines_to_japanese():
    result = mw.translate_blender_setup_fail_message(_FAIL_MESSAGE_SAMPLE, lang="ja")
    assert "Blenderのセットアップに失敗しました。" in result
    assert "理由: The remote server returned an error: (404) Not Found." in result
    assert "お試しください:" in result
    assert "自動ダウンロードが繰り返し失敗する場合は" in result
    assert (
        "(1) https://www.blender.org/download/ からBlender 4.3.2 の"
        "Windows x64 Portable(zip)版をダウンロードする" in result
    )
    assert "診断情報(パス構造のみ、フォルダ名は含みません):" in result
    # 未知構造として意図的に翻訳対象外にした行(実パス・診断行)は原文のまま残る
    assert r"C:\P\Work\DiveToPalworld\assets\tools\blender-4.3.2-windows-x64" in result
    assert "[D2P_PATH_SHAPE] step=AppRoot(received as argument) len=25 seg=5" in result
    # 未翻訳のまま素通しだった旧文言が残っていないこと
    assert "Blender setup failed." not in result
    assert "What to try:" not in result


def test_fail_message_english_matches_raw_except_technical_marker():
    result = mw.translate_blender_setup_fail_message(_FAIL_MESSAGE_SAMPLE, lang="en")
    expected = _FAIL_MESSAGE_SAMPLE.replace(
        "[D2P_BLENDER_SETUP_FAIL] Blender setup failed.", "Blender setup failed."
    )
    assert result == expected


def test_fail_message_all_five_languages_translate_header_line():
    for lang in i18n.LANGS:
        result = mw.translate_blender_setup_fail_message(_FAIL_MESSAGE_SAMPLE, lang=lang)
        assert result, f"{lang} が空(未実装/データ欠落)"
        assert "[D2P_BLENDER_SETUP_FAIL]" not in result


def test_unknown_fail_message_falls_back_to_raw_text_not_blank_not_marker():
    # 負の対照1: ensure_blender.ps1側の構造が変わった/一致しないケースを模す。
    mutated = "Blender not found"
    result = mw.translate_blender_setup_fail_message(mutated, lang="ja")
    assert result == mutated
    assert result != ""
    assert "??" not in result


def test_empty_fail_message_returns_empty_not_marker():
    assert mw.translate_blender_setup_fail_message("", lang="ja") == ""


# ---------------------------------------------------------------------------
# dev#1242: blender_setup.run_ensure_blender_setup_process()がPowerShell実行
# ファイル自体の起動に失敗した場合(WinError2等)に返す
# blender_setup.LAUNCH_FAIL_HEADER + "Reason: {ex}" の言語混在解消を検証する。
#
# 実ユーザー報告(issue本文): 「status: ensure_blender.ps1の起動に失敗しました:
# [WinError 2] 系统找不到指定的文件。」(日本語のツール文言+中国語のOS例外文字列
# が1文に混在)。旧実装はこのメッセージをmain_window.pyの翻訳機構を経由しない
# 独自ハードコード文字列として組み立てていたため、UI言語に関わらず常にこの
# 混在が発生していた。新実装(blender_setup.py)は既存の
# [D2P_BLENDER_SETUP_FAIL]構造に乗せることで、ヘッダ部分だけがUI言語へ翻訳され、
# OS生例外文字列は"Reason: "行の詳細としてそのまま(=解析用に消えない)残る。
# ---------------------------------------------------------------------------

import blender_setup as bs  # noqa: E402


def _build_launch_fail_message(raw_os_exception_text: str) -> str:
    # run_ensure_blender_setup_process()のOSError捕捉部と同じ組み立て方
    # (blender_setup.py L.561-562相当)を、実プロセスを起動せず直接再現する。
    return f"{bs.LAUNCH_FAIL_HEADER}\nReason: {raw_os_exception_text}"


def test_launch_fail_header_translates_to_japanese_without_mixing():
    # issueの再現ケース: OS例外文字列は中国語(WinError2、実ユーザーのOS言語)。
    raw = _build_launch_fail_message("[WinError 2] 系统找不到指定的文件")
    result = mw.translate_blender_setup_fail_message(raw, lang="ja")
    # ヘッダはUI言語(日本語)へ翻訳される
    assert "Blenderセットアップの起動に失敗しました。" in result
    # マーカー・旧ハードコード文言は残らない
    assert "[D2P_BLENDER_SETUP_FAIL]" not in result
    assert "Failed to launch ensure_blender.ps1." not in result
    # OS生例外文字列は"理由: "の詳細として引き続き読める(診断情報を消さない)
    assert "理由: [WinError 2] 系统找不到指定的文件" in result


def test_launch_fail_header_all_five_languages_distinct_and_non_empty():
    raw = _build_launch_fail_message("[WinError 2] The system cannot find the file specified")
    seen = set()
    for lang in i18n.LANGS:
        result = mw.translate_blender_setup_fail_message(raw, lang=lang)
        assert result, f"{lang} が空(未実装/データ欠落)"
        assert "[D2P_BLENDER_SETUP_FAIL]" not in result
        # OS生例外文字列(詳細)はどの言語でも消えずに残る
        assert "The system cannot find the file specified" in result
        seen.add(result)
    # 5言語とも異なる文言(未実装で原文のまま素通しになっていないこと)
    assert len(seen) == len(i18n.LANGS)


def test_launch_fail_header_english_matches_raw_except_technical_marker():
    raw = _build_launch_fail_message("[WinError 2] The system cannot find the file specified")
    result = mw.translate_blender_setup_fail_message(raw, lang="en")
    expected = raw.replace(bs.LAUNCH_FAIL_HEADER, "Failed to launch ensure_blender.ps1.")
    assert result == expected


# ---------------------------------------------------------------------------
# dev#19 uimock2_fixes評価#6の副産物(2026-08-11): 揺れものUIの英語表示を
# 実機(WSB)確認していたところ、無関係の別経路で言語混在を実際に発見した。
# blender_setup.do_ensure_blender_ready()のDEV_NOT_FOUND_NO_SCRIPT分岐
# (開発チェックアウト等でensure_blender.ps1もblender.exeも見つからない場合)
# が、生の日本語文字列をPython側から直接返していた。このモジュールは
# 「UIに触れない」設計(do_ensure_blender_ready()のdocstring参照)であり、
# i18n_data.jsonを経由しない――つまり test_i18n_keys.py の全キー完全性検査
# (test_table_all_keys_all_languages_non_empty)はi18n.TABLEに登録された
# キーしか見ないため、この経路をそもそも検査対象に含められず、無力だった
# (「i18nキー漏れテストが緑なのに漏れた」の実例)。
#
# 修理はdev#1242(LAUNCH_FAIL_HEADER)と全く同じ型: blender_setup.py側は
# 英語ASCIIを返し、main_window.py側の_BLENDER_SETUP_FAIL_LINE_TEMPLATESへ
# 行単位の翻訳規則を追加する。
# ---------------------------------------------------------------------------


def test_dev_not_found_message_is_ascii_not_hardcoded_japanese(tmp_path, monkeypatch):
    # 負の対照込み: blender_setup.py側が返す生メッセージ自体に、もう
    # 日本語(CJK文字)が含まれていないことを機械検査する(この経路がi18n化
    # されずに日本語のまま素通しされていた旧不具合そのものの再発防止)。
    import re as _re
    monkeypatch.setattr(
        bs, "_DEV_FALLBACK_BLENDER_DIR", str(tmp_path / "no_such_blender_dir")
    )
    ok, fail_message, action = bs.do_ensure_blender_ready(str(tmp_path))
    assert ok is False
    assert action == bs.BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT
    assert fail_message is not None
    cjk = _re.compile(r"[\u3040-\u30FF\u4E00-\u9FFF]")
    assert not cjk.search(fail_message), (
        f"blender_setup.py側が生の日本語を返している(i18n未経由): {fail_message!r}"
    )
    assert fail_message.startswith("Blender not found (dev environment): ")


def test_dev_not_found_message_translates_to_japanese_without_mixing():
    raw = "Blender not found (dev environment): C:\\some\\path\\blender.exe"
    result = mw.translate_blender_setup_fail_message(raw, lang="ja")
    assert result == "Blenderが見つかりません(開発環境): C:\\some\\path\\blender.exe"
    assert "Blender not found" not in result


def test_dev_not_found_message_all_five_languages_distinct_and_non_empty():
    raw = "Blender not found (dev environment): C:\\some\\path\\blender.exe"
    seen = set()
    for lang in i18n.LANGS:
        result = mw.translate_blender_setup_fail_message(raw, lang=lang)
        assert result, f"{lang} が空(未実装/データ欠落)"
        assert "C:\\some\\path\\blender.exe" in result  # 実パスは言語問わず残る
        seen.add(result)
    assert len(seen) == len(i18n.LANGS)


def test_dev_not_found_message_english_matches_raw_identity():
    raw = "Blender not found (dev environment): C:\\some\\path\\blender.exe"
    result = mw.translate_blender_setup_fail_message(raw, lang="en")
    assert result == raw  # 英語UIでは無改変(この行はそもそも英語ASCIIのため)


# ---------------------------------------------------------------------------
# ① 配線の実証: _on_blender_setup_done()経由でstatusLabel/次アクション導線
# (_offer_report_after_failure)まで翻訳済み文言が届くこと。
# ---------------------------------------------------------------------------


class _FakeLabel:
    def __init__(self) -> None:
        self.text: str | None = None

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]


class _FakeButtonPlace:
    def __init__(self) -> None:
        self.forgot = False
        self.placed = False

    def place(self, **kwargs) -> None:
        self.placed = True

    def place_forget(self) -> None:
        self.forgot = True


class _FakeSelfForBlenderSetupDone:
    def __init__(self) -> None:
        self.widgets = {
            "busyBar": _FakeButtonPlace(),
            "statusLabel": _FakeLabel(),
            "blenderRetryButton": _FakeButtonPlace(),
        }
        self._update_button_states = lambda: None
        # dev#1239: _on_blender_setup_done()がconvertButtonのゲート再計算を明示的に
        # 呼ぶようになったため(本ファイルの対象外の関心事なのでno-opで済ませる)。
        self._refresh_convert_button_freshness = lambda: None
        self._warm_startup_after_blender_ready = lambda: None
        self.offers: list[str] = []
        self._offer_report_after_failure = lambda cause: self.offers.append(cause)
        self.logged: list[str] = []
        self._log = lambda text, **_k: self.logged.append(text)

    _on_blender_setup_done = mw.MainWindow._on_blender_setup_done
    _set_status = mw.MainWindow._set_status


def test_on_blender_setup_done_shows_japanese_fail_guidance_in_status_label():
    i18n.set_language("ja")
    fake_self = _FakeSelfForBlenderSetupDone()
    fake_self._on_blender_setup_done(
        False, _FAIL_MESSAGE_SAMPLE, mw.blender_setup.BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT
    )
    text = fake_self.widgets["statusLabel"].text
    assert text is not None
    assert "Blenderのセットアップに失敗しました。" in text
    assert "Blender setup failed." not in text
    # 次アクション導線(問い合わせオファー)にも同じ翻訳済み文言が渡ること
    assert fake_self.offers == [text]


def test_on_blender_setup_done_short_unknown_fail_message_unchanged():
    # 負の対照の配線版: dev#23bのBlenderManualPathError等、ps1由来ではない
    # 短い既存メッセージ("Blender not found"等)は従来どおり無変化のまま届く。
    i18n.set_language("ja")
    fake_self = _FakeSelfForBlenderSetupDone()
    fake_self._on_blender_setup_done(
        False, "Blender not found", mw.blender_setup.BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT
    )
    assert fake_self.widgets["statusLabel"].text == "Blender not found"
    assert fake_self.offers == ["Blender not found"]
