"""Automatic source settings must reach cooked-node parameters without hand tuning."""
from pathlib import Path
from types import SimpleNamespace as N
import json
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'pipeline/py'))
import sway_auto
import sway_abp_build
from sway_node_overrides import load_node_overrides, SwayNodeMetadataError


def fixture(params, *, lengths=(1,3,2), motion=None):
    source=('Tail','A','B')
    unit=N(key='pb:Tail#0',source='pb',anchor='Tail',chains=(source[1:],),params=params)
    cp=N(source_chain=source,representative_source=source,
         donor_chain_female=('d1','d2','tip'),donor_chain_male=('d1','d2','tip'),
         weight_expansion={n:n for n in source},
         donor_chain_for=lambda gender:('d1','d2','tip'))
    gp=N(group=N(units=(unit,)),chain_plans=(cp,),hub_root_female='hub',hub_root_male='hub')
    wiring=N(group_plans=(gp,),chain_fit_events=())
    p=0;heads={'hub':(0,0,0)}
    for n,l in zip(('d1','d2','tip'),lengths):
        p+=l;heads[n]=(0,0,p)
    job={'sway_enable':True,'sway_adaptation':'physbone-v1'}
    overrides={'hub':{'limit_angle':45}}
    if motion:overrides['hub']['motion']=motion
    raw=[{'anchor':'Tail','chains':[list(source[1:])],'params':params}]
    return wiring,job,overrides,heads,raw


def build(params, **kwargs):
    w,j,o,h,r=fixture(params,**kwargs)
    overrides,report=sway_auto.attach_source_profiles(w,j,o,'Female',h,r)
    node=sway_abp_build.build_spec_nodes(['hub'],'futsuu',node_overrides=overrides)[0]
    return node,report


def test_default_auto_responds_continuously_to_source_parameters():
    common={'version':'Version_1_1','integration_type':'Advanced','spring':.4,'stiffness':.2}
    a,_=build(dict(common,pull=.2))
    b,_=build(dict(common,pull=.201))
    assert a['params']['stiffness']!=b['params']['stiffness']
    assert abs(a['params']['stiffness']-b['params']['stiffness'])<.01


def test_source_parent_depth_curve_moves_to_child_endpoint_arc_length():
    p={'version':'Version_1_1','integration_type':'Advanced','pull':1,'spring':0,
       'stiffness':0,'endpoint_position':[0,1,0],
       'curves':{'pull':{'keys':[{'time':0,'value':.2},{'time':1,'value':.8}],
                          'samples':[{'time':0,'value':.2},{'time':.5,'value':.5},{'time':1,'value':.8}]}}}
    node,_=build(p)
    for actual, expected in zip(node['extended_curves']['stiffness'], [[0,.2],[1/6,.2],[4/6,.5],[1,.8]]):
        assert [actual[0],actual[1]*node['params']['stiffness']]==pytest.approx(expected)


def test_immobile_mode_and_source_angle_are_preserved_per_component():
    node,_=build({'pull':.5,'spring':.2,'stiffness':0,'immobile':.7,'immobile_type':'World',
                  'version':'Version_1_1','integration_type':'Advanced',
                  'limit_type':'Angle','max_angle_x':12,'limit_rotation':[0,0,0]})
    assert all(v*node['params']['wdl']==.7 for _,v in node['extended_curves']['wdl'])
    assert all(v*node['params']['wdr']==0 for _,v in node['extended_curves']['wdr'])
    assert all(0<v*node['params']['limit_angle']<=12 for _,v in node['extended_curves']['limit_angle'])


def test_explicit_manual_tuning_keeps_existing_result():
    payload={'settings':{'profile':'calm','amount':.5},'source':'pb','source_params':{'pull':.5,'spring':.5}}
    node,report=build({'pull':.1},motion=payload)
    assert 'extended_curves' not in node
    assert report['components'][0]['parameter_mode']=='manual_override'


def test_old_job_does_not_add_automatic_metadata():
    w,j,o,h,r=fixture({'pull':.1});j.pop('sway_adaptation')
    changed,report=sway_auto.attach_source_profiles(w,j,o,'Female',h,r)
    assert changed==o and report is None


def test_missing_export_metadata_is_reported_without_fabricating_precision():
    _,report=build({'pull':.3,'spring':.4})
    warnings=report['components'][0]['warnings']
    assert any('version' in w.lower() for w in warnings)
    assert any('curve' in w.lower() for w in warnings)


def test_final_metadata_requires_both_genders_and_rejects_stale_source(tmp_path):
    w,j,o,h,r=fixture({'version':'Version_1_1','pull':.3,'spring':.4})
    j['job_dir']=str(tmp_path)
    directory=tmp_path/'converted';directory.mkdir()
    overrides,manifest=sway_auto.attach_source_profiles(w,j,o,'Female',h,r)
    (directory/'sway_node_overrides.json').write_text(json.dumps(overrides))
    (directory/'sway_adaptation_female.json').write_text(json.dumps(manifest))
    with pytest.raises(SwayNodeMetadataError,match='full conversion'):
        load_node_overrides(j)
    manifest['gender']='male'
    (directory/'sway_adaptation_male.json').write_text(json.dumps(manifest))
    loaded=load_node_overrides(j)
    assert loaded['hub']['source_profile']['params']==overrides['hub']['source_profile']['params']
    j['uniform_scale']=.5
    with pytest.raises(SwayNodeMetadataError,match='stale'):
        load_node_overrides(j)


