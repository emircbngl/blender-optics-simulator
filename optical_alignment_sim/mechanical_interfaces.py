"""Version-1 mechanical interface values. Pure Python; never infer compatibility."""
from copy import deepcopy
import math


class SchemaError(ValueError):
    """Invalid or unsupported mechanical data; callers must preserve the old record."""


def require(ok, message):
    if not ok:
        raise SchemaError(message)


def fields(value, keys, path):
    require(isinstance(value, dict) and set(value) == set(keys.split()), path + ': wrong fields')


def number(value, path):
    require(type(value) in (int, float) and math.isfinite(value), path + ': expected finite number')


def refs(value, sources, path):
    require(isinstance(value, list) and all(isinstance(s, str) and s in sources for s in value),
            path + ': dangling source reference')


def text(value, path, nullable=False):
    require((value is None and nullable) or (isinstance(value, str) and bool(value.strip())),
            path + ': expected nonempty text')


UNITS = {'mm': ('length', 1.0), 'in': ('length', 25.4),
         'deg': ('angle', 1.0), 'rad': ('angle', 180.0 / math.pi)}


def quantity(value=None, unit='mm', evidence=None):
    return dict(value=value, unit=unit, evidence=list(evidence or []),
                tolerance=None, model_error_limit=None)


def validate_quantity(q, sources, dimension='length', positive=False):
    fields(q, 'value unit evidence tolerance model_error_limit', 'quantity')
    require(q['unit'] in UNITS and UNITS[q['unit']][0] == dimension, 'quantity: incompatible unit')
    refs(q['evidence'], sources, 'quantity.evidence')
    if q['value'] is not None:
        number(q['value'], 'quantity.value')
        require(not positive or q['value'] > 0, 'quantity: must be positive')
        require(bool(q['evidence']), 'known quantity needs evidence')
    if q['tolerance'] is not None:
        fields(q['tolerance'], 'minus plus evidence', 'tolerance')
        refs(q['tolerance']['evidence'], sources, 'tolerance.evidence')
        require(q['value'] is not None and bool(q['tolerance']['evidence']), 'tolerance needs value and evidence')
        for k in ('minus', 'plus'):
            number(q['tolerance'][k], 'tolerance.' + k)
            require(q['tolerance'][k] >= 0, 'negative tolerance')
    if q['model_error_limit'] is not None:
        number(q['model_error_limit'], 'model_error_limit')
        require(q['value'] is not None and q['model_error_limit'] >= 0, 'invalid model error limit')


def normalize_quantity(q, dimension='length'):
    """Return canonical mm/deg copy, including tolerance; source input stays unchanged."""
    # Standalone conversion still validates the shape and values, but not source existence.
    validate_quantity(q, {s: None for s in q.get('evidence', []) +
                          (q.get('tolerance') or {}).get('evidence', [])}, dimension)
    result = deepcopy(q)
    factor = UNITS[q['unit']][1]
    result['unit'] = 'mm' if dimension == 'length' else 'deg'
    if result['value'] is not None:
        result['value'] *= factor
    if result['tolerance'] is not None:
        for key in ('minus', 'plus'):
            result['tolerance'][key] *= factor
    if result['model_error_limit'] is not None:
        result['model_error_limit'] *= factor
    return result


def validate_frame(frame, sources):
    if frame is None:
        return  # unknown datum, not the identity frame
    fields(frame, 'origin unit quaternion_wxyz evidence', 'frame')
    require(frame['unit'] in ('mm', 'in'), 'frame: expected length unit')
    refs(frame['evidence'], sources, 'frame.evidence')
    require(bool(frame['evidence']), 'frame needs datum evidence')
    for key, size in (('origin', 3), ('quaternion_wxyz', 4)):
        require(isinstance(frame[key], list) and len(frame[key]) == size, 'invalid frame vector')
        for n in frame[key]:
            number(n, key)
    require(abs(sum(n*n for n in frame['quaternion_wxyz']) - 1.0) < 1e-6,
            'frame quaternion must be unit length')


DIMENSIONS = {'diameter', 'depth', 'engagement_min', 'engagement_max', 'seat_depth',
              'optic_thickness_min', 'optic_thickness_max', 'rod_spacing', 'clearance',
              'tool_clearance', 'insertion_min', 'insertion_max'}
KINDS = {'thread', 'smooth_bore', 'shaft', 'plane', 'hole_pattern', 'dovetail', 'clamp', 'optic_seat'}


def new_interface(identifier, kind):
    return dict(id=identifier, kind=kind, frame=None, thread=None, dimensions={}, holes=[],
                mating_direction=None, access=dict(tool=None, approach_frame=None),
                lock=dict(kind=None, state=None), evidence=[])


def validate_interface(item, sources):
    fields(item, 'id kind frame thread dimensions holes mating_direction access lock evidence', 'interface')
    text(item['id'], 'interface.id')
    require(item['kind'] in KINDS, 'unknown interface kind')
    refs(item['evidence'], sources, 'interface.evidence')
    validate_frame(item['frame'], sources)
    require(item['mating_direction'] in (None, '+Z', '-Z', 'either'), 'invalid insertion direction')
    require(isinstance(item['dimensions'], dict) and set(item['dimensions']) <= DIMENSIONS,
            'unknown dimension')
    for q in item['dimensions'].values():
        validate_quantity(q, sources)
        require(q['value'] is None or q['value'] >= 0, 'negative mechanical dimension')
    for lo, hi in (('engagement_min', 'engagement_max'), ('optic_thickness_min', 'optic_thickness_max'),
                   ('insertion_min', 'insertion_max')):
        a, b = item['dimensions'].get(lo), item['dimensions'].get(hi)
        if a and b and a['value'] is not None and b['value'] is not None:
            require(normalize_quantity(a)['value'] <= normalize_quantity(b)['value'], 'reversed dimension range')
    require(isinstance(item['holes'], list), 'holes must be a list')
    for h in item['holes']:
        fields(h, 'frame diameter depth', 'hole')
        validate_frame(h['frame'], sources)
        validate_quantity(h['diameter'], sources, positive=True)
        validate_quantity(h['depth'], sources, positive=True)
    t = item['thread']
    require(t is None or item['kind'] == 'thread', 'thread metadata on non-thread interface')
    if t is not None:
        fields(t, 'standard gender hand form fit_class major_diameter pitch evidence', 'thread')
        for key in ('standard', 'form', 'fit_class'):
            text(t[key], 'thread.' + key, nullable=True)
        require(t['gender'] in (None, 'internal', 'external'), 'invalid thread gender')
        require(t['hand'] in (None, 'right', 'left'), 'invalid thread hand')
        refs(t['evidence'], sources, 'thread.evidence')
        require(all(t[k] is None for k in ('standard','gender','hand','form','fit_class')) or bool(t['evidence']),
                'known thread labels need evidence')
        validate_quantity(t['major_diameter'], sources, positive=True)
        validate_quantity(t['pitch'], sources, positive=True)
    fields(item['access'], 'tool approach_frame', 'access')
    text(item['access']['tool'], 'access.tool', nullable=True)
    validate_frame(item['access']['approach_frame'], sources)
    fields(item['lock'], 'kind state', 'lock')
    text(item['lock']['kind'], 'lock.kind', nullable=True)
    require(item['lock']['state'] in (None, 'unlocked', 'locked'), 'invalid lock state')
