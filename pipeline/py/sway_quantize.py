# -*- coding: utf-8 -*-
"""sway_quantize.py -- PB(pull/spring)とVRM SpringBone値を
やわらかめ/ふつう/かため の3段プリセットへ量子化する純関数(dev#1508 W1c)。

**製品コード。** 元は `work\\sway_threshold\\quantize.py`(机上レーンの
ドラフト、bpy非依存の同一ロジック)。導出根拠・数値の出どころ・限界の正直な
開示は同ディレクトリの `work\\sway_threshold\\THRESHOLDS.md` を参照
(このファイルは製品配置であり、導出過程の説明はTHRESHOLDS.md側に残す
——ここでは複製しない)。self-testは `pipeline\\py\\test_sway_quantize.py`
の単体テストへ移設済み(旧 `if __name__ == "__main__":` の
`_run_selftest()` はここには無い)。

--------------------------------------------------------------------------
設計の要約(詳細はTHRESHOLDS.md):

1. PB側: work/rd_1423_pbkp/oracle/features.json の5条件(baseline/pull_low/
   pull_high/spring_low/spring_high、v2_full_captureウィンドウ、PHYSICS状態の
   骨のみ平均)から、(pull,spring) -> (extrema_rate_hz, theta_variance_deg2) の
   粗い単調モデルを組む(各軸独立の対数線形=幾何補間、baseline基準の乗法分解。
   OATスイープ設計と整合)。stiffness軸は既存研究(FORMULA.md)で軌跡レベル
   無効果と判明済みのため使わない。

2. KP側: work/rd_1423_pbkp/kp_calib/table.csv (18点) から3プリセットの
   (rate,var) を求める。ふつう(s0.2/d0.08/w0.0)=g01と、かため(s0.3/d0.3/w0.3)=g18
   は実測格子点に厳密一致。やわらかめ(s0.05/d0.25/w0.0)は測定格子の外
   (stiffness下限0.2を下回る)のため、**最近傍点g01/g09等から最も近いg09
   (s0.2/d0.3/w0.0)で代用した外挿値**——THRESHOLDS.md §2-3に限界を明記。

3. 任意の(pull,spring)について1のモデルで特徴量を推定し、2の3プリセットとの
   対数比距離(FORMULA.mdが採用した重み w_rate=1.0 : w_var=0.3 を踏襲——
   「人間の知覚は比率で効く」2026-08-16指揮者裁定と整合)を計算、最小の
   プリセットへ分類する。

4. 検算: baseline(=flatverしっぽのPB実値、pull=0.348, spring=0.49)は
   本モデルで「かため」に分類される。

境界は厳密には2次元(pull,springの単純な線形しきい値2本には完全収まらない、
THRESHOLDS.md §3で開示)なため、本ファイルは「対数比距離による分類」そのものを
関数として実装している(これが実質的な「単調な規則」)。THRESHOLDS.md 側に
人間可読な近似しきい値表を別途載せている。
"""

from __future__ import annotations

import math

# 量子化ラベル。sway_allocator.py の style/グループ化キーとしてそのまま使う。
STYLES = ("yawa", "futsuu", "kata")


# ---------------------------------------------------------------------------
# 1. PB側オラクル(work/rd_1423_pbkp/oracle/features.json から算出、
#    v2_full_capture, state=="PHYSICS" の骨のみ平均。算出過程は
#    THRESHOLDS.md §1に手計算の内訳を記載)
# ---------------------------------------------------------------------------

