"""Small regression witnesses for the agent-facing control contract.

Run inside Blender with the add-on registered. These checks protect the boundary an MCP agent
uses: fresh reads, explicit mutation results, physically meaningful tolerance statistics, and
power bookkeeping for degenerate nonlinear output modes.
"""
import math
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import optical_alignment_sim as oas
oas.register()
from optical_alignment_sim import optics_api as api, elements_generic as eg
from optical_alignment_sim import tracer, alignment, physics

checks = []


def check(name, condition, detail=""):
    ok = bool(condition)
    checks.append(ok)
    print("  %-68s %s%s" % (name, "PASS" if ok else "FAIL",
                           (" <- " + detail) if not ok else ""), flush=True)


def clear():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    tracer.cached_segments = []
    bpy.context.scene.optics.live_enabled = False
    bpy.context.view_layer.update()


manifest = api.capabilities()
contract = manifest.get("control_contract", {})
check("capabilities exposes inspect -> mutate -> verify contract",
      contract.get("protocol") == "inspect -> decide -> mutate -> verify")
check("contract separates reads and writes",
      set(contract.get("read", ())) >= {"get_state", "diagnose"}
      and set(contract.get("write", ())) >= {"set_param", "set_mount"})
check("contract marks corrections advisory",
      contract.get("advisories_are_not_commands") is True)

# Quaternion-independent tolerance perturbation + all-trial yield.
clear()
coll = bpy.data.collections.new("CONTROL_TEST")
bpy.context.scene.collection.children.link(coll)
eg.source("S", (-120, 0, 0), (1, 0, 0), coll=coll)
mirror = eg.mirror("M", (0, 0, 0), (1, 0, 0), (0, 1, 0), coll=coll)
eg.detector("D", (0, 120, 0), (0, 1, 0), coll=coll, size=4)
mirror.rotation_mode = 'QUATERNION'
bpy.context.view_layer.update()
tol = api.tolerance_scan(["M"], "D", sigma_pos_mm=0.0, sigma_ang_deg=0.8,
                         n=40, seed=4, tol_mm=100.0)
check("quaternion tolerance scan has angular sensitivity",
      tol.get("pointing_rms_mm", 0.0) > 0.0, str(tol))
check("tolerance yield uses all trials",
      abs(tol.get("yield", -1.0) - tol.get("hit_rate", -2.0)) < 1e-12, str(tol))

# Degenerate signal/idler are separate output modes; they must add power, not a false coherent cross term.
clear()
coll = bpy.data.collections.new("NONLINEAR_CONTROL_TEST")
bpy.context.scene.collection.children.link(coll)
eg.source("S", (-80, 0, 0), (1, 0, 0), coll=coll, wavelength=405)
eg.crystal("X", (0, 0, 0), (1, 0, 0), coll=coll, nl_process='SPDC',
           nl_lambda2_nm=800, crystal_length_mm=10)
eg.detector("D", (80, 0, 0), (1, 0, 0), coll=coll)
bpy.context.view_layer.update()
segs = tracer.trace_scene(bpy.context.scene, max_segments=128, max_depth=16)
incoming = [s for s in segs if s.get("to") == "D"]
measured = alignment.measure(segs, "D")[0]
arriving = sum(s.get("power", 0.0) for s in incoming)
check("degenerate SPDC detector power equals arriving power",
      abs(measured - arriving) < 1e-9 and measured <= 1.0 + 1e-9,
      "measured=%r arriving=%r" % (measured, arriving))

# Large phase mismatch must converge instead of aliasing the 400-step default grid.
low = physics.chi2_shg_efficiency(0.512, -5026.548245743669)
check("chi2 mismatch is resolved without RK4 phase aliasing", low < 1e-6, str(low))

# Exercise actual panel draw paths with registered Blender RNA, with Advanced disabled.
from types import SimpleNamespace
from optical_alignment_sim import ui, properties
class Layout:
    def __init__(self, fields): self.fields = fields
    def child(self, *a, **k): return Layout(self.fields)
    column = row = box = grid_flow = split = child
    def prop(self, data, name, **kw):
        assert hasattr(data, name), name
        self.fields.add(name)
    def operator(self, name, **kw):
        namespace, op = name.split('.')
        getattr(getattr(bpy.ops, namespace), op).get_rna_type()
        self.fields.add(name)
        return SimpleNamespace()
    def label(self, **kw): pass
    def template_list(self, *a, **kw): pass
    def separator(self, *a, **kw): pass

