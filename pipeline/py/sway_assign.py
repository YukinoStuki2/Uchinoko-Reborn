# -*- coding: utf-8 -*-
"""sway_assign.py -- 揺れチェーン自動割当エンジン(dev#19 R3中核、dev#1371)。

これまでの sway_cloth_bones 機構(pipeline\\blender\\step02_retarget.py、
dev#1355/dev#1363/dev#1365)は job.json に手書きした単一チェーン(flatapronの
尻尾のみ)を、単一のdonorファミリー(SWAY_DONOR_FAMILIES、既定OldCloth001)へ
比例配分するだけだった。haori(振袖2+袴スカート複数+尻尾+耳)やAlicia(髪2+
スカート10)のような多チェーン検体を通すには、

  ①正規化済み揺れチェーン群(anchor+骨名列。PhysBoneサイドカー
    dev#1356/app_py\\physbone_catalog.py の physbones.json スキーマ、
    および並行WP dev#1370 のVRM spring正規化から供給される想定)
  ②共有骨格(SK_PalHuman)の骨在庫(親子データ。
    work\\rd_19_haori\\sk_palhuman_bones.json / classify_bones.py が
    R3-benchで先行調査した領域分類手法を踏襲)

から、donorチェーンへの自動割当を行うエンジンが要る。本モジュールはその
エンジン本体で、Blender(bpy)に一切依存しない純粋関数群として実装する
(pytest単体で検証可能。実変換・Blender起動は不要)。

## 割当規則(すべてissue #1371 / dev#19の確定裁定)

1. **部位一致**: チェーンのanchorの解剖学的部位(骨盤系/頭系/腕系/胸系/脚系)
   を祖先探索で分類し、同部位のdonorチェーンだけを候補にする(過去の
   「頭固着」失敗の再発防止 — 揺れものが無関係な部位のdonor骨に載ると、
   ゲーム側アニメで頭に張り付いたように見える)。
2. **チビ安全**: donorチェーンの祖先系列がCHIBI_CANDIDATES
   (step02_retarget.py、chibi_fit_armature()が明示的に動かす標準ボーン群)
   を経由するものは候補から除外する(dev#1365の設計規則。chibi_fit補正
   デルタが道連れ伝播すると最大約88cmもズレて破綻した実測がある)。
3. **アンカー1階層**: ソースチェーン先頭(PhysBone搭載ボーン=anchor相当)は
   donorチェーンの親(標準ボーン、例: pelvis)へ畳み、2節目以降(実際に
   揺れる部分)だけをdonorチェーンへ比例配分する。低レベルの比例配分・
   アンカー分離ロジックは step02_retarget.py の sway_cloth_target_indices()/
   sway_cloth_bone_targets()/SWAY_CLOTH_ANCHOR(dev#1355)をそのまま
   **import利用**する(このWPでは step02_retarget.py を一切改変しない
   —— 並行レーンが同ファイルを触りうるため)。
4. **節数優先**: 要求節数(ソースの揺れる節数)に最も近い、できればそれ以上の
   節数を持つdonorチェーンを選ぶ。ちょうどのdonorが無ければ、圧縮比例配分
   (sway_cloth_bone_targetsが自然にサポートするn_source>n_donorのケース)
   で最も長いdonorへ寄せる。
5. **在庫排他**: 1つのdonorチェーンは1つのソースチェーンにのみ割り当てる
   (割当済みチェーンはプールから除去)。
6. **在庫不足の明示**: 候補が尽きたチェーンは「割当不能」として理由付きで
   出力する(無音で捨てない)。
7. **相乗りフォールバック**(donorexp WP、2026-08-11、issue#19、dev#19裁定
   §5-3の③「対応できない揺れものを作らない」): ①専用donor(規則4、節数
   優先)→②節数圧縮(規則4後半、n_source>n_donorの比例配分)を試みても
   専用donorの在庫が尽きた(registered_pool空)チェーンは、③「同じ部位
   (region)で既にこの回で割当済みのチェーンへウェイトを相乗りさせる」
   フォールバックへ回す。「最寄り」は側(L/R、_side_of())の一致を最優先し、
   同点はdonor.chain_root名のソート順で決定的に解決する(_pick_best_donor()
   と同じ決定性の作法)。相乗り先が同じdonorチェーンを共有するため
   在庫排他(規則5)の対象外(新たな在庫消費は発生しない)。同一region内に
   割当済みチェーンが1つも無ければ(=そのregionにdonorが1つも無かった、
   真の在庫ゼロ)相乗りもできず、従来どおり「割当不能」になる
   (Assignment.coride=Trueが相乗り経由の割当の目印、
   build_donor_inventory()/AssignmentResult.reportのcoride項参照)。

## 出力形式

- `job_fragment`: step02の既存キー("sway_cloth_bones")をそのまま使う。
  ただし既存の SWAY_DONOR_FAMILIES は手作業で登録した2ファミリーしか
  持たないのに対し、本エンジンは骨在庫から動的にdonorチェーンを発見する
  ため、既存の "sway_cloth_donor_family" キーには目安として発見した
  ファミリー接頭辞を入れつつ、実際に使う具体ボーン名列は新規キー
  "sway_cloth_donor_chain" で渡す(step02側でこれを消費する配線は
  **別WP(統合WP)の仕事**——本WPはLayers-Affected: noneの純追加)。
- `abp_node`: 並行WP(多ノードABP生成)の入力形式の素案。正式スキーマは
  未確定のため、チェーンごとの root_bone・実ボーン列・解決済み割当を
  含む最小限の辞書に留める。
- `report`: 割当済み/割当不能の一覧(理由つき)。
"""

from __future__ import annotations

import os
import re
import sys
import types
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

import sway_native_rule  # dev#19 native-donor-rule WP: donor選定のn+1規則(同一
# ディレクトリpipeline\py\、bpy非依存の純粋関数のみ)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
BLENDER_DIR = os.path.join(REPO_ROOT, "pipeline", "blender")


# =====================================================================
# step02_retarget.py の純粋関数の読み取り専用importヘルパー
# =====================================================================
#
# step02_retarget.pyはBlenderスクリプト前提でモジュール先頭に
# `import bpy` / `from mathutils import Matrix, Vector` を持つため、
# Blender本体が無い通常のpython/pytest環境では素朴な `import` ができない。
# tests\coverage\test_step02_sway_cloth_mapping_dev1355.py が確立した手法
# (最小のダミーbpy/mathutilsをsys.modulesへ差し込み、末尾の裸のmain()呼び出し
# 行だけを取り除いてexec()する)を、production側のこのモジュールでも
# 同一原理で再利用する。step02_retarget.py自体は一切書き換えない(並行
# レーンが同ファイルを触りうるため、読み取りのみ)。実Blender内で本モジュール
# が使われる場合は本物のbpyが既にsys.modulesにあるので、スタブ注入は
# 完全にスキップされる(既存の`bpy`を上書きしない)。


