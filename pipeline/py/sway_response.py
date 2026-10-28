"""Continuous PhysBone-to-KawaiiPhysics *small-angle* response coefficients.

This is an independently derived coefficient match, not a copy of either
solver. With a fixed pivot at 60 Hz and without gravity, limits, collisions,
or stretch, write one endpoint update as ``u = a * (rest - x) + b * v``.
KawaiiPhysics applies damping before pull, so ``a = stiffness`` and
``b = (1 - stiffness) * (1 - damping)``. Source versions and integration modes
produce different a/b values; matching names such as 'stiffness' is incorrect.

The mapping does not equate moving-pivot behavior, arbitrary frame rates,
large rotations, gravity, or collision responses. Source parameter curves must
be sampled before calling this function. Evidence and derivation are documented
in docs/PHYSBONE_RESPONSE_MAPPING.md. No SDK dependency is needed at runtime.
"""
from __future__ import annotations

import math
from collections.abc import Mapping


REFERENCE_FPS = 60


def response_coefficients(params):
    """Return KP scalars and explicit provenance for one sampled source bone.

    Recognized source ``version`` values are Version_1_0 / Version_1_1 or
    '1.0' / '1.1'. ``integration_type`` is Simplified / Advanced. Unknown
    values use a documented fallback and set status='fallback'; missing or
    non-finite scalar values use the source SDK's 0.2 constructor defaults.
    Warnings are data for the caller to present once per source component.
    """
    params = params if isinstance(params, Mapping) else {}
    warnings = []
    source_version = params.get("version")
    versions = {"Version_1_0": "1.0", "Version_1_1": "1.1", "1.0": "1.0", "1.1": "1.1"}
    version = versions.get(source_version) if isinstance(source_version, str) else None
    if version is None:
        version = "1.1"
        warnings.append("unknown or missing PhysBone version; using the 1.1 response approximation")
    source_integration = params.get("integration_type")
    integration = source_integration
    if integration not in ("Simplified", "Advanced"):
        integration = "Simplified"
        warnings.append("unknown or missing integration type; using the Simplified response approximation")

    def unit(name):
        raw = params.get(name)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            warnings.append(f"invalid or missing {name}; using source SDK default 0.2")
            return 0.2
        value = float(raw)
        clamped = max(0.0, min(1.0, value))
        if clamped != value:
            warnings.append(f"{name} outside [0, 1]; clamped as in the source SDK")
        return clamped

    pull = unit("pull")
    spring = unit("spring")
    if integration == "Simplified":
        memory = 0.99 * spring
        pull_gain = (1.0 - memory) * pull
        retention = memory
    else:
        source_stiffness = unit("stiffness")
        if version == "1.0":
            # The old orientation term expands the unit direction before its
            # normalization. Linearizing at rest divides both gains by 1+s.
            divisor = 1.0 + source_stiffness
            pull_gain = pull / divisor
            retention = spring * (1.0 - pull) / divisor
        else:
            # The 1.1 orientation blend reduces the complete candidate step.
            pull_gain = (1.0 - source_stiffness) * pull
            retention = (1.0 - source_stiffness) * spring * (1.0 - pull)

    remaining = 1.0 - pull_gain
    # Full pull erases all previous velocity, so damping is immaterial; choose
    # the finite fully-damped value. Else 0 <= retention <= remaining.
    damping = 1.0 if remaining <= 0.0 else 1.0 - retention / remaining
    damping = max(0.0, min(1.0, damping))
    return {
        "stiffness": pull_gain,
        "damping": damping,
        "pull_gain": pull_gain,
        "velocity_retention": retention,
        "reference_fps": REFERENCE_FPS,
        "source_version": source_version if isinstance(source_version, str) else None,
        "source_integration": source_integration if isinstance(source_integration, str) else None,
        "resolved_version": version,
        "resolved_integration": integration,
        "status": "fallback" if warnings else "matched_small_angle",
        "warnings": warnings,
    }
