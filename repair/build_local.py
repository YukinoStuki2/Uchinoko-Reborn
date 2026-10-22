"""Build a separate local repair installation using an existing licensed runtime.

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

REPO=Path(__file__).resolve().parents[1]
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
    shutil.copytree(source,destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc','tests'))

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
    for source,dest in [('app_py','app'),('pipeline','pipeline'),('unity','unity')]:
        copy_tree(REPO/source,res/dest)
    # These binary assets belong to the installed converter. Keep them out of
    # source control; the fork uses an exact copy only in this local installation.
    for src in (runtime/'pipeline').rglob('*'):
        if src.is_file() and src.suffix.lower() in {'.bin','.uasset','.uexp','.ubulk','.uptnl'}:
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
    shutil.copy2(REPO/'repair/VALIDATION.md',target/'repair/VALIDATION.md')
    manifest={'format':1,'version':'2.13.0-reborn.1','kind':'local-development-installation',
              'source_repository':str(REPO),'runtime_source':str(installed),
              'public_distribution':False,'source_files':{}}
    for folder in ('app','pipeline','unity'):
        for path in (res/folder).rglob('*'):
            if path.is_file() and path.suffix in {'.py','.ps1','.cs','.json'}:
                manifest['source_files'][path.relative_to(res).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    (target/'repair_build.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {'target':str(target),'source_files':len(manifest['source_files']),'version':manifest['version']}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.installed,args.output),ensure_ascii=False,indent=2))
