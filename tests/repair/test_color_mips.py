import numpy as np
import pytest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'pipeline/py'))
from vp_color_mips import make_opaque_srgb_mips

def test_average_light_not_encoded_bytes():
    x=np.array([[[0,0,0,255],[255,255,255,255]],[[255,255,255,255],[0,0,0,255]]],np.uint8)
    out=make_opaque_srgb_mips(x,2)
    assert out[0] is x
    assert out[1].tolist()==[[[188,188,188,255]]]

def test_independent_direct_footprint_reference():
    x=np.random.default_rng(1729).integers(0,256,(64,64,4),dtype=np.uint8);x[:,:,3]=255
    out=make_opaque_srgb_mips(x,7)
    # Independent scalar sRGB functions plus a direct mean from original mip0.
    def tolin(n):
        c=n/255.
        return c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4
    def tobyte(c):return round(255*(12.92*c if c<=.0031308 else 1.055*c**(1/2.4)-.055))
    for level in (1,3,6):
        k=1<<level
        for y,z in ((0,0),(out[level].shape[0]-1,out[level].shape[1]-1)):
            expected=[tobyte(sum(tolin(int(v)) for v in x[y*k:(y+1)*k,z*k:(z+1)*k,c].flat)/(k*k)) for c in range(3)]
            assert out[level][y,z,:3].tolist()==expected

def test_constant_preserved_across_full_chain():
    x=np.full((16,8,4),(25,123,240,255),np.uint8)
    for out in make_opaque_srgb_mips(x,5):assert np.all(out==[25,123,240,255])

def test_rectangular_last_axis_and_mip_sizes():
    x=np.full((1,16,4),(88,99,111,255),np.uint8)
    assert [a.shape[:2] for a in make_opaque_srgb_mips(x,5)]==[(1,16),(1,8),(1,4),(1,2),(1,1)]

@pytest.mark.parametrize('shape,levels,alpha',[( (3,4,4),2,255),((4,4,4),4,255),((4,4,4),0,255),((4,4,4),3,254)])
def test_invalid_or_transparent_inputs_rejected(shape,levels,alpha):
    x=np.full(shape,alpha,np.uint8)
    with pytest.raises(ValueError):make_opaque_srgb_mips(x,levels)

def test_4k_bc1_budget_is_unchanged():
    sizes=[max(1,4096>>i) for i in range(13)]
    assert sum(((n+3)//4)**2*8 for n in sizes)==11184824

@pytest.mark.parametrize('mixed',[False,True])
def test_injection_filters_opaque_albedo_before_encoding(tmp_path,monkeypatch,mixed):
    import vp_tex,vp_texinject
    x=np.full((8,8,4),(190,125,70,255),np.uint8);x[::2,::2]=[0,0,0,0]
    png=tmp_path/'source.png';vp_tex.encode_png(str(png),x)
    source=tmp_path/'template.uexp';source.write_bytes(b'HEAD'+bytes(24)+b'TAIL')
    layout={'pixel_format':'PF_DXT1','size_x':4,'size_y':4,'mips':[
        {'w':4,'h':4,'size':8,'offset':4,'inline':True,'abs_off':0},
        {'w':2,'h':2,'size':8,'offset':12,'inline':True,'abs_off':0},
        {'w':1,'h':1,'size':8,'offset':20,'inline':True,'abs_off':0}]}
    monkeypatch.setattr(vp_texinject.vp_core,'parse_texture2d',lambda _:layout)
    monkeypatch.setattr(vp_texinject.vp_core,'parse_texture2d_mixed',lambda _:layout)
    resize_calls=[];pixels=[];real_resize=vp_texinject.resize_detail;real_encode=vp_tex.encode
    def resize(a,w,h):
        assert a.shape==(8,8,4) and np.array_equal(a[:,:,3],x[:,:,3])
        assert np.all(a[:,:,:3]==[190,125,70]) # Transparent black was dilated first.
        resize_calls.append((w,h));return real_resize(a,w,h)
    def encode(a,pf):pixels.append(a.copy());return real_encode(a,pf)
    monkeypatch.setattr(vp_texinject,'resize_detail',resize)
    monkeypatch.setattr(vp_tex,'encode',encode)
    output=tmp_path/'result.uexp'
    if mixed:vp_texinject.inject_texture_file_vanilla_slot(str(source),None,str(png),str(output),None)
    else:vp_texinject.inject_texture_file(str(source),str(png),str(output),alpha_coverage=True)
    assert resize_calls==[(4,4)]
    assert [a.shape[:2] for a in pixels]==[(4,4),(2,2),(1,1)]
    assert all(np.all(a[:,:,3]==255) for a in pixels)
    assert len(output.read_bytes())==len(source.read_bytes())
    assert output.read_bytes()[:4]==b'HEAD' and output.read_bytes()[-4:]==b'TAIL'
