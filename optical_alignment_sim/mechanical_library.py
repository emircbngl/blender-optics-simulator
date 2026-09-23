"""Stage 05a-2: schema-v1 mechanical records for real parts, built from the vendor's own drawings.

Every value here is duplicated from docs/mechanics/product-evidence.json, because the add-on ships
without its docs. PROVENANCE maps each value to the inventory fact it came from, and
tests/test_support_assembly.py fails if any of them drift apart. Drawing sources carry the SHA-256 of
the file that was actually read; the files themselves are not in this repository.

What these records are NOT: validated fits. Every drawing is stamped FOR INFORMATION ONLY / NOT FOR
MANUFACTURING PURPOSES and states no tolerance, so each quantity is a nominal with `tolerance: None`,
and `evidence_level` stays `unverified`. Three values are derived rather than published, and say so in
PROVENANCE: the post holder's 12.7 mm minimum insertion (the thumbscrew's ball has to reach the post),
its 0.8 mm allowed gap (the vendor states Ø12 mm posts fit), and its 6.8 mm floor (length minus bore).

Frames follow schema v1: each part's origin is the centre of its bottom face with +Z up its axis, and
an interface frame's +Z is the OUTWARD normal -- so a post's foot points down and a bore's mouth up.
"""
from copy import deepcopy

from . import mechanical_catalog as _catalog
from .mechanical_interfaces import new_interface

DOWN = [0.0, 1.0, 0.0, 0.0]            # pi about X: the frame's +Z along the part's -Z
UP = [1.0, 0.0, 0.0, 0.0]
TOWARD_X = [0.7071067811865476, 0.0, 0.7071067811865476, 0.0]   # pi/2 about Y: +Z along +X

SOURCES = {
    'tr50m_drawing': dict(url='https://media.thorlabs.com/globalassets/items/t/tr/tr5/tr50_m/0331-e0w.pdf',
                          locator='Thorlabs drawing 0331, sheet 1', revision='J', checked_on='2026-09-22',
                          sha256='625b2c6d15603a1062b2415208305de63c2e150d171654d5049992ec0df1fdeb'),
    'ph50m_drawing': dict(url='https://media.thorlabs.com/globalassets/items/p/ph/ph5/ph50_m/23132-e0w.pdf',
                          locator='Thorlabs drawing 23132, sheet 1', revision='B', checked_on='2026-09-22',
                          sha256='a5bb3dfdda36ef2acf0111292cdeaf306ee70a13bc0ab490907ab40767d51b22'),
    'ts6hm_drawing': dict(url='https://media.thorlabs.com/globalassets/items/t/ts/ts6/ts6h_m/23136-e0w.pdf',
                          locator='Thorlabs drawing 23136, sheet 1', revision='B', checked_on='2026-09-23',
                          sha256='acfbcb98fb87d515a38d7d15efcfab16ae98ef14be11f95b79efc187c42a52c0'),
    'post_family': dict(url='https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1266',
                        locator='Optical Posts: metric and Ø12 mm sections', revision=None,
                        checked_on='2026-09-23', sha256=None),
    'rs2pm_product': dict(url='https://www.thorlabs.com/thorproduct.cfm?partnumber=RS2P/M',
                          locator='product title', revision=None, checked_on='2026-09-23', sha256=None),
    'mb4560m_drawing': dict(url='https://media.thorlabs.com/globalassets/items/m/mb/mb4/mb4560_m/6282-e0w.pdf',
                            locator='Thorlabs drawing 6282, sheet 1', revision='B', checked_on='2026-09-23',
                            sha256='c7cffde6a32966346b230c045122e7f7515655f5d005cbf5983af56eca1b507f'),
    'edu_speb2m_manual': dict(url='https://media.thorlabs.com/globalassets/items/e/ed/edu/edu-speb2/mtn021357-d02.pdf',
                              locator='MTN021357-D02 section 6.2 and the metric kit screw list',
                              revision='Rev A, July 22, 2020', checked_on='2026-09-23',
                              sha256='d2627eb6d83648f6c7d2de80fa54550f636cecf9149b1a01759aa09b582ddf6d'),
    # The thread hand. ISO 965-1 5.4: "When left hand threads are specified the letters LH shall be added
    # to the thread designation". No designation in this library carries LH, so each is right-handed --
    # and each record says so by citing both its own designation and this clause.
    'iso965_1': dict(url='https://cdn.standards.iteh.ai/samples/5393/bb7c10816efa4087b66e40d8375fb23b/ISO-965-1-1998.pdf',
                     locator='ISO 965-1:1998 5.4 (12.4 in the 2013 edition)', revision='1998',
                     checked_on='2026-09-23',
                     sha256='ebbde6db362d145114f804724b8e8f6a027edb21195648da3325addc4e18fa2e'),
}

