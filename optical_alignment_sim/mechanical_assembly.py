"""Stage 04a: the mechanical assembly graph, its states and the gates around them.

Two graphs live here and they are deliberately not the same object:

* the **physical graph** -- every joint between two mechanical interfaces. It may fork, it may bind
  one part at several points, and it may close a loop (four cage rods through two plates do exactly
  that). Loops are accepted, because the real hardware has them.
* the **transform-ownership forest** -- the subset of joints that carry a part's pose. It is a forest:
  one parent per part, no cycles. A joint that cannot carry (the part already has a parent, or the
  proposed parent is inside the part's own sub-assembly) is still recorded, as a physical-only joint.

A joint is a claim that two interfaces mate, so only a stage-03 `compatible` verdict may become one.
`adapter_required`, `unknown` and `incompatible` are refused with the reason, and nothing is written.
The four states follow bench practice -- ``aligned`` (held in place), ``seated`` (in its seat),
``fastened`` (screwed), ``locked`` (a declared lock engaged) -- and move one step at a time in either
direction, so the order is always explicit. A part comes off in the reverse order it went on.

This stage adds no geometry: nothing here moves, creates or measures anything. Placement from the
mating frames, sub-assembly propagation and loop pose consistency are stage 04b and are not claimed.
Pure Python, no bpy: the API layer reads the records and the stored graph and passes them in.
"""
import math

from .mechanical_interfaces import SchemaError, normalize_quantity

GRAPH_VERSION = 1

# Bench practice, in order. Forward: hold it, seat it, screw it, lock it. Backward: the reverse.
STATES = ('aligned', 'seated', 'fastened', 'locked')
_RANK = {state: index for index, state in enumerate(STATES)}

# Motions of an interface that a joint holds. `True` = the joint still leaves that interface's own
# declared motion free; `False` = the joint holds it and the motion has to be undone first.
_MOTION_FREE = {'aligned': True, 'seated': True, 'fastened': False, 'locked': False}

CARRIES = (None, 'a', 'b', 'none')


def new_graph():
    return {'schema_version': GRAPH_VERSION, 'joints': []}


def _require(ok, message):
    if not ok:
        raise SchemaError(message)


def _endpoint(value, path):
    _require(isinstance(value, dict), path + ' must be an object')
    _require(set(value) == {'instance_id', 'definition_id', 'object', 'interface'},
             path + ' has unexpected fields')
    for key in ('instance_id', 'interface'):
        _require(isinstance(value[key], str) and value[key], path + '.' + key + ' must be a name')
    for key in ('definition_id', 'object'):
        _require(value[key] is None or isinstance(value[key], str), path + '.' + key + ' must be text or null')


