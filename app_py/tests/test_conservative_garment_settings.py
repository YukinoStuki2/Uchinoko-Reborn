"""The experimental skirt option must survive GUI/job transport without stale builds."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline_runner as pr
from ui import main_window as mw
from test_main_window_restore import _FakeSelf, _FakeScale, _write_job_dir
from test_pipeline_runner_sway_fallback_dev1649 import FakeProcessHandle
from test_palworld_manual_fallback_dev229 import _FakeSelfForStartPipeline, _FakeEntry


@pytest.mark.parametrize("mode,selected,expected", [
    ("auto", True, True), ("auto", False, False), ("auto", "true", False),
    ("none", True, False), ("normal", True, False), ("soft", True, False),
])
def test_job_requires_explicit_auto_opt_in(tmp_path, mode, selected, expected):
    path = pr.write_job(str(tmp_path / "app"), str(tmp_path / "work"),
                        str(tmp_path / "avatar.fbx"), sway_intensity=mode,
                        conservative_garment=selected)
    data = pr.read_job(path)
    assert (data.get("conservative_garment") is True) is expected
    if not expected:
        assert "conservative_garment" not in data


def test_material_update_checks_cooked_setting_before_overwriting_job(tmp_path):
    app, work, avatar = (str(tmp_path / x) for x in ("app", "work", "avatar.fbx"))
    path = pr.write_job(app, work, avatar)
    build = Path(path).parent / "build"
    build.mkdir()
    (build / "job_snapshot.json").write_text("{}", encoding="utf8")
    before = Path(path).read_bytes()
    with pytest.raises(ValueError, match="Full Convert"):
        pr.run_pipeline(app, work, avatar, materials_only=True,
                        conservative_garment=True, on_line=lambda _: None,
                        on_exit=lambda _: None)
    assert Path(path).read_bytes() == before


def test_experimental_failure_does_not_retry_without_existing_physics(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ProcessHandle", FakeProcessHandle)
    monkeypatch.setattr(pr, "find_pwsh", lambda *a, **kw: "pwsh")
    FakeProcessHandle.instances = []
    app, work, avatar = (str(tmp_path / x) for x in ("app", "work", "avatar.fbx"))
    exits = []
    handle = pr.run_pipeline(app, work, avatar, conservative_garment=True,
                            on_line=lambda _: None, on_exit=exits.append)
    assert pr.read_job(os.path.join(handle.job_dir, "job.json"))["conservative_garment"] is True
    FakeProcessHandle.instances[0].fire_exit(1)
    assert exits == [1]
    assert len(FakeProcessHandle.instances) == 1
    failed_job = pr.read_job(os.path.join(handle.job_dir, "job.json"))
    assert failed_job["conservative_garment"] is True
    assert failed_job["sway_enable"] is True


@pytest.mark.parametrize("extra,expected", [
    ({"conservative_garment": True, "sway_enable": True,
      "sway_adaptation": "physbone-v1", "sway_intensity": "normal"}, True),
    ({"conservative_garment": True, "sway_enable": False}, False),
    ({"conservative_garment": True, "sway_enable": True, "sway_intensity": "normal"}, False),
    ({}, False),
])
def test_restoring_other_model_clears_unavailable_garment_mode(tmp_path, extra, expected):
    work = str(tmp_path / "work")
    directory = _write_job_dir(work, "Avatar", "C:/avatars/Avatar.fbx", **extra)
    fake = _FakeSelf(str(tmp_path / "app"), work)
    fake._conservative_garment_var = _FakeScale(True)
    mw.MainWindow._apply_restored_settings(fake, directory, set_vrm_path=False)
    assert fake._conservative_garment_var.get() is expected
    assert mw.MainWindow._garment_settings(fake) == {"conservative_garment": expected}


def test_new_model_does_not_inherit_experimental_opt_in(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    fake = _FakeSelf(str(app), str(tmp_path / "work"))
    fake._conservative_garment_var = _FakeScale(True)
    fake._set_vrm_path(str(tmp_path / "NewAvatar.fbx"))
    assert fake._conservative_garment_var.get() is False


def test_gui_convert_forwards_active_garment_option(tmp_path, monkeypatch):
    avatar = tmp_path / "avatar.fbx"
    avatar.touch()
    fake = _FakeSelfForStartPipeline(vrm_path=str(avatar), palworld_located=True)
    fake.work_root = str(tmp_path / "work")
    fake._conservative_garment_var = _FakeScale(True)
    fake.widgets["swayIntensityBar"] = _FakeEntry(str(mw.SWAY_INTENSITY_VALUES.index("auto")))
    calls = []
    monkeypatch.setattr(mw.pipeline_runner, "run_pipeline", lambda *a, **kw: calls.append(kw))
    mw.MainWindow._start_pipeline(fake, preview_only=False, materials_only=False)
    assert calls[0]["conservative_garment"] is True


def test_checkbox_is_off_and_fits_existing_physics_row(hidden_root, tmp_path):
    from test_main_window_lab_ui import _make_fake_self
    fake = _make_fake_self(hidden_root, str(tmp_path))
    fake._is_pipeline_running = False
    fake._blender_ready = True
    fake._work_root_failed = False
    fake.work_root = str(tmp_path / "work")
    mw.MainWindow._build_widgets(fake)
    check = fake.widgets["conservativeGarmentCheck"]
    assert fake._conservative_garment_var.get() is False
    geometry = check.place_info()
    assert int(geometry["x"]) >= 488
    assert int(geometry["x"]) + int(geometry["width"]) <= 1058
    assert int(geometry["y"]) + int(geometry["height"]) <= mw._KODAWARI_PANEL_HEIGHT
