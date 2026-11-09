"""Build automatic, per-component physics from exported source parameters.

No avatar names or hair/tail-specific presets belong here. PhysBone describes
the parent segment; KP simulates its child endpoint. Source depth coordinates
are resampled at the actual donor arc lengths, after final placement checks.
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
import math
import hashlib
import json
from pathlib import Path

import sway_hub_wire
import sway_limits
from sway_response import response_coefficients
from sway_gravity import fit_gravity

MODE = "physbone-v1"
# Changes to node selection or the source-to-target mapping require a complete
# conversion. Fast repack must not silently reuse manifests from older rules.
ADAPTATION_REVISION = 3
CHANNELS = ("stiffness", "damping", "wdl", "wdr", "radius", "limit_angle")


def enabled(job):
    return job.get("sway_adaptation") == MODE and job.get("sway_enable") is True


def input_fingerprint(job):
    """Invalidate saved physics when source metadata or conversion settings change."""
    inputs = {key: job.get(key) for key in (
        "sway_adaptation", "sway_enable", "uniform_scale", "size_fit_mode", "sway_chain_overrides",
        "sway_lab_assignments", "drop_bones")}
    inputs["adaptation_revision"] = ADAPTATION_REVISION
    if job.get("conservative_garment") is True:
        inputs["conservative_garment"] = True
    for key in ("physbones_json", "humanoid_json"):
        path = Path(job[key]) if job.get(key) else None
        inputs[key] = hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def validate_profile(profile):
    """Reject incomplete saved automatic metadata instead of uniform fallback."""
    if not isinstance(profile, Mapping) or profile.get('parameter_mode') != MODE:
        raise ValueError('Invalid automatic PhysBone profile; run a full conversion')
    params, curves = profile.get('params'), profile.get('extended_curves')
    if not isinstance(params, Mapping) or not isinstance(curves, Mapping):
        raise ValueError('Missing automatic PhysBone parameters/curves; run a full conversion')
    for key in (*CHANNELS, 'gravity_z'):
        if _finite(params.get(key), None) is None:
            raise ValueError(f'Invalid automatic PhysBone {key}; run a full conversion')
    for key in CHANNELS:
        points = curves.get(key)
        if not isinstance(points, list) or not points:
            raise ValueError(f'Missing automatic PhysBone {key} curve; run a full conversion')
        previous = -1.0
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError(f'Invalid automatic PhysBone {key} curve; run a full conversion')
            t, value = (_finite(v, None) for v in point)
            if t is None or value is None or not 0 <= t <= 1 or t <= previous:
                raise ValueError(f'Invalid automatic PhysBone {key} sample; run a full conversion')
            previous = t


def _finite(value, default):
    return float(value) if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) else default


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _curve(params, key, ratio, warnings):
    curves = params.get("curves")
    if not isinstance(curves, Mapping):
        warnings.add("source curves were not exported; reconvert from Unity to retain their variation")
        return 1.0
    curve = curves.get(key)
    if not isinstance(curve, Mapping):
        if curve is None:
            warnings.add(f"source curve {key} is unavailable; using its scalar value")
        return 1.0
    if curve.get("keys") == []:
        return 1.0
    samples = curve.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError(f"PhysBone {key} curve has keys but no Unity-evaluated samples; export from Unity again")
    points = []
    for point in samples:
        if not isinstance(point, Mapping):
            raise ValueError(f"Invalid Unity samples in {key}")
        t, value = _finite(point.get("time"), None), _finite(point.get("value"), None)
        if t is None or value is None:
            raise ValueError(f"Non-finite Unity sample in {key}; export from Unity again")
        points.append((t, value))
    points.sort()
    if any(b[0] <= a[0] for a, b in zip(points, points[1:])):
        raise ValueError(f"Duplicate Unity curve sample times: {key}")
    i = bisect_right([p[0] for p in points], ratio)
    if i == 0:
        return points[0][1]
    if i == len(points):
        return points[-1][1]
    a, b = points[i-1], points[i]
    fraction = (ratio-a[0])/(b[0]-a[0])
    return a[1]+fraction*(b[1]-a[1])


def _sample(params, ratio, radius_ratio, warnings):
    result = dict(params)
    for key in ("pull", "spring", "stiffness", "immobile", "gravity_falloff"):
        default = .2 if key in ("pull", "spring", "stiffness") else 0.0
        base = _finite(params.get(key), None)
        if base is None:
            warnings.add(f"invalid or missing {key}; using source default {default}")
            base = default
        value = base * _curve(params, key, ratio, warnings)
        result[key] = _clamp(value)
        if result[key] != value:
            warnings.add(f"sampled {key} outside [0, 1]; clamped as in the source SDK")
    for key in ("gravity", "max_angle_x", "max_angle_z"):
        result[key] = _finite(params.get(key), 0.0) * _curve(params, key, ratio, warnings)
    rotation = params.get("limit_rotation") or [0, 0, 0]
    if not isinstance(rotation, (list, tuple)) or len(rotation) != 3:
        raise ValueError("PhysBone limit_rotation must be a finite three-axis rotation")
    result["limit_rotation"] = [_finite(v, 0.0)*_curve(params, "limit_rotation_"+axis, ratio, warnings)
                                for axis, v in zip("xyz", rotation)]
    result["radius"] = max(0.0, _finite(params.get("radius"), 0.0)*_curve(params, "radius", radius_ratio, warnings))
    return result


def _source_paths(unit, raw_entries):
    matches = [r for r in raw_entries if r.get("anchor") == unit.anchor and r.get("params") == unit.params]
    if not matches:
        matches = [r for r in raw_entries if r.get("anchor") == unit.anchor]
    if len(matches) != 1:
        raise ValueError(f"Cannot identify exported PhysBone component {unit.anchor!r}; export from Unity again")
    return [(unit.anchor, *chain) for chain in matches[0].get("chains", ())]


def _profile(unit, cp, root, heads, params, source_paths, gender, job, source_fit_scale):
    warnings = set()
    representative = cp.representative_source or cp.source_chain
    donors = tuple(cp.donor_chain_for(gender))
    # Both native and free-pool layouts map the source anchor to the hub.
    chain = (root, *donors)
    if len(chain) < 2:
        raise ValueError(f"PhysBone {unit.anchor!r} has no simulated child endpoint")
    if any(n not in heads for n in chain):
        raise ValueError(f"Missing final donor position for {unit.anchor!r}")
    lengths = [math.dist(heads[a], heads[b]) for a, b in zip(chain, chain[1:])]
    total = sum(lengths)
    if total <= 1e-8 or not math.isfinite(total):
        raise ValueError(f"Degenerate final PhysBone chain {unit.anchor!r}")
    original = max(source_paths, key=lambda path: (sum(n in path for n in representative), len(path)))
    depths = {name:i for i, name in enumerate(original)}
    geometry = params.get("geometry") if isinstance(params.get("geometry"), Mapping) else {}
    transforms = {r["name"]:r for r in geometry.get("transforms", ()) if isinstance(r, Mapping) and "name" in r}
    max_depth = int(_finite(geometry.get("max_chain_index"), max(map(len, source_paths), default=1)-1))
    endpoint = params.get("endpoint_position")
    has_endpoint = isinstance(endpoint, (tuple, list)) and len(endpoint)==3 and any(_finite(v,0)!=0 for v in endpoint)
    force_denominator = max_depth+int(has_endpoint)-1
    radius_denominator = max_depth+int(has_endpoint)
    if not geometry:
        warnings.add("source geometry/SDK depth ratios unavailable; inferred from exported chain topology")
    if len(cp.source_chain) < len(representative):
        warnings.add("source joints remain merged; per-segment behavior is an approximation")
    if len(source_paths)>1:
        warnings.add("secondary branches share the representative chain and its parameter samples")
    if params.get("colliders"):
        warnings.add("source PhysBone colliders are not yet reproduced by the cooked backend")
    warnings.add("response coefficients match at 60 Hz near rest; large rotations and other frame rates differ")
    if params.get("immobile_type", "AllMotion") == "AllMotion":
        warnings.add("AllMotion immobility approximates component movement; local animated-pivot suppression differs")
    rows = []; position = 0.0
    for i, length in enumerate(lengths, start=1):
        position += length
        source = cp.source_chain[min(i-1, len(cp.source_chain)-1)]
        depth = depths.get(source, min(i-1, max_depth))
        record = transforms.get(source, {})
        ratio = _finite(record.get("force_ratio"), _clamp(depth/force_denominator) if force_denominator>0 else 0)
        child_source = cp.source_chain[i] if i < len(cp.source_chain) else None
        child_record = transforms.get(child_source, {})
        radius_ratio = _finite(child_record.get("transform_ratio"), _clamp((depth+1)/radius_denominator) if radius_denominator>0 else 0)
        sampled = _sample(params, ratio, radius_ratio, warnings)
        response = response_coefficients(sampled)
        warnings.update(response["warnings"])
        # Preserve the distinction between a locked source cone and KP's zero
        # sentinel for unlimited movement.
        if sampled.get("limit_type", "None") != "None" and sampled["max_angle_x"]<=0:
            angle = 1e-6
        else:
            limit = sway_limits.convert_limit(sampled, compatibility=True)
            angle = limit.angle if limit.supported else 1e-6
            if limit.reason:
                warnings.add(limit.reason)
        immobile = sampled["immobile"]
        source_scale = child_record.get("lossy_scale", record.get("lossy_scale"))
        if not isinstance(source_scale, (list, tuple)) or len(source_scale) != 3:
            warnings.add("source world scale unavailable; radius assumes unit source scale")
            source_scale = (1, 1, 1)
        world_scale = max(abs(_finite(v, 1)) for v in source_scale)
        values = {"stiffness":response["stiffness"], "damping":response["damping"],
                  "wdl":immobile, "wdr":0.0 if sampled.get("immobile_type")=="World" else immobile,
                  "limit_angle":angle,
                  "radius":sampled["radius"]*world_scale*source_fit_scale*_finite(job.get("uniform_scale"),1.0)}
        rows.append({"source_parent":source,"target_endpoint":chain[i],"source_ratio":ratio,
                     "target_length_ratio":1.0 if i == len(lengths) else _clamp(position/total),
                     "length_cm":length*_finite(job.get("uniform_scale"),1.0),"values":values,
                     "source_gravity":sampled["gravity"],"source_gravity_falloff":sampled["gravity_falloff"],
                     "direction":[(b-a)/length if length>1e-8 else 0 for a,b in zip(heads[chain[i-1]],heads[chain[i]])],
                     "pull_gain":response["pull_gain"],"limit_angle":angle,
                     "response_status":response["status"]})
    gravity = fit_gravity(rows, params.get('version'))
    warnings.update(gravity['warnings'])
    curves = {}
    scalars = {"gravity_z":gravity['gravity_z']}
    for key in CHANNELS:
        maximum = max(row["values"][key] for row in rows)
        scalars[key] = maximum
        values = [[0.0, rows[0]["values"][key]/maximum if maximum else 1.0]]
        for row in rows:
            point = [row["target_length_ratio"],row["values"][key]/maximum if maximum else 1.0]
            if point[0] <= values[-1][0]+1e-10:
                warnings.add("coincident donor heads share a curve coordinate")
                values[-1] = point
            else:
                values.append(point)
        curves[key]=values
    return {"params":scalars,"extended_curves":curves,"samples":rows,"warnings":sorted(warnings),
            "source_version":params.get("version"),"integration_type":params.get("integration_type"),
            "reference_fps":60,"parameter_mode":MODE,"gravity_fit":gravity,
            "source_fit_scale":source_fit_scale}


def attach_source_profiles(wiring, job, overrides, gender, donor_heads, raw_physbones, *, source_fit_scale=100.0):
    if not enabled(job):
        return overrides, None
    if _finite(source_fit_scale, None) is None or source_fit_scale <= 0:
        raise ValueError('Automatic PhysBone conversion requires a finite positive source fit scale')
    result = {name:dict(value) for name,value in overrides.items()}
    manifest = sway_hub_wire.source_adaptation_manifest(wiring,gender)
    manifest['input_fingerprint'] = input_fingerprint(job)
    manifest['node_overrides'] = {}
    diagnostics = {r['unit_key']:r for r in manifest['components']}
    for gp in wiring.group_plans:
        plans = iter(gp.chain_plans)
        active_units = [unit for unit in gp.group.units if any(unit.chains)]
        if len(active_units) > 1:
            raise ValueError("Automatic PhysBone adaptation requires a separate node for each component")
        for unit in active_units:
            cp = next(plans)
            if unit.source!='pb':
                continue
            roots = {gp.hub_root_female,gp.hub_root_male}
            root = gp.hub_root_female if gender.lower()=='female' else gp.hub_root_male
            row = diagnostics[unit.key]
            row['target_root'] = root
            if any(result.get(root,{}).get('motion') for root in roots):
                row.update(parameter_mode='manual_override',warnings=['explicit component tuning takes precedence over automatic adaptation'])
                manifest['node_overrides'][root] = result[root]
                continue
            profile = _profile(unit,cp,root,donor_heads,unit.params,_source_paths(unit,raw_physbones),gender,job,source_fit_scale)
            result.setdefault(root,{})['source_profile']=profile
            manifest['node_overrides'][root] = result[root]
            row.update(parameter_mode=MODE,warnings=profile['warnings'],samples=profile['samples'],
                       source_version=profile['source_version'],integration_type=profile['integration_type'],
                       gravity_fit=profile['gravity_fit'])
    return result,manifest
