"""Stage 03: decide whether two mechanical interfaces actually mate.

The rule of this module is that a missing value is never a pass. Every rule states which quantities it
used and which source ids backed them; a rule that had to read a `None` returns `unknown` and names the
field, and a verdict of `compatible` requires at least one piece of evidence. Visual overlap, a shared
family name or two equal diameters are not compatibility.

Verdicts: `compatible`, `incompatible`, `unknown`, `adapter_required`. Pure Python, no bpy: the API layer
reads the records off objects and passes them in.
"""
from .mechanical_interfaces import SchemaError, normalize_quantity

VERDICTS = ('compatible', 'incompatible', 'unknown', 'adapter_required')

# Values are stated in decimals and stored in binary floating point, so a difference of two stated
# values can miss an equally stated limit by round-off alone: 12.8 - 12.0 is 0.8000000000000007. This
# absorbs representation error only. It is a billionth of a millimetre, not a tolerance, and nothing
# physical is decided inside it.
REPRESENTATION_MM = 1e-9

# Which interface kinds can mate at all. A pair outside this table is not "incompatible" through a
# measurement -- it is a pairing the model has no rule for, so it is reported as unknown.
MATING_KINDS = {
    frozenset({'thread'}): 'thread',
    frozenset({'smooth_bore', 'shaft'}): 'bore_shaft',
    frozenset({'optic_seat'}): 'optic_seat',
    frozenset({'hole_pattern'}): 'hole_pattern',
    frozenset({'dovetail', 'clamp'}): 'dovetail_clamp',
    frozenset({'plane'}): 'plane',
}


def _q(interface, name):
    """(value_mm, evidence) of a dimension, or (None, []) when the part does not state it."""
    q = interface.get('dimensions', {}).get(name)
    if q is None:
        return None, []
    canonical = normalize_quantity(q)
    return canonical['value'], list(q.get('evidence') or [])


def _thread_value(interface, name):
    thread = interface.get('thread') or {}
    q = thread.get(name)
    if q is None:
        return None, []
    canonical = normalize_quantity(q)
    return canonical['value'], list(q.get('evidence') or [])


def _tolerance(interface, name):
    """How far two nominally equal dimensions may differ: the part's own declared model error limit.

    There is no default. Without a declared limit the values must match exactly, because inventing a
    tolerance is exactly the guess this stage exists to prevent.
    """
    q = interface.get('dimensions', {}).get(name) or {}
    return q.get('model_error_limit') or 0.0


class _Report:
    """Collects rule outcomes so the verdict is derived, never asserted."""

    def __init__(self):
        self.rules = []
        self.missing = []
        self.evidence = []

    def note(self, rule, result, detail, evidence=()):
        self.rules.append({'rule': rule, 'result': result, 'detail': detail, 'evidence': sorted(set(evidence))})
        for source in evidence:
            if source not in self.evidence:
                self.evidence.append(source)

    def unknown(self, rule, field, detail, evidence=()):
        if field not in self.missing:
            self.missing.append(field)
        self.note(rule, 'unknown', detail, evidence)

    def verdict(self):
        if any(r['result'] == 'incompatible' for r in self.rules):
            return 'incompatible'
        if self.missing or any(r['result'] == 'unknown' for r in self.rules):
            return 'unknown'
        if not self.rules or not self.evidence:
            # Nothing was actually measured, or nothing was sourced: that is not a pass.
            return 'unknown'
        return 'compatible'

    def result(self, pair_kind):
        return {'verdict': self.verdict(), 'pair_kind': pair_kind, 'rules': self.rules,
                'missing': list(self.missing), 'evidence': list(self.evidence)}


def _check_thread(a, b, report):
    """Two threads mate when they are the same thread, opposite genders, and the screw does not bottom."""
    ta, tb = a.get('thread') or {}, b.get('thread') or {}
    thread_evidence = list(ta.get('evidence') or []) + list(tb.get('evidence') or [])
    genders = {ta.get('gender'), tb.get('gender')}
    if None in genders:
        report.unknown('thread.gender', 'thread.gender', 'one side does not state internal/external')
    elif genders != {'internal', 'external'}:
        report.note('thread.gender', 'incompatible', 'both sides are %s' % ta.get('gender'), thread_evidence)
    else:
        report.note('thread.gender', 'compatible', 'internal to external', thread_evidence)

    for field in ('standard', 'hand', 'form'):
        va, vb = ta.get(field), tb.get(field)
        if va is None or vb is None:
            report.unknown('thread.' + field, 'thread.' + field, 'not stated on both sides')
        elif va != vb:
            report.note('thread.' + field, 'incompatible', '%s vs %s' % (va, vb), thread_evidence)
        else:
            report.note('thread.' + field, 'compatible', va, thread_evidence)

    for field in ('major_diameter', 'pitch'):
        va, ea = _thread_value(a, field)
        vb, eb = _thread_value(b, field)
        if va is None or vb is None:
            report.unknown('thread.' + field, 'thread.' + field, 'not stated on both sides', ea + eb)
            continue
        limit = max((ta.get(field) or {}).get('model_error_limit') or 0.0,
                    (tb.get(field) or {}).get('model_error_limit') or 0.0)
        if abs(va - vb) > limit:
            report.note('thread.' + field, 'incompatible', '%.4f mm vs %.4f mm' % (va, vb), ea + eb)
        else:
            report.note('thread.' + field, 'compatible', '%.4f mm' % va, ea + eb)

    # Bottoming: the male side's usable length against the female side's depth. A screw longer than the
    # hole is a real assembly failure (a flip mount's caution is exactly this), so it is checked, not assumed.
    male, female = (a, b) if ta.get('gender') == 'external' else (b, a)
    reach, e_reach = _q(male, 'engagement_max')
    if reach is None:
        reach, e_reach = _q(male, 'engagement_min')
    depth, e_depth = _q(female, 'depth')
    if reach is None or depth is None:
        report.unknown('thread.engagement', 'thread.engagement', 'screw reach or hole depth not stated',
                       e_reach + e_depth)
    elif reach > depth:
        report.note('thread.engagement', 'incompatible',
                    'screw reaches %.2f mm into a %.2f mm hole: it bottoms out' % (reach, depth),
                    e_reach + e_depth)
    else:
        report.note('thread.engagement', 'compatible',
                    '%.2f mm of reach in a %.2f mm hole' % (reach, depth), e_reach + e_depth)


