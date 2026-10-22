# -*- coding: utf-8 -*-
"""sway_allocator.py -- 揺れもの自動アロケータの純ロジック(dev#1508 W1c、
issue https://github.com/pandrabox/DiveToPalworld-dev/issues/1508)。

正本仕様: `.devonly\\docs\\sway\\sway_wrapup\\SPEC.md` §1(「1. 標準機能『ゆらす』」)。
列車計画: `.devonly\\docs\\sway\\sway_wrapup\\TRAIN.md` Wave1 W1c。

physbones.json/springbones.json(W1a/W1bが生成する、アバターのPB/SB鎖の
列挙結果)を入力に、以下を**決定論的な純関数**として行う。**bpy非依存・
実機/Unity不要・pytest単体で完結**する(実際のPalworld骨格への配線は
後続W2a「骨配線(ハブ実装)」の仕事——本モジュールはW2aへ渡す「計画
オブジェクト」(`AllocationPlan`)を作るところまで)。

## パイプライン(SPEC §1の番号に対応)

1. **候補判定**: physbones.json/springbones.jsonに列挙されている時点で
   既にPB/SB付き鎖(付いていない骨はそもそも列挙されない)。よって本モジュール
   での「候補判定」は素直なパースそのもの(名前は一切見ない、`parse_physbones`/
   `parse_springbones`)。
2. **無偏向判定**(`_judge_pb_bias`/`_judge_sb_bias`、2026-08-16訂正版):
   - PB: `limit_type=="None"` → 無偏向。`limit_type=="Angle"`かつ
     `limit_rotation`(Pitch/Roll/Yaw)全0 → 無偏向。`limit_type=="Angle"`で
     rotation≠0 → 偏向。`limit_type`が`"Hinge"`/`"Polar"` → 偏向。
     未知のlimit_typeは安全側(偏向)に倒す。
   - SB: 角度制限機構が無いので常に無偏向。
3. **量子化**(`sway_quantize.quantize_pb`/`quantize_sb`、dev#1508 W1cで
   `work\\sway_threshold\\quantize.py`を製品配置へ取り込み済み)。
3b. **角度制限写し**(`_pb_limit_angle`、dev#1453裁定): 無偏向PBの
   `limit_type=="Angle"`は`max_angle_x`(=PBのMax Angle値、
   `work\\rd_1453_anglimit\\PROPOSAL.md`が確認した「Angle→LimitAngle=
   maxAngleX(直接一致)」写像)をそのまま`limit_angle`へ写す。
   `limit_type=="None"`は写すものが無いので`0`(無制限)。SBは常に`0`。
4. **グループ化は廃止(dev#1551、2026-08-17オーナー裁定)**: `build_groups`は
   もはや複数の`ChainUnit`を束ねない——**1 ChainUnit = 1 SwayGroup = 1 KPノード**
   (issue https://github.com/pandrabox/DiveToPalworld-dev/issues/1551
   「hubを廃止し1chainあたり1KPノードへ移行する」、条件分岐待ちでなく
   即時標準経路)。旧dev#1508時代は`(親humanoid骨, style)`のペアで複数の
   ChainUnit(耳L/Rなど、anchorが異なっても同じ親humanoid骨に解決される
   もの)を1グループへ統合していた(`anchor_group_of`引数)が、ハブ構造
   (1スロット=複数鎖共有)が実機不具合(付け根ずれ=数値条件1違反、
   issue #1551本文)の容疑だったため、統合そのものを完全に取り除いた。
   `anchor_group_of`引数は削除済み——同じ`anchor`文字列を複数の
   ChainUnitが共有していても(まれ)、もはや統合しない。
5. **容量9・優先順位**(`allocate`): ①しっぽ最優先(`sway_identify.
   identify_sway_kind`の"tail"判定、耳は2026-08-16裁定で特別扱い廃止済み
   のため優先順位には関与しない) ②残りは骨数(グループ=ChainUnit1個ぶんの
   ボーン数)降順 ③同数はグループの代表骨名(anchor)の辞書順。
   上位9グループ(=9 ChainUnit)のみ`accepted`、溢れは`rejected_units`に
   理由付きで残す(dev#1551「容量あふれ鎖は完全に無傷で残す」)。
6. **ラボ割当上書き**(`apply_lab_overrides`、`allocate`の`lab_assignments`
   引数): 指定が無ければ完全に自動判定のまま(=ラボ機能OFF相当)。指定
   された鍵(`ChainUnit.key`)は自動判定より優先される。UIからの読み書き
   結線(ラボストアの実装)はW2cの仕事——ここにあるのは適用ロジックの
   入口のみ。

## 出力契約(`AllocationPlan`、W2a「骨配線」の入力)

```
AllocationPlan(
    accepted=(SwayGroup, ...),      # 採用グループ、優先順位降順(先頭が最優先)、最大capacity件
    rejected_units=(ChainUnit, ...),# 非採用ユニット(偏向除外/容量超過/ラボOFF)+理由
    all_units=(ChainUnit, ...),     # 全ユニット(診断ログ用。採用/非採用いずれも判定理由を保持)
    capacity=9,
)
```

`SwayGroup.chains` は、そのグループに属する全チェーン(骨名タプルの並び、
`anchor自身は含まない`)。W2aはこれを1つのKPノードのサブツリーとして
再親化する入力に使う想定。

## springbones.json の想定スキーマ(暫定、W1b確定後に要すり合わせ)

W1b(VRM SpringBone抽出)は本WPと並行のWaveであり、確定スキーマの実例が
まだ無い。本モジュールは physbones.json と対称な構造を暫定的に仮定する:

```json
{
  "format": "divetopalworld-springbones-1",
  "springbones": [
    {
      "anchor": "<親骨の生名>",
      "chains": [["b1", "b2", ...]],
      "params": {
        "stiffness": 1.0, "gravity_power": 0.0, "drag_force": 0.4
      }
    }
  ]
}
```

`params`の3値は`sway_quantize.quantize_sb(stiffness, gravity_power,
drag_force)`にそのまま渡す(VRM0.x/1.0共通の同名項目という前提、
`sway_quantize.py`のdocstring参照)。W1bの実出力がこの前提と食い違う場合は
`parse_springbones`側の調整のみで済む設計(呼び出し側の`allocate`契約は
変えずに済む)。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_identify  # noqa: E402  (尻尾同定の唯一の真実の源。sway_chain_override_store.py等と同じ理由でpipeline/py内から直接import)
import sway_quantize  # noqa: E402  (dev#1508 W1c: quantize_pb/quantize_sbの製品配置)

DEFAULT_CAPACITY = 9

PHYSBONES_FORMAT = "divetopalworld-physbones-1"
SPRINGBONES_FORMAT = "divetopalworld-springbones-1"

_UNBIASED_LIMIT_TYPES_NO_ANGLE = ("None",)
_BIASED_LIMIT_TYPES = ("Hinge", "Polar")


# =====================================================================
# データ型
# =====================================================================

@dataclass(frozen=True)
class LabAssignment:
    """ラボ「揺れもの詳細」パネルの手動割当1件(dev#1508 SPEC §2)。

    style: 適用する「ゆれかた」の名前(組み込み"yawa"/"futsuu"/"kata"、
      またはカスタム定義名。本モジュールは名前を不透明な文字列として
      扱うのみで、実パラメータへの解決はW2c/UI側の責務)。
    enabled: Falseなら自動判定に関わらずこのユニットを非採用にする
      (SPEC「任意の鎖に任意のゆれかたを割当可能」の裏返し=OFFにもできる)。
    limit_angle: 指定時はSPEC 3bの自動写しより優先する(未指定Noneなら
      自動写しの値をそのまま使う)。
    """

    style: str
    enabled: bool = True
    limit_angle: Optional[float] = None


@dataclass(frozen=True)
class ChainUnit:
    """1つのPB/SBコンポーネント(=物理的に1つのVRCPhysBone/SpringBone
    コンポーネント。物理的な鎖が複数本(房)あってもコンポーネントは1つ)から
    作られる、判定済みの中間表現。SPEC §2「一覧の行単位=PB/SBコンポーネント
    単位」と同じ粒度。
    """

    key: str                             # 安定キー "pb:<anchor>#<idx>" 等
    source: str                          # "pb" | "sb"
    anchor: str                          # 親骨(生の名前。$GUID接尾辞込み)
    chains: Tuple[Tuple[str, ...], ...]  # コンポーネント内の全チェーン(各チェーンはanchorを含まない骨名タプル)
    bone_count: int                      # 全チェーンの骨数合計
    params: Dict[str, object]            # 元paramsそのまま(診断・ラボ用に保持)
    is_biased: bool                      # 偏向判定(自動)
    bias_reason: str                     # 偏向理由(無偏向なら空文字列)
    is_tail: bool                        # sway_identify基準の尻尾判定
    style: Optional[str]                 # "yawa"/"futsuu"/"kata"等。非採用確定時はNoneもありうる
    limit_angle: float                   # 0=無制限
    lab_override: bool = False           # ラボ手動割当で確定したか
    excluded_reason: Optional[str] = None  # 非採用理由。Noneなら採用(groupingへ進む)
    pb_object_name: str = ""             # 診断ログ用(dev#1508 W2a): PBオブジェクト自身の
                                          # 表示名(entry["pb_object_name"]、無ければ空文字列)
    collider_count: int = 0              # 診断ログ用(dev#1508 W2a): このコンポーネントが
                                          # 参照するコライダー数(PB=params["colliders"]、
                                          # SB=entry["colliders"]の長さ。コライダー自体は
                                          # 変換されない=SPEC §2「放棄確定」ため参照数のみ保持)


@dataclass(frozen=True)
class SwayGroup:
    """1つの`ChainUnit`に対応する、1つのKPノードぶんの配線単位
    (dev#1551、2026-08-17オーナー裁定「hubを廃止し1chainあたり1KPノード
    へ移行する」——`build_groups()`docstring参照)。

    **`units`は常に長さ1**(dev#1508時代は複数ChainUnitを1グループへ
    統合しうる型だったが、dev#1551でその統合機構自体を廃止した)。
    型としては引き続きタプルのまま残す——`sway_hub.py`側の既存コード
    (`for unit in group.units: for chain in unit.chains:`)が変更なしで
    動く互換性のため。`anchor`はその唯一のunit自身の`anchor`と常に一致する。"""

    group_key: Tuple[str, str]           # (anchor, style)
    anchor: str                          # 唯一のunitのanchor(dev#1551で常に単一)
    style: str
    units: Tuple[ChainUnit, ...]         # 常に長さ1(dev#1551)
    chains: Tuple[Tuple[str, ...], ...]  # そのunit自身のchains
    bone_count: int
    is_tail: bool


@dataclass(frozen=True)
class AllocationPlan:
    """アロケータの最終出力。後続W2a(骨配線)の入力契約(モジュール
    docstring参照)。"""

    accepted: Tuple[SwayGroup, ...]
    rejected_units: Tuple[ChainUnit, ...]
    all_units: Tuple[ChainUnit, ...]
    capacity: int = DEFAULT_CAPACITY


# =====================================================================
# 2. 無偏向判定
# =====================================================================

def _judge_pb_bias(params: Mapping[str, object]) -> Tuple[bool, str]:
    """PBの偏向判定(SPEC §1-2、2026-08-16訂正版)。戻り値は
    (is_biased, reason)。reasonは無偏向なら空文字列。"""
    limit_type = str(params.get("limit_type", "None"))
    if limit_type == "None":
        # RotationはLimitの一部でNone時は不使用の死データ。値が残っていても問わない。
        return False, ""
    if limit_type == "Angle":
        rot = params.get("limit_rotation") or [0, 0, 0]
        if all(abs(float(v)) < 1e-9 for v in rot):
            return False, ""
        return True, f"偏向(Angleコーン中心オフセット): limit_rotation={list(rot)}"
    if limit_type in _BIASED_LIMIT_TYPES:
        return True, f"偏向({limit_type}型)"
    # 未知のlimit_typeは安全側(偏向扱い)に倒す。
    return True, f"偏向(未知のlimit_type={limit_type!r}、安全側判定)"


def _judge_sb_bias(_params: Mapping[str, object]) -> Tuple[bool, str]:
    """SpringBoneは角度制限機構が無いので常に無偏向(SPEC §1-2)。"""
    return False, ""


# =====================================================================
# 3b. 角度制限写し
# =====================================================================

def _pb_limit_angle(params: Mapping[str, object], is_biased: bool) -> float:
    """SPEC §1-3b。無偏向Angle型はmax_angle_x(=PBのMax Angle)をそのまま
    写す。limit_type=="None"は写すものが無いので0(無制限)。偏向鎖(is_biased)
    はどのみち非採用になるため0を返す(値としての意味は持たない)。"""
    if is_biased:
        return 0.0
    limit_type = str(params.get("limit_type", "None"))
    if limit_type == "Angle":
        return float(params.get("max_angle_x", 0.0))
    return 0.0


def _sb_limit_angle(_params: Mapping[str, object], _is_biased: bool) -> float:
    """SpringBoneは角度制限機構が無いので常に0(無制限)。"""
    return 0.0


# =====================================================================
# 尻尾判定
# =====================================================================

def _is_tail_component(anchor: str, chains: Sequence[Sequence[str]]) -> bool:
    """コンポーネント内のいずれかのチェーンが尻尾同定(`sway_identify.
    identify_sway_kind`)に一致すれば尻尾コンポーネントとする。耳判定は
    2026-08-16裁定(耳の特別扱い完全廃止)により優先順位に使わない
    ——ここでは意図的に見ない。"""
    for chain in chains:
        if sway_identify.identify_sway_kind(anchor, chain) == "tail":
            return True
    return False


# =====================================================================
# 1. 候補判定(パース)
# =====================================================================

def _iter_components(container_json: Optional[Mapping[str, object]], list_key: str):
    if not container_json:
        return
    for entry in container_json.get(list_key, []) or []:
        yield entry


def parse_physbones(physbones_json: Optional[Mapping[str, object]]) -> List[ChainUnit]:
    """physbones.json(W1a出力想定、`format`は`PHYSBONES_FORMAT`)から
    `ChainUnit`のリストを作る(候補判定+無偏向判定+量子化+角度制限写し+
    尻尾判定まで、自動判定分をすべて確定させる)。"""
    units: List[ChainUnit] = []
    for idx, entry in enumerate(_iter_components(physbones_json, "physbones")):
        anchor = str(entry.get("anchor", ""))
        chains = tuple(tuple(c) for c in entry.get("chains", []) or [])
        params = dict(entry.get("params", {}) or {})
        is_biased, reason = _judge_pb_bias(params)
        style = None if is_biased else sway_quantize.quantize_pb(
            float(params.get("pull", 0.0)), float(params.get("spring", 0.0)))
        limit_angle = _pb_limit_angle(params, is_biased)
        bone_count = sum(len(c) for c in chains)
        is_tail = _is_tail_component(anchor, chains)
        pb_object_name = str(entry.get("pb_object_name", ""))
        colliders = params.get("colliders")
        collider_count = len(colliders) if isinstance(colliders, list) else 0
        units.append(ChainUnit(
            key=f"pb:{anchor}#{idx}", source="pb", anchor=anchor, chains=chains,
            bone_count=bone_count, params=params, is_biased=is_biased,
            bias_reason=reason, is_tail=is_tail, style=style,
            limit_angle=limit_angle, pb_object_name=pb_object_name,
            collider_count=collider_count,
        ))
    return units


def parse_springbones(springbones_json: Optional[Mapping[str, object]]) -> List[ChainUnit]:
    """springbones.json(W1b出力想定、暫定スキーマはモジュールdocstring
    参照)から`ChainUnit`のリストを作る。SBは常に無偏向、limit_angleは
    常に0。"""
    units: List[ChainUnit] = []
    for idx, entry in enumerate(_iter_components(springbones_json, "springbones")):
        anchor = str(entry.get("anchor", ""))
        chains = tuple(tuple(c) for c in entry.get("chains", []) or [])
        params = dict(entry.get("params", {}) or {})
        is_biased, reason = _judge_sb_bias(params)
        style = sway_quantize.quantize_sb(
            float(params.get("stiffness", 0.0)),
            float(params.get("gravity_power", 0.0)),
            float(params.get("drag_force", 0.0)),
        )
        limit_angle = _sb_limit_angle(params, is_biased)
        bone_count = sum(len(c) for c in chains)
        is_tail = _is_tail_component(anchor, chains)
        pb_object_name = str(entry.get("pb_object_name", ""))
        colliders = entry.get("colliders")
        collider_count = len(colliders) if isinstance(colliders, list) else 0
        units.append(ChainUnit(
            key=f"sb:{anchor}#{idx}", source="sb", anchor=anchor, chains=chains,
            bone_count=bone_count, params=params, is_biased=is_biased,
            bias_reason=reason, is_tail=is_tail, style=style,
            limit_angle=limit_angle, pb_object_name=pb_object_name,
            collider_count=collider_count,
        ))
    return units


# =====================================================================
# 6. ラボ割当上書き(入口。UI結線はW2c)
# =====================================================================

def apply_lab_overrides(
    units: Sequence[ChainUnit],
    lab_assignments: Optional[Mapping[str, LabAssignment]],
) -> List[ChainUnit]:
    """ラボ「揺れもの詳細」パネルの手動割当を、自動判定の結果へ上書きする
    入口(SPEC §2「割当」)。

    `lab_assignments`が`None`または空なら、自動判定のユニットをそのまま
    返す(=ラボ機能OFF相当、SPEC「なし=OFF」)。指定されたキー
    (`ChainUnit.key`)は自動判定(偏向判定・量子化)より優先する:
    `enabled=False`なら理由付きで非採用に、`enabled=True`(既定)なら
    `style`/`limit_angle`を上書きしたうえで偏向フラグを解除して採用候補へ
    戻す(ラボは「PB/SBの無い骨も割当可能」なので、自動判定側が偏向除外
    していたユニットも上書きで復活しうる)。

    UIからのストア読み書き(保存・復元)はW2c(ラボパネル配線)の仕事——
    本関数が担うのはこの適用ロジックのみ。
    """
    if not lab_assignments:
        return list(units)
    out: List[ChainUnit] = []
    for u in units:
        ov = lab_assignments.get(u.key)
        if ov is None:
            out.append(u)
            continue
        if not ov.enabled:
            out.append(replace(
                u, style=None, is_biased=True,
                bias_reason=u.bias_reason or "ラボ割当でOFF",
                excluded_reason=f"ラボ割当でOFF: {u.key}", lab_override=True,
            ))
            continue
        out.append(replace(
            u, style=ov.style, is_biased=False, bias_reason="",
            limit_angle=ov.limit_angle if ov.limit_angle is not None else u.limit_angle,
            excluded_reason=None, lab_override=True,
        ))
    return out


# =====================================================================
# 4. グループ化
# =====================================================================

def build_groups(units: Sequence[ChainUnit]) -> List[SwayGroup]:
    """dev#1551(2026-08-17オーナー裁定、issue #1551「hubを廃止し
    1chainあたり1KPノードへ移行する」、条件分岐待ちでなく即時標準経路):
    `excluded_reason is None`(=採用候補)かつ`style`確定済みの各ユニットを、
    そのまま独立した1つの`SwayGroup`(`units=(u,)`)として返す——dev#1508
    時代の`(親humanoid骨, style)`束ね(耳L/R等の複数ChainUnitを1つの
    SwayGroupへ統合する仕組み、旧`anchor_group_of`引数)は完全に廃止した。
    同じ`anchor`文字列を複数のChainUnitが共有していても(まれ)、もはや
    統合しない——ハブ構造(1スロット=複数鎖共有)が実機不具合の容疑
    だったため、統合そのものを取り除くことが対策そのもの。

    戻り値の順序は`units`の登場順(決定論、パース順=physbones→springbones、
    各リスト内は入力順)。"""
    groups: List[SwayGroup] = []
    for u in units:
        if u.excluded_reason is not None or u.style is None:
            continue
        groups.append(SwayGroup(
            group_key=(u.anchor, u.style), anchor=u.anchor, style=u.style,
            units=(u,), chains=u.chains, bone_count=u.bone_count, is_tail=u.is_tail,
        ))
    return groups


def _group_priority_key(g: SwayGroup) -> Tuple[int, int, str]:
    """SPEC §1-6の優先順位: ①しっぽ最優先 ②骨数降順 ③骨名(anchor)辞書順。
    昇順ソートでこの順に並ぶようキーを作る(タプル比較、小さいほど優先)。"""
    return (0 if g.is_tail else 1, -g.bone_count, g.anchor)


# =====================================================================
# 5. 容量・優先順位 + 全体エントリポイント
# =====================================================================

def allocate(
    physbones_json: Optional[Mapping[str, object]] = None,
    springbones_json: Optional[Mapping[str, object]] = None,
    *,
    lab_assignments: Optional[Mapping[str, LabAssignment]] = None,
    capacity: int = DEFAULT_CAPACITY,
) -> AllocationPlan:
    """アロケータ本体。physbones.json/springbones.json(いずれか一方でも
    可)から`AllocationPlan`を組み立てる(SPEC §1の1〜6を通しで実行)。

    dev#1551(2026-08-17): `anchor_group_of`引数は削除済み(`build_groups()`
    docstring参照——複数ChainUnitの統合機構そのものを廃止したため、渡す
    対象が無くなった)。容量9のスロット勘定(下の`groups[:capacity]`)は
    **ChainUnit単位**で数える(1 ChainUnit = 1 グループ = 1スロット、
    dev#1508時代の「統合後のグループ数で数える」は統合が無くなったことで
    自動的にこの意味になる)。呼び出し側でこの関数へ`anchor_group_of=`を
    渡していたコードは、キーワード引数ごと削除すること(TypeErrorになる)。"""
    units: List[ChainUnit] = []
    units.extend(parse_physbones(physbones_json))
    units.extend(parse_springbones(springbones_json))

    units = apply_lab_overrides(units, lab_assignments)

    # 自動判定分の偏向除外を確定させる(ラボ上書きが無い/ラボがONで復活
    # させたユニットはis_biased=Falseになっているのでここでは触らない)。
    finalized: List[ChainUnit] = []
    for u in units:
        if u.excluded_reason is not None:
            finalized.append(u)
        elif u.is_biased:
            finalized.append(replace(
                u, excluded_reason=f"偏向のため既定OFF: {u.bias_reason}"))
        else:
            finalized.append(u)

    groups = build_groups(finalized)
    groups.sort(key=_group_priority_key)
    accepted_groups = tuple(groups[:capacity])
    overflow_groups = groups[capacity:]
    overflow_keys = {u.key for g in overflow_groups for u in g.units}

    final_units: List[ChainUnit] = []
    for u in finalized:
        if u.key in overflow_keys:
            final_units.append(replace(
                u, excluded_reason=f"容量超過で非採用: {u.anchor}"))
        else:
            final_units.append(u)

    rejected_units = tuple(u for u in final_units if u.excluded_reason is not None)
    return AllocationPlan(
        accepted=accepted_groups, rejected_units=rejected_units,
        all_units=tuple(final_units), capacity=capacity,
    )
