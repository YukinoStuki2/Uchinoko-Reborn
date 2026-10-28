"""Readable physics diagnostics must count source components, not genders."""
from pathlib import Path
import contextlib
import io
import json
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "py"))
import convert_noue
import sway_report

REASON = ("tail.004: posture mismatch (dev#1625): donor 'NPC_GrassBoss001_Skin001_tail_02' "
          "direction differs by 22.97 deg (exceeds cull threshold 16.5 deg)")


def fixture():
    # Recorded curved-chain example counts, using synthetic names for unrelated parts.
    rows = []
    for status, count in (("active", 8), ("capacity_overflow", 11),
                          ("unsupported_limit", 46), ("no_weighted_chain", 4)):
        for i in range(count):
            rows.append({"unit_key": f"pb:{status}_{i}#{len(rows)}", "anchor": f"{status}_{i}",
                         "source": "pb", "status": status, "reason": "source decision",
                         "limit_type": "Hinge" if status == "unsupported_limit" else "Angle"})
    tail = {"unit_key": "pb:tail.044#60", "source": "pb", "anchor": "tail.044",
            "status": "gate_transform", "reason": REASON}
    rows.append(tail)
    coverage = {"format": "uchinoko-reborn-sway-coverage-1", "gender": "female",
                "total_components": 70, "active_components": 8, "capacity": 9,
                "components": rows}
    exclusion = {"format": "divetopalworld-sway-exclusions-1", "total_units": 70,
                 "excluded": [{**tail, "stage": "gate_transform"}]}
    return coverage, exclusion


def write_inputs(tmp_path, coverage=None, exclusion=None):
    if coverage is None and exclusion is None:
        coverage, exclusion = fixture()
    for gender in ("female", "male"):
        if coverage is not None:
            (tmp_path / f"sway_coverage_{gender}.json").write_text(
                json.dumps({**coverage, "gender": gender}), encoding="utf-8")
        if exclusion is not None:
            (tmp_path / f"sway_exclusions_{gender}.json").write_text(
                json.dumps({**exclusion, "gender": gender}), encoding="utf-8")


def test_recorded_tail_deduplicated_and_full_reason_reaches_readable_report(tmp_path):
    write_inputs(tmp_path)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        convert_noue.warn_posture_mismatch_cull(str(tmp_path), ["Female", "Male"])
    lines = out.getvalue().splitlines()
    markers = [line for line in lines if line.startswith("##AVATAR_WARNING##")]
    assert len(markers) == 1
    data = json.loads(markers[0].split(sway_report.MARKER_PREFIX, 1)[1])
    assert data["counts"]["gate_transform"] == 1
    assert data["posture"][0]["genders"] == ["female", "male"]
    report = Path(data["report_path"]).read_text(encoding="utf-8")
    assert "tail.044" in report and "tail.004" in report
    assert "22.97°" in report and "16.5°" in report
    assert "8/70" in report and "未获独立节点" in report and "11" in report
    assert "特殊约束" in report and "46" in report and "无权重" in report
    assert "不会继续模拟" in report
    assert "共 1 个源部件" in report


def test_final_coverage_wins_over_earlier_capacity_exclusion():
    coverage, exclusions = fixture()
    no_weight = next(row for row in coverage["components"] if row["status"] == "no_weighted_chain")
    exclusions["excluded"].append({**no_weight, "stage": "capacity_overflow", "reason": "earlier allocation"})
    report = sway_report.summarize({"female": coverage}, {"female": exclusions})
    assert report["counts"]["no_weighted_chain"] == 4
    assert report["counts"]["capacity_overflow"] == 11


def test_distinct_source_units_with_same_anchor_are_not_merged():
    coverage, exclusions = fixture()
    tail = dict(coverage["components"][-1], unit_key="pb:tail.044#99")
    coverage["components"].append(tail)
    report = sway_report.summarize({"female": coverage, "male": coverage}, {})
    assert report["counts"]["gate_transform"] == 2


