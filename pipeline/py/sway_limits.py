"""Bounded PhysBone-to-KawaiiPhysics angular compatibility.

An offset VRC Angle cone can contain a smaller cone around its rest axis. The
SDK rotates local +Y with EulerXYZ before aligning that frame to the segment.
Use its actual axis displacement: a twist about +Y does not tilt the cone.
Hinge/Polar constraints cannot be represented by KP's single symmetric cone;
their approximation requires explicit user opt-in.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional


@dataclass(frozen=True)
class LimitConversion:
    supported: bool
    angle: float
    mode: str
    reason: str = ""


def _angle(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0 <= number <= 180 else None


def limit_axis_deviation_degrees(rotation) -> Optional[float]:
    """Angle from +Y to EulerXYZ(rotation) * +Y, as SDK CalcLimitAxis does.

    Its following FromToRotation(+Y, boneVector) rotates both the unshifted and
    shifted axes equally, so the deviation is independent of the imported rig.
    EulerXYZ applies X then Y then Z (Rz @ Ry @ Rx on column vectors).
    """
    if not isinstance(rotation, (tuple, list)) or len(rotation) != 3:
        return None
    try:
        values = [float(v) for v in rotation]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in values):
        return None
    x, y, z = [math.radians(v % 360) for v in values]
    alignment = math.cos(x) * math.cos(z) + math.sin(x) * math.sin(y) * math.sin(z)
    return math.degrees(math.acos(max(-1.0, min(1.0, alignment))))


def convert_limit(params: Mapping[str, object], *, compatibility: bool = False) -> LimitConversion:
    kind = str(params.get("limit_type", "None"))
    if kind == "None":
        return LimitConversion(True, 0.0, "unlimited_source")
    if kind not in {"Angle", "Hinge", "Polar"}:
        return LimitConversion(False, 0.0, "unsupported", f"Unsupported PhysBone limit type: {kind}")
    angle = _angle(params.get("max_angle_x", 0))
    if angle is None or angle <= 0:
        return LimitConversion(False, 0.0, "locked_or_invalid", f"Locked or invalid {kind} source angle; KP zero means unlimited")
    rotation = limit_axis_deviation_degrees(params.get("limit_rotation") or [0, 0, 0])
    if rotation is None:
        return LimitConversion(False, 0.0, "invalid_rotation", "Invalid PhysBone limit rotation")
    if kind == "Angle":
        remaining = angle - rotation
        if remaining > 1e-6:
            return LimitConversion(True, remaining, "inscribed_cone" if rotation > 1e-6 else "direct")
        if not compatibility:
            return LimitConversion(False, 0.0, "rest_axis_outside", "Source Angle cone has no positive rest-centred inner cone")
    elif not compatibility:
        return LimitConversion(False, 0.0, "needs_compatibility", f"{kind} requires explicit bounded approximation; KP cannot preserve its directional constraint")
    if kind == "Polar":
        angle_z = _angle(params.get("max_angle_z", 0))
        if angle_z is None or angle_z <= 0:
            return LimitConversion(False, 0.0, "locked_or_invalid", "Locked or invalid Polar axis")
        angle = min(angle, angle_z)
    # This is intentionally not called an equivalent physical conversion. It
    # allows a small rest-centred sway while preserving placement safety gates.
    return LimitConversion(True, min(15.0, angle), "compatibility_cone",
                           f"Explicit {kind} approximation: directional limits and source colliders are not reproduced")
