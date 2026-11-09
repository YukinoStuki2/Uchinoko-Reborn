"""Add bounded, independent garment roots to the authored ten-node cloth layer.

This is an explicit compatibility mode, not an equivalent PhysBone solver.
The existing nine nodes keep their own profiles and chains. The reserve node
uses a cone of at most three degrees, with no gravity, wind or collisions.
"""
from __future__ import annotations

from pathlib import Path
import math
import re
import struct

import live_template
import sway_abp_curves as curves
import vp_refskel_extend as refskel

RESERVE_ROOT = "M_Hunter001_17"
MAX_ROOTS = 64
_FIELDS = {"damping": "Damping", "stiffness": "Stiffness",
           "wdl": "WorldDampingLocation", "wdr": "WorldDampingRotation",
           "radius": "Radius", "limit_angle": "LimitAngle"}


class GarmentAbpError(curves.CurveStructureError):
    """Reject malformed assets or a request outside the compatibility limits."""


def _inspect(header, payload):
    h, names, exports, cdo = curves._metadata(header, payload)
    reader = curves._Tags(payload, names)
    start = cdo["serial_offset"] - len(header)
    rows, _ = reader.properties(start, start + cdo["serial_size"], exact=False)
    nodes = {}
    for node in rows.values():
        if node.get("struct") != "AnimNode_KawaiiPhysics":
            continue
        fields = reader.children(node, "AnimNode_KawaiiPhysics")
        bone = reader.children(fields["RootBone"], "BoneReference")["BoneName"]
        if bone["kind"] != "NameProperty" or bone["size"] != 8:
            raise GarmentAbpError("invalid root BoneName")
        root = reader.fname(bone["payload"], bone["end"])[0]
        if root in nodes:
            raise GarmentAbpError("duplicate physics root")
        nodes[root] = (node, fields)
    return h, names, exports, cdo, nodes


def _semantic(reader, tag):
    """Resolve FNames before comparing templates with different NameMaps."""
    kind = tag["kind"]
    data = reader.data[tag["payload"]:tag["end"]]
    if kind == "StructProperty":
        try:
            rows, _ = reader.properties(tag["payload"], tag["end"])
        except curves.CurveStructureError:
            return (kind, tag.get("struct"), data)
        return (kind, tag.get("struct"), {k: _semantic(reader, v) for k, v in rows.items()})
    if kind == "ArrayProperty" and tag.get("inner") == "StructProperty":
        (count,), at = reader.unpack("i", tag["payload"], tag["end"])
        inner, at = reader.tag(at, tag["end"])
        if inner is None or count < 0:
            raise GarmentAbpError("invalid struct array")
        return (kind, count, inner["name"], inner.get("struct"), reader.data[at:tag["end"]])
    if kind in ("NameProperty", "EnumProperty", "ByteProperty") and len(data) == 8:
        return (kind, reader.fname(tag["payload"], tag["end"])[0])
    if kind == "BoolProperty":
        return (kind, reader.data[tag["size_at"] + 8])
    return (kind, data)


def physics_node_semantics(header, payload):
    """Return normalized node properties, useful for preservation checks."""
    _, names, _, _, nodes = _inspect(header, payload)
    reader = curves._Tags(payload, names)
    return {root: {key: _semantic(reader, tag) for key, tag in fields.items()}
            for root, (_, fields) in nodes.items()}


