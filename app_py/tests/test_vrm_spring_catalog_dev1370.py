# test_vrm_spring_catalog_dev1370.py -- dev#19/dev#1370(揺れもの、L1)
# app_py\vrm_spring_catalog.py の単体試験(tkinter非依存、Blender非依存)。
# 2026-08-16 dev#1508 W1bで拡張: "type"/"pb_object_name"/正規化params/
# "colliders"フィールドの追加、VRM0の1boneGroup=1エントリ再グループ化を反映。
#
# 正本: gh issue view 1370 --repo pandrabox/DiveToPalworld-dev (初版)
#       gh issue view 1508 --repo pandrabox/DiveToPalworld-dev (本拡張)
#   調査: C:\P\Work\DiveToPalworld\work\rd_19_vrm_spring_survey.md
#   設計: C:\P\Work\DiveToPalworld\.devonly\docs\sway\sway_pbunit_design\DESIGN.md §2
#
# 合成GLB(test_bone_catalog_dev1277.pyと同じ手法、CLAUDE.md「構造だけの
# 最小検体を自分で作る」)で構造ロジックを固定し、実VRM検体(gitignore対象、
# 存在すれば追加検証=W1b受入条件のスナップショットテスト)でスナップショットを
# 取る二段構え。
from __future__ import annotations

import json
import os
import struct
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pytest  # noqa: E402

import vrm_spring_catalog as vsc  # noqa: E402
import physbone_catalog as pc  # noqa: E402

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
# VRM0(secondaryAnimation.boneGroups)、合成GLB
# ---------------------------------------------------------------------------

def _vrm0_doc_simple_linear():
    """Head -> hairRoot -> hairTip という単純な直線チェーン1本。"""
    return {
        "nodes": [
            {"name": "Head", "children": [1]},           # 0
            {"name": "hairRoot", "children": [2]},        # 1(ルート)
            {"name": "hairTip"},                          # 2(リーフ)
        ],
        "extensions": {
            "VRM": {
                "secondaryAnimation": {
                    "boneGroups": [
                        {"bones": [1], "stiffiness": 1.5, "dragForce": 0.4,
                         "gravityPower": 0.0, "hitRadius": 0.02},
                    ]
                }
            }
        },
    }


def test_vrm0_single_linear_chain_includes_root(tmp_path):
    path = tmp_path / "vrm0_linear.vrm"
    _write_glb(str(path), _vrm0_doc_simple_linear())

    result = vsc.catalog_from_vrm(str(path))
    assert result["ok"] is True
    assert result["format"] == "divetopalworld-physbones-1"
    assert len(result["physbones"]) == 1
    entry = result["physbones"][0]
    assert entry["type"] == "springbone"
    assert entry["anchor"] == "Head"
    assert entry["source"] == "vrm0_spring"
    # ルート自身(hairRoot)がchains先頭に含まれる(既存仕様どおり、
    # PhysBone/VRM1と異なりVRM0はルート自身も揺れる)
    assert entry["chains"] == [["hairRoot", "hairTip"]]
    # params: VRM0の生キーを正規化した語彙(生値はそのまま透過)
    assert entry["params"]["stiffness"] == 1.5
    assert entry["params"]["drag_force"] == 0.4
    assert entry["params"]["gravity_power"] == 0.0
    assert entry["params"]["hit_radius"] == 0.02
    # SpringBoneは角度制限機構が無いので常に無偏向——limit系はnullで明示
    assert entry["params"]["limit_type"] is None
    assert entry["params"]["max_angle_x"] is None
    assert entry["params"]["max_angle_z"] is None
    assert entry["params"]["limit_rotation"] is None
    # comment未設定なので機械生成の表示名にフォールバック
    assert entry["pb_object_name"] == "boneGroup_0"
    assert entry["colliders"] == []


def test_vrm0_group_comment_becomes_display_name(tmp_path):
    """VRoid等が書くcomment(グループ名)があればpb_object_nameの第一候補になる。"""
    doc = _vrm0_doc_simple_linear()
    doc["extensions"]["VRM"]["secondaryAnimation"]["boneGroups"][0]["comment"] = "FrontHair"
    path = tmp_path / "vrm0_named.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    assert result["physbones"][0]["pb_object_name"] == "FrontHair"