def test_nonempty_source_curve_without_samples_cannot_silently_disappear():
    with pytest.raises(ValueError,match='no Unity-evaluated samples'):
        build({'pull':.3,'curves':{'pull':{'keys':[{'time':.4,'value':.7}]}}})


def test_fast_repack_rejects_profiles_from_older_conversion_rules(tmp_path, monkeypatch):
    w,j,o,h,r=fixture({'version':'Version_1_1','pull':.3,'spring':.4})
    j['job_dir']=str(tmp_path);j['genders']=['female']
    directory=tmp_path/'converted';directory.mkdir()
    overrides,manifest=sway_auto.attach_source_profiles(w,j,o,'Female',h,r)
    (directory/'sway_node_overrides.json').write_text(json.dumps(overrides))
    (directory/'sway_adaptation_female.json').write_text(json.dumps(manifest))
    assert load_node_overrides(j)
    monkeypatch.setattr(sway_auto, 'ADAPTATION_REVISION', sway_auto.ADAPTATION_REVISION+1)
    with pytest.raises(SwayNodeMetadataError,match='stale automatic source metadata'):
        load_node_overrides(j)


def test_radius_uses_child_transform_ratio_and_world_scale():
    params={'pull':.3,'radius':.02,'endpoint_position':[0,1,0],
            'curves':{'radius':{'keys':[{}], 'samples':[{'time':0,'value':0},{'time':1,'value':1}]}},
            'geometry':{'max_chain_index':2,'transforms':[
                {'name':'Tail','force_ratio':0,'transform_ratio':0,'lossy_scale':[1,1,1]},
                {'name':'A','force_ratio':.5,'transform_ratio':1/3,'lossy_scale':[2,2,2]},
                {'name':'B','force_ratio':1,'transform_ratio':2/3,'lossy_scale':[3,3,3]}]}}
    node,_=build(params)
    assert [value*node['params']['radius'] for _,value in node['extended_curves']['radius']]==pytest.approx([4/3,4/3,4,6])


def test_bivariant_profile_is_only_attached_to_current_actual_geometry():
    w,j,o,h,r=fixture({'pull':.2})
    gp=w.group_plans[0];gp.hub_root_male='male_hub'
    overrides,manifest=sway_auto.attach_source_profiles(w,j,o,'Female',h,r)
    assert 'male_hub' not in manifest['node_overrides']
    assert 'source_profile' not in overrides.get('male_hub',{})


def test_radius_includes_actual_avatar_to_pal_fit_scale():
    w,j,o,h,r=fixture({'pull':.3,'radius':.02})
    plain,_=sway_auto.attach_source_profiles(w,j,o,'Female',h,r,source_fit_scale=100)
    fitted,_=sway_auto.attach_source_profiles(w,j,o,'Female',h,r,source_fit_scale=155.8)
    assert fitted['hub']['source_profile']['params']['radius']==pytest.approx(
        plain['hub']['source_profile']['params']['radius']*1.558)


def test_single_gender_build_requires_only_its_final_manifest(tmp_path):
    w,j,o,h,r=fixture({'pull':.2})
    j.update(job_dir=str(tmp_path),genders=['Female'])
    overrides,manifest=sway_auto.attach_source_profiles(w,j,o,'Female',h,r)
    directory=tmp_path/'converted';directory.mkdir()
    (directory/'sway_node_overrides.json').write_text(json.dumps(overrides))
    (directory/'sway_adaptation_female.json').write_text(json.dumps(manifest))
    assert 'source_profile' in load_node_overrides(j)['hub']


