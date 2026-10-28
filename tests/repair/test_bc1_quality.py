"""BC1 quality gains must preserve storage size and the legacy error floor."""
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pipeline/py'))
import vp_tex
import vp_texinject
from test_vp_tex import _pure_python_encode_dxt1


def block_error(image, payload, fmt='PF_DXT1'):
    h, w = image.shape[:2]
    decoded = vp_tex.decode_dxt(payload, w, h, fmt)
    # Padding affects the fit, so compare the actual displayed pixels only.
    error = (image[:, :, :3].astype(np.int32) - decoded[:, :, :3]) ** 2
    return np.array([error[y:y+4, x:x+4].sum()
                     for y in range(0, h, 4) for x in range(0, w, 4)])


def test_cross_channel_gradient_is_preserved_instead_of_greyed_out():
    image = np.zeros((4, 4, 4), np.uint8)
    levels = np.array([30, 95, 160, 225], dtype=np.uint8)
    image[:, :, 0] = levels
    image[:, :, 1] = 255-levels
    image[:, :, 2] = 50
    image[:, :, 3] = 255
    legacy = _pure_python_encode_dxt1(image)
    improved = vp_tex.encode_dxt1(image)
    assert len(improved) == len(legacy) == 8
    assert block_error(image, improved).sum() < block_error(image, legacy).sum() * .1


@pytest.mark.parametrize('shape', [(16, 16), (4, 4), (8, 12)])
def test_every_complete_block_is_no_worse_than_independent_legacy_reference(shape):
    rng = np.random.default_rng(20261025)
    image = rng.integers(0, 256, size=(*shape, 4), dtype=np.uint8)
    legacy = _pure_python_encode_dxt1(image)
    improved = vp_tex.encode_dxt1(image)
    assert len(improved) == len(legacy)
    assert np.all(block_error(image, improved) <= block_error(image, legacy))
    assert improved == vp_tex.encode_dxt1(image)


