"""Export through an already open Unity Editor using a local, fixed file protocol.

Only three small Editor scripts are installed. No project/Library copy, process
termination, Unity lock removal, scene save, socket, or arbitrary method dispatch.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

SCRIPTS = ("D2PConstraintDiag.cs", "DiveToPalworldExporter.cs", "UchinokoEditorBridge.cs")
INSTALL_REL = Path("Assets/Editor/UchinokoRebornBridge")
STATE_REL = Path("Library/UchinokoRebornBridge")
OWNER = "uchinoko-reborn-editor-bridge-v1"


def _write_json(path: Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # Access denied is not evidence that an Editor has stopped.
            return ctypes.get_last_error() == 5
        try:
            code = ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _ensure_editor_idle(state: Path) -> None:
    path = state / "running.json"
    if not path.exists():
        return
    running = _read_json(path)
    try:
        pid = int(running["editorPid"])
    except (KeyError, ValueError, TypeError):
        raise RuntimeError("Cannot verify the Editor export state; check Unity before retrying")
    if _process_alive(pid):
        raise RuntimeError("Unity is still finishing the previous export; wait for its completion before retrying or removing the bridge")
    path.unlink(missing_ok=True)


def validate_paths(project: Path, prefab: Path, out: Path) -> tuple[Path, Path, Path]:
    project, prefab, out = (p.resolve() for p in (project, prefab, out))
    if not (project / "ProjectSettings/ProjectVersion.txt").is_file():
        raise ValueError("Not a Unity project")
    if not prefab.is_file() or prefab.suffix.lower() != ".prefab":
        raise ValueError("Select a saved .prefab file")
    if not prefab.is_relative_to((project / "Assets").resolve()):
        raise ValueError("Prefab must be inside this project's Assets folder")
    if out == project or out.is_relative_to(project):
        raise ValueError("Export output must be outside the Unity project")
    if str(project).startswith("\\\\") or str(out).startswith("\\\\"):
        raise ValueError("The open Editor bridge requires local project and output paths")
    return project, prefab, out


@contextmanager
def _client_lock(state: Path):
    """OS-owned lock automatically releases if a client is cancelled or killed."""
    state.mkdir(parents=True, exist_ok=True)
    with (state / "client.lock").open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Another Uchinoko export is using this Unity project") from exc
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def install_bridge(project: Path, app_root: Path) -> str:
    """Maintain only our owned scripts; preserve a backup before each update."""
    destination = project / INSTALL_REL
    state = project / STATE_REL
    state.mkdir(parents=True, exist_ok=True)
    _ensure_editor_idle(state)
    manifest = destination / "ownership.json"
    previous = _read_json(manifest)
    if destination.exists() and previous.get("owner") != OWNER:
        raise RuntimeError("Bridge destination exists and is not owned by Uchinoko Reborn")
    payload = {}
    for name in SCRIPTS:
        source = (app_root / "unity" / name).read_bytes()
        if name != "UchinokoEditorBridge.cs":
            # Isolate from a manually installed exporter and the batch exporter.
            source = b"namespace Uchinoko.Reborn.EditorExport {\n" + source + b"\n}\n"
        payload[name] = source
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    changed = []
    for name, data in payload.items():
        target = destination / name
        if target.exists():
            old = target.read_bytes()
            if hashlib.sha256(old).hexdigest() != previous.get("files", {}).get(name):
                raise RuntimeError("Bridge script has local edits; preserve them before updating: " + name)
            if old == data:
                continue
        changed.append(name)
    digest = hashlib.sha256("".join(hashes[n] for n in SCRIPTS).encode("ascii")).hexdigest()
    if changed:
        (state / "ready.json").unlink(missing_ok=True)
        destination.mkdir(parents=True, exist_ok=True)
        if previous:
            backup = state / "backups" / (str(time.time_ns()))
            backup.mkdir(parents=True)
            for name in SCRIPTS:
                if (destination / name).exists():
                    (backup / name).write_bytes((destination / name).read_bytes())
            (backup / "ownership.json").write_bytes(manifest.read_bytes())
        # Bridge is written last, after its implementation dependencies.
        for name in changed:
            (destination / name).write_bytes(payload[name])
        _write_json(manifest, {"owner": OWNER, "files": hashes})
    return digest


def remove_bridge(project: Path) -> None:
    """Remove only files matching our ownership record; retain diagnostics/backups."""
    project = project.resolve()
    if not (project / "ProjectSettings/ProjectVersion.txt").is_file():
        raise ValueError("Not a Unity project")
    destination = project / INSTALL_REL
    state = project / STATE_REL
    with _client_lock(state):
        _ensure_editor_idle(state)
        manifest = destination / "ownership.json"
        previous = _read_json(manifest)
        if previous.get("owner") != OWNER:
            raise RuntimeError("No owned Uchinoko Reborn Editor bridge found")
        for name in SCRIPTS:
            path = destination / name
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != previous.get("files", {}).get(name):
                raise RuntimeError("Bridge script has local edits; no files removed: " + name)
        # No recursive removal: unrelated files in this folder remain untouched.
        for name in SCRIPTS:
            (destination / name).unlink(missing_ok=True)
            # Unity owns .meta files; retain them rather than removing metadata
            # which a user may have edited. Unity removes orphan metas on refresh.
        remaining = [p for p in destination.iterdir() if p.name != "ownership.json"]
        if not remaining:
            manifest.unlink()
            destination.rmdir()
        else:
            # Keep ownership when Unity metadata remains, so reinstalling can
            # distinguish our removed bridge from an unrelated existing folder.
            _write_json(manifest, {**previous, "removed": True})
        (state / "request.json").unlink(missing_ok=True)
        (state / "ready.json").unlink(missing_ok=True)


def export_open_project(project: Path, prefab: Path, out: Path, app_root: Path,
                        timeout: float = 600, poll: float = 0.5) -> None:
    project, prefab, out = validate_paths(project, prefab, out)
    state = project / STATE_REL
    with _client_lock(state):
        fingerprint = install_bridge(project, app_root)
        request_id = uuid.uuid4().hex
        request = state / "request.json"
        result_file = state / "result.json"
        deadline = time.monotonic() + timeout
        print("[editor-bridge] Using the open Unity project. Save prefab changes first; scenes are never saved.", flush=True)
        print("[editor-bridge] Focus Unity once to import the bridge. If Auto Refresh is off, use Assets > Refresh (Ctrl+R).", flush=True)
        queued = False
        last_status = None
        try:
            while time.monotonic() < deadline:
                ready = _read_json(state / "ready.json")
                if not queued and ready.get("fingerprint") == fingerprint:
                    out.mkdir(parents=True, exist_ok=True)
                    _write_json(request, {"protocol": 1, "id": request_id,
                        "prefab": prefab.relative_to(project).as_posix(), "output": str(out),
                        "expiresUtc": int(time.time() + max(1, deadline - time.monotonic())),
                        "clientPid": os.getpid(), "fingerprint": fingerprint})
                    queued = True
                result = _read_json(result_file)
                if result.get("id") == request_id:
                    status = result.get("status")
                    if status != last_status:
                        print("[editor-bridge] " + str(result.get("message", status)), flush=True)
                        last_status = status
                    if status == "done":
                        if not any(out.glob("*.fbx")) or not (out / "humanoid.json").is_file():
                            raise RuntimeError("Editor reported success without complete export files")
                        print("D2P_EXPORT_DONE " + str(out), flush=True)
                        return
                    if status == "error":
                        raise RuntimeError(str(result.get("message", "Unity export failed")))
                time.sleep(poll)
            raise TimeoutError("Unity did not finish the export. Focus Unity, leave Play mode, and check Console for compile errors; then retry. No project lock was removed.")
        finally:
            # Cancellation must not leave a request that unexpectedly runs later.
            if _read_json(request).get("id") == request_id:
                request.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--prefab", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--app-root", type=Path)
    parser.add_argument("--remove", action="store_true", help="Remove owned bridge scripts only")
    args = parser.parse_args()
    try:
        if args.remove:
            remove_bridge(args.project)
        elif args.prefab and args.out and args.app_root:
            export_open_project(args.project, args.prefab, args.out, args.app_root)
        else:
            parser.error("Export requires --prefab, --out and --app-root")
    except (OSError, ValueError, RuntimeError) as exc:
        print("[editor-bridge] ERROR: " + str(exc), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
