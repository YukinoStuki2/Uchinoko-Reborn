"""Shared loading of final physics metadata for full builds and fast repacks."""
from __future__ import annotations

import json
import math
from pathlib import Path

from sway_allocator_wire import NODE_OVERRIDES_FILENAME
from sway_motion import sanitize_motion_settings


class SwayNodeMetadataError(ValueError):
    pass


def load_node_overrides(job):
    """Read the exact final donor metadata; never discard opted-in tuning.

    Empty metadata is valid when no candidates survive placement. Legacy jobs
    without per-component tuning retain their pre-metadata uniform fallback.
    A corrupt existing file is always an error rather than an unbounded reset.
    """
    required = job.get("sway_adaptation") == "physbone-v1" or any(isinstance(entry, dict) and
                   sanitize_motion_settings(entry.get("motion")) is not None
                   for entry in (job.get("sway_chain_overrides") or []))
    directory = job.get("job_dir")
    path = Path(directory) / "converted" / NODE_OVERRIDES_FILENAME if directory else None
    if path is None or not path.is_file():
        if required:
            raise SwayNodeMetadataError(
                "Motion settings require final sway node metadata. Run a full conversion before repacking.")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise SwayNodeMetadataError(
            "Cannot read final sway node metadata. Run a full conversion before repacking.") from exc
    if not isinstance(data, dict) or any(not isinstance(key, str) or not key or not isinstance(value, dict)
                                        for key, value in data.items()):
        raise SwayNodeMetadataError(
            "Invalid final sway node metadata. Run a full conversion before repacking.")
    from sway_auto import enabled, input_fingerprint, validate_profile
    if enabled(job):
        # Each Blender pass owns only its gender's actual geometry. The old
        # common file is overwritten by the last pass, so load both final
        # manifests before building all twenty animation blueprints.
        result = {key: {k: v for k, v in value.items() if k != 'source_profile'}
                  for key, value in data.items()}
        resolved = {}
        try:
            genders = {str(g).lower() for g in job.get('genders', ('female', 'male'))}
            if not genders or not genders <= {'female', 'male'}:
                raise ValueError('invalid requested genders')
            for gender in sorted(genders):
                manifest_path = path.parent / f'sway_adaptation_{gender}.json'
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                if (manifest.get('format') != 'uchinoko-reborn-sway-adaptation-1' or
                        manifest.get('gender') != gender or
                        manifest.get('mode') != 'physbone-v1' or
                        manifest.get('input_fingerprint') != input_fingerprint(job)):
                    raise ValueError('stale automatic source metadata')
                current = manifest.get('node_overrides')
                if not isinstance(current, dict):
                    raise ValueError('missing final gender node metadata')
                if manifest.get('active_physbone_anchors') and not current:
                    raise ValueError('active PhysBones have no final parameters')
                components = manifest.get('components')
                if not isinstance(components, list) or any(not isinstance(c, dict) for c in components):
                    raise ValueError('missing automatic component inventory')
                if {c.get('anchor') for c in components} != set(manifest.get('active_physbone_anchors', [])):
                    raise ValueError('inconsistent active PhysBone inventory')
                if {c.get('target_root') for c in components} != set(current):
                    raise ValueError('incomplete automatic node metadata')
                for root, value in current.items():
                    if not isinstance(value, dict):
                        raise ValueError('invalid node metadata')
                    profile = value.get('source_profile')
                    if profile is not None:
                        validate_profile(profile)
                    elif not value.get('motion'):
                        raise ValueError('missing source profile')
                    if root in resolved and not _same_effective_profile(resolved[root], value):
                        raise ValueError(f'gender physics differs on shared root {root}')
                    resolved[root] = value
            result.update(resolved)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise SwayNodeMetadataError(
                f'Cannot use automatic PhysBone metadata ({exc}). Run a full conversion before repacking.') from exc
        return result
    return data


def _same_effective_profile(left, right):
    """Shared roots can differ in report labels, but not effective physics."""
    if 'source_profile' not in left or 'source_profile' not in right:
        return left == right
    a, b = left['source_profile'], right['source_profile']
    for key in a['params']:
        if not math.isclose(a['params'][key], b['params'][key], rel_tol=1e-5, abs_tol=1e-6):
            return False
    for key, points in a['extended_curves'].items():
        other = b['extended_curves'][key]
        if len(points) != len(other) or any(
            not math.isclose(x, y, rel_tol=1e-5, abs_tol=1e-6)
            for first, second in zip(points, other) for x, y in zip(first, second)):
            return False
    return True
