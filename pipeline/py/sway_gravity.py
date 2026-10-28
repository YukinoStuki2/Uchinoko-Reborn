"""Fit a node's constant gravity to PB 1.1's neutral-pose resting directions.

This is a static, 60 Hz fit, not a reproduction of orientation-dependent
PhysBone gravity/falloff. The force is derived from each actual segment length
and the target KP pull coefficient, without a universal gravity multiplier.
See docs/PHYSBONE_RESPONSE_MAPPING.md for the equation and limitations.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

REFERENCE_FPS = 60
MAX_RELATIVE_RESIDUAL = 0.1
_DOWN = (0.0, 0.0, -1.0)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _length(v):
    return math.sqrt(_dot(v, v))


def fit_gravity(samples, source_version):
    """Return gravity_z, status, warnings, residual, reference_fps.

    Each sample contains direction (final donor rest vector in UE axes),
    length_cm, pull_gain, source_gravity, source_gravity_falloff. Optional
    limit_angle is the final KP cone in degrees; zero means unlimited.
    Unsupported or inconsistent fits return zero and status='fallback'.
    Never silently clip an unrepresentable force into a plausible-looking one.
    """
    warnings = []

    def result(value=0.0, status="neutral", residual=0.0):
        return {"gravity_z": value, "status": status, "warnings": list(warnings),
                "residual": residual, "reference_fps": REFERENCE_FPS}

    def fail(reason, residual=None):
        warnings.append(reason)
        return result(status="fallback", residual=residual)

    def number(value, label, low=None, high=None):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"invalid {label}")
        value = float(value)
        if (low is not None and value < low) or (high is not None and value > high):
            raise ValueError(f"out-of-range {label}")
        return value

    if not isinstance(samples, (list, tuple)):
        return fail("gravity samples are missing or invalid")
    if not samples:
        return result()
    if source_version not in ("Version_1_1", "1.1"):
        return fail("gravity source version is not known PhysBone 1.1; no equivalent scalar is available")
    rows = []
    nonzero_source = False
    try:
        for index, row in enumerate(samples):
            if not isinstance(row, Mapping):
                raise ValueError(f"invalid gravity sample {index}")
            direction = row.get("direction")
            if not isinstance(direction, (list, tuple)) or len(direction) != 3:
                raise ValueError(f"invalid direction at sample {index}")
            n = tuple(number(v, "direction") for v in direction)
            size = _length(n)
            if size <= 1e-12:
                raise ValueError(f"zero direction at sample {index}")
            n = tuple(v / size for v in n)
            length = number(row.get("length_cm"), "length_cm")
            if length <= 0:
                raise ValueError(f"nonpositive length_cm at sample {index}")
            pull = number(row.get("pull_gain"), "pull_gain", 0, 1)
            gravity = number(row.get("source_gravity"), "source_gravity", -1, 1)
            falloff = number(row.get("source_gravity_falloff"), "source_gravity_falloff", 0, 1)
            cone = number(row.get("limit_angle", 0.0), "limit_angle", 0, 180)
            nonzero_source |= gravity != 0
            if gravity != 0 and falloff != 0:
                warning = "gravity falloff is frozen at the captured neutral pose; dynamic orientation response is not represented"
                if warning not in warnings:
                    warnings.append(warning)
            # With zero source response gain, 1.1 cannot move toward gravity.
            effective = gravity * (1 - falloff) if pull > 0 else 0.0
            raw = tuple((1 - abs(effective)) * n[i] + effective * _DOWN[i] for i in range(3))
            magnitude = _length(raw)
            if magnitude <= 1e-10:
                raise ValueError(f"degenerate neutral gravity target at sample {index}")
            target = tuple(v / magnitude for v in raw)
            cosine = max(-1.0, min(1.0, _dot(n, target)))
            angle = math.degrees(math.acos(cosine))
            if cone > 0 and angle > cone + 1e-6:
                raise ValueError(f"neutral gravity target exceeds the cooked cone at sample {index}")
            if angle > 1e-6 and (pull >= 1.0 or cosine <= 1e-10):
                raise ValueError(f"no unique finite neutral gravity fit at sample {index}")
            # P = I - target*target^T removes the radial component. A static
            # target requires P(a*L*n + (1-a)*G*down/(2*60^2)) = 0.
            pn = tuple(n[i] - target[i] * _dot(target, n) for i in range(3))
            pd = tuple(_DOWN[i] - target[i] * _dot(target, _DOWN) for i in range(3))
            c = .5 * (1 - pull) / REFERENCE_FPS**2
            offset = tuple(pull * length * v for v in pn)
            slope = tuple(c * v for v in pd)
            rows.append((offset, slope, pull, length, n, target, c))
    except (ValueError, OverflowError) as exc:
        return fail(str(exc))
    signal = sum(_dot(offset, offset) for offset, *_ in rows)
    if signal <= 1e-24:
        return result()
    denominator = sum(_dot(slope, slope) for _, slope, *_ in rows)
    if denominator <= 1e-30:
        return fail("no finite gravity acceleration can reach the neutral targets")
    acceleration = -sum(_dot(offset, slope) for offset, slope, *_ in rows) / denominator
    if not math.isfinite(acceleration) or abs(acceleration) >= 3.4e38:
        return fail("neutral gravity acceleration is not a finite cooked float")
    residual = math.sqrt(sum(sum((offset[i] + slope[i] * acceleration)**2 for i in range(3))
                             for offset, slope, *_ in rows) / signal)
    if residual > MAX_RELATIVE_RESIDUAL:
        return fail("one node cannot represent these source gravity targets: relative residual exceeds 0.1", residual)
    for _, _, pull, length, n, target, c in rows:
        resultant = tuple(pull * length * n[i] + c * acceleration * _DOWN[i] for i in range(3))
        if _length(resultant) > 1e-12 and _dot(resultant, target) <= 0:
            return fail("fitted gravity points opposite a source neutral target", residual)
    if nonzero_source:
        warnings.append("gravity fits only neutral-pose static balance at 60 Hz; transient and moving-pose behavior differ")
    return result(-acceleration, "matched_neutral_pose", residual)
