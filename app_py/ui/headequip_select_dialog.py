# headequip_select_dialog.py -- dev#277第1弾④(2026-08-08 オーナー裁定
# 「頭装備切り替え」)ラボ機能。
#
# equipment_select_dialog.py(dev#165、装備限定)と同型のUI
# (「ＵＩは装備限定とおなじである」オーナー原文)だが、**チェックの意味論が
# 反転している**点が唯一かつ最重要の違い:
#
#   装備限定    : チェックON = 注入対象に含める(絞り込み)。既定 = 全ON。
#   頭装備切り替え: チェックON = 表示する(スタブ生成をスキップ)。既定 = 全OFF。
#
# 「チェックを外した頭装備は、表示しないこと」「デフォルトは全てＯＦＦ」
# (オーナー原文、dev#277)により、装備限定のような「空=全ON」代入トリック
# (未カスタマイズ時にUI上だけ全チェックON表示へすり替える処理)は不要
# ——空選択がそのまま自然に「全チェックOFF」という正しい既定表示になる。
#
# app_pyはpipeline\pyをimportしない設計のため、頭装備コード一覧+表示名は
# pipeline\py\vp_headequip_names.py をsubprocessで起動してJSONを受け取る
# (equipment_select_dialog.pyと同じ「越境しない」流儀)。
from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox
from typing import Callable, Dict, List, Optional, Set

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import window_pos  # noqa: E402

# 選択状態の保存・読み出しロジックは tkinter非依存の headequip_filter_store.py
# にある(equipment_filter_store.pyと同じ理由: pipeline_runner.pyがヘッドレス
# 経路から本モジュールをimportせずに済むよう分離)。
import headequip_filter_store as _store  # noqa: E402

LAB_FEATURE_ID = _store.LAB_FEATURE_ID
_state_path = _store._state_path
load_selected_codes = _store.load_selected_codes
save_selected_codes = _store.save_selected_codes
reset = _store.reset
is_active = _store.is_active
state_summary = _store.state_summary


# ---------------------------------------------------------------------------
# 頭装備カタログ+表示名の解決(pipeline\py\vp_headequip_names.py を
# subprocessで起動する)。
# ---------------------------------------------------------------------------

def _pipeline_script_path(app_root: str, name: str) -> str:
    return os.path.join(app_root, "pipeline", "py", name)


def query_headequip_catalog(
    app_root: str,
    palworld_pak: Optional[str],
    lang: str,
    cache_dir: Optional[str] = None,
    python_exe: Optional[str] = None,
    timeout: float = 60.0,
) -> dict:
    """頭装備コード一覧+可能な限りの表示名を取得する。戻り値は常に
    {"ok": bool, "source": str, "detail": str, "codes": [...], "names": {...}}
    の形(例外を投げない)。

    装備限定(query_equipment_catalog)と異なり、palworld_pak未解決でも
    codesは取れる(コード一覧はこのアプリ自身のカタログ由来で、ユーザーの
    pakに依存しない——vp_headequip_names.py参照)。"""
    manifest_path = _pipeline_script_path(app_root, "noue_template_manifest.json")
    if not os.path.exists(manifest_path):
        return {"ok": False, "source": "none",
                "detail": f"noue_template_manifest.json not found: {manifest_path}",
                "codes": [], "names": {}}

    script = _pipeline_script_path(app_root, "vp_headequip_names.py")
    if not os.path.exists(script):
        return {"ok": False, "source": "none",
                "detail": f"vp_headequip_names.py not found: {script}",
                "codes": [], "names": {}}

    cache_dir = cache_dir or os.path.join(app_root, "work", "_shared_cache", "headequip_names")
    py = python_exe or sys.executable
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    pak_arg = palworld_pak if (palworld_pak and os.path.exists(palworld_pak)) else ""
    try:
        r = subprocess.run(
            [py, script, manifest_path, pak_arg, lang, cache_dir],
            capture_output=True, text=True, timeout=timeout,
            creationflags=creationflags)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "source": "none",
                "detail": f"vp_headequip_names.py could not be run: "
                          f"{type(e).__name__}: {e}",
                "codes": [], "names": {}}

    if r.returncode != 0 or not (r.stdout or "").strip():
        stderr_tail = (r.stderr or "")[-500:]
        return {"ok": False, "source": "none",
                "detail": f"vp_headequip_names.py exited with {r.returncode} "
                          f"(stderr tail: {stderr_tail})",
                "codes": [], "names": {}}

    try:
        last_line = r.stdout.strip().splitlines()[-1]
        result = json.loads(last_line)
    except (json.JSONDecodeError, IndexError) as e:
        return {"ok": False, "source": "none",
                "detail": f"vp_headequip_names.py produced unparsable output: {e}",
                "codes": [], "names": {}}

    result.setdefault("codes", [])
    result.setdefault("names", {})
    return result


# ---------------------------------------------------------------------------
# ダイアログ本体(検索ボックス+スクロール付き複数選択チェックリスト)。
# equipment_select_dialog.show_equipment_select_dialog()とほぼ同じ骨格。
# ---------------------------------------------------------------------------

@dataclass
class HeadEquipSelectContext:
    app_root: str
    palworld_pak: Optional[str]
    lang: str
    cache_dir: Optional[str] = None
    python_exe: Optional[str] = None
    append_log: Callable[[str], None] = field(default=lambda msg: None)


