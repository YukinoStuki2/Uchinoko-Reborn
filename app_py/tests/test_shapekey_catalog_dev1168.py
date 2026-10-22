# test_shapekey_catalog_dev1168.py -- dev#1168(シェイプキー)ラボ機能。
#
# app_py\shapekey_catalog.py の単体試験(tkinter非依存)。
#
# VRM側は実VRM検体を必須にしない(CLAUDE.md「構造だけの最小検体を自分で
# 作る、その人のアバターは要らない」): 自前で構造だけの最小GLBコンテナ
# (glTF 2.0 JSONチャンクのみ、BINチャンク無し)を組み立てて検証する。
# 実VRM検体(test\vrm\、gitignore対象・本worktreeには存在しない)が
# たまたま存在する環境向けに、存在すれば追加で走らせる補助テストも用意する。
from __future__ import annotations

import json
import os
import struct
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pytest  # noqa: E402

import shapekey_catalog as sc  # noqa: E402

REPO_ROOT = os.path.dirname(_APP_PY_DIR)


def _build_glb(doc: dict) -> bytes:
    """glTF JSONチャンクのみ(BINチャンク無し)の最小GLBバイト列を組み立てる。"""
    payload = json.dumps(doc).encode("utf-8")
    pad = (4 - len(payload) % 4) % 4
    payload += b" " * pad  # glTF仕様: JSONチャンクは空白でパディング
    header = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(payload))
    chunk_header = struct.pack("<I4s", len(payload), b"JSON")
    return header + chunk_header + payload


def _write_glb(path, doc: dict) -> None:
    with open(path, "wb") as f:
        f.write(_build_glb(doc))


# ---------------------------------------------------------------------------
# catalog_from_vrm(): 合成GLB
# ---------------------------------------------------------------------------

def test_mesh_with_target_names_extracted(tmp_path):
    doc = {
        "meshes": [
            {
                "name": "head",
                "extras": {"targetNames": ["blink_L", "blink_R", "smile"]},
                "primitives": [
                    {"attributes": {}, "targets": [
                        {"POSITION": 1}, {"POSITION": 2}, {"POSITION": 3}]},
                ],
            },
            {
                "name": "hair",
                "primitives": [{"attributes": {}}],  # ブレンドシェイプ無し
            },
        ],
        "nodes": [
            {"name": "head", "mesh": 0},
            {"name": "hair", "mesh": 1},
        ],
    }
    path = tmp_path / "synthetic.vrm"
    _write_glb(str(path), doc)

    result = sc.catalog_from_vrm(str(path))

    assert result["ok"] is True
    assert result["meshes"] == {"head": ["blink_L", "blink_R", "smile"]}
    assert "hair" not in result["meshes"], "ブレンドシェイプの無いメッシュは含めない"


def test_node_name_used_instead_of_mesh_name_when_they_differ(tmp_path):
    """死因の直接再現+修正確認(dev#1285、オーナー報告): 実VRM
    (AliciaSolid_vrm-0.51.vrm)ではnode名"face"に対しmesh名が"face.baked"と
    いう別名になっており、Blender importerはObject.nameをnode名にする。
    キーはnode名でなければならない(mesh名を返すと
    pipeline\\blender\\step01_import_vrm.py の drop_shape_keys() が
    orig_names(=node名)で逆引きできず、常に不一致で焼き込みが発火しない)。"""
    doc = {
        "meshes": [
            {
                "name": "face.baked",
                "extras": {"targetNames": ["mouth_a"]},
                "primitives": [{"attributes": {}, "targets": [{"POSITION": 1}]}],
            },
        ],
        "nodes": [
            {"name": "face", "mesh": 0},
        ],
    }
    path = tmp_path / "node_mesh_name_mismatch.vrm"
    _write_glb(str(path), doc)

    result = sc.catalog_from_vrm(str(path))

    assert result["ok"] is True
    assert result["meshes"] == {"face": ["mouth_a"]}, (
        "node名'face'ではなくmesh名'face.baked'を返している"
        "(dev#1285の死因そのもの)")


def test_missing_target_names_falls_back_to_index_display(tmp_path):
    """WP指示書item3の明示仕様: targetNames欠落時はインデックス表示。"""
    doc = {
        "meshes": [
            {
                "name": "body",
                "primitives": [
                    {"attributes": {}, "targets": [{"POSITION": 1}, {"POSITION": 2}]},
                ],
            },
        ],
        "nodes": [{"name": "body", "mesh": 0}],
    }
    path = tmp_path / "no_names.vrm"
    _write_glb(str(path), doc)

    result = sc.catalog_from_vrm(str(path))

    assert result["ok"] is True
    assert result["meshes"] == {"body": ["target_0", "target_1"]}


def test_node_without_name_falls_back_to_mesh_name_or_generated_name(tmp_path):
    doc = {
        "meshes": [
            {
                "extras": {"targetNames": ["a"]},
                "primitives": [{"attributes": {}, "targets": [{"POSITION": 1}]}],
            },
        ],
        "nodes": [{"mesh": 0}],  # node名もmesh名も無い(glTF仕様上は許容)
    }
    path = tmp_path / "no_names_at_all.vrm"
    _write_glb(str(path), doc)

    result = sc.catalog_from_vrm(str(path))
    assert result["meshes"] == {"node_0": ["a"]}


def test_multiple_primitives_use_max_target_count(tmp_path):
    doc = {
        "meshes": [
            {
                "name": "outfit",
                "extras": {"targetNames": ["x", "y"]},
                "primitives": [
                    {"attributes": {}, "targets": [{"POSITION": 1}]},
                    {"attributes": {}, "targets": [{"POSITION": 1}, {"POSITION": 2}]},
                ],
            },
        ],
        "nodes": [{"name": "outfit", "mesh": 0}],
    }
    path = tmp_path / "multi_prim.vrm"
    _write_glb(str(path), doc)

    result = sc.catalog_from_vrm(str(path))
    assert result["meshes"] == {"outfit": ["x", "y"]}


