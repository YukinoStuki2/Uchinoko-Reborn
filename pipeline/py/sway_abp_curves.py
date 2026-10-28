"""Resize cooked KawaiiPhysics curves through bounded UE property tags.

Only key arrays, their enclosing sizes and package serial offsets change.
Unknown properties and native CDO data are copied byte for byte. This module
uses the repository's package reader and does not require Unreal or UAssetAPI.
"""
from __future__ import annotations

from collections import defaultdict
import math
import struct

import live_template
import parse_uasset_header


class CurveStructureError(ValueError):
    """Reject unsupported or inconsistent cooked data before returning edits."""


CURVE_PROPERTIES = {
    "damping": "DampingCurveData", "stiffness": "StiffnessCurveData",
    "wdl": "WorldDampingLocationCurveData", "wdr": "WorldDampingRotationCurveData",
    "radius": "RadiusCurveData", "limit_angle": "LimitAngleCurveData",
}
MAX_KEYS = 256
_KEY = struct.Struct("<BBBffffff")


class _Tags:
    def __init__(self, data, names):
        self.data, self.names = data, names

    def unpack(self, fmt, at, end):
        size = struct.calcsize("<" + fmt)
        if not 0 <= at <= at + size <= end <= len(self.data):
            raise CurveStructureError(f"property bounds at {at}, end {end}")
        return struct.unpack_from("<" + fmt, self.data, at), at + size

    def fname(self, at, end):
        (index, number), at = self.unpack("ii", at, end)
        if not 0 <= index < len(self.names) or number < 0:
            raise CurveStructureError("invalid property FName")
        return self.names[index] + (f"_{number - 1}" if number else ""), at

    def tag(self, at, end):
        start = at
        name, at = self.fname(at, end)
        if name == "None":
            return None, at
        kind, at = self.fname(at, end)
        size_at = at
        (size, index), at = self.unpack("ii", at, end)
        if size < 0 or index < 0:
            raise CurveStructureError("negative property size or index")
        tag = dict(name=name, kind=kind, start=start, size_at=size_at, size=size, index=index)
        if kind == "StructProperty":
            tag["struct"], at = self.fname(at, end)
            _, at = self.unpack("16s", at, end)
        elif kind in ("ByteProperty", "EnumProperty"):
            _, at = self.fname(at, end)
        elif kind == "BoolProperty":
            (value,), at = self.unpack("B", at, end)
            if value not in (0, 1):
                raise CurveStructureError("invalid BoolProperty")
        elif kind in ("ArrayProperty", "SetProperty"):
            tag["inner"], at = self.fname(at, end)
        elif kind == "MapProperty":
            _, at = self.fname(at, end)
            _, at = self.fname(at, end)
        (has_guid,), at = self.unpack("B", at, end)
        if has_guid not in (0, 1):
            raise CurveStructureError("invalid property GUID flag")
        if has_guid:
            _, at = self.unpack("16s", at, end)
        if at + size > end:
            raise CurveStructureError(f"{name} exceeds its enclosing property")
        tag.update(payload=at, end=at + size)
        return tag, at

    def properties(self, start, end, *, exact=True):
        rows, at = {}, start
        while at < end:
            tag, at = self.tag(at, end)
            if tag is None:
                if exact and at != end:
                    raise CurveStructureError("unexpected tagged-struct trailing data")
                return rows, at
            if tag["name"] in rows:
                raise CurveStructureError("duplicate property " + tag["name"])
            rows[tag["name"]] = tag
            at = tag["end"]
        raise CurveStructureError("property list missing None terminator")

    def children(self, tag, struct_name):
        if tag["kind"] != "StructProperty" or tag.get("struct") != struct_name:
            raise CurveStructureError("unexpected struct for " + tag["name"])
        return self.properties(tag["payload"], tag["end"])[0]


