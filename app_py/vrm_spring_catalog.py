# vrm_spring_catalog.py -- dev#19「両路線共通の入力基盤」R3部品(dev#1370)。
# 2026-08-16 dev#1508 W1b(揺れもの最終仕様)で拡張: PB側physbones.jsonと
# 完全共通のエントリ形へ揃え、"type"フィールドで区別できるようにした。
# VRM入力(VRM0/VRM1)のspringBoneデータを読み、揺れチェーンの内部表現へ正規化する。
#
# 正本: gh issue view 1370 --repo pandrabox/DiveToPalworld-dev (初版)
#       gh issue view 1508 --repo pandrabox/DiveToPalworld-dev (本拡張)
#   調査: C:\P\Work\DiveToPalworld\work\rd_19_vrm_spring_survey.md
#   設計: C:\P\Work\DiveToPalworld\.devonly\docs\sway\sway_pbunit_design\DESIGN.md §2
#
# 目的: prefab側のPhysBoneサイドカー(dev#1356、app_py\physbone_catalog.py、
# 実データ例: work\rd_1423_sleeve2\conv\flatHaori_export\physbones.json、
# スキーマ={format, physbones:[{anchor, chains:[[...]], params:{...}}]})に
# 相当するVRM側の等価物を作る。取得経路はbone_catalog.py/shapekey_catalog.pyと
# 同じ「glTF/GLBコンテナの先頭JSONチャンク直読み」手法(Blenderのフル起動は
# 不要、pytestで直接検証できる)。
#
# スキーマ(physbone_catalog.pyのentryへ"type"/"pb_object_name"/"source"/
# "params"/"colliders"を追加した上位互換):
#   {"type": "springbone", "anchor": str, "chains": [[str, ...], ...],
#    "pb_object_name": str, "source": "vrm0_spring"|"vrm1_spring",
#    "params": {...正規化済み生値、limit系はnull(SpringBoneに角度制限機構が
#                無いため常に無偏向、SPEC.md §1)...},
#    "colliders": [{...診断用、コピー実装はしない...}, ...]}
# physbone_catalog._parse_entry()はdict.get("anchor")/dict.get("chains")しか
# 読まないため、この形のentryをphysbone_catalog側の検証にそのまま通しても
# 問題なく解釈できる(anchor/chains以外のキーは単に無視される、上位互換)。
# 逆にPB側エントリには"type"フィールドが無い(=暗黙にphysbone)——消費側
# (後続工事の自動アロケータ)は`entry.get("type") == "springbone"`で
# 明示的に区別するか、"type"キー不在をphysbone扱いにすればよい。
#
# 意味論の差(VRM0とVRM1とPhysBoneの3者比較):
#   - PhysBone(prefab): anchor(rootTransform)自身は揺れない。chainsはanchorの
#     子孫のみ(anchor自身の名前を含まない)。1 VRCPhysBoneコンポーネント=
#     1エントリ(複数chains可)。
#   - VRM1(spring_bone1.springs): joints[0]の直前の親ノードが実質的な
#     アンカー(揺れない)で、joints列そのものが1本のチェーン(揺れる)。
#     PhysBoneと同型——anchor=joints[0]の親、chains=[joints列]("root自身"を
#     含まない)。1 spring=1エントリ(PBと同じ粒度)。
#   - VRM0(secondaryAnimation.boneGroups): 仕様上はbones配列の各要素
#     (ルート)自身も揺れる対象。PhysBone/VRM1と揃えるため、本モジュールは
#     「anchor=ルートの親ノード、chains=ルート自身を先頭に含めた子孫パス」
#     という形に正規化する。ルート自身がchains側に含まれる点がVRM1/PhysBone
#     と異なる——"source"フィールドで区別できるようにしてあるので、消費側
#     (割当エンジン、別WP)が意味差を吸収できる。
#     2026-08-16改訂: 旧実装は1boneGroupをルート本数ぶん複数エントリに
#     分解していた(prefab側の「1コンポーネント=1エントリ」と非対称、
#     DESIGN.md §2.2で指摘)。**1boneGroup=1エントリへ再グループ化**する
#     (実データ確認: AliciaSolid_vrm-0.51.vrmの3groupはいずれも単一anchor
#     ——1group内の全rootが同じ親を持つのが通常ケース)。1group内で複数の
#     異なるanchorが混在する縮退ケースは、(group, anchor)単位に分けて
#     複数エントリを許容する(データを黙って落とすより安全側)。
#
# 空グループ(bones空/joints空)は読み飛ばす(VRoid系エクスポータの既知の癖。
# work\rd_19_vrm_spring_survey.md §4参照、C:\UnityP\Flatv3_vrm\flatv3.vrmで実測)。
#
# コライダー(2026-08-16追加): VRM0はboneGroup.colliderGroups(索引)→
# secondaryAnimation.colliderGroups[].{node, colliders:[{offset,radius}]}、
# VRM1はspring.colliderGroups(索引)→VRMC_springBone.colliderGroups[].colliders
# (索引)→VRMC_springBone.colliders[].{node, shape}という2段参照。SPEC.md §2
# 「コライダー放棄が確定」(prefab側と同じ判断)のため、本モジュールもコピー
# 実装はせず診断用に{node名, 生shape/radius}を記録するのみ(消費されない)。
#
# 消費(sway写像への実結線)は本モジュールのスコープ外——搬送・正規化のみ
# (dev#1356 physbone_catalog.pyと同じ立ち位置)。job文脈への搭載は
# app_py\pipeline_runner.py write_job()側(vrm_pathが.vrmの場合のみ、
# 結果が非空ならjob["springbones"]へ)。
from __future__ import annotations

