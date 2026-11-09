"""Build or update a local repair installation using an existing licensed runtime.

This is a local development builder. It does not create a public distribution or
copy any avatar/work/settings files. Binary templates remain runtime inputs and
are not imported into the source repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
from datetime import datetime
import uuid

REPO=Path(__file__).resolve().parents[1]
VERSION = '2.13.0-reborn.13'
BLENDER_DIR = 'res/assets/tools/blender-4.3.2-windows-x64'
RUNTIME_PATHS = {
    'TCL_LIBRARY': 'res/python_embed/tcl/tcl8.6',
    'TK_LIBRARY': 'res/python_embed/tcl/tk8.6',
    'D2P_BLENDER_EXE': BLENDER_DIR + '/blender.exe',
    'D2P_OOZ_PYTHON': BLENDER_DIR + '/4.3/python/bin/python.exe',
    'D2P_SHARED_CACHE': 'res/work/_shared_cache',
    'BLENDER_USER_CONFIG': 'res/blender_user/config',
    'BLENDER_USER_SCRIPTS': 'res/blender_user/scripts',
    'BLENDER_USER_EXTENSIONS': 'res/blender_user/extensions',
    'BLENDER_USER_DATAFILES': 'res/blender_user/datafiles',
}
# Keep explicit Unity/PowerShell discovery overrides, but isolate conversion
# resources, development caches and Python/Blender module lookup from other installs.
CLEAR_ENVIRONMENT = (
    'PYTHONHOME', 'PYTHONPATH', 'TCLLIBPATH',
    'BLENDER_USER_RESOURCES', 'BLENDER_SYSTEM_RESOURCES',
    'BLENDER_SYSTEM_SCRIPTS', 'BLENDER_SYSTEM_DATAFILES', 'BLENDER_SYSTEM_PYTHON',
    'D2P_NOUE_TEMPLATE_ROOT', 'D2P_LAYER_CACHE', 'D2P_QUARANTINE_UE_ROOT',
    'D2P_JOB', 'D2P_STOP_BEFORE_NOUE', 'D2P_REPORT_BASEURL',
    'D2P_OOZ_SITE_PACKAGES', 'D2P_PYTHON311_DLL',
)

# JSON is also a common user-state format. Only these application-owned inputs
# may accompany source; a job/model/settings JSON must never become a default.
SOURCE_STATIC = {
    'app_py/i18n_data.json', 'pipeline/job.example.json',
    'pipeline/py/known_good_palworld.json', 'pipeline/py/noue_template_manifest.json',
    'pipeline/py/sway_known_moving_bones.json', 'pipeline/py/sway_root_amplitude.json',
    'pipeline/py/noue_master/shader_platform_facts.json',
    'pipeline/py/noue_master/stub_asset_ids.json',
    'pipeline/py/noue_master/pak_extract_extra/_vrm2palworld_anchor.txt',
    'pipeline/py/sway_abp_templates/README.md',
}
PRIVATE_DIRECTORIES = {'work', 'data', 'exports', 'logs', 'cache', '_shared_cache',
                       '__pycache__', '.pytest_cache', 'source_backups', 'tests'}


def source_files(root: Path):
    """Yield only converter code and reviewed static inputs from a source tree."""
    for top, destination in (('app_py', 'app'), ('pipeline', 'pipeline'), ('unity', 'unity')):
        for path in (root / top).rglob('*'):
            relative = path.relative_to(root)
            if (not path.is_file() or path.is_symlink()
                    or not path.resolve().is_relative_to(root.resolve())
                    or any(part in PRIVATE_DIRECTORIES or part.startswith('.') for part in relative.parts)):
                continue
            key = relative.as_posix()
            if path.name.startswith('test_'):
                continue
            allowed = path.suffix in {'.py', '.ps1', '.cs'} or key in SOURCE_STATIC
            allowed |= (relative.parent.as_posix() == 'pipeline/py/sway_abp_templates/specs'
                        and path.name.startswith('spec_') and path.suffix == '.json')
            if allowed:
                yield path, destination + '/' + path.relative_to(root / top).as_posix()


def isolated_environment(target: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in CLEAR_ENVIRONMENT:
        env.pop(name, None)
    env.update({name: str(target / rel) for name, rel in RUNTIME_PATHS.items()})
    return env


def launcher_text() -> str:
    lines = ['@echo off', 'setlocal', 'set "HERE=%~dp0"']
    lines.extend(f'set "{name}="' for name in CLEAR_ENVIRONMENT)
    for name, rel in RUNTIME_PATHS.items():
        lines.append(f'set "{name}=%HERE%{rel.replace(chr(47), chr(92))}"')
    lines.extend([
        'start "" "%HERE%res\\python_embed\\pythonw.exe" -E -X utf8 "%HERE%res\\app\\main.py"',
        'endlocal', '',
    ])
    return '\n'.join(lines)

def copy_tree(source: Path,destination: Path) -> None:
    shutil.copytree(source,destination,ignore=shutil.ignore_patterns(
        '__pycache__', '.pytest_cache', '_shared_cache', 'cache', 'logs',
        'settings_*.txt', 'settings_*.json', '*.log', '*.dmp',
        '*.pyc', '*.blend', '*.fbx', '*.vrm', '*.unitypackage', 'job.json', 'model.json'))

def build(installed: Path,target: Path) -> dict:
    installed=installed.resolve();target=target.resolve()
    runtime=installed/'res'
    if target.exists():
        raise ValueError(f'Target already exists; choose a new directory: {target}')
    if target.is_relative_to(installed) or installed.is_relative_to(target):
        raise ValueError('The repair install must be separate from the original install')
    required=[runtime/'python_embed/pythonw.exe',runtime/'assets/tools/blender-4.3.2-windows-x64/blender.exe',
              runtime/'licenses/UCHINOKO_LICENSE.txt',runtime/'pipeline/py/sway_abp_templates']
    required.extend(runtime/rel for rel in (
        'python_embed/python.exe', 'python_embed/python311._pth',
        'python_embed/tcl/tcl8.6/init.tcl', 'python_embed/tcl/tk8.6/tk.tcl',
        'assets/tools/blender-4.3.2-windows-x64/4.3/python/bin/python.exe',
    ))
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)
    if 'MIT License' not in required[2].read_text(encoding='utf-8-sig'):
        raise ValueError('The installed source license is not the expected MIT license')
    required_space=sum(p.stat().st_size for folder in ('python_embed','assets') for p in (runtime/folder).rglob('*') if p.is_file())+150_000_000
    if shutil.disk_usage(target.parent).free<required_space:
        raise OSError(f'Not enough free space for a separate runtime: need {required_space} bytes')
    target.mkdir()
    res=target/'res';res.mkdir()
    for source, relative in source_files(REPO):
        dest=res/relative
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dest)
    # These binary assets belong to the installed converter. Keep them out of
    # source control; the fork uses an exact copy only in this local installation.
    for template in ('py/noue_master','py/sway_abp_templates/cooked'):
        for src in (runtime/'pipeline'/template).rglob('*'):
            if (src.is_file() and src.suffix.lower() in {'.bin','.uasset','.uexp','.ubulk','.uptnl'}
                    and not any(part in PRIVATE_DIRECTORIES for part in src.relative_to(runtime/'pipeline').parts)):
                dst=res/'pipeline'/src.relative_to(runtime/'pipeline')
                dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    for folder in ('python_embed','assets','licenses'):
        copy_tree(runtime/folder,res/folder)
    # A new fork defaults to generating output without installing into the game.
    (res/'settings_autoapply.txt').write_text('false',encoding='utf-8')
    (res/'settings_language.txt').write_text('zh-CN',encoding='utf-8')
    for name, rel in RUNTIME_PATHS.items():
        if name.startswith('BLENDER_USER_') or name == 'D2P_SHARED_CACHE':
            (target/rel).mkdir(parents=True,exist_ok=True)
    (target/'UchinokoReborn.bat').write_text(launcher_text(),encoding='ascii')
    shutil.copy2(REPO/'LICENSE',target/'LICENSE')
    shutil.copy2(REPO/'README.md',target/'README.md')
    shutil.copy2(REPO/'README_REPAIR.md',target/'README_REPAIR.md')
    (target/'repair').mkdir()
    for document in (REPO/'repair').glob('*.md'):
        shutil.copy2(document,target/'repair'/document.name)
    manifest={'format':1,'version':VERSION,'kind':'local-development-installation',
              'public_distribution':False,'source_files':{}}
    for folder in ('app','pipeline','unity'):
        for path in (res/folder).rglob('*'):
            if path.is_file() and path.suffix in {'.py','.ps1','.cs','.json'}:
                manifest['source_files'][path.relative_to(res).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    (target/'repair_build.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {'target':str(target),'source_files':len(manifest['source_files']),'version':manifest['version']}


def update(target: Path) -> dict:
    """Update managed source only, keeping the runtime, settings and work intact.

    Refuse to overwrite locally changed source. A small, durable source backup
    supports rollback without duplicating Python, Blender or model data.
    """
    target = target.resolve()
    manifest_path = target / 'repair_build.json'
    old = json.loads(manifest_path.read_text(encoding='utf-8'))
    if old.get('kind') != 'local-development-installation':
        raise ValueError('Only a managed Uchinoko Reborn installation can be updated')
    if not (target / 'res/python_embed/pythonw.exe').is_file():
        raise FileNotFoundError(target / 'res/python_embed/pythonw.exe')

    def checked(relative: str) -> Path:
        path = target / relative
        if not path.resolve().is_relative_to(target) or path == target:
            raise ValueError(f'Unsafe managed source path: {relative}')
        return path

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    old_sources = old['source_files']
    installed_static = {('app/' + key[len('app_py/'):] if key.startswith('app_py/') else key)
                        for key in SOURCE_STATIC}
    for relative, expected in old_sources.items():
        parts = Path(relative).parts
        if (not parts or parts[0] not in {'app', 'pipeline', 'unity'} or '..' in parts
                or (Path(relative).suffix not in {'.py', '.ps1', '.cs', '.json'}
                    and relative not in installed_static)):
            raise ValueError(f'Unsafe managed source path: {relative}')
        path = checked('res/' + relative)
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f'Installed source was modified; keep it before updating: {path}')
    payload = {}
    new_sources = {}
    for path, key in source_files(REPO):
        content = path.read_bytes()
        new_sources[key] = hashlib.sha256(content).hexdigest()
        installed = checked('res/' + key)
        if key not in old_sources and installed.exists() and digest(installed) != new_sources[key]:
            raise ValueError(f'Unmanaged file would be overwritten: {installed}')
        payload['res/' + key] = content
    payload['UchinokoReborn.bat'] = launcher_text().encode('ascii')
    for name in ('LICENSE', 'README.md', 'README_REPAIR.md'):
        payload[name] = (REPO / name).read_bytes()
    for path in (REPO / 'repair').glob('*.md'):
        payload['repair/' + path.name] = path.read_bytes()
    current = dict(old, format=1, version=VERSION, source_files=new_sources)
    current.pop('source_repository', None)
    current.pop('runtime_source', None)
    payload['repair_build.json'] = (json.dumps(current, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    removed = {'res/' + key for key in old_sources if key not in new_sources}
    changed = {key: value for key, value in payload.items()
               if not checked(key).exists() or checked(key).read_bytes() != value}
    if not changed and not removed:
        return {'target': str(target), 'version': VERSION, 'changed': 0}
    # Finish all path and space checks before making changes.
    affected = sorted(set(changed) | removed)
    existing = [key for key in affected if checked(key).exists()]
    needed = sum(checked(key).stat().st_size for key in existing) + sum(map(len, changed.values()))
    if shutil.disk_usage(target).free < needed + 5_000_000:
        raise OSError(f'Not enough space for the source update and rollback: need {needed} bytes')
    backup = checked('repair/source_backups/' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
    backup.mkdir(parents=True)
    for key in existing:
        dest = backup / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(checked(key), dest)
    (backup / 'rollback.json').write_text(json.dumps({'existing': existing, 'affected': affected}, indent=2), encoding='utf-8')
    temporary = []
    applied = []
    try:
        for key, content in changed.items():
            destination = checked(key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging = destination.with_name(destination.name + '.update-' + uuid.uuid4().hex)
            temporary.append(staging)
            staging.write_bytes(content)
            os.replace(staging, destination)
            applied.append(key)
        for key in removed:
            checked(key).unlink()
            applied.append(key)
    except BaseException:
        for key in reversed(applied):
            destination = checked(key)
            if key in existing:
                shutil.copy2(backup / key, destination)
            elif destination.exists():
                destination.unlink()
        raise
    finally:
        for path in temporary:
            if path.exists():
                path.unlink()
    return {'target': str(target), 'version': VERSION, 'changed': len(changed),
            'removed': len(removed), 'source_files': len(new_sources), 'backup': str(backup)}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--update',action='store_true',help='Update source in an existing installation, preserving runtime and models')
    args=parser.parse_args()
    if not args.update and args.installed is None:
        parser.error('--installed is required when creating an installation')
    print(json.dumps(update(args.output) if args.update else build(args.installed,args.output),ensure_ascii=False,indent=2))
