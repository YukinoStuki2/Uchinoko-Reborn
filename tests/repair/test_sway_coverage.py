import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "py"))
import sway_allocator
import sway_chain_defaults
import sway_coverage
import sway_degrade
import sway_hub


def mock_group(group):
    chains = []
    key = group.units[0].key
    for index, unit in enumerate(group.units):
        representative, branches = sway_hub.select_tuft_representative(unit.chains)
        if not representative and not branches:
            continue
        source = (unit.anchor,) + representative
        donors = tuple(f"{key}_{index}_{i}" for i in range(len(source)))
        chains.append(sway_hub.ChainDonorPlan(source, donors, donors,
                                             {n: n for n in source}, source))
    return sway_hub.GroupHubPlan(group, "hub_" + key, "hub_" + key,
                                group.anchor, tuple(chains))


def entry(name, kind="None"):
    return {"anchor": name, "chains": [[name + "1", name + "2"]],
            "params": {"limit_type": kind, "max_angle_x": 45, "max_angle_z": 45}}


def test_report_accounts_for_default_rejection_and_final_gate_rejection():
    entries = [entry("Hair"), entry("Skirt", "Hinge"), entry("Tail")]
    overrides = sway_chain_defaults.lab_assignments_from_job({}, entries, [])
    plan = sway_allocator.allocate({"physbones": entries}, lab_assignments=overrides)
    groups = [mock_group(g) for g in plan.accepted if g.anchor == "Hair"]
    report = sway_coverage.build_coverage_report(
        physbone_entries=entries, springbone_entries=[], filtered_physbone_entries=entries,
        filtered_springbone_entries=[], initial_assignments=overrides,
        wiring=SimpleNamespace(group_plans=groups), gender="Female",
        exclusions=[sway_degrade.make_exclusion_entry("pb:Tail#2", "gate_transform", "posture mismatch")])
    assert report["total_components"] == 3
    assert report["active_components"] == 1
    assert report["counts"] == {"active": 1, "unsupported_limit": 1, "gate_transform": 1}


def test_report_retains_capacity_and_weightless_components():
    entries = [entry(f"Cloth{i:02}") for i in range(11)]
    filtered = [dict(e) for e in entries]
    filtered[-1]["chains"] = []
    overrides = sway_chain_defaults.lab_assignments_from_job({}, filtered, [])
    plan = sway_allocator.allocate({"physbones": filtered}, lab_assignments=overrides)
    report = sway_coverage.build_coverage_report(
        physbone_entries=entries, springbone_entries=[], filtered_physbone_entries=filtered,
        filtered_springbone_entries=[], initial_assignments=overrides,
        wiring=SimpleNamespace(group_plans=[mock_group(g) for g in plan.accepted]),
        gender="Male", exclusions=[])
    assert report["total_components"] == 11
    assert report["counts"] == {"active": 9, "capacity_overflow": 1, "no_weighted_chain": 1}


def test_explicit_disabled_hinge_is_distinct_from_default_unsupported_hinge():
    entries = [entry("Skipped", "Hinge"), entry("Unsupported", "Hinge")]
    job = {"sway_chain_overrides": [{"bones": ["Skipped", "Skipped1", "Skipped2"], "enabled": False}]}
    overrides = sway_chain_defaults.lab_assignments_from_job(job, entries, [])
    report = sway_coverage.build_coverage_report(
        physbone_entries=entries, springbone_entries=[], filtered_physbone_entries=entries,
        filtered_springbone_entries=[], initial_assignments=overrides,
        wiring=SimpleNamespace(group_plans=[]), gender="Female", exclusions=[], job=job)
    assert report["counts"] == {"disabled": 1, "unsupported_limit": 1}


def test_global_disable_report_cannot_retain_previous_component_status():
    report = sway_coverage.disabled_coverage_report("Female")
    assert report["globally_disabled"]
    assert report["active_components"] == 0
    assert report["counts"] == {} and report["components"] == []


def test_production_planner_segment_counts_and_readable_report():
    import sway_report
    from test_sway_preserve_segments import environment, plan
    rows = [{"anchor": "tail", "chains": [[f"tail.{i:03d}" for i in range(1, 19)],
                                            ["tail.001", "branch.001"]],
             "params": {"limit_type": "None"}}]
    job = {"sway_chain_overrides": [{"bones": ["tail"], "preserve_segments": True}]}
    for enabled, expected in ((False, 5), (True, 19)):
        wiring = plan(rows, environment(),
                      preserve_chain_anchors=frozenset({"tail"}) if enabled else frozenset())
        report = sway_coverage.build_coverage_report(
            physbone_entries=rows, springbone_entries=[], filtered_physbone_entries=rows,
            filtered_springbone_entries=[], initial_assignments={}, wiring=wiring,
            gender="Female", exclusions=[], job=job)
        row = report["components"][0]
        assert row["representative_source_joints"] == 19
        assert row["independent_mapped_joints"] == expected
        assert row["unweighted_terminal_bones"] == 1
        assert row["merged_secondary_branches"] == 1
        assert row["preserve_segments_requested"] is True
        assert row["preserve_segments_effective"] is enabled
        text = sway_report.render_chinese(sway_report.summarize({"female": report}, {}))
        assert f"19→{expected}" in text
        assert "另 1 个无权重末端骨" in text
        assert "其余 1 条分支仍合并" in text
        assert ("已请求并生效" if enabled else "已请求，但未生效") in text


def test_rejected_preservation_is_not_reported_as_effective():
    rows = [entry("Hair")]
    report = sway_coverage.build_coverage_report(
        physbone_entries=rows, springbone_entries=[], filtered_physbone_entries=rows,
        filtered_springbone_entries=[], initial_assignments={},
        wiring=SimpleNamespace(group_plans=[]), gender="Female", exclusions=[],
        job={"sway_chain_overrides": [{"bones": ["Hair"], "preserve_segments": True}]})
    row = report["components"][0]
    assert row["preserve_segments_requested"] is True
    assert row["preserve_segments_effective"] is False
    assert "representative_source_joints" not in row


def test_auto_report_distinguishes_preserved_and_fallback_components_without_toggles():
    import sway_report
    from test_sway_preserve_segments import environment, entry as long_entry, plan
    rows = [long_entry("tail", 18), long_entry("Hair", 3)]
    wiring = plan(rows, environment(), auto_preserve_segments=True)
    report = sway_coverage.build_coverage_report(
        physbone_entries=rows, springbone_entries=[], filtered_physbone_entries=rows,
        filtered_springbone_entries=[], initial_assignments={}, wiring=wiring,
        gender="Female", exclusions=[], job={"sway_adaptation": "physbone-v1", "sway_enable": True})
    tail, hair = report["components"]
    assert all(r["automatic_segments_requested"] and r["preserve_segments_requested"] for r in (tail, hair))
    assert tail["preserve_segments_effective"] is True
    assert hair["preserve_segments_effective"] is False
    assert tail["adaptation_mode"] == "physbone-v1"
    rendered = sway_report.render_chinese(sway_report.summarize({"female": report}, {}))
    assert "19→19" in rendered and "已请求并生效" in rendered and "已请求，但未生效" in rendered
