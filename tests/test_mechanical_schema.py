"""Schema, atomic persistence, legacy scenes and optical isolation. Run inside Blender."""
import sys
import tempfile
from pathlib import Path
from copy import deepcopy
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import mechanical_catalog as C, mechanical_interfaces as I
from optical_alignment_sim import optics_api, scan

# A synthetic fixture, not published product evidence.
r = C.new_record('fixture:post:metric:r1', 'TEST FIXTURE', 'FAKE-POST', 'metric', 'R1')
r['sources']['fixture'] = dict(url='https://example.invalid/fixture', locator='synthetic fixture',
                               revision='R1', checked_on='2026-09-16', sha256=None)
i = I.new_interface('mechanical:top', 'thread')
i['frame'] = dict(origin=[0, 0, 1], unit='in', quaternion_wxyz=[1, 0, 0, 0], evidence=['fixture'])
i['thread'] = dict(standard='FIXTURE', gender='external', hand='right', form=None, fit_class=None,
                   major_diameter=I.quantity(.25, 'in', ['fixture']),
                   pitch=I.quantity(None, 'mm'), evidence=['fixture'])
i['dimensions']['engagement_max'] = I.quantity(.2, 'in', ['fixture'])
i['dimensions']['engagement_max']['tolerance'] = dict(minus=.01, plus=.02, evidence=['fixture'])
i['dimensions']['engagement_max']['model_error_limit'] = .001
r['interfaces'].append(i)
r['motions'].append(dict(id='travel', interface_id=i['id'], kind='translation',
                         minimum=I.quantity(0, 'in', ['fixture']),
                         maximum=I.quantity(1, 'in', ['fixture']), evidence=['fixture']))
assert C.loads(C.dumps(r)) == r
original = deepcopy(r)
n = C.normalized(r)
assert r == original
assert n['interfaces'][0]['frame']['origin'] == [0, 0, 25.4]
assert n['interfaces'][0]['thread']['major_diameter']['value'] == 6.35
q = n['interfaces'][0]['dimensions']['engagement_max']
assert abs(q['value'] - 5.08) < 1e-10
assert abs(q['tolerance']['plus'] - .508) < 1e-10
assert abs(q['model_error_limit'] - .0254) < 1e-10
assert n['interfaces'][0]['thread']['pitch']['value'] is None
assert n['motions'][0]['maximum']['value'] == 25.4
assert abs(I.normalize_quantity(I.quantity(3.141592653589793, 'rad', ['fixture']), 'angle')['value']-180) < 1e-9

rejected = 0
def reject(change):
    global rejected
    bad = deepcopy(r)
    change(bad)
    try:
        C.dumps(bad)
    except I.SchemaError:
        rejected += 1
    else:
        raise AssertionError('malformed fixture accepted')
reject(lambda x: x.update(schema_version=2))
reject(lambda x: x.update(schema_version=True))
reject(lambda x: x.update(evidence_level='assembly_verified'))
reject(lambda x: x.update(unrecognized=True))
reject(lambda x: x['interfaces'].append(deepcopy(x['interfaces'][0])))
reject(lambda x: x['interfaces'][0]['frame'].update(quaternion_wxyz=[0,0,0,0]))
reject(lambda x: x['interfaces'][0]['frame']['origin'].__setitem__(0, float('nan')))
reject(lambda x: x['interfaces'][0]['thread']['major_diameter'].update(unit='deg'))
reject(lambda x: x['interfaces'][0]['thread']['major_diameter'].update(value=-1))
reject(lambda x: x['interfaces'][0]['thread']['major_diameter'].update(evidence=['missing']))
reject(lambda x: x['interfaces'][0]['thread']['pitch'].update(value=.5))
reject(lambda x: x['motions'][0].update(interface_id='optical:top'))
reject(lambda x: x['motions'][0]['minimum'].update(value=2))
reject(lambda x: x['interfaces'][0].update(kind=[]))
reject(lambda x: x['interfaces'][0]['dimensions']['engagement_max']['tolerance'].update(minus=-1))
try:
    C.loads('{"schema_version":1,"schema_version":2}')
except I.SchemaError:
    rejected += 1
else:
    raise AssertionError('duplicate JSON key accepted')

optics_api.build_example('cage_system')
scene = bpy.context.scene
ob = bpy.data.objects['CG_CleanPol']
legacy = bpy.data.objects['CG_Collimate']
# A file saved with empty new property is a legacy unannotated scene: no migration on read/load.
pose = tuple(v for row in ob.matrix_world for v in row)
preset = ob.optics.mount_preset
trace_values = scan._trace(scene)
trace = repr(trace_values)
assert C.read_object(legacy) == dict(status='legacy_unmapped', record=None)
assert legacy.mechanics.record_json == ''
C.attach_object(ob, r)
raw = ob.mechanics.record_json
try:
    C.attach_object(ob, C.new_record('another'))
except I.SchemaError:
    pass
else:
    raise AssertionError('implicit replacement accepted')
bad = deepcopy(r); bad['schema_version'] = 99
try:
    C.attach_object(ob, bad, replace=True)
except I.SchemaError:
    pass
else:
    raise AssertionError('future record accepted')
assert ob.mechanics.record_json == raw
assert repr(scan._trace(scene)) == trace
assert tuple(v for row in ob.matrix_world for v in row) == pose
assert ob.optics.mount_preset == preset
assert optics_api.capabilities()['mechanical_assembly']['available'] is False
with tempfile.TemporaryDirectory(prefix='mechanical-schema-') as directory:
    path = str(Path(directory) / 'roundtrip.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    ob = bpy.data.objects['CG_CleanPol']
    assert C.read_object(ob)['record'] == r
    assert ob.mechanics.record_json == raw
    assert ob.optics.mount_preset == preset
    assert tuple(v for row in ob.matrix_world for v in row) == pose
    assert C.read_object(bpy.data.objects['CG_Collimate'])['status'] == 'legacy_unmapped'
    def trace_close(a, b, path='trace'):
        # Blender recomposes matrices on reload; use the existing optical suite's 1e-9 bound.
        if isinstance(a, float) and isinstance(b, float):
            assert abs(a-b) <= 1e-9 * max(1, abs(a), abs(b)), (path, a, b)
        elif isinstance(a, dict) and isinstance(b, dict):
            assert a.keys() == b.keys(), path
            for key in a:
                trace_close(a[key], b[key], path + '.' + str(key))
        elif isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
            assert len(a) == len(b), path
            for index, (x, y) in enumerate(zip(a,b)):
                trace_close(x,y,path + '[' + str(index) + ']')
        else:
            assert a == b, (path, a, b)
    trace_close(trace_values, scan._trace(bpy.context.scene))
    # Unknown future records remain byte-for-byte intact and are not downgraded on read.
    future = raw.replace('"schema_version":1', '"schema_version":99')
    ob.mechanics.record_json = future
    assert C.read_object(ob)['status'] == 'unreadable'
    assert ob.mechanics.record_json == future
    C.attach_object(ob, r, replace=True)
    assert C.read_object(ob)['record'] == r
addon.unregister()
assert not hasattr(bpy.types.Object, 'mechanics')
addon.register()
assert hasattr(bpy.types.Object, 'mechanics')
print(f'MECHANICAL SCHEMA PASS: {rejected} malformed cases; units/nulls; atomic writes; '
      'save/reload; legacy metadata; optical isolation; capability honesty; registration lifecycle')
