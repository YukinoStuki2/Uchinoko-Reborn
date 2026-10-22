# -*- coding: utf-8 -*-
"""sway_native_rule.py -- donor家系選定の「実シミュレーション骨n+1規則」
(dev#19 native-donor-rule WP、issue #19、issue #19 2026-08-14 12:10コメント
「恒久ルール」)。

## 根因(2026-08-14夜、issue #19コメントより)

KawaiiPhysicsのInitModifyBones()は鎖構築時に**共有USkeletonアセット
(SK_PalHuman_Skeleton)のRefSkeletonを参照する**。このアセットに実際に登録
されている("native"な)ボーン数を超えてウェイトを乗せても、超えた分は
一度も物理に入らない。さらにKPは鎖の**終端骨の回転を毎フレームbind姿勢へ
固定する**仕様(ApplySimulateResult)があるため、native境界ぎりぎりまで
ウェイトを乗せると「終端の実ウェイト骨が凍結する」という視認可能な破綻に
つながる(尻尾=tail_05、耳(旧構成)=ear_04で実際に発生)。

## 恒久ルール(オーナー裁定、2026-08-14夜、issue #19コメント原文)

donor選定は「親一致」かつ「実シミュレーション対象骨(Skeletonアセット
登録済みネイティブ骨)で数えて転写元n+1本以上」。捏造骨での不足糊塗は禁止
(シミュレーションに入らない)。

**weighted本数の上限は native_sim_count − 1**(2026-08-14夜、オーナー最終
訂正: 当初−2案は「耳native=5」という誤った前提に基づいており、実測native=4
かつ現行耳構成(weighted3/native4、マージン1)が官能合格したことで根拠が
崩れた。機構的にも回転凍結で腐るのは終端骨そのものだけであり、終端−1の
関節は健康な終端骨の位置から再構成されるため無事——マージン1本で十分)。

## n_donor cap の副作用範囲(重要な非対称性)

ウェイト転写先決定の実呼び出し経路は2種類あり、cap(donor本数の絞り込み)に
対する挙動が異なる:

- **`sway_cloth_weight_targets_direct()`**(pipeline\\blender\\
  step02_retarget.py、明示job指定=family_name経路が使う「シンプルに1対1」
  割当): n_source <= n_donor の間は常に恒等写像`[0,1,...,n_source-1]`を
  返すため、n_donorをnative_sim_count-1へcapしてもn_source<=native_sim_count-1
  (=qualifies()成立)である限り**副作用が無い**。本モジュールの
  `cap_chain()`はこの関数を使う呼び出し元(resolve_sway_chain_entries()の
  family_name分岐)から**常に**適用してよい。
- **`sway_cloth_bone_targets()`/`sway_cloth_target_indices()`**
  (pipeline\\py\\sway_assign.py 自動割当エンジンが使う比例配分): n_donorの
  値そのものが配分結果に影響する(`round(i * n_donor / n_source)`)ため、
  cap は**qualifiesしない(fallback)donorに対してのみ**適用すること。
  qualifiesする通常経路でcapを掛けると、無関係な既存の比例配分結果まで
  変えてしまう(無退行を壊す)。sway_assign.py側の呼び出し元はこの非対称性を
  踏まえ、`qualifies(native_sim_count, n_source)`がFalseのdonorに限って
  `cap_chain()`(またはn_donor相当の絞り込み)を適用する設計とする。

本モジュールはbpy非依存の純粋関数のみ(pytest単体で検証可能)。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple


def qualifies(native_sim_count: Optional[int], n_source: int) -> bool:
    """native_sim_countがn_source+1本以上あるか(規則の核心条件)。
    native_sim_countがNone(未計測/未登録)なら常にFalse(安全側)。"""
    return native_sim_count is not None and native_sim_count >= n_source + 1


def pick_family(
    candidates: Sequence[Tuple[str, Optional[int]]],
    n_source: int,
    requested: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """donor家系を選ぶ(親一致で絞り込み済みの候補プールを受け取る想定)。

    candidates: [(family_name, native_sim_count), ...]。呼び出し側が既に
      「親一致」(anchor match)でフィルタ済みであること(本関数は親の概念を
      知らない、純粋な選定ロジックのみ)。

    戻り値: (chosen_family_name, warning_message_or_None)。

    選定順位:
      1. requestedが指定され、かつcandidatesに含まれ、かつqualifies()なら、
         そのままrequestedを採用(警告なし——明示指定が規則を満たす通常
         ケース)。
      2. qualifies()する候補が1件以上あれば、その中で最小のnative_sim_count
         (=節数を必要以上に無駄にしない、決定的タイブレークは名前の昇順)
         を選ぶ。requestedと異なればauto-correct警告を返す。
      3. qualifiesする候補が無ければ、candidates全体の中でnative_sim_count
         最大の家系へフォールバックし、warningを返す(「weighted本数は
         native_sim_count-1に制限される」旨を含む——実際の制限適用は
         呼び出し側がcap_chain()を通すこと)。
      4. candidates自体が空ならrequestedをそのまま返す(判定不能、安全側で
         素通し。既存呼び出し元の無退行のため——親一致候補が1件も無い状況は
         本規則の対象外)。
    """
    if not candidates:
        return requested, None

    by_name = dict(candidates)
    if requested is not None and requested in by_name and qualifies(by_name[requested], n_source):
        return requested, None

    qualified: List[Tuple[str, int]] = [
        (name, cnt) for name, cnt in candidates if qualifies(cnt, n_source)
    ]
    if qualified:
        chosen_name, chosen_cnt = min(qualified, key=lambda t: (t[1], t[0]))
        warning = None
        if requested is not None and requested != chosen_name:
            warning = (
                f"sway donor native rule: requested family {requested!r} does not satisfy "
                f"native_sim_count>=n_source+1 (n_source={n_source}); "
                f"auto-corrected to {chosen_name!r} (native_sim_count={chosen_cnt})"
            )
        return chosen_name, warning

    fallback_name, fallback_cnt = max(candidates, key=lambda t: ((t[1] if t[1] is not None else -1), t[0]))
    weighted_cap = max(0, (fallback_cnt or 0) - 1)
    warning = (
        f"sway donor native rule: no candidate family satisfies native_sim_count>=n_source+1 "
        f"(n_source={n_source}); falling back to {fallback_name!r} "
        f"(native_sim_count={fallback_cnt}), weighted bones capped to {weighted_cap}"
    )
    return fallback_name, warning


def cap_chain(chain: Sequence[str], native_sim_count: Optional[int]) -> List[str]:
    """donor chain(ボーン名列)を native_sim_count-1 本までに切り詰める。

    native_sim_countがNone(未計測)なら無変更(そのままlist化して返す、
    安全側=既存呼び出し元の無退行)。切り詰めにより空になる場合でも、
    捏造・水増しはしない(単に短いリストを返す。呼び出し側の既存の
    n_donor<=0安全網に委ねる)。

    常にこの1本の関数で「qualifiedな場合もfallbackな場合も同じcapを適用する」
    (モジュールdocstring参照、n_source<=native_sim_count-1の前提下では
    capは既存の比例配分ロジックに対して副作用が無いことが保証される)。
    """
    chain = list(chain)
    if native_sim_count is None:
        return chain
    limit = max(0, native_sim_count - 1)
    return chain[:limit]
