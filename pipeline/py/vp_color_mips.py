"""Optional opaque albedo mip filter; do not use for data maps or transparency."""

def make_opaque_srgb_mips(rgba,num_levels):
    """Area-filter decoded sRGB light values while keeping all GPU dimensions.

    Mip zero is unchanged. Float linear averages, not previously quantized output,
    feed the next level. This avoids gamma-space darkening and repeated 8-bit
    rounding without sharpening halos, new mip levels or a streaming bias.
    Callers must establish that the asset is opaque sRGB albedo.
    """
    import numpy as np
    if rgba.dtype!=np.uint8 or rgba.ndim!=3 or rgba.shape[2]!=4:
        raise ValueError('opaque albedo mips require uint8 RGBA')
    h,w=rgba.shape[:2]
    if not h or not w or (h&(h-1)) or (w&(w-1)):
        raise ValueError('opaque albedo mip dimensions must be powers of two')
    if not isinstance(num_levels,int) or num_levels<1 or num_levels>max(h,w).bit_length():
        raise ValueError('requested mip count exceeds the complete image chain')
    if not np.all(rgba[:,:,3]==255):
        raise ValueError('opaque albedo mip filter cannot process transparency')
    result=[rgba]
    if num_levels==1:return result
    x=np.arange(256,dtype=np.float32)/255.
    lut=np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)
    cur=lut[rgba[:,:,:3]]
    for _ in range(num_levels-1):
        h,w=cur.shape[:2]
        if h==1:cur=(cur[:,::2]+cur[:,1::2])*.5
        elif w==1:cur=(cur[::2]+cur[1::2])*.5
        else:cur=(cur[::2,::2]+cur[1::2,::2]+cur[::2,1::2]+cur[1::2,1::2])*.25
        srgb=np.where(cur<=.0031308,12.92*cur,1.055*np.power(cur,1/2.4)-.055)
        out=np.empty((*cur.shape[:2],4),dtype=np.uint8)
        out[:,:,:3]=np.clip(np.rint(srgb*255),0,255).astype(np.uint8);out[:,:,3]=255
        result.append(out)
    return result
