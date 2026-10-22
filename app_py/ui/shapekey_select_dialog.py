# shapekey_select_dialog.py -- dev#1168(2026-08-09 シェイプキー)ラボ機能。
#
# 変換時にBlender側で焼き込むシェイプキー(ブレンドシェイプ)値を設定する
# ダイアログ+ラボUI基盤(dev#1186)向けの機能レジストリ記述子。
#
# 仕様の正本: gh issue view 1168 --repo pandrabox/DiveToPalworld-dev
#   2026-08-09オーナー裁定「シェイプキーはBSありでexportしちゃうと同じ
#   ロジックに乗せられて便利。②+スライダーUIでGO」。
#   UI裁定(同日、指揮者コメント): 「任意のメッシュとBS一覧とスライダー、
#   検索機能付き」(オーナー原文)。人間の頭部はBSが数千個ある場合があるため
#   検索は必須――全件のスライダー常時描画はtkinterでは破綻するため、
#   検索で絞った結果+変更済みキーのみ描画する。
#
# **本WPはlab_window.py/main_window.pyへの結線を行わない**(並行WPとの衝突
# 回避、指示書の書き込み許可範囲)。結線に必要なのは以下の対応(equipment_
# select_dialog.py wiring節と同じ形、lab_window.py側に薄いアダプタ3関数+
# LabFeature追加が必要):
#   lab_window.py 側(_shapekey_status_summary/_open_shapekey_dialog/
#   _shapekey_reset_default の3アダプタ+LAB_FEATURESへの追加。アダプタは
#   self.app_root・self.work_root・self.widgets["vrmBox"].get().strip() を
#   ShapeKeySelectContextへ渡すだけ):
#     def _shapekey_status_summary(self):
#         avatar = self.widgets["vrmBox"].get().strip() if "vrmBox" in self.widgets else ""
#         return shapekey_select_dialog.state_summary(self.app_root, avatar)
#     def _shapekey_reset_default(self):
#         shapekey_select_dialog.reset(self.app_root)
#     def _open_shapekey_dialog(self, parent, on_change):
#         avatar = self.widgets["vrmBox"].get().strip() if "vrmBox" in self.widgets else ""
#         ctx = shapekey_select_dialog.ShapeKeySelectContext(
#             app_root=self.app_root, work_root=self.work_root, avatar_path=avatar,
#             append_log=getattr(self, "_log", lambda msg: None))
#         dlg = shapekey_select_dialog.show_shapekey_select_dialog(parent, ctx)
#         dlg.bind("<Destroy>", lambda _e: on_change(), add="+")
#         return dlg
#     SHAPEKEY_FEATURE = LabFeature(
#         feature_id=shapekey_select_dialog.LAB_FEATURE_ID,
#         name_key=shapekey_select_dialog.LAB_REGISTRY_DESCRIPTOR["name_key"],
#         status_summary=_shapekey_status_summary,
#         open_dialog=_open_shapekey_dialog,
#         reset_default=_shapekey_reset_default)
#     LAB_FEATURES = [..., SHAPEKEY_FEATURE]
#   pipeline_runner.py(job.json組み立て箇所)側は本WPで既に配線済み
#   (write_job()がshapekey_filter_store.load_config()を直接読む)。
#
# app_pyはpipeline\pyをimportしない設計(pak_manager.py冒頭コメント踏襲)。
# 一覧取得(shapekey_catalog.py)はVRM=glTF JSON直読み/prefab=Unityエクスポート
# 時のサイドカーJSON(shape_keys.json)読み込みのみで、いずれもsubprocess・
# pipeline\py越境は不要。
from __future__ import annotations

import os
import sys
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pipeline_runner  # noqa: E402  (resolve_unity_export_out_dir()の再利用のみ)
import shapekey_catalog  # noqa: E402
import shapekey_filter_store as _store  # noqa: E402
from ui import window_pos  # noqa: E402  (2026-08-08: 親窓に重ねる位置決め)

LAB_FEATURE_ID = _store.LAB_FEATURE_ID
load_config = _store.load_config
save_config = _store.save_config
reset = _store.reset
is_active = _store.is_active
state_summary = _store.state_summary


# ---------------------------------------------------------------------------
# カタログ解決(VRM=glTF直読み/prefab=Unityエクスポートのサイドカー)。
# ---------------------------------------------------------------------------