def validate_graph(graph):
    """Structural check of a stored graph. Raises SchemaError; never repairs."""
    _require(isinstance(graph, dict), 'assembly graph must be an object')
    _require(set(graph) == {'schema_version', 'joints'}, 'unexpected assembly graph fields')
    _require(graph['schema_version'] == GRAPH_VERSION and type(graph['schema_version']) is int,
             'unsupported assembly graph version')
    _require(isinstance(graph['joints'], list), 'joints must be a list')
    seen_ids, seen_sockets = set(), set()
    for joint in graph['joints']:
        _require(isinstance(joint, dict), 'joint must be an object')
        _require(set(joint) == {'id', 'a', 'b', 'state', 'carries', 'closes_loop', 'verdict', 'evidence'},
                 'unexpected joint fields')
        _require(isinstance(joint['id'], str) and joint['id'], 'joint.id must be a name')
        _require(joint['id'] not in seen_ids, 'duplicate joint id: ' + str(joint['id']))
        seen_ids.add(joint['id'])
        _endpoint(joint['a'], 'joint.a')
        _endpoint(joint['b'], 'joint.b')
        _require(joint['state'] in STATES, 'unknown joint state')
        _require(joint['carries'] in (None, 'a', 'b'), 'joint.carries must be a, b or null')
        _require(isinstance(joint['closes_loop'], bool), 'joint.closes_loop must be a boolean')
        _require(joint['verdict'] == 'compatible', 'a stored joint must rest on a compatible verdict')
        _require(isinstance(joint['evidence'], list) and all(isinstance(s, str) for s in joint['evidence']),
                 'joint.evidence must be source ids')
        for side in ('a', 'b'):
            socket = (joint[side]['instance_id'], joint[side]['interface'])
            _require(socket not in seen_sockets, 'interface %s of %s carries two joints'
                     % (socket[1], socket[0]))
            seen_sockets.add(socket)
        _require(joint['a']['instance_id'] != joint['b']['instance_id'], 'a joint needs two parts')
    carried = [joint[joint['carries']]['instance_id'] for joint in graph['joints']
               if joint['carries'] is not None]
    for child in carried:
        _require(carried.count(child) == 1,
                 '%s is carried by two joints; a transform tree allows one parent' % child)
    parents = ownership(graph)
    for child in parents:
        seen, node = {child}, parents.get(child)
        while node is not None:
            _require(node not in seen, 'transform ownership cycle at ' + child)
            seen.add(node)
            node = parents.get(node)
    return graph


def ownership(graph):
    """child instance_id -> parent instance_id, from the carrying joints only."""
    out = {}
    for joint in graph['joints']:
        if joint['carries'] is None:
            continue
        child = joint[joint['carries']]['instance_id']
        parent = joint['a' if joint['carries'] == 'b' else 'b']['instance_id']
        out[child] = parent
    return out


def carried_parts(graph, instance_id):
    """`instance_id` plus everything whose pose it carries, transitively. Breadth-first, stable order."""
    parents = ownership(graph)
    children = {}
    for child, parent in parents.items():
        children.setdefault(parent, []).append(child)
    order, queue = [instance_id], [instance_id]
    while queue:
        for child in sorted(children.get(queue.pop(0), [])):
            if child not in order:
                order.append(child)
                queue.append(child)
    return order


def depth(graph, instance_id):
    parents, steps, node = ownership(graph), 0, instance_id
    while parents.get(node) is not None and steps < len(parents) + 1:
        node = parents[node]
        steps += 1
    return steps


def joints_of(graph, instance_id):
    return [j for j in graph['joints']
            if instance_id in (j['a']['instance_id'], j['b']['instance_id'])]


def find_joint(graph, joint_id):
    for joint in graph['joints']:
        if joint['id'] == joint_id:
            return joint
    return None


def socket_joint(graph, instance_id, interface_id):
    for joint in graph['joints']:
        for side in ('a', 'b'):
            if (joint[side]['instance_id'], joint[side]['interface']) == (instance_id, interface_id):
                return joint, side
    return None, None


def matching_joint(graph, a, interface_a, b, interface_b):
    """The joint already binding exactly these two sockets, in either order."""
    want = {(a, interface_a), (b, interface_b)}
    for joint in graph['joints']:
        have = {(joint[side]['instance_id'], joint[side]['interface']) for side in ('a', 'b')}
        if have == want:
            return joint
    return None


def _next_id(graph):
    used = {j['id'] for j in graph['joints']}
    index = 1
    while ('joint:%d' % index) in used:
        index += 1
    return 'joint:%d' % index


def _endpoint_of(record, interface_id, object_name):
    return {'instance_id': record['instance_id'], 'definition_id': record.get('definition_id'),
            'object': object_name, 'interface': interface_id}


def _refuse(reason, **extra):
    out = {'ok': False, 'error': reason}
    out.update(extra)
    return out


def _interface(record, interface_id):
    for item in record.get('interfaces', []):
        if item['id'] == interface_id:
            return item
    return None