def _check_bore_shaft(a, b, report):
    """A post in a holder: the shaft has to enter the bore, and the bore has to hold enough of it."""
    bore, shaft = (a, b) if a['kind'] == 'smooth_bore' else (b, a)
    bore_d, e_bore = _q(bore, 'diameter')
    shaft_d, e_shaft = _q(shaft, 'diameter')
    if bore_d is None or shaft_d is None:
        report.unknown('bore.diameter', 'diameter', 'bore or shaft diameter not stated', e_bore + e_shaft)
    elif shaft_d > bore_d + _tolerance(bore, 'diameter'):
        report.note('bore.diameter', 'incompatible',
                    'a %.2f mm shaft does not enter a %.2f mm bore' % (shaft_d, bore_d), e_bore + e_shaft)
    else:
        report.note('bore.diameter', 'compatible',
                    '%.2f mm shaft in a %.2f mm bore' % (shaft_d, bore_d), e_bore + e_shaft)
        # Entering the bore is not a fit. Without a stated clearance there is no basis to call a gap a
        # slip fit, and a gap wider than the stated one is a different standard wearing the same diameter.
        gap = bore_d - shaft_d
        allowed, e_clear = _q(bore, 'clearance')
        if allowed is None:
            report.unknown('bore.fit', 'clearance',
                           'the bore states no clearance, so a %.2f mm gap cannot be called a fit' % gap)
        elif gap > allowed + REPRESENTATION_MM:
            report.note('bore.fit', 'incompatible',
                        'a %.2f mm gap exceeds the %.2f mm clearance this bore allows' % (gap, allowed),
                        e_clear + e_bore + e_shaft)
        else:
            report.note('bore.fit', 'compatible',
                        '%.2f mm gap within the %.2f mm clearance' % (gap, allowed),
                        e_clear + e_bore + e_shaft)

    need, e_need = _q(bore, 'insertion_min')
    have, e_have = _q(shaft, 'insertion_max')
    if have is None:
        have, e_have = _q(shaft, 'engagement_max')
    if need is None or have is None:
        report.unknown('bore.insertion', 'insertion', 'required or available insertion depth not stated',
                       e_need + e_have)
    elif have < need:
        report.note('bore.insertion', 'incompatible',
                    'the holder needs %.2f mm of insertion; the post offers %.2f mm' % (need, have),
                    e_need + e_have)
    else:
        report.note('bore.insertion', 'compatible',
                    '%.2f mm available against %.2f mm required' % (have, need), e_need + e_have)


def _check_optic_seat(seat, optic_thickness_mm, report):
    lo, e_lo = _q(seat, 'optic_thickness_min')
    hi, e_hi = _q(seat, 'optic_thickness_max')
    if optic_thickness_mm is None:
        report.unknown('seat.optic_thickness', 'optic_thickness_mm', 'no optic thickness given to check')
        return
    if lo is None or hi is None:
        report.unknown('seat.optic_thickness', 'optic_thickness_min/max',
                       'the seat does not state the thickness it accepts', e_lo + e_hi)
        return
    if optic_thickness_mm < lo or optic_thickness_mm > hi:
        report.note('seat.optic_thickness', 'incompatible',
                    'a %.2f mm optic is outside the %.2f-%.2f mm the seat takes'
                    % (optic_thickness_mm, lo, hi), e_lo + e_hi)
    else:
        report.note('seat.optic_thickness', 'compatible',
                    '%.2f mm fits %.2f-%.2f mm' % (optic_thickness_mm, lo, hi), e_lo + e_hi)


