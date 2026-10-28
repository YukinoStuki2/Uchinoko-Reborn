"""Exercise variable curves against all locally licensed cooked ABP templates."""
from pathlib import Path
import os
import struct
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline" / "py"))
import sway_abp_build as build
import sway_abp_curves as curves

TEMPLATES = Path(os.environ.get("UCHINOKO_LICENSED_TEMPLATES",
    str(REPO.parent / "UchinokoReborn" / "res" / "pipeline" / "py" / "sway_abp_templates")))
ASSETS = sorted((TEMPLATES / "cooked").glob("*.uasset"))


@pytest.fixture
def asset():
    if not ASSETS:
        pytest.skip("licensed cooked templates are not present")
    p = ASSETS[0]
    return p.read_bytes(), p.with_suffix(".uexp").read_bytes()


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def points(count):
    return [[f32(i / max(1, count - 1)), f32(.25 + .5 * i / max(1, count - 1))]
            for i in range(count)]


def test_all_twenty_licensed_templates_are_covered():
    if not ASSETS:
        pytest.skip("licensed cooked templates are not present")
    assert len(ASSETS) == 20


@pytest.mark.parametrize("path", ASSETS, ids=lambda p: p.stem)
def test_every_template_resize_all_six_curves_and_restore_exact_original(path):
    header, payload = path.read_bytes(), path.with_suffix(".uexp").read_bytes()
    original = curves.read_curves(header, payload)
    assert len(original) in (9, 10)
    nodes = [{"root_bone": root} for root in original]
    assert curves.patch_curves(header, payload, nodes) == (header, payload)
    counts = [0, 1, 3, 17, 64, 256]
    for index, node in enumerate(nodes):
        node["extended_curves"] = {key: points(counts[(index + i) % len(counts)])
                                   for i, key in enumerate(curves.CURVE_PROPERTIES)}
    after_h, after_p = curves.patch_curves(header, payload, nodes)
    assert len(after_h) == len(header)
    expected = {n["root_bone"]: n["extended_curves"] for n in nodes}
    assert curves.read_curves(after_h, after_p) == expected
    # All unrelated exports and native CDO trailing data remain exact despite
    # changed lengths; this catches offsets accidentally patched only in CDO.
    old_meta = curves._inspect(header, payload)
    new_meta = curves._inspect(after_h, after_p)
    for old, new in zip(old_meta[1], new_meta[1]):
        if old is old_meta[2]:
            old_start, new_start = old_meta[4], new_meta[4]
        else:
            old_start = old["serial_offset"] - len(header)
            new_start = new["serial_offset"] - len(after_h)
        old_end = old["serial_offset"] - len(header) + old["serial_size"]
        new_end = new["serial_offset"] - len(after_h) + new["serial_size"]
        assert payload[old_start:old_end] == after_p[new_start:new_end]
    assert new_meta[0].bulk_data_start_offset - old_meta[0].bulk_data_start_offset == len(after_p) - len(payload)
    restore = [{"root_bone": root, "extended_curves": values} for root, values in original.items()]
    assert curves.patch_curves(after_h, after_p, restore) == (header, payload)


@pytest.mark.parametrize("bad", [
    [[0, float("nan")]], [[0, float("inf")]], [[False, 1]], [[0, True]],
    [[0, 1], [0, 2]], [[.8, 1], [.2, 2]], [[-.1, 1]], [[1.1, 1]],
    [[0, 1e50]], [[0, 1, 2]], "curve", [[.5, 1], [.50000000001, 2]],
    [[i / 256, 1] for i in range(257)],
])
def test_bad_requested_points_fail_closed(asset, bad):
    header, payload = asset
    root = next(iter(curves.read_curves(header, payload)))
    with pytest.raises(curves.CurveStructureError):
        curves.patch_curves(header, payload, [{"root_bone": root, "extended_curves": {"damping": bad}}])


@pytest.mark.parametrize("field", ["array_count", "inner_size", "parent_size", "name_index", "serial_size"])
def test_corrupt_container_or_key_structure_fails_closed(asset, field):
    header, payload = asset
    h, _, cdo, nodes, _ = curves._inspect(header, payload)
    root, node = next(iter(nodes.items()))
    key = node["stiffness"]
    edited_h, edited_p = bytearray(header), bytearray(payload)
    if field == "array_count":
        struct.pack_into("<i", edited_p, key["tags"][-2]["payload"], 999)
    elif field == "inner_size":
        struct.pack_into("<i", edited_p, key["tags"][-1]["size_at"], 0)
    elif field == "parent_size":
        struct.pack_into("<i", edited_p, key["tags"][1]["size_at"], 1)
    elif field == "name_index":
        struct.pack_into("<i", edited_p, key["tags"][1]["start"], h.name_count + 1)
    else:
        struct.pack_into("<q", edited_h, cdo["serial_size_offset"], len(payload) + 100)
    with pytest.raises(curves.CurveStructureError):
        curves.patch_curves(bytes(edited_h), bytes(edited_p),
                            [{"root_bone": root, "extended_curves": {"stiffness": points(3)}}])


def test_unknown_root_curve_and_external_reference_fail_closed(asset):
    header, payload = asset
    _, _, _, nodes, _ = curves._inspect(header, payload)
    root, node = next(iter(nodes.items()))
    for request in ({"root_bone": "missing", "extended_curves": {"damping": points(3)}},
                    {"root_bone": root, "extended_curves": {"missing": points(3)}}):
        with pytest.raises(curves.CurveStructureError):
            curves.patch_curves(header, payload, [request])
    changed = bytearray(payload)
    struct.pack_into("<i", changed, node["damping"]["external"]["payload"], 1)
    with pytest.raises(curves.CurveStructureError, match="external"):
        curves.patch_curves(header, bytes(changed),
                            [{"root_bone": root, "extended_curves": {"damping": points(3)}}])


def test_template_pipeline_applies_scalar_patch_before_variable_curves(asset, monkeypatch):
    manifest = build.load_template_manifest(str(TEMPLATES / "specs"))
    template = manifest[0]
    original_builder = build.build_spec_nodes
    chosen = template["root_bones"][0]

    def spec_nodes(*args, **kwargs):
        result = original_builder(*args, **kwargs)
        next(n for n in result if n["root_bone"] == chosen)["extended_curves"] = {
            "damping": points(17), "stiffness": points(64), "radius": points(3)}
        return result

    monkeypatch.setattr(build, "build_spec_nodes", spec_nodes)
    header, payload = build.patch_template_bytes(template, "futsuu", str(TEMPLATES / "cooked"))
    result = curves.read_curves(header, payload)
    assert result[chosen]["damping"] == points(17)
    assert result[chosen]["stiffness"] == points(64)
    assert result[chosen]["radius"] == points(3)
    assert all(value["wdl"] == [[0, 1], [1, 1]] for value in result.values())
