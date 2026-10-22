# -*- coding: utf-8 -*-
"""dev#6 構造チェック: retarget段(step02_retarget.py)の出力を検証するための
生の幾何データ抽出(Blender headless)。

判定ロジック自体は持たない(pipeline\\py\\vp_structural_check.py へ分離、
Blender不要で単体テストできるようにするため)。このスクリプトの役割は
3つのBlenderファイル/JSONから必要な数値だけを読み出してJSONへ書き出すこと。

設計文書: .devonly\\docs\\rd\\visual_check_rescope_20260802.md 4節。

実行: blender --background --factory-startup --python-exit-code 1 --python
      dump_retarget_structure.py -- <job.json> <Male|Female> <out.json>

入力:
  converted/step01_clean.blend  (retarget前。アバター自身の骨格)
  converted/step02_{gender}.blend (検査対象。retarget後の出力)
  converted/avatar_meta.json     (pal_map: {パル名: アバター実ボーン名})
  vanilla/refskel_{gender}.json  (Palworld本体から一度だけ抽出した固定データ。
                                   今回のアバター・今回のretarget実行に非依存)
  vanilla/common_bones.json

出力: <out.json> — vp_structural_check.evaluate() がそのまま読める辞書。

SPINE_CHAIN/ROTATE_CHAINS は step02_retarget.py と同じ値をここに複製している
(step02_retarget.py はモジュール末尾で無条件に main() を呼ぶため import
できず、かつ既存のstep02本体ロジックは変更しない方針のため)。両者を
変更するときは一致を保つこと。
"""
import json
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# pipeline\blender の vp_bl(build_pal_armature 等)を使うための追加パス
# (vp_atlas_uvbake.py と同じパターン)
_BLENDER_DIR = os.path.join(HERE, "..", "blender")
if _BLENDER_DIR not in sys.path:
    sys.path.insert(0, _BLENDER_DIR)
import vp_bl  # noqa: E402
from vp_bl import core  # noqa: E402

TAG = "dump_retarget_structure"

# step02_retarget.py の同名定数の複製(コメント参照、import不可のため)。
# dev#1232: vp_structural_check.ROTATE_CHAIN_PAIRS はこのリストと同じ
# ペア集合を、chain_reversals()のpre/post比較から除外する目的で別途
# 複製している(auto_fit_pose()がこれらのチェーンを強制的にパル標準方向へ
# 回転させるため、pre/post比較が意味を持たない)。3箇所とも変更するときは
# 一致を保つこと。
ROTATE_CHAINS = [
    ("clavicle_l", "upperarm_l"), ("upperarm_l", "lowerarm_l"),
    ("lowerarm_l", "hand_l"), ("hand_l", "middle_01_l"),
    ("clavicle_r", "upperarm_r"), ("upperarm_r", "lowerarm_r"),
    ("lowerarm_r", "hand_r"), ("hand_r", "middle_01_r"),
]
SPINE_CHAIN = ["pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head"]
# 脚チェーンもstep02_retarget.pyのCHIBI_CANDIDATESに含まれる関節移動対象
# (向き不変・位置のみ)。ROTATE_CHAINSは腕のみを対象にしているが、
# チェーン単調性/左右対称性チェックは脚も見る価値があるため、CHIBI_CANDIDATESの
# 隣接関係から脚チェーンのペアも追加する(股関節はpelvisの子)
LEG_CHAINS = [
    ("pelvis", "thigh_l"), ("thigh_l", "calf_l"), ("calf_l", "foot_l"),
    ("foot_l", "ball_l"),
    ("pelvis", "thigh_r"), ("thigh_r", "calf_r"), ("calf_r", "foot_r"),
    ("foot_r", "ball_r"),
]


def _chain_pairs():
    spine_pairs = list(zip(SPINE_CHAIN, SPINE_CHAIN[1:]))
    return spine_pairs + list(ROTATE_CHAINS) + list(LEG_CHAINS)


def _lr_pairs(names):
    pairs = []
    for n in names:
        if n.endswith("_l"):
            r = n[:-2] + "_r"
            if r in names:
                pairs.append((n, r))
    return pairs


