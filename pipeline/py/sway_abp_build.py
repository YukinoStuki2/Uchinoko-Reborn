# -*- coding: utf-8 -*-
"""dev#19(揺れものpak生成の製品パイプライン結線): job.json の標準機能
「揺れの度合い」(`sway_intensity`、GUI `main_window.py` swayIntensityBar、
値は "none"/"hard"/"normal"/"soft")を、UE・UAssetGUI・.NET一切無しで揺れABP
(KawaiiPhysics付き `ABP_{gender}_{family}_Implimentation`)のpak同梱へ結線する。

## 設計方針: テンプレはデータ、パッチャ・本モジュールはロジックのみ

`pipeline\\py\\sway_abp_templates\\`(cooked/ = 著作済みuasset/uexp、specs/ =
ノード構成メタデータ)がテンプレの実体。本モジュールは **どのノードが何本
あるか・root_boneが何かを一切ハードコードしない**——`specs/*.json` を実行時に
読んで動的に組み立てる。したがって `sway_abp_templates/` の中身を丸ごと
差し替えれば(例: dev#1396 NameMap欠落根治後のテンプレへの差し替え)、本
モジュールのコードを一切変更せずに新テンプレへ追従する
(`sway_abp_templates/README.md` 参照)。

## パラメータ選択(硬さプリセット、2026-08-14夜 kp_tuner GUI実機官能で再確定)

`sway_intensity` から硬さプリセット(damping・stiffness・wd)を選ぶテーブルは
2026-08-14夜、kp_tuner GUIでの実機実験によるオーナー官能確定値を正本とする。
kata/futsuuはオーナー官能で確定した値そのもの。yawaはF1(2026-08-14昼に
オーナー官能で最初に確定した値。同日夜の再調整で表から一時消えていたが、
2026-08-16オーナー裁定で正式値として復帰)。これで3段すべてが官能アンカー
済みになった。

wdl/wdr(たなびきの支配パラメータ)は本ラウンドでプリセットごとに異なる値と
判明した新知見——kata=0.3(揺れ控えめ)、futsuu/yawa=0.0(全たなびき)。
このためHARDNESSは(damping, stiffness, wd)の3要素タプルへ拡張した
(旧2要素構造から2026-08-14夜に再拡張)。

旧来の「stiffnessカーブroot0.6固定・上りカーブ」「gravity_z=-98」
「limit_angle=55の上りカーブ」は根拠のない歴史的残骸と確定(2026-08-14)し
廃止した。以後stiffness/damping/wdl/wdr/limit_angle/gravity_zはいずれも
鎖全域一律(カーブは恒等=[[0,1.0],[1,1.0]]、形状操作をしない)。
これらは特定テンプレのボーン名に依存しない汎用の物理パラメータであり、
「テンプレ固有値をハードコードしない」制約の対象外(テンプレ差し替えでも
不変であるべき値)。

## 鎖の家系別パラメータ(耳/尻尾) -- 自動判定は2026-08-16廃止(dev#1508 W2a)

`rd_19_earpivot`の実測により、耳は尻尾と同一パラメータでは根元が漂うことが
判明し、当初は耳を常にkata値固定にしていた。**dev#1508最終仕様(SPEC.md §1-7
「耳の特別扱いは完全廃止」)により、この自動固定は廃止した**——耳鎖も他の鎖と
同じく候補判定・無偏向判定・量子化を経て決まった値を使う(node_overrides、
下記「ノード単位の値上書き」参照)。`chain_family_for(root_bone)` 自体は
ラボ機能「生パラメータ全解放パネル」(dev#1418、下記)がtail/ear別の手動
上書きを適用する先を選ぶために引き続き使う(この用途は自動判定とは別軸)。

## ノード単位の値上書き(dev#1508 W2a、揺れ対象の自動アロケータ結線)
## → 優先順位はdev#1587で反転(2026-08-19、v2.11方式)

`build_spec_nodes()`の`node_overrides`引数({root_bone名: {"style":
"yawa"/"futsuu"/"kata", "limit_angle": float|None}})は、
`pipeline\\py\\sway_allocator.py`(候補判定・無偏向判定・量子化)+
`pipeline\\py\\sway_assign.py`(donor骨への実配線)を経て決まった、
root_bone(=実際に骨がウェイト転写されたdonorチェーンの先頭)ごとの
量子化スタイル・limit_angleである。呼び出し側
(`pipeline\\blender\\step02_retarget.py`)が`job_dir/converted/
sway_node_overrides.json`へ書き出し、`build_pak_from_avatar.py`
`_run_sway_abp_patch()`がそれを読んで本関数へ中継する(BlenderプロセスとUE
非依存パッチプロセスは別プロセスのため、job_dir配下の副ファイル経由で
受け渡す設計。既存の`_chibi_bone_world_head`等と同じ流儀)。

**2026-08-19 dev#1587修理(オーナー裁定「なおればそれでいいよ」)**:
`style`(硬さ)は**overrideの有無に関わらず常にjob["sway_intensity"]由来の
`hardness_key`を使う**(旧仕様=overrideがあればそちらを優先、は廃止)。
旧仕様では実際にウェイトが配線された鎖(=node_overridesに載る鎖)で
GUI「硬さ4択」が常にno-opになっていた(issue dev#1587、laneK3実測:
hard/soft間でoverride対象3鎖のparamsが完全一致していた)。`limit_angle`
(SPEC.md §1-3b「角度制限写し」、donor自身のPB/SB限界角)は本修理の対象外
——引き続きoverrideに載っていればそちらで上書きする。自動アロケータの
配線トポロジ(どの鎖をどのdonorへ)自体は本修理でも変えない——変わるのは
硬さ値の出どころ(hardness_key vs override["style"])だけ。
`sway_allocator.py`/`sway_quantize.py`が生成するstyleの値自体は
将来の鎖ごと設定機能(第3便以降)向けの資産として引き続き保持する。

## 揺れ無効時は完全no-op

job.json に `sway_intensity` キーが無い、または値が "none"/未知の場合、
`sway_abp_pak_entries()` は空リストを返す(ファイルI/Oすら発生しない)。
呼び出し側(`build_pak_from_avatar.py`)はこの結果をpakへ追加するだけなので、
揺れ無効ジョブのpak出力はこのWP適用前と完全に一致する(ABPファイルが1つも
追加されないため)。
"""
from __future__ import annotations

