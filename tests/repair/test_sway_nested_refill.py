"""Automatic allocation fills safe slots before the donor inventory is built."""
import ast
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "py"))
import sway_allocator as allocator
import sway_chain_defaults
import sway_coverage
import sway_hub_wire
import sway_source_bones
from test_sway_nested_follow_parent import entry, entries


def full_inventory():
    return [entry("Base", ("A", "Branch", "B", "C", "D", "End")),
            entry("Branch", ("B", "C", "D", "End"))] + [
                entry(f"Cloth{i:02}", (f"Cloth{i:02}_a", f"Cloth{i:02}_b"))
                for i in range(8)]


def test_refill_is_opt_in_and_uses_the_next_independent_candidate():
    rows = entries() + [entry("Small", ("TipA",))]
    legacy = allocator.allocate({"physbones": rows}, capacity=2)
    auto = allocator.allocate({"physbones": rows}, capacity=2, refill_nested=True)
    assert [g.anchor for g in legacy.accepted] == ["Base"]
    assert [g.anchor for g in auto.accepted] == ["Base", "Small"]
    assert auto.all_units[1].nested_parent_key == "pb:Base#0"


def test_auto_compacts_multiple_levels_and_accounts_for_followers_beyond_cutoff():
    rows = entries() + [entry("Tip", ("End",)), entry("Small", ("S",))]
    plan = allocator.allocate({"physbones": rows}, capacity=2, refill_nested=True)
    assert [g.anchor for g in plan.accepted] == ["Base", "Small"]
    assert {u.nested_parent_key for u in plan.all_units[1:3]} == {"pb:Base#0"}
    # Even when no independent slot is free, a child already covered by the
    # selected parent needs no extra simulator and is accounted as following.
    one = allocator.allocate({"physbones": rows}, capacity=1, refill_nested=True)
    assert one.all_units[1].nested_parent_key == "pb:Base#0"
    assert "容量超過" in one.all_units[3].excluded_reason


def test_unselected_parent_never_suppresses_a_higher_priority_child():
    # Child gets tail priority, while the parent is generic by construction.
    rows = [entry("Base", ("A", "B", "C", "D")), entry("C", ("D",))]
    original = allocator._is_tail_component
    try:
        allocator._is_tail_component = lambda anchor, chains: anchor == "C"
        plan = allocator.allocate({"physbones": rows}, capacity=1, refill_nested=True)
    finally:
        allocator._is_tail_component = original
    assert [g.anchor for g in plan.accepted] == ["C"]
    assert plan.all_units[1].nested_parent_key is None
    assert "容量超過" in plan.all_units[0].excluded_reason


def test_refill_keeps_explicit_off_unsupported_and_explicit_style():
    rows = entries() + [entry("Off", ("O",)), entry("Unsupported", ("U",), limit="Hinge"),
                        entry("Small", ("S",))]
    overrides = {"pb:Off#2": allocator.LabAssignment("", enabled=False),
                 "pb:Small#4": allocator.LabAssignment("yawa", enabled=True)}
    plan = allocator.allocate({"physbones": rows}, capacity=2, refill_nested=True,
                              lab_assignments=overrides)
    assert [g.anchor for g in plan.accepted] == ["Base", "Small"]
    assert plan.accepted[-1].style == "yawa"
    assert "OFF" in plan.all_units[2].excluded_reason
    assert plan.all_units[3].is_biased and plan.all_units[3].excluded_reason


def test_same_anchor_different_parameters_are_not_merged_during_refill():
    rows = entries() + [entry("Root", ("R",)), entry("Root", ("R",))]
    rows[2]["params"]["pull"] = .1
    rows[3]["params"]["pull"] = .8
    plan = allocator.allocate({"physbones": rows}, capacity=3, refill_nested=True)
    assert [g.units[0].key for g in plan.accepted] == ["pb:Base#0", "pb:Root#2", "pb:Root#3"]
    assert all(u.nested_parent_key is None for u in plan.all_units[2:])