def _lock_kinds(interface_a, interface_b):
    return [i['lock']['kind'] for i in (interface_a, interface_b) if (i['lock'] or {}).get('kind')]


def plan_join(graph, record_a, interface_a, object_a, record_b, interface_b, object_b,
              compatibility, carries=None):
    """Decide one join. Returns {'ok', 'graph', 'joint', 'created'} or a refusal with its reason.

    `compatibility` is the stage-03 answer for this pair; only `compatible` may become a joint. The
    graph handed back is a new object -- the caller writes it, so a refusal cannot leave a half-joint.
    `carries` is None (decide from the graph), 'a'/'b' (that side is carried, refused if impossible) or
    'none' (record the joint without carrying a pose).
    """
    _require(carries in CARRIES, "carries must be None, 'a', 'b' or 'none'")
    validate_graph(graph)
    ia, ib = record_a['instance_id'], record_b['instance_id']
    if ia == ib:
        return _refuse('a part cannot be joined to itself (same instance_id %s)' % ia)
    item_a, item_b = _interface(record_a, interface_a), _interface(record_b, interface_b)
    for item, record, interface_id in ((item_a, record_a, interface_a), (item_b, record_b, interface_b)):
        if item is None:
            return _refuse('no interface %r on %s' % (interface_id, record.get('definition_id')))
    existing = matching_joint(graph, ia, interface_a, ib, interface_b)
    if existing is not None:
        # Calling twice is not two joints: the same two sockets are already bound.
        return {'ok': True, 'graph': graph, 'joint': dict(existing), 'created': False,
                'note': 'these interfaces are already joined; nothing was written'}
    verdict = compatibility.get('verdict')
    if verdict != 'compatible':
        return _refuse('the compatibility verdict is %s, so these interfaces may not be joined' % verdict,
                       verdict=verdict, missing=list(compatibility.get('missing') or []),
                       adapter_chain=list(compatibility.get('adapter_chain') or []),
                       remedy=('insert the adapter as its own two joints' if verdict == 'adapter_required'
                               else 'state the missing data, or choose parts that mate'))
    for instance_id, interface_id, record in ((ia, interface_a, record_a), (ib, interface_b, record_b)):
        held, _side = socket_joint(graph, instance_id, interface_id)
        if held is not None:
            return _refuse('interface %s of %s already carries %s; one socket holds one joint'
                           % (interface_id, record.get('definition_id') or instance_id, held['id']))
    parents = ownership(graph)
    subassembly_b, subassembly_a = carried_parts(graph, ib), carried_parts(graph, ia)
    # Already in one physical component, so this joint adds a second route between the two: a loop.
    closes_loop = _connected(graph, ia, ib)
    reasons = {}
    options = []
    for side, child, parent, sub in (('b', ib, ia, subassembly_b), ('a', ia, ib, subassembly_a)):
        if parents.get(child) is not None:
            reasons[side] = ('%s is already carried by %s; a transform tree allows one parent'
                             % (child, parents[child]))
        elif parent in sub:
            reasons[side] = ('%s is inside the sub-assembly %s carries, so carrying it would close a '
                             'transform cycle' % (parent, child))
        else:
            options.append(side)
    if carries == 'none':
        chosen = None
    elif carries in ('a', 'b'):
        if carries not in options:
            return _refuse(reasons[carries], remedy="pass carries='none' to record this as a "
                                                    'physical joint that carries no pose')
        chosen = carries
    else:
        # Default: the part named second is mounted onto the part named first. When that cannot carry a
        # pose the joint is still real -- it is recorded as physical-only, which is how a cage closes.
        chosen = 'b' if 'b' in options else ('a' if 'a' in options else None)
    joint = {'id': _next_id(graph),
             'a': _endpoint_of(record_a, interface_a, object_a),
             'b': _endpoint_of(record_b, interface_b, object_b),
             'state': 'aligned', 'carries': chosen, 'closes_loop': bool(closes_loop),
             'verdict': 'compatible', 'evidence': sorted(set(compatibility.get('evidence') or []))}
    result = {'schema_version': GRAPH_VERSION, 'joints': [dict(j) for j in graph['joints']] + [joint]}
    validate_graph(result)
    out = {'ok': True, 'graph': result, 'joint': joint, 'created': True}
    if chosen is None and carries is None:
        out['note'] = ('recorded as a physical joint that carries no pose: '
                       + '; '.join(reasons[s] for s in sorted(reasons)))
    return out