import json
import struct
from typing import Dict, List, Optional

GLB_MAGIC = b"glTF"

FORMAT_ID = "divetopalworld-physbones-1"


def _empty_result(detail: str) -> dict:
    return {"ok": False, "detail": detail, "format": FORMAT_ID, "physbones": []}


def _read_glb_json_chunk(vrm_path: str) -> dict:
    """VRM(GLBコンテナ)の先頭JSON chunkだけを読んでパースする
    (bone_catalog.py/shapekey_catalog.pyと同じ手法の流用、意図的な複製。
    CLAUDE.md「外部依存パスの原則」等と同様、既存の複製流儀にならう)。"""
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


def _node_name(nodes: List[dict], idx) -> Optional[str]:
    if not isinstance(idx, int) or not (0 <= idx < len(nodes)):
        return None
    node = nodes[idx]
    if not isinstance(node, dict):
        return None
    name = node.get("name")
    if not name:
        name = f"node_{idx}"
    return str(name)


def _build_parent_map(nodes: List[dict]) -> Dict[int, int]:
    """glTFのnodes[].childrenから子->親の逆引き表を作る(glTFノード自体には
    親フィールドが無いため)。"""
    parent: Dict[int, int] = {}
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            continue
        for c in (n.get("children") or []):
            if isinstance(c, int):
                parent[c] = i
    return parent


def _walk_descendant_chains(nodes: List[dict], root_idx: int,
                             max_depth: int = 256) -> List[List[str]]:
    """root_idxを先頭に含めた、子孫方向の全リーフパスを列挙する(分岐があれば
    複数チェーンとして全列挙、PhysBoneの複数チェーン列挙と同じ考え方)。
    循環参照(壊れたVRM)に対する安全策としてvisited集合+深さ上限を持つ。"""
    results: List[List[str]] = []

    def rec(idx: int, path: List[int], visited: frozenset):
        if idx in visited or len(path) >= max_depth:
            results.append(path[:])
            return
        visited = visited | {idx}
        path = path + [idx]
        node = nodes[idx] if 0 <= idx < len(nodes) else None
        children = (node.get("children") or []) if isinstance(node, dict) else []
        children = [c for c in children if isinstance(c, int) and 0 <= c < len(nodes)]
        if not children:
            results.append(path)
            return
        for c in children:
            rec(c, path, visited)

    if 0 <= root_idx < len(nodes):
        rec(root_idx, [], frozenset())
    names_chains = []
    for path in results:
        names = [_node_name(nodes, i) for i in path]
        if all(n for n in names):
            names_chains.append(names)
    return names_chains


def _null_limit_params() -> dict:
    """SpringBone(VRM0/VRM1いずれも)は角度制限機構を持たない——SPEC.md §1
    「SpringBoneは角度制限機構が無いので常に無偏向扱い」の裁定どおり、
    PB側と同じキー語彙で明示的にnullを埋める(キー自体を省略すると
    「未確認」と「機構が無いので無い」が区別できなくなるため、正直に埋める)。"""
    return {
        "limit_type": None,
        "max_angle_x": None,
        "max_angle_z": None,
        "limit_rotation": None,
    }


