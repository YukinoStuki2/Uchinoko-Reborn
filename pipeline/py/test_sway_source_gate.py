# -*- coding: utf-8 -*-
"""test_sway_source_gate.py -- sway_source_gate.pyの単体テスト
(dev#1508 受入ゲート正本化)。実機・pak・Blenderに一切依存しない
(bpy非依存、純粋関数のみ、プレーンなdictでtransform/weightを渡す)。
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sway_source_gate as gate  # noqa: E402


def _t(pos, tail=None, scale=(1.0, 1.0, 1.0)):
    if tail is None:
        tail = (pos[0], pos[1], pos[2] + 1.0)  # 既定: +Z方向へ1.0伸びる非退化ボーン
    return {"pos": list(pos), "tail": list(tail), "scale": list(scale)}


def test_run_gate_all_pass_when_everything_matches_exactly():
    source_bones = ["anchor1", "chain1"]
    group_targets = {"anchor1": "donorA", "chain1": "donorB"}
    src_t = {"anchor1": _t((0, 0, 0)), "chain1": _t((0, 0, 1))}
    dst_t = {"donorA": _t((0, 0, 0)), "donorB": _t((0, 0, 1))}
    src_w = {"anchor1": {"geo_00": {"5": 1.0}}, "chain1": {"geo_00": {"6": 0.5}}}
    dst_w = {"donorA": {"geo_00": {"5": 1.0}}, "donorB": {"geo_00": {"6": 0.5}}}

    report = gate.run_gate(source_bones, group_targets, src_t, src_w, dst_t, dst_w)
    assert report.ok
    assert not report.failed


def test_run_gate_fails_when_source_bone_has_no_donor_mapping():
    """負の対照(dev#1508の症状そのもの): anchorがgroup_targetsに無い
    場合、そのボーンはFAILし、理由文言に「off-by-one」を含む。"""
    source_bones = ["anchor1"]
    group_targets = {}  # anchor1が無い == dev#1508バグの再現
    report = gate.run_gate(source_bones, group_targets, {}, {}, {}, {})
    assert not report.ok
    assert len(report.failed) == 1
    assert report.failed[0].bone == "anchor1"
    assert "off-by-one" in report.failed[0].reasons[0]


def test_run_gate_warns_on_position_mismatch_beyond_epsilon_dev1551():
    """dev#1551(断言ゲート警告格下げ、2026-08-18オーナー裁定確定):
    位置不一致はもはや`ok`をFalseにしない(鎖を除外しない・変換を止めない)
    ——`transform_warnings`へ分離され、警告としてのみ記録される。"""
    source_bones = ["b1"]
    group_targets = {"b1": "d1"}
    src_t = {"b1": _t((0, 0, 0))}
    dst_t = {"d1": _t((0, 0, 1.0), tail=(0, 0, 2.0))}  # 1m ズレ、明らかにepsilon超え
    report = gate.run_gate(source_bones, group_targets, src_t, {}, dst_t, {})
    assert report.ok
    assert not report.failed
    assert any("position mismatch" in r for r in report.results[0].transform_warnings)


def test_run_gate_passes_on_position_within_epsilon():
    source_bones = ["b1"]
    group_targets = {"b1": "d1"}
    src_t = {"b1": _t((0, 0, 0))}
    dst_t = {"d1": _t((0, 0, gate.EPS_POS * 0.5))}  # epsilon未満
    report = gate.run_gate(source_bones, group_targets, src_t, {}, dst_t, {})
    assert report.ok


def test_run_gate_warns_on_direction_mismatch_beyond_tolerance_dev1551():
    """donor回転はlook-at再構成のため生クォータニオンではなく、tail-head
    方向ベクトルの角度差で比較する(モジュールdocstring「回転の比較方法」
    節、2026-08-16実データ検証で訂正)。90度ズレは明らかに許容角度
    (1e-3度、2026-08-16夜レーンF実測で15度から引き締め)を超えるが、
    dev#1551(断言ゲート警告格下げ)により`ok`はFalseにならず、
    `transform_warnings`へ記録されるのみ。"""
    source_bones = ["b1"]
    group_targets = {"b1": "d1"}
    src_t = {"b1": _t((0, 0, 0), tail=(0, 0, 1))}  # +Z方向
    dst_t = {"d1": _t((0, 0, 0), tail=(1, 0, 0))}  # +X方向(90度ズレ)
    report = gate.run_gate(source_bones, group_targets, src_t, {}, dst_t, {})
    assert report.ok
    assert any("direction mismatch" in r for r in report.results[0].transform_warnings)


def test_run_gate_warns_on_small_direction_mismatch_that_old_15deg_tolerance_missed_dev1551():
    """負の対照(2026-08-16夜レーンF、15度撤廃の直接検証、dev#1551で
    「格下げ」に更新): 実測で確認した正常範囲(最大3.52e-6度)よりずっと
    大きいが、旧15度許容なら見逃していた5度のズレは、引き締め後の
    epsilon(1e-3度)では確実に警告として検出される(`ok`には影響しない
    ——dev#1551断言ゲート警告格下げ)。"""
    import math
    source_bones = ["b1"]
    group_targets = {"b1": "d1"}
    src_t = {"b1": _t((0, 0, 0), tail=(0, 0, 1))}  # +Z方向
    small_angle_rad = math.radians(5.0)  # 5度、旧15度許容ならPASSしていた
    dst_tail = (math.sin(small_angle_rad), 0, math.cos(small_angle_rad))
    dst_t = {"d1": _t((0, 0, 0), tail=dst_tail)}
    report = gate.run_gate(source_bones, group_targets, src_t, {}, dst_t, {})
    assert report.ok
    assert any("direction mismatch" in r for r in report.results[0].transform_warnings)


def test_run_gate_passes_on_direction_within_float_precision_tolerance():
    """許容角度(1e-3度)未満の、float精度級の向きズレはPASSする
    (2026-08-16夜レーンF実測: comodo/flatHaori計176ボーンの実残差は最大
    3.52e-6度だった。この値の目安として1e-4度=epsilonの1/10を使う)。"""
    import math
    source_bones = ["b1"]
    group_targets = {"b1": "d1"}
    src_t = {"b1": _t((0, 0, 0), tail=(0, 0, 1))}  # +Z方向
    small_angle_rad = math.radians(gate.EPS_FORWARD_ANGLE_DEG * 0.1)  # epsilon未満
    dst_tail = (math.sin(small_angle_rad), 0, math.cos(small_angle_rad))
    dst_t = {"d1": _t((0, 0, 0), tail=dst_tail)}
    report = gate.run_gate(source_bones, group_targets, src_t, {}, dst_t, {})
    assert report.ok


def test_run_gate_skips_direction_check_when_degenerate():
    """どちらかの方向ベクトルが退化(tail==head、リーフ骨等)している
    場合は角度比較をスキップする(判定不能、FAILにしない)。"""
    source_bones = ["b1"]
    group_targets = {"b1": "d1"}
    src_t = {"b1": _t((0, 0, 0), tail=(0, 0, 0))}  # 退化(tail==head)
    dst_t = {"d1": _t((0, 0, 0), tail=(1, 0, 0))}
    report = gate.run_gate(source_bones, group_targets, src_t, {}, dst_t, {})
    assert report.ok  # position一致・退化方向はスキップなので全体PASS


def test_run_gate_warns_on_scale_mismatch_dev1551():
    """dev#1551(断言ゲート警告格下げ): スケール不一致も他のtransform項目
    同様、`ok`には影響しない警告になる。"""
    source_bones = ["b1"]
    group_targets = {"b1": "d1"}
    src_t = {"b1": _t((0, 0, 0), scale=(1, 1, 1))}
    dst_t = {"d1": _t((0, 0, 0), scale=(2, 1, 1))}
    report = gate.run_gate(source_bones, group_targets, src_t, {}, dst_t, {})
    assert report.ok
    assert any("scale mismatch" in r for r in report.results[0].transform_warnings)


def test_run_gate_fails_when_weight_lost():
    """負の対照(dev#1508の直接症状): ソースにあった頂点ウェイトが
    donor側で失われている(=根元の頂点が揺れないボーンへ迷子になる
    バグと同型)場合、FAILし理由に「lost weight」を含む。"""
    source_bones = ["b1"]
    group_targets = {"b1": "d1"}
    src_t = {"b1": _t((0, 0, 0))}
    dst_t = {"d1": _t((0, 0, 0))}
    src_w = {"b1": {"geo_00": {"5": 1.0, "6": 0.8}}}
    dst_w = {"d1": {"geo_00": {"5": 1.0}}}  # 頂点6のウェイトが消えている
    report = gate.run_gate(source_bones, group_targets, src_t, src_w, dst_t, dst_w)
    assert not report.ok
    assert any("lost weight" in r for r in report.failed[0].reasons)


def test_run_gate_fails_when_weight_value_differs():
    source_bones = ["b1"]
    group_targets = {"b1": "d1"}
    src_t = {"b1": _t((0, 0, 0))}
    dst_t = {"d1": _t((0, 0, 0))}
    src_w = {"b1": {"geo_00": {"5": 1.0}}}
    dst_w = {"d1": {"geo_00": {"5": 0.5}}}  # 値が違う
    report = gate.run_gate(source_bones, group_targets, src_t, src_w, dst_t, dst_w)
    assert not report.ok
    assert any("weight value mismatch" in r for r in report.failed[0].reasons)


def test_run_gate_passes_on_weight_within_epsilon():
    source_bones = ["b1"]
    group_targets = {"b1": "d1"}
    src_t = {"b1": _t((0, 0, 0))}
    dst_t = {"d1": _t((0, 0, 0))}
    src_w = {"b1": {"geo_00": {"5": 1.0}}}
    dst_w = {"d1": {"geo_00": {"5": 1.0 - gate.EPS_WEIGHT * 0.5}}}
    report = gate.run_gate(source_bones, group_targets, src_t, src_w, dst_t, dst_w)
    assert report.ok


def test_run_gate_fails_when_donor_snapshot_missing():
    """donorが決まっている(group_targetsにキーはある)が、実際にはpal_arm
    にそのdonor骨のスナップショットが無い(=骨自体が存在しない/配置され
    なかった)ケース。"""
    source_bones = ["b1"]
    group_targets = {"b1": "d1"}
    report = gate.run_gate(source_bones, group_targets, {"b1": _t((0, 0, 0))}, {}, {}, {})
    assert not report.ok
    assert any("missing from pal_arm snapshot" in r for r in report.failed[0].reasons)


# ---------------------------------------------------------------------
# dev#1551 chain-length-fit: merge_groupsのウェイト合算比較
# ---------------------------------------------------------------------

def test_run_gate_merge_group_compares_summed_source_weight():
    """節数フィット(先端マージ)で2本のソース骨が同じdonorへ写ったとき、
    ウェイト比較は「グループ全員の合算」対「donorの実ウェイト(remapの
    ADD合成後)」で行われ、単純な1:1比較なら誤ってFAILする状況でも
    正しくPASSすることを確認する。"""
    source_bones = ["tail_04", "tail_05"]
    group_targets = {"tail_04": "d_shared", "tail_05": "d_shared"}
    src_t = {"tail_04": _t((0, 0, 0)), "tail_05": _t((0, 0, 0))}
    dst_t = {"d_shared": _t((0, 0, 0))}
    src_w = {"tail_04": {"geo_00": {"5": 0.6}}, "tail_05": {"geo_00": {"5": 0.4}}}
    # donor側は remap の ADD 合成後、両者の合計(1.0)を持つ想定
    dst_w = {"d_shared": {"geo_00": {"5": 1.0}}}
    merge_groups = frozenset({frozenset({"tail_04", "tail_05"})})

    report = gate.run_gate(source_bones, group_targets, src_t, src_w, dst_t, dst_w,
                            merge_groups=merge_groups)
    assert report.ok


def test_run_gate_negative_control_without_merge_groups_the_same_input_fails():
    """負の対照: 上と同じ入力でも`merge_groups`を渡さなければ(=単純1:1
    比較のまま)、donorの合算値(1.0)と各ソース骨の個別値(0.6/0.4)が
    一致せずFAILすることを確認する——`merge_groups`が実際に比較方法を
    切り替えていることの証明。"""
    source_bones = ["tail_04", "tail_05"]
    group_targets = {"tail_04": "d_shared", "tail_05": "d_shared"}
    src_t = {"tail_04": _t((0, 0, 0)), "tail_05": _t((0, 0, 0))}
    dst_t = {"d_shared": _t((0, 0, 0))}
    src_w = {"tail_04": {"geo_00": {"5": 0.6}}, "tail_05": {"geo_00": {"5": 0.4}}}
    dst_w = {"d_shared": {"geo_00": {"5": 1.0}}}

    report = gate.run_gate(source_bones, group_targets, src_t, src_w, dst_t, dst_w)
    assert not report.ok


def test_run_gate_skips_transform_check_for_non_representative_merged_bone_dev1551():
    """dev#1551実機検証で発覚した回帰固定: 節数フィット(先端マージ)発動時、
    donorのジオメトリは常にマージグループの**代表**(先端側)骨の
    transformで配置されるため、**非代表**の元ボーン(例: tail_04、
    根元寄り)を自分自身の生transformとdonorとで比較すると構造的に
    不一致になる(=バグではなく設計どおり)。`representative_of`で
    非代表と分かれば、このボーンの位置/向き/スケール検査はスキップされ、
    ウェイト検査(別経路、merge_groups)だけが効くことを確認する。"""
    source_bones = ["tail_04", "tail_05"]
    group_targets = {"tail_04": "d_shared", "tail_05": "d_shared"}
    # tail_04(非代表)の生transformはdonorと大きくズレている(通常なら
    # position mismatchでFAILする値)が、tail_05(代表)のtransformは
    # donorと完全一致させる。
    src_t = {"tail_04": _t((99, 99, 99)), "tail_05": _t((0, 0, 0))}
    dst_t = {"d_shared": _t((0, 0, 0))}
    src_w = {"tail_04": {"geo_00": {"5": 0.6}}, "tail_05": {"geo_00": {"5": 0.4}}}
    dst_w = {"d_shared": {"geo_00": {"5": 1.0}}}
    merge_groups = frozenset({frozenset({"tail_04", "tail_05"})})
    representative_of = {"tail_04": "tail_05", "tail_05": "tail_05"}

    report = gate.run_gate(source_bones, group_targets, src_t, src_w, dst_t, dst_w,
                            merge_groups=merge_groups, representative_of=representative_of)
    assert report.ok, [r.reasons for r in report.results]


def test_run_gate_negative_control_representative_bone_transform_still_checked_dev1551():
    """負の対照: 代表骨自身のtransformがdonorとズレていれば、
    `representative_of`を渡しても**警告として検出される**ことを確認する
    (代表骨の検査までスキップされてしまえば無検査状態になり危険)。
    dev#1551(断言ゲート警告格下げ)により`ok`自体はFalseにならないが、
    `transform_warnings`には残ることを確認する(=検査は行われている)。"""
    source_bones = ["tail_04", "tail_05"]
    group_targets = {"tail_04": "d_shared", "tail_05": "d_shared"}
    src_t = {"tail_04": _t((0, 0, 0)), "tail_05": _t((99, 99, 99))}  # 代表(tail_05)がズレている
    dst_t = {"d_shared": _t((0, 0, 0))}
    src_w = {"tail_04": {"geo_00": {"5": 0.6}}, "tail_05": {"geo_00": {"5": 0.4}}}
    dst_w = {"d_shared": {"geo_00": {"5": 1.0}}}
    merge_groups = frozenset({frozenset({"tail_04", "tail_05"})})
    representative_of = {"tail_04": "tail_05", "tail_05": "tail_05"}

    report = gate.run_gate(source_bones, group_targets, src_t, src_w, dst_t, dst_w,
                            merge_groups=merge_groups, representative_of=representative_of)
    assert report.ok
    by_bone = {r.bone: r for r in report.results}
    assert any("position mismatch" in w for w in by_bone["tail_05"].transform_warnings)
    assert not by_bone["tail_04"].transform_warnings  # 非代表: 検査自体をスキップ


def test_summary_lines_reports_failed_bones():
    source_bones = ["anchor1"]
    report = gate.run_gate(source_bones, {}, {}, {}, {}, {})
    lines = report.summary_lines()
    assert "1 FAILED" in lines[0]
    assert any("anchor1" in ln for ln in lines[1:])


# ---------------------------------------------------------------------
# dev#1625(2026-08-21 オーナー裁定): 姿勢不一致ハブの最小切除
# ---------------------------------------------------------------------

def test_direction_mismatch_deg_returns_angle():
    """+Z方向と+X方向は90度。"""
    angle = gate.direction_mismatch_deg((0, 0, 0), (0, 0, 1), (0, 0, 0), (1, 0, 0))
    assert angle == pytest.approx(90.0)


def test_direction_mismatch_deg_returns_none_when_degenerate():
    """tail==headの退化方向は判定不能(None)。"""
    angle = gate.direction_mismatch_deg((0, 0, 0), (0, 0, 0), (0, 0, 0), (1, 0, 0))
    assert angle is None


def test_bones_exceeding_posture_cull_threshold_culls_large_mismatch():
    """dev#1625実報告(AvatarSample_A.vrm)の再現: 45.86度は閾値
    (16.5度)を大きく超えるため切除対象になる。"""
    import math
    src_t = {"J_Bip_C_Head": _t((0, 0, 0), tail=(0, 0, 1))}
    angle_rad = math.radians(45.86)
    donor_tail = (math.sin(angle_rad), 0, math.cos(angle_rad))
    dst_t = {"donor_hat": _t((0, 0, 0), tail=donor_tail)}
    group_targets = {"J_Bip_C_Head": "donor_hat"}

    result = gate.bones_exceeding_posture_cull_threshold(
        ["J_Bip_C_Head"], src_t, dst_t, group_targets)
    assert "J_Bip_C_Head" in result
    assert result["J_Bip_C_Head"] == pytest.approx(45.86, abs=0.01)


def test_bones_exceeding_posture_cull_threshold_negative_control_small_mismatch_not_culled():
    """負の対照(dev#1551の趣旨を継続): 較正済み白検体の実測最大値
    (13.68度、prefab_flatapron)相当の小さな不一致は切除されない
    ——閾値(16.5度)を下回るため。"""
    import math
    src_t = {"Tail.005": _t((0, 0, 0), tail=(0, 0, 1))}
    angle_rad = math.radians(13.68)
    donor_tail = (math.sin(angle_rad), 0, math.cos(angle_rad))
    dst_t = {"donor_tail": _t((0, 0, 0), tail=donor_tail)}
    group_targets = {"Tail.005": "donor_tail"}

    result = gate.bones_exceeding_posture_cull_threshold(
        ["Tail.005"], src_t, dst_t, group_targets)
    assert result == {}


def test_bones_exceeding_posture_cull_threshold_skips_missing_donor_mapping():
    """donor未割当の骨は(別経路が処理する前提のため)静かにスキップし、
    KeyErrorを起こさない。"""
    src_t = {"b1": _t((0, 0, 0))}
    result = gate.bones_exceeding_posture_cull_threshold(
        ["b1"], src_t, {}, {})
    assert result == {}


def test_bones_exceeding_posture_cull_threshold_skips_missing_snapshot():
    """donorは割り当てられているがtransformスナップショットが片方
    無い場合も静かにスキップする。"""
    group_targets = {"b1": "d1"}
    result = gate.bones_exceeding_posture_cull_threshold(
        ["b1"], {}, {}, group_targets)
    assert result == {}


def test_bones_exceeding_posture_cull_threshold_multiple_bones_mixed():
    """複数骨のうち閾値超えの骨だけが結果に現れる(dev#1625の「最小切除」
    ——他のハブは無傷で残す、の直接検証)。"""
    import math
    over_rad = math.radians(45.86)
    under_rad = math.radians(2.0)
    src_t = {
        "over": _t((0, 0, 0), tail=(0, 0, 1)),
        "under": _t((10, 0, 0), tail=(10, 0, 1)),
    }
    dst_t = {
        "donor_over": _t((0, 0, 0), tail=(math.sin(over_rad), 0, math.cos(over_rad))),
        "donor_under": _t((10, 0, 0), tail=(10 + math.sin(under_rad), 0, 1 + math.cos(under_rad) - 1)),
    }
    group_targets = {"over": "donor_over", "under": "donor_under"}

    result = gate.bones_exceeding_posture_cull_threshold(
        ["over", "under"], src_t, dst_t, group_targets)
    assert set(result.keys()) == {"over"}