original_advanced = ui._advanced_enabled
try:
    ui._advanced_enabled = lambda: False
    obj = bpy.data.objects['X']
    seen = {}
    for et, *_ in properties.ELEMENT_TYPES:
        obj.optics.element_type = et
        fields = set()
        ui.OPTICS_PT_element.draw(SimpleNamespace(layout=Layout(fields)),
                                 SimpleNamespace(object=obj))
        seen[et] = fields
    check("every element basic panel draws valid properties and operators", bool(seen))
    check("shutter and waveplate essentials are visible without Advanced",
          'shutter_open' in seen['SHUTTER'] and 'fast_axis_deg' in seen['WAVEPLATE'])
    check("unrelated source/lens controls are absent from shutter",
          not ({'focal_length', 'wavelength', 'waist_um'} & seen['SHUTTER']))
    bpy.context.scene.optics.trace_mode = 'ORDER'
    fields = set()
    ui.OPTICS_PT_trace_settings.draw(SimpleNamespace(layout=Layout(fields)), bpy.context)
    check("order mode exposes its required sequence", 'order_csv' in fields)
finally:
    ui._advanced_enabled = original_advanced

clear()
scene = bpy.context.scene
scene.optics.trace_mode = 'AUTO'
scene.optics.scene_units_authoritative = True
scene.unit_settings.scale_length = 1.0
source = eg.source('UnitsSource', (-100, 0, 0), (1, 0, 0))
bpy.context.view_layer.update()
state = api.get_state()
factor = state['coordinate_units']['mm_per_world_unit']
center = next(e['world_center'] for e in state['elements'] if e['name'] == source.name)
check("agent can interpret raw coordinates in a declared metre scene",
      abs(center[0] * factor + 100.0) < 1e-4 and factor == 1000.0)

# Nonlinear scene regression witnesses, including independent polarization limits.
def nonlinear(process, wavelength=1064, second=800, angle=0, solver=False):
    clear()
    scene = bpy.context.scene
    scene.optics.scene_units_authoritative = False
    src = eg.source('S', (-80, 0, 0), (1, 0, 0), wavelength=wavelength)
    src.optics.pol_angle = angle
    crystal = eg.crystal('X', (0, 0, 0), (1, 0, 0), nl_process=process,
                         nl_lambda2_nm=second, phase_matching_type='TYPE2',
                         use_chi2_solver=solver, crystal_length_mm=10)
    eg.detector('D', (80, 0, 0), (1, 0, 0))
    bpy.context.view_layer.update()
    segs = api._trace(scene)
    return [s for s in segs if s['to'] == 'D']

for solver in (False, True):
    powers = []
    for angle in (0, 45, 90):
        hits = nonlinear('SHG', angle=angle, solver=solver)
        powers.append(sum(s['power'] for s in hits if s['kind'] == 'SHG'))
        check('Type-II preserves total power (%s, %s)' % (solver, angle),
              abs(sum(s['power'] for s in hits)-1) < 2e-4)
    check('Type-II requires both pump components (solver=%s)' % solver,
          powers[0] < 1e-6 and powers[2] < 1e-6 and powers[1] > 1e-4, str(powers))
for process, pump, second in [('DFG',1550,1064), ('OPO',1064,532)]:
    hits = nonlinear(process, pump, second)
    check('invalid %s child preserves pump' % process,
          len(hits) == 1 and hits[0]['kind'] == 'TRANSMIT' and hits[0]['power'] == 1)
hits = nonlinear('OPO', 532, 800)
sig = next(s for s in hits if s['kind'] == 'SIGNAL')
idl = next(s for s in hits if s['kind'] == 'IDLER')
check('nondegenerate OPO generates equal signal/idler photon flux',
      abs(sig['power']*sig['wavelength'] - idl['power']*idl['wavelength']) < 0.2)
