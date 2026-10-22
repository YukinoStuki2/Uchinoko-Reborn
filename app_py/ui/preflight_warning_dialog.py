# preflight_warning_dialog.py -- dev#1230(2026-08-08オーナー裁定):
# ユーザーサイドpreflightの非ブロック化。preflight FAILでもpakは完成させ、
# このダイアログで「MODを解除」「問合せ」の2導線をユーザーへ示す。
#
# ダイアログ文面の正本(オーナー原文完コピ、issue #1230本文。一字一句
# 変えない): i18n_data.json の MsgPreflightWarningBody キー(5言語、
# ja=原文正本・他言語はAI判定の同義訳)。
#
# ボタン文言は新規i18nキーを増やさず、既存キーをそのまま再利用する
# (CLAUDE.md「設定項目/文言は少ないほうがいい」):
#   「MODを解除」= LabelRemove(既存removeButtonと同じ文言・同じ処理を呼ぶ)
#   「問合せ」    = BtnReport(既存reportButtonと同じ文言・同じ処理を呼ぶ)
# どちらのボタンも main_window.py の既存ハンドラ(_on_remove_applied /
# _on_show_support_dialog)を、二重実装せずそのままコールバックとして
# 直接呼ぶ(PreflightWarningContext経由)。
#
# 書き込み許可: このファイル(新規)。main_window.py側の結線・i18n_data.jsonの
# 新規キー追加は本WP(dev#1230)の指示書が別途認めている。
from __future__ import annotations

import os
import sys
import tkinter as tk
from dataclasses import dataclass
from typing import Callable

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import window_pos  # noqa: E402


@dataclass
class PreflightWarningContext:
    """ダイアログの2ボタンが実際に呼ぶ処理。main_window.py側は
    self._on_remove_applied / self._on_show_support_dialog(いずれも既存
    メソッド、新規実装しない)をそのまま束縛して渡す想定。"""

    on_remove_mod: Callable[[], None]
    on_open_inquiry: Callable[[], None]


def show_preflight_warning_dialog(
    parent: tk.Misc, ctx: PreflightWarningContext
) -> tk.Toplevel:
    """preflight FAIL時、pak完成と同時に出す警告ダイアログ本体。

    2ボタン(「MODを解除」/「問合せ」)はどちらも押した瞬間にダイアログを
    閉じてから、渡されたコールバックを呼ぶ(ダイアログを残したまま処理を
    始めない——既存の_offer_report_after_failure()と同じ「先に閉じてから
    遷移する」流儀)。閉じるだけ(×ボタン)も許可する
    (gender_select_dialog.py等と同じ、未保存で閉じるのと同型の「何もせず
    閉じる」選択肢)。"""
    # dev#1367(2026-08-15、実報告B5357788): 旧実装は resizable(False, False)
    # + place(height=190)の固定サイズで、環境(DPI・翻訳文の長さ)次第で本文が
    # 見切れていた。pack()ベースへ変更し、①ウィンドウをリサイズ可能にする
    # (resizable()を呼ばない=既定True)②本文Labelの高さを固定せず、
    # 内容量に応じて自動でジオメトリが決まる(dlg.geometry("WxH")を呼ばない
    # =Tkが子ウィジェットの要求サイズから自動計算する)、の二重の安全策で
    # 見切れを構造的に防ぐ。
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("TitlePreflightWarning"))
    dlg.transient(parent)
    i18n.register(dlg, "TitlePreflightWarning", lambda w, t: w.title(t))

    body = tk.Label(
        dlg, text=i18n.S("MsgPreflightWarningBody"), anchor="nw",
        justify="left", wraplength=400,
    )
    body.pack(fill="both", expand=True, padx=12, pady=12)
    i18n.register(body, "MsgPreflightWarningBody")

    def _on_remove() -> None:
        dlg.destroy()
        ctx.on_remove_mod()

    def _on_inquiry() -> None:
        dlg.destroy()
        ctx.on_open_inquiry()

    btn_row = tk.Frame(dlg)
    btn_row.pack(fill="x", padx=12, pady=(0, 12))

    remove_btn = tk.Button(btn_row, text=i18n.S("LabelRemove"), command=_on_remove, width=14)
    remove_btn.pack(side="left")
    i18n.register(remove_btn, "LabelRemove")

    inquiry_btn = tk.Button(btn_row, text=i18n.S("BtnReport"), command=_on_inquiry, width=14)
    inquiry_btn.pack(side="left", padx=(8, 0))
    i18n.register(inquiry_btn, "BtnReport")

    dlg.minsize(360, 160)
    window_pos.apply_offset_position(dlg, parent)
    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    return dlg
