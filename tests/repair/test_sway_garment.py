"""Independent garment roots must not disturb the existing physics layout."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pipeline/py'))
import sway_allocator
import sway_garment
import sway_hub
import sway_hub_wire
import sway_hub_placement
import extract_vanilla
import pak_live_extract


def fixture(count=24, free_count=140):
    rows = []
    parents = {'Hips': 'Armature', 'DressHem': 'Hips'}
    weights = set()
    for i in range(count):
        names = [f'Panel{i}_{j}' for j in range(4)]
        parents[names[0]] = 'DressHem'
        parents.update(dict(zip(names[1:], names)))
        weights.update(names[:-1])
        rows.append({'anchor': names[0], 'enabled': True, 'active_in_hierarchy': True,
                     'chains': [names[1:]], 'params': {
                         'limit_type': 'Polar', 'max_angle_x': 30, 'max_angle_z': 3,
                         'limit_rotation': [float(i), 0, 0], 'pull': .4, 'spring': .25,
                         'stiffness': .2, 'gravity': 0, 'immobile': .8,
                         'radius': .01 + i * .001, 'curves': {'radius': {'keys': []}}}})
    units = tuple(sway_allocator.parse_physbones({'physbones': rows}))
    bones = [dict(name='root', parent_idx=-1), dict(name='pelvis', parent_idx=0)]
    old = []
    for i in range(9):
        root, tip = f'old_root_{i}', f'old_tip_{i}'
        root_index = len(bones)
        bones.extend((dict(name=root, parent_idx=1), dict(name=tip, parent_idx=root_index)))
        unit = replace(units[0], key=f'old:{i}', anchor=f'old_source_{i}',
                       chains=((f'old_source_tip_{i}',),), style='kata')
        group = sway_allocator.SwayGroup((unit.anchor, 'kata'), unit.anchor, 'kata',
                                        (unit,), unit.chains, 1, False)
        chain = sway_hub.ChainDonorPlan((unit.anchor, unit.chains[0][0]), (tip,), (tip,),
                                      {unit.anchor: unit.anchor, unit.chains[0][0]: unit.chains[0][0]})
        old.append(sway_hub.GroupHubPlan(group, root, root, 'Hips', (chain,)))
    bones.append(dict(name='M_Hunter001_17', parent_idx=1))
    bones.append(dict(name='HunterChild', parent_idx=len(bones)-1))
    bones.extend(dict(name=f'free_{i:03}', parent_idx=1) for i in range(free_count))
    for b in bones:
        b.update(fname_base=b['name'], fname_number=0)
    wiring = sway_hub.HubWiringPlan(tuple(old), (), ('prior fit event',))
    catalog = sway_hub.SkeletonCatalog.from_bones_list(bones)
    kwargs = dict(conservative_garment=True, source_parents=parents, weighted_bones=weights,
                  anchor_pal_name_of={'Hips': 'pelvis'}, reserved=frozenset({'HunterChild'}),
                  protected=frozenset({'root', 'pelvis', 'free_000'}),
                  known_moving=frozenset({'free_001'}), hub_root_names=('M_Hunter001_17',))
    return wiring, units, catalog, kwargs


def plan(data):
    wiring, units, catalog, kwargs = data
    return sway_garment.plan_conservative_garment(wiring, units, catalog, **kwargs)


def test_disabled_preserves_the_exact_previous_plan():
    data = fixture()
    data[3]['conservative_garment'] = False
    result = plan(data)
    assert result.wiring is data[0]
    assert not result.group_plans and not result.node_request


def test_sibling_panels_get_separate_fixed_roots_and_exact_weight_mapping():
    original, units, catalog, kwargs = fixture()
    before = sway_hub_wire.source_to_donor_bone_map(original, 'Female')
    result = sway_garment.plan_conservative_garment(original, units, catalog, **kwargs)
    assert len(result.wiring.group_plans) == 33
    assert result.wiring.group_plans[:9] == original.group_plans
    assert all(a is b for a, b in zip(result.wiring.group_plans, original.group_plans))
    assert result.wiring.chain_fit_events == original.chain_fit_events
    assert len(result.group_plans) == 24
    assert result.node_request['root_bone'] == 'M_Hunter001_17'
    roots = [g.hub_root_female for g in result.group_plans]
    assert result.node_request['simulation_root'] == roots[0]
    assert result.node_request['additional_roots'] == roots[1:]
    assert len(set(roots)) == 24
    for gender in ('Female', 'Male'):
        mapping = sway_hub_wire.source_to_donor_bone_map(result.wiring, gender)
        assert all(mapping[k] == v for k, v in before.items())
        for unit, group in zip(units, result.group_plans):
            cp = group.chain_plans[0]
            targets = (group.hub_root_female, *cp.donor_chain_for(gender))
            source = (unit.anchor, *unit.chains[0])
            assert len(targets) == 5 and len(source) == 4
            assert cp.weight_expansion == {name: name for name in source}
            assert [mapping[name] for name in source] == list(targets[:-1])
            assert targets[-1] not in mapping.values()
            assert group.anchor_target == 'Hips'
            assert list(map(catalog.index_of, targets)) == sorted(map(catalog.index_of, targets))
    added = {n for g in result.group_plans for n in (g.hub_root_female, *g.chain_plans[0].donor_chain_female)}
    assert len(added) == 120
    assert not added & {'M_Hunter001_17', 'HunterChild', 'free_000', 'free_001'}
    assert not added & set(before.values())
    assert set(result.node_request['bone_fnames']) == set(roots)


@pytest.mark.parametrize('problem', ('branch', 'nested', 'nonlinear', 'missing_weight',
                                    'different_response', 'disabled', 'animated',
                                    'stretch', 'different_curves', 'overlapping_component',
                                    'dynamic_parent'))
def test_unsupported_source_family_fails_closed(problem):
    wiring, units, catalog, kwargs = fixture()
    units = list(units)
    unit = units[0]
    params = copy.deepcopy(unit.params)
    if problem == 'branch':
        unit = replace(unit, chains=unit.chains + (('extra',),))
    elif problem == 'nested':
        kwargs['source_parents'][unit.anchor] = units[1].chains[0][0]
    elif problem == 'nonlinear':
        kwargs['source_parents'][unit.chains[0][1]] = 'DressHem'
    elif problem == 'missing_weight':
        kwargs['weighted_bones'].discard(unit.chains[0][0])
    elif problem == 'different_response':
        params['spring'] = .9
    elif problem == 'disabled':
        unit = replace(unit, source_disabled_reason='disabled by Unity')
    elif problem == 'animated':
        params['is_animated'] = True
    elif problem == 'stretch':
        params['max_stretch'] = .1
    elif problem == 'different_curves':
        params['curves']['pull'] = {'samples': [{'time': 0, 'value': .5}]}
    elif problem == 'overlapping_component':
        units.append(replace(unit, key='nested:duplicate', anchor=unit.chains[0][0],
                             chains=(unit.chains[0][1:],)))
    elif problem == 'dynamic_parent':
        units.append(replace(unit, key='dynamic:parent', anchor='DressHem',
                             chains=((unit.anchor, *unit.chains[0]),),
                             params={**params, 'limit_type': 'Angle'}))
    units[0] = replace(unit, params=params)
    result = sway_garment.plan_conservative_garment(wiring, units, catalog, **kwargs)
    assert result.wiring is wiring
    assert not result.group_plans and result.diagnostics


def test_no_matching_real_physbone_or_wrong_hierarchy_is_not_a_garment():
    wiring, units, catalog, kwargs = fixture()
    result = sway_garment.plan_conservative_garment(wiring, (), catalog, **kwargs)
    assert result.wiring is wiring
    kwargs['source_parents']['DressHem'] = 'Head'
    result = sway_garment.plan_conservative_garment(wiring, units, catalog, **kwargs)
    assert result.wiring is wiring


def test_insufficient_safe_donors_does_not_partially_enable_a_skirt():
    data = fixture(free_count=90)
    result = plan(data)
    assert result.wiring is data[0]
    assert any('120' in line and 'donor' in line for line in result.diagnostics)


def test_unrelated_leaf_descendant_of_a_moving_bone_is_reserved_by_caller():
    data = fixture()
    data[3]['reserved'] |= {'free_002', 'free_003'}
    result = plan(data)
    assert result.group_plans[0].hub_root_female == 'free_004'


def test_weighted_source_tip_gets_an_extra_unweighted_simulated_endpoint():
    wiring, units, catalog, kwargs = fixture()
    kwargs['weighted_bones'].update(u.chains[0][-1] for u in units)
    result = sway_garment.plan_conservative_garment(wiring, units, catalog, **kwargs)
    assert len(result.group_plans) == 24
    mapping = sway_hub_wire.source_to_donor_bone_map(result.wiring, 'Female')
    all_targets = set()
    for group in result.group_plans:
        cp = group.chain_plans[0]
        targets = (group.hub_root_female, *cp.donor_chain_female)
        assert len(targets) == 5
        assert targets[-1] not in mapping.values()
        assert [mapping[source] for source in cp.source_chain] == list(targets[:-1])
        all_targets.update(targets)
    assert len(all_targets) == 120
    manifest = sway_hub_wire.source_adaptation_manifest(
        sway_hub.HubWiringPlan(result.group_plans, ()), 'Female')
    assert len(manifest['preserved_physbone_anchors']) == 24
    assert all(row['unweighted_terminal_bones'] == 1 for row in manifest['components'])


def test_existing_geometry_resolver_places_the_extra_endpoint_after_the_source_tip():
    wiring, units, catalog, kwargs = fixture()
    kwargs['weighted_bones'].update(u.chains[0][-1] for u in units)
    result = sway_garment.plan_conservative_garment(wiring, units, catalog, **kwargs)
    group = result.group_plans[0]
    cp = group.chain_plans[0]
    avatar = {name: {'head': [0, i, 0], 'tail': [0, i + 1, 0]}
              for i, name in enumerate(cp.source_chain)}
    sim = sway_hub_placement.Similarity(1.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    anchor, heads, tails, _ = sway_hub_placement.resolve_grouped_chain(
        avatar, sim, cp, group.group.anchor, cp.donor_chain_female)
    assert anchor == (0.0, 0.0, 0.0)
    assert heads == [(0.0, float(i), 0.0) for i in range(1, 5)]
    assert tails[-1] == (0.0, 5.0, 0.0)


def test_missing_fname_metadata_is_left_for_job_identity_loader_not_guessed():
    wiring, units, catalog, kwargs = fixture()
    bones = [{k: v for k, v in b.items() if not k.startswith('fname_')} for b in catalog.bones]
    result = sway_garment.plan_conservative_garment(
        wiring, units, sway_hub.SkeletonCatalog.from_bones_list(bones), **kwargs)
    assert result.group_plans
    assert 'bone_fnames' not in result.node_request


def template_asset(tmp_path, name):
    path = tmp_path / 'Player' / 'Outfit' / name / (name + '.uasset')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    path.with_suffix('.uexp').touch()
    return path


def test_mesh_protection_reads_all_genders_and_excluded_equipment(tmp_path, monkeypatch):
    female = template_asset(tmp_path, 'SK_Player_Female_Outfit_Hunter001')
    male = template_asset(tmp_path, 'SK_Player_Male_Outfit_Plastic001')
    excluded = template_asset(tmp_path, 'SK_Player_Male_Outfit_Octavia001_v02')
    material = template_asset(tmp_path, 'MI_IgnoredMaterial')
    rows = {str(female): {'pelvis': {}, 'native_f': {}},
            str(male): {'pelvis': {}, 'native_m': {}},
            str(excluded): {'pelvis': {}, 'native_collab': {}}}
    seen = []
    def read(path, min_bones=40):
        seen.append(path)
        return rows[path]
    monkeypatch.setattr(sway_garment.core, 'load_refskel', read)
    monkeypatch.setattr(sway_garment, '_source_mesh_inventory', lambda pak: (frozenset(), {}))
    assert sway_garment.protected_mesh_bones(tmp_path, palworld_pak='unused') == frozenset(
        {'pelvis', 'native_f', 'native_m', 'native_collab'})
    assert set(seen) == set(rows)
    assert str(material) not in seen


@pytest.mark.parametrize('problem', ('empty', 'missing_uexp', 'unreadable', 'empty_bones'))
def test_incomplete_mesh_inventory_fails_closed(tmp_path, monkeypatch, problem):
    if problem != 'empty':
        asset = template_asset(tmp_path, 'SK_Player_Female_Outfit_Test')
        if problem == 'missing_uexp':
            asset.with_suffix('.uexp').unlink()
    def read(path):
        if problem == 'unreadable':
            raise RuntimeError('truncated RefSkeleton')
        return {} if problem == 'empty_bones' else {'root': {}}
    monkeypatch.setattr(sway_garment.core, 'load_refskel', read)
    with pytest.raises(ValueError, match='Garment donor protection'):
        sway_garment.protected_mesh_bones(tmp_path, palworld_pak='unused')


def test_native_mesh_bones_are_never_allocated_even_when_original_leaves(tmp_path, monkeypatch):
    template_asset(tmp_path, 'SK_Player_Male_Outfit_Test')
    monkeypatch.setattr(sway_garment.core, 'load_refskel', lambda path: {'free_002': {}, 'free_003': {}})
    monkeypatch.setattr(sway_garment, '_source_mesh_inventory', lambda pak: (frozenset(), {}))
    data = fixture()
    data[3]['protected'] |= sway_garment.protected_mesh_bones(tmp_path, palworld_pak='unused')
    result = plan(data)
    assert result.group_plans[0].hub_root_female == 'free_004'
    chosen = {b for group in result.group_plans for chain in group.chain_plans
              for b in (group.hub_root_female, *chain.donor_chain_female)}
    assert not chosen & {'free_002', 'free_003'}


def source_inventory_fixture(tmp_path, monkeypatch):
    pak = tmp_path / 'Pal-Windows.pak'
    pak.write_bytes(b'fixture pak identity')
    pairs = {}
    for category, root in extract_vanilla.SK_CATEGORY_ROOTS.items():
        # Unknown family names and nested variants must be discovered by location.
        stem = f'Pal/Content/{root}/NewFamily/v02/SK_{category}_variant'
        pairs[stem + '.uasset'] = category.encode()
        pairs[stem + '.uexp'] = b'refskeleton fixture'
    monkeypatch.setattr(sway_garment.core, 'read_pak_entries', lambda path: ('../../../', dict(pairs)))
    monkeypatch.setattr(pak_live_extract, 'extract_files', lambda path, names: {n: pairs[n] for n in names})
    def read(path, min_bones=40):
        assert min_bones == 1
        category = Path(path).read_text()
        return {'pelvis': {}, 'free_' + {'outfit': '004', 'head': '005', 'hair': '006', 'headequip': '007'}.get(category, '008'): {}}
    monkeypatch.setattr(sway_garment.core, 'load_refskel', read)
    return pak, pairs


def test_original_pak_bones_protect_omitted_and_stubbed_headgear(tmp_path, monkeypatch):
    pak, pairs = source_inventory_fixture(tmp_path, monkeypatch)
    original, report = sway_garment._source_mesh_inventory(pak)
    assert original == frozenset({'pelvis', 'free_004', 'free_005', 'free_006', 'free_007'})
    assert report['category_counts'] == dict.fromkeys(extract_vanilla.SK_CATEGORY_ROOTS, 1)
    assert len(report['meshes']) == 4
    assert all(len(row['uasset_sha256']) == len(row['uexp_sha256']) == 64 for row in report['meshes'])
    data = fixture()
    data[3]['protected'] |= original
    result = plan(data)
    chosen = {b for group in result.group_plans for chain in group.chain_plans
              for b in (group.hub_root_female, *chain.donor_chain_female)}
    assert not chosen & original
    assert result.wiring.group_plans[:9] == data[0].group_plans


def test_new_player_categories_are_included_without_extending_an_allowlist(tmp_path, monkeypatch):
    pak, pairs = source_inventory_fixture(tmp_path, monkeypatch)
    stem = 'Pal/Content/Pal/Model/Character/Player/NewCategory/v03/SK_future'
    pairs[stem + '.uasset'] = b'newcategory'
    pairs[stem + '.uexp'] = b'new category refskeleton'
    # Associated assets and other character trees are not skeletal meshes.
    pairs[stem + '_Skeleton.uasset'] = b'not a mesh'
    pairs['Pal/Content/Pal/Model/Character/Monster/SK_test.uasset'] = b'not a player'
    original, report = sway_garment._source_mesh_inventory(pak)
    assert 'free_008' in original
    assert report['category_counts']['newcategory'] == 1
    assert len(report['meshes']) == 5


@pytest.mark.parametrize('problem', ('missing_pak', 'empty_category', 'missing_uexp',
                                    'extraction_gap', 'unreadable', 'empty_bones'))
def test_source_inventory_cannot_silently_weaken_protection(tmp_path, monkeypatch, problem):
    pak, pairs = source_inventory_fixture(tmp_path, monkeypatch)
    if problem == 'missing_pak':
        pak.unlink()
    elif problem == 'empty_category':
        for key in list(pairs):
            if '/Hair/' in key:
                del pairs[key]
    elif problem == 'missing_uexp':
        del pairs[next(key for key in pairs if key.endswith('.uexp'))]
    elif problem == 'extraction_gap':
        monkeypatch.setattr(pak_live_extract, 'extract_files', lambda path, names: {})
    elif problem == 'unreadable':
        def fail(*args, **kwargs):
            raise RuntimeError('truncated')
        monkeypatch.setattr(sway_garment.core, 'load_refskel', fail)
    elif problem == 'empty_bones':
        monkeypatch.setattr(sway_garment.core, 'load_refskel', lambda *args, **kwargs: {})
    with pytest.raises(ValueError, match='Garment donor protection'):
        sway_garment._source_mesh_inventory(pak)


def test_protection_report_records_actual_source_and_template_union(tmp_path, monkeypatch):
    pak, _ = source_inventory_fixture(tmp_path, monkeypatch)
    source_bones, source_report = sway_garment._source_mesh_inventory(pak)
    template_asset(tmp_path, 'SK_Player_Female_Outfit_Test')
    monkeypatch.setattr(sway_garment.core, 'load_refskel', lambda path: {'template_only': {}})
    monkeypatch.setattr(sway_garment, '_source_mesh_inventory', lambda path: (source_bones, source_report))
    report_path = tmp_path / 'donor_protection.json'
    protected = sway_garment.protected_mesh_bones(tmp_path, palworld_pak=pak, report_path=report_path)
    report = json.loads(report_path.read_text())
    assert protected == source_bones | {'template_only'}
    assert set(report['protected_bones']) == protected
    assert set(report['source_bones']) == source_bones
    assert report['pak']['size'] == pak.stat().st_size
    assert report['format'] == 'garment-native-donor-protection-v1'
