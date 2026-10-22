# dt_flag_head_hide_dialog.py -- dev#1258(WP-E、2026-08-09オーナー裁定)
# ラボ機能「差替え中装備のみ頭OFF」のダイアログ。
#
# equipment_select_dialog.py/headequip_select_dialog.pyと同じ「lab_window.py
# には薄いアダプタだけを置き、実UIはここに閉じ込める」構成(WP指示書の
# 書き込み許可からlab_window.py/main_window.py本体を外す規約に従う——
# 結線(LabFeature記述子の追加)はマージ時に指揮者が1行だけ足す)。
#
# 単一の真偽値トグルのみのため、equipment_select_dialog/headequip_select_dialog
# のような検索付き複数選択チェックリストは不要。drop_bonesダイアログ
# (lab_window.py内)と同じ最小構成(機能説明ラベル+1個の操作UI+OKボタン)
# だが、操作UIはEntryではなくCheckbutton 1個。
from __future__ import annotations

import os
import sys
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import window_pos  # noqa: E402

# 選択状態の保存・読み出しロジックはtkinter非依存のdt_flag_head_hide_store.py
# にある(equipment_filter_store.py/headequip_filter_store.pyと同じ理由)。
import dt_flag_head_hide_store as _store  # noqa: E402

LAB_FEATURE_ID = _store.LAB_FEATURE_ID
load_enabled = _store.load_enabled
save_enabled = _store.save_enabled
reset = _store.reset
is_active = _store.is_active
state_summary = _store.state_summary


@dataclass
class DtFlagHeadHideContext:
    app_root: str
    append_log: Callable[[str], None] = field(default=lambda msg: None)


def show_dt_flag_head_hide_dialog(parent: tk.Misc, ctx: DtFlagHeadHideContext) -> tk.Toplevel:
    """dev#1258(WP-E)の「差替え中装備のみ頭OFF」設定ダイアログ本体。

    equipment_select_dialog.show_equipment_select_dialog()/
    headequip_select_dialog.show_headequip_select_dialog()と同じ
    `(parent, ctx) -> tk.Toplevel`の呼び出し規約(on_changeは呼び出し側が
    `<Destroy>`イベントへbindする、lab_window.py._open_equipment_filter_dialog
    と同じ結線パターン)。OK押下時のみバッキングストアへ保存する
    (drop_bonesダイアログと同じ「OKで適用、×/キャンセルは破棄」の流儀)。
    GUI内に機能説明を必ず置く(lab-devスキル「ドキュメントが不要である
    ように」)。"""
    # dev#1367(2026-08-15、実報告B5357788同型パターン是正): 旧実装は
    # resizable(False, False) + place(height=130)固定で、長い翻訳文(実測:
    # 英語版が5言語中最長)だとdescが見切れる恐れがあった。pack()ベースへ
    # 変更し、リサイズ可能(resizable()を呼ばない=既定True)+desc高さは
    # 内容量に応じて自動(dlg.geometry("WxH")を呼ばない)。desc/check/ok_btnは
    # 既存test_dt_flag_head_hide_dialog_dev1258.pyがdlg.winfo_children()を
    # 非再帰で検索するため、引き続きdlgの直接の子として置く(中間Frameで
    # 包まない)。
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("LabDtFlagHeadHideDialogTitle"))
    dlg.transient(parent)
    i18n.register(dlg, "LabDtFlagHeadHideDialogTitle", lambda w, t: w.title(t))

    desc = tk.Label(dlg, text=i18n.S("LabDtFlagHeadHideHint"),
                     wraplength=416, justify="left", anchor="nw")
    desc.pack(fill="x", padx=12, pady=(12, 8))
    i18n.register(desc, "LabDtFlagHeadHideHint")

    var = tk.BooleanVar(value=load_enabled(ctx.app_root))
    check = tk.Checkbutton(dlg, text=i18n.S("LabDtFlagHeadHideCheckboxLabel"),
                            variable=var, anchor="w")
    check.pack(fill="x", padx=12, pady=(0, 8))
    i18n.register(check, "LabDtFlagHeadHideCheckboxLabel")

    def _apply_and_close() -> None:
        enabled = bool(var.get())
        save_enabled(ctx.app_root, enabled)
        ctx.append_log(f"[lab][dt_flag_head_hide] setting saved: enabled={enabled}")
        dlg.destroy()

    ok_btn = tk.Button(dlg, text=i18n.S("BtnOk"), command=_apply_and_close, width=12)
    ok_btn.pack(anchor="e", padx=12, pady=(0, 12))
    i18n.register(ok_btn, "BtnOk")

    dlg.minsize(360, 180)
    window_pos.apply_offset_position(dlg, parent)
    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    return dlg


# ---------------------------------------------------------------------------
# dev#1186 ラボ機能レジストリ記述子(lab_window.py側が結線する)。
# ---------------------------------------------------------------------------

LAB_REGISTRY_DESCRIPTOR = {
    "id": LAB_FEATURE_ID,
    "name_key": "LabFeatureDtFlagHeadHide",
    "state_summary": state_summary,
    "open_dialog": show_dt_flag_head_hide_dialog,
    "reset": reset,
}
