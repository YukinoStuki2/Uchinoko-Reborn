# -*- coding: utf-8 -*-
"""sway_abp_patcher.py の単体テスト(dev#19、WP-B相当)。

dt_flag_patcher.py / test_vp_dt_row_select.py と同じ方針で、Palworld由来の
バイト列は一切含まない。フィクスチャは全て本ファイル内の
_build_synthetic_template() が合成する「架空の」ABPノードブロック(架空の
ボーン名・架空のNameMap)であり、sway_abp_patcher.py が前提とする物理
レイアウト(RootBone.BoneNameのFNameからの相対オフセット表)を自己完結で
再現している。

実テンプレ(work/rd_19_hardset/abp/cooked/、10家系×F/M・全3プリセット)
との一致は、このWPの実装過程で直接検証済み(work/rd_19_abp_patcher/calib/、
本モジュールのオフセット表を導出した実測そのもの)。work/ はgitignore
対象・Palworldの実データを含むため、その検証はこのリポジトリの自動テスト
には含めない(同梱スタブ問題の再発を避けるため、dt_flag_patcher.pyと同じ
注意)。
"""
from __future__ import annotations

import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sway_abp_patcher as m  # noqa: E402

BLOCK_SIZE = 5000  # 実テンプレのブロック長(実測9970)より小さい架空値。
                    # 本モジュールはこの値を一切ハードコードせず動的に
                    # 算出するので、テスト用に別の値を使っても構造検証になる。

_PARAM_DEFAULTS = {
    "damping": 0.4, "stiffness": 1.0, "wdl": 0.9, "wdr": 0.9,
    "radius": 6.0, "limit_angle": 55.0, "gravity_z": -98.0,
}
_CURVE_DEFAULTS = {
    "stiffness": [[0.0, 0.6], [1.0, 0.08]],
    "wdl": [[0.0, 0.95], [1.0, 0.55]],
    "wdr": [[0.0, 0.95], [1.0, 0.55]],
    "limit_angle": [[0.0, 0.4], [1.0, 1.0]],
}


def _pack_fname(index: int, number: int = 0) -> bytes:
    return struct.pack("<ii", index, number)


def _write_node_block(buf: bytearray, anchor: int, fname_idx: int, fname_num: int,
                       params: dict, curves: dict) -> None:
    """1ノード分のブロックを buf[anchor : anchor+BLOCK_SIZE] に合成する。
    実測レイアウト(sway_abp_patcher._PARAM_OFFSETS / _CURVE_OFFSETS)通りの
    位置にのみ意味のある値を置き、それ以外は 0xAA のダミーで埋める
    (canary位置だけは仕様通り 0x00,0x00,0x00 にする)。"""
    buf[anchor:anchor + BLOCK_SIZE] = b"\xAA" * BLOCK_SIZE
    buf[anchor:anchor + 8] = _pack_fname(fname_idx, fname_num)

    for key, (rel_off, fmt) in m._PARAM_OFFSETS.items():
        struct.pack_into("<" + fmt, buf, anchor + rel_off, params[key])
    gz_off, gz_fmt = m._GRAVITY_Z_OFFSET
    struct.pack_into("<" + gz_fmt, buf, anchor + gz_off, params["gravity_z"])

    for ckey, (k0_offs, k1_offs) in m._CURVE_OFFSETS.items():
        pts = curves[ckey]
        for (t_off, v_off), (t_val, v_val) in zip((k0_offs, k1_offs), pts):
            buf[anchor + t_off - 3:anchor + t_off] = b"\x00\x00\x00"  # canary
            struct.pack_into("<f", buf, anchor + t_off, t_val)
            struct.pack_into("<f", buf, anchor + v_off, v_val)


def _build_synthetic_template(names, root_bones, per_node_overrides=None):
    """names: NameMap(list[str])。root_bones: 各ノードのroot_bone文字列
    (namesに含まれる前提、number=0の単純ケース)。per_node_overrides:
    {node_index: {"params": {...}, "curves": {...}}} で一部の値を変える。
    戻り値: uexp_bytes(bytearrayではなくbytes)。"""
    per_node_overrides = per_node_overrides or {}
    total_len = BLOCK_SIZE * len(root_bones)
    buf = bytearray(total_len)
    for i, bone in enumerate(root_bones):
        idx = names.index(bone)
        params = dict(_PARAM_DEFAULTS)
        curves = {k: [list(p) for p in v] for k, v in _CURVE_DEFAULTS.items()}
        override = per_node_overrides.get(i, {})
        params.update(override.get("params", {}))
        for ck, pts in override.get("curves", {}).items():
            curves[ck] = pts
        _write_node_block(buf, i * BLOCK_SIZE, idx, 0, params, curves)
    return bytes(buf)


