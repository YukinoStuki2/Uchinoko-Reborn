# -*- coding: utf-8 -*-
"""sway_hub.py -- 揺れもの「汎用ハブ配線」の骨トポロジ計画(dev#1508 W2a-2、
issue https://github.com/pandrabox/DiveToPalworld-dev/issues/1508)。

正本仕様: `.devonly\\docs\\sway\\sway_wrapup\\SPEC.md` §5「工事項目」(ハブ設計規則)。
列車計画: `.devonly\\docs\\sway\\sway_wrapup\\TRAIN.md` Wave2 W2a。

## 本モジュールの役割(現時点のスコープ)

`pipeline\\py\\sway_allocator.py`(W1c、候補判定・無偏向判定・量子化・
グループ化・容量9)の出力(`AllocationPlan`)を受け取り、各採用グループ
(`SwayGroup`)を**ハブroot骨**(`pipeline\\py\\sway_abp_templates\\specs\\*.json`
が持つ9本の固定root_bone名のどれか)へ割り当て、そのグループが持つ各鎖に
**自由骨プール**(予約68本を除いた共有Skeleton在庫)からdonor骨を割り当てる
——**骨の名前とトポロジ(誰が誰の親か)だけ**を決める(SPEC §5「ハブ設計規則」)。

**本モジュールが決めないもの(スコープ外、既知の未完了)**: donor骨・ハブの
実際のワールド座標配置(`work\\rd_1423_haori_full2\\scripts\\
compute_umbrella_transforms.py`が確立した「exact-bone-copy」配置数学を
本番パイプラインへ移設する仕事)。この座標計算はアバターの実Unity座標
(Blenderロード後のavatar_arm、または実世界ダンプ)に依存するため、bpy非依存の
このモジュールの範囲外——`pipeline\\blender\\step02_retarget.py`側で本モジュールの
トポロジ計画を消費し、`sway_shared_skeleton.ReparentStep.new_local_transform`
を実座標で埋める後続の配線処理(未実装、本WPは基盤のみ)が必要。

## ハブroot骨(9本、性別ごと)の由来

`sway_abp_build.load_template_manifest()`が動的に読む`specs/*.json`の
`root_bones`(1テンプレあたり9〜10本、性別内の全テンプレで完全に同一)を
**そのまま**「割当可能なハブスロット」として使う——ハードコードしない
(`sway_abp_build.py`のモジュールdocstring「テンプレはデータ」の方針を踏襲)。
男性側の10本目(M_Hunter001_17)は恒久予備として使わない(SPEC §1-5)。

## 予約骨(donorに使えない骨)

`work\\rd_1423_kpledger\\RESERVED_BONES.md`(68本、ledger.json由来)相当の
骨集合は、既に何らかのKPノードの物理チェーンの一部として構造的に使われている
——本モジュールはこの集合の**動的な等価物**として「全KPノードroot骨それぞれの、
共有Skeleton内での既存の子孫全部」を自動的に計算し(`reserved_descendants_of()`)、
別途のRESERVED_BONES.md静的リストへの依存を持たない(将来テンプレ差し替えで
対象骨が変わっても本モジュールの変更が不要)。

**注意(2026-08-16 Masterライターレビュー指摘、本WPで修正)**: 予約集合の入力は
`discover_hub_slots()`が返す「ハブ*割当対象*として使う9本」ではなく、
`all_kp_node_root_names()`が返す**全KPノードroot骨**(男性専用の恒久予備
M_Hunter001_17を含む)でなければならない。SPEC §1-5「男グラフの10本目は
恒久予備として使わない」は「ハブ割当スロットとして使わない」という意味であり、
「予約(構造的に子孫を持つ既存ノードとして扱わない)」の意味ではない——
M_Hunter001_17は実在するKPノード(scarf_2)のroot骨であり、その子孫
(M_Hunter001_17自身/M_Hunter001_19)は既に別のKP鎖の一部として構造的に
使われている。9本(discover_hub_slots())を入力にすると、この2本が
donor自由プールへ誤って解放されてしまう(実測で確認済み、女性9+男性9=18本
入力では66本しか予約されない。全16本の一意root名を入力にすると68本ぴったり
——`work\\rd_1423_kpledger\\RESERVED_BONES.md`と完全一致)。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Set, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_abp_build  # noqa: E402
import sway_allocator  # noqa: E402
import sway_identify  # noqa: E402  (dev#1508 laneA4: EAR_NAME_PATTERNSを可視性tier判定へ再利用)

TAG = "sway_hub"

# =====================================================================
# 振幅ランク表 + 既知の動くdonor骨(dev#1508 laneA4、amplitude-root)
# =====================================================================
#
# work\night_20260817\briefs\laneA4_amplitude_assign.md 実装。正本データは
# 同梱JSON(出所・手法はJSON自身のdocstringに明記、モジュールとして
# ハードコードしない——「テンプレはデータ」の方針を踏襲)。
_DEFAULT_ROOT_AMPLITUDE_PATH = os.path.join(_HERE, "sway_root_amplitude.json")
_DEFAULT_KNOWN_MOVING_PATH = os.path.join(_HERE, "sway_known_moving_bones.json")


def load_root_amplitude_rank(path: str = _DEFAULT_ROOT_AMPLITUDE_PATH) -> Dict[str, float]:
    """`sway_root_amplitude.json`の`roots`セクションを{root名: 振幅cm}へ
    平坦化して返す(`plan_hub_wiring()`の`amplitude_rank`引数へそのまま
    渡せる形)。ファイルが無い/壊れている場合は空dict(振幅データ無し=
    amplitude-aware割当は自動的に無効化され、`plan_hub_wiring()`は
    従来どおりのenumerate順にフォールバックする、④既定値不変の精神を
    データ欠落時にも維持する安全側フォールバック)。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    roots = data.get("roots", {})
    out: Dict[str, float] = {}
    for name, info in roots.items():
        try:
            out[name] = float(info["amplitude_cm"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def load_known_moving_chain_bones(path: str = _DEFAULT_KNOWN_MOVING_PATH) -> FrozenSet[str]:
    """`sway_known_moving_bones.json`の`known_moving_chain_bones`を
    frozensetで返す(`free_donor_pool()`/`plan_hub_wiring()`の
    `known_moving`引数へそのまま渡せる形)。ファイルが無い/壊れている
    場合は空frozenset(安全側フォールバック、既定値不変)。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return frozenset()
    return frozenset(str(n) for n in data.get("known_moving_chain_bones", []))


def _group_visibility_tier(group: "sway_allocator.SwayGroup") -> int:
    """振幅ランクによるroot割当の優先度(dev#1508 laneA4、brief item2
    「可視性・剛性の高いグループほど低振幅rootへ」の判定)。

    tier 0: 耳・頭部系(EAR_NAME_PATTERNS一致、または"head"トークン一致)
      -- 最優先で低振幅rootを求める(brief「耳は最重要」)。
    tier 1: それ以外全部(袖・胸・スカーフ等の既定) -- 次点。
    tier 2: しっぽ(`group.is_tail`) -- v2.11実績(GrassBoss尻尾は高振幅の
      まま官能白だった、laneA3確認)により最後に残った(=最も高振幅な)
      rootでも許容できる、という優先度最低の扱い。

    名前判定は`sway_identify.py`の既存パターン(耳/尻尾トークン照合、
    dev#19最終裁定)を流用——新しい名前推定ロジックを増やさない。"""
    if group.is_tail:
        return 2
    candidates = [group.anchor] + [b for chain in group.chains for b in chain]
    for name in candidates:
        low = (name or "").lower()
        if any(p.lower() in low for p in sway_identify.EAR_NAME_PATTERNS):
            return 0
        if "head" in low or "頭" in (name or "") or "atama" in low:
            return 0
    return 1


def _slot_visibility_tier(slot_name: str) -> int:
    """スロット骨自身の名前から、`_group_visibility_tier()`と同じ意味論の
    tierを判定する(tier0=耳/head系, tier1=その他, tier2=しっぽ系、dev#1551
    「耳donorの横取り防止」issue #1551)。`sway_identify.identify_sway_kind()`の
    既存パターン(耳/尻尾トークン照合)をそのまま再利用——新しい名前推定
    ロジックを増やさない(`_group_visibility_tier()`のdocstring方針を踏襲)。
    """
    kind = sway_identify.identify_sway_kind(slot_name, [])
    if kind == "tail":
        return 2
    if kind == "ear":
        return 0
    low = (slot_name or "").lower()
    if "head" in low or "頭" in (slot_name or "") or "atama" in low:
        return 0
    return 1


def _assign_slots_by_visibility_amplitude(
    accepted: Sequence["sway_allocator.SwayGroup"],
    hub_names_slot_order: Sequence[str],
    amplitude_rank: Mapping[str, float],
) -> List[int]:
    """`accepted`(優先順位順、要素の並び自体は一切変更しない)の各要素へ、
    `hub_names_slot_order`のどのインデックスを割り当てるかを返す
    (`accepted`と同じ長さのリスト、`accepted[i]`が使うスロット番号が
    `結果[i]`)。

    手順(dev#1551「耳donorの横取り防止」issue #1551、正本work\\run_1551\\
    integL\\RESULT.md、実データ実測で発見: 耳/head系グループが実在するのに
    "HeadEquip062_ear_01_r"のような耳系スロットが無関係な非耳グループに
    先取りされ、そのスロットが元々持つPAL側の意味(装備の耳飾り等)ごと
    アバターの無関係な部位へreparentされてしまう):
    グループ・スロットの両方を`_group_visibility_tier()`/
    `_slot_visibility_tier()`で同じtier体系(0=耳/head, 1=その他, 2=尻尾)へ
    分類し、**同tier内で**振幅昇順に対応させる(「可視性が高いグループほど
    低振幅rootを得る」brief item2はtier内で維持)。あるtierのグループ数が
    そのtierのスロット供給を超える場合(在庫過多)、または逆にそのtierの
    スロットが余る場合は、**あぶれた分だけ**全tier横断のプール(振幅昇順)へ
    フォールバックする——「場当たりの名指しでなく、割当の決定順の構造で
    解決」(dev#1551 issue本文)、既存の`_group_priority_key()`
    (`sway_allocator.py`、しっぽ優先=tier最優先で受入枠を確保する既存則)と
    同じ「同種を同種の枠へ優先確保し、あぶれたら共有プールへ回す」設計を
    踏襲する。

    `claim_order`(グループの処理順=tier昇順、同tier内は元の優先順位)は
    従来と完全に同一——tierをまたぐ処理順序自体は変えず、「どのスロットが
    もらえるか」の対応規則だけを「フラットな振幅順1:1対応」から
    「tier一致優先+あぶれの共有プール」へ変更した。"""
    n = len(accepted)
    group_tier = [_group_visibility_tier(g) for g in accepted]
    slot_tier = [_slot_visibility_tier(name) for name in hub_names_slot_order]

    claim_order = sorted(range(n), key=lambda i: (group_tier[i], i))
    slot_order_by_amplitude = sorted(
        range(len(hub_names_slot_order)),
        key=lambda i: (amplitude_rank.get(hub_names_slot_order[i], float("inf")), i))

    # tierごとに、振幅昇順を保ったままスロットindexを振り分けるバケツ。
    slots_by_tier: Dict[int, List[int]] = {0: [], 1: [], 2: []}
    for idx in slot_order_by_amplitude:
        slots_by_tier[slot_tier[idx]].append(idx)

    slot_for_group_index: Dict[int, int] = {}
    leftover_groups: List[int] = []
    for group_idx in claim_order:
        bucket = slots_by_tier[group_tier[group_idx]]
        if bucket:
            slot_for_group_index[group_idx] = bucket.pop(0)
        else:
            leftover_groups.append(group_idx)

    # あぶれたグループ(自tierのスロット供給が尽きた)は、全tier横断で
    # 残っているスロットを振幅昇順に、元の優先順位どおり順に消費する。
    remaining_slots = sorted(
        (idx for bucket in slots_by_tier.values() for idx in bucket),
        key=lambda i: (amplitude_rank.get(hub_names_slot_order[i], float("inf")), i))
    for group_idx in leftover_groups:
        slot_for_group_index[group_idx] = remaining_slots.pop(0)

    return [slot_for_group_index[i] for i in range(n)]


class SwayHubError(RuntimeError):
    """ハブ配線計画の想定外エラー(黙って握り潰さず変換全体を止めるための
    シグナル、sway_abp_build.SwayAbpBuildErrorと同じ設計方針)。"""


# =====================================================================
# ハブroot骨スロット(9本、性別ごと)の動的発見
# =====================================================================

def _slot_key(name: str) -> str:
    """性別接頭辞(F_/M_)を剥がした「スロット照合キー」。HeadEquip062_ear_01_l
    やNPC_GrassBoss001_Skin001_tail_01のような性別非依存の共有名はそのまま
    返る(sway_assign._family_prefix()の性別接頭辞除去と同じ考え方)。"""
    if name.startswith("F_") or name.startswith("M_"):
        return name[2:]
    return name


@dataclass(frozen=True)
class HubSlots:
    """性別ごとのハブroot骨9本(スロット順、優先順位の高いSwayGroupから
    順に割り当てる対象)。`female`/`male`は同じスロット順(同じ`_slot_key`)で
    並んでいる——`node_overrides`を組み立てる側が同じスロットのF/M名へ同じ
    style/limit_angleを書けるようにするため(SPEC §1-5「男女で採用結果を
    同一にするため」)。"""

    female: Tuple[str, ...]
    male: Tuple[str, ...]

    def names_for(self, gender: str) -> Tuple[str, ...]:
        return self.male if gender == "Male" else self.female

    def both_names_at(self, slot: int) -> Tuple[str, str]:
        """指定スロットの(female名, male名)のペア。node_overridesを
        両性別ぶん同時に書くために使う(SPEC §1-5)。"""
        return self.female[slot], self.male[slot]


def discover_hub_slots(templates_dir: str = sway_abp_build.TEMPLATES_DIR) -> HubSlots:
    """`sway_abp_templates/specs/*.json`から、性別ごとの固定ハブroot骨9本を
    動的に発見する(ハードコードしない、モジュールdocstring参照)。

    全F系テンプレのroot_bonesが完全一致し、全M系テンプレのroot_bonesが
    完全一致することを検証する(不一致は`SwayHubError`——テンプレの構造的
    前提が崩れている異常事態であり、静かに片方を採用してはならない)。
    M側の本数がF側より1本多い場合(実データ: 恒久予備M_Hunter001_17)は、
    F側に無いスロットキーを持つ末尾を捨てて9本に揃える。
    """
    manifest = sway_abp_build.load_template_manifest(
        os.path.join(templates_dir, "specs"))
    if not manifest:
        raise SwayHubError(f"no sway ABP templates found under {templates_dir}")

    f_lists = [tuple(t["root_bones"]) for t in manifest
               if os.path.basename(t["spec_path"]).startswith("spec_F_")]
    m_lists = [tuple(t["root_bones"]) for t in manifest
               if os.path.basename(t["spec_path"]).startswith("spec_M_")]
    if not f_lists or not m_lists:
        raise SwayHubError("expected both spec_F_*.json and spec_M_*.json templates")
    if len(set(f_lists)) != 1:
        raise SwayHubError(f"female templates disagree on root_bones: {set(f_lists)}")
    if len(set(m_lists)) != 1:
        raise SwayHubError(f"male templates disagree on root_bones: {set(m_lists)}")

    female = f_lists[0]
    male_all = m_lists[0]
    female_keys = [_slot_key(n) for n in female]
    male_by_key = {_slot_key(n): n for n in male_all}
    missing = [k for k in female_keys if k not in male_by_key]
    if missing:
        raise SwayHubError(f"male templates missing counterparts for slots: {missing}")
    male = tuple(male_by_key[k] for k in female_keys)
    return HubSlots(female=female, male=male)


def all_kp_node_root_names(templates_dir: str = sway_abp_build.TEMPLATES_DIR) -> FrozenSet[str]:
    """全KPノードのroot_bone名を、性別・ハブ*割当対象*として使うかどうかとは
    無関係に、全F系+全M系テンプレから集めて返す(重複除去、性別非依存の
    共有名——耳L/耳R/GrassBoss尻尾——は1つにまとまる)。

    `discover_hub_slots()`が返す9本(女)/9本(男、恒久予備M_Hunter001_17を
    トリム済み)とは別物——こちらは**予約集合の計算専用の入力**であり、
    `reserved_descendants_of()`へはこの関数の戻り値を渡すこと
    (モジュールdocstring「予約骨」節参照。9本渡しは既知のバグ、修正済み)。
    """
    manifest = sway_abp_build.load_template_manifest(
        os.path.join(templates_dir, "specs"))
    if not manifest:
        raise SwayHubError(f"no sway ABP templates found under {templates_dir}")
    names: Set[str] = set()
    for t in manifest:
        names.update(t["root_bones"])
    return frozenset(names)


# =====================================================================
# 予約骨(donorに使えない骨)の動的導出
# =====================================================================

def _children_map(bones: Sequence[Mapping[str, object]]) -> Dict[int, List[int]]:
    children: Dict[int, List[int]] = {}
    for i, b in enumerate(bones):
        p = b["parent_idx"]
        if isinstance(p, int) and p >= 0:
            children.setdefault(p, []).append(i)
    return children


def reserved_descendants_of(
    hub_root_names: Sequence[str], bones: Sequence[Mapping[str, object]],
) -> FrozenSet[str]:
    """指定したroot骨それぞれの、共有Skeleton内での既存の子孫全部
    (root骨自身も含む)を予約集合として返す——`work\\rd_1423_kpledger\\
    RESERVED_BONES.md`(静的68本リスト)の動的な等価物(モジュールdocstring
    参照)。donor骨プールから除外する対象。

    **`hub_root_names`には`all_kp_node_root_names()`の戻り値(全16本、
    恒久予備M_Hunter001_17を含む)を渡すこと**——`discover_hub_slots()`の
    9本(女)/9本(男)だけを渡すと、恒久予備の子孫(M_Hunter001_17/
    M_Hunter001_19)が予約から漏れる(モジュールdocstring「予約骨」節、
    2026-08-16 Masterライターレビュー指摘の修正)。

    bones: `sway_shared_skeleton.full_skeleton_catalog()["bones"]`の
    `bones`リスト(順序がそのまま元のRefSkeletonインデックスに対応する
    前提——full_skeleton_catalog()の契約どおり)。
    """
    name_to_idx = {b["name"]: i for i, b in enumerate(bones)}
    children = _children_map(bones)
    names = [b["name"] for b in bones]

    reserved: Set[str] = set()
    for root_name in hub_root_names:
        idx = name_to_idx.get(root_name)
        if idx is None:
            continue  # テスト用の小さい合成catalogでは一部だけ存在しうる
        stack = [idx]
        while stack:
            cur = stack.pop()
            reserved.add(names[cur])
            stack.extend(children.get(cur, []))
    return frozenset(reserved)


# =====================================================================
# 自由donorプール
# =====================================================================

@dataclass(frozen=True)
class SkeletonCatalog:
    """`sway_shared_skeleton.full_skeleton_catalog()`の生dictを扱いやすく
    ラップしたもの(名前->インデックス、名前->parent_idx)。"""

    bones: Tuple[Mapping[str, object], ...]
    name_to_idx: Dict[str, int]

    @classmethod
    def from_bones_list(cls, bones: Sequence[Mapping[str, object]]) -> "SkeletonCatalog":
        return cls(bones=tuple(bones),
                    name_to_idx={b["name"]: i for i, b in enumerate(bones)})

    def index_of(self, name: str) -> int:
        return self.name_to_idx[name]


def load_skeleton_catalog(json_path: str) -> SkeletonCatalog:
    """`vanilla\\sk_palhuman_full.json`(dev#1508 W2a-2c、
    `extract_vanilla.extract_shared_skeleton_catalog()`が書き出す、
    `sway_shared_skeleton.full_skeleton_catalog()`と同一の形)を読んで
    `SkeletonCatalog`へ変換する。呼び出し側(`sway_hub_wire.py`)がこの
    ファイルパスの決定(job_dir/vanilla/配下)を担う——本関数はファイル形式
    の変換のみ。"""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    return SkeletonCatalog.from_bones_list(data["bones"])


def free_donor_pool(
    catalog: SkeletonCatalog, reserved: FrozenSet[str], hub_root_names: Sequence[str],
    protected: FrozenSet[str] = frozenset(),
    known_moving: FrozenSet[str] = frozenset(),
) -> List[str]:
    """自由骨プール(予約68本相当+ハブroot骨自身+保護骨を除いた在庫)を、
    共有Skeleton内の元のインデックス昇順で返す(donor選択がこの順で貪欲に
    消費すれば、トポロジ制約(new_parent_idx<target_idx)を機械的に満たせる
    ——モジュールdocstring/`sway_shared_skeleton.py`のトポロジ不変条件参照)。

    root骨(index 0、parent=-1)自体も除外する(reparent対象になり得ない)。

    **`protected`(2026-08-16実データ調査で発見・本WPで追加した安全策)**:
    共有Skeleton(SK_PalHuman_Skeleton、実測4079骨)には揺れもの用の
    cloth/hair付属骨だけでなく、**基幹の人型ボディリグそのもの**
    (`pelvis`/`spine_01`〜`spine_03`/`neck_01`/`head`/`thigh_l`/`hand_l`等、
    `pipeline\\py\\extract_vanilla.py`が書き出す`vanilla\\common_bones.json`の
    `"common"`リスト、実測65本、Male∩Femaleの共通基幹ボーン)が同居している
    ——`reserved`(KPノードroot骨の子孫)にはこれらが含まれない(基幹リグは
    どのKPノードの子孫でもないため)。**`protected`を渡さないと、自由骨
    プールが人型の脚・脊椎・頭等をdonorとして選び、実際にreparentして
    しまいうる**(基幹ボーンが揺れもの用に引っ越しされ、アバターの見た目・
    アニメーションが構造的に破壊される、実測で確認した重大な安全上の欠落
    ——テストで負の対照として固定)。呼び出し側(将来のstep02_retarget.py/
    build_pak_from_avatar.py結線)は必ず`common_bones.json`の`"common"`
    リストをこの引数へ渡すこと。

    `known_moving`(dev#1508 laneA4、`sway_known_moving_bones.json`
    相当): hub root骨自身ではないが実機実測でvanillaアニメーション由来の
    動きが確認された骨名の集合(donor_quietness.json由来、ベストエフォート
    ——全4079骨の網羅ではない、モジュール内`load_known_moving_chain_bones()`
    docstring参照)。指定された名前は自由プールから除外し、既知の動く骨を
    避ける(brief item2「鎖donorは静音109から選定、現行が動く骨を掴んで
    いる場合は置換」)。既定は空集合(4既定値不変)。
    """
    hub_set = set(hub_root_names)
    protected_set = set(protected)
    moving_set = set(known_moving)
    out = []
    for b in catalog.bones:
        name = b["name"]
        if name in reserved or name in hub_set or name in protected_set:
            continue
        if name in moving_set:
            continue
        if b["parent_idx"] == -1:
            continue
        out.append(name)
    return out


# =====================================================================
# dev#1551 chain-length-fit: donor節数フィット(先端マージ)
# =====================================================================
#
# 背景(issue #1551): 現行の自由骨プール(`free_donor_pool()`)は共有
# Skeleton内の「予約68本(実質はKPノードroot骨全部の子孫)を除く任意の
# 空き骨」から、カタログインデックス順に貪欲消費するだけで、その骨が
# **実際にゲーム側の描画メッシュ(CharacterMesh0)上で歩行可能(walkable)
# か**は一切問わない。UEのSkeletalMesh(装備アイテムごとの実メッシュ
# アセット)は、共有Skeletonアセット(SK_PalHuman_Skeleton)に定義された
# 骨のうち、そのメッシュ自身が頂点ウェイトを持つ骨だけを実際のボーン配列
# へ残す最適化(未使用骨の除去)を行いうる——共有Skeletonアセット自身は
# 常に全4079骨を保持するため、`free_donor_pool()`はこの「メッシュ側では
# 消えている(未使用の葉として残された)骨」を平気でdonorに選んでしまう
# (dev#1551 integQ実測: donor `HeadEquip061_ear_04_l`はSK_PalHuman_
# Skeletonカタログには実在するが実機bonedumpのCharacterMesh0骨配列には
# 一切現れない——無関係な家系"061"の未使用延長骨だった)。
#
# KawaiiPhysicsは鎖の**実際に歩行できた末端骨**の回転を毎フレームbind
# 姿勢へ固定する(`ApplySimulateResult`、dev#19 native-donor-rule WPの
# 恒久ルール、`pipeline\\py\\sway_native_rule.py`docstring参照)。歩行不能な
# 「幽霊」donorがチェーンの末尾に混ざると、この固定が**1つ手前の
# ウェイト付き実donor骨**へ繰り上がって当たり、視認可能な凍結になる
# (実測: flatHaori耳の3節目=ウェイト付き最終節が凍る)。
#
# 修理方針: **ハブroot自身の直系子孫(同じ装備メッシュ由来、n+1規則の
# 「native」相当)を、無関係な自由骨プールより優先してdonorに使う**
# ——同じ装備アセットの設計者が意図的に連ねた鎖である分、実際に
# メッシュへウェイトが乗っている(=歩行可能な)可能性が構造的に高い。
# 優先chainの本数がソース鎖の要求本数に足りない場合は、**分配マージ**で
# 収める(dev#1572、2026-08-18オーナー最終裁定。旧「純粋な先端マージ」
# (dev#1551初版)を置き換え): 「根本は単独維持(実効節数1のときだけ
# 全結合)、残りの骨を残りノード数へできるだけ均等に分配、余りは先端側の
# 塊へ」——`fit_chain_to_length()`docstring参照。


class ChainFitError(SwayHubError):
    """`fit_chain_to_length()`が、donor容量が1本も無い(`max_len<=0`)と
    判定したときに送出する——chainが非空である限り最低1本のdonor枠が
    要る(dev#1572: 実効節数1のときは根本も含めた全要素が単一グループへ
    収まるため、`max_len==1`自体はもはやエラーではない)。呼び出し側は
    既存のunassignable/自由プールフォールバックへ倒すこと。"""


def _children_by_index(catalog: "SkeletonCatalog") -> Dict[int, List[int]]:
    children: Dict[int, List[int]] = {}
    for i, b in enumerate(catalog.bones):
        p = b["parent_idx"]
        if isinstance(p, int) and p >= 0:
            children.setdefault(p, []).append(i)
    return children


def hub_native_descendant_chain(
    hub_name: str, catalog: "SkeletonCatalog", stop_names: FrozenSet[str],
) -> Tuple[str, ...]:
    """`hub_name`自身の共有Skeleton内での既存の直系子孫を、分岐の無い
    一本道である限り根元(hubに一番近い)から先端へ順に辿って返す。

    停止条件(いずれか): (a) 子が無い(葉に到達)、(b) 子が複数ある
    (分岐——単純な直列鎖として扱えない、安全側で打ち切る)、(c) 子が
    `stop_names`に含まれる(別のKPノードroot骨の領域に踏み込む——
    呼び出し側は他ハブスロットの root骨名集合を渡すこと)。

    `hub_name`がcatalogに無ければ空タプル(安全側、呼び出し元は自由
    プール経由の既存フォールバックへ回ること)。"""
    idx = catalog.name_to_idx.get(hub_name)
    if idx is None:
        return ()
    children = _children_by_index(catalog)
    out: List[str] = []
    cur = idx
    while True:
        kids = children.get(cur, [])
        if len(kids) != 1:
            break
        child_idx = kids[0]
        child_name = catalog.bones[child_idx]["name"]
        if child_name in stop_names:
            break
        out.append(child_name)
        cur = child_idx
    return tuple(out)


def fit_chain_to_length(
    chain: Sequence[str], max_len: int,
) -> Tuple[Tuple[str, ...], Dict[str, str]]:
    """`chain`(根元→先端の順。`chain[0]`は常にanchor=根本)を、donor容量
    `max_len`本に収まるよう**分配マージ**して縮退させる(dev#1572、
    2026-08-18オーナー最終裁定。旧「純粋な先端マージ」(dev#1551初版)を
    置き換え)。

    分配規則(オーナー確定): 「根本は単独維持(**実効節数1のときだけ
    全結合**——このときのみ根本も他要素とマージされる唯一の例外)、
    残りの骨を残りノード数へできるだけ均等に分配、余りは先端側の塊へ」。
    具体例(5骨ABCDE、Aが根本、実効節数nに対し):
    n=1: (ABCDE) / n=2: A(BCDE) / n=3: A(BC)(DE) / n=4: ABC(DE) / n=5: ABCDE。
    6骨で実効3なら A(BC)(DEF)(残りノード数2への均等分配、余り1本は
    先端側の塊(DEF)へ)。

    アルゴリズム: `max_len>=len(chain)`なら恒等写像。`max_len==1`なら
    全要素(根本含む)を1グループへ。それ以外(`2<=max_len<len(chain)`)
    は根本を単独グループとして固定し、残り`len(chain)-1`要素を
    `max_len-1`個のグループへ`divmod`で均等分配(商=各グループの基本
    サイズ、余りは**末尾側(先端寄り)**のグループから順に+1本)。

    マージ塊のdonorノード幾何(呼び出し側の責務、本関数はグループ分割と
    代表名だけを返す): 塊の先頭骨のheadから末尾骨のtailまでのスパン
    (関節は塊境界にのみ存在)。

    戻り値: (fitted_chain, expansion_map)。
      - `fitted_chain`: 各グループの**代表**(グループ内で最も先端側=
        マージ区間の末尾要素——「マージ後の代表点はマージ区間の端点を
        保つ形で自然に」)を根元→先端順に並べたもの
        (長さ = min(len(chain), max_len))。
      - `expansion_map`: `chain`の全要素 -> その要素が属するグループの
        代表名(未マージの要素は恒等写像)。ウェイト転写側
        (`sway_hub_wire.source_to_donor_bone_map()`)が「マージされた
        元ボーンのウェイトを代表donorへ合算する」ために使う。

    `chain`が空なら`((), {})`。`max_len<=0`かつ`chain`が非空なら常に
    `ChainFitError`(donor枠が1本も無い)。"""
    if not chain:
        return (), {}
    if max_len <= 0:
        raise ChainFitError(
            f"fit_chain_to_length: max_len={max_len} cannot hold any donor "
            f"slot for chain of {len(chain)} bone(s) {list(chain)!r}")
    if max_len >= len(chain):
        return tuple(chain), {b: b for b in chain}
    if max_len == 1:
        # 実効節数1のみ、根本も含めた全要素を単一グループへ全結合する
        # (オーナー確定の唯一の例外規則)。
        rep = chain[-1]
        return (rep,), {b: rep for b in chain}

    root = chain[0]
    rest = chain[1:]
    n_groups_rest = max_len - 1
    base, remainder = divmod(len(rest), n_groups_rest)
    sizes = [base] * n_groups_rest
    # 余りは先端側(末尾)のグループから順に+1本。
    for i in range(n_groups_rest - remainder, n_groups_rest):
        sizes[i] += 1

    groups: List[List[str]] = [[root]]
    cursor = 0
    for size in sizes:
        groups.append(list(rest[cursor:cursor + size]))
        cursor += size

    fitted = tuple(g[-1] for g in groups)
    expansion: Dict[str, str] = {}
    for g in groups:
        rep = g[-1]
        for member in g:
            expansion[member] = rep
    return fitted, expansion


def select_tuft_representative(
    chains: Sequence[Sequence[str]],
) -> Tuple[Tuple[str, ...], Tuple[Tuple[str, ...], ...]]:
    """dev#1572(房Merge、issue #1572「房Mergeの機構」、2026-08-19第3便):
    根本(anchor)からたどって同じ深さの骨をマージする"房Merge"の入口——
    同じコンポーネント(=同じ`sway_allocator.ChainUnit`、1つのPB/SBが
    複数チェーンを持つ=Y字分岐)から、**幾何の代表**(最長枝、同着は
    入力順先頭)と、**残りの枝**(ウェイト写像専用、幾何には一切関与
    しない)を分離する。

    「安いから付けるおまけ機能。検査対象外。問題は起きてから考える」
    (issue #1572本文)——多段・複雑分岐は同じコードを通るだけの成り行き
    (保証なし)。

    `chains`が0本または1本なら房ではない通常の直列鎖であり、完全に
    無変更(恒等): `(chains[0], ())`または`((), ())`。"""
    if not chains:
        return (), ()
    if len(chains) == 1:
        return tuple(chains[0]), ()
    longest_idx = max(range(len(chains)), key=lambda i: len(chains[i]))
    representative = tuple(chains[longest_idx])
    others = tuple(tuple(c) for i, c in enumerate(chains) if i != longest_idx)
    return representative, others


def expand_tuft_weight_mapping(
    representative_chain: Sequence[str],
    expansion: Mapping[str, str],
    other_branches: Sequence[Sequence[str]],
) -> Dict[str, str]:
    """dev#1572(房Merge): `other_branches`(`select_tuft_representative()`が
    分離した代表枝以外の枝)の各骨を、**同じ深さ**(anchorから数えた
    インデックス、`representative_chain`内の位置)の代表枝の骨が実際に
    対応するdonor代表(`expansion`、`fit_chain_to_length()`が代表枝自身に
    行ったwithin-chain統合込みの対応)へ写す——猫又が容量不足でさらに
    縮退していても正しく追従する。

    戻り値は`expansion`(代表枝のみの対応)と`other_branches`の骨の対応を
    合流させた1つの辞書(`ChainDonorPlan.weight_expansion`にそのまま
    使う——`sway_hub_wire.source_to_donor_bone_map()`はこの辞書経由で
    ウェイトを転写するので、房の全枝が自動的にカバーされる)。

    幾何(`donor_group_members()`が読む塊の先頭/末尾)は代表枝の
    `weight_expansion`エントリだけを使うよう`ChainDonorPlan.
    representative_source`側で別途絞る——本関数はその絞り込みを一切
    行わない(合流のみ)。

    `other_branches`が空(房でない通常の直列鎖)なら`expansion`をそのまま
    (コピーして)返す(恒等、無退行)。"""
    out = dict(expansion)
    if not other_branches:
        return out
    for branch in other_branches:
        for i, bone in enumerate(branch):
            if i >= len(representative_chain):
                # 代表枝(最長のはず)より深い分岐——想定外の入力。対応先が
                # 無いため安全側で無視する(保証なしのおまけ機能、KISS)。
                continue
            rep_bone = representative_chain[i]
            out[bone] = expansion.get(rep_bone, rep_bone)
    return out


def resolve_safety_margin(
    extended_source: Sequence[str],
    safety_margin_by_chain: Optional[Mapping[Tuple[str, ...], int]],
    default_safety_margin: int,
) -> int:
    """dev#1551(安全域WP、issue #1551「安全域」欄): `extended_source`
    (`(anchor,) + chain`、`fit_chain_to_length()`へ渡すのと同じ形)に対して
    実際に適用する安全域(削るdonor本数)を決める。`safety_margin_by_chain`に
    完全一致するキーがあればそれを使い(GUI「揺れもの詳細」の鎖ごとの
    上書き、`app_py\\sway_chain_override_store.py`の`bones`列と同じ
    タプル形)、無ければ`default_safety_margin`(呼び出し側既定、
    `sway_hub_wire.wire_and_diagnose_hub()`のdocstring参照)。負値は0に
    丸める(「削る」の逆(伸ばす)は本WPの対象外)。"""
    if safety_margin_by_chain:
        margin = safety_margin_by_chain.get(tuple(extended_source), default_safety_margin)
    else:
        margin = default_safety_margin
    return max(0, int(margin))


def target_len_with_safety_margin(n_ext: int, donor_capacity: int, margin: int) -> int:
    """dev#1551/dev#1572(安全域WP、2026-08-18オーナー最終裁定で式を訂正、
    2026-08-19朝オーナー追加裁定で容量root込み化+下限1許可):
    オーナー確定の計算式——「反映骨数(root込み) = max(1, min(donor容量
    (root込み) − 安全域, アバター鎖長(root込み)))」。**安全域はdonor容量
    だけを削る**——donorが潤沢に余っていれば安全域はアバター側の関節を
    一切削らない(旧式`min(donor容量, アバター鎖長) − 安全域`は、donorが
    豊富でもアバターの関節を無条件に削ってしまう誤りだった。検算表
    (donor5節・avatar3節): 安全域0〜2はいずれも3節のまま不変、安全域3で
    初めて2節へ減る——`min(5-3,3)=2`)。

    `n_ext`は`(anchor,) + chain`の長さ(anchor自身を含む、
    `ChainDonorPlan.source_chain`と同じ規約)。`donor_capacity`は
    **hub root自身を含めた**donor容量(呼び出し側の責務——
    `plan_hub_wiring()`のnative chain経路では`len(remaining_native)+1`
    (native descendant本数+hub root自身の1本)を渡すこと。hub root自身が
    アバター第1節(anchor)の実ジオメトリ+ウェイトを担う現役骨であるため
    (PR #1569、2026-08-19オーナー追加裁定)、`hub_native_descendant_chain()`
    の戻り(root抜き)をそのまま渡すと容量を1本過小評価する)。

    **下限1(2026-08-19朝オーナー裁定で2から緩和)**: 安全域がどれだけ
    大きくても反映骨数は0や負値にならず、最低1(=hub root自身1本へ
    アバター鎖全体が全結合、`fit_chain_to_length(chain, 1)`の「実効節数1
    のときだけ全結合」規則と対応)。旧裁定の下限2(anchor+子1本、根本の
    マージを避ける)は、容量勘定がroot抜きだった旧式に合わせた保守的な
    下限であり、容量をroot込みへ訂正した本裁定により不要になった
    (root込み容量1(=root自身のみ)でも`n=1`という有効な解が存在するため)。
    """
    effective_capacity = donor_capacity - max(0, int(margin))
    return max(1, min(effective_capacity, n_ext))


def merged_weight_groups(wiring: "HubWiringPlan") -> FrozenSet[FrozenSet[str]]:
    """`wiring`全体を走査し、`fit_chain_to_length()`が実際にマージした
    (=2要素以上をまとめた)グループ全部を`frozenset`の集合として返す
    (dev#1551)。`sway_degrade.detect_weight_collisions()`へ渡し、意図的な
    先端マージを「ウェイト衝突バグ」として誤検出しないための除外リスト
    として使う——`step02_retarget.py`の呼び出し側の責務。"""
    groups: Set[FrozenSet[str]] = set()
    for gp in wiring.group_plans:
        for cp in gp.chain_plans:
            by_rep: Dict[str, List[str]] = {}
            for member, rep in cp.weight_expansion.items():
                by_rep.setdefault(rep, []).append(member)
            for members in by_rep.values():
                if len(members) >= 2:
                    groups.add(frozenset(members))
    return frozenset(groups)


def representative_of_map(wiring: "HubWiringPlan") -> Dict[str, str]:
    """`wiring`全体の`weight_expansion`を1つの辞書へ合流させる
    (dev#1551): {元アバター骨名 -> 代表(マージ先)骨名}。節数フィット未
    発動の骨は恒等写像(`bone == representative_of[bone]`)。

    呼び出し側は、この写像で「非代表(マージされて消えた側)」と分かった
    骨について、`sway_source_gate.check_bone_transform()`の**個別**比較を
    スキップする(donorは代表骨のジオメトリで配置されているため、
    非代表骨自身の生transformと比べると構造的に不一致になる——`fit_
    chain_to_length()`の「マージ後の代表点はマージ区間の端点を保つ」
    という設計どおりの結果であり、バグではない)。代表骨自身(自己写像)は
    従来どおり厳密に比較する。"""
    out: Dict[str, str] = {}
    for gp in wiring.group_plans:
        for cp in gp.chain_plans:
            out.update(cp.weight_expansion)
    return out


def donor_group_members(cp: "ChainDonorPlan") -> Dict[str, Tuple[str, ...]]:
    """dev#1572(夜間便2、issue #1572追記「フィット計画を単一ソースに」):
    `cp.weight_expansion`(元アバター骨名 -> 代表(donor)骨名)から、
    `cp.source_chain`の各代表が実際に束ねている元アバター骨名の集合を、
    元の根元->先端順(`weight_expansion`の**挿入順**、`fit_chain_to_length()`
    が`groups`を根元から先端へ順に走って`expansion`を組み立てるため、
    Python 3.7+の辞書挿入順保証によりこの順序がそのまま元
    `extended_source`の並びを再現する)のまま`{代表名: (元要素...)}`として
    返す。

    **なぜ要るか**: `fit_chain_to_length()`のdocstring「マージ塊のdonor
    ノード幾何(呼び出し側の責務...): 塊の先頭骨のheadから末尾骨のtailまで
    のスパン」は、以前は呼び出し側(`place_hub_donor_chains()`/
    `sway_hub_placement.resolve_source_chain()`)ごとに**独自に**(かつ
    誤って)実装されていた——具体的には`cp.source_chain`の各代表名を
    そのまま「元の鎖の1点」として`av_point(name)`する実装になっており、
    代表名自身の位置しか読まず、マージされた非代表メンバー(グループの
    先頭側)の位置を一切参照していなかった。一方ウェイト側
    (`sway_hub_wire.source_to_donor_bone_map()`)は`weight_expansion`を
    正しく経由してグループ全メンバーへウェイトを展開しており、結果として
    「ウェイトが乗る境界」と「donorの物理的な形状(スパン)の境界」が
    ズレる実データバグを生んでいた(2026-08-19未明、指揮者がflatapron耳
    donorの実測ダンプで確認: 幾何は[001+002]スパンなのにウェイトは
    [Head_L.001]単独、というグループ境界の不一致)。

    本関数を`place_hub_donor_chains()`(bpy依存)と`sway_hub_placement.
    resolve_source_chain()`/`_hub_root_real_segment_transform()`
    (bpy非依存)の**両方**が経由することで、幾何とウェイトが同じ1つの
    グルーピングを共有する(二重実装の解消)。

    各代表`rep`について`groups[rep][0]`が塊の先頭骨(head側、根元寄り)、
    `groups[rep][-1]`が塊の末尾骨(tail側、先端寄り)——`rep`自身は常に
    `groups[rep][-1]`と一致する(`fit_chain_to_length()`の
    `rep = g[-1]`規約)。節数フィット未発動(恒等写像)の代表は単要素の
    タプル(`groups[rep] == (rep,)`)になる。

    dev#1572(房Merge): `cp.representative_source`が非空なら、その集合に
    含まれない`weight_expansion`のメンバー(=房Mergeで合流された代表枝
    以外の枝の骨、`expand_tuft_weight_mapping()`参照)を除外してから
    グルーピングする——**幾何(このグループ境界=donorのhead/tailスパン)は
    常に代表枝(最長枝)だけで決まる**ようにするため(房の非代表枝の
    骨がここに混ざると、donorの物理スパンが誤って非代表枝側へ歪む)。
    `representative_source`が空(既定、房でない通常の鎖・本関数を直接
    呼ぶ既存テスト)なら従来どおり無フィルタ(完全無退行)。"""
    filter_set = frozenset(cp.representative_source) if cp.representative_source else None
    groups: Dict[str, List[str]] = {}
    for member, rep in cp.weight_expansion.items():
        if filter_set is not None and member not in filter_set:
            continue
        groups.setdefault(rep, []).append(member)
    return {rep: tuple(members) for rep, members in groups.items()}


# =====================================================================
# ハブ割当+donorトポロジ計画
# =====================================================================

@dataclass(frozen=True)
class ChainDonorPlan:
    """1本のソース鎖に対する、donor骨名の列(ソース鎖と同じ長さ、順序対応)。

    **`source_chain`は`sway_allocator.ChainUnit.chains`の1要素そのものでは
    ない**——`group.anchor`(PBのroot骨自身、SPEC §5「PBのroot骨(anchor)
    自身も揺れる最初の可動骨であり、ハブ直下のドナーに写す」)を先頭に
    1本追加した拡張版(2026-08-16 dev#1508耳根元骨欠落バグ修正、
    `plan_hub_wiring()`のdocstring参照)。anchor自身はスキンウェイトを
    持つ実関節であり(VRChat PB Root Transform自体は物理シム対象外だが、
    メッシュの頂点ウェイトはanchor骨に乗っている——`sway_assign.py`の
    旧docstringが言う「anchor自身は揺れない」は物理ドメインの話であり、
    スキンドメイン(頂点ウェイトの転写先)では別の骨として扱わなければ
    ならない)。"""

    source_chain: Tuple[str, ...]

    # dev#1551(性別またぎdedup漏れ修正、issue #1551コメント/
    # work\run_1551\integG\RESULT.md正本): ハブrootが性別で異なる名前を
    # 持つ「bivariant」スロット(例: F_OldCloth001_04/M_OldCloth001_04)では、
    # donor鎖の続き骨(このフィールド)も女性向け/男性向けで**互いに素な**
    # 骨集合を持つ——共有Skeleton(SK_PalHuman_Skeleton)は単一の階層であり、
    # 同じ物理骨を2つの異なる親(M_root/F_root)へ同時にreparentすることは
    # できない(1本の骨は1つの親しか持てない)。以前は`donor_chain`という
    # 単一フィールドが性別に依らず**同じ骨集合**を指しており、
    # `plan_hub_wiring()`はgender引数を取らずに1回だけ計画を作っていたため、
    # 性別ごとに実行される`step02_retarget.py`が同じ骨名へ異なる新親
    # (M_root→F_root)を書こうとして衝突し、後着の性別(既定順でFemale)の
    # 書き込みが単純dedupで丸ごと落ちていた(実測: 両検体・全bivariant
    # タグでFemale側donor鎖が0件、根因コード根拠はintegG RESULT.md)。
    #
    # ハブroot自体が性別非依存(univariant、耳・しっぽ等の共有donor、
    # `hub_root_female == hub_root_male`)なスロットでは、女性向け/男性向けの
    # 計算結果が本来から完全に同一の値になる(0.0000cm一致、integG 1-3節で
    # 実測確認済み)ため、この場合は`donor_chain_female is donor_chain_male`
    # (同一タプルを共有、二重消費しない——`plan_hub_wiring()`参照)。
    # dev#1572(2026-08-19朝追加裁定「余剰donorの先端延長を全donor登録へ
    # 訂正」): native chain経路では、この列は**「内容」donor(実ウェイトを
    # 持つ、`source_chain`と対応する)+「延長」donor(内容写像が無い、
    # 無ウェイトの直線継続——`source_chain`より後ろのインデックスに
    # 対応する要素は無く、`sway_hub_wire.source_to_donor_bone_map()`の
    # zip()が自動的にウェイト対応から除外する)」の**両方**を含む。
    # `plan_hub_wiring()`docstring「native経路のdonor登録本数は安全域と
    # 無関係に常に全capacity」節参照。自由プール経路(leaf hub/bivariant)は
    # 延長を持たず、常に`source_chain`と同じ長さ(従来どおり)。
    donor_chain_female: Tuple[str, ...]
    donor_chain_male: Tuple[str, ...]

    # dev#1551(chain-length-fit WP): `source_chain`の各要素(元のアバター
    # 骨名、`_end`合成含む)を、実際にdonorが割り当たっている代表要素名へ
    # 写す辞書。**通常(節数フィット不発動)は恒等写像**
    # (`{b: b for b in source_chain}`)——`source_chain`自体がそのまま
    # `donor_chain_*`と1:1対応するため。節数フィット
    # (`fit_chain_to_length()`)が発動した場合のみ、複数の元要素が同じ
    # 代表(マージ先、常にマージ区間の先端側要素)を指す。
    #
    # `sway_hub_wire.source_to_donor_bone_map()`はこの辞書経由で「元の
    # 全アバター骨名 -> 実際のdonor骨名」を組み立てる(代表がdonorへ
    # 1:1対応、複数の元要素が同じ代表を指せば自動的に同じdonorへ集約
    # =ウェイトのADD合算、モジュールdocstring参照)。
    weight_expansion: Dict[str, str]

    # dev#1572(房Merge、issue #1572「房Mergeの機構」第3便): 幾何
    # (`donor_group_members()`が読む塊のhead/tailスパン)の絞り込みに使う、
    # 「代表枝(最長枝)の拡張ソース」(`(anchor,) + representative_chain`、
    # `fit_chain_to_length()`へ渡した`extended_source`と同一)。**既定は
    # 空タプル**(=絞り込み無効、房でない通常の鎖・本フィールドを知らない
    # 既存の直接構築テストは完全無退行——`donor_group_members()`docstring
    # 参照)。房Mergeが発動したチェーン(`select_tuft_representative()`が
    # `other_branches`を返した場合)のみ`plan_hub_wiring()`がここへ
    # `extended_source`を設定し、`weight_expansion`に合流された非代表枝の
    # 骨(ウェイト専用、幾何には無関係)を`donor_group_members()`から除外
    # させる。
    representative_source: Tuple[str, ...] = ()

    def donor_chain_for(self, gender: str) -> Tuple[str, ...]:
        """`gender`("Male"/"Female")に応じたdonor骨列を返す。呼び出し側
        (`sway_hub_placement.plan_reparent_steps()`・`sway_hub_wire.
        source_to_donor_bone_map()`・`pipeline\\blender\\step02_retarget.py`
        の`place_hub_donor_chains()`等)は、性別ごとに実行される処理から
        必ずこのメソッド経由で参照すること——`donor_chain_female`/
        `donor_chain_male`を直接使うと性別を取り違える恐れがある。"""
        return self.donor_chain_male if gender == "Male" else self.donor_chain_female


@dataclass(frozen=True)
class GroupHubPlan:
    """1つの採用`SwayGroup`に対するハブ配線計画(トポロジのみ、座標は
    含まない——モジュールdocstring「本モジュールが決めないもの」参照)。"""

    group: sway_allocator.SwayGroup
    hub_root_female: str
    hub_root_male: str
    anchor_target: str          # ハブをreparentする先(groupの親骨=group.anchor)
    chain_plans: Tuple[ChainDonorPlan, ...]


@dataclass(frozen=True)
class HubWiringPlan:
    """`plan_hub_wiring()`の戻り値一式。"""

    group_plans: Tuple[GroupHubPlan, ...]
    unassignable: Tuple[Tuple[sway_allocator.SwayGroup, str], ...]  # (group, reason)

    # dev#1551(chain-length-fit WP): `plan_hub_wiring()`が節数フィット
    # (先端マージ)を発動させたときの英語診断メッセージの列(既定=空、
    # 発動しなければ従来どおり空タプルで無変更)。呼び出し側
    # (`sway_hub_wire.wire_and_diagnose_hub()`)が既存の診断ログへ合流させる。
    chain_fit_events: Tuple[str, ...] = ()


def plan_hub_wiring(
    plan: sway_allocator.AllocationPlan,
    catalog: SkeletonCatalog,
    hub_slots: HubSlots,
    reserved: FrozenSet[str],
    protected: FrozenSet[str] = frozenset(),
    known_moving: FrozenSet[str] = frozenset(),
    amplitude_rank: Optional[Mapping[str, float]] = None,
    default_safety_margin: int = 0,
    safety_margin_by_chain: Optional[Mapping[Tuple[str, ...], int]] = None,
) -> HubWiringPlan:
    """`AllocationPlan.accepted`(優先順位順、最大9件)を、`hub_slots`の
    スロット順に1対1で割り当て、各グループの全鎖にdonor骨名列を配る
    (自由骨プールから、元のインデックス昇順で貪欲に消費——トポロジ制約を
    機械的に満たす、モジュールdocstring参照)。

    **トポロジ制約(2026-08-16実機smoke run実測で発見・本WPで修正)**:
    `sway_shared_skeleton.reparent_bone_content_only()`は`new_parent_idx
    <target_idx`(親は常に子より前の配列インデックス)を要求する。donorは
    共有Skeleton内で「元から存在する」骨(パッチは内容だけの書き換え、
    新規追加はしない)であり、その`target_idx`は**donor自身の元のカタログ
    インデックスに固定**される——一方、reparent先のハブroot骨(`new_parent`)
    は9スロットのうちどれかで、そのカタログインデックスはスロットごとに
    バラバラ(自由プール前方に低インデックスのdonor候補があっても、
    それが選ばれたスロットのハブroot自身より**若い**インデックスなら
    トポロジ違反になる——実データで実際に発生: donor候補
    `NPC_Female_SorajimaPeople01_tassel_01_l`(index=27)がハブroot
    `M_OldCloth001_04`(index=355)の子として選ばれ、27<355のため違反)。

    修正: 各スロットについて、そのスロットの**female/male両方のハブroot
    インデックスのうち大きい方**(共有Skeletonは男女のハブroot骨名を両方
    同時に持ち、`sway_hub_placement.plan_reparent_steps()`は性別ごとに
    別々のReparentStepを生成してマージされる——モジュールdocstring
    「本モジュールが決めないもの」およびstep02_retarget.pyのマージ処理
    参照。両性別の`new_parent`インデックスを両方満たす必要がある)より
    **後ろ**にあるdonorだけを対象に、元のインデックス昇順で貪欲に消費する
    (グループをまたいだ在庫排他は維持、消費済み集合で管理)。

    在庫不足(自由プールが尽きた、またはこのスロットのハブrootインデックス
    より後ろに十分な自由donorが残っていない)場合、そのグループは
    `unassignable`へ理由付きで回す(黙って一部の鎖だけ配線して残りを
    無視する、のような中途半端な状態を作らない——グループ単位で全鎖
    そろって配線できるかどちらかに倒す)。

    `protected`: `free_donor_pool()`docstring参照(基幹人型リグ保護)。
    呼び出し側は`vanilla\\common_bones.json`の`"common"`リストを渡すこと
    ——省略すると基幹ボーンがdonorに選ばれうる(安全性の欠落、本WPで
    追加)。

    **anchorオフバイワン修正(2026-08-16、dev#1508耳根元骨欠落バグ)**:
    `group.chains`の各鎖は`sway_allocator`の規約により`anchor自身を
    含まない`(子孫のみ)。しかしanchor骨(PBのroot骨)自身も実際に
    メッシュの頂点ウェイトを持つ実関節であり、SPEC §5「PBのroot骨
    (anchor)自身も揺れる最初の可動骨であり、ハブ直下のドナーに写す
    (chains配列だけを写すオフバイワン禁止)」の裁定どおり、**各チェーンの
    `source_chain`は`group.anchor`を先頭に追加した拡張版**
    (`(group.anchor,) + chain`)として donor を割り当てる
    (`ChainDonorPlan`docstring参照)。1グループが複数チェーンを持つ場合
    (同じanchorから分岐する複数鎖)、各チェーンは独立に「anchor+自チェーン」
    ぶんのdonorを消費する——同じanchorに複数のdonorが割り当たり得るが
    (dedup最適化はしない、実装の単純さ優先)、後続の
    `source_to_donor_bone_map()`は辞書の性質上最後に処理された割当が
    生き残るだけで、weight-remap先が曖昧になることはない(同じ実骨は
    常に同じworld位置を指すため、どのdonorが「勝つ」かは無害)。

    **`known_moving`/`amplitude_rank`(dev#1508 laneA4、amplitude-root)**:
    `known_moving`は`free_donor_pool()`docstring参照(既知の動く鎖donor
    骨を自由プールから除外)。`amplitude_rank`(`load_root_amplitude_rank()`
    相当、{root名: 振幅cm})を渡すと、スロット割当が単純な
    `enumerate(plan.accepted)`(優先順位=スロット順そのまま)ではなく、
    `_assign_slots_by_visibility_amplitude()`(可視性tier×振幅昇順マッチ、
    brief item2)へ切り替わる——**`accepted`自体の並び順(優先順位・容量9の
    判定)には一切影響しない**、あくまでどのグループがどの物理root名を
    得るかだけを変える。省略時(既定None)は従来どおりのenumerate順
    (④既定値不変)。

    **`default_safety_margin`/`safety_margin_by_chain`(dev#1551/dev#1572
    安全域WP、issue #1551「安全域」欄、2026-08-18オーナー最終裁定+
    2026-08-19朝オーナー追加裁定で容量root込み化+下限1許可)**:
    オーナー確定仕様「反映骨数(root込み) = max(1, min(donor容量(root込み)
    − 安全域, アバター鎖長))(安全域はdonor容量だけを削る)。削減は
    先端(tip)側からの分配マージ(`fit_chain_to_length()`)、根本は
    不変(実効節数1の全結合を除く)、反映骨数の下限は1」を実現する
    (`target_len_with_safety_margin()`)。
    「donor容量(root込み)」は、native chainを持つグループでは
    `len(remaining_native)+1`(hub root自身がアバター第1節=anchorの実
    donorを無償で1枠担う、PR #1569+2026-08-19朝裁定)——旧式(容量を
    `hub_native_descendant_chain()`の戻りのみ、root抜きで数える)は容量を
    1本過小評価し、安全域が意図せず1本分早く効いてしまうバグだった
    (`target_len_with_safety_margin()`docstring参照)。反映骨数の下限が
    1に達した場合、`donor_needed=target_len-1=0`(実ウェイトを持つ
    子孫donorは1本も消費されない)、hub root自身1本へアバター鎖全体が
    全結合される(`fit_chain_to_length(chain, 1)`の全結合規則)。

    **native経路のdonor*登録*本数は安全域と無関係に常に全capacity
    (2026-08-19朝追加裁定「余剰donorの先端延長を全donor登録へ訂正」)**:
    安全域が動かすのは`donor_needed`(実ウェイトを持つ「内容」donor本数)
    だけであり、`ChainDonorPlan.donor_chain_female`/`donor_chain_male`
    (実際にstep02がreparent登録する骨列)は常に`remaining_native`全部
    (内容+残り全部の無ウェイト延長)。安全域が大きいほど「内容」は減るが、
    その分「延長」(無ウェイト・最終内容セグメントと同じseg_vec方向への
    直線継続、`place_hub_donor_chains()`/`sway_hub_placement.
    resolve_grouped_chain()`の既存「余剰donor」ロジックが担う)が増え、
    donor*登録*総数(=native_chainの全長、グループ内の後続チェーンへの
    持ち越しも含め)は不変——旧裁定(v2.11以前)の「donorのstep02適用節数は
    安全域に関わらず常に全容量」を復元する(dev#1572のPR #1577で「内容
    本数ぶんのdonorしか登録しない」退行が入っていたのを訂正)。
    自由プール経路(leaf hub/bivariant)はこの延長の対象外(自由プールは
    容量無制限扱いで「余剰」という概念自体が無い、既存どおり
    `target_len`本だけを消費)。
    各鎖の`extended_source`(`(anchor,)+chain`)ごとに`resolve_safety_margin()`
    で実効安全域を決める(`safety_margin_by_chain`の完全一致キーを優先、
    無ければ`default_safety_margin`)。両引数とも既定は0(=旧来どおり
    無効化、完全無退行)。呼び出し側(`sway_hub_wire.wire_and_diagnose_hub()`
    docstring参照)が製品既定値(1)を明示的に渡す。"""
    hub_names_slot_order = hub_slots.female  # スロット順の代表(female側)
    if len(plan.accepted) > len(hub_names_slot_order):
        raise SwayHubError(
            f"AllocationPlan.accepted has more groups ({len(plan.accepted)}) "
            f"than hub slots ({len(hub_names_slot_order)}) -- "
            "sway_allocator.allocate()のcapacityがハブスロット数を超えている")

    free_pool = free_donor_pool(
        catalog, reserved, list(hub_slots.female) + list(hub_slots.male),
        protected=protected, known_moving=known_moving)
    consumed: Set[str] = set()
    # dev#1551(chain-length-fit): 他ハブの領域に踏み込まないための
    # native-chain walkの停止集合(このスロット自身のhub名を含んでいても
    # 無害——walkはhub自身から出発しhub自身を再訪しない一本道のため)。
    all_hub_names = frozenset(hub_slots.female) | frozenset(hub_slots.male)
    chain_fit_events: List[str] = []

    group_plans: List[GroupHubPlan] = []
    unassignable: List[Tuple[sway_allocator.SwayGroup, str]] = []

    if amplitude_rank:
        slot_indices = _assign_slots_by_visibility_amplitude(
            plan.accepted, hub_names_slot_order, amplitude_rank)
    else:
        slot_indices = list(range(len(plan.accepted)))

    for pos, group in enumerate(plan.accepted):
        slot = slot_indices[pos]
        hub_female, hub_male = hub_slots.both_names_at(slot)
        # dev#1551(性別またぎdedup漏れ修正): このスロットのハブroot自体が
        # 性別で異なる名前を持つか(bivariant)。univariant(耳・しっぽ等の
        # 共有donor、hub_female==hub_male)ならdonor鎖続き骨も女性/男性で
        # 同じ骨集合を共有してよい(値が完全に同一になるため衝突しない、
        # ChainDonorPlan.donor_chain_forのdocstring参照)。bivariantなら
        # 女性向け/男性向けで**互いに素な**donor骨集合を割り当てる必要が
        # あるため、消費数を2倍にする。
        is_bivariant = hub_female != hub_male
        # 両性別のハブrootインデックスのうち大きい方より後ろのdonorだけが
        # トポロジ制約を両性別ぶん同時に満たせる(docstring参照)。
        hub_idx_bound = max(catalog.index_of(hub_female), catalog.index_of(hub_male))
        available = [name for name in free_pool
                     if name not in consumed and catalog.index_of(name) > hub_idx_bound]

        # dev#1508 hubwire final(2026-08-16オーナー裁定「グループ化は
        # (親骨×ゆれかた)」): 1グループが複数の異なるanchor(耳L/R等)を
        # 統合しうるようになったため、prependするanchorは`group.anchor`
        # (代表値、統合後は必ずしも各chainの本来のanchorと一致しない)
        # ではなく、**そのchainが実際に属するunit自身のanchor**
        # (`unit.anchor`)を使う——`group.chains`(フラット化済み、anchor
        # 対応を失っている)ではなく`group.units`(各`ChainUnit.anchor`を
        # 保持)を辿ることで、統合前と同じ「anchor自身も揺れる最初の
        # 可動骨」donor割当を各anchorについて独立に維持する。単一anchorの
        # グループ(統合が起きなかった従来どおりのケース)では
        # `unit.anchor == group.anchor`なので出力は無変更。
        #
        # dev#1551(chain-length-fit): univariantなスロット(hub_female==
        # hub_male)では、ハブroot自身の共有Skeleton内native直系子孫
        # (同じ装備メッシュ由来、無関係な自由骨より実機で歩行可能な公算が
        # 高い、モジュールdocstring参照)を、自由骨プールより優先して使う。
        # 1グループが複数チェーンを同じハブへ統合する場合、native_chainは
        # 消費順に使い切り(native_cursor)、尽きたチェーンだけ自由プールへ
        # 回す——このため「自由プールから実際に何本要るか」は事前に1回
        # シミュレーションしないと分からず(native chainが吸収する分を
        # 見込まないと旧来のn_needed_total判定が過大になる)、
        # 以下は(a)dry-runで自由プール必要数を求めて容量判定→
        # (b)判定を通ったら同じ順序で実割当、の2パス構成にする。
        # bivariantスロットは対象外(女性/男性で別名のハブrootを持つため
        # native chainの長さが揃う保証が無く、複雑化を避けて既存の自由
        # プール経路のまま——将来WPで拡張可)。native_chain=()なら以下の
        # ロジックは常に「自由プールから丸ごと」を選び、無変更に帰着する。
        native_chain = (() if is_bivariant else
                        hub_native_descendant_chain(hub_female, catalog, all_hub_names))

        # dev#1572(房Merge、issue #1572「房Mergeの機構」第3便): 1つの
        # unit(=1つのPB/SBコンポーネント)が複数チェーン(房・Y字分岐)を
        # 持つ場合、旧来は各チェーンを独立した`chains_flat`エントリとして
        # 別々のdonor家系へ割り当てていた(v2.11の猫又が「2枝が別々のdonor
        # 家系へ独立割当されて両方揺れていた」、issue追記2)。房Mergeは
        # ここで各unitぶん**1エントリ**(代表=最長枝、others=残りの枝)へ
        # 畳み、代表枝だけが以降のdonorフィット・容量勘定を通る——房でない
        # 通常のunit(chains長さ0/1)は`select_tuft_representative()`が
        # 恒等を返すため、この変更は無関係(完全無退行)。
        chains_flat: List[Tuple[str, Tuple[str, ...], Tuple[Tuple[str, ...], ...]]] = []
        for unit in group.units:
            representative, other_branches = select_tuft_representative(unit.chains)
            if not representative and not other_branches:
                continue  # unit.chainsが空(通常は起きない、安全側でスキップ)
            chains_flat.append((unit.anchor, representative, other_branches))

        def _dry_run() -> int:
            native_cursor = 0
            free_needed = 0
            for anchor, chain, _other_branches in chains_flat:
                # 容量勘定(安全域・節数Merge)の母集団は代表枝(最長枝)基準
                # (dev#1572 房Merge指示: 「安全域・節数Mergeの母集団は代表枝
                # (最長枝)基準でよい——枝ごとに違う長さの厳密扱いはしない」)。
                extended_source = (anchor,) + chain
                n_ext = len(extended_source)
                margin = resolve_safety_margin(
                    extended_source, safety_margin_by_chain, default_safety_margin)
                if native_chain:
                    # dev#1572(2026-08-19朝裁定): donor容量はhub root自身
                    # +1を含める(remaining_nativeはroot抜き子孫のみ)。
                    # native chainがこのグループに存在する限り(univariantで
                    # leaf hubでない限り)、下限1(root単独)まで常に native
                    # 経路で吸収できるため、自由プールへは絶対に落ちない。
                    remaining_native = len(native_chain) - native_cursor
                    capacity_root_included = remaining_native + 1
                    target_len = target_len_with_safety_margin(
                        n_ext, capacity_root_included, margin)
                    # dev#1572(2026-08-19朝追加裁定「余剰donorの先端延長を
                    # 全donor登録へ訂正」): 安全域は内容本数(donor_needed)
                    # だけを動かし、実際に登録するdonor本数(=native_cursorの
                    # 消費量)は常にこのチェーンが持つ残りnative全部
                    # (remaining_native)——実割当ループと対称に、ここでも
                    # cursorをremaining_native全量ぶん進める(以降のチェーンは
                    # 自由プールへは決して落ちない設計自体は不変、この
                    # dry-runの戻り値free_neededには影響しない)。
                    native_cursor += remaining_native
                else:
                    # 自由プールは(dry-run/実割当とも)容量無制限扱い
                    # ——実在の枯渇判定は`n_needed_total > len(available)`側で
                    # 別途行う(既存規約、docstring参照)。leaf hub(native
                    # chain無し)/bivariantスロットはroot込み容量の対象外
                    # (root自身は自由プール経路でも実は1枠を担うが、自由
                    # プールは無制限扱いなので容量計算上は影響しない——
                    # 本WPのスコープ外、dev#1572背景参照)。
                    target_len = target_len_with_safety_margin(n_ext, n_ext, margin)
                    free_needed += target_len * (2 if is_bivariant else 1)
            return free_needed

        n_needed_total = _dry_run()
        if n_needed_total > len(available):
            unassignable.append((group, (
                f"free donor pool exhausted after topology filtering (slot={slot}, "
                f"hub={hub_female}/{hub_male}, need {n_needed_total} bone(s)"
                f"{' (x2: bivariant hub root needs disjoint donor chains per gender)' if is_bivariant else ''} "
                f"with catalog index > {hub_idx_bound}, {len(available)} available)")))
            continue

        chain_plans: List[ChainDonorPlan] = []
        cursor = 0
        native_cursor = 0
        for anchor, chain, other_branches in chains_flat:
            extended_source = (anchor,) + chain
            n_ext = len(extended_source)
            margin = resolve_safety_margin(
                extended_source, safety_margin_by_chain, default_safety_margin)

            if native_chain:
                # dev#1572(2026-08-19朝裁定、root込み容量): このグループが
                # native chainを持つ限り(univariantでleaf hubでない限り)、
                # 常にこの経路——下限1(root自身のみ、native descendant
                # 0本)まで native+root だけで吸収できるため、旧来の
                # 「native不足→自由プールへフォールバック」分岐は構造的に
                # 到達不能になった(_dry_run()と対称)。
                remaining_native = native_chain[native_cursor:]
                capacity_root_included = len(remaining_native) + 1
                target_len = target_len_with_safety_margin(
                    n_ext, capacity_root_included, margin)
                donor_needed = target_len - 1  # 内容(実ウェイト)donor本数、root自身が1枠を無償で担う
                fitted_source, expansion = fit_chain_to_length(extended_source, target_len)
                content_donors = remaining_native[:donor_needed]
                # dev#1572(2026-08-19朝追加裁定「余剰donorの先端延長を全
                # donor登録へ訂正」): 安全域が動かすのは内容(donor_needed)
                # 本数だけ——実際に登録するdonor本数(donor_chain_female/
                # donor_chain_male)は常にこのチェーンが持つ残りnative全部
                # (remaining_native)であり、内容を超えた残りは「無ウェイト・
                # 同長の直線延長」として全部付ける(内容写像が無い=
                # weight_expansionの値に一切現れない=source_to_donor_bone_
                # map()のzip()が自動的にウェイト対応から除外する、モジュール
                # docstring/`sway_hub_wire.source_to_donor_bone_map()`
                # docstring参照)。幾何配置(`place_hub_donor_chains()`/
                # `sway_hub_placement.resolve_grouped_chain()`)は既に
                # 「余剰donor(内容写像の対応が無い延長donor)」を最終内容
                # セグメントと同じseg_vec方向へ直線延長する既存ロジックを
                # 持つ(2026-08-19時点では常にn_donor==donor_needed止まりで
                # 発動していなかった、本WPでdonor_female/maleを全量へ拡張
                # したことで初めて発動する)。安全域はdonor容量(root込み)
                # だけを削る、というオーナー確定式の意味を「反映(＝実際に
                # メッシュ含む)骨数」ではなく「登録するdonor骨数」には及ばさない
                # ——登録総数は常に容量(native_chain全長+root)で不変。
                donor_female = remaining_native  # 内容+延長(常に全部)
                native_cursor += len(remaining_native)  # 内容・延長問わず全部消費
                donor_male = donor_female
                if target_len < n_ext:
                    # 容量root込みでもnative側が本来足りない(margin=0でも
                    # 縮退する)なら「chain-fit」、native+rootには十分な
                    # 余裕がありmarginだけが縮退の原因なら「safety-margin」
                    # ——旧分岐(branch1/branch2)のタグ分けを踏襲する。
                    tag = ("sway-safety-margin" if capacity_root_included >= n_ext
                           else "sway-chain-fit")
                    n_extension = len(remaining_native) - donor_needed
                    donor_desc = (f"hub root + {donor_needed} native donor(s) "
                                  f"{list(content_donors)!r}" if donor_needed > 0
                                  else "hub root only, no native donor consumed")
                    if n_extension > 0:
                        donor_desc += (f" + {n_extension} unweighted extension "
                                        "donor(s) (straight continuation)")
                    chain_fit_events.append(
                        f"[{tag}] chain for anchor={anchor!r} "
                        f"(hub={hub_female!r}) merged from tip (safety_margin={margin}): "
                        f"{n_ext} source bone(s) {list(extended_source)!r} -> "
                        f"{target_len} donor slot(s) ({donor_desc}) "
                        f"(root {extended_source[0]!r} kept unmerged)")
                # dev#1572(房Merge): `other_branches`(この鎖が房だった場合の
                # 非代表枝)の骨を、同じ深さの代表枝の骨が対応するdonor代表へ
                # 追加で写す——ウェイト側(`weight_expansion`)だけを合流し、
                # 幾何(`donor_group_members()`)は`representative_source`で
                # 代表枝のみへ絞る(`ChainDonorPlan.representative_source`
                # docstring参照)。`other_branches`が空なら`expansion`と
                # 完全に同一(恒等、無退行)。
                full_expansion = expand_tuft_weight_mapping(chain, expansion, other_branches)
                chain_plans.append(ChainDonorPlan(
                    source_chain=fitted_source,
                    donor_chain_female=donor_female, donor_chain_male=donor_male,
                    weight_expansion=full_expansion, representative_source=extended_source))
                continue

            # native chainが無い(leaf hub)、またはbivariantスロット——
            # 既存の自由プール経路(dev#1551安全域WP): 自由プールは容量
            # 無制限扱い(donor_capacity=n_ext)なので、target_len=n_ext-margin
            # (下限1)。dev#1572のroot込み容量勘定は対象外(背景参照)。
            target_len = target_len_with_safety_margin(n_ext, n_ext, margin)
            fitted_source, expansion = fit_chain_to_length(extended_source, target_len)
            if target_len < n_ext:
                chain_fit_events.append(
                    f"[sway-safety-margin] chain for anchor={anchor!r} "
                    f"(hub={hub_female!r}) merged from tip (safety_margin={margin}): "
                    f"{n_ext} source bone(s) {list(extended_source)!r} -> "
                    f"{target_len} free-pool donor slot(s) (root {extended_source[0]!r} "
                    f"kept unmerged)")
            donor_female = tuple(available[cursor:cursor + target_len])
            cursor += target_len
            if is_bivariant:
                # dev#1551: 男性向けは女性向けと重ならない次のブロックを
                # 消費する(互いに素な骨集合、docstring参照)。
                donor_male = tuple(available[cursor:cursor + target_len])
                cursor += target_len
            else:
                # univariant: 女性/男性で同一の骨集合を指す(二重消費
                # しない、既存挙動と完全に無変更——integG 1-3節で
                # 0.0000cm一致確認済みの経路)。
                donor_male = donor_female
            # dev#1572(房Merge): 上のnative経路と同じ合流(コメント参照)。
            full_expansion = expand_tuft_weight_mapping(chain, expansion, other_branches)
            chain_plans.append(ChainDonorPlan(
                source_chain=fitted_source,
                donor_chain_female=donor_female, donor_chain_male=donor_male,
                weight_expansion=full_expansion, representative_source=extended_source))
        consumed.update(available[:cursor])

        group_plans.append(GroupHubPlan(
            group=group, hub_root_female=hub_female, hub_root_male=hub_male,
            anchor_target=group.anchor, chain_plans=tuple(chain_plans)))

    return HubWiringPlan(group_plans=tuple(group_plans), unassignable=tuple(unassignable),
                          chain_fit_events=tuple(chain_fit_events))


def filter_wiring_by_resolvable_anchor(
    wiring: HubWiringPlan, anchor_pal_name_of: Mapping[str, str],
) -> HubWiringPlan:
    """`wiring.group_plans`のうち、`anchor_pal_name_of`(呼び出し側が
    `build_group_targets()`等で用意する{アバター骨名->PALボーン名})へ
    `group.anchor`が解決できないグループを`unassignable`側へ理由付きで
    移す(グループ単位で座標配置・pak側reparent計画の両方から除外する
    ための共通フィルタ、dev#1508 W2a-2c)。

    **なぜ必要か**: PB/SBの`anchor`(コンポーネントのrootTransform名)は
    必ずしもavatar_armの実ボーンに対応するとは限らない(NDMFベイク後に
    生成される名前($GUID付き)がボーンとしてインポートされない場合がある、
    実データ検証で確認)。`sway_hub_placement.plan_reparent_steps()`は
    未解決を`SwayHubPlacementError`で例外化する設計(呼び出し側が
    「完全なanchor_pal_name_of」を渡す契約)のため、呼び出し側
    (`step02_retarget.py`)は本関数で事前にグループ単位フィルタしてから
    渡す——個別の未解決チェーン1本のために変換全体を止めない、既存の
    `reposition_sway_donor_chain_and_leaf()`等と同じ安全側フォールバック
    方針(die()しない)を、ハブ経路でも一貫させる。

    戻り値のgroup_plansは元の順序を保つ。node_overrides/refskel_dict/
    診断ログは、本関数の戻り値に対して**再計算**すること(呼び出し側の
    責務、フィルタ前の値を使い回さない)。"""
    resolvable: List[GroupHubPlan] = []
    newly_unassignable: List[Tuple[sway_allocator.SwayGroup, str]] = []
    for gp in wiring.group_plans:
        anchor_pal = anchor_pal_name_of.get(gp.group.anchor)
        if anchor_pal is None:
            newly_unassignable.append((gp.group, (
                f"anchor {gp.group.anchor!r} has no resolvable PAL-side bone "
                "(anchor_pal_name_of incomplete -- likely a non-bone "
                "PB/SB rootTransform)")))
            continue
        resolvable.append(gp)
    return HubWiringPlan(
        group_plans=tuple(resolvable),
        unassignable=wiring.unassignable + tuple(newly_unassignable))


def filter_wiring_excluding_units(
    wiring: HubWiringPlan, excluded_unit_keys: FrozenSet[str],
    reason: str = "excluded by sway degrade loop retry",
) -> HubWiringPlan:
    """dev#1551 Lane V(VRM経路step02 KeyError修理): `wiring`から
    `excluded_unit_keys`に属するunit(`ChainUnit.key`、dev#1551以降は
    1unit=1group=1KPノードなので実質グループ単位)を持つグループを
    取り除いた**部分集合**を返す(`plan_hub_wiring()`を再実行しない)。

    **なぜ再実行ではなく部分集合フィルタでなければならないか(根本原因)**:
    `plan_hub_wiring()`のdonor骨割当は自由donorプールを`plan.accepted`の
    出現順に貪欲消費するグローバルな計画であり、あるグループを
    `plan.accepted`から取り除いて`plan_hub_wiring()`を**再実行**すると、
    (除外されたグループより後ろで処理される)残る全グループへの自由
    プール消費の開始位置がずれ、既存グループへ**前回とは異なるdonor骨**が
    割り当てられうる——グループを減らす操作は「配線結果の部分集合」を
    全く保証しない(実データで確認: VRM入力Seed-san.vrmの縮退リトライで
    `M_Hunter001_14`系グループへ女性用donor骨`F_Bronze001_bag_01`が新規に
    割り当てられた)。

    `pipeline\\blender\\step02_retarget.py`の`run_sway_degrade_loop()`は、
    attempt0(初回`wire_sway_hub_auto()`)の結果だけを使ってBlenderの
    `pal_arm`(編集対象armature)を1回だけ構築し、以後のリトライは
    「pal_armに含まれる骨だけを対象に配線しなおす」という前提で書かれて
    いた(同関数のdocstring)——`plan_hub_wiring()`を再実行するとこの前提が
    破れ、pal_armに存在しない新規donor骨をKeyErrorで参照してクラッシュ
    する(dev#1551 Lane V実測)。

    本関数は`plan_hub_wiring()`を一切呼ばない(座標・donor名は`wiring`
    (通常はattempt0の結果)からそのまま引き継ぐ)ため、戻り値の
    `group_plans`は入力`wiring.group_plans`の**文字どおりの部分集合**
    (順序も要素も変更なし)であることが構造的に保証される——リトライを
    何度繰り返しても、attempt0の時点でpal_armへ既に構築済みの骨集合を
    超えることは無い。

    戻り値のgroup_plansは元の順序を保つ。node_overrides/refskel_dict/
    診断ログは、本関数の戻り値に対して呼び出し側が再計算すること
    (`filter_wiring_by_resolvable_anchor()`と同じ流儀)。"""
    kept: List[GroupHubPlan] = []
    newly_unassignable: List[Tuple[sway_allocator.SwayGroup, str]] = []
    for gp in wiring.group_plans:
        unit_keys = {u.key for u in gp.group.units}
        if unit_keys & excluded_unit_keys:
            newly_unassignable.append((gp.group, reason))
            continue
        kept.append(gp)
    return HubWiringPlan(
        group_plans=tuple(kept),
        unassignable=wiring.unassignable + tuple(newly_unassignable))


def node_overrides_from_wiring_plan(
    wiring: HubWiringPlan,
) -> Dict[str, Dict[str, object]]:
    """`sway_abp_build.build_spec_nodes()`のnode_overrides引数
    ({root_bone名: {"style","limit_angle"}})を組み立てる。SPEC §1-5
    「男女で採用結果を同一にするため」、同じスロットのfemale/male両方の
    ハブroot名へ同じ値を書く(sway_allocator_wire.compute_node_overrides()の
    後継——キーが「実際に配線されたdonorのchain_root」から「ハブroot骨」へ
    変わった点が本WPの変更点)。"""
    overrides: Dict[str, Dict[str, object]] = {}
    for gp in wiring.group_plans:
        # グループ内のunitが複数あっても(anchor,style)は共通(build_groups()の
        # 契約)なので代表unitのlimit_angleを使う——ただしunit間でlimit_angleが
        # 異なりうる(角度制限は鎖単位、SPEC §1-3b)場合は最小値を安全側に採用
        # (最も厳しい制限を優先。0=無制限は「制限なし」なのでmin()に混ぜると
        # 誤って無制限を選んでしまうため、0はスキップして残りの最小、全部0なら0)。
        angles = [u.limit_angle for u in gp.group.units if u.limit_angle > 0]
        limit_angle = min(angles) if angles else 0.0
        value = {"style": gp.group.style, "limit_angle": limit_angle}
        overrides[gp.hub_root_female] = value
        overrides[gp.hub_root_male] = value
    return overrides


# =====================================================================
# 診断ログ(sway_allocator_wire.build_diagnostics_lines()のハブ版、W2a-2c)
# =====================================================================

def _original_settings_for(unit: sway_allocator.ChainUnit) -> Dict[str, object]:
    """`sway_allocator_wire._original_settings_for()`と意図的に同一の実装
    (ハブ経路はsway_assign/sway_allocator_wireへ依存しないため、本モジュール
    内に独立した診断整形を持つ——両モジュールとも同じ`ChainUnit.params`契約
    (SPEC.md §5)を読むだけの純粋関数であり、二重実装のコストは軽微)。"""
    base: Dict[str, object] = {
        "type": unit.source,
        "pb_object_name": unit.pb_object_name,
        "collider_count": unit.collider_count,
    }
    p = unit.params
    if unit.source == "pb":
        base.update({
            "limit_type": p.get("limit_type"),
            "limit_rotation": p.get("limit_rotation"),
            "max_angle_x": p.get("max_angle_x"),
            "pull": p.get("pull"),
            "spring": p.get("spring"),
            "integration_type": p.get("integration_type"),
        })
    else:
        base.update({
            "stiffness": p.get("stiffness"),
            "gravity_power": p.get("gravity_power"),
            "drag_force": p.get("drag_force"),
        })
    return base


def build_diagnostics_lines(
    plan: sway_allocator.AllocationPlan,
    wiring: HubWiringPlan,
    gender: str,
) -> List[str]:
    """`plan.all_units`(採用/非採用問わず)全件について、ハブ配線結果を
    含めた診断1行JSONを返す(`sway_allocator_wire.build_diagnostics_lines()`と
    同一のレコード形——オーナー追加指示2026-08-16の4要件、モジュール
    docstring参照——だが`donor_root_bone`はハブ経路では「そのグループが
    束ねられたハブroot骨名」(`gender`に応じてfemale/male側を選ぶ)を指す。

    `wiring.unassignable`(donor自由プール枯渇でグループごと配線不能に
    なったケース)の理由も、該当グループに属する全ユニットへ
    `wiring_lost_reason`として反映する。

    dev#1508 hubwire final(2026-08-16オーナー裁定「グループ化は
    (親骨×ゆれかた)」): 1グループが複数の異なるanchor(耳L/R等)を統合
    しうるようになったため、`(unit.anchor, unit.style)`を再計算して
    `gp.group.group_key`(統合後は`(親humanoid骨, style)`)と突き合わせる
    旧実装は、統合されたunit(代表anchorと異なる側)で一致せず誤って
    「配線されていない」と報告する退行を起こす。unit自身(`unit.key`、
    コンポーネント単位で一意)を`gp.group.units`から直接引く方式へ変更し、
    グループ化の鍵がどう変わっても常に正しく突き合わせる。"""
    hub_by_unit_key: Dict[str, str] = {}
    for gp in wiring.group_plans:
        hub_name = gp.hub_root_male if gender == "Male" else gp.hub_root_female
        for u in gp.group.units:
            hub_by_unit_key[u.key] = hub_name
    reason_by_unit_key: Dict[str, str] = {}
    for g, reason in wiring.unassignable:
        for u in g.units:
            reason_by_unit_key[u.key] = reason

    lines: List[str] = []
    for unit in plan.all_units:
        judged = {
            "candidate": True,
            "is_biased": unit.is_biased,
            "bias_reason": unit.bias_reason,
            "style": unit.style,
            "limit_angle": unit.limit_angle,
            "is_tail": unit.is_tail,
            "group_key": [unit.anchor, unit.style] if unit.style else None,
        }
        hub_name = hub_by_unit_key.get(unit.key)
        lost_reason = reason_by_unit_key.get(unit.key)

        wiring_lines = []
        for chain in unit.chains:
            if hub_name is not None:
                wiring_lines.append({"chain": list(chain), "donor_root_bone": hub_name})
            elif lost_reason is not None:
                wiring_lines.append({
                    "chain": list(chain), "donor_root_bone": None,
                    "wiring_lost_reason": lost_reason})
            else:
                wiring_lines.append({"chain": list(chain), "donor_root_bone": None})

        record: Dict[str, object] = {
            "sway_diag": True,
            "key": unit.key,
            "anchor": unit.anchor,
            "original": _original_settings_for(unit),
            "judged": judged,
            "excluded_reason": unit.excluded_reason,
            "wiring": wiring_lines,
        }
        if unit.collider_count > 0:
            record["collider_note"] = (
                f"元はコライダー{unit.collider_count}個で保護、変換後は保護なし"
                "(dev#1508 SPEC.md §2 コライダー放棄確定)")
        lines.append(json.dumps(record, ensure_ascii=False))
    return lines


# =====================================================================
# refskel-dict構築(Blender工程のbuild_pal_armature/pak側refskel拡張の
# 両方が食べられる形、W2a-2c)
# =====================================================================

# ハブroot骨の構造登録上の親(refskel-dict内のプレースホルダ)。全性別・
# 全ハブスロットで常に存在が保証されている共通ボーン(vanilla\common_bones.json
# の"common"に必ず含まれる)を使う——**この値はグループの実際のアンカー骨
# ではない**(意図的な設計判断、指示書完了報告参照): 実際のワールド位置は
# per-avatarのchibi_bone_world_head機構が別途パッチする(build_avatar_variant.py
# のcompute_patched_local_positions()は指定ボーンのワールド目標位置から
# 「宣言された親」基準のローカルオフセットを逆算するため、宣言された親が
# 何であってもパッチ後のワールド位置は正しくなる——親宣言の役割は
# `vp_refskel_extend.resolve_missing_bone_chain()`が安全かつ短い経路で
# 「既存のRefSkeletonへ到達できる」ことを保証するためだけの構造的placeholder)。
# 実際に描画されるキャラクターの物理・アニメーション階層は共有Skeleton
# (SK_PalHuman_Skeleton)側のreparent(Phase 3.7、`sway_hub_placement.
# plan_reparent_steps()`が正しいanchor_pal名で構築する)が担う。
PLACEHOLDER_STRUCTURAL_PARENT = "pelvis"

# 構造登録専用の非退化プレースホルダ値(_add_one_leaf_bone()と同じ発想:
# 「RefSkeletonへ構造登録するための仮の非ゼロ値」で足り、この値そのものが
# 実機出力に残ることは無い。extract_vanilla.py _add_one_leaf_bone()参照)。
_PLACEHOLDER_QUAT = [0.0, 0.0, 0.0, 1.0]
_PLACEHOLDER_POS = [0.0, 0.0, 1.0]
_PLACEHOLDER_SCALE = [1.0, 1.0, 1.0]


def refskel_dict_for_wiring(
    wiring: HubWiringPlan, gender: str,
    placeholder_parent: str = PLACEHOLDER_STRUCTURAL_PARENT,
    anchor_pal_of: Optional[Mapping[str, str]] = None,
) -> Dict[str, Dict[str, object]]:
    """`wiring`(`gender`向け)が実際に使うハブroot骨+全donor鎖骨だけを対象に、
    `vp_core.load_refskel()`と同一の形({name: {"parent","quat","pos","scale"}})の
    refskel-dictを返す(`pipeline\\blender\\vp_bl.build_pal_armature()`の
    `refskel_path`引数へそのまま渡せる、および
    `build_pak_from_avatar._refskel_extend_overrides()`が読む
    `vanilla\\refskel_*_{gender}.json`と同じ拡張材料として使える——両者とも
    `merge_refskel_files()`/グロブパターンで「ファイル名に依らずマージする」
    設計のため、本関数の出力をそのままJSONへ書けば両方の消費者に配線される)。

    トポロジ: ハブrootの親は`anchor_pal_of`が引ければその値、引けなければ
    `placeholder_parent`(モジュール定数のdocstring参照)。donor鎖ノードiの
    親はチェーン内の1つ前のノード(i==0ならハブroot自身)。座標値は全て
    構造登録専用のプレースホルダ(per-avatarの実位置はBlender側の再配置+
    chibi_bone_world_head機構が別途決める、モジュール定数のdocstring参照)。

    `anchor_pal_of`(dev#1551 integ14、メッシュ側RefSkeleton reparent欠落の
    修正): {アバターボーン名(`SwayGroup.anchor`、`GroupHubPlan.anchor_target`と
    同じ)-> 対応する共有Skeleton内の実PALボーン名}。呼び出し側
    (`step02_retarget.py`の`group_targets`/`anchor_pal_map`、
    `sway_hub_placement.plan_reparent_steps()`が受け取る`anchor_pal_name_of`と
    同一の辞書)が用意する。**integ13の実機実測(work\\run_1551\\integ13\\
    RESULT.md)で判明した構造欠陥の修正**: 従来はハブroot骨の親を常に
    `placeholder_parent`("pelvis"、モジュール定数のdocstring「実際の
    ワールド位置はper-avatarのchibi_bone_world_head機構が別途パッチする
    ため親宣言の値自体はどうでもよい」という設計前提)にしていたが、
    `build_pak_from_avatar._refskel_extend_overrides()`のreparent_needed
    機構(既存donor骨の親上書き)がこの値を**メッシュ側(実際に注入される
    出力SK自身)のRefSkeletonへもそのまま書き込む**ため、メッシュ側の
    ハブroot親が実アンカー("head"等)ではなく"pelvis"に固定される実害が
    integ13実機測定(Hair037_tail_root_01の対Head偏差15cm、対照
    HeadEquip062_ear_01_lとbyte-for-byte一致)で確認された——共有Skeleton
    (Phase 3.7)側だけを正しくreparentしても、ランタイムFKはメッシュ側
    RefSkeletonの親を使うため無効化されていた。`anchor_pal_of`を渡すことで
    この値を実アンカーへ揃え、共有Skeleton側(`sway_hub_placement.
    plan_reparent_steps()`の①ハブroot自身reparent)と同じ親を持たせる。
    省略時(None、既定)は従来どおり`placeholder_parent`のまま(後方互換、
    既存呼び出し元・テストは無変更)。解決できない(辞書に無い/Noneが
    引ける)グループは`placeholder_parent`へフォールバックする(warning無しの
    fail-safe——構造登録専用の値のため、この骨は後段の
    `_refskel_extend_overrides()`のreparent_neededが単に対象外になるだけで
    安全)。"""
    refskel: Dict[str, Dict[str, object]] = {}

    def _placeholder(parent: Optional[str]) -> Dict[str, object]:
        return {"parent": parent, "quat": list(_PLACEHOLDER_QUAT),
                "pos": list(_PLACEHOLDER_POS), "scale": list(_PLACEHOLDER_SCALE)}

    for gp in wiring.group_plans:
        hub_name = gp.hub_root_male if gender == "Male" else gp.hub_root_female
        if hub_name not in refskel:
            hub_parent = placeholder_parent
            if anchor_pal_of is not None:
                hub_parent = anchor_pal_of.get(gp.anchor_target) or placeholder_parent
            refskel[hub_name] = _placeholder(hub_parent)
        for cp in gp.chain_plans:
            prev = hub_name
            for donor_name in cp.donor_chain_for(gender):
                if donor_name not in refskel:
                    refskel[donor_name] = _placeholder(prev)
                prev = donor_name
    return refskel
