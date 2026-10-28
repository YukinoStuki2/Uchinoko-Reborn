"""Opt-in per-component PhysBone/SpringBone adaptation for KawaiiPhysics.

The old conversion is unchanged without a ``motion`` override. The existing
measured pull/spring quantizer is reused; these conservative profiles are an
approximation, not a reproduction of VRChat's solver. Collider shapes, animated
parameter curves and rotated hinge/polar constraints are not copied here.
"""
from __future__ import annotations

import math
from typing import Mapping

import sway_quantize

PROFILES = ("source", "calm")
AMOUNT_RANGE = (0.25, 1.5)
DAMPING_RANGE = (0.05, 1.0)
GRAVITY_RANGE = (-100.0, 0.0)


def _number(value, default=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value) if math.isfinite(value) else default


def _clamp(value, low, high):
    return max(low, min(high, value))


def sanitize_motion_settings(raw):
    """Omit legacy/invalid settings; never allow NaN/Inf into cooked assets."""
    if not isinstance(raw, Mapping) or raw.get("profile") not in PROFILES:
        return None
    out = {"profile": raw["profile"],
           "amount": _clamp(_number(raw.get("amount"), 1.0), *AMOUNT_RANGE)}
    for key, limits in (("damping", DAMPING_RANGE), ("gravity_z", GRAVITY_RANGE)):
        value = _number(raw.get(key))
        if value is not None:
            out[key] = _clamp(value, *limits)
    return out


def _matching_settings(unit, entries):
    matches = []
    for chain in unit.chains:
        key = (unit.anchor, *chain)
        exact = [e for e in entries if tuple(e.get("bones") or ()) == key]
        # Blender removes unweighted bones before allocation. An ordered subset
        # match preserves a user's setting through that filtering, without
        # treating every similarly named chain as the same component.
        candidates = exact
        if not exact:
            candidates = []
            for entry in entries:
                original = entry.get("bones") or []
                if not original or original[0] != unit.anchor:
                    continue
                iterator = iter(original[1:])
                if all(any(value == bone for value in iterator) for bone in chain):
                    candidates.append(entry)
        for entry in candidates:
            settings = sanitize_motion_settings(entry.get("motion"))
            if settings is not None and entry.get("enabled", True):
                matches.append(settings)
    if not matches:
        return None
    if any(value != matches[0] for value in matches[1:]):
        raise ValueError(f"conflicting motion settings for component {unit.anchor!r}")
    return matches[0]


def attach_motion_overrides(wiring, job, existing_overrides):
    """Attach settings and source metadata to *final* donor node overrides.

    No topology, rest transforms or allocation decisions are changed. Call after
    graceful-degrade retries, so settings only reach successfully wired nodes.
    """
    result = {name: dict(value) for name, value in existing_overrides.items()}
    entries = [entry for entry in (job.get("sway_chain_overrides") or [])
               if isinstance(entry, Mapping) and isinstance(entry.get("bones"), list)
               and entry["bones"] and all(isinstance(bone, str) and bone for bone in entry["bones"])]
    for gp in wiring.group_plans:
        payloads = []
        for unit in gp.group.units:
            settings = _matching_settings(unit, entries)
            if settings is not None:
                payloads.append({"settings": settings, "source": unit.source,
                                 "source_params": dict(unit.params or {})})
        if not payloads:
            continue
        if any(value != payloads[0] for value in payloads[1:]):
            raise ValueError("different motion profiles cannot share one physics node")
        for root in (gp.hub_root_female, gp.hub_root_male):
            result.setdefault(root, {})["motion"] = payloads[0]
    return result


def adapt_motion_params(base_params, payload, hardness_presets):
    """Return bounded KP scalar parameters for an explicitly opted-in component.

    ``hardness_presets`` is sway_abp_build.HARDNESS, avoiding a second preset
    table. Larger amount widens the cone and lowers motion resistance. The
    profile's cone remains finite: KP uses zero to mean *unlimited*, not rigid.
    Gravity defaults to zero to preserve the author's rest shape; VRC gravity
    and its falloff do not share KP's coordinate/force semantics.
    """
    result = dict(base_params)
    if not isinstance(payload, Mapping):
        return result
    settings = sanitize_motion_settings(payload.get("settings"))
    if settings is None:
        return result
    source_params = payload.get("source_params")
    source_params = source_params if isinstance(source_params, Mapping) else {}
    def p(key, fallback=0.0):
        return _number(source_params.get(key), fallback)
    if payload.get("source") in ("sb", "springbone"):
        style = sway_quantize.quantize_sb(p("stiffness"), p("gravity_power"), p("drag_force"))
    else:
        style = sway_quantize.quantize_pb(p("pull", 0.5), p("spring", 0.5))
    damping, stiffness, world_damping = hardness_presets[style]
    calm = settings["profile"] == "calm"
    amount = settings["amount"]
    damping = max(damping, 0.45 if calm else 0.30)
    stiffness = max(stiffness, 0.30 if calm else 0.15)
    world_damping = max(world_damping, 0.40 if calm else 0.20)
    result["damping"] = settings.get("damping", damping)
    result["stiffness"] = _clamp(stiffness / amount, 0.05, 0.95)
    result["wdl"] = result["wdr"] = _clamp(world_damping + (1.0 - amount) * 0.3, 0.0, 0.95)
    max_angle = 25.0 if calm else 45.0
    # Existing node limit already accounts for compatibility mapping of rotated
    # source cones. Respect it instead of recovering a larger raw PB angle.
    source_angle = _number(base_params.get("limit_angle"), 0.0)
    if source_angle > 0:
        max_angle = min(max_angle, source_angle)
    angle = _clamp(max_angle * amount, 1e-6, 90.0)
    result["limit_angle"] = min(angle, source_angle) if source_angle > 0 else angle
    result["gravity_z"] = settings.get("gravity_z", 0.0)
    return result
