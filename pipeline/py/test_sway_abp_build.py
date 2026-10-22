# -*- coding: utf-8 -*-
"""sway_abp_build.py の単体テスト(dev#19、揺れものpak生成の製品パイプライン
結線)。

`pipeline\\py\\sway_abp_templates\\` に同梱された実テンプレ(自前生成アセット、
sway_abp_templates/README.md参照)を対象にしたスモーク検証と、
純ロジック部分(硬さプリセット選択・no-op条件)の単体テストの両方を持つ。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sway_abp_build as m  # noqa: E402
import sway_abp_patcher  # noqa: E402
import vp_core  # noqa: E402


# =====================================================================
# 硬さプリセット選択(純ロジック、I/O無し)
# =====================================================================

@pytest.mark.parametrize("intensity,expected", [
    (None, None),
    ("", None),
    ("none", None),
    ("hard", "kata"),
    ("normal", "futsuu"),
    ("soft", "yawa"),
    ("bogus", None),  # 負の対照: 未知の値は安全側でNone
])
def test_hardness_key_for_intensity(intensity, expected):
    assert m.hardness_key_for_intensity(intensity) == expected


def test_build_spec_nodes_shape():
    """尻尾/汎用布系(chain_family_for()=="tail")ノードの形。"""
    nodes = m.build_spec_nodes(["boneA", "boneB"], "kata")
    assert [n["root_bone"] for n in nodes] == ["boneA", "boneB"]
    damping, stiffness, wd = m.HARDNESS["kata"]
    for n in nodes:
        assert n["params"]["damping"] == damping
        assert n["params"]["stiffness"] == stiffness
        # 2026-08-14夜官能確定: wdl/wdrはプリセット別値(kata=0.3)。
        # gravity_z=0・limit_angle=0は尻尾系のhardness_key非依存の既定
        # (KP公式の制限無効センチネル)。
        assert n["params"]["wdl"] == wd
        assert n["params"]["wdr"] == wd
        assert n["params"]["gravity_z"] == 0.0
        assert n["params"]["limit_angle"] == 0
        # カーブは恒等(root=tip=1.0、鎖方向のシェーピングをしない)。
        for key in ("stiffness", "wdl", "wdr", "limit_angle"):
            assert n["curves"][key] == [[0, 1.0], [1, 1.0]]


def test_build_spec_nodes_ear_no_longer_family_fixed():
    """dev#1508最終仕様(SPEC.md §1-7): 耳の自動kata固定は廃止済み。
    node_overrides省略時は耳ノードも尻尾ノードと同じくhardness_key一律の
    値を受け取る(family分岐がhardness選択にもう関与しないことの直接確認)。"""
    root_bones = ["F_Kigurumi001_tail_01", "HeadEquip062_ear_01_l", "HeadEquip062_ear_01_r"]
    for hardness_key in ("yawa", "futsuu", "kata"):
        nodes = m.build_spec_nodes(root_bones, hardness_key)
        by_bone = {n["root_bone"]: n for n in nodes}
        damping, stiffness, wd = m.HARDNESS[hardness_key]
        for rb in root_bones:
            assert by_bone[rb]["params"]["damping"] == damping
            assert by_bone[rb]["params"]["stiffness"] == stiffness
            assert by_bone[rb]["params"]["wdl"] == wd
            assert by_bone[rb]["params"]["wdr"] == wd


def test_build_spec_nodes_hardness_key_takes_precedence_over_node_override_style(): # noqa: E501
    """dev#1587修理(2026-08-19オーナー裁定「なおればそれでいいよ」、v2.11方式):
    job.sway_intensity由来のhardness_keyが、node_overrides["style"]より優先して
    全root_boneへ一括で刻まれる(旧dev#1508 W2aの優先順位を反転)。

    修理前は逆(override["style"]が勝つ)だったため、実配線鎖
    (=自動アロケータがnode_overridesを書く鎖、laneK3実測で耳/尻尾3鎖)では
    GUI「硬さ4択」が常にno-opだった(issue dev#1587)。node_overridesに
    載っているroot_boneでも、hardness_keyを変えればparamsが変わることを
    直接確認する(修理前はここが変わらない=赤)。"""
    root_bones = ["F_Kigurumi001_tail_01", "HeadEquip062_ear_01_l"]
    # 自動量子化がstyle="kata"固定で書いたと仮定した鎖(両方に付与)。
    node_overrides = {
        "F_Kigurumi001_tail_01": {"style": "kata", "limit_angle": None},
        "HeadEquip062_ear_01_l": {"style": "kata", "limit_angle": None},
    }
    nodes_hard = m.build_spec_nodes(root_bones, "kata", node_overrides=node_overrides)
    nodes_soft = m.build_spec_nodes(root_bones, "yawa", node_overrides=node_overrides)
    by_bone_hard = {n["root_bone"]: n for n in nodes_hard}
    by_bone_soft = {n["root_bone"]: n for n in nodes_soft}

    kata_damping, kata_stiffness, kata_wd = m.HARDNESS["kata"]
    yawa_damping, yawa_stiffness, yawa_wd = m.HARDNESS["yawa"]

    for rb in root_bones:
        # hardness_key="kata"で呼べばoverrideの有無に関わらずkata値。
        assert by_bone_hard[rb]["params"]["damping"] == kata_damping
        assert by_bone_hard[rb]["params"]["stiffness"] == kata_stiffness
        assert by_bone_hard[rb]["params"]["wdl"] == kata_wd
        # hardness_key="yawa"で呼べばoverride["style"]="kata"を無視してyawa値。
        assert by_bone_soft[rb]["params"]["damping"] == yawa_damping
        assert by_bone_soft[rb]["params"]["stiffness"] == yawa_stiffness
        assert by_bone_soft[rb]["params"]["wdl"] == yawa_wd
        # 修理前はここが等しくなってしまっていた(overrideのkata固定が常勝)。
        assert by_bone_hard[rb]["params"] != by_bone_soft[rb]["params"]


def test_build_spec_nodes_node_override_limit_angle_still_applies_after_fix():
    """dev#1587修理の範囲確認: 反転したのはstyle(硬さ)の出どころだけで、
    node_overrides["limit_angle"](SPEC.md §1-3b角度制限写し、donor自身の
    値)は引き続きparamsへ書かれる(配線トポロジ・limit_angle写しは不変、
    タスク契約「変えるのはhardness値の出どころだけ」の直接確認)。"""
    root_bones = ["boneA"]
    node_overrides = {"boneA": {"style": "kata", "limit_angle": 42.5}}
    nodes = m.build_spec_nodes(root_bones, "yawa", node_overrides=node_overrides)
    assert nodes[0]["params"]["limit_angle"] == 42.5
    # styleはyawa側(hardness_key)が勝つ。
    yawa_damping, yawa_stiffness, _ = m.HARDNESS["yawa"]
    assert nodes[0]["params"]["damping"] == yawa_damping
    assert nodes[0]["params"]["stiffness"] == yawa_stiffness


@pytest.mark.parametrize("hardness_key", ["yawa", "futsuu", "kata"])
def test_build_spec_nodes_intensity_stamps_all_root_bones_uniformly(hardness_key):
    """受入②: hard/normal/softいずれのhardness_keyでも、node_overridesの
    有無・styleに関わらず、全root_boneがv2.11正値テーブル(HARDNESS)どおりの
    値を一律に持つ(一括刻印)。overrideの無いbone・overrideありでstyleが
    一致するbone・overrideありでstyleが不一致なboneの3通りを混在させる。"""
    root_bones = ["boneA", "boneB", "boneC", "HeadEquip062_ear_01_l"]
    other_style = "yawa" if hardness_key != "yawa" else "kata"
    node_overrides = {
        "boneA": {"style": hardness_key, "limit_angle": None},  # override==hardness_key(一致)
        "boneB": {"style": other_style, "limit_angle": None},   # override!=hardness_key(不一致)
        # boneC・耳ボーンはoverride無し
    }
    nodes = m.build_spec_nodes(root_bones, hardness_key, node_overrides=node_overrides)
    damping, stiffness, wd = m.HARDNESS[hardness_key]
    assert len(nodes) == len(root_bones)
    for n in nodes:
        assert n["params"]["damping"] == damping
        assert n["params"]["stiffness"] == stiffness
        assert n["params"]["wdl"] == wd
        assert n["params"]["wdr"] == wd


def test_build_spec_nodes_node_overrides_limit_angle_written():
    """dev#1508 SPEC §1-3b: node_overridesのlimit_angleがparamsへ写る
    (Noneなら上書きしない=既定の0のまま)。"""
    root_bones = ["boneA", "boneB"]
    node_overrides = {
        "boneA": {"style": "futsuu", "limit_angle": 42.5},
        "boneB": {"style": "futsuu", "limit_angle": None},
    }
    nodes = m.build_spec_nodes(root_bones, "futsuu", node_overrides=node_overrides)
    by_bone = {n["root_bone"]: n for n in nodes}
    assert by_bone["boneA"]["params"]["limit_angle"] == 42.5
    assert by_bone["boneB"]["params"]["limit_angle"] == 0  # 上書き無し=既定値のまま


def test_build_spec_nodes_no_overrides_matches_pre_w2a_behavior():
    """④相当の無退行確認: node_overrides省略/None/空dictは全て同一出力
    (このW2a機能追加前と一致する)。"""
    root_bones = ["F_Kigurumi001_tail_01", "HeadEquip062_ear_01_l"]
    baseline = m.build_spec_nodes(root_bones, "kata")
    omitted = m.build_spec_nodes(root_bones, "kata", node_overrides=None)
    empty = m.build_spec_nodes(root_bones, "kata", node_overrides={})
    assert omitted == baseline
    assert empty == baseline


@pytest.mark.parametrize("root_bone,expected", [
    ("HeadEquip062_ear_01_l", "ear"),
    ("HeadEquip062_ear_01_r", "ear"),
    ("F_Kigurumi001_tail_01", "tail"),
    ("NPC_GrassBoss001_Skin001_tail_01", "tail"),
    ("F_OldCloth001_04", "tail"),  # 汎用布鎖もtail家系(既定)扱い
    ("Ear_Special_01", "ear"),  # 大文字始まりも判定できる(.lower()確認)
])
def test_chain_family_for(root_bone, expected):
    assert m.chain_family_for(root_bone) == expected


def test_build_spec_nodes_unknown_hardness_raises():
    # 負の対照: 未知の硬さキーは黙って既定値へ倒れず例外
    with pytest.raises(m.SwayAbpBuildError):
        m.build_spec_nodes(["boneA"], "totally_unknown_preset")


def test_hardness_and_base_params_regression():
    """2026-08-14夜 kp_tuner GUI実機官能確定値の回帰防止
    (値そのものの意図しない変更を検出)。yawa=F1(2026-08-14昼オーナー官能
    確定値、2026-08-16裁定で復帰)。"""
    assert m.HARDNESS["yawa"] == (0.25, 0.05, 0.0)  # F1・オーナー官能確定値
    assert m.HARDNESS["futsuu"] == (0.08, 0.20, 0.0)  # オーナー官能確定値
    assert m.HARDNESS["kata"] == (0.30, 0.30, 0.3)  # オーナー官能確定値
    assert m._BASE_PARAMS["gravity_z"] == 0.0  # noqa: SLF001
    assert m._BASE_PARAMS["limit_angle"] == 0  # noqa: SLF001
    # _EAR_PARAMS_OVERRIDE(耳の自動kata固定)はdev#1508最終仕様(SPEC.md
    # §1-7)で廃止済み。定数自体が存在しないことを負の対照として確認。
    assert not hasattr(m, "_EAR_PARAMS_OVERRIDE")


# =====================================================================
# no-op条件(揺れ無効、完全にI/Oを起こさない)
# =====================================================================

@pytest.mark.parametrize("job", [
    {},
    {"sway_intensity": "none"},
    {"sway_intensity": "bogus"},
])
def test_sway_abp_pak_entries_disabled_is_noop(job, tmp_path):
    out_dir = tmp_path / "out"
    entries = m.sway_abp_pak_entries(job, str(out_dir))
    assert entries == []
    # 完全no-op: out_dirすら作られない
    assert not out_dir.exists()


def test_sway_abp_pak_entries_no_templates_is_noop(tmp_path):
    """テンプレ未同梱(specs/が空)ディレクトリを渡した場合も安全に空リスト。"""
    empty_templates = tmp_path / "empty_templates"
    os.makedirs(empty_templates / "cooked")
    os.makedirs(empty_templates / "specs")
    entries = m.sway_abp_pak_entries(
        {"sway_intensity": "hard"}, str(tmp_path / "out"), templates_dir=str(empty_templates))
    assert entries == []


# =====================================================================
# 実テンプレ(pipeline\py\sway_abp_templates\)を使ったスモーク検証
# =====================================================================

def test_real_manifest_loads():
    manifest = m.load_template_manifest()
    assert manifest, "sway_abp_templates/specs/ にテンプレが1件も見つからない"
    for t in manifest:
        assert t["target_abp"].startswith(
            "/Game/Pal/Blueprint/Character/Player/Imp_Cloth/ABP_")
        assert t["root_bones"], f"{t['target_abp']}: root_bones is empty"
        assert t["uasset_name"].endswith(".uasset")
        assert t["uexp_name"].endswith(".uexp")


def test_real_manifest_count_matches_cooked_files():
    """specs/*.jsonの件数(=テンプレ論理数)と、cooked/配下の実ファイル数
    (uasset+uexpのペア)が一致することを機械確認する(README.mdの
    「テンプレ差し替え」手順で片方だけ更新し忘れた事故を検出する目的)。"""
    manifest = m.load_template_manifest()
    cooked_files = set(os.listdir(m.COOKED_DIR))
    for t in manifest:
        assert t["uasset_name"] in cooked_files, f"missing cooked file: {t['uasset_name']}"
        assert t["uexp_name"] in cooked_files, f"missing cooked file: {t['uexp_name']}"


@pytest.mark.parametrize("intensity", ["hard", "normal", "soft"])
def test_sway_abp_pak_entries_real_smoke(intensity, tmp_path):
    """実テンプレへ実際にパッチをかけ、指定した硬さプリセットの値が
    書き込まれていることを sway_abp_patcher.read_kawaii_physics_node_values()
    で読み戻して確認する(値を合わせるのではなく、実際に効いていることの
    直接検証、CLAUDE.md「実装したと効いているは別」の精神)。

    先頭テンプレ(spec_F_Ancient001.json)のroot_bonesは耳鎖("ear"を含む)と
    尻尾/汎用布鎖が混在するため、鎖ごとにfamily別の期待値で検証する。"""
    manifest = m.load_template_manifest()
    entries = m.sway_abp_pak_entries({"sway_intensity": intensity}, str(tmp_path))
    assert len(entries) == 2 * len(manifest)

    hardness_key = m.hardness_key_for_intensity(intensity)
    damping, stiffness, wd = m.HARDNESS[hardness_key]

    # 先頭1テンプレだけ深く検証すれば十分(残りはsway_abp_patcher.py側の
    # 単体テストが構造そのものを既に検証済み)。
    t0 = manifest[0]
    uasset_out = os.path.join(str(tmp_path), t0["uasset_name"])
    uexp_out = os.path.join(str(tmp_path), t0["uexp_name"])
    assert os.path.isfile(uasset_out)
    assert os.path.isfile(uexp_out)

    names = vp_core.read_names(uasset_out)
    with open(uexp_out, "rb") as f:
        patched_uexp = f.read()
    spec_nodes_for_read = [{"root_bone": rb} for rb in t0["root_bones"]]
    values = sway_abp_patcher.read_kawaii_physics_node_values(
        patched_uexp, names, spec_nodes_for_read)
    assert len(values) == len(t0["root_bones"])

    # dev#1508最終仕様(SPEC.md §1-7): 耳の自動kata固定は廃止済み。
    # node_overrides省略時は耳/尻尾いずれもhardness_key一律の値を持つ。
    seen = 0
    for v in values:
        seen += 1
        assert v["params"]["damping"] == pytest.approx(damping)
        assert v["params"]["stiffness"] == pytest.approx(stiffness)
        assert v["params"]["wdl"] == pytest.approx(wd)
        # カーブは恒等(root=tip=1.0)。
        assert v["curves"]["stiffness"][0][1] == pytest.approx(1.0)
        assert v["curves"]["stiffness"][1][1] == pytest.approx(1.0)
    assert seen == len(t0["root_bones"])

    # 負の対照: uasset(NameMap等)自体はテンプレのバイトのままであること
    # (sway_abp_patcher.pyはuexpのみを書き換える設計、docstring参照)。
    orig_uasset = os.path.join(m.COOKED_DIR, t0["uasset_name"])
    with open(orig_uasset, "rb") as f:
        orig_bytes = f.read()
    with open(uasset_out, "rb") as f:
        out_bytes = f.read()
    assert orig_bytes == out_bytes


@pytest.mark.parametrize("intensity", ["hard", "normal", "soft"])
def test_sway_abp_pak_entries_real_smoke_intensity_overrides_node_style(intensity, tmp_path):
    """受入②(実テンプレ経由、dev#1587): 実配線鎖を模して全root_boneへ
    node_overridesの"style"を意図的に**逆極性**で仕込んでも、
    job["sway_intensity"]由来のhardness_keyが一律に勝つ(=laneK3が実測した
    「override対象鎖だけhard/soft間でparamsが変わらない」不具合の直接的な
    負の対照。修理前はこのテストが失敗する)。"""
    manifest = m.load_template_manifest()
    t0 = manifest[0]
    opposite_style = {"hard": "yawa", "normal": "yawa", "soft": "kata"}[intensity]
    node_overrides = {
        rb: {"style": opposite_style, "limit_angle": None} for rb in t0["root_bones"]
    }

    entries = m.sway_abp_pak_entries(
        {"sway_intensity": intensity}, str(tmp_path), node_overrides=node_overrides)
    assert len(entries) == 2 * len(manifest)

    hardness_key = m.hardness_key_for_intensity(intensity)
    damping, stiffness, wd = m.HARDNESS[hardness_key]

    uasset_out = os.path.join(str(tmp_path), t0["uasset_name"])
    uexp_out = os.path.join(str(tmp_path), t0["uexp_name"])
    names = vp_core.read_names(uasset_out)
    with open(uexp_out, "rb") as f:
        patched_uexp = f.read()
    spec_nodes_for_read = [{"root_bone": rb} for rb in t0["root_bones"]]
    values = sway_abp_patcher.read_kawaii_physics_node_values(
        patched_uexp, names, spec_nodes_for_read)
    assert len(values) == len(t0["root_bones"])
    for v in values:
        assert v["params"]["damping"] == pytest.approx(damping)
        assert v["params"]["stiffness"] == pytest.approx(stiffness)
        assert v["params"]["wdl"] == pytest.approx(wd)
        assert v["params"]["wdr"] == pytest.approx(wd)


def test_rel_path_derivation_matches_common_mount_convention():
    """pak内相対パスがtarget_abpの"/Game/Pal/"以降とバイト一致し、
    ".."を含まないこと(vp_pakwrite.COMMON_MOUNT体系の不変条件)を確認する。"""
    manifest = m.load_template_manifest()
    t0 = manifest[0]
    rel = m._rel_from_target_abp(t0["target_abp"])  # noqa: SLF001 (WP内部関数の直接検証)
    assert rel == t0["target_abp"][len("/Game/Pal/"):]
    assert ".." not in rel.split("/")
    assert not rel.startswith("/")


def test_malformed_spec_raises(tmp_path):
    """負の対照: target_abp/nodesを欠いたspecは黙って無視されず例外になる。"""
    specs_dir = tmp_path / "specs"
    os.makedirs(specs_dir)
    with open(specs_dir / "broken.json", "w", encoding="utf-8") as f:
        json.dump({"ali": "x", "skeleton": "y"}, f)  # target_abp/nodes欠落
    with pytest.raises(m.SwayAbpBuildError):
        m.load_template_manifest(str(specs_dir))


# =====================================================================
# ラボ機能「生パラメータ全解放パネル」(dev#1418、
# work\wp_1418_rawparam\BRIEF.md、2026-08-15)。受入の柱=④既定値不変
# (job["lab_raw_sway_params"]キー不在/空/不正でバイト完全一致)+
# 負の対照(有効な上書きでは一致しない)。
# =====================================================================


def test_raw_sway_params_from_job_missing_or_malformed_is_none():
    assert m.raw_sway_params_from_job({}) is None
    assert m.raw_sway_params_from_job({"lab_raw_sway_params": None}) is None
    assert m.raw_sway_params_from_job({"lab_raw_sway_params": {}}) is None
    assert m.raw_sway_params_from_job({"lab_raw_sway_params": "bogus"}) is None
    assert m.raw_sway_params_from_job({"lab_raw_sway_params": []}) is None


def test_raw_sway_params_from_job_unknown_family_ignored():
    # 負の対照: tail/ear以外のキーは黙って無視される(構造ガーベジ耐性)。
    job = {"lab_raw_sway_params": {"wing": {"stiffness": 0.9}}}
    assert m.raw_sway_params_from_job(job) is None


def test_raw_sway_params_from_job_extracts_valid_family():
    job = {"lab_raw_sway_params": {"tail": {"stiffness": 0.9, "damping": 0.4}}}
    result = m.raw_sway_params_from_job(job)
    assert result == {"tail": {"stiffness": 0.9, "damping": 0.4}}


def test_raw_sway_params_from_job_clamps_out_of_range():
    job = {"lab_raw_sway_params": {
        "tail": {"stiffness": 5.0, "gravity_z": 50.0, "limit_angle": -10.0},
    }}
    result = m.raw_sway_params_from_job(job)
    assert result["tail"]["stiffness"] == 1.0  # clamp上限
    assert result["tail"]["gravity_z"] == 0.0  # 範囲(-100..0)の上限
    assert result["tail"]["limit_angle"] == 0.0  # 範囲(0..180)の下限


@pytest.mark.parametrize("raw", [None, True, False, "bogus", [1, 2]])
def test_raw_sway_params_from_job_invalid_value_type_ignored(raw):
    # 負の対照: 個別キーの値が数値でない/boolはそのキーだけ無視される
    # (他の有効な値は活きる、家系ごと丸ごと無効にはしない設計)。
    job = {"lab_raw_sway_params": {"tail": {"stiffness": raw, "damping": 0.5}}}
    result = m.raw_sway_params_from_job(job)
    assert result == {"tail": {"damping": 0.5}}


def test_raw_sway_params_from_job_non_dict_family_ignored():
    job = {"lab_raw_sway_params": {"tail": "not-a-dict", "ear": {"wd": 0.5}}}
    result = m.raw_sway_params_from_job(job)
    assert result == {"ear": {"wd": 0.5}}


def test_apply_raw_sway_params_only_overrides_present_keys():
    base = {"stiffness": 0.2, "damping": 0.08, "wdl": 0.0, "wdr": 0.0,
            "gravity_z": 0.0, "limit_angle": 0, "radius": 6}
    result = m.apply_raw_sway_params(base, {"stiffness": 0.9})
    assert result["stiffness"] == 0.9
    # 他キーは不変(radiusはそもそもraw_overrideの対象外)。
    assert result["damping"] == base["damping"]
    assert result["wdl"] == base["wdl"]
    assert result["radius"] == base["radius"]
    # 入力baseは変更されない。
    assert base["stiffness"] == 0.2


def test_apply_raw_sway_params_wd_writes_both_wdl_and_wdr():
    base = {"stiffness": 0.2, "damping": 0.08, "wdl": 0.0, "wdr": 0.0,
            "gravity_z": 0.0, "limit_angle": 0, "radius": 6}
    result = m.apply_raw_sway_params(base, {"wd": 0.7})
    assert result["wdl"] == 0.7
    assert result["wdr"] == 0.7


@pytest.mark.parametrize("hardness_key", ["yawa", "futsuu", "kata"])
def test_params_for_default_raw_override_matches_pre_feature_output(hardness_key):
    """④既定値不変: raw_override省略/None/空dictのいずれも同一出力。
    dev#1508最終仕様でfamily引数は廃止済み(params_forはhardness_keyのみ)。"""
    expected = m.params_for(hardness_key)
    assert m.params_for(hardness_key, raw_override=None) == expected
    assert m.params_for(hardness_key, raw_override={}) == expected


def test_params_for_nonempty_raw_override_diverges_from_default():
    """負の対照: 有効なraw_overrideでは既定出力と一致しない。"""
    default = m.params_for("futsuu")
    overridden = m.params_for("futsuu", raw_override={"stiffness": 0.99})
    assert overridden != default
    assert overridden["stiffness"] == 0.99

    overridden2 = m.params_for("futsuu", raw_override={"damping": 0.01})
    assert overridden2 != default
    assert overridden2["damping"] == 0.01


def test_build_spec_nodes_default_raw_params_matches_pre_feature_output():
    """④既定値不変(単体レベル): raw_params省略/None/空dictはいずれも
    このパラメータ追加前と同一構造を返す。"""
    baseline = m.build_spec_nodes(["boneA", "HeadEquip062_ear_01_l"], "kata")
    omitted = m.build_spec_nodes(["boneA", "HeadEquip062_ear_01_l"], "kata", raw_params=None)
    empty = m.build_spec_nodes(["boneA", "HeadEquip062_ear_01_l"], "kata", raw_params={})
    assert omitted == baseline
    assert empty == baseline


def test_build_spec_nodes_raw_params_only_affects_matching_family():
    """負の対照: raw_paramsに"tail"だけ指定した場合、耳ノードは無変更、
    尻尾ノードだけ変わる。"""
    root_bones = ["F_Kigurumi001_tail_01", "HeadEquip062_ear_01_l"]
    baseline = m.build_spec_nodes(root_bones, "kata")
    raw_params = {"tail": {"stiffness": 0.77}}
    overridden = m.build_spec_nodes(root_bones, "kata", raw_params=raw_params)

    by_bone_base = {n["root_bone"]: n for n in baseline}
    by_bone_over = {n["root_bone"]: n for n in overridden}

    assert overridden != baseline
    assert by_bone_over["F_Kigurumi001_tail_01"]["params"]["stiffness"] == 0.77
    assert by_bone_over["F_Kigurumi001_tail_01"] != by_bone_base["F_Kigurumi001_tail_01"]
    # 耳ノードは影響を受けない(paramsもcurvesも不変)。
    assert by_bone_over["HeadEquip062_ear_01_l"] == by_bone_base["HeadEquip062_ear_01_l"]


def test_sway_abp_pak_entries_default_job_matches_no_raw_sway_params_key(tmp_path):
    """④受入の柱(実テンプレ経由・バイト完全一致): job["lab_raw_sway_params"]
    キー不在と、キーはあるが空dict/不正値のケースが、キー自体を最初から
    知らない旧来のjobと完全一致するuexpバイト列を生成することを確認する。"""
    manifest = m.load_template_manifest()
    assert manifest, "テンプレが同梱されていない(実測環境前提のテスト)"

    jobs = [
        {"sway_intensity": "hard"},
        {"sway_intensity": "hard", "lab_raw_sway_params": {}},
        {"sway_intensity": "hard", "lab_raw_sway_params": None},
        {"sway_intensity": "hard", "lab_raw_sway_params": {"tail": {}}},
    ]
    baseline_entries = None
    baseline_bytes = None
    for i, job in enumerate(jobs):
        out_dir = tmp_path / f"case{i}"
        entries = m.sway_abp_pak_entries(job, str(out_dir))
        assert len(entries) == 2 * len(manifest)
        byte_map = {}
        for abs_path, rel in sorted(entries):
            with open(abs_path, "rb") as f:
                byte_map[rel] = f.read()
        if baseline_entries is None:
            baseline_entries = sorted(entries)
            baseline_bytes = byte_map
        else:
            for rel, data in byte_map.items():
                assert baseline_bytes[rel] == data, f"case{i}: {rel} のバイトが既定と不一致"


def test_sway_abp_pak_entries_nonempty_raw_sway_params_changes_bytes(tmp_path):
    """負の対照: 有効なlab_raw_sway_paramsを渡すと、既定(キー不在)と異なる
    uexpバイト列が生成されること(実テンプレ経由で「効いている」ことの直接
    検証、CLAUDE.md「実装したと効いているは別」の精神)。"""
    manifest = m.load_template_manifest()
    assert manifest

    out_default = tmp_path / "default"
    out_raw = tmp_path / "raw"
    entries_default = m.sway_abp_pak_entries({"sway_intensity": "hard"}, str(out_default))
    entries_raw = m.sway_abp_pak_entries(
        {"sway_intensity": "hard", "lab_raw_sway_params": {
            "tail": {"stiffness": 0.9, "damping": 0.9, "wd": 0.9,
                      "gravity_z": -50.0, "limit_angle": 90.0},
            "ear": {"stiffness": 0.05, "damping": 0.05, "wd": 0.05,
                    "gravity_z": -20.0, "limit_angle": 10.0},
        }},
        str(out_raw))
    assert len(entries_default) == len(entries_raw) == 2 * len(manifest)

    diffs = 0
    for (abs_a, rel_a), (abs_b, rel_b) in zip(sorted(entries_default), sorted(entries_raw)):
        assert rel_a == rel_b
        with open(abs_a, "rb") as fa, open(abs_b, "rb") as fb:
            data_a, data_b = fa.read(), fb.read()
        if rel_a.endswith(".uexp"):
            if data_a != data_b:
                diffs += 1
    assert diffs > 0, "raw sway paramsを与えてもuexpバイトが一切変化しなかった"


def test_sway_abp_pak_entries_real_smoke_raw_override_readback(tmp_path):
    """実テンプレへ実際にraw_override付きでパッチをかけ、読み戻し値が
    渡した生パラメータと一致することを確認する(値を合わせるのではなく、
    実際に効いていることの直接検証)。"""
    manifest = m.load_template_manifest()
    job = {"sway_intensity": "hard", "lab_raw_sway_params": {
        "tail": {"stiffness": 0.42, "damping": 0.33, "wd": 0.61,
                  "gravity_z": -12.0, "limit_angle": 77.0},
        "ear": {"stiffness": 0.11, "damping": 0.22, "wd": 0.33,
                "gravity_z": -5.0, "limit_angle": 33.0},
    }}
    entries = m.sway_abp_pak_entries(job, str(tmp_path))
    assert len(entries) == 2 * len(manifest)

    t0 = manifest[0]
    uasset_out = os.path.join(str(tmp_path), t0["uasset_name"])
    uexp_out = os.path.join(str(tmp_path), t0["uexp_name"])
    names = vp_core.read_names(uasset_out)
    with open(uexp_out, "rb") as f:
        patched_uexp = f.read()
    spec_nodes_for_read = [{"root_bone": rb} for rb in t0["root_bones"]]
    values = sway_abp_patcher.read_kawaii_physics_node_values(
        patched_uexp, names, spec_nodes_for_read)

    ears_seen = 0
    tails_seen = 0
    for v in values:
        family = m.chain_family_for(v["root_bone"])
        if family == "ear":
            ears_seen += 1
            assert v["params"]["stiffness"] == pytest.approx(0.11)
            assert v["params"]["damping"] == pytest.approx(0.22)
            assert v["params"]["wdl"] == pytest.approx(0.33)
            assert v["params"]["wdr"] == pytest.approx(0.33)
            assert v["params"]["gravity_z"] == pytest.approx(-5.0)
            assert v["params"]["limit_angle"] == pytest.approx(33.0)
        else:
            tails_seen += 1
            assert v["params"]["stiffness"] == pytest.approx(0.42)
            assert v["params"]["damping"] == pytest.approx(0.33)
            assert v["params"]["wdl"] == pytest.approx(0.61)
            assert v["params"]["wdr"] == pytest.approx(0.61)
            assert v["params"]["gravity_z"] == pytest.approx(-12.0)
            assert v["params"]["limit_angle"] == pytest.approx(77.0)
    assert ears_seen > 0 and tails_seen > 0
