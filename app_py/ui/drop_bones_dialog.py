# drop_bones_dialog.py -- dev#1277(2026-08-09 オーナー裁定「ボーンでメッシュ
# 削除はボーン名を選択できるようにする」)ラボ機能「ボーンでメッシュ削除」。
#
# 旧実装(lab_window.py open_drop_bones_dialog、dev#1186でこだわり設定パネル
# から移設)はカンマ区切り手入力のEntry1個のみだった。本WPでmesh_delete_
# dialog.py/shapekey_select_dialog.pyと同型の独立モジュールへ切り出し、
# チェックリスト選択式へ変更する(DESIGN.md 2.3/3節、
# C:\P\Work\DiveToPalworld\work\rd_shapekey_preview\DESIGN.md)。
#
# **意味論(既存のmesh_delete/equipment系と向きが逆)**: チェックON =
# そのボーンに紐づくメッシュを削除する。既定 = 全チェックOFF(削除無し、
# ラボ憲章④=未実装状態と完全同一)。保存する値は「チェックONにしたボーン名の
# 集合」(=削除対象、カンマ区切り文字列)——job.json組み立て
# (pipeline_runner.write_job()のdrop_bones_text.split(",")、
# Blender側のarm.data.bones.get(name)完全一致)は一切変更しない。
#
# **バッキングストアは既存のmain_window.py側Entry(widgets["dropBonesBox"])**
# (mesh_delete_store.py/shapekey_filter_store.pyのような専用JSONストアは
# 新設しない——drop_bonesは元々アバター単位の永続化を持たずEntryの現在値が
# そのまま真実であり、この構造を変える理由が無い)。呼び出し元
# (lab_window.py)がEntryの読み書きをコールバックとしてContextへ渡す。
#
# ボーン名カタログの取得方法(VRM=glTF skins.joints直読み/prefab=Unity
# エクスポートのbones.jsonサイドカー)は bone_catalog.py へ分離済み
# (実測検証結果はそちらのモジュールdocstring参照)。
from __future__ import annotations

import os
import sys
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox
from typing import Callable, Dict, List, Optional, Set

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import bone_catalog  # noqa: E402
import i18n  # noqa: E402
import pipeline_runner  # noqa: E402  (resolve_unity_export_out_dir()の再利用のみ、越境しない)
from ui import window_pos  # noqa: E402  (2026-08-08: 親窓に重ねる位置決め)


# ---------------------------------------------------------------------------
# ボーン名カタログの解決(mesh_delete_dialog.query_mesh_catalog()と同型)。
# ---------------------------------------------------------------------------

def query_bone_catalog(app_root: str, work_root: str, avatar_path: str) -> dict:
    """入力アバターのボーン名一覧を取得する。戻り値は常に
    {"ok": bool, "source": str, "detail": str, "bones": [...]}
    の形(例外を投げない)。"""
    if not avatar_path or not os.path.exists(avatar_path):
        return {"ok": False, "source": "none",
                "detail": f"avatar not selected or not found: {avatar_path!r}",
                "bones": []}

    ext = os.path.splitext(avatar_path)[1].lower()

    if ext == ".vrm":
        result = bone_catalog.catalog_from_vrm(avatar_path)
        return {"ok": result["ok"], "source": "vrm",
                "detail": result["detail"], "bones": result["bones"]}

    if ext == ".prefab":
        out_dir = pipeline_runner.resolve_unity_export_out_dir(work_root, avatar_path)
        sidecar = os.path.join(out_dir, "bones.json")
        result = bone_catalog.catalog_from_sidecar(sidecar)
        return {"ok": result["ok"], "source": "prefab",
                "detail": result["detail"], "bones": result["bones"]}

    return {"ok": False, "source": "none",
            "detail": f"unsupported avatar extension for bone enumeration: {ext!r}",
            "bones": []}


# ---------------------------------------------------------------------------
# ダイアログ本体。カタログ取得成功時=チェックリスト(検索付き)、失敗時=
# カンマ区切り手入力のフォールバック(mesh_delete_dialog.pyと同じ構え)。
# ---------------------------------------------------------------------------

@dataclass
class DropBonesContext:
    app_root: str
    work_root: str
    avatar_path: str
    # バッキングストア(main_window.pyのdropBonesBox Entry)の読み書き。
    get_current_text: Callable[[], str] = field(default=lambda: "")
    set_current_text: Callable[[str], None] = field(default=lambda text: None)
    # 既存の鮮度判定再計算(main_window.py._on_drop_bones_changed相当)。
    on_changed: Callable[[], None] = field(default=lambda: None)
    append_log: Callable[[str], None] = field(default=lambda msg: None)
    # dev#1277: WP1(dev#1277-shapekey-preview-btn)と同じ配線パターン。
    # lab_window.py側がself._on_preview_onlyを渡す。Noneなら
    # ボタン押下時トリガーしない(単体試験でのフェイク経路を壊さない)。
    trigger_preview: Optional[Callable[[], None]] = field(default=None)


