# -*- coding: utf-8 -*-
"""dev#846 突き合わせテスト: NCC実装2箇所(pipeline\\py\\convert_noue.py と
devtools\\atlas_compare.py)+その消費者(tests\\relgate\\visual_check.py)の
数値パリティを機械的に監視する。

## 背景(work\\opus2_846\\.devonly\\docs\\rd\\ncc_implementations_comparison_20260802.md、第1段)

issue #846 は「NCC計算が3箇所に複製されている」と書くが、実体は**2つの独立実装+
1つの再利用者**である:

  - `pipeline\\py\\convert_noue.py::_atlas_ncc_flat_rgb` / `_atlas_tile_min_ncc` … 独立実装(本番)
  - `devtools\\atlas_compare.py::ncc_flat` / `grid_ncc` … 独立実装(devtools/relgateが使う実体)
  - `tests\\relgate\\visual_check.py` … 自前実装を持たず `atlas_compare.compare()` を
    そのまま呼ぶだけ(72行目/133行目)。つまり atlas_compare.py の数値がそのまま
    relgate(リリース関所)の判定に使われる。

第1段はタイル単位の核心の式(`_atlas_ncc_flat_rgb` と `ncc_flat`)が**ビット単位で
一致**することを実測済み。

## このテストの立場(dev#820で確立した流儀: 統合せず突き合わせ試験で担保する)

PR #844(dev#371、本ファイル作成時点で未マージ)は、擬陽性是正(平坦タイルは
NCCで判定できる情報を持たないので除外する)を **`convert_noue.py`側にだけ**
`ATLAS_VISUAL_TILE_MEAN_DIFF_FLOOR` として追加する。`devtools\\atlas_compare.py`
(→ relgate)には同じ手当てが無い。つまり **#844マージ後は「本番PASS・関所FAIL」
という一方向の食い違いが新たに生まれる**。

本ファイルは「2実装が常に一致する」と素朴に固定しない(#844マージ直後にmasterが
赤くなる)。かといって一致検査を持たないと次の乖離を誰も検知できない。よって:

  - **既知の乖離カタログ(KNOWN_DEVIATIONS)** を持つ。カタログに載っている形の
    食い違いだけを許容し、**乖離の向き**(本番がPASS寄り・関所がFAIL寄り)まで
    固定する。
  - カタログに無い形の食い違いが出たら、あるいは向きが逆転したら、FAILする
    (負の対照テスト§で実際に確認する)。

このファイルは `pipeline\\py\\convert_noue.py` / `devtools\\atlas_compare.py` の
実装本体を一切変更しない(#844と衝突するため。本WPが足すのは検査だけ)。

実行: python -m pytest pipeline/py/test_ncc_impl_parity.py -q
"""
import inspect
import os
import sys

import numpy as np
import pytest

HERE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(HERE_DIR))
DEVTOOLS_DIR = os.path.join(REPO_DIR, "devtools")
if HERE_DIR not in sys.path:
    sys.path.insert(0, HERE_DIR)
if DEVTOOLS_DIR not in sys.path:
    sys.path.insert(0, DEVTOOLS_DIR)

import convert_noue as cn  # noqa: E402
import atlas_compare as ac  # noqa: E402


