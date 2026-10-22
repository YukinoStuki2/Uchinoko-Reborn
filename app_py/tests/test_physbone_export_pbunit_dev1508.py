# -*- coding: utf-8 -*-
r"""dev#1508 W1a受入試験: physbones.jsonのPB単位拡張スキーマを固定する。

正本: .devonly\docs\sway\sway_wrapup\SPEC.md §5 / .devonly\docs\sway\sway_pbunit_design\DESIGN.md §1。
対象: unity\DiveToPalworldExporter.cs ExtractPhysBoneChains()の拡張(dev#1356/
dev#19のベース実装に、PBオブジェクト自身の識別情報とVRCPhysBoneColliderの
全列挙を追加する変更)。既存 test_physbone_catalog_dev1356.py /
test_physbone_params_export_dev19.py と同じ理由(C#側はUnityエディタ拡張のため
単体テストのインフラが無い)で、本ファイルが「C#が書くはずの拡張JSON出力形式」を
Python側でスキーマ検証として固定する。

追加されたキー(dev#1356/dev#19の既存11 paramsキーに追加、DESIGN.md §1.2):
  - 各physbonesエントリ: "anchor_explicit_root" / "pb_object_name" /
    "pb_object_path"
  - params: "integration_type" / "ignore_transforms" / "endpoint_position" /
    "multi_child_type" / "colliders"(参照キーのリスト、コピーではない——
    SPEC.md §2「コライダー放棄確定」)
  - ドキュメント直下に新設: "colliders"(トップレベル、シーン全体の
    VRCPhysBoneColliderを別セクションで全列挙。SPEC.md §5)

このWPでも「パイプライン側の消費はしない」(dev#19 pb_param_export briefと同じ
スコープ限定): app_py\physbone_catalog.py(既存の搬送のみパーサ)には手を
入れない——新キーは黙って無視される。本ファイルの
test_existing_catalog_reader_still_ignores_new_fields_unchanged がその事実を
固定する(既存test_physbone_catalog_dev1356.pyが無改修で緑のまま=無退行の証拠)。

実行: python -m pytest app_py\tests\test_physbone_export_pbunit_dev1508.py -v
"""
from __future__ import annotations

import json
import os
import sys

HERE_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_PY_DIR = os.path.dirname(HERE_DIR)
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import physbone_catalog as pc  # noqa: E402


# =====================================================================
# スキーマ契約(dev#1508 W1aで拡張された形)
# =====================================================================

ENTRY_TOP_KEYS = {"anchor", "anchor_explicit_root", "pb_object_name", "pb_object_path", "chains", "params"}

PARAM_KEYS_V2 = {
    "pull", "spring", "stiffness", "gravity", "gravity_falloff",
    "immobile", "immobile_type", "limit_type",
    "max_angle_x", "max_angle_z", "limit_rotation", "radius",
    "integration_type", "ignore_transforms", "endpoint_position",
    "multi_child_type", "colliders",
}

COLLIDER_ENTRY_KEYS = {
    "key", "name", "path", "anchor", "anchor_explicit_root",
    "shape_type", "radius", "height", "position", "rotation",
}

VALID_LIMIT_TYPES = {"None", "Angle", "Hinge", "Polar"}
VALID_IMMOBILE_TYPES = {"AllMotion", "World"}
VALID_INTEGRATION_TYPES = {"Simplified", "Advanced"}
VALID_MULTI_CHILD_TYPES = {"Ignore", "First", "Average"}
VALID_SHAPE_TYPES = {"Sphere", "Capsule", "Plane"}


def _validate_entry_schema(entry) -> tuple[bool, str]:
    if not isinstance(entry, dict):
        return False, "entry is not an object"
    keys = set(entry.keys())
    if keys != ENTRY_TOP_KEYS:
        missing = ENTRY_TOP_KEYS - keys
        extra = keys - ENTRY_TOP_KEYS
        return False, f"entry key set mismatch: missing={missing} extra={extra}"
    if not isinstance(entry["anchor"], str) or not entry["anchor"]:
        return False, "anchor must be a non-empty string"
    if not isinstance(entry["anchor_explicit_root"], bool):
        return False, "anchor_explicit_root must be a bool"
    if not isinstance(entry["pb_object_name"], str):
        return False, "pb_object_name must be a string"
    if not isinstance(entry["pb_object_path"], str):
        return False, "pb_object_path must be a string"
    if not isinstance(entry["chains"], list):
        return False, "chains must be a list"
    return _validate_params_schema(entry["params"])


