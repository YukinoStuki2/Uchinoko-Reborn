"""Nested source chains follow an enabled parent without a second simulator."""
from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "py"))
import sway_allocator as allocator
import sway_coverage


def entry(anchor, *chains, limit="None"):
    return {"anchor": anchor, "chains": [list(chain) for chain in chains],
            "params": {"limit_type": limit, "max_angle_x": 45, "max_angle_z": 45}}


def entries():
    return [entry("Base", ("Middle", "Branch", "Tip", "End")),
            entry("Branch", ("Tip", "End"))]


def test_selected_nested_chain_follows_parent_and_remains_accounted_for():
    plan = allocator.allocate({"physbones": entries()})
    assert [group.anchor for group in plan.accepted] == ["Base"]
    child = next(unit for unit in plan.all_units if unit.anchor == "Branch")
    assert child.nested_parent_key == "pb:Base#0"
    assert child in plan.rejected_units
    assert "follow parent" in child.excluded_reason
    assert child.chains == (("Tip", "End"),), "source definition must be retained"


def test_parent_disabled_leaves_child_independent():
    plan = allocator.allocate({"physbones": entries()}, lab_assignments={
        "pb:Base#0": allocator.LabAssignment("", enabled=False)})
    assert [group.anchor for group in plan.accepted] == ["Branch"]
    assert plan.accepted[0].units[0].nested_parent_key is None


def test_explicit_child_on_still_uses_compatible_follow_when_parent_is_selected():
    plan = allocator.allocate({"physbones": entries()}, lab_assignments={
        "pb:Branch#1": allocator.LabAssignment("futsuu", enabled=True)})
    child = next(unit for unit in plan.all_units if unit.anchor == "Branch")
    assert child.nested_parent_key == "pb:Base#0"
    assert child.lab_override
    assert child.style == "futsuu", "retain the setting for a later child-only conversion"


def test_explicit_child_off_is_not_reported_as_compatibility_follow():
    plan = allocator.allocate({"physbones": entries()}, lab_assignments={
        "pb:Branch#1": allocator.LabAssignment("", enabled=False)})
    child = next(unit for unit in plan.all_units if unit.anchor == "Branch")
    assert child.nested_parent_key is None
    assert "OFF" in child.excluded_reason


def test_unsupported_parent_does_not_suppress_supported_child():
    rows = entries()
    rows[0]["params"]["limit_type"] = "Hinge"
    plan = allocator.allocate({"physbones": rows})
    assert [group.anchor for group in plan.accepted] == ["Branch"]


def test_overlapping_but_not_contained_chains_remain_independent():
    rows = entries()
    rows[1]["chains"].append(["OtherTip"])
    plan = allocator.allocate({"physbones": rows})
    assert {group.anchor for group in plan.accepted} == {"Base", "Branch"}


def test_bone_name_set_alone_does_not_establish_nested_ancestry():
    rows = entries()
    rows[1]["chains"] = [["End", "Tip"]]
    plan = allocator.allocate({"physbones": rows})
    assert len(plan.accepted) == 2


def test_same_root_duplicate_components_are_not_treated_as_descendants():
    rows = [entry("Root", ("A", "B")), entry("Root", ("A",))]
    plan = allocator.allocate({"physbones": rows})
    assert len(plan.accepted) == 2


def test_multiple_nested_levels_all_follow_the_outermost_selected_parent():
    rows = entries() + [entry("Tip", ("End",))]
    plan = allocator.allocate({"physbones": rows})
    assert len(plan.accepted) == 1
    assert {unit.nested_parent_key for unit in plan.all_units[1:]} == {"pb:Base#0"}


def test_compacting_selected_children_does_not_promote_capacity_overflow():
    rows = entries() + [entry("Small", ("TipA",))]
    plan = allocator.allocate({"physbones": rows}, capacity=2)
    assert [group.anchor for group in plan.accepted] == ["Base"]
    overflow = next(unit for unit in plan.all_units if unit.anchor == "Small")
    assert "容量超過" in overflow.excluded_reason


def test_parent_outside_selected_capacity_does_not_suppress_child():
    # Existing tail priority can select a child ahead of a larger generic
    # parent; compaction must operate on accepted groups, not all candidates.
    rows = [entry("Base", ("A", "B", "C", "D")), entry("C", ("D",))]
    units = allocator.parse_physbones({"physbones": rows})
    from dataclasses import replace
    groups = allocator.build_groups([units[0], replace(units[1], is_tail=True)])
    groups.sort(key=allocator._group_priority_key)
    assert groups[0].anchor == "C"
    assert allocator._nested_followers(groups[:1]) == {}


def coverage(active):
    from test_sway_coverage import mock_group
    rows = entries()
    plan = allocator.allocate({"physbones": rows})
    groups = [mock_group(g) for g in plan.accepted] if active else []
    return sway_coverage.build_coverage_report(
        physbone_entries=rows, springbone_entries=[], filtered_physbone_entries=rows,
        filtered_springbone_entries=[], initial_assignments={},
        wiring=SimpleNamespace(group_plans=groups), exclusions=[], gender="Female")


def test_report_distinguishes_following_from_disabled_or_independent_physics():
    report = coverage(True)
    assert report["counts"] == {"active": 1, "nested_follow_parent": 1}
    child = report["components"][1]
    assert child["parent_unit_key"] == "pb:Base#0"
    assert child["independent_parameters_applied"] is False


def test_report_never_claims_a_child_moves_when_the_parent_did_not_survive():
    report = coverage(False)
    child = report["components"][1]
    assert child["status"] == "nested_parent_unavailable"