def _bone_world_head(arm, name):
    b = arm.data.bones.get(name)
    if b is None:
        return None
    w = arm.matrix_world @ b.head_local
    return [w.x, w.y, w.z]


def _bone_quat(arm, name):
    b = arm.data.bones.get(name)
    if b is None:
        return None
    q = b.matrix_local.to_quaternion()
    return [q.w, q.x, q.y, q.z]


def main():
    job, rest = vp_bl.load_job_from_argv()
    if len(rest) < 2:
        core.die(TAG, "usage: -- <job.json> <Male|Female> <out.json>")
    gender = rest[0]
    out_path = rest[1]
    if gender not in ("Male", "Female"):
        core.die(TAG, f"invalid gender: {gender}")
    gl = gender.lower()

    conv = core.job_subdir(job, "converted")
    vanilla = os.path.join(job["job_dir"], "vanilla")

    step01_path = os.path.join(conv, "step01_clean.blend")
    step02_path = os.path.join(conv, f"step02_{gl}.blend")
    meta_path = os.path.join(conv, "avatar_meta.json")
    refskel_path = os.path.join(vanilla, f"refskel_{gl}.json")
    common_path = os.path.join(vanilla, "common_bones.json")
    for p in (step01_path, step02_path, meta_path, refskel_path, common_path):
        if not os.path.exists(p):
            core.die(TAG, f"required input not found: {p}")

    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    pal_map = meta["pal_map"]  # {pal_name: avatar_bone_name}

    with open(common_path, encoding="utf-8") as f:
        common = json.load(f)["common"]

    chain_pairs = _chain_pairs()
    chain_bone_names = sorted({b for pair in chain_pairs for b in pair})
    lr_pairs = _lr_pairs(set(chain_bone_names))

    # 1) step01(retarget前): アバター自身のボーンから、チェーンに使う点のみ抽出
    bpy.ops.wm.open_mainfile(filepath=step01_path)
    avatar_arm = bpy.data.objects.get(meta["armature"])
    if avatar_arm is None:
        avatar_arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if avatar_arm is None:
        core.die(TAG, "step01: avatar Armature not found")
    step01_points = {}
    for pal_name in chain_bone_names:
        av_name = pal_map.get(pal_name)
        if av_name is None:
            continue
        w = _bone_world_head(avatar_arm, av_name)
        if w is not None:
            step01_points[pal_name] = w

    # 2) step02(retarget後): パル名アーマチュアから同じ点+向き比較用の全common_bones
    bpy.ops.wm.open_mainfile(filepath=step02_path)
    pal_arm = bpy.data.objects.get("Armature")
    if pal_arm is None:
        pal_arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if pal_arm is None:
        core.die(TAG, "step02: pal Armature not found")
    step02_points = {}
    for pal_name in chain_bone_names:
        w = _bone_world_head(pal_arm, pal_name)
        if w is not None:
            step02_points[pal_name] = w
    test_quat = {}
    for name in common:
        q = _bone_quat(pal_arm, name)
        if q is not None:
            test_quat[name] = q

    # 3) 向き不変性チェックの基準: refskel固定データからその場で再構築した標準骨格
    #    (今回の実行結果に一切依存しない独立の基準 — 設計文書4-3節)
    ref_arm = vp_bl.build_pal_armature(refskel_path, common, name="RefOriented")
    ref_quat = {}
    for name in common:
        q = _bone_quat(ref_arm, name)
        if q is not None:
            ref_quat[name] = q

    data = {
        "gender": gender,
        "common_bones": sorted(set(ref_quat) & set(test_quat)),
        "ref_quat": ref_quat,
        "test_quat": test_quat,
        "chain_pairs": [list(p) for p in chain_pairs],
        "lr_pairs": [list(p) for p in lr_pairs],
        "step01_points": step01_points,
        "step02_points": step02_points,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"[{TAG}] wrote {out_path}: common_bones={len(data['common_bones'])} "
          f"chain_pairs={len(chain_pairs)} lr_pairs={len(lr_pairs)} "
          f"step01_points={len(step01_points)} step02_points={len(step02_points)}")


main()
