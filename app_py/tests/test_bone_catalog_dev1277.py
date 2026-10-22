# test_bone_catalog_dev1277.py -- dev#1277(ボーンでメッシュ削除の選択式化)
# ラボ機能。
#
# app_py\bone_catalog.py の単体試験(tkinter非依存)。
#
# VRM側は実VRM検体を必須にしない(CLAUDE.md「構造だけの最小検体を自分で
# 作る、その人のアバターは要らない」): test_shapekey_catalog_dev1168.pyと
# 同じ手法で、自前で構造だけの最小GLBコンテナ(glTF 2.0 JSONチャンクのみ)を
# 組み立てて検証する。実VRM検体(test\vrm\、gitignore対象・本worktreeには
# 存在しない可能性がある)がたまたま存在する環境向けの補助テストも用意し、
# skins.jointsのnode名がBlenderインポート後のarm.data.bones名と実際に一致
# するという実測結果(bone_catalog.pyモジュールdocstring参照)の記録も兼ねる。
from __future__ import annotations

import json
import os
import struct
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pytest  # noqa: E402

import bone_catalog as bc  # noqa: E402

REPO_ROOT = os.path.dirname(_APP_PY_DIR)


def _build_glb(doc: dict) -> bytes:
    payload = json.dumps(doc).encode("utf-8")
    pad = (4 - len(payload) % 4) % 4
    payload += b" " * pad
    header = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(payload))
    chunk_header = struct.pack("<I4s", len(payload), b"JSON")
    return header + chunk_header + payload


def _write_glb(path, doc: dict) -> None:
    with open(path, "wb") as f:
        f.write(_build_glb(doc))


# ---------------------------------------------------------------------------
# catalog_from_vrm(): 合成GLB
# ---------------------------------------------------------------------------

def test_skin_joints_extracted_in_order(tmp_path):
    doc = {
        "nodes": [
            {"name": "Hips"},
            {"name": "Spine"},
            {"name": "Head"},
            {"name": "not_a_bone_decoration"},  # skinsから参照されない
        ],
        "skins": [
            {"joints": [0, 1, 2]},
        ],
    }
    path = tmp_path / "synthetic.vrm"
    _write_glb(str(path), doc)

    result = bc.catalog_from_vrm(str(path))

    assert result["ok"] is True
    assert result["bones"] == ["Hips", "Spine", "Head"]
    assert "not_a_bone_decoration" not in result["bones"], (
        "skinsから参照されていないnodeはボーンカタログに含めない")


def test_multiple_skins_are_merged_deduplicated(tmp_path):
    doc = {
        "nodes": [
            {"name": "Hips"},
            {"name": "Tail1"},
            {"name": "Tail2"},
        ],
        "skins": [
            {"joints": [0, 1]},
            {"joints": [0, 2]},  # Hips重複、Tail2は別スキン
        ],
    }
    path = tmp_path / "multi_skin.vrm"
    _write_glb(str(path), doc)

    result = bc.catalog_from_vrm(str(path))
    assert result["ok"] is True
    assert result["bones"] == ["Hips", "Tail1", "Tail2"]


def test_node_without_name_falls_back_to_generated_name(tmp_path):
    doc = {
        "nodes": [{}],  # 名前無し(glTF仕様上は許容)
        "skins": [{"joints": [0]}],
    }
    path = tmp_path / "no_name.vrm"
    _write_glb(str(path), doc)

    result = bc.catalog_from_vrm(str(path))
    assert result["bones"] == ["node_0"]


def test_no_skins_key_returns_ok_false_empty(tmp_path):
    path = tmp_path / "no_skins.vrm"
    _write_glb(str(path), {"asset": {"version": "2.0"}, "nodes": [{"name": "Hips"}]})
    result = bc.catalog_from_vrm(str(path))
    assert result["ok"] is False
    assert result["bones"] == []


def test_out_of_range_joint_index_is_ignored(tmp_path):
    """負の対照: skins.jointsが不正なindex(範囲外)を含んでいても例外にならない。"""
    doc = {
        "nodes": [{"name": "Hips"}],
        "skins": [{"joints": [0, 99]}],
    }
    path = tmp_path / "bad_index.vrm"
    _write_glb(str(path), doc)
    result = bc.catalog_from_vrm(str(path))
    assert result["ok"] is True
    assert result["bones"] == ["Hips"]


# --- 負の対照: 壊れた/非対応入力でも例外を投げず ok=False へ落ちる ---------

def test_nonexistent_file_falls_back(tmp_path):
    result = bc.catalog_from_vrm(str(tmp_path / "does_not_exist.vrm"))
    assert result["ok"] is False
    assert result["bones"] == []


def test_non_glb_file_falls_back(tmp_path):
    path = tmp_path / "not_a_glb.vrm"
    path.write_bytes(b"this is not a glb file at all, just plain text padding")
    result = bc.catalog_from_vrm(str(path))
    assert result["ok"] is False
    assert "not a glTF/VRM binary container" in result["detail"]


