# -*- coding: utf-8 -*-
"""Step02: パル骨格への載せ替え(オートフィット+チビ骨格方式)。性別ごとに実行。

実行: blender --background --factory-startup --python-exit-code 1 --python step02_retarget.py -- <job.json> <Male|Female>
入力: converted/step01_clean.blend + vanilla/refskel_{gender}.json
出力: converted/step02_{gender}.blend

方式はPalModで実証済みのチビ骨格(検査⑨⑩で100点):
  - アバターを体幹比でパル(cm)系へスケール、腰位置合わせ
  - 腕チェーンをパル方向へ回転(A→Tポーズ化)+肩スライダー適用
  - 形状をメッシュへ焼き込み、接地
  - パル骨格の関節をアバターの関節位置へ移動(向き不変、位置のみ=チビ骨格)
  - ウェイトをパル名へ移植(Humanoid外は最寄り祖先へ統合)、バインド
"""

import json
import math
import os
import sys
import time  # dev#1508 graceful-degrade(night_20260817 laneI): sway_exclusions.jsonのロック待ち
from typing import Dict, List  # dev#1508 graceful-degrade(night_20260817 laneI)のローカル型注釈用

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# dev#1375(dev#19 R3統合): 揺れチェーン自動割当エンジン(bpy非依存、
# pipeline\py\配下)をこのBlenderスクリプトから直接importできるようにする。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py"))
import vp_bl
import vp_dup_armature as vp_dup  # dev#1174: 重複armature検出、bpy非依存
import vp_modnorm
import sway_allocator  # dev#1508 受入ゲート: 判定ロジックの正本(sway_source_bones経由で使う)
import sway_allocator_wire  # dev#1508 W2a: アロケータ実結線(候補判定・量子化・診断ログ、
                             # W2a-2c時点では手動指定(job["sway_manual"])専用に縮小——
                             # 自動割当はsway_hub_wire.pyのハブ経路へ完全置換(下記参照)
import sway_assign as sway_assign_mod  # dev#1375: 揺れチェーン自動割当エンジン(手動指定用)
import sway_identify  # dev#19 native-donor-rule WP: 尻尾/耳の同定(既定チェック計算、W2aでは未使用。互換importとして残置)
import sway_native_rule  # dev#19 native-donor-rule WP: donor家系のn+1規則選定
import sway_hub  # dev#1508 W2a-2c: 汎用ハブ配線(トポロジ計画)
import sway_hub_wire  # dev#1508 W2a-2c: ハブ配線の高レベル入口(アロケータ実行〜診断ログ)
import sway_hub_placement  # dev#1508 W2a-2c: 座標配置の共通quat演算(build_donor_chain_quats)
                            # と、pak側shared-skeleton reparent計画(plan_reparent_steps)
import sway_shared_skeleton  # dev#1508 W2a-2c: ReparentStepのjsonシリアライズに使う型
import sway_source_bones  # dev#1508 受入ゲート正本化: 対象骨集合の独立導出(配線実装を経由しない)
import sway_source_gate  # dev#1508 受入ゲート正本化: ソース基準1:1比較(fail-closed)
import sway_pivot_axiom  # dev#1508 hubwire final: オーナー制定公理(支点の対親相対位置不変)の検査
import sway_degrade  # dev#1508 graceful-degrade(night_20260817 laneI): 揺れ鎖の明示的縮退
import sway_chain_defaults  # dev#1572第3便: 既定enabled判定の唯一の共有関数
                             # (GUI側app_py\ui\sway_style_dialog.pyと同一関数を呼ぶ)
from vp_bl import core

TAG = "step02"

# dev#1625(2026-08-21 オーナー裁定): 姿勢不一致切除の理由文字列に埋め込む
# 固定マーカー。`_sway_degrade_precheck()`(切除理由の生成側)と、
# 切除発生時の##AVATAR_WARNING##告知(集計側)の両方が同じ文字列を参照する
# ことで、他の切除理由(容量超過/重み衝突/支点公理違反等)と取り違えない。
SWAY_POSTURE_MISMATCH_CULL_TAG = "posture mismatch (dev#1625)"

# 腕チェーンの回転フィット(パル名で表現。アバター側はpal_mapで引く)。
# dev#1232: このリストは pipeline\py\dump_retarget_structure.py および
# pipeline\py\vp_structural_check.ROTATE_CHAIN_PAIRS へ複製されている
# (auto_fit_pose()がこれらのチェーンをretarget前の向きに関係なく強制的に
# パル標準方向へ回転させるため、構造チェックのpre/post比較対象から
# 除外する必要がある)。3箇所とも変更するときは一致を保つこと。
ROTATE_CHAINS = [
    ("clavicle_l", "upperarm_l"), ("upperarm_l", "lowerarm_l"),
    ("lowerarm_l", "hand_l"), ("hand_l", "middle_01_l"),
    ("clavicle_r", "upperarm_r"), ("upperarm_r", "lowerarm_r"),
    ("lowerarm_r", "hand_r"), ("hand_r", "middle_01_r"),
]

# チビ骨格で明示移動する候補(マップされているものだけ移動)
CHIBI_CANDIDATES = [
    "spine_01", "spine_02", "spine_03", "neck_01", "head",
    "clavicle_l", "clavicle_r",
    "upperarm_l", "lowerarm_l", "hand_l", "upperarm_r", "lowerarm_r", "hand_r",
    "thigh_l", "calf_l", "foot_l", "ball_l",
    "thigh_r", "calf_r", "foot_r", "ball_r",
]
for _f in ("thumb", "index", "middle", "ring", "pinky"):
    for _s in ("01", "02", "03"):
        for _side in ("l", "r"):
            CHIBI_CANDIDATES.append(f"{_f}_{_s}_{_side}")

# 体幹チェーン(未マップの中間ボーンは比率補間で配置)
SPINE_CHAIN = ["pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head"]

# セグメント中間のtwistボーンは区間比率でスケール配置
CHIBI_TWIST_BONES = {
    "upperarm_twist_01_l": ("upperarm_l", "lowerarm_l"),
    "upperarm_twist_01_r": ("upperarm_r", "lowerarm_r"),
    "lowerarm_twist_01_l": ("lowerarm_l", "hand_l"),
    "lowerarm_twist_01_r": ("lowerarm_r", "hand_r"),
    "thigh_twist_01_l": ("thigh_l", "calf_l"),
    "thigh_twist_01_r": ("thigh_r", "calf_r"),
    "calf_twist_01_l": ("calf_l", "foot_l"),
    "calf_twist_01_r": ("calf_r", "foot_r"),
}

ZERO_WEIGHT_FALLBACK_BONE = "pelvis"

# 揺れ髪: ゲーム物理はhair_*ボーンを頭基準のアニメ位置で駆動する。
# PalMod検査⑪の教訓: 頭から遠いもの(尻尾)を載せると頭に張り付くが、
# 頭に付いている本物の髪ならこの仕組みに正しく乗れる。
# チェーン構成はバニラ髪RefSkeletonから動的に導出(1.0はhair_01..26)
HAIR_SPLIT_THRESHOLD = 0.5


def _bone_world(arm, bone_name):
    return arm.matrix_world @ arm.data.bones[bone_name].head_local


def _pose_head_world(arm, name):
    return arm.matrix_world @ arm.pose.bones[name].head


def global_scale_and_place(avatar_arm, pal_arm, pal_map, warnings=None):
    """体幹長(hips→head)の比で全体スケールを決め、腰位置を合わせる。

    warnings: step01が avatar_meta.json へ残した警告文字列のリスト(省略可、
    既定None)。dev#1174: 下のfail-fastガードが発火したとき、step01が既に
    重複armatureを検出・警告していたら、その旨をdie()メッセージへ併記して
    診断の手掛かりを増やす(warnings自体は一切書き換えない)。
    """
    av_hips = _bone_world(avatar_arm, pal_map["pelvis"])
    av_head = _bone_world(avatar_arm, pal_map["head"])
    pal_pelvis = _bone_world(pal_arm, "pelvis")
    pal_head = _bone_world(pal_arm, "head")
    av_len = (av_head - av_hips).length
    # dev#1074の常時ログ(実報告ZEBJLH7Lの調査タスク1): scaleが異常値になった
    # 場合に次回以降の同種問い合わせをログだけで即座に切り分けられるよう、
    # 算出根拠の実座標を必ず残す(失敗時だけでなく毎回出す)。
    print(f"[{TAG}] scale basis: av_hips={tuple(av_hips)} av_head={tuple(av_head)} "
          f"av_len={av_len:.6f} pal_pelvis={tuple(pal_pelvis)} pal_head={tuple(pal_head)}")
    if av_len < 1e-6:
        core.die(TAG, "cannot measure the avatar's torso length")
    # dev#1074(実報告ZEBJLH7L、outfit SK injection failed for 58): av_lenが
    # 「完全ゼロではないが異常に小さい」場合、上のepsilonガードを素通りして
    # s(全体スケール)が桁違いの異常値(実測x8555)になる。この異常値は気づかれずに
    # 後段(メッシュ焼き込み→dump_avatar_mesh→衣装SK注入)へ伝播し、3モジュール先の
    # バイナリパーサ(vp_core.py の頂点位置範囲チェック)でしか露見しない
    # (「胴が短い体型」ではこの桁の値にはならない — 既知の正常範囲x30〜x180から
    # 逆算すると、av_lenが通常の1/50〜1/200=2〜10mm相当まで潰れている必要があり、
    # どんな極端な体型でもヒップと頭のボーンが数mmまで近接することは無い)。
    # 「胴の長さ(hips-head)は腰幅(thigh_l-thigh_r)より極端に小さくなり得ない」という、
    # 体型・スケールを問わずどんな人型キャラクターにも成り立つ幾何的制約を使い、
    # 同一アバター内の別の骨格測定と比較する自己参照式の不変量でここを検出する
    # (外部の実測値・観測範囲への値寄せではない。値を伸ばして誤魔化す先=正規化は、
    # 破綻した座標から正しい値を捏造することになるため取らない。診断して止める)。
    hip_l = pal_map.get("thigh_l")
    hip_r = pal_map.get("thigh_r")
    if hip_l and hip_r:
        av_hip_width = (_bone_world(avatar_arm, hip_l)
                         - _bone_world(avatar_arm, hip_r)).length
        # 実human体型なら胴長は腰幅の数倍〜十数倍が通例。1/10未満は「ヒップと頭が
        # 実質同一座標」級の破綻でしか起こらないため、極端なデフォルメ体型も安全に
        # 通す側に倒した緩い下限として使う。
        if av_hip_width > 1e-6 and av_len < av_hip_width * 0.1:
            dup_note = ""
            if warnings and any(vp_dup.GUIDANCE_TEXT in w for w in warnings):
                # dev#1174: step01が既にduplicate-armatureの痕跡を検出・警告
                # していた場合、この異常scaleの説明として併記する(整合、
                # issue #1174のログ設計の追補)
                dup_note = (" step01 already flagged a possible duplicate "
                            "skeleton (Armature) in this avatar earlier in the "
                            "log (search for 'duplicate-named bone'); that is "
                            "a likely explanation for this corrupted measurement.")
            core.die(TAG, "the avatar's torso length "
                     f"({av_len:.4f}) is implausibly small relative to its hip width "
                     f"({av_hip_width:.4f}). The source file's Humanoid Hips/Head bone "
                     "assignment is likely broken (the two bones sit at nearly the same "
                     "position). Re-check the Hips/Head assignment in the tool that "
                     "exported this avatar (e.g. Unity's Configure Avatar)." + dup_note)
    s = (pal_head - pal_pelvis).length / av_len
    avatar_arm.scale = (s, s, s)
    bpy.context.view_layer.update()
    av_hips2 = _bone_world(avatar_arm, pal_map["pelvis"])
    avatar_arm.location += pal_pelvis - av_hips2
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    avatar_arm.select_set(True)
    for child in avatar_arm.children_recursive:
        child.select_set(True)
    bpy.context.view_layer.objects.active = avatar_arm
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    print(f"[{TAG}] global fit: scale x{s:.3f}, pelvis aligned")


def auto_fit_pose(avatar_arm, pal_arm, pal_map):
    """腕チェーンだけ、パル骨格の関節方向へ回転(A→Tポーズ化)。
    方向の基準は関節(子ボーンのhead)位置(合成テールは信用しない)。"""
    pal_mw = pal_arm.matrix_world
    done = 0
    for pal_bone, pal_child in ROTATE_CHAINS:
        av_bone = pal_map.get(pal_bone)
        av_child = pal_map.get(pal_child)
        if av_bone is None or av_child is None:
            print(f"[{TAG}][WARN] chain skip: {pal_bone}->{pal_child}")
            continue
        pal_dir = (pal_mw @ pal_arm.data.bones[pal_child].head_local
                   - pal_mw @ pal_arm.data.bones[pal_bone].head_local).normalized()
        cur_head = _pose_head_world(avatar_arm, av_bone)
        cur_dir = (_pose_head_world(avatar_arm, av_child) - cur_head).normalized()
        rot = cur_dir.rotation_difference(pal_dir).to_matrix().to_4x4()
        pb = avatar_arm.pose.bones[av_bone]
        cur = avatar_arm.matrix_world @ pb.matrix
        trans = cur.translation.copy()
        new_m = rot @ cur
        new_m.translation = trans
        pb.matrix = avatar_arm.matrix_world.inverted() @ new_m
        bpy.context.view_layer.update()
        done += 1
    print(f"[{TAG}] auto-fit: arm chains rotated ({done} bones)")


def apply_shoulder_offset(avatar_arm, pal_map, deg):
    """肩スライダー: Upper Armをワールド前後軸まわりに外へ開く(±deg)。
    バインドはバニラのままなので全ポーズが一律この分だけ開く。"""
    import math
    if abs(deg) < 0.01:
        return
    for pal_bone, sign in (("upperarm_l", -1.0), ("upperarm_r", 1.0)):
        av = pal_map.get(pal_bone)
        if av is None:
            continue
        pb = avatar_arm.pose.bones[av]
        rot = Matrix.Rotation(math.radians(sign * deg), 4, "Y")
        cur = avatar_arm.matrix_world @ pb.matrix
        trans = cur.translation.copy()
        new_m = rot @ cur
        new_m.translation = trans
        pb.matrix = avatar_arm.matrix_world.inverted() @ new_m
        bpy.context.view_layer.update()
    print(f"[{TAG}] shoulder offset: ±{deg}deg")


def apply_output_scale(pal_arm, meshes, k):
    """L1完結の一様スケール(dev#560、2026-08-07)。chibi_fit_armature()直後、
    root(0,0,0、refskelの唯一のparent=Noneボーンで chibi_fit_armature() の
    移動対象にも入らないため不動)を基準にキャラの見た目サイズをk倍する。
    既定1.0では呼び出し元がスキップし、以降のFBX輸出・
    chibi_bone_world_head dumpにも一切影響しない(pakバイト不変、負の対照)。

    背景(dev#157/PR#357の反省、2026-07-30ぱん官能NG「手が大きく崩壊」):
    旧方式はpakレベルでRefSkeleton(cookedバインドポーズ)のTranslationだけを
    k倍していたが、注入されるメッシュ頂点位置(このBlender工程が作る実体)は
    一切スケールされないため、スケルトンとメッシュの対応関係がk!=1.0で
    ズレて破綻していた(この節の上のU21コメントが説明する「chibi-fit後の
    関節位置とcookedバインドポーズのズレ」と同型の問題)。

    本関数はpal_arm(スケルトン)とmeshes(メッシュ頂点)を、両者がまだ
    同一のワールド座標系にある**この時点**で同時にスケールすることで、
    対応関係を崩さない(dev#560 2026-08-02オーナー提案「Blender工程末尾で
    スケール適用」の実装)。

    座標系の前提(呼び出し時点で成立、コード上の不変量):
      - pal_arm: オブジェクト変換は恒等(build_pal_armature()以降、
        chibi_fit_armature()を含め一度もobjectレベルのlocation/rotation/
        scaleを変更していない)。よってedit boneのhead/tailは絶対
        ワールド座標そのもの
      - meshes: snap_to_ground()末尾のtransform_apply(location=True)で
        object.locationが(0,0,0)・scaleが(1,1,1)にリセットされている
        (bake_pose_into_meshes()より前のglobal_scale_and_place()でも
        同様にscale/locationをbake済み)。よってメッシュ頂点のローカル
        座標もワールド座標そのもの
    """
    if k == 1.0:
        return
    if k <= 0:
        core.die(TAG, f"uniform_scale must be > 0 (got {k})")
    bpy.ops.object.select_all(action="DESELECT")
    pal_arm.select_set(True)
    bpy.context.view_layer.objects.active = pal_arm
    bpy.ops.object.mode_set(mode="EDIT")
    for b in pal_arm.data.edit_bones:
        b.head = b.head * k
        b.tail = b.tail * k
    bpy.ops.object.mode_set(mode="OBJECT")

    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.scale = (k, k, k)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    print(f"[{TAG}] output scale (dev#560): k={k:.4f} applied to skeleton+meshes "
          f"(root-fixed at world origin)")


def bake_pose_into_meshes(avatar_arm, mesh_objs):
    # 二重の安全網(公開issue #18): 通常はstep01の入口正規化で処理済みだが、
    # 無効フラグ(show_viewport=False)のArmatureモディファイアが残っていると
    # modifier_applyがBlender自身のRuntimeError(「モディファイアーはOFFです」)で
    # 停止する。ここでも適用直前に強制ONへ正規化してから進む(停止させない)。
    vp_modnorm.normalize_armature_modifiers(mesh_objs, tag=TAG)
    for obj in mesh_objs:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for mod in list(obj.modifiers):
            if mod.type == "ARMATURE":
                try:
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                except RuntimeError as e:
                    # issue #18のログ改修: どのメッシュ・モディファイアで
                    # 落ちたかを必ずログに残す(従来は特定不能だった)
                    core.die(TAG, "modifier_apply failed on mesh "
                             f"'{obj.name}' modifier '{mod.name}': {e}")


def snap_to_ground(mesh_objs):
    min_z = min((obj.matrix_world @ Vector(c)).z
                for obj in mesh_objs for c in obj.bound_box)
    for obj in mesh_objs:
        obj.location.z -= min_z
    bpy.ops.object.select_all(action="DESELECT")
    for obj in mesh_objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objs[0]
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    print(f"[{TAG}] ground snap: dz={-min_z:.1f}")
    return -min_z


def chibi_fit_armature(pal_arm, avatar_arm, pal_map, dz, exclude_descendants=None):
    """パル骨格の関節をアバターの(フィット・接地後の)関節位置へ移動する。
    向き(tail方向・roll)は変えず位置のみ。未マップの体幹中間ボーンは比率補間。

    exclude_descendants: 4)の「その他の子孫は最寄りの移動済み祖先のデルタで
    平行移動」ロジックから除外するボーン名の集合(dev#1365)。sway donorチェーン
    (cloth_chain+extra_bones)のように、祖先がCHIBI_CANDIDATES(例: thigh_r)を
    経由すると、実在の人体関節ではないのに巨大なchibi-fit補正デルタへ道連れ
    移動され、写像済みメッシュ頂点の実座標との間に最大約88cmものオフセットが
    生じる(work\\rd_19_r2b3\\diag_ancient\\DIAG.md実測)。Noneまたは空集合なら
    従来どおり全ての未マップ子孫が対象(既定・無退行)。"""
    exclude_descendants = exclude_descendants or set()
    # 1) 明示ターゲット(マップ済み候補)
    targets = {}
    for pal_name in CHIBI_CANDIDATES:
        av = pal_map.get(pal_name)
        if av is None:
            continue
        pb = avatar_arm.pose.bones.get(av)
        if pb is None:
            continue
        w = avatar_arm.matrix_world @ pb.head
        targets[pal_name] = Vector((w.x, w.y, w.z + dz))

    inv_pal = pal_arm.matrix_world.inverted()
    bpy.ops.object.select_all(action="DESELECT")
    pal_arm.select_set(True)
    bpy.context.view_layer.objects.active = pal_arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = pal_arm.data.edit_bones
    old_head = {b.name: b.head.copy() for b in eb}

    # 2) 体幹チェーンの未マップ中間(spine_02/03, neck_01等)を旧比率で補間
    chain = [b for b in SPINE_CHAIN if b in eb]
    known = [b for b in chain if b in targets or b == "pelvis"]
    for i, name in enumerate(chain):
        if name in targets or name == "pelvis":
            continue
        below = next((b for b in reversed(chain[:i])
                      if b in targets or b == "pelvis"), None)
        above = next((b for b in chain[i + 1:] if b in targets), None)
        if below is None or above is None:
            continue
        p_below_new = targets.get(below, inv_pal.inverted() @ old_head[below]
                                  if False else None)
        # pelvisは移動しない(グローバル配置で一致済み)→ 旧位置=新位置
        new_below = targets[below] if below in targets \
            else pal_arm.matrix_world @ old_head[below]
        new_above = targets[above]
        seg_old = old_head[above] - old_head[below]
        if seg_old.length < 1e-6:
            continue
        t = (old_head[name] - old_head[below]).length / seg_old.length
        targets[name] = new_below.lerp(new_above, t)
        print(f"[{TAG}] chibi interp: {name} (t={t:.2f} on {below}->{above})")

    moved_delta = {}
    ordered = [b.name for b in pal_arm.data.bones]  # 階層順
    for name in ordered:
        if name not in targets or name not in eb:
            continue
        b = eb[name]
        new_head = inv_pal @ targets[name]
        delta = new_head - b.head
        b.tail = b.tail + delta
        b.head = new_head
        moved_delta[name] = delta

    # 3) twist: 区間比率で配置
    for name, (p_name, c_name) in CHIBI_TWIST_BONES.items():
        if name not in eb or p_name not in old_head or c_name not in old_head:
            continue
        b = eb[name]
        old_seg = old_head[c_name] - old_head[p_name]
        new_seg = eb[c_name].head - eb[p_name].head
        if old_seg.length < 1e-6:
            continue
        t = (old_head[name] - old_head[p_name]).length / old_seg.length
        new_head = eb[p_name].head + new_seg * t
        delta = new_head - b.head
        b.tail = b.tail + delta
        b.head = new_head
        moved_delta[name] = delta

    # 4) その他の子孫(weapon/eyes/root外): 最寄りの移動済み祖先のデルタで平行移動
    def nearest_moved_ancestor(bone):
        p = bone.parent
        while p is not None:
            if p.name in moved_delta:
                return p.name
            p = p.parent
        return None

    for b in eb:
        if b.name in moved_delta:
            continue
        if b.name in exclude_descendants:
            continue
        anc = nearest_moved_ancestor(b)
        if anc is None:
            continue
        delta = moved_delta[anc]
        b.tail = b.tail + delta
        b.head = b.head + delta

    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"[{TAG}] chibi skeleton: {len(moved_delta)} joints moved "
          f"(+descendants translated) known_chain={known}")


# ---------------------------------------------------- sway donor静止姿勢の再配置(dev#19 swayfix)

def resample_polyline(points, n_out):
    """points(Vector様のオブジェクト列、len>=2。__sub__/.length/.lerp()の
    ダックタイピングのみに依存、bpy非依存)を、累積弧長に沿ってn_out個
    (n_out>=2)の等間隔点へリサンプルする純粋関数。

    先頭・末尾は常にpoints[0]/points[-1]と厳密一致する(端点保存)。
    全点が同一座標(全区間長ゼロ)の場合は、全出力点をpoints[0]にする
    (縮退ケースの安全側フォールバック、ゼロ除算を避ける)。

    work\\rd_19_anglelimit\\PROPOSAL.md §4.1(sway donorをアバター実チェーンの
    形へ再配置する)の中核演算。donor節数(n_out)がソース節数と異なっても、
    実チェーンの実測形状(方向・曲がり)をそのまま保ったまま節数だけ変換する。
    """
    if n_out < 2:
        raise ValueError("n_out must be >= 2")
    if len(points) < 2:
        raise ValueError("points must have at least 2 elements")
    seg_lens = [(points[i + 1] - points[i]).length for i in range(len(points) - 1)]
    total = sum(seg_lens)
    if total < 1e-9:
        return [points[0] for _ in range(n_out - 1)] + [points[-1]]
    cum = [0.0]
    for length in seg_lens:
        cum.append(cum[-1] + length)
    out = []
    for k in range(n_out):
        target = total * k / (n_out - 1)
        seg_i = 0
        while seg_i < len(seg_lens) - 1 and cum[seg_i + 1] < target:
            seg_i += 1
        seg_len = seg_lens[seg_i]
        t = 0.0 if seg_len < 1e-9 else (target - cum[seg_i]) / seg_len
        t = max(0.0, min(1.0, t))
        out.append(points[seg_i].lerp(points[seg_i + 1], t))
    return out


def resample_polyline_or_direct(points, n_out):
    """tailmatch WP(dev#19、issue#19、work\\rd_19_flight\\briefs\\
    tailmatch_probe.mdが正本、裁定2026-08-12確定版の原理5「donor選定は節数
    完全一致を最優先。一致時はdonor節i→ソース関節iの直写(均等再サンプリング
    禁止)」)の実装。

    n_out(donor側が必要とする点数)が len(points)(ソース側ポリラインの
    実座標点数)と厳密に一致するとき、resample_polyline()による弧長比率での
    再配分を経由せず、pointsをそのまま(donor節i == ソース関節iの座標直写で)
    返す。

    resample_polyline()は両端点こそ保存するが、途中の節位置は「全長に対する
    弧長比率」で再配置してしまうため、節数がちょうど一致している場合でも
    ソース側の不均等な節間隔(関節の実際の曲がり・詰まり)を均してしまう——
    これがオーナーの「ちょっといやなところにボーンがあるような、えにも
    いわれぬ不快感」の構造原因(dev#19裁定コメント2026-08-12確定版、原理5)。
    節数が一致するときは再配分そのものが不要(1対1で写せる)ため、直写に
    切り替える。

    節数不一致時は本関数はresample_polyline()へそのまま委譲する(既定挙動:
    呼び出し元・既存テストへの後方互換を壊さない)。
    """
    if n_out == len(points):
        return list(points)
    return resample_polyline(points, n_out)


# ------------------------------------------ donor回転(quat)再構成(dev#19 rotfix WP)
#
# work\rd_19_scurve\PROPOSAL.md(主因の確定)+work\rd_19_anglemap\PROPOSAL.md
# (角度写像・BoneForwardAxis規約の確認)が正本。①(位置のみ再配置)は
# reposition_sway_donor_chain_and_leaf()で既に実装済みだが、donor骨の
# quat(回転)は旧donor(腰布・鞄等)の静止姿勢のまま据え置かれており、
# KawaiiPhysicsのSimulateRotation(=swing×ParentBone.PoseRotation、
# work\rd_19_anglelimit\PROPOSAL.md §1.2/§2.4)が静止時から致命的な不整合
# (実測86°〜176°)を可視化していた(scurve PROPOSAL §2)。
#
# 以下の関数群は「UEコンポーネント空間」の生の(x,y,z)ベクトル・quatに
# 対してのみ計算する(x,y,z,w順、pipeline\py\build_avatar_variant.pyの
# _quat_mul/_quat_rotateと同一のHamilton積規約)。Blender専用スクリプトから
# pipeline/py側の実装へ依存を増やさないための意図的な重複実装
# (2026-07-28言語方針「環境が強制する分だけ」に沿う、build_avatar_variant.py
# 側の_quat_mul/_quat_rotateと1対1で対応することをコメントで明記する)。
#
# 「UEコンポーネント空間」への変換は、既存のchibi_bone_world_head機構
# (main()末尾)と同じ(x, -y, z)変換(Blenderワールド/armature空間->UE)を
# 使う。scurve PROPOSAL §2.2実測(「quatのローカル+X(world)」と「バニラ
# 位置ベースの方向」が誤差0.0°で一致)がこの変換で成立していたことを踏襲
# しており、position用の変換をそのまま方向ベクトルにも適用してよい(線形
# 変換のため差分ベクトルにも同じ変換が成り立つ)。

def _q_mul(a, b):
    """Hamilton四元数積(a*b、a=outer側=後から適用、b=inner側=先に適用)。
    build_avatar_variant.py の _quat_mul と同一の式・同一の(x,y,z,w)順。"""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _v_len(a):
    return math.sqrt(_v_dot(a, a))