def _verify_graph(header, payload):
    _, names, _, cdo, _ = _inspect(header, payload)
    reader = curves._Tags(payload, names)
    start = cdo["serial_offset"] - len(header)
    rows, _ = reader.properties(start, start + cdo["serial_size"], exact=False)
    graph = [t for t in rows.values() if t.get("struct", "").startswith("AnimNode_")]
    links = {}
    inputs, outputs, physics = set(), [], set()
    for index, node in enumerate(graph):
        fields = reader.children(node, node["struct"])
        if node["struct"] == "AnimNode_LinkedInputPose":
            inputs.add(index)
            continue
        link_fields = [f for f in fields.values() if f.get("struct") in ("PoseLink", "ComponentSpacePoseLink")]
        if len(link_fields) != 1:
            raise GarmentAbpError("unexpected cloth graph linkage")
        link = reader.children(link_fields[0], link_fields[0]["struct"])["LinkID"]
        linked = struct.unpack_from("<i", payload, link["payload"])[0]
        links[index] = linked
        if node["struct"] == "AnimNode_Root" and linked >= 0:
            outputs.append(index)
        if node["struct"] == "AnimNode_KawaiiPhysics":
            physics.add(index)
            alpha = fields["Alpha"]
            if struct.unpack_from("<f", payload, alpha["payload"])[0] != 1:
                raise GarmentAbpError("cloth physics node is disabled")
    if len(outputs) != 1 or len(physics) != 10:
        raise GarmentAbpError("expected one cloth output and ten physics nodes")
    at, visited = outputs[0], set()
    while at not in inputs:
        if at in visited or at not in links:
            raise GarmentAbpError("broken or cyclic cloth graph")
        visited.add(at)
        at = links[at]
    if not physics.issubset(visited):
        raise GarmentAbpError("garment reserve is not connected to cloth output")


def _rename_template(header, payload, old, new):
    h, names, _, _ = curves._metadata(header, payload)
    replacements = {name: name.replace(old, new) for name in names if old in name}
    if len(replacements) != 4 or len(old) != len(new):
        raise GarmentAbpError("unexpected template self names")
    changed, at = bytearray(header), h.name_offset
    for name in names:
        length = struct.unpack_from("<i", header, at)[0]
        if length <= 0:
            raise GarmentAbpError("non-ASCII template NameMap")
        end = at + 4 + length + 4
        if name in replacements:
            encoded = refskel.name_entry_bytes(replacements[name])
            if len(encoded) != end - at:
                raise GarmentAbpError("template self rename changes length")
            changed[at:end] = encoded
        at = end
    # PackageName in FPackageFileSummary is an FString, not a NameMap entry.
    summary = bytes(changed[:h.name_offset]).replace(old.encode("ascii"), new.encode("ascii"))
    changed[:h.name_offset] = summary
    if old.encode("ascii") in changed:
        raise GarmentAbpError("unmigrated template self reference")
    curves._metadata(bytes(changed), payload)
    return bytes(changed)


def load_garment_template(template, cooked_dir):
    """Load the corresponding authored M ten-node graph for either target sex.

    The returned third item is the actual ten root names. Call the existing
    scalar/curve patcher before patch_garment_node; that patcher uses fixed
    template layout and must not run after AdditionalRootBones is resized.
    """
    target = Path(template["uasset_name"]).stem
    if not re.fullmatch(r"ABP_[FM]_[A-Za-z0-9]+_Implimentation", target):
        raise GarmentAbpError("unsupported cloth template name")
    source = target.replace("ABP_F_", "ABP_M_", 1)
    folder = Path(cooked_dir)
    header = (folder / (source + ".uasset")).read_bytes()
    payload = (folder / (source + ".uexp")).read_bytes()
    actual = physics_node_semantics(header, payload)
    if len(actual) != 10 or RESERVE_ROOT not in actual:
        raise GarmentAbpError("male template has no unique ten-node reserve")
    _verify_graph(header, payload)
    if target != source:
        original_h = (folder / (target + ".uasset")).read_bytes()
        original_p = (folder / (target + ".uexp")).read_bytes()
        original = physics_node_semantics(original_h, original_p)
        if set(original) != set(actual) - {RESERVE_ROOT}:
            raise GarmentAbpError("female and male baseline roots differ")
        for root, fields in original.items():
            left = {k: v for k, v in fields.items() if k != "ComponentPose"}
            right = {k: v for k, v in actual[root].items() if k != "ComponentPose"}
            if left != right:
                raise GarmentAbpError("female and male baseline physics differ")
        header = _rename_template(header, payload, source, target)
    return header, payload, list(actual)


