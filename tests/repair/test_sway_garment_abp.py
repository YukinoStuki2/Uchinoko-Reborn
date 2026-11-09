"""Bounded garment additions must retain every existing physics node."""
from pathlib import Path
import os
import struct
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline" / "py"))
import sway_garment_abp as garment
import sway_abp_curves as curves
import sway_abp_build as build
import sway_abp_patcher as scalar
import sway_auto
import sway_garment_profile as profile_store

TEMPLATES = Path(os.environ.get("UCHINOKO_LICENSED_TEMPLATES",
    str(REPO.parent / "UchinokoReborn" / "res" / "pipeline" / "py" / "sway_abp_templates")))
ASSETS = sorted((TEMPLATES / "cooked").glob("ABP_*.uasset"))


def request(**changes):
    result = {"simulation_root": "TestGarmentRoot_01",
              "additional_roots": ["TestGarmentRoot_02", "TestGarmentRoot_03"],
              "params": {"stiffness": .65, "damping": .6, "wdl": .8, "wdr": .8,
                         "limit_angle": 3, "radius": 0, "gravity_z": 0}}
    result.update(changes)
    return result


def test_disabled_garment_patch_is_byte_identical_without_parsing():
    assert garment.patch_garment_node(b"header", b"payload", None) == (b"header", b"payload")


@pytest.mark.parametrize("changes", [
    {"additional_roots": ["TestGarmentRoot_01"]},
    {"additional_roots": ["a", "a"]}, {"simulation_root": ""},
    {"additional_roots": ["x"] * 256},
    {"params": {"limit_angle": 0}}, {"params": {"limit_angle": 4}},
    {"params": {"radius": 1}}, {"params": {"gravity_z": -1}},
    {"params": {"stiffness": float("nan")}},
    {"curves": {"limit_angle": [[0, 0], [1, 1]]}},
    {"curves": {"damping": [[0, 2], [1, 1]]}},
    {"bone_fnames": {"TestGarmentRoot_01": ["wrong", 0]}},
])
def test_unsafe_requests_fail_before_package_access(changes):
    with pytest.raises(garment.GarmentAbpError):
        garment.patch_garment_node(b"bad", b"bad", request(**changes))


def test_fname_identity_preserves_numbered_names_and_zero_padded_names():
    assert garment._bone_fname("M_Hunter001_17", {}) == ("M_Hunter001", 18)
    assert garment._bone_fname("Garment_01", {}) == ("Garment_01", 0)
    assert garment._bone_fname("Garment_17", {"Garment_17": ["Garment_17", 0]}) == ("Garment_17", 0)


@pytest.mark.parametrize("path", ASSETS, ids=lambda p: p.stem)
def test_all_licensed_families_preserve_nine_nodes_and_compiled_graph(path):
    template = {"uasset_name": path.name, "uexp_name": path.with_suffix(".uexp").name,
                "target_abp": "/Game/Pal/Blueprint/Character/Player/Imp_Cloth/" + path.stem}
    header, payload, roots = garment.load_garment_template(template, path.parent)
    assert len(roots) == 10
    if path.stem.startswith("ABP_F_"):
        assert b"ABP_M_" not in header
    before = garment.physics_node_semantics(header, payload)
    assert garment.RESERVE_ROOT in before
    after_h, after_p = garment.patch_garment_node(header, payload, request())
    after = garment.physics_node_semantics(after_h, after_p)
    assert set(after) == set(before) - {garment.RESERVE_ROOT} | {"TestGarmentRoot_01"}
    for root in before:
        if root != garment.RESERVE_ROOT:
            assert before[root] == after[root]
    decoded = garment.read_garment_node(after_h, after_p, "TestGarmentRoot_01")
    assert decoded["additional_roots"] == request()["additional_roots"]
    assert decoded["params"]["limit_angle"] == 3
    assert decoded["params"]["gravity_z"] == 0
    assert decoded["params"]["radius"] == 0
    # Every export apart from CDO remains byte-exact, including graph code.
    old = curves._metadata(header, payload)
    new = curves._metadata(after_h, after_p)
    for a, b in zip(old[2], new[2]):
        if a is old[3]:
            continue
        start_a, start_b = a["serial_offset"] - len(header), b["serial_offset"] - len(after_h)
        assert payload[start_a:start_a+a["serial_size"]] == after_p[start_b:start_b+b["serial_size"]]


