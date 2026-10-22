# -*- coding: utf-8 -*-
"""dev#1072: build_avatar_variant.build_duplicated_vertices()のstats計装の単体テスト。

背景: 容量膨張の問い合わせ(実例K4XRB4DK、issue #1072)を調査した結果、
位置一致クラスタ(FDuplicatedVerticesBuffer)のサイズkがO(k^2)で出力サイズを
膨張させることを実測で確認した(issue #1072コメント2026-08-07参照、
work\\wp_1072\\work\\wp_1072\\measure\\measure_dvb_scaling.py)。従来この
クラスタサイズ分布は一切ログに出ておらず、以後も同種の報告が来るたびに
「原因不明」を繰り返すため、`build_duplicated_vertices()`へ最小限の`stats`
引数を追加した(戻り値/出力バイト列は不変、計装の追加のみ)。

本テストは:
  1. stats引数を渡さない場合(既定)、従来どおりの戻り値であること(負の対照)
  2. 重複なしの入力でmax_cluster_size=1/0が正しく報告されること
  3. サイズkの単一クラスタでmax_cluster_size=k、dup_vert_data長=k*(k-1)
     (このWPの根因仮説そのものの数式)であること
  4. 複数クラスタが混在する場合、最大サイズが正しく報告されること
を検証する。

実行: python -m pytest pipeline\\py\\test_build_duplicated_vertices_stats.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_avatar_variant as bav  # noqa: E402


def _v(x, y, z):
    """build_duplicated_vertices()は'pos'キーしか見ないので、他属性はダミーでよい。"""
    return {"pos": [x, y, z]}


def test_stats_none_is_backward_compatible_negative_control():
    """負の対照: stats引数を渡さない(既定None)場合、戻り値は従来どおり
    (stats=Noneを渡した場合と完全に同じ)。本WPの追加が既存呼び出し元
    (build_uexp_variant()の唯一の呼び出し箇所)の挙動を変えていないことの確認。"""
    verts = [_v(0, 0, 0), _v(0, 0, 0), _v(1, 1, 1)]
    result_default = bav.build_duplicated_vertices(verts)
    result_explicit_none = bav.build_duplicated_vertices(verts, stats=None)
    assert result_default == result_explicit_none


def test_stats_no_duplicates_reports_max_cluster_size_1():
    """負の対照: 位置重複が1件も無ければmax_cluster_size=1、n_clusters_gt1=0。"""
    verts = [_v(0, 0, 0), _v(1, 1, 1), _v(2, 2, 2)]
    stats = {}
    dup_vert_data, _ = bav.build_duplicated_vertices(verts, stats=stats)
    assert stats["max_cluster_size"] == 1
    assert stats["n_clusters_gt1"] == 0
    # 重複が無い場合、実装のフォールバック(check()通過用のダミー1件)により
    # dup_vert_dataは長さ1になる(build_duplicated_vertices()のdocstring参照)。
    assert len(dup_vert_data) == 1


def test_stats_empty_input_reports_max_cluster_size_0():
    """境界: 頂点0個の場合、max_cluster_size=0(存在しないクラスタの最大値)。"""
    stats = {}
    bav.build_duplicated_vertices([], stats=stats)
    assert stats["max_cluster_size"] == 0
    assert stats["n_clusters_gt1"] == 0


def test_stats_single_large_cluster_matches_ok_formula():
    """このWPの根因仮説そのもの: サイズkの単一クラスタは
    dup_vert_data長=k*(k-1)(O(k^2))になる。issue #1072の実測(k=501で
    理論値との比が1.03に収束)と整合する数式を、実プロダクションコードの
    戻り値で直接検証する。"""
    k = 37
    verts = [_v(9.0, 9.0, 9.0) for _ in range(k)] + [_v(0, 0, 0), _v(1, 1, 1)]
    stats = {}
    dup_vert_data, dup_vert_index = bav.build_duplicated_vertices(verts, stats=stats)
    assert stats["max_cluster_size"] == k
    assert stats["n_clusters_gt1"] == 1
    assert len(dup_vert_data) == k * (k - 1)
    # クラスタ外の2頂点(末尾)はDVBに寄与しない(0件)
    assert dup_vert_index[k] == (0, 0)
    assert dup_vert_index[k + 1] == (0, 0)


def test_stats_multiple_clusters_reports_the_largest():
    """複数クラスタが混在する入力では、最大のクラスタサイズが報告される
    (小さいクラスタに埋もれて見落とされないことの確認)。"""
    verts = (
        [_v(0, 0, 0), _v(0, 0, 0)]                    # クラスタサイズ2
        + [_v(5, 5, 5) for _ in range(9)]              # クラスタサイズ9(最大)
        + [_v(1, 1, 1), _v(1, 1, 1), _v(1, 1, 1)]       # クラスタサイズ3
    )
    stats = {}
    bav.build_duplicated_vertices(verts, stats=stats)
    assert stats["max_cluster_size"] == 9
    assert stats["n_clusters_gt1"] == 3
