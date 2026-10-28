"""Nested PhysBones can override part of a parent chain's fitted group."""
from dataclasses import replace
from types import SimpleNamespace

from test_sway_merged_rest_direction import SOURCE
import sway_hub as hub
import sway_hub_wire as wire
import sway_source_gate as gate
import sway_degrade


def nested_case():
    fitted, expansion = hub.fit_chain_to_length(tuple(SOURCE), 2)
    parent = hub.ChainDonorPlan(fitted, ("parent_tip",), ("parent_tip",), expansion)
    # The child's explicit root/chain take ownership of the final two source
    # bones. The original parent geometry representative is therefore owned
    # by the child, but the parent still holds the first two merged weights.
    child = hub.ChainDonorPlan(("tail.003", "tail.004"),
                             ("child_tip",), ("child_tip",),
                             {"tail.003": "tail.003", "tail.004": "tail.004"})
    def group(root, cp):
        return SimpleNamespace(hub_root_female=root, hub_root_male=root,
                               chain_plans=(cp,))
    return hub.HubWiringPlan((group("parent_root", parent), group("child_root", child)), ())


def test_nested_components_have_disjoint_effective_weight_merge_groups():
    wiring = nested_case()
    assert hub.merged_weight_groups(wiring) == frozenset({
        frozenset({"tail.001", "tail.002"})})


def test_parent_representative_remains_checkable_after_child_owns_its_old_rep():
    wiring = nested_case()
    mapping = wire.source_to_donor_bone_map(wiring, "Female")
    reps = hub.representative_of_map(wiring)
    # Every owned source resolves to a representative on the SAME donor.
    assert all(mapping[source] == mapping[rep] for source, rep in reps.items())
    groups = hub.source_geometry_groups(wiring)
    parent_rep = reps["tail.001"]
    assert groups[parent_rep] == ("tail.001", "tail.002", "tail.003", "tail.004")
    assert groups["tail.004"] == ("tail.004",)


def run_source_gate(wiring, donor_weights):
    source_weights = {name: {"mesh": {"0": .1}} for name in SOURCE}
    donors = {
        "parent_root": SOURCE["tail.044"],
        "parent_tip": dict(SOURCE["tail.004"], pos=SOURCE["tail.001"]["pos"]),
        "child_root": SOURCE["tail.003"], "child_tip": SOURCE["tail.004"],
    }
    return gate.run_gate(
        tuple(SOURCE), wire.source_to_donor_bone_map(wiring, "Female"),
        SOURCE, source_weights, donors, donor_weights,
        merge_groups=hub.merged_weight_groups(wiring),
        representative_of=hub.representative_of_map(wiring),
        source_geometry_groups=hub.source_geometry_groups(wiring))


def test_final_weight_gate_does_not_count_child_weights_twice():
    wiring = nested_case()
    weights = {name: {"mesh": {"0": .1}} for name in
               ("parent_root", "child_root", "child_tip")}
    weights["parent_tip"] = {"mesh": {"0": .2}}
    report = run_source_gate(wiring, weights)
    assert report.ok, [(r.bone, r.reasons) for r in report.failed]
    assert all(not r.transform_warnings for r in report.results)
    # Incorrectly copying the two child weights to the parent must fail.
    weights["parent_tip"]["mesh"]["0"] = .4
    assert not run_source_gate(wiring, weights).ok


def test_unrelated_sources_accidentally_sharing_a_donor_still_fail_collision_gate():
    wiring = nested_case()
    child_group = wiring.group_plans[1]
    cp = child_group.chain_plans[0]
    child_group.chain_plans = (replace(
        cp, donor_chain_female=("parent_tip",), donor_chain_male=("parent_tip",)),)
    mapping = wire.source_to_donor_bone_map(wiring, "Female")
    collisions = sway_degrade.detect_weight_collisions(
        mapping, set(SOURCE), hub.merged_weight_groups(wiring))
    assert set(collisions) == {"parent_tip"}
    assert set(collisions["parent_tip"]) == {"tail.001", "tail.002", "tail.004"}


def test_override_order_matches_the_actual_mapper_and_groups_never_overlap():
    wiring = nested_case()
    wiring = replace(wiring, group_plans=tuple(reversed(wiring.group_plans)))
    mapping = wire.source_to_donor_bone_map(wiring, "Female")
    reps = hub.representative_of_map(wiring)
    assert all(mapping[source] == mapping[rep] for source, rep in reps.items())
    groups = hub.merged_weight_groups(wiring)
    assert groups == frozenset({frozenset(set(SOURCE) - {"tail.044"})})
    assert sum(len(group) for group in groups) == len(set().union(*groups))
