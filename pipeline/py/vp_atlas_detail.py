"""Deterministic rectangular atlas packing within the existing texture budget.

Sources share a resolution scale; inputs at most 256px keep their native
resolution. No avatar, material-name, or body-part heuristics are used.
Rectangles are never rotated, so existing affine UV transforms remain valid.
"""
from __future__ import annotations

def _pack(sizes, canvas_size, padding):
    free = [(0, 0, canvas_size, canvas_size)]
    placed = {}
    ordered = sorted(enumerate(sizes), key=lambda row: (-max(row[1]), -min(row[1]), -row[1][0]*row[1][1], row[0]))
    for index, (width, height) in ordered:
        width += 2*padding
        height += 2*padding
        candidates = [(min(w-width,h-height), max(w-width,h-height), y, x, j)
                      for j,(x,y,w,h) in enumerate(free) if w>=width and h>=height]
        if not candidates:
            return None
        _,_,y,x,_ = min(candidates)
        placed[index] = (x+padding,y+padding)
        updated = []
        for fx,fy,fw,fh in free:
            if x>=fx+fw or x+width<=fx or y>=fy+fh or y+height<=fy:
                updated.append((fx,fy,fw,fh))
                continue
            if x>fx: updated.append((fx,fy,x-fx,fh))
            if x+width<fx+fw: updated.append((x+width,fy,fx+fw-x-width,fh))
            if y>fy: updated.append((fx,fy,fw,y-fy))
            if y+height<fy+fh: updated.append((fx,y+height,fw,fy+fh-y-height))
        # MaxRects free regions overlap. Remove contained regions without
        # deleting their equal duplicate twice.
        updated = sorted(set(updated))
        free = [a for i,a in enumerate(updated) if not any(
            i!=j and a[0]>=b[0] and a[1]>=b[1] and a[0]+a[2]<=b[0]+b[2] and a[1]+a[3]<=b[1]+b[3]
            for j,b in enumerate(updated))]
    return placed