def _v_normalize(a):
    n = _v_len(a)
    if n < 1e-12:
        return (1.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def _q_find_between(a, b):
    """単位ベクトルaをbへ最短回転で重ねるquat(UE `FQuat::FindBetweenVectors`
    と同型の構成。work\\rd_19_anglelimit\\PROPOSAL.md §2.4に引用されている
    `SimulateRotation = FQuat::FindBetweenVectors(PoseVector, SimulateVector)
    * ParentBone.PoseRotation` と同じ演算パターンを、静止姿勢のdonor quat
    再構成にも流用する)。a≈-b(180°、縮退)はaと直交する任意軸まわりの
    180°回転で代替する。"""
    dot = max(-1.0, min(1.0, _v_dot(a, b)))
    if dot < -0.999999:
        axis = _v_cross((1.0, 0.0, 0.0), a)
        if _v_len(axis) < 1e-6:
            axis = _v_cross((0.0, 1.0, 0.0), a)
        axis = _v_normalize(axis)
        return (axis[0], axis[1], axis[2], 0.0)
    half = _v_normalize((a[0] + b[0], a[1] + b[1], a[2] + b[2]))
    axis = _v_cross(a, half)
    w = _v_dot(a, half)
    return (axis[0], axis[1], axis[2], w)


def build_donor_chain_quats(ue_dirs):
    """donorチェーンの各リンクについて、「自分->子方向」(ue_dirs[i]、UE
    コンポーネント空間、チェーン順)をローカル+X(BoneForwardAxis既定=
    X_Positive、work\\rd_19_anglelimit\\PROPOSAL.md §1.2/work\\rd_19_anglemap\\
    PROPOSAL.md §1.1で確定済みの規約)が指すコンポーネント空間quatの列を
    返す(長さlen(ue_dirs)、入出力とも順序対応)。

    roll(ローカル+X軸まわりの捩れ)は隣接リンク間で最小回転となるよう
    連鎖的に決める(work\\rd_19_scurve\\PROPOSAL.md §7.1「隣接リンク間で
    最小捻れとなるparallel-transport」の実装、いわゆるrotation-minimizing
    frame)。先頭リンクのみ(1,0,0)からの最短回転で初期化する(先頭のroll
    自体は任意——「前方向が実子方向と一致する」という受入基準には影響
    しない。曖昧な箇所を実装判断で埋めた、詳細はnotes_rotfix.md)。"""
    quats = []
    prev_dir = None
    prev_q = None
    for raw in ue_dirs:
        d = _v_normalize(raw)
        if prev_q is None:
            q = _q_find_between((1.0, 0.0, 0.0), d)
        else:
            delta = _q_find_between(prev_dir, d)
            q = _q_mul(delta, prev_q)
        quats.append(q)
        prev_dir = d
        prev_q = q
    return quats


def compute_chain_bend_weights(avatar_arm, bone_names):
    """dev#19 rotfix WP(項目2、屈曲考慮ウェイト配分): sway_cloth_bones連鎖
    (chain順、index0=アンカー相当)の各ボーンについて、「入ってくる方向」
    (bone[i-1]->bone[i])と「出ていく方向」(bone[i]->bone[i+1])のなす角度
    (度)を屈曲量として返す(長さlen(bone_names)、先頭・末尾は隣接2方向が
    定義できないため0.0)。

    sway_cloth_target_indices()のbend_weights引数へ渡すことで、実チェーン
    の屈曲(方向反転)が急な箇所でウェイト写像が2骨を1donorへ圧縮するのを
    避ける(work\\rd_19_scurve\\PROPOSAL.md §3.4/§7.2の設計提案の実装)。"""
    mw = avatar_arm.matrix_world
    pts = []
    for n in bone_names:
        pb = avatar_arm.pose.bones.get(n)
        pts.append((mw @ pb.head) if pb is not None else None)
    weights = [0.0] * len(bone_names)
    for i in range(1, len(bone_names) - 1):
        if pts[i - 1] is None or pts[i] is None or pts[i + 1] is None:
            continue
        v1 = pts[i] - pts[i - 1]
        v2 = pts[i + 1] - pts[i]
        if v1.length < 1e-9 or v2.length < 1e-9:
            continue
        dot = max(-1.0, min(1.0, v1.normalized().dot(v2.normalized())))
        weights[i] = math.degrees(math.acos(dot))
    return weights


def reposition_sway_donor_chain_and_leaf(pal_arm, avatar_arm, active_entries, dz):
    """swayfix WP(dev#19、issue#19): PROPOSAL §7.5の①②修正を1回のedit-mode
    セッションで適用する。chibi_fit_armature()の**直後**(anchor_boneが
    CHIBI_CANDIDATESの一員でも、その最終位置が確定した後)に呼ぶこと。

    ①(donor静止姿勢の再配置): dev#19 exact-bone-copy WP(2026-08-14夜、
    オーナー仕様)により、donor(ウェイト転写先、cloth_chain)がソース
    (sway_cloth_bones、実際にウェイトが乗っている転写元)以上の本数で
    足りている(n_donor>=n_source、ウェイト1対1化WP・PR #1421後の既定形)
    ときは、donor節i(0<=i<n_source)の head/tail を **転写元ボーンiの
    head/tail(pose位置+dz)そのままBlender上で完全コピー**する(弧長
    リサンプル・比率再配分を一切経由しない。「始点・終点を持てばよい」
    というオーナー原文どおり、donorの節間隔・方向は転写元の実測どおりで
    均さない)。3本目相当(最後の転写元ボーン)のtailは転写元自身のtail
    (=耳・しっぽの先端)とそのまま一致する。donorがソースより多い(余剰)
    分は、最後の転写元ボーン自身のベクトル(head->tail、セグメント長も
    転写元のまま)を先端から繰り返し延長して埋める(leaf_boneが有れば
    その先も同じ延長で続ける、既存のleaf外挿と同じ手口)。

    donorがソースより不足する(n_donor<n_source、donor本数が足りない
    家系だけの既存フォールバック)ときは、旧来どおりresample_polyline_or_direct()
    で弧長比率の再配分を行う(節数完全一致時は直写になるtailmatch WP、
    dev#19裁定原理5の挙動を含め無変更)。
    donor anchor(cloth_chain[0]の親、entry["anchor_bone"])は本関数では動かず
    (chibi_fit_armature()が既に確定済みの位置を使う)、そこから実チェーン形状を
    続ける。

    ②(実リーフボーン、PROPOSAL §7.2-7.4): entry["leaf_bone"]がNoneでなければ、
    cloth_chain末尾の子として新規editbone(ウェイト無し)を作成し、①で
    確定した延長点へ配置する(既存ならその場で位置更新のみ、冪等)。

    ③(donor回転の再構成、dev#19 rotfix WP、work\\rd_19_scurve\\PROPOSAL.md §7.1が
    正本): ①②の位置に加えて、cloth_chain各リンクのquat(コンポーネント空間、
    UE規約)を「自分->子方向」がローカル+X(BoneForwardAxis=X_Positive)を
    満たすよう再構成し、戻り値の辞書(bone名->(x,y,z,w))として返す。方向は
    常にdonor自身のhead位置列(=①で配置したhead、tailの完全コピーとは
    独立)の連なりから計算する——tailは「見た目・編集上の整合」のための
    値であり、回転はhead位置(=実際にcooked SKへ反映される座標、
    chibi_bone_world_head機構)の連なりが表す関節連鎖の向きを表現する
    必要があるため(exact-bone-copyでtailを転写元のtailへ独立に上書き
    しても、rootが実チェーンの節間隔と食い違わない限り両者は一致するが、
    donorがソースより多い延長区間・不連続なtailを持つケースでも回転計算が
    崩れないよう、明示的にhead列を単一の正とする)。leaf_bone自身の回転は
    再構成しない(leafは物理チェーンの終端で子を持たず、そのローカルquat
    は誰にも参照されないため、scurve PROPOSAL §4のe項判定と同じ理由で
    no-op)。他の73ボーン相当(cloth_chain外)の回転はここでは一切扱わない
    (既存通りテンプレート値のまま、build_avatar_variant.py側)。

    位置は、pal_arm.data.bones全体をダンプする既存のU21 chibi_bone_world_head
    機構(main()末尾)が自動的にper-avatarでcooked SKへ反映する(新規
    プラミング不要、headのみが読まれるためtailの値そのものは出力に影響
    しない)。回転は本関数の戻り値(donor_quats)をmain()が新規の
    chibi_bone_world_quat_{gender}.jsonへダンプし、build_avatar_variant.pyの
    新設パッチ経路がsway donorチェーンだけに限定して反映する。

    sway未指定(active_entries空)なら即return {}(完全no-op、既定出力不変)。
    """
    donor_quats = {}
    if not active_entries:
        return donor_quats

    bpy.ops.object.select_all(action="DESELECT")
    pal_arm.select_set(True)
    bpy.context.view_layer.objects.active = pal_arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = pal_arm.data.edit_bones
    n_repositioned = 0
    n_leaf = 0
    for e in active_entries:
        sway_bones = e["sway_cloth_bones"]
        cloth_chain = e["cloth_chain"]
        leaf_name = e.get("leaf_bone")

        def av_point(name, use_tail=False):
            pb = avatar_arm.pose.bones.get(name)
            if pb is None:
                return None
            local = pb.tail if use_tail else pb.head
            w = avatar_arm.matrix_world @ local
            return Vector((w.x, w.y, w.z + dz))

        # dev#19 tail-end-marker WP(2026-08-14夜、リリース前ブロッカー、
        # work\rd_19_smokefinal2\FINAL_REPORT.md「原因切り分け」節が正本):
        # sway_cloth_bonesの末尾は、Unity PhysBoneチェーン終端の合成tip
        # マーカー("<親骨名>_end"、physbones.json/ExtractPhysBoneChains()の
        # CollectPhysBoneLeafChains()が書き出すFBX慣習「leaf bone」終端
        # Transform)であることが常態で、Blender step01インポート後の実
        # ポーズボーンとしては存在しない。これを他の実在名と同列に
        # avatar_arm.pose.bones.get()へ通すと、この1名が必ず解決失敗し
        # any(p is None ...)がTrueになって鎖全体の座標コピーが恒常的に
        # スキップされる(修正前の実バグ、smokefinal2で初めて可視化)。
        # 対処: 末尾が"_end"で、かつ実在骨として解決できない場合だけ実在骨
        # リストから除外する(FBX慣習の"_end"は親骨のtail位置を表すため、
        # 除外後のtip = 直前の実在骨のtail = 同じ先端位置になり、外挿の
        # 意味も保たれる)。それ以外の名前解決失敗(実在すべき名前が
        # 見つからない想定外ケース)は従来どおりWARN+skipのまま(安全側維持)。
        if (len(sway_bones) >= 2 and sway_bones[-1].endswith("_end")
                and avatar_arm.pose.bones.get(sway_bones[-1]) is None):
            sway_bones = sway_bones[:-1]

        # アンカーのみ(実チェーン長1未満)・donorチェーン空なら再配置対象が無い
        if len(sway_bones) < 2 or not cloth_chain:
            continue

        points = [av_point(n) for n in sway_bones]
        tip = av_point(sway_bones[-1], use_tail=True)
        if tip is None or any(p is None for p in points):
            # アバター側ボーンが見つからない(想定外) — 安全側でこのentryの
            # 再配置をスキップし、vanilla位置のまま残す(die()しない、
            # 他entryの処理は継続)。
            print(f"[{TAG}][WARN] sway reposition: avatar bone(s) for "
                  f"{sway_bones} not found in pose — skipped (vanilla position kept)")
            continue

        anchor_head = eb[e["anchor_bone"]].head.copy() if e["anchor_bone"] in eb else None
        if anchor_head is None:
            print(f"[{TAG}][WARN] sway reposition: anchor bone "
                  f"{e['anchor_bone']!r} not in pal_arm — skipped")
            continue
        # dev#19 bonespace WP(work\rd_19_flight\briefs\reposition_space_fix.md
        # が正本、issue#19): 旧実装はここでpolylineをanchor_world基準へ
        # 「形だけ」再配置していた(shape = anchor_world + (p - polyline[0]))。
        # これはsway_bones[0](アバターの実チェーン先頭骨、例:"Tail Root")の
        # 位置がアンカー(donorの親、例:pelvis)の位置とほぼ一致するという
        # 誤った前提に依存しており、実際には成り立たない——アンカーは
        # PALスケルトンの親ボーン(階層上の存在)であり、実チェーンの根元
        # とは無関係な位置にありうる(オーナー実見+実測、work\rd_19_bonespace\
        # 診断: flatapron検体でpelvis head Z≈95に対し、Tail Rootが実際に
        # ウェイトを持つメッシュ頂点群の重心Z≈35、乖離60cm超)。donorチェーンが
        # 担当するメッシュ頂点は常にpolyline自身(アバター実チェーンのworld
        # 位置)の上にあるため、アンカーへの再ルートは行わない(anchor_headは
        # この後のquat再構成の縮退フォールバックでのみ引き続き使用)。
        n_source = len(sway_bones)
        n_donor = len(cloth_chain)
        exact_tails = None  # dev#19 exact-bone-copy: donor[i].tailを転写元
                             # ボーンiのtailで直接上書きする場合のみ設定
                             # (長さn_source。回転計算には使わない、head_pts
                             # のみが計算の正)。

        if n_donor >= n_source:
            # dev#19 exact-bone-copy WP(2026-08-14夜、オーナー仕様): donorが
            # 転写元と同数以上なら、節i<-転写元関節iのhead/tail完全コピー
            # (resample/direct-write関数を経由しない)。
            src_heads = points  # points[i] == 転写元ボーンiのhead(既に検証済み)
            src_tails = [av_point(n, use_tail=True) for n in sway_bones]
            last_head = src_heads[-1]
            seg_vec = tip - last_head  # 最終転写元ボーン自身のベクトル
            if seg_vec.length < 1e-6:
                seg_vec = Vector((0.0, 0.0, 1.0))

            # head_pts: donor各節のhead(index 0..n_donor-1)+その次の点
            # (leaf headまたは単なる延長先、index n_donor)。余剰donor
            # (n_donor > n_source)は tip から seg_vec を繰り返し足して
            # 「最終転写元骨の延長方向へ順に突き出す」(オーナー原文どおり)。
            head_pts = list(src_heads)
            extend_point = tip
            for _k in range(n_donor - n_source):
                head_pts.append(extend_point)
                extend_point = extend_point + seg_vec
            head_pts.append(extend_point)  # 長さ n_donor + 1

            exact_tails = src_tails  # 長さ n_source、donor[0:n_source]のtailに使う
        else:
            # 既存フォールバック(donor不足、「転写元がdonorより多い場合」):
            # 弧長リサンプル(節数完全一致ならtailmatch WPの直写、dev#19裁定
            # 原理5)。無変更。
            polyline = points + [tip]
            n_wanted = n_donor + 1 if leaf_name else n_donor
            resampled = resample_polyline_or_direct(polyline, n_wanted)
            head_pts = list(resampled)

        inv_pal = pal_arm.matrix_world.inverted()
        local_pts = [inv_pal @ p for p in head_pts]
        for i, name in enumerate(cloth_chain):
            b = eb[name]
            b.head = local_pts[i]
            if exact_tails is not None and i < len(exact_tails):
                b.tail = inv_pal @ exact_tails[i]
            else:
                b.tail = local_pts[i + 1] if i + 1 < len(local_pts) else local_pts[i]
        n_repositioned += len(cloth_chain)

        if leaf_name:
            leaf_head = local_pts[n_donor]
            b = eb.get(leaf_name)
            if b is None:
                b = eb.new(leaf_name)
                b.parent = eb[cloth_chain[-1]]
            b.head = leaf_head
            direction = local_pts[n_donor] - local_pts[n_donor - 1]
            if direction.length < 1e-6:
                direction = Vector((0.0, 0.0, 1.0))
            b.tail = leaf_head + direction.normalized() * max(direction.length, 0.5)
            n_leaf += 1

        # ③ donor回転の再構成(dev#19 rotfix WP、上のdocstring参照)。
        # local_pts(pal_arm armature空間、head_local/tail_localと同じ座標系)
        # を既存のchibi_bone_world_head機構と同一の(x,-y,z)変換でUEコンポー
        # ネント空間へ移し、区間ごとの方向ベクトルからquatを再構成する。
        def to_ue(v):
            return (v.x, -v.y, v.z)

        n_pts = len(local_pts)
        seg_dirs = [to_ue(local_pts[i + 1] - local_pts[i]) for i in range(n_pts - 1)]
        chain_dirs = []
        for i in range(n_donor):
            if i < len(seg_dirs):
                chain_dirs.append(seg_dirs[i])
            elif seg_dirs:
                # リーフ無しでチェーン長がresample点数を超える退化ケース
                # (通常発生しない): 直前セグメントの方向を延長する
                # (scurve PROPOSAL §7.1の「先端は自然な延長」の精神)。
                chain_dirs.append(seg_dirs[-1])
            else:
                # n_donor==1かつresample点が1個(退化ケース): アンカーから
                # 先頭donorへの方向で代替する。
                chain_dirs.append(to_ue(local_pts[0] - anchor_head))
        chain_quats = build_donor_chain_quats(chain_dirs)
        for name, q in zip(cloth_chain, chain_quats):
            donor_quats[name] = q

    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"[{TAG}] sway reposition (dev#19 swayfix): {n_repositioned} donor "
          f"bone(s) repositioned, {n_leaf} leaf bone(s) placed, "
          f"{len(donor_quats)} donor quat(s) reconstructed (dev#19 rotfix)")
    return donor_quats


# ------------------------------------------------------------- 揺れ髪(Hairスロット)

def detect_hair_chains(avatar_arm, pal_map, explicit_roots, spring_roots,
                       warnings):
    """揺れ髪に載せるアバターのボーンを {bone名: (root名, 深さ比率0..1)} で返す。

    優先順(2026-07-21ぱん要件):
      1. job.hair_bones(明示指定)
      2. VRM定義のSpringBoneルートのうち**頭の子孫**のもの(自動)。
         尻尾・スカート等の頭外springは除外(頭基準駆動で壊れるため)
      3. フォールバック: 頭の子で非Humanoidかつ子を持つボーン
    """
    mapped = set(pal_map.values())
    head = avatar_arm.data.bones.get(pal_map.get("head", ""))
    if head is None:
        return {}

    def is_head_descendant(bone):
        p = bone.parent
        while p is not None:
            if p == head:
                return True
            p = p.parent
        return False

    if explicit_roots:
        roots = []
        for n in explicit_roots:
            b = avatar_arm.data.bones.get(n)
            if b is None:
                warnings.append(f"hair_bones: bone not found: {n}")
            else:
                roots.append(b)
        src = "explicit"
    elif spring_roots:
        roots, skipped = [], []
        for n in spring_roots:
            b = avatar_arm.data.bones.get(n)
            if b is None:
                continue
            if b.name in mapped:
                continue
            if is_head_descendant(b):
                roots.append(b)
            else:
                skipped.append(n)
        src = "VRM SpringBone definition"
        if skipped:
            print(f"[{TAG}] spring skip (outside head, left rigid): {skipped}")
    else:
        roots = [c for c in head.children
                 if c.name not in mapped and len(c.children) >= 1]
        src = "auto-detected (head children)"
    if roots:
        print(f"[{TAG}] hair-sway source: {src}")
    result = {}
    for root in roots:
        chain = [root] + list(root.children_recursive)
        depth = {root.name: 0}
        for b in chain[1:]:
            depth[b.name] = depth[b.parent.name] + 1
        max_d = max(depth.values()) or 1
        for b in chain:
            result[b.name] = (root.name, depth[b.name] / max_d)
    if result:
        print(f"[{TAG}] hair-sway chains: roots={[r.name for r in roots]} "
              f"bones={len(result)}")
    return result


def load_hair_chains(hair_refskel_path):
    """バニラ髪RefSkeletonから揺れチェーン(長さ2以上の連鎖)を導出する。
    返り値: (refskel dict, [[root, ..., tip], ...])"""
    import json as _json
    with open(hair_refskel_path, encoding="utf-8") as f:
        van = _json.load(f)
    hair_names = [n for n in van if n.startswith("hair_")]
    children = {}
    for n in hair_names:
        p = van[n]["parent"]
        if p and p.startswith("hair_"):
            children.setdefault(p, []).append(n)
    roots = [n for n in hair_names
             if not (van[n]["parent"] or "").startswith("hair_")]
    chains = []
    for r in sorted(roots):
        chain = [r]
        cur = r
        while children.get(cur):
            cur = sorted(children[cur])[0]
            chain.append(cur)
        if len(chain) >= 2:
            chains.append(chain)
    print(f"[{TAG}] vanilla hair: {len(hair_names)} bones, "
          f"{len(chains)} sway chains")
    return van, chains


def add_sway_hair_bones(pal_arm, hair_refskel_path):
    """バニラ髪のhair_01..09を、チビ頭位置+バニラの頭相対オフセットに新造する。
    バインド位置=実行時のアニメ駆動位置に一致させる(頭相対を厳密保存する
    平行移動なので、ゲーム内でレスト時のズレがゼロになる)。"""
    import json as _json

    from mathutils import Matrix, Quaternion
    with open(hair_refskel_path, encoding="utf-8") as f:
        van = _json.load(f)

    world = {}

    def ue_world(name):
        if name in world:
            return world[name]
        b = van[name]
        q = Quaternion((b["quat"][3], b["quat"][0], b["quat"][1], b["quat"][2]))
        p = Vector(b["pos"])
        if b["parent"] is None or b["parent"] not in van:
            world[name] = (q, p)
        else:
            pq, pp = ue_world(b["parent"])
            world[name] = (pq @ q, pp + pq @ p)
        return world[name]

    M = Matrix(((1, 0, 0), (0, -1, 0), (0, 0, 1)))
    Minv = M.inverted()

    def to_blender(name):
        uq, up = ue_world(name)
        return (M @ uq.to_matrix() @ Minv).to_quaternion(), M @ up

    # 頭相対オフセットを保存する平行移動量(チビ頭 − バニラ髪SKの頭)
    _, van_head_pos = to_blender("head")
    chibi_head = (pal_arm.matrix_world
                  @ pal_arm.data.bones["head"].head_local)
    delta = chibi_head - van_head_pos

    bpy.ops.object.select_all(action="DESELECT")
    pal_arm.select_set(True)
    bpy.context.view_layer.objects.active = pal_arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = pal_arm.data.edit_bones
    inv_arm = pal_arm.matrix_world.inverted()
    made = 0
    for name in sorted(n for n in van if n.startswith("hair_")):
        if name in eb:
            continue
        q, p = to_blender(name)
        b = eb.new(name)
        b.head = (0, 0, 0)
        b.tail = (0, 4, 0)
        b.matrix = inv_arm @ Matrix.LocRotScale(p + delta, q, Vector((1, 1, 1)))
        parent = van[name]["parent"]
        if parent in eb:
            b.parent = eb[parent]
        made += 1
    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"[{TAG}] sway hair bones created: {made} (delta={tuple(round(v,1) for v in delta)})")
    return made > 0


def assign_hair_chains(pal_arm, avatar_arm, hair_bones, sway_chains):
    """アバター髪ボーン → バニラ揺れチェーンのボーン の割当表を作る。
    アバターのチェーン(root)ごとに最寄りのバニラチェーンを選び、
    深さ比率でチェーン内の対応ボーン(根本〜先端)に載せる。"""
    chain_by_root = {}
    for chain in sway_chains:
        b = pal_arm.data.bones.get(chain[0])
        if b is not None:
            chain_by_root[chain[0]] = (
                chain, pal_arm.matrix_world @ b.head_local)
    if not chain_by_root:
        return {}
    assignment = {}
    root_to_chain = {}
    for av_name, (root_name, ratio) in hair_bones.items():
        if root_name not in root_to_chain:
            rb = avatar_arm.data.bones.get(root_name)
            rpos = avatar_arm.matrix_world @ rb.head_local
            nearest = min(chain_by_root.values(),
                          key=lambda cv: (cv[1] - rpos).length)
            root_to_chain[root_name] = nearest[0]
            print(f"[{TAG}] hair chain: {root_name} -> {nearest[0][0]}"
                  f"..{nearest[0][-1]}")
        chain = root_to_chain[root_name]
        idx = min(int(ratio * len(chain)), len(chain) - 1)
        assignment[av_name] = chain[idx]
    return assignment


def split_hair_mesh(meshes, hair_bones):
    """髪頂点(髪ボーン合計ウェイト>閾値)を各メッシュから分離し、
    1つの HairSway オブジェクトに統合して返す。
    分離断片はbefore/afterの集合差分で確実に捕捉する(名前推測は
    ViewLayer外の取り残しを生む — flatv3揺れ髪WIPで実害確認済みの修正)。"""
    fragments = []
    survivors = []
    for obj in meshes:
        idx = {vg.index for vg in obj.vertex_groups if vg.name in hair_bones}
        if not idx:
            survivors.append(obj)
            continue
        sel = [v.index for v in obj.data.vertices
               if sum(g.weight for g in v.groups if g.group in idx)
               > HAIR_SPLIT_THRESHOLD]
        if not sel:
            survivors.append(obj)
            continue
        if len(sel) == len(obj.data.vertices):
            fragments.append(obj)  # メッシュ丸ごと髪
            continue
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        for i in sel:
            obj.data.vertices[i].select = True
        before = set(bpy.data.objects)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.separate(type="SELECTED")
        bpy.ops.object.mode_set(mode="OBJECT")
        new_frags = [o for o in set(bpy.data.objects) - before
                     if o.type == "MESH"]
        fragments.extend(new_frags)
        survivors.append(obj)
    if not fragments:
        return survivors, None
    bpy.ops.object.select_all(action="DESELECT")
    ok = 0
    for f in fragments:
        try:
            f.select_set(True)
            ok += 1
        except RuntimeError:
            print(f"[{TAG}][WARN] fragment is outside the ViewLayer: {f.name}")
    if ok == 0:
        return survivors, None
    bpy.context.view_layer.objects.active = fragments[0]
    if ok > 1:
        bpy.ops.object.join()
    hair_obj = bpy.context.view_layer.objects.active
    hair_obj.name = "HairSway"
    if hair_obj.data:
        hair_obj.data.name = "HairSway"
    n = len(hair_obj.data.vertices)
    print(f"[{TAG}] hair split: {n} verts -> HairSway")
    return survivors, hair_obj


# ------------------------------------------------------------- ウェイト移植

def attach_orphan_roots(avatar_arm, pal_map):
    """孤立ルート(parent=Noneかつ d2p_skeleton_root以外)を、レスト姿勢の
    ワールド座標で最も近い「マップ済み(=RefSkeletonに実在する)」ボーンへ
    子として接続する。

    背景(2026-07-26): NDMF/Modular AvatarのMerge Armatureが、対応先の
    無い揺れ物サブリグ(胸ゆれ・スカート等、名前が`Foo$<GUID>`形式)を、
    本体骨格へ実際のボーン親子関係としては接続せずに取り込む場合がある。
    その結果 build_group_targets() の祖先walkがそのサブリグの中で尽きて
    しまい、標準骨格側へウェイトを合算できない(agyo検体で実測)。

    接続は EditBone.parent の張り替えのみで、use_connect は付けない。
    Blenderの EditBone.head/tail はアーマチュア空間の絶対座標であり
    parentが何であっても値は変化しない(use_connect時のみ子headが
    強制的に親tailへ一致させられる)。また対象ボーンはこの時点で
    ポーズ変換(matrix_basis)を一切受けていないレスト状態なので、
    後続のpose計算(PoseBone.matrix)もparentの変更では変わらない。
    よってこの処理はメッシュ・レスト姿勢を一切動かさない。
    """
    mapped_names = set(pal_map.values())
    bones = avatar_arm.data.bones
    # 既にマップ済みのボーン(例: FBXのeRoot挿入でHipsがparent=Noneになるケース)は
    # そもそも救済不要(build_group_targetsがinv.get()で直接解決する)。
    # 除外しないと「自分自身への接続」という無意味な結果になる(2026-07-26、
    # jinbe再検証で実測)。
    orphan_roots = [b.name for b in bones
                    if b.parent is None and b.name != "d2p_skeleton_root"
                    and b.name not in mapped_names]
    if not orphan_roots:
        return
    candidates = [b.name for b in bones if b.name in mapped_names]
    if not candidates:
        print(f"[{TAG}][WARN] orphan root connection: no mapped candidate bone "
              f"({orphan_roots}) — passing through with unknown ancestor")
        return

    cand_world = {n: _bone_world(avatar_arm, n) for n in candidates}
    orphan_world = {n: _bone_world(avatar_arm, n) for n in orphan_roots}
    nearest_of = {
        name: min(candidates, key=lambda n: (cand_world[n] - orphan_world[name]).length)
        for name in orphan_roots
    }

    bpy.ops.object.select_all(action="DESELECT")
    avatar_arm.select_set(True)
    bpy.context.view_layer.objects.active = avatar_arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = avatar_arm.data.edit_bones
    for name, nearest in nearest_of.items():
        eb[name].use_connect = False
        eb[name].parent = eb[nearest]
    bpy.ops.object.mode_set(mode="OBJECT")
    for name, nearest in nearest_of.items():
        dist = (cand_world[nearest] - orphan_world[name]).length
        print(f"[{TAG}] orphan root attach: {name} -> {nearest} (dist={dist:.2f})")


def build_group_targets(avatar_arm, pal_map, merge_fingers):
    """アバター各ボーン → 最終パルグループ名 の対応表を作る。
    マップ外ボーンは最寄りのマップ済み祖先へ。指統合オプションはここで畳む。"""
    inv = {v: k for k, v in pal_map.items()}  # 実ボーン名 → パル名
    finger_fold = {}
    if merge_fingers:
        for f in ("thumb", "index", "middle", "ring", "pinky"):
            for s in ("01", "02", "03"):
                for side in ("l", "r"):
                    finger_fold[f"{f}_{s}_{side}"] = f"hand_{side}"

    result = {}
    for bone in avatar_arm.data.bones:
        pal = inv.get(bone.name)
        if pal is None:
            anc = bone.parent
            while anc is not None and anc.name not in inv:
                anc = anc.parent
            if anc is None:
                continue  # rootより上: 拾えない(後段の警告+pelvis救済に任せる)
            pal = inv[anc.name]
        result[bone.name] = finger_fold.get(pal, pal)
    return result


def remap_vertex_groups(obj, group_targets):
    """頂点グループをパル名へ集約する(名前衝突安全な二相方式)。

    dev#234: マップ先が見つからない(unknown ancestor)頂点グループは、
    警告後に重みごと除去する(祖先パルボーンへの畳み込みは行わない)。
    根拠: build_group_targets()は既にavatar_arm.data.bones全件について
    祖先を辿ってpal_mapへの解決を尽くしており(かつattach_orphan_roots()が
    孤立ルートを事前に最寄りのマップ済みボーンへ接続済み)、それでも
    group_targetsに現れないのは (a) 頂点グループ名に対応するボーンが
    アーマチュアに実在しない(ダングリング。マージされたサブリグの残骸等)、
    または (b) ボーンは実在するが祖先を辿っても本当にマップ済みへ到達
    できない、のいずれか。どちらも「畳み込み先の祖先パルボーン」を
    remap_vertex_groups()側で新たに探索し直す余地は無い(同じ探索は
    build_group_targets()が既に尽くしている)。除去せずに残すと、その
    頂点グループが元ボーン名(例: "pelvis001")を保持したままメッシュに
    生存し、dump_avatar_mesh.py がそれを拾ってJSONへ書き出し、
    RefSkeletonに存在しないボーン名として後段のSK注入を全滅させる
    (実報告SB7BAUA5)。除去後は既存のrescue_zero_weight_vertices()
    (全グループ合計ウェイトが閾値未満の頂点をpelvis等へ束縛する既存の
    安全網)に一本化される——これはbuild_group_targets()のコメント
    「rootより上: 拾えない(後段の警告+pelvis救済に任せる)」が元々
    想定していた後始末そのもの。"""
    tmp_prefix = "PAL::"
    acc = {}  # 最終パル名 -> 一時グループ
    unmatched = []
    for vg in list(obj.vertex_groups):
        target = group_targets.get(vg.name)
        if target is None:
            unmatched.append(vg.name)
            obj.vertex_groups.remove(vg)  # dev#234: 畳み込み先が無いので重みごと除去
            continue
        tmp_name = tmp_prefix + target
        tmp = obj.vertex_groups.get(tmp_name)
        if tmp is None:
            tmp = obj.vertex_groups.new(name=tmp_name)
            acc[target] = tmp
        src_idx = vg.index
        tmp_idx = tmp.index
        for v in obj.data.vertices:
            for g in v.groups:
                if g.group == src_idx and g.weight > 0.0:
                    tmp.add([v.index], g.weight, "ADD")
                    break
        obj.vertex_groups.remove(vg)
    for vg in list(obj.vertex_groups):
        if vg.name.startswith(tmp_prefix):
            vg.name = vg.name[len(tmp_prefix):]
    if unmatched:
        print(f"[{TAG}][WARN] group(s) with unknown ancestor ({obj.name}): {unmatched}")
    print(f"[{TAG}] remap: {obj.name} -> {len(acc)} pal groups")
    return len(acc)


def rescue_zero_weight_vertices(obj, target_bone=ZERO_WEIGHT_FALLBACK_BONE, pal_arm=None):
    """全頂点(または無重みの頂点)をtarget_boneへ100%束縛する。
    target_boneの既定はpelvis(従来どおり)。呼び出し側(main())が、非スキン
    メッシュ(帽子等)については元の親ボーンから解決したパルボーン名を渡す。

    dev#1246追記(2026-08-08、座標系ずれ実報告TFVNM33Vの根治・欠陥A): 全頂点が
    orphan(=このメッシュはremap後にパルボーンへのウェイトを1つも持たない
    =元の追従先を完全に失った、log_structure_summary()のno_skin_meshes判定と
    同じ確定的な事実)の場合だけ、メッシュそのものをtarget_boneの現在位置へ
    移動する。Blenderのアーマチュアモディファイアはレスト姿勢では恒等変形
    (どのボーンへ100%ウェイトを置いても静止姿勢の見た目は変わらない)ため、
    束縛先ボーンを差し替えるだけでは画面上の位置は一切動かない——
    「rigidにtarget_boneへ束縛した」という名目と、実際の表示位置が矛盾した
    ままになる。全頂点orphanは元のワールド座標がもはや何の意味も持たない
    (追従先ごと消えた)ことが確定しているケースなので、値を実測に寄せる
    類の修正ではなく、rigid bindの意味(「このボーンに追従する」)と表示位置を
    一致させる構造的な補正として、メッシュをtarget_boneの位置へ引き寄せる。
    一部頂点だけがorphan(通常のウェイト塗り漏れ)の場合は、メッシュの大部分は
    正しい位置にあるはずなので、この移動は行わない(束縛のみ、従来どおり)。
    pal_arm省略時(呼び出し側が渡さない場合)は移動処理自体をスキップする。"""
    orphans = [v.index for v in obj.data.vertices
               if sum(g.weight for g in v.groups) < 0.01]
    if not orphans:
        return
    vg = obj.vertex_groups.get(target_bone)
    if vg is None:
        vg = obj.vertex_groups.new(name=target_bone)
    vg.add(orphans, 1.0, "REPLACE")
    moved = False
    if pal_arm is not None and len(orphans) == len(obj.data.vertices):
        bone = pal_arm.data.bones.get(target_bone)
        if bone is not None:
            target_world = pal_arm.matrix_world @ bone.head_local
            current_center, _ = _mesh_world_bbox_center(obj)
            delta = target_world - current_center
            obj.location += delta
            bpy.context.view_layer.update()
            moved = True
    print(f"[{TAG}] zero-weight rescue: {obj.name}: {len(orphans)} verts -> "
          f"{target_bone}" + (" (mesh relocated to bone position: fully "
          "orphaned, rest-pose rigid bind alone does not move it)" if moved else ""))


def rebind(mesh_objs, pal_arm):
    for obj in mesh_objs:
        for mod in list(obj.modifiers):
            if mod.type == "ARMATURE":
                obj.modifiers.remove(mod)
        obj.parent = pal_arm
        obj.matrix_parent_inverse.identity()
        mod = obj.modifiers.new(name="Armature", type="ARMATURE")
        mod.object = pal_arm
        # 注意(2026-07-26 SX班診断で判明): obj.parent への再代入は
        # parent_type/parent_bone を変更しない(Blenderの仕様)。元がボーン子
        # (parent_type=BONE、静的メッシュがVRM/FBXの特定ボーンへ直接固定されて
        # いたケース)だった場合、ここで親アーマチュアをpal_armへ差し替えても
        # parent_bone は元アバターのボーン名のまま残る。pal_armにはパル標準名
        # (head/pelvis等)しか無いため、その名前はほぼ確実に存在せず、
        # Blenderはボーンオフセットを解決できずに黙って親オブジェクト原点
        # (pal_armの原点=足元)を使う。結果、そのメッシュは骨格原点へ落ちる
        # (このファイル末尾のlog_structure_summary()が検出する「原点取り残し」
        # の実際の発生源）。ここではrebind()の挙動そのものは変えず
        # (CLAUDE.mdの方針: 変換の挙動を変えないこと)、main()側で
        # rebind()呼び出し前に記録したparent_type/parent_boneを使って
        # 事後に検出・警告するだけに留める。


# ------------------------------------------------------------- 構造サマリ(成功時ログ)
# 2026-07-26 SX班: 「変換は成功したが結果が異常」(例: 頭に載っていたはずの帽子が
# 足元・原点付近に落ちる)を、アバター本体を貰わずログだけで診断できるようにする。
# CLAUDE.md「値を寄せて合わせる修正は却下」に従い、絶対座標のしきい値は使わない。
# 判定は2段構え:
#   1) 決定的判定(dangling): 元ファイルでボーン子(parent_type=BONE)だった
#      静的メッシュの親ボーン名が、変換後の骨格に存在しない。これは名前の
#      有無という事実であり、しきい値を一切含まない。上のrebind()コメント
#      で説明した実際の破損メカニズムそのものを検出する。
#   2) 補助的判定(要確認): 「アバター自身の全体バウンディングボックス対角線」を
#      物差しにした相対距離のみを使う。検体ごとにスケール(cm/m、体格)が
#      異なるため、絶対値のしきい値は検体を跨いで意味を持たない。相対値なら
#      「その検体の中で明らかに近すぎる」を検体に依存せず言える。
#      誤検出対策: 正常な脚部も骨格原点(接地点)に近いため、位置だけでなく
#      「スキニングが単一グループに偏っている(=事実上の剛体、真の脚部は
#      複数ボーンへ滑らかに分散する)」の両方が揃った場合のみ警告する。
#      それでも断定はできないため文言は「要確認」に留める(1)と違い、
#      これは統計的な目安であり確定情報ではない。
REL_ORIGIN_ALERT = 0.06  # 全体バウンディングボックス対角線に対する比率(検体非依存)。
SUMMARY_MESH_LIMIT = 20  # 非エンジニアが問い合わせ文面に貼ることを想定した上限。
                         # 超える場合は正常メッシュを省略する(異常候補は件数に
                         # 関わらず全件出す)。


def _mesh_world_bbox_center(obj):
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    n = len(corners)
    if n == 0:
        return Vector((0.0, 0.0, 0.0)), []
    center = Vector((sum(c.x for c in corners) / n,
                      sum(c.y for c in corners) / n,
                      sum(c.z for c in corners) / n))
    return center, corners


def _analyze_skinning(obj):
    """頂点グループへの重み配分から、複数ボーンへ滑らかに分散(スキニング)か、
    単一グループへほぼ全重みが集中(実質的に剛体)かを判定する。"""
    idx_to_name = {vg.index: vg.name for vg in obj.vertex_groups}
    if not idx_to_name:
        return {"n_groups": 0, "dominant": None, "dominant_ratio": 0.0}
    weight_sum = {}
    for v in obj.data.vertices:
        for g in v.groups:
            name = idx_to_name.get(g.group)
            if name is None or g.weight <= 0.0:
                continue
            weight_sum[name] = weight_sum.get(name, 0.0) + g.weight
    total = sum(weight_sum.values())
    if total <= 0.0:
        return {"n_groups": 0, "dominant": None, "dominant_ratio": 0.0}
    dominant = max(weight_sum, key=weight_sum.get)
    ratio = weight_sum[dominant] / total
    n_sig = sum(1 for w in weight_sum.values() if w / total > 0.01)
    return {"n_groups": n_sig, "dominant": dominant, "dominant_ratio": ratio}