def test_different_gender_results_are_kept_separate():
    coverage, _ = fixture()
    male = json.loads(json.dumps(coverage))
    male["components"][-1].update(status="active", reason="passed")
    male["active_components"] = 9
    report = sway_report.summarize({"female": coverage, "male": male}, {})
    assert report["counts"]["gate_transform"] == 1
    assert report["posture"][0]["genders"] == ["female"]
    assert report["genders"]["male"]["active"] == 9


def test_disabled_and_unweighted_are_informational_not_safety_errors():
    coverage = {"components": [
        {"unit_key": "pb:off#0", "anchor": "off", "status": "disabled"},
        {"unit_key": "pb:none#1", "anchor": "none", "status": "no_weighted_chain"}],
        "total_components": 2, "active_components": 0, "capacity": 9}
    report = sway_report.summarize({"female": coverage}, {})
    assert report["safety_excluded_components"] == 0
    assert report["counts"] == {"disabled": 1, "no_weighted_chain": 1}


def test_legacy_exclusions_do_not_invent_active_total(tmp_path):
    _, exclusions = fixture()
    write_inputs(tmp_path, exclusion=exclusions)
    report = sway_report.write_report(tmp_path, ["female", "male"])
    assert report["counts"]["gate_transform"] == 1
    assert report["genders"]["female"]["active"] is None
    assert "未记录完整覆盖率" in Path(report["report_path"]).read_text(encoding="utf8")


def test_corrupt_coverage_is_reported_as_unknown_not_zero(tmp_path):
    (tmp_path / "sway_coverage_female.json").write_text("{broken", encoding="utf8")
    report = sway_report.write_report(tmp_path, ["female"])
    assert report["input_warnings"]
    assert report["genders"]["female"]["active"] is None
    assert "读取失败" in Path(report["report_path"]).read_text(encoding="utf8")


@pytest.mark.parametrize("field,value", [
    ("status", []), ("status", {}), ("placement_checks", None),
    ("placement_checks", [None]), ("anchor", {}), ("reason", [])])
def test_legal_json_with_invalid_row_fields_degrades_to_unknown(tmp_path, field, value):
    coverage, exclusions = fixture()
    coverage["components"][-1][field] = value
    write_inputs(tmp_path, coverage, exclusions)
    report = sway_report.write_report(tmp_path, ["female", "male"])
    assert report["input_warnings"]
    assert report["genders"]["female"]["active"] is None
    assert report["counts"]["unknown"] == 1
    assert "启用 0/0" not in Path(report["report_path"]).read_text(encoding="utf8")


@pytest.mark.parametrize("value", [-1, 8.5, True, "8", float("nan")])
def test_invalid_coverage_counts_do_not_claim_success(tmp_path, value):
    coverage, exclusions = fixture()
    coverage["active_components"] = value
    write_inputs(tmp_path, coverage, exclusions)
    report = sway_report.write_report(tmp_path, ["female"])
    assert report["genders"]["female"]["active"] is None
    assert report["input_warnings"]


def write_checks(tmp_path, gender="female", failed=False):
    source = {"ok": not failed, "checked": 68, "failed": []}
    if failed:
        source["failed"] = [{"bone": f"tail.{i:03}", "donor": "donor_tail",
                             "reasons": [f"weight mismatch {j}" for j in range(300)]}
                            for i in range(11)]
    (tmp_path / f"sway_source_gate_{gender}.json").write_text(json.dumps(source), encoding="utf8")
    (tmp_path / f"sway_pivot_axiom_{gender}.json").write_text(
        json.dumps({"ok": True, "checked": 9, "failed": []}), encoding="utf8")


def test_final_gate_failure_is_not_hidden_by_active_coverage_and_details_are_bounded(tmp_path):
    write_inputs(tmp_path)
    write_checks(tmp_path, failed=True)
    write_checks(tmp_path, "male")
    report = sway_report.write_report(tmp_path, ["female", "male"])
    assert report["genders"]["female"]["active"] == 8
    assert report["final_checks"]["female"]["status"] == "failed"
    assert report["final_checks"]["male"]["status"] == "passed"
    txt = Path(report["report_path"]).read_text(encoding="utf8")
    assert "未通过 11/68" in txt and "共 300 条原因" in txt
    assert "weight mismatch 2" in txt and "weight mismatch 299" not in txt
    assert "sway_source_gate_female.json" in txt


