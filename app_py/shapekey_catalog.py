# shapekey_catalog.py -- dev#1168(シェイプキー)ラボ機能の一覧取得(tkinter非依存)。
#
# 正本: gh issue view 1168 --repo pandrabox/DiveToPalworld-dev
#   (2026-08-09 指揮者コメント「シェイプキーWP発進」節)。
#
# 対象範囲: VRMはシェイプキー(ブレンドシェイプ/モーフターゲット)が任意メッシュに
# 載る仕様のため全SkinnedMeshRenderer対象(VRC流の「Bodyだけ」はVRMでは
# 成立しない、指揮者裁定原文)。取得経路は入力形式で2通り:
#   - VRM(0.0/1.0とも実体はglTF 2.0のGLBバイナリコンテナ): Blenderのフル起動は
#     不要——先頭のJSONチャンクを直読みすれば
#     meshes[].primitives[].targets(モーフターゲット数)と
#     meshes[].extras.targetNames(名前配列、事実上の業界慣習であり glTF コア
#     仕様にはキー名フィールドが無い)が取れる(dev#1168調査でSeed-san.vrm実測
#     確認済み: mesh.extras.targetNames、primitive.extrasではなくmesh.extras側)。
#   - prefab(Unityエクスポート経由): unity\DiveToPalworldExporter.csがエクスポート時に
#     書き出すサイドカーJSON(shape_keys.json、material_map.jsonと同じ流儀)を読む。
#
# targetNames欠落時はインデックス表示("target_0"等、WP指示書item3の明示仕様)。
from __future__ import annotations

import json
import os
import struct
from typing import Dict, List

GLB_MAGIC = b"glTF"


def _empty_result(detail: str) -> dict:
    return {"ok": False, "detail": detail, "meshes": {}}


def catalog_from_vrm(vrm_path: str) -> dict:
    """VRM(GLBコンテナ)のJSONチャンクを直読みし、ブレンドシェイプを1つ以上
    持つメッシュだけを {"ok": bool, "detail": str,
    "meshes": {mesh_name: [key_name, ...]}} の形で返す。例外を投げない
    (三点セット: 失敗しても呼び出し側は空カタログとして安全に処理できる)。

    2026-08-09死因修正(dev#1285、オーナー報告「シェイプキー変更してから
    プレビュー更新しても反映されない」): キーはglTFの meshes[].name(例:
    "face.baked")ではなく、そのメッシュを参照する nodes[].name(例:
    "face")を使う。VRM Blenderアドオンはインポート時にBlenderの
    Object.nameをnode名にする(mesh名ではない。UniVRM 0.x書き出しでは
    mesh名に".baked"サフィックスが付き両者が一致しない実例をAliciaSolid
    検体で確認済み: node名"face" / mesh名"face.baked")。
    pipeline\\blender\\step01_import_vrm.py の drop_shape_keys() は
    cleanup_objects() が返す orig_names(=インポート直後のObject.name、
    すなわちnode名)でjob["shape_keys"]のキーを逆引きするため、旧実装
    (mesh名を返す)だとcfg.get(orig)が常にNoneになり、スライダー値を
    いくら変更しても焼き込みが一切発火しない(=プレビューが変わらない、
    オーナー報告の死因)。prefab経路(unity\\DiveToPalworldExporter.csの
    ExportShapeKeys()、Renderer.nameを書き出す)は元々node名相当を採用
    しており正しかった——VRM経路だけがこの不一致を持っていた。"""
    try:
        with open(vrm_path, "rb") as f:
            header = f.read(12)
            if len(header) < 12:
                return _empty_result("file too small for a GLB header")
            magic, _version, _length = struct.unpack("<4sII", header)
            if magic != GLB_MAGIC:
                return _empty_result(f"not a GLB container (magic={magic!r})")
            chunk_header = f.read(8)
            if len(chunk_header) < 8:
                return _empty_result("missing first GLB chunk header")
            chunk_len, chunk_type = struct.unpack("<I4s", chunk_header)
            if chunk_type != b"JSON":
                return _empty_result(f"first GLB chunk is not JSON (type={chunk_type!r})")
            data = f.read(chunk_len)
            if len(data) < chunk_len:
                return _empty_result("truncated GLB JSON chunk")
        doc = json.loads(data.decode("utf-8"))
    except (OSError, struct.error, UnicodeDecodeError, json.JSONDecodeError) as e:
        return _empty_result(f"{type(e).__name__}: {e}")

    if not isinstance(doc, dict):
        return _empty_result("GLB JSON chunk is not an object")

    gltf_meshes = doc.get("meshes") or []
    meshes: Dict[str, List[str]] = {}
    for node_idx, node in enumerate(doc.get("nodes") or []):
        if not isinstance(node, dict):
            continue
        mesh_idx = node.get("mesh")
        if not isinstance(mesh_idx, int) or not (0 <= mesh_idx < len(gltf_meshes)):
            continue
        mesh = gltf_meshes[mesh_idx]
        if not isinstance(mesh, dict):
            continue
        names = _extract_target_names(mesh)
        if not names:
            continue
        # node名が無い(glTF仕様上は許容される)場合のみ、Blender importerの
        # 既定フォールバック名に近いmesh名/インデックス表示を使う。通常の
        # VRMエクスポータはnodeへ必ず名前を付けるため、この分岐への到達は
        # 稀(three点セットの安全側フォールバックであり、原因究明の対象では
        # ない)。
        node_name = node.get("name") or mesh.get("name") or f"node_{node_idx}"
        # 2026-08-09: 同名node(=同名Blender Object)が複数ある場合は先勝ち
        # (material_map.json ExportMaterials()の「seenNames」流儀に合わせる、
        # 後続は無視)。
        meshes.setdefault(str(node_name), names)
    return {"ok": True, "detail": "ok", "meshes": meshes}


