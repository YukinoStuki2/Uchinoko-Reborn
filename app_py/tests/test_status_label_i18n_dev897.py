# test_status_label_i18n_dev897.py -- dev#897受入試験。
#
# 症状: pak適用後のステータス「適用しました: X」が、Languageを切り替えても
# 日本語のまま残る(オーナー報告、2026-08-02)。
#
# 原因(本ファイルが立証する構造): main_window.pyのstatusLabelは
# i18n.register()の登録簿を一切経由しない直書き(self.widgets["statusLabel"]
# .config(text=i18n.F(...))を呼び出し箇所ごとに直接叩く設計)だった。
# i18n.apply_language()は登録簿だけを再適用するため、statusLabelへ最後に
# 設定した文言は「言語切替時に再計算する仕組みが存在しない」まま取り残される
# (appliedLabel側は同種の問題をdev#596で_on_update_applied_status()の
# 明示呼び出しにより解消済みだったが、statusLabelは未対応だった)。
#
# 修正: MainWindow._set_status(render)ヘルパーを導入し、config(text=...)する
# 全箇所をこれ経由に統一した(main_window.py参照)。renderは「現在言語で文言を
# 組み立て直す関数」そのもの(完成済み文字列ではない)。_on_language_selected()
# が切替のたびself._last_status_render()を呼び直す。updateLabel(dev#173で
# 「本WPのスコープ外」としていた同類インスタンス)も_pending_update_versionを
# 使って同時に直した。
#
# tkの実ウィンドウは一切開かない(既存test_busy_bar_progress.py等と同じ、
# フェイクself+MainWindowの未束縛メソッド直接束縛の流儀)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402


class _FakeLabel:
    def __init__(self) -> None:
        self.text: str | None = None

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]


class _FakeCombo:
    def __init__(self, display_name: str) -> None:
        self._display_name = display_name

    def get(self) -> str:
        return self._display_name


class _FakePakList:
    def heading(self, _col_id, **_kwargs) -> None:
        pass


class _FakeSelfForLanguageSwitch:
    """_on_language_selectedを束縛せずに呼ぶための最小self。appliedLabel側
    (_on_update_applied_status)はdev#596で別途検証済みのため、ここではno-opで
    差し替えて統計対象から外す(本ファイルの関心事はstatusLabel/updateLabelの
    2点のみ)。"""

    def __init__(self, app_root: str, lang_display_name: str) -> None:
        self.app_root = app_root
        self._lang_combo = _FakeCombo(lang_display_name)
        self._pak_list_columns: dict = {}
        self._kodawari_open = False
        self._last_status_render = None
        self._pending_update_version: str | None = None
        self.widgets = {
            "pakList": _FakePakList(),
            "kodawariToggle": _FakeLabel(),
            "statusLabel": _FakeLabel(),
            "updateLabel": _FakeLabel(),
        }

    def _update_window_title(self) -> None:
        pass

    def _on_update_applied_status(self) -> None:
        # dev#596領分(appliedLabel)は本ファイルの対象外。
        pass

    def _refresh_verified_version_label(self) -> None:
        # dev#1156領分(verifiedVersionLabel)は本ファイルの対象外。
        pass

    _set_status = mw.MainWindow._set_status
    _on_language_selected = mw.MainWindow._on_language_selected


def setup_function(_fn) -> None:
    i18n.set_language("ja")


def teardown_function(_fn) -> None:
    i18n.set_language("ja")


# ---------------------------------------------------------------------------
# (1) 本丸: _set_status()経由で設定したstatusLabelが言語切替に追随すること
# ---------------------------------------------------------------------------


def test_status_label_follows_language_switch_after_set_status(tmp_path):
    fake = _FakeSelfForLanguageSwitch(str(tmp_path), "English")
    i18n.set_language("ja")
    fake._set_status(lambda: i18n.F("StatusAppliedFormat", "AliciaSolidvrm051"))
    assert fake.widgets["statusLabel"].text == "適用しました: AliciaSolidvrm051"

    fake._on_language_selected()

    assert fake.widgets["statusLabel"].text == "Applied: AliciaSolidvrm051", (
        "dev#897再発: Languageを英語へ切り替えてもstatusLabelが日本語のまま残っている"
    )