def _metadata(header, payload):
    try:
        h = live_template._parse_header_with_offsets(header)
        if struct.unpack_from("<i", header, h.total_header_size_off)[0] != len(header):
            raise CurveStructureError("TotalHeaderSize differs from input header length")
        if not (0 < h.name_count <= 100000 and 0 < h.export_count <= 10000):
            raise CurveStructureError("invalid name/export count")
        names, end = live_template._read_name_table(header, h.name_offset, h.name_count)
        if end > h.import_offset or len(names) != h.name_count:
            raise CurveStructureError("invalid name table bounds")
        exports, at = [], h.export_offset
        for _ in range(h.export_count):
            item, at = parse_uasset_header.parse_export_entry(header, at)
            name_index, number = item["object_name"]
            if not 0 <= name_index < len(names) or number < 0 or at > len(header):
                raise CurveStructureError("invalid export name or bounds")
            item["name"] = names[name_index] + (f"_{number - 1}" if number else "")
            start = item["serial_offset"] - len(header)
            size = item["serial_size"]
            if size < 0 or (size and not 0 <= start <= start + size <= len(payload)):
                raise CurveStructureError("export serial range exceeds payload")
            exports.append(item)
        ranges = sorted((e["serial_offset"], e["serial_offset"] + e["serial_size"])
                        for e in exports if e["serial_size"])
        if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])):
            raise CurveStructureError("overlapping export serial ranges")
        defaults = [e for e in exports if e["name"].startswith("Default__")]
        if len(defaults) != 1:
            raise CurveStructureError("expected exactly one CDO export")
        return h, names, exports, defaults[0]
    except (ValueError, RuntimeError, struct.error, IndexError, UnicodeError) as exc:
        if isinstance(exc, CurveStructureError):
            raise
        raise CurveStructureError(f"unsupported cooked package: {exc}") from exc


def _inspect(header, payload):
    h, names, exports, cdo = _metadata(header, payload)
    reader = _Tags(payload, names)
    start = cdo["serial_offset"] - len(header)
    rows, property_end = reader.properties(start, start + cdo["serial_size"], exact=False)
    nodes = {}
    for node in rows.values():
        if node.get("struct") != "AnimNode_KawaiiPhysics":
            continue
        fields = reader.children(node, "AnimNode_KawaiiPhysics")
        try:
            root_fields = reader.children(fields["RootBone"], "BoneReference")
            root_tag = root_fields["BoneName"]
            if root_tag["kind"] != "NameProperty" or root_tag["size"] != 8:
                raise CurveStructureError("RootBone is not a BoneName FName")
            root, _ = reader.fname(root_tag["payload"], root_tag["end"])
            if root in nodes:
                raise CurveStructureError("duplicate KawaiiPhysics root " + root)
            curves = {}
            for short, property_name in CURVE_PROPERTIES.items():
                curve = fields[property_name]
                curve_fields = reader.children(curve, "RuntimeFloatCurve")
                editor = curve_fields["EditorCurveData"]
                curve_rows = reader.children(editor, "RichCurve")
                keys = curve_rows["Keys"]
                if keys["kind"] != "ArrayProperty" or keys.get("inner") != "StructProperty":
                    raise CurveStructureError("curve Keys is not a struct array")
                (count,), inner_at = reader.unpack("i", keys["payload"], keys["end"])
                inner, data_at = reader.tag(inner_at, keys["end"])
                if (inner is None or inner["kind"] != "StructProperty"
                        or inner.get("struct") != "RichCurveKey" or inner["name"] != "Keys"
                        or not 0 <= count <= MAX_KEYS or inner["size"] != count * _KEY.size
                        or data_at + count * _KEY.size != keys["end"]):
                    raise CurveStructureError("invalid RichCurveKey array layout")
                points = []
                for index in range(count):
                    record = _KEY.unpack_from(payload, data_at + index * _KEY.size)
                    if not all(math.isfinite(v) for v in record[3:]):
                        raise CurveStructureError("nonfinite stored curve key")
                    points.append([record[3], record[4]])
                curves[short] = dict(points=points, count=count, data_at=data_at,
                                     tags=(node, curve, editor, keys, inner),
                                     external=curve_fields.get("ExternalCurve"))
            nodes[root] = curves
        except KeyError as exc:
            raise CurveStructureError(f"missing KawaiiPhysics curve property: {exc}") from exc
    if not nodes:
        raise CurveStructureError("no KawaiiPhysics nodes in CDO")
    return h, exports, cdo, nodes, property_end


def read_curves(uasset_bytes, uexp_bytes):
    """Read all six curves by actual property tags, including resized output."""
    nodes = _inspect(uasset_bytes, uexp_bytes)[3]
    return {root: {name: curve["points"] for name, curve in curves.items()}
            for root, curves in nodes.items()}