def _validate_params_schema(params) -> tuple[bool, str]:
    if not isinstance(params, dict):
        return False, "params is not an object"
    keys = set(params.keys())
    if keys != PARAM_KEYS_V2:
        missing = PARAM_KEYS_V2 - keys
        extra = keys - PARAM_KEYS_V2
        return False, f"params key set mismatch: missing={missing} extra={extra}"

    numeric_keys = {"pull", "spring", "stiffness", "gravity", "gravity_falloff",
                     "immobile", "max_angle_x", "max_angle_z", "radius"}
    for k in numeric_keys:
        v = params[k]
        if v is not None and not isinstance(v, (int, float)):
            return False, f"{k} must be number or null, got {type(v).__name__}"

    lt = params["limit_type"]
    if lt is not None and lt not in VALID_LIMIT_TYPES:
        return False, f"limit_type has unexpected value: {lt!r}"
    it = params["immobile_type"]
    if it is not None and it not in VALID_IMMOBILE_TYPES:
        return False, f"immobile_type has unexpected value: {it!r}"
    intg = params["integration_type"]
    if intg is not None and intg not in VALID_INTEGRATION_TYPES:
        return False, f"integration_type has unexpected value: {intg!r}"
    mct = params["multi_child_type"]
    if mct is not None and mct not in VALID_MULTI_CHILD_TYPES:
        return False, f"multi_child_type has unexpected value: {mct!r}"

    lr = params["limit_rotation"]
    if lr is not None:
        if not isinstance(lr, list) or len(lr) != 3:
            return False, "limit_rotation must be null or a 3-element list"
        if not all(isinstance(x, (int, float)) for x in lr):
            return False, "limit_rotation elements must all be numbers"

    ep = params["endpoint_position"]
    if ep is not None:
        if not isinstance(ep, list) or len(ep) != 3:
            return False, "endpoint_position must be null or a 3-element list"
        if not all(isinstance(x, (int, float)) for x in ep):
            return False, "endpoint_position elements must all be numbers"

    it_list = params["ignore_transforms"]
    if not isinstance(it_list, list) or not all(isinstance(x, str) for x in it_list):
        return False, "ignore_transforms must be a list of strings (possibly empty)"

    coll_list = params["colliders"]
    if not isinstance(coll_list, list) or not all(isinstance(x, str) for x in coll_list):
        return False, "colliders must be a list of strings (possibly empty)"

    return True, "ok"


def _validate_collider_entry_schema(entry) -> tuple[bool, str]:
    if not isinstance(entry, dict):
        return False, "collider entry is not an object"
    keys = set(entry.keys())
    if keys != COLLIDER_ENTRY_KEYS:
        missing = COLLIDER_ENTRY_KEYS - keys
        extra = keys - COLLIDER_ENTRY_KEYS
        return False, f"collider entry key set mismatch: missing={missing} extra={extra}"
    if not isinstance(entry["key"], str) or not entry["key"]:
        return False, "key must be a non-empty string"
    if not isinstance(entry["anchor_explicit_root"], bool):
        return False, "anchor_explicit_root must be a bool"
    st = entry["shape_type"]
    if st is not None and st not in VALID_SHAPE_TYPES:
        return False, f"shape_type has unexpected value: {st!r}"
    rot = entry["rotation"]
    if rot is not None:
        if not isinstance(rot, list) or len(rot) != 4:
            return False, "rotation must be null or a 4-element list (quaternion x,y,z,w)"
    pos = entry["position"]
    if pos is not None:
        if not isinstance(pos, list) or len(pos) != 3:
            return False, "position must be null or a 3-element list"
    return True, "ok"


def _sample_params(**overrides) -> dict:
    base = {
        "pull": 0.348, "spring": 0.49, "stiffness": 0.2,
        "gravity": 0.0, "gravity_falloff": 0.0,
        "immobile": 0.335, "immobile_type": "AllMotion",
        "limit_type": "None", "max_angle_x": 45.0, "max_angle_z": 45.0,
        "limit_rotation": [0.0, 0.0, 0.0], "radius": 0.0005,
        "integration_type": "Simplified", "ignore_transforms": [],
        "endpoint_position": None, "multi_child_type": "Ignore",
        "colliders": [],
    }
    base.update(overrides)
    return base


def _sample_doc(entries, colliders=None) -> dict:
    return {
        "format": "divetopalworld-physbones-1",
        "physbones": entries,
        "colliders": colliders or [],
    }