# (part, path into the record, inventory fact id). A path is interface.dimension, interface.thread.field,
# interface.frame.z or motion.minimum/maximum. The test reads each value and compares it with the fact.
PROVENANCE = [
    ('TR50/M', 'shaft.diameter', 'tr50m_dwg_outer_diameter'),
    ('TR50/M', 'shaft.insertion_max', 'tr50m_dwg_length'),
    ('TR50/M', 'base_tap.depth', 'tr50m_dwg_base_thread_depth'),
    ('TR50/M', 'top_stud.engagement_min', 'tr50m_dwg_setscrew_protrusion_min'),
    ('TR50/M', 'top_stud.engagement_max', 'tr50m_dwg_setscrew_protrusion_max'),
    ('TR50/M', 'top_stud.frame.z', 'tr50m_dwg_length'),
    ('TR50/M-JP', 'shaft.diameter', 'tr_jp_outer_diameter'),
    ('TR50/M-JP', 'shaft.insertion_max', 'tr_jp_length'),
    ('RS2P/M', 'shaft.diameter', 'rs2pm_outer_diameter'),
    ('RS2P/M', 'shaft.insertion_max', 'rs2pm_length'),
    ('PH50/M', 'bore.diameter', 'ph50m_dwg_bore_diameter'),
    ('PH50/M', 'bore.insertion_max', 'ph50m_dwg_bore_depth'),
    ('PH50/M', 'bore.insertion_min', 'ph50m_min_insertion_lower_bound'),       # derived
    ('PH50/M', 'bore.clearance', 'ph_series_allowed_gap_lower_bound'),         # derived
    ('PH50/M', 'bore.frame.z', 'ph50m_dwg_length'),
    ('PH50/M', 'motion:height.minimum', 'ph50m_min_insertion_lower_bound'),    # derived
    ('PH50/M', 'motion:height.maximum', 'ph50m_dwg_bore_depth'),
    ('MB4560/M', 'tap.frame.z', 'mb4560m_dwg_size[2]'),
    ('M6x16 cap screw (EDU-SPEB2/M kit)', 'thread.engagement_max', 'kit_table_screw_length'),
]


def _q(value, evidence, unit='mm'):
    return {'value': value, 'unit': unit, 'evidence': list(evidence), 'tolerance': None,
            'model_error_limit': None}


def _frame(z, quaternion, evidence, x=0.0):
    return {'origin': [x, 0.0, z], 'unit': 'mm', 'quaternion_wxyz': list(quaternion), 'evidence': list(evidence)}


def _thread(standard, gender, major, pitch, evidence):
    # "M6 X 1.0" states the form, the nominal major diameter and the pitch in its own words. The hand is
    # right because the designation carries no LH (ISO 965-1 5.4), so the labels cite the standard too;
    # the numbers cite only the part's own document.
    return {'standard': standard, 'gender': gender, 'hand': 'right', 'form': 'M', 'fit_class': None,
            'major_diameter': _q(major, evidence), 'pitch': _q(pitch, evidence),
            'evidence': list(evidence) + ['iso965_1']}


def _interface(identifier, kind, frame, dimensions, evidence, thread=None):
    item = new_interface(identifier, kind)
    item.update(frame=frame, dimensions=dimensions, thread=thread, evidence=list(evidence))
    return item


def _record(definition_id, part_number, sources, interfaces, motions=(), revision=None):
    rec = _catalog.new_record(definition_id, manufacturer='Thorlabs', part_number=part_number,
                              variant='metric', revision=revision)
    rec['sources'] = {sid: dict(SOURCES[sid]) for sid in sources}
    rec['interfaces'] = list(interfaces)
    rec['motions'] = list(motions)
    rec['evidence_level'] = 'unverified'
    return rec


def _post(part_number, diameter, length, sid, extra=(), revision=None):
    shaft = _interface('shaft', 'shaft', _frame(0.0, DOWN, [sid]),
                       {'diameter': _q(diameter, [sid]), 'insertion_max': _q(length, [sid])}, [sid])
    sources = [sid] + (['iso965_1'] if extra else [])
    return _record('thorlabs:' + part_number, part_number, sources, [shaft] + list(extra), revision=revision)


def _tr50m():
    d = 'tr50m_drawing'
    base_tap = _interface('base_tap', 'thread', _frame(0.0, DOWN, [d]), {'depth': _q(8.6, [d])}, [d],
                          _thread('M6', 'internal', 6.0, 1.0, [d]))
    top_stud = _interface('top_stud', 'thread', _frame(50.0, UP, [d]),
                          {'engagement_min': _q(4.6, [d]), 'engagement_max': _q(5.2, [d])}, [d],
                          _thread('M4', 'external', 4.0, 0.7, [d]))
    return _post('TR50/M', 12.7, 50.0, d, (base_tap, top_stud), revision='J')


