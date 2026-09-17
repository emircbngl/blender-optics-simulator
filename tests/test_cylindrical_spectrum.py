"""Cylindrical focusing and ideal spectrometer integration; run inside Blender."""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bpy
import numpy as np
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import elements_generic as G, tracer, scan, optics_api, physics

checks = []
def check(label, cond):
    checks.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + label, flush=True)

def clear():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

clear()
src = G.source('Source', (0,0,-100), (0,0,1), wavelength=633)
lens = G.lens('Cylinder', (0,0,0), (0,0,1), focal=100, lens_type='CYLINDRICAL')
det = G.detector('Camera', (0,0,97.5), (0,0,1), size=20)
bpy.context.view_layer.update()
segs = tracer.trace_scene(bpy.context.scene, max_segments=128)
arrival = next(s for s in segs if s.get('to') == det.name)
check('cylindrical lens carries astigmatic state', bool(arrival.get('gaussian')))
if arrival.get('gaussian'):
    from optical_alignment_sim.gaussian import GaussianQ
    q = GaussianQ.unpack(arrival['gaussian'])
    widths = q.radii(633)
    check('cylinder forms a line, not a round spot', max(widths)/min(widths) > 5)
arr, used = scan._fringe_array(det, segs, 2, 256)
yy, xx = np.mgrid[:256,:256]
weights = arr[:,:,0]
mx = (weights*xx).sum()/weights.sum(); my = (weights*yy).sum()/weights.sum()
vx = (weights*(xx-mx)**2).sum()/weights.sum(); vy = (weights*(yy-my)**2).sum()/weights.sum()
check('sensor image resolves focused and unfocused axes', max(vx,vy)/min(vx,vy) > 10)
check('detector offers intensity and spectrum modes', hasattr(det.optics, 'sensor_mode'))
check('spectrum API is available', callable(getattr(optics_api, 'detector_spectrum', None)))
if hasattr(det.optics, 'sensor_mode'):
    clear()
    G.source('Green', (0,0,-100), (0,0,1), wavelength=532)
    G.source('Red', (0,0,-100), (0,0,1), wavelength=633)
    det = G.detector('Spectrum', (0,0,0), (0,0,1), size=20)
    det.optics.sensor_mode = 'SPECTRUM'
    det.optics.spectrum_resolution_nm = 2
    bpy.context.view_layer.update()
    result = optics_api.detector_spectrum('Spectrum')
    check('two wavelengths survive at same detector pixel', [x['wavelength_nm'] for x in result['lines']] == [532.,633.])
    check('spectrum conserves received power', abs(sum(result['bin_power'])-result['total_power']) < 1e-9)
    check('spectrum total equals two source powers', abs(result['total_power']-2) < 1e-6)
    check('finite resolution broadens lines', max(result['bin_power']) < 1 and sum(p>0 for p in result['bin_power']) > 4)

