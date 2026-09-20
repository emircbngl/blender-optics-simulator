"""Ideal wavelength-resolving detector; Gaussian instrument FWHM in nm.

Intensity images are false-color spatial measurements, not spectrometers.
This readout uses simulated arrival wavelengths and relative optical power.
"""
import math
import csv
import numpy as np
from . import alignment


def measure(det, segments):
    groups = {}
    for s in segments:
        if s.get('to') == det.name:
            groups.setdefault(float(s['wavelength']), []).append(s)
    lines = []
    for wl, arrivals in sorted(groups.items()):
        p, _, _ = alignment.measure(segments, det.name, det.optics.analyzer, incoming=arrivals)
        lines.append({'wavelength_nm': wl, 'power': max(0.,p)})
    resolution = float(det.optics.spectrum_resolution_nm)
    sigma = resolution/math.sqrt(8*math.log(2))
    out = {'detector': det.name, 'lines': lines, 'resolution_fwhm_nm': resolution,
           'total_power': sum(line['power'] for line in lines), 'power_unit': 'relative',
           'wavelength_nm': [], 'bin_power': [], 'power_density_per_nm': [], 'bin_edges_nm': [],
           'sampling_limited': False}
    if not lines:
        return out
    lo = max(0., lines[0]['wavelength_nm']-6*sigma)
    hi = lines[-1]['wavelength_nm']+6*sigma
    requested = max(64, math.ceil((hi-lo)/(resolution/6)))
    count = min(8192,requested)
    edges = np.linspace(lo,hi,count+1)
    power = np.zeros(count)
    for line in lines:
        cdf = np.array([.5*(1+math.erf((e-line['wavelength_nm'])/(math.sqrt(2)*sigma))) for e in edges])
        mass = np.maximum(0., np.diff(cdf))
        # Renormalize finite plotted tails; never discard received source power.
        power += line['power'] * mass/mass.sum()
    out.update(wavelength_nm=((edges[:-1]+edges[1:])/2).tolist(), bin_power=power.tolist(),
               power_density_per_nm=(power/np.diff(edges)).tolist(), bin_edges_nm=edges.tolist(),
               sampling_limited=requested>count)
    return out


def image(result, px=256):
    arr = np.empty((px,px,4), dtype='float32'); arr[:] = (.04,.05,.07,1)
    # Small built-in bitmap labels keep live plots self-contained in Blender's
    # Python (no font, Pillow, matplotlib or GPU dependency).
    glyphs = {
        '0':'111101101101111', '1':'010110010010111', '2':'111001111100111',
        '3':'111001111001111', '4':'101101111001001', '5':'111100111001111',
        '6':'111100111101111', '7':'111001010010010', '8':'111101111101111',
        '9':'111101111001111', '.':'000000000000010', '-':'000000111000000',
        '+':'000010111010000', 'e':'000111111100111', 'r':'000110101100100',
        'l':'100100100100111', 'n':'000110101101101', 'm':'000101111111101',
        '/':'001001010100100',
    }
    scale=max(1,px//128)
    left,right,bottom,top=30*scale,6*scale,16*scale,12*scale
    width=px-left-right-1; height=px-bottom-top-1
    def text(x,y,value):
        x=max(0,min(int(x),px-len(value)*4*scale))
        for ch in value:
            glyph=glyphs.get(ch,'0'*15)
            for row in range(5):
                for col in range(3):
                    if glyph[row*3+col]=='1':
                        yy=y+(4-row)*scale; xx=x+col*scale
                        arr[yy:yy+scale,xx:xx+scale,:3]=.7
            x+=4*scale
    for i in range(5):
        x=left+int(width*i/4); y=bottom+int(height*i/4)
        arr[bottom:bottom+height+1,x,:3]=.18
        arr[y,left:left+width+1,:3]=.18
    values = result['power_density_per_nm']
    text(2*scale,px-7*scale,'rel/nm')
    text(left+width//2-4*scale,2*scale,'nm')
    text(left-6*scale,bottom,'0')
    edges=result['bin_edges_nm']
    if edges:
        for fraction in (0.,.5,1.):
            label='%.4g' % (edges[0]+fraction*(edges[-1]-edges[0]))
            text(left+fraction*width-len(label)*2*scale,bottom-7*scale,label)
    if not values or max(values)<=0: return arr
    text(0,bottom+height-4*scale,'%.2g' % max(values))
    # Max per display column preserves narrow peaks at low screen resolution.
    bins = np.array_split(np.asarray(values), min(len(values),width+1))
    ys = [float(b.max()) for b in bins]
    xs = np.linspace(left,left+width,len(ys))
    coords = [(x,bottom+y/max(ys)*height) for x,y in zip(xs,ys)]
    for (x0,y0),(x1,y1) in zip(coords,coords[1:]):
        n = max(2,int(max(abs(x1-x0),abs(y1-y0)))+1)
        xx = np.linspace(x0,x1,n).astype(int); yy = np.linspace(y0,y1,n).astype(int)
        arr[yy,xx,:3] = (.25,.8,1.)
    return arr


def caption(result):
    edges = result['bin_edges_nm']
    span = ('%.1f–%.1f nm' % (edges[0],edges[-1])) if edges else 'no arrivals'
    return '%s | FWHM %g nm | P=%g rel.%s' % (span,result['resolution_fwhm_nm'],result['total_power'],
             ' | grid limited' if result['sampling_limited'] else '')


def save_csv(result, path):
    with open(path,'w',newline='',encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['wavelength_nm','bin_lower_nm','bin_upper_nm','bin_power_relative',
                         'power_density_relative_per_nm','resolution_fwhm_nm'])
        for i,(wl,p,density) in enumerate(zip(result['wavelength_nm'],result['bin_power'],result['power_density_per_nm'])):
            writer.writerow([wl,result['bin_edges_nm'][i],result['bin_edges_nm'][i+1],p,density,result['resolution_fwhm_nm']])
    return path
