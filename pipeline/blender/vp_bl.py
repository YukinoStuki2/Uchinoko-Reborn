# -*- coding: utf-8 -*-
"""Blender工程の共通ヘルパー: ジョブ読込・パルアーマチュア構築・VRM Humanoidマップ。

パルアーマチュアはPSKを使わず、実行時抽出したRefSkeleton JSON(数値のみ)から
直接構築する。UE→Blenderの座標変換は M=diag(1,-1,1) の共役
(PalMod add_hair_bones/patch_psk_to_1_0 で較正・実証済みの規約)。
"""

import difflib
import json
import os
import re
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "py"))
import vp_core as core  # noqa: E402
import vp_dup_armature as vp_dup  # noqa: E402 (dev#1174: 重複armature検出、bpy非依存)


def blender_argv():
    """blender ... -- <args> の <args> 部分。"""
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def load_job_from_argv():
    args = blender_argv()
    if not args:
        core.die("vp_bl", "no job JSON specified (-- job.json)")
    return core.load_job(args[0]), args[1:]


def die(tag, msg):
    core.die(tag, msg)


def disable_version_backup():
    """Blenderの保存時バックアップ(既存ファイルを.blend1へリネームしてから
    書く"version backup"機構)を無効化する。dev#472: このリネームが他プロセスの
    ロックで失敗すると「Unable to make version backup」がユーザーに生で露出する
    (2026-07-31実機、v2.2.11)。バックアップのリネーム自体を起こさないのが
    構造対策の本体(vp_core.translate_save_errorはそれでも失敗した場合の保険)。
    このプロセス(このBlenderインスタンス)内の以降の保存すべてに効く。"""
    bpy.context.preferences.filepaths.save_version = 0


def save_mainfile_or_die(tag, filepath):
    """save_as_mainfileの共通ラッパー(dev#472)。

    保存前にdisable_version_backup()でバックアップ用リネーム自体を無効化する。
    それでも保存が失敗した場合: 元の例外(診断用、英語原文)を先にログへ残し、
    vp_core.translate_save_errorで翻訳できた場合のみユーザー向けメッセージで
    die()する。翻訳対象外の例外(保存失敗と無関係)はそのまま伝播させ、
    握りつぶさない。"""
    disable_version_backup()
    try:
        bpy.ops.wm.save_as_mainfile(filepath=filepath)
    except Exception as e:
        print(f"[{tag}][ERROR] save_as_mainfile failed: {core.format_exception_for_log(e)}")
        friendly = core.translate_save_error(e)
        if friendly is None:
            raise
        die(tag, friendly)


# ------------------------------------------------ パルアーマチュア構築(PSK不使用)

# UEワールド → Blenderワールド: 位置 p_b = M @ p_ue、回転 R_b = M R_ue M^-1
_M = Matrix(((1, 0, 0), (0, -1, 0), (0, 0, 1)))
_Minv = _M.inverted()


def _ue_world_chain(refskel):
    """RefSkeletonローカル値をUEワールドへ連鎖合成して {bone: (quat, pos)} を返す。"""
    world = {}

    def rec(name):
        if name in world:
            return world[name]
        b = refskel[name]
        q = Quaternion((b["quat"][3], b["quat"][0], b["quat"][1], b["quat"][2]))
        p = Vector(b["pos"])
        if b["parent"] is None or b["parent"] not in refskel:
            world[name] = (q, p)
        else:
            pq, pp = rec(b["parent"])
            world[name] = (pq @ q, pp + pq @ p)
        return world[name]

    for n in refskel:
        rec(n)
    return world


