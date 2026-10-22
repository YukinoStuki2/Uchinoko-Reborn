# test_support_dialog_ended_dev1641.py -- dev#1641(2026-08-22オーナー裁定):
# 8/28のClaude運用終了に向けたサポート窓口の畳み込み。
#
# 要求(issue本文より):
#   「問い合わせボタン押下で終了文を表示し、送信フローへ進ませない。
#   ログ収集・送信処理は起動しない。」
#
# 実装: app_py/ui/main_window.py の _on_show_support_dialog() を、
# messagebox.showinfo(終了メッセージ)だけを出して即returnする形に変更
# (support_dialog.show_support_dialog以下の呼び出しへ到達しない、最小差分の
# 到達不能化)。support_dialog.py本体・inquiry.py本体は削除していない。
#
# 実tkウィンドウは開かない: test_preflight_warning_dialog_wiring.pyと同じ
# 「フェイクself」方式(mw.MainWindow.__new__(mw.MainWindow))を使う。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import dist_channel  # noqa: E402
from ui import main_window as mw  # noqa: E402
from ui import support_dialog  # noqa: E402
import inquiry  # noqa: E402


def _bare_window() -> mw.MainWindow:
    return mw.MainWindow.__new__(mw.MainWindow)


def test_support_button_shows_ended_message_only(monkeypatch):
    """正の対照: ボタンハンドラ呼び出しは終了メッセージのmessagebox.showinfo
    だけを出す(タイトル=BtnReport、本文=SupportEndedMessage)。"""
    fake = _bare_window()

    info_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: info_calls.append(a))

    mw.MainWindow._on_show_support_dialog(fake)

    assert info_calls == [(i18n.S("BtnReport"), i18n.S("SupportEndedMessage"))]
    # オーナー原文の核となる一節が実際に出ていること(訳文差し替えの検知)
    assert "資金ショート" in i18n.S("SupportEndedMessage")


def test_support_button_never_reaches_send_flow(monkeypatch):
    """中核受入ゲート: ログ収集・送信フロー(support_dialog.show_support_dialog
    以下)へ一切進まないこと。旧コードパスの入口(dist_channel.read_dist_channel、
    support_dialog.show_support_dialog、inquiry.send_report_payload)を全部
    「呼ばれたら即失敗」に差し替えて実測する(負の対照を兼ねる: もし本WPの
    到達不能化が効いていなければ、このいずれかが呼ばれて即座に検出できる)。"""
    fake = _bare_window()

    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: None)

    def _boom(*a, **kw):
        raise AssertionError("旧送信フローの入口が呼ばれた(到達不能化が壊れている)")

    monkeypatch.setattr(dist_channel, "read_dist_channel", _boom)
    monkeypatch.setattr(support_dialog, "show_support_dialog", _boom)
    monkeypatch.setattr(inquiry, "send_report_payload", _boom)

    # 例外が飛ばずに完走すること自体が検出結果(飛べばpytestが失敗として報告する)
    mw.MainWindow._on_show_support_dialog(fake)


def test_ended_message_i18n_present_for_all_languages():
    """5言語(ja/en/ko/zhTW/zhCN)すべてに終了文言が存在すること。"""
    import json

    with open(os.path.join(_APP_PY_DIR, "i18n_data.json"), encoding="utf-8") as f:
        data = json.load(f)
    entry = data["SupportEndedMessage"]
    for lang in ("ja", "en", "ko", "zhTW", "zhCN"):
        assert entry.get(lang), f"SupportEndedMessage[{lang}] が空"
