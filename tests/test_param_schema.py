"""The per-type parameter schema is complete and drawn.

1. Every property that changes an element's trace, a detector readout or the diagnostics is in that type's
   schema. Found by perturbation, not by reading the tracer: build the element in a source -> element ->
   detector bench, change one property, compare. Enum/bool values that matter are explored as contexts
   (a bandpass filter, a PPLN crystal with the solver on, ...) three levels deep.
2. Every schema field that matters for the current settings is drawn with Advanced off, in the Element
   panel or its More child panel.
3. Witnesses for fields the panel used to offer without effect, or never offered.

Run: blender --background --factory-startup --python-exit-code 1 --python tests/test_param_schema.py
"""
import os
import sys
from types import SimpleNamespace

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import optical_alignment_sim as oas
oas.register()
from optical_alignment_sim import (properties, tracer, alignment, diagnostics, ui, param_schema,
                                   optics_api as api, elements_generic as eg)

checks = []


def check(name, condition, detail=""):
    ok = bool(condition)
    checks.append(ok)
    print("  %-72s %s%s" % (name, "PASS" if ok else "FAIL", (" <- " + detail) if not ok else ""), flush=True)


RNA = properties.OpticalElementProps.bl_rna.properties
TYPES = [t for t, *_ in properties.ELEMENT_TYPES if t != 'NONE']
# outputs, bookkeeping and mount/placement state: not element parameters
NOT_PARAMS = {"rna_type", "name", "is_optical", "element_type", "align_state", "align_detail", "wf_rms",
              "mech_state", "ports_index", "dofs_index", "part_key", "mount_preset", "anchor", "cage_id",
              "tube_id", "rail_id", "rail_family", "mount_type", "support_system", "prism_parity"}
NOT_PARAM_PREFIX = ("meas_", "misalign_", "base_pose", "composed_")
TERMINAL = ('DETECTOR', 'PHOTODIODE', 'POWER_METER', 'WAVEFRONT_SENSOR', 'BEAM_DUMP')
REFLECTIVE = ('MIRROR', 'PRISM_MIRROR', 'DICHROIC', 'GRATING', 'RETROREFLECTOR', 'DEFORMABLE_MIRROR')


def perturbable():
    out = []
    for p in RNA:
        n = p.identifier
        if n in NOT_PARAMS or n.startswith(NOT_PARAM_PREFIX) or p.is_readonly or getattr(p, "array_length", 0):
            continue
        if p.type in ('FLOAT', 'INT', 'BOOLEAN') or (p.type == 'ENUM' and not p.is_enum_flag):
            out.append(p)
    return out


PROPS = perturbable()


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    tracer.cached_segments = []


def build(t):
    clear()
    X = (1, 0, 0)
    if t in ('SOURCE', 'FIBER_COLLIMATOR'):
        e = eg.source('E', (0, 0, 0), X)
    else:
        eg.source('S', (-80, 0, 0), X)
        builders = {'BEAMSPLITTER': lambda: eg.beamsplitter('E', (0, 0, 0), X, (0, 1, 0)),
                    'LENS': lambda: eg.lens('E', (0, 0, 0), X), 'WAVEPLATE': lambda: eg.waveplate('E', (0, 0, 0), X),
                    'POLARIZER': lambda: eg.polarizer('E', (0, 0, 0), X),
                    'APERTURE': lambda: eg.aperture('E', (0, 0, 0), X),
                    'FILTER': lambda: eg.optical_filter('E', (0, 0, 0), X),
                    'CRYSTAL': lambda: eg.crystal('E', (0, 0, 0), X),
                    'OBJECTIVE': lambda: eg.objective('E', (0, 0, 0), X), 'AOM': lambda: eg.aom('E', (0, 0, 0), X),
                    'PRISM': lambda: eg.prism('E', (0, 0, 0), X)}
        if t in TERMINAL:
            e = eg.detector('E', (0, 0, 0), X)
        elif t in REFLECTIVE:
            e = eg.mirror('E', (0, 0, 0), X, (0, 1, 0))
        elif t in builders:
            e = builders[t]()
        else:
            e = eg._inline('E', (0, 0, 0), X, None, t, 'wp')
    e.optics.element_type = t
    if t not in TERMINAL:
        eg.detector('D1', (80, 0, 0), X)
        eg.detector('D2', (0, 80, 0), (0, 1, 0))
    bpy.context.view_layer.update()
    return e


def fingerprint(scene):
    segs = tracer.trace_scene(scene, max_segments=64, max_depth=12)
    tracer.cached_segments = segs
    try:
        alignment.refresh_report(scene)
    except Exception:
        pass
    fp = [(s.get("from"), s.get("to"), s.get("kind"), round(s.get("power", 0), 5), round(s.get("wavelength", 0), 4),
           tuple(round(c, 3) for c in s["p1"]), tuple(round(c, 3) for c in s["p2"]),
           tuple(round(c, 4) for c in (s.get("jones") or ())), round(s.get("opl", 0), 4)) for s in segs]
    fp += [(o.name, round(o.optics.meas_power, 5), o.optics.meas_text) for o in scene.objects if o.optics.is_optical]
    try:
        fp.append(tuple((d.get("kind"), d.get("element"), d.get("detail")) for d in diagnostics.run_diagnostics(scene)))
    except Exception as exc:
        fp.append(("diagnostics error", str(exc)))
    return fp


