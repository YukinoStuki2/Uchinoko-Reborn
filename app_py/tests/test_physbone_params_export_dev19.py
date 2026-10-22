# -*- coding: utf-8 -*-
r"""dev#19(揺れもの)pb_param_export WP受入試験。

正本: C:\P\Work\DiveToPalworld\work\rd_19_flight\briefs\pb_param_export.md

対象: unity\DiveToPalworldExporter.cs ExtractPhysBoneChains()の拡張(PhysBoneの
数値・角度制限パラメータをphysbones.jsonの各エントリへ"params"として追加する変更)。
C#側はUnityエディタ拡張のため単体テストのインフラが無く(既存
test_physbone_catalog_dev1356.pyの前例どおり)、本ファイルが
「C#が書くはずのJSON出力形式」をPython側でスキーマ検証として固定する。

このWPでは「値を捨てず伝える」パイプライン側消費は行わない(brief §3:
「パイプライン側の消費はしない。JSONに載せるまで」)。したがって
app_py\physbone_catalog.py(既存の"搬送のみ"パーサ、{"anchor","chains"}のみを
読む)には手を入れない——"params"キーは黙って無視される(json辞書に余分な
キーがあっても既存の_parse_entry()は素通しで無視する)。これにより既存の
test_physbone_catalog_dev1356.py全件が無改修で無退行のまま緑を維持する
(本ファイルのtest_existing_catalog_reader_still_ignores_params_unchangedで
その事実そのものを固定する)。

実行: python -m pytest app_py\tests\test_physbone_params_export_dev19.py -v
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
# physbones.json "params" オブジェクトのスキーマ契約
#   (unity\DiveToPalworldExporter.cs PhysBoneParamsJson()が書くキー集合)
# =====================================================================

REQUIRED_PARAM_KEYS = {
    "pull", "spring", "stiffness", "gravity", "gravity_falloff",
    "immobile", "immobile_type", "limit_type",
    "max_angle_x", "max_angle_z", "limit_rotation", "radius",
}

VALID_LIMIT_TYPES = {"None", "Angle", "Hinge", "Polar"}
VALID_IMMOBILE_TYPES = {"AllMotion", "World"}

# 数値(float または null)のキー
_NUMERIC_KEYS = {"pull", "spring", "stiffness", "gravity", "gravity_falloff",
                  "immobile", "max_angle_x", "max_angle_z", "radius"}


def _validate_params_schema(params) -> tuple[bool, str]:
    """1エントリの"params"オブジェクトを検証する。(ok, detail)を返す。
    dev#19裁定「読めない値はnullで正直に」の検証: 各値はnullも許容する。"""
    if not isinstance(params, dict):
        return False, "params is not an object"
    keys = set(params.keys())
    if keys != REQUIRED_PARAM_KEYS:
        missing = REQUIRED_PARAM_KEYS - keys
        extra = keys - REQUIRED_PARAM_KEYS
        return False, f"key set mismatch: missing={missing} extra={extra}"

    for k in _NUMERIC_KEYS:
        v = params[k]
        if v is not None and not isinstance(v, (int, float)):
            return False, f"{k} must be number or null, got {type(v).__name__}"

    lt = params["limit_type"]
    if lt is not None and lt not in VALID_LIMIT_TYPES:
        return False, f"limit_type has unexpected value: {lt!r}"

    it = params["immobile_type"]
    if it is not None and it not in VALID_IMMOBILE_TYPES:
        return False, f"immobile_type has unexpected value: {it!r}"

    lr = params["limit_rotation"]
    if lr is not None:
        if not isinstance(lr, list) or len(lr) != 3:
            return False, "limit_rotation must be null or a 3-element list"
        if not all(isinstance(x, (int, float)) for x in lr):
            return False, "limit_rotation elements must all be numbers"

    return True, "ok"


def _sample_physbones_doc(entry_params) -> dict:
    """C#が書くphysbones.jsonの1エントリを模したドキュメントをその場で組み立てる
    (実Unity輸出を経由しない、スキーマ固定のためのゴールデンサンプル)。"""
    return {
        "format": "divetopalworld-physbones-1",
        "physbones": [
            {
                "anchor": "Chest_Furisode",
                "chains": [["Sode_01", "Sode_02", "Sode_03"]],
                "params": entry_params,
            },
        ],
    }


# =====================================================================
# 正の対照: 全パラメータが読めている(ふりそで=Angle細かい、想定)
# =====================================================================

def test_full_params_angle_limit_valid():
    full_params = {
        "pull": 0.2, "spring": 0.25, "stiffness": 0.15,
        "gravity": 0.0, "gravity_falloff": 0.0,
        "immobile": 0.0, "immobile_type": "AllMotion",
        "limit_type": "Angle", "max_angle_x": 30.0, "max_angle_z": 15.0,
        "limit_rotation": [0.0, 0.0, 0.0], "radius": 0.05,
    }
    doc = _sample_physbones_doc(full_params)
    ok, detail = _validate_params_schema(doc["physbones"][0]["params"])
    assert ok, detail
    # JSON往復でも構造が保たれること
    round_tripped = json.loads(json.dumps(doc))
    ok2, detail2 = _validate_params_schema(round_tripped["physbones"][0]["params"])
    assert ok2, detail2


# =====================================================================
# 正の対照: Hinge制限(羽織り、想定)+ 一部フィールドがnull(読めなかった想定)
# =====================================================================