def _ph50m():
    d, t, f = 'ph50m_drawing', 'ts6hm_drawing', 'post_family'
    bore = _interface('bore', 'smooth_bore', _frame(50.0, UP, [d]), {
        'diameter': _q(12.8, [d]),
        # Derived, and conservative: the vendor states Ø12 mm posts fit, so at least 0.8 mm is allowed.
        # A wider gap is not claimed, so a thinner post is rejected rather than guessed at.
        'clearance': _q(0.8, [d, f]),
        # Derived: the TS6H/M ball bears at the thumbscrew axis, 12.7 mm below the top face.
        'insertion_min': _q(12.7, [d, t]),
        'insertion_max': _q(43.2, [d]),
    }, [d, t])
    bore['lock'] = {'kind': 'hex-locking thumbscrew (TS6H/M, 5 mm hex)', 'state': 'unlocked'}
    bore['access'] = {'tool': '5 mm hex key',
                      'approach_frame': _frame(50.0 - 12.7, TOWARD_X, [d, t], x=12.5 + 10.0)}
    base_tap = _interface('base_tap', 'thread', _frame(0.0, DOWN, [d]),
                          {'depth': _q(50.0 - 43.2, [d])}, [d],     # derived: the floor under the bore
                          _thread('M6', 'internal', 6.0, 1.0, [d]))
    height = {'id': 'height', 'interface_id': 'bore', 'kind': 'translation',
              'minimum': _q(12.7, [d, t]), 'maximum': _q(43.2, [d]), 'evidence': [d, t]}
    return _record('thorlabs:PH50/M', 'PH50/M', [d, t, f, 'iso965_1'], [bore, base_tap], [height], revision='B')


def _mb4560m():
    # One grid tap, the one 12.5 mm in from a corner. The board has 432 of them on a 25 mm pitch; a joint
    # takes one socket, and addressing the whole grid is not modelled yet. The origin is the centre of
    # the bottom face, so that tap sits at (-287.5, -212.5) on the 12.7 mm top face.
    d = 'mb4560m_drawing'
    tap = _interface('tap', 'thread', {'origin': [-287.5, -212.5, 12.7], 'unit': 'mm',
                                       'quaternion_wxyz': list(UP), 'evidence': [d]},
                     # The drawing gives no tap depth and no THRU: the depth is known to exist, not its value.
                     {'depth': _q(None, [])}, [d], _thread('M6', 'internal', 6.0, 1.0, [d]))
    return _record('thorlabs:MB4560/M', 'MB4560/M', [d, 'iso965_1'], [tap], revision='B')


def _kit_screw(length, locator_source='edu_speb2m_manual'):
    # The kit manual gives the size, not a catalogue part number, so the identity says only that much.
    # Its length under the head is an upper bound on engagement: what it actually engages is the length
    # minus what it clamps, which schema v1 cannot express (a three-part stack; schema v2).
    m = locator_source
    thread = _interface('thread', 'thread', _frame(0.0, DOWN, [m]),
                        {'engagement_max': _q(float(length), [m])}, [m], _thread('M6', 'external', 6.0, 1.0, [m]))
    rec = _catalog.new_record('thorlabs:edu-speb2m:M6x%d' % length, manufacturer='Thorlabs', part_number=None,
                              variant='M6 x %d mm socket head cap screw, supplied in EDU-SPEB2/M' % length,
                              revision=None)
    rec['sources'] = {sid: dict(SOURCES[sid]) for sid in (m, 'iso965_1')}
    rec['interfaces'] = [thread]
    rec['evidence_level'] = 'unverified'
    return rec


_BUILDERS = {
    'TR50/M': _tr50m,
    'TR50/M-JP': lambda: _post('TR50/M-JP', 12.0, 50.0, 'post_family'),
    'RS2P/M': lambda: _post('RS2P/M', 25.0, 50.0, 'rs2pm_product'),
    'PH50/M': _ph50m,
    'MB4560/M': _mb4560m,
    'M6x16 cap screw (EDU-SPEB2/M kit)': lambda: _kit_screw(16),
}


def parts():
    return sorted(_BUILDERS)


def record(part_number):
    """A fresh, validated record for one real part: a new instance_id every call, so two copies of the
    same product in one scene are two parts, never a duplicated record."""
    if part_number not in _BUILDERS:
        raise KeyError('no sourced record for %r; available: %s' % (part_number, ', '.join(parts())))
    return _catalog.validate(deepcopy(_BUILDERS[part_number]()))