def _connected(graph, a, b):
    """Are the two parts already in one physical component? Then a new joint closes a loop."""
    seen, queue = {a}, [a]
    while queue:
        for joint in joints_of(graph, queue.pop(0)):
            for side in ('a', 'b'):
                other = joint[side]['instance_id']
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
    return b in seen


def plan_state(graph, joint_id, state, interface_a=None, interface_b=None):
    """One step along aligned <-> seated <-> fastened <-> locked. Skipping a state is refused."""
    validate_graph(graph)
    joint = find_joint(graph, joint_id)
    if joint is None:
        return _refuse('no joint %r in this scene' % joint_id)
    if state not in STATES:
        return _refuse('unknown state %r; the states are %s' % (state, ', '.join(STATES)))
    if state == joint['state']:
        return {'ok': True, 'graph': graph, 'joint': dict(joint), 'changed': False,
                'note': 'the joint is already ' + state}
    step = _RANK[state] - _RANK[joint['state']]
    if abs(step) != 1:
        direction = 'forward' if step > 0 else 'back'
        return _refuse('%s is %s; going %s to %s skips %s, and assembly order is explicit'
                       % (joint_id, joint['state'], direction, state,
                          ', '.join(STATES[min(_RANK[state], _RANK[joint['state']]) + 1:
                                            max(_RANK[state], _RANK[joint['state']])])))
    if state == 'locked':
        kinds = _lock_kinds(interface_a or {'lock': {}}, interface_b or {'lock': {}})
        if not kinds:
            return _refuse('neither interface declares a lock, so a locked state is not supported by '
                           'the data', missing=['interface lock kind'])
    joints = []
    for item in graph['joints']:
        item = dict(item)
        if item['id'] == joint_id:
            item['state'] = state
        joints.append(item)
    result = validate_graph({'schema_version': GRAPH_VERSION, 'joints': joints})
    return {'ok': True, 'graph': result, 'joint': find_joint(result, joint_id), 'changed': True}


def plan_separate(graph, joint_id):
    """Remove a joint. Only an `aligned` joint comes apart; anything else names the next step."""
    validate_graph(graph)
    joint = find_joint(graph, joint_id)
    if joint is None:
        return _refuse('no joint %r in this scene' % joint_id)
    if joint['state'] != 'aligned':
        back = STATES[_RANK[joint['state']] - 1]
        return _refuse('%s is %s; take it to %s first' % (joint_id, joint['state'], back),
                       next_step={'joint': joint_id, 'state': back})
    joints = [dict(j) for j in graph['joints'] if j['id'] != joint_id]
    result = validate_graph({'schema_version': GRAPH_VERSION, 'joints': joints})
    return {'ok': True, 'graph': result, 'removed': dict(joint)}


def _steps_to_open(joint):
    """The states a joint passes through on the way off, in order."""
    back = list(STATES[:_RANK[joint['state']]])[::-1]
    return [{'joint': joint['id'], 'state': s} for s in back] + [{'joint': joint['id'], 'separate': True}]