def _resolve_vrm0_colliders(sa: dict, nodes: List[dict],
                             collider_group_indices) -> List[dict]:
    """VRM0: boneGroup.colliderGroups(索引リスト)→
    secondaryAnimation.colliderGroups[].{node, colliders:[{offset,radius}]}を
    解決する。診断用のみ(SPEC.md §2「コライダー放棄が確定」、コピー実装はしない)。
    壊れた索引は個別に読み飛ばす(fail-open、全体を諦めない)。"""
    if not isinstance(collider_group_indices, list):
        return []
    all_groups = sa.get("colliderGroups")
    if not isinstance(all_groups, list):
        return []
    out: List[dict] = []
    for gi in collider_group_indices:
        if not isinstance(gi, int) or not (0 <= gi < len(all_groups)):
            continue
        group = all_groups[gi]
        if not isinstance(group, dict):
            continue
        node_name = _node_name(nodes, group.get("node"))
        for c in (group.get("colliders") or []):
            if not isinstance(c, dict):
                continue
            out.append({
                "node": node_name,
                "offset": c.get("offset"),
                "radius": c.get("radius"),
            })
    return out


def _resolve_vrm1_colliders(sb_ext: dict, nodes: List[dict],
                             collider_group_indices) -> List[dict]:
    """VRM1: spring.colliderGroups(索引リスト)→
    VRMC_springBone.colliderGroups[].colliders(索引リスト)→
    VRMC_springBone.colliders[].{node, shape}の2段参照を解決する。
    診断用のみ(SPEC.md §2「コライダー放棄が確定」)。"""
    if not isinstance(collider_group_indices, list):
        return []
    all_groups = sb_ext.get("colliderGroups")
    all_colliders = sb_ext.get("colliders")
    if not isinstance(all_groups, list) or not isinstance(all_colliders, list):
        return []
    out: List[dict] = []
    for gi in collider_group_indices:
        if not isinstance(gi, int) or not (0 <= gi < len(all_groups)):
            continue
        group = all_groups[gi]
        if not isinstance(group, dict):
            continue
        for ci in (group.get("colliders") or []):
            if not isinstance(ci, int) or not (0 <= ci < len(all_colliders)):
                continue
            collider = all_colliders[ci]
            if not isinstance(collider, dict):
                continue
            out.append({
                "node": _node_name(nodes, collider.get("node")),
                "shape": collider.get("shape"),
            })
    return out


def _parse_vrm0(doc: dict) -> List[dict]:
    """VRM0: extensions.VRM.secondaryAnimation.boneGroups を正規化する。
    1boneGroup=1エントリ(通常は単一anchor、実データで確認済み)。1group内で
    rootのanchor(親骨)が複数種に分かれる縮退ケースは(group, anchor)単位に
    分けて複数エントリにする(データを黙って落とさない)。"""
    nodes = doc.get("nodes") or []
    if not isinstance(nodes, list):
        return []
    vrm_ext = (doc.get("extensions") or {}).get("VRM")
    if not isinstance(vrm_ext, dict):
        return []
    sa = vrm_ext.get("secondaryAnimation")
    if not isinstance(sa, dict):
        return []
    groups = sa.get("boneGroups")
    if not isinstance(groups, list):
        return []
    parent_map = _build_parent_map(nodes)

    entries: List[dict] = []
    for gi, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        bones = group.get("bones")
        if not isinstance(bones, list) or not bones:
            # 空グループ(bones空)は読み飛ばす(VRoid系エクスポータの既知の癖)
            continue

        params = {
            "stiffness": group.get("stiffiness"),  # VRM0仕様の綴りが"stiffiness"
            "gravity_power": group.get("gravityPower"),
            "gravity_dir": group.get("gravityDir"),
            "drag_force": group.get("dragForce"),
            "hit_radius": group.get("hitRadius"),
            **_null_limit_params(),
        }
        colliders = _resolve_vrm0_colliders(sa, nodes, group.get("colliderGroups"))
        display_name = group.get("comment") or f"boneGroup_{gi}"

        # anchorごとにchainsをまとめる(通常は1anchorだけになる)
        chains_by_anchor: Dict[str, List[List[str]]] = {}
        for root_idx in bones:
            if not isinstance(root_idx, int) or not (0 <= root_idx < len(nodes)):
                continue
            parent_idx = parent_map.get(root_idx)
            anchor = _node_name(nodes, parent_idx) if parent_idx is not None else None
            if not anchor:
                # ルートに親が無い(=シーン直下)、または親名が空。表現不能な
                # 縮退ケースのためこの1ルートだけ捨てる(他のルートは継続)。
                continue
            chains = _walk_descendant_chains(nodes, root_idx)
            if not chains:
                continue
            chains_by_anchor.setdefault(anchor, []).extend(chains)

        for anchor, chains in chains_by_anchor.items():
            entries.append({
                "type": "springbone",
                "anchor": anchor,
                "pb_object_name": display_name,
                "chains": chains,
                "source": "vrm0_spring",
                "params": params,
                "colliders": colliders,
            })
    return entries