def _bone_fname(name, identities):
    identity = identities.get(name)
    if identity is None:
        match = re.fullmatch(r"(.+)_(0|[1-9][0-9]*)", name)
        identity = (match.group(1), int(match.group(2)) + 1) if match else (name, 0)
    if (not isinstance(identity, (list, tuple)) or len(identity) != 2
            or not isinstance(identity[0], str) or not identity[0]
            or type(identity[1]) is not int or not 0 <= identity[1] <= 2147483647
            or identity[0] + (f"_{identity[1] - 1}" if identity[1] else "") != name):
        raise GarmentAbpError("bone FName identity does not match its display name")
    if any(ord(c) < 32 or ord(c) > 126 for c in identity[0]):
        raise GarmentAbpError("garment root requires an ASCII FName")
    return tuple(identity)


def _validate_request(request):
    if not isinstance(request, dict) or request.get("root_bone", RESERVE_ROOT) != RESERVE_ROOT:
        raise GarmentAbpError("only the reserved garment node may be changed")
    root, additional = request.get("simulation_root"), request.get("additional_roots", [])
    if not isinstance(root, str) or not root or not isinstance(additional, (list, tuple)):
        raise GarmentAbpError("garment roots must be named")
    roots = [root, *additional]
    if (len(roots) > MAX_ROOTS or any(not isinstance(n, str) or not n for n in roots)
            or len(set(roots)) != len(roots)):
        raise GarmentAbpError("duplicate or excessive garment roots")
    identities = request.get("bone_fnames", {})
    if not isinstance(identities, dict):
        raise GarmentAbpError("invalid bone FName identities")
    identities = {name: _bone_fname(name, identities) for name in roots}
    params = request.get("params", {})
    if not isinstance(params, dict) or set(params) != set(_FIELDS) | {"gravity_z"}:
        raise GarmentAbpError("garment requires all seven bounded parameters")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in params.values()):
        raise GarmentAbpError("garment parameters must be finite numbers")
    if (any(not 0 <= params[k] <= 1 for k in ("damping", "stiffness", "wdl", "wdr"))
            or not 0 < params["limit_angle"] <= 3
            or params["radius"] != 0 or params["gravity_z"] != 0):
        raise GarmentAbpError("garment parameters exceed conservative compatibility limits")
    requested_curves = request.get("curves", request.get("extended_curves", {}))
    if not isinstance(requested_curves, dict) or set(requested_curves) - set(curves.CURVE_PROPERTIES):
        raise GarmentAbpError("unknown garment curve")
    converted = {}
    for key in curves.CURVE_PROPERTIES:
        points = requested_curves.get(key, [[0, 1], [1, 1]])
        curves._validate_points(points)
        if not points or any(not 0 <= v <= 1 or (key == "limit_angle" and v == 0) for _, v in points):
            raise GarmentAbpError("garment curves exceed conservative compatibility limits")
        converted[key] = points
    return roots, identities, params, converted