check('nondegenerate OPO total power is conserved', abs(sum(s['power'] for s in hits)-1) < 2e-4)

from optical_alignment_sim import handlers
signature = handlers._signature(bpy.context.scene)
bpy.data.objects['X'].optics.ports[0].local_position.y += 1
check('port geometry invalidates live signature', signature != handlers._signature(bpy.context.scene))
try:
    physics.chi2_shg_efficiency(1, 1e10)
    check('excessive solver resolution fails explicitly', False)
except ValueError:
    check('excessive solver resolution fails explicitly', True)

# Export must consume one fresh trace, with per-element rows still populated.
import tempfile
clear()
api.build_example('mach_zehnder')
original_trace = tracer.trace_scene
trace_calls = []
def counted_trace(*args, **kwargs):
    trace_calls.append(1)
    return original_trace(*args, **kwargs)
try:
    tracer.trace_scene = counted_trace
    report = api.export_report(os.path.join(tempfile.gettempdir(), 'optics-regression-report.html'))
finally:
    tracer.trace_scene = original_trace
check('report shares one trace and retains element rows',
      len(trace_calls) == 1 and report.get('n_elements', 0) > 0, str(report))

hits = nonlinear('OPO', 532, 800)
detector = bpy.data.objects['D']
detector.optics.det_material = 'Si'
api.get_state()
expected = sum(physics.responsivity('Si', hit['wavelength']) * hit['power'] for hit in hits) * detector.optics.det_gain
check('multicolour detector sums wavelength-specific responsivity',
      abs(detector.optics.meas_current-expected) < 1e-5,
      str((detector.optics.meas_current, expected)))
for mismatch in (0, 1, 10, 100):
    actual = physics.chi2_shg_type2_efficiency(0.8, 0.5, dkL=mismatch)
    expected = physics.chi2_shg_efficiency(0.4, mismatch)
    check('balanced Type-II agrees with independent Type-I reduction at dkL=%s' % mismatch,
          abs(actual-expected) < 1e-7, str((actual, expected)))

from optical_alignment_sim import operators
bpy.context.view_layer.update()
operators._store_corrections(bpy.context.window_manager, [dict(issue='crossed_polarizer',
    element='D', suggested_fix='Adjust the analyzer', tool='set_param', severity='WARN')])
old_analyzer = bpy.data.objects['D'].optics.analyzer
result = bpy.ops.optics.fix_diagnosis(index=0)
check('manual correction selects its element without changing optical settings',
      result == {'FINISHED'} and bpy.context.object.name == 'D'
      and bpy.context.object.optics.analyzer == old_analyzer)

check('grating diffraction efficiency is editable without Advanced',
      'reflectivity' in seen['GRATING'], str(sorted(seen['GRATING'])))

# Live off: an explicit Trace Now stays until something the trace read changes.
clear()
api.build_example('mach_zehnder')
scene = bpy.context.scene
scene.optics.live_enabled = False
bpy.context.view_layer.update()
bpy.ops.optics.trace_now()
traced = len(tracer.cached_segments)
optic = next(o for o in scene.objects if o.optics.is_optical and o.optics.element_type == 'MIRROR')
optic.select_set(True)
bpy.context.view_layer.update()
after_select = len(tracer.cached_segments)
optic.hide_render = not optic.hide_render
bpy.context.view_layer.update()
after_unrelated = len(tracer.cached_segments)
optic.location.x += 1.0
bpy.context.view_layer.update()
check('live-off trace survives selecting an object', traced > 0 and after_select == traced,
      "%d -> %d" % (traced, after_select))
check('live-off trace survives a change the tracer does not read', after_unrelated == traced,
      "%d -> %d" % (traced, after_unrelated))
check('live-off trace is dropped when an optic moves', len(tracer.cached_segments) == 0,
      str(len(tracer.cached_segments)))