def test_missing_final_checks_and_missing_gender_are_unknown(tmp_path):
    coverage, _ = fixture()
    (tmp_path / "sway_coverage_female.json").write_text(json.dumps(coverage), encoding="utf8")
    report = sway_report.write_report(tmp_path, ["female", "male"])
    assert report["genders"]["male"]["active"] is None
    assert report["final_checks"]["female"]["status"] == "unknown"
    assert report["input_warnings"]


def test_legacy_nonposture_exclusions_still_warn_when_final_gate_fails(tmp_path):
    exclusions = {"total_units": 1, "excluded": [
        {"unit_key": "pb:tail#0", "anchor": "tail", "stage": "capacity_overflow"}]}
    write_inputs(tmp_path, exclusion=exclusions)
    write_checks(tmp_path, failed=True)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        convert_noue.warn_posture_mismatch_cull(tmp_path, ["female"])
    assert "##AVATAR_WARNING##" in out.getvalue()


def test_report_write_failure_does_not_fail_completed_conversion(tmp_path, monkeypatch):
    write_inputs(tmp_path)
    original = Path.write_text

    def refuse_reports(path, *args, **kwargs):
        if path.name in (sway_report.REPORT_FILENAME, sway_report.SUMMARY_FILENAME):
            raise PermissionError("test read-only destination")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", refuse_reports)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        convert_noue.warn_posture_mismatch_cull(tmp_path, ["female"])
    data = json.loads(out.getvalue().split(sway_report.MARKER_PREFIX, 1)[1])
    assert data["report_path"] is None
    assert len(data["report_write_errors"]) == 2
    assert "PermissionError" in out.getvalue()


def test_unexpected_reporting_error_does_not_fail_conversion(tmp_path, monkeypatch):
    def broken(*args):
        raise TypeError("invalid new schema")
    monkeypatch.setattr(sway_report, "write_report", broken)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        convert_noue.warn_posture_mismatch_cull(tmp_path, ["female"])
    data = json.loads(out.getvalue().split(sway_report.MARKER_PREFIX, 1)[1])
    assert data["genders"]["female"]["active"] is None
    assert data["report_write_errors"]


def load_gui_modules():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app_py"))
    import i18n
    import pipeline_runner
    from ui import main_window
    return i18n, pipeline_runner, main_window


def test_real_marker_reaches_translated_gui_completion_list_and_raw_log(tmp_path, monkeypatch):
    write_inputs(tmp_path)
    write_checks(tmp_path, failed=True)
    write_checks(tmp_path, "male")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        convert_noue.warn_posture_mismatch_cull(tmp_path, ["female", "male"])
    marker = next(line for line in out.getvalue().splitlines() if line.startswith("##AVATAR_WARNING##"))
    i18n, runner, window = load_gui_modules()
    monkeypatch.setattr(i18n, "current_lang", "zhCN")
    logged = []
    fake = SimpleNamespace(_pipeline_warnings=[], _log=logged.append)
    window.MainWindow._on_pipeline_line(fake, marker)
    assert logged == [marker]
    assert len(fake._pipeline_warnings) == 1
    notice = fake._pipeline_warnings[0]
    assert "SWAY_REPORT" not in notice
    assert "姿态排除 1 个源部件" in notice and "8/70" in notice
    assert "tail.044" in notice and "tail.004" in notice and "22.97°" in notice
    assert "女性 未通过" in notice and "男性 通过" in notice
    assert str(tmp_path / sway_report.REPORT_FILENAME) in notice
    translated = {runner.translate_avatar_warning(runner.parse_avatar_warning(marker), lang=lang)
                  for lang in ("zhCN", "zhTW", "en", "ja", "ko")}
    assert len(translated) == 5
    assert all("SWAY_REPORT" not in item for item in translated)


