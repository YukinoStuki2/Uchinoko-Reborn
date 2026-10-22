# output_folder_dialog.py -- dev#1368(2026-08-15オーナー裁定)ラボ機能
# 「出力先フォルダを開く」のダイアログ。
#
# オーナー裁定: 「メイン窓にボタンは増やさない」「出力先フォルダを開くは
# ラボ機能として実装」「アンインストール手順はREADMEに書く」の3点。本
# モジュールは1点目・2点目(ダイアログ本体)を担う。
#
# equipment_select_dialog.py/dt_flag_head_hide_dialog.pyと同じ「lab_window.py
# には薄いアダプタだけを置き、実UIはここに閉じ込める」構成(.claude\skills\
# lab-dev\SKILL.mdの約束事どおり)。
#
# 本機能は他のラボ機能と異なりjob設定に一切触れない「アクションのみ」の
# ラボ機能(フォルダを開くだけで、保存する状態が無い)。ラボ憲章④(既定値=
# 未実装状態と完全一致)は、設定自体が存在しないことで自明に満たす——
# state_summary()は常にNone(=無効表示)、reset()はno-op。
#
# パス解決: 変換結果(pak等)の実際の保存先は、main_window.pyが
# self.work_root として保持する値そのもの(_resolve_work_root()の戻り値、
# pak_manager.list_built_paks(work_root)が走査する起点と同一——同関数は
# <work_root>\<jobDir>\build\*_PlayerSwap_P.pak を列挙する)。本モジュールは
# その値を素直にラベル表示するだけで、自前でパスを組み立て直さない
# (呼び出し元=lab_window.py側のアダプタがself.work_rootをそのまま
# OutputFolderContext.work_rootへ渡す)。
from __future__ import annotations

import os
import sys
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox
from typing import Callable, Optional

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import window_pos  # noqa: E402

LAB_FEATURE_ID = "output_folder"


def state_summary(app_root: str) -> Optional[str]:  # noqa: ARG001 -- 規約上の引数
    """本機能は設定を保存しないアクションのみのラボ機能のため、常にNone
    (=ラボ窓の状態列は「無効」表示のまま)を返す。他のラボ機能と同じ
    `state_summary(app_root) -> Optional[str]` 形にはそろえておく
    (lab_window.py側のLabFeature記述子と型を合わせるため)。"""
    return None


def reset(app_root: str) -> None:  # noqa: ARG001 -- 規約上の引数
    """設定を持たないためno-op(「全てのラボ機能を無効化」ボタンから
    呼ばれても何もしない)。"""
    return None


def _default_open_folder(path: str) -> None:
    os.startfile(path)  # noqa: S606 -- Windows専用、フォルダを開くだけ


@dataclass
class OutputFolderContext:
    work_root: str
    open_folder: Callable[[str], None] = field(default=_default_open_folder)
    append_log: Callable[[str], None] = field(default=lambda msg: None)


def show_output_folder_dialog(parent: tk.Misc, ctx: OutputFolderContext) -> tk.Toplevel:
    """dev#1368の「出力先フォルダを開く」ダイアログ本体。

    equipment_select_dialog.show_equipment_select_dialog()等と同じ
    `(parent, ctx) -> tk.Toplevel` の呼び出し規約(on_changeは呼び出し側が
    `<Destroy>`イベントへbindする、lab_window.py._open_equipment_filter_dialog
    と同じ結線パターン)。保存する設定が無いため、OK/キャンセルの区別も
    無く「閉じる」ボタン1個のみ。"""
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("LabOutputFolderDialogTitle"))
    dlg.resizable(False, False)
    dlg.geometry("480x220")
    dlg.transient(parent)
    i18n.register(dlg, "LabOutputFolderDialogTitle", lambda w, t: w.title(t))
    window_pos.apply_offset_position(dlg, parent)

    desc = tk.Label(
        dlg, text=i18n.S("LabOutputFolderHint"),
        wraplength=456, justify="left", anchor="nw",
    )
    desc.place(x=12, y=12, width=456, height=100)
    i18n.register(desc, "LabOutputFolderHint")

    path_label = tk.Label(
        dlg, text=ctx.work_root, wraplength=456, justify="left", anchor="nw",
        relief="groove",
    )
    path_label.place(x=12, y=116, width=456, height=44)

    folder_exists = os.path.isdir(ctx.work_root)

    if not folder_exists:
        notice = tk.Label(
            dlg, text=i18n.S("LabOutputFolderMissingNotice"),
            wraplength=456, justify="left", anchor="nw", fg="#666666",
        )
        notice.place(x=12, y=164, width=456, height=32)
        i18n.register(notice, "LabOutputFolderMissingNotice")

    def _open_and_report() -> None:
        try:
            ctx.open_folder(ctx.work_root)
            ctx.append_log(f"[lab][output_folder] opened: {ctx.work_root}")
        except OSError as ex:
            # dev#1514: 従来はstr(ex)(OSError生文字列)をダイアログへ直接
            # 埋め込んでいた。ダイアログにはフォルダパスまで(実行可能な
            # 手がかり)にとどめ、生例外はappend_log(上)だけに残す
            # (診断能力を落とさない)。
            ctx.append_log(f"[lab][output_folder] failed to open: {ctx.work_root} ({ex})")
            messagebox.showerror(
                i18n.S("LabOutputFolderDialogTitle"),
                i18n.F("MsgLabOutputFolderOpenFailedFormat", ctx.work_root),
            )

    open_btn = tk.Button(
        dlg, text=i18n.S("BtnLabOutputFolderOpen"), command=_open_and_report,
        state=(tk.NORMAL if folder_exists else tk.DISABLED),
    )
    open_btn.place(x=12, y=180, width=220, height=28)
    i18n.register(open_btn, "BtnLabOutputFolderOpen")

    close_btn = tk.Button(dlg, text=i18n.S("BtnClose"), command=dlg.destroy)
    close_btn.place(x=368, y=180, width=100, height=28)
    i18n.register(close_btn, "BtnClose")

    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    return dlg


# ---------------------------------------------------------------------------
# dev#1186 ラボ機能レジストリ記述子(lab_window.py側が結線する)。
# ---------------------------------------------------------------------------

LAB_REGISTRY_DESCRIPTOR = {
    "id": LAB_FEATURE_ID,
    "name_key": "LabFeatureOutputFolder",
    "state_summary": state_summary,
    "open_dialog": show_output_folder_dialog,
    "reset": reset,
}