# Converted light reaching a detector still belongs to its source (coherence ids are tuples).
clear()
eg.source('S', (-80, 0, 0), (1, 0, 0), wavelength=532)
eg.crystal('X', (0, 0, 0), (1, 0, 0), nl_process='OPO', nl_lambda2_nm=800, crystal_length_mm=10)
pump_block = eg.optical_filter('F', (40, 0, 0), (1, 0, 0))
pump_block.optics.filt_type = 'LP'
pump_block.optics.cut_nm = 700
eg.detector('D', (80, 0, 0), (1, 0, 0))
bpy.context.view_layer.update()
arrivals = [s for s in api._trace(scene) if s['to'] == 'D']
issues = [i.get('id') or i.get('kind') or i.get('code') for i in api.diagnose().get('diagnostics', [])]
check('OPO signal/idler reach the detector with the pump blocked',
      arrivals and all(s['wavelength'] > 700 for s in arrivals), str(arrivals))
check('converted light is not reported as an orphaned source', 'orphan_source' not in issues, str(issues))

# Unpolarized Type-II: a depolarized constant-intensity beam is a uniform ensemble of pure states on
# the Poincare sphere, so the conversion is the ensemble average and cannot depend on crystal roll.
import random
from mathutils import Matrix
rng = random.Random(7)
def random_pure_fo():
    # uniform on the sphere: normalised 3-D Gaussian Stokes direction; s1 is the o/e component
    x, y, z = (rng.gauss(0.0, 1.0) for _ in range(3))
    return 0.5 * (1.0 + x / math.sqrt(x * x + y * y + z * z))
samples = [random_pure_fo() for _ in range(20000)]
for eff in (0.3, 0.8):
    mc = sum(min(eff * 4 * fo * (1 - fo), 2 * min(fo, 1 - fo)) for fo in samples) / len(samples)
    got = physics.type2_unpolarized_static_efficiency(eff)
    check('static unpolarized Type-II matches a Monte-Carlo pure-state average (eff=%s)' % eff,
          abs(got - mc) < 5e-3, str((got, mc)))
check('static unpolarized Type-II is 2/3 of balanced below the cap',
      abs(physics.type2_unpolarized_static_efficiency(0.3) - 0.2) < 1e-12)
for drive in (0.05, 2.0):
    mc = sum(physics.chi2_shg_type2_efficiency(drive, fo) for fo in samples[:400]) / 400
    got = physics.chi2_shg_type2_unpolarized_efficiency(drive)
    check('solver unpolarized Type-II matches a Monte-Carlo pure-state average (drive=%s)' % drive,
          abs(got - mc) < 0.03 * max(mc, 1e-9), str((got, mc)))

def unpol_type2(roll_deg=0.0, before=None, solver=False):
    clear()
    s = eg.source('S', (-80, 0, 0), (1, 0, 0), wavelength=1064)
    s.optics.pol_type = 'UNPOL'
    if before == 'POLARIZER':
        eg.polarizer('P', (-40, 0, 0), (1, 0, 0)).optics.pol_axis_deg = 0.0
    elif before == 'HWP':
        eg.waveplate('W', (-40, 0, 0), (1, 0, 0), kind='HWP', fast_axis=22.5)
    x = eg.crystal('X', (0, 0, 0), (1, 0, 0), nl_process='SHG', phase_matching_type='TYPE2',
                   crystal_length_mm=10, use_chi2_solver=solver)
    x.matrix_world = Matrix.Rotation(math.radians(roll_deg), 4, 'X') @ x.matrix_world
    eg.detector('D', (80, 0, 0), (1, 0, 0))
    bpy.context.view_layer.update()
    hits = [h for h in api._trace(bpy.context.scene) if h['to'] == 'D']
    return sum(h['power'] for h in hits if h['kind'] == 'SHG'), sum(h['power'] for h in hits)

rolls = [unpol_type2(r) for r in (0.0, 22.5, 45.0)]
expected = physics.type2_unpolarized_static_efficiency(0.4)
# segment powers are rounded to 4 decimals (tracer _seg)
check('unpolarized Type-II SHG does not depend on crystal roll',
      len({shg for shg, _ in rolls}) == 1 and abs(rolls[0][0] - expected) < 1e-4, str((rolls, expected)))
check('unpolarized Type-II SHG conserves power', all(abs(tot - 1.0) < 1e-4 for _, tot in rolls), str(rolls))
check('a half-wave plate keeps the beam unpolarized', abs(unpol_type2(0.0, 'HWP')[0] - expected) < 1e-4,
      str(unpol_type2(0.0, 'HWP')))
