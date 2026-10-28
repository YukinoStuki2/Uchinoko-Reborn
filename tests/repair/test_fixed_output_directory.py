"""Fixed output settings survive updates and never mutate linked historical jobs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app_py"))
import settings
import pipeline_runner
import pak_manager
import warm_startup
import work_paths
from ui import main_window as mw


@pytest.fixture(autouse=True)
def isolate_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("UCHINOKO_REBORN_SETTINGS_DIR", str(tmp_path / "shared-settings"))
    monkeypatch.setattr(pipeline_runner, "find_blender", lambda _: "blender.exe")
    monkeypatch.setattr(pipeline_runner, "paks_dir_quiet", lambda _: None)


def bare(app_root):
    window = mw.MainWindow.__new__(mw.MainWindow)
    window.app_root = str(app_root)
    return window


def test_shared_setting_survives_new_install_path(tmp_path):
    chosen = str(tmp_path / "模型 outputs")
    settings.save_work_root(chosen)
    old, new = bare(tmp_path / "version3"), bare(tmp_path / "version4")
    assert old._resolve_work_root() == new._resolve_work_root() == chosen
    assert not (tmp_path / "version4" / "work").exists()
    assert new._work_root_configured and not new._work_root_failed


def test_explicit_unwritable_root_never_falls_back(tmp_path, monkeypatch):
    chosen = str(tmp_path / "unavailable")
    settings.save_work_root(chosen)
    window = bare(tmp_path / "application")
    monkeypatch.setattr(window, "_probe_work_root", lambda _: "access denied")
    assert window._resolve_work_root() == chosen
    assert window._work_root_failed and not window._work_root_used_fallback
    assert not (tmp_path / "application" / "work").exists()


@pytest.mark.parametrize("bad", ["", "relative/work", "C:\\one\nC:\\two"])
def test_invalid_explicit_setting_disables_instead_of_using_default(tmp_path, bad):
    location = Path(settings.work_root_file())
    location.parent.mkdir(parents=True)
    location.write_text(bad, encoding="utf8")
    window = bare(tmp_path / "application")
    assert window._resolve_work_root() == ""
    assert window._work_root_failed
    assert not (tmp_path / "application" / "work").exists()


def test_missing_setting_preserves_legacy_default(tmp_path):
    window = bare(tmp_path / "application")
    assert window._resolve_work_root() == str(tmp_path / "application" / "work")
    assert not window._work_root_configured


def test_busy_switch_and_failed_save_leave_current_root_intact(tmp_path, monkeypatch):
    window = bare(tmp_path / "app")
    current = str(tmp_path / "current")
    settings.save_work_root(current)
    window.work_root = current
    window._is_pipeline_running = True
    window._log = lambda _: None
    notices = []
    monkeypatch.setattr(mw.messagebox, "showinfo", lambda *a: notices.append(a))
    monkeypatch.setattr(mw.messagebox, "showerror", lambda *a: notices.append(a))
    assert window._apply_output_directory(str(tmp_path / "other")) is False
    window._is_pipeline_running = False
    window._warm_cache_status = warm_startup.WarmCacheStatus()
    window._warm_cache_status.mark_started()
    assert window._apply_output_directory(str(tmp_path / "other")) is False
    window._warm_cache_status.mark_done(0)
    monkeypatch.setattr(settings, "save_work_root", lambda _: (_ for _ in ()).throw(PermissionError("readonly")))
    assert window._apply_output_directory(str(tmp_path / "other")) is False
    assert window.work_root == settings.load_work_root() == current
    assert len(notices) == 3


def test_invalid_root_blocks_direct_conversion_export_and_cache(tmp_path):
    window = bare(tmp_path / "app")
    window._work_root_failed = True
    window._log = lambda _: None
    # These methods return before accessing controls or invoking any process.
    window._start_pipeline(preview_only=True, materials_only=False, auto=True)
    window._on_prefab_selected(str(tmp_path / "test.prefab"))
    window._warm_startup_after_blender_ready()


@pytest.fixture
def tkinter_root():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    yield root
    root.destroy()


def test_real_settings_dialog_to_job_export_list_restore_delete_chain(tmp_path, monkeypatch, tkinter_root):
    import tkinter as tk
    from tkinter import ttk
    from ui.work_root_dialog import WorkRootDialog

    app_root = tmp_path / "version4" / "res"
    app_root.mkdir(parents=True)
    source = tmp_path / "SourceModel.prefab"
    source.write_text("prefab", encoding="utf8")
    window = bare(app_root)
    window.root = tkinter_root
    window.work_root = str(app_root / "work")
    window._work_root_failed = False
    window._is_pipeline_running = False
    window._blender_ready = False
    window._active_handle = None
    window._pak_paths = {}
    window._pak_candidates = []
    window._shoulder_offset_deg = 0
    window._merge_fingers = window._unlit = window._license_confirmed = False
    window._force_two_sided = True
    window._log = lambda _: None
    window._on_update_applied_status = lambda: None
    window._refresh_lab_warning = lambda: None
    previews = []
    window._apply_previews = previews.append
    window.widgets = {key: tk.Entry(tkinter_root) for key in ("vrmBox", "dropBonesBox")}
    window.widgets.update({key: tk.Label(tkinter_root) for key in
                           ("previewFront", "previewSide", "outputDirectoryLabel", "swayIntensityValueLabel")})
    window.widgets.update({key: tk.Button(tkinter_root) for key in ("convertButton", "previewButton", "matsButton")})
    window.widgets.update({key: tk.Scale(tkinter_root, from_=0, to=200) for key in
                           ("shadowBar", "heightScaleBar", "swayIntensityBar")})
    window.widgets["pakList"] = ttk.Treeview(tkinter_root, columns=("name", "file", "size", "date"))
    window.widgets["vrmBox"].insert(0, str(source))
    window.widgets["heightScaleBar"].set(100)
    output = tmp_path / "fixed-models"
    dialog = WorkRootDialog(tkinter_root, window.work_root, window._apply_output_directory)
    dialog.withdraw()
    dialog.path_var.set(str(output))
    dialog.save_button.invoke()
    assert window.work_root == settings.load_work_root() == str(output)
    assert window.widgets["outputDirectoryLabel"]["text"] == str(output)

    # Actual job writer, and actual export launcher with only process execution replaced.
    job_path = Path(pipeline_runner.write_job(str(app_root), window.work_root, str(source),
                                            shoulder_offset_deg=12, uniform_scale=1.2))
    assert job_path == output / "SourceModel" / "job.json"
    class Handle:
        def __init__(self, shell, args, *callbacks): self.args = args
        def start(self): pass
    monkeypatch.setattr(pipeline_runner, "ProcessHandle", Handle)
    monkeypatch.setattr(pipeline_runner, "find_pwsh", lambda *a, **k: "pwsh")
    handle = pipeline_runner.run_unity_export(str(app_root), window.work_root, str(source),
                                             on_line=lambda _: None, on_exit=lambda _: None)
    assert handle.out_dir == str(output / "SourceModel_export")
    assert str(output / "SourceModel_export") in handle.args
    pak = job_path.parent / "build" / "SourceModel_PlayerSwap_P.pak"
    pak.parent.mkdir()
    pak.write_bytes(b"test")
    window._on_refresh_pak_list()
    assert list(window._pak_paths.values()) == [str(pak)]
    assert window._apply_restored_settings(str(job_path.parent), set_vrm_path=True)
    assert window._shoulder_offset_deg == 12
    assert window.widgets["heightScaleBar"].get() == 120
    assert previews
    new_install = bare(tmp_path / "version5" / "res")
    assert new_install._resolve_work_root() == str(output)
    targets = pak_manager.resolve_delete_targets(window.work_root, str(app_root), str(pak))
    assert targets["job_dir"] == str(job_path.parent)
    assert window._palworld_manifest_breadcrumb_path() == str(output / "_warm_dummy" / "vanilla" / "vanilla_manifest.json")
    assert not (app_root / "work").exists()


def junction(link, target):
    if os.name != "nt":
        link.symlink_to(target, target_is_directory=True)
        return
    def quote(value): return "'" + str(value).replace("'", "''") + "'"
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                             f"New-Item -ItemType Junction -Path {quote(link)} -Target {quote(target)} | Out-Null"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_historical_junction_lists_and_reads_but_cannot_be_overwritten_or_cleaned(tmp_path):
    archive = tmp_path / "other-drive-history" / "OldModel"
    archive.mkdir(parents=True)
    marker = archive / "keep.txt"
    marker.write_text("keep", encoding="utf8")
    (archive / "job.json").write_text('{"avatar_name":"OldModel"}', encoding="utf8")
    (archive / "build").mkdir()
    (archive / "build" / "OldModel_PlayerSwap_P.pak").write_bytes(b"pak")
    root = tmp_path / "model-root"
    root.mkdir()
    link = root / "OldModel"
    junction(link, archive)
    assert work_paths.is_directory_link(str(link))
    assert pipeline_runner.read_job(str(link / "job.json"))["avatar_name"] == "OldModel"
    assert pak_manager.list_built_paks(str(root))[0][0] == str(link / "build" / "OldModel_PlayerSwap_P.pak")
    with pytest.raises(ValueError, match="historical"):
        pipeline_runner.write_job(str(tmp_path / "app"), str(root), str(tmp_path / "OldModel.prefab"))
    pipeline_runner._clean_job_dir_for_retry(str(link))
    assert link.exists() and marker.read_text(encoding="utf8") == "keep"
    targets = pak_manager.resolve_delete_targets(str(root), str(tmp_path / "app"),
                                                str(link / "build" / "OldModel_PlayerSwap_P.pak"))
    assert targets == {"job_dir": str(link), "ue_project_dir": None}
    pak_manager.delete_avatar_artifacts(**targets)
    assert not link.exists()
    assert marker.read_text(encoding="utf8") == "keep"


def test_delete_target_must_be_direct_child_of_selected_root(tmp_path):
    with pytest.raises(ValueError):
        pak_manager.resolve_delete_targets(str(tmp_path / "selected"), str(tmp_path),
                                           str(tmp_path / "elsewhere" / "Model" / "build" / "x.pak"))


def test_linked_unity_export_is_rejected_before_process_start(tmp_path):
    archive = tmp_path / "old-export"
    archive.mkdir()
    root = tmp_path / "models"
    root.mkdir()
    junction(root / "Model_export", archive)
    try:
        with pytest.raises(ValueError, match="historical"):
            pipeline_runner.run_unity_export(str(tmp_path), str(root), "Model.prefab",
                                             on_line=lambda _: None, on_exit=lambda _: None)
    finally:
        pak_manager.delete_avatar_artifacts(str(root / "Model_export"))


def test_warm_worker_freezes_selected_root_and_blocks_switch_until_child_started(tmp_path, monkeypatch):
    window = bare(tmp_path / "app")
    window.work_root = str(tmp_path / "models")
    window._active_handle = None
    window._warm_cache_status = warm_startup.WarmCacheStatus()
    window._paks_dir_cache = None
    captured = []
    class DeferredThread:
        def __init__(self, target, **kwargs): captured.append(target)
        def start(self): pass
    monkeypatch.setattr(mw.threading, "Thread", DeferredThread)
    monkeypatch.setattr(mw.blender_setup, "find_blender", lambda _: "blender.exe")
    monkeypatch.setattr(mw.pak_manager, "paks_dir_quiet", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(warm_startup, "warm_startup_after_blender_ready",
                        lambda app, root, *a, **kw: calls.append((app, root, kw)))
    window._warm_startup_after_blender_ready()
    assert window._work_root_change_busy()
    captured[0]()
    assert calls[0][1] == window.work_root
    assert calls[0][2]["status"] is window._warm_cache_status
    assert not window._work_root_change_busy()


@pytest.mark.parametrize("override", [None, "separate-cache"])
def test_ui_caches_use_same_root_as_pipeline(tmp_path, monkeypatch, override):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "py"))
    import vp_core
    if override:
        monkeypatch.setenv("D2P_SHARED_CACHE", str(tmp_path / override))
    else:
        monkeypatch.delenv("D2P_SHARED_CACHE", raising=False)
    assert work_paths.shared_cache_root(str(tmp_path / "models")) == vp_core.shared_cache_root(str(tmp_path / "models"))
