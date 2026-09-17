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
        assert not source['cad_file_acquired'], 'stage 01 did not acquire CAD'
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
    for p in data['support_parts']:
        assert p['source_id'] in sources and p['compatibility'] == 'unknown'
    assert data['stage_gate'] == dict(preset_inventory_complete=True, product_identity_complete=False,
                                     dimension_validation_complete=False, assembly_training_complete=False)
    mapped = sum(p['target']['part_number'] is not None for p in products)
    print(f'INVENTORY PASS: {len(expected)}/{len(expected)} presets; {mapped} source-named targets; '
          f'{len(expected)-mapped} explicit identity/evidence gaps; {len(sources)} source records')
    print('This validates coverage and provenance structure, not source accuracy, mesh dimensions or compatibility.')

if __name__ == '__main__':
    check()
