"""Opt-in, bounded sway for sibling garment PhysBone chains.

One KawaiiPhysics node may share response parameters across independent roots.
It must never share their pivots, merge their weights, or steal an existing
physics slot. This planner appends exact chains to an already accepted layout;
the caller writes their separate additional-root node after placement checks.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import tempfile
from typing import Mapping, Sequence

import sway_allocator
import sway_hub
import sway_limits
import vp_core as core


GARMENT_MODE = 'conservative_garment'
TEMPLATE_ROOT = 'M_Hunter001_17'
MAX_ANGLE = 3.0
_GARMENT_WORDS = ('skirt', 'dress', 'hem', 'スカート', '裙')
_RESPONSE_FIELDS = (
    'pull', 'spring', 'stiffness', 'gravity', 'gravity_falloff', 'immobile',
    'immobile_type', 'integration_type', 'version', 'is_animated',
    'stretch_motion', 'max_stretch', 'max_squish', 'limit_type', 'max_angle_x',
    'max_angle_z', 'multi_child_type', 'ignore_transforms', 'ignore_other_physbones',
    'reset_when_disabled', 'colliders',
)
_APPROXIMATED_CURVES = frozenset(('radius', 'limit_rotation_x', 'limit_rotation_y',
                                'limit_rotation_z'))


@dataclass(frozen=True)
class GarmentPlan:
    wiring: sway_hub.HubWiringPlan
    group_plans: tuple[sway_hub.GroupHubPlan, ...] = ()
    units: tuple[sway_allocator.ChainUnit, ...] = ()
    node_request: Mapping[str, object] | None = None
    diagnostics: tuple[str, ...] = ()


def _source_mesh_inventory(palworld_pak):
    """Read native geometry bones, including assets omitted/stubbed by templates.

    Discovery follows the whole Player tree, not a family/category allowlist.
    Only short-lived extracted files are written; no stale inventory cache can
    survive a game update or be shipped as a user's local build input.
    """
    import extract_vanilla
    import pak_live_extract

    pak = Path(palworld_pak).resolve() if palworld_pak else None
    if pak is None or not pak.is_file():
        raise ValueError(f'Garment donor protection: source Palworld PAK is missing: {palworld_pak}')
    before = pak.stat()
    prefix = extract_vanilla.PAK_CONTENT_PREFIX + 'Pal/Model/Character/Player/'
    try:
        _, entries = core.read_pak_entries(str(pak))
        assets = sorted(name for name in entries if name.startswith(prefix)
                        and name.endswith('.uasset')
                        and extract_vanilla.is_mesh_sk_name(Path(name).stem))
        counts = {}
        for name in assets:
            category = name[len(prefix):].split('/')[0].lower()
            counts[category] = counts.get(category, 0) + 1
        if any(not counts.get(category) for category in extract_vanilla.SK_CATEGORY_ROOTS):
            raise ValueError('incomplete Player mesh inventory (Outfit/Head/Hair/HeadEquip required)')
        paths = [sidecar for name in assets for sidecar in (name, name[:-7] + '.uexp')]
        missing = set(paths).difference(entries)
        if missing:
            raise ValueError(f'missing source mesh sidecar: {sorted(missing)[0]}')
        extracted = pak_live_extract.extract_files(str(pak), paths)
        if set(extracted) != set(paths):
            raise ValueError('source extraction did not return the complete Player mesh inventory')
        protected, rows = set(), []
        with tempfile.TemporaryDirectory(prefix='uchinoko_native_bones_') as temporary:
            for index, name in enumerate(assets):
                asset = Path(temporary) / f'mesh_{index}.uasset'
                uasset = extracted.pop(name)
                uexp = extracted.pop(name[:-7] + '.uexp')
                asset.write_bytes(uasset)
                asset.with_suffix('.uexp').write_bytes(uexp)
                try:
                    refs = core.load_refskel(str(asset), min_bones=1)
                    if not isinstance(refs, Mapping) or not refs or any(
                            not isinstance(bone, str) or not bone for bone in refs):
                        raise ValueError('empty or invalid native bones')
                except Exception as exc:
                    raise ValueError(f'cannot read original mesh {name}: {exc}') from exc
                protected.update(refs)
                rows.append({'path': name, 'bone_count': len(refs),
                             'uasset_sha256': hashlib.sha256(uasset).hexdigest(),
                             'uexp_sha256': hashlib.sha256(uexp).hexdigest()})
                asset.unlink()
                asset.with_suffix('.uexp').unlink()
        after = pak.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('source PAK changed while reading native bones; retry after the update finishes')
    except (Exception, SystemExit) as exc:
        raise ValueError(f'Garment donor protection: {exc}') from exc
    return frozenset(protected), {
        'pak': {'path': str(pak), 'size': before.st_size, 'mtime_ns': before.st_mtime_ns},
        'category_counts': counts, 'meshes': rows,
        'source_bones': sorted(protected),
    }


def protected_mesh_bones(template_dir, *, palworld_pak, report_path=None) -> frozenset[str]:
    """Protect native bones from source game meshes and original outfit templates.

    A donor absent from OldCloth can already have an early index in another
    equipment mesh. Appending its planned parent there cannot legally reparent
    that existing bone. Read the original templates before allocation so all
    new garment bones are appended consistently instead. Both genders and
    excluded equipment are included: the shared Skeleton still affects those
    meshes even when their geometry is not injected.

    ``library/sk`` and ``noue_work/variant`` are converted outputs, not inputs
    for this function. The caller must supply its live/override template root.
    Templates can replace Head/Hair/HeadEquip meshes with empty stubs or omit
    visible native equipment. Therefore their inventory alone cannot protect
    those geometry bones; the original Player meshes in the source PAK are
    always read too. Incomplete or unreadable inputs are errors, never empty
    protection sets that would silently permit unsafe donors.
    """
    outfit_root = Path(template_dir) / 'Player' / 'Outfit'
    assets = sorted(outfit_root.rglob('SK_*.uasset')) if outfit_root.is_dir() else []
    if not assets:
        raise ValueError(f'Garment donor protection: no original outfit meshes under {outfit_root}')
    protected = set()
    for asset in assets:
        if not asset.with_suffix('.uexp').is_file():
            raise ValueError(f'Garment donor protection: missing .uexp for {asset.name}')
        try:
            refskel = core.load_refskel(str(asset))
        except Exception as exc:
            raise ValueError(f'Garment donor protection: cannot read native bones of {asset.name}') from exc
        if not isinstance(refskel, Mapping) or not refskel or any(
                not isinstance(name, str) or not name for name in refskel):
            raise ValueError(f'Garment donor protection: empty or invalid native bones in {asset.name}')
        protected.update(refskel)
    source_bones, report = _source_mesh_inventory(palworld_pak)
    protected.update(source_bones)
    if report_path is not None:
        report.update(format='garment-native-donor-protection-v1',
                      template_outfit_meshes=len(assets), protected_bones=sorted(protected))
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return frozenset(protected)


def _ancestors(name, parents):
    result, seen = [], {name}
    while parents.get(name):
        name = parents[name]
        if name in seen:
            return ()  # A malformed hierarchy cannot identify a safe anchor.
        seen.add(name)
        result.append(name)
    return tuple(result)


def _is_candidate(unit, source_parents, hips_source):
    if unit.source != 'pb' or unit.params.get('limit_type') != 'Polar':
        return False
    ancestors = _ancestors(unit.anchor, source_parents)
    if hips_source not in ancestors:
        return False
    local_path = (unit.anchor, *ancestors[:ancestors.index(hips_source)])
    return any(word in name.casefold() for name in local_path for word in _GARMENT_WORDS)


def _response_signature(unit):
    params = unit.params
    values = {key: params.get(key) for key in _RESPONSE_FIELDS}
    values['curves'] = {key: value for key, value in (params.get('curves') or {}).items()
                        if key not in _APPROXIMATED_CURVES}
    return json.dumps(values, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _used_bones(wiring):
    used = set()
    for group in wiring.group_plans:
        used.update((group.hub_root_female, group.hub_root_male))
        for chain in group.chain_plans:
            used.update(chain.donor_chain_female)
            used.update(chain.donor_chain_male)
    return used


def plan_conservative_garment(
    wiring: sway_hub.HubWiringPlan,
    units: Sequence[sway_allocator.ChainUnit],
    catalog: sway_hub.SkeletonCatalog,
    *,
    conservative_garment: bool = False,
    source_parents: Mapping[str, str],
    weighted_bones: Sequence[str],
    anchor_pal_name_of: Mapping[str, str],
    reserved: frozenset[str],
    protected: frozenset[str],
    known_moving: frozenset[str],
    hub_root_names: Sequence[str] = (),
    hips_source: str = 'Hips',
) -> GarmentPlan:
    """Append one compatible sibling family without altering previous groups.

    Source hierarchy and actual vertex weights are required evidence. Naming
    only narrows real enabled PhysBone candidates; it cannot create physics.
    Radius, directional frames and source colliders are not reproduced by this
    opt-in mode. Its separate node must have radius/gravity zero and at most a
    three-degree rest-centred cone. Source scalar/curve response remains the
    input to the existing automatic parameter conversion.

    Returned ``node_request`` provides topology only. The caller adds validated
    ``params``/``curves`` after final geometry, and raw ``bone_fnames`` through
    the job identity loader when an older catalog lacks them. Failure leaves
    the original wiring object unchanged, with an actionable diagnostic.
    """
    def reject(reason):
        return GarmentPlan(wiring, diagnostics=(f'[garment] {reason}',))

    if conservative_garment is not True:
        return GarmentPlan(wiring)
    candidates = tuple(u for u in units if _is_candidate(u, source_parents, hips_source))
    if not candidates:
        return reject('No compatible garment PhysBone family below the hips was found.')
    if len(candidates) < 2:
        return reject('At least two independent sibling garment PhysBones are required.')
    if len({source_parents.get(u.anchor) for u in candidates}) != 1:
        return reject('Garment roots are not siblings; nested or separate families cannot share this node.')
    anchor_pal = anchor_pal_name_of.get(hips_source)
    if anchor_pal not in catalog.name_to_idx or anchor_pal not in protected:
        return reject('The hips must resolve to a protected humanoid bone before garment wiring.')
    old_keys = {u.key for g in wiring.group_plans for u in g.group.units}
    old_sources = {name for g in wiring.group_plans for c in g.chain_plans
                   for name in c.weight_expansion}
    all_sources, lengths, signatures, angles = set(), set(), set(), []
    weighted = frozenset(weighted_bones)
    for unit in candidates:
        if unit.key in old_keys or unit.source_disabled_reason or unit.lab_override:
            return reject(f'{unit.anchor}: already allocated, disabled, or manually overridden PhysBone.')
        if unit.nested_parent_key or len(unit.chains) != 1 or not unit.chains[0]:
            return reject(f'{unit.anchor}: branching or nested garment PhysBones are unsupported.')
        path = (unit.anchor, *unit.chains[0])
        if len(path) < 3 or len(set(path)) != len(path):
            return reject(f'{unit.anchor}: a unique chain with a real terminal bone is required.')
        if any(source_parents.get(child) != parent for parent, child in zip(path, path[1:])):
            return reject(f'{unit.anchor}: source bones do not form the exported linear hierarchy.')
        if not set(path[:-1]) <= weighted:
            return reject(f'{unit.anchor}: every nonterminal segment needs source weights.')
        if all_sources.intersection(path) or old_sources.intersection(path):
            return reject(f'{unit.anchor}: source weights overlap another physics component.')
        # Independent components beneath these chains also have their own pivot
        # semantics. Even an inactive/non-garment child is not silently absorbed.
        for other in units:
            ancestors = _ancestors(unit.anchor, source_parents)
            if other.key != unit.key and (other.anchor in path or
                    other.anchor in ancestors[:ancestors.index(hips_source)]):
                return reject(f'{unit.anchor}: nested or duplicate PhysBone component detected.')
        params = unit.params
        if params.get('is_animated') or any(params.get(k, 0) != 0 for k in
                                          ('stretch_motion', 'max_stretch', 'max_squish')):
            return reject(f'{unit.anchor}: animated or stretching garments need a separate conversion.')
        limit = sway_limits.convert_limit(params, compatibility=True)
        if not limit.supported or not math.isfinite(limit.angle) or limit.angle <= 0:
            return reject(f'{unit.anchor}: no positive bounded Polar approximation is available.')
        try:
            signatures.add(_response_signature(unit))
        except (TypeError, ValueError, AttributeError):
            return reject(f'{unit.anchor}: malformed response parameters or source curves.')
        angles.append(min(MAX_ANGLE, limit.angle))
        all_sources.update(path)
        lengths.add(len(path))
    if len(lengths) != 1 or len(signatures) != 1:
        return reject('Sibling garments have incompatible chain lengths, response parameters or curves.')

    used = _used_bones(wiring)
    roots = set(hub_root_names) | {TEMPLATE_ROOT}
    pool = sway_hub.free_donor_pool(catalog, frozenset(set(reserved) | used),
                                    tuple(roots), protected, known_moving)
    parent_indices = {b['parent_idx'] for b in catalog.bones if b['parent_idx'] >= 0}
    hips_index = catalog.index_of(anchor_pal)
    # Reusing an original leaf prevents KawaiiPhysics from traversing unrelated
    # old children. Ascending indices preserve the shared-skeleton topology rule.
    pool = [name for name in pool if catalog.index_of(name) not in parent_indices
            and catalog.index_of(name) > hips_index]
    need = sum(2 + len(u.chains[0]) for u in candidates)
    if len(pool) < need:
        return reject(f'Insufficient safe leaf donors: need {need}, available {len(pool)}; garment left unchanged.')

    groups, converted, cursor = [], [], 0
    for unit, angle in zip(candidates, angles):
        source = (unit.anchor, *unit.chains[0])
        # A weighted terminal still needs a simulated child endpoint. Use the
        # existing hub placement convention: its extra donor extends from the
        # last source tail and deliberately has no source weight assignment.
        target_count = len(source) + 1
        targets = tuple(pool[cursor:cursor + target_count])
        cursor += target_count
        converted_unit = replace(unit, is_biased=False, bias_reason='', style='kata',
                                 limit_angle=angle, excluded_reason=None)
        converted.append(converted_unit)
        group = sway_allocator.SwayGroup((unit.anchor, GARMENT_MODE), unit.anchor, 'kata',
                                         (converted_unit,), unit.chains, unit.bone_count, False)
        chain = sway_hub.ChainDonorPlan(source, targets[1:], targets[1:],
                                       {name: name for name in source}, source)
        groups.append(sway_hub.GroupHubPlan(group, targets[0], targets[0], hips_source, (chain,)))
    new_roots = [group.hub_root_female for group in groups]
    request = dict(root_bone=TEMPLATE_ROOT, simulation_root=new_roots[0],
                   additional_roots=new_roots[1:], source_keys=[u.key for u in candidates])
    identities = {}
    for name in new_roots:
        bone = catalog.bones[catalog.index_of(name)]
        base, number = bone.get('fname_base'), bone.get('fname_number')
        if (not isinstance(base, str) or type(number) is not int or number < 0
                or (base if number == 0 else f'{base}_{number - 1}').casefold() != name.casefold()):
            identities = {}
            break
        identities[name] = [base, number]
    if identities:
        request['bone_fnames'] = identities
    combined = replace(wiring, group_plans=wiring.group_plans + tuple(groups))
    return GarmentPlan(combined, tuple(groups), tuple(converted), request, (
        f'[garment] Added {len(groups)} independent garment roots and {need} donor bones; '
        f'previous {len(wiring.group_plans)} groups are unchanged.',
        '[garment] Opt-in approximation: at most 3-degree rest-centred sway; source directional '
        'limits, radius and colliders are not reproduced.',
    ))