def test_hinge_limit_with_some_nulls_is_valid():
    """dev#19裁定「存在しない/読めない値はnullで正直に」: nullは正当な値であり、
    スキーマ違反ではない。"""
    params = {
        "pull": 0.3, "spring": None, "stiffness": 0.4,
        "gravity": 0.5, "gravity_falloff": None,
        "immobile": None, "immobile_type": None,
        "limit_type": "Hinge", "max_angle_x": 60.0, "max_angle_z": None,
        "limit_rotation": None, "radius": None,
    }
    doc = _sample_physbones_doc(params)
    ok, detail = _validate_params_schema(doc["physbones"][0]["params"])
    assert ok, detail


# =====================================================================
# 正の対照: limitType=None(角度制限なしのPhysBone)
# =====================================================================

def test_limit_type_none_is_valid():
    params = {
        "pull": 0.2, "spring": 0.2, "stiffness": 0.2,
        "gravity": 0.0, "gravity_falloff": 0.0,
        "immobile": 0.0, "immobile_type": "World",
        "limit_type": "None", "max_angle_x": 0.0, "max_angle_z": 0.0,
        "limit_rotation": [0.0, 0.0, 0.0], "radius": 0.1,
    }
    ok, detail = _validate_params_schema(params)
    assert ok, detail


# =====================================================================
# 負の対照: 全フィールドが読めなかった(SDK非対応バージョン等)想定でも
#   キー自体は必ず揃っている(値がnullでもキー省略はしない)
# =====================================================================

def test_all_null_params_is_valid_but_key_omission_is_not():
    all_null = {k: None for k in REQUIRED_PARAM_KEYS}
    ok, detail = _validate_params_schema(all_null)
    assert ok, detail

    missing_one = dict(all_null)
    del missing_one["limit_type"]
    ok2, detail2 = _validate_params_schema(missing_one)
    assert not ok2, "キー欠落は検出されるべき"
    assert "missing" in detail2


# =====================================================================
# 負の対照: brief原文の想定語「damping」はVRCPhysBoneBaseに実在しない
#   (C:\UnityP\test22のVRC.Dynamics.dllをメタデータ読み取りで確認済み、
#   本WP notes_pbparams.md参照)。誤って追加された場合はスキーマ不一致として
#   検出されること(このWPの解釈=「damping相当はgravity/gravity_falloff/
#   springで代替、専用キーは出さない」の固定)。
# =====================================================================

def test_damping_key_is_not_part_of_schema():
    with_damping = {k: None for k in REQUIRED_PARAM_KEYS}
    with_damping["damping"] = None
    ok, detail = _validate_params_schema(with_damping)
    assert not ok
    assert "extra" in detail


# =====================================================================
# 負の対照: limit_type/immobile_typeに未知の値
# =====================================================================

def test_unknown_limit_type_value_is_rejected():
    params = {k: None for k in REQUIRED_PARAM_KEYS}
    params["limit_type"] = "Bogus"
    ok, detail = _validate_params_schema(params)
    assert not ok
    assert "limit_type" in detail


def test_unknown_immobile_type_value_is_rejected():
    params = {k: None for k in REQUIRED_PARAM_KEYS}
    params["immobile_type"] = "Bogus"
    ok, detail = _validate_params_schema(params)
    assert not ok
    assert "immobile_type" in detail


# =====================================================================
# 負の対照: limit_rotationが3要素でない
# =====================================================================

def test_malformed_limit_rotation_is_rejected():
    params = {k: None for k in REQUIRED_PARAM_KEYS}
    params["limit_rotation"] = [0.0, 0.0]  # 2要素しかない
    ok, detail = _validate_params_schema(params)
    assert not ok
    assert "limit_rotation" in detail


# =====================================================================
# 負の対照: 数値キーに文字列が入っている(型不正)
# =====================================================================

def test_wrong_type_numeric_field_is_rejected():
    params = {k: None for k in REQUIRED_PARAM_KEYS}
    params["pull"] = "not-a-number"
    ok, detail = _validate_params_schema(params)
    assert not ok
    assert "pull" in detail


# =====================================================================
# 既存の無退行: 既存の搬送のみパーサ(physbone_catalog.py)はparamsを
#   黙って無視し、{"anchor","chains"}のみの既存挙動を保つこと。
#   (本WPは「パイプライン側の消費はしない」brief制約の直接的な検証:
#   physbone_catalog.pyへの変更ゼロで、既存test_physbone_catalog_dev1356.py
#   が引き続き無改修で緑のまま=無退行の証拠)
# =====================================================================

def test_existing_catalog_reader_still_ignores_params_unchanged(tmp_path):
    sidecar = tmp_path / "physbones.json"
    doc = _sample_physbones_doc({
        "pull": 0.2, "spring": 0.2, "stiffness": 0.2,
        "gravity": 0.0, "gravity_falloff": 0.0,
        "immobile": 0.0, "immobile_type": "AllMotion",
        "limit_type": "Angle", "max_angle_x": 30.0, "max_angle_z": 15.0,
        "limit_rotation": [0.0, 0.0, 0.0], "radius": 0.05,
    })
    sidecar.write_text(json.dumps(doc), encoding="utf-8")

    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    # 既存の搬送スキーマ通り、"params"は結果に現れない(anchor/chainsのみ)
    assert result["physbones"] == [
        {"anchor": "Chest_Furisode", "chains": [["Sode_01", "Sode_02", "Sode_03"]]},
    ]
