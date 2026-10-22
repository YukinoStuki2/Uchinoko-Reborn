# test_blender_phase_i18n_dev933.py -- dev#933: Blenderセットアップ##PROGRESS##
# phaseトークンのGUI表示言語退行(PR #922/dev#21 ensure_blender.ps1純ASCII化に
# 伴う副作用)の修理を検証する。
#
# 背景: pipeline\cli\ensure_blender.ps1 (dev#21で純ASCII化。本WPでは書き換え
# 禁止) が出す `##PROGRESS## <pct> <phase>` のphaseはASCII固定文字列のまま。
# GUI側(app_py\ui\main_window.py::_on_blender_progress)がこのphaseを直接
# i18n.F() へ渡していたため、日本語UIでもBlenderセットアップ中の進捗フェーズ
# 文言だけ英語のまま出ていた(convert_noue.py側の##PROGRESS##は
# i18n.translate_progress_label()/pipeline_runner.translate_progress_label_dynamic()
# 経由で既に翻訳されていたが、Blenderセットアップ専用の別経路だけがこの機構を
# 経由していなかった)。translate_blender_phase()による変換が実際の
# statusLabelまで届くところまで検証する(「実装した」と「効いている」は別、
# を実測で確認する。CLAUDE.md「検証の作法」節)。
#
# tkの実ウィンドウは一切開かない(test_progress_eta_wiring.py等と同型の
# フェイクself方式。禁止領域「ホスト画面への干渉禁止」を厳守)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402


# ---------------------------------------------------------------------------
# フェイク部品(test_progress_eta_wiring.py._FakeSelfForPipelineLineと同型)
# ---------------------------------------------------------------------------


class _FakeLabel:
    def __init__(self) -> None:
        self.text: str | None = None

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]


class _FakeBusyBar(dict):
    """widgets["busyBar"]の最小代替。_on_blender_progress()が呼ぶ
    .place(...)(no-op)と["value"]=pct(dict代入)の両方に応える。"""

    def place(self, **kwargs) -> None:
        pass


class _FakeSelfForBlenderProgress:
    """_on_blender_progress()を未束縛のまま呼ぶための最小self。"""

    def __init__(self) -> None:
        self.widgets = {
            "busyBar": _FakeBusyBar(),
            "statusLabel": _FakeLabel(),
        }

    _on_blender_progress = mw.MainWindow._on_blender_progress
    _set_status = mw.MainWindow._set_status


def setup_function(_fn) -> None:
    i18n.set_language("ja")


def teardown_function(_fn) -> None:
    i18n.set_language("ja")


# ---------------------------------------------------------------------------
# translate_blender_phase() 単体: 固定辞書11件が全てja訳される
# (ja訳文はPR #922マージ前=815bc82^の原文をそのまま復元したもの。ただし
# Verifying integrity (SHA256)/Verifying Python environment (import ooz)の
# 2件は、GUI文言総点検WP(2026-08-09)でja/ko/zhTW/zhCNから開発者向け実装詳細
# "(SHA256)"/"(import ooz)"を除去した。raw文字列(=en訳)自体がensure_blender.
# ps1側の固定文字列でありこのWPの書き込み許可外のため、enはraw同一のまま
# 据え置き=技術詳細が残る。ja/ko/zhTW/zhCNだけ非対称に改善する形になるが、
# 開発者向け語彙除去を優先した判断)
# ---------------------------------------------------------------------------

_STATIC_PHASES_JA = {
    "Checking Blender status": "Blenderの状態を確認中",
    "Blender is ready": "Blenderは準備済みです",
    "Checking free disk space": "ディスク空き容量を確認中",
    "Using specified zip (no download, test/offline mode)": (
        "指定zipを使用します(ダウンロードなし、試験/オフライン用)"
    ),
    "Verifying integrity (SHA256)": "整合性を確認中",
    "Extracting": "展開中",
    "Extraction complete": "展開完了",
    "Injecting Python environment patches": "Python環境の差し込みを実行中",
    "Verifying Python environment (import ooz)": "Python環境の動作検証中",
    "Moving to final location": "最終配置に移動中",
    "Blender setup complete": "Blenderのセットアップ完了",
}


def test_all_static_phases_translate_to_japanese():
    for raw, expected_ja in _STATIC_PHASES_JA.items():
        assert mw.translate_blender_phase(raw, lang="ja") == expected_ja, raw


def test_all_static_phases_translate_to_english_identity():
    # 原文(ps1が出す文字列そのもの)は英語文言でもあるため、en訳は原文と一致する
    for raw in _STATIC_PHASES_JA:
        assert mw.translate_blender_phase(raw, lang="en") == raw, raw


def test_all_five_languages_present_and_distinct_for_every_new_static_phase():
    for raw in _STATIC_PHASES_JA:
        for lang in i18n.LANGS:
            text = mw.translate_blender_phase(raw, lang=lang)
            assert text, f"{raw}/{lang} が空(未実装/データ欠落)"
            if lang != "en":
                assert text != raw, f"{raw}/{lang}: 翻訳されず原文のまま(退行)"