def test_gui_preserves_different_gender_measurements_and_malformed_fallback(tmp_path):
    coverage, exclusions = fixture()
    write_inputs(tmp_path, coverage, exclusions)
    male = json.loads(json.dumps(coverage))
    male["components"][-1]["reason"] = REASON.replace("22.97", "25.50")
    (tmp_path / "sway_coverage_male.json").write_text(json.dumps(male), encoding="utf8")
    _, runner, _ = load_gui_modules()
    notice = runner.translate_avatar_warning(sway_report.marker_payload(
        sway_report.write_report(tmp_path, ["female", "male"])), lang="zhCN")
    assert "女性; 骨 tail.004; 22.97°" in notice
    assert "男性; 骨 tail.004; 25.50°" in notice
    for malformed in ("SWAY_REPORT_V1 {", 'SWAY_REPORT_V1 {"genders":[],"counts":{}}'):
        assert runner.translate_avatar_warning(malformed, lang="zhCN") == malformed


def test_nested_components_follow_parent_without_claiming_independent_parameters(tmp_path):
    coverage = {"total_components": 2, "active_components": 1, "capacity": 9, "components": [
        {"unit_key": "pb:parent#0", "anchor": "tail_parent", "status": "active"},
        {"unit_key": "pb:child#1", "anchor": "tail_child", "status": "nested_follow_parent",
         "parent_unit_key": "pb:parent#0", "independent_parameters_applied": False}]}
    write_inputs(tmp_path, coverage=coverage)
    report = sway_report.write_report(tmp_path, ["female"])
    assert report["counts"] == {"active": 1, "nested_follow_parent": 1}
    txt = Path(report["report_path"]).read_text(encoding="utf8")
    assert "父组件：tail_parent" in txt and "子组件的独立参数未移植" in txt
    _, runner, _ = load_gui_modules()
    notice = runner.translate_avatar_warning(sway_report.marker_payload(report), lang="zhCN")
    assert "随父级动态" in notice and "子参数不单独生效" in notice
    assert "保持静态" not in notice


def test_duplicate_coverage_units_make_totals_unknown(tmp_path):
    row = {"unit_key": "pb:tail#0", "anchor": "tail", "status": "active"}
    write_inputs(tmp_path, coverage={"total_components": 2, "active_components": 2,
                                    "capacity": 9, "components": [row, row]})
    report = sway_report.write_report(tmp_path, ["female"])
    assert report["genders"]["female"]["active"] is None
    assert report["counts"] == {"unknown": 1}


def test_corrupt_final_check_outside_display_sample_is_unknown(tmp_path):
    write_inputs(tmp_path)
    write_checks(tmp_path, failed=True)
    path = tmp_path / "sway_source_gate_female.json"
    data = json.loads(path.read_text(encoding="utf8"))
    data["failed"][5]["reasons"] = None
    path.write_text(json.dumps(data), encoding="utf8")
    report = sway_report.write_report(tmp_path, ["female"])
    assert report["final_checks"]["female"]["status"] == "unknown"
    assert report["input_warnings"]


def test_empty_final_checks_do_not_claim_verified_physics(tmp_path):
    write_inputs(tmp_path)
    for kind in ("sway_source_gate", "sway_pivot_axiom"):
        (tmp_path / f"{kind}_female.json").write_text(
            json.dumps({"ok": True, "checked": 0, "failed": []}), encoding="utf8")
    report = sway_report.write_report(tmp_path, ["female"])
    assert report["final_checks"]["female"]["status"] == "unknown"


def automatic_manifest(gender="female"):
    channels = ("stiffness", "damping", "wdl", "wdr", "radius", "limit_angle")
    profile = {"parameter_mode": "physbone-v1", "params": {k: .2 for k in (*channels, "gravity_z")},
               "extended_curves": {k: [[0., .5], [1., 1.]] for k in channels}}
    row = {"unit_key": "pb:tail#0", "anchor": "tail", "target_root": "donor_tail",
           "representative_source_joints": 19, "independent_mapped_joints": 19,
           "unweighted_terminal_bones": 1, "merged_secondary_branches": 3, "preserved": True,
           "parameter_mode": "physbone-v1", "source_version": "Version_1_1", "integration_type": "Advanced",
           "gravity_fit": {"status": "fallback", "gravity_z": 0},
           "warnings": ["source PhysBone colliders are not yet reproduced by the cooked backend",
                        "Explicit Hinge approximation: directional limits and source colliders are not reproduced",
                        "source curve pull is unavailable; using its scalar value",
                        "response coefficients match at 60 Hz near rest; large rotations and other frame rates differ"]}
    return {"mode": "physbone-v1", "gender": gender, "components": [row],
            "node_overrides": {"donor_tail": {"source_profile": profile}}}


