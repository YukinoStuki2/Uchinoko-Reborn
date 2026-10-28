"""An open source project uses its Editor; no second Editor or project copy."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app_py"))
import unity_editor_bridge as bridge


@pytest.mark.skipif(os.name != "nt", reason="Exercises the real Unity Windows file lock")
@pytest.mark.parametrize("helper_directory", ["app_py", "app"])
def test_export_command_routes_locked_project_to_existing_editor(tmp_path, helper_directory):
    """Run the production PS entry point with an exclusive UnityLockfile handle.

    Unity and the Python bridge are stand-ins; routing, resolver, and Windows
    sharing violation are real. The old command exits with 'Close Unity'.
    """
    app = tmp_path / "app"
    cli = app / "pipeline" / "cli"
    cli.mkdir(parents=True)
    script = cli / "export_from_unity.ps1"
    shutil.copyfile(ROOT / "pipeline" / "cli" / script.name, script)
    resolver = app / "pipeline" / "py" / "dep_resolver.py"
    resolver.parent.mkdir()
    resolver.write_text("import sys\nprint('D2P_RESOLVED: ' + sys.executable)\n", encoding="utf-8")
    helper = app / helper_directory / "unity_editor_bridge.py"
    helper.parent.mkdir()
    helper.write_text("print('EXISTING_EDITOR_SELECTED')\n", encoding="utf-8")
    project = tmp_path / "avatar [测试]"
    (project / "Assets").mkdir(parents=True)
    prefab = project / "Assets" / "avatar.prefab"
    prefab.write_text("fixture", encoding="utf-8")
    (project / "ProjectSettings").mkdir()
    (project / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 2022.3.22f1\n")
    (project / "Temp").mkdir()
    lock = project / "Temp" / "UnityLockfile"
    lock.touch()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(lock), 0x80000000, 0, None, 3, 0x80, None)
    assert handle not in (None, ctypes.c_void_p(-1).value)
    try:
        result = subprocess.run([shutil.which("pwsh") or "powershell", "-NoProfile", "-File",
                                 str(script), "-Prefab", str(prefab), "-Out", str(tmp_path / "out")],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
    finally:
        kernel.CloseHandle(handle)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "EXISTING_EDITOR_SELECTED" in result.stdout


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "project [测试]"
    (path / "Assets").mkdir(parents=True)
    (path / "Assets/avatar.prefab").write_text("saved prefab", encoding="utf-8")
    (path / "ProjectSettings").mkdir()
    (path / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 2022.3.22f1")
    return path


def test_bridge_install_updates_owned_sources_and_preserves_local_edits(project, tmp_path):
    original = bridge.install_bridge(project, ROOT)
    target = project / bridge.INSTALL_REL / "DiveToPalworldExporter.cs"
    assert target.read_text(encoding="utf-8").startswith("namespace Uchinoko.Reborn.EditorExport")
    assert bridge.install_bridge(project, ROOT) == original
    target.write_text("user edit", encoding="utf-8")
    with pytest.raises(RuntimeError, match="local edits"):
        bridge.install_bridge(project, ROOT)
    with pytest.raises(RuntimeError, match="local edits"):
        bridge.remove_bridge(project)
    assert target.read_text() == "user edit"


def test_unowned_install_folder_is_not_overwritten(project):
    target = project / bridge.INSTALL_REL
    target.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="not owned"):
        bridge.install_bridge(project, ROOT)


def test_remove_bridge_preserves_unrelated_files_and_logs(project):
    bridge.install_bridge(project, ROOT)
    extra = project / bridge.INSTALL_REL / "keep.txt"
    extra.write_text("user data")
    bridge.remove_bridge(project)
    assert extra.read_text() == "user data"
    assert not (extra.parent / "DiveToPalworldExporter.cs").exists()


def test_only_saved_prefab_from_same_project_and_external_output(project, tmp_path):
    outside = tmp_path / "outside.prefab"
    outside.write_text("other project")
    with pytest.raises(ValueError, match="Assets"):
        bridge.validate_paths(project, outside, tmp_path / "out")
    with pytest.raises(ValueError, match="saved .prefab"):
        bridge.validate_paths(project, ROOT / "app_py/unity_editor_bridge.py", tmp_path / "out")
    with pytest.raises(ValueError, match="outside"):
        bridge.validate_paths(project, project / "Assets/avatar.prefab", project / "export")


def test_request_completion_requires_matching_id_and_complete_export(project, tmp_path):
    fingerprint = bridge.install_bridge(project, ROOT)
    state = project / bridge.STATE_REL
    bridge._write_json(state / "ready.json", {"fingerprint": fingerprint})
    bridge._write_json(state / "result.json", {"id": "old-request", "status": "done"})
    out = tmp_path / "output"
    observed = []

    def editor():
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            request = bridge._read_json(state / "request.json")
            if request:
                observed.append(request)
                (out / "avatar.fbx").write_bytes(b"FBX fixture")
                (out / "humanoid.json").write_text("{}")
                bridge._write_json(state / "result.json", {"id": request["id"], "status": "done"})
                return
            time.sleep(.01)

    thread = threading.Thread(target=editor)
    thread.start()
    try:
        bridge.export_open_project(project, project / "Assets/avatar.prefab", out, ROOT, timeout=3, poll=.01)
    finally:
        thread.join(timeout=4)
    assert len(observed) == 1
    assert observed[0]["prefab"] == "Assets/avatar.prefab"
    assert observed[0]["clientPid"] == os.getpid()
    assert not (state / "request.json").exists()


def test_timeout_removes_deferred_request(project, tmp_path):
    fingerprint = bridge.install_bridge(project, ROOT)
    state = project / bridge.STATE_REL
    bridge._write_json(state / "ready.json", {"fingerprint": fingerprint})
    with pytest.raises(TimeoutError):
        bridge.export_open_project(project, project / "Assets/avatar.prefab", tmp_path / "out", ROOT, timeout=.05, poll=.01)
    assert not (state / "request.json").exists()


def test_simultaneous_client_is_rejected(project):
    with bridge._client_lock(project / bridge.STATE_REL):
        with pytest.raises((RuntimeError, OSError)):
            with bridge._client_lock(project / bridge.STATE_REL):
                pytest.fail("second export entered the same project")


def test_cancelled_client_cannot_update_or_remove_an_inflight_editor_export(project, tmp_path):
    bridge.install_bridge(project, ROOT)
    state = project / bridge.STATE_REL
    bridge._write_json(state / "running.json", {"id": "in-flight", "editorPid": os.getpid()})
    for operation in (
        lambda: bridge.install_bridge(project, ROOT),
        lambda: bridge.remove_bridge(project),
        lambda: bridge.export_open_project(project, project / "Assets/avatar.prefab", tmp_path / "out", ROOT, timeout=.01),
    ):
        with pytest.raises(RuntimeError, match="still finishing"):
            operation()
    assert (project / bridge.INSTALL_REL / "DiveToPalworldExporter.cs").is_file()


def test_stopped_editor_record_does_not_block_future_export(project, monkeypatch):
    bridge.install_bridge(project, ROOT)
    state = project / bridge.STATE_REL
    bridge._write_json(state / "running.json", {"id": "old", "editorPid": 123})
    monkeypatch.setattr(bridge, "_process_alive", lambda pid: False)
    bridge.install_bridge(project, ROOT)
    assert not (state / "running.json").exists()


def test_uninstall_never_deletes_user_edited_unity_metadata(project):
    bridge.install_bridge(project, ROOT)
    meta = project / bridge.INSTALL_REL / "DiveToPalworldExporter.cs.meta"
    meta.write_text("user edited metadata")
    bridge.remove_bridge(project)
    assert meta.read_text() == "user edited metadata"
    bridge.install_bridge(project, ROOT)
    assert (meta.parent / "DiveToPalworldExporter.cs").is_file()
    assert meta.read_text() == "user edited metadata"
