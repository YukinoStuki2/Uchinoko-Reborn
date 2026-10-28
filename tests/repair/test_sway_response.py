"""Compare derived KP coefficients with independent PB small-angle motion."""
from pathlib import Path
import math
import random
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "py"))
from sway_response import response_coefficients


def normalize(point):
    length = math.hypot(*point)
    return tuple(c / length for c in point)


def pb_step(position, velocity, params):
    """Independent unit-length, fixed-pivot 2D response; no collisions/gravity."""
    pull, spring, stiff = (params[k] for k in ("pull", "spring", "stiffness"))
    rest = (0., 1.)
    if params["integration_type"] == "Simplified":
        memory = .99 * spring
        displacement = tuple((rest[i] - position[i]) * pull * (1. - memory)
                             + velocity[i] * memory for i in range(2))
    else:
        momentum = tuple(v * spring for v in velocity)
        displacement = tuple(momentum[i] + (rest[i] - position[i] - momentum[i]) * pull
                             for i in range(2))
        if params["version"] == "Version_1_0":
            displacement = tuple(displacement[i] + position[i] * stiff for i in range(2))
        else:
            proposed = tuple(position[i] + displacement[i] for i in range(2))
            displacement = tuple(displacement[i] + (position[i] - proposed[i]) * stiff
                                 for i in range(2))
    new_position = normalize(tuple(position[i] + displacement[i] for i in range(2)))
    if params["integration_type"] == "Simplified":
        next_velocity = displacement
    else:
        next_velocity = tuple(new_position[i] - position[i] for i in range(2))
    return new_position, next_velocity


def kp_step(position, velocity, coefficients):
    moved = tuple(position[i] + velocity[i] * (1. - coefficients["damping"]) for i in range(2))
    rest = (0., 1.)
    corrected = tuple(moved[i] + (rest[i] - moved[i]) * coefficients["stiffness"] for i in range(2))
    result = normalize(corrected)
    return result, tuple(result[i] - position[i] for i in range(2))


@pytest.mark.parametrize("version", ["Version_1_0", "Version_1_1"])
@pytest.mark.parametrize("integration", ["Simplified", "Advanced"])
@pytest.mark.parametrize("pull,spring,stiffness", [(.2, .2, .2), (.8, .7, .1), (.1, .95, .7),
                                                 (1., 0., 0.), (0., 1., 1.), (1., 1., 1.)])
def test_independent_fixed_pivot_small_angle_trajectory(version, integration, pull, spring, stiffness):
    params = dict(version=version, integration_type=integration, pull=pull, spring=spring, stiffness=stiffness)
    co = response_coefficients(params)
    epsilon = 1e-5
    pb_position = kp_position = (math.sin(epsilon), math.cos(epsilon))
    pb_velocity = kp_velocity = (0., 0.)
    errors = []
    for _ in range(240):
        pb_position, pb_velocity = pb_step(pb_position, pb_velocity, params)
        kp_position, kp_velocity = kp_step(kp_position, kp_velocity, co)
        errors.append(abs(pb_position[0] - kp_position[0]) / epsilon)
    assert max(errors) < 2e-7
    assert co["reference_fps"] == 60
    assert co["status"] == "matched_small_angle"
    assert co["warnings"] == []


@pytest.mark.parametrize("version,integration", [("Version_1_0", "Advanced"),
                                                ("Version_1_1", "Advanced"),
                                                ("Version_1_1", "Simplified")])
def test_one_step_numerical_jacobian_matches_both_independent_gains(version, integration):
    randomizer = random.Random(41292)
    eps = 1e-7
    for _ in range(80):
        params = dict(version=version, integration_type=integration,
                      **{k: randomizer.random() for k in ("pull", "spring", "stiffness")})
        co = response_coefficients(params)
        displaced, _ = pb_step((eps, math.sqrt(1. - eps * eps)), (0., 0.), params)
        impulsed, _ = pb_step((0., 1.), (eps, 0.), params)
        assert 1. - displaced[0] / eps == pytest.approx(co["pull_gain"], abs=2e-13)
        assert impulsed[0] / eps == pytest.approx(co["velocity_retention"], abs=2e-13)
        assert (1. - co["stiffness"]) * (1. - co["damping"]) == pytest.approx(
            co["velocity_retention"], abs=2e-15)


def test_mapping_is_continuous_between_old_preset_boundaries():
    params = dict(version="Version_1_1", integration_type="Advanced", pull=.348, spring=.49, stiffness=.2)
    previous = response_coefficients(params)
    for i in range(1, 201):
        params["pull"] = .348 + i * 1e-5
        current = response_coefficients(params)
        assert current["stiffness"] > previous["stiffness"]
        assert current["stiffness"] - previous["stiffness"] < 1e-4
        assert abs(current["damping"] - previous["damping"]) < 1e-4
        previous = current


def test_full_pull_has_no_singular_damping():
    for integration in ("Simplified", "Advanced"):
        result = response_coefficients(dict(version="Version_1_1", integration_type=integration,
                                            pull=1, spring=0, stiffness=0))
        assert result["stiffness"] == 1
        assert result["damping"] == 1
        assert result["velocity_retention"] == 0


def test_unknown_version_is_explicit_fallback():
    result = response_coefficients(dict(version="future_2", integration_type="Advanced",
                                        pull=.3, spring=.4, stiffness=.5))
    assert result["source_version"] == "future_2"
    assert result["resolved_version"] == "1.1"
    assert result["status"] == "fallback"
    assert any("version" in item for item in result["warnings"])


def test_unknown_integration_is_explicit_fallback():
    result = response_coefficients(dict(version="Version_1_1", integration_type="future_mode",
                                        pull=.3, spring=.4, stiffness=.5))
    assert result["source_integration"] == "future_mode"
    assert result["resolved_integration"] == "Simplified"
    assert result["status"] == "fallback"
    assert any("integration" in item for item in result["warnings"])


@pytest.mark.parametrize("value", [None, "0.5", True, float("nan"), float("inf"), -float("inf")])
def test_invalid_numbers_fall_back_to_sdk_defaults_with_warning(value):
    result = response_coefficients(dict(version="Version_1_1", integration_type="Advanced",
                                        pull=value, spring=value, stiffness=value))
    assert math.isfinite(result["stiffness"]) and math.isfinite(result["damping"])
    assert 0 <= result["stiffness"] <= 1 and 0 <= result["damping"] <= 1
    assert result["status"] == "fallback"
    assert len(result["warnings"]) == 3


def test_out_of_range_values_follow_source_clamp():
    bad = response_coefficients(dict(version="1.1", integration_type="Advanced", pull=4, spring=-1, stiffness=2))
    good = response_coefficients(dict(version="1.1", integration_type="Advanced", pull=1, spring=0, stiffness=1))
    assert (bad["stiffness"], bad["damping"]) == (good["stiffness"], good["damping"])
    assert len(bad["warnings"]) == 3


def test_simplified_does_not_require_unused_stiffness():
    result = response_coefficients(dict(version="1.0", integration_type="Simplified", pull=.3, spring=.4))
    assert result["warnings"] == []


def test_no_settings_returns_finite_explicit_fallback():
    result = response_coefficients(None)
    assert result["status"] == "fallback"
    assert any("version" in item for item in result["warnings"])
    assert any("integration" in item for item in result["warnings"])
