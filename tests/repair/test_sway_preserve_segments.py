"""Opt-in segment preservation must reach the production donor planner."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "py"))
import sway_allocator as allocator
import sway_hub as hub
import sway_hub_wire as wire


def entry(anchor, count):
    return {"anchor": anchor, "chains": [[f"{anchor}.{i:03d}" for i in range(1, count + 1)]],
            "params": {"limit_type": "None", "pull": .36, "spring": .1}}


def environment(free_count=35, *, second_native=False):
    definitions = [("root", -1), ("pelvis", 0), ("early_free", 0), ("hub_tail", 1)]
    for i in range(1, 6):
        definitions.append((f"native{i}", len(definitions)-1))
    definitions.append(("hub_hair", 1))
    if second_native:
        for i in range(1, 4):
            definitions.append((f"other_native{i}", len(definitions)-1))
    definitions += [("protected", 0), ("animated", 0), ("reserved", 0)]
    definitions += [(f"free{i:02d}", 0) for i in range(free_count)]
    bones = [{"name": n, "parent_idx": p, "quat": [0, 0, 0, 1],
              "pos": [1, 0, 0], "scale": [1, 1, 1]} for n, p in definitions]
    catalog = hub.SkeletonCatalog.from_bones_list(bones)
    slots = hub.HubSlots(female=("hub_tail", "hub_hair"), male=("hub_tail", "hub_hair"))
    reserved = hub.reserved_descendants_of(slots.female, bones) | {"reserved"}
    return catalog, slots, reserved


def plan(rows, env, **kwargs):
    allocation = allocator.allocate({"physbones": rows})
    return hub.plan_hub_wiring(allocation, *env, protected=frozenset({"pelvis", "protected"}),
                               known_moving=frozenset({"animated"}), default_safety_margin=1,
                               **kwargs)


def test_long_source_retains_each_main_joint_and_real_unweighted_terminal():
    rows = [entry("tail", 18)]
    env = environment()
    old = plan(rows, env)
    current = plan(rows, env, preserve_chain_anchors=frozenset({"tail"}))
    old_map = wire.source_to_donor_bone_map(old, "Female")
    new_map = wire.source_to_donor_bone_map(current, "Female")
    main = [f"tail.{i:03d}" for i in range(1, 14)]
    assert len({old_map[n] for n in main}) == 3, "reproduce the reported main-tail collapse"
    assert len({new_map[n] for n in main}) == 13
    cp = current.group_plans[0].chain_plans[0]
    assert cp.source_chain == ("tail", *rows[0]["chains"][0])
    assert cp.donor_chain_female[:5] == tuple(f"native{i}" for i in range(1, 6))
    assert cp.donor_chain_female[-1] not in new_map.values()
    assert len(cp.donor_chain_female) == len(cp.source_chain)
    assert new_map == wire.source_to_donor_bone_map(current, "Male")
    assert not (set(cp.donor_chain_female) & {"early_free", "protected", "animated", "reserved"})
    indices = [env[0].index_of(n) for n in ("hub_tail",) + cp.donor_chain_female]
    assert indices == sorted(set(indices))
    refskel = hub.refskel_dict_for_wiring(current, "Female")
    parent = "hub_tail"
    for donor in cp.donor_chain_female:
        assert refskel[donor]["parent"] == parent
        parent = donor


def test_opt_in_does_not_steal_baseline_free_donors_from_other_components():
    rows = [entry("tail", 18), entry("Hair", 3)]
    env = environment()
    old = plan(rows, env)
    current = plan(rows, env, preserve_chain_anchors=frozenset({"tail"}))
    old_map = wire.source_to_donor_bone_map(old, "Female")
    new_map = wire.source_to_donor_bone_map(current, "Female")
    assert {n: v for n, v in old_map.items() if n.startswith("Hair")} == {
        n: v for n, v in new_map.items() if n.startswith("Hair")}
    tail_cp = current.group_plans[0].chain_plans[0]
    other_cp = current.group_plans[1].chain_plans[0]
    assert not (set(tail_cp.donor_chain_female) & set(other_cp.donor_chain_female))


def test_default_and_unknown_anchor_keep_the_existing_plan_identical():
    rows = [entry("tail", 18), entry("Hair", 3)]
    env = environment()
    old = plan(rows, env)
    assert plan(rows, env, preserve_chain_anchors=frozenset()) == old
    assert plan(rows, env, preserve_chain_anchors=frozenset({"missing"})) == old


def test_insufficient_free_inventory_rejects_whole_group_without_starving_other_group():
    rows = [entry("tail", 18), entry("Hair", 3)]
    env = environment(free_count=5)
    old = plan(rows, env)
    result = plan(rows, env, preserve_chain_anchors=frozenset({"tail"}))
    assert [gp.group.anchor for gp in result.group_plans] == ["Hair"]
    assert len(result.unassignable) == 1
    assert "preserve" in result.unassignable[0][1].lower()
    assert wire.source_to_donor_bone_map(result, "Female") == {
        n: v for n, v in wire.source_to_donor_bone_map(old, "Female").items() if n.startswith("Hair")}


def test_two_preserved_groups_have_exclusive_added_donors():
    rows = [entry("tail", 18), entry("Hair", 12)]
    result = plan(rows, environment(second_native=True), preserve_chain_anchors=frozenset({"tail", "Hair"}))
    assert len(result.group_plans) == 2
    used = [n for gp in result.group_plans for cp in gp.chain_plans for n in cp.donor_chain_female]
    assert len(used) == len(set(used))
    mapping = wire.source_to_donor_bone_map(result, "Female")
    assert len({mapping[n] for n in rows[1]["chains"][0]}) == 12


@pytest.mark.parametrize("margin", [0, 1, 3])
def test_margin_reserves_terminal_bones_without_merging_requested_source(margin):
    rows = [entry("tail", 18)]
    source = ("tail", *rows[0]["chains"][0])
    result = plan(rows, environment(), preserve_chain_anchors=frozenset({"tail"}),
                  safety_margin_by_chain={source: margin})
    cp = result.group_plans[0].chain_plans[0]
    assert cp.source_chain == source
    assert len(cp.donor_chain_female) + 1 - len(source) == max(1, margin)


def test_preserving_chain_that_already_fits_keeps_existing_plan():
    rows = [entry("tail", 3)]
    env = environment()
    assert plan(rows, env, preserve_chain_anchors=frozenset({"tail"})) == plan(rows, env)


def test_unsupported_leaf_hub_is_reported_without_partial_assignment():
    rows = [entry("tail", 18), entry("Hair", 3)]
    env = environment()
    old = plan(rows, env)
    result = plan(rows, env, preserve_chain_anchors=frozenset({"Hair"}))
    assert result.group_plans == old.group_plans[:1]
    assert len(result.unassignable) == 1
    assert result.unassignable[0][0].anchor == "Hair"
    assert "unsupported" in result.unassignable[0][1]


def test_rejected_leaf_opt_in_keeps_later_component_donor_identity():
    rows = [entry("tail", 18), entry("Hair", 3), entry("Ribbon", 2)]
    catalog, _, reserved = environment()
    slots = hub.HubSlots(female=("hub_tail", "hub_hair", "reserved"),
                         male=("hub_tail", "hub_hair", "reserved"))
    env = catalog, slots, reserved
    old = plan(rows, env)
    result = plan(rows, env, preserve_chain_anchors=frozenset({"Hair"}))
    assert len(result.unassignable) == 1
    old_map = wire.source_to_donor_bone_map(old, "Female")
    new_map = wire.source_to_donor_bone_map(result, "Female")
    assert {n: v for n, v in old_map.items() if n.startswith("Ribbon")} == {
        n: v for n, v in new_map.items() if n.startswith("Ribbon")}


def test_preservation_keeps_tuft_branch_weights_and_only_preserves_representative():
    rows = [entry("tail", 18)]
    rows[0]["chains"].append(["tail.001", "tail.002", "branch.001", "branch.002"])
    result = plan(rows, environment(), preserve_chain_anchors=frozenset({"tail"}))
    mapping = wire.source_to_donor_bone_map(result, "Female")
    assert len({mapping[n] for n in rows[0]["chains"][0]}) == 18
    assert mapping["branch.001"] == mapping["tail.003"]
    assert mapping["branch.002"] == mapping["tail.004"]


def test_high_level_wire_passes_opt_in_to_production_planner(monkeypatch):
    catalog, slots, _ = environment()
    monkeypatch.setattr(hub, "discover_hub_slots", lambda *args: slots)
    monkeypatch.setattr(hub, "all_kp_node_root_names", lambda *args: slots.female)
    result = wire.wire_and_diagnose_hub(
        physbone_entries=[entry("tail", 18)], gender="Female", catalog=catalog,
        common_bones=frozenset({"pelvis", "protected"}), known_moving=frozenset({"animated"}),
        amplitude_rank={}, default_safety_margin=1, preserve_chain_anchors=frozenset({"tail"}))
    assert len(result.wiring.group_plans[0].chain_plans[0].source_chain) == 19


def test_parse_preserve_segments_ignores_disabled_and_malformed_overrides():
    assert wire.preserve_chain_anchors_from_overrides([
        {"bones": ["tail", "A"], "preserve_segments": True},
        {"bones": ["tail", "B"], "preserve_segments": True},
        {"bones": ["off"], "preserve_segments": True, "enabled": False},
        {"bones": ["false"], "preserve_segments": False},
        {"bones": ["number"], "preserve_segments": 1},
        {"bones": ["string"], "preserve_segments": "true"},
        {"bones": [], "preserve_segments": True},
        {"bones": ["bad", 3], "preserve_segments": True},
        {"bones": ["", "A"], "preserve_segments": True},
        {"bones": ["blank", " "], "preserve_segments": True},
        {"bones": "tail", "preserve_segments": True},
        None, 1,
    ]) == frozenset({"tail"})
    for value in (None, {}, "tail", 1):
        assert wire.preserve_chain_anchors_from_overrides(value) == frozenset()


def test_auto_preserves_supported_component_and_keeps_unsupported_leaf_active():
    rows = [entry("tail", 18), entry("Hair", 3)]
    env = environment()
    baseline = plan(rows, env)
    result = plan(rows, env, auto_preserve_segments=True)
    assert len(result.group_plans) == len(baseline.group_plans) == 2
    assert result.unassignable == baseline.unassignable
    assert result.group_plans[1] == baseline.group_plans[1]
    assert len(result.group_plans[0].chain_plans[0].source_chain) == 19
    assert any("kept baseline wiring" in e and "Hair" in e for e in result.chain_fit_events)


def test_auto_short_inventory_keeps_baseline_instead_of_deleting_physics():
    rows = [entry("tail", 18), entry("Hair", 3)]
    env = environment(free_count=5)
    baseline = plan(rows, env)
    result = plan(rows, env, auto_preserve_segments=True)
    assert result.group_plans == baseline.group_plans
    assert result.unassignable == baseline.unassignable
    assert any("free donor pool exhausted" in e for e in result.chain_fit_events)


def test_auto_two_supported_components_use_disjoint_donors():
    result = plan([entry("tail", 18), entry("Hair", 12)], environment(second_native=True),
                  auto_preserve_segments=True)
    assert len(result.group_plans) == 2
    donors = [n for g in result.group_plans for cp in g.chain_plans for n in cp.donor_chain_female]
    assert len(donors) == len(set(donors))
    manifest = wire.source_adaptation_manifest(result, "Female")
    assert manifest["active_physbone_anchors"] == ["Hair", "tail"]
    assert manifest["preserved_physbone_anchors"] == ["Hair", "tail"]
    tail = next(r for r in manifest["components"] if r["anchor"] == "tail")
    assert tail["representative_source_joints"] == tail["independent_mapped_joints"] == 19
    assert tail["unweighted_terminal_bones"] == 1


def test_auto_bivariant_falls_back_and_does_not_enable_disabled_component():
    catalog, _, reserved = environment(free_count=50)
    slots = hub.HubSlots(female=("hub_tail",), male=("hub_hair",))
    allocation = allocator.allocate({"physbones": [entry("tail", 18), entry("off", 2)]},
        lab_assignments={"pb:off#1": allocator.LabAssignment(style="", enabled=False)})
    baseline = hub.plan_hub_wiring(allocation, catalog, slots, reserved)
    result = hub.plan_hub_wiring(allocation, catalog, slots, reserved, auto_preserve_segments=True)
    assert result.group_plans == baseline.group_plans
    manifest = wire.source_adaptation_manifest(result, "Male")
    assert manifest["active_physbone_anchors"] == ["tail"]
    assert "unsupported" in manifest["planner_diagnostics"][0]


def test_wire_auto_flag_reaches_production_planner(monkeypatch):
    catalog, slots, _ = environment()
    monkeypatch.setattr(hub, "discover_hub_slots", lambda *args: slots)
    monkeypatch.setattr(hub, "all_kp_node_root_names", lambda *args: slots.female)
    result = wire.wire_and_diagnose_hub(physbone_entries=[entry("tail", 18)],
        gender="Female", catalog=catalog, common_bones=frozenset({"pelvis"}),
        known_moving=frozenset({"animated"}), amplitude_rank={}, default_safety_margin=1,
        auto_preserve_segments=True)
    assert len(result.wiring.group_plans[0].chain_plans[0].source_chain) == 19
