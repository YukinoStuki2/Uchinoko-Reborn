"""Blender integration regression: an FBX transform action must not survive import.

Run with blender -b --factory-startup --python-exit-code 1 --python THIS -- OUTPUT
Add --baseline 7bd7130 to exercise the original importer from its Git baseline.
No purchased avatar or game assets are required. The generated FBX is a two-bone
armature and a box, with an animated 0.01 object scale like the reported failure.
"""
import ast
import json
from pathlib import Path
import sys
import subprocess

import bpy

repo = Path(__file__).resolve().parents[2]
out = Path(sys.argv[sys.argv.index('--')+1]).resolve()
out.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
data=bpy.data.armatures.new('FixtureSkeleton')
arm=bpy.data.objects.new('FixtureAvatar',data)
bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active=arm
arm.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
hips=data.edit_bones.new('Hips'); hips.head=(0,0,80); hips.tail=(0,0,100)
head=data.edit_bones.new('Head'); head.head=(0,0,130); head.tail=(0,0,150); head.parent=hips
bpy.ops.object.mode_set(mode='OBJECT')
arm.scale=(.01,.01,.01)
arm.keyframe_insert(data_path='scale',frame=1)
# Identical keys are optimized away by the FBX exporter. A second, different
# value keeps the object-scale channel in the actual FBX so normalization must
# survive action evaluation when the saved blend is reopened.
arm.scale=(.02,.02,.02)
arm.keyframe_insert(data_path='scale',frame=10)
arm.scale=(.01,.01,.01)
bpy.ops.mesh.primitive_cube_add(size=1,location=(0,0,1))
mesh=bpy.context.object
mesh.name='FixtureBody';mesh.scale=(.4,.3,1.6)
bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
mesh.vertex_groups.new(name='Hips').add(list(range(len(mesh.data.vertices))),1,'REPLACE')
modifier=mesh.modifiers.new('Skin','ARMATURE');modifier.object=arm
mesh.parent=arm;mesh.matrix_parent_inverse=arm.matrix_world.inverted()
bpy.context.scene.frame_set(1)
bpy.ops.object.select_all(action='SELECT')
fbx=out/'animated-scale.fbx'
bpy.ops.export_scene.fbx(filepath=str(fbx),use_selection=True,object_types={'ARMATURE','MESH'},
    add_leaf_bones=False,bake_anim=True,bake_anim_use_all_actions=False,bake_anim_use_nla_strips=False)

source=repo/'pipeline/blender/step01_import_vrm.py'
if '--baseline' in sys.argv:
    revision=sys.argv[sys.argv.index('--baseline')+1]
    source_text=subprocess.check_output(
        ['git','show',f'{revision}:pipeline/blender/step01_import_vrm.py'],
        cwd=repo).decode('utf-8-sig')
else:
    source_text=source.read_text(encoding='utf-8')
tree=ast.parse(source_text,filename=str(source))
assert isinstance(tree.body[-1],ast.Expr) and tree.body[-1].value.func.id=='main'
tree.body.pop()
ns={'__file__':str(source),'__name__':'repair_fbx_regression'}
exec(compile(tree,str(source),'exec'),ns)
bpy.ops.wm.read_factory_settings(use_empty=True)
arm,_=ns['import_fbx_avatar']({'vrm_path':str(fbx)},[])
ns['cleanup_objects'](arm,[])
# Editing bones is part of step01's leaf-marker normalization. It reevaluates
# retained FBX actions and used to restore object transforms after the first bake.
bpy.context.view_layer.objects.active=arm
bpy.ops.object.mode_set(mode='EDIT');bpy.ops.object.mode_set(mode='OBJECT')
ns['apply_transforms'](arm)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'normalized.blend'))
bpy.ops.wm.open_mainfile(filepath=str(out/'normalized.blend'),load_ui=False,use_scripts=False)
arm=next(o for o in bpy.data.objects if o.type=='ARMATURE')
observations=[]
for frame in (1,5,10):
    bpy.context.scene.frame_set(frame)
    length=(arm.matrix_world @ arm.data.bones['Head'].head_local-arm.matrix_world @ arm.data.bones['Hips'].head_local).length
    observations.append({'frame':frame,'scale':list(arm.scale),'hips_head':length,
                         'has_animation':bool(arm.animation_data)})
print('REPAIR_FBX_RESULT '+json.dumps(observations))
(out/'observations.json').write_text(json.dumps(observations,indent=2),encoding='utf-8')
assert all(abs(r['hips_head']-.5)<1e-4 for r in observations),'Animated scale corrupted skeleton dimensions'
assert all(max(abs(s-1) for s in r['scale'])<1e-5 for r in observations),'Object scale is not normalized'
assert all(not r['has_animation'] for r in observations), 'Imported animation can overwrite normalized transforms'
print('REPAIR_FBX_PASS')