def merge_refskel_files(paths):
    """複数のrefskel_*.json(各々が人体骨格全体+そのファミリー固有チェーンを
    含む自己完結データ)を1つの辞書へマージする純粋関数(bpy非依存)。

    dev#19 m2defects(2026-08-11、work\\rd_19_m2smoke\\RESULT.md 欠陥1):
    旧実装は`dict.update()`で「後着ファイルが上書き」する素朴なマージだった。
    これは「共通ボーンの値はfamily間で同一」という前提に立っていたが、
    実データ(refskel_headequip062_ear_{gender}.json)ではclavicle_l/rの
    quatが基準骨格(refskel_{gender}.json)と最大約10度食い違うことが実測で
    判明した(HeadEquip062_ear系SKアセット固有の抽出結果差と見られる)。
    後着ファイルがこの食い違った値で共通ボーンを上書きすると、揺れチェーン
    とは無関係な体幹骨格(肩など)が丸ごと歪む(retarget_structure_check
    FATAL、orientation 10.10deg)。

    修正: **先に読み込んだファイルの値を権威として保持し、後続ファイルでは
    上書きしない**(setdefault方式)。呼び出し側(step02_retarget.py)が
    常に基準骨格ファイル(refskel_{gender}.json)をリスト先頭に置くことで、
    マージ順序(sway entriesの列挙順)に依存せず、共通ボーンは常に基準骨格
    の値を使う決定的な結果になる。単一パス指定時は従来と完全に同じ1ファイル
    読み込みのみで、挙動は無変更(後方互換)。
    """
    refskel = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            loaded = json.load(f)
        for k, v in loaded.items():
            refskel.setdefault(k, v)
    return refskel


def build_pal_armature(refskel_path, common_bones, name="PalArmature"):
    """RefSkeleton JSONからパル骨格アーマチュアを構築する(cm単位)。
    common_bones に無いボーン(衣装固有クロスボーン)は作らない。

    refskel_path: 単一のファイルパス(従来どおり、str/os.PathLike)、または
    複数パスのリスト(dev#1375、dev#19 R3統合: 同時Nチェーンが異なるdonor
    ファミリー由来のrefskel_{suffix}_{gender}.json複数を必要とする場合、
    全ファイルの内容をマージしてから骨格を構築する)。マージの詳細・
    優先順位(先着ファイル優先)は merge_refskel_files() のdocstring参照
    (dev#19 m2defects)。単一パス指定時は従来と完全に同じ1ファイル読み込み
    のみで、挙動・ログとも無変更(後方互換)。
    """
    paths = [refskel_path] if isinstance(refskel_path, (str, os.PathLike)) else list(refskel_path)
    refskel = merge_refskel_files(paths)
    keep = [b for b in refskel if b in set(common_bones)]
    world = _ue_world_chain(refskel)

    arm_data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_data.edit_bones
    for bone_name in keep:  # refskelは親→子順
        uq, up = world[bone_name]
        p = _M @ up
        q = (_M @ uq.to_matrix() @ _Minv).to_quaternion()
        b = eb.new(bone_name)
        b.head = (0, 0, 0)
        b.tail = (0, 4, 0)  # 長さ4cm(向きはmatrixで決まる)
        b.matrix = Matrix.LocRotScale(p, q, Vector((1, 1, 1)))
        parent = refskel[bone_name]["parent"]
        if parent and parent in eb:
            b.parent = eb[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"[vp_bl] pal armature built: {len(keep)} bones from "
          f"{', '.join(os.path.basename(p) for p in paths)}")
    return arm


# ------------------------------------------------------- VRM Humanoidマッピング

# VRM1(アドオンのsnake_case属性名) → パルボーン
VRM1_TO_PAL = {
    "hips": "pelvis", "spine": "spine_01", "chest": "spine_02",
    "upper_chest": "spine_03", "neck": "neck_01", "head": "head",
    "left_shoulder": "clavicle_l", "left_upper_arm": "upperarm_l",
    "left_lower_arm": "lowerarm_l", "left_hand": "hand_l",
    "right_shoulder": "clavicle_r", "right_upper_arm": "upperarm_r",
    "right_lower_arm": "lowerarm_r", "right_hand": "hand_r",
    "left_upper_leg": "thigh_l", "left_lower_leg": "calf_l",
    "left_foot": "foot_l", "left_toes": "ball_l",
    "right_upper_leg": "thigh_r", "right_lower_leg": "calf_r",
    "right_foot": "foot_r", "right_toes": "ball_r",
    # 指: VRM1の親指は Metacarpal/Proximal/Distal の3節
    "left_thumb_metacarpal": "thumb_01_l", "left_thumb_proximal": "thumb_02_l",
    "left_thumb_distal": "thumb_03_l",
    "right_thumb_metacarpal": "thumb_01_r", "right_thumb_proximal": "thumb_02_r",
    "right_thumb_distal": "thumb_03_r",
}
for _f_vrm, _f_pal in (("index", "index"), ("middle", "middle"),
                       ("ring", "ring"), ("little", "pinky")):
    for _s_vrm, _s_pal in (("proximal", "01"), ("intermediate", "02"),
                           ("distal", "03")):
        for _side, _sfx in (("left", "l"), ("right", "r")):
            VRM1_TO_PAL[f"{_side}_{_f_vrm}_{_s_vrm}"] = f"{_f_pal}_{_s_pal}_{_sfx}"

