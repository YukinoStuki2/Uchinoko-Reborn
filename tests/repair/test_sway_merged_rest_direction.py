"""Compare a fitted donor to its whole source span, not its final member.

The five source segments below are the minimal curved-chain example tail reproduction.
They retain only rest geometry; no meshes, textures or user paths are needed.
"""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from test_sway_degrade_retry import production_namespace
import sway_hub
import sway_hub_placement as placement
import sway_hub_wire
import sway_source_gate as gate


SOURCE = {
    "tail.044": {
        "pos": (9.389341162072606e-16, .023457420989871025, .8368863463401794),
        "tail": (.002452859887853265, .034719157963991165, .8361811637878418)},
    "tail.001": {
        "pos": (.00245285639539361, .03471914678812027, .8361812233924866),
        "tail": (-1.2367963542203597e-8, .09351417422294617, .8278310894966125)},
    "tail.002": {
        "pos": (1.9523636041185455e-9, .09351416677236557, .8278313279151917),
        "tail": (-2.329776149778695e-9, .1403060406446457, .7683429718017578)},
    "tail.003": {
        "pos": (-1.3024816780671244e-9, .14030584692955017, .7683428525924683),
        "tail": (-5.020396542931849e-9, .1658770889043808, .6988365054130554)},
    "tail.004": {
        "pos": (-8.101974202645579e-9, .16587711870670319, .6988365054130554),
        "tail": (-1.4725539898563511e-8, .18161547183990479, .6120253801345825)},
}
SOURCE = {name: dict(value, scale=(1, 1, 1)) for name, value in SOURCE.items()}


def fitted_case():
    source = dict(SOURCE)
    fitted, expansion = sway_hub.fit_chain_to_length(tuple(source), 2)
    cp = sway_hub.ChainDonorPlan(fitted, ("donor",), ("donor",), expansion)
    gp = SimpleNamespace(chain_plans=(cp,), hub_root_female="root_donor",
                         hub_root_male="root_donor")
    wiring = sway_hub.HubWiringPlan((gp,), ())
    dump = {n: {"head": t["pos"], "tail": t["tail"]} for n, t in source.items()}
    _, heads, tails, _ = placement.resolve_grouped_chain(
        dump, placement.Similarity(1, (0, 0, 0), (0, 0, 0)), cp,
        "tail.044", ("donor",))
    donors = {"root_donor": source["tail.044"],
              "donor": {"pos": heads[0], "tail": tails[0], "scale": (1, 1, 1)}}
    prep = SimpleNamespace(
        real_source_bone_names=set(source), source_transform_snapshot=source,
        donor_transform_snapshot=donors, source_weight_snapshot={},
        anchor_parent_of={}, axiom_baseline_pos={}, axiom_observed_pos={})
    return wiring, prep


def precheck(wiring, prep):
    ns = production_namespace()
    ns["_sway_gate_prepare"] = lambda *args, **kwargs: prep
    return ns["_sway_degrade_precheck"](
        {}, "Female", [], [], None, None, {}, wiring, 0, {}, {}, {})[1]


def test_real_curved_tail_is_not_disabled_when_donor_matches_fitted_span():
    wiring, prep = fitted_case()
    last = prep.source_transform_snapshot["tail.004"]
    donor = prep.donor_transform_snapshot["donor"]
    # This is the exact 22.97-degree warning from the reported conversion.
    assert gate.direction_mismatch_deg(last["pos"], last["tail"],
                                       donor["pos"], donor["tail"]) == pytest.approx(
                                           22.9679577769, abs=1e-6)
    assert precheck(wiring, prep) == {}


def test_wrongly_rotated_merged_donor_is_still_disabled():
    wiring, prep = fitted_case()
    donor = prep.donor_transform_snapshot["donor"]
    donor["tail"] = tuple(a + b for a, b in zip(donor["pos"], (1, 0, 0)))
    failures = precheck(wiring, prep)
    assert set(failures) == {"tail.004"}
    assert "posture mismatch" in failures["tail.004"][0]
    assert "threshold 16.5 deg" in failures["tail.004"][0]


def test_singleton_root_direction_is_still_checked():
    wiring, prep = fitted_case()
    original = prep.donor_transform_snapshot["root_donor"]
    prep.donor_transform_snapshot["root_donor"] = dict(
        original, tail=tuple(a + b for a, b in zip(original["pos"], (0, 0, 1))))
    assert set(precheck(wiring, prep)) == {"tail.044"}


