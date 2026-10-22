# -*- coding: utf-8 -*-
"""重複armature/同名ボーンの検出(dev#1174)。

背景(実報告4件・issue #1174本文): アバターに「重複した骨格」が混入していると、
輸出/インポート経路のどこかで同じ役割のボーンが2つ存在することになり、
Humanoid必須ボーン(hips/head等)の解決に失敗する。

  * P7ARCMQ7(prefab入力): Unity輸出FBXに `hips_2`/`head_3` 型の連番サフィックス
    付きボーンがあり、humanoid.jsonが期待する素の名前と一致せずFATAL。
  * VKKLD4HA/35TX8ERY(VRM入力): VRMアドオンの
    `[VRM Add-on:WARNING] Duplicated VRM0 bone: "HumanBoneName.HIPS"` 直後に
    Humanoid定義読み込みFATAL。
  * ZEBJLH7L(VRM入力): avatar_meta.jsonのbonesに `Armature`系統と
    `Armature.001`系統の完全なボーン階層が2つ同居。global_scale_and_place()の
    av_len計算が壊れてscale x8555の異常値になった(dev#1074でfail-fastガード
    出荷済み、PR#1115)。

機構仮説(オーナー、issue #1174コメント1): 「正しいボーンの子に同名ボーンがある」
型、または「骨格が2つあってconstraintで追従している」型。後者はVRM/FBX書き出しで
constraintが消える(glTF系はconstraint非対応)ため、衣装側骨格がレスト姿勢のまま
原点付近に置き去りになる。

このモジュールはbpy非依存(文字列・数値・辞書のみ)。Blender外の
tests/coverage/selftestから直接検証できる(vp_modnorm.pyと同じ設計方針)。

**スコープの判断(2026-08-08、本WPで確定)**: 検出対象は「実際にHumanoidマッピング
で選ばれたボーン(pal_map値)の近傍」に限定する。骨格全体を無差別にサフィックス
走査すると、尻尾・触角等の正常なボーンチェーン(Blenderが複製時に
"Tail"→"Tail.001"→"Tail.002"と連番を振る、通常構造)を誤検知するため
(dev#300コメント参照)。Humanoid必須ボーンが役割の異なる別ボーンと同名衝突する
ことは通常構造では起こらないため、この限定により正常検体での誤検知を避けつつ
実報告4件すべてを捕捉できる。
"""
import re

# Blender方式の連番サフィックス: ".001", ".002", ...(3桁ゼロ埋め、Blender仕様)
_BLENDER_SUFFIX_RE = re.compile(r"^(.*)\.(\d{3,})$")
# Unity FBX Exporter方式の連番サフィックス: "_2", "_3", ...(dev#300
# EnsureUniqueTransformNames/ResolveUniqueNamesが生成する形。"_1"は無い
# ——初出はサフィックス無しのまま、2回目以降が"_2"から始まる)
_UNITY_SUFFIX_RE = re.compile(r"^(.*)_([2-9]\d*)$")


def strip_dup_suffix(name):
    """名前から連番サフィックス(Blender式".NNN" / Unity式"_N")を剥がした
    ベース名を返す。サフィックスが無ければそのまま返す。
    """
    if not name:
        return name
    m = _BLENDER_SUFFIX_RE.match(name)
    if m:
        return m.group(1)
    m = _UNITY_SUFFIX_RE.match(name)
    if m:
        return m.group(1)
    return name


def find_mapped_bone_duplicates(pal_map, bone_names):
    """pal_mapで実際に選ばれた各実ボーン名について、同じベース名(連番
    サフィックス違い)を持つ別のボーンが骨格内に存在するかを調べる。

    pal_map: {パルボーン名: 実ボーン名}(step01がVRM/FBXいずれかの経路で
        解決した後の対応表)。
    bone_names: そのアーマチュアに実在する全ボーン名の一覧。

    返り値: {パルボーン名: [重複と判定した別ボーン名, ...]}(見つかったものだけ。
    何も無ければ空辞書)。
    """
    result = {}
    for pal_bone, actual_name in pal_map.items():
        if not actual_name:
            continue
        base = strip_dup_suffix(actual_name)
        dups = [n for n in bone_names
                if n != actual_name and strip_dup_suffix(n) == base]
        if dups:
            result[pal_bone] = sorted(dups)
    return result


def find_vrm0_duplicate_human_bone_assignment(items):
    """VRM0のhuman_bonesリストで、同一HumanBoneNameが複数回割り当てられて
    いないかを調べる(VRMアドオンの
    `[VRM Add-on:WARNING] Duplicated VRM0 bone: ...` 相当を、Blender/アドオンの
    警告テキストをパースせず、データそのものから直接検出する)。

    items: [(bone_enum, node_bone_name), ...] のリスト
        (bone_enumはVRM0のHumanBoneName、例 "hips"。node_bone_nameは対応する
        実ボーン名。空文字/Noneでもよい——未割当スロットとの区別はしない、
        ここでは「同じbone_enumが複数回出現した」ことだけを見る)。

    返り値: {bone_enum: [node_bone_name, ...]}(2回以上出現したものだけ)。
    """
    seen = {}
    for bone_enum, node_name in items:
        if not bone_enum:
            continue
        seen.setdefault(bone_enum, []).append(node_name)
    return {k: v for k, v in seen.items() if len(v) > 1}


def select_primary_armature(candidates):
    """複数Armatureオブジェクトから主骨格を選ぶ。

    candidates: [{"key": 識別子, "has_humanoid_mapping": bool,
                  "skinned_vertex_count": int, "bone_count": int}, ...]
    優先順位: has_humanoid_mapping(Trueが優先) > skinned_vertex_count(大) >
    bone_count(大)。全て同点なら先頭(候補リストの並び順)を採用する。

    返り値: 選ばれた候補のdict、またはcandidatesが空ならNone。
    """
    if not candidates:
        return None
    best = candidates[0]
    for c in candidates[1:]:
        if _priority_key(c) > _priority_key(best):
            best = c
    return best


def _priority_key(c):
    return (
        1 if c.get("has_humanoid_mapping") else 0,
        c.get("skinned_vertex_count", 0) or 0,
        c.get("bone_count", 0) or 0,
    )


# ユーザー向け案内(FATAL/WARN共通)。ツール名は一切出さない
# (CLAUDE.md 2026-07-29裁定: 特定ツールの名指しは製品コード・ログ・エラー
# メッセージ・公開文面のいずれでも禁止。汎用実装のみ)
#
# dev#1225(オーナー裁定、2026-08-08)により旧文言(「Unityで重複Armature/
# ボーンを統合して再輸出してください」、dev#1174/PR #1181)を差し替えた。
# 裁定原文: 「使用者のアバターに『余分な』ものがあると主張したり、何かを
# 削除したり依頼することは一切許容されません」。旧文言はユーザーへ
# アバターの改変(統合)を依頼しており、複数Armature(アクセサリ・衣装が
# 独自骨格を持つ)自体はVRChatアバターの通常構造であって「アバター側の
# 不備」ではない。新文言は主語をツール側に置き、ユーザーへの改変依頼を
# 含まない(dev#1226)
GUIDANCE_TEXT = (
    "This avatar has multiple skeletons (Armatures), which is a normal "
    "structure when accessories or outfits carry their own rig. This tool "
    "could not fully resolve which bone belongs to the main body in this "
    "structure."
)