# VRM0(camelCase) → パルボーン
VRM0_TO_PAL = {
    "hips": "pelvis", "spine": "spine_01", "chest": "spine_02",
    "upperChest": "spine_03", "neck": "neck_01", "head": "head",
    "leftShoulder": "clavicle_l", "leftUpperArm": "upperarm_l",
    "leftLowerArm": "lowerarm_l", "leftHand": "hand_l",
    "rightShoulder": "clavicle_r", "rightUpperArm": "upperarm_r",
    "rightLowerArm": "lowerarm_r", "rightHand": "hand_r",
    "leftUpperLeg": "thigh_l", "leftLowerLeg": "calf_l",
    "leftFoot": "foot_l", "leftToes": "ball_l",
    "rightUpperLeg": "thigh_r", "rightLowerLeg": "calf_r",
    "rightFoot": "foot_r", "rightToes": "ball_r",
    # 指: VRM0の親指は Proximal/Intermediate/Distal
    "leftThumbProximal": "thumb_01_l", "leftThumbIntermediate": "thumb_02_l",
    "leftThumbDistal": "thumb_03_l",
    "rightThumbProximal": "thumb_01_r", "rightThumbIntermediate": "thumb_02_r",
    "rightThumbDistal": "thumb_03_r",
}
for _f_vrm, _f_pal in (("Index", "index"), ("Middle", "middle"),
                       ("Ring", "ring"), ("Little", "pinky")):
    for _s_vrm, _s_pal in (("Proximal", "01"), ("Intermediate", "02"),
                           ("Distal", "03")):
        for _side, _sfx in (("left", "l"), ("right", "r")):
            VRM0_TO_PAL[f"{_side}{_f_vrm}{_s_vrm}"] = f"{_f_pal}_{_s_pal}_{_sfx}"


# Unity Humanoid(humanName) → パルボーン。humanoid.json(Unityの
# HumanoidMapExporter.csが書き出す対応表)用。指はスペース区切りの正式名
UNITY_TO_PAL = {
    "Hips": "pelvis", "Spine": "spine_01", "Chest": "spine_02",
    "UpperChest": "spine_03", "Neck": "neck_01", "Head": "head",
    "LeftShoulder": "clavicle_l", "LeftUpperArm": "upperarm_l",
    "LeftLowerArm": "lowerarm_l", "LeftHand": "hand_l",
    "RightShoulder": "clavicle_r", "RightUpperArm": "upperarm_r",
    "RightLowerArm": "lowerarm_r", "RightHand": "hand_r",
    "LeftUpperLeg": "thigh_l", "LeftLowerLeg": "calf_l",
    "LeftFoot": "foot_l", "LeftToes": "ball_l",
    "RightUpperLeg": "thigh_r", "RightLowerLeg": "calf_r",
    "RightFoot": "foot_r", "RightToes": "ball_r",
}
for _f_u, _f_pal in (("Thumb", "thumb"), ("Index", "index"),
                     ("Middle", "middle"), ("Ring", "ring"),
                     ("Little", "pinky")):
    for _s_u, _s_pal in (("Proximal", "01"), ("Intermediate", "02"),
                         ("Distal", "03")):
        for _side, _sfx in (("Left", "l"), ("Right", "r")):
            UNITY_TO_PAL[f"{_side} {_f_u} {_s_u}"] = f"{_f_pal}_{_s_pal}_{_sfx}"


