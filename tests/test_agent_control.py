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
operators._store_diagnosis(bpy.context.window_manager, [dict(issue='crossed_polarizer',
    element='D', suggested_fix='Adjust the analyzer', tool='set_param', severity='WARN')])
old_analyzer = bpy.data.objects['D'].optics.analyzer
result = bpy.ops.optics.fix_diagnosis(index=0)
check('manual correction selects its element without changing optical settings',
      result == {'FINISHED'} and bpy.context.object.name == 'D'
      and bpy.context.object.optics.analyzer == old_analyzer)

failed = len(checks) - sum(checks)
print("AGENT CONTROL %s (%d/%d checks)" % ("PASS" if failed == 0 else "FAIL",
                                            sum(checks), len(checks)), flush=True)
sys.exit(failed)