def _parse_vrm1(doc: dict) -> List[dict]:
    """VRM1: extensions.VRMC_springBone.springs を正規化する。1 spring=
    1エントリ(既にPhysBoneと同じ粒度、変更不要)。"""
    nodes = doc.get("nodes") or []
    if not isinstance(nodes, list):
        return []
    sb_ext = (doc.get("extensions") or {}).get("VRMC_springBone")
    if not isinstance(sb_ext, dict):
        return []
    springs = sb_ext.get("springs")
    if not isinstance(springs, list):
        return []
    parent_map = _build_parent_map(nodes)

    entries: List[dict] = []
    for si, spring in enumerate(springs):
        if not isinstance(spring, dict):
            continue
        joints = spring.get("joints")
        if not isinstance(joints, list) or not joints:
            # 空チェーン(joints空)は読み飛ばす
            continue
        joint_indices = []
        joint_params = []
        for j in joints:
            if not isinstance(j, dict):
                continue
            idx = j.get("node")
            if not isinstance(idx, int) or not (0 <= idx < len(nodes)):
                continue
            joint_indices.append(idx)
            joint_params.append({
                "hit_radius": j.get("hitRadius"),
                "stiffness": j.get("stiffness"),
                "gravity_power": j.get("gravityPower"),
                "gravity_dir": j.get("gravityDir"),
                "drag_force": j.get("dragForce"),
            })
        if not joint_indices:
            continue
        chain_names = [_node_name(nodes, i) for i in joint_indices]
        if not all(chain_names):
            continue
        root_idx = joint_indices[0]
        parent_idx = parent_map.get(root_idx)
        anchor = _node_name(nodes, parent_idx) if parent_idx is not None else None
        if not anchor:
            # 縮退ケース(先頭jointに親が無い)。このspring自体を捨てる。
            continue

        # 先頭jointの生値を代表値としてparamsトップレベルへ持ち上げる(VRM0の
        # group単位params/PB側paramsと語彙を揃えるため)。全joint分の生値は
        # "joints"に保持したまま(精度が要る後続工事のため落とさない)。
        head = joint_params[0]
        params = {
            "stiffness": head.get("stiffness"),
            "gravity_power": head.get("gravity_power"),
            "gravity_dir": head.get("gravity_dir"),
            "drag_force": head.get("drag_force"),
            "hit_radius": head.get("hit_radius"),
            **_null_limit_params(),
            "joints": joint_params,
        }
        colliders = _resolve_vrm1_colliders(sb_ext, nodes, spring.get("colliderGroups"))
        display_name = spring.get("name") or f"spring_{si}"

        entries.append({
            "type": "springbone",
            "anchor": anchor,
            "pb_object_name": display_name,
            "chains": [chain_names],
            "source": "vrm1_spring",
            "params": params,
            "colliders": colliders,
        })
    return entries


def vrm_springbones(vrm_path: str) -> List[dict]:
    """VRMファイルのspringBoneデータ(VRM0/VRM1いずれか、両方あれば両方)を
    正規化したエントリのリストで返す。例外はcatalog_from_vrm()側で捕捉する
    設計のためここでは投げっぱなしにする(bone_catalog.vrm_bone_namesと
    同じ役割分担)。"""
    doc = _read_glb_json_chunk(vrm_path)
    if not isinstance(doc, dict):
        raise ValueError("GLB JSON chunk is not an object")
    entries: List[dict] = []
    entries.extend(_parse_vrm0(doc))
    entries.extend(_parse_vrm1(doc))
    return entries


def catalog_from_vrm(vrm_path: str) -> dict:
    """{"ok": bool, "detail": str, "format": str, "physbones": [...]} を返す
    (例外を投げない、三点セットの③=detailに探索結果を残す)。

    springBoneデータが1つも無い(=通常のVRM、または全グループが空)場合も
    例外ではなくok=Trueで返す(physbone_catalog.catalog_from_sidecarの
    「空リストは正常系」という判断を踏襲——springBone無しのVRMは頻繁にある
    正当な状態であり、故障ではない)。"""
    try:
        entries = vrm_springbones(vrm_path)
    except (OSError, ValueError, struct.error,
            json.JSONDecodeError, AttributeError, TypeError) as e:
        return _empty_result(f"failed to parse VRM container: {type(e).__name__}: {e}")
    return {
        "ok": True,
        "detail": f"parsed glTF JSON chunk directly (no Blender launch): {len(entries)} chain(s)",
        "format": FORMAT_ID,
        "physbones": entries,
    }