def show_drop_bones_dialog(parent: tk.Misc, ctx: DropBonesContext) -> tk.Toplevel:
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("LabFeatureDropBones"))
    dlg.geometry("380x460")
    dlg.transient(parent)
    i18n.register(dlg, "LabFeatureDropBones", lambda w, t: w.title(t))
    window_pos.apply_offset_position(dlg, parent)

    hint = tk.Label(dlg, text=i18n.S("LabDropBonesHint"),
                     wraplength=356, justify="left", anchor="w")
    hint.pack(fill="x", padx=8, pady=(8, 0))
    i18n.register(hint, "LabDropBonesHint")

    result = query_bone_catalog(ctx.app_root, ctx.work_root, ctx.avatar_path)
    ctx.append_log(f"[lab][drop_bones] catalog query: ok={result.get('ok')} "
                    f"source={result.get('source')} detail={result.get('detail')}")

    names: List[str] = list(result.get("bones") or [])
    current_names: Set[str] = {n.strip() for n in ctx.get_current_text().split(",")
                                if n.strip()}

    if not result.get("ok") or not names:
        # フォールバック: カンマ区切り手入力(旧実装と同じ入力欄、モジュール
        # docstring参照)。
        notice = tk.Label(dlg, text=i18n.S("LabDropBonesCatalogUnavailableNotice"),
                           fg="#a06000", wraplength=356, justify="left")
        notice.pack(fill="x", padx=8, pady=(8, 0))
        i18n.register(notice, "LabDropBonesCatalogUnavailableNotice")

        manual_label = tk.Label(dlg, text=i18n.S("LabelDropBones"), anchor="w")
        manual_label.pack(fill="x", padx=8, pady=(8, 0))
        i18n.register(manual_label, "LabelDropBones")

        manual_entry = tk.Entry(dlg)
        manual_entry.insert(0, ctx.get_current_text())
        manual_entry.pack(fill="x", padx=8, pady=(0, 4))

        hint2 = tk.Label(dlg, text=i18n.S("HintDropBonesEmpty"), anchor="nw", justify="left")
        hint2.pack(fill="x", padx=8, pady=(0, 8))
        i18n.register(hint2, "HintDropBonesEmpty")

        def _save_manual() -> None:
            raw = [n.strip() for n in manual_entry.get().split(",") if n.strip()]
            ctx.set_current_text(",".join(raw))
            ctx.on_changed()
            ctx.append_log(f"[lab][drop_bones] manual entry saved: {len(raw)} name(s)")

        btn_frame = tk.Frame(dlg)
        btn_frame.pack(fill="x", padx=8, pady=8, side="bottom")

        def on_ok_manual() -> None:
            _save_manual()
            dlg.destroy()

        ok_btn = tk.Button(btn_frame, text=i18n.S("BtnOk"), command=on_ok_manual)
        ok_btn.pack(side="right")
        i18n.register(ok_btn, "BtnOk")
        cancel_btn = tk.Button(btn_frame, text=i18n.S("BtnCancel"), command=dlg.destroy)
        cancel_btn.pack(side="right", padx=(0, 4))
        i18n.register(cancel_btn, "BtnCancel")

        # dev#1277: 保存はするがダイアログは閉じない(on_ok_manualとの違いは
        # dlg.destroy()の有無のみ、WP1 mesh_delete_dialog.pyと同じ形)。
        def on_preview_update_manual() -> None:
            _save_manual()
            if ctx.trigger_preview:
                ctx.trigger_preview()

        preview_btn = tk.Button(btn_frame, text=i18n.S("BtnPreviewUpdate"),
                                 command=on_preview_update_manual)
        preview_btn.pack(side="left")
        i18n.register(preview_btn, "BtnPreviewUpdate")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        return dlg

    # --- チェックリストモード(カタログ取得成功) ---
    search_frame = tk.Frame(dlg)
    search_frame.pack(fill="x", padx=8, pady=(4, 0))
    search_label = tk.Label(search_frame, text=i18n.S("LabShapeKeysSearchLabel"))
    search_label.pack(side="left")
    i18n.register(search_label, "LabShapeKeysSearchLabel")
    search_var = tk.StringVar()
    search_entry = tk.Entry(search_frame, textvariable=search_var)
    search_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))

    list_frame = tk.Frame(dlg)
    list_frame.pack(fill="both", expand=True, padx=8, pady=(8, 0))
    canvas = tk.Canvas(list_frame, highlightthickness=0)
    scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas)
    inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def _on_mousewheel(event: "tk.Event") -> str:
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    canvas.bind("<MouseWheel>", _on_mousewheel)
    inner.bind("<MouseWheel>", _on_mousewheel)

    # チェックON = 削除対象(既存Entry値との交差のみ既定ON、カタログに
    # 無い残留名は静かに捨てる——ラボ憲章②「雑な実装でよい」の範囲)。
    check_vars: Dict[str, tk.BooleanVar] = {}
    check_buttons: Dict[str, tk.Checkbutton] = {}
    for name in sorted(names, key=lambda n: n.lower()):
        var = tk.BooleanVar(value=(name in current_names))
        check_vars[name] = var
        cb = tk.Checkbutton(inner, text=name, variable=var, anchor="w")
        cb.bind("<MouseWheel>", _on_mousewheel)
        check_buttons[name] = cb

    def _apply_filter(*_args) -> None:
        q = search_var.get().strip().lower()
        for name, cb in check_buttons.items():
            if not q or q in name.lower():
                cb.pack(anchor="w", fill="x")
            else:
                cb.pack_forget()

    search_var.trace_add("write", _apply_filter)
    _apply_filter()

    btn_frame1 = tk.Frame(dlg)
    btn_frame1.pack(fill="x", padx=8, pady=(8, 0))
    select_all_btn = tk.Button(
        btn_frame1, text=i18n.S("LabEquipmentFilterSelectAll"),
        command=lambda: [v.set(True) for v in check_vars.values()])
    select_all_btn.pack(side="left")
    i18n.register(select_all_btn, "LabEquipmentFilterSelectAll")
    clear_all_btn = tk.Button(
        btn_frame1, text=i18n.S("LabEquipmentFilterClearAll"),
        command=lambda: [v.set(False) for v in check_vars.values()])
    clear_all_btn.pack(side="left", padx=(4, 0))
    i18n.register(clear_all_btn, "LabEquipmentFilterClearAll")

    btn_frame2 = tk.Frame(dlg)
    btn_frame2.pack(fill="x", padx=8, pady=8)

    def _collect_selected() -> List[str]:
        return sorted(name for name, var in check_vars.items() if var.get())

    def _save_selection(to_drop: List[str]) -> None:
        ctx.set_current_text(",".join(to_drop))
        ctx.on_changed()
        ctx.append_log(
            f"[lab][drop_bones] selection saved: "
            f"{len(to_drop)} of {len(names)} bone(s) marked for deletion")

    def on_ok() -> None:
        to_drop = _collect_selected()
        if names and len(to_drop) == len(names):
            # 全ボーンを削除対象にするのは骨格の全損に等しい(mesh_delete_
            # dialog.pyの「全OFF警告」と対称の安全弁)。誤操作(全選択ボタンの
            # 押し過ぎ等)を弾く。
            messagebox.showwarning(
                i18n.S("LabFeatureDropBones"),
                i18n.S("LabDropBonesAllSelectedWarning"))
            return
        _save_selection(to_drop)
        dlg.destroy()

    ok_btn = tk.Button(btn_frame2, text=i18n.S("BtnOk"), command=on_ok)
    ok_btn.pack(side="right")
    i18n.register(ok_btn, "BtnOk")
    cancel_btn = tk.Button(btn_frame2, text=i18n.S("BtnCancel"), command=dlg.destroy)
    cancel_btn.pack(side="right", padx=(0, 4))
    i18n.register(cancel_btn, "BtnCancel")

    # dev#1277: 保存はするがダイアログは閉じない(on_okとの違いは全選択警告
    # 判定+保存までを共有しつつdlg.destroy()を呼ばない点のみ、WP1
    # mesh_delete_dialog.pyと同じ形)。押した瞬間にctx.trigger_preview()
    # (=main_window._on_preview_only、既存の二重起動ガード・vrm未指定ガード
    # 込み)を呼ぶ(DESIGN.md 2.2/2.3節)。
    def on_preview() -> None:
        to_drop = _collect_selected()
        if names and len(to_drop) == len(names):
            messagebox.showwarning(
                i18n.S("LabFeatureDropBones"),
                i18n.S("LabDropBonesAllSelectedWarning"))
            return
        _save_selection(to_drop)
        if ctx.trigger_preview:
            ctx.trigger_preview()

    preview_btn = tk.Button(btn_frame2, text=i18n.S("BtnPreviewUpdate"),
                             command=on_preview)
    preview_btn.pack(side="left")
    i18n.register(preview_btn, "BtnPreviewUpdate")

    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    return dlg
