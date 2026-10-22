# bone_catalog.py -- dev#1277(「ボーンでメッシュ削除」の選択式化)ラボ機能の
# ボーン名カタログ取得(tkinter非依存)。
#
# 正本: gh issue view 1277 --repo pandrabox/DiveToPalworld-dev
#   設計調査: C:\P\Work\DiveToPalworld\work\rd_shapekey_preview\DESIGN.md 3節。
#
# 対象名前空間: pipeline\blender\step01_import_vrm.py drop_bone_meshes()が
# 引く `arm.data.bones.get(name)` = Blenderへインポート済みアーマチュアの
# 全ボーン名(人型55種に限らず尻尾・耳・スカート・指等の非Humanoidボーンを含む)。
#
# 取得経路(shapekey_catalog.pyと同じ二分岐):
#   - VRM(.vrm、実体はglTF 2.0のGLBバイナリコンテナ): Blenderのフル起動は
#     不要——先頭JSONチャンクを直読みし、skins[].joints(ノードindex配列)が
#     指す nodes[].name を集約する。
#   - prefab(.prefab): Unityエクスポート時のサイドカーJSON(bones.json、
#     unity\DiveToPalworldExporter.cs ExportBones()が書き出す)を読む。
#
# **実測検証(2026-08-09、本WP)**: DESIGN.md 3.1節が明記した「未検証リスク
# (VRM importアドオンがボーン名をリネームする可能性)」を、Blenderを実際に
# 起動して検証した。手順: test\vrm\AliciaSolid_vrm-0.51.vrm(VRM0)と
# test\vrm\collected\AliciaSolid_vrm-1.00.vrm(VRM1)の2検体について、
# (a) 本モジュールと同じglTF直読み手法でskins[].jointsのnode名一覧を抽出、
# (b) Blender 4.3.2 + 同梱VRMアドオン(third_party\VRM_Addon_for_Blender-
#     Extension-4_4_0.zip、pipeline\blender\vp_bl.pyと同じ
#     `bpy.ops.import_scene.vrm(filepath=...)` 呼び出し。--background実行では
#     `BLENDER_VRM_AUTOMATIC_LICENSE_CONFIRMATION=true` 環境変数が必須——
#     これが無いとライセンス確認が必要なVRM(AliciaSolid含む)は無警告で
#     インポートされずarmatureオブジェクトが0件になる。本番パイプラインは
#     step01_import_vrm.py内で既にこの環境変数をimport_vrm()の直前にセット
#     済みなので本番には影響しない)でVRMをインポートし、
#     `arm.data.bones` の実名一覧をダンプ、を比較した。
# **結果**: 両検体とも128件のjoint名が一切改名されずそのままBlenderの
# ボーン名として現れた(完全一致、大文字小文字・接頭辞付与も無し)。差分は
# VRMアドオンが追加する単一の合成ルートボーン"Root"(skins.jointsには
# 含まれない)のみ——これは実害無し(そのボーンは選択肢に出ないだけで、
# 他の全ボーン名の一致には影響しない)。したがって「未検証リスク」は解消:
# VRM importアドオンはHumanoid/非Humanoidボーン問わずリネームを行わない。
from __future__ import annotations

import json
import os
import struct
from typing import List

GLB_MAGIC = b"glTF"


def _empty_result(detail: str) -> dict:
    return {"ok": False, "detail": detail, "bones": []}


def _read_glb_json_chunk(vrm_path: str) -> dict:
    """VRM(GLBコンテナ)の先頭JSON chunkだけを読んでパースする
    (mesh_delete_dialog.py/shapekey_catalog.pyと同じ手法の流用)。"""
    with open(vrm_path, "rb") as f:
        header = f.read(12)
        if len(header) < 12:
            raise ValueError("file too small to be a GLB/VRM container")
        magic, _version, _length = struct.unpack("<4sII", header)
        if magic != GLB_MAGIC:
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


def vrm_bone_names(vrm_path: str) -> List[str]:
    """VRMファイルのskins[].jointsが指すノード名一覧を返す(重複除去、
    出現順)。モジュールdocstringの実測どおり、Blenderインポート後の
    arm.data.bones名と一致する見込み。"""
    doc = _read_glb_json_chunk(vrm_path)
    if not isinstance(doc, dict):
        raise ValueError("GLB JSON chunk is not an object")
    nodes = doc.get("nodes") or []
    names: List[str] = []
    seen = set()
    for skin in doc.get("skins") or []:
        if not isinstance(skin, dict):
            continue
        joints = skin.get("joints")
        if not isinstance(joints, list):
            continue
        for idx in joints:
            if not isinstance(idx, int) or not (0 <= idx < len(nodes)):
                continue
            node = nodes[idx]
            name = node.get("name") if isinstance(node, dict) else None
            if not name:
                name = f"node_{idx}"
            name = str(name)
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
    return names


def catalog_from_vrm(vrm_path: str) -> dict:
    """{"ok": bool, "detail": str, "bones": [...]} を返す(例外を投げない、
    三点セットの③=detailに探索結果を残す)。"""
    try:
        names = vrm_bone_names(vrm_path)
    except (OSError, ValueError, struct.error,
            json.JSONDecodeError, AttributeError, TypeError) as e:
        return _empty_result(f"failed to parse VRM container: {type(e).__name__}: {e}")
    if not names:
        return _empty_result("no skin joints found in VRM")
    return {"ok": True,
            "detail": "parsed glTF JSON chunk directly (no Blender launch)",
            "bones": names}


def catalog_from_sidecar(sidecar_path: str) -> dict:
    """prefab経路: Unityエクスポート時に書き出されたbones.jsonを読む。
    サイドカー自体が無い(=本WPより前にエクスポートされた古いキャッシュ)場合も
    例外を投げずok=Falseで返す(呼び出し側=ダイアログがカンマ区切り手入力の
    フォールバックへ落とす)。"""
    if not sidecar_path or not os.path.isfile(sidecar_path):
        return _empty_result(f"sidecar not found: {sidecar_path}")
    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return _empty_result(f"{type(e).__name__}: {e}")
    if not isinstance(data, dict):
        return _empty_result("sidecar is not a JSON object")
    bones = data.get("bones")
    if not isinstance(bones, list) or not bones:
        return _empty_result(f"sidecar has no 'bones' list: {sidecar_path}")
    return {"ok": True, "detail": f"read {sidecar_path}",
            "bones": [str(b) for b in bones]}