def _humanize_unity_bone(name):
    """Unity HumanBone名をConfigure Avatarパネルの表示名に近い形へ整形する。
    'LeftFoot' -> 'Left Foot' のようにキャメルケースへ空白を挿入する。
    指のフル名(既にスペース区切り、例 'Left Thumb Proximal')はそのまま返す
    (dev#233: エラーメッセージで内部pal_bone名でなくUnity側の人間可読名を出すため)"""
    if " " in name:
        return name
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


# パルボーン → Unity Humanoid人間可読名(逆引き)。UNITY_TO_PALはUnity名→pal名の
# 全単射なので素直に反転できる。die()メッセージで内部名でなくUnityのRigタブ/
# Configure Avatar上の表示名を出すために使う(dev#233)
PAL_TO_UNITY_HUMAN = {
    _pal: _humanize_unity_bone(_unity) for _unity, _pal in UNITY_TO_PAL.items()
}

# パルボーン → humanoid.jsonの生キー(例: "Hips", "Head"。逆引き、全単射)。
# 診断メッセージでhumanoid.jsonの実際の値(human.get(key))を引くために使う
# (dev#456)。PAL_TO_UNITY_HUMANは表示用に整形済みなのでキー引きには使えない。
PAL_TO_UNITY_RAW = {_pal: _unity for _unity, _pal in UNITY_TO_PAL.items()}

# step01_import_vrm.py::main()の必須ボーンチェックと同一の11件(dev#1260)。
# 従来はこの列挙がstep01側だけのローカル定数で、humanoid_map_from_json()
# 内部の充足チェックは"pelvis"/"head"の2件しか見ていなかった(dev#456)。
# 実報告CN23H3S5(Left Upper Leg)/R5PEK47D(Left Upper Arm)はいずれも
# pelvis/head以外で欠けており、step01側の情報の乏しいdie()
# (missing_humanoid_bone_message、命名違い/衝突の区別が無い)を踏んでいた。
# 単一のソースをここに置き、両ファイルから参照する。
REQUIRED_PAL_BONES = (
    "pelvis", "spine_01", "head", "upperarm_l", "upperarm_r",
    "hand_l", "hand_r", "thigh_l", "thigh_r", "foot_l", "foot_r",
)


def missing_humanoid_bone_message(pal_bone):
    """必須Humanoidボーン未割当のFATAL文言を組み立てる(dev#233)。

    内部pal_bone名(例: foot_l)をそのまま出すと非エンジニアのユーザーは
    Unity側のどこを直せばいいか分からない。Unity Configure Avatar上の
    表示名(例: Left Foot)+具体的な対処手順に変換して返す。
    pal_bone が逆引きテーブルに無い(想定外)場合は内部名のままフォールバック
    する(黙って情報を落とすより、原文言のまま出すほうが安全)。
    """
    human = PAL_TO_UNITY_HUMAN.get(pal_bone, pal_bone)
    return (f"required Humanoid bone is unassigned: {human}. "
            "Open the avatar in Unity, select it, and check the Rig tab > "
            f"Configure Avatar to assign {human}, then re-export.")


def _compat_name(name):
    """Unity FBX ExporterのMaya互換命名と同じ変換(スペース・ドット→_)。
    互換命名で書かれた既存FBXも読めるようにするフォールバック用"""
    return name.replace(" ", "_").replace(".", "_")


def _closest_bone_candidates(target, bone_names, limit=3, cutoff=0.5):
    """bone_names の中から target に近い名前を difflib で拾う(dev#456)。
    命名違い・輸出時のリネームで一致しなかった場合に、ユーザーへの手掛かりとして
    出す候補。見つからなければ空リスト(嘘の候補を出すよりは何も出さない)。"""
    if not target:
        return []
    return difflib.get_close_matches(target, bone_names, n=limit, cutoff=cutoff)


def _dup_hit_for_expected(expected, candidates):
    """dev#1174: candidates(difflibの曖昧一致候補)の中に、expectedと同じ
    ベース名の連番サフィックス違い(strip_dup_suffixによる厳密一致)を持つ
    ものが無いかを調べる。あれば重複armature/衝突の痕跡とみなす
    (_humanoid_json_missing_messageとclassify_missing_bone_reasonの共通処理、
    dev#1260でこの2箇所が同じ判定基準を共有するよう抽出した)。"""
    return any(vp_dup.strip_dup_suffix(c) == vp_dup.strip_dup_suffix(expected)
               for c in candidates)