def _extract_target_names(mesh: dict) -> List[str]:
    """1メッシュぶんのモーフターゲット名一覧を返す(無ければ空リスト)。"""
    prims = mesh.get("primitives") or []
    n_targets = 0
    for p in prims:
        if isinstance(p, dict) and isinstance(p.get("targets"), list):
            n_targets = max(n_targets, len(p["targets"]))
    if n_targets == 0:
        return []

    names = None
    extras = mesh.get("extras")
    if isinstance(extras, dict) and isinstance(extras.get("targetNames"), list):
        names = extras["targetNames"]
    else:
        # 一部エクスポータはprimitive.extras.targetNamesへ置く(mesh.extras優先、
        # 無ければこちらへフォールバック)。
        for p in prims:
            if not isinstance(p, dict):
                continue
            pextras = p.get("extras")
            if isinstance(pextras, dict) and isinstance(pextras.get("targetNames"), list):
                names = pextras["targetNames"]
                break

    if names and len(names) >= n_targets:
        return [str(n) for n in names[:n_targets]]
    # targetNames欠落時はインデックス表示(WP指示書item3の明示仕様)。
    return [f"target_{i}" for i in range(n_targets)]


def catalog_from_sidecar(sidecar_path: str) -> dict:
    """prefab経路: Unityエクスポート時に書き出されたshape_keys.jsonを読む。
    {"ok": bool, "detail": str, "meshes": {mesh_name: [key_name, ...]}}。
    サイドカー自体が無い(=本WPより前にエクスポートされた古いキャッシュ)場合も
    例外を投げず ok=False で返す(呼び出し側=ダイアログが「再エクスポートして
    ください」相当の案内を出す想定)。"""
    if not sidecar_path or not os.path.isfile(sidecar_path):
        return _empty_result(f"sidecar not found: {sidecar_path}")
    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return _empty_result(f"{type(e).__name__}: {e}")
    if not isinstance(data, dict):
        return _empty_result("sidecar is not a JSON object")
    meshes = data.get("meshes")
    if not isinstance(meshes, dict):
        return _empty_result("sidecar has no 'meshes' object")
    out: Dict[str, List[str]] = {}
    for mesh_name, keys in meshes.items():
        if isinstance(keys, list) and keys:
            out[str(mesh_name)] = [str(k) for k in keys]
    return {"ok": True, "detail": "ok", "meshes": out}