def _install_bpy_stub_if_absent() -> None:
    if "bpy" not in sys.modules:
        bpy_stub = types.ModuleType("bpy")
        bpy_stub.data = types.SimpleNamespace()
        bpy_stub.context = types.SimpleNamespace()
        bpy_stub.ops = types.SimpleNamespace()
        sys.modules["bpy"] = bpy_stub
    if "mathutils" not in sys.modules:
        class _Dummy:
            def __init__(self, *args, **kwargs):
                pass

            def __getattr__(self, _name):
                return lambda *a, **k: self

            def __matmul__(self, _other):
                return self

            def __add__(self, _other):
                return self

        mathutils_stub = types.ModuleType("mathutils")
        mathutils_stub.Matrix = _Dummy
        mathutils_stub.Vector = _Dummy
        mathutils_stub.Quaternion = _Dummy  # vp_bl.pyがimportする
        sys.modules["mathutils"] = mathutils_stub


@lru_cache(maxsize=1)
def _load_step02_symbols():
    """step02_retarget.pyのトップレベル定義(CHIBI_CANDIDATES /
    sway_cloth_target_indices / sway_cloth_bone_targets / SWAY_CLOTH_ANCHOR)
    を、ファイル自体を書き換えずに読み取り専用で取り出す。

    戻り値: {"CHIBI_CANDIDATES": [...], "sway_cloth_target_indices": fn,
             "sway_cloth_bone_targets": fn, "SWAY_CLOTH_ANCHOR": int}
    """
    _install_bpy_stub_if_absent()
    for p in (BLENDER_DIR, os.path.join(REPO_ROOT, "pipeline", "py")):
        if p not in sys.path:
            sys.path.insert(0, p)
    src_path = os.path.join(BLENDER_DIR, "step02_retarget.py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    lines = src.splitlines()
    if lines[-1].strip() != "main()":
        raise RuntimeError(
            "step02_retarget.py末尾の想定(裸のmain()呼び出し)が変わっている。"
            "sway_assign.pyのstep02関数ローダーが前提にしている構造が崩れた"
            f"(実際の末尾行={lines[-1]!r})。step02_retarget.py側の変更に"
            "合わせてこのローダーを更新すること。")
    src_without_main_call = "\n".join(lines[:-1])
    namespace = {"__name__": "step02_retarget_under_test", "__file__": src_path}
    code = compile(src_without_main_call, src_path, "exec")
    exec(code, namespace)  # noqa: S102 -- 読み取り専用ソースを純関数抽出のためexec

    required = (
        "CHIBI_CANDIDATES", "sway_cloth_target_indices",
        "sway_cloth_bone_targets", "SWAY_CLOTH_ANCHOR",
        # dev#19 R3統合(dev#1375)で追加: 「保護不能な場合のみ除外」規則
        # (下記 build_donor_inventory() docstring参照)が明示ターゲット集合の
        # 全体(CHIBI_CANDIDATES/SPINE_CHAIN/CHIBI_TWIST_BONES)を必要とする。
        "SPINE_CHAIN", "CHIBI_TWIST_BONES",
        # swayfix WP(dev#19、issue#19、2026-08-11)で追加: build_pak_from_avatar.py
        # が「ウェイト無しリーフボーンも、その家系のcloth_chainが使用中なら
        # RefSkeleton拡張の対象に含める」判定にSWAY_DONOR_FAMILIES/
        # resolve_sway_leaf()を再利用する(単一ソース、家系名の重複ハードコード
        # を避けるため)。
        "SWAY_DONOR_FAMILIES", "resolve_sway_leaf",
    )
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(
            f"step02_retarget.pyから期待した定義が見つからない: {missing}")
    return {name: namespace[name] for name in required}


# =====================================================================
# 領域分類(祖先探索。work\rd_19_haori\classify_bones.pyのR3-bench手法を踏襲)
# =====================================================================

# donor側(共有骨格 SK_PalHuman、パル標準命名)の「直近祖先が命中したら
# そこで分類確定」テーブル。classify_bones.py REGION_OF_STANDARD を移植
# (領域の切り方はこのWPの新規モジュールとして自己完結させるため、
# work\ 配下のスクラッチファイルには依存しない=読み取り専用の一次資料
# として参照するに留め、値はここに複製する。将来 common_bones.json 側の
# 標準骨リストが増減した場合は手動同期が必要——既知の限界として明示)。
REGION_OF_STANDARD_DONOR: Dict[str, str] = {
    "root": "Root",
    "pelvis": "Hips/Pelvis",
    "spine_01": "Spine/Chest", "spine_02": "Spine/Chest", "spine_03": "Spine/Chest",
    "neck_01": "Head/Neck", "head": "Head/Neck",
    "eyes_l": "Head/Neck", "eyes_r": "Head/Neck",
    "clavicle_l": "Arm.L", "upperarm_l": "Arm.L", "lowerarm_l": "Arm.L", "hand_l": "Arm.L",
    "upperarm_twist_01_l": "Arm.L", "lowerarm_twist_01_l": "Arm.L", "weapon_l": "Arm.L",
    "clavicle_r": "Arm.R", "upperarm_r": "Arm.R", "lowerarm_r": "Arm.R", "hand_r": "Arm.R",
    "upperarm_twist_01_r": "Arm.R", "lowerarm_twist_01_r": "Arm.R", "weapon_r": "Arm.R",
    "thigh_l": "Leg.L", "calf_l": "Leg.L", "foot_l": "Leg.L", "ball_l": "Leg.L",
    "thigh_twist_01_l": "Leg.L", "calf_twist_01_l": "Leg.L",
    "thigh_r": "Leg.R", "calf_r": "Leg.R", "foot_r": "Leg.R", "ball_r": "Leg.R",
    "thigh_twist_01_r": "Leg.R", "calf_twist_01_r": "Leg.R",
}
for _finger in ("index", "middle", "ring", "pinky", "thumb"):
    for _i in (1, 2, 3):
        REGION_OF_STANDARD_DONOR[f"{_finger}_0{_i}_l"] = "Arm.L"
        REGION_OF_STANDARD_DONOR[f"{_finger}_0{_i}_r"] = "Arm.R"

# source側(アバター/VRChat Humanoid命名)の正規化名テーブル。名前は
# lower化+英数字以外を除去した後に照合する(_normalize_name参照)ので、
# "Hips" "hips" "hip_bone" のような表記ゆれをある程度吸収できる。
HUMANOID_REGION_ALIASES: Dict[str, str] = {
    "hips": "Hips/Pelvis", "pelvis": "Hips/Pelvis", "hip": "Hips/Pelvis",
    "spine": "Spine/Chest", "chest": "Spine/Chest", "upperchest": "Spine/Chest",
    "neck": "Head/Neck", "head": "Head/Neck",
    "leftshoulder": "Arm.L", "leftupperarm": "Arm.L", "leftlowerarm": "Arm.L",
    "leftforearm": "Arm.L", "lefthand": "Arm.L", "leftarm": "Arm.L",
    "rightshoulder": "Arm.R", "rightupperarm": "Arm.R", "rightlowerarm": "Arm.R",
    "rightforearm": "Arm.R", "righthand": "Arm.R", "rightarm": "Arm.R",
    "leftupperleg": "Leg.L", "leftthigh": "Leg.L", "leftlowerleg": "Leg.L",
    "leftcalf": "Leg.L", "leftshin": "Leg.L", "leftfoot": "Leg.L", "leftleg": "Leg.L",
    "rightupperleg": "Leg.R", "rightthigh": "Leg.R", "rightlowerleg": "Leg.R",
    "rightcalf": "Leg.R", "rightshin": "Leg.R", "rightfoot": "Leg.R", "rightleg": "Leg.R",
}

UNCLASSIFIED = "Unclassified"


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def classify_source_region(
    anchor: str, source_parent_of: Dict[str, Optional[str]],
) -> Optional[str]:
    """ソース(アバター)側anchorの解剖学的部位を、anchor自身から祖先を
    たどりながら HUMANOID_REGION_ALIASES に命中するまで分類する(祖先探索、
    issue #1371 規則1)。命中しなければ None(=分類不能。呼び出し側は
    「割当不能」として明示する)。

    source_parent_of: {bone_name: parent_bone_name_or_None} の部分マップで
    よい(anchorからの祖先経路さえ辿れれば十分。全身分を持つ必要は無い)。
    循環参照は安全側(検出したら打ち切り)で扱う。
    """
    cur: Optional[str] = anchor
    seen = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        hit = HUMANOID_REGION_ALIASES.get(_normalize_name(cur))
        if hit is not None:
            return hit
        cur = source_parent_of.get(cur)
    return None


# =====================================================================
# donor在庫の動的発見(共有骨格の親子データから)
# =====================================================================

@dataclass(frozen=True)
class DonorCandidate:
    """共有骨格(SK_PalHuman)から動的発見された、1本のdonorチェーン候補。"""

    chain_root: str          # チェーンの根(標準ボーンの直接の子)
    anchor_bone: str         # chain_rootの親(常に標準ボーン。例: "pelvis")
    region: str              # REGION_OF_STANDARD_DONORでのanchor_boneの分類
    chain: Tuple[str, ...]   # chain_root(先頭)からleafまでの実ボーン名列
    chibi_unsafe: bool       # 保護不能(dev#1375改訂: donorチェーン自身の名前が
                              # 明示ターゲット集合と衝突する場合のみTrue。
                              # build_donor_inventory()docstring参照)
    family_prefix: str       # chain_root名から連番/L・R接尾辞/性別接頭辞を除いた家系名
    registered: bool = True  # dev#19実データ欠陥修正(issue #1379): 呼び出し側が
                              # registered_familiesを指定した場合のみ意味を持つ
                              # (build_donor_inventory()docstring参照)。未指定時は
                              # 常にTrue(=フィルタなし、既存呼び出し元は無退行)。


def _family_prefix(
    name: str, registered_families: Optional[Sequence[str]] = None,
) -> str:
    """"OldCloth001_04" -> "OldCloth001"、"NPC_Head_ear_l_01" ->
    "NPC_Head_ear" のように、末尾の連番・左右接尾辞を除いた家系名を作る。
    work\\rd_19_haori\\classify_bones.py family_prefix() と同じ考え方。

    dev#19実データ欠陥修正(issue #1379、欠陥1): 先頭の性別接頭辞(F_/M_、
    filter_bone_pairs_by_gender()と同じ命名規約)も除去する。実データ
    (work\\rd_19_haori\\sk_palhuman_bones.json)では骨盤系donorの大半が
    gendered("F_OldCloth001_04"等)であり、これを剥がさないと
    step02_retarget.SWAY_DONOR_FAMILIESの登録キー("OldCloth001"、接頭辞なし)
    と永久に一致しない(F_OldCloth001_04 -> 旧"F_OldCloth001" -> 不一致で
    resolve段が全skipになっていた実測、issue #1379 RESULT.md §1参照)。

    dev#19実データ欠陥修正2(issue #1426): 上記の末尾連番除去だけの推測
    パースは、「家系名+中間語+連番」命名(例: "F_Kigurumi001_tail_01"、
    "F_Ancient001_waistClothA_01")を還元できない
    ("Kigurumi001_tail"/"Ancient001_waistClothA"のように中間語が残り、
    SWAY_DONOR_FAMILIESの登録キー"Kigurumi001"/"Ancient001"と永久に不一致
    ——自動割当エンジン経由でKigurumi001/Ancient001が「未登録」扱いになり
    候補プールから漏れる実害があった。work\\rd_19_smokefinal2\\FINAL_REPORT.md
    で実証: 6帯尻尾がKigurumi001(n+1規則の正解、native8)ではなく
    OldCloth001(native4、圧縮cap後3本)へ誤って割り当てられた)。

    registered_families(通常はSWAY_DONOR_FAMILIESのキー集合。
    build_donor_inventory()の同名引数をそのまま中継)を指定すると、まず
    性別接頭辞(F_/M_)を剥がした名前が、いずれかの登録家系名で始まるか
    (前方一致。名前がその家系名と完全一致するか、家系名の直後が"_"で
    続くか)を調べる——推測パースではなく、登録テーブル駆動の照合。
    複数の登録家系名が同時にprefixになりうる場合(将来家系が増えた場合の
    保険)は、より長い(=より具体的な)家系名を優先する。一致すれば、
    その登録家系名をそのまま返す(中間語の有無に関わらず正しく還元できる
    ——"F_Kigurumi001_tail_01"は"Kigurumi001"で始まるので"Kigurumi001"を
    返す)。一致しなければ、従来どおりの推測パース(末尾の連番・左右接尾辞・
    性別接頭辞除去)へフォールバックする(未登録の家系は登録テーブルに
    無い以上、推測に頼るしかない——負の対照: 未知の骨名は従来どおり
    "未登録"のまま)。registered_families省略時(None)は常に推測パースのみ
    (既存呼び出し元は無退行、単体テストの直接呼び出し互換)。"""
    if registered_families:
        degendered = re.sub(r"^[FM]_", "", name)
        best: Optional[str] = None
        for fam in registered_families:
            if degendered == fam or degendered.startswith(fam + "_"):
                if best is None or len(fam) > len(best):
                    best = fam
        if best is not None:
            return best
    base = re.sub(r"(?:_\d+)?(?:_[lr])?(?:_end)?$", "", name)
    base = re.sub(r"_[lr]$", "", base)
    base = re.sub(r"^[FM]_", "", base)
    return base or name


def _build_maps(
    bone_pairs: Sequence[Tuple[str, Optional[str]]],
) -> Tuple[Dict[str, Optional[str]], Dict[str, List[str]]]:
    parent_of: Dict[str, Optional[str]] = {}
    children: Dict[str, List[str]] = {}
    for name, parent in bone_pairs:
        parent_of[name] = parent
        if parent is not None:
            children.setdefault(parent, []).append(name)
    return parent_of, children


def _longest_chain(root: str, children: Dict[str, List[str]]) -> List[str]:
    """rootから子孫を辿れる最長経路(ノード名列、root自身を含む)を返す。
    分岐がある場合は最長の枝を選び、同点は名前のソート順で決定的に選ぶ
    (real dataの最大深さは実測10前後のため再帰で十分安全)。"""
    best = [root]
    for child in sorted(children.get(root, [])):
        candidate = [root] + _longest_chain(child, children)
        if len(candidate) > len(best):
            best = candidate
    return best


def build_donor_inventory(
    bone_pairs: Sequence[Tuple[str, Optional[str]]],
    chibi_candidates: Optional[Sequence[str]] = None,
    registered_families: Optional[Sequence[str]] = None,
) -> List[DonorCandidate]:
    """共有骨格の生の親子データ(name, parent_name_or_None)から、donor
    チェーン候補を動的発見する。

    「チェーンの根」は work\\rd_19_haori\\classify_bones.py と同じ定義
    (=標準ボーンの直接の子である非標準ボーン)。各根から
    _longest_chain() で実ボーン名列を確定し、根の親(=常に標準ボーン)を
    anchor_bone・その分類を region として持たせる。

    ## chibi_unsafe規則(dev#19 R3統合、dev#1375で改訂)

    dev#1371導入時点の旧規則は「anchor_bone(donorチェーンの親=標準ボーン)が
    CHIBI_CANDIDATESに含まれるか」で判定していた。これは`head`直下の耳
    donor候補(HeadEquip062_ear_01_l/r等)を含む頭系donorのほぼ全滅を招き
    (work\\rd_19_ears\\PROPOSAL.md §5.2で判明)、耳を通せなかった。

    dev#19スレッド2026-08-11の前提(オーナー/指揮者裁定): 「dev#1365の
    exclude_descendants保護が適用されるdonor(=sway_assign経由でSWAY割当
    されたdonorは全て)はチビ道連れから守られる」。この前提の下では、
    donorチェーン自身(chain_root〜leaf)は`chibi_fit_armature()`の
    4)「その他の子孫」パス(道連れ移動)から常に除外される
    (step02_retarget.py main()の`sway_donor_bone_names`集約→
    `exclude_descendants`引数、dev#1365)。したがってanchor_boneが
    CHIBI_CANDIDATESに含まれるかどうかは道連れ保護の有無に無関係であり、
    旧規則は過剰に保守的だった。

    新規則:「保護不能な場合のみ除外」——exclude_descendants保護は
    donorチェーン自身の名前を除外集合に加えることで働くが、もしdonor
    チェーンの構成ボーンが明示ターゲット集合
    (CHIBI_CANDIDATES ∪ SPINE_CHAIN ∪ CHIBI_TWIST_BONES、
    =chibi_fit_armature()の1)3)で明示的に位置決めされるボーン群)自身と
    名前が衝突していたら、そのボーンはexclude_descendantsで弾く4)に
    到達する前に1)/3)で強制的に位置決めされてしまうため、保護が構造的に
    利かない(=保護不能)。この場合のみchibi_unsafe=Trueとする。
    実データのdonorファミリー命名(OldCloth001_04、HeadEquip062_ear_01_l等)
    はいずれも標準ボーン名と衝突しないため、通常は全donor候補が
    chibi_safe(=chibi_unsafe False)になる——これが耳donorを通す変更の
    正体。負の対照は名前衝突を人為的に作ったフィクスチャで裏取りする
    (tests\\coverage\\test_sway_assign_dev1371.py参照)。

    chibi_candidates省略時は step02_retarget.CHIBI_CANDIDATES/SPINE_CHAIN/
    CHIBI_TWIST_BONES の和集合をimport利用する(既定=新規則)。明示的に
    上書きしたい場合(単体テストでの規則on/off)は、判定に使う明示
    ターゲット集合そのものをこの引数へ渡す(空リストなら常にchibi_safe、
    旧CHIBI_CANDIDATESのみを渡せば旧規則相当の挙動を再現できる)。

    registered_families(dev#19実データ欠陥修正、issue #1379、欠陥2):
    「登録済み家系」名(step02_retarget.SWAY_DONOR_FAMILIESのキー集合が
    典型)の集合。指定時、各候補のfamily_prefix(dev#19欠陥1修正済みの
    性別接頭辞除去版)がこの集合に含まれるかどうかを
    DonorCandidate.registered へ記録する(除外はしない——候補一覧には
    残す。実際の絞り込みは assign_sway_chains() 側が行う。ここでは
    「在庫として存在するが未登録」の可視化(欠陥3関連)に必要な情報を
    落とさないため、フラグ付けに留める)。省略時(None)は全候補
    registered=True(=フィルタなし、既存呼び出し元は無退行)。
    """
    if chibi_candidates is None:
        syms = _load_step02_symbols()
        chibi_candidates = (
            list(syms["CHIBI_CANDIDATES"])
            + list(syms["SPINE_CHAIN"])
            + list(syms["CHIBI_TWIST_BONES"].keys())
        )
    chibi_set = set(chibi_candidates)
    registered_set = set(registered_families) if registered_families is not None else None

    parent_of, children = _build_maps(bone_pairs)
    standard = set(REGION_OF_STANDARD_DONOR)

    candidates: List[DonorCandidate] = []
    for name, parent in bone_pairs:
        if name in standard:
            continue
        if parent is None or parent not in standard:
            continue
        # name = chain root (標準ボーンparentの直接の子、非標準)
        chain = _longest_chain(name, children)
        region = REGION_OF_STANDARD_DONOR.get(parent, UNCLASSIFIED)
        # 保護不能判定: donorチェーン自身(chain_root〜leaf)の名前が明示
        # ターゲット集合と衝突するか(規則の詳細はdocstring参照)。anchor_bone
        # (=chainの親、常に標準ボーン)自体は判定対象に含めない——旧規則からの
        # 意図的な変更点そのもの。
        protection_impossible = any(b in chibi_set for b in chain)
        family_prefix = _family_prefix(name, registered_families)
        registered = True if registered_set is None else family_prefix in registered_set
        candidates.append(DonorCandidate(
            chain_root=name,
            anchor_bone=parent,
            region=region,
            chain=tuple(chain),
            chibi_unsafe=protection_impossible,
            family_prefix=family_prefix,
            registered=registered,
        ))
    return candidates


# =====================================================================
# ソースチェーン
# =====================================================================

@dataclass(frozen=True)
class SourceChain:
    """1本の揺れチェーン(PhysBoneサイドカー physbones.json の1エントリの
    chains[i]に対応)。

    id: レポート用の識別子(呼び出し側が任意に付与。例: "haori:sode_l:0")
    anchor: PhysBone搭載ボーン(rootTransform)相当。anchor自身は揺れない。
    chain: anchorの子孫のみ(anchor自身の名前を含まない。physbones.jsonの
           "chains[i]"と同一の意味論、dev#1356)。
    """

    id: str
    anchor: str
    chain: Tuple[str, ...]

    @property
    def bones(self) -> Tuple[str, ...]:
        """sway_cloth_bone_targets()が期待する意味論(index0=アンカー相当)
        に合わせて、anchorを先頭に足した完全なボーン列を返す。"""
        return (self.anchor,) + tuple(self.chain)


# =====================================================================
# 割当結果
# =====================================================================

@dataclass(frozen=True)
class Assignment:
    source: SourceChain
    donor: DonorCandidate
    region: str
    bone_targets: Tuple[str, ...]  # len == len(source.bones)。解決済み実ボーン名
    job_fragment: Dict
    abp_node: Dict
    # donorexp WP(2026-08-11、issue#19、規則7): このAssignmentが専用donor
    # (規則4)ではなく相乗りフォールバック(規則7)経由で作られたか。Trueの
    # 場合、donorは同一region内で別の(coride=Falseの)Assignmentが既に
    # 使っているものと同一チェーンを共有する(新規在庫消費なし)。既定False
    # (=既存呼び出し元・既存テストは無退行)。
    coride: bool = False


@dataclass(frozen=True)
class Unassigned:
    source: SourceChain
    reason: str


@dataclass
class AssignmentResult:
    assigned: List[Assignment] = field(default_factory=list)
    unassigned: List[Unassigned] = field(default_factory=list)

    @property
    def report(self) -> Dict:
        return {
            "assigned": [
                {
                    "id": a.source.id,
                    "region": a.region,
                    "anchor": a.source.anchor,
                    "donor_chain_root": a.donor.chain_root,
                    "donor_family_prefix": a.donor.family_prefix,
                    "requested_nodes": len(a.source.chain),
                    "donor_nodes": len(a.donor.chain),
                    "coride": a.coride,
                }
                for a in self.assigned
            ],
            "unassigned": [
                {"id": u.source.id, "anchor": u.source.anchor, "reason": u.reason}
                for u in self.unassigned
            ],
        }


def _side_of(name: str) -> Optional[str]:
    """名前からL/R側を推定する(dev#1375追加、左右donor選択の同点判定に
    使う補助関数)。アンダースコア・ドット・空白区切りのトークンに完全一致
    する "l"/"r"/"left"/"right"(大小無視)を探す -- "Head_R.001"のような
    中間トークン、"HeadEquip062_ear_01_r"のような末尾トークン、どちらも
    拾える(単純なsuffix一致だと"Head_R.001"の".001"末尾に阻まれて見逃す)。
    判定できなければNone(側の概念が無い名前、例: "pelvis"/"Tail Root")。
    """
    tokens = re.split(r"[^a-zA-Z0-9]+", name.lower())
    if any(t in ("r", "right") for t in tokens):
        return "R"
    if any(t in ("l", "left") for t in tokens):
        return "L"
    return None


def _pick_best_donor(
    pool: Sequence[DonorCandidate], required_nodes: int,
    preferred_side: Optional[str] = None,
) -> Optional[DonorCandidate]:
    """規則4(節数優先): 要求節数以上で最も近い(最小)donorを優先。
    候補が全て不足なら、最も長い(圧縮量が最小の)donorを選ぶ。

    preferred_side(dev#1375追加、L/R取り違え防止): ソース側anchorの側
    (_side_of()で判定できた場合のみ、Noneなら従来どおり無視)と一致する
    donor_root名を持つ候補が1件以上あれば、その部分集合だけを対象に絞る。
    耳のように同一region(Head/Neck)に左右両方のsway_assign実行対象が
    同時に存在する場合、旧規則(chain_root名のソート順のみ)だと"_l"側の
    donorが常に先取りされ、右耳が左耳donorへ誤って割り当たる事故が起きる
    (実測: flatapron耳フィクスチャで発覚、dev#1375)。preferred_sideが
    Noneまたは一致候補が無い場合は従来どおり全候補から選ぶ(既存の
    dev#1371フィクスチャ(側の概念が無いanchor名)は無退行)。
    同点は最終的にchain_root名のソート順で決定的に解決する(従来どおり)。
    """
    if not pool:
        return None
    sufficient = [c for c in pool if len(c.chain) >= required_nodes]
    base_pool = sufficient if sufficient else pool
    if preferred_side is not None:
        side_matched = [c for c in base_pool if _side_of(c.chain_root) == preferred_side]
        if side_matched:
            base_pool = side_matched
    key_fn = lambda c: (len(c.chain), c.chain_root)  # noqa: E731
    return min(base_pool, key=key_fn) if sufficient else max(base_pool, key=key_fn)


def _pick_coride_target(
    assigned_so_far: Sequence[Assignment], region: str,
    preferred_side: Optional[str] = None,
) -> Optional[Assignment]:
    """規則7(相乗りフォールバック、donorexp WP、issue#19): 専用donorの在庫が
    尽きたチェーンを相乗りさせる「最寄り」の既割当チェーンを選ぶ。

    候補は同一region(部位)の既割当(result.assigned、この回の処理順で
    これまでに確定した分)に限る——相乗り先も専用donorと同じく部位一致を
    崩さない。preferred_side(_side_of()でソース側anchorから判定できた
    場合のみ)と一致するdonor.chain_rootを持つ既割当があればそちらを優先
    する(_pick_best_donor()と同じL/R取り違え防止の作法)。同点は
    donor.chain_root名→source.id の順で決定的に解決する。

    同一region内に既割当が1つも無ければ(=そのregionにdonorが1つも無かった、
    真の在庫ゼロ)相乗りする先が存在しないためNoneを返す(呼び出し側は
    従来どおり「割当不能」として扱う)。
    """
    candidates = [a for a in assigned_so_far if a.region == region]
    if not candidates:
        return None
    if preferred_side is not None:
        side_matched = [
            a for a in candidates if _side_of(a.donor.chain_root) == preferred_side]
        if side_matched:
            candidates = side_matched
    return min(candidates, key=lambda a: (a.donor.chain_root, a.source.id))


def assign_sway_chains(
    source_chains: Sequence[SourceChain],
    donor_inventory: Sequence[DonorCandidate],
    source_parent_of: Dict[str, Optional[str]],
    *,
    symbols: Optional[Dict] = None,
) -> AssignmentResult:
    """揺れチェーン自動割当エンジン本体(issue #1371)。

    source_chainsを1本ずつ処理し、①anchorの部位分類(規則1)→②同部位の
    在庫プールから節数優先(規則4)でdonorを選ぶ→③アンカー1階層+比例配分
    (規則3、sway_cloth_bone_targets再利用)→④在庫から除去(規則5)、を行う。
    donor_inventoryはあらかじめ build_donor_inventory() でチビ安全フィルタ
    (規則2)まで済ませたものを渡す想定(本関数はchibi_unsafeなdonorも
    念のため再度除外するため、フィルタ漏れがあっても安全側に倒れる)。

    ソースが空リストの場合は空のAssignmentResultを返す(規則6の裏側=
    割当ゼロは既定動作に一切影響しない、受入条件(d))。

    symbols: dev#19 R3統合(dev#1375)で追加。省略時は従来どおり
    `_load_step02_symbols()`(step02_retarget.pyソースの読み取り専用
    exec抽出)を使う。**step02_retarget.py自身の内部から呼ぶ場合**は、
    実行中のモジュールが既にこれらの関数を直接持っているため、
    `{"sway_cloth_bone_targets": sway_cloth_bone_targets,
    "SWAY_CLOTH_ANCHOR": SWAY_CLOTH_ANCHOR}` を明示的に渡すことで、
    自分自身のソースを再度execする無駄な自己参照(_load_step02_symbols()の
    exec抽出は「外部からBlender無しでstep02の純粋関数を使う」ための迂回路
    であり、step02自身の中から使うときは不要)を避けられる。
    """
    syms = symbols if symbols is not None else _load_step02_symbols()
    sway_cloth_bone_targets = syms["sway_cloth_bone_targets"]
    SWAY_CLOTH_ANCHOR = syms["SWAY_CLOTH_ANCHOR"]
    # dev#19 native-donor-rule WP(issue #19、2026-08-14夜): SWAY_DONOR_FAMILIES
    # は _load_step02_symbols() が既に読み取り専用で取り出し済み(swayfix WP、
    # モジュールdocstring参照)。native_sim_count(実シミュレーション対象骨数)
    # をfamily_prefix経由で引けるようにする。
    sway_donor_families = syms.get("SWAY_DONOR_FAMILIES") or {}

    def _native_sim_count_of(candidate: DonorCandidate) -> Optional[int]:
        fam = sway_donor_families.get(candidate.family_prefix)
        return fam.get("native_sim_count") if fam else None

    def _build_assignment(source: SourceChain, donor: DonorCandidate, region: str,
                           coride: bool) -> Assignment:
        """規則3(アンカー1階層+比例配分)を適用し、Assignmentを組み立てる
        共通ロジック(専用donor経路・相乗り経路の両方が使う)。相乗り経路
        (coride=True)でも、donorが同じでもsourceが異なれば比例配分
        (sway_cloth_bone_targets)は当然source側の節数(n_source)基準で
        独立に計算される——「同じdonorチェーンへ複数のsourceがウェイトを
        乗せる」がまさに「相乗り」の実体(group_targetsはsourceボーン名を
        キーにした辞書のため、複数sourceが同じdonorボーン名を指しても
        step02側で衝突しない、pipeline\\blender\\step02_retarget.py
        main()のgroup_targets[av]=...代入部を参照)。"""
        n_source = len(source.bones)
        n_donor = len(donor.chain)
        target_indices = sway_cloth_bone_targets(n_source, n_donor)
        bone_targets = tuple(
            donor.anchor_bone if idx == SWAY_CLOTH_ANCHOR else donor.chain[idx]
            for idx in target_indices
        )

        # dev#19 native-donor-rule WP(issue #19): job_fragment["sway_cloth_
        # donor_chain"]は、step02側のresolve_sway_chain_entries()
        # explicit_chain分岐でそのまま実ウェイト転写chainとして使われる
        # (sway_cloth_weight_targets_direct()、1:1直接割当)。donor.chainの
        # 節数が実シミュレーション骨数(native_sim_count)を満たさない場合は
        # native_sim_count-1本までcapする(sway_native_rule.pyモジュール
        # docstring「n_donor capの副作用範囲」参照: sway_cloth_bone_targets
        # (このすぐ上のbone_targets計算、ABP authoring用)は比例配分のため
        # capするとcap無しの結果を変えてしまう——だからbone_targets計算自体は
        # 無変更のまま、weight転写専用のsway_cloth_donor_chainだけをcapする)。
        # required_nodes(=len(source.chain)、アンカー自身を除いた転写帯数)が
        # qualifies()を満たす通常経路ではcap後も全長不変(no-op)。
        donor_native = _native_sim_count_of(donor)
        if sway_native_rule.qualifies(donor_native, len(source.chain)):
            weighted_donor_chain = list(donor.chain)
        else:
            weighted_donor_chain = sway_native_rule.cap_chain(donor.chain, donor_native)

        job_fragment = {
            "sway_cloth_bones": list(source.bones),
            "sway_cloth_donor_family": donor.family_prefix,
            "sway_cloth_donor_chain": weighted_donor_chain,
            # dev#1375追加: 旧来のsway_cloth_bones機構はアンカーを常に
            # "pelvis"固定していたが(骨盤系donorしか無かったため)、自動
            # 割当エンジンは頭系(head)・腕系(weapon_l/r)等、区々の
            # anchor_boneを発見しうる。step02側の多チェーン処理
            # (job["sway_chains"])はこのキーを読んでチェーンごとに
            # 正しいアンカーへ畳む(未指定時は後方互換で"pelvis"既定)。
            "sway_cloth_donor_anchor": donor.anchor_bone,
        }
        abp_node = {
            "source_id": source.id,
            "region": region,
            # dev#1375修正: 素案時点では"root_bone"にdonor.anchor_bone
            # (骨盤/頭等の標準ボーン、揺れない側)を入れていたが、
            # work\rd_19_multinode\RESULT.md §2確定形式のKawaiiPhysicsノード
            # "root_bone"は実際に揺れる最初の節(=donor.chain_root、
            # 例: "F_OldCloth001_04")を指す(RESULT.md §3の検証仕様表と
            # 一致させた)。WP指示書「abp_node出力は…本WPで正式スキーマに
            # 合わせて調整してよい」に基づく修正(sway_assign.py自体が
            # dev#1371時点で未消費のため、この修正に伴う退行は無い)。
            "root_bone": donor.chain_root,
            "anchor_bone": donor.anchor_bone,
            "donor_chain_root": donor.chain_root,
            "donor_chain": list(donor.chain),
            "source_bones": list(source.bones),
            "bone_targets": list(bone_targets),
        }
        return Assignment(
            source=source, donor=donor, region=region,
            bone_targets=bone_targets, job_fragment=job_fragment,
            abp_node=abp_node, coride=coride,
        )

    # 規則2の再確認(呼び出し側のフィルタ漏れに対する安全側フォールバック)
    pool: List[DonorCandidate] = [c for c in donor_inventory if not c.chibi_unsafe]

    result = AssignmentResult()
    for source in source_chains:
        region = classify_source_region(source.anchor, source_parent_of)
        if region is None:
            result.unassigned.append(Unassigned(
                source=source,
                reason=f"anchor '{source.anchor}' の解剖学的部位を分類できなかった"
                       "(HUMANOID_REGION_ALIASES未収載)"))
            continue

        preferred_side = _side_of(source.anchor)
        region_pool = [c for c in pool if c.region == region]

        # dev#19実データ欠陥修正(issue #1379、欠陥2): 節数優先(規則4)は
        # 「登録済み家系」の中だけで働かせる。registered_familiesを指定せずに
        # build_donor_inventory()した場合は全候補がregistered=Trueのため、
        # この絞り込みは無退行(region_pool == registered_poolのまま)。
        registered_pool = [c for c in region_pool if c.registered]

        if not registered_pool:
            # 規則7(相乗りフォールバック、donorexp WP): 専用donorの在庫が
            # 尽きた(そもそも region_pool が空=真の在庫ゼロ、または
            # region_pool はあるが登録済み家系が無い、のいずれか)場合、
            # まず同一regionで既に割当済みのチェーンへの相乗りを試みる。
            coride_target = _pick_coride_target(result.assigned, region, preferred_side)
            if coride_target is not None:
                result.assigned.append(_build_assignment(
                    source, coride_target.donor, region, coride=True))
                continue
            if not region_pool:
                reason = (f"region '{region}' に利用可能なdonorチェーン在庫が無い"
                          "(部位一致・在庫排他の結果、相乗り先の既割当チェーンも無い)")
            else:
                # 欠陥3関連: 在庫はあるが登録済み家系が無い場合を、単なる
                # 「在庫が無い」と区別して明示する(無音で丸めない)。
                unregistered_families = sorted({c.family_prefix for c in region_pool})
                reason = (
                    f"region '{region}' の在庫は存在するが、登録済み家系が無い"
                    f"(在庫としては存在するが未登録: {unregistered_families}、"
                    "相乗り先の既割当チェーンも無い)")
            result.unassigned.append(Unassigned(source=source, reason=reason))
            continue

        required_nodes = len(source.chain)
        # dev#19 native-donor-rule WP(issue #19、2026-08-14夜恒久ルール):
        # 「実シミュレーション骨(native_sim_count)でn+1本以上」を満たす候補が
        # あれば、その中だけから選ぶ(節数優先=規則4はqualifyする候補内で
        # 適用)。満たす候補が無ければ従来どおりregistered_pool全体から選ぶ
        # (_build_assignment側のcap_chain()が終端の凍結ボーンへウェイトが
        # 乗らないよう安全側に倒す)。native_sim_count情報を持たない家系
        # (SWAY_DONOR_FAMILIESに未登録、既存呼び出し元テスト等)は常に
        # qualifies()=Falseとなり無条件でこのフィルタの対象外になる——安全側
        # (=既存の無登録家系フィクスチャは無退行、後段のregistered_pool
        # フォールバックへ素通しされる)。
        qualified_pool = [
            c for c in registered_pool
            if sway_native_rule.qualifies(_native_sim_count_of(c), required_nodes)
        ]
        donor_pool = qualified_pool if qualified_pool else registered_pool
        donor = _pick_best_donor(donor_pool, required_nodes, preferred_side)
        assert donor is not None  # registered_poolが非空なら必ず選ばれる

        # 規則5: 在庫排他。選ばれたdonorをプール全体から除去する
        pool = [c for c in pool if c.chain_root != donor.chain_root]

        result.assigned.append(_build_assignment(source, donor, region, coride=False))

    return result


# =====================================================================
# 便利アダプタ
# =====================================================================

def bones_from_indexed(
    records: Sequence[Sequence],
) -> List[Tuple[str, Optional[str]]]:
    """work\\rd_19_haori\\sk_palhuman_bones.json のような、index-based
    ([name, parent_idx], parent_idx==-1がルート)形式の骨リストを、本モジュール
    が扱う (name, parent_name_or_None) のペア列へ変換する。

    実運用のフル骨格データ(4079骨)をこのモジュールへ静的に埋め込むことは
    せず、必要なときにこのアダプタで読み込む設計とした(受入条件のテストは
    軽量な合成フィクスチャで完結させる。解釈はWP完了報告に明記)。
    """
    names = [r[0] for r in records]
    out: List[Tuple[str, Optional[str]]] = []
    for name, parent_idx in records:
        parent_name = names[parent_idx] if isinstance(parent_idx, int) and parent_idx >= 0 else None
        out.append((name, parent_name))
    return out


def source_chains_from_physbone_catalog(entries: Sequence[Dict]) -> List[SourceChain]:
    """app_py\\physbone_catalog.py の catalog_from_sidecar()["physbones"]
    ([{"anchor": str, "chains": [[str,...], ...]}, ...])を SourceChain の
    リストへ変換する。1エントリに複数チェーンがあれば
    "<anchor>#<index>"というidで展開する。"""
    out: List[SourceChain] = []
    for entry in entries:
        anchor = entry["anchor"]
        for i, chain in enumerate(entry.get("chains", [])):
            out.append(SourceChain(
                id=f"{anchor}#{i}", anchor=anchor, chain=tuple(chain)))
    return out


def _prefixed_source_chains(entries: Sequence[Dict], prefix: str) -> List[SourceChain]:
    """source_chains_from_physbone_catalog()と同じ入力形式を、id衝突を
    避けるための接頭辞つきで展開する内部ヘルパー(dev#1375、
    assign_avatar_sway()が複数の搬送元(prefab側physbones.json / VRM側
    springbones)を1本のリストへ合流させるために使う。既存の
    source_chains_from_physbone_catalog()自体はdev1371テストの
    id形式("<anchor>#<i>")契約があるため変更しない)。

    idはanchorごとの通し番号(entry単位ではなく全entryを跨いだ連番)で
    採番する——実データ(VRM springBoneは同じanchor("Head"等)を持つ
    エントリが複数、各エントリのchainsは1本のことが多い、実測: AliciaSolid
    _vrm-0.51.vrmで6件が全て anchor="Head")では、entry内index基準の
    採番だと同じ"anchor#0"が複数回衝突し、レポート・ABP仕様生成での
    チェーン識別が破綻する(dev#1375実測で判明、修正)。"""
    out: List[SourceChain] = []
    counters: Dict[str, int] = {}
    for entry in entries:
        anchor = entry["anchor"]
        for chain in entry.get("chains", []):
            i = counters.get(anchor, 0)
            counters[anchor] = i + 1
            out.append(SourceChain(
                id=f"{prefix}:{anchor}#{i}", anchor=anchor, chain=tuple(chain)))
    return out


# =====================================================================
# gender別donor在庫フィルタ
# =====================================================================

def filter_bone_pairs_by_gender(
    bone_pairs: Sequence[Tuple[str, Optional[str]]], gender: str,
) -> List[Tuple[str, Optional[str]]]:
    """共有骨格(SK_PalHuman)は男女のdonorファミリーが同一階層に混在する
    (実測: work\\rd_19_haori\\sk_palhuman_bones.jsonに"M_OldCloth001_04"と
    "F_OldCloth001_04"が両方pelvis直下に存在。"HeadEquip062_ear_01_l"の
    ような性別非依存のdonor家系にはM_/F_接頭辞が無い)。

    このフィルタを掛けずに build_donor_inventory() を実データへ適用すると、
    Male変換にF_接頭辞のdonorが(またはその逆)混入して割り当てられうる
    (region/節数だけでは性別を区別できないため)。gender("Male"/"Female"、
    step02_retarget.pyのgender引数と同じ語彙)に応じて、対象と異なる
    性別接頭辞を持つボーンだけを bone_pairs から取り除く。接頭辞を持たない
    ボーン(標準ボーン、HeadEquip*等の共有donor家系)はそのまま残す。

    実データでは同一家系のボーンは全て同じ接頭辞で統一されている
    (例: "F_OldCloth001_05"の親は"F_OldCloth001_04"、異なる接頭辞の親を
    持つボーンは無い)ため、名前の接頭辞だけを見る単純フィルタで
    チェーン全体が一貫して除去される(祖先を辿って接頭辞混在をチェック
    する必要が無い、work\\rd_19_haori\\sk_palhuman_bones.json実測に基づく
    設計判断)。
    """
    keep_prefix = "M_" if gender == "Male" else "F_"
    drop_prefix = "F_" if gender == "Male" else "M_"
    return [
        (name, parent) for name, parent in bone_pairs
        if not (name.startswith(drop_prefix) and not name.startswith(keep_prefix))
    ]


# =====================================================================
# 高レベル入口: 変換フローへの結線(dev#19 R3統合、dev#1375)
# =====================================================================

def assign_avatar_sway(
    *,
    physbone_entries: Sequence[Dict] = (),
    springbone_entries: Sequence[Dict] = (),
    manual_chains: Sequence[Dict] = (),
    donor_bone_pairs: Sequence[Tuple[str, Optional[str]]],
    source_parent_of: Dict[str, Optional[str]],
    gender: str,
    chibi_candidates: Optional[Sequence[str]] = None,
    symbols: Optional[Dict] = None,
    registered_families: Optional[Sequence[str]] = None,
) -> AssignmentResult:
    """変換フローへの結線窓口(1関数)。job.jsonの3系統の搬送元入力を
    1本のSourceChainリストへ正規化し、gender別フィルタ済みのdonor在庫へ
    assign_sway_chains()で割り当てる。

    physbone_entries: job["physbones_json"]を app_py\\physbone_catalog.py
      catalog_from_sidecar()で読んだ ["physbones"]リスト(prefab側)。
    springbone_entries: job["springbones"]の中身
      (app_py\\vrm_spring_catalog.py catalog_from_vrm()["physbones"]相当、
      VRM側。搬送元は異なるがphysbone_catalogと同一スキーマ
      {"anchor": str, "chains": [[str,...],...]})。
    manual_chains: job["sway_manual"]の中身。各要素は
      {"bones": [anchor, node1, node2, ...], "id": 任意(省略可)}。
      stiffness等のABPパラメータはここでは扱わない(骨の割当と無関係。
      build_multinode_abp_spec()のmanual_params引数で別途消費する設計、
      責務分離)。bonesが1要素以下(アンカーのみ、揺れる節が無い)の
      エントリは無視する(assign_sway_chains自体はn_source==1でも
      「全体アンカー」として扱えるが、手動指定の入力ミス
      (要素0個・None)を安全側で弾く簡易バリデーション)。
    donor_bone_pairs: 共有骨格の生の親子データ(gender別フィルタ**前**、
      pipeline\\data\\sk_palhuman_bones.json由来を想定)。本関数が内部で
      filter_bone_pairs_by_gender()を適用する。
    gender: "Male"または"Female"。
    registered_families: dev#19実データ欠陥修正(issue #1379、欠陥2)。
      「登録済み家系」名の集合(step02_retarget.SWAY_DONOR_FAMILIESのキー
      集合を想定)。指定時、この集合に含まれない家系は候補プールから
      事実上除外される(build_donor_inventory()のregistered_families引数
      へそのまま中継、詳細はそちらのdocstring参照)。省略時(None)は
      フィルタなし(既存呼び出し元は無退行)。

    3系統とも空(既定)なら sources が空リストになり、
    assign_sway_chains([], ...) の安全なno-op(受入条件d)がそのまま働く。
    """
    sources: List[SourceChain] = []
    sources += source_chains_from_physbone_catalog(physbone_entries)
    sources += _prefixed_source_chains(springbone_entries, "vrmspring")
    for i, m in enumerate(manual_chains):
        bones = list(m.get("bones") or [])
        if len(bones) < 2:
            continue  # アンカーのみ(揺れる節が0本)は無効な指定として無視
        sources.append(SourceChain(
            id=m.get("id") or f"manual#{i}", anchor=bones[0], chain=tuple(bones[1:])))

    gendered_pairs = filter_bone_pairs_by_gender(donor_bone_pairs, gender)
    inventory = build_donor_inventory(
        gendered_pairs, chibi_candidates=chibi_candidates,
        registered_families=registered_families)
    return assign_sway_chains(sources, inventory, source_parent_of, symbols=symbols)


# =====================================================================
# 静的ゲート: 宣言されたチェーンの割当状況レポート(item6、PROPOSAL §6)
# =====================================================================

def build_sway_lost_report(result: AssignmentResult) -> Dict:
    """「ボーンが技術的に解決できた」ことと「意図した動的挙動(PhysBone)が
    保持された」ことは別軸である(work\\rd_19_ears\\PROPOSAL.md §6)。本関数は
    後者を機械的に可視化する集計を返す——宣言された揺れチェーンの総数・
    実際にdonorへ割り当てられた本数・割当不能(sway-lost)になった本数と
    その理由。呼び出し側(step02_retarget.py)はこれを
    `[step02][sway-report]`ログ行として出力する想定(実装は別関数、本関数
    はbpy非依存の純粋集計のみ)。

    受入条件の負の対照(WP指示書「宣言対象の欠落を機械検出可能に」):
    「揺れチェーンを1本も配線しないままsource_chainsにエントリがある」
    ケースでlost_chains > 0になることをテストで確認する(dev1371フィク
    スチャの(b)(c)がそのまま使える——在庫不足/保護不能のいずれも
    lost扱いになる)。
    """
    lost = [
        {"id": u.source.id, "anchor": u.source.anchor, "reason": u.reason}
        for u in result.unassigned
    ]
    return {
        "declared_chains": len(result.assigned) + len(result.unassigned),
        "assigned_chains": len(result.assigned),
        "lost_chains": len(lost),
        "lost": lost,
    }


# =====================================================================
# ABP仕様JSON生成(item5、cook・UE操作は行わない純粋関数)
# =====================================================================

def build_multinode_abp_spec(
    result: AssignmentResult,
    *,
    ali: str,
    skeleton: str,
    target_abp: str,
    manual_params: Optional[Dict[str, Dict]] = None,
) -> Dict:
    """割当結果(AssignmentResult.assigned)から
    work\\rd_19_multinode\\RESULT.md §2の確定spec JSON形式を生成する。

    生成のみ(ファイル書き出し・UE Python実行・cookは一切行わない。実
    authoringは統合ビルドWPの仕事、RESULT.md §5の手順を使う)。

    manual_params: {source_id: {"dummy_bone_length": float,
    "params": {...}, "curves": {...}}} という上書き辞書(省略可)。
    job["sway_manual"]の各エントリがstiffness等のABPパラメータを持つ
    場合、呼び出し側がsource.idをキーにしてこの辞書へ変換して渡す想定
    (骨の割当自体はstiffnessと無関係のため assign_avatar_sway() 側では
    扱わない、責務分離)。指定の無いチェーンはparams/curves省略
    (=プラグイン既定値)、dummy_bone_lengthは省略(既定0)。

    nodesの並び順はresult.assignedの順(=assign_sway_chains()が
    source_chainsを処理した順、通常はjob.json記載順)。KawaiiPhysicsノード
    のroot_boneはdonor.chain_root(dev#1375修正、abp_node参照)。
    """
    manual_params = manual_params or {}
    nodes = []
    for a in result.assigned:
        override = manual_params.get(a.source.id, {})
        node: Dict = {"root_bone": a.abp_node["root_bone"]}
        dbl = override.get("dummy_bone_length")
        if dbl:
            node["dummy_bone_length"] = dbl
        if override.get("params"):
            node["params"] = override["params"]
        if override.get("curves"):
            node["curves"] = override["curves"]
        nodes.append(node)
    return {"ali": ali, "skeleton": skeleton, "target_abp": target_abp, "nodes": nodes}