# =====================================================================
# 正の対照: 受入検体comodoの耳PB相当(anchor Head_L.001, limitType None,
#   pull 0.348 / spring 0.49)——SPEC.md §5b「comodoの耳が既定で揺れる」検査の
#   前提となる、Unityが書くはずのエントリ形をそのまま固定する
# =====================================================================

def test_comodo_ear_like_entry_is_valid():
    entry = {
        "anchor": "Head_L.001",
        "anchor_explicit_root": False,
        "pb_object_name": "Head_L.001",
        "pb_object_path": "Armature/Hips/Spine/Chest/Neck/Head/Head_L.001",
        "chains": [["Head_L.002", "Head_L.003", "Head_L.003_end"]],
        "params": _sample_params(),
    }
    ok, detail = _validate_entry_schema(entry)
    assert ok, detail
    # JSON往復でも構造が保たれること
    doc = _sample_doc([entry])
    round_tripped = json.loads(json.dumps(doc))
    ok2, detail2 = _validate_entry_schema(round_tripped["physbones"][0])
    assert ok2, detail2


def test_full_document_with_colliders_section_is_valid():
    entry = {
        "anchor": "Chest_Necktie",
        "anchor_explicit_root": True,
        "pb_object_name": "Dynamic",
        "pb_object_path": "Armature/Dynamic/Necktie",
        "chains": [["Necktie_01", "Necktie_02"]],
        "params": _sample_params(
            limit_type="Hinge", integration_type="Advanced",
            multi_child_type="Average", ignore_transforms=["Necktie_ignore1"],
            endpoint_position=[0.0, -0.05, 0.0],
            colliders=["Armature/Chest/ChestCollider"],
        ),
    }
    collider = {
        "key": "Armature/Chest/ChestCollider",
        "name": "ChestCollider",
        "path": "Armature/Chest/ChestCollider",
        "anchor": "ChestCollider",
        "anchor_explicit_root": False,
        "shape_type": "Sphere",
        "radius": 0.1,
        "height": 0.0,
        "position": [0.0, 0.0, 0.0],
        "rotation": [0.0, 0.0, 0.0, 1.0],
    }
    doc = _sample_doc([entry], colliders=[collider])
    assert set(doc.keys()) == {"format", "physbones", "colliders"}
    ok, detail = _validate_entry_schema(doc["physbones"][0])
    assert ok, detail
    ok2, detail2 = _validate_collider_entry_schema(doc["colliders"][0])
    assert ok2, detail2


# =====================================================================
# 正の対照: 別Object+rootTransform指しPB(flatapron実例、SPEC.md §5)
#   pb_object_name/pb_object_pathがanchorと異なる値になるケース
# =====================================================================

def test_explicit_root_transform_entry_has_distinct_pb_object_and_anchor():
    entry = {
        "anchor": "apron_bone_root",  # rootTransformで指定された効果対象
        "anchor_explicit_root": True,
        "pb_object_name": "apron",     # PB自身が載っているGameObject名(別物)
        "pb_object_path": "Armature/Dynamic/apron",
        "chains": [["apron_01", "apron_02"]],
        "params": _sample_params(limit_type="Hinge"),
    }
    ok, detail = _validate_entry_schema(entry)
    assert ok, detail
    assert entry["anchor"] != entry["pb_object_name"]
    assert entry["anchor_explicit_root"] is True


# =====================================================================
# 負の対照: エントリのキー集合不一致(欠落・余剰)
# =====================================================================

def test_entry_missing_pb_object_path_is_rejected():
    entry = {
        "anchor": "Tail_Root",
        "anchor_explicit_root": False,
        "pb_object_name": "Tail_Root",
        "chains": [["Tail_01"]],
        "params": _sample_params(),
    }
    ok, detail = _validate_entry_schema(entry)
    assert not ok
    assert "missing" in detail


def test_entry_with_extra_key_is_rejected():
    entry = {
        "anchor": "Tail_Root",
        "anchor_explicit_root": False,
        "pb_object_name": "Tail_Root",
        "pb_object_path": "Armature/Tail_Root",
        "chains": [["Tail_01"]],
        "params": _sample_params(),
        "unexpected_extra_key": 1,
    }
    ok, detail = _validate_entry_schema(entry)
    assert not ok
    assert "extra" in detail


# =====================================================================
# 負の対照: paramsの新キー集合不一致・型不正
# =====================================================================

