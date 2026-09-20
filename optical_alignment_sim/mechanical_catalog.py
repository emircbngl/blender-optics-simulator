"""Mechanical metadata snapshots, independent of optical properties and scene geometry.

No catalog identity is guessed from an old mount name. No schema migration runs on load.
This module deliberately exposes no MCP tool: compatibility/assembly comes in later stages.
"""
from copy import deepcopy
import json
from uuid import uuid4
from .mechanical_interfaces import (SchemaError, fields, require, text, refs,
                                    validate_interface, validate_quantity, normalize_quantity)

SCHEMA_VERSION = 1


def new_record(definition_id, manufacturer=None, part_number=None, variant=None, revision=None):
    return dict(schema_version=SCHEMA_VERSION, instance_id=str(uuid4()), definition_id=definition_id,
                identity=dict(manufacturer=manufacturer, part_number=part_number, variant=variant,
                              revision=revision), geometry_revision=None, sources={}, interfaces=[],
                motions=[], evidence_level='unverified', validation_evidence=[])


def _validate(record):
    fields(record, 'schema_version instance_id definition_id identity geometry_revision sources interfaces '
           'motions evidence_level validation_evidence', 'record')
    require(type(record['schema_version']) is int and record['schema_version'] == SCHEMA_VERSION,
            'unsupported mechanical schema version')
    for key in ('instance_id', 'definition_id'):
        text(record[key], key)
    fields(record['identity'], 'manufacturer part_number variant revision', 'identity')
    for k, value in record['identity'].items():
        text(value, 'identity.' + k, nullable=True)
    text(record['geometry_revision'], 'geometry_revision', nullable=True)
    require(isinstance(record['sources'], dict), 'sources must be an object')
    for sid, source in record['sources'].items():
        text(sid, 'source id')
        fields(source, 'url locator revision checked_on sha256', 'source')
        for key in ('url', 'locator', 'checked_on'):
            text(source[key], 'source.' + key)
        require(source['url'].startswith('https://'), 'source must use https')
        text(source['revision'], 'source.revision', nullable=True)
        digest = source['sha256']
        require(digest is None or (isinstance(digest, str) and len(digest) == 64 and
                                  all(c in '0123456789abcdef' for c in digest)), 'invalid source digest')
    require(isinstance(record['interfaces'], list), 'interfaces must be a list')
    ids = []
    for item in record['interfaces']:
        validate_interface(item, record['sources'])
        ids.append(item['id'])
    require(len(ids) == len(set(ids)), 'duplicate mechanical interface id')
    require(isinstance(record['motions'], list), 'motions must be a list')
    motion_ids = []
    for motion in record['motions']:
        fields(motion, 'id interface_id kind minimum maximum evidence', 'motion')
        text(motion['id'], 'motion.id')
        motion_ids.append(motion['id'])
        require(motion['interface_id'] in ids, 'motion references missing interface')
        require(motion['kind'] in ('translation', 'rotation'), 'invalid motion kind')
        refs(motion['evidence'], record['sources'], 'motion.evidence')
        dimension = 'length' if motion['kind'] == 'translation' else 'angle'
        for key in ('minimum', 'maximum'):
            validate_quantity(motion[key], record['sources'], dimension)
        a, b = (normalize_quantity(motion[k], dimension)['value'] for k in ('minimum', 'maximum'))
        require(a is None or b is None or a <= b, 'reversed motion limits')
    require(len(motion_ids) == len(set(motion_ids)), 'duplicate motion id')
    # Later stages may introduce verified levels with actual gate results. Labels alone cannot promote.
    require(record['evidence_level'] in ('unverified', 'visual_approximation'),
            'verified evidence levels require a future validation gate')
    refs(record['validation_evidence'], record['sources'], 'validation_evidence')
    return deepcopy(record)


def validate(record):
    try:
        return _validate(record)
    except (TypeError, ValueError, KeyError) as exc:
        raise SchemaError(str(exc)) from exc


def normalized(record):
    """Canonical mm/deg calculation view; persisted source units remain unchanged."""
    result = validate(record)
    def frame(value):
        if value is not None and value['unit'] == 'in':
            value['origin'] = [v * 25.4 for v in value['origin']]
            value['unit'] = 'mm'
    for item in result['interfaces']:
        frame(item['frame'])
        frame(item['access']['approach_frame'])
        item['dimensions'] = {k: normalize_quantity(q) for k, q in item['dimensions'].items()}
        if item['thread'] is not None:
            for key in ('major_diameter', 'pitch'):
                item['thread'][key] = normalize_quantity(item['thread'][key])
        for hole in item['holes']:
            frame(hole['frame'])
            for key in ('diameter', 'depth'):
                hole[key] = normalize_quantity(hole[key])
    for motion in result['motions']:
        dimension = 'length' if motion['kind'] == 'translation' else 'angle'
        for key in ('minimum', 'maximum'):
            motion[key] = normalize_quantity(motion[key], dimension)
    return result


def dumps(record):
    return json.dumps(validate(record), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


def loads(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    try:
        return validate(json.loads(raw, object_pairs_hook=unique))
    except (TypeError, ValueError, KeyError) as exc:
        raise SchemaError(str(exc)) from exc


def read_object(obj):
    """Read without populating old scenes. Unknown future data remains stored unchanged."""
    raw = obj.mechanics.record_json
    if not raw:
        return dict(status='legacy_unmapped', record=None)
    try:
        return dict(status='metadata_only', record=loads(raw))
    except SchemaError as exc:
        return dict(status='unreadable', record=None, error=str(exc))


def attach_object(obj, record, *, replace=False):
    """Explicit opt-in only. Validate completely before the single serialized property write."""
    encoded = dumps(record)
    if obj.mechanics.record_json and not replace:
        raise SchemaError('mechanical metadata already exists; explicit replacement required')
    obj.mechanics.record_json = encoded
    return read_object(obj)
