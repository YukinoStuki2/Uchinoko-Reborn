"""Blender integration for optional independent garment roots.

The ordinary allocation/degradation loop stays unchanged. Capture source
weights before retargeting, add garment bones to the build inventory, then
check their final geometry and weights separately after the ordinary checks.
"""
from dataclasses import replace
import json
from pathlib import Path

import sway_allocator
import sway_garment
import sway_garment_profile
import sway_hub
import sway_hub_wire
import sway_source_gate


def prepare(job, gender, wiring, raw_entries, parents, weighted, anchor_map,
            common, pal_map, avatar_arm, meshes, read_weights):
    if not sway_garment_profile.enabled(job):
        return None
    catalog = sway_hub.load_skeleton_catalog(str(Path(job["job_dir"]) / "vanilla/sk_palhuman_full.json"))
    # Protect both live templates and the complete original game inventory.
    # Equipment absent from the template may still load from the base game;
    # its bones must not be reassigned to a garment's pelvis chain either.
    from convert_noue import resolve_noue_assets
    template = resolve_noue_assets(job)["template"]
    protected = frozenset(common) | sway_garment.protected_mesh_bones(
        template, palworld_pak=job.get("paths", {}).get("palworld_pak"),
        report_path=Path(job["job_dir"]) / "converted" /
                    f"sway_garment_donor_protection_{gender.lower()}.json")
    roots = sway_hub.all_kp_node_root_names()
    units = sway_allocator.parse_physbones({"physbones": raw_entries})
    # Explicit component choices take precedence over the optional family mode.
    explicit = {entry["bones"][0] for entry in job.get("sway_chain_overrides", [])
                if entry.get("bones") and "enabled" in entry}
    units = [replace(u, lab_override=True) if u.anchor in explicit else u for u in units]
    plan = sway_garment.plan_conservative_garment(
        wiring, units, catalog, conservative_garment=True,
        source_parents=parents, weighted_bones=weighted, anchor_pal_name_of=anchor_map,
        hips_source=pal_map.get("pelvis", "Hips"),
        reserved=sway_hub.reserved_descendants_of(roots, catalog.bones),
        protected=protected, known_moving=sway_hub.load_known_moving_chain_bones(),
        hub_root_names=roots)
    for line in plan.diagnostics:
        print("[step02] " + line)
    extra = sway_hub.HubWiringPlan(group_plans=plan.group_plans, unassignable=())
    # Inventory comes from the source component, before observing the mapping.
    sources = {b for u in plan.units for c in u.chains for b in (u.anchor, *c)}
    _, weights = read_weights(avatar_arm, meshes, sources)
    return {"plan": plan, "wiring": extra, "sources": sources, "weights": weights,
            "refskel": sway_hub.refskel_dict_for_wiring(extra, gender, anchor_pal_of=anchor_map)}


def combine(wiring, state):
    return replace(wiring, group_plans=wiring.group_plans + state["wiring"].group_plans) if state else wiring


def finish_gate(state, job, gender, avatar_arm, pal_arm, meshes, mapping, dz,
                read_source, read_donors):
    if not state or not state["sources"]:
        return
    source = read_source(avatar_arm, state["sources"], float(job.get("uniform_scale", 1)), dz)
    donors = {mapping[n] for n in state["sources"] if n in mapping}
    transforms, weights = read_donors(pal_arm, meshes, donors)
    report = sway_source_gate.run_gate(sorted(state["sources"]), mapping,
                                      source, state["weights"], transforms, weights)
    failures = [{"bone": r.bone, "donor": r.donor, "reasons": r.reasons,
                 "transform_warnings": r.transform_warnings}
                for r in report.results if not r.ok or r.transform_warnings]
    # Independent fixed pivots must remain below the torso, never another skirt
    # root. This also prevents an accidental moving shared hub.
    for gp in state["wiring"].group_plans:
        name = gp.hub_root_male if gender.lower() == "male" else gp.hub_root_female
        bone = pal_arm.data.bones.get(name)
        if bone is None or bone.parent is None or bone.parent.name != "pelvis":
            failures.append({"bone": name, "reasons": ["garment pivot is not attached to pelvis"]})
    conv = Path(job["job_dir"]) / "converted"
    (conv / f"sway_garment_gate_{gender.lower()}.json").write_text(json.dumps(
        {"ok": not failures, "checked": len(report.results), "failed": failures},
        ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        raise ValueError(f"Garment geometry/weight check failed ({len(failures)} bones); see sway_garment_gate_{gender.lower()}.json")
    path = conv / f"sway_source_donor_map_{gender.lower()}.json"
    combined = json.loads(path.read_text(encoding="utf-8"))
    combined.update({n: mapping[n] for n in sorted(state["sources"])})
    path.write_text(json.dumps(combined, ensure_ascii=False), encoding="utf-8")
    print(f"[step02] garment source gate: PASS ({len(report.results)} independent source joints)")


def annotate_coverage(report, state):
    if not state or not state["plan"].units:
        return
    keys = {u.key for u in state["plan"].units}
    for row in report["components"]:
        if row["unit_key"] in keys:
            row.update(reason="Independent garment chain passed placement; bounded shared response",
                       limit_conversion="conservative_garment", converted_limit_angle=3.0,
                       shared_response=True, preserve_segments_effective=True,
                       unweighted_terminal_bones=1)
    report["capacity"] = 10
    report["garment_components"] = len(keys)
    report["limitations"] = [s for s in report["limitations"] if "nine independent" not in s]
    report["limitations"].append("Nine original nodes retained; one additional node drives independent garment roots with a shared bounded response")