_NAMES = ["Filler0", "TailBone", "EarL", "EarR", "Filler1"]
_ROOT_BONES = ["TailBone", "EarL", "EarR"]


def _make_spec_nodes(param_overrides=None, curve_overrides=None):
    param_overrides = param_overrides or {}
    curve_overrides = curve_overrides or {}
    nodes = []
    for bone in _ROOT_BONES:
        nodes.append({
            "root_bone": bone,
            "params": dict(param_overrides.get(bone, _PARAM_DEFAULTS)),
            "curves": {k: [list(p) for p in v]
                       for k, v in curve_overrides.get(bone, _CURVE_DEFAULTS).items()},
        })
    return nodes


# --------------------------------------------------------------- resolve_bone_fname

def test_resolve_bone_fname_literal():
    names = ["A", "M_Hunter001_06", "M_Hunter001"]
    assert m.resolve_bone_fname("M_Hunter001_06", names) == (1, 0)


def test_resolve_bone_fname_base_suffix():
    names = ["A", "M_Hunter001"]
    # "M_Hunter001_14" はNameMapに無いので、ベース+number=15として解決する
    # (実データの実例: dev#19 RESULT.md flatapron scarf_1/scarf_2)。
    assert m.resolve_bone_fname("M_Hunter001_14", names) == (1, 15)


def test_resolve_bone_fname_unresolvable():
    names = ["A", "B"]
    with pytest.raises(m.AbpStructureError):
        m.resolve_bone_fname("NoSuchBone_03", names)


# --------------------------------------------------------------------- find anchors

def test_find_node_anchors_happy_path():
    uexp = _build_synthetic_template(_NAMES, _ROOT_BONES)
    anchors, block_size = m.find_node_anchors(uexp, _NAMES, _ROOT_BONES)
    assert block_size == BLOCK_SIZE
    assert anchors == [0, BLOCK_SIZE, 2 * BLOCK_SIZE]


def test_find_node_anchors_disambiguates_collision():
    """実データで実際に踏んだ罠(dev#19 hardset RESULT.md: Kigurumi001_tail_01
    が別ノードの内部データからも参照され複数ヒットする)を合成データで再現し、
    予測位置検証で正しいアンカーだけを選べることを確認する。"""
    uexp = bytearray(_build_synthetic_template(_NAMES, _ROOT_BONES))
    # EarR ("D") のFNameパターンを、TailBoneノード(index0)ブロック内の
    # 無関係な filler 位置(0xAAで埋めた領域)にも1回埋め込む -> 衝突を発生させる。
    ear_r_idx = _NAMES.index("EarR")
    decoy_pos = 100  # ブロック0の filler 領域内(意味のあるオフセットとは重ならない)
    uexp[decoy_pos:decoy_pos + 8] = _pack_fname(ear_r_idx, 0)
    uexp = bytes(uexp)

    anchors, block_size = m.find_node_anchors(uexp, _NAMES, _ROOT_BONES)
    # 罠を仕込んでも、正しいアンカー(2*BLOCK_SIZE)が選ばれること。
    assert anchors == [0, BLOCK_SIZE, 2 * BLOCK_SIZE]
    assert block_size == BLOCK_SIZE


def test_find_node_anchors_missing_bone_raises():
    uexp = _build_synthetic_template(_NAMES, _ROOT_BONES)
    with pytest.raises(m.AbpStructureError):
        m.find_node_anchors(uexp, _NAMES, ["TailBone", "EarL", "NoSuchBone"])


# ------------------------------------------------------------------------ patching

def test_patch_updates_only_targeted_fields():
    uexp = _build_synthetic_template(_NAMES, _ROOT_BONES)
    new_params = {"TailBone": dict(_PARAM_DEFAULTS, damping=0.5, gravity_z=-50.0)}
    spec_nodes = _make_spec_nodes(param_overrides=new_params)
    patched = m.patch_kawaii_physics_nodes(uexp, _NAMES, spec_nodes)

    assert len(patched) == len(uexp)
    values = m.read_kawaii_physics_node_values(patched, _NAMES, spec_nodes)
    assert values[0]["params"]["damping"] == pytest.approx(0.5)
    assert values[0]["params"]["gravity_z"] == pytest.approx(-50.0)
    # 他ノードは無変更
    assert values[1]["params"]["damping"] == pytest.approx(0.4)
    assert values[2]["params"]["damping"] == pytest.approx(0.4)
    # 変更していないTailBoneの他フィールドも無変更
    assert values[0]["params"]["stiffness"] == pytest.approx(1.0)