def test_expected_geometry_never_uses_observed_donor_or_mutates_source():
    wiring, prep = fitted_case()
    original = deepcopy(prep.source_transform_snapshot)
    expected = gate.source_transforms_for_geometry_groups(
        prep.source_transform_snapshot, sway_hub.source_geometry_groups(wiring))
    assert expected["tail.004"]["pos"] == original["tail.001"]["pos"]
    assert expected["tail.004"]["tail"] == original["tail.004"]["tail"]
    assert expected["tail.044"] == original["tail.044"]
    assert prep.source_transform_snapshot == original


def test_missing_group_endpoint_keeps_conservative_original_check():
    wiring, prep = fitted_case()
    prep.source_transform_snapshot.pop("tail.001")
    prep.real_source_bone_names.remove("tail.001")
    assert set(precheck(wiring, prep)) == {"tail.004"}


def test_secondary_tuft_weight_branches_do_not_define_expected_geometry():
    wiring, prep = fitted_case()
    gp = wiring.group_plans[0]
    cp = gp.chain_plans[0]
    # A secondary branch is deliberately far from the representative branch.
    # It contributes weights, but must not change this donor's rest span.
    prep.source_transform_snapshot["side_branch"] = {
        "pos": (50, 60, 70), "tail": (100, 80, 90), "scale": (1, 1, 1)}
    prep.real_source_bone_names.add("side_branch")
    cp = replace(cp, weight_expansion=dict(cp.weight_expansion, side_branch="tail.004"),
                 representative_source=tuple(SOURCE))
    gp.chain_plans = (cp,)
    groups = sway_hub.source_geometry_groups(wiring)
    assert groups["tail.004"] == ("tail.001", "tail.002", "tail.003", "tail.004")
    assert precheck(wiring, prep) == {}


def final_gate(wiring, prep, source_weights=None, donor_weights=None):
    return gate.run_gate(
        sorted(prep.real_source_bone_names),
        sway_hub_wire.source_to_donor_bone_map(wiring, "Female"),
        prep.source_transform_snapshot, source_weights or {},
        prep.donor_transform_snapshot, donor_weights or {},
        merge_groups=sway_hub.merged_weight_groups(wiring),
        representative_of=sway_hub.representative_of_map(wiring),
        source_geometry_groups=sway_hub.source_geometry_groups(wiring))


def test_final_source_gate_uses_fitted_span_and_keeps_weight_validation():
    wiring, prep = fitted_case()
    source_weights = {"tail.001": {"mesh": {"0": .4}},
                      "tail.004": {"mesh": {"0": .6}}}
    donor_weights = {"donor": {"mesh": {"0": 1}}}
    report = final_gate(wiring, prep, source_weights, donor_weights)
    assert report.ok
    assert all(not result.transform_warnings for result in report.results)
    donor_weights["donor"]["mesh"]["0"] = .5
    report = final_gate(wiring, prep, source_weights, donor_weights)
    assert not report.ok, "bad merged weights must still fail the source gate"


def test_final_gate_still_reports_misplaced_donor():
    wiring, prep = fitted_case()
    donor = prep.donor_transform_snapshot["donor"]
    donor["pos"] = tuple(v + 1 for v in donor["pos"])
    report = final_gate(wiring, prep)
    result = next(r for r in report.results if r.bone == "tail.004")
    assert any("position mismatch" in item for item in result.transform_warnings)
    assert any("direction mismatch" in item for item in result.transform_warnings)


def test_full_chain_merge_preserves_root_head_as_expected_group_origin():
    fitted, expansion = sway_hub.fit_chain_to_length(tuple(SOURCE), 1)
    cp = sway_hub.ChainDonorPlan(fitted, (), (), expansion)
    wiring = sway_hub.HubWiringPlan((SimpleNamespace(chain_plans=(cp,)),), ())
    expected = gate.source_transforms_for_geometry_groups(
        SOURCE, sway_hub.source_geometry_groups(wiring))
    assert expected["tail.004"]["pos"] == SOURCE["tail.044"]["pos"]
    assert expected["tail.004"]["tail"] == SOURCE["tail.004"]["tail"]
