# mesh_delete_dialog.py -- dev#1168前半(2026-08-09 オーナー指示「メッシュの
# ほうは名前一覧出してチェックはずすときえるでいいでしょ」)ラボ機能
# 「メッシュ削除」。
#
# equipment_select_dialog.py/headequip_select_dialog.py(dev#165/dev#277第1弾④)
# と同型のチェックリストUI。**意味論(装備限定と同じ向き)**:
#   チェックON  = そのメッシュを残す。既定 = 全チェックON(削除無し)。
#   チェックOFF = そのメッシュを削除する。
# 保存する値は「チェックOFFにしたメッシュ名の集合」(=削除対象。
# mesh_delete_store.save_deleted_names())。全ON(既定)のままOKを押すと
# 削除対象は空集合になり、job["drop_meshes"]キーが一切出ない状態
# (ラボ憲章④=未実装状態と完全同一)を維持する。equipment_select_dialogの
# 「全OFF(=全削除)は保存を弾く」警告もここで踏襲する
# (アバターを全損させる保存を許さない)。
#
# 装備限定・頭装備切り替えと異なり、本機能のチェックリストは**Palworld側の
# 固定カタログではなく、入力アバター自身のメッシュ名**が対象になる
# (アバターを差し替えるたびに一覧が変わる)。取得方法は入力形式ごとに
# 異なる(2026-08-09実装時点の調査結果、完了報告にも明記):
#
#   VRM(.vrm): VRMファイル自体がglTF 2.0のバイナリコンテナ(GLB形式、
#     ヘッダ+JSON chunk+BIN chunk)なので、Blenderを起動せずJSON chunkだけを
#     直接パースする(高速)。nodes[].mesh を持つノードのnode.name(無ければ
#     meshes[mesh_idx].name)を「元のメッシュ名」として採用する——
#     pipeline\\blender\\step01_import_vrm.py の cleanup_objects() が
#     Blenderオブジェクト名(=VRMインポート時のノード名)を最終的に
#     geo_XXへリネームする直前の名前と一致する見込み(実サンプル4種で
#     実測、work\\wp_1168_mesh\\PROGRESS.md参照)。
#
#   prefab(.prefab): Unity輸出は既にGUI操作(prefab選択)の時点で走っている
#     前提とし、ここでは追加の輸出を行わない(ダイアログを開くたびに重い
#     Unity起動を挟まないため)。輸出済みキャッシュ
#     (pipeline_runner.resolve_unity_export_out_dir()が指すout_dir配下の
#     material_map.json、DiveToPalworldExporter.cs ExportMaterials()が
#     "meshes"キーにRenderer.name=GameObject名で書き出す)をそのまま読む。
#     未輸出/ファイル欠落ならカタログ取得失敗として扱う。
#
#   いずれも失敗した場合(未対応拡張子・パース失敗・輸出未実行等)は
#   カンマ区切り手入力のフォールバックUIに落とす(dev#1168本文が元々
#   想定していた `メッシュ名;メッシュ名` 形式を、チェックリストが使えない
#   ときの代替として採用。「わからないときは黙って壊さない」——保存済み
#   設定はカタログ失敗時に上書きしない、equipment_select_dialogのPR #1202
#   バグ修正と同じ方針)。
#
# **本WPはlab_window.py/main_window.pyへの結線を行わない**(lab-devスキル
# 指示、並行WP=シェイプキー側との衝突回避)。結線に必要なのは以下の1行のみ:
#   lab_window.py 側:
#     LAB_FEATURES = [..., 既存のLabFeatureアダプタパターンで
#       mesh_delete_dialog.LAB_REGISTRY_DESCRIPTOR を包んだ MeshFeature]
#     (equipment_select_dialog/headequip_select_dialogのEQUIPMENT_FILTER_
#      FEATURE/HEADEQUIP_TOGGLE_FEATUREアダプタと同じ形。avatar_pathは
#      self.widgets["vrmBox"].get()、work_rootはself.work_rootから渡す)
#   pipeline_runner.py 側: 既に本WPで配線済み(mesh_delete_store経由)。
from __future__ import annotations

import json
import os
import struct
import sys
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox
from typing import Callable, Dict, List, Optional, Set

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pipeline_runner  # noqa: E402  (resolve_unity_export_out_dir()の再利用のみ、越境しない)
from ui import window_pos  # noqa: E402  (2026-08-08: 親窓に重ねる位置決め)

# 選択状態の保存・読み出しロジックは tkinter非依存の mesh_delete_store.py
# にある(equipment_filter_store.pyと同じ理由: pipeline_runner.pyがヘッドレス
# 経路から本モジュールをimportせずに済むよう分離)。
import mesh_delete_store as _store  # noqa: E402