def _humanoid_json_missing_message(missing_pals, human, bone_names):
    """humanoid.jsonの必須Humanoidボーン(pelvis/head)が解決できないときの
    FATAL文言を組み立てる(dev#456: 実報告 NHBGLP8M)。

    旧文言は「Hips/Head」という汎用テキストを両方まとめて出すだけで、
    ・そもそもUnity側でそのスロットが未割当だったのか
    ・スロットはあるがそのボーン名がFBXに存在しない(命名違い・輸出漏れ)のか
    ・後者なら実際は何という名前のボーンが見つかったか
    が一切残らなかった。ここでは missing_pals(実際に欠けているもののみ)ごとに
    上記を区別して具体名を出す。die()を呼ぶのは引き続き呼び出し側の責務のまま
    (このタスクは通す条件を緩めるのが目的ではない)。

    missing_pals: 欠けているpal_bone名のリスト("pelvis"/"head")
    human: humanoid.jsonの "humanoid" 辞書({Unity生キー: FBXボーン名})
    bone_names: 実際にFBX/アーマチュアに存在するボーン名の一覧
    """
    parts = []
    for pal in missing_pals:
        unity_key = PAL_TO_UNITY_RAW.get(pal, pal)
        human_label = PAL_TO_UNITY_HUMAN.get(pal, pal)
        expected = human.get(unity_key)
        if not expected:
            parts.append(
                f"{human_label} ({unity_key}): not present in humanoid.json "
                f"(the Unity Humanoid rig had no bone assigned to this slot)")
            continue
        candidates = _closest_bone_candidates(expected, bone_names)
        if candidates:
            # dev#1174(実報告P7ARCMQ7): 候補の中にexpectedと同じベース名の
            # 連番サフィックス違い("hips_2"/"Hips.001"等)があれば、単なる
            # 命名違いではなく重複armatureの痕跡である可能性が高い。difflibの
            # 曖昧一致(_closest_bone_candidates)とは別に、こちらは
            # strip_dup_suffixによる厳密一致なので誤検知しにくい
            dup_hit = _dup_hit_for_expected(expected, candidates)
            parts.append(
                f"{human_label} ({unity_key}): humanoid.json points to bone "
                f"'{expected}', which is not in the exported FBX. Similarly "
                f"named bones found instead: {', '.join(candidates)}"
                + (f". {vp_dup.GUIDANCE_TEXT}" if dup_hit else ""))
        else:
            parts.append(
                f"{human_label} ({unity_key}): humanoid.json points to bone "
                f"'{expected}', which is not in the exported FBX "
                f"(no similarly named bone found)")
    return (
        "could not resolve required Humanoid bone(s) from humanoid.json -- "
        + " | ".join(parts)
        + ". Open the avatar in Unity, select it, and check the Rig tab > "
        "Configure Avatar to assign the missing bone(s), then re-export."
    )


def classify_missing_bone_reason(missing_pals, human, bone_names):
    """dev#1260(実報告CN23H3S5/R5PEK47D再検証、オーナー裁定2026-08-09):
    missing_pals全体から、GUI向け##AVATAR_FATAL##マーカーに使う分類コードを
    1つ選ぶ。

    オーナー裁定の2分類に対応する:
      - "collision": アクセサリ骨格等との同名ボーン衝突が疑われる
        (dev#1226の権威ボーン解決+衝突説明の対象)
      - "unassigned": 本当に未割当、または命名違いだが重複の痕跡が無い
        (dev#250の候補提示フローの対象)

    missing_pals中のどれか1件でも衝突の痕跡(_dup_hit_for_expected)が
    あれば"collision"を返す(GUIの状態表示は1行のため、複数理由が同時に
    起きた場合は"collision"を優先する——衝突の方がより具体的な診断であり、
    見落とすと誤ってdev#250的な「候補から選ばせる」誘導をしかねないため)。
    詳細な理由の切り分けは常にログ本文(_humanoid_json_missing_message)側に
    全件分残る。この関数はログ文言を変えない(GUIマーカー選択専用)。
    """
    for pal in missing_pals:
        unity_key = PAL_TO_UNITY_RAW.get(pal, pal)
        expected = human.get(unity_key)
        if not expected:
            continue
        candidates = _closest_bone_candidates(expected, bone_names)
        if candidates and _dup_hit_for_expected(expected, candidates):
            return "collision"
    return "unassigned"


