"""Behavioral witnesses from the September review; run inside Blender."""
import os
import sys
from unittest.mock import patch
import bpy
from mathutils import Vector
sys.path.insert(0, os.environ.get('OAS_REVIEW_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import handlers, tracer, alignment, operators, elements_generic as eg
checks = []
def check(name, ok, detail=''):
    checks.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + ': ' + str(detail), flush=True)
scene = bpy.context.scene
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
scene.optics.live_enabled = True
handlers._pending_scene = scene
handlers._last_sig = None
scene.render.use_lock_interface = False
with patch.object(handlers, '_is_background', return_value=False), patch.object(tracer, 'trace_scene', return_value=[]), patch.object(alignment, 'refresh_report') as refresh:
    handlers.on_render_init(scene)
    handlers._deferred_trace()
    check('queued live trace cannot refresh report during unlocked render', refresh.call_count == 0, refresh.call_count)
    handlers.on_render_done(scene)
    handlers._deferred_trace()
    check('the held live trace refreshes the report once the render is done', refresh.call_count == 1, refresh.call_count)
scene.optics.live_enabled = False
# Store an actual RNA enum selection, then alter the items callback's ordering.
ann = operators.OPTICS_OT_tolerance_scan.__annotations__['target']
if isinstance(ann, str):
    ann = eval(ann, vars(operators))
class ReviewTarget(bpy.types.PropertyGroup):
    __annotations__ = {'target': ann}
bpy.utils.register_class(ReviewTarget)
bpy.types.Scene.review_target = bpy.props.PointerProperty(type=ReviewTarget)
b = eg.detector('B_detector', (100, 0, 0), (1, 0, 0))
scene.review_target.target = 'B_detector'
a = eg.detector('A_detector', (120, 0, 0), (1, 0, 0))
check('adding earlier detector preserves target', scene.review_target.target == 'B_detector', scene.review_target.target)
bpy.data.objects.remove(a, do_unlink=True)
check('removing another detector preserves target', scene.review_target.target == 'B_detector', scene.review_target.target)
# The selected detector itself renamed, then deleted: the target must not silently become another detector.
a = eg.detector('A_detector', (120, 0, 0), (1, 0, 0))
b.name = 'C_detector'
bpy.context.view_layer.update()
check('renaming the selected detector does not retarget another detector',
      scene.review_target.target != 'A_detector', scene.review_target.target)
bpy.data.objects.remove(b, do_unlink=True)
bpy.context.view_layer.update()
check('deleting the selected detector does not retarget another detector',
      scene.review_target.target != 'A_detector', scene.review_target.target)
from optical_alignment_sim import optics_api
_lost = optics_api.tolerance_scan(['A_detector'], target=scene.review_target.target, n=2)
check('a scan on the lost target says the target is missing instead of measuring elsewhere',
      scene.review_target.target == '' and "give a 'target'" in _lost.get('error', ''),
      (scene.review_target.target, _lost.get('error')))
del bpy.types.Scene.review_target
bpy.utils.unregister_class(ReviewTarget)
r = tracer._Ray(Vector((0, 0, 0)), Vector((1, 0, 0)), 1., 0, None, 1064., 'TRANSMIT', -1,
                jones=(1+0j, 0j), aberr=[0., .125, -.25], unpol=True, ghost_depth=2)
out = tracer._prism_exit_ray(r, b, Vector((1, 0, 0)), Vector((1, 0, 0)), 2., .9, 0)
check('prism exit preserves aberration', out.aberr == r.aberr, out.aberr)
check('prism exit preserves unpolarized ensemble flag', out.unpol, out.unpol)
check('prism exit preserves ghost recursion depth', out.ghost_depth == 2, out.ghost_depth)
# Exercise entry, internal folds/cemented faces, and exit, not only the helper.
for prism_type in ('EQUILATERAL', 'LITTROW', 'PELLIN_BROCA', 'AMICI', 'RIGHT_ANGLE', 'PENTA', 'DOVE', 'ROOF', 'RHOMBOID', 'PORRO'):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    source = eg.source('S', (-120, 0, 0), (1, 0, 0))
    source.optics.pol_type = 'UNPOL'
    aberrator = eg._inline('A', (-60, 0, 0), (1, 0, 0), None, 'ABERRATOR', 'wp')
    aberrator.optics.aberr_spec[3] = .125
    eg.prism('P', (0, 0, 0), (1, 0, 0), prism_type=prism_type, apex_deg=30.0 if prism_type == 'LITTROW' else 60.0)
    bpy.context.view_layer.update()
    exits = []
    original_exit = tracer._prism_exit_ray
    def capture(*args):
        result = original_exit(*args)
        exits.append(result)
        return result
    with patch.object(tracer, '_prism_exit_ray', side_effect=capture):
        tracer.trace_scene(scene)
    check(prism_type + ' full trace retains ensemble and aberration',
          len(exits) == 2 and all(r.unpol and r.aberr and abs(r.aberr[3]-.125) < 1e-6 for r in exits),
          [(r.unpol, r.aberr) for r in exits])
# Observable consequence: the same unpolarized beam through a prism and Type-II
# crystal must not acquire crystal-roll sensitivity under this ensemble model.
from mathutils import Matrix
import math
source.optics.wavelength = 1064.
crystal = eg.crystal('C', exits[0].p1 + exits[0].dir * 50., exits[0].dir,
                     nl_process='SHG', phase_matching_type='TYPE2')
base = crystal.matrix_world.copy()
powers = []
for degrees in (0., 45., 90.):
    crystal.matrix_world = base @ Matrix.Rotation(math.radians(degrees), 4, 'Z')
    bpy.context.view_layer.update()
    segments = tracer.trace_scene(scene)
    powers.append(sum(s['power'] for s in segments if s['from'] == 'C' and s['wavelength'] < 600))
check('prism then Type-II conversion is nonzero and roll invariant',
      min(powers) > 0 and max(powers)-min(powers) < 1e-4, powers)
print('REVIEW REGRESSION %s (%d/%d checks)' % ('PASS' if all(checks) else 'FAIL', sum(checks), len(checks)), flush=True)
if not all(checks):
    raise AssertionError('review witnesses failed')