def log_structure_summary(meshes, pal_arm, orig_parent_info, material_count,
                          no_skin_meshes=frozenset(), rescue_target=None):
    """成功時にも構造の要点(名前/頂点数/バウンディングボックス中心/スキニング有無/
    静的メッシュの元親)をログへ残し、「原点取り残し」を機械的に検出して警告する。

    no_skin_meshes: remap_vertex_groups()が「0 pal groups」を返した(=remap後の
    頂点グループが1つも無い)メッシュ名の集合。2026-07-26 HF班診断:
    shapell_Osakiの帽子(Beret)・リボン(Ribbon)の実ログはどちらもこの状態
    だった。一方、健全な既存検体(AliciaSolid_vrm-0.51.vrm、指揮者提供の
    実測データ)は12メッシュ全てが1個以上のpal groupを持ち、0件は無い
    (単一ボーンへの剛体スキニング=グループ1・最大配分100%というパターン
    自体は健全な検体にも6件あり、これだけでは異常の印にならないことが
    実測で確認済み)。つまり「remap後に対応するパルボーンへのウェイトが
    1つも無い」(=zero-weight rescueで全頂点がpelvisへ一律救済される)こと
    自体が、距離やグループ数のようなしきい値を介さない事実そのものであり、
    このメッシュのスキニング(≒追従先ボーン)が丸ごと失われたことの決定的
    な証拠になる。dangling(親ボーン参照切れ)と同格の確定判定として扱う。

    rescue_target: {mesh名: 実際にrescue_zero_weight_vertices()で束縛した
    パルボーン名}。2026-07-26 HB班: 元の親ボーンをpal_mapへ解決できた場合は
    pelvis以外のボーンへ束縛されるため、警告文言もそれに合わせて「pelvisへ
    一律固定」から実態(解決できたボーン名)へ差し替える。解決できず従来通り
    pelvisへ落ちた場合は、これまでどおりの文言のまま。"""
    rescue_target = rescue_target or {}
    infos = []
    all_corners = []
    for obj in meshes:
        center, corners = _mesh_world_bbox_center(obj)
        all_corners.extend(corners)
        skin = _analyze_skinning(obj)
        opt = orig_parent_info.get(obj.name, {})
        infos.append({
            "name": obj.name, "vcount": len(obj.data.vertices),
            "center": center, "skin": skin,
            "orig_parent_type": opt.get("parent_type"),
            "orig_parent_bone": opt.get("parent_bone"),
        })
    if not all_corners:
        print(f"[{TAG}][structure] cannot produce a summary with 0 meshes")
        return

    mn = Vector((min(c.x for c in all_corners), min(c.y for c in all_corners),
                 min(c.z for c in all_corners)))
    mx = Vector((max(c.x for c in all_corners), max(c.y for c in all_corners),
                 max(c.z for c in all_corners)))
    size = mx - mn
    diag = size.length
    origin = pal_arm.matrix_world.translation

    # 単位はcm(vp_bl.build_pal_armature()のdocstring「RefSkeleton JSONから
    # パル骨格アーマチュアを構築する(cm単位)」のとおり。step02の
    # global_scale_and_place()でアバターをこのパル骨格スケールへ合わせ済み)
    print(f"[{TAG}][structure] mesh_count={len(infos)} bone_count={len(pal_arm.data.bones)} "
          f"material_count={material_count} overall_bbox=({size.x:.1f},{size.y:.1f},{size.z:.1f})cm "
          f"skeleton_origin=({origin.x:.2f},{origin.y:.2f},{origin.z:.2f})")

    ok_lines, warn_lines = [], []
    for m in infos:
        d = (m["center"] - origin).length
        rel = (d / diag) if diag > 1e-6 else 0.0
        skin = m["skin"]
        is_rigid = skin["n_groups"] <= 1
        dangling = bool(m["orig_parent_type"] == "BONE" and m["orig_parent_bone"]
                        and m["orig_parent_bone"] not in pal_arm.data.bones)
        no_skin = m["name"] in no_skin_meshes
        cx, cy, cz = (round(v, 1) for v in m["center"])
        skin_desc = (f"skinned(groups={skin['n_groups']}, dominant "
                     f"{skin['dominant_ratio']*100:.0f}%)" if skin["n_groups"] > 0
                     else "no weights")
        parent_desc = ""
        if is_rigid:
            if m["orig_parent_type"] == "BONE" and m["orig_parent_bone"]:
                parent_desc = f" orig_parent=bone '{m['orig_parent_bone']}'"
            elif m["orig_parent_type"]:
                parent_desc = f" orig_parent_type={m['orig_parent_type']}"
        detail = (f"[{TAG}][structure]   - {m['name']}: verts={m['vcount']} {skin_desc} "
                  f"center_cm=({cx},{cy},{cz}) rel_dist_from_origin={rel*100:.1f}%{parent_desc}")
        if dangling:
            # 文言注記(2026-07-26): 「骨格原点へ落ちる」と断定していないのは
            # 意図的。負の対照(work/sx_log/negctrl)でこの経路を実際に再現・
            # 確認したところ、rebind()後もBlenderの評価結果自体は元の位置
            # (頭付近)に留まるケースがあり、"必ず原点へ落ちる"とは言い切れな
            # かった。しかし親ボーン参照が新骨格に存在しないという事実は
            # 変わらず、以降の工程(UEへのバインドポーズ書き出し等、この
            # ファイルの管理外)でどう解釈されるかは保証がない。事実
            # (参照切れ)は断定し、結果への言及は「不定」にとどめる
            warn_lines.append(
                f"[{TAG}][WARN][structural anomaly / dangling parent bone reference] {m['name']}: "
                f"in the source file this was rigidly attached directly to bone "
                f"'{m['orig_parent_bone']}' (a bone-child, not skinning), but the converted "
                f"skeleton has no bone of that name, so the reference could not be resolved. "
                f"The position may not have carried over as intended "
                f"(current center is {d:.1f}cm from the skeleton origin, {rel*100:.1f}% of overall "
                f"size. Please visually check the position in the preview image below)")
            warn_lines.append(detail)
        elif no_skin:
            # 確定判定その2(2026-07-26 HF班、指揮者提供のAlicia負例で設計):
            # remap_vertex_groups()後にこのメッシュへ対応するパルボーンの
            # 頂点グループが1つも無かった=元アバターのどのウェイトも
            # 新骨格へ引き継げず、zero-weight rescueで全頂点が救済措置で
            # 束縛された。距離やグループ数のしきい値を一切使わない事実
            # (remapの戻り値が0だったという事実そのもの)なので、dangling
            # 同様に確定情報として扱う。
            #
            # 2026-07-26 HB班追記: 束縛先はもはやpelvis固定とは限らない。
            # 非スキンメッシュ(帽子・リボン等)は元の親ボーンをpal_mapへ解決
            # できていれば(unskinned_source_bone、main()側で解決)そのボーンへ
            # 束縛されるため、その場合は文言を実態(解決できたボーン名)に
            # 合わせる。解決できず従来通りpelvisへ落ちた場合のみ、以前と同じ
            # 「一律固定」の文言を使う("pelvisへ一律固定"は嘘になってはいけない)
            target = rescue_target.get(m["name"], ZERO_WEIGHT_FALLBACK_BONE)
            if target != ZERO_WEIGHT_FALLBACK_BONE:
                warn_lines.append(
                    f"[{TAG}][WARN][structural / non-skinned mesh binding] "
                    f"{m['name']}: after remap, this mesh had zero vertex groups "
                    f"corresponding to a pal bone (a static mesh not skinned in the source "
                    f"avatar). Its original parent bone was traced and resolved to the pal "
                    f"skeleton's '{target}', and bound to it, so position/follow will match "
                    f"that bone (current center is {d:.1f}cm from the skeleton origin, "
                    f"{rel*100:.1f}% of overall size. Please visually check the position in "
                    f"the preview image below)")
            else:
                warn_lines.append(
                    f"[{TAG}][WARN][structural anomaly / skinning lost (0 pal groups)] "
                    f"{m['name']}: after remap, this mesh had zero vertex groups "
                    f"corresponding to a pal bone. The source avatar's weights could not "
                    f"be carried over to any bone in the new skeleton, so all vertices were "
                    f"rescued and rigidly bound to '{ZERO_WEIGHT_FALLBACK_BONE}'. It will not "
                    f"follow the pose, and the position/orientation is likely not as intended "
                    f"(current center is {d:.1f}cm from the skeleton origin, {rel*100:.1f}% of "
                    f"overall size. Please visually check the position in the preview image "
                    f"below)")
            warn_lines.append(detail)
        elif rel < REL_ORIGIN_ALERT and is_rigid:
            warn_lines.append(
                f"[{TAG}][WARN][please check / near origin] {m['name']}: unusually close to "
                f"the skeleton origin relative to other meshes ({rel*100:.1f}% of overall "
                f"size), and skinning is concentrated in a single group. This may indicate a "
                f"lost parent, so a visual check is recommended (this is not confirmed)")
            warn_lines.append(detail)
        else:
            ok_lines.append(detail)

    for w in warn_lines:
        print(w)
    if len(ok_lines) <= SUMMARY_MESH_LIMIT:
        for line in ok_lines:
            print(line)
    else:
        for line in ok_lines[:SUMMARY_MESH_LIMIT]:
            print(line)
        print(f"[{TAG}][structure]   ...and {len(ok_lines) - SUMMARY_MESH_LIMIT} more omitted "
              f"(within normal range: skinned and sufficiently far from the origin)")


# dev#19 R2b-3(2026-08-11、試着室pak実験専用。dev#1363で本流化):
# sway_cloth_bones機構が使えるdonorファミリーの一覧。"{prefix}"(M_/F_)を
# 除いたボーン名テンプレを列挙する(prefixは呼び出し側resolve_sway_donor()が
# 付与)。refskel_suffixが空文字なら従来どおりrefskel_{gender}.json、
# 非空ならrefskel_{suffix}_{gender}.json(extract_vanilla.py
# "sway_extra_family"が抽出する追加ファミリー用)を読む。
#
# donorexp WP(2026-08-11、issue#19、notes_master_1385.md白黒判定の解消):
# refskel_suffixは家系ごとに一意な値(=そのファミリーの辞書キーを小文字化
# したもの)にすること。かつてKigurumi001/Ancient001/HeadEquip062_earの
# 3ファミリーが揃って固定文字列"extra"を共有していたため、
# extract_vanilla.pyが書く出力ファイル名(refskel_extra_{gender}.json)も
# 3ファミリーで衝突し、複数ファミリーを同時抽出すると後勝ちの上書きが起きる
# 構造的バグだった(resolve_sway_chain_entries()のvanilla_dirチェックは
# 「ファイルが存在するか」しか見ないため、上書き後の中身が要求家系のもので
# なくてもすり抜け、後段でボーン欠落によるcore.die()を引き起こす)。
# extract_vanilla.py側もrefskel_output_name()で同じ「家系キー小文字化」規則
# へ揃えたため、ここのrefskel_suffixとextract_vanilla.py側の出力ファイル名は
# 常に一致する(残存する固定名"refskel_extra_*.json"参照はゼロ、grep確認済み
# ——work\rd_19_flight\notes_donorexp.md参照)。
# swayfix WP(dev#19、issue#19、2026-08-11、work\rd_19_anglelimit\PROPOSAL.md
# §7.2-7.4が正本): 各家系の"leaf"キーは、cloth_chain末尾へ追加する**ウェイト
# 無しの実リーフボーン1本**の生名(接頭辞・拡張子なし、chain/siblingsと同じ
# 命名規則で「次の連番」)。PROPOSAL §7.2確定: KawaiiPhysicsのDummyBoneLength
# 経路(BoneForwardAxis依存の直線外挿)が②(先端の前後非対称異常)③(やわ設定の
# 激しい上下振動)の構造原因であり、実子(実リーフボーン)ルートに切り替える
#ことでこの経路自体を迂回する(値調整では治らない、オーナー裁定)。
# vanilla抽出には存在しない合成ボーンのため、extract_vanilla.py側で
# プレースホルダ位置(chain末尾2骨の差分を1節分延長)を合成してrefskel JSONへ
# 追記し(_add_synthetic_leaf_bone())、dev#1378のRefSkeleton引き込み経路
# (vp_refskel_extend.py)で全装備SKへ構造的に登録される。実際のper-avatar
# 位置はstep02側のreposition_sway_donor_chain_and_leaf()が計算し、既存のU21
# chibi_bone_world_head機構でcooked SKへ反映される(新規プラミング不要、
# notes_swayfix.md参照)。
# dev#19 native-donor-rule WP(issue #19、2026-08-14夜): 各家系の
# "native_sim_count"(実シミュレーション対象骨数)は、実機KawaiiPhysicsが
# 参照する共有USkeletonアセット(SK_PalHuman_Skeleton)のNameMapを実測して
# 決めた値(推測値ではない)。測定手順: pipeline\\py\\vp_core.read_names()で
# work\\rd_19_chainprobe\\skel_probe\\SK_PalHuman_Skeleton.uasset(4123名)を
# 読み、各家系の"chain"要素(先頭chain_rootから連番)がリテラル一致する
# 個数を数える(2026-08-14実測。断絶点=最初に不在になった連番の1つ手前)。
# "chain"フィールド自体は既に「native境界で止まる」よう過去のWPで整えられて
# おり(例: OldCloth001は"_08"が非nativeなのでchainが"_07"で止まる、
# tailexclude WPはtail_10/11を実機破綻を理由にchainから除外済み)、いずれの
# 家系も native_sim_count == len(chain) が実測で成立する(2026-08-14確認、
# 全家系分を実測。将来"chain"の定義を変えた場合はこの等式が崩れうるため、
# 値は独立フィールドとして持つ——len(chain)から自動導出しない)。
# "anchor"は家系の実際の親標準ボーン(pelvis直下/head直下)。donor選定の
# 「親一致」条件(pipeline\\py\\sway_native_rule.py)に使う。
SWAY_DONOR_FAMILIES = {
    "OldCloth001": {
        "refskel_suffix": "",
        "chain": [f"OldCloth001_{i:02d}" for i in (4, 5, 6, 7)],
        "siblings": [f"OldCloth001_{i:02d}" for i in (1, 2, 3)],
        "bag": True,
        "leaf": "OldCloth001_08",
        "anchor": "pelvis",
        "native_sim_count": 4,  # NameMap実測2026-08-14: _01〜_07在籍(7)、
                                 # chain=(_04..._07)の4本が全てnative。_08不在
    },
    # Ancient001(エンシェント鎧、腰布waistClothA/B/Cの3チェーン、各4節、
    # thigh_r<-pelvis<-root。R2b-3で実測確認、寄せる本体はAのみ使用しB/Cは
    # ノード不発防止の同梱のみ)。
    "Ancient001": {
        "refskel_suffix": "ancient001",
        "chain": [f"Ancient001_waistClothA_{i:02d}" for i in (1, 2, 3, 4)],
        "siblings": ([f"Ancient001_waistClothB_{i:02d}" for i in (1, 2, 3, 4)]
                     + [f"Ancient001_waistClothC_{i:02d}" for i in (1, 2, 3, 4)]),
        "bag": False,
        "leaf": "Ancient001_waistClothA_05",
        "anchor": "pelvis",
        "native_sim_count": 4,  # NameMap実測2026-08-14: waistClothA_01〜_04
                                 # 在籍(4)、_05不在
    },
    # Kigurumi001(きぐるみ尻尾、pelvis直下8節の単一チェーン。dev#19
    # rd_19_refskel実証(2026-08-11)で全装備SKへのRefSkeleton追加登録が
    # 静的検証済みになったことを受けた8節donor。4節OldCloth001由来の
    # 先端折れ(6->4圧縮)を6->8の余裕で解消する)。兄弟チェーン無し。
    "Kigurumi001": {
        "refskel_suffix": "kigurumi001",
        "chain": [f"Kigurumi001_tail_{i:02d}" for i in range(1, 9)],
        "siblings": [],
        "bag": False,
        "leaf": "Kigurumi001_tail_09",
        "anchor": "pelvis",
        "native_sim_count": 8,  # NameMap実測2026-08-14: tail_01〜_08在籍(8)、
                                 # _09不在(work\rd_19_donorswap\の官能合格構成
                                 # と一致)
    },
    # dev#1375(dev#19 R3統合、耳donor): work\rd_19_ears\PROPOSAL.md §4で
    # 特定した候補(SK_PalHuman、head直下、左右対称、4節=flatapronの耳と
    # 節数完全一致)。HeadEquip*系donorはSK_PalHuman上で性別分岐の無い
    # 共有ボーン(実測: M_/F_接頭辞なし)のため"gendered": Falseとし、
    # chain/siblingsの名前へ接頭辞を付けない。
    #
    # refskel_suffix(donorexp WP、2026-08-11再修正): 導入時点は独自の
    # "headequip062ear"、issue#1384修正でKigurumi001/Ancient001と同じ共有
    # 固定名"extra"に揃えた時期があったが、これが3ファミリー共有名衝突の
    # 原因そのものだった(上のSWAY_DONOR_FAMILIES docstring参照)。donorexp
    # WPで家系ごとの一意名(このファミリー自身のキーを小文字化しただけの
    # "headequip062_ear")へ戻し、かつ衝突原因を構造的に除去した。
    "HeadEquip062_ear": {
        "refskel_suffix": "headequip062_ear",
        "gendered": False,
        "chain": [f"HeadEquip062_ear_0{i}_l" for i in (1, 2, 3, 4)],
        "siblings": [f"HeadEquip062_ear_0{i}_r" for i in (1, 2, 3, 4)],
        "bag": False,
        "leaf": "HeadEquip062_ear_05_l",
        "anchor": "head",
        "native_sim_count": 4,  # NameMap実測2026-08-14: ear_01〜_04_l/_r在籍
                                 # (4)、_05不在(想定"5"は誤り。2026-08-14夜
                                 # native-donor-rule WPで実測訂正)。flatapron
                                 # 耳(3帯)はnative(4)>=n_source(3)+1を境界値
                                 # で満たし現行構成のまま無変更
    },
    # donorexp WP(2026-08-11、issue#19、要件3): 骨盤系スカート用donor拡充。
    # work\rd_19_haori\sk_palhuman_bones.json実測(4079骨中、pelvis直下158骨)
    # で、Player/Outfit系のバニラ装備家系のうちpelvis直下の独立チェーン数が
    # 最多(4チェーン: 01(2節)/03(1節)/04(2節)/06(4節)、他候補は最大でも
    # OldCloth001の2チェーンまで)だった候補。深い方(06、4節)をchainに、
    # 残り3チェーンをsiblingsに入れる(Ancient001と同じ配置方針:
    # chain=比例配分の本体、siblings=ノード不発防止の同梱のみ)。
    # 選定根拠の候補比較はwork\rd_19_flight\notes_donorexp.md参照。
    "Hunter001": {
        "refskel_suffix": "hunter001",
        "chain": [f"Hunter001_{i:02d}" for i in (6, 7, 8, 9)],
        "siblings": [f"Hunter001_{i:02d}" for i in (1, 2, 3, 4, 5)],
        "bag": False,
        "leaf": "Hunter001_10",
        "anchor": "pelvis",
        "native_sim_count": 4,  # NameMap実測2026-08-14: Hunter001_06〜_09
                                 # 在籍(4)、_10不在
    },
    # tailmatch WP(dev#19、issue#19、2026-08-12、work\rd_19_flight\briefs\
    # tailmatch_probe.mdが正本、裁定「原理5: donor選定は節数完全一致を
    # 最優先」の実証): flataponのしっぽ(Tail Root..Tail.005、6節)と節数が
    # 完全一致する中央チェーンdonor。work\rd_19_donorcatalog\catalog.json
    # 全数調査(第一候補)で特定。SK_NPC_GrassBoss001_Skin001(NPC専用メッシュ、
    # 共有骨格SK_PalHuman_Skeletonに同梱)由来で、命名は01,02,03,04,05,10と
    # 欠番があるが親子は単一の直鎖(root=tail_01<-pelvis、以降tail_02..05..10
    # の順で一直線、work\rd_19_flight\notes_tailmatch.md実測で確認済み)。
    # SK_PalHuman_Skeleton自体は4079骨でvp_core.find_refskeleton()の
    # フィンガープリント上限(count<=400)を超えるため直接抽出できないが、
    # 実際のNPCメッシュSK(181骨、Male/Female分岐なし共有アセット)から
    # 同じ機構で抽出できることを実測確認済み(HeadEquip062_earと同型の
    # gendered=False)。
    #
    # tailexclude WP(dev#19、issue#19、2026-08-13、
    # work\rd_19_pbmap\TAIL_ROOT_FALLBACK_ROOTCAUSE_20260813.md・
    # TAIL_VISUAL_VERDICT_20260813.mdが正本): tail_10・tail_11をchain/leafから
    # 除外した(旧chainは(1,2,3,4,5,10)、旧leafは"..._11")。真因調査により、
    # UE FNameの末尾数字自動分割仕様(先頭ゼロ無しの2桁以上の連番は
    # ベース名+数値の別内部表現へ分割され、先頭ゼロ付き"01"〜"09"は分割が
    # 抑制される)のため、main.luaの名前ベースのボーン参照解決がtail_10/11
    # だけで失敗し、実機で安定しない基準点(Root相当)へフォールバックすること
    # が高確度で判明した(前者ドキュメント)。さらに実機目視確認(後者
    # ドキュメント)で、歩行中にしっぽが画面上で脈絡なく巨大化・カメラへの
    # 異常接近・ほぼ消失を繰り返す、実際にゲーム内で見える破綻であることが
    # 確定した。tail_10はSK_NPC_GrassBoss001_Skin001由来のvanilla実骨だが、
    # 除外により物理チェーンがtail_05までに短縮される(揺れの可動範囲が
    # 狭まる)というトレードオフを許容してでも、「壊れたデータを使うより、
    # 健全な範囲だけで正しく動かす」ことを優先した(オーナー承認済み、値を
    # 寄せて誤魔化す対処ではなく構造的なchain/leaf定義の変更)。
    # 新leaf(次の連番、tail_05の次)="..._06"——先頭ゼロ付きのため、
    # 上記FName分割問題を新たに引き起こさない。
    "NPC_GrassBoss001_Skin001_tail": {
        "refskel_suffix": "npc_grassboss001_skin001_tail",
        "gendered": False,
        "chain": [f"NPC_GrassBoss001_Skin001_tail_{i:02d}" for i in (1, 2, 3, 4, 5)],
        "siblings": [],
        "bag": False,
        "leaf": "NPC_GrassBoss001_Skin001_tail_06",
        # dev#19 weight-direct-assign WP(2026-08-14、オーナー裁定「元々ウェイト
        # が乗っているボーンがn本なら、donorはn+1本以上でなければならない」):
        # しっぽの実転写元は6帯(Tail Root+Tail.001-005)で、chainは5節しかない
        # ため、ちょうど1本(旧leaf="..._06")を可動donorへ転用しないと全帯が
        # 収まらない。転用すると"..._06"に実ウェイトが乗るため、揺れの末端を
        # 表す新しいウェイト無しの実リーフボーンがさらに先に要る。"leaf2"は
        # そのための追加合成リーフ(先頭ゼロ2桁"_07"、UE FName分割地雷
        # ("_10"/"_11"問題、tailexclude WP参照)を踏まない命名)。
        # resolve_sway_chain_entries()のspillover分岐でのみ使われ、それ以外の
        # 家系(leaf2未定義)では①n_source<=n_donorなら1:1で足りる、
        # ②n_source>n_donorならアンカー畳み込みへ従来どおりフォールバックする。
        #
        # dev#19 native-donor-rule WP(2026-08-14夜、issue #19根因確定)による
        # 訂正: 上記leaf2スピルオーバー機構は、"_06"/"_07"がSK_PalHuman_Skeleton
        # のNameMapに実在しない(native_sim_count=5、下記)という事実を見落として
        # いた欠陥設計だった——KPは共有Skeletonアセットを実際に歩くため、"_06"へ
        # 昇格したウェイトは一度も物理に入らず、実効鎖terminal(tail_05、native
        # 境界そのもの)がKPの終端回転凍結仕様により凍結し、それが逆に
        # ウェイト付きボーンとして視認可能な破綻(先端の異常固着)になっていた。
        # native-donor-rule(pipeline\py\sway_native_rule.py)がpick_family()で
        # native_sim_count>=n_source+1を満たす家系(6帯尻尾ならKigurumi001)を
        # 優先選定するため、この家系(native=5)は6帯尻尾には最早選ばれない
        # (qualifiesしない)。leaf2機構自体は後方互換のため削除しないが、
        # 事実上のフォールバック専用(qualifiesする家系が他に無い場合のみ
        # 到達)という位置づけになる。
        "leaf2": "NPC_GrassBoss001_Skin001_tail_07",
        "anchor": "pelvis",
        "native_sim_count": 5,  # NameMap実測2026-08-14: tail_01〜_05在籍(5)、
                                 # _06/_07/_10/_11は不在(_10/_11はtailexclude
                                 # WPにより既にchainから除外済みで無関係)
    },
}


def _resolve_family_by_name(fam, gender):
    """SWAY_DONOR_FAMILIES の1エントリ(dict)をgender別の実ボーン名列へ
    解決する共通ロジック(dev#1375で resolve_sway_donor() から抽出)。

    fam["gendered"](省略時True)がFalseなら性別接頭辞を付けない
    (HeadEquip*系のような、SK_PalHuman上で性別分岐が無い共有donor家系用、
    dev#1375追加)。

    戻り値: (cloth_chain, extra_bones, refskel_name)
      cloth_chain  … 比例配分先のdonorチェーン本体(接頭辞付き完全ボーン名。
                      gendered=Falseならfamの生の名前そのまま)
      extra_bones  … ノード不発防止のため追加でスケルトンへ含める同ファミリーの
                      他ボーン(ウェイトは載せない。bag込み)
      refskel_name … build_pal_armature()へ渡すbindpose数値ファイル名
                      (vanilla/配下、OldCloth001は従来どおりrefskel_{gender}.json、
                      拡張ファミリーはextract_vanilla.py "sway_extra_family"が
                      書き出すrefskel_{suffix}_{gender}.json)
    """
    gendered = fam.get("gendered", True)
    prefix = ("M_" if gender == "Male" else "F_") if gendered else ""
    cloth_chain = [f"{prefix}{b}" for b in fam["chain"]]
    # KawaiiPhysicsノードは複数チェーンをまとめて駆動する(実装ABPの実測、
    # OldCloth001は01/04/bagの3ノード、Ancient001はwaistClothA/B/Cの3ノード)。
    # ルートボーン欠落でノードごと不発になる事故を防ぐため、ウェイトを
    # 載せない他チェーンのボーンも含め同ファミリーは全てスケルトンに入れる
    extra_bones = [f"{prefix}{b}" for b in fam["siblings"]]
    if fam["bag"]:
        bag = ("M_Outfit_OldCloth001_bag_01" if gender == "Male"
               else "F_OldCloth001_bag_01")
        extra_bones.append(bag)
    refskel_name = (f"refskel_{fam['refskel_suffix']}_{gender.lower()}.json"
                     if fam["refskel_suffix"] else f"refskel_{gender.lower()}.json")
    return cloth_chain, extra_bones, refskel_name


# earleaf WP(dev#19、issue#19、work\rd_19_leafcheck\RESULT.md欠陥A正本):
# L/R対称家系(HeadEquip062_ear等)の名前接尾辞規約("_l"/"_r"末尾)を扱う
# 共通ヘルパー。pipeline\py\extract_vanilla.py 側にも意図的に重複定義
# (bpy非依存モジュールへ素直にimportできない——SWAY_DONOR_FAMILIES/
# SYNTHETIC_LEAF_BONES自体の既存の重複運用と同じ、両ファイルの冒頭コメント
# 参照。2箇所を変更するときは規約(「末尾"_l"/"_r"」)の一致を保つこと)。
def _sway_side_suffix_of(name):
    """nameが"_l"または"_r"で終わっていればその接尾辞("_l"/"_r")を返す。
    どちらでもなければNone(左右の概念を持たない家系、例: OldCloth001)。"""
    if name.endswith("_l") or name.endswith("_r"):
        return name[-2:]
    return None


def _sway_with_side_suffix(name, suffix):
    """name末尾の"_l"/"_r"をsuffixへ置換する(nameがその接尾辞を持たない、
    またはsuffixがNoneなら無変更で返す)。"""
    if suffix is None:
        return name
    if name.endswith("_l") or name.endswith("_r"):
        return name[:-2] + suffix
    return name


def resolve_sway_leaf(fam, gender, chain=None, key="leaf"):
    """swayfix WP(dev#19、issue#19): SWAY_DONOR_FAMILIESの1エントリから、
    cloth_chain末尾に追加する実リーフボーン(ウェイト無し)の完全ボーン名を
    返す。famが"leaf"キーを持たなければNone(未対応家系。リーフ追加をスキップ
    し、①の再配置のみ適用する後方互換動作——DummyBoneLength=0化の影響を
    受ける前の旧来動作のまま残る)。

    key(dev#19 weight-direct-assign WP、2026-08-14): 既定"leaf"。
    "leaf2"を渡すと、旧leafを可動donorへ転用した後段の第2合成リーフ
    (fam["leaf2"])を同じ左右接尾辞規則で解決する(resolve_sway_chain_entries()
    のspillover分岐専用)。fam[key]が無ければNoneを返す(呼び出し元同様)。

    命名・接頭辞規則は_resolve_family_by_name()のcloth_chain/extra_bonesと
    同一(fam.get("gendered", True)でM_/F_接頭辞の要否を判定)。

    earleaf WP(dev#19、issue#19、work\\rd_19_leafcheck\\RESULT.md欠陥A):
    fam["leaf"]はL/R対称家系(HeadEquip062_ear等)ではL側決め打ちの1文字列
    しか持たない(chain="..._l"、siblings="..._r"という設計のため)。
    chain(実際に使われるdonorチェーン、接頭辞込みの完全ボーン名列、
    resolve_sway_chain_entries()が解決したexplicit_chain/cloth_chain)を
    渡すと、その末尾ボーンの左右接尾辞(_l/_r)へ合わせてleaf名の接尾辞を
    書き換える——L側donorが選ばれたエントリにはL側leaf、R側donorが選ばれた
    エントリにはR側leafが一意に対応するようになる。旧実装はL/R問わず常に
    同じ"..._05_l"を返しており、sway_assign.py `_family_prefix()` がL/R
    接尾辞を正規化で剥がしてfamily名を共有させる設計と組み合わさることで、
    R側の計算結果がL側リーフの位置を無条件上書きするキメラ配置を起こして
    いた(RESULT.md §2-3)。chain省略時・chainが左右接尾辞を持たない家系
    (OldCloth001等)は従来どおり無変更(既定動作に対して無退行)。
    """
    leaf = fam.get(key)
    if not leaf:
        return None
    gendered = fam.get("gendered", True)
    prefix = ("M_" if gender == "Male" else "F_") if gendered else ""
    leaf_name = f"{prefix}{leaf}"
    if chain:
        chain_side = _sway_side_suffix_of(chain[-1])
        leaf_name = _sway_with_side_suffix(leaf_name, chain_side)
    return leaf_name


def resolve_sway_donor(job, gender):
    """dev#19本流化(2026-08-11、dev#1363): sway_cloth_bones機構が使う
    donorファミリーをjob.jsonの指定から解決する。

    R2b-3実験時点ではこのロジックはmain()内にインライン展開されていたが、
    bpy/Blender状態に一切触れない純粋関数のため、main()から抽出して単体
    テスト可能にした(振る舞いは実験版と完全に同一、抽出のみ)。

    job.json "sway_cloth_donor_family" で選択(未指定時は既定"OldCloth001"、
    本関数導入前・R2b-3拡張導入前と一字一句同じ挙動=無退行)。
    "sway_cloth_donor_family" に SWAY_DONOR_FAMILIES 未収載の値が指定されたら
    即座にdie()する(known値一覧つき)。単一チェーン仕様(旧sway_cloth_bones)
    専用のエントリポイントであり続ける——複数チェーン(job["sway_chains"]、
    dev#1375)は _resolve_family_by_name() を直接使い、未登録familyを
    die()ではなくスキップで扱う(resolve_sway_chain_entries()参照)。

    戻り値: (cloth_chain, extra_bones, refskel_name)(_resolve_family_by_name()
    と同じ、docstring参照)。
    """
    donor_family = job.get("sway_cloth_donor_family", "OldCloth001")
    fam = SWAY_DONOR_FAMILIES.get(donor_family)
    if fam is None:
        core.die(TAG, f"sway_cloth_donor_family: unknown family {donor_family!r} "
                      f"(known: {sorted(SWAY_DONOR_FAMILIES)})")
    return _resolve_family_by_name(fam, gender)


def sway_cloth_target_indices(n_source, n_donor, bend_weights=None):
    """dev#19 R2a-v2(2026-08-11、本流化dev#1355): sway_cloth_bones機構の
    節写像(比例配分の低レベル関数)。

    ソース側ボーン列(chain順)のindex(0起点)を donor側チェーン(chain順)
    のindexへ比例配分で対応させる、純粋関数(Blender/bpy非依存、単体テスト
    容易)。戻り値: 長さn_sourceのlist、各要素は0..n_donor-1のdonor index。

    旧実装(`cloth_chain[min(i, n_donor-1)]`、恒等写像+末尾クランプ)は
    n_source > n_donorのとき、末尾側の(n_source - n_donor + 1)本の
    ソースボーンが**最終donor1本だけへ縮退**していた(6->4の実例:
    Tail.003/004/005の3本がOldCloth001_07のみへ集約、work\\rd_19_r2a2\\
    RESULT.md診断表参照)。本関数は代わりに `round(i * n_donor / n_source)`
    で線形の比例配分を行い、最大でも `ceil(n_source / n_donor)` 本までしか
    同一donorへ集約しない(6->4の実例では3本->2本への改善: 実際の対応は
    [0,1,1,2,3,3]=donor0に1本・donor1に2本・donor2に1本・donor3に2本、
    tests\\coverage\\test_step02_sway_cloth_mapping_dev19r2a2.py参照)。

    n_source == n_donorのとき常に恒等写像(target_idx == i、旧実装と完全
    一致)。この関数自体は「アンカーを1本消費する」意味論を持たない
    (dev#1355のアンカー規則は呼び出し側 sway_cloth_bone_targets() が
    n_source-1で本関数を呼ぶことで実現する。関数自体の粒度は変更しない
    ことで、旧13ケースのテストをそのまま維持できる)。

    bend_weights(dev#19 rotfix WP、項目2「屈曲考慮ウェイト配分」、
    work\\rd_19_scurve\\PROPOSAL.md §3.4/§7.2が正本): Noneなら上記の旧来の
    等重み比例配分(byte-for-byte同一の計算式、この引数を追加する前の
    全呼び出し元・全既存テストへの無退行を構造的に保証する)。非Noneの
    場合は長さn_sourceの非負floatのlist(各ソースボーンiの「屈曲量」、
    通常はcompute_chain_bend_weights()の出力を渡す)を受け取り、屈曲が
    急な箇所ほど大きな「配分幅」を割り当てることで、屈曲の反転点で隣接
    2骨が同一donorへ圧縮されるのを避ける(scurve PROPOSAL §3.4で確認された
    「反転点の2骨が同一donor骨へ集約され、メッシュ追従が悪化する」問題への
    構造的な対処。個々の閾値やdonor数へ値を合わせ込む修正ではない)。
    重みは `1.0 + 屈曲度/180.0`(屈曲0°で1.0、180°で2.0、屈曲の最大理論値
    180°による正規化——実測値への値合わせではない)を各ソースボーンの
    「幅」とし、幅の累積(重み付き弧長相当)を等分割してdonor indexへ丸める。
    """
    if n_donor <= 0:
        return []
    if n_source <= 0:
        return []
    if bend_weights is None:
        out = []
        for i in range(n_source):
            idx = round(i * n_donor / n_source)
            idx = max(0, min(idx, n_donor - 1))
            out.append(idx)
        return out

    if len(bend_weights) != n_source:
        raise ValueError(
            f"bend_weights length ({len(bend_weights)}) must equal "
            f"n_source ({n_source})")
    weights = [1.0 + max(0.0, w) / 180.0 for w in bend_weights]
    cum = [0.0]
    for w in weights:
        cum.append(cum[-1] + w)
    total = cum[-1]
    out = []
    for i in range(n_source):
        mid = (cum[i] + cum[i + 1]) / 2.0
        idx = int(mid * n_donor / total)
        idx = max(0, min(idx, n_donor - 1))
        out.append(idx)
    return out


# sway_cloth_bone_targets()の戻り値でアンカー(揺れない、donorチェーンの
# 親ボーンへ束縛)を表す番兵。donor chainの実インデックス(0..n_donor-1)と
# 衝突しない負値にしている。
SWAY_CLOTH_ANCHOR = -1


def sway_cloth_bone_targets(n_source, n_donor, bend_weights=None):
    """dev#1355(2026-08-11、オーナー裁定): sway_cloth_bones機構のアンカー
    1階層規則。

    VRCPhysBoneの意味論は「搭載ボーン自身はアンカーで揺れない、子から
    揺れる」。dev#19 R2実証時点(sway_cloth_target_indices()単体)は
    ソースチェーン先頭(PhysBone搭載ボーン相当)をdonorチェーン先頭
    (実際に揺れる最初の節、_04)へ直接割り当てており、PhysBone意味論より
    1階層浅かった。

    本関数はソース側ボーン列(chain順、index0がPhysBone搭載ボーン=アンカー
    相当)を受け取り:
    - index0(先頭) -> SWAY_CLOTH_ANCHOR(donorチェーンの親、pelvis側の
      アンカーへ畳む。呼び出し元はこの番兵を実際のアンカーボーン名へ解決
      する)
    - index1以降(2節目以降、実際に揺れる部分) -> donorチェーン
      (0..n_donor-1)へ sway_cloth_target_indices(n_source-1, n_donor) で
      比例配分

    戻り値: 長さn_sourceのlist。要素はSWAY_CLOTH_ANCHOR、または
    0..n_donor-1のdonor index。

    n_source==1(チェーンが1本のみ、子が無い)の場合、PhysBone意味論に
    忠実に全体をアンカー(揺れなし)として扱う([SWAY_CLOTH_ANCHOR]を返す)。
    これは意図的な選択で、「単体のボーンなら揺れが無いより多少でもある方
    がまし」という妥協はしていない——搭載ボーン自身は揺れないという意味論
    を最小ケースでも一貫させるため(1本しかないチェーンをsway_cloth_bones
    に指定すること自体が実験機構の想定外の使い方であり、実害を心配する
    実運用ケースは無い)。

    bend_weights(dev#19 rotfix WP): 非Noneの場合、長さn_sourceのlist
    (index0=アンカー自身の屈曲量、通常compute_chain_bend_weights()の
    そのままの出力)を受け取り、index0を除いた残り(sway_cloth_target_indices
    へ渡すn_source-1本ぶん)をそのまま下層へ引き継ぐ。
    """
    if n_source <= 0 or n_donor <= 0:
        return []
    if n_source == 1:
        return [SWAY_CLOTH_ANCHOR]
    tail_bend = bend_weights[1:] if bend_weights is not None else None
    tail = sway_cloth_target_indices(n_source - 1, n_donor, bend_weights=tail_bend)
    return [SWAY_CLOTH_ANCHOR] + tail