def test_vrm0_branching_subtree_yields_multiple_chains(tmp_path):
    """1ルートの子孫が分岐する場合、リーフごとに複数チェーンとして全列挙される
    (PhysBoneの複数チェーン列挙と同じ考え方)。"""
    doc = {
        "nodes": [
            {"name": "Head", "children": [1]},          # 0
            {"name": "ribbonRoot", "children": [2, 3]},  # 1(ルート、分岐)
            {"name": "ribbonL"},                         # 2
            {"name": "ribbonR"},                          # 3
        ],
        "extensions": {
            "VRM": {"secondaryAnimation": {"boneGroups": [{"bones": [1]}]}}
        },
    }
    path = tmp_path / "vrm0_branch.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    assert result["ok"] is True
    assert len(result["physbones"]) == 1
    entry = result["physbones"][0]
    assert entry["anchor"] == "Head"
    assert sorted(entry["chains"]) == sorted([
        ["ribbonRoot", "ribbonL"],
        ["ribbonRoot", "ribbonR"],
    ])


def test_vrm0_multiple_roots_sharing_anchor_yield_single_entry(tmp_path):
    """2026-08-16改訂(dev#1508 W1b): 1グループに複数bones(ルート)があり、
    全rootが同じ親(anchor)を持つ場合は**1エントリ**に束ねられる
    (prefab側physbones.jsonの「1コンポーネント=1エントリ、複数chains」構造と
    揃える。実測: AliciaSolid_vrm-0.51.vrmの各groupが単一anchorだった
    構造と同じ、旧仕様の「ルートごとに別エントリ」から変更)。"""
    doc = {
        "nodes": [
            {"name": "Head", "children": [1, 2]},
            {"name": "hairA"},  # 1
            {"name": "hairB"},  # 2
        ],
        "extensions": {
            "VRM": {"secondaryAnimation": {"boneGroups": [{"bones": [1, 2]}]}}
        },
    }
    path = tmp_path / "vrm0_multiroot.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    assert len(result["physbones"]) == 1
    entry = result["physbones"][0]
    assert entry["anchor"] == "Head"
    assert sorted(entry["chains"]) == [["hairA"], ["hairB"]]


def test_vrm0_multiple_roots_with_different_anchors_split_by_anchor(tmp_path):
    """縮退ケース: 1グループ内でrootの親(anchor)が複数種に分かれる場合、
    (group, anchor)単位で複数エントリに分ける(データを黙って落とさない、
    多数決で1つへ寄せない——CLAUDE.md「値を寄せて合わせない」)。"""
    doc = {
        "nodes": [
            {"name": "Head", "children": [1]},
            {"name": "hairA"},  # 1(親=Head)
            {"name": "Chest", "children": [3]},
            {"name": "tassel"},  # 3(親=Chest)
        ],
        "extensions": {
            "VRM": {"secondaryAnimation": {"boneGroups": [{"bones": [1, 3]}]}}
        },
    }
    path = tmp_path / "vrm0_split_anchor.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    assert len(result["physbones"]) == 2
    anchors = sorted(e["anchor"] for e in result["physbones"])
    assert anchors == ["Chest", "Head"]
    # 同じグループ由来なのでpb_object_nameは両エントリで同じ(機械生成名)
    assert {e["pb_object_name"] for e in result["physbones"]} == {"boneGroup_0"}


def test_vrm0_empty_bones_group_is_skipped(tmp_path):
    """負の対照: bones=[]の空グループ(VRoid系エクスポータの既知の癖、
    C:\\UnityP\\Flatv3_vrm\\flatv3.vrmで実測)は読み飛ばされる。"""
    doc = {
        "nodes": [{"name": "Head"}],
        "extensions": {
            "VRM": {
                "secondaryAnimation": {
                    "boneGroups": [
                        {"bones": [], "colliderGroups": [], "stiffiness": 1, "dragForce": 0.4},
                    ]
                }
            }
        },
    }
    path = tmp_path / "vrm0_empty_group.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    assert result["ok"] is True
    assert result["physbones"] == []


def test_vrm0_root_without_parent_is_skipped(tmp_path):
    """縮退ケース: ルートに親が無い(シーン直下)場合、anchorを表現できないため
    そのチェーンは捨てる(例外にはしない)。"""
    doc = {
        "nodes": [{"name": "sceneRootBone", "children": [1]}, {"name": "child"}],
        "extensions": {
            "VRM": {"secondaryAnimation": {"boneGroups": [{"bones": [0]}]}}
        },
    }
    path = tmp_path / "vrm0_no_parent.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    assert result["ok"] is True
    assert result["physbones"] == []


