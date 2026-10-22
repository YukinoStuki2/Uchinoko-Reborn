# -*- coding: utf-8 -*-
"""dev#371 受入テスト: convert_noue.py のタイルNCC擬陽性是正
(ATLAS_VISUAL_TILE_MEAN_DIFF_FLOOR / _atlas_tile_min_ncc)。

背景(issue #371、研究WP work\\rd_x2rsc\\PROPOSAL.md参照):
実報告で「全体NCC=0.9958なのに1タイルだけ0.0204でFATAL」が発生した。
真因はNCC(相関係数)の数学的性質——比較対象の残差(画素差そのもの)が
無相関であれば、分散の大小に関わらず相関係数が0近辺のノイズ値になる。
ほぼ単色のタイル(material_map.json欠落時のsolid colorフォールバック等)は
量子化・ディザ由来の無相関な残差しか持たないため、目視で完全に同一でも
NCCが数値的に意味を失う。

このWPが実装したのは「平均絶対画素差(mean|a-b|)が
ATLAS_VISUAL_TILE_MEAN_DIFF_FLOOR(=2.0、量子化幅由来)以下のタイルは、
NCCで判定できる情報を持たないとみなしmin-NCC探索から除外する」という
1段のみ(研究WP提案の二段判定案の1段目)。NCC<0.70でFAILの閾値そのものは
変更していない。研究WPが新規発見した「NCC>=0.70だが平坦面の色が実際に
変わった」ケース(D_POS軸)はこのWPでは未実装(D_POS未計測のため、
値を作ることは「値を寄せて合わせる」に該当し却下対象になる)——
本ファイルのテストはこの既知の未実装スコープを増悪させていないことの
確認までで、D_POS軸の新規検出能力は主張しない。

実行: python -m pytest pipeline/py/test_atlas_tile_ncc_dev371.py -q
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_noue as cn  # noqa: E402


# ------------------------------------------------------------------ helpers

def _rgba(rgb_u8):
    """(h,w,3) uint8 -> (h,w,4) uint8 (alpha=255固定、不透明タイルとして扱う)"""
    h, w = rgb_u8.shape[:2]
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[..., :3] = rgb_u8
    out[..., 3] = 255
    return out


def _dithered_flat_tile(rng, h, w, base, p_flip=0.3):
    """ほぼ単色(ソリッドカラーフォールバック相当)のタイル。量子化・ディザ由来の
    ±1程度の独立ノイズだけを持つ。pre/postを別々に呼んで独立ノイズにすると、
    目視で完全に同一(mean|diff|が1未満)でもNCCが数値的に崩れる
    (研究WP実測: solid_plane検体の再現。issue #371参照)。"""
    flips = rng.choice([-1, 0, 1], size=(h, w, 3), p=[p_flip / 2, 1 - p_flip, p_flip / 2])
    arr = np.clip(base + flips, 0, 255).astype(np.uint8)
    return _rgba(arr)


def _healthy_tile_pair(rng, h, w, resample_amp=6):
    """健全なタイル(pre/postでベイクの再サンプリング由来の小さな独立ノイズは
    あるが、内容自体は一致)。resample_amp程度の独立ノイズは実際のBlender
    ベイクの非決定的リサンプル(devtools\\atlas_compare.pyの既知の限界を参照)
    に相当する規模で、mean|diff|はATLAS_VISUAL_TILE_MEAN_DIFF_FLOORより
    十分大きい(=床には引っかからない)が、NCCは高い値になる。"""
    base = rng.integers(0, 255, size=(h, w, 3)).astype(np.int16)
    noise_a = rng.integers(-resample_amp, resample_amp + 1, size=(h, w, 3))
    noise_b = rng.integers(-resample_amp, resample_amp + 1, size=(h, w, 3))
    ta = np.clip(base + noise_a, 0, 255).astype(np.uint8)
    tb = np.clip(base + noise_b, 0, 255).astype(np.uint8)
    return _rgba(ta), _rgba(tb)


def _corrupted_tile_pair(rng, h, w):
    """本物の局所破損(別の絵に化けた)を模した、pre/postが無関係な内容の
    ペア。NCCが低くdmeanも大きい=床では救済されないはずの負の対照。"""
    ta = rng.integers(0, 255, size=(h, w, 3)).astype(np.uint8)
    tb = rng.integers(0, 255, size=(h, w, 3)).astype(np.uint8)
    return _rgba(ta), _rgba(tb)


def _build_grid(patch, grid, tiles):
    """gridは(rows, cols)。tilesは{(gy,gx): (ta,tb)}。残りは(gy,gx)ごとに
    tilesに無ければ埋めない(テストは常に全マスを埋めて呼ぶ)。"""
    rows, cols = grid
    h = rows * patch
    w = cols * patch
    a = np.zeros((h, w, 4), dtype=np.uint8)
    b = np.zeros((h, w, 4), dtype=np.uint8)
    for (gy, gx), (ta, tb) in tiles.items():
        y0, x0 = gy * patch, gx * patch
        a[y0:y0 + patch, x0:x0 + patch] = ta
        b[y0:y0 + patch, x0:x0 + patch] = tb
    return a, b


# ------------------------------------------------------------------ 1. 擬陽性ケース: 単発の平坦タイル

def test_flat_tile_alone_is_excluded_not_pseudo_fail():
    """単発のほぼ単色タイル(pre/post独立ディザのみ)だけの画像は、
    現行のNCC直接計算では低い値(擬陽性)になるが、_atlas_tile_min_ncc は
    そのタイルを判定不能として除外し、worst_ncc=None(=タイル判定は
    適用対象なし)を返すこと。"""
    rng = np.random.default_rng(1)
    a = _dithered_flat_tile(rng, 64, 64, base=186)
    b = _dithered_flat_tile(rng, 64, 64, base=186)

    direct_ncc = cn._atlas_ncc_flat_rgb(a, b)
    assert direct_ncc < cn.ATLAS_VISUAL_MIN_TILE_NCC, (
        f"前提条件が崩れている: 直接NCCが既に閾値以上 ({direct_ncc}) では"
        f"擬陽性の再現になっていない")

    worst_ncc, worst_xy = cn._atlas_tile_min_ncc(a, b, 64)
    assert worst_ncc is None and worst_xy is None, (
        f"平坦タイルが除外されず worst_tile として報告された: "
        f"ncc={worst_ncc} xy={worst_xy}")


# ------------------------------------------------------------------ 2. 擬陽性ケース: 健全な画像に平坦タイルが混在

def test_mixed_scene_flat_tile_does_not_dominate_worst():
    """3x3タイルのうち8枚は健全(内容一致+ベイク由来の小さな独立ノイズ)、
    1枚だけがほぼ単色(ソリッドカラーフォールバック相当)。全体としては
    ほぼ完全一致に見える構図で、平坦タイルが worst_tile として
    誤検出されない(=擬陽性が消える)ことを確認する。"""
    rng = np.random.default_rng(2)
    tiles = {}
    for gy in range(3):
        for gx in range(3):
            if gy == 2 and gx == 2:
                tiles[(gy, gx)] = (
                    _dithered_flat_tile(rng, 64, 64, base=186),
                    _dithered_flat_tile(rng, 64, 64, base=186),
                )
            else:
                tiles[(gy, gx)] = _healthy_tile_pair(rng, 64, 64)
    a, b = _build_grid(64, (3, 3), tiles)

    worst_ncc, worst_xy = cn._atlas_tile_min_ncc(a, b, 64)
    assert worst_xy != (128, 128), (
        "平坦タイル(128,128)がworst_tileとして誤検出された(擬陽性が残っている)")
    if worst_ncc is not None:
        assert worst_ncc >= cn.ATLAS_VISUAL_MIN_TILE_NCC, (
            f"健全タイルのはずが閾値未満のworst_ncc={worst_ncc}を報告した"
            f"(擬陽性が残っている、worst_xy={worst_xy})")


# ------------------------------------------------------------------ 3. 負の対照(本丸): 本物の破損は引き続き検出される

def test_real_corruption_is_still_detected_negative_control():
    """§2と同じ構図(平坦タイル1枚+健全タイル7枚)に、さらに1枚だけ
    「別の絵に化けた」本物の破損タイルを混ぜる。擬陽性を消す修正が
    検査そのものを骨抜きにしていないことの証明として、本物の破損タイルが
    引き続き worst_tile として検出され、ATLAS_VISUAL_MIN_TILE_NCC 未満
    (=変換を止めるFAIL)になることを確認する。"""
    rng = np.random.default_rng(3)
    tiles = {}
    for gy in range(3):
        for gx in range(3):
            if gy == 2 and gx == 2:
                tiles[(gy, gx)] = (
                    _dithered_flat_tile(rng, 64, 64, base=186),
                    _dithered_flat_tile(rng, 64, 64, base=186),
                )
            elif gy == 1 and gx == 1:
                tiles[(gy, gx)] = _corrupted_tile_pair(rng, 64, 64)
            else:
                tiles[(gy, gx)] = _healthy_tile_pair(rng, 64, 64)
    a, b = _build_grid(64, (3, 3), tiles)

    worst_ncc, worst_xy = cn._atlas_tile_min_ncc(a, b, 64)
    assert worst_xy == (64, 64), (
        f"本物の破損タイル(64,64)がworst_tileとして検出されなかった: "
        f"worst_xy={worst_xy} worst_ncc={worst_ncc}(検査が骨抜きになっている)")
    assert worst_ncc is not None and worst_ncc < cn.ATLAS_VISUAL_MIN_TILE_NCC, (
        f"本物の破損タイルのNCCが閾値以上になった: {worst_ncc} "
        f"(見逃し=検査が骨抜きになっている)")


# ------------------------------------------------------------------ 4. 境界: mean|a-b| が床ちょうど付近

def _boundary_pair(delta_mag, size=8):
    """内部に実変化(=非ゼロ分散)を持つタイルに、pre/postで独立な
    ±delta_mag の系統誤差を乗せる。mean|a-b| はちょうど delta_mag になる
    (符号を交互に配置しているため常に|diff|=delta_mag)。"""
    n = size * size * 3
    idx = np.arange(n)
    base_vals = 120 + (idx % 5) * 3
    sign = np.where(idx % 2 == 0, 1, -1)
    a_flat = base_vals.astype(np.int16)
    b_flat = a_flat + sign * delta_mag
    a = np.clip(a_flat, 0, 255).astype(np.uint8).reshape(size, size, 3)
    b = np.clip(b_flat, 0, 255).astype(np.uint8).reshape(size, size, 3)
    return _rgba(a), _rgba(b)


def test_boundary_mean_diff_exactly_at_floor_is_excluded():
    """mean|a-b| がちょうど ATLAS_VISUAL_TILE_MEAN_DIFF_FLOOR(=2.0)のタイルは
    除外される(<=なので境界値を含む)。"""
    a, b = _boundary_pair(delta_mag=2, size=8)
    dmean = float(np.abs(a[..., :3].astype(np.float64) - b[..., :3].astype(np.float64)).mean())
    assert dmean == cn.ATLAS_VISUAL_TILE_MEAN_DIFF_FLOOR, (
        f"テスト構築の前提が崩れている: dmean={dmean} != "
        f"{cn.ATLAS_VISUAL_TILE_MEAN_DIFF_FLOOR}")

    worst_ncc, worst_xy = cn._atlas_tile_min_ncc(a, b, 8)
    assert worst_ncc is None and worst_xy is None, (
        f"床ちょうど(dmean={dmean})のタイルが除外されなかった: "
        f"ncc={worst_ncc} xy={worst_xy}")


def test_boundary_mean_diff_just_above_floor_is_evaluated():
    """mean|a-b| が床をわずかに超える(=量子化ノイズの範囲外)タイルは
    除外されず、通常どおりNCCで判定される(=見落とさない側の確認)。"""
    a, b = _boundary_pair(delta_mag=3, size=8)
    dmean = float(np.abs(a[..., :3].astype(np.float64) - b[..., :3].astype(np.float64)).mean())
    assert dmean > cn.ATLAS_VISUAL_TILE_MEAN_DIFF_FLOOR

    worst_ncc, worst_xy = cn._atlas_tile_min_ncc(a, b, 8)
    assert worst_ncc is not None and worst_xy is not None, (
        "床をわずかに超えたタイルが誤って除外された(見落としの再発)")
    # このタイルは意図的に系統誤差(擬似ディザ)を乗せてあるので、除外されず
    # 通常のNCC計算パスを通ったことだけを確認する(具体的な合否は
    # ATLAS_VISUAL_MIN_TILE_NCC=0.70との比較で別途決まる。ここでは
    # 「除外ロジックをすり抜けて評価対象になったこと」が確認事項)。
    direct_ncc = cn._atlas_ncc_flat_rgb(a, b)
    assert worst_ncc == direct_ncc


# ------------------------------------------------------------------ 5. 全透明タイルの既存挙動は不変(回帰)

def test_fully_transparent_tile_still_skipped():
    """既存の「全透明(alpha=0)タイルは未使用領域としてスキップ」の挙動が、
    今回のmean-diff床の追加で壊れていないことの回帰確認。"""
    h = w = 64
    a = np.zeros((h, w, 4), dtype=np.uint8)  # alpha=0 全体
    b = np.zeros((h, w, 4), dtype=np.uint8)
    b[..., :3] = 200  # RGBが違ってもalpha=0同士ならスキップされる想定
    worst_ncc, worst_xy = cn._atlas_tile_min_ncc(a, b, 64)
    assert worst_ncc is None and worst_xy is None


# ------------------------------------------------------------------ 6. 既知の残存バグ(denom==0の1LSB差)も本修正で解消される(回帰)

def test_uniform_one_lsb_difference_no_longer_hard_fails():
    """issue本文が言及した「厳密な単色 + 1LSB差」(denom==0分岐が0.0を返す
    従来のバグ)も、mean-diff床の追加により除外される(dmean=1.0<=2.0)。
    旧実装なら _atlas_ncc_flat_rgb 単体は0.0を返す(下のassertで確認)が、
    _atlas_tile_min_ncc は床でこのタイルを弾くため擬陽性化しない。"""
    h = w = 64
    a = np.full((h, w, 4), 128, dtype=np.uint8)
    a[..., 3] = 255
    b = np.full((h, w, 4), 129, dtype=np.uint8)
    b[..., 3] = 255

    direct_ncc = cn._atlas_ncc_flat_rgb(a, b)
    assert direct_ncc == 0.0, (
        "前提条件が変わっている: denom==0分岐の挙動が変化した"
        f"(direct_ncc={direct_ncc})")

    worst_ncc, worst_xy = cn._atlas_tile_min_ncc(a, b, 64)
    assert worst_ncc is None and worst_xy is None
