"""Bone identity is the serialized FName pair, not its displayed string."""
from pathlib import Path
import json
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "py"))
import sway_shared_skeleton as shared
import vp_refskel_extend as extend

TAIL = "NPC_GrassBoss001_Skin001_tail"


def asset_bytes(names, payload_size):
    data = bytearray()
    fields = {}

    def field(key, value=0, fmt="i"):
        fields[key] = len(data)
        data.extend(struct.pack("<" + fmt, value))

    field("magic", 0x9E2A83C1, "I")
    field("legacy", -8)
    for key in ("ue3", "ue4", "ue5", "license", "custom", "header", "package"):
        field(key)
    field("flags", 0x80000000, "I")
    field("names", len(names))
    for key in ("name_offset", "soft_count", "soft_offset", "text_count", "text_offset"):
        field(key)
    field("export_count", 1)
    for key in ("export_offset", "import_count", "import_offset", "depends_offset",
                "refs_count", "refs_offset", "search_offset", "thumbnail_offset"):
        field(key)
    data.extend(bytes(16))
    field("generations", 1)
    field("gen_exports", 1)
    field("gen_names", len(names))
    for _ in range(2):
        data.extend(bytes(14))
    for key in ("compression", "chunks", "source", "extra", "registry"):
        field(key)
    field("bulk", 0, "q")
    for key in ("world", "chunk_ids", "preload_count", "preload_offset"):
        field(key)
    field("names_referenced", len(names))
    field("toc", -1, "q")
    struct.pack_into("<i", data, fields["name_offset"], len(data))
    data.extend(b"".join(extend.name_entry_bytes(name) for name in names))
    export_offset = len(data)
    struct.pack_into("<i", data, fields["export_offset"], export_offset)
    # One genuine 96-byte FObjectExport, bIsAsset=true.
    data.extend(bytes(96))
    struct.pack_into("<I", data, export_offset + 68, 1)
    struct.pack_into("<i", data, fields["depends_offset"], len(data))
    data.extend(bytes(4))
    struct.pack_into("<i", data, fields["header"], len(data))
    struct.pack_into("<q", data, fields["bulk"], len(data) + payload_size)
    struct.pack_into("<qq", data, export_offset + 28, payload_size, len(data))
    return bytes(data)


def payload(identities):
    names = list(dict.fromkeys(base for base, _ in identities))
    count = len(identities)
    data = bytearray(bytes(37) + struct.pack("<i", count))
    for i, (base, number) in enumerate(identities):
        data.extend(struct.pack("<iii", names.index(base), number, i - 1))
    data.extend(struct.pack("<i", count))
    for _ in identities:
        data.extend(struct.pack("<10d", 0, 0, 0, 1, 0, 1, 0, 1, 1, 1))
    data.extend(struct.pack("<i", count))
    for i, (base, number) in enumerate(identities):
        data.extend(struct.pack("<iii", names.index(base), number, i))
    rb_offset = len(data)
    data.extend(struct.pack("<i", count) + struct.pack(f"<{count}H", *range(count)))
    data.extend(bytes(53))
    return names, bytes(data), rb_offset


def write_pair(tmp_path, identities, stem="SK"):
    names, raw, rb_offset = payload(identities)
    ua, ux = tmp_path / (stem + ".uasset"), tmp_path / (stem + ".uexp")
    ua.write_bytes(asset_bytes(names, len(raw)))
    ux.write_bytes(raw)
    return ua, ux, names, rb_offset


def test_catalog_preserves_numbered_and_literal_tail_identity(tmp_path):
    identities = [("root", 0), (TAIL + "_01", 0), (TAIL, 11), (TAIL, 21)]
    ua, ux, _, _ = write_pair(tmp_path, identities)
    catalog = shared.full_skeleton_catalog(str(ua), str(ux), min_bones=4, max_bones=4)
    assert [(b["fname_base"], b["fname_number"]) for b in catalog["bones"]] == identities


def test_scanner_rejects_map_identity_with_same_display(tmp_path):
    identities = [("root", 0), (TAIL, 11), (TAIL + "_10", 0)]
    _, ux, names, _ = write_pair(tmp_path, identities)
    raw = bytearray(ux.read_bytes())
    loc = shared.scan_full_refskeleton(raw, names, min_bones=3, max_bones=3)
    struct.pack_into("<ii", raw, loc.map_data + 12, names.index(TAIL + "_10"), 0)
    with pytest.raises(shared.SharedSkeletonError):
        shared.scan_full_refskeleton(raw, names, min_bones=3, max_bones=3)


