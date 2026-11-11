#!/usr/bin/env python3
"""Sync molecular-pair links to the current selected UV-response tables.

Only selected_NH_OH_rows and selected_NH_OH_response_scope are derived here.
All recorded experimental responses and other molecular-pair fields are kept.
Run with --check to validate the deposited links without writing any files.
"""
from collections import Counter
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / 'code/data/structures/actual_pairs.json'
PAIR_POOLS = {'AP039': 'NH_PL36', 'AP048': 'OH_CuNi_96'}
CATALYSTS = {'NH_PL36': {'Ag13'}, 'OH_CuNi_96': {'Cu66', 'Ni203'}}
DERIVED_FIELDS = {'selected_NH_OH_rows', 'selected_NH_OH_response_scope'}



def immutable_digest(records):
    """Hash every field that this builder is not permitted to change."""
    projection = [{key: value for key, value in row.items()
                   if key not in DERIVED_FIELDS} for row in records]
    payload = json.dumps(projection, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def selected_links(pool):
    source = ROOT / 'optimization/selections' / pool / 'selected_conditions.csv'
    with source.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert 12 <= len(rows) <= 60 and len(rows) % 12 == 0, (pool, len(rows))
    assert len({int(row['candidate_index']) for row in rows}) == len(rows), pool
    assert Counter(row['batch_number'] for row in rows) == {
        str(batch): 12 for batch in range(1, len(rows) // 12 + 1)}, pool
    links = []
    for row in sorted(rows, key=lambda item: int(item['candidate_index'])):
        assert row['pool_id'] == pool, row
        assert row['record_type'] == 'COMPUTATIONAL_PLAN', row
        assert row['catalyst_code'] in CATALYSTS[pool], row
        assert math.isfinite(float(
            row['archived_response_revealed_after_computational_selection'])), row
        links.append({
            'record_type': row['record_type'],
            'pool_id': pool,
            'batch_number': row['batch_number'],
            'display_sample_id': '-'.join(row['sample_id'].split('-')[-2:]),
            'original_sample_id': row['sample_id'],
            'catalyst': row['catalyst_code'],
            'ligand': row['ligand'],
            'base': row['base'],
            'solvent': row['solvent'],
            'archived_response':
                row['archived_response_revealed_after_computational_selection'],
            'response_units': 'UV response',
            'source_sheet': row['source_sheet'],
            'source_response_cell': row['source_response_cell'],
            'source_pool_id': row.get('source_pool_id', pool),
            'source_excel_row': row['source_excel_row'],
            'formulation_code': row.get('formulation_code', ''),
            'formulation': row.get('formulation', row['base']),
        })
    return links


def synchronize(records):
    assert len(records) == 108, len(records)
    assert {row['actual_pair_id'] for row in records} == {
        f'AP{number:03}' for number in range(1, 109)}
    links = {pair: selected_links(pool) for pair, pool in PAIR_POOLS.items()}
    total = sum(len(value) for value in links.values())
    scope = (f'The current N–H and O–H condition-selection analysis contains {total} selected UV responses. '
             'The O–H library varies catalyst–base formulations and solvent. These analytical signals are '
             'not chemical yields. Computational batch labels do not establish laboratory chronology.')
    result = []
    for row in records:
        updated = dict(row)
        updated['selected_NH_OH_rows'] = links.get(row['actual_pair_id'], [])
        updated['selected_NH_OH_response_scope'] = scope
        result.append(updated)
    assert immutable_digest(records) == immutable_digest(result)
    assert Counter(link['pool_id'] for row in result
                   for link in row['selected_NH_OH_rows']) == {
        pool: len(links[pair]) for pair, pool in PAIR_POOLS.items()}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='Validate the supplied links without writing them.')
    args = parser.parse_args()
    records = json.loads(TARGET.read_text(encoding='utf-8'))
    result = synchronize(records)
    if args.check:
        assert records == result, 'Derived links are stale; run without --check.'
    else:
        TARGET.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')
    print(json.dumps({
        'status': 'PASS',
        'mode': 'check' if args.check else 'synchronize',
        'molecular_pairs': len(result),
        'selected_response_links': sum(len(row['selected_NH_OH_rows']) for row in result),
        'selected_links_by_pair': {pair: len(next(
            row['selected_NH_OH_rows'] for row in result
            if row['actual_pair_id'] == pair)) for pair in PAIR_POOLS},
        'active_pools': list(PAIR_POOLS.values()),
        'response_units': 'UV response',
        'unmodified_fields_sha256': immutable_digest(result),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