_PB_ORACLE = {
    "pull_low":    dict(pull=0.0,   spring=0.49, rate=0.4461,  var=192.80),
    "baseline":    dict(pull=0.348, spring=0.49, rate=0.8030,  var=8.516),
    "pull_high":   dict(pull=1.0,   spring=0.49, rate=1.8402,  var=0.99883),
    "spring_low":  dict(pull=0.348, spring=0.0,  rate=0.5576,  var=6.2215),
    "spring_high": dict(pull=0.348, spring=1.0,  rate=2.2974,  var=1113.455),
}
_BASE_PULL = _PB_ORACLE["baseline"]["pull"]
_BASE_SPRING = _PB_ORACLE["baseline"]["spring"]
_BASE_RATE = _PB_ORACLE["baseline"]["rate"]
_BASE_VAR = _PB_ORACLE["baseline"]["var"]


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _geo_interp(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    """x0<=x<=x1 の範囲で y を対数線形(幾何)補間する。y0,y1>0前提。"""
    if x1 == x0:
        return y0
    t = (x - x0) / (x1 - x0)
    return math.exp(math.log(y0) + t * (math.log(y1) - math.log(y0)))


def _axis_factor(v: float, lo_factor: float, hi_factor: float, base_v: float) -> float:
    """baseline基準の乗法係数(1.0=baseline)を、区間[0,base_v]と[base_v,1]で
    それぞれ対数線形補間する(OATスイープの5点だけで組む粗い単調モデル)。"""
    v = _clamp(v, 0.0, 1.0)
    if v <= base_v:
        return _geo_interp(v, 0.0, lo_factor, base_v, 1.0)
    return _geo_interp(v, base_v, 1.0, 1.0, hi_factor)


def pb_feature(pull: float, spring: float) -> tuple[float, float]:
    """(pull, spring) -> 推定 (extrema_rate_hz, theta_variance_deg2)。

    pull, spring は [0,1] にクランプする(PBの正規レンジ。範囲外入力は
    境界値として扱う=外挿しない)。
    """
    fpr = _axis_factor(pull, _PB_ORACLE["pull_low"]["rate"] / _BASE_RATE,
                        _PB_ORACLE["pull_high"]["rate"] / _BASE_RATE, _BASE_PULL)
    fpv = _axis_factor(pull, _PB_ORACLE["pull_low"]["var"] / _BASE_VAR,
                        _PB_ORACLE["pull_high"]["var"] / _BASE_VAR, _BASE_PULL)
    fsr = _axis_factor(spring, _PB_ORACLE["spring_low"]["rate"] / _BASE_RATE,
                        _PB_ORACLE["spring_high"]["rate"] / _BASE_RATE, _BASE_SPRING)
    fsv = _axis_factor(spring, _PB_ORACLE["spring_low"]["var"] / _BASE_VAR,
                        _PB_ORACLE["spring_high"]["var"] / _BASE_VAR, _BASE_SPRING)
    rate = _BASE_RATE * fpr * fsr
    var = _BASE_VAR * fpv * fsv
    return rate, var


# ---------------------------------------------------------------------------
# 2. KP側3プリセットの特徴量(work/rd_1423_pbkp/kp_calib/table.csv から算出。
#    PHYSICS状態の骨(F_Kigurumi001_tail_01..07)のみ平均、ANCHOR_LOCKEDの
#    tail_08は除外。算出過程はTHRESHOLDS.md §2に手計算の内訳を記載)
# ---------------------------------------------------------------------------

_KP_PRESETS = {
    # ふつう = g01 (stiffness=0.2, damping=0.08, wd=0.0) 実測格子点に厳密一致
    "futsuu": dict(rate=3.8177, var=92.4193),
    # かため = g18 (stiffness=0.3, damping=0.3, wd=0.3) 実測格子点に厳密一致
    "kata": dict(rate=2.33567, var=30.0391),
    # やわらかめ: 真の目標(stiffness=0.05,damping=0.25,wd=0.0)は測定格子の
    # stiffness下限(0.2)を下回るため外挿。格子内最近傍点 g09
    # (stiffness=0.2, damping=0.3, wd=0.0)の実測値で代用——THRESHOLDS.md §2-3
    "yawa": dict(rate=2.6245, var=87.2474),
}

# FORMULA.md(dev#1423 レーンD)が採用した重みをそのまま踏襲。
# 「人間の知覚は比率で効く」(2026-08-16指揮者裁定, FORMULA.md §7-4)ため
# 対数比で距離を測る。
_W_RATE = 1.0
_W_VAR = 0.3


def _logratio_dist(rate_pb: float, var_pb: float, preset: dict) -> float:
    dr = math.log(preset["rate"] / rate_pb)
    dv = math.log(preset["var"] / var_pb)
    return math.sqrt((_W_RATE * dr) ** 2 + (_W_VAR * dv) ** 2)


def quantize_pb(pull: float, spring: float) -> str:
    """PhysBoneの (pull, spring) から、最も性格が近いプリセット
    "yawa" | "futsuu" | "kata" を返す。

    pull, spring は PBの正規レンジ[0,1]を想定(範囲外はクランプする)。
    """
    pull = _clamp(pull, 0.0, 1.0)
    spring = _clamp(spring, 0.0, 1.0)
    rate_pb, var_pb = pb_feature(pull, spring)
    best_name = None
    best_dist = None
    # 辞書順ではなく決定的な順序で回す(同点時の再現性のため)
    for name in ("yawa", "futsuu", "kata"):
        d = _logratio_dist(rate_pb, var_pb, _KP_PRESETS[name])
        if best_dist is None or d < best_dist:
            best_dist = d
            best_name = name
    return best_name


# ---------------------------------------------------------------------------
# 3. VRM SpringBone (VRM0.x: stiffness/gravityPower/dragForce、
#    VRM1.0: 同名の同等項目) -> 3段への写像。
#
#    **実測データは無い**(THRESHOLDS.md §4で明記)。ここで保証するのは
#    「硬い設定ほど硬い段に落ちる」という順序保存のみ(BRIEF §手順5で明示的に
#    許可された最小要件)。硬さの向き:
#      - dragForce(減衰) が大きいほど硬い(KPのdampingと同じ役割)
#      - stiffness(復元力) が大きいほど硬い(PBのpullに近い役割)
#      - gravityPower(下方向への恒常的な力) が大きいほど軟らかい
#        (常時揺れ続ける=柔らかい印象に寄与するとみなす)
#    3項を[0,1]へ正規化し、重み付き線形結合Hをそのまま2しきい値(1/3, 2/3)で
#    3分割する。Hは各入力について偏微分の符号が固定(単調性は式の構成から
#    自明に成立)。
# ---------------------------------------------------------------------------

# 正規化に使う値レンジの仮定(VRM0.x/1.0 spring bone仕様の一般的な実用範囲。
# 実測較正はしていない、THRESHOLDS.md §4に明記)
_SB_STIFFNESS_MAX = 4.0
_SB_GRAVITY_MAX = 2.0
_SB_DRAG_MAX = 1.0

_SB_W_DRAG = 0.4
_SB_W_STIFFNESS = 0.4
_SB_W_GRAVITY = 0.2


def quantize_sb(stiffness: float, gravity_power: float, drag_force: float) -> str:
    """VRM SpringBoneのjoint値から "yawa" | "futsuu" | "kata" を返す。

    実測較正なし。硬い設定ほど硬い段に落ちる順序保存のみを保証する
    (BRIEF §手順5)。VRM0.x/VRM1.0の同名項目に共通して使える。
    """
    s = _clamp(stiffness, 0.0, _SB_STIFFNESS_MAX) / _SB_STIFFNESS_MAX
    g = _clamp(gravity_power, 0.0, _SB_GRAVITY_MAX) / _SB_GRAVITY_MAX
    d = _clamp(drag_force, 0.0, _SB_DRAG_MAX) / _SB_DRAG_MAX

    h = _SB_W_DRAG * d + _SB_W_STIFFNESS * s + _SB_W_GRAVITY * (1.0 - g)

    if h < 1.0 / 3.0:
        return "yawa"
    if h < 2.0 / 3.0:
        return "futsuu"
    return "kata"