def plan_detail_atlas(source_sizes, canvas_size=4096, padding=8):
    """Return pixel rectangles and affine transforms, with non-overlap gutters."""
    if type(canvas_size) is not int or canvas_size<32 or canvas_size%4:
        raise ValueError('atlas canvas must be a positive multiple of four, at least 32')
    if type(padding) is not int or padding<0 or padding%4:
        raise ValueError('atlas padding must be a nonnegative multiple of four')
    sizes = [tuple(size) for size in source_sizes]
    if not sizes or any(len(size)!=2 or any(type(v) is not int or v<=0 for v in size) for size in sizes):
        raise ValueError('atlas source dimensions must be positive integer pairs')
    largest=max(max(size) for size in sizes)
    def dimensions(edge, preserve_small):
        result=[]
        for w,h in sizes:
            scale=1.0 if preserve_small and max(w,h)<=256 else min(1.0,edge/largest)
            # Preserve aspect ratio to at most one BC block; align the content
            # and its extruded border with BC1 blocks.
            result.append((max(4,int(w*scale)//4*4),max(4,int(h*scale)//4*4)))
        return result
    best=None
    for preserve_small in (True,False):
        low,high=1,max(1,largest//4)
        while low<=high:
            mid=(low+high)//2
            target=dimensions(mid*4,preserve_small)
            placed=_pack(target,canvas_size,padding)
            if placed is not None:
                best=(target,placed);low=mid+1
            else:
                high=mid-1
        if best is not None:
            break
    if best is None:
        raise ValueError(f'{len(sizes)} texture regions cannot fit with {padding}px gutters in {canvas_size}px')
    target,placed=best
    regions=[]
    for i,((sw,sh),(w,h)) in enumerate(zip(sizes,target)):
        x,y=placed[i]
        regions.append({'source_size':[sw,sh],'origin':[x,y],'size':[w,h],
                        'transform':[w/canvas_size,h/canvas_size,x/canvas_size,y/canvas_size]})
    return {'format':'uchinoko-detail-atlas-1','canvas':[canvas_size,canvas_size],
            'padding':padding,'regions':regions,
            'content_area':sum(w*h for w,h in target),
            'allocated_area':sum((w+padding*2)*(h+padding*2) for w,h in target)}


def _area_axis(data, count, axis):
    """Integrate source texel boxes; no aliasing from choosing one input pixel."""
    import numpy as np
    source=np.moveaxis(data,axis,0)
    old=source.shape[0]
    if old==count:
        return data
    resized=np.empty((count,*source.shape[1:]),dtype=np.float32)
    # Bound cumulative/integral temporaries to a few MiB instead of keeping a
    # second full float64 4K image. This also avoids transposed reshape copies.
    chunk=max(1,262144//max(old,count)//source.shape[2])
    for start in range(0,source.shape[1],chunk):
        block=source[:,start:start+chunk,:]
        if count>old:
            points=(np.arange(count,dtype=np.float64)+.5)*old/count-.5
            lower=np.floor(points).astype(np.int64)
            fraction=(points-lower)[:,None,None]
            values=block[lower.clip(0,old-1)]*(1-fraction)+block[(lower+1).clip(0,old-1)]*fraction
        else:
            boundaries=np.arange(count+1,dtype=np.float64)*old/count
            indices=np.floor(boundaries).astype(np.int64).clip(0,old)
            cumulative=np.concatenate((np.zeros_like(block[:1]),np.cumsum(block,axis=0,dtype=np.float64)),axis=0)
            fraction=(boundaries-indices)[:,None,None]
            integral=cumulative[indices]+block[np.minimum(indices,old-1)]*fraction
            values=np.diff(integral,axis=0)/(old/count)
        resized[:,start:start+chunk,:]=values
    return np.moveaxis(resized,0,axis)


def _limited_lanczos_axis(data, count, axis):
    """Two-lobe reconstruction for modest minification, bounded by local colors.

    Compared with a texel-box average this retains resolvable fine lines while
    attenuating frequencies above the new Nyquist limit. Clamp negative-lobe
    ringing to the central positive lobe's range. Strong minification retains
    exact area integration; upsampling retains the established bilinear path.
    """
    import numpy as np
    source=np.moveaxis(data,axis,0)
    old=source.shape[0]
    if not .5 <= count/old < 1:
        return _area_axis(data,count,axis)
    scale=count/old
    points=(np.arange(count)+.5)/scale-.5
    radius=int(np.ceil(2/scale))
    offsets=np.arange(-radius,radius+1)
    indices=np.floor(points).astype(np.int64)[:,None]+offsets[None,:]
    distance=(points[:,None]-indices)*scale
    weights=np.where(np.abs(distance)<2,np.sinc(distance)*np.sinc(distance/2),0)
    weights/=weights.sum(axis=1)[:,None]
    indices=indices.clip(0,old-1)
    resized=np.empty((count,*source.shape[1:]),dtype=np.float32)
    chunk=max(1,262144//max(old,count)//source.shape[2])
    for start in range(0,source.shape[1],chunk):
        block=source[:,start:start+chunk]
        value=np.zeros((count,*block.shape[1:]),dtype=np.float32)
        low=np.full_like(value,np.inf);high=np.full_like(value,-np.inf)
        for tap in range(len(offsets)):
            samples=block[indices[:,tap]]
            weight=weights[:,tap,None,None]
            value+=samples*weight
            central=weight>0
            low=np.minimum(low,np.where(central,samples,np.inf))
            high=np.maximum(high,np.where(central,samples,-np.inf))
        resized[:,start:start+chunk]=np.clip(value,low,high)
    return np.moveaxis(resized,0,axis)


def resize_detail(rgba, width, height):
    """Linear-light detail filtering with conservative alpha and fill handling.

    Alpha always uses area integration. Textures with near-transparent pixels
    retain area RGB filtering too: their extended colors are inferred padding,
    whose boundaries must not acquire artificial high-frequency contrast.
    """
    import numpy as np
    if rgba.ndim!=3 or rgba.shape[2]!=4 or rgba.dtype!=np.uint8 or width<=0 or height<=0:
        raise ValueError('expected RGBA8 image and positive destination dimensions')
    if rgba.shape[:2]==(height,width):
        return rgba
    data=rgba.astype(np.float32)/255
    for start in range(0,data.shape[0],64):
        rgb=data[start:start+64,:,:3]
        data[start:start+64,:,:3]=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    if np.any(rgba[:,:,3]<16):
        data=_area_axis(_area_axis(data,width,1),height,0)
    else:
        rgb=_limited_lanczos_axis(_limited_lanczos_axis(data[:,:,:3],width,1),height,0)
        alpha=_area_axis(_area_axis(data[:,:,3:4],width,1),height,0)
        data=np.concatenate((rgb,alpha),axis=2)
    result=np.empty_like(data,dtype=np.uint8)
    for start in range(0,data.shape[0],64):
        block=data[start:start+64]
        rgb=block[:,:,:3]
        block[:,:,:3]=np.where(rgb<=.0031308,rgb*12.92,1.055*np.maximum(rgb,0)**(1/2.4)-.055)
        result[start:start+64]=np.rint(block*255).clip(0,255).astype(np.uint8)
    return result


def build_detail_atlas_image(images, canvas_size=4096, padding=8):
    """Generate one final-size atlas and the UV transform for each source."""
    import numpy as np
    layout=plan_detail_atlas([(int(img.shape[1]),int(img.shape[0])) for img in images],canvas_size,padding)
    return compose_detail_atlas(images,layout)


def compose_detail_atlas(images, layout):
    """Consume images one at a time; path callers need not retain all sources."""
    import numpy as np
    canvas_size=layout['canvas'][0];padding=layout['padding']
    canvas=np.zeros((canvas_size,canvas_size,4),dtype=np.uint8)
    canvas[:,:,3]=255
    for image,region in zip(images,layout['regions']):
        x,y=region['origin'];w,h=region['size']
        resized=resize_detail(image,w,h)
        # Pad each source independently; filtering near its border must not
        # sample a neighboring material's color.
        padded=np.pad(resized,((padding,padding),(padding,padding),(0,0)),mode='edge')
        canvas[y-padding:y+h+padding,x-padding:x+w+padding]=padded
    return canvas,[row['transform'] for row in layout['regions']],layout
