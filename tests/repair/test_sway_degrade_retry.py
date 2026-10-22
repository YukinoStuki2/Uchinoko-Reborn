"""Exercise the production retry/precheck/final gate seam without Blender.

Only geometry access is substituted. Allocation, wiring, source selection,
posture and pivot gates, retry attribution and JSON emission are real code.
The real-rurune Blender check complements these small deterministic cases.
"""
import ast
import json
import os
from pathlib import Path
import sys
from typing import Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "py"))
import sway_allocator as allocator
import sway_degrade
import sway_hub
import sway_hub_wire
import sway_pivot_axiom
import sway_source_bones
import sway_source_gate
import vp_core


def production_namespace():
    path = ROOT / "pipeline" / "blender" / "step02_retarget.py"
    names = {
        "sway_gate_compute_source_bone_names", "_SwayGatePrep",
        "_sway_gate_prepare", "_sway_degrade_precheck", "run_sway_degrade_loop",
        "run_sway_source_gate", "_finalize_sway_source_gate_result",
    }
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                and n.name in names]
    assert len(selected) == len(names)
    ns = dict(json=json, os=os, Dict=Dict, List=List, core=vp_core,
              sway_allocator=allocator, sway_degrade=sway_degrade,
              sway_hub=sway_hub, sway_hub_wire=sway_hub_wire,
              sway_pivot_axiom=sway_pivot_axiom,
              sway_source_bones=sway_source_bones, sway_source_gate=sway_source_gate,
              TAG="step02", _SWAY_DEGRADE_MAX_RETRIES=2,
              SWAY_POSTURE_MISMATCH_CULL_TAG="posture mismatch (dev#1625)")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), ns)
    return ns


def transform(pos=(0, 0, 1), direction=(0, 0, 1)):
    return {"pos": list(pos), "tail": [a + b for a, b in zip(pos, direction)],
            "scale": [1, 1, 1], "quat": [0, 0, 0, 1]}


class Scenario:
    def __init__(self, tmp_path, n=12, broken="first", initial_overrides=None):
        self.ns = production_namespace()
        self.conv = tmp_path / "converted"
        self.conv.mkdir()
        atlas = tmp_path / "build" / "atlas"
        atlas.mkdir(parents=True)
        self.entries = [{"anchor": f"Hair{i:02d}", "chains": [[f"Hair{i:02d}_tip"]],
                         "params": {"limit_type": "None", "pull": .5, "spring": .5}}
                        for i in range(n)]
        self.raw = {"physbones": self.entries}
        self.plan = allocator.allocate(physbones_json=self.raw,
                                       lab_assignments=initial_overrides)
        roots = tuple(f"slot{i}" for i in range(9))
        names = ("root",) + roots + tuple(f"free{i}" for i in range(90))
        catalog = sway_hub.SkeletonCatalog.from_bones_list([
            {"name": name, "parent_idx": -1 if i == 0 else 0,
             "pos": [0, 0, 0], "quat": [0, 0, 0, 1], "scale": [1, 1, 1]}
            for i, name in enumerate(names)])
        self.wiring = sway_hub.plan_hub_wiring(
            self.plan, catalog, sway_hub.HubSlots(female=roots, male=roots), frozenset())
        assert len(self.wiring.group_plans) == min(n, 9)
        self.base = {b: "head" for u in self.plan.all_units
                     for b in sway_source_bones.expand_unit_source_bones(u)}
        self.base["Head"] = "head"
        self.parents = {e["anchor"]: "Head" for e in self.entries}
        self.source = {b: transform() for b in self.base}
        self.source["Head"] = transform((0, 0, 0))
        self.current_donors = {}
        if broken == "first":
            self.broken = {self.plan.accepted[0].anchor}
        elif broken == "all":
            self.broken = set(self.parents)
        else:
            self.broken = set()
        self.initial_overrides = initial_overrides
        snapshot = {b: {"weights": {}} for b in self.base}
        (atlas / "step01_sway_snapshot.json").write_text(json.dumps({"bones": snapshot}))
        source = tmp_path / "physbones.json"
        source.write_text(json.dumps(self.raw))
        self.job = {"job_dir": str(tmp_path), "sway_enable": True,
                    "physbones_json": str(source)}
        self.ns["place_hub_donor_chains"] = self.place
        self.ns["_sway_gate_live_source_transforms"] = self.source_transforms
        self.ns["_sway_gate_donor_transforms_and_weights"] = self.donor_transforms

    def place(self, pal_arm, avatar_arm, wiring, gender, anchor_map, dz):
        self.current_donors = {"head": transform((0, 0, 0))}
        mapping = sway_hub_wire.source_to_donor_bone_map(wiring, gender)
        for source, donor in mapping.items():
            direction = (1, 0, 0) if source.split("_tip")[0] in self.broken else (0, 0, 1)
            self.current_donors[donor] = transform(direction=direction)
        return {d: [0, 0, 0, 1] for d in mapping.values()}

    def source_transforms(self, arm, names, output_scale, dz, use_rest=True):
        return {n: self.source[n] for n in names if n in self.source}

    def donor_transforms(self, arm, meshes, names):
        return ({n: self.current_donors[n] for n in names if n in self.current_donors},
                {n: {} for n in names})

    def run(self):
        self.result = self.ns["run_sway_degrade_loop"](
            self.job, "Female", self.entries, [], None, None, self.base, self.base, 0,
            "", {"head": "Head"}, self.parents, self.wiring,
            sway_hub.node_overrides_from_wiring_plan(self.wiring), [],
            sway_hub.refskel_dict_for_wiring(self.wiring, "Female", anchor_pal_of=self.base),
            initial_lab_overrides=self.initial_overrides)
        return self.result

    def final_gate(self):
        wiring, _, _, _, _, overrides, exclusions, disabled = self.result
        mapping = dict(self.base)
        mapping.update(sway_hub_wire.source_to_donor_bone_map(wiring, "Female"))
        self.ns["run_sway_source_gate"](
            self.job, "Female", self.entries, [], None, None, [], mapping,
            str(self.conv), "", wiring, 0, {"head": "Head"}, self.parents,
            lab_assignments=overrides)
        report = sway_degrade.ExclusionReport(
            gender="female", total_units=len(self.plan.all_units),
            fully_disabled=disabled, excluded=tuple(exclusions))
        (self.conv / "sway_exclusions_female.json").write_text(json.dumps(report.to_dict()))
        return json.loads((self.conv / "sway_source_donor_map_female.json").read_text())