def prepare_multicomponent_auto_metadata(tmp_path, roots=("tail_hub", "hair_hub")):
    """Run the real allocator/planner/profile path for two independent PBs."""
    import sway_allocator
    import sway_hub
    import sway_hub_wire
    rows = []
    for anchor, pull in (("Tail", .35), ("Hair", .55)):
        rows.append({"anchor": anchor, "chains": [[f"{anchor}.{i}" for i in range(1, 6)]],
                     "params": {"version": "Version_1_1", "integration_type": "Advanced",
                                "pull": pull, "spring": .4, "stiffness": .2,
                                "gravity": 0, "radius": .01, "limit_type": "None",
                                "curves": {"pull": {"keys": [{"time": 0, "value": .2},
                                                              {"time": 1, "value": 1}],
                                                     "samples": [{"time": 0, "value": .2},
                                                                 {"time": .5, "value": .6},
                                                                 {"time": 1, "value": 1}]}}}})
    definitions = [("skeleton_root", -1)]
    for index, root in enumerate(roots):
        definitions.append((root, 0))
        for bone_index in range(6):
            definitions.append((f"native_{index}_{bone_index}", len(definitions) - 1))
    bones = [{"name": name, "parent_idx": parent, "quat": [0, 0, 0, 1],
              "pos": [0, 0, 1], "scale": [1, 1, 1]} for name, parent in definitions]
    catalog = sway_hub.SkeletonCatalog.from_bones_list(bones)
    slots = sway_hub.HubSlots(female=tuple(roots), male=tuple(roots))
    allocation = sway_allocator.allocate({"physbones": rows})
    wiring = sway_hub.plan_hub_wiring(allocation, catalog, slots,
        sway_hub.reserved_descendants_of(roots, bones), default_safety_margin=1,
        auto_preserve_segments=True)
    assert len(wiring.group_plans) == 2
    heads = {}
    for index, group in enumerate(wiring.group_plans):
        for i, name in enumerate((group.hub_root_female,) + group.chain_plans[0].donor_chain_female):
            heads[name] = (index * 20, 0, float(i * i + i))
    job = {"job_dir": str(tmp_path), "sway_intensity": "normal", "sway_enable": True,
           "sway_adaptation": "physbone-v1"}
    source = tmp_path / "physbones.json"
    source.write_text(json.dumps({"physbones": rows}), encoding="utf-8")
    job["physbones_json"] = str(source)
    converted = tmp_path / "converted"
    converted.mkdir(exist_ok=True)
    manifests = {}
    for gender in ("Female", "Male"):
        overrides, manifest = sway_auto.attach_source_profiles(
            wiring, job, sway_hub.node_overrides_from_wiring_plan(wiring), gender, heads, rows)
        assert len(manifest["active_physbone_anchors"]) == len(manifest["node_overrides"]) == 2
        manifests[gender.lower()] = manifest
        (converted / f"sway_adaptation_{gender.lower()}.json").write_text(json.dumps(manifest), encoding="utf-8")
    (converted / "sway_node_overrides.json").write_text(json.dumps(overrides), encoding="utf-8")
    (tmp_path / "job.json").write_text(json.dumps(job), encoding="utf-8")
    return job, manifests


def test_wrong_gender_manifest_is_rejected_for_real_two_component_plan(tmp_path):
    job, manifests = prepare_multicomponent_auto_metadata(tmp_path)
    assert len(load_node_overrides(job)) == 2
    (tmp_path / "converted/sway_adaptation_male.json").write_text(
        json.dumps(manifests["female"]), encoding="utf-8")
    with pytest.raises(SwayNodeMetadataError, match="full conversion"):
        load_node_overrides(job)


@pytest.mark.parametrize("gender", ["female", "male"])
def test_one_missing_active_node_profile_is_rejected_with_other_profile_present(tmp_path, gender):
    job, manifests = prepare_multicomponent_auto_metadata(tmp_path)
    assert len(load_node_overrides(job)) == 2
    incomplete = manifests[gender]
    missing = incomplete["components"][0]["target_root"]
    incomplete["node_overrides"].pop(missing)
    assert incomplete["node_overrides"], "exercise partial loss, not an empty metadata file"
    (tmp_path / f"converted/sway_adaptation_{gender}.json").write_text(
        json.dumps(incomplete), encoding="utf-8")
    with pytest.raises(SwayNodeMetadataError, match="incomplete automatic node metadata"):
        load_node_overrides(job)


def test_shinano_ahoge_actual_arc_lengths_reach_exact_curve_endpoint():
    # Minimal donor-head coordinates reproducing sequential rotation loss. Sequential addition of their
    # lengths previously gave position / sum(lengths) == 1.0000000000000002
    # on Python 3.12, making the cooked-node validator reject the conversion.
    points = (
        (-1.1510796546936035, 5.919496536254883, 199.13711547851562),
        (-4.3804216384887695, 8.718430519104004, 198.9197998046875),
        (-7.729156494140625, 11.067866325378418, 195.72738647460938),
        (-10.180183410644531, 12.154864311218262, 191.08856201171875),
        (-10.677940368652344, 11.466195106506348, 187.4141845703125),
        (-8.950385093688965, 8.91520881652832, 185.23904418945312),
        (-7.222829818725586, 6.364222526550293, 183.06390380859375),
        (-5.495274543762207, 3.8132362365722656, 180.88876342773438),
    )
    w, job, overrides, _, raw = fixture({
        'pull': .18, 'spring': .75, 'stiffness': .2,
        'integration_type': 'Simplified', 'radius': .005,
    })
    donors = tuple(f'd{i}' for i in range(1, len(points)))
    cp = w.group_plans[0].chain_plans[0]
    cp.donor_chain_female = cp.donor_chain_male = donors
    cp.donor_chain_for = lambda gender: donors
    heads = dict(zip(('hub', *donors), points))
    changed, _ = sway_auto.attach_source_profiles(
        w, job, overrides, 'Female', heads, raw, source_fit_scale=150.6028055403097)
    node = sway_abp_build.build_spec_nodes(
        ['hub'], 'futsuu', node_overrides=changed)[0]
    for curve in node['extended_curves'].values():
        assert curve[-1][0] == 1.0
        assert all(0 <= point[0] <= 1 for point in curve)