LAB_FEATURE_ID = _store.LAB_FEATURE_ID
_state_path = _store._state_path
load_deleted_names = _store.load_deleted_names
save_deleted_names = _store.save_deleted_names
reset = _store.reset
is_active = _store.is_active
state_summary = _store.state_summary


# ---------------------------------------------------------------------------
# メッシュ名カタログの取得(VRM: GLBコンテナ直接パース / prefab: 既存の
# Unity輸出キャッシュ読み出し。いずれもBlender/Unityを新規起動しない)。
# ---------------------------------------------------------------------------

def _read_glb_json_chunk(vrm_path: str) -> dict:
    """VRM(GLBコンテナ)の先頭JSON chunkだけを読んでパースする。
    ヘッダ: <4s magic("glTF") I version I total_length>、続けて
    <I chunk_length 4s chunk_type> + chunk_dataの繰り返し(glTF 2.0仕様)。
    最初のchunkが常にJSON(仕様上の制約)。異常系はValueErrorへ正規化する
    (呼び出し元がまとめてok=Falseへ落とすため)。"""
    with open(vrm_path, "rb") as f:
        header = f.read(12)
        if len(header) < 12:
            raise ValueError("file too small to be a GLB/VRM container")
        magic, _version, _length = struct.unpack("<4sII", header)
        if magic != b"glTF":
            raise ValueError(f"not a glTF/VRM binary container (magic={magic!r})")
        chunk_header = f.read(8)
        if len(chunk_header) < 8:
            raise ValueError("missing JSON chunk header")
        chunk_len, chunk_type = struct.unpack("<I4s", chunk_header)
        if chunk_type != b"JSON":
            raise ValueError(f"first chunk is not JSON (type={chunk_type!r})")
        chunk = f.read(chunk_len)
        if len(chunk) < chunk_len:
            raise ValueError("truncated JSON chunk")
    return json.loads(chunk)


def vrm_mesh_names(vrm_path: str) -> List[str]:
    """VRMファイルからメッシュを持つノードの名前一覧を返す(重複除去、
    出現順)。pipeline\\blender\\step01_import_vrm.py の cleanup_objects()が
    最終的にgeo_XXへリネームする前の名前と一致する見込み(モジュール
    docstring参照)。"""
    doc = _read_glb_json_chunk(vrm_path)
    meshes = doc.get("meshes") or []
    names: List[str] = []
    seen: Set[str] = set()
    for idx, node in enumerate(doc.get("nodes") or []):
        if not isinstance(node, dict) or "mesh" not in node:
            continue
        mesh_idx = node.get("mesh")
        name = node.get("name")
        if not name and isinstance(mesh_idx, int) and 0 <= mesh_idx < len(meshes):
            name = meshes[mesh_idx].get("name")
        if not name:
            name = f"mesh_{idx}"
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def query_mesh_catalog(app_root: str, work_root: str, avatar_path: str) -> dict:
    """入力アバターのメッシュ名一覧を取得する。戻り値は常に
    {"ok": bool, "source": str, "detail": str, "names": [...]}
    の形(例外を投げない、三点セットの③=detailに探索結果を残す)。"""
    if not avatar_path or not os.path.exists(avatar_path):
        return {"ok": False, "source": "none",
                "detail": f"avatar not selected or not found: {avatar_path!r}",
                "names": []}

    ext = os.path.splitext(avatar_path)[1].lower()

    if ext == ".vrm":
        try:
            names = vrm_mesh_names(avatar_path)
        except (OSError, ValueError, struct.error,
                json.JSONDecodeError, AttributeError, TypeError) as e:
            return {"ok": False, "source": "vrm",
                    "detail": f"failed to parse VRM container: {type(e).__name__}: {e}",
                    "names": []}
        if not names:
            return {"ok": False, "source": "vrm",
                    "detail": "no mesh nodes found in VRM", "names": []}
        return {"ok": True, "source": "vrm",
                "detail": "parsed glTF JSON chunk directly (no Blender launch)",
                "names": names}

    if ext == ".prefab":
        out_dir = pipeline_runner.resolve_unity_export_out_dir(work_root, avatar_path)
        map_path = os.path.join(out_dir, "material_map.json")
        if not os.path.isfile(map_path):
            return {"ok": False, "source": "prefab",
                    "detail": f"material_map.json not found (Unity export not run yet?): "
                              f"{map_path}",
                    "names": []}
        try:
            with open(map_path, encoding="utf-8") as f:
                data = json.load(f)
            names = list((data.get("meshes") or {}).keys())
        except (OSError, json.JSONDecodeError, AttributeError, TypeError) as e:
            return {"ok": False, "source": "prefab",
                    "detail": f"failed to read material_map.json: {type(e).__name__}: {e}",
                    "names": []}
        if not names:
            return {"ok": False, "source": "prefab",
                    "detail": f"material_map.json has no meshes: {map_path}", "names": []}
        return {"ok": True, "source": "prefab",
                "detail": f"read {map_path}", "names": names}

    return {"ok": False, "source": "none",
            "detail": f"unsupported avatar extension for mesh enumeration: {ext!r}",
            "names": []}