def test_vrm0_colliders_are_resolved_diagnostically(tmp_path):
    """VRM0: boneGroup.colliderGroups(索引)→secondaryAnimation.colliderGroups
    を解決し、診断用に{node, offset, radius}を記録する(コピー実装はしない、
    SPEC.md §2「コライダー放棄が確定」)。"""
    doc = {
        "nodes": [
            {"name": "Head", "children": [1]},
            {"name": "hairRoot"},
            {"name": "HeadColliderNode"},
        ],
        "extensions": {
            "VRM": {
                "secondaryAnimation": {
                    "boneGroups": [{"bones": [1], "colliderGroups": [0]}],
                    "colliderGroups": [
                        {"node": 2, "colliders": [{"offset": {"x": 0, "y": 0, "z": 0}, "radius": 0.05}]},
                    ],
                }
            }
        },
    }
    path = tmp_path / "vrm0_collider.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    entry = result["physbones"][0]
    assert entry["colliders"] == [
        {"node": "HeadColliderNode", "offset": {"x": 0, "y": 0, "z": 0}, "radius": 0.05},
    ]


# ---------------------------------------------------------------------------
# VRM1(VRMC_springBone.springs)、合成GLB
# ---------------------------------------------------------------------------

def test_vrm1_single_spring_chain_excludes_anchor(tmp_path):
    doc = {
        "nodes": [
            {"name": "hair_A", "children": [1]},      # 0(親=アンカー)
            {"name": "hair_A.001", "children": [2]},   # 1(joints[0])
            {"name": "hair_A_end"},                    # 2(joints[1])
        ],
        "extensions": {
            "VRMC_springBone": {
                "springs": [
                    {
                        "name": "FrontHairA",
                        "joints": [
                            {"node": 1, "stiffness": 1.0, "dragForce": 0.5},
                            {"node": 2, "stiffness": 1.0, "dragForce": 0.5},
                        ],
                    }
                ]
            }
        },
    }
    path = tmp_path / "vrm1_single.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    assert result["ok"] is True
    assert len(result["physbones"]) == 1
    entry = result["physbones"][0]
    assert entry["type"] == "springbone"
    assert entry["anchor"] == "hair_A"
    assert entry["source"] == "vrm1_spring"
    # VRM1はPhysBoneと同型: chainsはjoints列そのもの(アンカー自身を含まない)
    assert entry["chains"] == [["hair_A.001", "hair_A_end"]]
    assert entry["pb_object_name"] == "FrontHairA"
    # 先頭jointの生値が代表値としてparamsトップレベルへ持ち上がる
    assert entry["params"]["stiffness"] == 1.0
    assert entry["params"]["drag_force"] == 0.5
    assert entry["params"]["limit_type"] is None
    # 全joint分の生値はjointsに保持される(精度が要る後続工事のため)
    assert len(entry["params"]["joints"]) == 2
    assert entry["colliders"] == []


def test_vrm1_spring_without_name_falls_back_to_machine_name(tmp_path):
    doc = {
        "nodes": [{"name": "root", "children": [1]}, {"name": "tip"}],
        "extensions": {
            "VRMC_springBone": {"springs": [{"joints": [{"node": 1}]}]}
        },
    }
    path = tmp_path / "vrm1_noname.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    assert result["physbones"][0]["pb_object_name"] == "spring_0"


def test_vrm1_empty_joints_spring_is_skipped(tmp_path):
    doc = {
        "nodes": [{"name": "root"}],
        "extensions": {"VRMC_springBone": {"springs": [{"name": "Empty", "joints": []}]}},
    }
    path = tmp_path / "vrm1_empty.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    assert result["ok"] is True
    assert result["physbones"] == []


def test_vrm1_multiple_springs_yield_multiple_entries(tmp_path):
    doc = {
        "nodes": [
            {"name": "bagpack", "children": [1]},
            {"name": "robo_wire", "children": [2]},
            {"name": "robo_wire_end"},
            {"name": "hair_root", "children": [4]},
            {"name": "hair_tip"},
        ],
        "extensions": {
            "VRMC_springBone": {
                "springs": [
                    {"name": "RoboWire", "joints": [{"node": 1}, {"node": 2}]},
                    {"name": "Hair", "joints": [{"node": 4}]},
                ]
            }
        },
    }
    path = tmp_path / "vrm1_multi.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    assert len(result["physbones"]) == 2
    sources = {e["source"] for e in result["physbones"]}
    assert sources == {"vrm1_spring"}