def test_status_label_follows_language_switch_across_all_languages(tmp_path):
    """5言語すべてで追随することを確認する(1言語だけの偶然一致を排除)。"""
    display_by_lang = dict(zip(i18n.LANGS, i18n.LANG_DISPLAY_NAMES))
    for lang in i18n.LANGS:
        fake = _FakeSelfForLanguageSwitch(str(tmp_path / lang), display_by_lang[lang])
        i18n.set_language("ja")
        fake._set_status(lambda: i18n.F("StatusAppliedFormat", "Foo"))
        fake._on_language_selected()
        # 切替後は「新しい言語での文言」と一致するはず。i18n.S/Fは切替後の
        # current_langを見るので、switch後にi18n.F(...)を呼んで期待値を作る。
        i18n.set_language(lang)
        expected = i18n.F("StatusAppliedFormat", "Foo")
        assert fake.widgets["statusLabel"].text == expected, (
            f"lang={lang}: statusLabelが期待した訳文になっていない"
        )


# ---------------------------------------------------------------------------
# (2) 負の対照: _set_status()を経由せず直書きした場合は追随しない
#     (=本修正が無ければ再現していたはずの症状そのものを再現できる検査)
# ---------------------------------------------------------------------------


def test_negative_control_direct_config_write_does_not_follow_language_switch(tmp_path):
    """直接 widgets["statusLabel"].config(text=...) した場合(_set_status()を
    経由しない、dev#897修正前の実装そのもの)は、言語切替後も古い言語のまま
    残ることを示す負の対照。これが起きないことをtest_status_label_follows_...
    が保証している——つまりこの検査自体が「症状を検出できる」ことの証明。"""
    fake = _FakeSelfForLanguageSwitch(str(tmp_path), "English")
    i18n.set_language("ja")
    # 修正前の実装を模す: _set_status()を経由しない直書き。
    fake.widgets["statusLabel"].config(text=i18n.F("StatusAppliedFormat", "AliciaSolidvrm051"))
    assert fake._last_status_render is None  # 直書きなのでレンダラは記憶されない

    fake._on_language_selected()

    assert fake.widgets["statusLabel"].text == "適用しました: AliciaSolidvrm051", (
        "直書き経路なのに言語切替後の文言が変わっている(このテストの前提が崩れている)"
    )


# ---------------------------------------------------------------------------
# (3) updateLabel(dev#173で「スコープ外」としていた同類インスタンス)
# ---------------------------------------------------------------------------


def test_update_label_follows_language_switch(tmp_path):
    fake = _FakeSelfForLanguageSwitch(str(tmp_path), "English")
    i18n.set_language("ja")
    fake._pending_update_version = "v2.4.0"
    fake.widgets["updateLabel"].config(text=i18n.F("UpdateNoticeFormat", "v2.4.0"))
    assert fake.widgets["updateLabel"].text == i18n.F("UpdateNoticeFormat", "v2.4.0")

    fake._on_language_selected()

    i18n.set_language("en")
    assert fake.widgets["updateLabel"].text == i18n.F("UpdateNoticeFormat", "v2.4.0"), (
        "dev#897同類: updateLabelがLanguageを英語へ切り替えても追随していない"
    )


def test_update_label_untouched_when_no_pending_update(tmp_path):
    """負の対照: 更新通知が表示されていない(_pending_update_version=None)間は、
    updateLabelへ触れないこと(存在しない通知を作り出さない)。"""
    fake = _FakeSelfForLanguageSwitch(str(tmp_path), "English")
    i18n.set_language("ja")
    assert fake.widgets["updateLabel"].text is None
    fake._on_language_selected()
    assert fake.widgets["updateLabel"].text is None
