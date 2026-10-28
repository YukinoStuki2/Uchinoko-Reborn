"""Replace per-gender plans; merge them only after Blender workers finish."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile

COMBINED_FILENAME = "sway_hub_reparent.json"
GENDERS = ("Male", "Female")


def gender_path(converted, gender):
    if gender not in GENDERS:
        raise ValueError(f"Unsupported reparent gender: {gender!r}")
    return Path(converted) / f"sway_hub_reparent_{gender.lower()}.json"


def _validate(steps, label):
    if not isinstance(steps, list):
        raise ValueError(f"{label}: reparent plan must be a list")
    seen = set()
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError(f"{label}: reparent step must be an object")
        for key in ("target", "new_parent"):
            if not isinstance(step.get(key), str) or not step[key]:
                raise ValueError(f"{label}: reparent step needs {key}")
        if step["target"] in seen:
            raise ValueError(f"{label}: duplicate reparent target {step['target']!r}")
        seen.add(step["target"])
        transform = step.get("new_local_transform")
        if transform is None:
            continue
        if not isinstance(transform, (list, tuple)) or len(transform) != 3:
            raise ValueError(f"{label}: invalid transform for {step['target']!r}")
        for values, size in zip(transform, (4, 3, 3)):
            if (not isinstance(values, (list, tuple)) or len(values) != size
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(v) for v in values)):
                raise ValueError(f"{label}: invalid transform for {step['target']!r}")
    return steps


def _atomic_write(path, steps):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(steps, stream, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_gender(converted, gender, steps):
    """Replace every step, including with [] after disabling physics."""
    path = gender_path(converted, gender)
    _validate(steps, str(path))
    _atomic_write(path, steps)
    return path


def _read(path):
    with path.open(encoding="utf-8") as stream:
        return _validate(json.load(stream), str(path))


def _same_transform(a, b):
    if a is None or b is None:
        return a is b
    return all(math.isclose(x, y, rel_tol=1e-6, abs_tol=1e-5)
               for left, right in zip(a, b) for x, y in zip(left, right))


def read_for_build(converted, genders):
    """Only exports without any per-gender plans can use the legacy file."""
    if not isinstance(genders, (list, tuple, set, frozenset)):
        raise ValueError("Reparent build needs a list of requested genders")
    requested = set(genders)
    if not requested or not requested <= set(GENDERS):
        raise ValueError(f"Invalid reparent build genders: {genders!r}")
    combined = Path(converted) / COMBINED_FILENAME
    if not any(gender_path(converted, gender).is_file() for gender in GENDERS):
        return _read(combined) if combined.is_file() else []
    merged = {}
    for gender in GENDERS:
        if gender not in requested:
            continue
        path = gender_path(converted, gender)
        if not path.is_file():
            raise ValueError(f"Missing current {gender} reparent plan: {path}. "
                             "Run a full conversion for all requested genders.")
        for step in _read(path):
            previous = merged.get(step["target"])
            if previous is not None:
                if (previous["new_parent"] != step["new_parent"]
                        or not _same_transform(previous.get("new_local_transform"),
                                               step.get("new_local_transform"))):
                    raise ValueError(f"Conflicting {gender} reparent geometry for shared bone "
                                     f"{step['target']!r}; rebuild both genders together")
                continue
            merged[step["target"]] = step
    result = list(merged.values())
    _atomic_write(combined, result)
    return result
