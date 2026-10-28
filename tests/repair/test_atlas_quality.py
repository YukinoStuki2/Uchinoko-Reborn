"""Source detail must survive atlas packing without increasing the 4K budget."""
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pipeline/py'))
import vp_atlas
import vp_tex


def test_detailed_sources_gain_space_when_other_materials_are_solid_or_small():
    sizes = [(256,256), (2048,2048), (1024,1024), (16,16), (16,16),
             (2048,2048), (2048,2048), (128,128), (16,16), (2048,2048),
             (512,2048), (2048,2048), (16,16), (2048,2048), (2048,2048),
             (2048,2048), (1024,1024)]
    layout = vp_atlas.plan_detail_atlas(sizes)
    assert layout['canvas'] == [4096,4096]
    assert layout['regions'][9]['size'][0] >= 1300
    assert layout['regions'][9]['size'][1] >= 1300
    assert layout['regions'][3]['size'] == [16,16]
    assert layout['regions'][0]['size'] == [256,256]
    assert layout == vp_atlas.plan_detail_atlas(sizes)


def test_packed_uvs_read_their_own_pixels_and_padding_has_the_same_edge_color():
    images = [np.full((32,64,4), [250,0,0,255], dtype=np.uint8),
              np.full((64,32,4), [0,250,0,255], dtype=np.uint8),
              np.full((4,4,4), [0,0,250,255], dtype=np.uint8)]
    canvas, transforms, layout = vp_atlas.build_detail_atlas_image(images, canvas_size=128, padding=4)
    assert canvas.shape == (128,128,4)
    for i, (xf, region) in enumerate(zip(transforms, layout['regions'])):
        su,sv,ou,ov = xf
        assert 0 <= ou < ou+su <= 1 and 0 <= ov < ov+sv <= 1
        for u,v in ((0,0),(1,1),(.5,.5)):
            x,y=vp_atlas.apply_transform(u,v,xf)
            assert np.array_equal(canvas[min(int(y*128),127), min(int(x*128),127)], images[i][0,0])
        x,y=region['origin'];w,h=region['size']
        assert np.array_equal(canvas[y-2,x-2],images[i][0,0])
        assert np.array_equal(canvas[y+h+1,x+w+1],images[i][0,0])


def test_downsample_averages_fine_detail_instead_of_aliasing():
    image=np.zeros((16,16,4),dtype=np.uint8);image[:,:,3]=255
    image[:,1::2,:3]=255
    small=vp_atlas.resize_detail(image,4,4)
    assert small[:,:,:3].min() > 100
    assert small[:,:,:3].max() < 200
    assert np.ptp(small[:,:,:3]) == 0
    assert np.array_equal(vp_atlas.resize_detail(image,16,16),image)


def test_legacy_grid_api_and_single_texture_plan_stay_compatible():
    image=np.full((8,8,4),255,dtype=np.uint8)
    canvas,rows,cols,size=vp_atlas.build_atlas_image([image,image,image],cell_size=8)
    assert (canvas.shape,rows,cols,size)==((16,16,4),2,2,8)
    assert vp_atlas.plan_label(['one.png'])==({},1,1)


def test_many_small_images_reduce_only_when_native_resolution_cannot_fit():
    layout=vp_atlas.plan_detail_atlas([(32,32)]*100,canvas_size=128,padding=4)
    assert len(layout['regions'])==100
    assert all(max(r['size'])<32 for r in layout['regions'])
    for i,a in enumerate(layout['regions']):
        ax,ay=a['origin'];aw,ah=a['size']
        assert 4<=ax and 4<=ay and ax+aw+4<=128 and ay+ah+4<=128
        for b in layout['regions'][i+1:]:
            bx,by=b['origin'];bw,bh=b['size']
            assert ax+aw+8<=bx or bx+bw+8<=ax or ay+ah+8<=by or by+bh+8<=ay


@pytest.mark.parametrize('sizes', [[],[(0,2)],[(2,-3)],[(1.5,8)]])
def test_invalid_input_dimensions_fail_clearly(sizes):
    with pytest.raises(ValueError,match='dimensions'):
        vp_atlas.plan_detail_atlas(sizes)


def test_real_conversion_seam_writes_detail_layout_and_correct_slot_uvs(tmp_path):
    import json
    import convert_noue
    (tmp_path/'textures').mkdir()
    image=np.full((512,512,4),[200,40,20,255],dtype=np.uint8)
    vp_tex.encode_png(str(tmp_path/'textures/detail.png'),image)
    meta={'slots':{'m00':{'texture':'detail.png','base_color':[1,1,1,1]},
                   'm01':{'texture':None,'base_color':[0,0,1,1]}}}
    textures,slot_xf,_=convert_noue.resolve_textures({'job_dir':str(tmp_path)},meta)
    layout=json.loads((tmp_path/'build/atlas/atlas_layout_body.json').read_text())
    assert layout['canvas']==[4096,4096]
    assert layout['regions'][0]['size']==[512,512]
    assert layout['regions'][1]['size']==[16,16]
    assert slot_xf['m00']==layout['regions'][0]['transform']
    assert slot_xf['m01']==layout['regions'][1]['transform']
    w,h,canvas=vp_tex.decode_png(textures['body'])
    for slot,color in [('m00',[200,40,20,255]),('m01',[0,0,255,255])]:
        su,sv,ou,ov=slot_xf[slot]
        assert list(canvas[int((ov+sv/2)*h),int((ou+su/2)*w)])==color