def test_no_meshes_key_returns_empty_but_ok(tmp_path):
    path = tmp_path / "empty.vrm"
    _write_glb(str(path), {"asset": {"version": "2.0"}})
    result = sc.catalog_from_vrm(str(path))
    assert result["ok"] is True
    assert result["meshes"] == {}


def test_mesh_with_no_referencing_node_is_excluded(tmp_path):
    """負の対照: nodesから参照されていないmeshは(たとえブレンドシェイプを
    持っていても)カタログに出ない——実VRMでは必ずnodeがmeshを参照するため、
    これは構造上到達しないはずの状態を安全側に倒すことの確認。"""
    doc = {
        "meshes": [
            {
                "name": "orphan",
                "extras": {"targetNames": ["a"]},
                "primitives": [{"attributes": {}, "targets": [{"POSITION": 1}]}],
            },
        ],
        "nodes": [],
    }
    path = tmp_path / "orphan_mesh.vrm"
    _write_glb(str(path), doc)

    result = sc.catalog_from_vrm(str(path))
    assert result["ok"] is True
    assert result["meshes"] == {}


# --- 負の対照: 壊れた/非対応入力でも例外を投げず ok=False へ落ちる ---------

def test_nonexistent_file_falls_back(tmp_path):
    result = sc.catalog_from_vrm(str(tmp_path / "does_not_exist.vrm"))
    assert result["ok"] is False
    assert result["meshes"] == {}


def test_non_glb_file_falls_back(tmp_path):
    path = tmp_path / "not_a_glb.vrm"
    path.write_bytes(b"this is not a glb file at all, just plain text padding")
    result = sc.catalog_from_vrm(str(path))
    assert result["ok"] is False
    assert "not a GLB container" in result["detail"]


def test_truncated_glb_falls_back(tmp_path):
    path = tmp_path / "truncated.vrm"
    full = _build_glb({"meshes": []})
    path.write_bytes(full[:16])  # ヘッダのみ、チャンク本体を切り詰める
    result = sc.catalog_from_vrm(str(path))
    assert result["ok"] is False


def test_bin_chunk_first_is_rejected_gracefully(tmp_path):
    """負の対照: 先頭チャンクがJSON以外(BIN等)の異常なGLBでも例外にならない。"""
    header = struct.pack("<4sII", b"glTF", 2, 12 + 8 + 4)
    chunk_header = struct.pack("<I4s", 4, b"BIN\x00")
    path = tmp_path / "bin_first.vrm"
    path.write_bytes(header + chunk_header + b"\x00\x00\x00\x00")
    result = sc.catalog_from_vrm(str(path))
    assert result["ok"] is False
    assert "not JSON" in result["detail"]


# ---------------------------------------------------------------------------
# catalog_from_sidecar(): Unityエクスポータが書くshape_keys.json相当
# ---------------------------------------------------------------------------

def test_sidecar_catalog_reads_meshes(tmp_path):
    sidecar = tmp_path / "shape_keys.json"
    sidecar.write_text(json.dumps({
        "format": "divetopalworld-shapekeys-1",
        "fbx": "avatar.fbx",
        "meshes": {"Body": ["smile", "blink"], "Empty": []},
    }), encoding="utf-8")

    result = sc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    assert result["meshes"] == {"Body": ["smile", "blink"]}
    assert "Empty" not in result["meshes"], "空配列のメッシュは含めない"


def test_sidecar_missing_file_falls_back(tmp_path):
    result = sc.catalog_from_sidecar(str(tmp_path / "does_not_exist.json"))
    assert result["ok"] is False
    assert result["meshes"] == {}


def test_sidecar_empty_path_falls_back():
    result = sc.catalog_from_sidecar("")
    assert result["ok"] is False


def test_sidecar_corrupt_json_falls_back(tmp_path):
    sidecar = tmp_path / "shape_keys.json"
    sidecar.write_text("{ this is not valid json", encoding="utf-8")
    result = sc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is False


def test_sidecar_missing_meshes_key_falls_back(tmp_path):
    sidecar = tmp_path / "shape_keys.json"
    sidecar.write_text(json.dumps({"format": "x", "fbx": "a.fbx"}), encoding="utf-8")
    result = sc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 補助: 実VRM検体(test\vrm\、gitignore対象)がこの環境にたまたま存在すれば
# 追加で検証する(存在しない=このworktreeでは常時skip)。
# ---------------------------------------------------------------------------

_REAL_VRM_SAMPLE = os.path.join(REPO_ROOT, "test", "vrm", "Seed-san.vrm")


@pytest.mark.skipif(not os.path.isfile(_REAL_VRM_SAMPLE),
                     reason="test\\vrm\\Seed-san.vrm が無い環境(gitignore対象、"
                            "開発機のローカル資産)")
def test_real_vrm_sample_head_mesh_has_named_targets():
    """開発機のローカル資産で実際に確認済みの構造(dev#1168調査時点、
    mesh.extras.targetNames): head メッシュに43個の名前付きブレンドシェイプ
    (eye_close/blink_L/...等)が乗っている。"""
    result = sc.catalog_from_vrm(_REAL_VRM_SAMPLE)
    assert result["ok"] is True
    assert "head" in result["meshes"]
    names = result["meshes"]["head"]
    assert len(names) == 43
    assert "blink_L" in names
    assert "eye_close" in names
    assert all(not n.startswith("target_") for n in names), (
        "実検体には名前が付いているはずなのにインデックス表示にフォールバック"
        "している")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
