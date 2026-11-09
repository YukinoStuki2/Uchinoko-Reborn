"""The cooked mesh must contain the opted-in physics chain, including its tip."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "py"))
import build_pak_from_avatar as build


TAIL = "NPC_GrassBoss001_Skin001_tail_"


def bone(parent):
    return {"parent": parent, "quat": [0, 0, 0, 1], "pos": [0, 1, 0],
            "scale": [1, 1, 1]}


def fixture(tmp_path, monkeypatch, gender="Female", overrides=None):
    converted = tmp_path / "converted"
    vanilla = tmp_path / "vanilla"
    converted.mkdir()
    vanilla.mkdir()
    if overrides is None:
        overrides = [{"bones": ["tail", "tail.001"], "preserve_segments": True}]
    (tmp_path / "job.json").write_text(json.dumps({"sway_chain_overrides": overrides}))
    # The old family leaf 06 is still valid metadata for non-opted-in builds.
    legacy = {TAIL + "01": bone("pelvis")}
    for i in range(2, 7):
        legacy[TAIL + f"{i:02}"] = bone(TAIL + f"{i-1:02}")
    prefix = "F_" if gender == "Female" else "M_"
    other = prefix + "OldCloth001_"
    for i in range(4, 9):
        legacy[other + f"{i:02}"] = bone("pelvis" if i == 4 else other + f"{i-1:02}")
    (vanilla / f"refskel_{gender.lower()}.json").write_text(json.dumps(legacy))
    planned = {n: b for n, b in legacy.items() if n.startswith(TAIL) and n != TAIL + "06"}
    planned[TAIL + "10"] = bone(TAIL + "05")
    planned["free_donor"] = bone(TAIL + "10")
    planned["free_terminal"] = bone("free_donor")
    (converted / f"sway_hub_refskel_{gender.lower()}.json").write_text(json.dumps(planned))
    monkeypatch.setattr(build.sway_shared_skeleton, "fname_identities_for_job",
                        lambda _: {name: (name, 0) for name in set(legacy) | set(planned)})
    (converted / f"sway_source_donor_map_{gender.lower()}.json").write_text(
        json.dumps({"tail": TAIL + "01", "tail.001": "free_donor"}))
    original = {"root": bone(None), "pelvis": bone("root"),
                TAIL + "01": bone("pelvis"), "unrelated": bone("root")}
    captured = []
    monkeypatch.setattr(build.core, "load_refskel", lambda _: original)

    def extend(_asset, _exp, new_bones, _out_asset, _out_exp):
        captured.extend(new_bones)
        return {"n_bones_before": len(original), "n_bones_after": len(original) + len(new_bones)}

    monkeypatch.setattr(build.vp_refskel_extend, "extend_sk_refskeleton", extend)
    monkeypatch.setattr(build.vp_refskel_extend, "reparent_existing_bone",
                        lambda *args: pytest.fail("must not reparent unrelated existing bones"))
    used = [TAIL + "02", "free_donor", other + "07"]
    dump = {"_job_converted_dir": str(converted),
            "vertices": [{"weights": [(name, 1) for name in used]}]}
    template = tmp_path / "template"
    base = template / f"SK_Pal_{gender}_Test"

    def run():
        return build._refskel_extend_overrides(
            [(str(base.with_suffix(".uexp")), str(base.with_suffix(".uasset")))],
            str(template), str(tmp_path / "build" / "variant"), {gender: dump})

    return run, captured, original, planned, other, converted


@pytest.mark.parametrize("gender", ["Female", "Male"])
def test_preserved_plan_adds_unweighted_terminal_without_obsolete_branch(tmp_path, monkeypatch, gender):
    run, captured, original, planned, other, _ = fixture(tmp_path, monkeypatch, gender)
    assert run()
    names = [b["name"] for b in captured]
    assert "free_terminal" in names, "a real tip is required to rotate the last weighted joint"
    assert TAIL + "06" not in names, "the obsolete synthetic tip would split tail_05"
    assert other + "08" in names, "unrelated legacy components still need their synthetic tip"
    assert set(planned) <= set(original) | set(names)
    assert len(names) == len(set(names))
    already = set(original)
    for entry in captured:
        assert entry["parent"] in already
        already.add(entry["name"])
    # The retained chain has only the explicit child at each joint.
    combined = dict(original, **{b["name"]: b for b in captured})
    for parent in planned:
        children = [n for n, b in combined.items() if b["parent"] == parent]
        assert children == [n for n, b in planned.items() if b["parent"] == parent]


def test_build_extension_attaches_authoritative_identity_to_legacy_sidecar(tmp_path, monkeypatch):
    run, captured, _, planned, _, _ = fixture(tmp_path, monkeypatch)
    original_loader = build.sway_shared_skeleton.fname_identities_for_job
    calls = []

    def identities(path):
        calls.append(path)
        result = original_loader(path)
        result[TAIL + "10"] = (TAIL.rstrip("_"), 11)
        result.pop("F_OldCloth001_08")  # Legacy synthesized terminal, absent from vanilla.
        return result

    monkeypatch.setattr(build.sway_shared_skeleton, "fname_identities_for_job", identities)
    run()
    tail = next(b for b in captured if b["name"] == TAIL + "10")
    assert (tail["fname_base"], tail["fname_number"]) == (TAIL.rstrip("_"), 11)
    assert len(calls) == 1
    synthetic = next(b for b in captured if b["name"] == "F_OldCloth001_08")
    assert "fname_base" not in synthetic


def test_empty_build_never_reads_shared_skeleton(tmp_path, monkeypatch):
    monkeypatch.setattr(build.sway_shared_skeleton, "fname_identities_for_job",
                        lambda _: pytest.fail("unused physics must not trigger skeleton extraction"))
    assert build._refskel_extend_overrides([], str(tmp_path), str(tmp_path), {}) == {}


@pytest.mark.parametrize("overrides", [[], [{"bones": ["tail"], "preserve_segments": False}],
                                      [{"bones": ["tail"], "preserve_segments": "true"}],
                                      [{"bones": ["tail"], "preserve_segments": True, "enabled": False}]])
def test_legacy_path_keeps_synthetic_leaf_and_does_not_require_sidecars(tmp_path, monkeypatch, overrides):
    run, captured, _, _, _, converted = fixture(tmp_path, monkeypatch, overrides=overrides)
    (converted / "sway_source_donor_map_female.json").unlink()
    run()
    names = {b["name"] for b in captured}
    assert TAIL + "06" in names
    assert "free_terminal" not in names


@pytest.mark.parametrize("name", ["sway_hub_refskel_female.json", "sway_source_donor_map_female.json"])
def test_opted_in_chain_cannot_silently_use_incomplete_sidecars(tmp_path, monkeypatch, name):
    run, _, _, _, _, converted = fixture(tmp_path, monkeypatch)
    (converted / name).unlink()
    with pytest.raises(build.vp_refskel_extend.RefskelExtendError, match="full conversion"):
        run()


def test_unassigned_source_anchor_does_not_claim_another_hub(tmp_path, monkeypatch):
    run, captured, _, _, _, converted = fixture(tmp_path, monkeypatch)
    (converted / "sway_source_donor_map_female.json").write_text(json.dumps({"other": TAIL + "01"}))
    run()
    names = {b["name"] for b in captured}
    assert TAIL + "06" in names
    assert "free_terminal" not in names


@pytest.mark.parametrize("gender", ["Female", "Male"])
def test_auto_manifest_protects_active_subtree_without_manual_toggle(tmp_path, monkeypatch, gender):
    run, captured, _, _, _, converted = fixture(tmp_path, monkeypatch, gender, overrides=[])
    (tmp_path / "job.json").write_text(json.dumps({"sway_adaptation": "physbone-v1", "sway_enable": True}))
    (converted / f"sway_adaptation_{gender.lower()}.json").write_text(json.dumps({
        "format": "uchinoko-reborn-sway-adaptation-1", "mode": "physbone-v1",
        "gender": gender.lower(), "active_physbone_anchors": ["tail"],
        "preserved_physbone_anchors": []}))
    run()
    names = {b["name"] for b in captured}
    assert "free_terminal" in names
    assert TAIL + "06" not in names


def test_auto_missing_manifest_requires_full_conversion(tmp_path, monkeypatch):
    run, _, _, _, _, _ = fixture(tmp_path, monkeypatch, overrides=[])
    (tmp_path / "job.json").write_text(json.dumps({"sway_adaptation": "physbone-v1", "sway_enable": True}))
    with pytest.raises(build.vp_refskel_extend.RefskelExtendError, match="full conversion"):
        run()


@pytest.mark.parametrize("manifest", [
    {"format": "uchinoko-reborn-sway-adaptation-1", "mode": "physbone-v1",
     "gender": "male", "active_physbone_anchors": ["tail"]},
    {"format": "uchinoko-reborn-sway-adaptation-1", "mode": "physbone-v1",
     "gender": "female", "active_physbone_anchors": "tail"},
    {"format": "uchinoko-reborn-sway-adaptation-1", "mode": "physbone-v1",
     "gender": "female", "active_physbone_anchors": ["missing_source"]},
])
def test_auto_invalid_or_stale_manifest_never_silently_omits_terminals(tmp_path, monkeypatch, manifest):
    run, _, _, _, _, converted = fixture(tmp_path, monkeypatch, overrides=[])
    (tmp_path / "job.json").write_text(json.dumps({"sway_adaptation": "physbone-v1", "sway_enable": True}))
    (converted / "sway_adaptation_female.json").write_text(json.dumps(manifest))
    with pytest.raises(build.vp_refskel_extend.RefskelExtendError, match="full conversion"):
        run()


@pytest.mark.parametrize("enabled", [False, None])
def test_auto_global_disable_does_not_require_manifest(tmp_path, monkeypatch, enabled):
    run, captured, _, _, _, _ = fixture(tmp_path, monkeypatch, overrides=[])
    (tmp_path / "job.json").write_text(json.dumps({"sway_adaptation": "physbone-v1", "sway_enable": enabled}))
    run()
    assert "free_terminal" not in {b["name"] for b in captured}


def garment_fixture(tmp_path, monkeypatch, gender):
    import sway_auto
    import sway_garment_profile
    run, captured, _, planned, _, converted = fixture(tmp_path, monkeypatch, gender, overrides=[])
    job = {"job_dir": str(tmp_path), "sway_adaptation": "physbone-v1", "sway_enable": True,
           "conservative_garment": True}
    (tmp_path / "job.json").write_text(json.dumps(job))
    manifest = {"format": "uchinoko-reborn-sway-adaptation-1", "mode": "physbone-v1",
                "gender": gender.lower(), "active_physbone_anchors": []}
    (converted / f"sway_adaptation_{gender.lower()}.json").write_text(json.dumps(manifest))
    report = {"format": sway_garment_profile.FORMAT, "enabled": True, "gender": gender.lower(),
              "input_fingerprint": sway_auto.input_fingerprint(job), "source_keys": ["pb:tail#0"],
              "request": {"simulation_root": TAIL + "01", "additional_roots": []},
              "source_to_donor": {"tail": TAIL + "01", "tail.001": "free_donor"},
              "adaptation": dict(manifest, active_physbone_anchors=["tail"], components=[{
                  "unit_key": "pb:tail#0", "anchor": "tail", "target_root": TAIL + "01"}])}
    report_path = converted / f"sway_garment_{gender.lower()}.json"
    report_path.write_text(json.dumps(report))
    return run, captured, planned, report, report_path, converted


@pytest.mark.parametrize("gender", ["Female", "Male"])
def test_garment_subtree_keeps_unweighted_tips_without_changing_nine_node_manifest(tmp_path, monkeypatch, gender):
    run, captured, planned, _, _, _ = garment_fixture(tmp_path, monkeypatch, gender)
    run()
    names = {b["name"] for b in captured}
    assert "free_terminal" in names
    assert TAIL + "06" not in names
    assert set(planned) - {TAIL + "01"} <= names


@pytest.mark.parametrize("corruption", ["missing", "stale", "wrong_anchor", "missing_final_mapping"])
def test_garment_cannot_silently_drop_endpoint_from_incomplete_metadata(tmp_path, monkeypatch, corruption):
    run, _, _, report, report_path, converted = garment_fixture(tmp_path, monkeypatch, "Female")
    if corruption == "missing":
        report_path.unlink()
    elif corruption == "stale":
        report["input_fingerprint"] = "old-build"
        report_path.write_text(json.dumps(report))
    elif corruption == "wrong_anchor":
        report["adaptation"]["active_physbone_anchors"] = ["other-source"]
        report_path.write_text(json.dumps(report))
    else:
        path = converted / "sway_source_donor_map_female.json"
        path.write_text(json.dumps({"tail.001": "free_donor"}))
    with pytest.raises(build.vp_refskel_extend.RefskelExtendError, match="full conversion"):
        run()