def test_retry_retains_eight_good_chains_without_promoting_overflow(tmp_path):
    case = Scenario(tmp_path)
    result = case.run()
    wiring, overrides, _, _, _, lab, exclusions, disabled = result
    original_keys = {u.key for gp in case.wiring.group_plans for u in gp.group.units}
    remaining_keys = {u.key for gp in wiring.group_plans for u in gp.group.units}
    assert len(remaining_keys) == 8, "one bad chain must not disable eight good chains"
    assert remaining_keys < original_keys
    assert not disabled
    assert len(overrides) == 8
    original_map = sway_hub_wire.source_to_donor_bone_map(case.wiring, "Female")
    final_map = case.final_gate()
    assert all(original_map[b] == d for b, d in final_map.items())
    accepted = allocator.allocate(physbones_json=case.raw, lab_assignments=lab)
    assert {u.key for g in accepted.accepted for u in g.units} == remaining_keys
    assert len([e for e in exclusions if e.stage == sway_degrade.STAGE_GATE_TRANSFORM]) == 1


def test_all_disabled_does_not_emit_rigid_fallback_as_dynamic_donor(tmp_path):
    case = Scenario(tmp_path, n=30, broken="all")
    result = case.run()
    assert result[-1] is True
    assert result[0].group_plans == ()
    assert result[1] == {}
    assert case.final_gate() == {}, "rigid head fallback is not a sway donor"
    import preflight_pak
    ok, detail = preflight_pak.check_sway_source_gate_against_pak(case.job, "", "", [])
    assert ok, detail


def test_empty_final_gate_replaces_previous_success_files(tmp_path):
    case = Scenario(tmp_path, n=0, broken=None)
    for filename, payload in (
        ("sway_source_donor_map_female.json", {"old_hair": "old_donor"}),
        ("sway_source_gate_female.json", {"ok": False, "checked": 2}),
        ("sway_pivot_axiom_female.json", {"ok": False, "checked": 1}),
    ):
        (case.conv / filename).write_text(json.dumps(payload))
    case.run()
    assert case.final_gate() == {}
    for name in ("sway_source_gate_female.json", "sway_pivot_axiom_female.json"):
        report = json.loads((case.conv / name).read_text())
        assert report["ok"] is True and report["checked"] == 0


@pytest.mark.parametrize("count", [2, 9, 12])
def test_no_failure_preserves_initial_wiring_and_all_donors(tmp_path, count):
    case = Scenario(tmp_path, n=count, broken=None)
    original = sway_hub_wire.source_to_donor_bone_map(case.wiring, "Female")
    result = case.run()
    assert result[0] == case.wiring
    assert not result[-1]
    assert case.final_gate() == original


def test_force_on_survivor_keeps_explicit_style_after_retry(tmp_path):
    overrides = {"pb:Hair08#8": allocator.LabAssignment(style="yawa", enabled=True)}
    case = Scenario(tmp_path, initial_overrides=overrides)
    result = case.run()
    assert len(result[0].group_plans) == 8
    assert result[5]["pb:Hair08#8"] == overrides["pb:Hair08#8"]


def test_systemic_disable_closes_entire_source_inventory(tmp_path):
    case = Scenario(tmp_path, n=30, broken="all")
    case.ns["_SWAY_DEGRADE_MAX_RETRIES"] = 0
    result = case.run()
    assert result[-1] is True
    assert not result[0].group_plans
    plan = allocator.allocate(physbones_json=case.raw, lab_assignments=result[5])
    assert not plan.accepted
    assert case.final_gate() == {}