def disassembly_order(graph, instance_id):
    """What has to come apart, in order, to free one part.

    `release` opens only the joints that cross the boundary of the sub-assembly this part carries, so
    the part comes off as a unit with whatever it holds. `full` takes that sub-assembly apart as well,
    deepest joint first, which is the order a bench is stripped in.
    """
    validate_graph(graph)
    inside = carried_parts(graph, instance_id)
    boundary, internal = [], []
    for joint in graph['joints']:
        ends = (joint['a']['instance_id'], joint['b']['instance_id'])
        count = sum(1 for e in ends if e in inside)
        if count == 1:
            boundary.append(joint)
        elif count == 2:
            internal.append(joint)
    def deepest(joint):
        return -max(depth(graph, joint[side]['instance_id']) for side in ('a', 'b'))
    release, full = [], []
    for joint in sorted(boundary, key=deepest):
        release.extend(_steps_to_open(joint))
    for joint in sorted(internal + boundary, key=deepest):
        full.extend(_steps_to_open(joint))
    return {'part': instance_id, 'carries': inside[1:], 'release': release, 'full': full}


def motion_permissions(graph, record):
    """Per declared motion: may it move now, and if not, which joint holds it.

    A motion whose interface carries no joint is free -- nothing is attached there. Seating still
    leaves it free, because seating is what the motion is for. Fastening holds it, and a locked joint
    refuses it outright until the lock is opened.
    """
    validate_graph(graph)
    instance_id = record['instance_id']
    out = []
    for motion in record.get('motions', []):
        joint, _side = socket_joint(graph, instance_id, motion['interface_id'])
        entry = {'motion': motion['id'], 'interface': motion['interface_id'], 'kind': motion['kind'],
                 'joint': None if joint is None else joint['id'],
                 'joint_state': None if joint is None else joint['state']}
        for key in ('minimum', 'maximum'):
            quantity = motion.get(key)
            dimension = 'length' if motion['kind'] == 'translation' else 'angle'
            entry[key] = None if quantity is None else normalize_quantity(quantity, dimension)['value']
        if joint is None:
            entry.update(permitted=True, reason='nothing is joined at this interface')
        elif _MOTION_FREE[joint['state']]:
            entry.update(permitted=True,
                         reason='%s is %s, which still leaves this motion free' % (joint['id'], joint['state']))
        elif joint['state'] == 'locked':
            entry.update(permitted=False, reason='%s is locked; unlock it first' % joint['id'],
                         next_step={'joint': joint['id'], 'state': 'fastened'})
        else:
            entry.update(permitted=False, reason='%s is fastened; loosen it to seated first' % joint['id'],
                         next_step={'joint': joint['id'], 'state': 'seated'})
        out.append(entry)
    return out


# ---------------------------------------------------------------------------------------------------
# Stage 04b: where a joined part actually goes.
#
# The convention, stated rather than inferred: seating makes the two declared interface frames
# COINCIDENT AND ANTI-PARALLEL -- the child's local +Z, which schema v1 calls the connection axis and
# surface normal, turns to face the parent's. Nothing else is read out of the data. Any depth past that
# datum is an explicit `insertion_mm` (positive = into the parent, along the parent socket's -Z), and it
# is checked against the stated insertion limits. Clocking about the axis is an explicit angle, because
# schema v1 carries no clocking datum beyond the frame's own +X.
#
# An interface with no frame has no datum, so it cannot be placed: the answer is `unknown` and names the
# field. That is the same rule as stage 03 -- a missing value is never a pass.
# ---------------------------------------------------------------------------------------------------

IDENTITY = (((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0))
# pi about local X: +Z -> -Z, +X kept. This is what makes two mating faces look at each other.
MATE_FLIP = (((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0)), (0.0, 0.0, 0.0))


def rotation_from_quaternion(wxyz):
    """Unit quaternion (w, x, y, z) -> row-major 3x3. The schema already requires unit length."""
    w, x, y, z = (float(v) for v in wxyz)
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm == 0.0:
        raise SchemaError('a frame quaternion of zero length has no orientation')
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
            (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
            (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)))


