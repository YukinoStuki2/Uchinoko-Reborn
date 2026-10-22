# -*- coding: utf-8 -*-
"""sway_degrade.py -- 揺れ鎖の明示的縮退(dev#1508 graceful-degrade、
night_20260817 laneI)の純ロジック(bpy非依存)。

正本背景: `work\\night_20260817\\briefs\\laneI_graceful_degrade.md`。
#1546でVRM SpringBone配線(W1b)+受入ゲートfail-closed化が入った結果、
「配線できない揺れ鎖を持つアバターは変換全体が失敗する」ようになった
(実例: Seed-san.vrm、既存のdonor供給不足(dev#1508 W2a/W2b領域、本モジュール
では直さない)で`sway_source_gate`が特定の鎖だけFAILし、`core.die()`で
pak自体が生成されなくなる)。

オーナー原則(いずれも裁定済み):
- 「検出→出荷+警告が既定、ブロック禁止」
- 「体験を損なう機能は無いほうがまし」
- fail-closed(壊れた配線を黙って出荷しない)

この3つを同時に満たす挙動: **正しく配線できた鎖だけ揺らす。できない鎖は
除外して警告し、変換は必ず完走する。壊れた配線のまま出荷は決してしない。**

本モジュールは「どのunit(鎖)を除外すべきか」の決定ロジックと、
`sway_exclusions*.json`のスキーマ・シリアライズ・preflight側の判定
ヘルパーだけを持つ(bpy非依存、実機/Unity/pak不要でpytest単体完結)。
実際にBlender armature/meshを操作する重い処理(`sway_hub_wire.
wire_and_diagnose_hub()`の再実行・`place_hub_donor_chains()`の再配置)は
呼び出し側(`pipeline\\blender\\step02_retarget.py`)の責務。

## 除外の実装手段: `sway_allocator.LabAssignment(enabled=False)`

`sway_allocator.apply_lab_overrides()`は元々ラボ「揺れもの詳細」パネルの
手動割当(`ChainUnit.key`をキーとする上書き)向けに用意された、既存の
正式な拡張点である。本レーンはこれを"lab_assignments"引数として
`sway_hub_wire.wire_and_diagnose_hub()`/`sway_allocator.allocate()`両方に
そのまま渡すだけで、「このunit(鎖)を今回は採用しない」を機械的に実現
できる(新規の除外機構を発明する必要が無い、既存拡張点の正しい再利用)。

## 除外の粒度: unit(鎖)単位、group(統合後グループ)単位ではない

`sway_source_bones.bone_group_keys()`は`(親humanoid骨, style)`で統合
**済み**のグループ粒度しか返さない——1グループに複数の鎖(例: 耳L/R)が
統合されている場合、そのグループ単位で除外すると無関係な鎖まで道連れに
なってしまう。`sway_source_bones.bone_unit_keys()`(統合前のunit粒度)を
使い、FAILしたボーンが属するunit.keyだけを除外する。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_allocator  # noqa: E402

FORMAT = "divetopalworld-sway-exclusions-1"

# 除外が起きた段階(sway_exclusions.jsonの"stage"、診断用途のみ)。
STAGE_ALLOCATION_UNASSIGNABLE = "allocation_unassignable"  # 容量/donor在庫/anchor未解決(既存の正常フォールバック)
STAGE_CAPACITY_OVERFLOW = "capacity_overflow"  # dev#1551: sway_allocator.allocate()の容量9超過で非採用(配線しない・削除しない・座標も動かさない、完全無傷)
STAGE_GATE_TRANSFORM = "gate_transform"    # 受入ゲート: 位置/向き/スケール不一致
STAGE_GATE_AXIOM = "gate_axiom"            # 受入ゲート: 支点の対親相対位置公理違反
STAGE_GATE_WEIGHT_COLLISION = "gate_weight_collision"  # 受入ゲート: 複数鎖が同じdonorへ重みを奪い合う(予測検査)
STAGE_SYSTEMIC_DISABLE = "systemic_disable"  # 帰属できない/リトライ上限到達 -> sway全OFF


@dataclass(frozen=True)
class ExclusionEntry:
    """1鎖(unit)ぶんの除外記録。`unit_key`は`sway_allocator.ChainUnit.key`
    ("pb:<anchor>#<idx>" / "sb:<anchor>#<idx>")そのもの。"""

    unit_key: str
    source: str    # "pb" | "sb"
    anchor: str
    stage: str
    reason: str

    def to_dict(self) -> Dict[str, str]:
        return {"unit_key": self.unit_key, "source": self.source,
                "anchor": self.anchor, "stage": self.stage, "reason": self.reason}


def _unit_key_source_anchor(unit_key: str) -> Tuple[str, str]:
    """"pb:<anchor>#<idx>" / "sb:<anchor>#<idx>" -> (source, anchor)。
    形式が壊れている場合は安全側で("?", unit_key)を返す(die()しない、
    診断ログの表示劣化のみに留める)。"""
    if ":" not in unit_key or "#" not in unit_key:
        return "?", unit_key
    source, rest = unit_key.split(":", 1)
    anchor = rest.rsplit("#", 1)[0]
    return source, anchor


def make_exclusion_entry(unit_key: str, stage: str, reason: str) -> ExclusionEntry:
    source, anchor = _unit_key_source_anchor(unit_key)
    return ExclusionEntry(unit_key=unit_key, source=source, anchor=anchor,
                           stage=stage, reason=reason)


# =====================================================================
# 帰属(attribution): FAILしたボーン名の集合 -> 除外すべきunit.keyの集合
# =====================================================================

def attribute_bones_to_units(
    failed_bone_names: Iterable[str],
    bone_unit_keys_map: Mapping[str, FrozenSet[str]],
) -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """FAILしたボーン名それぞれについて、`sway_source_bones.
    bone_unit_keys()`の対応表からunit.keyを引く。

    戻り値: (attributable_unit_keys, unattributed_bone_names)。
    後者が非空なら「帰属できないFAIL」(ボーン名がどのunitにも見つからない
    ——通常は起こらない想定だが、`hub_wiring.unassignable`との食い違い等の
    構造的異常を示す)であり、呼び出し側はこれを「鎖に帰属できない全体的な
    破綻」として扱い、個別除外ではなく縮退(sway全OFF)へ倒すべき
    (laneI指示書「3. fail-closedの維持」)。"""
    attributable: Set[str] = set()
    unattributed: Set[str] = set()
    for name in failed_bone_names:
        keys = bone_unit_keys_map.get(name)
        if not keys:
            unattributed.add(name)
            continue
        attributable.update(keys)
    return frozenset(attributable), frozenset(unattributed)


def detect_weight_collisions(
    donor_of: Mapping[str, str],
    weighted_bones: Iterable[str],
    expected_merge_groups: FrozenSet[FrozenSet[str]] = frozenset(),
) -> Dict[str, List[str]]:
    """事前予測(remap実行前)の重み衝突検査: 複数の(実際にメッシュ頂点
    ウェイトを持つ)ソース骨が同じdonor骨へ写像されると、`remap_vertex_
    groups()`の"ADD"合成で重みが合算され、`sway_source_gate.
    check_bone_weights()`の値一致検査が構造的にFAILする
    (`sway_source_gate.py`モジュールdocstring「頂点ウェイトは単純な
    コピー」参照——1:1のときだけ値一致が保証される)。

    remap実行前に(実メッシュを読まず)`donor_of`(骨名->donor骨名)と
    `weighted_bones`(step01スナップショットで非空の重みを持つと分かって
    いる骨名の集合)だけから予測できるため、`place_hub_donor_chains()`
    直後・remap実行前の縮退ループ内で使う。

    `expected_merge_groups`(dev#1551 chain-length-fit WP追加):
    `sway_hub.merged_weight_groups(wiring)`が返す、`fit_chain_to_length()`
    が**意図的に**先端マージした元ボーン名の集合たち。検出した衝突が
    このいずれかの**部分集合**(⊆)なら、バグではなく本WPの正規機構
    (節数フィット、ウェイトの合算は意図した挙動)なのでFAILから除外する
    ——完全一致ではなく部分集合判定にしているのは、マージグループには
    無ウェイトの元要素(`_end`合成マーカー等)も混ざりうり、その場合
    `weighted_bones`によるフィルタで実際に衝突と検出される集合が
    マージグループそのものより小さくなるため(実データ確認: 3要素の
    マージグループのうち無ウェイトの1要素を除いた2要素だけが衝突として
    現れるケース、dev#1551実機検証)。それ以外の(意図しない)衝突は
    従来どおり検出する。

    戻り値: {donor骨名: [衝突する複数のソース骨名, ...]}(2件未満の
    donorは衝突ではないため含まない。`expected_merge_groups`のいずれかに
    部分集合として含まれるものも含まない)。"""
    by_donor: Dict[str, List[str]] = {}
    weighted = set(weighted_bones)
    for bone, donor in donor_of.items():
        if not donor or bone not in weighted:
            continue
        by_donor.setdefault(donor, []).append(bone)
    out: Dict[str, List[str]] = {}
    for donor, bones in by_donor.items():
        if len(bones) < 2:
            continue
        bone_set = frozenset(bones)
        if any(bone_set <= group for group in expected_merge_groups):
            continue
        out[donor] = sorted(bones)
    return out


# =====================================================================
# 除外の適用: lab_assignments構築
# =====================================================================

def build_lab_overrides(
    unit_keys: Iterable[str],
    existing: Optional[Mapping[str, sway_allocator.LabAssignment]] = None,
) -> Dict[str, sway_allocator.LabAssignment]:
    """`unit_keys`(除外対象、これまでの累積分含む)を全て`enabled=False`の
    `LabAssignment`として登録した辞書を返す(`existing`があれば複製して
    追加、呼び出し側の累積ループで使う)。"""
    out: Dict[str, sway_allocator.LabAssignment] = dict(existing or {})
    for key in unit_keys:
        out[key] = sway_allocator.LabAssignment(style="", enabled=False)
    return out


def all_unit_keys(plan: sway_allocator.AllocationPlan) -> FrozenSet[str]:
    """`plan.all_units`全件のkeyを返す(縮退の限界(sway全OFF)に達したとき、
    「まだ除外していない残りの採用候補」を洗い出すのに使う)。"""
    return frozenset(u.key for u in plan.all_units)


_CAPACITY_OVERFLOW_REASON_PREFIX = "容量超過で非採用"  # sway_allocator.allocate()の固定文言


def exclusion_entries_for_capacity_overflow(
    plan: sway_allocator.AllocationPlan,
) -> List[ExclusionEntry]:
    """dev#1551(hub廃止・1chain=1KP、2026-08-17オーナー裁定)受入ゲート3
    「容量あふれ鎖は完全に無傷で残す(配線しない・削除しない・座標を
    動かさない)...sway_degradeの帰属記録に載せる」の実装。

    `plan`(通常は`lab_assignments`無しで再計算した「degrade loop実行前」
    相当の`AllocationPlan`——呼び出し側`pipeline\\blender\\step02_retarget.py`
    が既に`sway_degrade_total_units`算出のために同じ形で再計算している値を
    再利用する)の`rejected_units`のうち、`sway_allocator.allocate()`が
    付ける固定理由文言「容量超過で非採用: <anchor>」で非採用になった
    unitだけを`STAGE_CAPACITY_OVERFLOW`の`ExclusionEntry`へ変換する。

    **degrade loopのゲート失敗/システミック無効化とは独立の集合**:
    `lab_assignments`無しで計算した`plan`を渡す前提のため、degrade loopが
    後から動的に除外したunitはそもそもこの`plan`では最初から採用されて
    おり(容量超過ではない)、ここには現れない——二重計上は起きない。"""
    out: List[ExclusionEntry] = []
    for u in plan.rejected_units:
        if u.excluded_reason and u.excluded_reason.startswith(_CAPACITY_OVERFLOW_REASON_PREFIX):
            out.append(make_exclusion_entry(
                u.key, STAGE_CAPACITY_OVERFLOW, u.excluded_reason))
    return out


# =====================================================================
# sway_exclusions.json スキーマ
# =====================================================================

@dataclass
class ExclusionReport:
    gender: str
    total_units: int
    fully_disabled: bool
    excluded: Tuple[ExclusionEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, object]:
        return {
            "format": FORMAT,
            "gender": self.gender,
            "total_units": self.total_units,
            "fully_disabled": self.fully_disabled,
            "excluded": [e.to_dict() for e in self.excluded],
        }


def explains_zero_chains(report: Mapping[str, object]) -> bool:
    """preflight側(`preflight_pak.py`)向け: パース済みの`sway_exclusions_
    {gender}.json`(1件)が、「揺れ源は入力に存在したが、意図的な縮退の
    結果として最終的に0鎖になった」ことを正しく説明しているかどうかを
    機械判定する。

    `_had_sway_source_input(job)`がTrue(=揺れ源はある)なのにpakへ
    揺れ鎖が1本も乗らなかった場合、G3b/G15のfail-closed化(#1546、
    dev#1508 W1b)は本来これをFAIL(「配線結果が0鎖」という無言の欠落=
    dev#1508バグそのもの)として扱う。本関数がTrueを返す場合に限り、
    その特定のケースを「縮退として正当」と認めてよい——**"fully_disabled"
    フラグが立っているときだけ**(=縮退ループが実際に「これ以上リトライ
    しても直らない」と判定してsway全体を意図的にOFFへ倒した、laneI
    指示書の想定シナリオ)。

    `total_units`が0(=そもそも揺れ源ユニットが1件も無かった)場合は
    「揺れ源が無かった」に相当するため、そもそも`_had_sway_source_input`
    がFalseになるはずで本関数を呼ぶ必要は無い——念のためTrueを返す
    (縮退不要=常に正当)。"""
    if not report:
        return False
    if int(report.get("total_units", 0)) <= 0:
        return True
    return bool(report.get("fully_disabled", False))


# =====================================================================
# ユーザー向けログ(WARN)
# =====================================================================

def format_warn_line(entry: ExclusionEntry) -> str:
    """1鎖1行のWARN文言(ユーザーの「ログをコピー」に載る書式)。

    診断ログは英語固定(dev#29「診断ログ完全英語固定」裁定、
    `tests\\diag_log_lint\\test_no_japanese_diagnostic_logs_dev1282.py`が
    機械検査する)。laneI指示書「2. 可視化」節の趣旨(「この揺れ鎖は今回は
    揺れません」)は英語で表現し、アバターを咎める表現を使わない
    ("excess"/"invalid"/"broken"等、壊れている・不正だと決めつける語を
    避ける——単に「今回は動かない」という中立的な事実だけを述べる)。"""
    kind = {"pb": "PhysBone", "sb": "SpringBone"}.get(entry.source, entry.source)
    return (f"[sway-degrade] this sway chain will not sway this time: "
            f"{kind} anchor={entry.anchor!r} (unit={entry.unit_key!r}, "
            f"stage={entry.stage}) -- {entry.reason}")


def format_warn_lines(entries: Sequence[ExclusionEntry]) -> List[str]:
    return [format_warn_line(e) for e in entries]
