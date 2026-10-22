# -*- coding: utf-8 -*-
r"""dev#1356受入試験: app_py\physbone_catalog.py の単体テスト。

正本: gh issue view 1356 --repo pandrabox/DiveToPalworld-dev
WP指示書の受入条件1「C#側の単体化が難しければ、走査ロジックを検証可能な最小構造に
分離し、py側テストでphysbones.jsonのスキーマ検証+アンカー/チェーン構造の正しさを
サンプルJSONで固定する」に対応する。C#側(unity\DiveToPalworldExporter.cs
ExtractPhysBoneChains())にはUnityエディタ拡張のため単体テストのインフラが無く、
このファイルがphysbones.jsonのスキーマ契約を固定する唯一のテストになる。

実行: python -m pytest app_py\tests\test_physbone_catalog_dev1356.py -v
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
# 正の対照: 単一PhysBone・単一チェーン
# =====================================================================

def test_single_physbone_single_chain(tmp_path):
    sidecar = tmp_path / "physbones.json"
    sidecar.write_text(json.dumps({
        "format": "divetopalworld-physbones-1",
        "physbones": [
            {"anchor": "Chest_Necktie", "chains": [["Necktie_01", "Necktie_02", "Necktie_03"]]},
        ],
    }), encoding="utf-8")

    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    assert result["physbones"] == [
        {"anchor": "Chest_Necktie", "chains": [["Necktie_01", "Necktie_02", "Necktie_03"]]},
    ]


# =====================================================================
# 正の対照: マルチチェーン(分岐、複数リーフ)
# =====================================================================

def test_multi_chain_branch(tmp_path):
    """1つのanchorから複数チェーン(分岐)が全列挙されること。"""
    sidecar = tmp_path / "physbones.json"
    sidecar.write_text(json.dumps({
        "format": "divetopalworld-physbones-1",
        "physbones": [
            {
                "anchor": "Hair_Root",
                "chains": [
                    ["Hair_L_01", "Hair_L_02"],
                    ["Hair_R_01", "Hair_R_02", "Hair_R_03"],
                ],
            },
        ],
    }), encoding="utf-8")

    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    assert len(result["physbones"]) == 1
    assert len(result["physbones"][0]["chains"]) == 2
    assert result["physbones"][0]["anchor"] == "Hair_Root"


# =====================================================================
# 正の対照: 複数PhysBone(ネスト・複数エントリ)
# =====================================================================

def test_multiple_physbones(tmp_path):
    sidecar = tmp_path / "physbones.json"
    sidecar.write_text(json.dumps({
        "format": "divetopalworld-physbones-1",
        "physbones": [
            {"anchor": "Tail_Root", "chains": [["Tail_01", "Tail_02"]]},
            {"anchor": "Ear_L", "chains": [["Ear_L_01"]]},
            {"anchor": "Ear_R", "chains": [["Ear_R_01"]]},
        ],
    }), encoding="utf-8")

    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    assert len(result["physbones"]) == 3
    anchors = [p["anchor"] for p in result["physbones"]]
    assert anchors == ["Tail_Root", "Ear_L", "Ear_R"]


# =====================================================================
# 正の対照: PhysBoneが1つも無い(空physbones、VRC SDK未導入時の正常出力)
# =====================================================================

def test_empty_physbones_list_is_ok(tmp_path):
    """空リストはbone_catalog.pyのbonesと異なり正当な状態
    (PhysBone無し、またはVRC SDK未導入プロジェクトでの輸出)——ok=Falseへ
    縮退させない(WP指示書「抽出は無条件でよい」に対応)。"""
    sidecar = tmp_path / "physbones.json"
    sidecar.write_text(json.dumps({
        "format": "divetopalworld-physbones-1",
        "physbones": [],
    }), encoding="utf-8")

    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    assert result["physbones"] == []


# =====================================================================
# 負の対照: サイドカー自体が無い
# =====================================================================

def test_sidecar_missing_file_falls_back(tmp_path):
    result = pc.catalog_from_sidecar(str(tmp_path / "does_not_exist.json"))
    assert result["ok"] is False
    assert result["physbones"] == []


def test_sidecar_empty_path_falls_back():
    result = pc.catalog_from_sidecar("")
    assert result["ok"] is False


def test_sidecar_corrupt_json_falls_back(tmp_path):
    sidecar = tmp_path / "physbones.json"
    sidecar.write_text("{ this is not valid json", encoding="utf-8")
    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is False


def test_sidecar_not_an_object_falls_back(tmp_path):
    sidecar = tmp_path / "physbones.json"
    sidecar.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is False


def test_sidecar_missing_physbones_key_falls_back(tmp_path):
    sidecar = tmp_path / "physbones.json"
    sidecar.write_text(json.dumps({"format": "x"}), encoding="utf-8")
    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is False


# =====================================================================
# 負の対照: 個々のエントリ・チェーンの構造不正(安全側にエントリごと除外)
# =====================================================================

def test_entry_without_anchor_is_dropped(tmp_path):
    sidecar = tmp_path / "physbones.json"
    sidecar.write_text(json.dumps({
        "physbones": [
            {"chains": [["Tail_01"]]},  # anchor欠落
            {"anchor": "Ear_L", "chains": [["Ear_L_01"]]},
        ],
    }), encoding="utf-8")

    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    assert len(result["physbones"]) == 1
    assert result["physbones"][0]["anchor"] == "Ear_L"


def test_entry_with_non_string_anchor_is_dropped(tmp_path):
    sidecar = tmp_path / "physbones.json"
    sidecar.write_text(json.dumps({
        "physbones": [
            {"anchor": 123, "chains": [["Tail_01"]]},
        ],
    }), encoding="utf-8")

    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    assert result["physbones"] == []


def test_entry_with_non_list_chains_is_dropped(tmp_path):
    sidecar = tmp_path / "physbones.json"
    sidecar.write_text(json.dumps({
        "physbones": [
            {"anchor": "Tail_Root", "chains": "not-a-list"},
        ],
    }), encoding="utf-8")

    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    assert result["physbones"] == []


def test_chain_with_non_string_element_is_dropped(tmp_path):
    """チェーン内に不正な要素(数値等)があれば、そのチェーンだけを捨てる
    (他の正しいチェーンは残す)。"""
    sidecar = tmp_path / "physbones.json"
    sidecar.write_text(json.dumps({
        "physbones": [
            {"anchor": "Tail_Root", "chains": [["Tail_01", 42], ["Tail_A", "Tail_B"]]},
        ],
    }), encoding="utf-8")

    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    assert len(result["physbones"]) == 1
    assert result["physbones"][0]["chains"] == [["Tail_A", "Tail_B"]]


def test_empty_chain_is_dropped(tmp_path):
    sidecar = tmp_path / "physbones.json"
    sidecar.write_text(json.dumps({
        "physbones": [
            {"anchor": "Tail_Root", "chains": [[]]},
        ],
    }), encoding="utf-8")

    result = pc.catalog_from_sidecar(str(sidecar))
    assert result["ok"] is True
    assert result["physbones"] == [{"anchor": "Tail_Root", "chains": []}]