@pytest.mark.parametrize("field", ["enabled", "active_in_hierarchy"])
def test_source_disabled_component_stays_disabled_after_weight_filter_and_force_on(field):
    rows = [dict(entry("Disabled", ("D",)), **{field: False}), entry("Live", ("L",))]
    filtered = sway_hub_wire.filter_entries_by_weighted_bones(rows, frozenset({"D", "L"}))
    assert filtered[0][field] is False
    plan = allocator.allocate({"physbones": filtered}, refill_nested=True,
        lab_assignments={"pb:Disabled#0": allocator.LabAssignment("yawa", enabled=True)})
    assert [g.anchor for g in plan.accepted] == ["Live"]
    assert plan.all_units[0].source_disabled_reason
    report = sway_coverage.build_coverage_report(
        physbone_entries=rows, springbone_entries=[], filtered_physbone_entries=filtered,
        filtered_springbone_entries=[], initial_assignments={},
        wiring=SimpleNamespace(group_plans=[]), exclusions=[], gender="Female")
    assert report["components"][0]["status"] == "source_disabled"
    import sway_report
    rendered = sway_report.render_chinese(sway_report.summarize({"female": report}, {}))
    assert "源组件已关闭" in rendered and "Unity" in rendered


@pytest.mark.parametrize("value", [None, 0, "false", True])
def test_only_explicit_boolean_false_disables_source_component(value):
    row = dict(entry("Live", ("L",)), enabled=value, active_in_hierarchy=value)
    assert allocator.allocate({"physbones": [row]}, refill_nested=True).accepted


def test_wire_and_coverage_use_the_same_automatic_selection():
    from test_sway_hub_wire import _real_template_catalog
    rows = full_inventory()
    catalog, _ = _real_template_catalog()
    result = sway_hub_wire.wire_and_diagnose_hub(
        physbone_entries=rows, gender="Female", catalog=catalog,
        common_bones=frozenset(), refill_nested=True)
    assert len(result.wiring.group_plans) == 9
    report = sway_coverage.build_coverage_report(
        physbone_entries=rows, springbone_entries=[], filtered_physbone_entries=rows,
        filtered_springbone_entries=[], initial_assignments={}, wiring=result.wiring,
        exclusions=[], gender="Female", job={"sway_enable": True, "sway_adaptation": "physbone-v1"})
    assert report["counts"] == {"active": 9, "nested_follow_parent": 1}
    assert report["refill_nested"] is True
    assert not any("are not filled" in note for note in report["limitations"])


def load_function(script, name, namespace):
    path = ROOT / "pipeline" / "blender" / script
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def test_import_snapshot_and_independent_source_gate_include_refilled_component(tmp_path):
    rows = full_inventory()
    path = tmp_path / "physbones.json"
    path.write_text(json.dumps({"physbones": rows}))
    ns = dict(json=json, os=os, sway_allocator=allocator, sway_chain_defaults=sway_chain_defaults,
              sway_source_bones=sway_source_bones)
    load_function("step01_import_vrm.py", "_load_json_or_none", ns)
    snapshot = load_function("step01_import_vrm.py", "compute_sway_source_bone_names", ns)
    gate = load_function("step02_retarget.py", "sway_gate_compute_source_bone_names", ns)
    job = {"sway_enable": True, "sway_adaptation": "physbone-v1", "physbones_json": str(path)}
    assert "Cloth07_b" in snapshot(job)
    assert "Cloth07_b" in gate(rows, [], refill_nested=True)[0]
    assert "Cloth07_b" not in snapshot({**job, "sway_adaptation": "legacy"})


@pytest.mark.parametrize("broken", [None, "first"])
def test_automatic_retry_preserves_initial_refill_but_never_promotes_unwired_overflow(tmp_path, broken):
    from test_sway_degrade_retry import Scenario
    rows = full_inventory() + [entry("ZZOverflow", ("Z",))]
    case = Scenario(tmp_path, entries=rows, automatic=True, broken=broken)
    assert len(case.plan.accepted) == 9
    assert case.plan.accepted[-1].anchor == "Cloth07"
    result = case.run()
    active = {u.key for gp in result[0].group_plans for u in gp.group.units}
    assert len(active) == (8 if broken else 9)
    assert "pb:Cloth07#9" in active, "refilled and wired component must survive retry"
    assert "pb:ZZOverflow#10" not in active
    assert result[5]["pb:ZZOverflow#10"].enabled is False
    assert result[5]["pb:Branch#1"].enabled is False
    # Both precheck and post-remap gate independently allocate their source
    # scope; they must agree with the already built donor inventory.
    assert case.final_gate()
    if broken:
        assert result[5]["pb:Base#0"].enabled is False
        assert "pb:Branch#1" not in active