# ==================================================================
# 既知の乖離カタログ
# ==================================================================
# 各エントリは「このIDの乖離は許容する。ただし直下のテストが固定した
# 具体的な形・向き以外は許容しない」という意味。カタログに載っていない
# 乖離、または載っていても向きが逆の乖離は、対応するテストがFAILする形で
# 検出される(このモジュールはカタログを見て自動的に緩めるような汎用ループを
# 持たない——「許すが、許した形だけ」を意図的にテストごとにベタ書きする)。
KNOWN_DEVIATIONS = [
    {
        "id": "dev371_flat_tile_floor",
        "issue": "dev#371 / PR #844 / dev#846",
        "description": (
            "convert_noue._atlas_tile_min_ncc は、タイルの平均絶対画素差が "
            "ATLAS_VISUAL_TILE_MEAN_DIFF_FLOOR 以下なら、そのタイルをNCCで"
            "判定できる情報を持たないとみなしmin-NCC探索から除外する"
            "(PR #844)。atlas_compare.grid_ncc / relgateには同じ除外が無く、"
            "常にNCCを計算する。"
        ),
        "direction": (
            "production(convert_noue)の判定は常に atlas_compare/relgate と"
            "同じかそれより高い(=PASS寄り)値になる。逆方向"
            "(productionだけが低い値を出す)は絶対に許容しない。"
        ),
        "active_iff": "convert_noue に ATLAS_VISUAL_TILE_MEAN_DIFF_FLOOR が定義されている"
                      "(#844マージ後の状態)",
        "test": "test_known_deviation_flat_tile_floor_pre_and_post_844",
    },
    {
        "id": "denom0_global_vs_tile_asymmetry",
        "issue": "dev#846 第1段 発見2(convert_noue.py内 第4の実装)",
        "description": (
            "convert_noue.py の全体(global) NCC は _render_atlas_visual_check "
            "内にインライン再実装されており(_atlas_ncc_flat_rgb を呼ばない)、"
            "denom==0(タイル/画像全体が完全に単色)のときの救済(バイト一致なら"
            "1.0)が無く常に0.0を返す。タイル用の _atlas_ncc_flat_rgb "
            "(atlas_compare.ncc_flatと同型)は1.0に救済する。よってdenom==0の"
            "ときに限り、全体NCCとタイルNCC/atlas_compareの間で値が食い違う。"
        ),
        "direction": (
            "全体NCC(インライン)は denom==0 で常に0.0(より厳しい=FAIL寄り)。"
            "タイル用/atlas_compareは同条件で1.0(PASS寄り)。実害は低いと"
            "第1段で判定済み(画像全体が完全単色になるのは通常起きない)。"
            "実装は直さない(#844と同じファイルのため、本WPのスコープ外)。"
        ),
        "active_iff": "常時真(convert_noue.py:651-656相当のインライン実装が"
                      "現存する限り)",
        "test": "test_known_deviation_global_ncc_denom0_asymmetry",
    },
]


def _deviation(dev_id):
    for d in KNOWN_DEVIATIONS:
        if d["id"] == dev_id:
            return d
    raise KeyError(f"KNOWN_DEVIATIONSに登録されていない乖離ID: {dev_id}")


# ==================================================================
# 合成データのヘルパ(PR #844のテスト構図を踏襲。work\\opus2_846の
# 第1段実測でも同じ構図が使われている)
# ==================================================================

def _rgba(rgb_u8):
    h, w = rgb_u8.shape[:2]
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[..., :3] = rgb_u8
    out[..., 3] = 255
    return out


def _dithered_flat_tile(rng, h, w, base, p_flip=0.3):
    """ほぼ単色(ソリッドカラーフォールバック相当)タイル。量子化・ディザ由来の
    ±1独立ノイズのみ持つ。目視で完全同一でもNCCが数値的に崩れる(dev#371)。"""
    flips = rng.choice([-1, 0, 1], size=(h, w, 3), p=[p_flip / 2, 1 - p_flip, p_flip / 2])
    arr = np.clip(base + flips, 0, 255).astype(np.uint8)
    return _rgba(arr)


def _healthy_tile_pair(rng, h, w, resample_amp=6):
    """健全タイル(内容一致、ベイク由来の小さな独立ノイズのみ)。"""
    base = rng.integers(0, 255, size=(h, w, 3)).astype(np.int16)
    noise_a = rng.integers(-resample_amp, resample_amp + 1, size=(h, w, 3))
    noise_b = rng.integers(-resample_amp, resample_amp + 1, size=(h, w, 3))
    ta = np.clip(base + noise_a, 0, 255).astype(np.uint8)
    tb = np.clip(base + noise_b, 0, 255).astype(np.uint8)
    return _rgba(ta), _rgba(tb)


def _corrupted_tile_pair(rng, h, w):
    """本物の破損(別の絵に化けた)を模した無関係な内容のペア。"""
    ta = rng.integers(0, 255, size=(h, w, 3)).astype(np.uint8)
    tb = rng.integers(0, 255, size=(h, w, 3)).astype(np.uint8)
    return _rgba(ta), _rgba(tb)