def sway_cloth_weight_targets_direct(n_source, n_donor):
    """dev#19 weight-direct-assign WP(2026-08-14、オーナー裁定): ウェイト
    転写先決定の「シンプルに1対1」割当。

    背景(work\\rd_19_earweight\\probe_targets.txt正本): sway_cloth_bone_targets()
    (比例配分、内部はsway_cloth_target_indices())は、転写元ボーン数より
    donorチェーンが長いとき、離散丸めの必然としてdonorの一部を「誰からも
    ウェイトが来ない」空ボーンにしてしまう。耳donor(ear_01_l/ear_02_l/
    ear_03_l/ear_04_l、n_donor=4)に実転写元2本(n_source_real=2)を比例配分
    すると target_indices=[1, 3] となり、ear_01_l/ear_03_l が**先頭でも末尾
    でもない位置**で空になる(耳メッシュ根元の支点ずれの原因、オーナー
    目視確認済み)。

    第1次裁定:「donorが多いのは構わない。転写元と同数へシンプルに1対1で
    割り当てる」。第2次裁定(同日、上書き):「元々ウェイトが乗っている
    ボーンがn本なら、donorはn+1本以上でなければならない」——アンカー
    畳み込み(dev#1355)で先頭帯を剛体化すると、step01では起き得ない不快な
    折れ曲がりが発生しうる(オーナーがBlenderポーズ比較で確認)。このため
    本関数は「先頭帯(PhysBone搭載骨相当)も含め全帯を可動donorへ1対1で
    割り当てる」ことを既定とし、アンカー畳み込みは**donor本数が足りない
    家系だけの「しょうがない」フォールバック**に格下げされた。

    donor不足時にどこまで可動化できるかは呼び出し元
    (resolve_sway_chain_entries())の責務: 家系がleaf2(第2合成リーフ、
    このモジュールのSWAY_DONOR_FAMILIES参照)を持ち、転写元帯数が
    cloth_chainよりちょうど1本多いときは、旧leafを可動donorへ編入して
    cloth_chainを1本伸ばし(n_donorがn_sourceへ届くようにしてから)本関数を
    呼ぶ——この場合、本関数自身はn_source<=n_donor分岐に落ち、アンカー
    畳み込みは発生しない。それでも収まらない(donor不足の)家系だけが、
    本関数のn_source>n_donor分岐(アンカー畳み込みフォールバック)に到達する。

    - n_source <= n_donor(donor充足): 先頭帯を含む全帯を恒等写像
      (index i -> donor min(i, n_donor - 1))でdonorへ直接1対1割当する。
      アンカー畳み込みは行わない。n_source本数がdonor本数以下なら
      恒等写像(i -> i)そのもので、使われない残りdonorは常に**末尾側**に
      連続して残る(比例配分のように先頭・中間に穴を空けない)。
    - n_source > n_donor(donor不足、「しょうがない」フォールバック):
      先頭帯のみ SWAY_CLOTH_ANCHOR(呼び出し元がdonorチェーンの親
      head/pelvis等へ解決)へ畳み込み、残り(n_source-1)帯をdonorへ
      出現順のまま1対1(末尾donorへクランプ)で割り当てる。この分岐へ
      到達するのは常にn_donor>=1かつn_source>=2(n_source<=n_donorの分岐で
      n_donor<=0はすでに弾かれ、n_source==1は常にn_source<=n_donorを
      満たすためこちらへは来ない——旧dev#1355の「n_source==1は常に
      アンカーのみ」規則は、単独の実転写元帯にも1個以上donorがあれば
      直接乗せる新裁定のもとでは適用されない、意図的な仕様変更)。

    比例配分版(sway_cloth_bone_targets()/sway_cloth_target_indices()、
    dev#1355/dev#19 R2a-v2)は削除せず温存する(既存テスト
    test_step02_sway_cloth_mapping_dev1355.py等が対象。両関数とも
    bpy非依存の純粋関数)。本関数はウェイト転写の実呼び出し経路
    (main()内、sway_chains適用ループ)専用の置換であり、bend_weightsは
    受け取らない(1対1割当は屈曲量に依らない単純な出現順対応のため)。

    戻り値: 長さn_sourceのlist。要素はSWAY_CLOTH_ANCHOR、または
    0..n_donor-1のdonor index。n_source<=0またはn_donor<=0なら[]。
    """
    if n_source <= 0 or n_donor <= 0:
        return []
    if n_source <= n_donor:
        return [min(i, n_donor - 1) for i in range(n_source)]
    out = [SWAY_CLOTH_ANCHOR]
    for j in range(n_source - 1):
        out.append(min(j, n_donor - 1))
    return out


# =====================================================================
# 同時Nチェーン対応(dev#19 R3統合、dev#1375、item3)
# =====================================================================
#
# 旧sway_cloth_bones機構(job.jsonの単一キー、1回のstep02実行で1ファミリー/
# 1チェーンのみ)を、job["sway_chains"](リスト、複数チェーンを同時に扱う)へ
# 一般化する。旧単一キーは完全後方互換(_normalize_sway_chain_configs()が
# 1エントリのリストへラップするだけ、resolve_sway_donor()自体は無改変で
# そのまま使われ続ける)。bpy非依存の純粋関数のみ(単体テスト可能、
# tests\coverage\test_step02_sway_multichain_dev1375.py参照)。

def _normalize_sway_chain_configs(job):
    """job.jsonから「未解決の」揺れチェーン設定リストを取り出す(bpy非依存、
    ファイルI/O・sway_assign呼び出しは行わない最下層の正規化)。優先順位:

      1. job["sway_chains"](リスト)があればそれをそのまま返す(新仕様)。
      2. 無く job["sway_cloth_bones"] があれば、job["sway_cloth_donor_family"]
         (省略時"OldCloth001")込みの1エントリへラップして返す(旧仕様の
         後方互換パス。両方指定されている場合はsway_chains優先——旧キーは
         無視する。この組み合わせは想定運用に無いため優先順位のみ定義)。
      3. どちらも無ければ空リスト(=完全no-op、既定出力不変)。

    各エントリのスキーマは pipeline\\py\\sway_assign.py の
    Assignment.job_fragment と同一(自動割当エンジンの出力をそのまま
    job["sway_chains"]へ流用できる設計):
      {"sway_cloth_bones": [anchor, node1, ...],
       "sway_cloth_donor_family": str(省略可),
       "sway_cloth_donor_chain": [...](省略可、指定時はfamily解決より優先),
       "sway_cloth_donor_anchor": str(省略時既定"pelvis")}
    """
    chains = job.get("sway_chains")
    if chains:
        return list(chains)
    legacy = job.get("sway_cloth_bones")
    if legacy:
        return [{
            "sway_cloth_bones": list(legacy),
            "sway_cloth_donor_family": job.get("sway_cloth_donor_family", "OldCloth001"),
        }]
    return []


def resolve_sway_chain_entries(job, gender, auto_entries=None, vanilla_dir=None):
    """job設定(+auto_entries、sway_enable自動割当由来の追加エントリ)から、
    main()の骨格構築ループがそのまま消費できる「解決済み」エントリの
    リストを作る(bpy非依存の純粋関数)。

    1エントリ = {"sway_cloth_bones": [...], "cloth_chain": [...],
    "extra_bones": [...], "refskel_name": str|None, "anchor_bone": str,
    "skipped": bool, "skip_reason": str|None, "is_auto": bool}。
    skipped=Trueのエントリは呼び出し側(main())がgroup_targetsへ適用せず、
    対象ボーンは従来どおりのhead/pelvis等への畳み込みに任せる(安全側
    フォールバック、既定不変)。is_auto=True は auto_entries 由来
    (dev#19実データ欠陥修正、issue #1379: main()がend-to-end集計
    (build_sway_end_to_end_report())で手動指定と自動割当を区別するために
    使う。job["sway_chains"]手動指定側はis_auto=False)。

    vanilla_dir(dev#19実データ欠陥修正、issue #1379、欠陥2の安全網):
    指定時、explicit_chain分岐で解決したrefskel_nameが実際に
    `{vanilla_dir}/{refskel_name}` として存在するかを確認する。
    SWAY_DONOR_FAMILIESへ辞書登録済みでも、実際のrefskel抽出
    (extract_vanilla.py側)が未実装/未実行の家系(HeadEquip062_ear等)は
    このファイルが存在しない——素通しすると後続のbuild_pal_armature()が
    open()でFileNotFoundError実行時クラッシュを起こす(dev#19実データ
    欠陥修正時に発覚した危険、issue #1379)。ファイルが無ければdie()せず
    skip=Trueで安全に倒す(「耳はrefskel未結線の間はlost明示」という
    受入条件そのもの)。省略時(None、既定)はファイルチェックをスキップし
    従来どおり辞書登録の有無のみで判定する(main()以外の呼び出し元
    ——単体テスト・dryrun等——は無退行)。

    解決規則(エントリごと):
      - "sway_cloth_donor_chain"(具体ボーン名列、sway_assign.py自動割当の
        出力形式)が指定されていれば、それをcloth_chainとしてそのまま使う。
        refskel_nameは"sway_cloth_donor_family"がSWAY_DONOR_FAMILIESに
        登録されていればそのrefskel_suffixを流用する(同じ家系のbindpose
        データを再利用する設計)。登録が無ければ解決不能としてskip=True
        (die()しない——sway_enable自動割当は実験的機能であり、SK側の
        vanilla抽出(work\\rd_19_ears\\PROPOSAL.md §5.2で「本WPのスコープ外」
        と明記済み)が整うまでは「安全にスキップ」が正しい既定動作。
        item6の静的ゲートログはmain()側でこのskip_reasonを出力する)。
        辞書登録済みでもvanilla_dir指定時にファイルが実在しなければ
        同様にskip=True(上記docstring参照)。
      - "sway_cloth_donor_chain"が無く"sway_cloth_donor_family"のみなら、
        _resolve_family_by_name()(resolve_sway_donor()と同じロジック)で
        解決する。未登録familyはdie()(明示指定の設定ミスとして即座に停止、
        旧仕様resolve_sway_donor()の厳格さを踏襲——job["sway_chains"]の
        明示指定の誤字を静かに無視しないため。auto_entries由来はこの分岐に
        到達しない=常にsway_cloth_donor_chain付きで渡ってくる設計、
        sway_assign.Assignment.job_fragment参照)。この分岐はvanilla_dir
        チェック対象外(実運用ではOldCloth001の基底refskelのみが使われ、
        常に存在するため)。
    """
    manual_configs = _normalize_sway_chain_configs(job)
    tagged_entries = [(cfg, False) for cfg in manual_configs] + [
        (cfg, True) for cfg in list(auto_entries or [])]
    resolved = []
    for entry, is_auto in tagged_entries:
        sway_bones = list(entry.get("sway_cloth_bones") or [])
        if not sway_bones:
            continue
        anchor_bone = entry.get("sway_cloth_donor_anchor") or "pelvis"
        explicit_chain = entry.get("sway_cloth_donor_chain")
        family_name = entry.get("sway_cloth_donor_family")

        if explicit_chain:
            fam = SWAY_DONOR_FAMILIES.get(family_name) if family_name else None
            refskel_name = None
            if fam is not None:
                refskel_name = (f"refskel_{fam['refskel_suffix']}_{gender.lower()}.json"
                                 if fam["refskel_suffix"] else f"refskel_{gender.lower()}.json")
            # swayfix WP(dev#19): explicit_chain経路(auto-assign由来)のleaf_bone
            # はfamが解決できた場合のみ埋める。famが無い/refskel未解決なら
            # None(既存のskip挙動と同じく安全側、①②③のいずれも効かない)。
            # earleaf WP(dev#19、issue#19): chain=explicit_chainを渡し、この
            # エントリが実際に使うdonorチェーンの左右(_l/_r)に合わせてleaf名を
            # 解決する(欠陥A修正、上のresolve_sway_leaf()docstring参照)。
            leaf_bone = resolve_sway_leaf(fam, gender, chain=explicit_chain) if fam is not None else None
            # earleaf鎖leaf置き去りバグ修正(dev#19、issue#19、
            # work\rd_19_statue\PLAN_20260813.md確定バグが正本): explicit_chain
            # (sway_assign.build_donor_inventory()の_longest_chain()が共有骨格の
            # 実階層を末端まで歩いた結果)は、HeadEquip062_ear等「leafが合成で
            # なく実在バニラ骨」の家系では、その実在leaf骨(例: ear_05_l)を
            # **チェーン自身の末尾要素として既に含んでいる**——SWAY_DONOR_FAMILIES
            # の静的宣言(chain=4節+leaf=別の1節)と違い、動的発見は「chain」と
            # 「leaf」の区別を知らないため。resolve_sway_leaf()が返すleaf_bone名は
            # 常にchain[-1]と同じ左右接尾辞から作られるため、この場合
            # leaf_bone == explicit_chain[-1](同一ボーン名)になる。
            #
            # この自己衝突を放置すると、reposition_sway_donor_chain_and_leaf()が
            # 同じeditboneを2回書き込む: ①cloth_chainループが末尾要素へ
            # 正しいweld位置(local_pts[n_donor-1]->local_pts[n_donor])を設定 →
            # ②直後のleafブロックがeb.get(leaf_bone)で**同じボーンを名前解決**し、
            # n_wanted=n_donor+1で1つ多く取ったlocal_pts[n_donor]で頭位置を
            # 上書き(①の正しい溶接位置を消して1節分先へずらす)。実測ギャップ
            # (左右とも約5.44cm=耳ボーン1本長)はこの二重書きの帰結
            # (work\rd_19_earfix\ANALYSIS.md参照)。
            #
            # 修正: chain末尾がleaf_boneと同名(=既にleafを内包)なら、その末尾
            # 要素をcloth_chain本体から除外し、SWAY_DONOR_FAMILIES静的宣言と
            # 同じ「chain N節+独立leaf1節」の形へ正規化する。leaf_bone自体は
            # 変更しない(既存のleafブロックがその1回だけの書き込みを担当)。
            # 除外は名前一致という構造的条件のみで判定し、値を寄せて合わせる
            # ものではない。cloth_chainが1要素以下の退化ケースでもクラッシュ
            # しない(reposition側の`if len(sway_bones) < 2 or not cloth_chain`
            # 安全網がそのまま効く)。
            resolved_chain = list(explicit_chain)
            if leaf_bone is not None and resolved_chain and resolved_chain[-1] == leaf_bone:
                resolved_chain = resolved_chain[:-1]
            if refskel_name is None:
                resolved.append({
                    "sway_cloth_bones": sway_bones, "cloth_chain": resolved_chain,
                    "extra_bones": [], "refskel_name": None, "anchor_bone": anchor_bone,
                    "leaf_bone": None,
                    "skipped": True, "is_auto": is_auto,
                    "skip_reason": (
                        f"donor family {family_name!r} has no registered refskel "
                        "(SK vanilla extraction pending, dev#19 R3 follow-up) "
                        "-- chain left unmapped, no effect on output"),
                })
                continue
            if vanilla_dir is not None:
                refskel_json_path = os.path.join(vanilla_dir, refskel_name)
                if not os.path.isfile(refskel_json_path):
                    resolved.append({
                        "sway_cloth_bones": sway_bones, "cloth_chain": resolved_chain,
                        "extra_bones": [], "refskel_name": refskel_name, "anchor_bone": anchor_bone,
                        "leaf_bone": leaf_bone,
                        "skipped": True, "is_auto": is_auto,
                        "skip_reason": (
                            f"donor family {family_name!r} is registered but its refskel "
                            f"({refskel_name!r}) is not yet extracted under vanilla/ "
                            "(extraction pending, dev#19 R3 follow-up) "
                            "-- chain left unmapped, no effect on output"),
                    })
                    continue
                # dev#19 m2defects(欠陥2、work\rd_19_m2smoke\RESULT.md /
                # work\rd_19_haori_e2e\RESULT.md): 自動割当エンジン
                # (sway_assign.build_donor_inventory())はdonor在庫の静的
                # スナップショット(job_dir/vanilla/sk_palhuman_bones.json、
                # 4079骨)からdonor候補を選ぶ。この在庫は「登録済み家系名か」
                # しか見ておらず、選ばれた具体ボーン名(explicit_chain)が
                # 実際に今回のjobでextract_vanilla.pyが抽出したrefskel
                # ファイルの中に実在するかまでは保証しない——実データで
                # 静的スナップショットに幽霊骨(実ビルドに存在しないボーン、
                # 例: F_Hunter001_19/20、F_Hunter001_11/12)が含まれている
                # ケースが複数確認された。refskel_name自体の存在チェック
                # (上のブロック)だけでは、ファイルは在ってもその中身に
                # explicit_chainの個々のボーンが無いケースを捕まえられない
                # ため、ここで実ボーン名を突き合わせ、無ければHeadEquip062_ear
                # と同種のグレースフルWARN-skipにする(die()しない)。
                #
                # 注: この存在確認はexplicit_chain(トリム前、leaf含む)に対して
                # 行う——leaf_bone自身(=chain[-1]と同名)が実際にrefskelへ
                # 抽出されているかも同時に検証するため(トリム後のresolved_chain
                # だけを見るとleaf骨の欠落を見逃す)。
                try:
                    with open(refskel_json_path, encoding="utf-8") as f:
                        refskel_bone_names = set(json.load(f).keys())
                except (OSError, ValueError) as e:
                    # 読み込み自体が壊れている場合も安全側でskip(die()しない)。
                    resolved.append({
                        "sway_cloth_bones": sway_bones, "cloth_chain": resolved_chain,
                        "extra_bones": [], "refskel_name": refskel_name, "anchor_bone": anchor_bone,
                        "leaf_bone": leaf_bone,
                        "skipped": True, "is_auto": is_auto,
                        "skip_reason": (
                            f"donor family {family_name!r} refskel ({refskel_name!r}) "
                            f"could not be read ({e}) "
                            "-- chain left unmapped, no effect on output"),
                    })
                    continue
                missing_donor_bones = [b for b in explicit_chain if b not in refskel_bone_names]
                if missing_donor_bones:
                    resolved.append({
                        "sway_cloth_bones": sway_bones, "cloth_chain": resolved_chain,
                        "extra_bones": [], "refskel_name": refskel_name, "anchor_bone": anchor_bone,
                        "leaf_bone": leaf_bone,
                        "skipped": True, "is_auto": is_auto,
                        "skip_reason": (
                            f"donor family {family_name!r} refskel ({refskel_name!r}) "
                            f"does not contain the following auto-assigned donor bone(s): "
                            f"{missing_donor_bones} (the auto-assign engine's static bone "
                            "inventory snapshot disagrees with the actually-extracted "
                            "refskel for this job -- dev#19 m2defects) "
                            "-- chain left unmapped, no effect on output"),
                    })
                    continue
            resolved.append({
                "sway_cloth_bones": sway_bones, "cloth_chain": resolved_chain,
                "extra_bones": [], "refskel_name": refskel_name, "anchor_bone": anchor_bone,
                "leaf_bone": leaf_bone,
                "skipped": False, "skip_reason": None, "is_auto": is_auto,
            })
            continue

        if not family_name:
            family_name = "OldCloth001"

        # dev#19 native-donor-rule WP(issue #19、2026-08-14夜根因確定): 明示
        # job指定(family_name)を「親一致」かつ「native_sim_count>=n_source+1」
        # 規則で検証する。requested_familyがこの規則を満たさなければ、同じ
        # anchorを持つ登録済み家系の中からqualifyする最小native_sim_countの
        # 家系へauto-correctする(無ければnative_sim_count最大の家系へ
        # フォールバック)。sway_native_rule.pyはbpy非依存の純粋関数のみ
        # (テストはtests\coverage\test_sway_native_rule_dev19.py)。
        #
        # n_source(転写元の実帯数)は len(sway_bones) そのもの——この経路
        # (weight-direct-assign、sway_cloth_weight_targets_direct()使用)は
        # 「先頭帯(PhysBone搭載骨相当、例: "Tail Root")を含む全帯を可動donor
        # へ1対1で割り当てる」(第2次裁定、上のコメント参照)。sway_assign.py
        # 側のSourceChain(anchor別出し、n_source=len(source.bones)-1相当が
        # 実質の転写帯数)とは意味論が異なるため、ここで-1しない
        # (2026-08-14 native-donor-rule WP内で一度-1する誤りを作り、
        # 気付いて訂正した経緯を残す)。
        n_source = len(sway_bones)
        native_candidates = [
            (name, f.get("native_sim_count"))
            for name, f in SWAY_DONOR_FAMILIES.items()
            if f.get("anchor", "pelvis") == anchor_bone
        ]
        chosen_family, donor_warning = sway_native_rule.pick_family(
            native_candidates, n_source, requested=family_name)
        if chosen_family:
            family_name = chosen_family

        fam = SWAY_DONOR_FAMILIES.get(family_name)
        if fam is None:
            core.die(TAG, f"sway_chains: unknown donor family {family_name!r} "
                          f"(known: {sorted(SWAY_DONOR_FAMILIES)})")
        cloth_chain, extra_bones, refskel_name = _resolve_family_by_name(fam, gender)

        # 選ばれた家系がnative規則を満たさない(=真のフォールバック、上の
        # pick_family()がnative_sim_count最大の家系へ落とした場合)なら、
        # weighted本数をnative_sim_count-1本までcapする(sway_native_rule.py
        # モジュールdocstring「n_donor capの副作用範囲」参照: この経路
        # (sway_cloth_weight_targets_direct()使用)ではn_source<=native-1の
        # 間は恒等写像のためcapに副作用が無い。qualifyする通常経路では
        # cloth_chain全長がnative_sim_countと一致する設計のため、capは
        # 自動的に「末尾1本を切り落とす」だけで済む——捏造・水増しはしない)。
        chosen_native = fam.get("native_sim_count")
        if not sway_native_rule.qualifies(chosen_native, n_source):
            cloth_chain = sway_native_rule.cap_chain(cloth_chain, chosen_native)

        # earleaf WP(dev#19、issue#19): chain=cloth_chainを渡す
        # (この経路のcloth_chainはfam["chain"]由来で常にL側/無側のため、
        # 実質的にfam["leaf"]の値をそのまま返す旧来動作と一致——無退行)。
        leaf_bone = resolve_sway_leaf(fam, gender, chain=cloth_chain)
        # dev#19 weight-direct-assign WP(2026-08-14、オーナー裁定「元々ウェイト
        # が乗っているボーンがn本なら、donorはn+1本以上でなければならない」):
        # 転写元の実帯数(len(sway_bones))がcloth_chainよりちょうど1本多く、
        # かつ家系がleaf2(spillover専用の第2合成リーフ)を宣言していれば、
        # 旧leaf(例: tail_06)を可動donorへ昇格(cloth_chainへ編入)し、
        # leaf2(例: tail_07)を新しいウェイト無しの実リーフとして使う。
        # これによりsway_cloth_weight_targets_direct()のn_donor(=len(
        # cloth_chain))が転写元帯数と一致し、先頭帯も含め全帯を1:1で
        # 可動donorへ割り当てられる(アンカー畳み込みを回避)。
        # leaf2未宣言の家系、またはズレが1本を超える家系は、この分岐を
        # 素通りし従来どおりcloth_chain/leaf_boneのまま返す——
        # sway_cloth_weight_targets_direct()側の「donor不足フォールバック
        # (先頭帯のみアンカーへ畳み込み)」が③の「しょうがない」規約を担う。
        #
        # native-donor-rule WP: 上でnative規則によりcloth_chainがcapされた
        # (=真のフォールバック)場合は、leaf2スピルオーバー(旧leafを可動donor
        # へ昇格)を適用しない——native境界そのものを削っている状況で
        # さらに非nativeなleaf2を可動化するのは規則の趣旨(捏造骨での不足
        # 糊塗の禁止)に反するため。
        leaf2_raw = fam.get("leaf2")
        if (leaf2_raw and leaf_bone and len(sway_bones) == len(cloth_chain) + 1
                and sway_native_rule.qualifies(chosen_native, n_source)):
            expanded_chain = cloth_chain + [leaf_bone]
            leaf2_bone = resolve_sway_leaf(fam, gender, chain=expanded_chain, key="leaf2")
            if leaf2_bone:
                cloth_chain = expanded_chain
                leaf_bone = leaf2_bone
        resolved.append({
            "sway_cloth_bones": sway_bones, "cloth_chain": cloth_chain,
            "extra_bones": extra_bones, "refskel_name": refskel_name,
            "anchor_bone": anchor_bone,
            "leaf_bone": leaf_bone,
            "skipped": False, "skip_reason": None,
            "is_auto": is_auto,
            "donor_warning": donor_warning,
        })
    return resolved


def mark_sway_donor_collisions(entries):
    """dev#19 leafcollision WP(issue #1407): 同一donorボーンを複数のsway
    エントリが取り合う「donorボーン名衝突」を構造的に検出し、後発entryを
    安全にskip扱いへ倒す(bpy非依存の純粋関数、resolve_sway_chain_entries()
    直後にmain()から呼ぶ)。

    ## 発見された実バグ(work\\rd_19_pbmap\\REBUILD_VERIFY_20260813.md正本)

    `reposition_sway_donor_chain_and_leaf()`(613-738行)は各active entryを
    順番に処理し、そのentryの`cloth_chain`/`leaf_bone`が指すpal_arm側の
    edit boneへ`b.head = ...`を直接代入する。Blenderの`eb[name]`/`eb.get(name)`
    は**名前で解決される**ため、2つの独立したentryが同じボーン名(cloth_chain
    本体、または合成`leaf_bone`)を指していれば、後から処理される方が
    先に処理された方の正しい計算結果を単純に上書きする。これは以下の
    どちらの経路でも起こりうる(実際にflatapron検体のjob.jsonで両方とも
    再現した):

      (a) job["sway_chains"]内で**同じ`sway_cloth_donor_family`を複数の
          手動エントリが明示指定**する(例: 実際のflatapron job.jsonで
          `Hunter001`が2エントリに使われていた——`_resolve_family_by_name()`
          はfamily名だけから決まるcloth_chain/leafを返すため、同じfamilyを
          選べば必ず同じボーン名列になる)。
      (b) job["sway_manual"](sway_enable自動割当経由)が、job["sway_chains"]
          で既に明示指定済みのfamilyを**知らずに**同じdonorへ割り当てる
          (sway_assign.assign_sway_chains()の在庫排他(規則5)はエンジン
          自身が処理する候補プール内でしか働かず、job["sway_chains"]側の
          明示クレームを一切知らない——実例: `OldCloth001`をしっぽ
          (sway_chains)とエプロン(sway_manual自動割当)の両方が選んだ)。

    ## 対処方針

    entries(resolve_sway_chain_entries()の戻り値、job["sway_chains"]→
    job["sway_manual"]自動割当の順で解決順序が保たれている——
    `_normalize_sway_chain_configs()`+`tagged_entries`の結合順)を先頭から
    走査し、各未skipエントリの「donorボーン足跡」
    (`set(cloth_chain) | {leaf_bone}`。**extra_bones/siblingsは対象外**——
    これらはウェイトを載せない同梱ボーンで、複数entryが同じfamilyの
    siblingsを共有すること自体は`_resolve_family_by_name()`docstring
    「ノード不発防止」で意図された既存設計であり、衝突ではない)を、既に
    これより前のentryがclaim済みのボーン名集合と突き合わせる。重複が
    あれば、このentryをskip=Trueへ倒す(既存の「未登録family/refskel未抽出/
    アバター側ボーン欠落」と同じ「die()しない・対象ボーンは従来の
    fallback畳み込みに任せる」安全側方針を踏襲。明示指定
    (job["sway_chains"])は常にjob["sway_manual"]自動割当より前に解決される
    ため、**先に書かれた方(記述順で早いもの)が常に優先され、後発が
    グレースフルにlostへ回る**——job.json編集で優先順位を制御できる)。

    重複が無ければ、このentryのdonorボーン足跡をclaim済み集合へ加えて
    active(skipped不変)のまま返す。

    entries自体は破壊的に変更せず、新しいdictのリスト(各entryも浅い
    コピー)を返す(呼び出し側の元リストとの意図しないエイリアス共有を
    避ける——build_sway_end_to_end_report()等、同じsway_entriesを複数箇所が
    読む既存の使い方と衝突しないため)。
    """
    claimed = {}  # donorボーン名 -> それをclaimした最初のentryのラベル
    result = []
    for idx, e in enumerate(entries):
        e = dict(e)
        if e["skipped"]:
            result.append(e)
            continue
        footprint = set(e.get("cloth_chain") or [])
        leaf = e.get("leaf_bone")
        if leaf:
            footprint.add(leaf)
        if not footprint:
            result.append(e)
            continue
        conflict = sorted(footprint & claimed.keys())
        if conflict:
            first_label = claimed[conflict[0]]
            e["skipped"] = True
            e["skip_reason"] = (
                f"donor bone(s) {conflict} already claimed by an earlier sway "
                f"entry ({first_label!r}) -- structural donor-name collision "
                "across sway entries (dev#19 issue #1407), this entry left "
                "unmapped, no effect on output")
            result.append(e)
            continue
        label = (e["sway_cloth_bones"][0] if e.get("sway_cloth_bones")
                  else f"entry{idx}")
        for b in footprint:
            claimed[b] = label
        result.append(e)
    return result


def build_sway_end_to_end_report(sway_report, sway_entries):
    """dev#19実データ欠陥修正(issue #1379、欠陥3): sway-report(静的ゲート、
    item6)がエンジン段(sway_assign.assign_avatar_sway()の割当成功)だけを
    数え、resolve段(resolve_sway_chain_entries()、refskel未登録/未抽出)の
    skipを計上しないため、「declared=3 assigned=3 lost=0」と言いながら
    実配線が0本という偽緑が起きていた(work\\rd_19_final\\RESULT.md §2実測)。

    本関数はauto_entries由来(is_auto=True)のsway_entriesのうちresolve段で
    skipされたものを、sway_reportの assigned/lost 集計へ合流させ、
    end-to-endの実配線数を返す(bpy非依存の純粋関数、main()が呼ぶ)。
    手動指定(job["sway_chains"]、is_auto=False)のresolve skipは対象外
    ——手動指定は元々未登録家系をdie()する設計のため、resolve段まで
    到達してskip=Trueになるのは従来auto_entries由来のみだった
    (resolve_sway_chain_entries()の解決規則参照)。

    dev#19 leafcollision WP(issue #1407)以降の注記: main()は
    resolve_sway_chain_entries()の直後にmark_sway_donor_collisions()を
    通すため、is_auto=Falseのentry(job["sway_chains"]の明示エントリ同士が
    同じdonor familyを取り合う場合)もresolve段skipになりうる。本関数の
    集計対象(is_auto=Trueのみ)はあえて変更していない——それらの明示entry
    skipは既存の別ループ(main()、`e["skipped"] and not e.get("is_auto")`)が
    従来どおり個別にWARNログへ出力する仕組みが既にあり、二重計上を避ける
    ため。

    戻り値: sway_reportと同じ形({"declared_chains", "assigned_chains",
    "lost_chains", "lost"})。assigned_chains/lost_chainsはresolve段の
    結果を反映済み(=真の実配線数)、lostにはresolve段のskip理由も
    追加される。
    """
    resolve_lost = [e for e in sway_entries if e.get("is_auto") and e["skipped"]]
    lost = list(sway_report["lost"]) + [
        {"id": e["sway_cloth_bones"][0], "anchor": e["sway_cloth_bones"][0],
         "reason": e["skip_reason"]}
        for e in resolve_lost
    ]
    return {
        "declared_chains": sway_report["declared_chains"],
        "assigned_chains": sway_report["assigned_chains"] - len(resolve_lost),
        "lost_chains": sway_report["lost_chains"] + len(resolve_lost),
        "lost": lost,
    }


def build_donor_bone_pairs_from_vanilla(vanilla, gender):
    """dev#19根治WP(issue#19、m2defects欠陥2の根治): 自動割当エンジンの
    donor在庫discoveryを、**このjobが実際に抽出したrefskel_*.json**
    (resolve_sway_chain_entries()が後段の検証に使うのと同一のソース)から
    直接組み立てる(bpy非依存の純粋関数、単体テスト可能)。

    ## 旧実装の構造的欠陥(dev#19 m2defects)

    旧実装はvanilla/sk_palhuman_bones.json(SK_PalHuman共有Skeletonアセット
    の静的スナップショット)を、resolve/build段(extract_vanilla.pyが
    このjobのpakから都度抽出するrefskel_{family}_{gender}.json)とは別系統の
    discoveryソースとして読んでいた。しかもこのファイルはextract_vanilla.py
    が生成するものではなく(旧コメント「SK側抽出WPが将来生成するファイル」
    のとおり本パイプラインは一度も生成していない)、過去の一回限りのWP実験
    (work\\rd_19_haori\\sk_palhuman_bones.json)を各WPが手作業でjobの
    vanilla\\へコピーする運用に頼っていた(work\\rd_19_hardset\\RESULT.md
    §2「sk_palhuman_bones.jsonの事前コピー忘れ」が実例)。

    UEの仕様上、1つのSkeletonアセットを複数のSkeletalMeshアセットが共有
    すると、そのSkeletonアセットは参照した全メッシュのボーンの**和集合**を
    蓄積する。一方、個々の衣装メッシュ自身のRefSkeleton(=extract_vanilla.py
    が実際に抽出するrefskel_{family}_{gender}.json)はそのメッシュ自身が
    実際に使うボーンだけの**部分集合**。discovery(和集合を見る)と
    resolve/build(部分集合しか無い)が別ソースを見ている限り、「discoveryが
    在ると言ったボーンがresolve段に無い」(幽霊骨)は**いつでも起こりうる
    構造**であり、Hunter001胸元枝×Female(work\\rd_19_hardset\\RESULT.md
    §2実測、F_Hunter001_11/12)はその実例の1つに過ぎない。

    ## 根治

    discoveryとresolve/buildを**同一のソース**(このjobがpakから実抽出した
    refskel_*.json)へ統合する。SWAY_DONOR_FAMILIESに登録された各家系の
    refskel_suffixを使ってvanilla配下に実在するrefskel_{suffix}_{gender}.json
    (suffix=""ならrefskel_{gender}.json自身、OldCloth001はここに同梱済み)
    だけを列挙・マージする。これにより「discoveryが在ると言ったボーンが
    resolve段に無い」は構造的に発生し得なくなる(2つの独立データソースと
    いう発生前提そのものを除去)。resolve_sway_chain_entries()側の
    突き合わせ安全網(dev#19 m2defects欠陥2)はそのまま残す(保険として
    無害。この根治後は非発火になるはずだが、将来別の経路でdonor_bone_pairs
    が渡された場合の保険として残す価値がある)。

    未抽出の家系(sway_extra_familyで指定しなかった等)は静かにスキップする
    (die()しない、既存のresolve段vanilla_dirチェックと同じ安全側方針)。
    基準骨格(refskel_{gender}.json)が無ければ空リストを返す(呼び出し側
    main()が既存の「在庫が無い」メッセージへ倒す、後方互換)。

    戻り値: [(name, parent_or_None), ...]。複数ファイルにまたがって同名
    ボーンが現れた場合は最初に読んだファイル(基準骨格が先頭)の値を権威
    として保持する(vp_bl.merge_refskel_files()と同じ「先着優先」規約。
    vp_bl.pyはbpy依存のため本関数から直接importできず、意図的な重複——
    このファイル冒頭コメントのROTATE_CHAINS 3箇所重複と同じ運用)。
    """
    base_path = os.path.join(vanilla, f"refskel_{gender.lower()}.json")
    if not os.path.isfile(base_path):
        return []
    paths = [base_path]
    for fam in SWAY_DONOR_FAMILIES.values():
        suffix = fam["refskel_suffix"]
        if not suffix:
            continue  # OldCloth001はbase refskelへ既に同梱済み(refskel_suffix="")
        p = os.path.join(vanilla, f"refskel_{suffix}_{gender.lower()}.json")
        if os.path.isfile(p) and p not in paths:
            paths.append(p)
    merged = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            refskel = json.load(f)
        for name, info in refskel.items():
            merged.setdefault(name, info.get("parent"))
    return list(merged.items())