def _append_names(header, payload, wanted):
    """Reuse the shared-skeleton NameMap encoding and offset accounting."""
    h, names, exports, _ = curves._metadata(header, payload)
    added = list(dict.fromkeys(n for n in wanted if n not in names))
    if not added:
        return header
    _, at = live_template._read_name_table(header, h.name_offset, h.name_count)
    if at != h.import_offset:
        raise GarmentAbpError("unsupported NameMap insertion layout")
    insert = b"".join(refskel.name_entry_bytes(n) for n in added)
    delta = len(insert)
    result = bytearray(header[:at] + insert + header[at:])
    struct.pack_into("<i", result, h.name_count_off, h.name_count + len(added))
    struct.pack_into("<i", result, h.total_header_size_off, len(result))
    # The shared header reader supports the authored ABP custom versions;
    # the skeletal-mesh summary reader intentionally accepts only versionless
    # packages. Generations follow ThumbnailTableOffset and the package Guid.
    generations_at = h.thumbnail_table_offset_off + 4 + 16
    generation_count = struct.unpack_from("<i", header, generations_at)[0]
    if not 0 <= generation_count <= 100 or generations_at + 4 + 8 * generation_count > h.asset_registry_data_offset_off:
        raise GarmentAbpError("invalid package generations")
    for index in range(generation_count):
        count_at = generations_at + 8 + 8 * index
        old = struct.unpack_from("<i", header, count_at)[0]
        struct.pack_into("<i", result, count_at, old + len(added))
    for key in ("soft_object_paths_offset", "gatherable_text_offset", "export_offset", "import_offset",
                "depends_offset", "soft_package_references_offset", "searchable_names_offset",
                "thumbnail_table_offset", "asset_registry_data_offset", "world_tile_info_data_offset",
                "preload_dependency_offset", "bulk_data_start_offset", "payload_toc_offset"):
        field_at = getattr(h, key + "_off")
        fmt = "<q" if key in ("bulk_data_start_offset", "payload_toc_offset") else "<i"
        value = struct.unpack_from(fmt, header, field_at)[0]
        if value > 0:
            if value < at:
                raise GarmentAbpError("package offset precedes NameMap insertion")
            struct.pack_into(fmt, result, field_at, value + delta)
    referenced_at = h.payload_toc_offset_off - 4
    referenced = struct.unpack_from("<i", header, referenced_at)[0]
    struct.pack_into("<i", result, referenced_at, referenced + len(added))
    for export in exports:
        struct.pack_into("<q", result, export["serial_size_offset"] + delta + 8,
                         export["serial_offset"] + delta)
    result = bytes(result)
    curves._metadata(result, payload)
    return result


def _resize_cdo(header, payload, edits):
    h, _, exports, cdo = curves._metadata(header, payload)
    result, previous = bytearray(payload), len(payload) + 1
    for start, end, value in sorted(edits, reverse=True):
        if not 0 <= start <= end <= len(payload) or end > previous:
            raise GarmentAbpError("overlapping garment edits")
        result[start:end], previous = value, start
    delta, new_header = len(result) - len(payload), bytearray(header)
    cdo_end = cdo["serial_offset"] + cdo["serial_size"]
    for export in exports:
        at = export["serial_size_offset"]
        if export is cdo:
            struct.pack_into("<q", new_header, at, export["serial_size"] + delta)
        elif export["serial_offset"] >= cdo_end:
            struct.pack_into("<q", new_header, at + 8, export["serial_offset"] + delta)
    for field in ("bulk_data_start_offset", "payload_toc_offset"):
        value = getattr(h, field)
        if value >= cdo_end:
            struct.pack_into("<q", new_header, getattr(h, field + "_off"), value + delta)
        elif field == "bulk_data_start_offset" and value > 0:
            raise GarmentAbpError("bulk data overlaps the CDO")
    return bytes(new_header), bytes(result)


def _empty_array(reader, tag, expected=None):
    if tag["kind"] != "ArrayProperty":
        raise GarmentAbpError("expected an array property")
    (count,), at = reader.unpack("i", tag["payload"], tag["end"])
    if count != 0:
        raise GarmentAbpError("garment template array is not empty")
    if tag.get("inner") == "StructProperty":
        inner, end = reader.tag(at, tag["end"])
        if inner is None or inner["size"] != 0 or end != tag["end"] or (expected and inner.get("struct") != expected):
            raise GarmentAbpError("unexpected empty struct-array layout")
        return inner
    if at != tag["end"]:
        raise GarmentAbpError("unexpected empty array payload")
    return None


def _fname_bytes(names, identity):
    return struct.pack("<ii", names.index(identity[0]), identity[1])