def _build_grid(patch, grid, tiles):
    rows, cols = grid
    h, w = rows * patch, cols * patch
    a = np.zeros((h, w, 4), dtype=np.uint8)
    b = np.zeros((h, w, 4), dtype=np.uint8)
    for (gy, gx), (ta, tb) in tiles.items():
        y0, x0 = gy * patch, gx * patch
        a[y0:y0 + patch, x0:x0 + patch] = ta
        b[y0:y0 + patch, x0:x0 + patch] = tb
    return a, b


def _mixed_scene_8healthy_1flat(seed=2, patch=64):
    """3x3タイル中8枚健全+1枚(2,2)がほぼ単色。PR #844のテスト
    (test_mixed_scene_flat_tile_does_not_dominate_worst)と同一構図。"""
    rng = np.random.default_rng(seed)
    tiles = {}
    for gy in range(3):
        for gx in range(3):
            if gy == 2 and gx == 2:
                tiles[(gy, gx)] = (
                    _dithered_flat_tile(rng, patch, patch, base=186),
                    _dithered_flat_tile(rng, patch, patch, base=186),
                )
            else:
                tiles[(gy, gx)] = _healthy_tile_pair(rng, patch, patch)
    return _build_grid(patch, (3, 3), tiles)


def _scene_8healthy_1corrupted_no_flat(seed=5, patch=64):
    """3x3タイル中8枚健全+1枚(1,1)が本物の破損。平坦タイルを含まない
    (=#844のFLOORが一切作動しない)構図。"""
    rng = np.random.default_rng(seed)
    tiles = {}
    for gy in range(3):
        for gx in range(3):
            if gy == 1 and gx == 1:
                tiles[(gy, gx)] = _corrupted_tile_pair(rng, patch, patch)
            else:
                tiles[(gy, gx)] = _healthy_tile_pair(rng, patch, patch)
    return _build_grid(patch, (3, 3), tiles)


def _atlas_compare_tile_min(a, b, patch):
    """atlas_compare.grid_ncc() の戻り値([{x,y,ncc},...])から
    (worst_ncc, worst_xy) を production側と同じ形に整形するアダプタ
    (第1段§4案Aが指摘した「戻り値形状の違い」をテスト側で吸収する)。"""
    tiles = ac.grid_ncc(a, b, patch)
    if not tiles:
        return None, None
    worst = min(tiles, key=lambda t: t["ncc"])
    return worst["ncc"], (worst["x"], worst["y"])


HAS_DEV371_FLOOR = hasattr(cn, "ATLAS_VISUAL_TILE_MEAN_DIFF_FLOOR")


# ==================================================================
# 1. 核心の式(_atlas_ncc_flat_rgb / ncc_flat)のビット単位パリティ
#    (#844の影響を受けない。#844はこの関数自体を変更しない)
# ==================================================================

@pytest.mark.parametrize("case", [
    "healthy", "corrupted", "denom0_exact_match", "denom0_1lsb_diff",
])
def test_ncc_flat_rgb_bitwise_parity(case):
    rng = np.random.default_rng(hash(case) % (2 ** 31))
    if case == "healthy":
        a, b = _healthy_tile_pair(rng, 32, 32)
    elif case == "corrupted":
        a, b = _corrupted_tile_pair(rng, 32, 32)
    elif case == "denom0_exact_match":
        a = np.full((32, 32, 4), 128, dtype=np.uint8)
        a[..., 3] = 255
        b = a.copy()
    elif case == "denom0_1lsb_diff":
        a = np.full((32, 32, 4), 128, dtype=np.uint8)
        a[..., 3] = 255
        b = np.full((32, 32, 4), 129, dtype=np.uint8)
        b[..., 3] = 255
    else:
        raise AssertionError(case)

    prod = cn._atlas_ncc_flat_rgb(a, b)
    dev = ac.ncc_flat(a, b)
    assert prod == dev, (
        f"[{case}] _atlas_ncc_flat_rgb と ncc_flat がビット単位で不一致: "
        f"production={prod!r} atlas_compare={dev!r}(核心の式が乖離した——"
        f"KNOWN_DEVIATIONSに無い新規の乖離であり、直ちに調査すること)")


