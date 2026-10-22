# test_verified_version_label.py -- dev#495受入試験。
#
# 背景: ストアの動作環境欄に「検証済みの最新バージョンはツール内の表示を
# ご覧ください」と書く前に裏取りしたところ、**通常時のGUIには検証済み
# Palworldバージョンの表示が実在しなかった**(見えるのは①版不一致時の警告
# ダイアログ ②診断ログのみ)。本WPはGUI常時表示(verifiedVersionLabel)を
# 追加し、本ファイルで以下を検証する:
#   1) compat_check.merge_known_good()の結果から期待どおりの表示文字列が
#      組み立てられること(MainWindow._verified_version_display_text、静的
#      メソッドなのでウィジェット不要で直接検証できる)
#   2) 負の対照: known_goodを空にすると表示が実際に「不明」相当へ変わること
#      (推測で「対応済み」等と書かない、CLAUDE.md「値を寄せて合わせない」の順守)
#   3) 配信versions.jsonでknown_versionsが増えた場合に表示文字列が追従する
#      こと(ハードコードでないことの確認)
#   4) 「実装した」と「効いている」は別: _build_widgets()が実際に
#      verifiedVersionLabelを生成し、_refresh_verified_version_label()経由で
#      そのラベルのtextへ反映される配線そのものを、フェイクself(実tk窓は
#      開かず hidden_root を使い回す、test_main_window_lang_combo.pyと同じ
#      流儀)で実証する。
from __future__ import annotations

import gc
import os
import sys
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import compat_check as cc  # noqa: E402
import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402

# main_window.pyの_APP_PY_DIR(app_py/ui/main_window.py基準)から見て、
# 実行時のapp_root(app_py/main.py._resolve_app_root()相当)はapp_pyの
# 親ディレクトリ(pipeline/py/known_good_palworld.jsonを含むリポジトリ
# ルート)になる。同梱データを使う正常系テストはこのパスを使う。
_REPO_ROOT_WITH_BUNDLED_JSON = os.path.dirname(mw._APP_PY_DIR)

BUNDLED_JSON = (
    '{"known_versions":['
    '{"build_id":"111","pak_size":1000,"label":"1.0.1"},'
    '{"build_id":"222","pak_size":2000,"label":"1.0.2"}'
    '],"known_vanilla_manifest_sha256":["aaaa"]}'
)


def _make_fake_self(root: tk.Tk, app_root: str) -> mw.MainWindow:
    """test_main_window_lang_combo.pyの_make_fake_selfと同じ最小フェイク。
    _refresh_verified_version_label()は追加でself._remote_known_good_json
    (_load_known_good_palworld()参照)を必要とするため、こちらは呼び出し側で
    都度設定する。"""
    self = mw.MainWindow.__new__(mw.MainWindow)
    self.root = root
    self.app_root = app_root
    self.widgets = {}
    self._tooltips = []
    return self


# ===========================================================================
# 1) 表示文字列の組み立て(ウィジェット不要、純粋関数として検証)
# ===========================================================================


def test_display_text_lists_merged_labels():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    text = mw.MainWindow._verified_version_display_text(known)
    expected = i18n.F("LabelVerifiedPalworldVersionFormat", "1.0.1, 1.0.2")
    assert text == expected
    assert "1.0.1" in text and "1.0.2" in text


def test_display_text_merges_remote_additively():
    """配信versions.jsonのpalworld_known_goodブロックがknown_versionsを
    追加した場合、表示文字列にも新規ラベルが反映される(dev#89のマージが
    追加的であることの延長)。"""
    remote = '{"known_versions":[{"build_id":"333","pak_size":3000,"label":"1.0.3"}]}'
    known = cc.merge_known_good(BUNDLED_JSON, remote)
    text = mw.MainWindow._verified_version_display_text(known)
    assert "1.0.3" in text
    assert "1.0.1" in text  # 既存分が失われていない(マージは追加、置換ではない)


def test_display_text_unknown_when_known_good_empty():
    """負の対照: 同梱jsonの読み込みに失敗し(パッケージング事故等)、配信データも
    未取得の場合、known.versionsは空になる。この時「対応済み」等の推測表示を
    せず、LabelVerifiedPalworldVersionUnknownの文言(「不明」相当)を返すこと。"""
    known = cc.merge_known_good("", None)
    assert known.versions == []  # 前提の確認
    text = mw.MainWindow._verified_version_display_text(known)
    assert text == i18n.S("LabelVerifiedPalworldVersionUnknown")
    # 「不明」相当であって、既知バージョンのラベルを騙って含めていないこと
    assert "1.0.1" not in text and "1.0.2" not in text


# ===========================================================================
# 2) 配線の実証: _build_widgets() -> _refresh_verified_version_label() が
#    実際にverifiedVersionLabelのtextへ反映することを、フェイクselfで確認する
#    (実tk窓は開かない。hidden_rootはconftest.pyのsessionスコープ共有フィクスチャ)。
# ===========================================================================