def test_params_missing_new_keys_is_rejected():
    """旧(dev#19)11キーのみのparamsは、拡張スキーマでは欠落として検出される
    (旧検体互換の判定はUnity輸出のバージョン検出ではなくpy側で明示的に行う設計、
    このテストはその境界を固定する)。"""
    old_params = {
        "pull": 0.2, "spring": 0.2, "stiffness": 0.2,
        "gravity": 0.0, "gravity_falloff": 0.0,
        "immobile": 0.0, "immobile_type": "AllMotion",
        "limit_type": "None", "max_angle_x": 0.0, "max_angle_z": 0.0,
        "limit_rotation": [0.0, 0.0, 0.0], "radius": 0.1,
    }
    ok, detail = _validate_params_schema(old_params)
    assert not ok
    assert "missing" in detail


def test_unknown_integration_type_value_is_rejected():
    params = _sample_params(integration_type="Bogus")
    ok, detail = _validate_params_schema(params)
    assert not ok
    assert "integration_type" in detail


def test_unknown_multi_child_type_value_is_rejected():
    params = _sample_params(multi_child_type="Bogus")
    ok, detail = _validate_params_schema(params)
    assert not ok
    assert "multi_child_type" in detail


def test_ignore_transforms_wrong_type_is_rejected():
    params = _sample_params(ignore_transforms="not-a-list")
    ok, detail = _validate_params_schema(params)
    assert not ok
    assert "ignore_transforms" in detail


def test_colliders_refs_wrong_element_type_is_rejected():
    params = _sample_params(colliders=[123])
    ok, detail = _validate_params_schema(params)
    assert not ok
    assert "colliders" in detail


def test_endpoint_position_malformed_is_rejected():
    params = _sample_params(endpoint_position=[0.0, 0.0])  # 2要素しかない
    ok, detail = _validate_params_schema(params)
    assert not ok
    assert "endpoint_position" in detail


# =====================================================================
# 負の対照: コライダーエントリのキー集合・値不正
# =====================================================================

def test_collider_entry_missing_key_field_is_rejected():
    collider = {
        "name": "ChestCollider", "path": "Armature/Chest/ChestCollider",
        "anchor": "ChestCollider", "anchor_explicit_root": False,
        "shape_type": "Sphere", "radius": 0.1, "height": 0.0,
        "position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0],
    }
    ok, detail = _validate_collider_entry_schema(collider)
    assert not ok
    assert "missing" in detail


def test_collider_unknown_shape_type_is_rejected():
    collider = {
        "key": "k", "name": "n", "path": "p", "anchor": "a",
        "anchor_explicit_root": False, "shape_type": "Cube",
        "radius": 0.1, "height": 0.0, "position": [0, 0, 0],
        "rotation": [0, 0, 0, 1],
    }
    ok, detail = _validate_collider_entry_schema(collider)
    assert not ok
    assert "shape_type" in detail


def test_collider_rotation_malformed_is_rejected():
    collider = {
        "key": "k", "name": "n", "path": "p", "anchor": "a",
        "anchor_explicit_root": False, "shape_type": "Capsule",
        "radius": 0.1, "height": 0.2, "position": [0, 0, 0],
        "rotation": [0, 0, 0],  # 3要素しかない(クォータニオンは4要素)
    }
    ok, detail = _validate_collider_entry_schema(collider)
    assert not ok
    assert "rotation" in detail


# =====================================================================
# 既存の無退行: 既存の搬送のみパーサ(physbone_catalog.py)は拡張フィールドを
#   黙って無視し、{"anchor","chains"}のみの既存挙動を保つこと。
# =====================================================================

def test_existing_catalog_reader_still_ignores_new_fields_unchanged(tmp_path):
    sidecar = tmp_path / "physbones.json"
    entry = {
        "anchor": "Head_L.001",
        "anchor_explicit_root": False,
        "pb_object_name": "Head_L.001",
        "pb_object_path": "Armature/Head/Head_L.001",
        "chains": [["Head_L.002", "Head_L.003"]],
        "params": _sample_params(),
    }
    doc = _sample_doc([entry], colliders=[{
        "key": "k", "name": "n", "path": "p", "anchor": "a",
        "anchor_explicit_root": False, "shape_type": "Sphere",
        "radius": 0.1, "height": 0.0, "position": [0, 0, 0],
        "rotation": [0, 0, 0, 1],
    }])
    sidecar.write_text(json.dumps(doc), encoding="utf-8")

    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    assert result["physbones"] == [
        {"anchor": "Head_L.001", "chains": [["Head_L.002", "Head_L.003"]]},
    ]