# ---------------------------------------------------------------------------
# 可変部を含むphase(ダウンロード進捗MB数・展開ファイル数・バージョン埋め込み)
# ---------------------------------------------------------------------------


def test_dynamic_download_official_site_phase_translates_with_version():
    raw = "Downloading Blender 4.3.2 (official site, ~390MB)"
    assert (
        mw.translate_blender_phase(raw, lang="ja")
        == "Blender 4.3.2 をダウンロード中(公式サイト、約390MB)"
    )


def test_dynamic_download_mirror_phase_translates_with_version():
    raw = "Downloading Blender 4.3.2 (mirror, ~390MB)"
    assert (
        mw.translate_blender_phase(raw, lang="ja")
        == "Blender 4.3.2 をダウンロード中(ミラー、約390MB)"
    )


def test_dynamic_download_progress_mb_phase_translates_with_both_numbers():
    raw = "Downloading (12.3MB / 390.0MB)"
    assert mw.translate_blender_phase(raw, lang="ja") == "ダウンロード中 (12.3MB / 390.0MB)"


def test_dynamic_extraction_file_count_phase_translates_with_both_counts():
    raw = "Extracting (123 / 6292 files)"
    assert mw.translate_blender_phase(raw, lang="ja") == "展開中 (123 / 6292 ファイル)"


def test_dynamic_phases_translate_in_english_identity_too():
    # 英語UIではダウンロード先を変えても原文どおり(=無変化)であることを確認
    raw = "Downloading (1.0MB / 2.0MB)"
    assert mw.translate_blender_phase(raw, lang="en") == raw


# ---------------------------------------------------------------------------
# 負の対照1: 未知phase(ps1側トークンが変わった/一致しない)は
# 無言で空欄にも "??key??" にもならず、原文そのままへフォールバックする
# (i18n.py既存のtranslate_progress_label()と同じブラックリスト方式を踏襲。
# 選択理由: 未知phaseでもログ/画面から情報が消えないことを最優先する)
# ---------------------------------------------------------------------------


def test_unknown_static_phase_falls_back_to_raw_text_not_blank_not_marker():
    # ps1側のphaseトークンを意図的に1文字変えた(想定される最小の入力ずれ)
    mutated = "Checking Blender statuz"
    result = mw.translate_blender_phase(mutated, lang="ja")
    assert result == mutated
    assert result != ""
    assert "??" not in result


def test_unknown_dynamic_phase_falls_back_to_raw_text():
    # 単位をMB->GBに変える等、どのregexにも一致しない可変部phase
    mutated = "Downloading (12.3GB / 390.0GB)"
    result = mw.translate_blender_phase(mutated, lang="ja")
    assert result == mutated
    assert result != ""
    assert "??" not in result


def test_empty_phase_returns_empty_not_marker():
    assert mw.translate_blender_phase("", lang="ja") == ""


# ---------------------------------------------------------------------------
# 配線の実証: _on_blender_progress()経由でstatusLabelまで翻訳文言が届くこと
# (「実装した」と「効いている」は別、を実測する)
# ---------------------------------------------------------------------------


def test_on_blender_progress_shows_japanese_phase_in_status_label():
    fake_self = _FakeSelfForBlenderProgress()
    i18n.set_language("ja")
    fake_self._on_blender_progress(42, "Checking free disk space")
    text = fake_self.widgets["statusLabel"].text
    assert text is not None
    assert "ディスク空き容量を確認中" in text
    assert "Checking free disk space" not in text
    assert fake_self.widgets["busyBar"]["value"] == 42


def test_on_blender_progress_shows_english_phase_in_status_label():
    fake_self = _FakeSelfForBlenderProgress()
    i18n.set_language("en")
    fake_self._on_blender_progress(42, "Checking free disk space")
    text = fake_self.widgets["statusLabel"].text
    assert text is not None
    assert "Checking free disk space" in text


def test_on_blender_progress_shows_japanese_for_dynamic_download_phase():
    fake_self = _FakeSelfForBlenderProgress()
    i18n.set_language("ja")
    fake_self._on_blender_progress(15, "Downloading (12.3MB / 390.0MB)")
    text = fake_self.widgets["statusLabel"].text
    assert text is not None
    assert "ダウンロード中 (12.3MB / 390.0MB)" in text


def test_on_blender_progress_unknown_phase_still_shows_readable_text():
    # 負の対照1の配線版: 未知phaseがGUI経由でも無表示化しないこと
    fake_self = _FakeSelfForBlenderProgress()
    i18n.set_language("ja")
    fake_self._on_blender_progress(10, "Some Brand New Phase Never Seen Before")
    text = fake_self.widgets["statusLabel"].text
    assert text is not None
    assert "Some Brand New Phase Never Seen Before" in text
    assert "??" not in text


# ---------------------------------------------------------------------------
# dev#21非ASCII検査との整合(参考): この新規テストはensure_blender.ps1を
# 一切読み書きしない(合成したphase文字列のみを入力として使う)ので、
# tests\shipcheck\test_dist_ps1_ascii.py の非ASCII検査には影響しない。
# ---------------------------------------------------------------------------