@pytest.mark.parametrize("metadata", [True, False])
def test_extend_preserves_authoritative_fname_in_both_arrays(tmp_path, monkeypatch, metadata):
    identities = [("root", 0)] + [(f"bone{i}", 0) for i in range(1, 40)]
    ua, ux, _, rb_offset = write_pair(tmp_path, identities)
    monkeypatch.setattr(extend.sks, "parse_sk_structure", lambda *_: {
        "required_bones_offset": rb_offset, "required_bones": list(range(40))})
    requested = [(TAIL + "_01", TAIL + "_01", 0), (TAIL + "_10", TAIL, 11),
                 (TAIL + "_20", TAIL, 21)]
    refskel = {}
    parent = "root"
    for display, base, number in requested:
        refskel[display] = {"parent": parent, "quat": [0, 0, 0, 1],
                            "pos": [0, 1, 0], "scale": [1, 1, 1]}
        if metadata:
            refskel[display].update(fname_base=base, fname_number=number)
        parent = display
    new = extend.family_bones_from_refskel(refskel, list(refskel))
    out_ua, out_ux = tmp_path / "out.uasset", tmp_path / "out.uexp"
    extend.extend_sk_refskeleton(str(ua), str(ux), new, str(out_ua), str(out_ux))
    names = extend.core.read_names(str(out_ua))
    raw = out_ux.read_bytes()
    loc = shared.scan_full_refskeleton(raw, names, min_bones=43, max_bones=43)
    for offset in (loc.bi_count_pos + 4, loc.map_data):
        actual = []
        for i in range(40, 43):
            idx, num, _ = struct.unpack_from("<iii", raw, offset + i * 12)
            actual.append((names[idx], num))
        expected = [(base, num) if metadata else (display, 0) for display, base, num in requested]
        assert actual == expected
    # Two numbered bones share a single base NameMap entry.
    assert len(names) == 40 + (2 if metadata else 3)


def test_numbered_metadata_does_not_split_a_literal_numeric_name():
    bone = {"name": TAIL + "_20", "fname_base": TAIL + "_20", "fname_number": 0}
    assert extend.bone_fname(bone) == (TAIL + "_20", 0)


@pytest.mark.parametrize("metadata", [{"fname_base": TAIL},
    {"fname_base": TAIL, "fname_number": -1},
    {"fname_base": TAIL, "fname_number": True},
    {"fname_base": TAIL, "fname_number": 10}])
def test_invalid_raw_metadata_fails_before_writing(metadata):
    with pytest.raises(extend.RefskelExtendError):
        extend.bone_fname({"name": TAIL + "_10", **metadata})


@pytest.mark.parametrize("old_catalog", [True, False])
def test_job_identity_source_uses_metadata_or_reextracts_old_cache(tmp_path, monkeypatch, old_catalog):
    import pak_live_extract
    # 1000 entries exercises the production shared-Skeleton scanner bounds.
    identities = [("root", 0)] + [(f"bone{i}", 0) for i in range(1, 999)] + [(TAIL, 11)]
    ua, ux, _, _ = write_pair(tmp_path, identities)
    catalog = shared.full_skeleton_catalog(str(ua), str(ux))
    if old_catalog:
        for bone in catalog["bones"]:
            bone.pop("fname_base")
            bone.pop("fname_number")
    vanilla = tmp_path / "vanilla"
    vanilla.mkdir()
    (vanilla / "sk_palhuman_full.json").write_text(json.dumps(catalog))
    pak = tmp_path / "game.pak"
    pak.touch()
    monkeypatch.setattr(extend.core, "load_job", lambda _: {"paths": {"palworld_pak": str(pak)}})
    calls = []

    def extract(path, paths):
        calls.append(path)
        return {name: ua.read_bytes() if name.endswith(".uasset") else ux.read_bytes() for name in paths}

    monkeypatch.setattr(pak_live_extract, "extract_files", extract)
    actual = shared.fname_identities_for_job(str(tmp_path))
    assert actual[TAIL + "_10"] == (TAIL, 11)
    assert len(calls) == (1 if old_catalog else 0)


def test_missing_raw_metadata_cannot_guess_without_game_pak(tmp_path, monkeypatch):
    monkeypatch.setattr(extend.core, "load_job", lambda _: {"paths": {"palworld_pak": None}})
    with pytest.raises(shared.SharedSkeletonError, match="cannot be guessed"):
        shared.fname_identities_for_job(str(tmp_path))