def log_duplicate_bone_warning(tag, pal_map, bone_names, warnings):
    """dev#1174のvp_dup.find_mapped_bone_duplicates(実際にpal_mapで解決済みの
    ボーンの近傍に、連番サフィックス違いの同名ボーンが無いか)を実行し、
    見つかればprint()で即座にログへ出しつつwarningsへも積む。

    dev#1260: die()(core.die()、sys.exit()のみでwarningsリストを一切出力
    しない)がこの直後に必須ボーン未充足で発火する可能性がある呼び出し元
    (humanoid_map_from_json)向けに、print()を直接呼ぶことでdie()経路でも
    この診断がログに残るようにする。成功時はwarnings.appendした内容が
    従来どおりavatar_meta.json/最終WARN一覧にも反映される。

    返り値: dup_hits辞書({パルボーン: [重複ボーン名, ...]}、見つからなければ
    空辞書)。
    """
    dup_hits = vp_dup.find_mapped_bone_duplicates(pal_map, bone_names)
    if dup_hits:
        detail = "; ".join(f"{pal}={pal_map[pal]} vs {dup_hits[pal]}"
                            for pal in sorted(dup_hits))
        msg = (f"duplicate-named bone(s) detected near the mapped Humanoid "
               f"skeleton ({detail}). {vp_dup.GUIDANCE_TEXT}")
        print(f"[{tag}][WARN] {msg}")
        warnings.append(msg)
    return dup_hits


def humanoid_map_from_json(arm, json_path, warnings):
    """Unity輸出のhumanoid.jsonから {パルボーン: 実ボーン名} を作る(FBX入力用)。"""
    import json as _json
    with open(json_path, encoding="utf-8") as f:
        data = _json.load(f)
    human = data.get("humanoid", {})

    def resolve(bone_name):
        if bone_name in arm.data.bones:
            return bone_name
        if _compat_name(bone_name) in arm.data.bones:
            return _compat_name(bone_name)
        return None

    # Unity FBX Exporter産FBXはスケルトンルートがeRootで書かれ、Blenderの
    # インポータがアーマチュアオブジェクトへ変換するためルートボーン(Hips等)が
    # ボーン一覧から消える(2026-07-21、toto統合FBXで実測)。要求名が
    # アーマチュア名と一致する場合は原点にルートボーンを新造して復元する
    hips_name = human.get("Hips")
    if hips_name and resolve(hips_name) is None:
        obj_base = arm.name.split(".")[0]
        if obj_base in (hips_name, _compat_name(hips_name)):
            import bpy
            # 位置はhumanoid.jsonのhips_local(Unity座標m)から。
            # step01の平坦化(ワールド焼き込み+m正規化)後の空間では
            # Unity(x,y,z) → Blender (-x, -z, y) [m]
            hl = data.get("hips_local")
            if hl:
                head = (-hl[0], -hl[2], hl[1])
            else:
                head = (0.0, 0.0, 0.0)
                warnings.append("no hips_local, restoring to origin (old humanoid.json. "
                                "Re-export from Unity if the position is off)")
            bpy.context.view_layer.objects.active = arm
            bpy.ops.object.mode_set(mode="EDIT")
            eb = arm.data.edit_bones.new(hips_name)
            eb.head = head
            eb.tail = (head[0], head[1] + 0.05, head[2])  # +Y恒等姿勢(長さは不問)
            for b in list(arm.data.edit_bones):
                if b.parent is None and b.name != hips_name:
                    b.parent = eb
            bpy.ops.object.mode_set(mode="OBJECT")
            warnings.append(f"skeleton root restored: {hips_name} head={head}"
                            "(the FBX's eRoot had been turned into an armature)")

    pal_map = {}
    for human_name, bone_name in human.items():
        pal = UNITY_TO_PAL.get(human_name)
        if pal is None:
            continue  # 目・顎などは意図的に対象外(祖先統合でheadへ)
        actual = resolve(bone_name)
        if actual is not None:
            pal_map[pal] = actual
        else:
            warnings.append(f"humanoid.json: bone not in FBX: "
                            f"{human_name} -> {bone_name}")

    bone_names = [b.name for b in arm.data.bones]
    # dev#1260(実報告CN23H3S5/R5PEK47D再検証): 重複armature診断
    # (log_duplicate_bone_warning、dev#1174)を必須ボーン充足の判定
    # (die()の可能性がある)より前に実行する。die()はwarningsリストを
    # 一切出力しない(core.die()はsys.exit()するのみ)ため、後続でdie()が
    # 発火してもこの診断結果がログへ残るようにする(旧: pal_mapが完全に
    # 揃った場合にしか呼び出し元step01_import_vrm.py側で走らず、die()経路に
    # 届かなかった)。
    log_duplicate_bone_warning("vp_bl", pal_map, bone_names, warnings)

    # dev#1260: 必須ボーンチェックを従来の"pelvis"/"head"の2件から
    # REQUIRED_PAL_BONES全11件へ拡張する。旧実装はここで生き残ったpal_mapを
    # 呼び出し側(step01_import_vrm.pyのmain())へ返し、そちらの汎用チェック
    # ループが情報の乏しいmissing_humanoid_bone_message()でdie()していた
    # (実報告CN23H3S5="Left Upper Leg"/R5PEK47D="Left Upper Arm"はいずれも
    # pelvis/head以外で、この乏しい経路を踏んでいた)。
    missing = [p for p in REQUIRED_PAL_BONES if p not in pal_map]
    if missing:
        category = classify_missing_bone_reason(missing, human, bone_names)
        # app_py\pipeline_runner.pyのparse_avatar_fatal/translate_avatar_fatal
        # (dev#1261のno_meshマーカーと同型)が拾い、main_window.pyがUI言語へ
        # 翻訳して表示する。内部診断文言(die()の第2引数、英語)自体は問い合わせ
        # デバッグの作法(CLAUDE.md)どおり変更しない。
        print(f"##AVATAR_FATAL## humanoid_bone_{category}")
        die("vp_bl", _humanoid_json_missing_message(missing, human, bone_names))
    return pal_map