def test_vrm1_colliders_are_resolved_diagnostically(tmp_path):
    """VRM1: spring.colliderGroups(索引)→VRMC_springBone.colliderGroups.colliders
    (索引)→VRMC_springBone.colliders[].{node,shape}の2段参照を解決する。"""
    doc = {
        "nodes": [
            {"name": "hair_A", "children": [1]},
            {"name": "hair_A.001"},
            {"name": "HeadColliderNode"},
        ],
        "extensions": {
            "VRMC_springBone": {
                "springs": [{"name": "Hair", "joints": [{"node": 1}], "colliderGroups": [0]}],
                "colliderGroups": [{"colliders": [0]}],
                "colliders": [{"node": 2, "shape": {"sphere": {"radius": 0.05}}}],
            }
        },
    }
    path = tmp_path / "vrm1_collider.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    entry = result["physbones"][0]
    assert entry["colliders"] == [
        {"node": "HeadColliderNode", "shape": {"sphere": {"radius": 0.05}}},
    ]


# ---------------------------------------------------------------------------
# 既定不変: springBoneデータ自体が無いVRM
# ---------------------------------------------------------------------------

def test_no_spring_extensions_returns_ok_true_empty(tmp_path):
    """負の対照: springBone拡張が一切無いVRM(大半のVRMはこちら)でも例外に
    ならず、ok=True・空リストで返る(physbone_catalogの「空は正常系」判断を
    踏襲、故障ではない)。"""
    path = tmp_path / "no_spring.vrm"
    _write_glb(str(path), {"nodes": [{"name": "Hips"}]})

    result = vsc.catalog_from_vrm(str(path))
    assert result["ok"] is True
    assert result["physbones"] == []


def test_vrm0_and_vrm1_extensions_both_present_are_both_parsed(tmp_path):
    doc = {
        "nodes": [
            {"name": "Head", "children": [1]},
            {"name": "hairRoot"},
            {"name": "chest", "children": [3]},
            {"name": "wire.001"},
        ],
        "extensions": {
            "VRM": {"secondaryAnimation": {"boneGroups": [{"bones": [1]}]}},
            "VRMC_springBone": {"springs": [{"name": "Wire", "joints": [{"node": 3}]}]},
        },
    }
    path = tmp_path / "both.vrm"
    _write_glb(str(path), doc)

    result = vsc.catalog_from_vrm(str(path))
    assert len(result["physbones"]) == 2
    sources = sorted(e["source"] for e in result["physbones"])
    assert sources == ["vrm0_spring", "vrm1_spring"]
    assert all(e["type"] == "springbone" for e in result["physbones"])


# --- 負の対照: 壊れた/非対応入力でも例外を投げずok=Falseへ落ちる -----------

def test_nonexistent_file_falls_back(tmp_path):
    result = vsc.catalog_from_vrm(str(tmp_path / "does_not_exist.vrm"))
    assert result["ok"] is False
    assert result["physbones"] == []


def test_non_glb_file_falls_back(tmp_path):
    path = tmp_path / "not_a_glb.vrm"
    path.write_bytes(b"this is not a glb file at all, just plain text padding")
    result = vsc.catalog_from_vrm(str(path))
    assert result["ok"] is False
    assert "not a glTF/VRM binary container" in result["detail"]


def test_truncated_glb_falls_back(tmp_path):
    path = tmp_path / "truncated.vrm"
    full = _build_glb({"nodes": []})
    path.write_bytes(full[:16])
    result = vsc.catalog_from_vrm(str(path))
    assert result["ok"] is False


def test_out_of_range_joint_index_is_ignored(tmp_path):
    doc = {
        "nodes": [{"name": "anchor", "children": [1]}, {"name": "root"}],
        "extensions": {
            "VRMC_springBone": {
                "springs": [{"name": "Bad", "joints": [{"node": 1}, {"node": 99}]}]
            }
        },
    }
    path = tmp_path / "bad_index.vrm"
    _write_glb(str(path), doc)
    result = vsc.catalog_from_vrm(str(path))
    assert result["ok"] is True
    assert len(result["physbones"]) == 1
    assert result["physbones"][0]["chains"] == [["root"]]


# ---------------------------------------------------------------------------
# physbone_catalog.py(prefab側スキーマ検証)との上位互換確認
# ---------------------------------------------------------------------------

def test_entries_pass_physbone_catalog_entry_shape():
    """vrm_spring_catalogのentry(anchor/chains/type/pb_object_name/source/
    params/colliders)は、physbone_catalog._parse_entry()が読むanchor/chains
    のみに依存する検証をそのまま通せる形になっている(上位互換、モジュール
    docstring参照)。"""
    entry = {"type": "springbone", "anchor": "Head", "chains": [["a", "b"]],
              "pb_object_name": "FrontHair", "source": "vrm0_spring",
              "params": {"stiffness": 1.0}, "colliders": []}
    parsed = pc._parse_entry(entry)
    assert parsed == {"anchor": "Head", "chains": [["a", "b"]]}


