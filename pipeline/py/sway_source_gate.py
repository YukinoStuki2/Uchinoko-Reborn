# -*- coding: utf-8 -*-
"""sway_source_gate.py -- 揺れもの受入ゲート(dev#1508、fail-closed)の比較
ロジック(bpy非依存)。

正本仕様(オーナー最終文言、2026-08-16): 「step02は、step01のモデルにおいて
揺れると判定された全ボーンのTransform(位置・回転・スケールに加えスケールも)
を完全に保持し、メッシュにたいしてもウェイトを完全に保持する。誤差0といっても
いいくらい(浮動小数点誤差のみ許容)」。基準はソース側(`sway_source_bones.py`
が配線実装から独立に導出した対象骨集合)、計画(plan)を基準にした自己参照検査
にしてはならない(SPEC.md §5)。

本モジュール自体はbpy非依存の純粋比較ロジックのみを持つ(骨のtransform/
頂点ウェイトの実測値はBlender側(`pipeline\\blender\\step01_import_vrm.py`/
`pipeline\\blender\\step02_retarget.py`)が読み取り、プレーンなdict/JSONと
してこのモジュールへ渡す——`sway_hub.py`と同じ「重い処理はbpy側、判定は
bpy非依存側」という設計方針を踏襲)。

## 「Transform完全一致」の実装上の意味(重要な設計判断)

`avatar_arm`全体はstep01(インポート直後の生のアバター座標)から
step02のdonor配置時点までに、グローバルスケール・配置(`global_scale_
and_place()`)・ポーズ調整(`auto_fit_pose()`)・肩オフセット・ポーズ焼き
込み(`bake_pose_into_meshes()`)を経る。これらは全身に対する非一様な
調整を含みうるため、**「stepP01の生座標」と「step02のdonor骨のworld
座標」を無条件に数値比較することは、どんなに正しい実装でも意味を持たない**
(スケール・配置が変わって当然)。

そのため本ゲートのposition/rotation/scale比較は、「stepP01の生座標」
ではなく、**「donor配置(`place_hub_donor_chains()`)が実行される、まさに
その瞬間のavatar_arm実測値」を独立に(配線ロジックを経由せず)再取得した
もの**を左辺として使う(`pipeline\\blender\\step02_retarget.py`の
`_sway_gate_live_source_snapshot()`が担当、`sway_hub.py`の`av_point()`等の
配線ロジックは一切呼ばない、単純なbpy生読み取り)。この左辺は「donor骨が
exact-bone-copy契約(donor節i <- 転写元関節iのworld位置を完全コピー)を
実際に満たしているか」を検査でき、欠落・退化フォールバックの誤発動・
座標変換のバグを直接検出する。

一方、**頂点ウェイト(頂点集合+重み値)はstep01スナップショットとの直接
比較が可能かつ意味を持つ**——メッシュのオブジェクト名・頂点インデックス
はstep01からstep02まで不変であり(`remap_vertex_groups()`は頂点グループの
「対応付け」を変えるだけで頂点そのものは増減・並べ替えしない)、
「そのボーンが本来持つべき頂点ウェイト」はstep01時点の値がそのまま正解
になる。ウェイト比較はstep01スナップショット(JSON、`build\\atlas\\
step01_sway_snapshot.json`)を左辺として使う。

## 「回転」の比較方法(2026-08-16、実データ検証で訂正)

当初実装はsource/donorの生クォータニオンをそのまま比較していたが、
comodo/flatHaori実変換で**必ずFAILする**ことが判明した(修正版
`sway_hub.py`適用後もFAIL)。原因は実装バグではなく比較方法そのものの
誤り: donor骨の回転は`sway_hub_placement.build_donor_chain_quats()`に
よる**chain方向へのlook-at再構成**(ローカル+Xが次関節方向を向くよう
機械決定、KP/Palworldの物理ボーン規約)であり、**元アバターボーンが
持つ回転(FBXリグ由来の任意のroll)をそのままコピーしたものではない**
——position(head/tail)は完全コピーだが、rotationは位置から導出される
別の表現になる、という設計そのもの(`place_hub_donor_chains()`
docstring「exact-bone-copy」参照)。

そのため本ゲートは生クォータニオンの一致ではなく、**向き(tail-head方向
ベクトル)の角度差**を許容範囲(`EPS_FORWARD_ANGLE_DEG`)で比較する
——「donor骨が正しい方向を向いているか」を、reconstruction方式に依存
しない形で検査できる。どちらかの方向ベクトルが退化(ほぼゼロ長、リーフ
骨のtail=head等)の場合は角度比較をスキップする(判定不能、FAILにしない
——退化はexact-bone-copy契約の対象外)。

### 15度許容の撤廃(2026-08-16夜、レーンF実測)

上の「15度」は暫定値のまま出荷されていた(`work\\wp_wfinal\\PROGRESS.md`
の引き継ぎ)。donor tailは`place_hub_donor_chains()`が
`av_point(src[i], use_tail=True)`(=SOURCE骨自身のtail)を厳密にコピーする
設計であり、理論上donor方向はfloat精度でsource方向と一致するはず
——15度という緩さは実装バグの隠蔽ではなく、後述のとおり検証未了のまま
選ばれた値だった。

**実測(2026-08-16夜、レーンF)**: comodo/flatHaori各性別(計4回のBlender
step02実行、既存`work\\wp_wfinal_run5\\`と同一job設定を複製した独立計測
環境)で、`check_bone_transform`が実際に比較する全ボーン(176件、
comodo 24件×2性別+flatHaori 64件×2性別)の角度残差を(FAILしたものだけ
でなく)全数ダンプして分布を取った。結果は**最大3.52e-6度、平均
5.38e-7度、中央値0度**——176件全てが1e-4度を大きく下回るfloat32精度級の
残差であり、仮説どおり「向きはfloat一致」が実データで裏付けられた
(有意な構造的原因は存在しない)。

この実測に基づき、`EPS_FORWARD_ANGLE_DEG`を15度から1e-3度(観測最大値の
約280倍のマージン、他のepsilon同様に数桁の安全マージンを取った値)へ
引き締めた。1e-3度は「明後日の方向を向いている」構造的破綻(退化
フォールバック誤発動・座標変換バグ)は従来どおり確実に検出しつつ、
実測で確認したfloat精度の自然なブレは誤検知しない。

## `check_bone_transform`の不一致は警告のみ(2026-08-18、dev#1551オーナー裁定確定)

flatapron耳鎖の実データ検証(work\\run_1551\\laneR6_blendcmp\\NOTE.md)で、
`place_hub_donor_chains()`呼び出し時点のavatar_armライブポーズがstep01の
rest形状を保っていないケースが見つかった(donor配置の入力側`av_point()`を
rest(`data.bones`)基準に修理済み、`work\\run_1551\\laneR7_earfix\\RESULT.md`)。
本ゲートのソース側(`_sway_gate_live_source_transforms()`)は引き続きライブ
ポーズを読む設計のままであり、修理後もこの2つの読み取り経路が構造的に
異なる値を指すケースが起こりうる。「検査は警告にのみ使う」(思想録)の
方針で、`check_bone_transform()`の不一致(位置/向き/スケール)は
`BoneCheckResult.transform_warnings`へ分離し、`ok`(fail-closed判定)には
一切影響させない——鎖を静かに除外する・変換全体を止める、のどちらも
しない。donor欠落(no donor mapping)・頂点ウェイト不一致・支点公理違反は
従来どおりfail-closedのまま(`reasons`側)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

_EMPTY_MAP: Mapping[str, str] = {}  # run_gate()のrepresentative_of既定値(読み取り専用)

# ---------------------------------------------------------------------
# epsilon/tolerance(2026-08-16、選定根拠を明記):
# - 位置: 1e-4 m(0.1mm)。Blenderの内部bone/mesh座標はfloat32であり、
#   `place_hub_donor_chains()`はworld<->local変換(matrix_world.inverted()
#   の乗算)を鎖の長さぶん繰り返す。float32相対精度(~1.19e-7)がavatar
#   スケール(~1〜2m)の値に対して生む絶対誤差は理論上~1e-7m程度だが、
#   逆行列・複数回の行列積の蓄積誤差を安全側に見て3桁のマージンを取った。
#   既存コードの「ほぼゼロ」判定(1e-9m、退化ケース用)とは意味が違う
#   ——あちらは「実質ゼロかどうか」、こちらは「二値が一致するか」の
#   判定であるため、桁を分けている。
# - 向き(tail-head方向ベクトルの角度差): 1e-3度(2026-08-16夜、レーンF
#   実測で15度から引き締め。モジュールdocstring「15度許容の撤廃」節
#   参照)。donor tailはSOURCE骨自身のtailの厳密なコピー(exact-bone-copy
#   設計)のため、理論上donor方向はfloat精度でsource方向と一致するはず
#   ——実測(comodo/flatHaori計4回、176ボーン全数)でも最大3.52e-6度・
#   平均5.38e-7度と、仮説どおりfloat32精度級の残差しか出なかった。
#   1e-3度は観測最大値の約280倍のマージンを持たせつつ、「明後日の方向を
#   向いている」ような構造的破綻(退化フォールバック誤発動・座標変換
#   バグ)は従来どおり確実に検出できる値。
# - スケール: 相対差1e-4(donor骨のスケールは基本1.0付近が期待値)。
# - ウェイト: 1e-5。頂点ウェイトは単純なコピー(`remap_vertex_groups()`の
#   `tmp.add([v.index], g.weight, "ADD")`)のみで、複数回の行列演算を
#   経ないため位置よりさらに厳しい精度を要求できる。
# ---------------------------------------------------------------------
EPS_POS = 1e-4
EPS_FORWARD_ANGLE_DEG = 1e-3
EPS_SCALE = 1e-4
EPS_WEIGHT = 1e-5


@dataclass
class BoneCheckResult:
    bone: str
    donor: Optional[str]
    ok: bool
    reasons: List[str] = field(default_factory=list)
    # dev#1551(断言ゲート警告格下げ、オーナー裁定確定、正本
    # work\run_1551\laneR7_earfix\RESULT.md): check_bone_transform()の
    # 不一致理由はここへ分離する。`ok`(fail-closedの判定基準)には
    # 一切影響させない -- 欠落(no donor mapping)・ウェイト不一致は
    # 従来どおり`reasons`(fatal)のまま。
    transform_warnings: List[str] = field(default_factory=list)


@dataclass
class GateReport:
    results: Tuple[BoneCheckResult, ...]

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def failed(self) -> Tuple[BoneCheckResult, ...]:
        return tuple(r for r in self.results if not r.ok)

    def summary_lines(self) -> List[str]:
        lines = [f"sway_source_gate: {len(self.results)} bone(s) checked, "
                 f"{len(self.failed)} FAILED"]
        for r in self.failed:
            lines.append(f"  FAIL {r.bone!r} (donor={r.donor!r}): "
                         f"{'; '.join(r.reasons)}")
        return lines

    def transform_warning_lines(self) -> List[str]:
        """dev#1551: check_bone_transform()の不一致(位置/向き/スケール)を
        警告として一覧化する(fail-closedには寄与しない、ログへの可視化
        専用)。呼び出し側が"[WARN]"接頭辞を付けて印字する想定。"""
        lines = []
        for r in self.results:
            if r.transform_warnings:
                lines.append(f"{r.bone!r} (donor={r.donor!r}): "
                             f"{'; '.join(r.transform_warnings)}")
        return lines


def _vec_close(a: Sequence[float], b: Sequence[float], eps: float) -> bool:
    if len(a) != len(b):
        return False
    return all(abs(float(x) - float(y)) <= eps for x, y in zip(a, b))


def _vec_sub(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_len(a: Sequence[float]) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _vec_normalize(a: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    n = _vec_len(a)
    if n < 1e-9:
        return None  # 退化(ほぼゼロ長) -- 方向不定
    return (a[0] / n, a[1] / n, a[2] / n)


def _angle_between_deg(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """正規化済みベクトルa/bの間の角度(度)。どちらかが退化していれば
    None(判定不能)。"""
    na, nb = _vec_normalize(a), _vec_normalize(b)
    if na is None or nb is None:
        return None
    dot = max(-1.0, min(1.0, na[0] * nb[0] + na[1] * nb[1] + na[2] * nb[2]))
    return math.degrees(math.acos(dot))


def direction_mismatch_deg(
    source_pos: Sequence[float], source_tail: Sequence[float],
    donor_pos: Sequence[float], donor_tail: Sequence[float],
) -> Optional[float]:
    """向き(tail-head方向ベクトル)の角度差(度)だけを取り出す
    (`check_bone_transform()`内部ロジックの抜き出し、単独呼び出し用)。
    どちらかの方向ベクトルが退化(ほぼゼロ長)していればNone(判定不能)。

    dev#1625(2026-08-21 オーナー裁定)の姿勢不一致切除
    (`bones_exceeding_posture_cull_threshold()`)がこの値をfail-closedの
    `EPS_FORWARD_ANGLE_DEG`epsilonとは独立に使うため、比較ロジックを
    `check_bone_transform()`から切り出した(角度の算出方法自体は同一、
    `check_bone_transform()`もこの関数を経由するよう更新済み)。"""
    source_dir = _vec_sub(source_tail, source_pos)
    donor_dir = _vec_sub(donor_tail, donor_pos)
    return _angle_between_deg(source_dir, donor_dir)


# ---------------------------------------------------------------------
# dev#1625(2026-08-21 オーナー裁定): 姿勢不一致ハブの最小切除。
#
# 背景: `check_bone_transform()`のdirection mismatchはdev#1551で`ok`判定
# から分離済み(このモジュールdocstring「check_bone_transformの不一致は
# 警告のみ」節)——これは「float精度級の自然なブレ」と「chain-length-fit
# 由来の正当な残差」を誤ってFAILにしないための格下げであり、正しい判断
# だった。しかしオーナー実機報告(dev#1625、AvatarSample_A.vrm)で、
# donor骨が明後日の方向(最大120.98度)を向いたまま配線され、実機で頭部・
# 胸部が大破綻するケースが見つかった——「警告はするが配線はそのまま出荷
# する」という現状の設計では、この種の構造的破綻を防げない。
#
# 対応: 「壊れた配線を作らない」ため、既存の縮退機構
# (`sway_degrade.py`/`_sway_degrade_precheck()`、dev#1508 graceful-degrade)
# へ新しい切除トリガーを追加する——このハブ**だけ**を配線しないフォール
# バックへ落とし、変換自体は完走させる(dev#1551/dev#1592のゲート格下げ
# 裁定そのものは覆さない: `report.ok`/`_finalize_sway_source_gate_result()`
# は無改修)。
#
# 較正データ(2026-08-21、実測。詳細は work\wp_1625_notes\NOTES.md):
# 「既知白検体」の中で最も大きい実測方向不一致は、既定恒常検体
# prefab_flatapron(devtools\relgate.py DEFAULT_AVATAR_KEY、prefab/
# Modular Avatar代表)の 'Tail.005'->'NPC_GrassBoss001_Skin001_tail_05'、
# 13.68度(chain-length-fit由来の正当な残差、position mismatchも同時に
# 観測されており構造的に無害と判定できる)。
# 一方、dev#1625実報告検体AvatarSample_A.vrmの4件の異常ハブは19.31度
# (最小、耳HairJoint)〜120.98度(最大、J_Bip_C_UpperChest)。
# 閾値は両者のほぼ中間(16.5度=白の実測最大13.68度から約+2.8度、
# 既知異常の実測最小19.31度から約-2.8度)——どちらの値そのものにも
# 寄せていない(CLAUDE.md「値を寄せて合わせる修正は却下」)。
#
# 注記(2026-08-21、キャリブレーション中の追加発見): 同じ恒常セットの
# vrm1_seedsan(Seed-san.vrm)にも、この閾値を超える2件の大きな方向不一致
# (94.56度/96.89度、'head 1'/'bagpack')が実測された——AvatarSample_A
# 固有ではなく、dev#1508 hub配線方式に構造的に内在する問題である可能性が
# 高い(WP完了報告に記載、追加調査はこのWPのスコープ外)。
SWAY_POSTURE_CULL_THRESHOLD_DEG = 16.5


def bones_exceeding_posture_cull_threshold(
    representative_bones: Sequence[str],
    source_transform_snapshot: Mapping[str, Mapping[str, Sequence[float]]],
    donor_transform_snapshot: Mapping[str, Mapping[str, Sequence[float]]],
    group_targets: Mapping[str, str],
    threshold_deg: float = SWAY_POSTURE_CULL_THRESHOLD_DEG,
) -> Dict[str, float]:
    """`representative_bones`(既に代表骨だけに絞り込み済み、非代表の
    マージ済み骨は呼び出し側で除外しておくこと -- `run_gate()`の
    `representative_of`と同じ理由、マージ後の非代表骨は自分自身の生
    transformとdonorが構造的に不一致になるため対象外)のうち、
    donor骨への方向不一致が`threshold_deg`を超えるものだけを
    {bone名: 角度(度)}で返す(dev#1625)。

    donor未割当・スナップショット欠落・方向退化(リーフ骨等、判定不能)の
    骨は静かにスキップする(それらは別経路 -- `_sway_degrade_precheck()`の
    donor欠落チェック -- が既に処理済みの前提)。"""
    out: Dict[str, float] = {}
    for bone in representative_bones:
        donor = group_targets.get(bone)
        if donor is None:
            continue
        src = source_transform_snapshot.get(bone)
        dst = donor_transform_snapshot.get(donor)
        if src is None or dst is None:
            continue
        angle = direction_mismatch_deg(src["pos"], src["tail"], dst["pos"], dst["tail"])
        if angle is not None and angle > threshold_deg:
            out[bone] = angle
    return out


def check_bone_transform(
    source_pos: Sequence[float], source_tail: Sequence[float],
    source_scale: Sequence[float],
    donor_pos: Sequence[float], donor_tail: Sequence[float],
    donor_scale: Sequence[float],
) -> List[str]:
    """位置(head)は完全一致(epsilon)、向き(tail-head方向ベクトル)は
    角度差の許容範囲、スケールはepsilon付きで比較する(モジュール
    docstring「回転の比較方法」節参照 -- donor回転はlook-at再構成のため
    生クォータニオンではなく方向ベクトルで比較する)。"""
    reasons = []
    if not _vec_close(source_pos, donor_pos, EPS_POS):
        reasons.append(f"position mismatch: source={list(source_pos)} donor={list(donor_pos)}")

    source_dir = _vec_sub(source_tail, source_pos)
    donor_dir = _vec_sub(donor_tail, donor_pos)
    angle = direction_mismatch_deg(source_pos, source_tail, donor_pos, donor_tail)
    if angle is not None and angle > EPS_FORWARD_ANGLE_DEG:
        reasons.append(
            f"direction mismatch: {angle:.2f} deg (source tail-head vs donor "
            f"tail-head, tolerance {EPS_FORWARD_ANGLE_DEG} deg) -- "
            f"source_dir={source_dir} donor_dir={donor_dir}")

    if not _vec_close(source_scale, donor_scale, EPS_SCALE):
        reasons.append(f"scale mismatch: source={list(source_scale)} donor={list(donor_scale)}")
    return reasons


def check_bone_weights(
    source_weights: Mapping[Tuple[str, int], float],
    donor_weights: Mapping[Tuple[str, int], float],
) -> List[str]:
    """頂点集合+重み値の完全一致を検査する(epsilonはウェイト値のみ、
    頂点集合の一致は完全一致=1個でも過不足があればFAIL)。"""
    reasons = []
    src_keys = set(source_weights)
    donor_keys = set(donor_weights)
    if src_keys != donor_keys:
        missing = sorted(src_keys - donor_keys)
        extra = sorted(donor_keys - src_keys)
        if missing:
            reasons.append(f"{len(missing)} vertex(es) lost weight (e.g. {missing[:3]})")
        if extra:
            reasons.append(f"{len(extra)} vertex(es) gained unexpected weight (e.g. {extra[:3]})")
    for k in src_keys & donor_keys:
        if abs(source_weights[k] - donor_weights[k]) > EPS_WEIGHT:
            reasons.append(
                f"weight value mismatch at {k}: source={source_weights[k]} "
                f"donor={donor_weights[k]}")
    return reasons


def _flatten_weights(weights: Mapping[str, Mapping[str, float]]) -> Dict[Tuple[str, int], float]:
    """{mesh_name: {vertex_index(str or int): weight}} -> {(mesh,int(vidx)): weight}"""
    out: Dict[Tuple[str, int], float] = {}
    for mesh, per_vertex in (weights or {}).items():
        for vidx, w in per_vertex.items():
            out[(mesh, int(vidx))] = float(w)
    return out


def run_gate(
    source_bone_names: Sequence[str],
    group_targets: Mapping[str, str],
    source_transform_snapshot: Mapping[str, Mapping[str, Sequence[float]]],
    source_weight_snapshot: Mapping[str, Mapping[str, Mapping[str, float]]],
    donor_transform_snapshot: Mapping[str, Mapping[str, Sequence[float]]],
    donor_weight_snapshot: Mapping[str, Mapping[str, Mapping[str, float]]],
    merge_groups: FrozenSet[FrozenSet[str]] = frozenset(),
    representative_of: Mapping[str, str] = _EMPTY_MAP,
) -> GateReport:
    """ソース基準1:1ゲート本体。

    `source_bone_names`: 独立導出済みの対象骨名(`sway_source_bones.
    all_accepted_source_bone_names()`の戻り値、呼び出し側が用意)。

    `group_targets`: {ソース骨名 -> donor骨名}(step02が実際に決定した
    対応、`sway_hub_wire.source_to_donor_bone_map()`込みで更新済みの
    `group_targets`辞書をそのまま渡す想定)。エントリが無い/donor側の
    スナップショットが無い場合は即FAIL(欠落そのものを検出する)。

    `source_transform_snapshot`/`donor_transform_snapshot`:
    {骨名: {"pos":[x,y,z], "tail":[x,y,z], "scale":[x,y,z]}}。

    `source_weight_snapshot`/`donor_weight_snapshot`:
    {骨名: {mesh名: {頂点index(str): weight}}}。

    `merge_groups`(dev#1551 chain-length-fit WP追加):
    `sway_hub.merged_weight_groups(wiring)`の戻り値。節数フィット
    (先端マージ)で複数のソース骨が意図的に同じdonorへ写像された組。
    このグループに属する骨は、ウェイト比較の左辺を**グループ全員の
    ソースウェイトの合算**にする(donor側は`remap_vertex_groups()`の
    ADD合成で既にグループ全員ぶんを持つため、対称に合算しないと
    「メッシュ頂点ウェイトは単純なコピー」前提が崩れて誤FAILする)。
    グループに属さない骨は従来どおり1:1比較。

    `representative_of`(dev#1551 chain-length-fit WP追加):
    `sway_hub.representative_of_map(wiring)`の戻り値。{元アバター骨名 ->
    そのマージグループの代表(先端側)骨名}(節数フィット未発動の骨は
    恒等写像)。donorのジオメトリは常に**代表骨**のtransformで配置される
    (`fit_chain_to_length()`「マージ後の代表点はマージ区間の端点を保つ」
    設計)ため、**代表でない**(マージされて消えた側の)骨を自分自身の
    生transformとdonorとで比較すると構造的に不一致になる——バグではなく
    設計どおりの結果なので、この骨については位置/向き/スケール検査を
    スキップする(donor欠落自体の検査とウェイト検査は従来どおり行う)。
    代表骨自身(恒等写像)は従来どおり厳密に比較する。

    1本でも欠け/位置ズレ/向きズレ/スケールズレ/ウェイト不一致があれば
    その骨がFAILする(全数検査、`GateReport.ok`が全体の合否)。
    """
    bone_to_merge_group: Dict[str, FrozenSet[str]] = {}
    for group in merge_groups:
        for b in group:
            bone_to_merge_group[b] = group

    results: List[BoneCheckResult] = []
    for bone in source_bone_names:
        donor = group_targets.get(bone)
        if donor is None:
            results.append(BoneCheckResult(
                bone, None, False,
                ["no donor mapping (group_targets missing this source bone -- "
                 "this is exactly the dev#1508 off-by-one failure mode)"]))
            continue

        reasons: List[str] = []
        # dev#1551(断言ゲート警告格下げ): check_bone_transform()の不一致は
        # ここへ分離する(fail-closedの`reasons`には積まない)。
        transform_warnings: List[str] = []
        is_representative = representative_of.get(bone, bone) == bone

        src_t = source_transform_snapshot.get(bone)
        dst_t = donor_transform_snapshot.get(donor)
        if src_t is None:
            reasons.append("source bone missing from live avatar_arm snapshot")
        if dst_t is None:
            reasons.append(f"donor bone {donor!r} missing from pal_arm snapshot")
        if src_t is not None and dst_t is not None and is_representative:
            transform_warnings += check_bone_transform(
                src_t["pos"], src_t["tail"], src_t["scale"],
                dst_t["pos"], dst_t["tail"], dst_t["scale"])

        merge_group = bone_to_merge_group.get(bone)
        if merge_group:
            src_w: Dict[Tuple[str, int], float] = {}
            for member in merge_group:
                for k, v in _flatten_weights(source_weight_snapshot.get(member, {})).items():
                    src_w[k] = src_w.get(k, 0.0) + v
        else:
            src_w = _flatten_weights(source_weight_snapshot.get(bone, {}))
        dst_w = _flatten_weights(donor_weight_snapshot.get(donor, {}))
        reasons += check_bone_weights(src_w, dst_w)

        results.append(BoneCheckResult(bone, donor, not reasons, reasons, transform_warnings))
    return GateReport(results=tuple(results))