# =====================================================================
# 汎用ハブ配線(dev#1508 W2a-2c、旧family限定donor経路のPB/SB自動割当を完全置換)
# =====================================================================

# dev#1551(安全域WP、issue #1551「安全域」欄、2026-08-18オーナー最終裁定):
# 「先端の動きがおかしい揺れものをユーザー側から封じるノブ」の製品既定値
# ——GUIを一切触っていなくても、全鎖が既定でこの本数だけ先端をマージ縮約
# する(`sway_hub.target_len_with_safety_margin()`参照)。ユーザーは
# ラボ「揺れもの詳細設定」の鎖ごとの「安全域」欄でこの既定値を鎖単位に
# 上書きできる(`_safety_margin_overrides_from_job()`)。
# `sway_hub.plan_hub_wiring()`/`sway_hub_wire.wire_and_diagnose_hub()`
# 自体の引数既定は0(無退行)のまま——この定数が製品既定値を注入する
# 唯一の場所(RESULT.md「設計判断2」、work\run_1551\laneR2_safety\
# RESULT.md参照)。
SWAY_DEFAULT_SAFETY_MARGIN = 1


def _safety_margin_overrides_from_job(job, weighted_bone_names=None):
    """dev#1551(安全域WP)、dev#1582(鎖キー正規化修理)で改訂: `job["sway_
    chain_overrides"]`(`app_py\\sway_chain_override_store.py`のエントリ
    そのまま、GUI「揺れもの詳細設定」の鎖ごとの上書き)から、
    `sway_hub.plan_hub_wiring()`の`safety_margin_by_chain`引数へそのまま
    渡せる{extended_source(タプル) -> safety_margin}の対応表を作る。

    エントリの`"bones"`(`[anchor, node1, node2, ...]`)は、
    `app_py\\ui\\sway_chain_dialog._flatten_physbone_entries()`が書く
    生catalog形式(`_end`tip骨等の無ウェイト骨を含みうる)。一方
    `sway_hub.ChainDonorPlan.source_chain`が使う実際の
    `extended_source = (anchor,) + chain`は、`main()`が
    `collect_weighted_avatar_bone_names()`+`sway_hub_wire.
    filter_entries_by_weighted_bones()`で無ウェイト骨を間引いた**後**の
    chainから作られる(dev#1572)。この2つの規約は元々一致しないため、
    dev#1582(issue #1582、オーナー実測「安全域9を設定しても左耳が
    まとまらない」)まではキー不一致で上書きが誰にも当たらなかった。

    `weighted_bone_names`(省略時None): 渡されたときだけ、`bones`の**先頭
    (anchor)を除いた残り**を`sway_hub_wire.filter_entries_by_weighted_
    bones()`と全く同じ規約(集合に含まれない骨を間引いて詰める)で正規化
    してからタプル化する——「入口で正規化」の原則どおり、照合キーの母集団
    をパイプライン内部と1箇所で揃える。anchor自身は`filter_entries_by_
    weighted_bones()`の規約(「entry["anchor"]自体はこの関数の対象外
    (常に維持する)」)と一貫させ、weighted_bone_namesに含まれていなくても
    絶対に脱落させない。Noneのままなら無変更(単体テスト・呼び出し側が
    意図的にスキップする場面の安全側フォールバック、既存呼び出し元は
    完全無退行)。

    `"safety_margin"`キーを持たないエントリ(hardness/enabled/manualだけが
    既定から変わっている行)は対象外とする——このチェーンは
    `SWAY_DEFAULT_SAFETY_MARGIN`(製品既定値)をそのまま使う。job未指定
    /空リストなら空dict(=呼び出し側の`default_safety_margin`が常に効く、
    ラボ憲章④と一貫した安全側)。"""
    out = {}
    for entry in (job.get("sway_chain_overrides") or []):
        bones = entry.get("bones")
        margin = entry.get("safety_margin")
        if not bones or margin is None:
            continue
        if weighted_bone_names is not None:
            bones = [bones[0]] + [b for b in bones[1:] if b in weighted_bone_names]
        out[tuple(bones)] = margin
    return out


def _lab_assignments_from_job(job, physbone_entries, springbone_entries,
                               weighted_bone_names=None):
    """dev#1572第3便(issue #1572追記「チェインの揺れ設定問題1・2」)の
    唯一の入口。dev#1592(#1590取りこぼし修理、2026-08-19)でロジック本体を
    `sway_chain_defaults.lab_assignments_from_job()`へ抽出した——
    `pipeline\\blender\\step01_import_vrm.py::compute_sway_source_bone_names()`
    (dev#1508受入ゲートのground truthスナップショット対象骨を決める関数)も
    同じ解決結果を必要とするため、二重実装を避けて共有する
    (`sway_chain_defaults.py`モジュールdocstring「dev#1592」節参照)。

    本関数はここに薄い委譲として残す(既存テスト
    `tests\\coverage\\test_step02_sway_enabled_wiring_dev1572.py`が
    step02_retarget.pyのソースをexec抽出して`_lab_assignments_from_job`と
    いう名前で呼ぶ既存の互換性のため、名前・シグネチャは変更しない)。"""
    return sway_chain_defaults.lab_assignments_from_job(
        job, physbone_entries, springbone_entries,
        weighted_bone_names=weighted_bone_names)


def collect_weighted_avatar_bone_names(avatar_arm, meshes):
    """dev#1572(積み荷A、issue #1572追記3、2026-08-18オーナー最終裁定
    「無weightボーンには僕は興味がなく、ないものと扱ってます」):
    `meshes`のいずれかで頂点ウェイト>0の頂点グループを実際に持つ
    avatar_arm骨名の集合を返す(`sway_hub_wire.filter_entries_by_
    weighted_bones()`の`weighted_bone_names`引数へそのまま渡せる)。

    「実重み」の判定規約は既存の`_sway_gate_donor_transforms_and_weights()`
    (`g.weight > 0.0`)/`build_pak_from_avatar._dump_used_bone_names()`
    (`w > 0`)と同一——weight>0の頂点グループのみを「実際に使うボーン」と
    数える、プロジェクト全体で一貫した規約(2箇所目の再実装ではなく、
    同じ判定基準をbpy側で独立に評価しているだけ——dumpはBlender工程の
    **後**に書き出されるため、鎖抽出〜フィット入力の時点ではまだ存在
    しない)。

    頂点グループが1つも参照されないメッシュ(`obj.type != 'MESH'`含む)は
    黙ってスキップする(既存の`_sway_gate_donor_transforms_and_weights()`の
    フォールバックと同じ安全側方針)。"""
    names = set()
    for obj in meshes:
        if obj.type != "MESH":
            continue
        vg_by_idx = {vg.index: vg.name for vg in obj.vertex_groups}
        if not vg_by_idx:
            continue
        used_idx = set()
        for v in obj.data.vertices:
            for g in v.groups:
                if g.weight > 0.0:
                    used_idx.add(g.group)
        for idx in used_idx:
            name = vg_by_idx.get(idx)
            if name:
                names.add(name)
    return frozenset(names)


def wire_sway_hub_auto(job, gender, physbone_entries, vanilla, group_targets,
                        lab_assignments=None, quiet=False, weighted_bone_names=None):
    """dev#1508 W2a-2c本体: job["sway_enable"]が真のとき、PB/SB由来の
    自動割当(候補判定・無偏向判定・量子化・グループ化・容量9)を
    `pipeline\\py\\sway_hub_wire.py`(bpy非依存)経由で実行し、`sway_hub.
    HubWiringPlan`(トポロジ計画のみ、座標は含まない)を返す。

    旧`auto_assign_sway_chains()`(sway_allocator_wire.wire_and_diagnose()
    →sway_assign.pyのfamily限定donor経路)は、PB/SB自動割当についてはもう
    呼ばれない——手動指定(job["sway_manual"])専用に縮小した
    (`auto_assign_sway_chains()`のdocstring参照)。

    `vanilla/sk_palhuman_full.json`(`extract_vanilla.
    extract_shared_skeleton_catalog()`が書き出す、共有Skeleton4079骨の
    rest transformカタログ)が無ければ、揺れドナー在庫が未抽出という
    既存の安全側フォールバックと同じ扱いで空のHubWiringPlanを返す
    (die()しない、旧`build_donor_bone_pairs_from_vanilla()`が空リストの
    ときと同じ「在庫が無いので配線なし」の規約)。

    `group_targets`({アバター骨名->PALボーン名}、`build_group_targets()`の
    戻り値、呼び出し側が本関数より前に計算しておくこと): PB/SBの
    `anchor`(コンポーネントのrootTransform名)がavatar_armの実ボーンに
    対応しない場合(NDMFベイク後に生成される$GUID付き名前がボーンとして
    インポートされない等、実データ検証で確認済みの実例)、そのグループを
    `sway_hub.filter_wiring_by_resolvable_anchor()`でunassignable側へ
    理由付きで移してから(die()しない)、node_overrides/diagnostics_lines/
    refskel_dictを**フィルタ後のwiringに対して再計算**する(フィルタ前の
    値を使うと、実際には配線されないグループのKPノードoverride/donor骨が
    紛れ込む)。

    dev#1551/dev#1572(安全域WP、issue #1551「安全域」欄、2026-08-18オーナー
    最終裁定で式を訂正): 本関数は常に`SWAY_DEFAULT_SAFETY_MARGIN`(製品既定値、
    現在1)を`sway_hub_wire.wire_and_diagnose_hub()`へ渡す——GUIラボ「揺れもの
    詳細設定」を一切触っていなくても、全鎖が既定でこの本数だけ分配マージで
    縮約される(`sway_hub.target_len_with_safety_margin()`
    「反映骨数=min(donor容量−安全域,アバター鎖長)」、安全域はdonor容量だけを
    削る)。鎖ごとの上書きは`job["sway_chain_overrides"]`(GUI由来、
    `_safety_margin_overrides_from_job()`が抽出)経由で反映される。
    **2026-08-19朝追加裁定(dev#1572「余剰donorの先端延長を全donor登録へ
    訂正」)**: 安全域が動かすのはこの「反映骨数」(実ウェイトを持つ内容
    donor本数)だけであり、native chain経路で実際に*登録*されるdonor本数
    (`sway_hub.ChainDonorPlan.donor_chain_female`/`donor_chain_male`)は
    安全域と無関係に常にhub root native descendantの全長で不変——内容を
    超えた残りは無ウェイトの直線延長として`place_hub_donor_chains()`が
    自動的に配置する(`sway_hub.plan_hub_wiring()`docstring参照)。

    `weighted_bone_names`(dev#1582、鎖キー正規化修理): `_safety_margin_
    overrides_from_job()`へそのまま渡す(省略時Noneは無変更の安全側
    フォールバック)。呼び出し元`main()`が`physbone_entries`自体のフィルタ
    (dev#1572)に使ったのと同じ集合をここでも使うことで、GUI由来の
    override鎖キー(生catalog形式、`_end`等の無ウェイト骨を含みうる)を、
    実際に配線判定で使われる`extended_source`(weighted-only)と同じ規約へ
    揃える——揃えないとキー不一致でoverrideが誰にも当たらない
    (issue #1582、オーナー実測「安全域9を設定しても左耳がまとまらない」)。

    `lab_assignments`(dev#1508 graceful-degrade、night_20260817 laneI):
    `sway_allocator.LabAssignment`の辞書({unit.key -> LabAssignment})を
    そのまま`sway_hub_wire.wire_and_diagnose_hub()`(既に対応済みの引数)
    経由で`sway_allocator.allocate()`へ渡す。`enabled=False`のunitは
    グループ化より前に非採用へ回るため、そのunit(鎖)だけを無傷の他鎖から
    切り離して除外できる(`sway_degrade.py`モジュールdocstring参照)。
    省略時(None)は従来どおり全unitが自動判定のまま(=縮退なし)。

    `quiet`(同上): Trueなら診断ログ(`=== sway hub diagnostics ===`+
    `unassignable`のWARN行)の出力を抑制する。縮退ループが同じ性別内で
    本関数を複数回(除外セットを変えて)呼び直す際、中間attemptの重複
    ログでノイズを増やさないためのフラグ(最終的に確定したattemptだけ
    呼び出し側が改めて出力する)。

    戻り値: (wiring, node_overrides, diagnostics_lines, refskel_dict)。
    job["sway_enable"]が偽なら空のHubWiringPlan相当+空dict3つ
    (完全no-op)。"""
    empty_plan = sway_hub.HubWiringPlan(group_plans=(), unassignable=())
    if not job.get("sway_enable"):
        return empty_plan, {}, [], {}

    catalog_path = os.path.join(vanilla, "sk_palhuman_full.json")
    if not os.path.isfile(catalog_path):
        print(f"[{TAG}] sway_enable: no shared skeleton catalog found at "
              f"{catalog_path} (vanilla extraction needs to be redone) -- "
              "hub auto assignment skipped, no chains added")
        return empty_plan, {}, [], {}
    catalog = sway_hub.load_skeleton_catalog(catalog_path)

    with open(os.path.join(vanilla, "common_bones.json"), encoding="utf-8") as f:
        common_bones = frozenset(json.load(f)["common"])

    springbone_entries = list(job.get("springbones") or [])
    # dev#1551(2026-08-17オーナー裁定、issue #1551「hubを廃止し1chainあたり
    # 1KPノードへ移行する」): 旧dev#1508 hubwire final(group_targetsを
    # anchor_group_ofとして渡し、耳L(Head_L.001)/R(Head_R.001)のように
    # anchorが別でも親が同じ(headへ解決)なら1グループへ統合していた仕組み)
    # は、ハブ構造(1スロット=複数鎖共有)の実機不具合容疑を受けて廃止した。
    # 以後は1 ChainUnit(=1 PB/SBコンポーネント)が常に1グループ=1KPノードへ
    # 割り当てられる(`sway_allocator.build_groups()`docstring参照、
    # `anchor_group_of`引数自体が削除済み)。
    # dev#1551(安全域WP): 製品既定値(SWAY_DEFAULT_SAFETY_MARGIN)+
    # job["sway_chain_overrides"]由来の鎖ごと上書きを、常にここで注入する
    # (呼び出される側の既定は0=無効化のまま、モジュールdocstring・
    # 定数SWAY_DEFAULT_SAFETY_MARGINのコメント参照)。
    result = sway_hub_wire.wire_and_diagnose_hub(
        physbone_entries=physbone_entries, springbone_entries=springbone_entries,
        gender=gender, catalog=catalog, common_bones=common_bones,
        lab_assignments=lab_assignments,
        default_safety_margin=SWAY_DEFAULT_SAFETY_MARGIN,
        safety_margin_by_chain=_safety_margin_overrides_from_job(
            job, weighted_bone_names=weighted_bone_names))

    wiring = sway_hub.filter_wiring_by_resolvable_anchor(result.wiring, group_targets)
    node_overrides = sway_hub.node_overrides_from_wiring_plan(wiring)
    diagnostics_lines = sway_hub.build_diagnostics_lines(result.plan, wiring, gender)
    # dev#1551 integ14(メッシュ側RefSkeleton reparent欠落の修正): ハブroot骨の
    # refskel-dict上の親を、構造登録専用placeholder("pelvis")ではなく実アンカー
    # (group_targets、`plan_reparent_steps()`が使うanchor_pal_name_ofと同じ辞書)
    # にする。呼び出し元(wire_sway_hub_auto())のこの時点ではgroup_targetsは
    # まだsway donor上書き(.update())前の「標準retarget先」のままなので安全に
    # 使える(呼び出し元コメント「anchor_pal_map」節参照)。
    refskel_dict = sway_hub.refskel_dict_for_wiring(wiring, gender, anchor_pal_of=group_targets)

    if not quiet:
        print(f"[{TAG}] === sway hub diagnostics (dev#1508 W2a-2c, "
              f"{len(diagnostics_lines)} PB/SB component(s)) ===")
        for line in diagnostics_lines:
            print(f"[{TAG}][sway-diag] {line}")
        for group, reason in wiring.unassignable:
            print(f"[{TAG}][WARN][sway-hub] group anchor={group.anchor!r} style="
                  f"{group.style!r} not wired: {reason}")

    return wiring, node_overrides, list(diagnostics_lines), refskel_dict


def build_avatar_dump(avatar_arm, dz):
    """dev#1508 W2a-2c: avatar_arm(pose bones)の全ボーンをUEコンポーネント
    空間へダンプする({name: {"head":[x,-y,z+dz], "tail":[...]}})——
    `reposition_sway_donor_chain_and_leaf()`の`av_point()`と同一の座標規約
    (dz=`snap_to_ground()`の戻り値)。呼び出しタイミングは
    `global_scale_and_place()`+`auto_fit_pose()`+`apply_shoulder_offset()`+
    `bake_pose_into_meshes()`の直後(mesh焼き込み後の最終ポーズ)。
    `place_hub_donor_chains()`が内部で使う座標と完全に同じ規約
    (両者とも本関数と同じdz補正込みの生値を読む)。"""
    mw = avatar_arm.matrix_world
    result = {}
    for pb in avatar_arm.pose.bones:
        h = mw @ pb.head
        t = mw @ pb.tail
        result[pb.name] = {"head": [h.x, -h.y, h.z + dz], "tail": [t.x, -t.y, t.z + dz]}
    return result


def place_hub_donor_chains(pal_arm, avatar_arm, wiring, gender, anchor_pal_map, dz):
    """dev#1508 W2a-2c: `sway_hub.HubWiringPlan`の全グループについて、
    Blender pal_arm内で(1)ハブroot自身をanchor_pal直下へ恒等配置
    (SPEC「rootの置き場所は親骨と同位置で機械決定」)、(2)各donor鎖を
    exact-bone-copy(donor節i<-転写元関節iのhead/tail完全コピー)で配置する。
    `reposition_sway_donor_chain_and_leaf()`(旧family限定donor経路)と
    同一のアルゴリズム・座標規約を踏襲するが、ハブ経路は
    `sway_hub.plan_hub_wiring()`が常にn_donor==len(source_chain)を払い出す
    設計のため、比例配分フォールバック(resample_polyline_or_direct())を
    経由しない(常にexact-bone-copy側の分岐のみ)。

    anchor_pal(ハブrootのreparent先)は`anchor_pal_map`
    ({avatar骨名->PAL骨名}、`build_group_targets()`の戻り値の**凍結
    コピー**、`main()`の`group_targets.update(sway_hub_wire.
    source_to_donor_bone_map(...))`より前の値)から引く。
    **`group_targets`(sway donor上書き済み)を渡してはならない**
    (2026-08-16実データ実測バグ、dev#1508アンカーオフバイワン修正の
    副作用: anchorオフバイワン修正でanchor自身もdonorへ写るように
    なったため、`group_targets[anchor]`が「anchorの標準retarget先」から
    「anchorのdonor骨自身」へ上書きされ、ハブの新親=anchorのdonor骨・
    anchorのdonorの新親=ハブという循環参照になり、共有Skeletonの
    トポロジ制約違反で変換が停止していた。anchor_pal_mapは`main()`が
    `group_targets`の書き換え前にコピーして用意する)。
    anchor_palが未解決/pal_armに存在しない場合、そのグループの配線は
    スキップする(die()しない、`reposition_sway_donor_chain_and_leaf()`と
    同じ安全側フォールバック——node_overrides/refskel_dictは既に生成済み
    だが対応する骨がpal_armに実在しない状態になるだけで、後段の
    `missing`チェック(`main()`のactive_entries検証と同型)が必要なら
    呼び出し側が別途行う)。

    戻り値: donor_quats({donor骨名: (x,y,z,w)、UEコンポーネント空間}、
    `chibi_bone_world_quat_{gender}.json`へマージする)。
    `wiring.group_plans`が空なら即return {}(完全no-op)。"""
    donor_quats = {}
    if not wiring.group_plans:
        return donor_quats

    bpy.ops.object.select_all(action="DESELECT")
    pal_arm.select_set(True)
    bpy.context.view_layer.objects.active = pal_arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = pal_arm.data.edit_bones

    def av_point(name, use_tail=False):
        # dev#1551(donor取付幾何の修理、issue #1551、正本
        # work\run_1551\laneR7_earfix\RESULT.md): 生ポーズ(pose.bones)では
        # なくアバターのrest(data.bones、head_local/tail_local)を読む。
        # laneR6実測(work\run_1551\laneR6_blendcmp\NOTE.md)が、この関数の
        # 呼び出し時点(auto_fit_pose/apply_shoulder_offset/bake_pose_into_
        # meshes後)のavatar_armライブポーズがstep01のrest形状(関節の曲がり
        # 角)を保っていない実データケース(flatapron耳鎖)を確認した。
        # 一方data.bones(rest)はglobal_scale_and_place()のtransform_apply()
        # で一度だけ等方スケール+平行移動が焼き込まれた後、以降のどのコードも
        # avatar_armのedit bone位置を書き換えない(attach_orphan_roots()
        # docstring「EditBone.head/tailはアーマチュア空間の絶対座標であり
        # parentが何であっても値は変化しない」と同種の不変量、実際に
        # 検証済み)。rest基準に切り替えることで、角度・長さ比を保つ等方
        # 変換の性質により、step01の関節形状が写像後も保存される。
        b = avatar_arm.data.bones.get(name)
        if b is None:
            return None
        local = b.tail_local if use_tail else b.head_local
        w = avatar_arm.matrix_world @ local
        return Vector((w.x, w.y, w.z + dz))

    def to_ue(v):
        return (v.x, -v.y, v.z)

    n_groups_placed = 0
    for gp in wiring.group_plans:
        hub_name = gp.hub_root_male if gender == "Male" else gp.hub_root_female
        anchor_pal = anchor_pal_map.get(gp.group.anchor)
        if hub_name not in eb or anchor_pal is None or anchor_pal not in eb:
            print(f"[{TAG}][WARN] sway hub reposition: anchor "
                  f"{gp.group.anchor!r} -> pal bone unresolved, or hub root "
                  f"{hub_name!r} not in pal_arm -- group skipped "
                  "(vanilla placeholder position kept)")
            continue

        # ①ハブroot自身: dev#1551(ゼロ長root廃止修理、issue #1551、正本
        # work\run_1551\laneR1_rootfix\RESULT.md)。旧実装(PR #1560「耳
        # 付け根修正」)はhub root自身を「鎖始点」(=source_chain[1]、chainの
        # 最初の実sway骨)の位置へ動かし、tailをhead+微小オフセット(実質
        # ゼロ長)に固定していた——「1本目のネイティブdonor(実長)を潰して
        # ゼロ長rootに転用し、アバター内容を1donor下へずらして書く」設計
        # (hub時代のn+1専用root思想の名残)。結果、topology上hubの子である
        # donor_chain[0](source_chain[0]=anchor位置)が親であるhub
        # (source_chain[1]位置)よりhead側(上流)に来てしまい、1リンクずれ・
        # 7.8cm空隙・donor1本浪費・可視部が異常区間へのはみ出しが生じて
        # いた(2026-08-17深夜オーナー共同解析、実測: flatHaori耳)。
        #
        # 修正: hub root自身がsource_chain[0](=anchor自身)のexact
        # geometryを直接担う——head=anchorの実head位置、tail方向は
        # source_chain[1](chain[0]、無ければanchor自身のtail)への実位置。
        # 共有Skeleton側`sway_hub_placement._hub_root_real_segment_
        # transform()`と同じ「source_chain[0]/[1]を使う」規約を、
        # `sway_hub_placement.select_first_resolved_hub_segment()`
        # (単一ソース化した制御構造)経由でBlender側でも再現する。
        # av_pointが解決できない(対象ボーンがavatar_armに無い)場合・
        # `chain_plans`が空の場合は、従来どおりanchor_pal直下の恒等配置へ
        # フォールバックする(無退行、共有側のIDENTITY_TRANSFORM
        # フォールバックと同型の安全側動作)。
        anchor_eb = eb[anchor_pal]
        hub_eb = eb[hub_name]
        # dev#1551(chain-length-fit WP追修理): hub_eb.parentへの張り替え前に
        # use_connect=Falseを明示する。EditBone.use_connect=Trueだと子head
        # が親tailへ強制的に一致させられ(attach_orphan_roots()docstring
        # 「use_connect時のみ子headが強制的に親tailへ一致させられる」参照)、
        # 直後の`hub_eb.head = ...`明示代入が無視されてしまう。旧来は自由
        # プールの無関係な骨(vanillaでuse_connect=Falseなことが多い)だけを
        # donorに使っていたため症状が顕在化しなかったが、本WPでハブ自身の
        # native直系子孫(vanillaで意図的に連結=use_connect=Trueなことが
        # 多い、実データ2026-08-17実測: 耳donorの直後gate_transform FAILで
        # 発覚)をdonorに使うようになったため必須の防御になった。
        hub_eb.use_connect = False
        hub_eb.parent = anchor_eb

        def _resolve_hub_segment(cp):
            # dev#1572(夜間便2): tailの向きは「source_chain[1](=fit後の
            # 代表骨)自身」ではなく、`sway_hub.donor_group_members()`で
            # 引いたその代表グループの**先頭骨**(根元寄り、常に元の鎖の
            # chain[0]そのもの)のheadを使う——節数フィットで代表が先端側
            # (マージ区間の末尾)へ動いても、hub root自身のtail方向は
            # 常に「アバターの実際に次の関節」を指す(モジュールdocstring
            # 「①ハブroot自身」の意図どおり)。旧実装は代表名を直接
            # av_pointしていたため、フィットが発動するとhub root自身が
            # マージ区間の末尾まで異常に伸びていた(実測: flatapron耳、
            # 7.8cmのはずが26.7cmに肥大)。
            # dev#1572(第2便、安全域マージの全結合(実効節数1)修理):
            # headの側にも同じ理屈を適用する。`src[0]`(=fit後の唯一の
            # 代表)は通常(根本がマージされていない)ならそれ自身が根本
            # (=anchor)だが、実効節数1の全結合(`fit_chain_to_length(
            # chain,1)`)が発動すると`src[0]`はグループの末尾側(先端寄り)
            # 要素名になり、真のanchor(グループの先頭骨)の位置とは
            # 一致しない(共有Skeleton側`sway_hub_placement.
            # _hub_root_real_segment_transform()`の同型修正と同じ考え方)。
            # `sway_hub.donor_group_members(cp)[src[0]][0]`は常にその
            # グループの先頭骨を指すため、これ経由でheadを引く(通常
            # ケースは`members0[0]==src[0]`で無変更)。
            src = list(cp.source_chain)
            if not src:
                return None
            members0 = sway_hub.donor_group_members(cp).get(src[0], (src[0],))
            head = av_point(members0[0])
            if head is None:
                return None
            if len(src) < 2:
                tail = av_point(src[0], use_tail=True)
                return None if tail is None else (head, tail)
            rep = src[1]
            members = sway_hub.donor_group_members(cp).get(rep, (rep,))
            tail = av_point(members[0])
            if tail is None:
                tail = av_point(rep)  # 退化フォールバック(旧来どおり代表自身)
            if tail is None:
                return None
            return head, tail

        hub_segment = sway_hub_placement.select_first_resolved_hub_segment(
            gp.chain_plans, _resolve_hub_segment)

        if hub_segment is not None:
            natural_head, natural_tail = hub_segment
            hub_eb.head = pal_arm.matrix_world.inverted() @ natural_head
            hub_eb.tail = pal_arm.matrix_world.inverted() @ natural_tail
        else:
            hub_eb.head = anchor_eb.head.copy()
            hub_eb.tail = hub_eb.head + Vector((0.0, 0.0, 0.02))
        hub_world_head = pal_arm.matrix_world @ hub_eb.head
        hub_world_tail = pal_arm.matrix_world @ hub_eb.tail

        # hub自身の向き(quat、UEコンポーネント空間)も③と同じ規約で計算し、
        # donor_quats/exact_donor_worldへ記録する(dev#1551: hub自身が
        # exact_donor_worldの直接のキーになった、`main()`側の集約コード
        # 参照)。head==tail(退化)の場合はローカル+X軸をそのまま向ける。
        hub_dir_ue = to_ue(hub_world_tail - hub_world_head)
        hub_dir_len = math.sqrt(sum(c * c for c in hub_dir_ue))
        if hub_dir_len < 1e-6:
            donor_quats[hub_name] = (0.0, 0.0, 0.0, 1.0)
        else:
            donor_quats[hub_name] = sway_hub_placement.q_find_between(
                (1.0, 0.0, 0.0), tuple(c / hub_dir_len for c in hub_dir_ue))

        # ②各donor鎖: exact-bone-copy(dev#1572夜間便2: フィット計画
        # (`cp.weight_expansion`)由来のグループ境界を、ここ(donor rest幾何)
        # と`sway_hub_wire.source_to_donor_bone_map()`(ウェイト写像)の
        # 両方が`sway_hub.donor_group_members()`という同じ1つの関数から
        # 導出する——二重グルーピング実装の解消(issue #1572追記3)。
        #
        # `source_to_donor_bone_map()`と同じ整列規約:
        # `(hub_name,) + donor_chain`を`cp.source_chain`とzipするのと
        # 同義で、`donor_chain[i]`(0始まり)は`cp.source_chain[i+1]`の
        # 代表グループに対応する。旧実装は`cp.source_chain`の各代表名を
        # そのまま「元の鎖の1点」としてav_pointしており、代表名自身の
        # 位置しか読まず、マージされた非代表メンバー(グループの先頭側)の
        # 位置を無視していた——`fit_chain_to_length()`docstring「マージ塊の
        # donorノード幾何(呼び出し側の責務): 塊の先頭骨のheadから末尾骨の
        # tailまでのスパン」が未実装のまま放置されていたのが根因
        # (実測: flatapron耳donor、幾何は[001+002]スパンなのにウェイトは
        # [Head_L.001]単独、というグループ境界の不一致)。
        parent_eb = hub_eb
        for cp in gp.chain_plans:
            src = list(cp.source_chain)
            if not src:
                print(f"[{TAG}][WARN] sway hub reposition: empty source_chain "
                      f"(anchor={gp.group.anchor!r}) -- chain skipped")
                continue

            # dev#1572(第2便、安全域マージの全結合(実効節数1)修理):
            # `src[0]`を直接av_pointするのは、`src[0]`の代表グループが
            # 単独(=`(src[0],)`)であるとき(通常、根本がマージされて
            # いないとき)にしか正しくない。`fit_chain_to_length()`の
            # 「実効節数1のときだけ根本も含めた全結合」例外が発動すると、
            # `src[0]`(=唯一の代表)はグループの末尾側(先端寄り)要素名に
            # なり、グループの先頭骨(=真のanchor自身)の位置とは一致
            # しない。`sway_hub.donor_group_members(cp)[src[0]][0]`は
            # 常にそのグループの先頭骨を指すため、これ経由でanchor_ptを
            # 引く(通常ケースは`anchor_members[0]==src[0]`で無変更、
            # 共有Skeleton側`sway_hub_placement.resolve_grouped_chain()`の
            # 同型修正と同じ考え方)。
            anchor_members = sway_hub.donor_group_members(cp).get(src[0], (src[0],))
            anchor_pt = av_point(anchor_members[0])
            if anchor_pt is None:
                # 退化ケース(sway_hub_placement.resolve_source_chain()の
                # 縮退フォールバックと同じ考え方、Blender-native実装):
                # anchor自身が引けないなら、そのグループのanchor代表点で
                # 単独点として使う。
                anchor_pt = av_point(gp.group.anchor)
                if anchor_pt is None:
                    print(f"[{TAG}][WARN] sway hub reposition: no resolvable "
                          f"point for chain {cp.source_chain} (anchor="
                          f"{gp.group.anchor!r}) -- chain skipped")
                    continue

            # dev#1551(性別またぎdedup漏れ修正): bivariantなハブスロットでは
            # 女性向け/男性向けで互いに素なdonor骨集合を持つ(`ChainDonorPlan.
            # donor_chain_for()`docstring参照)。この関数は性別ごとに別々の
            # Blenderプロセスから1回だけ呼ばれる(`gender`は関数引数)ので、
            # ここでは常にこのプロセスのgender向けの骨列だけを使う。
            donor_chain = cp.donor_chain_for(gender)
            n_donor = len(donor_chain)
            group_members = sway_hub.donor_group_members(cp)

            # donor_heads[i]/donor_tails[i]: donor_chain[i]が担うべき
            # 「塊の先頭骨head 〜 末尾骨tail」(未解決/余剰donorはNoneのまま
            # 残し、後段でtipからの延長で埋める——`fit_chain_to_length()`の
            # 「マージ塊のdonorノード幾何」規約そのもの)。
            donor_heads = [None] * n_donor
            donor_tails = [None] * n_donor
            for i in range(n_donor):
                src_idx = i + 1
                if src_idx >= len(src):
                    continue  # 余剰donor(内容写像の対応が無い延長donor)
                rep = src[src_idx]
                members = group_members.get(rep, (rep,))
                head_pt = av_point(members[0])
                tail_pt = av_point(members[-1], use_tail=True)
                if head_pt is None:
                    head_pt = av_point(rep)  # 退化フォールバック(旧来どおり)
                if tail_pt is None:
                    tail_pt = av_point(rep, use_tail=True)
                donor_heads[i] = head_pt
                donor_tails[i] = tail_pt

            # tip: 延長方向の基準(最後に解決できたdonorのtail、無ければ
            # anchor自身のtail)。
            tip = next((t for t in reversed(donor_tails) if t is not None), None)
            if tip is None:
                tip = av_point(src[0], use_tail=True)
            if tip is None:
                tip = anchor_pt + Vector((0.0, 0.0, 2.0))

            last_resolved = next((h for h in reversed(donor_heads) if h is not None), anchor_pt)
            seg_vec = tip - last_resolved
            if seg_vec.length < 1e-6:
                seg_vec = Vector((0.0, 0.0, 1.0))

            extend_point = tip
            for i in range(n_donor):
                if donor_heads[i] is None:
                    donor_heads[i] = extend_point
                    extend_point = extend_point + seg_vec
            for i in range(n_donor):
                if donor_tails[i] is None:
                    donor_tails[i] = (donor_heads[i + 1] if i + 1 < n_donor
                                       else donor_heads[i] + seg_vec)

            local_heads = [pal_arm.matrix_world.inverted() @ p for p in donor_heads]
            local_tails = [pal_arm.matrix_world.inverted() @ p for p in donor_tails]

            for i, name in enumerate(donor_chain):
                b = eb[name]
                # dev#1551(chain-length-fit WP追修理): 上のhub_eb同様、
                # use_connect=Trueだと直後のb.head代入が無視される
                # (native donor chainで新規に顕在化した実データバグ)。
                b.use_connect = False
                b.parent = parent_eb if i == 0 else eb[donor_chain[i - 1]]
                b.head = local_heads[i]
                b.tail = local_tails[i]

            # ③donor回転の再構成(dev#19 rotfix WPと同一の考え方):
            # 各donor自身のhead->tail(=①②で確定した実スパン)から、
            # "自分->子方向"がローカル+Xを満たすquatをUEコンポーネント
            # 空間で再構成する。
            chain_dirs = [to_ue(local_tails[i] - local_heads[i]) for i in range(n_donor)]
            chain_quats = sway_hub_placement.build_donor_chain_quats(chain_dirs)
            for name, q in zip(donor_chain, chain_quats):
                donor_quats[name] = q
        n_groups_placed += 1

    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"[{TAG}] sway hub reposition: {n_groups_placed}/{len(wiring.group_plans)} "
          "group(s) placed")
    return donor_quats


# =====================================================================
# dev#1508 受入ゲート正本化(オーナー制定文言、fail-closed)
# =====================================================================

