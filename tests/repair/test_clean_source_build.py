"""A fresh build must not inherit the maintainer's model library or settings."""
import importlib.util
import json
from pathlib import Path


spec = importlib.util.spec_from_file_location('clean_reborn_builder', Path(__file__).parents[2] / 'repair/build_local.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf8')


def test_fresh_build_has_no_inherited_model_records_or_machine_paths(tmp_path, monkeypatch):
    repo, installed, target = (tmp_path / name for name in ('source', 'old-install', 'new-install'))
    for relative in ('LICENSE', 'README.md', 'README_REPAIR.md', 'repair/USAGE.md',
                     'app_py/main.py', 'pipeline/convert.py', 'unity/Exporter.cs'):
        write(repo, relative, 'public source')
    write(repo, 'app_py/i18n_data.json', '{"en": {}}')
    for relative in ('app_py/model.json', 'pipeline/job.json', 'pipeline/settings_private.json',
                     'pipeline/work/PrivateAvatar/private.py', 'app_py/tests/test_private.py'):
        write(repo, relative, 'private source state')
    for relative in ('python_embed/pythonw.exe', 'python_embed/python.exe', 'python_embed/python311._pth',
                     'python_embed/tcl/tcl8.6/init.tcl', 'python_embed/tcl/tk8.6/tk.tcl',
                     builder.BLENDER_DIR.removeprefix('res/') + '/blender.exe',
                     builder.BLENDER_DIR.removeprefix('res/') + '/4.3/python/bin/python.exe',
                     'pipeline/py/sway_abp_templates/cooked/template.bin',
                     'pipeline/py/noue_master/stub_uexp_scaffold.bin'):
        write(installed / 'res', relative, 'runtime template')
    write(installed / 'res', 'licenses/UCHINOKO_LICENSE.txt', 'MIT License')
    for relative in ('work/PrivateAvatar/job.json', 'settings_workroot.txt', 'settings_lastvrm.txt',
                     'pipeline/work/PrivateAvatar/mesh.uasset', 'assets/cache/PrivateAvatar/model.json',
                     'python_embed/last_run.log'):
        write(installed / 'res', relative, 'private installed state')
    monkeypatch.setattr(builder, 'REPO', repo)
    builder.build(installed, target)
    contents = {path.relative_to(target).as_posix(): path.read_bytes()
                for path in target.rglob('*') if path.is_file()}
    assert b'private' not in b'\n'.join(contents.values())
    assert not any('PrivateAvatar' in name or name.endswith('model.json') for name in contents)
    assert (target / 'res/app/i18n_data.json').is_file()
    assert (target / 'res/pipeline/py/sway_abp_templates/cooked/template.bin').is_file()
    assert list((target / 'res/work').iterdir()) == [target / 'res/work/_shared_cache']
    manifest = json.loads((target / 'repair_build.json').read_text())
    assert 'runtime_source' not in manifest and 'source_repository' not in manifest
    assert str(tmp_path) not in json.dumps(manifest)
    assert set(manifest['source_files']) == {'app/main.py', 'app/i18n_data.json',
                                            'pipeline/convert.py', 'unity/Exporter.cs'}


def test_fresh_output_preference_and_model_scan_are_empty(tmp_path, monkeypatch):
    import sys
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / 'app_py'))
    import settings
    import pak_manager
    monkeypatch.setenv('UCHINOKO_REBORN_SETTINGS_DIR', str(tmp_path / 'new-user-settings'))
    assert settings.load_work_root() is None
    assert settings.load_last_vrm(str(tmp_path / 'new-install')) is None
    assert pak_manager.list_built_paks(str(tmp_path / 'new-model-library')) == []