@pytest.mark.parametrize('shape', [(1, 1), (7, 9), (2, 11)])
def test_partial_blocks_remain_valid_and_opaque(shape):
    rng = np.random.default_rng(11)
    image = rng.integers(0, 256, size=(*shape, 4), dtype=np.uint8)
    payload = vp_tex.encode_dxt1(image)
    assert len(payload) == ((shape[0]+3)//4)*((shape[1]+3)//4)*8
    decoded = vp_tex.decode_dxt(payload, shape[1], shape[0], 'PF_DXT1')
    assert decoded.shape == image.shape
    assert np.all(decoded[:, :, 3] == 255)


@pytest.mark.parametrize('rgb', [(0, 0, 0), (255, 255, 255), (91, 123, 205)])
def test_solid_blocks_preserve_or_improve_quantization_without_dither(rgb):
    image = np.full((8, 8, 4), 255, dtype=np.uint8)
    image[:, :, :3] = rgb
    payload = vp_tex.encode_dxt1(image)
    previous = _pure_python_encode_dxt1(image)
    assert np.all(block_error(image,payload)<=block_error(image,previous))
    decoded=vp_tex.decode_dxt(payload,8,8,'PF_DXT1')
    assert np.all(decoded==decoded[:1,:1])
    if rgb in ((0,0,0),(255,255,255)):
        assert payload==previous
    else:
        assert block_error(image,payload).sum()<block_error(image,previous).sum()*.25


@pytest.mark.parametrize('kind', ['random','fabric_edge','skin_gradient','saturated_edge'])
def test_quantized_refinement_never_worsens_the_existing_pca_fitter(kind):
    rng=np.random.default_rng(20261026)
    image=np.full((32,32,4),255,dtype=np.uint8)
    if kind=='random':
        image[:,:,:3]=rng.integers(0,256,size=(32,32,3),dtype=np.uint8)
    else:
        x,y=np.meshgrid(np.arange(32),np.arange(32))
        coverage=np.clip((x-y+2)/4,0,1)[:,:,None]
        if kind=='fabric_edge':
            image[:,:,:3]=np.rint(np.array((91,123,205))+coverage*np.array((15,12,19))).astype(np.uint8)
        elif kind=='skin_gradient':
            image[:,:,:3]=np.rint(np.array((204,160,142))+(x[:,:,None]/31)*np.array((19,13,17))).astype(np.uint8)
        else:
            image[:,:,:3]=np.rint(np.array((240,25,35))+coverage*np.array((-210,200,150))).astype(np.uint8)
    with patch.object(vp_tex,'_color_block',vp_tex._color_block_fitted):
        previous=vp_tex.encode_dxt1(image)
    payload=vp_tex.encode_dxt1(image)
    before,after=block_error(image,previous),block_error(image,payload)
    assert len(payload)==len(previous)==512
    assert np.all(after<=before)
    assert after.sum()<before.sum()
    assert np.all(vp_tex.decode_dxt(payload,32,32,'PF_DXT1')[:,:,3]==255)
    assert payload==vp_tex.encode_dxt1(image)


def test_bc3_keeps_alpha_independent_of_color_refinement():
    image = np.zeros((4, 4, 4), np.uint8)
    image[:, :, 0] = [30, 95, 160, 225]
    image[:, :, 1] = 255-image[:, :, 0]
    image[:, :, 3] = np.arange(16).reshape(4, 4)*17
    payload = vp_tex.encode_dxt5(image)
    assert len(payload) == 16
    decoded = vp_tex.decode_dxt(payload, 4, 4, 'PF_DXT5')
    assert np.max(np.abs(decoded[:, :, 3].astype(int)-image[:, :, 3])) <= 18
    assert block_error(image, payload, 'PF_DXT5').sum() < 1000


def test_bc3_alpha_bytes_remain_identical_to_the_existing_fitter():
    rng=np.random.default_rng(20261026)
    image=rng.integers(0,256,size=(16,16,4),dtype=np.uint8)
    image[:,:,:3]=np.clip(image[:,:,:3]//16+np.array((91,123,205)),0,255)
    with patch.object(vp_tex,'_color_block',vp_tex._color_block_fitted):
        before=vp_tex.encode_dxt5(image)
    after=vp_tex.encode_dxt5(image)
    assert len(before)==len(after)==256
    assert np.array_equal(np.frombuffer(before,np.uint8).reshape(-1,16)[:,:8],
                          np.frombuffer(after,np.uint8).reshape(-1,16)[:,:8])
    assert np.all(block_error(image,after,'PF_DXT5')<=block_error(image,before,'PF_DXT5'))


def test_chunk_boundary_does_not_change_independent_blocks():
    rng = np.random.default_rng(8193)
    blocks = rng.integers(0, 256, size=(8193, 16, 3), dtype=np.uint8)
    combined = vp_tex._color_block(blocks)
    for start, stop in ((0, 1), (8191, 8193)):
        separate = vp_tex._color_block(blocks[start:stop])
        for actual, expected in zip(separate, combined):
            assert np.array_equal(actual, expected[start:stop])


@pytest.mark.parametrize('mixed', [False, True])
def test_injection_encodes_each_mip_once_and_measures_written_top_bytes(tmp_path, monkeypatch, mixed):
    image = np.zeros((4, 4, 4), np.uint8)
    image[:, :, 0] = [30, 95, 160, 225]
    image[:, :, 1] = 255-image[:, :, 0]
    image[:, :, 3] = 255
    source = tmp_path/'source.png'
    vp_tex.encode_png(str(source), image)
    template = tmp_path/'template.uexp';template.write_bytes(b'HDR!'+bytes(24)+b'END!')
    bulk = tmp_path/'template.ubulk';bulk.write_bytes(bytes(8))
    layout = {'pixel_format':'PF_DXT1','size_x':4,'size_y':4,'mips':[
        {'w':4,'h':4,'size':8,'offset':4,'inline':not mixed,'abs_off':0},
        {'w':2,'h':2,'size':8,'offset':12,'inline':True,'abs_off':0},
        {'w':1,'h':1,'size':8,'offset':20,'inline':True,'abs_off':0}]}
    monkeypatch.setattr(vp_texinject.vp_core, 'parse_texture2d', lambda _:layout)
    monkeypatch.setattr(vp_texinject.vp_core, 'parse_texture2d_mixed', lambda _:layout)
    encoded=[]
    original=vp_tex.encode
    def counting_encode(pixels, fmt):
        blob=original(pixels,fmt)
        encoded.append((pixels.shape,blob))
        return blob
    monkeypatch.setattr(vp_tex,'encode',counting_encode)
    output=tmp_path/'output.uexp';output_bulk=tmp_path/'output.ubulk'
    if mixed:
        result=vp_texinject.inject_texture_file_vanilla_slot(str(template),str(bulk),str(source),str(output),str(output_bulk))
        top=output_bulk.read_bytes()
    else:
        result=vp_texinject.inject_texture_file(str(template),str(source),str(output))
        top=output.read_bytes()[4:12]
    assert [shape[:2] for shape,_ in encoded]==[(4,4),(2,2),(1,1)]
    assert top==encoded[0][1]
    assert result['psnr']==pytest.approx(vp_tex.psnr(image,vp_tex.decode_dxt(top,4,4,'PF_DXT1')))
    assert output.read_bytes()[:4]==b'HDR!' and output.read_bytes()[-4:]==b'END!'
