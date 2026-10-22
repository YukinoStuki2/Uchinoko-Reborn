# physbone_catalog.py -- dev#1356(揺れもの、dev#19「両路線共通の入力基盤」)
# Unityエクスポータが書き出すphysbones.jsonサイドカーのスキーマ検証(tkinter非依存)。
#
# 正本: gh issue view 1356 --repo pandrabox/DiveToPalworld-dev
#   設計調査: C:\P\Work\DiveToPalworld\work\rd_19_r1_wall\PROPOSAL.md 「壁(a)Unity側」節。
#
# 本モジュールの役割は搬送のみ(受入条件1): unity\DiveToPalworldExporter.cs
# ExtractPhysBoneChains() が書くphysbones.jsonの構造を、bone_catalog.py/
# shapekey_catalog.pyと同じ「catalog_from_sidecar」流儀で検証・パースする。
# C#側はUnityエディタ拡張のため単体テストのインフラが無く(unity\に既存の
# テストディレクトリ無し)、WP指示書の受入条件1「走査ロジックを検証可能な
# 最小構造に分離し、py側テストでスキーマ検証+アンカー/チェーン構造の正しさを
# 固定(サンプルJSONで)」に従い、C#が書くはずの出力形式をこのモジュールの
# スキーマ検証として固定する。
#
# job文脈への配線(app_py\lu_export.py resolve_prefab_to_fbx()の
# "physbones_json"キー、あれば)は本モジュールを消費しない——搬送のみで、
# 実際にsway写像へ結線するのは別WP(WP指示書「消費は別WP」)。
#
# スキーマ(unity\DiveToPalworldExporter.cs ExtractPhysBoneChains()が書く形):
#   {
#     "format": "divetopalworld-physbones-1",
#     "physbones": [
#       {"anchor": "Chest_Necktie", "chains": [["Necktie_01", "Necktie_02"], ...]},
#       ...
#     ]
#   }
# 意味論(オーナー裁定2026-08-11): "anchor"(搭載/rootTransformボーン)自身は
# 揺れない。"chains"はanchorの子孫のみ(anchor自身の名前を含まない)、複数
# チェーン(マルチルート/分岐)は全列挙される。anchorに子孫が1つも無い
# PhysBoneはエントリごと省略される(C#側の仕様、空チェーンは書かれない)。
from __future__ import annotations

import json
import os
from typing import Dict, List


def _empty_result(detail: str) -> dict:
    return {"ok": False, "detail": detail, "physbones": []}


def _parse_chain(chain) -> List[str]:
    """1チェーン分(ボーン名のリスト)を検証してリストで返す。不正なら空リスト
    (呼び出し元が空チェーンを除外する)。"""
    if not isinstance(chain, list) or not chain:
        return []
    names = []
    for n in chain:
        if not isinstance(n, str) or not n:
            return []  # 1件でも不正な要素があればチェーン全体を捨てる(安全側)
        names.append(n)
    return names


def _parse_entry(entry) -> Dict | None:
    """1PhysBoneエントリ({"anchor": str, "chains": [[str,...],...]})を検証して
    正規化した辞書を返す。不正ならNone(呼び出し元がエントリごと捨てる)。"""
    if not isinstance(entry, dict):
        return None
    anchor = entry.get("anchor")
    if not isinstance(anchor, str) or not anchor:
        return None
    raw_chains = entry.get("chains")
    if not isinstance(raw_chains, list):
        return None
    chains = []
    for chain in raw_chains:
        parsed = _parse_chain(chain)
        if parsed:
            chains.append(parsed)
    return {"anchor": anchor, "chains": chains}


def catalog_from_sidecar(sidecar_path: str) -> dict:
    """prefab経路: Unityエクスポート時に書き出されたphysbones.jsonを読む。
    {"ok": bool, "detail": str, "physbones": [{"anchor": str, "chains": [[str,...],...]}, ...]}。

    サイドカー自体が無い(=本WPより前にエクスポートされた古いキャッシュ、または
    VRM入力経路でUnity輸出そのものが行われていない)場合も例外を投げずok=Falseで
    返す(bone_catalog.py/shapekey_catalog.pyと同じ安全側フォールバック)。

    "physbones": [] は正常系(PhysBoneが1つも無いアバター、またはVRC SDK未導入
    プロジェクトでの輸出)であり、C#側は常にphysbones.json自体は書き出すため、
    サイドカーが存在してphysbonesが空リストならok=Trueで返す(サイドカー自体が
    無い場合とは区別する——bone_catalog.pyのbonesと異なり、空リストであること
    自体が正当な状態のため、空リストを理由にok=Falseへ縮退させない)。"""
    if not sidecar_path or not os.path.isfile(sidecar_path):
        return _empty_result(f"sidecar not found: {sidecar_path}")
    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return _empty_result(f"{type(e).__name__}: {e}")
    if not isinstance(data, dict):
        return _empty_result("sidecar is not a JSON object")
    raw_entries = data.get("physbones")
    if not isinstance(raw_entries, list):
        return _empty_result("sidecar has no 'physbones' list")
    entries = []
    for raw in raw_entries:
        parsed = _parse_entry(raw)
        if parsed is not None:
            entries.append(parsed)
    return {"ok": True, "detail": f"read {sidecar_path}", "physbones": entries}