import glob
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import sway_abp_patcher  # noqa: E402
import vp_core  # noqa: E402
import vp_pakwrite  # noqa: E402

TEMPLATES_DIR = os.path.join(HERE, "sway_abp_templates")
COOKED_DIR = os.path.join(TEMPLATES_DIR, "cooked")
SPECS_DIR = os.path.join(TEMPLATES_DIR, "specs")

# dev#19揺れものUIプロトタイプ(main_window.py SWAY_INTENSITY_VALUES =
# ["none", "hard", "normal", "soft"])のjob.json値 -> 硬さプリセットキーへの
# 対応。"none"はここに含めない(揺れ無効、sway_abp_pak_entries()が空リストで
# 早期returnする)。
INTENSITY_TO_HARDNESS: Dict[str, str] = {
    "soft": "yawa",
    "normal": "futsuu",
    "hard": "kata",
}

# 正本: 2026-08-14夜、kp_tuner GUIでの実機実験によるオーナー官能確定値。
# (damping, stiffness, wd) の3要素タプル——wdはwdl/wdr共通値(鎖全域一律値
# そのもの、カーブによる形状操作はしない、curves_for()参照)。
# kata/futsuuはオーナー官能確定値そのもの。yawa=F1(2026-08-14昼オーナー官能
# 確定値、2026-08-16裁定で復帰)。
# wdl/wdrがプリセットごとに異なる値を持つのは本ラウンドの新知見
# (kata=0.3=揺れ控えめ、futsuu/yawa=0.0=全たなびき)。
HARDNESS: Dict[str, Tuple[float, float, float]] = {
    "yawa":   (0.25, 0.05, 0.0),  # F1(2026-08-14昼オーナー官能確定値、2026-08-16裁定で復帰)
    "futsuu": (0.08, 0.20, 0.0),
    "kata":   (0.30, 0.30, 0.3),
}

