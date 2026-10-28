"""Verify converted angular freedom rather than merely successful conversion."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "py"))
import sway_allocator
import sway_chain_defaults
import sway_limits


def component(limit_type="Angle", angle=60, rotation=(12, 0, 0)):
    return {"anchor": "Hair", "chains": [["Hair1", "Hair2"]],
            "params": {"pull": 0.2, "spring": 0.1, "limit_type": limit_type,
                       "max_angle_x": angle, "max_angle_z": angle,
                       "limit_rotation": list(rotation)}}


def test_offset_angle_keeps_positive_motion_inside_source_cone():
    plan = sway_allocator.allocate(physbones_json={"physbones": [component()]})
    assert len(plan.accepted) == 1, "A tilted, overlapping cone must retain bounded motion"
    assert plan.accepted[0].units[0].limit_angle == pytest.approx(48)


def test_periodic_euler_angles_do_not_disable_equivalent_cones():
    entry = component(rotation=(360, 0, 0))
    unit = sway_allocator.parse_physbones({"physbones": [entry]})[0]
    assert not unit.is_biased
    assert unit.limit_angle == 60


@pytest.mark.parametrize("twist", [90, 180, -90, 450])
def test_twisting_about_source_cone_axis_keeps_angular_freedom(twist):
    # SDK CalcLimitAxis rotates +Y with quaternion.EulerXYZ. A Y-only twist
    # leaves that axis unchanged; treating it as cone tilt loses this component.
    plan = sway_allocator.allocate(physbones_json={"physbones": [
        component(angle=30, rotation=(0, twist, 0))]})
    assert len(plan.accepted) == 1
    assert plan.accepted[0].units[0].limit_angle == pytest.approx(30)


def test_compound_rotation_uses_source_sdk_xyz_order():
    import numpy as np
    x, y, z = np.radians([20, 50, 30])
    rx = np.array([[1, 0, 0], [0, np.cos(x), -np.sin(x)], [0, np.sin(x), np.cos(x)]])
    ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    rz = np.array([[np.cos(z), -np.sin(z), 0], [np.sin(z), np.cos(z), 0], [0, 0, 1]])
    tilt = np.degrees(np.arccos(np.dot([0, 1, 0], rz @ ry @ rx @ [0, 1, 0])))
    result = sway_limits.convert_limit(component(angle=65, rotation=(20, 50, 30))["params"])
    assert result.angle == pytest.approx(65-tilt)


@pytest.mark.parametrize("rotation,angle", [((60, 0, 0), 60), ((70, 0, 0), 60)])
def test_cone_boundary_or_disjoint_axis_cannot_become_unlimited(rotation, angle):
    plan = sway_allocator.allocate(physbones_json={"physbones": [component(angle=angle, rotation=rotation)]})
    assert not plan.accepted


@pytest.mark.parametrize("kind", ["Hinge", "Polar"])
def test_manual_compatibility_remains_bounded_without_changing_defaults(kind):
    entry = component(limit_type=kind)
    assert not sway_allocator.allocate(physbones_json={"physbones": [entry]}).accepted
    job = {"sway_chain_overrides": [{"bones": ["Hair", "Hair1", "Hair2"], "enabled": True}]}
    overrides = sway_chain_defaults.lab_assignments_from_job(job, [entry], [])
    plan = sway_allocator.allocate(physbones_json={"physbones": [entry]}, lab_assignments=overrides)
    assert len(plan.accepted) == 1
    assert 0 < plan.accepted[0].units[0].limit_angle <= 15


@pytest.mark.parametrize("angle,rotation", [(0, (0, 0, 0)), (float("nan"), (0, 0, 0)), (60, (float("inf"), 0, 0))])
def test_invalid_or_locked_angle_is_not_unlimited(angle, rotation):
    plan = sway_allocator.allocate(physbones_json={"physbones": [component(angle=angle, rotation=rotation)]})
    assert not plan.accepted


def test_inner_cone_stays_inside_source_limit_for_arbitrary_imported_axes():
    """Independent matrix evaluation verifies the geometric safety claim."""
    import numpy as np

    rng = np.random.default_rng(50723)
    for _ in range(40):
        rotation = rng.uniform(-25, 25, size=3)
        x, y, z = np.radians(rotation)
        rx = np.array([[1, 0, 0], [0, np.cos(x), -np.sin(x)], [0, np.sin(x), np.cos(x)]])
        ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
        rz = np.array([[np.cos(z), -np.sin(z), 0], [np.sin(z), np.cos(z), 0], [0, 0, 1]])
        matrix = rz @ ry @ rx
        axis = rng.normal(size=3)
        axis /= np.linalg.norm(axis)
        tangent = np.cross(axis, np.eye(3)[np.argmin(np.abs(axis))])
        tangent /= np.linalg.norm(tangent)
        bitangent = np.cross(axis, tangent)
        # SDK first evaluates its local +Y cone, then rotates that frame onto
        # the actual bone direction. This keeps the test independent of the
        # scalar implementation and covers arbitrary imported bone frames.
        frame = np.column_stack((tangent, axis, -bitangent))
        result = sway_limits.convert_limit(component(angle=65, rotation=rotation)["params"])
        assert result.supported
        radius = math.radians(result.angle)
        for phase in np.linspace(0, 2 * math.pi, 24):
            candidate = np.cos(radius) * axis + np.sin(radius) * (
                np.cos(phase) * tangent + np.sin(phase) * bitangent)
            actual_angle = np.degrees(np.arccos(np.clip(np.dot(frame @ matrix @ [0, 1, 0], candidate), -1, 1)))
            assert actual_angle <= 65 + 1e-8