def test_auto_parameters_and_limits_are_readable_without_opening_json(tmp_path):
    write_inputs(tmp_path)
    manifest = automatic_manifest()
    (tmp_path / "sway_adaptation_female.json").write_text(json.dumps(manifest), encoding="utf8")
    report = sway_report.write_report(tmp_path, ["female"])
    assert report["source_adaptation"]["female"]["status"] == "recorded"
    text = Path(report["report_path"]).read_text(encoding="utf8")
    for expected in ("Unity PhysBone 自动参数转换", "19→19", "其余 3 条分支", "Version_1_1", "Advanced",
                     "碰撞器尚未移植", "Hinge 方向约束", "缺少 pull 源曲线", "60 Hz", "拟合未通过", "不是游戏内效果已验证"):
        assert expected in text
    assert "source PhysBone colliders are not" not in text
    assert "samples" not in report["source_adaptation"]["female"]["components"][0]


def test_auto_manifest_only_still_creates_report_with_unknown_coverage(tmp_path):
    (tmp_path / "sway_adaptation_female.json").write_text(json.dumps(automatic_manifest()), encoding="utf8")
    report = sway_report.write_report(tmp_path, ["female", "male"])
    assert report["genders"]["female"]["active"] is None
    assert report["source_adaptation"]["male"]["status"] == "unknown"
    assert "缺少该性别的自动转换记录" in Path(report["report_path"]).read_text(encoding="utf8")


@pytest.mark.parametrize("damage", ["json", "profile", "count", "warnings", "duplicate", "mode", "gravity"])
def test_malformed_automatic_metadata_never_claims_complete_success(tmp_path, damage):
    write_inputs(tmp_path)
    manifest = automatic_manifest()
    row = manifest["components"][0]
    if damage == "profile":
        manifest["node_overrides"]["donor_tail"]["source_profile"] = {}
    elif damage == "count":
        row["independent_mapped_joints"] = 5
    elif damage == "warnings":
        row["warnings"] = "not a list"
    elif damage == "duplicate":
        manifest["components"].append(dict(row))
    elif damage == "mode":
        row["parameter_mode"] = "unknown"
    elif damage == "gravity":
        row["gravity_fit"]["gravity_z"] = float("nan")
    path = tmp_path / "sway_adaptation_female.json"
    path.write_text("{bad" if damage == "json" else json.dumps(manifest), encoding="utf8")
    report = sway_report.write_report(tmp_path, ["female"])
    assert report["source_adaptation"]["female"]["status"] == "unknown"
    assert report["source_adaptation"]["female"]["components"] == []
    assert report["input_warnings"]
    text = Path(report["report_path"]).read_text(encoding="utf8")
    assert "自动参数状态未知" in text
    assert "完整保留代表主链关节" not in text


def test_manual_component_and_merged_chain_are_not_labelled_automatic_or_preserved(tmp_path):
    manifest = automatic_manifest()
    row = manifest["components"][0]
    row.update(parameter_mode="manual_override", independent_mapped_joints=6, preserved=False,
               warnings=["explicit component tuning takes precedence over automatic adaptation"])
    manifest["node_overrides"]["donor_tail"] = {"motion": {"profile": "calm"}}
    (tmp_path / "sway_adaptation_female.json").write_text(json.dumps(manifest), encoding="utf8")
    report = sway_report.write_report(tmp_path, ["female"])
    text = Path(report["report_path"]).read_text(encoding="utf8")
    assert "0 个使用自动参数，1 个使用手动参数" in text
    assert "19→6" in text and "不能宣称完整保留" in text
    assert "手动参数优先" in text


def test_absent_auto_manifest_leaves_legacy_report_unchanged(tmp_path):
    write_inputs(tmp_path)
    report = sway_report.write_report(tmp_path, ["female"])
    assert "source_adaptation" not in report
    assert "Unity PhysBone 自动参数转换" not in Path(report["report_path"]).read_text(encoding="utf8")