def resolve_catalog(app_root: str, work_root: str, avatar_path: str) -> dict:
    """{"ok": bool, "detail": str, "meshes": {mesh: [key, ...]}} を返す
    (例外を投げない)。"""
    if not avatar_path:
        return {"ok": False, "detail": "no avatar selected", "meshes": {}}
    lower = avatar_path.lower()
    if lower.endswith(".vrm"):
        return shapekey_catalog.catalog_from_vrm(avatar_path)
    if lower.endswith(".prefab"):
        out_dir = pipeline_runner.resolve_unity_export_out_dir(work_root, avatar_path)
        sidecar = os.path.join(out_dir, "shape_keys.json")
        return shapekey_catalog.catalog_from_sidecar(sidecar)
    return {"ok": False, "detail": f"unsupported avatar type: {avatar_path}", "meshes": {}}


# ---------------------------------------------------------------------------
# ダイアログ本体(メッシュ選択+検索ボックス+スクロール付きスライダー一覧)。
# ---------------------------------------------------------------------------

@dataclass
class ShapeKeySelectContext:
    app_root: str
    work_root: str
    avatar_path: str
    append_log: Callable[[str], None] = field(default=lambda msg: None)
    # dev#1277: 保存のみ行い、こだわり設定パネルの既存プレビュー再レンダ
    # 機構(main_window._on_preview_only)をダイアログ内から起動するための
    # コールバック(equipment_select_dialogのappend_logと同じ「呼び出し元の
    # 関数をそのまま渡す」パターン)。lab_window._open_shapekey_dialog()が
    # 束縛して渡す。テスト等でNoneのままでも例外にならない(ガード必須)。
    trigger_preview: Optional[Callable[[], None]] = field(default=None)


