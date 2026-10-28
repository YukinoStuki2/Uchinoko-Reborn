"""Detail filtering preserves resolvable contrast without ringing or aliasing."""
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pipeline/py'))
from vp_atlas_detail import resize_detail, _area_axis


def from_linear(values):
    encoded=np.where(values<=.0031308, values*12.92, 1.055*values**(1/2.4)-.055)
    rgb=np.rint(encoded*255).astype(np.uint8)
    result=np.full((*values.shape,4),255,dtype=np.uint8)
    result[:,:,:3]=rgb[:,:,None]
    return result


def to_linear(image):
    rgb=image[:,:,:3].astype(np.float32)/255
    return np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)


@pytest.mark.parametrize('frequency,min_amplitude,max_amplitude', [
    (.15,.23,.255), (.48,0,.03)])
def test_keeps_resolvable_lines_and_rejects_above_nyquist(frequency,min_amplitude,max_amplitude):
    values=np.broadcast_to(.5+.25*np.sin(2*np.pi*frequency*np.arange(1024)),(16,1024))
    output=resize_detail(from_linear(values),672,16)
    amplitude=float(np.std(to_linear(output)[0,8:-8,0])*2**.5)
    assert min_amplitude <= amplitude <= max_amplitude


def test_diagonal_step_has_no_bright_or_dark_halo():
    y,x=np.mgrid[:256,:256]
    image=from_linear(np.where(x>y*.7+20,.8,.2))
    output=resize_detail(image,168,168)
    assert output[:,:,:3].min() >= image[:,:,:3].min()
    assert output[:,:,:3].max() <= image[:,:,:3].max()


def test_alpha_coverage_keeps_area_integration():
    y,x=np.mgrid[:96,:96]
    image=from_linear(np.where(x>y*.8,.8,.2))
    image[:,:,3]=np.where(x>y,255,0)
    output=resize_detail(image,64,64)
    expected=_area_axis(_area_axis(image[:,:,3:4].astype(np.float32)/255,64,1),64,0)
    assert np.array_equal(output[:,:,3],np.rint(expected[:,:,0]*255).astype(np.uint8))


def test_deep_minification_is_still_an_exact_area_average():
    image=np.full((64,64,4),255,dtype=np.uint8)
    image[:,::2,:3]=0
    output=resize_detail(image,8,8)
    assert np.ptp(output[:,:,:3]) == 0


def test_native_size_does_not_filter_or_change_bytes():
    image=np.random.default_rng(7).integers(0,256,(17,29,4),dtype=np.uint8)
    assert np.array_equal(resize_detail(image,29,17),image)


def test_real_path_keeps_fill_alpha_until_filtering_but_outputs_opaque(tmp_path,monkeypatch):
    import vp_atlas
    import vp_tex
    values=np.broadcast_to(.5+.25*np.sin(2*np.pi*.15*np.arange(1024)),(16,1024))
    image=from_linear(values)
    image[0,0,3]=0
    path=tmp_path/'source.png'
    vp_tex.encode_png(str(path),image)
    layout={'canvas':[1024,1024],'padding':0,'regions':[
        {'origin':[0,0],'size':[672,16],'transform':[672/1024,16/1024,0,0]}]}
    monkeypatch.setattr(vp_atlas,'plan_detail_atlas',lambda *_:layout)
    output,_,_=vp_atlas.build_detail_atlas_from_paths([str(path)])
    expected=resize_detail(vp_tex.extend_opaque_color(image),672,16)
    assert np.array_equal(output[:16,:672,:3],expected[:,:,:3])
    assert output[:,:,3].min()==255
    # A prematurely opaque source would choose a different filter.
    opaque=vp_tex.extend_opaque_color(image).copy();opaque[:,:,3]=255
    assert not np.array_equal(output[:16,:672,:3],resize_detail(opaque,672,16)[:,:,:3])