def sway_gate_compute_source_bone_names(physbone_entries, springbone_entries,
                                         lab_assignments=None):
    """`sway_source_bones.py`(配線実装(sway_hub/sway_hub_wire)から独立)で
    「揺れると判定された全ボーン」(anchor含む)の名前集合+骨名->
    group_key集合の対応を導出する。

    `lab_assignments`(dev#1508 graceful-degrade、night_20260817 laneI):
    `sway_allocator.allocate()`へそのまま渡す。縮退ループが除外した
    unit.keyは`enabled=False`でここにも反映され、この関数が独立に
    再導出する対象骨集合からも一貫して除外される(`wire_sway_hub_auto()`
    に渡す`lab_assignments`と常に同じ値を使うこと——呼び出し側の責務)。

    `sway_hub_wire.wire_and_diagnose_hub()`が内部で行う`sway_allocator.
    allocate()`と全く同じ入力(physbone_entries/springbone_entries、
    lab_assignments省略=None、capacity省略=既定9)で独立に再実行する
    (決定論的な純関数のため同一結果になる——判定ロジック自体
    (sway_allocatorが正)は変更せず、対象骨集合の"展開"だけを配線コードの
    外で行う、SPEC.md §5裁定参照)。

    戻り値: (全対象骨名の集合, {骨名 -> {group_key, ...}}, 支点(anchor)名の
    集合)。第2要素は呼び出し側が`hub_wiring.unassignable`(容量9・donor
    在庫枯渇・anchorのPAL側retarget未解決という**既存の正常フォールバック**、
    SPEC §3-1)を理由に、dev#1508バグとは別種の「配線できないと判明済み」の
    骨をゲート対象から除外する判定に使う(`sway_source_bones.
    bone_group_keys()`docstring参照)。第3要素(dev#1508 hubwire final、
    公理検査`sway_pivot_axiom.py`向け)はchainsを含まない、anchor自身
    だけの集合(`sway_source_bones.accepted_anchor_names()`)。

    戻り値(dev#1508 graceful-degrade追加): 第4要素として`plan`
    (`sway_allocator.AllocationPlan`)自体も返す——縮退ループが
    `sway_source_bones.bone_unit_keys(plan)`(unit粒度の帰属表)を
    追加で導出するために必要(既存呼び出し元は3要素のみ使うため、
    タプルのunpack数を変えずに追加要素を末尾へ足す形にした)。"""
    physbones_raw = {"physbones": list(physbone_entries or [])}
    springbones_raw = {"springbones": list(springbone_entries or [])}
    plan = sway_allocator.allocate(
        physbones_json=physbones_raw, springbones_json=springbones_raw,
        lab_assignments=lab_assignments)
    return (sway_source_bones.all_accepted_source_bone_names(plan),
            sway_source_bones.bone_group_keys(plan),
            sway_source_bones.accepted_anchor_names(plan),
            plan)


def _sway_gate_live_source_transforms(avatar_arm, bone_names, output_scale, dz,
                                       use_rest=True):
    """`bone_names`(独立導出済みの対象骨名)について、avatar_armから
    配線ロジック(`sway_hub`/`sway_hub_wire`の`av_point()`関数そのもの)を
    一切呼ばず直接world head/tailを読む(`sway_source_gate.py`モジュール
    docstring「Transform完全一致」節参照、構造的独立性のためこの関数は
    sway_hub/sway_hub_wireをimportしない)。

    **座標規約は、比較先(donor骨)を実際に配置した関数の規約と完全に
    一致させる**(揃えないと「ゲートの左辺の作り方が違う」ことによる
    誤検知になる、2026-08-16実データ検証で発見・修正)。`use_rest`
    (dev#1551、2026-08-18追加)がその切り替えスイッチ:

    - `use_rest=True`(既定): `b.head_local`/`b.tail_local`(rest、
      armatureローカル)を読む。`place_hub_donor_chains()`のav_point()が
      pose.bones基準からdata.bones(rest)基準へ切り替わった(dev#1551
      donor取付幾何の修理)のに揃える——sway対象骨(anchor自身+chain)は
      すべてこちら。
    - `use_rest=False`: `pb.head`/`pb.tail`(ライブポーズ)を読む
      (旧来の挙動)。`sway_pivot_axiom`の「親」側(CHIBI_CANDIDATES経由の
      標準humanoidボーン、例: "Head")はchibi_fit_armature()が今なお
      ライブポーズ(`avatar_arm.pose.bones[av].head`)を読んで配置する
      ため、この呼び出し元だけはFalseを渡し、比較先の実際の配置基準に
      揃える(chibi_fit_armature()自体は本WPのスコープ外、無改変)。

    揃えない場合、avatar_armのライブポーズがrestからわずかにでもズレて
    いれば(実測: flatapron耳anchor自身で約2.1mm、laneR7実測)、
    `sway_pivot_axiom`(許容0.1mm)が誤って公理違反を検出する。

    `output_scale`: `apply_output_scale()`がdonor骨のworld位置へ事後的に
    掛ける一様スケール(既定1.0=no-op)。avatar_arm自体はこのスケールを
    経ないため、位置・tail成分にだけ同じ係数を掛けて正規化する(donor側の
    最終スケールへ揃える)。

    dev#1508 hubwire final(公理検査、2026-08-16): "quat"(world回転、
    `sway_pivot_axiom.relative_vector()`の「親world逆行列適用」に必要)も
    追加で出す——回転はdz(平行移動)にもoutput_scale(一様スケール)にも
    影響されないため無補正でそのまま返す。既存の"pos"/"tail"/"scale"
    キーは無変更(追加のみ、既存呼び出し元への影響なし)。"""
    out = {}
    for name in bone_names:
        if use_rest:
            b = avatar_arm.data.bones.get(name)
            if b is None:
                continue
            world_matrix = avatar_arm.matrix_world @ b.matrix_local
            head_w = avatar_arm.matrix_world @ b.head_local
            tail_w = avatar_arm.matrix_world @ b.tail_local
        else:
            pb = avatar_arm.pose.bones.get(name)
            if pb is None:
                continue
            world_matrix = avatar_arm.matrix_world @ pb.matrix
            head_w = avatar_arm.matrix_world @ pb.head
            tail_w = avatar_arm.matrix_world @ pb.tail
        scale = world_matrix.to_scale()
        quat = world_matrix.to_quaternion()
        out[name] = {
            "pos": [head_w.x * output_scale, head_w.y * output_scale,
                    (head_w.z + dz) * output_scale],
            "tail": [tail_w.x * output_scale, tail_w.y * output_scale,
                     (tail_w.z + dz) * output_scale],
            "scale": [scale.x, scale.y, scale.z],
            "quat": [quat.x, quat.y, quat.z, quat.w],
        }
    return out


def _sway_gate_donor_transforms_and_weights(pal_arm, meshes, donor_names):
    """`donor_names`(group_targets経由で解決したdonor骨名の集合)について、
    pal_arm内でのworld head/tail(向きの比較に使う、`sway_source_gate.py`
    モジュールdocstring「回転の比較方法」節参照)+全meshにおける頂点
    ウェイトテーブルを集める(ゲート右辺)。

    dev#1508 hubwire final(公理検査、2026-08-16): "quat"(world回転)も
    追加で出す(`_sway_gate_live_source_transforms()`と対になる、
    `sway_pivot_axiom`向け)。既存の"pos"/"tail"/"scale"キーは無変更。"""
    transforms = {}
    weights = {}
    for name in donor_names:
        b = pal_arm.data.bones.get(name)
        if b is None:
            continue
        world_matrix = pal_arm.matrix_world @ b.matrix_local
        head_w = pal_arm.matrix_world @ b.head_local
        tail_w = pal_arm.matrix_world @ b.tail_local
        scale = world_matrix.to_scale()
        quat = world_matrix.to_quaternion()
        transforms[name] = {
            "pos": [head_w.x, head_w.y, head_w.z],
            "tail": [tail_w.x, tail_w.y, tail_w.z],
            "scale": [scale.x, scale.y, scale.z],
            "quat": [quat.x, quat.y, quat.z, quat.w],
        }
        per_mesh = {}
        for obj in meshes:
            vg = obj.vertex_groups.get(name)
            if vg is None:
                continue
            idx = vg.index
            per_vertex = {}
            for v in obj.data.vertices:
                for g in v.groups:
                    if g.group == idx and g.weight > 0.0:
                        per_vertex[str(v.index)] = g.weight
                        break
            if per_vertex:
                per_mesh[obj.name] = per_vertex
        weights[name] = per_mesh
    return transforms, weights


class _SwayGatePrep:
    """`_sway_gate_prepare()`の戻り値(dev#1508 graceful-degrade、
    night_20260817 laneI: `run_sway_source_gate()`(remap後、最終防衛線)と
    縮退ループの事前チェック(remap前)の両方が同じ準備ロジックを共有する
    ための抽出)。"""

    __slots__ = ("real_source_bone_names", "source_transform_snapshot",
                 "source_weight_snapshot", "donor_transform_snapshot",
                 "donor_weight_snapshot", "anchor_parent_of",
                 "axiom_baseline_pos", "axiom_observed_pos", "plan")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw[k])


def _sway_gate_prepare(job, gender, physbone_entries, springbone_entries,
                        avatar_arm, pal_arm, meshes, group_targets,
                        hub_wiring, dz, pal_map, source_parent_of,
                        lab_assignments=None, quiet=False):
    """`run_sway_source_gate()`(remap後・weight込みの最終防衛線)と、
    縮退ループの事前チェック(`place_hub_donor_chains()`直後・remap前、
    `meshes=[]`でweight取得を省く)の両方が共有する準備ロジック
    (dev#1508 graceful-degrade、night_20260817 laneI で抽出)。

    対象骨が0件(非swayジョブ/全ユニット非採用/unassignable以外に残りが
    無い)なら`None`を返す(呼び出し側は「ゲート自体をスキップ(no-op)」
    として扱う)。"""
    all_source_bone_names, bone_group_keys, accepted_anchors, plan = \
        sway_gate_compute_source_bone_names(
            physbone_entries, springbone_entries, lab_assignments=lab_assignments)
    if not all_source_bone_names:
        if not quiet:
            print(f"[{TAG}] sway_source_gate: no judged-swaying bones (non-sway job "
                  "or all units rejected) -- gate skipped (no-op)")
        return None

    unassignable_group_keys = {
        f"{g.group_key[0]}|{g.group_key[1]}" for g, _reason in hub_wiring.unassignable}
    source_bone_names = set()
    exempted = []
    for name in all_source_bone_names:
        gks = bone_group_keys.get(name, frozenset())
        if gks and gks <= unassignable_group_keys:
            exempted.append(name)
            continue
        source_bone_names.add(name)
    if exempted and not quiet:
        print(f"[{TAG}] sway_source_gate: {len(exempted)} bone(s) exempted "
              f"(belong to hub_wiring.unassignable groups -- capacity/donor-pool/"
              f"anchor-resolution fallback, not dev#1508): {sorted(exempted)}")
    if not source_bone_names:
        if not quiet:
            print(f"[{TAG}] sway_source_gate: all judged-swaying bones exempted "
                  "(unassignable groups only) -- gate skipped (no-op)")
        return None

    snapshot_path = os.path.join(
        core.job_subdir(job, "build", "atlas"), "step01_sway_snapshot.json")
    if not os.path.isfile(snapshot_path):
        core.die(TAG, f"sway_source_gate: step01 snapshot not found at "
                 f"{snapshot_path} -- step01_import_vrm.py must run before "
                 "this gate can verify anything (dev#1508 fail-closed)")
    with open(snapshot_path, encoding="utf-8") as f:
        step01_snapshot = json.load(f).get("bones", {})
    source_weight_snapshot = {
        name: entry.get("weights", {}) for name, entry in step01_snapshot.items()}

    anchor_parent_of = sway_pivot_axiom.resolve_anchor_parent_avatar_names(
        sorted(accepted_anchors & source_bone_names), pal_map, source_parent_of)

    output_scale = float(job.get("uniform_scale", 1.0))
    source_transform_snapshot = _sway_gate_live_source_transforms(
        avatar_arm, source_bone_names, output_scale, dz)

    pelvis_pal_name = "pelvis"
    parent_avatar_names = set(anchor_parent_of.values())
    parent_names_at_pelvis = {p for p in parent_avatar_names
                               if group_targets.get(p) == pelvis_pal_name}
    parent_names_elsewhere = parent_avatar_names - parent_names_at_pelvis
    # dev#1551(2026-08-18): 親(anchor_parent_of.values())は標準humanoidボーン
    # (CHIBI_CANDIDATES経由、例: "Head"/"pelvis")であり、そのPAL側配置は
    # 今なおchibi_fit_armature()(本WPのスコープ外、無改変)がライブポーズ
    # (`pb.head`)を読んで行う。そのため親側だけはuse_rest=False(ライブ
    # ポーズ)のまま——比較先の実際の配置基準に揃える、上記関数docstring
    # 参照。anchor自身(source_transform_snapshot、上)はrest(既定)のまま。
    parent_source_transform_snapshot = {}
    if parent_names_at_pelvis:
        parent_source_transform_snapshot.update(_sway_gate_live_source_transforms(
            avatar_arm, parent_names_at_pelvis, output_scale, 0.0, use_rest=False))
    if parent_names_elsewhere:
        parent_source_transform_snapshot.update(_sway_gate_live_source_transforms(
            avatar_arm, parent_names_elsewhere, output_scale, dz, use_rest=False))

    real_source_bone_names = {b for b in source_bone_names if b in source_transform_snapshot}
    ghost_bones = source_bone_names - real_source_bone_names
    if ghost_bones and not quiet:
        print(f"[{TAG}] sway_source_gate: {len(ghost_bones)} bone(s) exempted "
              f"(not real pose bones in avatar_arm -- synthetic '_end' chain-tip "
              f"markers per the existing tail-end-marker convention): "
              f"{sorted(ghost_bones)}")

    anchor_parent_of = {a: p for a, p in anchor_parent_of.items()
                         if a in real_source_bone_names}

    donor_names = {group_targets[b] for b in real_source_bone_names if b in group_targets}
    parent_donor_names = {group_targets[p] for p in anchor_parent_of.values()
                           if p in group_targets}
    donor_transform_snapshot, donor_weight_snapshot = \
        _sway_gate_donor_transforms_and_weights(
            pal_arm, meshes, donor_names | parent_donor_names)

    axiom_baseline_pos = {}
    axiom_observed_pos = {}
    for anchor, parent in anchor_parent_of.items():
        src_a = source_transform_snapshot.get(anchor)
        src_p = parent_source_transform_snapshot.get(parent)
        if src_a is not None:
            axiom_baseline_pos[anchor] = src_a["pos"]
        if src_p is not None:
            axiom_baseline_pos[parent] = src_p["pos"]
        donor_a = group_targets.get(anchor)
        donor_p = group_targets.get(parent)
        obs_a = donor_transform_snapshot.get(donor_a) if donor_a else None
        obs_p = donor_transform_snapshot.get(donor_p) if donor_p else None
        if obs_a is not None:
            axiom_observed_pos[anchor] = obs_a["pos"]
        if obs_p is not None:
            axiom_observed_pos[parent] = obs_p["pos"]

    return _SwayGatePrep(
        real_source_bone_names=real_source_bone_names,
        source_transform_snapshot=source_transform_snapshot,
        source_weight_snapshot=source_weight_snapshot,
        donor_transform_snapshot=donor_transform_snapshot,
        donor_weight_snapshot=donor_weight_snapshot,
        anchor_parent_of=anchor_parent_of,
        axiom_baseline_pos=axiom_baseline_pos,
        axiom_observed_pos=axiom_observed_pos,
        plan=plan,
    )


def _finalize_sway_source_gate_result(report, axiom_report, report_path, axiom_report_path):
    """dev#1592(2026-08-19 オーナー裁定、この指示書に埋め込み済み):
    sway_source_gate FAILをFATAL停止からWARNING継続へ格下げする——
    「配布物におけるゲートはエラーレベルはなく、ワーニングどまり(つまり、
    壊れているおそれがあるなら告知をしたうえでとりあえず成果物をユーザーに
    出す)にすべき」。思想録の明文と一致: 「製品に組み込む検査機構は
    『問題を早めにユーザーに警告し、心構えを促す』目的のみに使える。
    『危ないかもしれないから渡さない』目的に実施してはならない」。

    検査ロジック・JSON出力の粒度は一切弱めない(呼び出し元が`report_path`/
    `axiom_report_path`へ書き出す"ok": false付きJSONは従来どおり——
    relgate/preflight等の機械判定はそのJSONを読めば従来と同じ精度で
    判定できる)。変わるのは本関数が「変換全体を止めるか、続けるか」の
    一点のみ(bpy非依存の純粋関数として抽出——`report`/`axiom_report`は
    `sway_source_gate.GateReport`/`sway_pivot_axiom.PivotAxiomReport`
    (いずれもbpy非依存dataclass)、`report_path`/`axiom_report_path`は
    プレーンな文字列パスなので、Blender起動なしに単体テストできる)。
    """
    if not report.ok or not axiom_report.ok:
        for line in report.summary_lines():
            print(f"[{TAG}][sway-gate] {line}")
        for line in axiom_report.summary_lines():
            print(f"[{TAG}][sway-gate] {line}")
        reasons = []
        if not report.ok:
            reasons.append(f"transform/weight gate {len(report.failed)}/"
                            f"{len(report.results)} bone(s) FAILED (see {report_path})")
        if not axiom_report.ok:
            reasons.append(f"pivot axiom {len(axiom_report.failed)}/"
                            f"{len(axiom_report.results)} pivot(s) FAILED "
                            f"(see {axiom_report_path})")
        # dev#1592: 従来はここで core.die(TAG, ...) して変換全体を停止して
        # いた(dev#1508 fail-closed accept gate)。オーナー裁定により停止を
        # 廃止し、WARNINGとして記録した上で変換を継続する(成果物は必ず
        # 出す)。FAIL件数とJSONパスはWARNINGメッセージに含めたまま
        # (ログだけで原因に到達できる、CLAUDE.md「問い合わせからの
        # デバッグ」節の方針を踏襲)。
        print(f"[{TAG}][WARN][sway-gate] sway_source_gate FAILED "
              f"({'; '.join(reasons)}) -- continuing without stopping the "
              "conversion (dev#1592: WARNING継続化、検査は維持したまま "
              "成果物を必ず出す)")
        return
    print(f"[{TAG}] sway_source_gate: PASS ({len(report.results)}/"
          f"{len(report.results)} bone(s), source-basis 1:1, {report_path}; "
          f"pivot axiom {len(axiom_report.results)}/{len(axiom_report.results)} "
          f"pivot(s), {axiom_report_path})")


def run_sway_source_gate(job, gender, physbone_entries, springbone_entries,
                          avatar_arm, pal_arm, meshes, group_targets, conv, vanilla,
                          hub_wiring, dz, pal_map, source_parent_of,
                          lab_assignments=None):
    """dev#1508 受入ゲート正本化 本体(オーナー制定文言、fail-closed):
    「step02は、step01のモデルにおいて揺れると判定された全ボーンの
    Transform(位置・回転・スケール)を完全に保持し、メッシュに対しても
    ウェイト値そのもの(頂点集合+重み)を完全に保持する。誤差0(浮動小数点
    epsilonのみ許容)」。

    `pal_map`/`source_parent_of`(dev#1508 hubwire final、公理検査
    `sway_pivot_axiom.py`向け、2026-08-16オーナー制定「揺れものの支点は、
    その親humanoidボーンに対して相対位置が一切変わらない」): `pal_map`は
    `meta["pal_map"]`(標準骨のretarget対応表)、`source_parent_of`は
    {アバター骨名 -> 親骨名}(avatar_arm.data.bonesから呼び出し側が組み立て
    済み、`auto_assign_sway_chains()`と同じ形)。どちらも支点(anchor)の
    「親humanoidボーン」解決に使う。

    対象骨が0件(非swayジョブ、または全ユニットが偏向/容量超過で非採用)
    なら即no-op(ゲート自体を実行しない、既存出力に一切影響しない)。

    左辺: 位置/回転/スケールは`avatar_arm`(donor配置と同じポーズ状態)を
    独立に再読み取り。頂点ウェイトは`build\\atlas\\step01_sway_snapshot.json`
    (`step01_import_vrm.py`が書き出したstep01時点のground truth)。

    **既存の正常フォールバック(容量9・donor在庫枯渇・anchorのPAL側
    retarget未解決)との切り分け(実地検証2026-08-16で発見)**:
    `sway_allocator.allocate()`の「採用」は骨配線(donor配置)の成功までは
    保証しない——`sway_hub.plan_hub_wiring()`/
    `filter_wiring_by_resolvable_anchor()`が容量超過後もなお在庫やanchor
    解決の都合で`wiring.unassignable`へ理由付きで回すことがある(SPEC
    §3-1「同時に揺れるのは9グループまで」、既存の意図的フォールバック、
    die()しない)。これはdev#1508バグ(理由なき静かな欠落)とは別物であり、
    ゲートが誤ってFAILにしてはならない。`hub_wiring.unassignable`
    (step02が既に計算済みのwiring結果、ここでは**観測するだけ**——
    対象骨集合の導出自体には使わない、構造的独立性は保つ)に属する
    group_keyの骨は、`sway_gate_compute_source_bone_names()`の
    bone_group_keys対応から特定し、理由をログへ出したうえでゲート対象から
    除外する。

    fail-closed: 除外後もなお1本でもFAILがあれば`core.die()`で変換全体を
    止める(「問題のあるものはそもそもリリースできない仕組み」の実装、
    CLAUDE.md「受入試験はリリースゲートに任せる」の例外——本ゲートは
    そのリリースゲート自体が信頼する土台の一部)。

    `lab_assignments`(dev#1508 graceful-degrade、night_20260817 laneI):
    呼び出し側(`main()`)の縮退ループが最終的に確定した除外集合
    ({unit.key -> LabAssignment(enabled=False)})をそのまま渡す。
    本関数は`sway_gate_compute_source_bone_names()`を通じて独立に
    対象骨集合を再導出する設計のため、`hub_wiring`(既に縮退済みの
    最終wiring)と食い違わないよう、縮退ループが使ったのと**同じ**
    `lab_assignments`をここにも渡す必要がある(呼び出し側の責務、
    `main()`のコメント参照)。省略時(None)は従来どおり縮退なし。

    本関数自体はこの時点(remap後)で新たに鎖を除外する機構は持たない
    ——remap前(`place_hub_donor_chains()`直後)の縮退ループが位置/向き/
    スケール/支点公理/重み衝突予測の全てを事前に検査済みのため、ここへ
    到達した時点で残っているのは「縮退ループの想定を超えた未知の破綻」
    のみであり、fail-closedの最終防衛線として`core.die()`を維持する
    (laneI指示書「3. fail-closedの維持」——縮退はあくまで配線前段の話、
    最終防衛線そのものを弱めない)。"""
    prep = _sway_gate_prepare(
        job, gender, physbone_entries, springbone_entries, avatar_arm, pal_arm,
        meshes, group_targets, hub_wiring, dz, pal_map, source_parent_of,
        lab_assignments=lab_assignments)
    if prep is None:
        # An empty result must replace a previous run's dynamic state. Leaving
        # these files untouched makes G15 inspect stale donors after all chains
        # have been disabled (or after the source no longer contains sway).
        empty_reports = {
            "sway_source_donor_map": {},
            "sway_source_gate": {"ok": True, "checked": 0, "failed": [],
                                 "transform_warnings": []},
            "sway_pivot_axiom": {"ok": True, "checked": 0, "failed": []},
        }
        for stem, payload in empty_reports.items():
            with open(os.path.join(conv, f"{stem}_{gender.lower()}.json"),
                      "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        return
    real_source_bone_names = prep.real_source_bone_names
    source_transform_snapshot = prep.source_transform_snapshot
    source_weight_snapshot = prep.source_weight_snapshot
    donor_transform_snapshot = prep.donor_transform_snapshot
    donor_weight_snapshot = prep.donor_weight_snapshot
    anchor_parent_of = prep.anchor_parent_of
    axiom_baseline_pos = prep.axiom_baseline_pos
    axiom_observed_pos = prep.axiom_observed_pos

    report = sway_source_gate.run_gate(
        sorted(real_source_bone_names), group_targets,
        source_transform_snapshot, source_weight_snapshot,
        donor_transform_snapshot, donor_weight_snapshot,
        merge_groups=sway_hub.merged_weight_groups(hub_wiring),
        representative_of=sway_hub.representative_of_map(hub_wiring))

    # dev#1508 hubwire final(公理検査、2026-08-16オーナー制定「揺れものの
    # 支点は、その親humanoidボーンに対して相対位置が一切変わらない」):
    # baseline(step01相当、avatar_arm live snapshot)とobserved(step02、
    # pal_arm donor配置後)の両方で、支点の対親相対ベクトルを比較する。
    # axiom_baseline_pos/axiom_observed_posは`_sway_gate_prepare()`が
    # 既に算出済み(親の回転を使わない設計判断の経緯は
    # `sway_pivot_axiom.relative_vector()`のdocstring参照)。
    axiom_report = sway_pivot_axiom.run_pivot_axiom_gate(
        anchor_parent_of, axiom_baseline_pos, {},
        axiom_observed_pos, {})

    axiom_report_path = os.path.join(
        conv, f"sway_pivot_axiom_{gender.lower()}.json")
    with open(axiom_report_path, "w", encoding="utf-8") as f:
        json.dump({
            "ok": axiom_report.ok,
            "checked": len(axiom_report.results),
            "failed": [
                {"pivot": r.pivot, "parent": r.parent, "distance": r.distance,
                 "reason": r.reason} for r in axiom_report.failed],
        }, f, ensure_ascii=False, indent=1)
    if axiom_report.results:
        print(f"[{TAG}] sway_pivot_axiom: {len(axiom_report.results)} pivot(s) "
              f"checked, {len(axiom_report.failed)} failed ({axiom_report_path})")

    # dev#1508 追加防衛線(オーナー裁定2026-08-16): 「ソース基準ゲートを
    # preflightにも最終防衛線として追加する」——preflight_pak.py
    # check_sway_source_gate_against_pak()(G15)が、この骨対応表と
    # vanilla/mod共有Skeletonカタログの実差分を突き合わせ、step02〜pak
    # 組み立ての間の破壊(パッチの取りこぼし等)を検出する。
    donor_map_path = os.path.join(conv, f"sway_source_donor_map_{gender.lower()}.json")
    with open(donor_map_path, "w", encoding="utf-8") as f:
        json.dump({b: group_targets[b] for b in sorted(real_source_bone_names)
                   if b in group_targets}, f, ensure_ascii=False)

    # dev#1551(断言ゲート警告格下げ、オーナー裁定確定、正本
    # work\run_1551\laneR7_earfix\RESULT.md): check_bone_transform()の
    # 不一致(位置/向き/スケール)はreport.okに寄与しない(sway_source_gate.py
    # のBoneCheckResult.transform_warnings、ok/failed判定からは分離済み)。
    # ここが「配線した上でWARNINGログに角度を残す」の実体——report.okの
    # 真偽に関わらず(=PASSでも)、鎖ごとの不一致を必ずWARNINGとして出す。
    transform_warning_lines = report.transform_warning_lines()

    report_path = os.path.join(conv, f"sway_source_gate_{gender.lower()}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "ok": report.ok,
            "checked": len(report.results),
            "failed": [
                {"bone": r.bone, "donor": r.donor, "reasons": r.reasons}
                for r in report.failed],
            "transform_warnings": [
                {"bone": r.bone, "donor": r.donor, "warnings": r.transform_warnings}
                for r in report.results if r.transform_warnings],
        }, f, ensure_ascii=False, indent=1)

    for line in transform_warning_lines:
        print(f"[{TAG}][WARN][sway-gate-transform] {line}")

    # dev#1508 hubwire final(公理検査): 既存のTransform/ウェイトゲートと
    # 公理検査を同じ扱いに統合する(片方だけ緑でも「PASS」とは呼ばない)。
    # dev#1592(2026-08-19 オーナー裁定): 従来はここでFAILが変換全体を
    # 停止させていた(fail-closed)。停止させるかどうかの判断は
    # `_finalize_sway_source_gate_result()`(bpy非依存の純粋関数、単体
    # テスト対象)へ抽出済み——現在はFATAL停止せずWARNING継続する。
    _finalize_sway_source_gate_result(report, axiom_report, report_path, axiom_report_path)


# =====================================================================
# dev#1508 graceful-degrade(揺れ鎖の明示的縮退、night_20260817 laneI)
# =====================================================================

_SWAY_DEGRADE_MAX_RETRIES = 2  # laneI指示書「1. 縮退機構」: 最大2回


def _sway_degrade_precheck(job, gender, physbone_entries, springbone_entries,
                            avatar_arm, pal_arm, base_group_targets, wiring,
                            dz, pal_map, source_parent_of, lab_assignments):
    """`place_hub_donor_chains()`直後・remap実行前に呼べる範囲だけで
    (weight値そのものの比較を除く)受入ゲート相当の検査を行う
    (dev#1508 graceful-degrade、night_20260817 laneI「3. fail-closedの
    維持」)。

    remapがまだ実行されていない(=avatar骨名つき頂点グループがまだ
    メッシュ上に残っている)ため、`sway_source_gate.check_bone_weights()`
    (donor骨の実際のメッシュ頂点ウェイト値)は検査できない。代わりに
    `sway_degrade.detect_weight_collisions()`で「remapを実行したら
    ウェイト値検査が構造的にFAILする」ケース(複数鎖が同じdonorへ
    ウェイトを奪い合う)を事前予測する——remapは`tmp.add(...,"ADD")`で
    単純合算するだけなので、衝突が無ければ値一致は幾何学的に保証される
    (`sway_source_gate.py`モジュールdocstring「頂点ウェイトは単純な
    コピー」参照)。位置/向き/スケール(`check_bone_transform`)+支点公理
    (`sway_pivot_axiom`)はremap前でも検査可能(donor骨の配置だけで
    判定でき、メッシュ頂点ウェイトを必要としない)。

    戻り値: (prep または None(対象0件no-op), failed_bone_reasons:
    {bone名 -> [reason文字列, ...]}, attempt_group_targets)。"""
    attempt_group_targets = dict(base_group_targets)
    attempt_group_targets.update(sway_hub_wire.source_to_donor_bone_map(wiring, gender))

    prep = _sway_gate_prepare(
        job, gender, physbone_entries, springbone_entries, avatar_arm, pal_arm,
        [], attempt_group_targets, wiring, dz, pal_map, source_parent_of,
        lab_assignments=lab_assignments, quiet=True)
    if prep is None:
        return None, {}, attempt_group_targets

    failed_bone_reasons: Dict[str, List[str]] = {}

    # dev#1551(chain-length-fit WP): 節数フィット(先端マージ)発動時、
    # donorのジオメトリは常に「マージグループの代表(先端側)骨」の
    # transformで配置される(sway_hub.fit_chain_to_length()「マージ後の
    # 代表点はマージ区間の端点を保つ」設計)。代表**でない**(マージされて
    # 消えた側の)骨を自分自身の生transformとdonorとで比較すると構造的に
    # 不一致になる——バグではなく設計どおりの結果なので、この骨について
    # 位置/向き/スケール検査をスキップする(donor欠落自体の検査は従来
    # どおり行う。sway_source_gate.run_gate()のrepresentative_of引数と
    # 同じ考え方)。
    representative_of = sway_hub.representative_of_map(wiring)
    for bone in sorted(prep.real_source_bone_names):
        donor = attempt_group_targets.get(bone)
        src = prep.source_transform_snapshot.get(bone)
        dst = prep.donor_transform_snapshot.get(donor) if donor else None
        if donor is None:
            failed_bone_reasons.setdefault(bone, []).append(
                "no donor mapping for this source bone")
            continue
        if src is None or dst is None:
            failed_bone_reasons.setdefault(bone, []).append(
                f"donor bone {donor!r} transform not found in pal_arm")
            continue
        if representative_of.get(bone, bone) != bone:
            continue  # 非代表のマージ済み骨: 個別transform比較は対象外
        # dev#1551(断言ゲート警告格下げ、オーナー裁定確定、正本
        # work\run_1551\laneR7_earfix\RESULT.md): check_bone_transform()の
        # 微小な不一致(位置/向き/スケール、float精度級・chain-length-fit
        # 由来の正当な残差を含む)はもう鎖除外の理由にしない(「静かに
        # 捨てて成功」の廃止)——ここでは`check_bone_transform()`自体は
        # 呼ばない(結果を捨てるだけの無意味な計算になるため)。最終防衛線
        # `run_sway_source_gate()`(非quiet、remap後に必ず1回だけ走る)側で
        # 全件まとめてWARNINGを出す。donor欠落(上のno donor mapping/
        # transform not found)・ウェイト衝突・支点公理違反は従来どおり
        # failed_bone_reasons(=degrade loopの除外トリガー)に積んだまま
        # (fail-closed維持)。
        #
        # dev#1625(2026-08-21 オーナー裁定「使命は自分のアバターで遊べる
        # こと、一部機能がそれを邪魔するならその停止はOK」)追加分: 上記の
        # 「格下げ」は微小な残差の話であり、donor骨が明後日の方向を向いた
        # ままの構造的破綻(実機報告、AvatarSample_A.vrmで最大120.98度)は
        # 別問題——ゲート自体(report.ok)は変えず、「壊れた配線を作らない」
        # ため縮退機構(このハブだけ切除)の判定材料としてだけ使う
        # (sway_source_gate.SWAY_POSTURE_CULL_THRESHOLD_DEG、較正データは
        # 同モジュールのコメント参照)。位置/スケールは対象外(REPORT.md/
        # 実機報告の症状=頭部・胸部の破綻は方向不一致に直結、位置/スケール
        # まで対象にすると較正済みでない誤爆の余地が増えるため、今回の
        # 最小切除の対象は方向のみに絞る)。
        angle = sway_source_gate.direction_mismatch_deg(
            src["pos"], src["tail"], dst["pos"], dst["tail"])
        if angle is not None and angle > sway_source_gate.SWAY_POSTURE_CULL_THRESHOLD_DEG:
            failed_bone_reasons.setdefault(bone, []).append(
                f"{SWAY_POSTURE_MISMATCH_CULL_TAG}: donor {donor!r} direction "
                f"differs by {angle:.2f} deg (exceeds cull threshold "
                f"{sway_source_gate.SWAY_POSTURE_CULL_THRESHOLD_DEG} deg)")

    donor_of = {b: attempt_group_targets.get(b) for b in prep.real_source_bone_names}
    weighted_bones = {b for b in prep.real_source_bone_names
                       if prep.source_weight_snapshot.get(b)}
    # dev#1551(chain-length-fit WP): 節数フィット(先端マージ)が意図的に
    # 作った「複数の元ボーン->同じdonor」写像は、ウェイト衝突バグではなく
    # 本WPの正規機構(ADD合算=仕様)なので除外する(sway_degrade.
    # detect_weight_collisions()docstring参照)。
    expected_merge_groups = sway_hub.merged_weight_groups(wiring)
    for donor, bones in sway_degrade.detect_weight_collisions(
            donor_of, weighted_bones, expected_merge_groups).items():
        for b in bones:
            failed_bone_reasons.setdefault(b, []).append(
                f"weight collision on donor {donor!r} with: "
                f"{[x for x in bones if x != b]}")

    axiom_report = sway_pivot_axiom.run_pivot_axiom_gate(
        prep.anchor_parent_of, prep.axiom_baseline_pos, {},
        prep.axiom_observed_pos, {})
    for r in axiom_report.failed:
        # dev#29診断ログ英語固定: `r.reason`(sway_pivot_axiom.py本体、
        # 本レーンの対象外)には既存の日本語混じり文言が含まれるため、
        # ここでは組み込まず本レーン側の英語だけの要約を使う。
        failed_bone_reasons.setdefault(r.pivot, []).append(
            f"pivot axiom violation: relative position to parent "
            f"{r.parent!r} moved {r.distance:.6f} (tolerance exceeded)")

    return prep, failed_bone_reasons, attempt_group_targets