def show_shapekey_select_dialog(parent: tk.Misc, ctx: ShapeKeySelectContext) -> tk.Toplevel:
    """dev#1168のシェイプキー設定ダイアログ本体。OKで選択を保存、Cancel/×は
    破棄のみ(未保存で閉じる、equipment/headequip選択ダイアログと同じ流儀)。"""
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("LabShapeKeysDialogTitle"))
    dlg.geometry("520x480")
    dlg.transient(parent)
    i18n.register(dlg, "LabShapeKeysDialogTitle", lambda w, t: w.title(t))
    window_pos.apply_offset_position(dlg, parent)

    hint = tk.Label(dlg, text=i18n.S("LabShapeKeysHint"),
                     wraplength=496, justify="left", anchor="w")
    hint.pack(fill="x", padx=8, pady=(8, 0))
    i18n.register(hint, "LabShapeKeysHint")

    result = resolve_catalog(ctx.app_root, ctx.work_root, ctx.avatar_path)
    ctx.append_log(f"[lab][shape_keys] catalog: ok={result.get('ok')} "
                    f"detail={result.get('detail')} "
                    f"meshes={len(result.get('meshes') or {})}")
    catalog: Dict[str, list] = dict(result.get("meshes") or {})

    if not catalog:
        notice = tk.Label(dlg, text=i18n.S("LabShapeKeysCatalogUnavailableNotice"),
                           fg="#a06000", wraplength=496, justify="left")
        notice.pack(fill="x", padx=8, pady=(8, 0))
        i18n.register(notice, "LabShapeKeysCatalogUnavailableNotice")

    # 編集中の値(mesh -> {key: value})。保存済み設定+今回のカタログに無い
    # メッシュぶんの残留値もそのまま保持する(カタログ取得が部分失敗しても
    # 既存設定を消さない、equipment_select_dialogのdev#1210修正と同じ考え方)。
    stored = load_config(ctx.app_root, ctx.avatar_path)
    values: Dict[str, Dict[str, float]] = {m: dict(kv) for m, kv in stored.items()}
    for m in catalog:
        values.setdefault(m, {})

    body = tk.Frame(dlg)
    body.pack(fill="both", expand=True, padx=8, pady=8)

    mesh_frame = tk.Frame(body)
    mesh_frame.pack(side="left", fill="y")
    mesh_label = tk.Label(mesh_frame, text=i18n.S("LabShapeKeysMeshListLabel"), anchor="w")
    mesh_label.pack(fill="x")
    i18n.register(mesh_label, "LabShapeKeysMeshListLabel")
    mesh_listbox = tk.Listbox(mesh_frame, exportselection=False, width=18, height=18)
    mesh_listbox.pack(fill="y", expand=True)
    mesh_names = sorted(catalog.keys())
    for m in mesh_names:
        mesh_listbox.insert(tk.END, m)

    right_frame = tk.Frame(body)
    right_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))

    search_frame = tk.Frame(right_frame)
    search_frame.pack(fill="x")
    search_label = tk.Label(search_frame, text=i18n.S("LabShapeKeysSearchLabel"))
    search_label.pack(side="left")
    i18n.register(search_label, "LabShapeKeysSearchLabel")
    search_var = tk.StringVar()
    search_entry = tk.Entry(search_frame, textvariable=search_var)
    search_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))

    list_frame = tk.Frame(right_frame)
    list_frame.pack(fill="both", expand=True, pady=(4, 0))
    canvas = tk.Canvas(list_frame, highlightthickness=0)
    scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas)
    inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # dev#1275実機報告(オーナー): スライダーを0.5より大きい値にすると
    # 見切れる。原因はcanvas内に埋め込んだinnerフレームの幅がcanvas自身の
    # 描画幅に束縛されておらず、ラベル(width=28)+スライダー(length=280)の
    # 合計自然幅がcanvasの可視幅を超えていたこと(可視幅は右のmesh_frame・
    # スクロールバー分を差し引いた残りでラベル+スライダーの合計より狭い)。
    # スライダーは`fill="x", expand=True`で伸縮可能なので、innerの幅を
    # canvas自身の実測幅へ追従させれば、スライダーがその残り幅に収まって
    # 右側が可視範囲外へはみ出さなくなる(横スクロールバーは追加しない
    # ――縦スクロールのみで完結させる元の設計を保つ)。
    def _on_canvas_configure(event: "tk.Event") -> None:
        canvas.itemconfig(inner_window, width=event.width)

    canvas.bind("<Configure>", _on_canvas_configure)

    def _on_mousewheel(event: "tk.Event") -> str:
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    canvas.bind("<MouseWheel>", _on_mousewheel, add="+")
    inner.bind("<MouseWheel>", _on_mousewheel)

    # 現在描画中の行(key -> Frame)+そのkeyのScaleウィジェット(key -> Scale)。
    # メッシュ切替・検索のたびに作り直す(数千件を常時保持しない、ラボ憲章②
    # 「雑な実装でよい」の範囲での素直な実装)。値の確定読み取りは
    # command=コールバックに頼らず(環境によって.set()時に発火しない実測が
    # あるため)、再描画直前/OK押下時に明示的にScale.get()を読み戻す
    # _sync_current_view_to_values()で行う(数値ラベルの表示更新だけは
    # command=でリアルタイムに追従させるが、保存に使う確定値の読み取りには
    # 使わない――上記の理由と矛盾しない)。
    #
    # dev#1275実機報告(オーナーSS): 1キーの行が「ラベル行+数値・スライダー
    # 行」の縦2段に見えて間延びしていた。原因はtk.Scale標準の値表示
    # (showvalue既定True)がトラフの真上に別行として数値を描画するため
    # (Frame自体は元から単一行だが、Scale内部の描画がもう1行分の高さを
    # 消費していた)。対処: showvalue=Falseにして標準の値表示を止め、
    # キー名ラベル・数値ラベル・スライダーの3つを同じ行に横並びさせる
    # (キー名/数値/スライダーの合計自然幅がcanvasの可視幅を超えないよう、
    # キー名は固定幅+末尾省略、数値は固定幅で確保し、残りをスライダーへ
    # fill="x", expand=Trueで配分――0.5超見切れ修正[canvas <Configure>で
    # innerの幅をcanvas幅へ追従]と両立させる)。
    _KEY_LABEL_MAX_CHARS = 22

    def _display_key(key: str) -> str:
        if len(key) <= _KEY_LABEL_MAX_CHARS:
            return key
        return key[: _KEY_LABEL_MAX_CHARS - 1] + "…"

    rows: Dict[str, tk.Frame] = {}
    row_scales: Dict[str, tk.Scale] = {}
    row_value_vars: Dict[str, tk.StringVar] = {}
    current_mesh_var = tk.StringVar(value=mesh_names[0] if mesh_names else "")

    def _current_mesh() -> str:
        return current_mesh_var.get()

    def _sync_current_view_to_values() -> None:
        mesh = _current_mesh()
        if not mesh:
            return
        mesh_values = values.setdefault(mesh, {})
        for key, scale in row_scales.items():
            try:
                v = float(scale.get())
            except (tk.TclError, ValueError, TypeError):
                continue
            if v:
                mesh_values[key] = v
            else:
                mesh_values.pop(key, None)

    def render_keys(*_args) -> None:
        _sync_current_view_to_values()  # 描画し直す前に、直前の表示内容を確定させる
        for w in rows.values():
            w.destroy()
        rows.clear()
        row_scales.clear()
        row_value_vars.clear()
        mesh = _current_mesh()
        keys = catalog.get(mesh, [])
        q = search_var.get().strip().lower()
        mesh_values = values.setdefault(mesh, {})
        for key in keys:
            current_val = mesh_values.get(key, 0.0)
            # 検索に一致しない行は、値が既に非既定(変更済み)なら常時表示、
            # そうでなければ描画自体をスキップする(数千件対策)。
            if q and q not in key.lower() and not current_val:
                continue
            row = tk.Frame(inner)
            row.bind("<MouseWheel>", _on_mousewheel)
            lbl = tk.Label(row, text=_display_key(key), width=_KEY_LABEL_MAX_CHARS, anchor="w")
            lbl.pack(side="left")
            lbl.bind("<MouseWheel>", _on_mousewheel)

            value_var = tk.StringVar(value=f"{current_val:.2f}")
            value_lbl = tk.Label(row, textvariable=value_var, width=4, anchor="e")
            value_lbl.pack(side="left", padx=(4, 4))
            value_lbl.bind("<MouseWheel>", _on_mousewheel)

            def _on_scale_move(v: str, var: tk.StringVar = value_var) -> None:
                try:
                    var.set(f"{float(v):.2f}")
                except (ValueError, TypeError):
                    pass

            scale = tk.Scale(
                row, from_=0.0, to=1.0, resolution=0.01, orient="horizontal",
                length=200, showvalue=False, command=_on_scale_move,
            )
            scale.set(current_val)
            scale.pack(side="left", fill="x", expand=True)
            scale.bind("<MouseWheel>", _on_mousewheel)
            row.pack(anchor="w", fill="x")
            rows[key] = row
            row_scales[key] = scale
            row_value_vars[key] = value_var

    def _on_mesh_select(_event=None) -> None:
        sel = mesh_listbox.curselection()
        if not sel:
            return
        current_mesh_var.set(mesh_listbox.get(sel[0]))
        search_var.set("")
        render_keys()

    mesh_listbox.bind("<<ListboxSelect>>", _on_mesh_select)
    search_var.trace_add("write", render_keys)
    if mesh_names:
        mesh_listbox.selection_set(0)
        render_keys()

    btn_frame = tk.Frame(dlg)
    btn_frame.pack(fill="x", padx=8, pady=8)

    def on_ok() -> None:
        _sync_current_view_to_values()
        save_config(ctx.app_root, ctx.avatar_path, values)
        n = sum(len(kv) for kv in values.values())
        ctx.append_log(f"[lab][shape_keys] saved: {n} key(s) across "
                        f"{sum(1 for kv in values.values() if kv)} mesh(es)")
        dlg.destroy()

    ok_btn = tk.Button(btn_frame, text=i18n.S("BtnOk"), command=on_ok)
    ok_btn.pack(side="right")
    i18n.register(ok_btn, "BtnOk")
    cancel_btn = tk.Button(btn_frame, text=i18n.S("BtnCancel"), command=dlg.destroy)
    cancel_btn.pack(side="right", padx=(0, 4))
    i18n.register(cancel_btn, "BtnCancel")

    # dev#1277: 保存はするがダイアログは閉じない(スライダーの続けての調整
    # → 再プレビューのワークフローを許すため、on_okとの違いはdlg.destroy()の
    # 有無のみ)。呼ぶのはこだわり設定パネルの既存ボタンと全く同じ
    # ctx.trigger_preview()(=main_window._on_preview_only)、新しいレンダ
    # 経路は発明しない(DESIGN.md 1.2節)。
    def on_preview_update() -> None:
        _sync_current_view_to_values()
        save_config(ctx.app_root, ctx.avatar_path, values)
        n = sum(len(kv) for kv in values.values())
        ctx.append_log(f"[lab][shape_keys] saved for preview: {n} key(s) across "
                        f"{sum(1 for kv in values.values() if kv)} mesh(es)")
        if ctx.trigger_preview:
            ctx.trigger_preview()

    preview_btn = tk.Button(btn_frame, text=i18n.S("BtnPreviewUpdate"),
                             command=on_preview_update)
    preview_btn.pack(side="left")
    i18n.register(preview_btn, "BtnPreviewUpdate")

    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    return dlg


# ---------------------------------------------------------------------------
# dev#1186 ラボ機能レジストリ記述子(lab_window.py側が結線するためのもの。
# 本WPではlab_window.pyを変更しない。equipment_select_dialog.py/
# headequip_select_dialog.pyと同型)。
# ---------------------------------------------------------------------------

LAB_REGISTRY_DESCRIPTOR = {
    "id": LAB_FEATURE_ID,
    "name_key": "LabFeatureShapeKeys",
    "state_summary": state_summary,
    "open_dialog": show_shapekey_select_dialog,
    "reset": reset,
}