@pytest.fixture
def licensed():
    if not ASSETS:
        pytest.skip("licensed templates not present")
    path = ASSETS[0]
    return garment.load_garment_template({"uasset_name": path.name,
        "uexp_name": path.with_suffix(".uexp").name}, path.parent)[:2]


def test_existing_node_collision_is_rejected(licensed):
    root = next(r for r in garment.physics_node_semantics(*licensed) if r != garment.RESERVE_ROOT)
    with pytest.raises(garment.GarmentAbpError, match="overlap"):
        garment.patch_garment_node(*licensed, request(additional_roots=[root]))


def test_malformed_additional_root_container_is_rejected(licensed):
    h, p = licensed
    _, _, _, _, nodes = garment._inspect(h, p)
    broken = bytearray(p)
    struct.pack_into("<i", broken, nodes[garment.RESERVE_ROOT][1]["AdditionalRootBones"]["payload"], 500)
    with pytest.raises(garment.GarmentAbpError):
        garment.patch_garment_node(h, bytes(broken), request())


def test_twenty_four_roots_after_existing_scalar_and_variable_curves(licensed):
    h, p = licensed
    names = curves._metadata(h, p)[1]
    roots = list(garment.physics_node_semantics(h, p))
    spec = build.build_spec_nodes(roots, "futsuu")
    p = scalar.patch_kawaii_physics_nodes(p, names, spec)
    first = next(n for n in spec if n["root_bone"] != garment.RESERVE_ROOT)
    first["extended_curves"] = {"stiffness": [[i / 16, .2 + i / 64] for i in range(17)]}
    h, p = curves.patch_curves(h, p, spec)
    before = garment.physics_node_semantics(h, p)
    chosen = request(additional_roots=[f"GarmentExtra_{i}" for i in range(23)])
    out_h, out_p = garment.patch_garment_node(h, p, chosen)
    assert len(garment.read_garment_node(out_h, out_p, chosen["simulation_root"])["additional_roots"]) == 23
    after = garment.physics_node_semantics(out_h, out_p)
    assert all(before[root] == after[root] for root in before if root != garment.RESERVE_ROOT)


def test_public_tag_reader_rejects_nonempty_or_wrong_struct_array():
    # Synthetic UE tags require no game assets and independently spell the
    # actual array header, catching a guessed struct type or count mismatch.
    names = ["None", "AdditionalRootBones", "ArrayProperty", "StructProperty",
             "KawaiiPhysicsRootBoneSetting", "WrongRootType"]
    fn = lambda n: struct.pack("<ii", names.index(n), 0)
    inner = (fn("AdditionalRootBones") + fn("StructProperty") + struct.pack("<ii", 0, 0)
             + fn("KawaiiPhysicsRootBoneSetting") + bytes(17))
    data = (fn("AdditionalRootBones") + fn("ArrayProperty") + struct.pack("<ii", 4+len(inner), 0)
            + fn("StructProperty") + bytes(1) + struct.pack("<i", 0) + inner)
    reader = curves._Tags(data, names)
    tag, _ = reader.tag(0, len(data))
    assert garment._empty_array(reader, tag, "KawaiiPhysicsRootBoneSetting")["size"] == 0
    changed = bytearray(data)
    struct.pack_into("<i", changed, tag["payload"], 1)
    with pytest.raises(garment.GarmentAbpError, match="not empty"):
        garment._empty_array(curves._Tags(changed, names), tag)
    with pytest.raises(garment.GarmentAbpError, match="layout"):
        garment._empty_array(reader, tag, "WrongRootType")