# 共通params(尻尾系/汎用布系の既定、root_bone・damping・stiffness・wdl/wdr
# 以外はhardness_keyに依らず一定)。
# gravity_z=0.0・limit_angle=0: KP公式の「制限無効」センチネル
# (2026-08-14オーナー官能確定、旧-98/55は根拠のない歴史的残骸と確定)。
_BASE_PARAMS = {
    "limit_angle": 0, "gravity_z": 0.0, "radius": 6,
}

# 旧耳家系(chain_family_for()=="ear")専用の固定上書きparams
# (_EAR_PARAMS_OVERRIDE)は2026-08-16 dev#1508最終仕様(SPEC.md §1-7
# 「耳の特別扱いは完全廃止」)で廃止した。耳鎖も一般規則(候補・無偏向・
# 量子化)で決まった値(node_overrides経由)を使う。定数自体は削除済み——
# 参照している旧コードがあればこの行が目印になる。


class SwayAbpBuildError(Exception):
    """テンプレ構造・spec整合性の想定外エラー(黙って握り潰さず変換全体を
    止めるためのシグナル、dt_flag_patcher.py / sway_abp_patcher.py と同じ
    設計方針)。"""


# ---------------------------------------------------------------------------
# ラボ機能「揺れ物理の生パラメータ全解放パネル」(dev#1418、
# work\wp_1418_rawparam\BRIEF.md、2026-08-15)。
#
# UI案の所在: work\rd_19_labgui\kp_tuner.py(2026-08-14夜、オーナーが実機で
# 使って気に入った開発用GUI)。同GUIの param モデル(family="tail"/"ear" ×
# キー stiffness/damping/wd(=wdl・wdr共通値)/gravity_z/limit_angle)を
# そのまま job キーの形として採用する(#1418コメント「UI案もできてる」の指す
# 実体、詳細は NOTES.md 参照)。
#
# job["lab_raw_sway_params"](既定=キー不在)は
# {"tail": {...5キー...}, "ear": {...5キー...}} のdict。キー不在/空/不正な
# 値はすべて「無効(=preset由来のparamsをそのまま使う)」として無視する
# (apply_tip_stiffen()と同じ「壊れた入力は安全側=no-opへ倒す」方針)。
# radiusは対象外(kp_tuner.py同様、公開UIに含めない)。
# ---------------------------------------------------------------------------

RAW_SWAY_PARAM_RANGES: Dict[str, Tuple[float, float]] = {
    "stiffness": (0.0, 1.0),
    "damping": (0.0, 1.0),
    "wd": (0.0, 1.0),
    "gravity_z": (-100.0, 0.0),
    "limit_angle": (0.0, 180.0),
}

RAW_SWAY_PARAM_FAMILIES: Tuple[str, ...] = ("tail", "ear")


