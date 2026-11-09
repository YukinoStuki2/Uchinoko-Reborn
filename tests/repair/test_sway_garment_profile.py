import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "py"))
import sway_auto
import sway_garment_profile as garment


def profile(angle=40, immobile=.8):
    params = dict(stiffness=.7, damping=.4, wdl=immobile, wdr=immobile,
                  radius=3.5, limit_angle=angle, gravity_z=-980)
    return dict(parameter_mode="physbone-v1", params=params,
                extended_curves={k: [[0., 1.], [1., .5]] for k in sway_auto.CHANNELS})


def test_shared_envelope_bounds_source_response_and_disables_unconverted_colliders():
    params, curves = garment.conservative_envelope([profile(3), profile(45, .9)])
    assert params["limit_angle"] == 3
    assert params["radius"] == params["gravity_z"] == 0
    assert params["wdl"] == .9
    assert curves["limit_angle"][-1] == [1., .5]


def test_zero_limit_cannot_turn_into_unlimited():
    params, _ = garment.conservative_envelope([profile(0)])
    assert 0 < params["limit_angle"] <= 3


def test_nearly_identical_root_arc_coordinates_remain_unique_when_cooked():
    first, second = profile(), profile()
    for key in sway_auto.CHANNELS:
        first["extended_curves"][key] = [[0., 1.], [.3333333333, .7], [1., .5]]
        second["extended_curves"][key] = [[0., 1.], [.3333333340, .6], [1., .5]]
    _, curves = garment.conservative_envelope([first, second])
    for points in curves.values():
        times = [struct.unpack("<f", struct.pack("<f", t))[0] for t, _ in points]
        assert times == sorted(set(times))
        assert len(times) == 3
        assert times[0] == 0. and times[-1] == 1.


def test_missing_and_stale_reports_reject_repack(tmp_path):
    job = dict(job_dir=str(tmp_path), sway_enable=True,
               sway_adaptation="physbone-v1", conservative_garment=True)
    with pytest.raises(ValueError, match="full conversion"):
        garment.load_request(job, "Female")
    report = dict(format=garment.FORMAT, gender="female", enabled=True,
                  input_fingerprint=sway_auto.input_fingerprint(job), source_keys=[], request=None)
    garment.write_report(job, "Female", report)
    assert garment.load_request(job, "Female") is None
    job["uniform_scale"] = .8
    with pytest.raises(ValueError, match="Stale"):
        garment.load_request(job, "Female")


def test_default_is_unchanged_without_opt_in():
    assert garment.load_request({"sway_enable": True, "sway_adaptation": "physbone-v1"}, "Male") is None