def humanoid_to_pal_map(arm):
    """VRMアドオンのHumanoid定義から {パルボーン: 実ボーン名} を作る。
    目・顎は意図的に対象外(非マップ→祖先統合でheadへ吸われる)。
    返り値: (pal_map, spec_version)"""
    ext = arm.data.vrm_addon_extension
    pal_map = {}

    # VRM1
    try:
        hb1 = ext.vrm1.humanoid.human_bones
        for attr, pal in VRM1_TO_PAL.items():
            bp = getattr(hb1, attr, None)
            if bp is None:
                continue
            bone_name = bp.node.bone_name
            if bone_name and bone_name in arm.data.bones:
                pal_map[pal] = bone_name
    except AttributeError:
        pass
    if "pelvis" in pal_map and "head" in pal_map:
        return pal_map, "1.0"

    # VRM0
    pal_map = {}
    vrm0_items = []  # dev#1174: (bone_enum, node_bone_name) の全件。重複割当の検出用
    try:
        for item in ext.vrm0.humanoid.human_bones:
            vrm0_items.append((item.bone, item.node.bone_name))
            pal = VRM0_TO_PAL.get(item.bone)
            if pal is None:
                continue
            bone_name = item.node.bone_name
            if bone_name and bone_name in arm.data.bones:
                pal_map[pal] = bone_name
    except AttributeError:
        pass
    if "pelvis" in pal_map and "head" in pal_map:
        return pal_map, "0.x"

    # dev#1174(実報告VKKLD4HA/35TX8ERY): アドオンが出す
    # `[VRM Add-on:WARNING] Duplicated VRM0 bone: ...` の直後にここでFATALに
    # なるケースがあった。アドオンの警告テキストをパースせず、human_bonesの
    # データそのものから同一HumanBoneNameの重複割当を直接検出し、汎用文言に
    # 反映する(検出できなくても従来どおりの文言でdie()する。誤検知の懸念より
    # 「診断が空振りする」方を安全側とする)
    dup = vp_dup.find_vrm0_duplicate_human_bone_assignment(vrm0_items)
    msg = ("could not read the VRM Humanoid definition (hips/head unassigned). "
           "The VRM file may be corrupt, or in a format the addon does not support")
    if dup:
        dup_desc = ", ".join(f"{k} -> {v}" for k, v in sorted(dup.items()))
        msg += (f". Detected duplicate Humanoid bone assignment(s) in the VRM "
                f"file itself ({dup_desc}). {vp_dup.GUIDANCE_TEXT}")
    die("vp_bl", msg)