def compose(first, second):
    """Rigid transform product: `first` then `second` applied in the frame `first` defines."""
    (ra, ta), (rb, tb) = first, second
    rot = tuple(tuple(sum(ra[i][k] * rb[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    trans = tuple(ta[i] + sum(ra[i][k] * tb[k] for k in range(3)) for i in range(3))
    return rot, trans


def invert(transform):
    rot, trans = transform
    inverse = tuple(tuple(rot[j][i] for j in range(3)) for i in range(3))
    return inverse, tuple(-sum(inverse[i][k] * trans[k] for k in range(3)) for i in range(3))


def translation(x, y, z):
    return IDENTITY[0], (float(x), float(y), float(z))


def rotation_about_z(degrees):
    angle = math.radians(float(degrees))
    cos, sin = math.cos(angle), math.sin(angle)
    return ((cos, -sin, 0.0), (sin, cos, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0)


def frame_transform(frame):
    """A schema v1 frame, already normalized to mm, as a rigid transform. None has no datum."""
    if frame is None:
        return None
    return rotation_from_quaternion(frame['quaternion_wxyz']), tuple(float(v) for v in frame['origin'])


def _axis(transform, index):
    rot = transform[0]
    return tuple(rot[i][index] for i in range(3))


def _angle_between(u, v):
    dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(u, v))))
    return math.degrees(math.acos(dot))


def mating_transform(clock_deg=0.0, insertion_mm=0.0):
    """Parent socket -> child socket: face to face, clocked, then pushed in by `insertion_mm`."""
    return compose(compose(MATE_FLIP, rotation_about_z(clock_deg)),
                   translation(0.0, 0.0, float(insertion_mm)))


def seating_pose(parent_world, parent_frame, child_frame, clock_deg=0.0, insertion_mm=0.0):
    """Where the child's object origin lands, given the parent's world transform.

    `parent_world` is the parent object's own transform; the frames are its and the child's declared
    interface frames in millimetres. Returns a rigid transform in the same world units.
    """
    socket = compose(parent_world, parent_frame)
    return compose(compose(socket, mating_transform(clock_deg, insertion_mm)), invert(child_frame))


def seating_residual(world_a, frame_a, world_b, frame_b, clock_deg=0.0, insertion_mm=0.0):
    """How far two already-placed interfaces are from actually mating, for a joint that closes a loop.

    The comparison is against where seating WOULD put interface b -- face to face with a, clocked and
    inserted as asked -- so a joint whose hop carries a depth is judged with that depth, not without it.
    Returns the gap in millimetres, the angle the axes are off, and the clocking difference. Nothing is
    corrected: this measures the stated geometry and hands back the numbers.
    """
    socket_a = compose(world_a, frame_a)
    socket_b = compose(world_b, frame_b)
    expected = compose(socket_a, mating_transform(clock_deg, insertion_mm))
    gap = math.sqrt(sum((expected[1][i] - socket_b[1][i]) ** 2 for i in range(3)))
    return {'gap_mm': gap,
            'axis_deg': _angle_between(_axis(expected, 2), _axis(socket_b, 2)),
            'clock_deg': _angle_between(_axis(expected, 0), _axis(socket_b, 0))}


def placement_limits(interface_a, interface_b, insertion_mm):
    """Stated insertion limits the requested depth has to respect. Unstated limits are not invented."""
    problems, used = [], []
    for item, side in ((interface_a, 'a'), (interface_b, 'b')):
        for field, compare in (('insertion_min', lambda v: insertion_mm < v),
                               ('insertion_max', lambda v: insertion_mm > v)):
            quantity = (item.get('dimensions') or {}).get(field)
            if quantity is None or quantity.get('value') is None:
                continue
            value = normalize_quantity(quantity)['value']
            used.extend(quantity.get('evidence') or [])
            if compare(value):
                problems.append('%s of interface %s states %s %.3f mm, and %.3f mm was asked for'
                                % (item['id'], side, field, value, insertion_mm))
    return problems, sorted(set(used))