check('a polarizer along the o axis leaves no Type-II conversion', unpol_type2(0.0, 'POLARIZER')[0] < 1e-6,
      str(unpol_type2(0.0, 'POLARIZER')))
solver_rolls = [unpol_type2(r, solver=True)[0] for r in (0.0, 45.0)]
check('solver unpolarized Type-II SHG does not depend on crystal roll',
      solver_rolls[0] > 0 and abs(solver_rolls[0] - solver_rolls[1]) < 1e-9, str(solver_rolls))

# Render handlers must not change data during an interactive render unless the interface is locked
# (bpy.app.handlers "Note on Altering Data"); the Render panel says so before the user renders.
from optical_alignment_sim import handlers
clear()
api.build_example('mach_zehnder')
scene = bpy.context.scene
scene.frame_set(1)
moving = next(o for o in scene.objects if o.optics.is_optical and o.optics.element_type == 'MIRROR')
moving.keyframe_insert('location', frame=1)
bpy.context.view_layer.update()
api.bake_beams()
def beams_marked():
    return any(o.get('render_probe') for o in scene.objects if o.name.startswith('BEAM_'))
next(o for o in scene.objects if o.name.startswith('BEAM_'))['render_probe'] = 1
moving.location.x += 3.0
bpy.context.view_layer.update()
original_background = handlers._is_background
try:
    handlers._is_background = lambda: False
    scene.render.use_lock_interface = False
    check('render lock warning shows for baked beams on an animated bench',
          handlers.beams_need_render_lock(scene))
    fields = set()
    ui.OPTICS_PT_render.draw(SimpleNamespace(layout=Layout(fields)), bpy.context)
    check('render panel offers Lock Interface inline', 'use_lock_interface' in fields, str(sorted(fields)))
    handlers.on_render_init(scene)
    handlers._last_sig = 'unchanged'
    handlers.on_frame_change(scene)
    handlers.on_render_pre(scene)
    check('unlocked render: frame change leaves live state alone', handlers._last_sig == 'unchanged')
    check('unlocked render: baked beams are not rebuilt', beams_marked())
    handlers.on_render_done(scene)
    scene.render.use_lock_interface = True
    check('no render lock warning once the interface is locked', not handlers.beams_need_render_lock(scene))
    handlers.on_render_init(scene)
    handlers.on_frame_change(scene)
    handlers.on_render_pre(scene)
    handlers.on_render_done(scene)
    check('locked render: frame change re-arms the live trace', handlers._last_sig != 'unchanged')
    check('locked render: moved optics re-bake their beams', not beams_marked())
finally:
    handlers._is_background = original_background
    scene.render.use_lock_interface = False

# Fine-step knobs (Harca-Yita, 31 Aug): each DOF carries its own step; - / + turn it by one step.
clear()
knob_mirror = eg.mirror('K', (0, 0, 0), (1, 0, 0), (0, 1, 0))
api.set_mount('K', 'KM100')
bpy.context.view_layer.update()
bpy.context.view_layer.objects.active = knob_mirror
tip_index, tip = next((i, d) for i, d in enumerate(knob_mirror.optics.dofs) if d.kind == 'TIP')
check('a DOF has a step size, 0.01 by default', abs(getattr(tip, 'step', -1) - 0.01) < 1e-9)
tip.step = 0.25
pose0 = knob_mirror.matrix_world.copy()
bpy.ops.optics.nudge_dof(name='K', index=tip_index, direction=1)
check('+ turns the knob by one step', abs(tip.current - 0.25) < 1e-6, str(tip.current))
check('+ moves the mount', max(abs(knob_mirror.matrix_world[r][c] - pose0[r][c])
                               for r in range(3) for c in range(3)) > 1e-4)
bpy.ops.optics.nudge_dof(name='K', index=tip_index, direction=-1)
check('- returns the knob and the pose', abs(tip.current) < 1e-6 and
      max(abs(knob_mirror.matrix_world[r][c] - pose0[r][c]) for r in range(3) for c in range(4)) < 1e-5)