def _vrm_op_available():
    try:
        bpy.ops.import_scene.vrm.get_rna_type()
        return True
    except Exception:
        return False


def missing_addon_zip_message(zip_path):
    """third_party\\ 同梱のVRMアドオンzipが見つからない/読めないときのFATAL文言
    (dev#11)。

    旧C#版(app\\DiveToPalworld.cs WriteJob())はこのケースでnull安全でない
    .Replace()呼び出しがNullReferenceExceptionを起こし、ユーザーには意味不明な
    クラッシュにしか見えなかった。py版のjob.json書き出し(pipeline_runner.
    write_job())は既にnull安全化済み(見つからなければ空文字列を書く)だが、
    そのままでは「後段が明確に失敗する」だけで、何が足りず・何が原因で・
    何をすればよいかが利用者に伝わらない。ここでその3点を明示する
    (missing_humanoid_bone_message()と同じ思想: 内部事情でなく利用者が
    次に取れる行動を書く)。"""
    where = zip_path or "third_party\\VRM_Addon_for_Blender-Extension*.zip"
    return (
        f"required bundled file missing: the VRM Add-on for Blender zip "
        f"({where}) was not found or is unreadable. "
        f"Likely cause: the distribution zip was extracted incompletely, "
        f"quarantined/deleted by antivirus software, or the download itself "
        f"is corrupted. "
        f"Next step: re-download the DiveToPalworld distribution and extract "
        f"it again (do not delete or move anything under third_party\\)."
    )


def ensure_vrm_addon(job):
    """VRMアドオンを使える状態にする。

    2026-07-28(dev issue #24 / 公開issue #14): 全Blender起動を--factory-startupに
    したため、ユーザーのuserpref.blendは一切読まれず、アドオンは毎セッション
    「無効」から始まる。ここで毎回enableする(enableはメモリ上の操作のみで
    ディスクのファイルを書き換えないため、並行実行にも安全)。
    以前あった bpy.ops.wm.save_userpref() は廃止した — --factory-startup状態で
    保存すると**ユーザーの実userpref.blendを工場出荷設定で上書き**してしまう
    (ユーザー環境の設定破壊)。絶対に復活させないこと。

    重要: 毎回zipを再インストールすると**アドオンのファイルを毎回書き換える**
    ことになり、並行実行中の別Blenderのインポートを即死させる
    (2026-07-21 flatv3事件)。ファイルが既にディスクにあれば「有効化」だけを
    行い、インストールは初回のみにする。"""
    if _vrm_op_available():
        return
    # 1) 既にディスクにあるextensionを有効化するだけ(ファイル書き換えなし)
    try:
        bpy.ops.preferences.addon_enable(module="bl_ext.user_default.vrm")
        if _vrm_op_available():
            print("[vp_bl] VRM addon enabled for this session (factory-startup, no reinstall)")
            return
    except Exception:
        pass
    # 2) 初回のみ: zipからインストール(enable_on_installでこのセッションでも有効化)
    zip_path = job["paths"].get("vrm_addon_zip")
    if not zip_path or not os.path.exists(zip_path):
        die("vp_bl", missing_addon_zip_message(zip_path))
    bpy.ops.extensions.package_install_files(
        repo="user_default", filepath=zip_path, enable_on_install=True)
    if not _vrm_op_available():
        die("vp_bl", "installed the VRM addon but import_scene.vrm is still not available")
    print("[vp_bl] VRM addon installed+enabled (session only; prefs are never saved)")