def alternatives(p, cur):
    if p.type == 'BOOLEAN':
        return [not cur]
    if p.type == 'ENUM':
        return [i.identifier for i in p.enum_items if i.identifier != cur]
    cands = [cur + 1, cur - 1] if p.type == 'INT' else [cur * 1.37 + 0.23, cur * 0.61 - 0.11]
    return [v for v in cands if p.hard_min <= v <= p.hard_max][:1]


def inputs(e, scene, base):
    found = set()
    for p in PROPS:
        n, cur = p.identifier, getattr(e.optics, p.identifier)
        for v in alternatives(p, cur):
            try:
                setattr(e.optics, n, v)
                bpy.context.view_layer.update()
                if fingerprint(scene) != base:
                    found.add(n)
            except (TypeError, ValueError):
                pass
            finally:
                setattr(e.optics, n, cur)
                bpy.context.view_layer.update()
            if n in found:
                break
    return found


def all_inputs(e, scene):
    direct = inputs(e, scene, fingerprint(scene))
    found = set(direct)

    def explore(known, depth):
        if depth >= 3:
            return
        for n in sorted(known):
            p = RNA[n]
            if p.type not in ('ENUM', 'BOOLEAN'):
                continue
            cur = getattr(e.optics, n)
            for v in alternatives(p, cur):
                setattr(e.optics, n, v)
                bpy.context.view_layer.update()
                extra = inputs(e, scene, fingerprint(scene)) - known - {n}
                found.update(extra)
                if extra:
                    explore(extra | known, depth + 1)
                setattr(e.optics, n, cur)
                bpy.context.view_layer.update()

    explore(direct, 1)
    return found


print("[every property that changes a type's result is in its schema]")
for t in TYPES:
    e = build(t)
    missing = sorted(all_inputs(e, bpy.context.scene) - set(param_schema.names(t)))
    check("%s: schema holds every input" % t, not missing, str(missing))


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


def drawn(obj):
    fields = set()
    ctx = SimpleNamespace(object=obj)
    ui.OPTICS_PT_element.draw(SimpleNamespace(layout=Layout(fields)), ctx)
    if ui.OPTICS_PT_element_more.poll(ctx):
        ui.OPTICS_PT_element_more.draw(SimpleNamespace(layout=Layout(fields)), ctx)
    return fields


print("[every field that matters now is drawn with Advanced off]")
original_advanced = ui._advanced_enabled
ui._advanced_enabled = lambda: False
try:
    obj = build('SOURCE')
    for t in TYPES:
        obj.optics.element_type = t
        contexts = [None]
        for n, _cond in param_schema.fields(t, "essentials") + param_schema.fields(t, "more"):
            p = RNA[n]
            if p.type in ('ENUM', 'BOOLEAN'):
                contexts += [(n, v) for v in alternatives(p, getattr(obj.optics, n))]
        missing = set()
        for ctx in contexts:
            if ctx:
                old = getattr(obj.optics, ctx[0])
                setattr(obj.optics, ctx[0], ctx[1])
            missing |= set(param_schema.current(obj.optics)) - drawn(obj)
            if ctx:
                setattr(obj.optics, ctx[0], old)
        check("%s: every current field is drawn" % t, not missing, str(sorted(missing)))
finally:
    ui._advanced_enabled = original_advanced

print("[fields the panel offered without effect, or never offered]")
ui._advanced_enabled = lambda: False
try:
    f = build('FILTER')
    f.optics.filt_type = 'BP'
    fields = drawn(f)
    check("bandpass filter offers its centre and width", {"cwl_nm", "fwhm_nm"} <= fields, str(sorted(fields)))
    check("bandpass filter does not offer the edge cuts it ignores", not ({"cut_lo_nm", "cut_hi_nm"} & fields))
    f.optics.filt_type = 'CGLASS_BP'
    fields = drawn(f)
    check("colored-glass bandpass offers both cuts, thickness and reference thickness",
          {"cut_lo_nm", "cut_hi_nm", "thickness_mm", "d_ref_mm"} <= fields and "od" not in fields, str(sorted(fields)))
    fields = drawn(build('OBJECTIVE'))
    check("objective NA and working distance are not offered as editable fields",
          not ({"obj_na", "obj_wd", "obj_long_wd"} & fields), str(sorted(fields)))
    check("detector material and gain are offered without Advanced",
          {"det_material", "det_gain"} <= drawn(build('DETECTOR')))
    check("lens glass is offered without Advanced", "lens_glass" in drawn(build('LENS')))
    check("prism glass is offered", "prism_glass" in drawn(build('PRISM')))
finally:
    ui._advanced_enabled = original_advanced

print("[the API reads the same schema]")
clear()
eg.source('S', (-80, 0, 0), (1, 0, 0))
eg._inline('I', (0, 0, 0), (1, 0, 0), None, 'ISOLATOR', 'wp')
bpy.context.view_layer.update()
state = {e['name']: e for e in api.get_state()['elements']}
check("editable_params come from the schema", state['I']['editable_params'] == param_schema.names('ISOLATOR'))
check("an isolator no longer lists isolation_db, which it does not read",
      'isolation_db' not in state['I']['editable_params'])
build('MIRROR')
params = api.inspect_element('E').get('params', {})
check("inspect_element reports only fields that matter now (no source fields on a mirror)",
      'wavelength' not in params and 'reflectivity' in params, str(params))

failed = len(checks) - sum(checks)
print("PARAM SCHEMA %s (%d/%d checks)" % ("PASS" if failed == 0 else "FAIL", sum(checks), len(checks)), flush=True)
sys.exit(failed)