tip.current = tip.max_val - 0.1
bpy.ops.optics.nudge_dof(name='K', index=tip_index, direction=1)
check('a step past the range stops at the limit', abs(tip.current - tip.max_val) < 1e-6, str(tip.current))
fields = set()
ui.OPTICS_PT_element.draw(SimpleNamespace(layout=Layout(fields)), SimpleNamespace(object=knob_mirror))
check('element panel offers - / + beside each knob', 'optics.nudge_dof' in fields and 'current' in fields)
fields = set()
ui.OPTICS_PT_mount.draw(SimpleNamespace(layout=Layout(fields)), SimpleNamespace(object=knob_mirror))
check('mount panel edits the step and turns the knob', {'step', 'current', 'optics.nudge_dof'} <= fields,
      str(sorted(fields)))
from optical_alignment_sim import mounts
saved = mounts.serialize_mount(knob_mirror)
check('a saved mount preset keeps the step', any(abs(d.get('step', -1) - 0.25) < 1e-9 for d in saved['dofs']),
      str(saved['dofs']))
check('get_state reports each knob step',
      any(abs(d.get('step', -1) - 0.25) < 1e-6
          for e in api.get_state()['elements'] if e['name'] == 'K' for d in e['mount']['dofs']))

# Diagnose and Propose Corrections keep their own lists, and selecting an object does not stale them.
clear()
api.build_example('mach_zehnder')
wm = bpy.context.window_manager
tilted = next(o for o in bpy.context.scene.objects if o.optics.is_optical and o.optics.element_type == 'MIRROR')
tilted.rotation_euler.z += 0.05
bpy.context.view_layer.update()
bpy.ops.optics.diagnose()
diagnosed = [i.issue for i in wm.optics_diagnosis_cache]
bpy.ops.optics.propose_corrections()
# a Diagnose record carries no suggested fix; a proposal does, so an overwrite is visible here
check('Propose Corrections keeps the Diagnose list',
      diagnosed and [i.issue for i in wm.optics_diagnosis_cache] == diagnosed
      and not any(i.suggested_fix for i in wm.optics_diagnosis_cache), str(diagnosed))
corrections = [i.suggested_fix for i in getattr(wm, 'optics_correction_cache', ())]
check('Propose Corrections fills its own list', corrections and all(corrections), str(corrections))
bpy.ops.optics.diagnose()
check('Diagnose keeps the Corrections list',
      corrections and [i.suggested_fix for i in getattr(wm, 'optics_correction_cache', ())] == corrections)
tilted.select_set(True)
bpy.context.view_layer.update()
check('selecting an object leaves both lists current',
      wm.optics_diagnosis_revision == wm.optics_scene_revision
      and getattr(wm, 'optics_correction_revision', -2) == wm.optics_scene_revision)
check('Fix is available after selecting an object', bpy.ops.optics.fix_diagnosis.poll())
tilted.rotation_euler.z += 0.01
bpy.context.view_layer.update()
check('moving an optic marks both lists out of date',
      wm.optics_diagnosis_revision != wm.optics_scene_revision
      and getattr(wm, 'optics_correction_revision', wm.optics_scene_revision) != wm.optics_scene_revision)

