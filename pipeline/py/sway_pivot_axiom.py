# -*- coding: utf-8 -*-
"""sway_pivot_axiom.py -- オーナー制定公理(2026-08-16)の検査(dev#1508
hubwire final)。

正本(オーナー原文): 「揺れものの支点は、その親humanoidボーンに対して、
あらゆる揺れや姿勢の影響に関係なく相対位置は一切変わらない」。

「支点」= 揺れ鎖のanchor骨(PBのroot骨、耳根元等の最初の可動骨)。
「親humanoidボーン」= anchorの祖先walk(`build_group_targets()`と同じ規約)で
見つかる、標準ヒューマノイド骨(pal_map/group_targetsに載っている最初の祖先)。

本モジュールはbpy非依存の純粋比較ロジックのみを持つ(`sway_source_gate.py`と
同じ設計方針——重い処理・実測値取得はBlender/ダンプ側、判定はここ)。

## 計算する量

支点の親ローカル座標系での相対位置ベクトル:
    relative_vector(pivot_world_pos, parent_world_pos, parent_world_quat)
        = parent_world_quat^-1 * (pivot_world_pos - parent_world_pos)

親の回転を打ち消した(=親から見て支点がどこにあるか)ベクトル。親の位置・
回転が変わっても(全身が動いても)、支点が親に対して剛体的に固定されて
いれば、このベクトルは不変であるはず——それが公理の主張そのもの。

## 経路ごとの当てはめ(呼び出し側の責務、モジュールdocstring外)

- step01→step02(静的・異なるアーマチュア間比較): `avatar_arm`(アバター
  自身のリグ)の支点/親と、`pal_arm`(Palworld標準リグ)のdonor(支点)/
  anchor_pal(親)を比較する。**親の回転は使わない**(`relative_vector()`
  の`parent_world_quat`引数を省略=恒等)——2026-08-16実データ検証
  (flatHaori再変換)で発見・訂正: avatar_arm側の親骨とpal_arm側の親骨は
  **別々のアーマチュアの別々の骨**であり、ローカル回転規約(bone roll)が
  互いに無関係(`chibi_fit_armature()`は位置のみ移動し回転は一切変えない
  設計)。親の回転で相対ベクトルを「親ローカル座標系」へ投影すると、
  回転規約の食い違いそのものが見かけ上の大きなズレ(実測: 全pivotが
  「同じ大きさ・別の軸」に系統的にズレる、90度級)として現れ、誤FAILする
  ——位置(head)はitem1のexact-bone-copy設計により両アーマチュア間で
  直接比較可能な値になっているため、恒等回転(world座標系のまま)の比較
  で足りる。
- pak(メッシュ側RefSkeleton基準): ビルド済みSKのRefSkeletonから同様に
  位置ベースで計算(dev#1508 hubwire final「既存donor骨の親上書き」修正後、
  正しい親を持つことが前提)。
- ダンプ(実機、全フレーム、2026-08-16オーナー設計注意、**動的・同一
  skeleton内比較**): 上記の静的比較とは違い、こちらは**同じpal_arm/共有
  Skeleton内**で時系列比較するため、親の回転規約の食い違いという問題は
  起きない——親の実際の姿勢変化(揺れ・アニメーション)を打ち消して
  「親から見た支点の位置」が時間不変であることを検査する、という
  `parent_world_quat`本来の用途どおりに使ってよい。また**ハブ骨を経由
  しない**——ハブは新設・無ウェイト骨でダンプに記録されない可能性が高い
  (原点落ち・欠測が正常、DUMP_ARTIFACT名簿に記録されるだけでFAILにしない)。
  支点(donor(anchor))と親humanoidボーン(例: head)は両方とも実ウェイトを
  持つ通常骨のはずなので、ダンプへ確実に記録される——この2点間だけを
  直接測る設計にすることで、ハブの欠測に一切依存しない。

基準(baseline)は呼び出し側が用意する「なるべく早い段階の忠実な実測値」
(`sway_source_gate.py`の位置比較と同じ理由でstep01の生座標そのものではなく
「donor配置直前のavatar_arm実測値」を使う——両モジュールとも同じ座標系
問題を抱えるため、同じ解決策を踏襲する)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

TAG = "sway_pivot_axiom"

# 位置epsilon: sway_source_gate.pyのEPS_POSと同一の根拠(Blender内部float32
# 精度+複数回の行列演算の蓄積誤差を安全側に見た値)。この検査もBlenderの
# world<->local変換を経由するため同じマージンを踏襲する。
EPS_REL_POS = 1e-4


# ------------------------------------------------------------------ quat/vec
# (bpy非依存モジュール間の意図的重複実装、sway_hub_placement.py/
# sway_source_gate.pyのモジュールdocstring「言語方針」節と同じ流儀)

def _q_conj(q: Sequence[float]) -> Tuple[float, float, float, float]:
    x, y, z, w = q
    return (-x, -y, -z, w)


def _q_rotate(q: Sequence[float], v: Sequence[float]) -> Tuple[float, float, float]:
    x, y, z, w = q
    vx, vy, vz = v
    uvx = y * vz - z * vy
    uvy = z * vx - x * vz
    uvz = x * vy - y * vx
    uuvx = y * uvz - z * uvy
    uuvy = z * uvx - x * uvz
    uuvz = x * uvy - y * uvx
    return (
        vx + 2.0 * (w * uvx + uuvx),
        vy + 2.0 * (w * uvy + uuvy),
        vz + 2.0 * (w * uvz + uuvz),
    )


def _v_sub(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _v_len(a: Sequence[float]) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


# ------------------------------------------------------------------ 公理計算

def relative_vector(
    pivot_world_pos: Sequence[float],
    parent_world_pos: Sequence[float],
    parent_world_quat: Sequence[float] = (0.0, 0.0, 0.0, 1.0),
) -> Tuple[float, float, float]:
    """支点の、親ローカル座標系での相対位置ベクトル(モジュールdocstring
    参照)。`parent_world_quat`省略時(恒等)は「親のワールド回転を無視した
    素の差ベクトル」になる——親骨のワールド回転を実測できない/意味を
    持たない経路(例: ダンプが位置のみ提供する場合)向けのフォールバック。
    """
    diff = _v_sub(pivot_world_pos, parent_world_pos)
    return _q_rotate(_q_conj(tuple(parent_world_quat)), diff)


@dataclass
class PivotCheckResult:
    pivot: str
    parent: str
    ok: bool
    distance: float
    baseline_vec: Tuple[float, float, float]
    observed_vec: Tuple[float, float, float]
    reason: str = ""


def check_pivot_invariant(
    pivot: str, parent: str,
    baseline_vec: Sequence[float], observed_vec: Sequence[float],
    eps: float = EPS_REL_POS,
) -> PivotCheckResult:
    """基準ベクトルと観測ベクトルの距離がeps以内であることを検査する。"""
    d = _v_len(_v_sub(observed_vec, baseline_vec))
    ok = d <= eps
    reason = "" if ok else (
        f"pivot {pivot!r} relative to parent {parent!r} moved {d:.6f} "
        f"(tolerance {eps}) -- baseline={list(baseline_vec)} "
        f"observed={list(observed_vec)} (violates the rigid-pivot axiom: "
        "支点の対親相対位置は不変でなければならない)")
    return PivotCheckResult(
        pivot=pivot, parent=parent, ok=ok, distance=d,
        baseline_vec=tuple(baseline_vec), observed_vec=tuple(observed_vec),
        reason=reason)


@dataclass
class PivotAxiomReport:
    results: Tuple[PivotCheckResult, ...]

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def failed(self) -> Tuple[PivotCheckResult, ...]:
        return tuple(r for r in self.results if not r.ok)

    def summary_lines(self) -> List[str]:
        lines = [f"sway_pivot_axiom: {len(self.results)} pivot(s) checked, "
                 f"{len(self.failed)} FAILED"]
        for r in self.failed:
            lines.append(f"  FAIL {r.reason}")
        return lines


def resolve_anchor_parent_avatar_names(
    anchors: Sequence[str],
    pal_map: Mapping[str, str],
    avatar_bone_parent: Mapping[str, Optional[str]],
) -> Dict[str, str]:
    """`build_group_targets()`と同一の祖先walk規約(標準骨に載っている
    最初の祖先を探す)で、各anchorの「親humanoidボーン(アバター側の実名)」
    を解決する。`avatar_bone_parent`: {アバター骨名 -> 親骨名 or None}
    (`avatar_arm.data.bones`から呼び出し側が組み立てる、bpy非依存にする
    ためプレーンなdictで受け取る——`pipeline\\blender\\step02_retarget.py`
    の`source_parent_of`と同じ形)。

    `pal_map`: `pipeline\\blender\\vp_bl.humanoid_map_from_json()`と同じ
    契約({パルボーン名 -> アバター側の実ボーン名}——**キーがパル名、
    値がアバター名**であることに注意。`build_group_targets()`は内部で
    `inv = {v: k for k, v in pal_map.items()}`と反転してから使う
    (「実ボーン名→パル名」)——本関数も同じ反転を行い、`cur`(アバター側の
    骨名を辿る変数)を`pal_map`の**値の集合**(アバター側の実名)と照合する
    (キー側=パル名と誤って照合すると、アバター側の生名がたまたまパル名
    文字列と一致しない限り一切解決できない——2026-08-16実データ検証
    (flatHaori再変換、pivot axiom 0/0)で発見した実装ミスの直接記録)。

    `build_group_targets()`との違い: あちらはbone.name自身が標準骨で
    あれば自分自身を返す(retarget先の解決)が、本関数は**支点自身では
    なく親**を求めるため、bone.parentから探索を開始する(自分自身が
    標準骨であっても意味が無い——支点は定義上「揺れる最初の可動骨」であり
    標準骨ではないはずだが、万一標準骨をanchorに持つ変則ケースでも、
    「親」を素直にたどる一貫した挙動にする)。

    解決できないanchor(祖先を辿っても標準骨に到達できない、またはavatar_
    bone_parentに存在しない)は戻り値に含めない(呼び出し側が対象から
    除外する、既存のsway_hub「anchor未解決」フォールバックと同じ設計)。"""
    standard_avatar_names = set(pal_map.values())
    out: Dict[str, str] = {}
    for anchor in anchors:
        cur = avatar_bone_parent.get(anchor)
        seen = set()
        while cur is not None and cur not in standard_avatar_names:
            if cur in seen:
                break  # 循環参照防御(構造的に起きないはずだが安全側)
            seen.add(cur)
            cur = avatar_bone_parent.get(cur)
        if cur is not None and cur in standard_avatar_names:
            out[anchor] = cur
    return out


def run_pivot_axiom_gate(
    anchor_parent_of: Mapping[str, str],
    baseline_positions: Mapping[str, Sequence[float]],
    baseline_rotations: Mapping[str, Sequence[float]],
    observed_positions: Mapping[str, Sequence[float]],
    observed_rotations: Mapping[str, Sequence[float]],
    eps: float = EPS_REL_POS,
) -> PivotAxiomReport:
    """`anchor_parent_of`({pivot骨名 -> 親骨名}、`resolve_anchor_parent_avatar_names()`
    等が用意)の各pivotについて、baseline(基準)側とobserved(観測)側それぞれで
    `relative_vector()`を計算し、`check_pivot_invariant()`で比較する。

    baseline_positions/observed_positions: {骨名 -> world head [x,y,z]}。
    baseline_rotations/observed_rotations: {骨名 -> world quat [x,y,z,w]}
    (無ければ恒等回転にフォールバック——`relative_vector()`のdocstring
    「ダンプが位置のみ提供する場合」参照)。

    pivot/parentどちらかの位置が見つからない場合はスキップする(呼び出し側の
    データ欠落を機械的に無視——FAILにはしない。存在確認自体は呼び出し側
    (例: DUMP_ARTIFACT名簿・ghost_bones除外)の責務であり、本関数は
    「両方揃っているものだけ」を検査する)。"""
    results: List[PivotCheckResult] = []
    for pivot, parent in anchor_parent_of.items():
        bp = baseline_positions.get(pivot)
        pp = baseline_positions.get(parent)
        op = observed_positions.get(pivot)
        opp = observed_positions.get(parent)
        if bp is None or pp is None or op is None or opp is None:
            continue
        bq = baseline_rotations.get(parent, (0.0, 0.0, 0.0, 1.0))
        oq = observed_rotations.get(parent, (0.0, 0.0, 0.0, 1.0))
        baseline_vec = relative_vector(bp, pp, bq)
        observed_vec = relative_vector(op, opp, oq)
        results.append(check_pivot_invariant(pivot, parent, baseline_vec,
                                              observed_vec, eps=eps))
    return PivotAxiomReport(results=tuple(results))