def _clamp_raw_sway_param(key: str, value: float) -> float:
    lo, hi = RAW_SWAY_PARAM_RANGES[key]
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def raw_sway_params_from_job(job: Dict) -> Optional[Dict[str, Dict[str, float]]]:
    """job["lab_raw_sway_params"]を読み、familyごとに検証・clamp済みの
    上書きdictへ変換する。以下はすべて「そのfamily/キーは上書き無し」
    (=既定のpreset値を使う)として黙って無視する(構造ガーベジをそのまま
    通さない、ただし本機能は「壊れた個別値だけ無視して残りは活かす」設計
    ——tip_stiffen_from_job()の「1個の壊れた値で機能全体を無効化する」より
    緩い。理由: 5キー×2家系=10個のうち1個だけタイプミスがあっても残り9個
    は活かせたほうがラボ機能としての実用性が高いため)。

    戻り値: 有効な上書きが1件も無ければNone(=完全no-op)。"""
    raw = job.get("lab_raw_sway_params")
    if not isinstance(raw, dict) or not raw:
        return None
    result: Dict[str, Dict[str, float]] = {}
    for family in RAW_SWAY_PARAM_FAMILIES:
        fam_raw = raw.get(family)
        if not isinstance(fam_raw, dict):
            continue
        overrides: Dict[str, float] = {}
        for key in RAW_SWAY_PARAM_RANGES:
            if key not in fam_raw:
                continue
            v = fam_raw[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            overrides[key] = _clamp_raw_sway_param(key, float(v))
        if overrides:
            result[family] = overrides
    return result or None


def apply_raw_sway_params(
    params: Dict[str, float], raw_override: Dict[str, float],
) -> Dict[str, float]:
    """params(params_for()の構築途中のdict)に raw_override
    (raw_sway_params_from_job()が返す1家系ぶんの上書き、キーは
    stiffness/damping/wd/gravity_z/limit_angleの部分集合)を適用した
    新しいdictを返す(paramsは変更しない)。raw_override内に存在する
    キーだけを上書きし、欠落キーはpreset由来の値を維持する。wdは
    wdl・wdrの両方へ同じ値を書く(kp_tuner.py全チャネル同期の踏襲)。"""
    new_params = dict(params)
    if "stiffness" in raw_override:
        new_params["stiffness"] = raw_override["stiffness"]
    if "damping" in raw_override:
        new_params["damping"] = raw_override["damping"]
    if "wd" in raw_override:
        new_params["wdl"] = raw_override["wd"]
        new_params["wdr"] = raw_override["wd"]
    if "gravity_z" in raw_override:
        new_params["gravity_z"] = raw_override["gravity_z"]
    if "limit_angle" in raw_override:
        new_params["limit_angle"] = raw_override["limit_angle"]
    return new_params


def curves_for() -> Dict[str, List[List[float]]]:
    """恒等カーブ(root=tip=1.0)。鎖方向のシェーピングは行わない
    ——旧来の「stiffnessカーブroot0.6固定・上りカーブ」「limit_angleの
    0.4→1.0上りカーブ」は根拠のない歴史的残骸と確定(2026-08-14)し廃止した。
    stiffness/wdl/wdr/limit_angleいずれもscalar params(params_for()の戻り値)
    の値がそのまま鎖全域へ一律適用される(呼び出し元がキーごと別の
    Dict/Listオブジェクトを受け取れるよう、毎回新規に組み立てる)。"""
    return {
        "stiffness": [[0, 1.0], [1, 1.0]],
        "wdl": [[0, 1.0], [1, 1.0]],
        "wdr": [[0, 1.0], [1, 1.0]],
        "limit_angle": [[0, 1.0], [1, 1.0]],
    }


def chain_family_for(root_bone: str) -> str:
    """root_bone名から鎖の家系("ear"/"tail")を判定する。
    耳ボーンの命名規約は "ear" 部分文字列を含む(既存
    `sway_abp_templates/specs/*.json` 全件で確認済み、例:
    "HeadEquip062_ear_01_l"/"_r")。それ以外は尻尾・汎用布として "tail"
    家系(既定パラメータ)を適用する。"""
    return "ear" if "ear" in root_bone.lower() else "tail"


def params_for(
    hardness_key: str,
    raw_override: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """hardness_keyから7項目params(stiffness/damping/wdl/wdr/limit_angle/
    gravity_z/radius)を組み立てる。

    2026-08-16 dev#1508最終仕様(SPEC.md §1-7)で耳の自動kata固定を廃止した
    ため、family引数は無くなった——全鎖がhardness_keyベースの値を使う
    (耳/尻尾いずれもnode_overrides経由で個別のhardness_keyを渡せる、
    build_spec_nodes()参照)。

    raw_override(dev#1418ラボ機能「生パラメータ全解放パネル」、既定None):
    Noneまたは空dictなら完全no-op(このパラメータ追加前と出力が一致する、
    ラボ憲章④)。値があれば `apply_raw_sway_params()` で最後に上書きする
    ——呼び出し側(build_spec_nodes())がchain_family_for()で選んだ
    family別のraw_overrideをここへ渡す(ラボ機能自体はfamily概念を維持)。
    """
    if hardness_key not in HARDNESS:
        raise SwayAbpBuildError(f"unknown hardness preset: {hardness_key!r}")
    p = dict(_BASE_PARAMS)
    damping, stiffness, wd = HARDNESS[hardness_key]
    p["damping"] = damping
    p["stiffness"] = stiffness
    p["wdl"] = wd
    p["wdr"] = wd
    if raw_override:
        p = apply_raw_sway_params(p, raw_override)
    return p


def hardness_key_for_intensity(sway_intensity: Optional[str]) -> Optional[str]:
    """job.get("sway_intensity")の値から硬さプリセットキーを返す。
    "none"・キー欠落(None)・未知の値はNone(=揺れ無効/対象外)。"""
    if not sway_intensity:
        return None
    return INTENSITY_TO_HARDNESS.get(sway_intensity)


def load_template_manifest(specs_dir: str = SPECS_DIR) -> List[Dict]:
    """`specs/*.json`を全件読み込む(ファイル名列は一切ハードコードせず
    globで動的発見、テンプレ差し替え時に本関数の変更が不要な理由)。

    各要素: {"spec_path": str, "target_abp": str, "root_bones": [str, ...],
    "uasset_name": str, "uexp_name": str}
    (uasset/uexp名は target_abp の末尾コンポーネントから導出する
    ——specファイル自体はファイル名を持たないため)。

    specs_dir が存在しない、または対象ファイルが1件も無い場合は空リストを
    返す(呼び出し側 sway_abp_pak_entries() がこれを「テンプレ未同梱」として
    安全に扱う——開発中のリポジトリ状態への耐性)。
    """
    if not os.path.isdir(specs_dir):
        return []
    manifest: List[Dict] = []
    for spec_path in sorted(glob.glob(os.path.join(specs_dir, "*.json"))):
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
        target_abp = spec.get("target_abp")
        nodes = spec.get("nodes") or []
        if not target_abp or not nodes:
            raise SwayAbpBuildError(
                f"malformed sway ABP template spec (missing target_abp/nodes): {spec_path}")
        root_bones = [n["root_bone"] for n in nodes]
        asset_name = target_abp.rsplit("/", 1)[-1]
        manifest.append({
            "spec_path": spec_path,
            "target_abp": target_abp,
            "root_bones": root_bones,
            "uasset_name": asset_name + ".uasset",
            "uexp_name": asset_name + ".uexp",
        })
    return manifest


def build_spec_nodes(
    root_bones: List[str], hardness_key: str,
    raw_params: Optional[Dict[str, Dict[str, float]]] = None,
    node_overrides: Optional[Dict[str, Dict[str, object]]] = None,
) -> List[Dict]:
    """指定した硬さプリセットで、root_bonesの各ノードのspec_nodes
    (sway_abp_patcher.patch_kawaii_physics_nodes()の入力形)を組み立てる。

    node_overrides(dev#1508 W2a、既定None、モジュールdocstring
    「ノード単位の値上書き」参照): {root_bone名: {"style": "yawa"/"futsuu"/
    "kata", "limit_angle": float|None}}。**2026-08-19 dev#1587修理で優先順位を
    反転**——style(硬さ)は常に引数のhardness_key(job["sway_intensity"]由来)
    を使い、overrideに載っていてもoverride["style"]は無視する(全root_bone
    一律刻印)。旧仕様(override["style"]優先)ではGUI「硬さ4択」が実配線鎖で
    常にno-opになっていた(issue dev#1587)。limit_angleは本修理の対象外
    ——overrideに載っていて値がNoneでなければ従来どおりparams["limit_angle"]
    を上書きする(SPEC.md §1-3b角度制限写し、donor自身の値)。
    family("ear"/"tail")はhardness選択には関与しない
    (chain_family_for()はラボraw_paramsの適用先選択にのみ使う、下記)。

    raw_params(dev#1418ラボ機能「生パラメータ全解放パネル」、既定None):
    {"tail": {...}, "ear": {...}} の形。Noneまたは対象familyのキーが
    無ければそのノードは完全no-op(このパラメータ追加前と出力が一致する)。"""
    nodes: List[Dict] = []
    for rb in root_bones:
        override = (node_overrides or {}).get(rb)
        # dev#1587修理(2026-08-19オーナー裁定「なおればそれでいいよ」、
        # v2.11方式): job.sway_intensity由来のhardness_keyがoverride["style"]
        # より優先する(旧: override["style"]があればそれを優先していた
        # ため、実配線鎖ではGUI「硬さ4択」が常にno-opだった、issue dev#1587
        # laneK3実測)。overrideのlimit_angleは従来どおり写す(SPEC.md
        # §1-3b、下記)——反転したのはstyle(硬さ)の出どころだけで、配線
        # トポロジ・limit_angle写しは変えない。
        node_hardness = hardness_key
        if node_hardness not in HARDNESS:
            raise SwayAbpBuildError(f"unknown hardness preset: {node_hardness!r}")
        family = chain_family_for(rb)
        raw_override = (raw_params or {}).get(family)
        params = params_for(node_hardness, raw_override)
        if override is not None and override.get("limit_angle") is not None:
            params["limit_angle"] = override["limit_angle"]
        curves = curves_for()
        nodes.append({"root_bone": rb, "params": params, "curves": curves})
    return nodes


def patch_template_bytes(
    template: Dict, hardness_key: str, cooked_dir: str = COOKED_DIR,
    raw_params: Optional[Dict[str, Dict[str, float]]] = None,
    node_overrides: Optional[Dict[str, Dict[str, object]]] = None,
) -> Tuple[bytes, bytes]:
    """1テンプレ(load_template_manifest()の1要素)をパッチし、
    (uasset_bytes, patched_uexp_bytes) を返す(uassetはNameMap等を含み
    パッチ対象外のためテンプレのバイトをそのまま返す)。

    raw_params/node_overrides: build_spec_nodes()へそのまま渡す
    (既定None=no-op)。"""
    uasset_path = os.path.join(cooked_dir, template["uasset_name"])
    uexp_path = os.path.join(cooked_dir, template["uexp_name"])
    if not (os.path.isfile(uasset_path) and os.path.isfile(uexp_path)):
        raise SwayAbpBuildError(
            f"sway ABP template files not found for {template['target_abp']}: "
            f"{uasset_path} / {uexp_path}")
    with open(uasset_path, "rb") as f:
        uasset_bytes = f.read()
    with open(uexp_path, "rb") as f:
        uexp_bytes = f.read()
    names = vp_core.read_names(uasset_path)
    spec_nodes = build_spec_nodes(
        template["root_bones"], hardness_key, raw_params, node_overrides)
    try:
        patched_uexp = sway_abp_patcher.patch_kawaii_physics_nodes(
            uexp_bytes, names, spec_nodes)
    except sway_abp_patcher.AbpStructureError as e:
        raise SwayAbpBuildError(
            f"failed to patch sway ABP template {template['target_abp']}: {e}") from e
    return uasset_bytes, patched_uexp


# pak内相対パス(mount_point=vp_pakwrite.COMMON_MOUNTと組み合わせて
# ".../Pal/Content/Pal/Blueprint/Character/Player/Imp_Cloth/ABP_..." になる、
# vp_pakwrite.SWAY_ABP_PREFIX参照)。target_abp("/Game/Pal/Blueprint/
# Character/Player/Imp_Cloth/ABP_...")の "/Game/Pal/" 以降をそのまま使う
# ——ディレクトリ構造もハードコードせずspec由来で決まる。
_GAME_PAL_PREFIX = "/Game/Pal/"


def _rel_from_target_abp(target_abp: str) -> str:
    if not target_abp.startswith(_GAME_PAL_PREFIX):
        raise SwayAbpBuildError(
            f"unexpected target_abp prefix (expected {_GAME_PAL_PREFIX!r}): {target_abp!r}")
    sub = target_abp[len(_GAME_PAL_PREFIX):]
    # normalize_rel(rel, "")はleading '/'除去+".."混入拒否のみを行う
    # (prefix=""なので文字列自体は変わらない、vp_pakwrite.pyの既存関数を
    # そのまま再利用してCOMMON_MOUNT体系の不変条件を強制する)。
    try:
        return vp_pakwrite.normalize_rel(sub, "")
    except ValueError as e:
        raise SwayAbpBuildError(f"invalid target_abp path {target_abp!r}: {e}") from e


def sway_abp_pak_entries(
    job: Dict, out_dir: str,
    templates_dir: str = TEMPLATES_DIR,
    node_overrides: Optional[Dict[str, Dict[str, object]]] = None,
) -> List[Tuple[str, str]]:
    """揺れABPのpak同梱エントリを組み立てる(main()から呼ぶ入口)。

    job: job.json を読み込んだdict。
    out_dir: パッチ後のuasset/uexpを書き出す作業ディレクトリ(呼び出し側が
      用意する。build_pak_from_avatar.py の work サブディレクトリ想定)。
    templates_dir: `sway_abp_templates/` 相当ディレクトリ(cooked/・specs/を
      含む)。テスト用に差し替え可能。
    node_overrides(dev#1508 W2a、既定None): build_spec_nodes()docstring
      「ノード単位の値上書き」参照。呼び出し側(build_pak_from_avatar.py)が
      job_dir配下のsway_node_overrides.jsonを読んで渡す想定。

    戻り値: [(abs_path, rel_path_in_common_mount), ...]。
    job["sway_intensity"] が "hard"/"normal"/"soft" のいずれでもない場合
    (キー欠落・"none"・未知の値)、またはテンプレが1件も見つからない場合は
    空リスト(=完全no-op、呼び出し側がこれをpakへ追加してもバイト不変)。

    job["lab_raw_sway_params"](dev#1418ラボ機能「生パラメータ全解放パネル」、
    既定キー不在)は raw_sway_params_from_job() 経由で build_spec_nodes() へ
    渡される。既定/キー不在ならこのラボ機能追加前と出力がバイト完全一致する
    (ラボ憲章④)。node_overrides省略時も同様に旧来の全ノード一律挙動と一致する。
    """
    hardness_key = hardness_key_for_intensity(job.get("sway_intensity"))
    if hardness_key is None:
        return []

    raw_params = raw_sway_params_from_job(job)

    cooked_dir = os.path.join(templates_dir, "cooked")
    specs_dir = os.path.join(templates_dir, "specs")
    manifest = load_template_manifest(specs_dir)
    if not manifest:
        return []

    os.makedirs(out_dir, exist_ok=True)
    entries: List[Tuple[str, str]] = []
    for template in manifest:
        uasset_bytes, patched_uexp = patch_template_bytes(
            template, hardness_key, cooked_dir, raw_params, node_overrides)
        rel = _rel_from_target_abp(template["target_abp"])
        uasset_out = os.path.join(out_dir, template["uasset_name"])
        uexp_out = os.path.join(out_dir, template["uexp_name"])
        with open(uasset_out, "wb") as f:
            f.write(uasset_bytes)
        with open(uexp_out, "wb") as f:
            f.write(patched_uexp)
        entries.append((uasset_out, rel + ".uasset"))
        entries.append((uexp_out, rel + ".uexp"))
    return entries
