"""Validate the staged interpreter, hidden Tk initialization and source manifest.

Run with any Python; the checks relaunch under the target's embedded interpreter
using the same isolated environment as its launcher. No conversion is started.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_local import CLEAR_ENVIRONMENT, RUNTIME_PATHS, isolated_environment, launcher_text


def validate(target: Path) -> dict:
    res = target / 'res'
    embed = res / 'python_embed'
    assert Path(sys.executable).resolve() == (embed / 'python.exe').resolve(), sys.executable
    assert sys.flags.isolated and sys.flags.ignore_environment
    assert 'site' not in sys.modules, 'Embedded Python unexpectedly enabled site packages'
    pth_files = list(embed.glob('*._pth'))
    assert len(pth_files) == 1, pth_files
    entries = [line.strip() for line in pth_files[0].read_text(encoding='utf-8-sig').splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
    assert entries == ['python311.zip', '.'], entries
    assert (target / 'UchinokoReborn.bat').read_text(encoding='ascii') == launcher_text()
    for name in CLEAR_ENVIRONMENT:
        assert not os.environ.get(name), name
    for name, rel in RUNTIME_PATHS.items():
        expected = (target / rel).resolve()
        assert Path(os.environ[name]).resolve() == expected, name
        assert expected.exists(), str(expected)
        assert expected.is_relative_to(res.resolve()), name

    # Tk maps its main window on the first event-loop iteration. Withdraw it
    # immediately after loading Tk, before processing events, so none is shown.
    import tkinter as tk
    root = tk.Tk(useTk=False)
    root.loadtk()
    root.withdraw()
    try:
        assert not root.winfo_ismapped()
        tcl_library = Path(root.tk.eval('info library')).resolve()
        tk_library = Path(root.tk.eval('set tk_library')).resolve()
        assert tcl_library == (embed / 'tcl/tcl8.6').resolve(), tcl_library
        assert tk_library == (embed / 'tcl/tk8.6').resolve(), tk_library
        tcl_version = root.tk.eval('info patchlevel')
        tk_version = root.tk.eval('package present Tk')
    finally:
        root.destroy()

    sys.path.insert(0, str(res / 'app'))
    sys.path.insert(0, str(res / 'pipeline/py'))
    import settings
    import blender_setup
    import update_check
    import inquiry
    from ui.main_window import REPAIR_VERSION, TOOL_VERSION

    manifest = json.loads((target / 'repair_build.json').read_text(encoding='utf8'))
    actual_sources = {
        path.relative_to(res).as_posix()
        for folder in ('app', 'pipeline', 'unity')
        for path in (res / folder).rglob('*')
        if path.is_file() and path.suffix in {'.py', '.ps1', '.cs', '.json'}
    }
    assert actual_sources == set(manifest['source_files']), 'Source manifest is incomplete'
    for rel, expected in manifest['source_files'].items():
        path = (res / rel).resolve()
        assert path.is_relative_to(res.resolve()), rel
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, rel
    assert TOOL_VERSION == 'v2.13.0'
    assert REPAIR_VERSION == 'v' + manifest['version']
    assert settings.load_autoapply(str(res)) is False
    blender = Path(blender_setup.find_blender(str(res))).resolve()
    assert blender.is_file() and blender.is_relative_to((res / 'assets/tools').resolve()), blender
    assert update_check._default_fetch_versions_json(TOOL_VERSION) is None
    assert not inquiry.send_report_payload('{}').ok
    assert (res / 'assets/third_party').is_dir()
    assert (res / 'pipeline/py/sway_abp_templates').is_dir()
    assert not (res / 'settings_lastvrm.txt').exists()
    return {'status': 'PASS', 'display_version': REPAIR_VERSION,
            'verified_source_files': len(manifest['source_files']),
            'python': sys.executable, 'tcl': tcl_version, 'tk': tk_version,
            'hidden_tk_initialized': True, 'runtime_paths_isolated': True,
            'automatic_game_installation': False, 'model_settings_copied': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('installation', type=Path)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    target = args.installation.resolve()
    if args.child:
        print(json.dumps(validate(target), ensure_ascii=False))
        return 0
    executable = target / 'res/python_embed/python.exe'
    result = subprocess.run(
        [str(executable), '-E', '-B', '-X', 'utf8', str(Path(__file__).resolve()),
         str(target), '--child'],
        cwd=target, env=isolated_environment(target),
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )
    print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='', file=sys.stderr)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
