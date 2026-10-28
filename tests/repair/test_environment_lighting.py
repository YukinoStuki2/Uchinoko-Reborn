"""Default conversion follows environment light; explicit shadow lift is retained."""
import inspect
import json
import os
from pathlib import Path
import struct
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app_py"))
sys.path.insert(0, str(ROOT / "pipeline" / "py"))
import pipeline_runner
import live_template
import vp_avatar_library
import vp_core
import vp_matparam


def test_new_gui_job_and_core_and_library_use_environment_light(tmp_path):
    avatar = tmp_path / "avatar.vrm"
    avatar.write_bytes(b"")
    job_path = pipeline_runner.write_job(str(tmp_path), str(tmp_path / "models"), str(avatar))
    generated = json.loads(Path(job_path).read_text(encoding="utf-8"))
    assert generated["shadow_lift"] == 0
    assert generated["unlit"] is False
    assert inspect.signature(pipeline_runner.run_pipeline).parameters["shadow_bar_value"].default == 100
    manual = tmp_path / "manual.json"
    manual.write_text(json.dumps({"paths": {"palworld_pak": "local-test.pak"}}))
    assert vp_core.load_job(str(manual))["shadow_lift"] == 0
    assert vp_avatar_library._settings_summary({})["shadow_lift"] == 0


def test_explicit_older_shadow_setting_is_preserved(tmp_path):
    avatar = tmp_path / "avatar.vrm"
    avatar.write_bytes(b"")
    path = pipeline_runner.write_job(str(tmp_path), str(tmp_path / "models"), str(avatar), shadow_bar_value=30)
    generated = json.loads(Path(path).read_text(encoding="utf-8"))
    assert generated["shadow_lift"] == .7
    generated["paths"]["palworld_pak"] = "local-test.pak"
    Path(path).write_text(json.dumps(generated))
    loaded = vp_core.load_job(path)
    assert loaded["shadow_lift"] == .7
    assert vp_avatar_library._settings_summary(loaded)["shadow_lift"] == .7


def test_zero_shadow_lift_clears_cached_emission_instead_of_skipping():
    ops, amount = live_template.unify_shadow_ops(0)
    assert amount == 0
    assert ("vector", "BaseColor", (1., 1., 1., 1.)) in ops
    assert ("scalar", "Emissive Texture Intensity", 0.) in ops


@pytest.mark.parametrize("amount,unlit,base,emission", [(0., False, 1., 0.), (.7, False, .3, .7),
                                                      (.7, True, 0., 1.)])
def test_actual_cooked_material_parameters(amount, unlit, base, emission):
    """Optional integration fixture remains outside the public repository."""
    source = os.environ.get("UCHINOKO_TEST_MATERIAL_UASSET")
    if not source:
        pytest.skip("set UCHINOKO_TEST_MATERIAL_UASSET to an existing cooked material pair")
    source = Path(source)
    raw_header, raw_payload = source.read_bytes(), source.with_suffix(".uexp").read_bytes()
    ops, _ = live_template.unify_shadow_ops(amount, unlit=unlit)
    header, payload, _ = vp_matparam.edit_material_instance(raw_header, raw_payload, ops)
    h = live_template._parse_header_with_offsets(header)
    names, _ = live_template._read_name_table(header, h.name_offset, h.name_count)
    parsed = vp_matparam.parse_mi_uexp(payload)
    def value(prop, name, fmt):
        array = parsed["arrays"][prop]
        entry = next(e for e in array["entries"] if names[e["name_idx"]] == name)
        return struct.unpack(fmt, entry["value"] or bytes(array["value_size"]))
    assert value(15, "BaseColor", "<4f") == pytest.approx((base, base, base, 1))
    assert value(14, "Emissive Texture Intensity", "<f")[0] == pytest.approx(emission)
    assert value(17, "Emissive Texture", "<i") == value(17, "Base Texture", "<i")
    assert source.read_bytes() == raw_header and source.with_suffix(".uexp").read_bytes() == raw_payload