def run_sway_degrade_loop(job, gender, physbone_entries, springbone_entries,
                           avatar_arm, pal_arm, group_targets, anchor_pal_map, dz,
                           vanilla, pal_map, source_parent_of,
                           initial_wiring, initial_node_overrides,
                           initial_diagnostics_lines, initial_refskel_dict,
                           initial_lab_overrides=None):
    """dev#1508 graceful-degrade(揺れ鎖の明示的縮退)の司令塔
    (laneI指示書「1. 縮退機構」)。

    `initial_*`: main()が`wire_sway_hub_auto()`を(除外なしで)既に1回
    呼んだ結果(attempt0)。pal_arm自体は既にこのattempt0のhub_refskel_dict
    (キー集合)を使って構築済みのため、再構築はしない——リトライは常に
    attempt0の「部分集合」のunitだけを使うので、pal_armに含まれる骨の
    集合が不足することは無い(除外されたunitのdonor骨はpal_arm内に
    残り続けるが、配置されず・group_targetsに現れず・weightも付かない
    無害な未使用骨のままになる、既存の`hub_wiring.unassignable`と同じ
    フォールバック形)。

    **dev#1551 Lane V修正(VRM step02 KeyError根治)**: 上記の「リトライは
    常にattempt0の部分集合」という前提は、この関数のリトライ実装
    (以前は`wire_sway_hub_auto()`を`lab_assignments`を変えて**再実行**して
    いた)では実際には保証されていなかった——`sway_hub.plan_hub_wiring()`の
    donor骨割当は自由donorプールを`plan.accepted`の出現順に貪欲消費する
    グローバルな計画であり、グループを1つ除外して再計画すると、残る
    グループへの消費開始位置がずれて**前回と異なるdonor骨**が割り当たり
    うる(実例: VRM入力test\\vrm\\Seed-san.vrmで、女性用donor骨
    `F_Bronze001_bag_01`がリトライ時に新規出現し、attempt0のpal_armに
    存在しないため`place_hub_donor_chains()`が`KeyError`でクラッシュした)。
    本関数は以後、リトライのたびに`wire_sway_hub_auto()`を再実行するの
    ではなく`sway_hub.filter_wiring_excluding_units()`で`initial_wiring`
    (attempt0)から除外対象unitのgroup_plansエントリを**削るだけ**にする
    (`_retry_wiring_from_initial()`ローカル関数)——donor骨割当・座標は
    一切再計算しないため、上記の「部分集合」不変条件が構造的に保証
    される。

    `initial_lab_overrides`(dev#1572第3便、issue #1572「チェインの揺れ設定
    問題1・2」): `main()`が`_lab_assignments_from_job()`で組み立てた、
    job["sway_chain_overrides"]由来の**全ユニットぶん**の明示的
    LabAssignment辞書(attempt0=`initial_wiring`を作った呼び出しと同じ値)。
    ここで`lab_overrides`の初期値として引き継ぐことで、`_sway_gate_
    prepare()`(下記while内、独立再導出)が最初のattemptから job の
    enabled上書きを正しく反映する——渡さなければ(既定None)従来どおり
    空dictから始まる(既存呼び出し元・既存単体テストへの完全無退行)。

    このdictはenabled=True(force-ON)のエントリも含みうる点が、旧来
    「`lab_overrides`=除外集合」という前提と異なる——`_retry_wiring_
    from_initial()`の`excluded_keys`計算と、下のunassignable記録の
    重複チェックの両方を`.enabled is False`のエントリだけに限定する形へ
    直してある(この2箇所以外は`existing=lab_overrides`で辞書をそのまま
    引き継ぐだけなので無改修で正しく動く)。

    戻り値: (final_wiring, final_node_overrides, final_diagnostics_lines,
    final_refskel_dict, hub_donor_quats, lab_overrides, exclusion_entries,
    fully_disabled)。`lab_overrides`は`run_sway_source_gate()`へ
    そのまま渡すべき最終除外集合(post-remap最終防衛線も同じ集合で
    対象骨を絞るため)。"""
    initial_plan = sway_allocator.allocate(
        physbones_json={"physbones": list(physbone_entries or [])},
        springbones_json={"springbones": list(springbone_entries or [])},
        lab_assignments=initial_lab_overrides)
    # The armature and donor wiring were built from attempt 0. Re-allocating
    # after a cull must not fill the vacant slot with a previously rejected
    # unit: no donor was built for that unit. Freeze the rejected set before
    # either precheck or the final source gate independently allocates again.
    # Existing force-ON/style overrides for accepted units remain unchanged.
    lab_overrides: Dict[str, sway_allocator.LabAssignment] = sway_degrade.build_lab_overrides(
        (u.key for u in initial_plan.rejected_units), existing=initial_lab_overrides)
    exclusion_entries: List[sway_degrade.ExclusionEntry] = \
        sway_degrade.exclusion_entries_for_capacity_overflow(initial_plan)
    wiring = initial_wiring
    node_overrides = initial_node_overrides
    diagnostics_lines = initial_diagnostics_lines
    refskel_dict = initial_refskel_dict
    fully_disabled = False
    attempt = 0

    def _retry_wiring_from_initial(current_lab_overrides):
        """dev#1551: `initial_wiring`(attempt0)を`current_lab_overrides`で
        除外されたunitぶんだけ部分集合フィルタし、node_overrides/
        diagnostics_lines/refskel_dictを**再計算**する(donor骨割当・
        座標はattempt0からそのまま引き継ぐ、`filter_wiring_excluding_units()`
        docstring参照)。診断ログ用の`plan`(採用/非採用の全unit一覧)だけは
        `current_lab_overrides`を反映して再計算が必要(bpy非依存・軽量、
        donor骨プールには触れない)。

        dev#1572第3便: `current_lab_overrides`は(job由来の)enabled=True
        エントリを含みうる(モジュール外のrun_sway_degrade_loop()
        docstring「initial_lab_overrides」参照)。除外対象はあくまで
        `enabled=False`のエントリだけ——force-ONのエントリのキーを
        誤って除外に含めると、既にattempt0で正しく配線済みの鎖を
        リトライのたびに剥がしてしまう(initial_wiringは`filter_wiring_
        excluding_units()`で部分集合を取るだけの一方向操作のため、
        一度剥がすと復元できない)。"""
        excluded_keys = frozenset(
            k for k, la in current_lab_overrides.items() if not la.enabled)
        retry_wiring = sway_hub.filter_wiring_excluding_units(
            initial_wiring, excluded_keys)
        retry_plan = sway_allocator.allocate(
            physbones_json={"physbones": list(physbone_entries or [])},
            springbones_json={"springbones": list(springbone_entries or [])},
            lab_assignments=current_lab_overrides)
        retry_node_overrides = sway_hub.node_overrides_from_wiring_plan(retry_wiring)
        retry_diagnostics_lines = sway_hub.build_diagnostics_lines(
            retry_plan, retry_wiring, gender)
        # dev#1551 integ14: 縮退リトライでもハブroot親を実アンカーにする
        # (wire_sway_hub_auto()側と同じ修正、anchor_pal_mapは
        # run_sway_degrade_loop()の引数として既に凍結済みの安全な辞書)。
        retry_refskel_dict = sway_hub.refskel_dict_for_wiring(
            retry_wiring, gender, anchor_pal_of=anchor_pal_map)
        return retry_wiring, retry_node_overrides, retry_diagnostics_lines, retry_refskel_dict

    while True:
        hub_donor_quats = place_hub_donor_chains(
            pal_arm, avatar_arm, wiring, gender, anchor_pal_map, dz)

        prep, failed_bone_reasons, attempt_group_targets = _sway_degrade_precheck(
            job, gender, physbone_entries, springbone_entries, avatar_arm, pal_arm,
            group_targets, wiring, dz, pal_map, source_parent_of, lab_overrides)

        # dev#1508 graceful-degrade「1. 割当・配線段階で成立しない鎖」:
        # 容量9・donor在庫枯渇・anchorのPAL側retarget未解決という既存の
        # 正常フォールバック(`wiring.unassignable`)は、このattemptで
        # 確定した時点で常に記録する(FAILの有無に関わらず——「新たに
        # 判明した除外」であり、次のattemptで同じgroupが繰り返し出ても
        # 上書きにしかならないので二重記載の実害はない)。
        for group, why in wiring.unassignable:
            for unit in group.units:
                # dev#1572第3便: lab_overridesはjob由来のenabled=True
                # エントリも含みうるため、「既に記録済み」の判定は
                # enabled=Falseのエントリに限定する(force-ONのユニットは
                # ここで初めてunassignable理由を記録する必要がある)。
                existing_la = lab_overrides.get(unit.key)
                if existing_la is not None and not existing_la.enabled:
                    continue  # 既に別段階で除外記録済み(重複記録を避ける)
                exclusion_entries.append(sway_degrade.make_exclusion_entry(
                    unit.key, sway_degrade.STAGE_ALLOCATION_UNASSIGNABLE, why))

        if prep is None or not failed_bone_reasons:
            # 成功(または対象0件のno-op)。このattemptを最終解とする。
            #
            # dev#1625(2026-08-21、AvatarSample_A.vrm実データ検証で発覚):
            # `prep is None`(=`sway_gate_compute_source_bone_names()`が
            # 現在のlab_overridesの下で0本の揺れ源しか残っていないと判定)
            # には構造的に異なる2ケースがある——
            #   (a) そもそも揺れ源input自体が無い(non-swayジョブ等)。
            #       この場合`exclusion_entries`はまだ空。
            #   (b) 前段のattempt(群)で個別unitを切除し続けた結果、
            #       最後の1本まで除外し尽くして「残り0本」に到達した。
            #       この場合`exclusion_entries`は非空。
            # (b)は実質的に「sway全OFFへ縮退した」のと同じ状態(出荷される
            # 揺れ鎖が0本)だが、従来の分岐(unattributed/リトライ上限到達)
            # を経由しないため`fully_disabled`が立たないまま「成功」として
            # breakしていた——`preflight_pak.py::_sway_degrade_explains_
            # zero_chains()`は`fully_disabled=True`でなければ「0鎖」を
            # 正当な縮退と認めない(dev#1508 laneI設計)ため、この抜け道は
            # G3b/G15をFAILさせる(=変換が完走しない、dev#1625裁定
            # 「変換自体はいつも通り完走」に反する)。exclusion_entriesの
            # 非空判定で(a)と(b)を区別し、(b)相当ならfully_disabledを立てる。
            if prep is None and exclusion_entries:
                fully_disabled = True
            break

        bone_unit_keys_map = sway_source_bones.bone_unit_keys(prep.plan)
        attributable, unattributed = sway_degrade.attribute_bones_to_units(
            failed_bone_reasons.keys(), bone_unit_keys_map)

        if unattributed or attempt >= _SWAY_DEGRADE_MAX_RETRIES:
            # 帰属できない、またはリトライ上限到達 -> sway全OFF縮退
            # (laneI指示書「3. fail-closedの維持」)。
            fully_disabled = True
            reason_bits = []
            if unattributed:
                reason_bits.append(
                    f"{len(unattributed)} bone(s) FAILED but could not be "
                    f"attributed to a specific chain: {sorted(unattributed)}")
            if attempt >= _SWAY_DEGRADE_MAX_RETRIES:
                reason_bits.append(
                    f"retry budget exhausted ({_SWAY_DEGRADE_MAX_RETRIES} retries)")
            systemic_reason = "; ".join(reason_bits) or "unattributed gate failure"
            all_keys = sway_degrade.all_unit_keys(initial_plan)
            still_active_keys = {key for key in all_keys
                                 if key not in lab_overrides or lab_overrides[key].enabled}
            for key in sorted(still_active_keys):
                exclusion_entries.append(sway_degrade.make_exclusion_entry(
                    key, sway_degrade.STAGE_SYSTEMIC_DISABLE, systemic_reason))
            lab_overrides = sway_degrade.build_lab_overrides(
                all_keys, existing=lab_overrides)
            wiring, node_overrides, diagnostics_lines, refskel_dict = \
                _retry_wiring_from_initial(lab_overrides)
            hub_donor_quats = place_hub_donor_chains(
                pal_arm, avatar_arm, wiring, gender, anchor_pal_map, dz)
            break

        # 特定の鎖(unit)へ帰属できた -> その鎖だけ除外してリトライ。
        reasons_by_unit: Dict[str, List[str]] = {}
        for bone, reasons in failed_bone_reasons.items():
            for uk in bone_unit_keys_map.get(bone, ()):
                if uk in attributable:
                    reasons_by_unit.setdefault(uk, []).extend(
                        f"{bone}: {r}" for r in reasons)
        for key in sorted(attributable):
            joined = "; ".join(reasons_by_unit.get(key, ["gate check failed"]))
            stage = (sway_degrade.STAGE_GATE_AXIOM if "pivot axiom" in joined
                     else sway_degrade.STAGE_GATE_WEIGHT_COLLISION if "weight collision" in joined
                     else sway_degrade.STAGE_GATE_TRANSFORM)
            exclusion_entries.append(sway_degrade.make_exclusion_entry(key, stage, joined))
        lab_overrides = sway_degrade.build_lab_overrides(attributable, existing=lab_overrides)
        attempt += 1
        wiring, node_overrides, diagnostics_lines, refskel_dict = \
            _retry_wiring_from_initial(lab_overrides)
        # 次のループ先頭でplace_hub_donor_chains()を呼び直す。

    print(f"[{TAG}] sway degrade: settled after {attempt + 1} attempt(s), "
          f"{len(exclusion_entries)} unit(s) excluded total, "
          f"fully_disabled={fully_disabled}")
    return (wiring, node_overrides, diagnostics_lines, refskel_dict, hub_donor_quats,
            lab_overrides, exclusion_entries, fully_disabled)


def _sway_exclusions_merge_write(conv, gender, report):
    """dev#1508 graceful-degrade(night_20260817 laneI)「2. 可視化」:
    ユーザー向け単一ファイル`converted\\sway_exclusions.json`(Male/Female
    両性別をマージしたビュー)へ書き出す。

    Male/Female のstep02プロセスはconvert.ps1からStart-Jobで並列実行
    される(CLAUDE.md「排他リソースと並列実行の可否」表参照)ため、
    単純な上書きは競合しうる。ロックファイル(`.lock`、
    `O_CREAT|O_EXCL`)で短時間の排他を取り、取れなければ数回リトライ
    してから諦めて非ロックで上書きする(best-effort)。

    **preflight側のfail-closed判定はこのファイルに依存させない**
    (`sway_exclusions_{gender}.json`、性別ごとにstep02プロセスが単独で
    書く競合の無いファイルが正本。こちらはユーザー向けログ閲覧の利便性
    のためだけの副産物であり、まれに競合で片方の性別分が欠けても
    fail-closedの安全性には影響しない)。"""
    path = os.path.join(conv, "sway_exclusions.json")
    lock_path = path + ".lock"
    got_lock = False
    for _ in range(10):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            got_lock = True
            break
        except FileExistsError:
            time.sleep(0.3)
    try:
        merged = {"format": sway_degrade.FORMAT, "genders": {}}
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    existing = json.load(f)
                if isinstance(existing, dict) and isinstance(existing.get("genders"), dict):
                    merged["genders"] = existing["genders"]
            except (OSError, json.JSONDecodeError):
                pass
        merged["genders"][gender.lower()] = report.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=1)
    finally:
        if got_lock:
            try:
                os.remove(lock_path)
            except OSError:
                pass


def auto_assign_sway_chains(job, gender, source_parent_of, donor_bone_pairs):
    """dev#1508 W2a-2c(汎用ハブ配線への完全置換、旧W2a実装からの縮小):
    **手動指定(job["sway_manual"])専用**の骨配線。旧実装はここでPB/SB自動
    割当(アロケータ駆動の候補判定→sway_assign.pyのfamily限定donor経路)も
    行っていたが、SPEC.md §1の自動割当は`wire_sway_hub_auto()`
    (`sway_hub_wire.py`のハブ経路)へ完全に置き換わった——本関数は
    `sway_allocator_wire.wire_and_diagnose()`をphysbone_entries/
    springbone_entriesとも空で呼ぶことで、PB/SB候補は一切通さず
    `manual_chains`(job["sway_manual"])だけをsway_assign.pyの既存donor
    動的発見エンジン(region分類+節数優先、無改変)へ渡す。

    手動指定がSPEC.md §1の対象外である理由: SPEC.md §1「標準機能『ゆらす』」の
    自動割当(候補・無偏向・量子化・グループ化・容量9・ハブ配線)は
    PB/SB付き鎖専用の仕組みであり、job["sway_manual"](任意骨の手動チェーン
    指定、揺れもの以前からの既存機能)はそもそもPB/SBの候補概念を経由
    しない——ハブ方式へ移行する動機(donor在庫の一般化・KP物理サブツリー
    化)は手動指定には無関係なため、旧来のfamily限定donor経路のまま存続
    させる(次のWPへの引き継ぎ事項ではない、意図的な設計判断)。

    job["sway_manual"]が空、またはdonor_bone_pairsが空なら空リスト2つ
    ((job_fragments, node_overrides)ともに空)+no-opレポート(=完全no-op)。

    戻り値: (job_fragments, node_overrides, diagnostics_lines, report)。
    - job_fragments: resolve_sway_chain_entries()が消費する形。
    - node_overrides: 手動指定はKPノードのstyle/limit_angleを持たないため
      常に空dict(sway_allocator_wire.compute_node_overrides()のchain_lookup
      が空になり、全Assignmentが素通りするため——このWPで意図的に変えた
      挙動ではなく、手動指定は元々SwayGroupを経由しないため必然的にこう
      なる、後方互換)。
    - diagnostics_lines: 1行1JSON文字列のリスト。
    - report: sway_assign.build_sway_lost_report()の出力。
    """
    manual_chains = list(job.get("sway_manual") or [])
    if not manual_chains or not donor_bone_pairs:
        return [], {}, [], {"declared_chains": 0, "assigned_chains": 0, "lost_chains": 0, "lost": []}

    chibi_candidates = (
        list(CHIBI_CANDIDATES) + list(SPINE_CHAIN) + list(CHIBI_TWIST_BONES.keys()))
    job_fragments, node_overrides, diagnostics_lines, report = sway_allocator_wire.wire_and_diagnose(
        physbone_entries=[],
        springbone_entries=[],
        manual_chains=manual_chains,
        donor_bone_pairs=donor_bone_pairs,
        source_parent_of=source_parent_of,
        gender=gender,
        chibi_candidates=chibi_candidates,
        symbols={"sway_cloth_bone_targets": sway_cloth_bone_targets,
                 "SWAY_CLOTH_ANCHOR": SWAY_CLOTH_ANCHOR,
                 # dev#19 native-donor-rule WP(issue #19): sway_assign.py側の
                 # assign_sway_chains()がnative_sim_count(実シミュレーション
                 # 対象骨数)をfamily_prefix経由で引けるようにする。この
                 # キーを欠くとnative規則が無条件でqualifies()=False扱いに
                 # なり、native規則が機能しない(自身のモジュール内呼び出し
                 # なので実行中のSWAY_DONOR_FAMILIESをそのまま渡せる、
                 # _load_step02_symbols()の読み取り専用exec抽出は不要)。
                 "SWAY_DONOR_FAMILIES": SWAY_DONOR_FAMILIES},
        registered_families=list(SWAY_DONOR_FAMILIES),
    )
    return job_fragments, node_overrides, diagnostics_lines, report