# ==================================================================
# 2. タイル分割min-NCCの構造的パリティ(平坦タイルを含まない構図)
#    #844のFLOORが作動しない条件を選んでいるため、#844の有無に関わらず
#    常に一致するはず
# ==================================================================

def test_tile_min_ncc_parity_without_flat_tiles():
    a, b = _scene_8healthy_1corrupted_no_flat()
    prod_ncc, prod_xy = cn._atlas_tile_min_ncc(a, b, 64)
    dev_ncc, dev_xy = _atlas_compare_tile_min(a, b, 64)

    if HAS_DEV371_FLOOR:
        # 前提確認: このシーンには平坦タイル(mean_abs_diff<=FLOOR)が
        # 存在しないこと(=FLOORが作動しない条件であることを保証する)。
        # 保証できていなければ、この関数が「FLOORの影響を受けない」ことの
        # 証明になっていない。
        h, w = a.shape[:2]
        for y in range(0, h - 64 + 1, 64):
            for x in range(0, w - 64 + 1, 64):
                ta, tb = a[y:y + 64, x:x + 64], b[y:y + 64, x:x + 64]
                dmean = float(np.abs(
                    ta[..., :3].astype(np.float64) - tb[..., :3].astype(np.float64)
                ).mean())
                assert dmean > cn.ATLAS_VISUAL_TILE_MEAN_DIFF_FLOOR, (
                    "テスト構築の前提が崩れている: このシーンに平坦タイルが"
                    "混入した(FLOOR非作動条件のテストになっていない)")

    assert prod_ncc == dev_ncc and prod_xy == dev_xy, (
        f"平坦タイルを含まない構図で production と atlas_compare の"
        f"worst_tileが不一致: production=({prod_ncc!r},{prod_xy!r}) "
        f"atlas_compare=({dev_ncc!r},{dev_xy!r})(KNOWN_DEVIATIONSに"
        f"無い新規の乖離)")


# ==================================================================
# 3. 既知の乖離1: dev371_flat_tile_floor
#    #844マージ前後どちらでも green になることをこの1関数で保証する
# ==================================================================

def test_known_deviation_flat_tile_floor_pre_and_post_844():
    dev = _deviation("dev371_flat_tile_floor")
    a, b = _mixed_scene_8healthy_1flat()
    prod_ncc, prod_xy = cn._atlas_tile_min_ncc(a, b, 64)
    dev_ncc, dev_xy = _atlas_compare_tile_min(a, b, 64)

    if not HAS_DEV371_FLOOR:
        # #844マージ前: production も atlas_compare も平坦タイル除外ロジックを
        # 持たない。既知の乖離はまだ発現しない条件 -> 完全一致するはず。
        assert prod_ncc == dev_ncc and prod_xy == dev_xy, (
            f"#844マージ前なのに production と atlas_compare が既に不一致: "
            f"production=({prod_ncc!r},{prod_xy!r}) "
            f"atlas_compare=({dev_ncc!r},{dev_xy!r})。"
            f"未知の乖離が#844と無関係に存在する可能性がある")
        # 平坦タイル(2,2)=(128,128)が実際にworst側で検出されていることの
        # 前提確認(=このテストが本当に「擬陽性が起こりうる状況」を再現できて
        # いることの保証。両者一致だけでは前提が空虚でも通ってしまうため)
        assert dev_xy == (128, 128), (
            f"前提条件が崩れている: 平坦タイル(128,128)がworst側として"
            f"再現できていない(dev_xy={dev_xy})")
        return

    # #844マージ後: production はFLOORで平坦タイル(2,2)を除外し、残り8枚の
    # 健全タイルからworstを選ぶ。atlas_compareはFLOORを持たないので、
    # 平坦タイルを含めた9枚全部からworstを選ぶ(=平坦タイルの低いNCCを
    # そのまま報告する)。これがKNOWN_DEVIATIONS記載の乖離そのもの。
    assert dev_xy == (128, 128), (
        "前提条件が崩れている: atlas_compare側で平坦タイルがworstとして"
        "検出できていない(擬陽性の再現になっていない)")
    assert prod_xy != (128, 128), (
        "productionが平坦タイル(128,128)をworstとして報告した = "
        "#844のFLOORが効いていない(#844の実装が変わった可能性)")

    # 乖離の向きを固定する: production(除外後の残り8枚のworst)は
    # atlas_compare(平坦タイルを含む9枚のworst)以上でなければならない
    # (=production が PASS 寄り、atlas_compare/relgate が FAIL 寄りの
    # 一方向のみを許容する。逆転していたらKNOWN_DEVIATIONS記載と矛盾する
    # ため直ちにFAILさせる)
    assert prod_ncc is not None, (
        "productionのworst_nccがNoneになった(全タイル除外?想定外の形)")
    assert prod_ncc >= dev_ncc, (
        f"乖離の向きが逆転している: production={prod_ncc!r} < "
        f"atlas_compare={dev_ncc!r}(KNOWN_DEVIATIONSの'direction'は"
        f"production >= atlas_compare のみを許容する。この逆転は"
        f"「本番が実害を見逃す」方向であり致命的)")

    # productionの値が「atlas_compareから平坦タイルだけを除いたときのworst」と
    # 一致することまで確認する(=FLOOR以外の理由でズレていないことの保証)
    tiles_excl_flat = [
        t for t in ac.grid_ncc(a, b, 64) if (t["x"], t["y"]) != (128, 128)
    ]
    expected_ncc = min(t["ncc"] for t in tiles_excl_flat)
    assert prod_ncc == expected_ncc, (
        f"productionの除外後worst_nccが「atlas_compareから平坦タイルだけを"
        f"除いた場合のworst」と不一致: production={prod_ncc!r} "
        f"expected={expected_ncc!r}(FLOOR以外の未知の乖離が混入した可能性)")

    assert dev["direction"]  # カタログのdirection文言が空でないことの健全性チェック