def _check_hole_pattern(a, b, report):
    """Cage plates and rods: the pattern only mates when spacing and hole size agree."""
    for field in ('rod_spacing', 'diameter'):
        va, ea = _q(a, field)
        vb, eb = _q(b, field)
        if va is None or vb is None:
            report.unknown('pattern.' + field, field, 'not stated on both sides', ea + eb)
            continue
        limit = max(_tolerance(a, field), _tolerance(b, field))
        if abs(va - vb) > limit:
            report.note('pattern.' + field, 'incompatible', '%.2f mm vs %.2f mm' % (va, vb), ea + eb)
        else:
            report.note('pattern.' + field, 'compatible', '%.2f mm' % va, ea + eb)


def check_interfaces(a, b, *, optic_thickness_mm=None):
    """Compare two interface dicts (schema v1). Returns the verdict with its rules, evidence and gaps."""
    report = _Report()
    kinds = frozenset({a['kind'], b['kind']})
    pair_kind = MATING_KINDS.get(kinds)
    if pair_kind is None:
        report.unknown('pairing', 'pairing rule',
                       'no rule for %s against %s in schema v1' % (a['kind'], b['kind']))
        return report.result(None)
    if pair_kind == 'thread':
        _check_thread(a, b, report)
    elif pair_kind == 'bore_shaft':
        _check_bore_shaft(a, b, report)
    elif pair_kind == 'optic_seat':
        _check_optic_seat(a if a['kind'] == 'optic_seat' else b, optic_thickness_mm, report)
    elif pair_kind == 'hole_pattern':
        _check_hole_pattern(a, b, report)
    else:
        # dovetail/clamp and plane seating need a profile and a seating datum that schema v1 does not carry.
        report.unknown('pairing', pair_kind + ' geometry',
                       'schema v1 carries no profile for %s; the fit cannot be decided from the data' % pair_kind)
    return report.result(pair_kind)


def _interface(record, interface_id):
    for item in record.get('interfaces', []):
        if item['id'] == interface_id:
            return item
    raise SchemaError('no interface %r on %s' % (interface_id, record.get('definition_id')))


def _identity(record):
    identity = record.get('identity') or {}
    return {'definition_id': record.get('definition_id'), 'manufacturer': identity.get('manufacturer'),
            'part_number': identity.get('part_number'), 'variant': identity.get('variant')}


def _named(record):
    """An adapter must be a real, identified product before it can be recommended."""
    identity = record.get('identity') or {}
    return bool(identity.get('manufacturer')) and bool(identity.get('part_number'))


def find_adapters(a, b, adapters, *, max_chain=2, optic_thickness_mm=None):
    """Shortest chain of adapter records that joins interface `a` to interface `b`.

    Breadth-first over the supplied records, so the shortest chain wins. A record may appear once per
    chain, which is what stops the A->B->A cycles the stage asks about. Each hop must be a `compatible`
    verdict on its own; an `unknown` hop is not silently accepted.
    """
    if max_chain < 1 or not adapters:
        return []
    queue = [([], a)]
    while queue:
        chain, current = queue.pop(0)
        if len(chain) >= max_chain:
            continue
        for record in adapters:
            if any(step['record'] is record for step in chain):
                continue                                  # each adapter at most once: no cycles
            for entry in record.get('interfaces', []):
                if check_interfaces(current, entry, optic_thickness_mm=optic_thickness_mm)['verdict'] != 'compatible':
                    continue
                for exit_ in record.get('interfaces', []):
                    if exit_['id'] == entry['id']:
                        continue
                    step = {'record': record, 'entry': entry['id'], 'exit': exit_['id']}
                    if check_interfaces(exit_, b, optic_thickness_mm=optic_thickness_mm)['verdict'] == 'compatible':
                        return chain + [step]
                    queue.append((chain + [step], exit_))
    return []


def check(record_a, interface_a, record_b, interface_b, *, adapters=(), max_chain=2,
          optic_thickness_mm=None):
    """Full answer for one mating question, including an adapter route when the direct fit fails.

    `adapters` are whole mechanical records (schema v1). An adapter chain is only offered when every hop
    is compatible on its own evidence; an adapter without manufacturer and part number is reported, but
    the verdict says its identity is missing rather than pretending a part exists.
    """
    a, b = _interface(record_a, interface_a), _interface(record_b, interface_b)
    direct = check_interfaces(a, b, optic_thickness_mm=optic_thickness_mm)
    result = {'ok': True, 'verdict': direct['verdict'], 'direct': direct,
              'parts': {'a': dict(_identity(record_a), interface=interface_a),
                        'b': dict(_identity(record_b), interface=interface_b)},
              'adapter_chain': [], 'missing': list(direct['missing']), 'evidence': list(direct['evidence'])}
    if direct['verdict'] == 'compatible' or not adapters:
        return result
    chain = find_adapters(a, b, list(adapters), max_chain=max_chain, optic_thickness_mm=optic_thickness_mm)
    if not chain:
        return result
    result['adapter_chain'] = [{'part': _identity(step['record']), 'enters': step['entry'], 'leaves': step['exit']}
                               for step in chain]
    result['verdict'] = 'adapter_required'
    if any(not _named(step['record']) for step in chain):
        # The chain exists in the data, but recommending an unnamed product is the guess we refuse to make.
        result['missing'].append('adapter identity (manufacturer and part number)')
    return result