# set_dof: the API/MCP way to turn one knob, by value or by its own step.
clear()
eg.source('TS', (-80, 0, 0), (1, 0, 0))
turned = eg.mirror('T', (0, 0, 0), (1, 0, 0), (0, 1, 0))
api.set_mount('T', 'KM100')
bpy.context.view_layer.update()
set_dof = getattr(api, 'set_dof', None)
check('optics_api exposes set_dof', callable(set_dof))
if callable(set_dof):
    tip_i, tip_d = next((i, d) for i, d in enumerate(turned.optics.dofs) if d.kind == 'TIP')
    pose0 = turned.matrix_world.copy()
    r = set_dof('T', 'tip', value=0.4)
    check('set_dof sets a knob by kind', r.get('ok') and abs(tip_d.current - 0.4) < 1e-6 and r.get('clamped') is False,
          str(r))
    check('set_dof moves the mount', max(abs(turned.matrix_world[i][j] - pose0[i][j])
                                         for i in range(3) for j in range(3)) > 1e-4)
    check('set_dof re-traces', r.get('segments', 0) > 0 and tracer.cached_segments, str(r))
    tip_d.step = 0.25
    r = set_dof('T', tip_i, steps=-2)
    check('set_dof steps by the knob step, by index', r.get('ok') and abs(tip_d.current - (-0.1)) < 1e-6, str(r))
    r = set_dof('T', 'TIP', value=tip_d.max_val + 10.0)
    check('set_dof clamps to the range and says so',
          r.get('ok') and r.get('clamped') is True and abs(tip_d.current - tip_d.max_val) < 1e-6, str(r))
    check('set_dof rejects an unknown kind', 'error' in set_dof('T', 'WOBBLE', value=1.0))
    check('set_dof rejects an index out of range', 'error' in set_dof('T', 99, value=1.0))
    check('set_dof needs exactly one of value / steps',
          'error' in set_dof('T', 'TIP') and 'error' in set_dof('T', 'TIP', value=1.0, steps=1))
    check('set_dof rejects a non-finite value', 'error' in set_dof('T', 'TIP', value=float('nan')))
    eg.detector('NoKnobs', (0, 90, 0), (0, 1, 0))
    r = set_dof('NoKnobs', 'TIP', value=0.0)
    check('set_dof rejects an element without knobs', 'error' in r and 'no adjustment' in r['error'], str(r))
    check('set_dof rejects an unknown element', 'error' in set_dof('nope', 'TIP', value=0.0))
    set_dof('T', 'TIP', value=0.0)
    bpy.context.view_layer.update()
    home = turned.matrix_world.translation.copy()
    turned.location.z += 5.0                               # moved by hand before the agent turns the knob
    bpy.context.view_layer.update()
    set_dof('T', 'TIP', value=0.7)
    set_dof('T', 'TIP', value=0.0)
    bpy.context.view_layer.update()
    check('a hand move survives set_dof', (turned.matrix_world.translation - home).length > 4.99
          and abs(turned.matrix_world.translation.z - (home.z + 5.0)) < 1e-4,
          str(tuple(turned.matrix_world.translation)))
    check('capabilities lists set_dof as a write', 'set_dof' in api.capabilities()['control_contract']['write'])

# Every optics operator is reachable from a panel, and no leaf panel is empty (P3).
import importlib, inspect, pkgutil
from optical_alignment_sim import optics_api as _api_for_reach
clear()
eg.source('RS', (-80, 0, 0), (1, 0, 0))
reach_obj = eg.mirror('RM', (0, 0, 0), (1, 0, 0), (0, 1, 0))
eg.detector('RD', (0, 80, 0), (0, 1, 0))
api.set_mount('RM', 'KM100')
reach_obj.optics.mech.add()
operators._store_corrections(bpy.context.window_manager, [dict(issue='x', element='RM', suggested_fix='f',
                                                               tool='align_element', severity='WARN')])
bpy.context.view_layer.update()
registered = set()
for module_info in pkgutil.iter_modules(oas.__path__):
    module = importlib.import_module("optical_alignment_sim." + module_info.name)
    for _n, cls in inspect.getmembers(module, inspect.isclass):
        if issubclass(cls, bpy.types.Operator) and getattr(cls, "bl_idname", "").startswith("optics."):
            registered.add(cls.bl_idname)
panels = [c for _n, c in inspect.getmembers(ui, inspect.isclass)
          if issubclass(c, bpy.types.Panel) and c.__module__ == ui.__name__]
parents = {getattr(c, "bl_parent_id", "") for c in panels}
drawn_ops, items = set(), {c.bl_idname: 0 for c in panels}
class ReachLayout:
    operator_context = 'INVOKE_DEFAULT'; use_property_split = False; use_property_decorate = False
    enabled = True; alert = False; active = True; scale_y = 1.0
    def __init__(self, pid): self.pid = pid
    def child(self, *a, **k): return ReachLayout(self.pid)
    column = row = box = grid_flow = split = column_flow = child
    def _item(self, *a, **k): items[self.pid] += 1
    prop = label = template_list = menu = prop_search = _item
    def operator(self, name, **k):
        drawn_ops.add(name); items[self.pid] += 1
        return SimpleNamespace()
    def separator(self, *a, **k): pass