def test_truncated_glb_falls_back(tmp_path):
    path = tmp_path / "truncated.vrm"
    full = _build_glb({"nodes": []})
    path.write_bytes(full[:16])
    result = bc.catalog_from_vrm(str(path))
    assert result["ok"] is False


def test_bin_chunk_first_is_rejected_gracefully(tmp_path):
    header = struct.pack("<4sII", b"glTF", 2, 12 + 8 + 4)
    chunk_header = struct.pack("<I4s", 4, b"BIN\x00")
    path = tmp_path / "bin_first.vrm"
    path.write_bytes(header + chunk_header + b"\x00\x00\x00\x00")
    result = bc.catalog_from_vrm(str(path))
    assert result["ok"] is False
    assert "not JSON" in result["detail"]


# ---------------------------------------------------------------------------
# catalog_from_sidecar(): Unityエクスポータが書くbones.json相当
# ---------------------------------------------------------------------------

def test_sidecar_catalog_reads_bones(tmp_path):
    sidecar = tmp_path / "bones.json"
    sidecar.write_text(json.dumps({
        "format": "divetopalworld-bones-1",
        "fbx": "avatar.fbx",
        "bones": ["Hips", "Spine", "Head"],
    }), encoding="utf-8")

    result = bc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    assert result["bones"] == ["Hips", "Spine", "Head"]


def test_sidecar_missing_file_falls_back(tmp_path):
    result = bc.catalog_from_sidecar(str(tmp_path / "does_not_exist.json"))
    assert result["ok"] is False
    assert result["bones"] == []


def test_sidecar_empty_path_falls_back():
    result = bc.catalog_from_sidecar("")
    assert result["ok"] is False


def test_sidecar_corrupt_json_falls_back(tmp_path):
    sidecar = tmp_path / "bones.json"
    sidecar.write_text("{ this is not valid json", encoding="utf-8")
    result = bc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is False


def test_sidecar_missing_bones_key_falls_back(tmp_path):
    sidecar = tmp_path / "bones.json"
    sidecar.write_text(json.dumps({"format": "x", "fbx": "a.fbx"}), encoding="utf-8")
    result = bc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is False


def test_sidecar_empty_bones_list_falls_back(tmp_path):
    sidecar = tmp_path / "bones.json"
    sidecar.write_text(json.dumps({"bones": []}), encoding="utf-8")
    result = bc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 実測検証(2026-08-09、本WP受入条件): 実VRM検体で、glTF skins.jointsの
# node名一覧が、Blenderへインポートした後のarm.data.bones名と実際に一致
# するかどうか(DESIGN.md 3.1節の「未検証リスク」)。ここではBlenderを
# 起動せず(重い)、既に手元で1回だけ実行して確定させた実測結果を固定する
# ――「未検証リスク」が解消済みであることをこのテストファイルの存在自体が
# 記録する(実測ログはPROGRESS.md参照、bone_catalog.pyモジュールdocstring
# にも要約を転記済み)。存在すれば追加で走らせる補助テスト(実測時と同じ
# 2検体、gitignore対象のためこの環境に無ければ常時skip)。
# ---------------------------------------------------------------------------

_VRM0_SAMPLE = os.path.join(REPO_ROOT, "test", "vrm", "AliciaSolid_vrm-0.51.vrm")
_VRM1_SAMPLE = os.path.join(REPO_ROOT, "test", "vrm", "collected", "AliciaSolid_vrm-1.00.vrm")


@pytest.mark.skipif(not os.path.isfile(_VRM0_SAMPLE),
                     reason="test\\vrm\\AliciaSolid_vrm-0.51.vrm が無い環境"
                            "(gitignore対象、開発機のローカル資産)")
def test_real_vrm0_sample_yields_128_joint_names():
    """実測(2026-08-09、本WP、Blender 4.3.2+同梱VRMアドオンでの突き合わせ):
    AliciaSolid_vrm-0.51.vrmはskins.jointsに128件のjoint名を持ち、これら全て
    がBlenderインポート後のarm.data.bones名と完全一致した(改名なし。差分は
    アドオンが追加する合成ルートボーン"Root"のみ、skins.jointsには含まれず
    実害無し)。"""
    result = bc.catalog_from_vrm(_VRM0_SAMPLE)
    assert result["ok"] is True
    assert len(result["bones"]) == 128
    assert "Hips" in result["bones"]
    assert "Head" in result["bones"]
    assert "Root" not in result["bones"], (
        "Rootはskins.jointsに含まれない合成ボーン(Blenderが追加する側)であり"
        "glTF側のカタログには出ないはず")


@pytest.mark.skipif(not os.path.isfile(_VRM1_SAMPLE),
                     reason="test\\vrm\\collected\\AliciaSolid_vrm-1.00.vrm が無い環境"
                            "(gitignore対象、開発機のローカル資産)")
def test_real_vrm1_sample_yields_128_joint_names():
    result = bc.catalog_from_vrm(_VRM1_SAMPLE)
    assert result["ok"] is True
    assert len(result["bones"]) == 128
    assert "Hips" in result["bones"]
    assert "Head" in result["bones"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
