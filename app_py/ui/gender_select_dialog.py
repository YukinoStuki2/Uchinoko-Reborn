# gender_select_dialog.py -- dev#336(2026-08-08 性別限定)ラボ機能。
#
# work\rd_1198_wpb\PROPOSAL.md §7(装備限定の縮退形としての再設計)の
# 結線: 変換時に注入対象を片方の性別(Male/Female)だけへ絞り込む、
# 3択ラジオボタン(両方=既定/男のみ/女のみ)のダイアログ+ラボUI基盤
# (dev#1186)向けの機能レジストリ記述子。
#
# equipment_select_dialog.py(装備限定)と異なりPalworld側のカタログ
# 解決(pak参照・subprocess起動)が不要——性別は固定2値なので、常に
# 静的な選択肢を出すだけでよい(PROPOSAL §7.3「UIはdev#336コメントの
# 裁定通り、独立したラボ機能『性別限定』(無効/女のみ/男のみ)」)。
#
# 選択状態の永続化はtkinter非依存のgender_filter_store.pyへ委譲
# (equipment_filter_store.py/headequip_filter_store.pyと同じ理由、
# pipeline_runner.pyがヘッドレス経路からimportするため)。
from __future__ import annotations

import os
import sys
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable, Optional

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import window_pos  # noqa: E402  (2026-08-08: 親窓に重ねる位置決め)

import gender_filter_store as _store  # noqa: E402

LAB_FEATURE_ID = _store.LAB_FEATURE_ID
_STATE_FILENAME = _store._STATE_FILENAME
_state_path = _store._state_path
load_selected_gender = _store.load_selected_gender
save_selected_gender = _store.save_selected_gender
reset = _store.reset
is_active = _store.is_active
state_summary = _store.state_summary

# UI上のラジオ値("Both"は内部専用のUI表現、保存形式はNone)。
_UI_BOTH = "Both"
_OPTIONS = (
    (_UI_BOTH, "LabGenderFilterOptionBoth"),
    ("Male", "LabGenderFilterOptionMaleOnly"),
    ("Female", "LabGenderFilterOptionFemaleOnly"),
)


@dataclass
class GenderSelectContext:
    app_root: str
    append_log: Callable[[str], None] = field(default=lambda msg: None)


def show_gender_select_dialog(parent: tk.Misc, ctx: GenderSelectContext) -> tk.Toplevel:
    """dev#336の性別限定ダイアログ本体。OKで選択を保存、Cancel/×は破棄のみ
    (未保存で閉じる、equipment_select_dialog.pyと同じ流儀)。"""
    # dev#1367(2026-08-15、実報告B5357788同型パターン是正): 旧実装は
    # resizable(False, False) + place(height=56)固定で、長い翻訳文だと
    # hintが見切れる恐れがあった。pack()ベースへ変更し、リサイズ可能
    # (resizable()を呼ばない=既定True)+ラベル高さは内容量に応じて自動
    # (dlg.geometry("WxH")を呼ばない=Tkが要求サイズから自動計算する)。
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("LabGenderFilterDialogTitle"))
    dlg.transient(parent)
    i18n.register(dlg, "LabGenderFilterDialogTitle", lambda w, t: w.title(t))

    hint = tk.Label(dlg, text=i18n.S("LabGenderFilterHint"), anchor="nw",
                     justify="left", wraplength=336)
    hint.pack(fill="x", padx=12, pady=(12, 8))
    i18n.register(hint, "LabGenderFilterHint")

    current = load_selected_gender(ctx.app_root)
    ui_value = current if current in ("Male", "Female") else _UI_BOTH
    var = tk.StringVar(value=ui_value)

    radio_widgets = []
    for value, key in _OPTIONS:
        rb = tk.Radiobutton(dlg, text=i18n.S(key), variable=var, value=value, anchor="w")
        rb.pack(fill="x", padx=12, pady=(0, 4))
        i18n.register(rb, key)
        radio_widgets.append(rb)

    def _on_ok() -> None:
        chosen = var.get()
        gender = None if chosen == _UI_BOTH else chosen
        save_selected_gender(ctx.app_root, gender)
        ctx.append_log(f"[lab][gender_filter] selection saved: {gender or 'Both (default)'}")
        dlg.destroy()

    btn_row = tk.Frame(dlg)
    btn_row.pack(fill="x", padx=12, pady=(8, 12))
    ok_btn = tk.Button(btn_row, text=i18n.S("BtnOk"), command=_on_ok)
    ok_btn.pack(side="right")
    i18n.register(ok_btn, "BtnOk")

    dlg.minsize(300, 180)
    # 2026-08-08: オーナー指摘「サブウィンドウが左上に出るのが使いにくい」
    # 対応。親窓+固定オフセットの位置へ明示的に出す。
    window_pos.apply_offset_position(dlg, parent)
    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    return dlg


# ---------------------------------------------------------------------------
# dev#1186 ラボ機能レジストリ記述子。
# id / i18n名称キー / 状態サマリ関数 / ダイアログを開く関数 / リセット関数。
# ---------------------------------------------------------------------------

LAB_REGISTRY_DESCRIPTOR = {
    "id": LAB_FEATURE_ID,
    "name_key": "LabFeatureGenderFilter",
    "state_summary": state_summary,
    "open_dialog": show_gender_select_dialog,
    "reset": reset,
}