def _patch(header, payload, request):
    roots, identities, params, requested_curves = _validate_request(request)
    before = physics_node_semantics(header, payload)
    if len(before) != 10 or RESERVE_ROOT not in before:
        raise GarmentAbpError("expected the unmodified ten-node garment template")
    if (set(roots) & (set(before) - {RESERVE_ROOT})) or RESERVE_ROOT in roots:
        raise GarmentAbpError("garment roots overlap an existing physics node")
    header = _append_names(header, payload, [i[0] for i in identities.values()]
                           + ["bUseOverrideExcludeBones", "OverrideExcludeBones"])
    _, names, _, _, nodes = _inspect(header, payload)
    node, fields = nodes[RESERVE_ROOT]
    reader = curves._Tags(payload, names)
    additional = fields["AdditionalRootBones"]
    inner = _empty_array(reader, additional, "KawaiiPhysicsRootBoneSetting")
    for key in ("ExcludeBones", "SphericalLimits", "CapsuleLimits", "BoxLimits", "PlanarLimits",
                "SphericalLimitsData", "CapsuleLimitsData", "BoxLimitsData", "PlanarLimitsData",
                "BoneConstraints", "BoneConstraintsData", "MergedBoneConstraints", "ExternalForces",
                "CustomExternalForces", "ModifyBones"):
        _empty_array(reader, fields[key])
    for key in ("LimitsDataAsset", "PhysicsAssetForLimits", "BoneConstraintsDataAsset"):
        tag = fields[key]
        if tag["kind"] != "ObjectProperty" or payload[tag["payload"]:tag["end"]] != b"\0" * 4:
            raise GarmentAbpError("external garment constraints are unsupported")
    root_tag = fields["RootBone"]
    root_fields = reader.children(root_tag, "BoneReference")
    bone = root_fields["BoneName"]
    edits = [(bone["payload"], bone["end"], _fname_bytes(names, identities[roots[0]]))]
    none = _fname_bytes(names, ("None", 0))
    elements = []
    for root in roots[1:]:
        # FKawaiiPhysicsRootBoneSetting fields follow the upstream v1.18.0
        # header (tag 20241201-v1.18.0) and the actual cooked inner struct tag.
        element = bytearray(payload[root_tag["start"]:root_tag["end"]])
        pos = bone["payload"] - root_tag["start"]
        element[pos:pos + 8] = _fname_bytes(names, identities[root])
        flag = (_fname_bytes(names, ("bUseOverrideExcludeBones", 0))
                + _fname_bytes(names, ("BoolProperty", 0)) + struct.pack("<iiBB", 0, 0, 0, 0))
        excluded = fields["ExcludeBones"]
        exclusion = bytearray(payload[excluded["start"]:excluded["end"]])
        exclusion[:8] = _fname_bytes(names, ("OverrideExcludeBones", 0))
        exclusion_inner = _empty_array(reader, excluded, "BoneReference")
        inner_pos = exclusion_inner["start"] - excluded["start"]
        exclusion[inner_pos:inner_pos + 8] = _fname_bytes(names, ("OverrideExcludeBones", 0))
        elements.append(bytes(element) + bytes(exclusion) + flag + none)
    array_data = b"".join(elements)
    edits += [(additional["payload"], additional["payload"] + 4, struct.pack("<i", len(elements))),
              (inner["size_at"], inner["size_at"] + 4, struct.pack("<i", len(array_data))),
              (inner["payload"], additional["end"], array_data)]
    for tag in (additional, node):
        edits.append((tag["size_at"], tag["size_at"] + 4, struct.pack("<i", tag["size"] + len(array_data))))
    physics = reader.children(fields["PhysicsSettings"], "KawaiiPhysicsSettings")
    for key, field in _FIELDS.items():
        tag = physics[field]
        if tag["kind"] != "FloatProperty" or tag["size"] != 4:
            raise GarmentAbpError("invalid physics scalar layout")
        edits.append((tag["payload"], tag["end"], struct.pack("<f", params[key])))
    gravity = fields["Gravity"]
    if gravity.get("struct") != "Vector" or gravity["size"] != 24:
        raise GarmentAbpError("invalid gravity layout")
    edits.append((gravity["payload"], gravity["end"], struct.pack("<ddd", 0, 0, 0)))
    for key in ("bEnableWind", "bAllowWorldCollision"):
        tag = fields[key]
        if tag["kind"] != "BoolProperty":
            raise GarmentAbpError("invalid garment boolean")
        edits.append((tag["size_at"] + 8, tag["size_at"] + 9, b"\0"))
    dummy = fields["DummyBoneLength"]
    if dummy["kind"] != "FloatProperty" or dummy["size"] != 4:
        raise GarmentAbpError("invalid dummy bone length")
    edits.append((dummy["payload"], dummy["end"], struct.pack("<f", 0)))
    header, payload = _resize_cdo(header, payload, edits)
    header, payload = curves.patch_curves(header, payload,
        [{"root_bone": roots[0], "extended_curves": requested_curves}])
    after = physics_node_semantics(header, payload)
    if set(after) != set(before) - {RESERVE_ROOT} | {roots[0]}:
        raise GarmentAbpError("garment patch changed the node set")
    if any(before[root] != after[root] for root in before if root != RESERVE_ROOT):
        raise GarmentAbpError("garment patch modified an existing physics node")
    verified = read_garment_node(header, payload, roots[0])
    if verified["additional_roots"] != roots[1:]:
        raise GarmentAbpError("garment roots failed round-trip verification")
    for key, value in params.items():
        if verified["params"][key] != struct.unpack("<f", struct.pack("<f", value))[0]:
            raise GarmentAbpError("garment parameters failed round-trip verification")
    _verify_graph(header, payload)
    return header, payload