def _validate_points(points):
    if not isinstance(points, (list, tuple)) or len(points) > MAX_KEYS:
        raise CurveStructureError(f"curve must contain 0..{MAX_KEYS} keys")
    encoded, previous = [], -1.0
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise CurveStructureError("curve key must be [time, value]")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
            raise CurveStructureError("curve time/value must be finite numbers")
        time, value = point
        if not 0 <= time <= 1 or time <= previous:
            raise CurveStructureError("curve times must strictly increase within [0, 1]")
        try:
            record = _KEY.pack(0, 0, 0, time, value, 0, 0, 0, 0)
        except (OverflowError, struct.error) as exc:
            raise CurveStructureError("curve value is not representable as float32") from exc
        stored_time = struct.unpack_from("<f", record, 3)[0]
        if stored_time <= previous:
            raise CurveStructureError("curve times collapse at float32 precision")
        previous = stored_time
        encoded.append(record)
    return b"".join(encoded)


def patch_curves(uasset_bytes, uexp_bytes, nodes):
    """Apply optional extended_curves after fixed-layout scalar patching.

    With no extended curves this is a byte-identical no-op. Resized results
    must be read with read_curves, never the old fixed-offset patcher/reader.
    """
    requests = {}
    for node in nodes:
        if "extended_curves" not in node:
            continue
        curves = node["extended_curves"]
        if not isinstance(curves, dict) or set(curves) - set(CURVE_PROPERTIES):
            raise CurveStructureError("invalid extended curve names")
        if not curves:
            continue
        root = node.get("root_bone")
        if not isinstance(root, str) or root in requests:
            raise CurveStructureError("missing or duplicate extended-curve root")
        requests[root] = {key: (_validate_points(value), len(value)) for key, value in curves.items()}
    if not requests:
        return uasset_bytes, uexp_bytes

    h, exports, cdo, actual, _ = _inspect(uasset_bytes, uexp_bytes)
    if set(requests) - set(actual):
        raise CurveStructureError("requested extended curve root is absent from CDO")
    sizes, edits = defaultdict(int), []
    for root, curves in requests.items():
        for name, (replacement, count) in curves.items():
            curve = actual[root][name]
            external = curve["external"]
            if (external is None or external["kind"] != "ObjectProperty" or external["size"] != 4
                    or struct.unpack_from("<i", uexp_bytes, external["payload"])[0] != 0):
                raise CurveStructureError("external runtime curves cannot be replaced locally")
            delta = len(replacement) - curve["count"] * _KEY.size
            for tag in curve["tags"]:
                sizes[tag["size_at"]] += delta
            keys = curve["tags"][-2]
            edits.append((keys["payload"], keys["payload"] + 4, struct.pack("<i", count)))
            edits.append((curve["data_at"], keys["end"], replacement))
    for at, delta in sizes.items():
        old = struct.unpack_from("<i", uexp_bytes, at)[0]
        edits.append((at, at + 4, struct.pack("<i", old + delta)))
    result = bytearray(uexp_bytes)
    previous = len(result) + 1
    for start, end, value in sorted(edits, reverse=True):
        if end > previous:
            raise CurveStructureError("overlapping curve edits")
        result[start:end] = value
        previous = start
    delta = len(result) - len(uexp_bytes)
    header = bytearray(uasset_bytes)
    cdo_end = cdo["serial_offset"] + cdo["serial_size"]
    for export in exports:
        at = export["serial_size_offset"]
        if export is cdo:
            struct.pack_into("<q", header, at, export["serial_size"] + delta)
        elif export["serial_offset"] >= cdo_end:
            struct.pack_into("<q", header, at + 8, export["serial_offset"] + delta)
    for field in ("bulk_data_start_offset", "payload_toc_offset"):
        value = getattr(h, field)
        if value >= cdo_end:
            struct.pack_into("<q", header, getattr(h, field + "_off"), value + delta)
        elif field == "bulk_data_start_offset" and value > 0:
            raise CurveStructureError("bulk data starts within the edited CDO")
    header, result = bytes(header), bytes(result)
    # Reparse boundaries and key counts before permitting a package to ship.
    verified = read_curves(header, result)
    for root, curves in requests.items():
        for key, (data, _) in curves.items():
            expected = [[r[3], r[4]] for r in _KEY.iter_unpack(data)]
            if verified[root][key] != expected:
                raise CurveStructureError("curve verification failed after resizing")
    return header, result
