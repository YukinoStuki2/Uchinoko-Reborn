"""Account for every imported physics component, including default exclusions."""
from __future__ import annotations

from collections import Counter

import sway_allocator
import sway_hub
import sway_hub_wire
import sway_limits


def disabled_coverage_report(gender):
    """Replace a prior run's results when physics is globally disabled."""
    return {"format": "uchinoko-reborn-sway-coverage-1", "gender": gender.lower(),
            "total_components": 0, "active_components": 0, "globally_disabled": True,
            "capacity": sway_allocator.DEFAULT_CAPACITY, "counts": {}, "components": [],
            "limitations": ["Physics conversion was disabled for this run; components were not evaluated"]}


def build_coverage_report(*, physbone_entries, springbone_entries,
                          filtered_physbone_entries, filtered_springbone_entries,
                          initial_assignments, wiring, exclusions, gender,
                          job=None):
    source = (sway_allocator.parse_physbones({"physbones": list(physbone_entries or [])})
              + sway_allocator.parse_springbones({"springbones": list(springbone_entries or [])}))
    automatic = ((job or {}).get("sway_adaptation") == "physbone-v1"
                 and bool((job or {}).get("sway_enable")))
    plan = sway_allocator.allocate(
        physbones_json={"physbones": list(filtered_physbone_entries or [])},
        springbones_json={"springbones": list(filtered_springbone_entries or [])},
        lab_assignments=initial_assignments, refill_nested=automatic)
    filtered = {u.key: u for u in plan.all_units}
    active = {u.key: gp for gp in wiring.group_plans for u in gp.group.units}
    requested = sway_hub_wire.preserve_chain_anchors_from_overrides(
        (job or {}).get("sway_chain_overrides"))
    if automatic:
        requested = requested | frozenset(u.anchor for gp in wiring.group_plans
                                         for u in gp.group.units if u.source == "pb")
    final_mapping = sway_hub_wire.source_to_donor_bone_map(wiring, gender)
    weighted_donors = set(final_mapping.values())
    segment_stats = {}
    for gp in wiring.group_plans:
        chain_plans = iter(gp.chain_plans)
        for unit in gp.group.units:
            representative, branches = sway_hub.select_tuft_representative(unit.chains)
            if not representative and not branches:
                continue
            cp = next(chain_plans)
            source_chain = cp.representative_source or ((unit.anchor,) + representative)
            mapped = {final_mapping[n] for n in source_chain if n in final_mapping}
            terminals = 0
            for donor in reversed(cp.donor_chain_for(gender)):
                if donor in weighted_donors:
                    break
                terminals += 1
            segment_stats[unit.key] = {
                "representative_source_joints": len(source_chain),
                "independent_mapped_joints": len(mapped),
                "unweighted_terminal_bones": terminals,
                "merged_secondary_branches": len(branches),
                "preserve_segments_effective": (unit.anchor in requested
                                                and len(mapped) == len(source_chain)
                                                and terminals > 0),
            }
    failures = {}
    for entry in exclusions:
        failures.setdefault(entry.unit_key, []).append({"stage": entry.stage, "reason": entry.reason})
    rows = []
    explicit_off = {tuple(entry.get("bones") or [])
                    for entry in (job or {}).get("sway_chain_overrides", [])
                    if "enabled" in entry and not entry["enabled"]}
    for unit in source:
        current = filtered.get(unit.key)
        row = {"unit_key": unit.key, "anchor": unit.anchor, "source": unit.source,
               "source_chains": len(unit.chains), "source_bones": unit.bone_count,
               "weighted_bones": current.bone_count if current else 0,
               "collider_count": unit.collider_count,
               "preserve_segments_requested": unit.anchor in requested,
               "preserve_segments_effective": False}
        if automatic:
            row["adaptation_mode"] = "physbone-v1"
            row["automatic_segments_requested"] = unit.source == "pb" and unit.key in active
        if unit.source == "pb":
            conversion = sway_limits.convert_limit(unit.params, compatibility=unit.key in active)
            row.update(limit_type=unit.params.get("limit_type", "None"),
                       limit_conversion=conversion.mode,
                       converted_limit_angle=conversion.angle,
                       compatibility_note=conversion.reason)
        if unit.source_disabled_reason:
            row.update(status="source_disabled", reason=unit.source_disabled_reason)
        elif unit.key in active:
            row.update(status="active", reason="Final donor wiring passed placement checks")
            row.update(segment_stats[unit.key])
        elif current and current.nested_parent_key:
            parent_key = current.nested_parent_key
            row.update(parent_unit_key=parent_key, independent_parameters_applied=False)
            if parent_key in active:
                row.update(status="nested_follow_parent",
                           reason=("Nested source bones follow the parent's physics to preserve "
                                   "continuity; child parameters are not applied independently"))
            else:
                row.update(status="nested_parent_unavailable",
                           reason=("The parent did not retain final donor wiring; this child "
                                   "has no independent simulator in this conversion"))
        elif not current or not current.chains:
            row.update(status="no_weighted_chain", reason="No descendant in this component has mesh weights")
        elif unit.key in failures:
            row.update(status=failures[unit.key][-1]["stage"], reason=failures[unit.key][-1]["reason"])
        elif current.excluded_reason and "容量超過" in current.excluded_reason:
            row.update(status="capacity_overflow", reason=current.excluded_reason)
        elif any((unit.anchor,) + tuple(chain) in explicit_off for chain in unit.chains):
            row.update(status="disabled", reason="Explicitly disabled in component settings")
        elif unit.is_biased:
            row.update(status="unsupported_limit", reason=unit.bias_reason)
        elif current.excluded_reason:
            row.update(status="disabled", reason=current.excluded_reason)
        else:
            row.update(status="unassigned", reason="No final donor wiring was available")
        if unit.key in failures:
            row["placement_checks"] = failures[unit.key]
        rows.append(row)
    counts = dict(sorted(Counter(r["status"] for r in rows).items()))
    return {"format": "uchinoko-reborn-sway-coverage-1", "gender": gender.lower(),
            "total_components": len(rows), "active_components": counts.get("active", 0),
            "capacity": plan.capacity, "refill_nested": automatic,
            "counts": counts, "components": rows,
            "limitations": ["Source PhysBone colliders and directional Hinge/Polar constraints are not reproduced",
                            "Current cooked animation templates provide nine independent physics nodes",
                            "Fully covered nested components follow the selected parent; their parameters are not independent",
                            ("Automatic allocation fills slots released by nested compaction before wiring; "
                             "later placement failures never promote unwired components" if automatic else
                             "Legacy allocation: slots released by nested compaction are not filled from capacity overflow")]}