def patch_garment_node(header, payload, request):
    """Patch only the spare node after ordinary scalar/curve processing."""
    if request is None:
        return header, payload
    try:
        return _patch(header, payload, request)
    except (curves.CurveStructureError, refskel.RefskelExtendError, KeyError,
            ValueError, TypeError, struct.error, OverflowError) as exc:
        if isinstance(exc, GarmentAbpError):
            raise
        raise GarmentAbpError(str(exc)) from exc


def read_garment_node(header, payload, root):
    """Decode the emitted independent roots without assuming record sizes."""
    _, names, _, _, nodes = _inspect(header, payload)
    reader = curves._Tags(payload, names)
    _, fields = nodes[root]
    tag = fields["AdditionalRootBones"]
    (count,), at = reader.unpack("i", tag["payload"], tag["end"])
    inner, at = reader.tag(at, tag["end"])
    if (not 0 <= count < MAX_ROOTS or inner is None or inner.get("struct") != "KawaiiPhysicsRootBoneSetting"
            or inner["end"] != tag["end"]):
        raise GarmentAbpError("invalid additional-root array")
    roots = []
    for _ in range(count):
        element, at = reader.properties(at, tag["end"], exact=False)
        if set(element) != {"RootBone", "bUseOverrideExcludeBones", "OverrideExcludeBones"}:
            raise GarmentAbpError("unexpected additional-root fields")
        bone = reader.children(element["RootBone"], "BoneReference")["BoneName"]
        roots.append(reader.fname(bone["payload"], bone["end"])[0])
        if _semantic(reader, element["bUseOverrideExcludeBones"]) != ("BoolProperty", 0):
            raise GarmentAbpError("unexpected exclusion override")
        _empty_array(reader, element["OverrideExcludeBones"], "BoneReference")
    if at != tag["end"]:
        raise GarmentAbpError("additional-root trailing data")
    physics = reader.children(fields["PhysicsSettings"], "KawaiiPhysicsSettings")
    params = {key: struct.unpack_from("<f", payload, physics[field]["payload"])[0]
              for key, field in _FIELDS.items()}
    params["gravity_z"] = struct.unpack_from("<d", payload, fields["Gravity"]["payload"] + 16)[0]
    return {"simulation_root": root, "additional_roots": roots, "params": params}