for advanced in (False, True):
    ui._advanced_enabled = (lambda a=advanced: a)
    for et, *_ in properties.ELEMENT_TYPES:
        if et == 'NONE':
            continue
        reach_obj.optics.element_type = et
        ctx = SimpleNamespace(object=reach_obj, active_object=reach_obj, selected_objects=[reach_obj],
                              scene=bpy.context.scene, window_manager=bpy.context.window_manager,
                              workspace=bpy.data.workspaces[0], preferences=bpy.context.preferences, region=None)
        for panel in panels:
            if hasattr(panel, "poll") and not panel.poll(ctx):
                continue
            inst = SimpleNamespace(layout=ReachLayout(panel.bl_idname),
                                   **{k: getattr(panel, k) for k in dir(panel) if k.startswith('_') and not k.startswith('__')})
            panel.draw(inst, ctx)
ui._advanced_enabled = original_advanced
reach_obj.optics.element_type = 'MIRROR'
IN_PREFERENCES = {'optics.apply_update', 'optics.install_update', 'optics.check_updates'}
unreachable = sorted(registered - drawn_ops - IN_PREFERENCES)
check('every optics operator is drawn in a panel', not unreachable, str(unreachable))
empty = sorted(pid for pid, n in items.items() if n == 0 and pid not in parents)
check('no leaf panel is empty', not empty, str(empty))
scene = bpy.context.scene
scene.optics.scene_units_authoritative = False
old_scale = scene.unit_settings.scale_length
scene.unit_settings.scale_length = 1.0                     # a metre-scale scene, off the add-on's mm convention
ui._advanced_enabled = lambda: False
try:
    fields = set()
    ui.OPTICS_PT_trace.draw(SimpleNamespace(layout=Layout(fields)), bpy.context)
    check('a metre-scale scene shows Convert Scene Units without Advanced',
          'optics.convert_scene_units' in fields, str(sorted(fields)))
finally:
    ui._advanced_enabled = original_advanced
    scene.unit_settings.scale_length = old_scale

# The new panel operators do what they say.
clear()
eg.source('GS', (-120, 0, 0), (1, 0, 0))
g1 = eg.lens('G1', (-40, 0, 0), (1, 0, 0))
g2 = eg.lens('G2', (40, 0, 0), (1, 0, 0))
bpy.context.view_layer.update()
for o in bpy.context.scene.objects:
    o.select_set(o.name in ('G1', 'G2'))
with bpy.context.temp_override(selected_objects=[g1, g2], object=g1, active_object=g1):
    result = bpy.ops.optics.make_support(kind='CAGE', cage_size='30')
check('Group Selected puts the selection on one cage',
      result == {'FINISHED'} and g1.optics.support_system == 'CAGE_30' and g2.optics.support_system == 'CAGE_30'
      and g1.optics.cage_id and g1.optics.cage_id == g2.optics.cage_id,
      str((result, g1.optics.support_system, g2.optics.support_system)))
with bpy.context.temp_override(selected_objects=[]):
    check('Group Selected needs a selection', not bpy.ops.optics.make_support.poll())
calls = []
original_sequence = api.render_sequence
api.render_sequence = lambda **kw: calls.append(kw) or {"frames": kw["frames"], "dir": "/tmp/x", "video": None}
try:
    result = bpy.ops.optics.render_sequence(frames=3, motion='HERO', engine='CYCLES', fps=12)
finally:
    api.render_sequence = original_sequence
check('Render Sequence passes its settings to render_sequence',
      result == {'FINISHED'} and calls and calls[0]['frames'] == 3 and calls[0]['motion'] == 'HERO'
      and calls[0]['engine'] == 'CYCLES' and calls[0]['fps'] == 12 and calls[0]['out_dir'] is None, str(calls))

failed = len(checks) - sum(checks)
print("AGENT CONTROL %s (%d/%d checks)" % ("PASS" if failed == 0 else "FAIL",
                                            sum(checks), len(checks)), flush=True)
sys.exit(failed)
