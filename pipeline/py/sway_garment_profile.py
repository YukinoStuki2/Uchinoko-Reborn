"""Persist the opt-in, bounded garment simulation beside the existing nine nodes.

Each root retains its own rest geometry and length coordinate. Shared settings
use the conservative envelope of the source-derived responses, not an avatar
name preset. Directional Polar limits and leg collisions are not equivalent.
"""
from __future__ import annotations

from bisect import bisect_right
import json
from pathlib import Path
import struct

import sway_auto

FORMAT = "uchinoko-reborn-conservative-garment-1"
LIMIT = 3.0


def enabled(job):
    return job.get("conservative_garment") is True and sway_auto.enabled(job)


def _value(profile, channel, t):
    points = profile["extended_curves"][channel]
    i = bisect_right([p[0] for p in points], t)
    if i == 0:
        v = points[0][1]
    elif i == len(points):
        v = points[-1][1]
    else:
        a, b = points[i - 1], points[i]
        v = a[1] + (b[1] - a[1]) * (t - a[0]) / (b[0] - a[0])
    return profile["params"][channel] * v


def conservative_envelope(profiles):
    if not profiles:
        raise ValueError("No source garment profiles")
    for profile in profiles:
        sway_auto.validate_profile(profile)
    params, curves = {"gravity_z": 0.0}, {}
    for channel in sway_auto.CHANNELS:
        # Sibling arc lengths can differ below the precision of a cooked
        # FRichCurveKey time. Deduplicate in its float32 representation before
        # sampling, rather than handing the serializer coincident time keys.
        coordinates = sorted({0.0, 1.0} | {
            struct.unpack("<f", struct.pack("<f", p[0]))[0]
            for profile in profiles for p in profile["extended_curves"][channel]})
        samples = []
        for t in coordinates:
            values = [_value(p, channel, t) for p in profiles]
            value = (0.0 if channel == "radius" else
                     max(1e-6, min(LIMIT, *values)) if channel == "limit_angle" else
                     max(values))
            samples.append([t, value])
        maximum = max(v for _, v in samples)
        params[channel] = maximum
        curves[channel] = [[t, v / maximum if maximum else 1.0] for t, v in samples]
    return params, curves


def make_report(job, wiring, gender, heads, raw_physbones, source_fit_scale,
                bone_fnames, *, rejected=()):
    report = {"format": FORMAT, "enabled": enabled(job), "gender": gender.lower(),
              "input_fingerprint": sway_auto.input_fingerprint(job),
              "source_keys": [], "request": None, "rejected": list(rejected),
              "limitations": ["Small rest-centred Polar approximation, at most three degrees per segment",
                              "Source leg colliders and directional Polar axes are not reproduced"]}
    if not enabled(job) or not wiring.group_plans:
        return report
    overrides, adaptation = sway_auto.attach_source_profiles(
        wiring, job, {}, gender, heads, raw_physbones, source_fit_scale=source_fit_scale)
    roots = [gp.hub_root_male if gender.lower() == "male" else gp.hub_root_female
             for gp in wiring.group_plans]
    profiles = [overrides[root]["source_profile"] for root in roots]
    params, curves = conservative_envelope(profiles)
    report["source_keys"] = [u.key for gp in wiring.group_plans for u in gp.group.units]
    report["request"] = {"root_bone": "M_Hunter001_17", "simulation_root": roots[0],
                         "additional_roots": roots[1:], "params": params,
                         "extended_curves": curves,
                         "bone_fnames": {n: list(bone_fnames[n]) for n in roots}}
    report["adaptation"] = adaptation
    report["source_to_donor"] = {
        source: donor for gp in wiring.group_plans for cp in gp.chain_plans
        for source, donor in zip(cp.source_chain,
                                 ((gp.hub_root_male if gender.lower() == "male" else gp.hub_root_female),
                                  *cp.donor_chain_for(gender)))}
    return report


def write_report(job, gender, report):
    path = Path(job["job_dir"]) / "converted" / f"sway_garment_{gender.lower()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def load_report(job, gender):
    if not enabled(job):
        return None
    path = Path(job["job_dir"]) / "converted" / f"sway_garment_{gender.lower()}.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Missing garment conversion report; run a full conversion") from exc
    if (not isinstance(report, dict) or report.get("format") != FORMAT or report.get("gender") != gender.lower()
            or report.get("enabled") is not True
            or report.get("input_fingerprint") != sway_auto.input_fingerprint(job)):
        raise ValueError("Stale garment conversion report; run a full conversion")
    if bool(report.get("source_keys")) != bool(report.get("request")):
        raise ValueError("Incomplete garment conversion report; run a full conversion")
    return report


def load_request(job, gender):
    report = load_report(job, gender)
    return report.get("request") if report is not None else None


def preserved_anchor_map(job, gender):
    """Validate source roots needed to retain the complete cooked mesh subtree."""
    report = load_report(job, gender)
    if report is None or report.get("request") is None:
        return {}
    try:
        adaptation = report["adaptation"]
        anchors = adaptation["active_physbone_anchors"]
        components = adaptation["components"]
        request = report["request"]
        roots = [request["simulation_root"], *request["additional_roots"]]
        if (adaptation.get("format") != "uchinoko-reborn-sway-adaptation-1"
                or adaptation.get("mode") != "physbone-v1"
                or adaptation.get("gender") != gender.lower()
                or not isinstance(anchors, list) or not anchors
                or any(not isinstance(n, str) or not n for n in anchors)
                or len(anchors) != len(set(anchors))
                or not isinstance(components, list)
                or len(components) != len(anchors)
                or {c["anchor"] for c in components} != set(anchors)
                or {c["unit_key"] for c in components} != set(report["source_keys"])
                or len(roots) != len(set(roots)) or len(roots) != len(anchors)
                or {c["target_root"] for c in components} != set(roots)):
            raise ValueError("inconsistent active garment roots")
        mapping = {c["anchor"]: c["target_root"] for c in components}
        if any(report["source_to_donor"].get(anchor) != root for anchor, root in mapping.items()):
            raise ValueError("garment source root mapping differs from simulation")
        return mapping
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError("Incomplete garment subtree metadata; run a full conversion") from exc
