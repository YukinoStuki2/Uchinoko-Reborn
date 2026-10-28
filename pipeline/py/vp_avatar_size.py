"""Uniform humanoid fitting, independent of Blender and accessory geometry."""
from __future__ import annotations

import math


def fit_measurement(source, reference, mode="legacy"):
    """Return one scale for the whole model, never stretch individual limbs.

    Coordinates are world-space, Z-up. Head-to-ankle span deliberately excludes
    hats, ears, hair and tails; it approximates body height, not mesh bounds.
    Missing or invalid humanoid markers fail explicitly instead of silently
    applying an arbitrary percentage. Old jobs keep torso matching.
    """
    if mode not in ("legacy", "vanilla"):
        raise ValueError(f"Unknown size_fit_mode: {mode!r}")

    def point(points, name):
        try:
            result = tuple(float(v) for v in points[name])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Size fitting requires the Humanoid {name} position") from exc
        if len(result) != 3 or not all(math.isfinite(v) for v in result):
            raise ValueError(f"Size fitting: {name} has an invalid position")
        return result

    def measure(points, selected):
        head = point(points, "head")
        if selected == "legacy":
            pelvis = point(points, "pelvis")
            span = math.dist(head, pelvis)
        else:
            feet = [point(points, n) for n in ("foot_l", "foot_r")]
            span = head[2] - sum(p[2] for p in feet) / 2.0
        if span <= 1e-6:
            raise ValueError("Size fitting needs an upright Humanoid rest pose: "
                             "Head must be above both feet and distinct from Hips")
        return span

    source_span = measure(source, mode)
    reference_span = measure(reference, mode)
    scale = reference_span / source_span
    legacy_scale = measure(reference, "legacy") / measure(source, "legacy")
    return {"mode": mode, "metric": "head_to_ankle_z" if mode == "vanilla" else "hips_to_head_length",
            "source_span": source_span, "reference_span_cm": reference_span,
            "source_to_cm_scale": scale, "relative_to_legacy": scale / legacy_scale}
