"""Repeated conversions must replace geometry and retain both worker outputs."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from threading import Barrier

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline/py"))
import sway_reparent_store as store
import build_pak_from_avatar as build
import fast_repack


def step(name, scale=1):
    return {"target": name, "new_parent": "head", "tag": name,
            "new_local_transform": [[0, 0, 0, 1], [10 * scale, 2 * scale, 3 * scale], [1, 1, 1]]}


def test_same_directory_rebuild_replaces_geometry_and_removes_disabled_groups(tmp_path):
    store.write_gender(tmp_path, "Male", [step("M_hair"), step("M_tail")])
    store.write_gender(tmp_path, "Female", [step("F_hair"), step("F_tail")])
    assert len(store.read_for_build(tmp_path, store.GENDERS)) == 4

    store.write_gender(tmp_path, "Male", [step("M_hair", .8)])
    store.write_gender(tmp_path, "Female", [step("F_hair", .8)])
    expected = [step("M_hair", .8), step("F_hair", .8)]
    assert store.read_for_build(tmp_path, store.GENDERS) == expected
    assert json.loads((tmp_path / store.COMBINED_FILENAME).read_text()) == expected

    store.write_gender(tmp_path, "Male", [])
    store.write_gender(tmp_path, "Female", [])
    assert store.read_for_build(tmp_path, store.GENDERS) == []
    assert json.loads((tmp_path / store.COMBINED_FILENAME).read_text()) == []


def test_single_gender_ignores_previous_other_gender(tmp_path):
    store.write_gender(tmp_path, "Male", [step("M_old")])
    store.write_gender(tmp_path, "Female", [step("F_current", .75)])
    assert store.read_for_build(tmp_path, ["Female"]) == [step("F_current", .75)]


def test_partial_new_export_never_falls_back_to_combined_file(tmp_path):
    (tmp_path / store.COMBINED_FILENAME).write_text(json.dumps([step("old")]))
    store.write_gender(tmp_path, "Male", [step("M_new")])
    with pytest.raises(ValueError, match="Missing current Female"):
        store.read_for_build(tmp_path, store.GENDERS)
    with pytest.raises(ValueError, match="Missing current Female"):
        store.read_for_build(tmp_path, ["Female"])


def test_legacy_export_is_still_readable(tmp_path):
    assert store.read_for_build(tmp_path, store.GENDERS) == []
    (tmp_path / store.COMBINED_FILENAME).write_text(json.dumps([step("legacy")]))
    assert store.read_for_build(tmp_path, store.GENDERS) == [step("legacy")]


def test_shared_targets_are_deduplicated_but_conflicting_geometry_fails(tmp_path):
    store.write_gender(tmp_path, "Male", [step("shared"), step("M_hair")])
    store.write_gender(tmp_path, "Female", [dict(step("shared"), tag="different diagnostic"), step("F_hair")])
    assert store.read_for_build(tmp_path, store.GENDERS) == [step("shared"), step("M_hair"), step("F_hair")]
    store.write_gender(tmp_path, "Female", [step("shared", .8)])
    with pytest.raises(ValueError, match="Conflicting Female reparent geometry"):
        store.read_for_build(tmp_path, store.GENDERS)


def test_parallel_workers_have_disjoint_atomic_replace_destinations(tmp_path, monkeypatch):
    barrier = Barrier(2)
    destinations = []
    real_replace = store.os.replace

    def simultaneous_replace(source, destination):
        destinations.append(destination)
        barrier.wait(timeout=10)
        real_replace(source, destination)

    monkeypatch.setattr(store.os, "replace", simultaneous_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(store.write_gender, tmp_path, gender, [step(gender)])
                   for gender in store.GENDERS]
        for future in futures:
            future.result()
    assert set(destinations) == {store.gender_path(tmp_path, gender) for gender in store.GENDERS}
    assert not (tmp_path / store.COMBINED_FILENAME).exists()
    assert not list(tmp_path.glob("*.tmp"))
    monkeypatch.setattr(store.os, "replace", real_replace)
    assert store.read_for_build(tmp_path, store.GENDERS) == [step("Male"), step("Female")]


def test_failed_atomic_replace_preserves_previous_complete_plan(tmp_path, monkeypatch):
    store.write_gender(tmp_path, "Male", [step("old")])

    def fail_replace(source, destination):
        raise OSError("simulated interrupted replace")

    monkeypatch.setattr(store.os, "replace", fail_replace)
    with pytest.raises(OSError, match="interrupted replace"):
        store.write_gender(tmp_path, "Male", [step("new")])
    assert json.loads(store.gender_path(tmp_path, "Male").read_text()) == [step("old")]
    assert not list(tmp_path.glob("*.tmp"))


def test_disabled_rebuild_removes_old_binary_cache_before_fast_repack(tmp_path, monkeypatch):
    converted = tmp_path / "converted"
    work = tmp_path / "build/noue_work"
    stage = work / "sway_hub_reparent"
    stage.mkdir(parents=True)
    store.write_gender(converted, "Female", [])
    stale = [converted / build.SWAY_HUB_PATCH_MANIFEST_FILENAME]
    stale += [stage / (build.SWAY_HUB_SK_PACKAGE_NAME + suffix) for suffix in (".uasset", ".uexp")]
    for path in stale:
        path.write_text("old build")
    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps({"genders": ["Female"], "job_dir": str(tmp_path)}))

    def no_pak_read(*args, **kwargs):
        pytest.fail("disabled plan must not read the game pak")

    monkeypatch.setattr(build.core, "read_pak_entries", no_pak_read)
    assert build._run_sway_hub_reparent_patch(str(job_path), str(work)) == []
    assert not any(path.exists() for path in stale)
    assert fast_repack._reuse_sway_hub_reparent(str(work), (str(tmp_path),)) == []