# ---------------------------------------------------------------------------
# 実測検証: 実VRM検体(gitignore対象、開発機のローカル資産。無ければskip)
# W1b受入条件のスナップショットテスト(SPEC.md §5「受入: Seed-san.vrm/
# AliciaSolid_vrm-0.51.vrmで実パースし、揺れ骨グループが妥当に出ること」)。
# ---------------------------------------------------------------------------

_VRM0_ALICIA = os.path.join(REPO_ROOT, "test", "vrm", "AliciaSolid_vrm-0.51.vrm")
_VRM1_SEEDSAN = os.path.join(REPO_ROOT, "test", "vrm", "Seed-san.vrm")
_VRM0_FLATV3_EMPTY = r"C:\UnityP\Flatv3_vrm\flatv3.vrm"


@pytest.mark.skipif(not os.path.isfile(_VRM0_ALICIA),
                     reason="test\\vrm\\AliciaSolid_vrm-0.51.vrm が無い環境"
                            "(gitignore対象、開発機のローカル資産)")
def test_real_vrm0_alicia_yields_3_grouped_entries():
    """実測(scratchpad/inspect_vrm.py、2026-08-16 W1b): AliciaSolid_vrm-0.51.vrm
    はboneGroups=3件(髪2グループ+スカート1グループ)、各グループは単一anchor
    (Head×2, Hips×1)——1boneGroup=1エントリへの再グループ化後は**3エントリ**
    (旧仕様=ルート単位18エントリから変更、DESIGN.md §2.2)。総chain数(揺れ骨の
    ルート本数)は18のまま変わらない(髪5+3本、スカート10本)。"""
    result = vsc.catalog_from_vrm(_VRM0_ALICIA)
    assert result["ok"] is True
    assert len(result["physbones"]) == 3
    assert all(e["type"] == "springbone" for e in result["physbones"])
    assert all(e["source"] == "vrm0_spring" for e in result["physbones"])
    anchors = sorted(e["anchor"] for e in result["physbones"])
    assert anchors == ["Head", "Head", "Hips"]
    total_chains = sum(len(e["chains"]) for e in result["physbones"])
    assert total_chains == 18
    skirt_entry = next(e for e in result["physbones"] if e["anchor"] == "Hips")
    assert len(skirt_entry["chains"]) == 10
    assert sorted(c[0] for c in skirt_entry["chains"])[0] == "skirt_01_01"
    # limit系は常にnull(SpringBoneは角度制限機構が無いので常に無偏向)
    assert all(e["params"]["limit_type"] is None for e in result["physbones"])


@pytest.mark.skipif(not os.path.isfile(_VRM1_SEEDSAN),
                     reason="test\\vrm\\Seed-san.vrm が無い環境"
                            "(gitignore対象、開発機のローカル資産)")
def test_real_vrm1_seedsan_yields_9_entries():
    """実測: Seed-san.vrmはspringBone1.0 springs=9件(尻尾髪・前髪7本・
    ロボワイヤー)。VRM1は元々1spring=1エントリなので件数は不変。"""
    result = vsc.catalog_from_vrm(_VRM1_SEEDSAN)
    assert result["ok"] is True
    assert len(result["physbones"]) == 9
    assert all(e["type"] == "springbone" for e in result["physbones"])
    assert all(e["source"] == "vrm1_spring" for e in result["physbones"])
    names = {e["pb_object_name"] for e in result["physbones"]}
    assert "TailHair" in names
    assert "RoboWire" in names
    tail = next(e for e in result["physbones"] if e["pb_object_name"] == "TailHair")
    assert tail["chains"] == [[
        "hair_tail_1", "hair_tail_2", "hair_tail_3",
        "hair_tail_4", "hair_tail_5", "hair_tail_6", "hair_tail_end",
    ]]
    assert tail["params"]["limit_type"] is None
    assert all(e["params"]["limit_type"] is None for e in result["physbones"])


@pytest.mark.skipif(not os.path.isfile(_VRM0_FLATV3_EMPTY),
                     reason="C:\\UnityP\\Flatv3_vrm\\flatv3.vrm が無い環境"
                            "(開発機のローカル資産、オーナー指定検体)")
def test_real_vrm0_flatv3_empty_group_yields_zero_chains():
    """実測(work\\rd_19_vrm_spring_survey.md §4): flatv3.vrmはboneGroups=1件
    だがbones=[]の完全な空エントリ(VRoid系エクスポータの既知の癖)。負の対照:
    空グループは読み飛ばされ0チェーンになる。"""
    result = vsc.catalog_from_vrm(_VRM0_FLATV3_EMPTY)
    assert result["ok"] is True
    assert result["physbones"] == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
