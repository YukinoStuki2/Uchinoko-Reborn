"""Neutral-pose gravity fits must be supported by the target static equation."""
from pathlib import Path
import math
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "py"))
from sway_gravity import fit_gravity


def sample(**kw):
    return dict(direction=[1., 0., 0.], length_cm=10., pull_gain=.2,
                source_gravity=.2, source_gravity_falloff=0., **kw)


def changed(**kw):
    row = sample()
    row.update(kw)
    return row


def normalize(v):
    size = math.sqrt(sum(x*x for x in v))
    return [x / size for x in v]


@pytest.mark.parametrize("gravity", [-.8, -.2, .1, .5, .8])
def test_single_segment_fits_independently_simulated_kp_rest_direction(gravity):
    row = changed(source_gravity=gravity)
    result = fit_gravity([row], "Version_1_1")
    assert result["status"] == "matched_neutral_pose"
    assert result["residual"] < 1e-10
    expected = normalize([1 - abs(gravity), 0, -gravity])
    position = [10., 0., 0.]
    previous = list(position)
    for _ in range(3000):
        velocity = [(position[i]-previous[i])*.5 for i in range(3)]
        previous = list(position)
        position = [position[i] + velocity[i] +
                    (.5*result["gravity_z"]/60**2 if i == 2 else 0) for i in range(3)]
        position = [position[i] + ((10. if i == 0 else 0.) - position[i])*.2 for i in range(3)]
        position = [x*10 for x in normalize(position)]
    assert normalize(position) == pytest.approx(expected, abs=1e-7)


def test_actual_segment_length_sets_acceleration_without_arbitrary_multiplier():
    short = fit_gravity([sample()], "1.1")
    long = fit_gravity([changed(length_cm=20)], "1.1")
    assert long["gravity_z"] == pytest.approx(2 * short["gravity_z"])
    # Tangent balance for horizontal n, g=.2: k*L*g/(1-g) = (1-k)*G/(2*60^2).
    assert short["gravity_z"] == pytest.approx(-2*60**2*.2*10*.2/(.8*.8))


def test_identical_components_fit_one_node_exactly():
    result = fit_gravity([sample(), sample()], "1.1")
    assert result["status"] == "matched_neutral_pose"
    assert result["residual"] < 1e-12


def test_conflicting_node_gravity_is_reported_instead_of_silently_averaged():
    result = fit_gravity([sample(), changed(source_gravity=-.2)], "1.1")
    assert result["status"] == "fallback"
    assert result["gravity_z"] == 0
    assert result["residual"] > .1
    assert any("residual" in s for s in result["warnings"])


def test_full_falloff_has_no_gravity_at_captured_rest_pose():
    result = fit_gravity([changed(source_gravity=.9, source_gravity_falloff=1)], "1.1")
    assert result["gravity_z"] == 0
    assert result["status"] == "neutral"
    assert any("falloff" in s for s in result["warnings"])


def test_gravity_needs_positive_pull_in_source_1_1():
    result = fit_gravity([changed(pull_gain=0)], "1.1")
    assert result["gravity_z"] == 0
    assert result["status"] == "neutral"


@pytest.mark.parametrize("version", [None, "Version_1_0", "unknown"])
def test_unsupported_version_uses_explicit_zero_fallback(version):
    result = fit_gravity([sample()], version)
    assert result["status"] == "fallback" and result["gravity_z"] == 0
    assert any("version" in s for s in result["warnings"])


@pytest.mark.parametrize("alteration", [dict(pull_gain=1), dict(source_gravity=1),
                                        dict(direction=[0, 0, 1], source_gravity=.5),
                                        dict(direction=[0, 0, 1], source_gravity=.8)])
def test_nonfinite_or_opposite_static_solution_is_rejected(alteration):
    result = fit_gravity([changed(**alteration)], "1.1")
    assert result["status"] == "fallback"
    assert result["gravity_z"] == 0
    assert result["warnings"]


def test_target_outside_cooked_cone_is_not_claimed_equivalent():
    result = fit_gravity([changed(source_gravity=.5, limit_angle=20)], "1.1")
    assert result["status"] == "fallback"
    assert result["gravity_z"] == 0
    assert any("cone" in s for s in result["warnings"])
    assert fit_gravity([changed(source_gravity=.5, limit_angle=0)], "1.1")["status"] == "matched_neutral_pose"


@pytest.mark.parametrize("alteration", [dict(length_cm=0), dict(length_cm=-2), dict(direction=[0, 0, 0]),
                                        dict(source_gravity=float("nan")), dict(pull_gain=float("inf")),
                                        dict(source_gravity_falloff=-1), dict(direction=[True, 0, 1])])
def test_invalid_geometry_and_parameters_never_reach_cooked_gravity(alteration):
    result = fit_gravity([changed(**alteration)], "1.1")
    assert result["status"] == "fallback" and result["gravity_z"] == 0
    assert result["warnings"]


def test_no_samples_has_no_force():
    result = fit_gravity([], "1.1")
    assert result["status"] == "neutral" and result["gravity_z"] == 0