# ==================================================================
# 4. 既知の乖離2: denom0_global_vs_tile_asymmetry(実装は直さず記録のみ)
# ==================================================================

def _inline_global_ncc_mirror(a, b):
    """convert_noue.py:651-656相当のインライン全体NCC実装を、コードを変更
    せずに読み取り専用でミラーしたもの(_render_atlas_visual_check内から
    直接呼べないため——同関数はBlenderレンダリング結果ファイルの存在確認から
    始まり、本WPで禁止された実変換無しには到達できない)。denom==0の扱いが
    _atlas_ncc_flat_rgbと食い違う(常に0.0、バイト一致救済が無い)ことだけを
    固定する。実装そのものを直すことは本WPのスコープ外(#844と同じファイル)。"""
    af = a[:, :, :3].astype(np.float64).ravel()
    bf = b[:, :, :3].astype(np.float64).ravel()
    af = af - af.mean()
    bf = bf - bf.mean()
    denom = float((af ** 2).sum() ** 0.5 * (bf ** 2).sum() ** 0.5)
    return float((af * bf).sum() / denom) if denom else 0.0


def test_known_deviation_global_ncc_denom0_asymmetry():
    _deviation("denom0_global_vs_tile_asymmetry")  # カタログ登録の存在確認

    # ソースの生存確認(カナリア): インライン実装の該当箇所が今も
    # 「denom があれば計算、無ければ0.0固定」という形のままであることを
    # 軽く確認する(全く別の実装に静かに変わっていたら、この乖離記録自体が
    # 陳腐化しているのでカナリアで気づけるようにする)。
    src = inspect.getsource(cn._render_atlas_visual_check)
    assert "if denom else 0.0" in src, (
        "convert_noue.py の _render_atlas_visual_check 内、全体NCCの"
        "denom==0処理の形が変わった可能性がある。"
        "KNOWN_DEVIATIONSの'denom0_global_vs_tile_asymmetry'記録が"
        "陳腐化していないか確認すること(本WPはこの実装を直さない前提で"
        "記録しているため、形が変われば記録ごと見直しが要る)")

    h = w = 8
    a = np.full((h, w, 4), 100, dtype=np.uint8)
    b = a.copy()  # denom==0、バイト完全一致

    inline_result = _inline_global_ncc_mirror(a, b)
    tile_result = cn._atlas_ncc_flat_rgb(a, b)

    assert inline_result == 0.0, (
        f"前提が変わった: インライン全体NCCのdenom==0処理が0.0を返さなく"
        f"なった({inline_result!r})。これは以前は '常に0.0' だった"
        f"(バイト一致でも救済なし)。仕様が変わったなら記録を更新すること")
    assert tile_result == 1.0, (
        f"前提が変わった: _atlas_ncc_flat_rgb のdenom==0救済"
        f"(バイト一致なら1.0)が効かなくなった({tile_result!r})")
    assert inline_result != tile_result, (
        "既知の乖離が消えている(=誰かが直した)。もし本当に直したなら、"
        "KNOWN_DEVIATIONSからこのエントリを外し、このテストを"
        "「一致することを確認する回帰テスト」に書き換えること"
        "(このassertが指し示すのは『まだ直っていない』という現状であり、"
        "直った場合はテストの意図そのものを更新するのが正しい対応)")