def test_patch_curve_values():
    uexp = _build_synthetic_template(_NAMES, _ROOT_BONES)
    new_curves = {"EarL": {"stiffness": [[0.0, 0.6], [1.0, 0.15]]}}
    spec_nodes = _make_spec_nodes(curve_overrides=new_curves)
    # only override the stiffness curve for EarL, keep the rest default
    for node in spec_nodes:
        if node["root_bone"] != "EarL":
            node["curves"] = dict(_CURVE_DEFAULTS)
        else:
            node["curves"] = {**_CURVE_DEFAULTS, **new_curves["EarL"]}

    patched = m.patch_kawaii_physics_nodes(uexp, _NAMES, spec_nodes)
    values = m.read_kawaii_physics_node_values(patched, _NAMES, spec_nodes)
    assert values[1]["curves"]["stiffness"][1][1] == pytest.approx(0.15)
    assert values[1]["curves"]["wdl"][1][1] == pytest.approx(0.55)  # 無変更


def test_patch_byte_length_unchanged():
    uexp = _build_synthetic_template(_NAMES, _ROOT_BONES)
    spec_nodes = _make_spec_nodes(param_overrides={"TailBone": dict(_PARAM_DEFAULTS, radius=9.0)})
    patched = m.patch_kawaii_physics_nodes(uexp, _NAMES, spec_nodes)
    assert len(patched) == len(uexp)


def test_patch_negative_control_untouched_bytes_identical():
    """負の対照: 書き換え対象外の全バイトが不変であること
    (patch_kawaii_physics_nodes 内部の検証と同じ主張を、テスト側からも
    独立に確認する)。"""
    uexp = _build_synthetic_template(_NAMES, _ROOT_BONES)
    spec_nodes = _make_spec_nodes(param_overrides={"EarR": dict(_PARAM_DEFAULTS, limit_angle=30.0)})
    patched = m.patch_kawaii_physics_nodes(uexp, _NAMES, spec_nodes)

    limit_angle_off = m._PARAM_OFFSETS["limit_angle"][0]
    ear_r_anchor = 2 * BLOCK_SIZE
    changed_start = ear_r_anchor + limit_angle_off
    changed_range = set(range(changed_start, changed_start + 4))

    # 実際に異なるバイトは(浮動小数点のバイト表現次第で)4バイト全部とは
    # 限らない(例: 55.0->30.0 は上位2バイトが偶然一致する)。厳密な主張は
    # 「差分は書き換え対象の4バイト範囲の部分集合に収まる」こと。
    diffs = [i for i in range(len(uexp)) if uexp[i] != patched[i]]
    assert diffs, "expected at least one byte to change"
    assert set(diffs) <= changed_range


def test_patch_rejects_curve_with_wrong_point_count():
    uexp = _build_synthetic_template(_NAMES, _ROOT_BONES)
    spec_nodes = _make_spec_nodes()
    spec_nodes[0]["curves"]["stiffness"] = [[0.0, 0.6], [0.3, 0.3], [1.0, 0.08]]  # 3点(スコープ外)
    with pytest.raises(m.AbpStructureError):
        m.patch_kawaii_physics_nodes(uexp, _NAMES, spec_nodes)


def test_patch_negative_control_corrupted_canary_detected():
    """負の対照: canary(InterpMode/TangentMode/TangentWeightMode)が想定
    (常時ゼロ)と異なる場合、オフセット表の前提が崩れているとみなして
    パッチを拒否すること(黙って誤った位置へ書かない)。"""
    uexp = bytearray(_build_synthetic_template(_NAMES, _ROOT_BONES))
    stiff_k0_time_off = m._CURVE_OFFSETS["stiffness"][0][0]
    canary_pos = 0 * BLOCK_SIZE + stiff_k0_time_off - 3
    uexp[canary_pos] = 0x07  # 想定外の値で汚す
    uexp = bytes(uexp)

    spec_nodes = _make_spec_nodes()
    with pytest.raises(m.AbpStructureError):
        m.patch_kawaii_physics_nodes(uexp, _NAMES, spec_nodes)


def test_patch_partial_spec_leaves_unspecified_fields_untouched():
    """spec側にキーが無いパラメータ/カーブは書き換えない(部分適用が
    安全にできること)。"""
    uexp = _build_synthetic_template(_NAMES, _ROOT_BONES)
    spec_nodes = [
        {"root_bone": "TailBone", "params": {"damping": 0.55}, "curves": {}},
        {"root_bone": "EarL", "params": {}, "curves": {}},
        {"root_bone": "EarR", "params": {}, "curves": {}},
    ]
    patched = m.patch_kawaii_physics_nodes(uexp, _NAMES, spec_nodes)
    values = m.read_kawaii_physics_node_values(patched, _NAMES, _make_spec_nodes())
    assert values[0]["params"]["damping"] == pytest.approx(0.55)
    assert values[0]["params"]["stiffness"] == pytest.approx(1.0)  # 無変更
    assert values[0]["curves"]["stiffness"][1][1] == pytest.approx(0.08)  # 無変更