def test_verified_version_label_created_and_wired_with_bundled_data(hidden_root, tmp_path):
    """正常系: app_rootを同梱known_good_palworld.jsonが実在するリポジトリ
    ルートに向け、_build_widgets()→_refresh_verified_version_label()の
    実際の呼び出し経路(main_window.MainWindow.__init__が行うのと同じ2手順)
    を再現する。verifiedVersionLabelのtextに同梱データ由来のラベルが実際に
    入っていることまで確認する(「実装したがGUIに出ていない」を防ぐ)。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, _REPO_ROOT_WITH_BUNDLED_JSON)
        self._remote_known_good_json = None

        mw.MainWindow._build_widgets(self)
        assert "verifiedVersionLabel" in self.widgets, (
            "_build_widgets()がverifiedVersionLabelを生成していない"
            "(dev#495のウィジェット骨格追加が外れている)"
        )

        mw.MainWindow._refresh_verified_version_label(self)
        gc.collect()
        hidden_root.update_idletasks()

        label = self.widgets["verifiedVersionLabel"]
        text = label.cget("text")
        assert text != "", "初期テキストが空のまま(_refresh_verified_version_labelが未配線)"
        assert "1.0.1" in text, f"同梱known_good由来のラベルが表示に出ていない: {text!r}"

        # 期待値は「同梱known_good_palworld.jsonの現在の中身」から都度計算する
        # (ラベル名をこのテストにハードコードすると、pipeline/py/
        # known_good_palworld.json側でバージョンが追加・更新されるたびに
        # このテストだけ書き換えが必要になり、CLAUDE.mdの「配信/同梱データの
        # 更新に自動追従」という本WPの趣旨に反するため)。
        bundled_path = os.path.join(
            _REPO_ROOT_WITH_BUNDLED_JSON, "pipeline", "py", "known_good_palworld.json"
        )
        with open(bundled_path, "r", encoding="utf-8") as f:
            bundled_text = f.read()
        expected_known = cc.merge_known_good(bundled_text, None)
        assert expected_known.versions, "同梱known_good_palworld.jsonの読み込みに失敗(テスト前提が崩れている)"
        expected_text = i18n.F(
            "LabelVerifiedPalworldVersionFormat",
            cc.supported_labels_joined(expected_known),
        )
        assert text == expected_text
    finally:
        i18n.clear_registry()


def test_verified_version_label_shows_unknown_when_known_good_missing(hidden_root, tmp_path):
    """負の対照(配線レベル): app_rootに同梱jsonが存在しない(pipeline/py無し)
    tmp_pathを渡すと、_load_known_good_palworld()内のOSErrorフォールバックで
    known.versionsが空になり、ラベルのtextが実際に「不明」相当へ変わることを
    確認する。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, str(tmp_path))
        self._remote_known_good_json = None

        mw.MainWindow._build_widgets(self)
        mw.MainWindow._refresh_verified_version_label(self)
        gc.collect()
        hidden_root.update_idletasks()

        label = self.widgets["verifiedVersionLabel"]
        text = label.cget("text")
        assert text == i18n.S("LabelVerifiedPalworldVersionUnknown")
        assert "1.0.1" not in text
    finally:
        i18n.clear_registry()


def test_verified_version_label_follows_remote_known_good_update(hidden_root, tmp_path):
    """配線レベルでの追従確認: _check_for_update_once()のworkerが
    self._remote_known_good_jsonを更新した後にself.root.after(0,
    self._refresh_verified_version_label)を呼ぶのと同じ手順を再現し、配信側で
    known_versionsが増えた場合にverifiedVersionLabelのtextが実際に変わる
    ことを確認する(ハードコードではなくmerge結果に追従している証拠)。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, _REPO_ROOT_WITH_BUNDLED_JSON)
        self._remote_known_good_json = None

        mw.MainWindow._build_widgets(self)
        mw.MainWindow._refresh_verified_version_label(self)
        gc.collect()
        hidden_root.update_idletasks()
        text_before = self.widgets["verifiedVersionLabel"].cget("text")
        # dev#1440: このprobeラベルは「同梱データにまだ無い版」を表す合成値である
        # 必要があるだけで、実在のPalworld版表記である必要は無い。かつて"1.0.3"を
        # 使っていたが、build 24575825(実在の1.0.3.101283)が同梱データへ正当に
        # 追加されたことで文字列衝突しテストが偽陽性FAILした。実在し得ない
        # 合成文字列に変更し、将来の同梱データ追加と衝突しない形に固定する。
        assert "9.9.9-remote-probe" not in text_before

        # _check_for_update_once()のworkerがresult.remote_known_good_jsonを
        # キャッシュした後の再反映と同じ操作
        self._remote_known_good_json = (
            '{"known_versions":[{"build_id":"999","pak_size":9999,'
            '"label":"9.9.9-remote-probe"}]}'
        )
        mw.MainWindow._refresh_verified_version_label(self)
        gc.collect()
        hidden_root.update_idletasks()
        text_after = self.widgets["verifiedVersionLabel"].cget("text")

        assert text_after != text_before
        assert "9.9.9-remote-probe" in text_after
        assert "1.0.1" in text_after  # 既存の同梱データは失われていない
    finally:
        i18n.clear_registry()