# ---------------------------------------------------------------------------
# ダイアログ本体。catalog取得成功時=チェックリスト、失敗時=カンマ区切り
# 手入力のフォールバック(モジュールdocstring参照)。
# ---------------------------------------------------------------------------

@dataclass
class MeshDeleteContext:
    app_root: str
    work_root: str
    avatar_path: str
    append_log: Callable[[str], None] = field(default=lambda msg: None)
    # dev#1277: shapekey_select_dialog.ShapeKeySelectContext.trigger_previewと
    # 同じパターン。保存後にこだわり設定パネルの既存プレビュー再レンダ機構
    # (main_window._on_preview_only)を起動するコールバック。lab_window.
    # _open_mesh_delete_dialog()が束縛して渡す。Noneのままでも例外にならない。
    trigger_preview: Optional[Callable[[], None]] = field(default=None)


def show_mesh_delete_dialog(parent: tk.Misc, ctx: MeshDeleteContext) -> tk.Toplevel:
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("LabMeshDeleteDialogTitle"))
    dlg.geometry("380x460")
    dlg.transient(parent)
    i18n.register(dlg, "LabMeshDeleteDialogTitle", lambda w, t: w.title(t))
    window_pos.apply_offset_position(dlg, parent)

    result = query_mesh_catalog(ctx.app_root, ctx.work_root, ctx.avatar_path)
    ctx.append_log(f"[lab][mesh_delete] catalog query: ok={result.get('ok')} "
                    f"source={result.get('source')} detail={result.get('detail')}")

    hint = tk.Label(dlg, text=i18n.S("LabMeshDeleteHint"),
                     wraplength=356, justify="left", anchor="w")
    hint.pack(fill="x", padx=8, pady=(8, 0))
    i18n.register(hint, "LabMeshDeleteHint")

    names: List[str] = list(result.get("names") or [])

    if not result.get("ok") or not names:
        # フォールバック: カンマ区切り手入力(モジュールdocstring参照)。
        notice = tk.Label(dlg, text=i18n.S("LabMeshDeleteCatalogUnavailableNotice"),
                           fg="#a06000", wraplength=356, justify="left")
        notice.pack(fill="x", padx=8, pady=(8, 0))
        i18n.register(notice, "LabMeshDeleteCatalogUnavailableNotice")

        manual_label = tk.Label(dlg, text=i18n.S("LabMeshDeleteManualLabel"), anchor="w")
        manual_label.pack(fill="x", padx=8, pady=(8, 0))
        i18n.register(manual_label, "LabMeshDeleteManualLabel")

        manual_entry = tk.Entry(dlg)
        manual_entry.insert(0, ", ".join(load_deleted_names(ctx.app_root, ctx.avatar_path)))
        manual_entry.pack(fill="x", padx=8, pady=(0, 8))

        btn_frame = tk.Frame(dlg)
        btn_frame.pack(fill="x", padx=8, pady=8, side="bottom")

        def on_ok_manual() -> None:
            raw = [n.strip() for n in manual_entry.get().split(",") if n.strip()]
            save_deleted_names(ctx.app_root, ctx.avatar_path, raw)
            ctx.append_log(f"[lab][mesh_delete] manual entry saved: {len(raw)} name(s)")
            dlg.destroy()

        ok_btn = tk.Button(btn_frame, text=i18n.S("BtnOk"), command=on_ok_manual)
        ok_btn.pack(side="right")
        i18n.register(ok_btn, "BtnOk")
        cancel_btn = tk.Button(btn_frame, text=i18n.S("BtnCancel"), command=dlg.destroy)
        cancel_btn.pack(side="right", padx=(0, 4))
        i18n.register(cancel_btn, "BtnCancel")

        # dev#1277: 保存はするがダイアログは閉じない(on_ok_manualとの違いは
        # dlg.destroy()の有無のみ)。
        def on_preview_update_manual() -> None:
            raw = [n.strip() for n in manual_entry.get().split(",") if n.strip()]
            save_deleted_names(ctx.app_root, ctx.avatar_path, raw)
            ctx.append_log(
                f"[lab][mesh_delete] manual entry saved for preview: {len(raw)} name(s)")
            if ctx.trigger_preview:
                ctx.trigger_preview()

        preview_btn = tk.Button(btn_frame, text=i18n.S("BtnPreviewUpdate"),
                                 command=on_preview_update_manual)
        preview_btn.pack(side="left")
        i18n.register(preview_btn, "BtnPreviewUpdate")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        return dlg

    # --- チェックリストモード(カタログ取得成功) ---
    full_names: Set[str] = set(names)
    deleted_saved: Set[str] = set(load_deleted_names(ctx.app_root, ctx.avatar_path))
    # チェックON=残す。既定(未カスタマイズ=削除リストが空)なら全チェックON。
    checked: Set[str] = full_names - deleted_saved

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

    check_vars: Dict[str, tk.BooleanVar] = {}
    for name in sorted(names, key=lambda n: n.lower()):
        var = tk.BooleanVar(value=(name in checked))
        check_vars[name] = var
        cb = tk.Checkbutton(inner, text=name, variable=var, anchor="w")
        cb.pack(anchor="w", fill="x")
        cb.bind("<MouseWheel>", _on_mousewheel)

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

    def on_ok() -> None:
        chosen = {name for name, var in check_vars.items() if var.get()}  # 残す側
        if full_names and not chosen:
            # 全OFF(=全メッシュ削除)は保存を弾く(equipment_select_dialogの
            # 「全OFF警告」と同じ枠、アバター全損の保存を防ぐ)。
            messagebox.showwarning(
                i18n.S("LabMeshDeleteDialogTitle"),
                i18n.S("LabMeshDeleteAllOffWarning"))
            return
        to_delete = full_names - chosen
        save_deleted_names(ctx.app_root, ctx.avatar_path, sorted(to_delete))
        ctx.append_log(
            f"[lab][mesh_delete] selection saved: "
            f"{len(to_delete)} of {len(full_names)} mesh(es) marked for deletion")
        dlg.destroy()

    ok_btn = tk.Button(btn_frame2, text=i18n.S("BtnOk"), command=on_ok)
    ok_btn.pack(side="right")
    i18n.register(ok_btn, "BtnOk")
    cancel_btn = tk.Button(btn_frame2, text=i18n.S("BtnCancel"), command=dlg.destroy)
    cancel_btn.pack(side="right", padx=(0, 4))
    i18n.register(cancel_btn, "BtnCancel")

    # dev#1277: 保存はするがダイアログは閉じない(on_okとの違いは全OFF警告
    # 判定+保存までを共有しつつdlg.destroy()を呼ばない点のみ)。押した瞬間に
    # ctx.trigger_preview()(=main_window._on_preview_only、既存の二重起動
    # ガード・vrm未指定ガード込み)を呼ぶ(DESIGN.md 2.2節)。
    def on_preview_update() -> None:
        chosen = {name for name, var in check_vars.items() if var.get()}  # 残す側
        if full_names and not chosen:
            messagebox.showwarning(
                i18n.S("LabMeshDeleteDialogTitle"),
                i18n.S("LabMeshDeleteAllOffWarning"))
            return
        to_delete = full_names - chosen
        save_deleted_names(ctx.app_root, ctx.avatar_path, sorted(to_delete))
        ctx.append_log(
            f"[lab][mesh_delete] selection saved for preview: "
            f"{len(to_delete)} of {len(full_names)} mesh(es) marked for deletion")
        if ctx.trigger_preview:
            ctx.trigger_preview()

    preview_btn = tk.Button(btn_frame2, text=i18n.S("BtnPreviewUpdate"),
                             command=on_preview_update)
    preview_btn.pack(side="left")
    i18n.register(preview_btn, "BtnPreviewUpdate")

    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    return dlg


# ---------------------------------------------------------------------------
# dev#1186 ラボ機能レジストリ記述子(lab_window.py側が結線する。
# id / i18n名称キー / 状態サマリ関数 / ダイアログを開く関数 / リセット関数)。
# 本WPではlab_window.pyを変更しない(モジュールdocstring参照)。
# ---------------------------------------------------------------------------

LAB_REGISTRY_DESCRIPTOR = {
    "id": LAB_FEATURE_ID,
    "name_key": "LabFeatureMeshDelete",
    "state_summary": state_summary,
    "open_dialog": show_mesh_delete_dialog,
    "reset": reset,
}
