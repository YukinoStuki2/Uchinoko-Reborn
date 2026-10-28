"""Opt-in motion controls must reach the actual cooked KawaiiPhysics nodes."""
from pathlib import Path
import math
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "pipeline" / "py"), str(ROOT / "app_py")]

import sway_abp_build as build
import sway_chain_override_store as store
import sway_motion as motion


def _wiring():
    unit = SimpleNamespace(anchor="Hair", chains=(("Hair1", "Hair2"),),
                           source="pb", params={"pull": 0.5, "spring": 0.4,
                                                "max_angle_x": 160.0})
    group = SimpleNamespace(units=(unit,))
    return SimpleNamespace(group_plans=(SimpleNamespace(
        group=group, hub_root_female="F_Hair", hub_root_male="M_Hair"),))


def _job(settings):
    return {"sway_chain_overrides": [{"bones": ["Hair", "Hair1", "Hair2"],
             "enabled": True, "motion": settings}]}


def test_legacy_settings_are_exact_noop():
    previous = {"F_Hair": {"style": "yawa", "limit_angle": 160.0}}
    assert motion.attach_motion_overrides(_wiring(), {}, previous) == previous
    expected = build.build_spec_nodes(["F_Hair"], "yawa", node_overrides=previous)
    actual = build.build_spec_nodes(["F_Hair"], "yawa", node_overrides=
                                  motion.attach_motion_overrides(_wiring(), {}, previous))
    assert actual == expected


def test_motion_survives_store_reload_and_affects_both_gender_nodes(tmp_path):
    entries = _job({"profile": "source", "amount": 0.5,
                    "damping": 0.6, "gravity_z": -25.0})["sway_chain_overrides"]
    store.save_config(str(tmp_path), "avatar.prefab", entries,
                      default_enabled_map={("Hair", "Hair1", "Hair2"): True})
    job = {"sway_chain_overrides": store.load_config(str(tmp_path), "avatar.prefab")}
    overrides = motion.attach_motion_overrides(_wiring(), job, {})
    nodes = build.build_spec_nodes(["F_Hair", "M_Hair"], "yawa", node_overrides=overrides)
    assert nodes[0]["params"] == nodes[1]["params"]
    params = nodes[0]["params"]
    assert params["damping"] == 0.6
    assert params["gravity_z"] == -25.0
    assert 0 < params["limit_angle"] <= 22.5
    assert params["stiffness"] > build.params_for("yawa")["stiffness"]


def test_smaller_amount_reduces_angle_and_increases_motion_resistance():
    def params(amount):
        override = motion.attach_motion_overrides(_wiring(), _job(
            {"profile": "source", "amount": amount}), {})
        return build.build_spec_nodes(["F_Hair"], "yawa", node_overrides=override)[0]["params"]
    low, high = params(0.25), params(1.5)
    assert 0 < low["limit_angle"] < high["limit_angle"] <= 67.5
    assert low["stiffness"] > high["stiffness"]
    assert low["wdl"] > high["wdl"]
    assert low["wdr"] > high["wdr"]


def test_calm_profile_is_more_restrained_than_source():
    results = []
    for profile in ("source", "calm"):
        override = motion.attach_motion_overrides(_wiring(), _job({"profile": profile}), {})
        results.append(build.build_spec_nodes(["F_Hair"], "yawa", node_overrides=override)[0]["params"])
    source, calm = results
    assert calm["limit_angle"] < source["limit_angle"]
    assert calm["damping"] >= source["damping"]
    assert calm["stiffness"] >= source["stiffness"]
    assert source["gravity_z"] == calm["gravity_z"] == 0


def test_matches_original_chain_after_unweighted_bones_are_filtered():
    job = _job({"profile": "calm"})
    job["sway_chain_overrides"][0]["bones"].insert(2, "Unweighted")
    overrides = motion.attach_motion_overrides(_wiring(), job, {})
    assert overrides["F_Hair"]["motion"]["settings"]["profile"] == "calm"


def test_invalid_numbers_cannot_reach_physics_output():
    settings = motion.sanitize_motion_settings({"profile": "source", "amount": math.nan,
                                               "damping": math.inf, "gravity_z": "oops"})
    assert settings == {"profile": "source", "amount": 1.0}
    assert motion.sanitize_motion_settings({"profile": "legacy"}) is None
    settings = motion.sanitize_motion_settings({"profile": "calm", "amount": -10,
                                               "damping": 200, "gravity_z": 980})
    assert settings == {"profile": "calm", "amount": 0.25, "damping": 1.0, "gravity_z": 0.0}


@pytest.mark.parametrize("angle", [0.2, 1.0, 15.0])
def test_increased_amount_cannot_widen_compatibility_limit(angle):
    payload = {"settings": {"profile": "source", "amount": 1.5}, "source": "pb"}
    result = motion.adapt_motion_params({"limit_angle": angle}, payload, build.HARDNESS)
    assert 0 < result["limit_angle"] <= angle


def test_control_changes_cooked_bytes_and_reads_back_actual_kp_fields():
    import os
    import sway_abp_patcher
    import vp_core
    template = build.load_template_manifest()[0]
    cooked_dir = os.environ.get("UCHINOKO_TEST_COOKED_DIR", build.COOKED_DIR)
    if not (Path(cooked_dir) / template["uasset_name"]).is_file():
        pytest.skip("Set UCHINOKO_TEST_COOKED_DIR to a legitimate local installation's templates")
    root = template["root_bones"][0]
    unit = _wiring().group_plans[0].group.units[0]
    payload = {"settings": {"profile": "source", "amount": 0.5, "damping": 0.6,
                            "gravity_z": -25.0}, "source": "pb", "source_params": unit.params}
    _, legacy_bytes = build.patch_template_bytes(template, "yawa", cooked_dir=cooked_dir)
    _, new_bytes = build.patch_template_bytes(template, "yawa", cooked_dir=cooked_dir,
                                             node_overrides={root: {"motion": payload}})
    assert new_bytes != legacy_bytes
    names = vp_core.read_names(str(Path(cooked_dir) / template["uasset_name"]))
    nodes = sway_abp_patcher.read_kawaii_physics_node_values(
        new_bytes, names, [{"root_bone": name} for name in template["root_bones"]])
    node = next(n for n in nodes if n["root_bone"] == root)
    assert node["params"]["damping"] == pytest.approx(0.6)
    assert node["params"]["gravity_z"] == -25.0
    assert 0 < node["params"]["limit_angle"] <= 22.5
