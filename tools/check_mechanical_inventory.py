"""Read-only stage-01 evidence gate; no Blender dependency or network access."""
import ast
import json
import runpy
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

def check():
    data = json.loads((ROOT / 'docs/mechanics/product-evidence.json').read_text())
    tree = ast.parse((ROOT / 'tools/inspect_mounts.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'mount_cases')
    original = next(n for n in ast.walk(function) if isinstance(n, ast.Dict)
                    and any(isinstance(k, ast.Constant) and k.value == 'KM100' for k in n.keys))
    expected = {ast.literal_eval(k) for k in original.keys}
    expected.update(runpy.run_path(str(ROOT / 'optical_alignment_sim/hardware_catalog.py'))['PRODUCTS'])
    products = data['products']
    ids = [p['preset_id'] for p in products]
    assert len(ids) == len(set(ids)), 'duplicate presets'
    assert set(ids) == expected, f'coverage mismatch: {set(ids) ^ expected}'
    sources = data['sources']
    for sid, source in sources.items():
        assert urlsplit(source['url']).scheme == 'https', sid
        assert source['locator'] and source['access'] and source['checked_on'], sid
        # Stage 01 acquired no CAD. Stage 05 opens vendor drawings with the owner's go-ahead, and a
        # source that did has to say so: a primary drawing, with a note recording that the file is
        # read for dimensions, kept out of the repository and not redistributed.
        if source['cad_file_acquired']:
            assert source['access'] in ('primary_drawing', 'primary_cad_model'), sid
            note = source.get('acquisition_note') or ''
            assert 'not redistributed' in note and 'not stored in this repository' in note, sid
            assert source['document_revision'], sid
    for p in products:
        assert p['current_model_status'] == 'visual_approximation'
        assert p['training_ready'] is False
        assert p['bom'] and p['critical_measurements'] and p['gaps'], p['preset_id']
        target = p['target']
        if target['part_number'] is not None:
            assert target['manufacturer'] and target['variant'] and target['source_ids']
            assert all(s in sources and sources[s]['access'] != 'unreadable' for s in target['source_ids'])
        else:
            assert p['mapping_status'] in ('identity_gap', 'evidence_gap')
        for item in p['bom']:
            assert all(s in sources for s in item['source_ids'])
            if item['part_number'] is not None:
                assert item['source_ids']
        for measurement in p['critical_measurements']:
            assert measurement['value'] is None, 'raw source facts belong in evidence_facts until datum validation'
            assert measurement['measurement_method']
            assert measurement['threshold_status'] == 'requires_dimensioned_source'
    for fact in data['evidence_facts']:
        assert fact['source_id'] in sources and set(fact['presets']) <= expected
        assert fact['locator'] and fact['verification'] == 'primary_published_nominal_not_mesh_verified'
    support_numbers = {p['part_number'] for p in data['support_parts']}
    for p in data['support_parts']:
        assert p['source_id'] in sources and p['compatibility'] == 'unknown'
    # Stage 05 acquisition: published facts about the support chain. They live apart from the preset
    # facts because a post or a holder is not a preset, and they are nominal until a drawing datum
    # and a mesh measurement agree.
    fact_ids = {f['id'] for f in data.get('support_facts', [])}
    for fact in data.get('support_facts', []):
        assert fact['source_id'] in sources, fact['id']
        assert set(fact['support_parts']) <= support_numbers, fact['id']
        assert fact['locator'], fact['id']
        # A number nobody published is allowed, but only when it says so and names what it came from.
        if fact['verification'] == 'derived_from_published_nominals':
            assert fact.get('derived_from') and set(fact['derived_from']) <= fact_ids, fact['id']
            assert fact['note'] and 'DERIVED' in fact['note'], fact['id']
        else:
            assert fact['verification'] == 'primary_published_nominal_not_mesh_verified', fact['id']
        # A tolerance is recorded only where the source states one, and then the locator quotes it.
        assert fact['manufacturing_tolerance'] is None or '\u00b1' in fact['locator'], \
            '%s: a tolerance must be quoted from its source, never inferred from decimal places' % fact['id']
    # A standards rule is adopted only with its source and the clause quoted, never from memory.
    for rule in data.get('standards_rules', []):
        assert rule['source_id'] in sources and rule['quote'] and rule['rule'] and rule['adopted'], rule['id']
    blockers = data.get('support_blockers')
    if blockers is not None:
        assert blockers['missing'] and blockers['next_action']
        for key in blockers.get('closed_since_last_record', []):
            assert key
        assert blockers['dependent_work_not_started'] is True, \
            'the plan forbids starting work that depends on evidence that is still missing'
    assert data['stage_gate'] == dict(preset_inventory_complete=True, product_identity_complete=False,
                                     dimension_validation_complete=False, assembly_training_complete=False)
    mapped = sum(p['target']['part_number'] is not None for p in products)
    print(f'INVENTORY PASS: {len(expected)}/{len(expected)} presets; {mapped} source-named targets; '
          f'{len(expected)-mapped} explicit identity/evidence gaps; {len(sources)} source records')
    facts = len(data.get('support_facts', []))
    if facts:
        drawings = sum(1 for f in data['support_facts']
                       if sources[f['source_id']]['access'] == 'primary_drawing')
        print(f'SUPPORT ACQUISITION: {facts} facts ({drawings} from primary drawings) for '
              f'{len({p for f in data["support_facts"] for p in f["support_parts"]})} support parts; '
              f'{len(data["support_blockers"]["missing"])} gaps still blocking stage 05')
    print('This validates coverage and provenance structure, not source accuracy, mesh dimensions or compatibility.')

if __name__ == '__main__':
    check()