@pytest.mark.parametrize("path", ASSETS, ids=lambda p: p.stem)
def test_actual_build_entry_keeps_all_nine_source_profiles(path):
    template = next(t for t in build.load_template_manifest(str(TEMPLATES / "specs"))
                    if t["uasset_name"] == path.name)
    overrides = {}
    for index, root in enumerate(r for r in template["root_bones"] if r != garment.RESERVE_ROOT):
        channels = {"stiffness": .2 + index * .03, "damping": .3 + index * .02,
                    "wdl": .4 + index * .02, "wdr": .5 + index * .02,
                    "radius": 1.5 + index * .1, "limit_angle": 18 + index,
                    "gravity_z": -20 - index}
        # Distinct scalars and nonuniform key counts detect accidentally using
        # a uniform preset or the original female NameMap against the M graph.
        source = {"parameter_mode": "physbone-v1", "params": channels,
                  "extended_curves": {channel: [[k / (index + 2), .4 + .5 * k / (index + 2)]
                                                 for k in range(index + 3)]
                                      for channel in sway_auto.CHANNELS}}
        overrides[root] = {"source_profile": source}
    baseline_h, baseline_p = build.patch_template_bytes(
        template, "futsuu", str(path.parent), node_overrides=overrides)
    chosen = request(additional_roots=[f"IndependentGarment_{i}" for i in range(23)])
    out_h, out_p = build.patch_template_bytes(
        template, "futsuu", str(path.parent), node_overrides=overrides, garment_request=chosen)
    baseline = garment.physics_node_semantics(baseline_h, baseline_p)
    after = garment.physics_node_semantics(out_h, out_p)
    assert set(after) == set(overrides) | {chosen["simulation_root"]}
    for root in overrides:
        # Adding the existing tenth compiled node changes F graph link indexes;
        # all nine original physics properties and curves must still match.
        assert {k: v for k, v in baseline[root].items() if k != "ComponentPose"} == {
            k: v for k, v in after[root].items() if k != "ComponentPose"}
    assert garment.read_garment_node(out_h, out_p, chosen["simulation_root"])["additional_roots"] == chosen["additional_roots"]


@pytest.mark.parametrize("genders,expected", [
    (None, {"female", "male"}), (["Female"], {"female"}),
    (["Male"], {"male"}), (["female", "MALE"], {"female", "male"}),
])
def test_pak_entry_loads_only_selected_gender_reports(tmp_path, monkeypatch, genders, expected):
    job = {"job_dir": str(tmp_path), "sway_enable": True, "sway_adaptation": "physbone-v1",
           "conservative_garment": True, "sway_intensity": "normal"}
    if genders is not None:
        job["genders"] = genders
    requests = {}
    for gender in expected:
        requests[gender] = request(simulation_root="Garment_" + gender)
        report = {"format": profile_store.FORMAT, "gender": gender, "enabled": True,
                  "input_fingerprint": sway_auto.input_fingerprint(job),
                  "source_keys": ["source/" + gender], "request": requests[gender]}
        profile_store.write_report(job, gender, report)
    manifest = [{"target_abp": "/Game/Pal/Blueprint/Character/Player/Imp_Cloth/ABP_" + sex + "_Cloth001_Implimentation",
                 "uasset_name": "ABP_" + sex + "_Cloth001_Implimentation.uasset",
                 "uexp_name": "ABP_" + sex + "_Cloth001_Implimentation.uexp"} for sex in ("F", "M")]
    monkeypatch.setattr(build, "load_template_manifest", lambda _: manifest)
    observed = {}
    def patch(template, hardness, cooked, raw, overrides, request_value):
        observed["female" if template["uasset_name"].startswith("ABP_F_") else "male"] = request_value
        return b"synthetic header", b"synthetic payload"
    monkeypatch.setattr(build, "patch_template_bytes", patch)
    entries = build.sway_abp_pak_entries(job, str(tmp_path / "output"), str(tmp_path / "templates"))
    assert len(entries) == 4
    assert observed == {gender: requests.get(gender) for gender in ("female", "male")}
    assert all(Path(path).is_file() for path, _ in entries)
