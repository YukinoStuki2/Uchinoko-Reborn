import importlib.util
import hashlib
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('reborn_local_builder', Path(__file__).parents[2] / 'repair/build_local.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def installation(tmp_path, monkeypatch):
    repo = tmp_path / 'source'
    target = tmp_path / 'installed'
    files = {
        'app_py/main.py': 'new main', 'pipeline/new.py': 'new pipeline',
        'unity/Bridge.cs': 'new bridge', 'LICENSE': 'license',
        'README.md': 'readme', 'README_REPAIR.md': 'repair readme',
        'repair/OUTPUT.md': 'help',
    }
    for name, text in files.items():
        file = repo / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
    installed = {
        'res/app/main.py': 'old main', 'res/pipeline/removed.py': 'old pipeline',
        'res/python_embed/pythonw.exe': 'runtime', 'res/work/Avatar/build/avatar.pak': 'model',
        'res/settings_lastvrm.txt': 'personal setting', 'res/pipeline/template.bin': 'binary template',
    }
    for name, text in installed.items():
        file = target / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
    manifest = {'format': 1, 'kind': 'local-development-installation', 'version': 'old',
                'source_files': {name[4:]: hashlib.sha256(text.encode()).hexdigest()
                                 for name, text in installed.items() if name.endswith('.py')}}
    (target / 'repair_build.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(builder, 'REPO', repo)
    return target


def test_update_reuses_runtime_models_settings_and_removes_only_owned_source(installation):
    target = installation
    result = builder.update(target)
    assert (target / 'res/app/main.py').read_text() == 'new main'
    assert not (target / 'res/pipeline/removed.py').exists()
    assert (target / 'res/pipeline/new.py').read_text() == 'new pipeline'
    assert (target / 'res/python_embed/pythonw.exe').read_text() == 'runtime'
    assert (target / 'res/work/Avatar/build/avatar.pak').read_text() == 'model'
    assert (target / 'res/settings_lastvrm.txt').read_text() == 'personal setting'
    assert (target / 'res/pipeline/template.bin').read_text() == 'binary template'
    assert (Path(result['backup']) / 'res/app/main.py').read_text() == 'old main'
    assert builder.update(target)['changed'] == 0


def test_locally_modified_source_is_preserved(installation):
    file = installation / 'res/app/main.py'
    file.write_text('user edited')
    with pytest.raises(ValueError, match='modified'):
        builder.update(installation)
    assert file.read_text() == 'user edited'
    assert not (installation / 'repair/source_backups').exists()


def test_unmanaged_collision_is_preserved(installation):
    file = installation / 'res/pipeline/new.py'
    file.write_text('private extension')
    with pytest.raises(ValueError, match='Unmanaged'):
        builder.update(installation)
    assert file.read_text() == 'private extension'


def test_mid_update_failure_restores_previous_source(installation, monkeypatch):
    original = builder.os.replace
    calls = 0

    def failing_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('simulated locked source file')
        original(source, destination)

    monkeypatch.setattr(builder.os, 'replace', failing_replace)
    with pytest.raises(OSError, match='locked'):
        builder.update(installation)
    assert (installation / 'res/app/main.py').read_text() == 'old main'
    assert (installation / 'res/pipeline/removed.py').read_text() == 'old pipeline'
    assert not (installation / 'res/pipeline/new.py').exists()
    assert json.loads((installation / 'repair_build.json').read_text())['version'] == 'old'


def test_manifest_cannot_escape_installation(installation):
    file = installation / 'repair_build.json'
    manifest = json.loads(file.read_text())
    manifest['source_files']['../../outside.py'] = 'irrelevant'
    file.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Unsafe'):
        builder.update(installation)


def test_manifest_cannot_claim_user_job_metadata(installation):
    job = installation / 'res/work/Avatar/job.json'
    job.write_text('{"avatar": "private"}')
    file = installation / 'repair_build.json'
    manifest = json.loads(file.read_text())
    manifest['source_files']['work/Avatar/job.json'] = hashlib.sha256(job.read_bytes()).hexdigest()
    file.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Unsafe'):
        builder.update(installation)
    assert job.read_text() == '{"avatar": "private"}'


def test_reviewed_static_document_allows_a_second_source_update(installation):
    source = builder.REPO / 'pipeline/py/sway_abp_templates/README.md'
    source.parent.mkdir(parents=True)
    source.write_text('Reviewed template documentation')
    builder.update(installation)
    assert builder.update(installation)['changed'] == 0
    source.write_text('Updated template documentation')
    builder.update(installation)
    assert (installation / 'res/pipeline/py/sway_abp_templates/README.md').read_text() == source.read_text()