def main():
    job, rest = vp_bl.load_job_from_argv()
    gender = rest[0] if rest else "Male"
    if gender not in ("Male", "Female"):
        core.die(TAG, f"invalid gender: {gender}")
    conv = core.job_subdir(job, "converted")
    vanilla = os.path.join(job["job_dir"], "vanilla")

    # dev#1508 W1b(入口正規化): job["springbones"]はprefabのjob["physbones_json"]
    # と違い、job.json/job.resolved.json自体には載らない(VRMのSpringBone解析は
    # step01(Blenderプロセス)内でしか行えず、step01/step02は別プロセスで同じ
    # $Jobファイルを個別に再読込するため)。step01がconverted\springbones.json
    # サイドカー(常に書く、無ければ空リスト)へ書き出したものを、ここ(入口)で
    # job["springbones"]へ差し戻す——以降の全消費箇所(wire_sway_hub_auto/
    # auto_assign_sway_chains)は既存のprefab経路(job["springbones"]直下、
    # フラットlist)と一字一句同じ扱いで読める(work\night_20260817\laneE\
    # SMOKE.mdが確定させた欠落の修理)。job["springbones"]が既に非空
    # (将来job.json側に直接載るケースが増えても)ならサイドカーより優先する。
    if not job.get("springbones"):
        springbones_sidecar_path = os.path.join(conv, "springbones.json")
        if os.path.isfile(springbones_sidecar_path):
            with open(springbones_sidecar_path, encoding="utf-8") as f:
                job["springbones"] = json.load(f).get("springbones", [])

    blend = os.path.join(conv, "step01_clean.blend")
    if not os.path.exists(blend):
        core.die(TAG, f"step01 produced no output: {blend}")
    bpy.ops.wm.open_mainfile(filepath=blend)

    with open(os.path.join(conv, "avatar_meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    pal_map = meta["pal_map"]
    # 非スキンメッシュ(帽子・リボン等)の元の親ボーン名(step01が記録)。
    # {geo_XX: 実ボーン名}。zero-weight rescueの束縛先解決に使う
    unskinned_source_bone = meta.get("unskinned_source_bone", {})

    avatar_arm = bpy.data.objects.get(meta["armature"])
    if avatar_arm is None:
        avatar_arm = next((o for o in bpy.data.objects
                           if o.type == "ARMATURE"), None)
    if avatar_arm is None:
        core.die(TAG, "avatar Armature not found")
    meshes = [bpy.data.objects[n] for n in meta["meshes"]
              if n in bpy.data.objects]
    if not meshes:
        core.die(TAG, "avatar mesh not found")

    # 構造サマリ用: rebind()でobj.parentがpal_armへ差し替わる前の、元ファイル
    # 由来のparent_type/parent_boneを記録しておく(rebind()のコメント参照)。
    # remap_vertex_groups等の以降の処理はparent_type/parent_boneを変更しない
    # ため、ここで捕捉すれば rebind() 直前まで有効。
    orig_parent_info = {
        obj.name: {"parent_type": obj.parent_type, "parent_bone": obj.parent_bone}
        for obj in meshes
    }

    # dev#1508 W2a-2c: attach_orphan_roots()/build_group_targets()は
    # pal_armに依存しない(avatar_arm+pal_mapのみ)ため、pal_arm構築より前
    # ここへ引き上げた——`wire_sway_hub_auto()`(下記sway_enable節)が
    # ハブ配線グループのanchor解決(`group_targets`)を必要とするため。
    # 元の位置(pal_arm構築直後)ではこの情報がまだ無かった。呼び出しの
    # タイミング自体は従来と同じ(pal_arm構築より前に一度だけ実行)であり、
    # 既存の非sway経路への影響はない。
    attach_orphan_roots(avatar_arm, pal_map)
    group_targets = build_group_targets(
        avatar_arm, pal_map, job.get("merge_fingers", False))
    # dev#1508(実データ検証2026-08-16で発見、anchorオフバイワン修正の副作用):
    # `group_targets`は後段で2つの別目的に使われる—— (a)
    # `remap_vertex_groups()`のメッシュ頂点ウェイト転写先(sway hub donor
    # 上書き込み、`group_targets.update(sway_hub_wire.
    # source_to_donor_bone_map())`が後で行う) と (b) ハブ自身の配置先
    # (`place_hub_donor_chains()`/`plan_reparent_steps()`の`anchor_pal =
    # group_targets.get(gp.group.anchor)`、「親骨と同位置」というSPEC
    # §5裁定の実装)。anchorオフバイワン修正でsource_to_donor_bone_map()が
    # anchor自身のキーも返すようになったため、(a)の`.update()`が
    # `group_targets[anchor]`を「anchorの標準retarget先(生成骨格の
    # 通常ボーン)」から「anchor自身のdonor骨」へ**上書きしてしまい**、
    # (b)のハブ配置が「ハブの新親=anchorのdonor骨」「anchorのdonorの新親=
    # ハブ」という循環参照になり、共有Skeletonのトポロジ制約
    # (`new_parent_idx<target_idx`)違反で変換全体が停止する実データ実測
    # バグ(flatHaori Phase 3.7)。(b)は`.update()`より**前**の値(標準
    # retarget先、sway wiringに一切左右されない)を使うべきなので、
    # `.update()`で書き換わる前にここで凍結コピーしておく。
    anchor_pal_map = dict(group_targets)

    with open(os.path.join(vanilla, "common_bones.json"), encoding="utf-8") as f:
        common = json.load(f)["common"]

    # 揺れもの: dev#19系列(docs\sway_design.md起点)。dev#1375(dev#19 R3統合)で
    # 単一チェーン限定(旧job["sway_cloth_bones"])から同時Nチェーン
    # (job["sway_chains"]、+job["sway_enable"]自動割当)へ一般化した。
    # job["sway_cloth_bones"]のみ指定・job["sway_chains"]/job["sway_enable"]が
    # 両方とも未指定の場合は_normalize_sway_chain_configs()が1エントリへ
    # ラップするだけで resolve_sway_donor() 相当のロジック
    # (_resolve_family_by_name())をそのまま経由する後方互換パス。
    # 3キーとも未指定なら sway_entries=[] となり、下のactive_entries分岐が
    # 旧コードと一字一句同じ処理(refskel_{gender}.jsonのみ、build_bones=common)
    # を実行する=既定出力完全不変(Layers-Affected: L1はsway有効時のみ)。
    #
    # dev#1375 item2「結線」本体: job["sway_enable"]が真のとき、
    # pipeline\py\sway_assign.py の自動割当エンジンへ、job["physbones_json"]
    # (prefab側PhysBoneサイドカー)・job["springbones"](VRM側)・
    # job["sway_manual"](手動指定)を渡し、donor在庫
    # (dev#19根治WP(issue#19)でsk_palhuman_bones.json静的スナップショット
    # 依存を廃止し、このjobが実抽出したrefskel_*.jsonから直接組み立てる形へ
    # 変更。discoveryとresolve/buildを同一ソースへ統合することで幽霊骨欠陥
    # クラス(m2defects)を構造的に無くす。build_donor_bone_pairs_from_vanilla()
    # docstring参照)へ割り当てさせる。
    auto_entries = []
    hub_wiring = sway_hub.HubWiringPlan(group_plans=(), unassignable=())
    hub_refskel_dict = {}
    hub_node_overrides = {}
    hub_diagnostics_lines = []
    # dev#1508 graceful-degrade(night_20260817 laneI): sway_enable=偽の
    # ときも`run_sway_degrade_loop()`を(既存のplace_hub_donor_chains()と
    # 同じく)無条件に呼ぶため、その引数として使う変数はここで安全な
    # 既定値を用意しておく(sway_enable=偽ならwire_sway_hub_auto()自身が
    # 即座に空を返すため、これらの値は実質使われない)。
    physbone_entries = []
    source_parent_of = {}
    manual_node_overrides = {}
    if job.get("sway_enable"):
        donor_bone_pairs = build_donor_bone_pairs_from_vanilla(vanilla, gender)
        if not donor_bone_pairs:
            print(f"[{TAG}] sway_enable: no donor bone inventory found under {vanilla} "
                  "(base refskel not extracted yet) -- "
                  "manual assignment skipped, no manual chains added")
        physbone_entries = []
        physbones_path = job.get("physbones_json")
        if physbones_path and os.path.isfile(physbones_path):
            with open(physbones_path, encoding="utf-8") as f:
                physbone_entries = json.load(f).get("physbones", [])
        source_parent_of = {
            b.name: (b.parent.name if b.parent else None)
            for b in avatar_arm.data.bones
        }
        # dev#1572(積み荷A、issue #1572追記3、2026-08-18オーナー最終裁定
        # 「無weightボーンには僕は興味がなく、ないものと扱ってます」):
        # sway鎖の分配・マージ・donor割当の母集団からウェイトを持たない
        # 骨を1回だけここで取り除く(鎖抽出〜フィット入力の唯一の集約点、
        # `sway_hub_wire.filter_entries_by_weighted_bones()`docstring
        # 参照)。`physbone_entries`(このあとwire_sway_hub_auto()へ渡す
        # ローカル変数)と`job["springbones"]`(wire_sway_hub_auto()内部が
        # `job.get("springbones")`で読む値、`run_sway_degrade_loop()`等の
        # 下流も同じjob辞書から都度読むため、ここで書き換えれば全消費者へ
        # 一貫して伝わる)の両方をこの時点で書き換える——
        # `sway_gate_compute_source_bone_names()`(独立再導出、gate用)も
        # 同じ`physbone_entries`/`job.get("springbones")`ローカル変数を
        # 受け取る呼び出し元(後述`run_sway_degrade_loop()`/
        # `run_sway_source_gate()`呼び出し)なので、二重実装なしに両経路が
        # 同じフィルタ済み値を見る。
        weighted_bone_names = collect_weighted_avatar_bone_names(avatar_arm, meshes)
        physbone_entries = sway_hub_wire.filter_entries_by_weighted_bones(
            physbone_entries, weighted_bone_names)
        job["springbones"] = sway_hub_wire.filter_entries_by_weighted_bones(
            job.get("springbones") or [], weighted_bone_names)
        # dev#1508 W2a-2c: PB/SB自動割当は汎用ハブ配線(sway_hub_wire.py)へ
        # 完全置換。手動指定(job["sway_manual"])は引き続き旧family限定donor
        # 経路(auto_assign_sway_chains()、physbone_entries渡しは廃止済み——
        # 関数docstring参照)。
        # dev#1582(鎖キー正規化修理): weighted_bone_namesをそのまま渡し、
        # GUI由来の安全域override鎖キー(_end等の無ウェイト骨込み)を
        # physbone_entries/springbonesと同じ規約(weighted-only)へ揃える
        # (`wire_sway_hub_auto()`docstring参照)。
        # dev#1572第3便(issue #1572「チェインの揺れ設定問題1・2」):
        # job["sway_chain_overrides"]のenabledを全ユニットぶん明示的な
        # LabAssignment辞書へ変換し(`_lab_assignments_from_job()`
        # docstring参照)、attempt0(この呼び出し)と縮退ループ(下記
        # `run_sway_degrade_loop()`)の両方の起点として渡す——「パイプ
        # ラインは明示リストに従うだけ」を実際に満たす唯一の配線点。
        job_lab_assignments = _lab_assignments_from_job(
            job, physbone_entries, job.get("springbones"),
            weighted_bone_names=weighted_bone_names)
        hub_wiring, hub_node_overrides, hub_diagnostics_lines, hub_refskel_dict = \
            wire_sway_hub_auto(job, gender, physbone_entries, vanilla, group_targets,
                                lab_assignments=job_lab_assignments,
                                weighted_bone_names=weighted_bone_names)
        auto_entries, manual_node_overrides, manual_diagnostics_lines, sway_report = \
            auto_assign_sway_chains(job, gender, source_parent_of, donor_bone_pairs)

        diagnostics_lines = list(hub_diagnostics_lines) + list(manual_diagnostics_lines)
        # dev#1508 W2a(2026-08-16オーナー追加指示): 変換ログ(「ログをコピー」
        # で送られてくるログ)に、全PB/SBについて「採用(ゆれかた/理由)/
        # 除外(偏向・容量・配線不能)」を機械可読形式で必ず出す
        # (成功時にも全部出す——build_diagnostics_lines()系がplan.all_unitsを
        # 無条件に全件出力する設計)。
        print(f"[{TAG}] === sway diagnostics (dev#1508, {len(diagnostics_lines)} "
              "PB/SB component(s)) ===")
        for line in diagnostics_lines:
            print(f"[{TAG}][sway-diag] {line}")

        # dev#1508 W2a: グループごとの量子化プリセット値+limit_angle写しを
        # ノード単位でKPへ書き込むため、Blenderプロセス(このstep02)と
        # UE非依存パッチプロセス(build_pak_from_avatar.py Phase 3.6)の間で
        # job_dir配下の副ファイル経由で受け渡す(sway_allocator_wire.py
        # モジュールdocstring「job_dirを跨いだ受け渡し」参照)。ハブ経路
        # (hub_node_overrides、キー=ハブroot骨名)と手動経路
        # (manual_node_overrides、通常は常に空dict——auto_assign_sway_chains()
        # docstring参照)を1つのdictへマージする(名前空間が異なるため衝突
        # しない)。
        node_overrides = {**manual_node_overrides, **hub_node_overrides}
        overrides_path = os.path.join(conv, sway_allocator_wire.NODE_OVERRIDES_FILENAME)
        with open(overrides_path, "w", encoding="utf-8") as f:
            json.dump(node_overrides, f, ensure_ascii=False)
        print(f"[{TAG}] sway node overrides written: {overrides_path} "
              f"({len(node_overrides)} node(s))")

        # dev#1508 W2a-2c: ハブroot+自由donorプールの骨のrefskel-dict
        # (`sway_hub.refskel_dict_for_wiring()`)を、Blender側の
        # build_pal_armature()拡張材料+pak側`_refskel_extend_overrides()`
        # 拡張材料の両方に使うため、job_dir/converted/配下へ書く(vanilla/
        # ではない——job固有の動的データを共有vanillaキャッシュへ書くと、
        # 同じPalworldインストールを共有する別ジョブへ漏れうる。
        # `build_pak_from_avatar._refskel_extend_overrides()`側の対応する
        # 追加コメント参照)。空dictでも常に書く(sway_node_overrides.jsonと
        # 同じ「常時書く」流儀、ファイル不在=旧ジョブとの区別に使う)。
        hub_refskel_path = os.path.join(conv, f"sway_hub_refskel_{gender.lower()}.json")
        with open(hub_refskel_path, "w", encoding="utf-8") as f:
            json.dump(hub_refskel_dict, f, ensure_ascii=False)
        print(f"[{TAG}] sway hub refskel written: {hub_refskel_path} "
              f"({len(hub_refskel_dict)} bone(s))")

    # dev#19実データ欠陥修正(issue #1379、欠陥3): resolve_sway_chain_entries()
    # にvanilla_dirを渡し、辞書登録済みでも実ファイルが無い家系(例:
    # HeadEquip062_ear、抽出未実装)を安全にlostへ倒す(FileNotFoundError
    # クラッシュ回避)。この関数呼び出し自体はsway_enable無効時も従来どおり
    # 実行される(auto_entries=[]のno-op経路、既定出力不変)。
    sway_entries = resolve_sway_chain_entries(
        job, gender, auto_entries=auto_entries, vanilla_dir=vanilla)

    # dev#19 leafcollision WP(issue #1407): 複数のsway entryが同じdonorボーン
    # (cloth_chain本体または合成leaf_bone)を取り合うと、reposition段で後発
    # entryが先発entryの正しい計算結果を単純上書きする(donorボーン名衝突、
    # mark_sway_donor_collisions()docstring参照)。resolve直後・reposition前に
    # ここで検出し、後発側を安全にskip扱いへ倒す(die()しない、既存の
    # 「未登録family/refskel未抽出/アバター側ボーン欠落」skipと同じ安全側
    # フォールバック方針)。sway_entries空・全skip済みなら完全no-op。
    sway_entries = mark_sway_donor_collisions(sway_entries)

    if job.get("sway_enable"):
        # item6(静的ゲート、work\rd_19_ears\PROPOSAL.md §6)+dev#19実データ
        # 欠陥修正(issue #1379、欠陥3): sway_report(エンジン段)単独では
        # resolve段のskipを数えず「assigned=N lost=0」の偽緑になっていた
        # (work\rd_19_final\RESULT.md §2実測)。build_sway_end_to_end_report()
        # でresolve段skipを合流させ、実配線数のみを"assigned"として報告する。
        end_to_end = build_sway_end_to_end_report(sway_report, sway_entries)
        if end_to_end["declared_chains"]:
            print(f"[{TAG}] sway-report: declared={end_to_end['declared_chains']} "
                  f"assigned={end_to_end['assigned_chains']} "
                  f"lost={end_to_end['lost_chains']}")
        for lost in end_to_end["lost"]:
            print(f"[{TAG}][WARN][sway-lost] {lost['id']} "
                  f"(anchor={lost['anchor']}): {lost['reason']}")

    # 手動指定(job["sway_chains"]、is_auto=False)のresolve段skipは上の
    # end_to_end集計の対象外(sway_enable自動割当専用の静的ゲートのため)
    # なので、ここで別途ログに出す(auto側は上で出力済み、二重出力回避)。
    for e in sway_entries:
        if e["skipped"] and not e.get("is_auto"):
            print(f"[{TAG}][WARN][sway-lost] {e['sway_cloth_bones'][0]}: {e['skip_reason']}")

    # dev#19 native-donor-rule WP(issue #19): resolve_sway_chain_entries()の
    # family_name分岐が明示job指定をnative_sim_count>=n_source+1規則で検証・
    # auto-correctした場合、その事実をログへ出す(item6の静的ゲートと同じ
    # 「無音で丸めない」方針。「診断ログだけで原因に到達できる」CLAUDE.md方針
    # に沿い、donorがユーザーの期待と違う家系へ差し替わった/縮退した場合の
    # 手がかりを残す)。
    for e in sway_entries:
        if e.get("donor_warning"):
            print(f"[{TAG}][WARN][sway-donor] {e['sway_cloth_bones'][0]}: {e['donor_warning']}")

    active_entries = [e for e in sway_entries if not e["skipped"]]

    # dev#1508 W2a-2c: ハブroot+自由donorプールの骨名(hub_refskel_dictの
    # キー、既にjob_dir/converted/へ書き出し済み——上の`if job.get(
    # "sway_enable")`節参照)を、旧family限定donor経路(active_entries)と
    # 同じ仕組みでbuild_bones/refskel_pathsへ合流させる。
    hub_bone_names = list(hub_refskel_dict.keys())
    hub_refskel_path = os.path.join(conv, f"sway_hub_refskel_{gender.lower()}.json")

    cloth_chain = []
    extra_bones = []
    build_bones = common
    refskel_names = []
    leaf_bones = []
    for e in active_entries:
        cloth_chain += e["cloth_chain"]
        extra_bones += e["extra_bones"]
        if e["refskel_name"] not in refskel_names:
            refskel_names.append(e["refskel_name"])
        # swayfix WP(dev#19): entry["leaf_bone"](§7.2-7.4の実リーフボーン)
        # をbuild_bonesへ含める。refskel JSON側(extract_vanilla.py
        # _add_synthetic_leaf_bone())に合成エントリが無い場合は
        # build_pal_armature()内のvp_bl側が単に見つからないボーンとして
        # スキップする(既存の未知ボーン耐性、die()しない設計を踏襲)。
        leaf = e.get("leaf_bone")
        if leaf:
            leaf_bones.append(leaf)
    if active_entries or hub_bone_names:
        # 重複除去(複数エントリのextra_bonesに同じボーンが重複しうる。
        # build_pal_armature()へ渡す前に一意化、最初に現れた順を維持)
        cloth_chain = list(dict.fromkeys(cloth_chain))
        extra_bones = list(dict.fromkeys(extra_bones))
        leaf_bones = list(dict.fromkeys(leaf_bones))
        build_bones = common + cloth_chain + extra_bones + leaf_bones + hub_bone_names
        # dev#19 m2defects(欠陥1): vp_bl.build_pal_armature()のマージは
        # 「先着ファイル優先」(merge_refskel_files()のdocstring参照)。
        # 共通ボーン(clavicle等)の権威を常に基準骨格(refskel_{gender}.json)
        # に固定するため、entries列挙順に関わらず必ずリスト先頭へ強制する
        # (基準骨格ファイルはextract_vanillaで常に生成されるため必ず存在する)。
        base_refskel_name = f"refskel_{gender.lower()}.json"
        if base_refskel_name in refskel_names:
            refskel_names.remove(base_refskel_name)
        refskel_names.insert(0, base_refskel_name)
        refskel_paths = [os.path.join(vanilla, name) for name in refskel_names]
        if hub_bone_names:
            refskel_paths.append(hub_refskel_path)
        pal_arm = vp_bl.build_pal_armature(refskel_paths, build_bones)
    else:
        refskel_name = f"refskel_{gender.lower()}.json"
        pal_arm = vp_bl.build_pal_armature(
            os.path.join(vanilla, refskel_name), build_bones)

    # dev#1508 W2a-2c: attach_orphan_roots()/build_group_targets()自体は
    # main()冒頭(pal_arm構築より前)へ引き上げ済み(上のコメント参照)。
    # ハブ配線結果のgroup_targets更新は、dev#1508 graceful-degrade
    # (night_20260817 laneI)の縮退ループが最終wiringを確定させた後
    # (`place_hub_donor_chains()`呼び出し位置、下記)でまとめて行う
    # ——縮退ループが除外したunitのdonor骨を先にgroup_targetsへ書き込んで
    # しまうと、remap_vertex_groups()がそのままweightを渡してしまう
    # (縮退が効かなくなる)ため、ここでは意図的に呼ばない。
    for e in active_entries:
        missing = [b for b in e["cloth_chain"] if b not in pal_arm.data.bones]
        if missing:
            core.die(TAG, f"sway_chains: vanilla sway bones were not built: {missing}")
        # dev#1355(2026-08-11)のアンカー1階層規則(先頭帯=搭載骨帯を常に
        # donorチェーンの親head/pelvis等へ畳む)は、dev#19 weight-direct-assign
        # WP(2026-08-14、オーナー裁定「元々ウェイトが乗っているボーンがn本
        # なら、donorはn+1本以上でなければならない」)により**donor不足時の
        # フォールバックへ格下げ**された。アンカー畳み込みで先頭帯を剛体化
        # すると、step01では起き得ない不快な折れ曲がりが発生しうる
        # (オーナーがBlenderポーズ比較で確認)。
        #
        # 新規定: 先頭帯を含む全転写元帯を、旧来の比例配分(sway_cloth_bone_targets()、
        # 内部はsway_cloth_target_indices())ではなく sway_cloth_weight_targets_direct()
        # でdonorチェーンへ「シンプルに1対1」割り当てる。donorが足りる家系は
        # 恒等写像(i -> donor[i])で先頭帯もdonorへ直接乗り、アンカーへは
        # 畳まない。donorが1本だけ足りない家系(leaf2を持つ、現状tailのみ、
        # resolve_sway_chain_entries()のspillover分岐参照)は旧leafを可動donorへ
        # 編入してcloth_chainを1本伸ばしてから本関数へ渡すため、実質的に
        # ここでも先頭帯がdonorへ直接乗る。それでもdonor不足の家系だけが
        # 本関数のアンカー畳み込みフォールバック(SWAY_CLOTH_ANCHOR)に落ちる
        # (③「しょうがない」フォールバック)。比例配分は転写元よりdonorが
        # 長いとき、離散丸めの必然としてdonorの一部を先頭・中間にも空けて
        # しまっていた(耳donorのear_01_l/ear_03_lが支点ずれを起こした原因、
        # work\rd_19_earweight\probe_targets.txt正本)。1対1割当は「使われない
        # 残りdonorは常に末尾側」を保証する。比例配分版の関数自体は削除せず
        # 既存テストのため温存(呼び出しだけ本経路から外した)。屈曲考慮
        # (compute_chain_bend_weights、dev#19 rotfix WP)は比例配分専用の
        # 機構だったため、1対1割当では使わない。
        # tests\coverage\test_step02_sway_cloth_weight_direct_dev19.py参照。
        sway_bones = e["sway_cloth_bones"]
        anchor_bone = e["anchor_bone"]
        target_indices = sway_cloth_weight_targets_direct(
            len(sway_bones), len(e["cloth_chain"]))
        for i, av in enumerate(sway_bones):
            idx = target_indices[i]
            group_targets[av] = (
                anchor_bone if idx == SWAY_CLOTH_ANCHOR else e["cloth_chain"][idx])
        print(f"[{TAG}] sway_chain (experimental): {sway_bones} -> "
              f"anchor={anchor_bone} chain={e['cloth_chain']}")

    global_scale_and_place(avatar_arm, pal_arm, pal_map, meta.get("warnings"))
    auto_fit_pose(avatar_arm, pal_arm, pal_map)
    apply_shoulder_offset(avatar_arm, pal_map,
                          float(job.get("shoulder_offset_deg", 0.0)))
    bake_pose_into_meshes(avatar_arm, meshes)
    dz = snap_to_ground(meshes)
    # dev#1365(2026-08-11): sway donorチェーン(cloth_chain+extra_bones)は
    # 実在の人体関節ではなく「揺れメッシュの入れ物」であり、chibi_fit_armature()
    # の子孫平行移動(道連れ)対象から除外する。donorファミリーの祖先が
    # CHIBI_CANDIDATES(例: Ancient001<-thigh_r)を経由すると、そのボーンの
    # chibi-fit補正デルタがdonorチェーン全体へ無条件に伝播し、バインド位置と
    # 写像済みメッシュ頂点の実座標が最大約88cmもズレて破綻する
    # (work\rd_19_r2b3\diag_ancient\DIAG.md実測)。除外しても、donorチェーン自体は
    # 常に build_bones に含まれ chibi_fit_armature() の1)〜3)の明示ターゲット
    # (CHIBI_CANDIDATES/SPINE_CHAIN/CHIBI_TWIST_BONES)には元々含まれないため、
    # sway_cloth未指定時(cloth_chain/extra_bones空)は完全no-op=既定出力不変。
    sway_donor_bone_names = set(cloth_chain) | set(extra_bones) | set(hub_bone_names)
    chibi_fit_armature(pal_arm, avatar_arm, pal_map, dz,
                        exclude_descendants=sway_donor_bone_names)

    # swayfix WP(dev#19、issue#19、work\rd_19_anglelimit\PROPOSAL.md §7が
    # 正本): chibi_fit_armature()の直後(anchor_boneの最終位置が確定した後)に
    # ①donor静止姿勢の再配置+②実リーフボーン配置+③donor回転の再構成
    # (dev#19 rotfix WP、work\rd_19_scurve\PROPOSAL.md §7.1)を行う。sway未指定
    # (active_entries空)なら関数内で即return {}=完全no-op、既定出力不変。
    sway_donor_quats = reposition_sway_donor_chain_and_leaf(
        pal_arm, avatar_arm, active_entries, dz)

    # dev#1508 W2a-2c: ハブ経路(hub_wiring)のdonor鎖を、旧経路と同じタイミング
    # (chibi_fit_armature()直後)でexact-bone-copy配置する。donor_quatsを
    # sway_donor_quatsへマージ(キー空間が異なるため衝突しない)。
    #
    # dev#1508 graceful-degrade(揺れ鎖の明示的縮退、night_20260817
    # laneI): 単発の`place_hub_donor_chains()`呼び出しの代わりに、
    # remap実行前に位置/向き/スケール/支点公理/重み衝突を検査し、
    # FAILが特定の鎖(unit)に帰属できればその鎖だけを除外して再配線・
    # 再検査する縮退ループを通す(最大2回リトライ、それでも直らなければ
    # sway全体をOFFへ縮退)。`hub_wiring`をここで最終確定値へ差し替える
    # ことで、以降の全参照(exact_donor_world/plan_reparent_steps/
    # run_sway_source_gate等)が自動的に縮退後の状態を見る。
    # dev#1508 graceful-degrade「2. 可視化」node: sway_enable=偽のときは
    # 縮退ループ自体を回さない(job["springbones"]はsway_enableと無関係に
    # 常時抽出されるため——laneG_vrm_w1b.md/PROGRESS.md「負の対照①」
    # 参照——縮退ループを無条件で回すと、sway無効のジョブでも無意味な
    # transformチェック→systemic disable扱いが走り、ユーザーが要求
    # していないsway_exclusions_{gender}.json/WARNが出てしまう)。
    if job.get("sway_enable"):
        (hub_wiring, hub_node_overrides, hub_diagnostics_lines, hub_refskel_dict,
         hub_donor_quats, sway_lab_overrides, sway_exclusion_entries,
         sway_fully_disabled) = run_sway_degrade_loop(
            job, gender, physbone_entries, job.get("springbones"),
            avatar_arm, pal_arm, group_targets, anchor_pal_map, dz,
            vanilla, pal_map, source_parent_of,
            hub_wiring, hub_node_overrides, hub_diagnostics_lines, hub_refskel_dict,
            initial_lab_overrides=job_lab_assignments)

        # 縮退ループが最終確定させたwiringを使って、ここで初めて
        # group_targetsへハブ配線結果を反映する(上の「dev#1508 W2a-2c:
        # attach_orphan_roots()」節コメント参照。除外されたunitのdonor骨は
        # source_to_donor_bone_map()の戻り値に一切現れないため、後段の
        # remap_vertex_groups()は自動的にそのソース骨を標準retarget先へ
        # 振り向ける)。
        if hub_wiring.group_plans:
            group_targets.update(sway_hub_wire.source_to_donor_bone_map(hub_wiring, gender))

        # dev#1508 graceful-degrade: 縮退ループがattempt0(main()冒頭の初回
        # wire_sway_hub_auto()呼び出し)より縮小したwiringへ確定させた場合、
        # 既に書き出し済みの`sway_node_overrides.json`/`sway_hub_refskel_
        # {gender}.json`(pal_arm構築前、attempt0の内容で書かれている——
        # pal_armの骨集合を決めるため書き込み自体は前倒しせざるを得ない)を
        # 最終確定値で上書きする。pak側の後続処理(Phase 3.6/3.7、この
        # Blenderプロセス終了後に別プロセスで読む)が、実際には配線されな
        # かった鎖のKPノード/refskel拡張データを見ずに済むようにする
        # (未上書きのままでも実害は無い——除外された鎖のdonor骨はweight 0の
        # ままpal_arm内に留まるだけで見た目に影響しない——が、上書きした方が
        # より正確)。
        node_overrides_final = {**manual_node_overrides, **hub_node_overrides}
        overrides_path = os.path.join(conv, sway_allocator_wire.NODE_OVERRIDES_FILENAME)
        with open(overrides_path, "w", encoding="utf-8") as f:
            json.dump(node_overrides_final, f, ensure_ascii=False)
        hub_refskel_path_final = os.path.join(conv, f"sway_hub_refskel_{gender.lower()}.json")
        with open(hub_refskel_path_final, "w", encoding="utf-8") as f:
            json.dump(hub_refskel_dict, f, ensure_ascii=False)
        if sway_exclusion_entries:
            print(f"[{TAG}] sway degrade: node overrides/refskel re-written with "
                  f"final (post-degrade) wiring: {overrides_path}, "
                  f"{hub_refskel_path_final}")

        # dev#1508 graceful-degrade「2. 可視化」: 除外が起きたら
        # converted\sway_exclusions_{gender}.json(常時、除外ゼロでも空で
        # 書く)+1鎖1行のWARN(ユーザーの「ログをコピー」に載る)。
        sway_full_plan = sway_allocator.allocate(
            physbones_json={"physbones": list(physbone_entries or [])},
            springbones_json={"springbones": list(job.get("springbones") or [])})
        sway_degrade_total_units = len(sway_degrade.all_unit_keys(sway_full_plan))
        # Capacity exclusions are recorded by the loop from its actual initial
        # plan, including the user's overrides. Re-allocating without overrides
        # here could mislabel an explicitly selected chain as overflow.
        sway_exclusions_report = sway_degrade.ExclusionReport(
            gender=gender.lower(), total_units=sway_degrade_total_units,
            fully_disabled=sway_fully_disabled, excluded=tuple(sway_exclusion_entries))
        sway_exclusions_path = os.path.join(conv, f"sway_exclusions_{gender.lower()}.json")
        with open(sway_exclusions_path, "w", encoding="utf-8") as f:
            json.dump(sway_exclusions_report.to_dict(), f, ensure_ascii=False, indent=1)
        for line in sway_degrade.format_warn_lines(sway_exclusion_entries):
            print(f"[{TAG}][WARN] {line}")
        # dev#1625(2026-08-21 オーナー裁定「変換自体はいつも通り完走+
        # 結果画面で告知」): GUI完了ダイアログ向けの##AVATAR_WARNING##は、
        # ここ(Blender工程、Phase 1)ではなく`pipeline\py\convert_noue.py`
        # (Phase 2-6)側で出す——`convert.ps1`のPhase 1リレー(Run-Blender/
        # Phase1GenderWorkerScript)は表示用に
        # `Select-String -Pattern "\[(step|preview|vp_bl|validate)|FATAL|Error"`
        # で行を間引いており、`##AVATAR_WARNING##`はこのパターンに一致
        # しないため、ここでprintしても呼び出し元(app_py)まで届かない
        # (convert.ps1はこのWPの書き込み許可範囲外、実機検証で発覚:
        # work\wp_1625_notes\NOTES.md参照)。Phase 2-6(convert_noue.py経由)
        # はフィルタ無しでそのまま中継される設計のため、この
        # `sway_exclusions_{gender}.json`(直前で書き出し済み)を
        # convert_noue.py側が読み直してそこでマーカーを出す。
        if sway_fully_disabled:
            # dev#29「診断ログ完全英語固定」(tests\diag_log_lint\
            # test_no_japanese_diagnostic_logs_dev1282.py)に従い英語で出す。
            print(f"[{TAG}][WARN][sway-degrade] the sway feature will not sway "
                  "this time for this avatar (this run only) -- see "
                  f"{sway_exclusions_path} for details")
        _sway_exclusions_merge_write(conv, gender, sway_exclusions_report)
    else:
        # sway_enable=偽: 従来どおりhub_wiring(空既定のまま)を単に配置
        # するだけ(no-op、`place_hub_donor_chains()`は空wiringなら即座に
        # {}を返す)。sway_lab_overridesはNone(run_sway_source_gate自体が
        # sway_enable=偽では呼ばれないため未使用だが、後方参照エラーを
        # 避けるため定義しておく)。sway_exclusions_{gender}.jsonは
        # 「対象外(total_units=0)」として常時出力する(laneI指示書
        # 「除外ゼロでも空で書く」の趣旨をsway_enable=偽の場合にも適用)。
        hub_donor_quats = place_hub_donor_chains(
            pal_arm, avatar_arm, hub_wiring, gender, anchor_pal_map, dz)
        sway_lab_overrides = None
        sway_exclusions_report = sway_degrade.ExclusionReport(
            gender=gender.lower(), total_units=0, fully_disabled=False, excluded=())
        sway_exclusions_path = os.path.join(conv, f"sway_exclusions_{gender.lower()}.json")
        with open(sway_exclusions_path, "w", encoding="utf-8") as f:
            json.dump(sway_exclusions_report.to_dict(), f, ensure_ascii=False, indent=1)
        _sway_exclusions_merge_write(conv, gender, sway_exclusions_report)
    sway_donor_quats.update(hub_donor_quats)

    # dev#1508 実機実測バグ修正(2026-08-16、オーナーリアルタイム観測
    # 「step02は正しいがpak/実機側はまだおかしい」): `sway_hub_placement.
    # plan_reparent_steps()`の独自近似計算(avatar_dump+hips/head基準の
    # 一様相似変換)は、`chibi_fit_armature()`の非一様な関節移動を反映
    # できず、実際にBlenderへ配置したdonor骨位置(mesh bindの基準そのもの)
    # と最大約35cm級でズレることが実データ実測で判明した(詳細は
    # sway_hub_placement.plan_reparent_steps()のdocstring「exact_donor_world」
    # 節参照)。ここで実際にpal_arm上に配置されたdonor骨のworld位置
    # (UE規約[x,-y,z]、chibi_bone_world_head_{gender}.jsonと同一の変換)+
    # 回転(hub_donor_quats、既にUE規約で計算済み)を集め、
    # plan_reparent_steps()へ渡すことで、mesh bind基準と共有Skeleton
    # reparent基準を同一ソースへ統一し、ズレを構造的に無くす。
    exact_donor_world = {}
    for gp in hub_wiring.group_plans:
        # dev#1551(ゼロ長root廃止修理): hub root自身も今やsource_chain[0]
        # (anchor)のexact geometryを担う実節のため、donor鎖と同じ扱いで
        # exact_donor_worldへ加える(`place_hub_donor_chains()`が
        # `hub_donor_quats[hub_name]`へ既に向きを記録済み)。
        hub_name = gp.hub_root_male if gender == "Male" else gp.hub_root_female
        if hub_name not in exact_donor_world:
            hb = pal_arm.data.bones.get(hub_name)
            if hb is not None and hub_name in hub_donor_quats:
                hw = pal_arm.matrix_world @ hb.head_local
                exact_donor_world[hub_name] = (
                    hub_donor_quats[hub_name], (hw.x, -hw.y, hw.z))
        for cp in gp.chain_plans:
            # dev#1551(性別またぎdedup漏れ修正): この`main()`呼び出しは
            # 性別ごとに別プロセスで1回だけ走るので、このプロセスの
            # `gender`向けのdonor骨列(bivariantスロットでは他方の性別と
            # 互いに素)だけを対象にする。
            for name in cp.donor_chain_for(gender):
                if name in exact_donor_world:
                    continue
                b = pal_arm.data.bones.get(name)
                if b is None or name not in hub_donor_quats:
                    continue
                w = pal_arm.matrix_world @ b.head_local
                pos_ue = (w.x, -w.y, w.z)
                exact_donor_world[name] = (hub_donor_quats[name], pos_ue)

    # dev#1508 W2a-2c(pak側、Phase 3.7結線): ハブroot+donor鎖の共有Skeleton
    # (SK_PalHuman_Skeleton)側reparent計画を`sway_hub_placement.
    # plan_reparent_steps()`(bpy非依存)で計算し、job_dir/converted/
    # sway_hub_reparent.jsonへ書く(`build_pak_from_avatar.py`
    # `_run_sway_hub_reparent_patch()`が読む契約、Phase 3.7)。
    # avatar_dumpはbake_pose_into_meshes()後・dz確定後のavatar_arm実ポーズ
    # (`build_avatar_dump()`、`place_hub_donor_chains()`のav_point()と
    # 同一座標規約)、anchor_pal_name_ofは`anchor_pal_map`(`group_targets`の
    # sway donor上書き前スナップショット、`place_hub_donor_chains()`
    # docstring「2026-08-16実データ実測バグ」節参照——`group_targets`
    # そのものを渡すと循環参照によるトポロジ違反で変換が停止する)。
    #
    # 性別ごとに1回ずつ実行されるこのstep02が、同一job_dirへ2回(Male/Female、
    # convert.ps1のPhase1では実際には並列バックグラウンドジョブとして同時に
    # 走る——書き込み順序は保証されない)書き込む——共有Skeletonは男女の
    # ハブroot/donor骨名を両方(F_/M_接頭辞)同時に持つため、両性別ぶんの
    # ReparentStepを**マージ**して書く(単純な上書きだと後に走った性別のみが
    # 反映され、先に走った性別のKP物理が抜け落ちる)。
    #
    # dev#1551(性別またぎdedup漏れ修正、issue #1551、正本work\run_1551\
    # integG\RESULT.md): 「両性別のターゲット骨名は接頭辞が異なり衝突しない」
    # という以前のコメントの前提は、ハブroot自身には真だが、donor鎖の続き骨
    # (`ChainDonorPlan.donor_chain`、旧単一フィールド)には**偽**だった——
    # donor鎖続き骨の絶対名は性別非依存の同一名で払い出されており、Male先行
    # 処理でF_接頭root向けのdonor鎖登録が丸ごとdedupで落ちていた(実測:
    # 両検体・全bivariantタグでFemale側donor鎖が0件)。`sway_hub.
    # plan_hub_wiring()`を修正し、ハブrootが性別で異なる名前を持つ
    # (bivariant)スロットではdonor鎖続き骨も女性向け/男性向けで**互いに素な**
    # 骨集合を割り当てるようにした(`ChainDonorPlan.donor_chain_for()`
    # docstring参照)——これにより「両性別のターゲット骨名は衝突しない」が
    # 構造的に真になり、以下の素直な追記マージ(既存targetを後着で
    # 上書きしない)が並列書き込みの順序に関わらず安全に成立する
    # (univariantスロット(耳・しっぽ等、女性/男性で同一名)は従来どおり
    # 両性別が同一内容を書くため、dedupで片方が省かれても実害が無い)。
    if hub_wiring.group_plans:
        avatar_dump = build_avatar_dump(avatar_arm, dz)
        catalog_path = os.path.join(vanilla, "sk_palhuman_full.json")
        catalog = sway_hub.load_skeleton_catalog(catalog_path)
        try:
            # dev#1508 W1b実データ検証で発見(work\night_20260817\laneG):
            # plan_reparent_steps()のhips_avatar_name/head_avatar_nameは
            # 既定でリテラル"Hips"/"Head"だが、avatar_dump(build_avatar_dump()
            # が作る、実アーマチュアの生ボーン名でキー付け)にその名前の
            # ボーンが実在するとは限らない(例: Seed-san.vrmの実ボーン名は
            # "head 1")。avatar_dumpのキーは実ボーン名そのものなので、
            # pal_map(パルボーン識別子->実ボーン名)から正しい実ボーン名を
            # 引いて渡す必要がある——今までPB(prefab)経路のテスト検体が
            # たまたま"Hips"/"Head"という実ボーン名の慣習に従っていたため
            # 露見していなかった潜在バグ(job["springbones"]が常に空だった
            # VRM経路では、このコードパス自体が一度も実行されていなかった)。
            # pal_mapに万一無い場合は旧来のリテラル既定へフォールバックする
            # (無退行)。
            reparent_steps = sway_hub_placement.plan_reparent_steps(
                hub_wiring, catalog, gender, avatar_dump, anchor_pal_map,
                hips_avatar_name=pal_map.get("pelvis", "Hips"),
                head_avatar_name=pal_map.get("head", "Head"),
                exact_donor_world=exact_donor_world)
        except sway_hub_placement.SwayHubPlacementError as e:
            core.die(TAG, f"sway hub reparent planning failed (dev#1508 W2a-2c): {e}")

        def _step_to_json(s):
            return {
                "target": s.target, "new_parent": s.new_parent,
                "new_local_transform": (
                    [list(s.new_local_transform[0]), list(s.new_local_transform[1]),
                     list(s.new_local_transform[2])]
                    if s.new_local_transform is not None else None),
                "tag": s.tag,
            }

        reparent_path = os.path.join(conv, "sway_hub_reparent.json")
        existing_steps = []
        if os.path.isfile(reparent_path):
            with open(reparent_path, encoding="utf-8") as f:
                existing_steps = json.load(f)
        existing_targets = {s["target"] for s in existing_steps}
        new_steps_json = [_step_to_json(s) for s in reparent_steps
                           if s.target not in existing_targets]
        merged_steps = existing_steps + new_steps_json
        with open(reparent_path, "w", encoding="utf-8") as f:
            json.dump(merged_steps, f, ensure_ascii=False)
        print(f"[{TAG}] sway hub reparent steps written: {reparent_path} "
              f"({len(new_steps_json)} new, {len(merged_steps)} total)")

    # dev#560(2026-08-07): L1完結の一様スケール。既定1.0では完全no-op
    # (関数側でも早期return、負の対照はtest_uniform_scale_l1.pyで検証)。
    # chibi_fit_armature()の直後・世界座標系がpal_arm/meshesで揃っている
    # このタイミングでのみ安全に呼べる(apply_output_scale()のdocstring参照)。
    apply_output_scale(pal_arm, meshes, float(job.get("uniform_scale", 1.0)))

    # U21: 指の破裂状変形の根治(noueパイプライン専用)。
    #
    # 背景: chibi_fit_armature()はpal_arm(パル骨格)の関節を「アバターの実際の
    # 関節位置」へ移動する(向き不変・位置のみ、docstring参照)。この移動後の
    # pal_arm rest poseが、以降の remap_vertex_groups/rebind でメッシュ頂点の
    # スキニング基準として使われる(=メッシュはこの配置に対して作られる)。
    #
    # ところがnoueパイプライン(build_avatar_variant.py)はテンプレートSKの
    # RefSkeleton(FTransform、=cookedバインドポーズ)をverbatimコピーするのみで、
    # このchibi-fit後の関節位置を一切反映しない(U21診断で確定、
    # docs/DEV_NOTES.md先頭のU21節参照)。その結果、注入されたメッシュ頂点
    # position(chibi-fit後の配置基準)と、cookedバインドポーズ(テンプレート
    # 自身の配置、既定はバニラ生成キャラの汎用体型)が数cm単位でズレる。
    # 手・腕は目立たないが、指は短いボーンのため即座に破裂状に見える
    # (PalMod HANDOFF.md 不具合③と同型)。
    #
    # 対策: chibi-fit後のpal_arm全ボーンのworld head位置を、メッシュ頂点と
    # 同じ座標規約(dump_avatar_mesh.py/vp_meshrestore.encode_position系列が
    # 検証済みの「Blenderワールド座標(x,y,z)->UE(x,-y,z)」変換、スケールは
    # 既にstep02のglobal_scale_and_place()でPalworld cm相当に揃え済みなので
    # 追加の100倍等は不要)でJSONへダンプする。build_avatar_variant.pyは
    # このJSONを読み、RefSkeletonのバインドポーズ位置(回転・スケールは
    # 元のまま)だけをこの値に一致するようパッチする
    # (chibi_fit_armature()が回転を一切変えない設計であることを利用し、
    # ローカル回転はテンプレート値を使い回してよい。詳細な導出はU21診断の
    # FK往復検証、docs/DEV_NOTES.md参照)。
    _chibi_bone_world_head = {
        b.name: [b.head_local.x, -b.head_local.y, b.head_local.z]
        for b in pal_arm.data.bones
    }
    _chibi_dump_path = os.path.join(
        conv, f"chibi_bone_world_head_{gender.lower()}.json")
    with open(_chibi_dump_path, "w", encoding="utf-8") as f:
        json.dump(_chibi_bone_world_head, f)
    print(f"[{TAG}] chibi_bone_world_head: {len(_chibi_bone_world_head)} bone(s) "
          f"-> {_chibi_dump_path}")

    # dev#19 rotfix WP: donor回転(quat、コンポーネント空間、UE規約)を
    # chibi_bone_world_quat_{gender}.jsonへダンプする(sway donorチェーンの
    # ボーンに限る、reposition_sway_donor_chain_and_leaf()の戻り値)。
    # sway_donor_quatsが空(=非swayジョブ)ならファイル自体を作らない
    # (chibi_bone_world_head同様、build_avatar_variant.py側は未検出を
    # 「回転パッチなし=完全no-op」として扱う、負の対照で確認)。
    if sway_donor_quats:
        _chibi_quat_dump_path = os.path.join(
            conv, f"chibi_bone_world_quat_{gender.lower()}.json")
        with open(_chibi_quat_dump_path, "w", encoding="utf-8") as f:
            json.dump({k: list(v) for k, v in sway_donor_quats.items()}, f)
        print(f"[{TAG}] chibi_bone_world_quat (dev#19 rotfix): "
              f"{len(sway_donor_quats)} donor bone(s) -> {_chibi_quat_dump_path}")

    # 揺れ髪: アバター髪を分離してバニラ髪の揺れチェーンに載せる
    hair_obj = None
    hair_assignment = {}
    hair_refskel = os.path.join(vanilla, "refskel_hair.json")
    if job.get("hair_sway", True):
        if not os.path.exists(hair_refskel):
            print(f"[{TAG}][WARN] refskel_hair.json not found — hair sway disabled "
                  "(vanilla extraction needs to be redone)")
        else:
            local_warn = []
            hair_bones = detect_hair_chains(
                avatar_arm, pal_map, job.get("hair_bones", []),
                meta.get("spring_roots", []), local_warn)
            for w in local_warn:
                print(f"[{TAG}][WARN] {w}")
            _van_hair, sway_chains = load_hair_chains(hair_refskel)
            if hair_bones and sway_chains \
                    and add_sway_hair_bones(pal_arm, hair_refskel):
                meshes, hair_obj = split_hair_mesh(meshes, hair_bones)
                if hair_obj is not None:
                    hair_assignment = assign_hair_chains(
                        pal_arm, avatar_arm, hair_bones, sway_chains)

    # no_skin_meshes: remap後にパルボーンへのウェイトが1つも無かった
    # (=0 pal groups)メッシュ名。log_structure_summary()の確定判定に使う
    # (詳細はlog_structure_summary()のdocstring参照)
    no_skin_meshes = set()
    # rescue_target: 実際にrescue_zero_weight_vertices()で束縛したパルボーン名
    # (log_structure_summary()の警告文言を実態に合わせるため)
    rescue_target = {}
    for obj in meshes:
        n_pal_groups = remap_vertex_groups(obj, group_targets)
        if n_pal_groups == 0:
            no_skin_meshes.add(obj.name)
        # 非スキンメッシュ(帽子・リボン等): 元の親ボーンをHumanoid対応表
        # (build_group_targets()が作った「実ボーン名→パルグループ名」、
        # 祖先walkのフォールバック込み)で解決し、そのパルボーンへ束縛する。
        # 解決できない場合のみ従来通りpelvis(要警告)
        target_bone = ZERO_WEIGHT_FALLBACK_BONE
        src_bone = unskinned_source_bone.get(obj.name)
        if src_bone:
            resolved = group_targets.get(src_bone)
            if resolved:
                target_bone = resolved
            else:
                print(f"[{TAG}][WARN] non-skinned mesh {obj.name}: original parent bone "
                      f"'{src_bone}' does not map to the pal skeleton, "
                      f"rescued to '{ZERO_WEIGHT_FALLBACK_BONE}'")
        rescue_target[obj.name] = target_bone
        rescue_zero_weight_vertices(obj, target_bone, pal_arm=pal_arm)
    if hair_obj is not None:
        hair_targets = dict(group_targets)
        hair_targets.update(hair_assignment)
        if remap_vertex_groups(hair_obj, hair_targets) == 0:
            no_skin_meshes.add(hair_obj.name)
        meshes = meshes + [hair_obj]

    # dev#1508 受入ゲート正本化(オーナー制定文言、fail-closed): メッシュの
    # 頂点ウェイトremapが全て終わり(上のremap_vertex_groups()ループ+hair)、
    # かつavatar_armがまだ削除されていない(次のbpy.data.objects.remove()の
    # 直前)、このタイミングでのみ両方の実測値が同時に揃う。job["sway_enable"]
    # が偽ならphysbone_entries自体が存在しない(gate自体が対象骨0件で
    # no-opになるはずだが、変数未定義エラーを避けるため呼び出し自体を
    # 同じ条件でガードする)。
    if job.get("sway_enable"):
        # dev#1508 graceful-degrade(night_20260817 laneI): 縮退ループが
        # 確定させた除外集合(sway_lab_overrides)を渡すことで、この
        # 最終防衛線が縮退済みの(=既に受入検証済みの)鎖だけを検査する
        # ——縮退で意図的に除外した鎖を「配線先が無い」FAILとして
        # 誤検出しない。
        run_sway_source_gate(
            job, gender, physbone_entries, job.get("springbones"),
            avatar_arm, pal_arm, meshes, group_targets, conv, vanilla,
            hub_wiring, dz, pal_map, source_parent_of,
            lab_assignments=sway_lab_overrides)

    rebind(meshes, pal_arm)
    bpy.data.objects.remove(avatar_arm, do_unlink=True)

    pal_arm.name = "Armature"
    if pal_arm.data:
        pal_arm.data.name = "Armature"

    # 成功時にも構造の要点をログへ残す(帽子が原点へ落ちる、のような
    # 「成功はしたが結果がおかしい」不具合を、検体を貰わずログだけで
    # 診断できるようにするため。CLAUDE.md「数値より先に画像を見る」の
    # ログ版: 実物を見なくても異常な位置関係に機械が気づけるようにする)
    log_structure_summary(meshes, pal_arm, orig_parent_info,
                          len(meta.get("slots", {})), no_skin_meshes,
                          rescue_target)

    out = os.path.join(conv, f"step02_{gender.lower()}.blend")
    vp_bl.save_mainfile_or_die(TAG, out)
    print(f"[{TAG}] saved: {out}")


main()
