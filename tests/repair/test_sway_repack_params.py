"""Shadow/material repacking must preserve per-component cooked physics."""
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "py"))
import build_pak_from_avatar as full
import fast_repack
import sway_abp_build


def prepare(tmp_path):
    job = {"job_dir": str(tmp_path), "sway_intensity": "soft", "sway_enable": True,
           "sway_chain_overrides": [{"bones": ["Hair", "Hair1"], "enabled": True,
                                      "motion": {"profile": "calm", "amount": 0.5}}]}
    root = sway_abp_build.load_template_manifest()[0]["root_bones"][0]
    overrides = {root: {"style": "yawa", "limit_angle": 8.0, "motion": {
        "settings": {"profile": "calm", "amount": 0.5, "gravity_z": -25.0},
        "source": "pb", "source_params": {"pull": 0.5, "spring": 0.4}}}}
    converted = tmp_path / "converted"
    converted.mkdir()
    (converted / "sway_node_overrides.json").write_text(json.dumps(overrides), encoding="utf-8")
    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    return job, job_path, overrides


def test_repack_forwards_saved_node_overrides(tmp_path, monkeypatch):
    job, _, expected = prepare(tmp_path)
    captured = []
    monkeypatch.setattr(sway_abp_build, "sway_abp_pak_entries",
                        lambda *args, **kw: captured.append(kw.get("node_overrides")) or [])
    fast_repack._rebuild_sway_abp(job, str(tmp_path / "repack"))
    assert captured == [expected]


@pytest.mark.parametrize("bad_metadata", [None, "{broken", "[]"])
def test_motion_cannot_silently_fall_back_when_metadata_missing_or_invalid(tmp_path, monkeypatch, capsys, bad_metadata):
    job, job_path, _ = prepare(tmp_path)
    path = tmp_path / "converted" / "sway_node_overrides.json"
    if bad_metadata is None:
        path.unlink()
    else:
        path.write_text(bad_metadata, encoding="utf-8")
    monkeypatch.setattr(full.core, "load_job", lambda _: job)
    monkeypatch.setattr(sway_abp_build, "sway_abp_pak_entries", lambda *a, **kw: pytest.fail("unsafe fallback"))
    for operation in (lambda: fast_repack._rebuild_sway_abp(job, str(tmp_path / "repack")),
                      lambda: full._run_sway_abp_patch(str(job_path), str(tmp_path / "full"))):
        with pytest.raises(SystemExit) as raised:
            operation()
        assert "full conversion" in (str(raised.value) + capsys.readouterr().out).lower()


def test_disabled_sway_does_not_require_metadata(tmp_path):
    job = {"sway_intensity": "none", "sway_chain_overrides": [
        {"bones": ["Hair"], "motion": {"profile": "source"}}]}
    assert fast_repack._rebuild_sway_abp(job, str(tmp_path)) == []


def test_real_full_and_repack_cooked_outputs_are_identical(tmp_path, monkeypatch):
    cooked = Path(os.environ.get("UCHINOKO_TEST_COOKED_DIR", sway_abp_build.COOKED_DIR))
    if not cooked.is_dir():
        pytest.skip("Set UCHINOKO_TEST_COOKED_DIR to local licensed templates")
    job, job_path, overrides = prepare(tmp_path)
    monkeypatch.setattr(full.core, "load_job", lambda _: job)
    original = sway_abp_build.sway_abp_pak_entries
    monkeypatch.setattr(sway_abp_build, "sway_abp_pak_entries", lambda job, out, **kw:
                        original(job, out, templates_dir=str(cooked.parent), **kw))
    full_entries = full._run_sway_abp_patch(str(job_path), str(tmp_path / "full"))
    repack_entries = fast_repack._rebuild_sway_abp(job, str(tmp_path / "repack"))
    full_bytes = {rel: Path(path).read_bytes() for path, rel in full_entries}
    repack_bytes = {rel: Path(path).read_bytes() for path, rel in repack_entries}
    assert full_bytes
    assert repack_bytes == full_bytes
    # Meaningful negative control: uniform legacy nodes differ from the tuned
    # files, so matching files proves the override was preserved.
    legacy = original(job, str(tmp_path / "legacy"), templates_dir=str(cooked.parent))
    assert {rel: Path(path).read_bytes() for path, rel in legacy} != full_bytes


def test_auto_real_full_and_repack_keep_variable_source_curves_identical(tmp_path, monkeypatch):
    import sway_abp_curves
    from test_sway_auto import prepare_multicomponent_auto_metadata
    cooked = Path(os.environ.get("UCHINOKO_TEST_COOKED_DIR", sway_abp_build.COOKED_DIR))
    if not cooked.is_dir():
        pytest.skip("Set UCHINOKO_TEST_COOKED_DIR to local licensed templates")
    templates = sway_abp_build.load_template_manifest(str(cooked.parent / "specs"))
    assert len(templates) == 20
    common_roots = set.intersection(*(set(t["root_bones"]) for t in templates))
    roots = sorted(common_roots)[:2]
    assert len(roots) == 2
    job, manifests = prepare_multicomponent_auto_metadata(tmp_path, roots)
    expected = {root: value["source_profile"]["extended_curves"]
                for root, value in manifests["female"]["node_overrides"].items()}
    assert all(len(values["stiffness"]) > 2 for values in expected.values())
    assert all(len({value for _, value in values["stiffness"]}) > 2 for values in expected.values())
    monkeypatch.setattr(full.core, "load_job", lambda _: job)
    original = sway_abp_build.sway_abp_pak_entries
    monkeypatch.setattr(sway_abp_build, "sway_abp_pak_entries", lambda job, out, **kw:
                        original(job, out, templates_dir=str(cooked.parent), **kw))
    full_entries = full._run_sway_abp_patch(str(tmp_path / "job.json"), str(tmp_path / "full-auto"))
    repack_entries = fast_repack._rebuild_sway_abp(job, str(tmp_path / "repack-auto"))
    full_bytes = {rel: Path(path).read_bytes() for path, rel in full_entries}
    repack_bytes = {rel: Path(path).read_bytes() for path, rel in repack_entries}
    assert len(full_bytes) == 40 and full_bytes == repack_bytes
    checked = 0
    for rel, header in full_bytes.items():
        if not rel.endswith(".uasset"):
            continue
        actual = sway_abp_curves.read_curves(header, full_bytes[rel[:-7] + ".uexp"])
        for root, values in expected.items():
            for key, points in values.items():
                assert len(actual[root][key]) == len(points)
                for got, want in zip(actual[root][key], points):
                    assert got == pytest.approx(want, abs=1e-6)
        checked += 1
    assert checked == 20
    legacy = original(job, str(tmp_path / "legacy-auto"), templates_dir=str(cooked.parent))
    assert {rel: Path(path).read_bytes() for path, rel in legacy} != full_bytes