# ---------------------------------------------------------------------------
# opt-in: 開発機ローカルの実cook成果物との照合(UE参照cook版との一致確認)
# ---------------------------------------------------------------------------

# work/ はgitignore対象(Palworld由来のcook成果物を含む)。ここでの参照は
# ファイル名(調査成果物の置き場所の慣習)のみで、実データ自体はこのテスト
# ファイルにもリポジトリにも含まれない。無ければ自動skip
# (test_vp_dt_row_select.py の opt-in real dump パターンと同じ)。
_HARDSET_ABP_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "work", "rd_19_hardset", "abp"))
_TEMPLATE_BASE = os.path.join(_HARDSET_ABP_DIR, "cooked", "ABP_M_OldCloth001_Implimentation")
_REFERENCE_BASE = os.path.join(_HARDSET_ABP_DIR, "cooked", "ABP_M_Ancient001_Implimentation")
_REFERENCE_SPEC = os.path.join(_HARDSET_ABP_DIR, "specs", "spec_M_Ancient001.json")


def test_patch_matches_real_ue_cooked_reference_opt_in():
    """opt-in: 開発機ローカルに work/rd_19_hardset/abp/ の実cook成果物がある
    場合のみ、以下を実データで確認する(dev#19 WP-B 受入ゲート「照合PASS+
    負の対照PASS」の再現可能な形):

      1. positive: ABP_M_OldCloth001(futsuu preset)テンプレへ
         ABP_M_Ancient001(kata preset)のspec値をパッチすると、実際にUEが
         authoring+cookした ABP_M_Ancient001 の値と一致する(9ノード×
         params7項目+カーブ4本×2点、全一致)。両テンプレは root_bone 集合が
         家系非依存で完全同一(gen_specs.py参照)なのでこの比較が成立する。
      2. negative control: spec値を1箇所変えると、参照とは一致しなくなる。
    """
    if not (os.path.isfile(_TEMPLATE_BASE + ".uexp") and os.path.isfile(_REFERENCE_BASE + ".uexp")
             and os.path.isfile(_REFERENCE_SPEC)):
        pytest.skip("開発機ローカルの実cook成果物が無い環境(work/rd_19_hardset/abp/...)")

    import copy
    import json as _json

    import vp_core  # noqa: E402  (pipeline/py内、sys.path挿入済み)

    with open(_REFERENCE_SPEC, encoding="utf-8") as f:
        ref_spec = _json.load(f)
    ref_nodes = ref_spec["nodes"]

    names = vp_core.read_names(_TEMPLATE_BASE + ".uasset")
    ref_names = vp_core.read_names(_REFERENCE_BASE + ".uasset")
    with open(_TEMPLATE_BASE + ".uexp", "rb") as f:
        template_uexp = f.read()
    with open(_REFERENCE_BASE + ".uexp", "rb") as f:
        reference_uexp = f.read()

    patched = m.patch_kawaii_physics_nodes(template_uexp, names, ref_nodes)
    assert len(patched) == len(template_uexp)

    got_values = m.read_kawaii_physics_node_values(patched, names, ref_nodes)
    ref_values = m.read_kawaii_physics_node_values(reference_uexp, ref_names, ref_nodes)

    def close(a, b):
        return abs(float(a) - float(b)) <= 1e-4

    for g, r in zip(got_values, ref_values):
        for pk in g["params"]:
            assert close(g["params"][pk], r["params"][pk]), (g["root_bone"], pk)
        for ck in g["curves"]:
            for gp, rp in zip(g["curves"][ck], r["curves"][ck]):
                assert close(gp[0], rp[0]) and close(gp[1], rp[1]), (g["root_bone"], ck)

    # negative control: 1箇所だけ変えると参照と一致しなくなること。
    bad_nodes = copy.deepcopy(ref_nodes)
    bad_nodes[0]["params"]["damping"] += 0.2
    bad_patched = m.patch_kawaii_physics_nodes(template_uexp, names, bad_nodes)
    bad_values = m.read_kawaii_physics_node_values(bad_patched, names, bad_nodes)
    assert not close(bad_values[0]["params"]["damping"], ref_values[0]["params"]["damping"])
    # 他ノードは無影響のまま。
    for g, r in zip(bad_values[1:], ref_values[1:]):
        assert close(g["params"]["damping"], r["params"]["damping"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