if hasattr(det.optics, 'sensor_mode'):
    from optical_alignment_sim import spectrum, alignment, library, ao, geometry
    from optical_alignment_sim.gaussian import GaussianQ
    from mathutils import Vector
    import tempfile, csv, json
    def peaks(values):
        v = np.asarray(values)
        return sum((v[1:-1]>v[:-2]) & (v[1:-1]>v[2:]) & (v[1:-1]>.1*v.max()))
    check('fine resolution resolves two spectral peaks', peaks(result['bin_power']) == 2)
    det.optics.spectrum_resolution_nm = 200
    coarse = optics_api.detector_spectrum(det.name)
    check('coarse resolution merges nearby colors', peaks(coarse['bin_power']) == 1)
    check('coarse resolution conserves power', abs(sum(coarse['bin_power'])-2)<1e-9)
    segs = tracer.trace_scene(bpy.context.scene)
    # Same-frequency coherent fields are summed BEFORE the instrument broadening.
    same = [dict(segs[0], src_id=7), dict(segs[0], src_id=7)]
    coherent = spectrum.measure(det,same)
    same[1]['src_id'] = 8
    incoherent = spectrum.measure(det,same)
    check('coherence within each wavelength is retained', abs(coherent['total_power']-2*incoherent['total_power'])<1e-8)
    det.optics.analyzer = 'H'
    h = spectrum.measure(det,segs)['total_power']
    det.optics.analyzer = 'V'
    v = spectrum.measure(det,segs)['total_power']
    # Existing H/V analyzers use a finite 1000:1 extinction, not ideal projectors.
    check('spectrometer applies finite-extinction analyzer before binning', abs(h+v-2.002)<1e-6 and min(h,v)<.01)
    det.optics.analyzer = 'NONE'
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp,'spectrum.csv')
        result = optics_api.detector_spectrum(det.name, path)
        with open(path) as f: rows = list(csv.DictReader(f))
        check('CSV values retain total measured power', abs(sum(float(r['bin_power_relative']) for r in rows)-2)<1e-9)
        check('Blender CSV operator exports successfully', bpy.ops.optics.save_spectrum(name=det.name,filepath=path)=={'FINISHED'})
        check('spectrum PNG save operator works', bpy.ops.optics.save_sensor(name=det.name,filepath=os.path.join(tmp,'spectrum.png'))=={'FINISHED'})
    empty = spectrum.measure(det,[])
    check('empty detector has empty spectrum and zero power', empty['lines']==[] and empty['total_power']==0)
    check('empty spectrum image is finite', np.isfinite(spectrum.image(empty)).all())
    bpy.context.scene.optics.monitor_show = True
    tracer.cached_segments = segs
    scan.live_fringe_update(bpy.context.scene)
    from optical_alignment_sim import monitor
    check('live sensor publishes spectrum with wavelength range', 'nm' in monitor._frames[det.name]['text'])
    tracer.cached_segments=[]
    scan.live_fringe_update(bpy.context.scene)
    check('empty live trace clears the old spectrum', det.name not in monitor._frames)

    # General astigmatism: rotate a cylinder relative to an already elliptical beam.
    q0 = physics.q_from_waist(.5,633)
    frame = [(1,0,0),(0,1,0)]
    q = GaussianQ(np.eye(2)*q0,frame)
    q1 = q.lens(100,(1,0,0)).abcd(physics.abcd_free(100))
    expected = [physics.q_propagate(q0,physics.abcd_lens(100))+100, q0+100]
    check('aligned cylinder matches independent scalar ABCD in both axes', np.allclose(q1.matrix,np.diag(expected)))
    check('thin cylinder preserves entrance beam radii', np.allclose(q.radii(633),q.lens(100,(1,0,0)).radii(633)))
    check('diverging cylinder widens powered axis', max(q.lens(-100,(1,0,0)).abcd(physics.abcd_free(100)).radii(633)) > .9)
    round_pair = q.lens(100,(1,0,0)).lens(100,(0,1,0)).abcd(physics.abcd_free(100))
    spherical = physics.q_propagate(q0,physics.abcd_lens(100))+100
    check('orthogonal cylinder pair equals spherical thin lens', np.allclose(round_pair.matrix,np.eye(2)*spherical))
    cross = q1.lens(80,(math.sqrt(.5),math.sqrt(.5),0)).abcd(physics.abcd_free(55))
    check('crossed cylinders retain off-diagonal coupling', abs(cross.matrix[0,1])>1)
    check('crossed cylinders remain symmetric with positive intensity', np.allclose(cross.matrix,cross.matrix.T) and np.all(np.linalg.eigvalsh(cross.precision(633))>0))
    check('branches do not mutate their parent Gaussian', np.allclose(q.matrix,np.eye(2)*q0))
    normal=np.array([1.,0.,-1.])/math.sqrt(2)
    reflection=np.eye(3)-2*np.outer(normal,normal)
    reflected=cross.reflect(normal)
    before=cross.axes.T @ np.linalg.inv(cross.precision(633)) @ cross.axes
    after=reflected.axes.T @ np.linalg.inv(reflected.precision(633)) @ reflected.axes
    check('reflection preserves full rotated elliptical covariance', np.allclose(after,reflection @ before @ reflection))

    def cylinder_bench(roll=0, unit=1):
        clear(); tracer.cached_segments=[]
        bpy.context.scene.unit_settings.system='METRIC'
        bpy.context.scene.unit_settings.scale_length=unit/1000
        G.source('Source',(0,0,-100),(0,0,1),wavelength=633)
        lens=G.lens('Cylinder',(0,0,0),(0,0,1),focal=100,lens_type='CYLINDRICAL')
        lens.rotation_euler.z=roll
        det=G.detector('Camera',(0,0,101.5),(0,0,1),size=20)
        bpy.context.view_layer.update()
        segs=tracer.trace_scene(bpy.context.scene,max_segments=128)
        s=next(s for s in segs if s.get('to')==det.name)
        return lens,det,segs,s
    lens,det,segs,s = cylinder_bench()
    test_ray=tracer._Ray(Vector((0,0,-10)),Vector((0,0,1)),1,0,None,633,'SOURCE',-1,q=q0)
    ghost=tracer._child(test_ray,lens,Vector((0,0,0)),Vector((0,0,-1)),.04,'GHOST',0,10)
    check('front-surface ghost does not acquire cylinder power', not isinstance(ghost.q,GaussianQ) and abs(ghost.q-(q0+10))<1e-9)
    q = GaussianQ.unpack(s['gaussian'])
    original = q.axes.T @ np.linalg.inv(q.precision(633)) @ q.axes
    arr,_ = scan._fringe_array(det,segs,2,256)
    original_image=arr.copy()
    profile=scan.beam_profile_data(bpy.context.scene,det.name)
    check('beam profile includes both axes to detector', len(profile['w_major'])==len(profile['z']) and
          abs(profile['w_major'][-1]-max(s['radii_mm']))<1e-6)
    inspect=optics_api.inspect_beam(det.name)
    check('inspect reports full Gaussian state without a fake scalar q', 'principal_radii_mm' in inspect and 'R_mm' not in inspect)
    json.dumps(inspect)
    from optical_alignment_sim import bake
    api_bake=optics_api.bake_beams()
    beam_index=next(i for i,row in enumerate(tracer.cached_segments) if row.get('to')==det.name)
    beam=bpy.data.objects['BEAM_%02d' % beam_index]
    end=np.array([tuple(v.co) for v in beam.data.vertices[-32:]])
    check('baked cylinder envelope retains unequal transverse widths', np.ptp(end[:,1])>1.4*np.ptp(end[:,0]))
    sig_before=bake._segments_sig(tracer.cached_segments)
    import bmesh
    bm=bmesh.new(); bm.from_mesh(lens.data)
    check('cylindrical lens mesh is watertight', all(e.is_manifold for e in bm.edges))
    bm.free()
    lens,det,segs,s=cylinder_bench(math.pi/2)
    qrot=GaussianQ.unpack(s['gaussian'])
    rotated=qrot.axes.T @ np.linalg.inv(qrot.precision(633)) @ qrot.axes
    check('90 degree lens roll exchanges physical beam axes', np.allclose(rotated[0,0],original[1,1],rtol=1e-5) and np.allclose(rotated[1,1],original[0,0],rtol=1e-5))
    check('bake invalidates when only ellipse orientation changes', bake._segments_sig(segs)!=sig_before)
    rotated_image,_=scan._fringe_array(det,segs,2,256)
    check('90 degree roll rotates sensor image', np.max(np.abs(rotated_image[:,:,0]-original_image[:,:,0].T))<1e-4)
    lens,det,segs,metre=cylinder_bench(unit=1000)
    check('astigmatic beam agrees in metre and millimetre scenes', np.allclose(sorted(metre['radii_mm']),sorted(s['radii_mm']),rtol=2e-5))
    lens,det,segs,s=cylinder_bench()
    q=GaussianQ.unpack(s['gaussian'])
    # Put an aperture at the detector plane; local aperture axes match the beam frame.
    ap=G.aperture('Aperture',(0,0,97.5),(0,0,1),radius=1)
    ap.optics.aperture_shape='RECTANGULAR'; ap.optics.clear_aperture=.02; ap.optics.aperture_half_y=.3
    bpy.context.view_layer.update()
    hit=Vector((0,0,97.5))
    power=q.aperture(ap,Vector((0,0,1)),hit,hit,Vector((0,0,1)),633,1)
    wx=q.marginal_radius((1,0,0),633); wy=q.marginal_radius((0,1,0),633)
    expected=math.erf(math.sqrt(2)*.02/wx)*math.erf(math.sqrt(2)*.3/wy)
    check('rectangular aperture integrates elliptical power', abs(power-expected)<2e-4)
    ap.optics.aperture_shape='CIRCULAR'; ap.optics.clear_aperture=2
    check('large circular aperture passes the whole line', q.aperture(ap,Vector((0,0,1)),hit,hit,Vector((0,0,1)),633,1)>.999)
    ray=tracer._Ray(hit,Vector((0,0,1)),1,0,None,633,'TRANSMIT',-1,q=q)
    slit=G.slit('Slit',hit,(0,0,1),width=.04)
    bpy.context.view_layer.update()
    t0=tracer._slit_T(ray,slit,hit,0)
    slit.optics.slit_angle=90
    t90=tracer._slit_T(ray,slit,hit,0)
    check('Raman slit resolves narrow and wide beam axes', t0>t90*5)
    # Wavefront sensor readout contains the cylinder's astigmatic curvature.
    det.optics.element_type='WAVEFRONT_SENSOR'
    coeffs,info=ao._sensor_wavefront(segs,det.name,1)
    check('WFS readout retains astigmatism', abs(coeffs[4])+abs(coeffs[5])>1e-4)
    for key in ['CYLINDRICAL_LENS','SPECTROMETER']:
        clear()
        ob,_=library.add_component(key)
        check('library creates '+key, ob is not None and (ob.optics.lens_type=='CYLINDRICAL' if key=='CYLINDRICAL_LENS' else ob.optics.sensor_mode=='SPECTRUM'))

print('CYLINDER/SPECTRUM %s (%d/%d checks)' % ('PASS' if all(checks) else 'FAIL',sum(checks),len(checks)), flush=True)
if not all(checks): raise SystemExit(1)
