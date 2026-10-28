"""Body fitting must ignore accessories and preserve a single model scale."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline/py"))
from vp_avatar_size import fit_measurement


def markers(head, pelvis, ankle):
    return {"head": (0, 0, head), "pelvis": (0, 0, pelvis),
            "foot_l": (.1, 0, ankle), "foot_r": (-.1, 0, ankle)}


def test_short_torso_does_not_oversize_whole_body():
    source = markers(1.5, 1, .1)
    reference = markers(150, 90, 10)
    assert fit_measurement(source, reference)["source_to_cm_scale"] == pytest.approx(120)
    fitted = fit_measurement(source, reference, "vanilla")
    assert fitted["source_to_cm_scale"] == pytest.approx(100)
    assert fitted["relative_to_legacy"] == pytest.approx(1 / 1.2)
    source.update(hat=(0, 0, 100), tail=(0, 0, -50))
    assert fit_measurement(source, reference, "vanilla") == fitted


def test_source_units_and_origin_do_not_change_resulting_size():
    source = markers(1.5, 1, .1)
    reference = markers(150, 90, 10)
    converted = {n: tuple(v * 100 + 23 for v in p) for n, p in source.items()}
    a = fit_measurement(source, reference, "vanilla")
    b = fit_measurement(converted, reference, "vanilla")
    assert a["source_to_cm_scale"] / 100 == pytest.approx(b["source_to_cm_scale"])
    assert a["relative_to_legacy"] == pytest.approx(b["relative_to_legacy"])


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), -1])
def test_invalid_rest_pose_stops_instead_of_using_guessed_scale(bad):
    source = markers(1.5, 1, .1)
    source["head"] = (0, 0, bad)
    with pytest.raises(ValueError):
        fit_measurement(source, markers(150, 90, 10), "vanilla")


def test_no_missing_foot_fallback_to_oversized_torso_fit():
    source = markers(1.5, 1, .1)
    del source["foot_r"]
    with pytest.raises(ValueError, match="foot_r"):
        fit_measurement(source, markers(150, 90, 10), "vanilla")