def show_headequip_select_dialog(parent: tk.Misc, ctx: HeadEquipSelectContext) -> tk.Toplevel:
    """dev#277第1弾④の頭装備切り替えダイアログ本体。呼び出しごとに
    Toplevelを1個作る。OKで選択を保存、Cancelは破棄のみ(未保存で閉じる)。

    equipment_select_dialogとの最重要差分: チェックON=表示する、既定=
    全チェックOFF(オーナー原文どおり)。「空=全ON」トリックは使わない。"""
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("LabHeadEquipToggleDialogTitle"))
    dlg.geometry("380x460")
    dlg.transient(parent)
    i18n.register(dlg, "LabHeadEquipToggleDialogTitle", lambda w, t: w.title(t))
    window_pos.apply_offset_position(dlg, parent)

    result = query_headequip_catalog(
        ctx.app_root, ctx.palworld_pak, ctx.lang,
        cache_dir=ctx.cache_dir, python_exe=ctx.python_exe)
    ctx.append_log(f"[lab][headequip_toggle] catalog query: ok={result.get('ok')} "
                    f"source={result.get('source')} detail={result.get('detail')}")

    codes: List[str] = list(result.get("codes") or [])
    names: Dict[str, str] = dict(result.get("names") or {})
    display = {c: names.get(c, c) for c in codes}

    hint = tk.Label(dlg, text=i18n.S("LabHeadEquipToggleHint"),
                     wraplength=356, justify="left", anchor="w")
    hint.pack(fill="x", padx=8, pady=(8, 0))
    i18n.register(hint, "LabHeadEquipToggleHint")

    if not codes:
        notice = tk.Label(dlg, text=i18n.S("LabHeadEquipToggleCatalogUnavailableNotice"),
                           fg="#a06000", wraplength=356, justify="left")
        notice.pack(fill="x", padx=8, pady=(8, 0))
        i18n.register(notice, "LabHeadEquipToggleCatalogUnavailableNotice")
    elif not result.get("ok") and not names:
        notice = tk.Label(dlg, text=i18n.S("LabHeadEquipToggleFallbackNotice"),
                           fg="#a06000", wraplength=356, justify="left")
        notice.pack(fill="x", padx=8, pady=(8, 0))
        i18n.register(notice, "LabHeadEquipToggleFallbackNotice")

    # equipment_select_dialogと異なり、既定(空選択)は「そのまま何もチェック
    # しない」がオーナー原文どおりの正しい表示なので、代入トリックは無い。
    full_codes: Set[str] = set(codes)
    selected: Set[str] = set(load_selected_codes(ctx.app_root))

    search_frame = tk.Frame(dlg)
    search_frame.pack(fill="x", padx=8, pady=8)
    search_label = tk.Label(search_frame, text=i18n.S("LabEquipmentFilterSearchLabel"))
    search_label.pack(side="left")
    i18n.register(search_label, "LabEquipmentFilterSearchLabel")
    search_var = tk.StringVar()
    search_entry = tk.Entry(search_frame, textvariable=search_var)
    search_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))

    list_frame = tk.Frame(dlg)
    list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
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

    check_vars: Dict[str, tk.BooleanVar] = {}
    check_widgets: Dict[str, tk.Checkbutton] = {}
    for code in sorted(codes, key=lambda c: display[c].lower()):
        var = tk.BooleanVar(value=(code in selected))
        check_vars[code] = var
        cb = tk.Checkbutton(inner, text=display[code], variable=var, anchor="w")
        cb.bind("<MouseWheel>", _on_mousewheel)
        check_widgets[code] = cb

    def apply_search(*_args) -> None:
        q = search_var.get().strip().lower()
        for cb in check_widgets.values():
            cb.pack_forget()
        for code in sorted(codes, key=lambda c: display[c].lower()):
            if q and q not in display[code].lower() and q not in code.lower():
                continue
            check_widgets[code].pack(anchor="w", fill="x")

    search_var.trace_add("write", apply_search)
    apply_search()

    btn_frame1 = tk.Frame(dlg)
    btn_frame1.pack(fill="x", padx=8)
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

    def on_ok() -> None:
        if not full_codes:
            # カタログ取得が完全失敗(codes=[])した状態では、何を選んだか
            # 判断できないため保存は一切行わない(equipment_select_dialogの
            # PR #1202バグ修正と同じ「わからないときは黙って壊さない」)。
            ctx.append_log(
                "[lab][headequip_toggle] catalog unavailable (codes empty); "
                "OK closed without saving, existing selection preserved")
            dlg.destroy()
            return
        chosen = {code for code, var in check_vars.items() if var.get()}
        # 頭装備切り替えは全OFF(=何も表示しない=既定)が正しい状態のため、
        # equipment_select_dialogの「全OFF警告」は不要(意味が逆)。
        save_selected_codes(ctx.app_root, sorted(chosen))
        ctx.append_log(
            f"[lab][headequip_toggle] selection saved: "
            f"{len(chosen)} of {len(full_codes)} code(s) checked (shown)")
        dlg.destroy()

    ok_btn = tk.Button(btn_frame2, text=i18n.S("BtnOk"), command=on_ok)
    ok_btn.pack(side="right")
    i18n.register(ok_btn, "BtnOk")
    cancel_btn = tk.Button(btn_frame2, text=i18n.S("BtnCancel"), command=dlg.destroy)
    cancel_btn.pack(side="right", padx=(0, 4))
    i18n.register(cancel_btn, "BtnCancel")

    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    return dlg


# ---------------------------------------------------------------------------
# dev#1186 ラボ機能レジストリ記述子(lab_window.py側が結線する)。
# ---------------------------------------------------------------------------

LAB_REGISTRY_DESCRIPTOR = {
    "id": LAB_FEATURE_ID,
    "name_key": "LabFeatureHeadEquipToggle",
    "state_summary": state_summary,
    "open_dialog": show_headequip_select_dialog,
    "reset": reset,
}
