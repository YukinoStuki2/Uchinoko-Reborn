# -*- coding: utf-8 -*-
"""sway_hub_placement.py -- 汎用ハブ配線の座標配置(dev#1508 W2a-2、
issue https://github.com/pandrabox/DiveToPalworld-dev/issues/1508)。

正本仕様: `.devonly\\docs\\sway\\sway_wrapup\\SPEC.md` §5「工事項目」(ハブ設計規則)。指揮者
指示書「本体」項目1(座標配置): 前任(`work\\wp_w2a2_hub\\PROGRESS.md`)が
確立した「採用鎖のUnity実座標へドナー骨を配置」の数学を製品コード化する。

## 出所

`work\\rd_1423_haori_full2\\scripts\\compute_umbrella_transforms.py`(full3の
座標配置数学、実機playtestまで検証済み)の**exact-bone-copy**アルゴリズムを
無改変で移植し、単一固定ハブ(`F_Kigurumi001_tail_01`)専用だった構造を
`sway_hub.HubWiringPlan`(複数ハブ・複数鎖・性別対応)向けに一般化した。
quat/vecの基礎演算は`pipeline\\blender\\step02_retarget.py`の`_q_mul`等と
同一規約(Hamilton積、(x,y,z,w)、親→子=a*b)——bpy非依存モジュール間の
意図的重複実装(2026-07-28言語方針、compute_umbrella_transforms.pyの
コメントを踏襲)。

## ハブroot自身の配置(SPEC §5「rootの置き場所は親骨と同位置で機械決定」)

ハブroot骨(`GroupHubPlan.hub_root_female`/`hub_root_male`)は、対応する
グループの実アバター側アンカー(`SwayGroup.anchor`)が retarget 先で
対応するPALボーン名(`anchor_pal_name_of`、呼び出し側が用意する既存の
リターゲットマップ)へ、**恒等ローカル変換**(=親と完全同位置)で
reparentする——アバター幾何に依存しない機械決定(SPEC原文どおり)。

## donor鎖の配置(exact-bone-copy)

各`ChainDonorPlan.donor_chain_for(gender)`(root_bone配下に一直線で連なる
donor骨列、bivariantなハブスロットでは性別ごとに互いに素——dev#1551性別
またぎdedup漏れ修正、`sway_hub.ChainDonorPlan.donor_chain_for()`docstring
参照)は、
ハブの確定worldトランスフォーム(reparent後の位置=anchor_pal_nameのcatalog
FK位置)を起点に、`ChainDonorPlan.source_chain`(アバターの実PB/SB鎖)の
実世界座標を`avatar_dump`(UEコンポーネント空間、pre-scale生値。step02側の
将来のダンプ関数が書き出す想定のフォーマット、`compute_umbrella_transforms.py`
の`avatar_world_dump.json`と同一契約)から読み、pelvis/head基準の相似変換
(`compute_similarity`)で共有Skeletonの座標系へ写像したうえで、
`resolve_grouped_chain()`(dev#1572夜間便2: `sway_hub.donor_group_members()`
経由でフィット計画のグループ境界=塊の先頭骨head〜末尾骨tailを反映、
余剰donorは最終セグメント方向へ延長)で各節のworld位置・向きを決める
(旧`place_chain()`は単体テスト用に残置、本経路では未使用)。

出力は`sway_shared_skeleton.ReparentStep`のリスト(ハブ1本+donor全本)——
そのまま`sway_shared_skeleton.apply_reparent_chain()`へ渡せる。

## 本モジュールがまだ担わないもの

`avatar_dump`の実際のダンプ処理(Blender側、avatar_arm.pose.bonesを走査して
UEコンポーネント空間へ書き出す)と`anchor_pal_name_of`(アバターボーン名->
PALボーン名のリターゲットマップ)の組み立ては、`pipeline\\blender\\
step02_retarget.py`側(bpy依存)の仕事——本モジュールは両方とも呼び出し側が
用意した入力として受け取るだけ(bpy非依存、単体テスト可能)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import sway_hub
import sway_shared_skeleton

TAG = "sway_hub_placement"

IDENTITY_TRANSFORM: Tuple[Tuple[float, float, float, float],
                          Tuple[float, float, float],
                          Tuple[float, float, float]] = (
    (0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0))


class SwayHubPlacementError(RuntimeError):
    """座標配置計画の想定外エラー(黙って握り潰さず変換全体を止めるための
    シグナル、sway_hub.SwayHubError/sway_shared_skeleton.SharedSkeletonError
    と同じ設計方針)。"""


# =====================================================================
# quat/vec基礎演算(bpy非依存の意図的重複実装、モジュールdocstring参照)
# =====================================================================

def q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def q_conj(q):
    x, y, z, w = q
    return (-x, -y, -z, w)


def q_rotate(q, v):
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


def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def v_len(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def v_normalize(a):
    n = v_len(a)
    if n < 1e-12:
        return (1.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def q_find_between(a, b):
    dot = max(-1.0, min(1.0, v_dot(a, b)))
    if dot < -0.999999:
        axis = v_cross((1.0, 0.0, 0.0), a)
        if v_len(axis) < 1e-6:
            axis = v_cross((0.0, 1.0, 0.0), a)
        axis = v_normalize(axis)
        return (axis[0], axis[1], axis[2], 0.0)
    half = v_normalize(v_add(a, b))
    axis = v_cross(a, half)
    w = v_dot(a, half)
    return (axis[0], axis[1], axis[2], w)


def build_donor_chain_quats(dirs):
    quats = []
    prev_dir = None
    prev_q = None
    for raw in dirs:
        d = v_normalize(raw)
        if prev_q is None:
            q = q_find_between((1.0, 0.0, 0.0), d)
        else:
            delta = q_find_between(prev_dir, d)
            q = q_mul(delta, prev_q)
        quats.append(q)
        prev_dir = d
        prev_q = q
    return quats


# =====================================================================
# 共有Skeleton FK(vanilla rest pose、ハブ/アンカーのworld位置算出用)
# =====================================================================

@dataclass(frozen=True)
class CatalogFk:
    """`sway_hub.SkeletonCatalog`のFK展開結果(vanilla restのworld
    位置・向き)。"""

    world_pos: Tuple[Tuple[float, float, float], ...]
    world_quat: Tuple[Tuple[float, float, float, float], ...]


def build_catalog_fk(catalog: sway_hub.SkeletonCatalog) -> CatalogFk:
    bones = catalog.bones
    n = len(bones)
    world_pos: List[Optional[Tuple[float, float, float]]] = [None] * n
    world_quat: List[Optional[Tuple[float, float, float, float]]] = [None] * n
    for i, b in enumerate(bones):
        p = b["parent_idx"]
        lp = tuple(b["pos"])
        lq = tuple(b["quat"])
        if p < 0:
            world_pos[i] = lp
            world_quat[i] = lq
        else:
            wp = world_pos[p]
            wq = world_quat[p]
            rp = q_rotate(wq, lp)
            world_pos[i] = v_add(wp, rp)
            world_quat[i] = q_mul(wq, lq)
    return CatalogFk(world_pos=tuple(world_pos), world_quat=tuple(world_quat))


# =====================================================================
# アバター側similarity変換(pelvis/head基準)
# =====================================================================

@dataclass(frozen=True)
class Similarity:
    scale: float
    avatar_hips_raw: Tuple[float, float, float]
    pal_pelvis_world: Tuple[float, float, float]


def compute_similarity(
    avatar_dump: Mapping[str, Mapping[str, Sequence[float]]],
    catalog: sway_hub.SkeletonCatalog, fk: CatalogFk,
    hips_avatar_name: str = "Hips", head_avatar_name: str = "Head",
    hips_pal_name: str = "pelvis", head_pal_name: str = "head",
) -> Similarity:
    """`global_scale_and_place()`と同じ一様スケール+並進(pelvis基準)の
    相似変換を、avatar_dump(生のUEコンポーネント空間座標、pre-scale)と
    共有Skeletonのpelvis/head FK位置から算出する。"""
    av_hips = avatar_dump.get(hips_avatar_name)
    av_head = avatar_dump.get(head_avatar_name)
    if av_hips is None or av_head is None:
        raise SwayHubPlacementError(
            f"avatar_dump missing required anchor bone(s): "
            f"{hips_avatar_name!r}/{head_avatar_name!r}")
    av_hips_pos = tuple(av_hips["head"])
    av_head_pos = tuple(av_head["head"])
    av_len = v_len(v_sub(av_head_pos, av_hips_pos))
    if av_len < 1e-9:
        raise SwayHubPlacementError(
            "degenerate avatar hips/head distance (~0) -- cannot compute similarity")
    try:
        pal_pelvis_idx = catalog.index_of(hips_pal_name)
        pal_head_idx = catalog.index_of(head_pal_name)
    except KeyError as e:
        raise SwayHubPlacementError(f"catalog missing anchor bone: {e}") from e
    pal_pelvis = fk.world_pos[pal_pelvis_idx]
    pal_head = fk.world_pos[pal_head_idx]
    pal_len = v_len(v_sub(pal_head, pal_pelvis))
    s = pal_len / av_len
    return Similarity(scale=s, avatar_hips_raw=av_hips_pos, pal_pelvis_world=pal_pelvis)


def av_world(avatar_dump, sim: Similarity, name: str, use_tail: bool = False):
    b = avatar_dump.get(name)
    if b is None:
        return None
    raw = tuple(b["tail"] if use_tail else b["head"])
    return v_add(v_scale(v_sub(raw, sim.avatar_hips_raw), sim.scale), sim.pal_pelvis_world)


# =====================================================================
# 鎖1本ぶんの配置(exact-bone-copy)
# =====================================================================

def resolve_source_chain(avatar_dump, sim: Similarity, source_chain: Sequence[str],
                          anchor_name: str):
    """`source_chain`(アバター実PB/SB鎖、compute_umbrella_transforms.pyと
    同じ規約でanchor自身を含まない)から実座標を引ける点列を返す。

    末尾が"_end"合成マーカー(FBX慣習のPhysBoneチェーン終端tip、実ポーズ
    ボーンとしては存在しない)で、かつavatar_dumpに実在しない場合は
    trimする(step02_retarget.pyのtail-end-marker WPと同じ規約)。

    退化ケース(chainから1点も実座標を引けない——`resolve_source_chain`が
    "<anchor>_end"1個だけの合成鎖しか持たない等): `anchor_name`
    (このグループの`SwayGroup.anchor`、PBコンポーネント自身のTransform、
    実際にavatar_dumpに実在するはず)を単独の点として使い、そこから
    小さく(+Z 2cm)延長したtipを合成する(構造的事実の忠実な反映、
    値の捏造ではない——compute_umbrella_transforms.pyのHIPS004_ANCHOR
    特別扱いを、全アンカーに対する一般規則へ格上げしたもの)。

    戻り値: (points, tip, used_source_bones) または (None, None, sway_bones)
    (呼び出し側が全経路失敗としてエラーにする)。"""
    sway_bones = list(source_chain)
    if (len(sway_bones) >= 2 and sway_bones[-1].endswith("_end")
            and avatar_dump.get(sway_bones[-1]) is None):
        sway_bones = sway_bones[:-1]
    points = [av_world(avatar_dump, sim, n) for n in sway_bones]
    if any(p is None for p in points) or not points:
        anchor_pt = av_world(avatar_dump, sim, anchor_name)
        if anchor_pt is not None:
            tip = v_add(anchor_pt, (0.0, 0.0, 2.0))
            return [anchor_pt], tip, [f"{anchor_name} (anchor, degenerate chain)"]
        return None, None, sway_bones
    tip = av_world(avatar_dump, sim, sway_bones[-1], use_tail=True)
    return points, tip, sway_bones


def place_chain(points, tip, donor_chain: Sequence[str]):
    """donor節i<-転写元関節iのhead/tail完全コピー(n_donor>=n_source前提、
    `sway_hub.plan_hub_wiring()`がdonor_chainをsource_chainと同じ長さで
    払い出すため常に等しい——モジュールdocstring参照)。余剰donorは最終
    セグメント方向へ延長する(この一般化モジュールではn_donor==n_sourceの
    ため延長は常に0本になるが、将来donor本数がsourceを超える設計変更に
    備えて元のfull3アルゴリズムをそのまま残す)。

    戻り値: head_pts(長さ n_donor+1)、exact_tails(長さ n_source)。"""
    n_source = len(points)
    n_donor = len(donor_chain)
    if n_donor < n_source:
        raise SwayHubPlacementError(
            f"donor chain shorter than source chain: {n_donor} < {n_source} "
            "(sway_hub.plan_hub_wiring() must guarantee equal length)")
    src_heads = points
    src_tails = points[1:] + [tip]
    # dev#1551(ゼロ長root廃止修理): hub rootがsource_chain[0]を専有する
    # ようになったため、呼び出し側(`plan_reparent_steps()`)は
    # `points`にsource_chain[0]を含めない「内容写像を1つ繰り上げた」列を
    # 渡す——退化ケース(残りが1点も無い)では`points`が空リストになりうる。
    # 空の場合は`tip`自身を基準に全donorを延長する(既存のBlender側
    # `place_hub_donor_chains()`の同型フォールバックと同じ考え方)。
    last_head = src_heads[-1] if src_heads else tip
    seg_vec = v_sub(tip, last_head)
    if v_len(seg_vec) < 1e-6:
        seg_vec = (0.0, 0.0, 1.0)
    head_pts = list(src_heads)
    extend_point = tip
    for _k in range(n_donor - n_source):
        head_pts.append(extend_point)
        extend_point = v_add(extend_point, seg_vec)
    head_pts.append(extend_point)
    exact_tails = src_tails
    return head_pts, exact_tails


def resolve_grouped_chain(
    avatar_dump, sim: Similarity, cp: "sway_hub.ChainDonorPlan",
    anchor_name: str, donor_chain: Sequence[str],
):
    """dev#1572(夜間便2、issue #1572追記「フィット計画を単一ソースに」):
    `resolve_source_chain()`+`place_chain()`の置き換え——`cp.source_chain`
    (フィット後の代表骨名列)を`sway_hub.donor_group_members(cp)`
    (`cp.weight_expansion`由来のグループ境界、`sway_hub_wire.
    source_to_donor_bone_map()`と同じ単一の真実)で展開し、各donorスロット
    (`donor_chain[i]`は`cp.source_chain[i+1]`の代表グループに対応、
    `source_to_donor_bone_map()`の「hub_nameを先頭に付けてsource_chainと
    zip」規約と同一の整列)が担う実スパンを「塊の先頭骨head〜末尾骨tail」
    (`sway_hub.fit_chain_to_length()`docstring「マージ塊のdonorノード幾何」)
    として解決する。

    旧`resolve_source_chain()`+`place_chain()`の組は`cp.source_chain`の
    各代表名をそのまま「元の鎖の1点」として読んでおり、フィットで代表が
    マージ区間の末尾側へ動いても先頭側メンバーの位置を一切参照しない
    ——ウェイト側(`weight_expansion`経由)とグループ境界がズレるバグの
    温床だった(step02_retarget.pyの`place_hub_donor_chains()`と同型、
    実測はそちら側のflatapron耳donorで確認済み)。

    戻り値: (anchor_pt, donor_heads, donor_tails, used)。
    `donor_heads[i]`/`donor_tails[i]`は`donor_chain[i]`の解決済み実座標
    (Tuple[float,float,float]、常に非None——未解決/余剰donorはtipからの
    延長で埋める)。全経路で解決不能(`source_chain[0]`もanchor自身も
    引けない)場合は`(None, [], [], None)`。"""
    src = list(cp.source_chain)
    if not src:
        return None, [], [], None
    group_members = sway_hub.donor_group_members(cp)
    # dev#1572(第2便、安全域マージの全結合(実効節数1)修理): `src[0]`を
    # そのままav_worldするのは、`src[0]`の代表グループが単独(=`(src[0],)`)
    # であるとき(通常、根本がマージされていないとき)にしか正しくない。
    # `fit_chain_to_length()`の「実効節数1のときだけ根本も含めた全結合」
    # 例外(`sway_hub.fit_chain_to_length()`docstring参照)が発動すると、
    # `src[0]`(=唯一の代表)はグループの**末尾側**(先端寄り)の要素名に
    # なる(`rep = chain[-1]`)——グループの**先頭骨**(=真のanchor自身)の
    # 位置ではない。`donor_group_members(cp)[src[0]][0]`は常にそのグループの
    # 先頭骨(根元寄り)を指すため、これを経由することで通常ケース
    # (グループが単独=`members[0] == src[0]`、無変更)と全結合ケース
    # (`members[0]`=真のanchor)の両方を同じ式で正しく扱える(`resolve_
    # grouped_chain()`が`src_idx>=1`側で既にやっている「代表を単なる1点として
    # 読まず、グループ境界(`donor_group_members()`)を経由する」規約を
    # `src[0]`自身にも一貫して適用するだけ——特殊分岐の追加ではない)。
    anchor_group = group_members.get(src[0], (src[0],))
    anchor_pt = av_world(avatar_dump, sim, anchor_group[0])
    used = "source_chain[0]" if anchor_group[0] == src[0] else "source_chain[0] group head"
    if anchor_pt is None:
        anchor_pt = av_world(avatar_dump, sim, anchor_name)
        used = f"{anchor_name} (anchor, degenerate chain)"
        if anchor_pt is None:
            return None, [], [], None

    n_donor = len(donor_chain)
    donor_heads: List[Optional[Tuple[float, float, float]]] = [None] * n_donor
    donor_tails: List[Optional[Tuple[float, float, float]]] = [None] * n_donor
    for i in range(n_donor):
        src_idx = i + 1
        if src_idx >= len(src):
            continue  # 余剰donor(内容写像の対応が無い延長donor)
        rep = src[src_idx]
        members = group_members.get(rep, (rep,))
        head_pt = av_world(avatar_dump, sim, members[0])
        tail_pt = av_world(avatar_dump, sim, members[-1], use_tail=True)
        if head_pt is None:
            head_pt = av_world(avatar_dump, sim, rep)  # 退化フォールバック
        if tail_pt is None:
            tail_pt = av_world(avatar_dump, sim, rep, use_tail=True)
        donor_heads[i] = head_pt
        donor_tails[i] = tail_pt

    tip = next((t for t in reversed(donor_tails) if t is not None), None)
    if tip is None:
        tip = av_world(avatar_dump, sim, src[0], use_tail=True)
    if tip is None:
        tip = v_add(anchor_pt, (0.0, 0.0, 2.0))

    last_resolved = next((h for h in reversed(donor_heads) if h is not None), anchor_pt)
    seg_vec = v_sub(tip, last_resolved)
    if v_len(seg_vec) < 1e-6:
        seg_vec = (0.0, 0.0, 1.0)

    extend_point = tip
    for i in range(n_donor):
        if donor_heads[i] is None:
            donor_heads[i] = extend_point
            extend_point = v_add(extend_point, seg_vec)
    for i in range(n_donor):
        if donor_tails[i] is None:
            donor_tails[i] = (donor_heads[i + 1] if i + 1 < n_donor
                               else v_add(donor_heads[i], seg_vec))

    return anchor_pt, donor_heads, donor_tails, used


# =====================================================================
# ハブroot自身の実節配置(dev#1551 ゼロ長root廃止修理)
# =====================================================================
#
# 背景(issue #1551、正本 work\run_1551\laneR1_rootfix\RESULT.md、
# 2026-08-17深夜オーナー共同解析): 旧実装(PR #1560「耳付け根修正」)は
# hub root自身を「鎖始点」(=source_chain[1]、chainの最初の実sway骨)の
# 位置へ動かし、tailをhead+微小オフセット(実質ゼロ長)に固定していた
# ——「1本目のネイティブdonor(実長)を潰してゼロ長rootに転用し、アバター
# 内容を1donor下へずらして書く」設計(hub時代のn+1専用root思想の名残)。
#
# `source_chain`は`(anchor,) + chain`(SPEC §5アンカーオフバイワン修正、
# `sway_hub.ChainDonorPlan`docstring参照)であり、source_chain[0]
# (=anchor自身)は実際にメッシュの頂点ウェイトを持つ実関節(SPEC §5
# 「PBのroot骨(anchor)自身も揺れる最初の可動骨」)。旧実装ではこの
# source_chain[0]がdonor_chain[0](旧来の「1本目のdonor」)へ写されて
# いたが、hub root自身はそれとは無関係にsource_chain[1]の位置へ
# 動かされていた——結果、topology上hubの子であるdonor_chain[0]
# (source_chain[0]=anchor位置)が、親であるhub(source_chain[1]位置)より
# head側(上流)に来てしまい、1リンクずれ・7.8cm空隙・donor1本浪費・
# 可視部が異常区間へはみ出す、という壊れ方になっていた。
#
# 修理: hub root自身がsource_chain[0](anchor)のexact geometry
# (head=anchor実位置、tailの向きはsource_chain[1]方向、無ければtip方向)を
# 直接担う——ちょうど旧donor_chain[0]と同じ内容を、hub root自身が引き
# 継ぐ形。ゼロ長root概念が消え、鎖はhumanoid(anchor_pal)へ直付けされた
# まま1本目から実節になる。donor鎖側(`plan_reparent_steps()`の②ループ)は
# 内容写像を1つ繰り上げて割り当てる(source_chain[1]以降をdonor_chainへ、
# `points[1:]`を`place_chain()`へ渡すだけの変更——`sway_hub.py`側の
# トポロジ計画・donor骨名の割当は無変更)。

def select_first_resolved_hub_segment(chain_plans, resolve):
    """dev#1551(ゼロ長root廃止修理): hub root自身の実節配置
    (head点・tail方向点のペア)を、`chain_plans`の先頭から順に試し、
    最初に解決できたものを返す(bpy非依存の汎用関数、Python側/Blender側で
    共有する制御構造——`_hub_root_real_segment_transform()`(本モジュール、
    exact_donor_world優先で値を引く)とBlender側`place_hub_donor_chains()`
    (av_pointで実座標を引く)が同じ「先頭から順に試し、最初に解決できた
    ものを採用する」制御構造を使う)。

    `chain_plans`: `sway_hub.ChainDonorPlan`のような、`.source_chain`
    (Sequence)属性を持つオブジェクトの列。

    `resolve(cp)`: そのchain_planから`(head_point, tail_point)`のペア、
    または解決不能なら`None`を返す呼び出し側のコールバック(値の引き方は
    呼び出し側の責務、ここでは制御構造のみを共有する)。

    戻り値: 最初に非Noneを返した`resolve()`の結果。全`chain_plans`が
    解決不能(または空)なら`None`(呼び出し側は恒等フォールバックが
    必要、と解釈する)。"""
    for cp in chain_plans:
        value = resolve(cp)
        if value is not None:
            return value
    return None


def _hub_root_real_segment_transform(
    hub_name: str, gp: sway_hub.GroupHubPlan, sim: Similarity,
    avatar_dump: Mapping[str, Mapping[str, Sequence[float]]],
    anchor_pal_world_pos: Tuple[float, float, float],
    anchor_pal_world_quat: Tuple[float, float, float, float],
    exact_donor_world: Mapping[str, Tuple[Tuple[float, float, float, float],
                                           Tuple[float, float, float]]],
) -> Tuple[Tuple[Tuple[float, float, float, float],
                 Tuple[float, float, float],
                 Tuple[float, float, float]],
           Tuple[float, float, float],
           Tuple[float, float, float, float]]:
    """dev#1551(ゼロ長root廃止修理、issue #1551、正本 work\\run_1551\\
    laneR1_rootfix\\RESULT.md): hub root自身(`gp`のハブroot骨)の
    `anchor_pal`直下での配置を、「そのグループのsource_chain[0]
    (=anchor自身)のアバター実rest位置」から計算する——モジュール
    docstring「ハブroot自身の実節配置」節参照。

    優先順位: `exact_donor_world[hub_name]`(Blender側`place_hub_donor_
    chains()`が計算した実配置、利用可能なら)、無ければ`gp.chain_plans`を
    先頭から順に試す近似計算(`resolve_source_chain()`、avatar_dump+
    相似変換)。向き(quat)はavatar_dumpに回転データが無いため、anchor
    (head点)からsource_chain[1](chainの最初の実sway骨、鎖が空ならtip)
    への方向ベクトルから`q_find_between()`で合成する(`build_donor_chain_
    quats()`の先頭リンクと同じ規約: ローカル+X軸をこの方向へ向ける)。

    複数の`gp.chain_plans`がある場合は先頭から順に試し、最初に解決できた
    ものを使う(dev#1551 1鎖=1グループ化により通常は`chain_plans`は
    1要素。複数鎖が残る場合は同じanchorから分岐する複数鎖であることが
    構造的に保証されている——`sway_hub.plan_hub_wiring()`の「dev#1508
    hubwire final」コメント参照——ため、いずれの鎖から引いても
    source_chain[0]は同じanchor位置になる)。

    どの鎖からもデータが得られない(`chain_plans`が空、または全鎖が
    `resolve_source_chain()`で退化=解決不能)場合は、従来どおり
    `IDENTITY_TRANSFORM`(=anchor_pal世界座標そのもの)にフォールバックする
    (データが無い以上、恒等以上に良い推定ができないための安全側動作、
    無退行)。

    戻り値: (new_local_transform, hub_world_pos, hub_world_quat)。
    後者2つは呼び出し側がdonor鎖配置の`parent_world_pos`/
    `parent_world_quat`としてそのまま使う。"""
    if hub_name in exact_donor_world:
        target_quat, target_pos = exact_donor_world[hub_name]
        local_pos = q_rotate(q_conj(anchor_pal_world_quat),
                              v_sub(target_pos, anchor_pal_world_pos))
        local_quat = q_mul(q_conj(anchor_pal_world_quat), target_quat)
        return (local_quat, local_pos, (1.0, 1.0, 1.0)), target_pos, target_quat

    def _resolve(cp):
        # dev#1572(夜間便2): tailの向きは「source_chain[1](=fit後の代表骨)
        # 自身」ではなく、`sway_hub.donor_group_members()`で引いたその代表
        # グループの**先頭骨**(根元寄り、常に元の鎖のchain[0]そのもの)の
        # headを使う——節数フィットで代表がマージ区間の末尾側へ動いても、
        # hub root自身のtail方向は常に「アバターの実際に次の関節」を指す
        # (place_hub_donor_chains()の同型修正と同じ考え方)。
        #
        # dev#1572(第2便、安全域マージの全結合(実効節数1)修理): headの
        # 側にも同じ理屈を適用する。`src[0]`(=fit後の唯一の代表)は通常
        # (根本がマージされていない)ならそれ自身が根本(=anchor)だが、
        # 実効節数1の全結合(`fit_chain_to_length(chain,1)`)が発動すると
        # `src[0]`はグループの末尾側(先端寄り)要素名になり、真のanchor
        # (グループの先頭骨)の位置とは一致しない。`donor_group_members(cp)
        # [src[0]][0]`は常にそのグループの先頭骨を指すため、これ経由で
        # headを引く(通常ケースは`members0[0]==src[0]`で無変更)。
        src = list(cp.source_chain)
        if not src:
            return None
        members0 = sway_hub.donor_group_members(cp).get(src[0], (src[0],))
        head_pos = av_world(avatar_dump, sim, members0[0])
        if head_pos is None:
            return None
        if len(src) < 2:
            tail_pos = av_world(avatar_dump, sim, src[0], use_tail=True)
            return None if tail_pos is None else (head_pos, tail_pos)
        rep = src[1]
        members = sway_hub.donor_group_members(cp).get(rep, (rep,))
        tail_pos = av_world(avatar_dump, sim, members[0])
        if tail_pos is None:
            tail_pos = av_world(avatar_dump, sim, rep)
        if tail_pos is None:
            return None
        return head_pos, tail_pos

    segment = select_first_resolved_hub_segment(gp.chain_plans, _resolve)
    if segment is None:
        return IDENTITY_TRANSFORM, anchor_pal_world_pos, anchor_pal_world_quat

    head_pos, tail_pos = segment
    offset = v_sub(tail_pos, head_pos)
    if v_len(offset) < 1e-6:
        target_quat = (0.0, 0.0, 0.0, 1.0)
    else:
        target_quat = q_find_between((1.0, 0.0, 0.0), v_normalize(offset))
    local_pos = q_rotate(q_conj(anchor_pal_world_quat),
                          v_sub(head_pos, anchor_pal_world_pos))
    local_quat = q_mul(q_conj(anchor_pal_world_quat), target_quat)
    return (local_quat, local_pos, (1.0, 1.0, 1.0)), head_pos, target_quat


# =====================================================================
# 本体: HubWiringPlan全体のReparentStep列を組み立てる
# =====================================================================

def plan_reparent_steps(
    wiring: sway_hub.HubWiringPlan,
    catalog: sway_hub.SkeletonCatalog,
    gender: str,
    avatar_dump: Mapping[str, Mapping[str, Sequence[float]]],
    anchor_pal_name_of: Mapping[str, str],
    hips_avatar_name: str = "Hips", head_avatar_name: str = "Head",
    hips_pal_name: str = "pelvis", head_pal_name: str = "head",
    exact_donor_world: Optional[Mapping[str, Tuple[Tuple[float, float, float, float],
                                                     Tuple[float, float, float]]]] = None,
) -> List[sway_shared_skeleton.ReparentStep]:
    """`wiring`(`sway_hub.plan_hub_wiring()`の出力)全体を、共有Skeleton
    reparent手順(`sway_shared_skeleton.ReparentStep`のリスト)へ変換する。

    `gender`: "Male"/"Female"(このjobが変換しているアバターの性別。
    `GroupHubPlan.hub_root_female`/`hub_root_male`のどちらを実際に
    reparentするかを選ぶ——共有Skeletonは1ジョブにつき1回だけパッチする、
    モジュールdocstring参照)。

    `anchor_pal_name_of`: {アバターボーン名(SwayGroup.anchor) -> 対応する
    共有Skeleton内のPALボーン名}。呼び出し側(将来のstep02_retarget.py
    結線)が既存のリターゲットマップから用意する——本モジュールはこの
    翻訳を行わない(bpy非依存の範囲外、モジュールdocstring参照)。

    `exact_donor_world`(2026-08-16実機実測バグ修正、オーナーリアルタイム
    観測「step02は正しいがpak/実機側はまだおかしい」で発見): {donor骨名 ->
    (world_quat_ue, world_pos_ue)}。指定されたdonor骨は、本関数内部の
    `avatar_dump`+`compute_similarity()`(hips/head基準の一様相似変換)に
    よる**近似再計算を使わず**、この値をそのまま採用する。

    根因: `compute_similarity()`は一様スケール+並進(hips/head基準)のみの
    近似であり、`step02_retarget.py`の`chibi_fit_armature()`が行う
    **非一様な**(関節ごとに個別調整する)関節移動を反映できない。結果、
    donor骨の実際の望ましい位置(`place_hub_donor_chains()`がBlender
    pal_arm上で計算した、メッシュのバインド基準そのもの)と、本関数が
    独自に再計算する位置とが、頭部等アバターの体型がPalworld既定体型から
    離れるほど大きく(実測で最大約35cm)乖離していた——メッシュは正しい
    位置に焼き込まれるが、KP物理骨格(共有Skeleton)は別の位置に置かれる
    ため、実機で「メッシュとボーンがズレる」不具合になっていた。

    `exact_donor_world`が指定された骨は、この近似計算全体(`resolve_
    source_chain()`/`place_chain()`/`build_donor_chain_quats()`)を
    バイパスし、呼び出し側(`step02_retarget.py`)が`place_hub_donor_
    chains()`実行後に読み取った実際のBlender pal_arm配置(mesh bindの
    基準そのもの)をそのまま使う——両者が原理的に同一ソースになるため、
    ズレが構造的に発生しなくなる。未指定の骨は従来どおりの近似計算に
    フォールバックする(後方互換、既存テストの経路を変えない)。

    `wiring.group_plans`が空なら空リストを返す(揺れ対象0件、完全no-op)。
    """
    if not wiring.group_plans:
        return []
    exact_donor_world = exact_donor_world or {}

    fk = build_catalog_fk(catalog)
    sim = compute_similarity(
        avatar_dump, catalog, fk,
        hips_avatar_name=hips_avatar_name, head_avatar_name=head_avatar_name,
        hips_pal_name=hips_pal_name, head_pal_name=head_pal_name)

    steps: List[sway_shared_skeleton.ReparentStep] = []
    for gp in wiring.group_plans:
        hub_name = gp.hub_root_male if gender == "Male" else gp.hub_root_female
        anchor_pal = anchor_pal_name_of.get(gp.anchor_target)
        if anchor_pal is None:
            raise SwayHubPlacementError(
                f"no PAL-side retarget mapping for anchor {gp.anchor_target!r} "
                f"(group hub={hub_name!r}) -- anchor_pal_name_of is incomplete")

        try:
            anchor_pal_idx = catalog.index_of(anchor_pal)
        except KeyError as e:
            raise SwayHubPlacementError(
                f"anchor PAL bone not found in shared skeleton: {anchor_pal!r}") from e
        anchor_pal_world_pos = fk.world_pos[anchor_pal_idx]
        anchor_pal_world_quat = fk.world_quat[anchor_pal_idx]

        # ---- ①ハブroot自身: dev#1551(ゼロ長root廃止修理、issue #1551、
        # 正本 work\run_1551\laneR1_rootfix\RESULT.md)。hub_rootの配置を
        # 「アバターの鎖始点(chain[0])の位置」(旧PR #1560、ゼロ長tail固定
        # つき)から「source_chain[0](anchor自身)のexact geometry」へ
        # 変更する(`_hub_root_real_segment_transform()`、モジュール
        # docstring「ハブroot自身の実節配置」節参照)。donor鎖側(②)は
        # 内容写像を1つ繰り上げて割り当てる——hub_rootの新しい位置を
        # `parent_world_pos`として使うだけで、各donorのローカルオフセットは
        # 既存の計算式で自動的に正しく再計算される。
        new_local_transform, hub_world_pos, hub_world_quat = _hub_root_real_segment_transform(
            hub_name, gp, sim, avatar_dump, anchor_pal_world_pos, anchor_pal_world_quat,
            exact_donor_world)

        steps.append(sway_shared_skeleton.ReparentStep(
            target=hub_name, new_parent=anchor_pal,
            new_local_transform=new_local_transform,
            tag=f"hub:{gp.group.anchor}->{anchor_pal}"))

        # ---- ②各donor鎖: exact-bone-copyでアバター実座標へ配置 ----
        # (`exact_donor_world`に無い骨のみ、近似計算(avatar_dump+相似変換)
        # を使う——docstring「2026-08-16実機実測バグ修正」参照)
        for cp in gp.chain_plans:
            # dev#1551(性別またぎdedup漏れ修正): bivariantなハブスロットでは
            # cp.donor_chain_female/donor_chain_maleが互いに素な骨集合を
            # 指す(ChainDonorPlan.donor_chain_forのdocstring参照)。この
            # `gender`(本関数の呼び出し元がstep02_retarget.pyの性別ごとの
            # プロセスから渡す)向けの骨列だけを使う。
            donor_chain = cp.donor_chain_for(gender)
            needs_approx = any(n not in exact_donor_world for n in donor_chain)
            head_pts = chain_quats = used = None
            if needs_approx:
                # dev#1572(夜間便2): `resolve_source_chain()`+`place_chain()`
                # (代表名を単なる1点として読む旧実装)を`resolve_grouped_
                # chain()`(`sway_hub.donor_group_members()`経由でグループ
                # 境界=塊の先頭骨head〜末尾骨tailを反映)へ置き換える——
                # ウェイト側(`sway_hub_wire.source_to_donor_bone_map()`)と
                # 同じ単一のグルーピングを共有する(place_hub_donor_chains()
                # の同型修正と同じ考え方)。
                anchor_pt, head_pts, tail_pts, used = resolve_grouped_chain(
                    avatar_dump, sim, cp, gp.group.anchor, donor_chain)
                if anchor_pt is None:
                    raise SwayHubPlacementError(
                        f"unresolved avatar bone(s) in chain (group anchor="
                        f"{gp.group.anchor!r}): {cp.source_chain}")

                n_donor = len(donor_chain)
                chain_dirs = [v_sub(tail_pts[i], head_pts[i]) for i in range(n_donor)]
                chain_quats = build_donor_chain_quats(chain_dirs)

            parent_world_pos = hub_world_pos
            parent_world_quat = hub_world_quat
            parent_name = hub_name
            for i, node_name in enumerate(donor_chain):
                if node_name in exact_donor_world:
                    target_quat, target_pos = exact_donor_world[node_name]
                    tag_suffix = "exact"
                else:
                    target_pos = head_pts[i]
                    target_quat = chain_quats[i]
                    tag_suffix = used if used else ""
                local_pos = q_rotate(q_conj(parent_world_quat),
                                      v_sub(target_pos, parent_world_pos))
                local_quat = q_mul(q_conj(parent_world_quat), target_quat)
                steps.append(sway_shared_skeleton.ReparentStep(
                    target=node_name, new_parent=parent_name,
                    new_local_transform=(local_quat, local_pos, (1.0, 1.0, 1.0)),
                    tag=f"donor:{gp.group.anchor}:{tag_suffix}"))
                parent_world_pos = target_pos
                parent_world_quat = target_quat
                parent_name = node_name

    return steps