# ==================================================================
# 5. 負の対照(必須): 検査自体が空胴でないことの証明
# ==================================================================

def test_negative_control_bitwise_parity_detects_injected_drift(monkeypatch):
    """核心の式(§1)を意図的にずらすと、パリティ検査が実際にFAILすることを
    証明する(検査が空胴化していないことの証明)。"""
    rng = np.random.default_rng(42)
    a, b = _healthy_tile_pair(rng, 32, 32)

    real_ncc_flat = ac.ncc_flat

    def _drifted_ncc_flat(x, y):
        return real_ncc_flat(x, y) + 0.05  # 意図的にずらす

    monkeypatch.setattr(ac, "ncc_flat", _drifted_ncc_flat)

    prod = cn._atlas_ncc_flat_rgb(a, b)
    dev = ac.ncc_flat(a, b)
    with pytest.raises(AssertionError):
        assert prod == dev, "この行がFAILすることを期待している(意図的なズレ)"


def test_negative_control_direction_reversal_is_caught():
    """乖離の向きが逆転した(=productionの方がatlas_compareより低い、
    「実害を見逃さない」はずが逆に厳しくなった、ではなく実際にはFAILすべき
    ケースをPASSさせてしまう危険な逆転)ケースを、direction固定の
    assertが実際に検出することを証明する。"""
    a, b = _mixed_scene_8healthy_1flat()
    dev_ncc, dev_xy = _atlas_compare_tile_min(a, b, 64)
    assert dev_xy == (128, 128)

    # production側の値を「atlas_compareより低い」よう捏造する
    # (=向きが逆転した異常事態を模擬)
    fake_prod_ncc = dev_ncc - 0.1

    with pytest.raises(AssertionError):
        assert fake_prod_ncc >= dev_ncc, (
            "この行がFAILすることを期待している(向き逆転の模擬)")


def test_negative_control_unregistered_mismatch_is_not_silently_allowed():
    """KNOWN_DEVIATIONSに登録されていない形の食い違いは、たとえ
    'production側の値の方が高い'という条件だけを見ても、テストの本体
    (test_known_deviation_flat_tile_floor_pre_and_post_844)がworst_xyの
    座標一致や『atlas_compareから平坦タイルだけを除いたときのworstと
    一致する』ところまで見ているため、単純な数値の大小比較だけでは
    すり抜けられないことを確認する(=カタログ外の乖離を数値の運だけで
    通過させない設計になっていることの証明)。"""
    a, b = _mixed_scene_8healthy_1flat()
    tiles = ac.grid_ncc(a, b, 64)
    tiles_excl_flat = [t for t in tiles if (t["x"], t["y"]) != (128, 128)]
    expected_ncc = min(t["ncc"] for t in tiles_excl_flat)

    # 「productionの値が atlas_compare 全体worstより高い」という条件だけは
    # 満たすが、「除外後worstと一致する」という、より厳しい第2条件には
    # 一致しない偽の値(=未登録の別原因で高くなったふりをする)
    bogus_prod_ncc = expected_ncc + 0.2137  # 除外後worstとは意図的に一致させない

    global_worst_ncc = min(t["ncc"] for t in tiles)
    assert bogus_prod_ncc >= global_worst_ncc  # 向きの条件は満たしてしまう
    with pytest.raises(AssertionError):
        assert bogus_prod_ncc == expected_ncc, (
            "この行がFAILすることを期待している"
            "(未登録の乖離を模擬——向きだけ見た検査ならすり抜けてしまう)")
