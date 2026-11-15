#!/usr/bin/env python3
"""Sync molecular-pair links to the current selected UV-response tables.

Only selected-response link fields are derived here; original chemistry records are retained.
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
PAIR_POOLS = {'AP039': 'NH', 'AP048': 'OH', 'AP090': 'SH'}
DERIVED_FIELDS = {'selected_NH_OH_rows', 'selected_NH_OH_response_scope', 'selected_BO_rows', 'selected_BO_response_scope'}



def immutable_digest(records):
    """Hash every field that this builder is not permitted to change."""
    projection = [{key: value for key, value in row.items()
                   if key not in DERIVED_FIELDS} for row in records]
    payload = json.dumps(projection, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def selected_links(pool):
    source = ROOT / 'optimization/current/runs' / pool / 'trajectory_conditions.csv'
    with source.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == {'NH':60, 'OH':56, 'SH':48}[pool]
    assert len({int(row['candidate_index']) for row in rows}) == len(rows)
    counts=Counter(row['batch_number'] for row in rows)
    assert counts.pop('0')==12 and set(counts.values())=={4}
    links=[]
    for row in sorted(rows,key=lambda r:int(r['candidate_index'])):
        links.append({'record_type':'COMPUTATIONAL_EVALUATION', 'pool_id':pool,
            'batch_number':row['batch_number'], 'candidate_index':row['candidate_index'],
            'display_sample_id':row['source_well'], 'original_sample_id':row['source_well'],
            'catalyst':row['cat'], 'ligand':row['ligand'], 'base':row['base'],
            'solvent':row['solvent'], 'archived_response':row['UV_response'],
            'response_units':'UV response', 'source_sheet':row['source_sheet'],
            'source_response_cell':row['source_response_cell'],
            'source_pool_id':row['source_pool'], 'source_excel_row':row['source_excel_row']})
    return links


def synchronize(records):
    assert len(records) == 108, len(records)
    assert {row['actual_pair_id'] for row in records} == {
        f'AP{number:03}' for number in range(1, 109)}
    links = {pair: selected_links(pool) for pair, pool in PAIR_POOLS.items()}
    total = sum(len(value) for value in links.values())
    scope = (f'The current N–H, O–H and S–H trajectories contain {total} selected UV responses '
             'within the shared 13920-condition decision space. UV signals are compared '
             'within the same substrate–product pair and analytical conditions.')
    result = []
    for row in records:
        updated = dict(row)
        updated['selected_BO_rows'] = links.get(row['actual_pair_id'], [])
        updated['selected_BO_response_scope'] = scope
        updated['selected_NH_OH_rows'] = links.get(row['actual_pair_id'], []) if row['actual_pair_id'] in ('AP039','AP048') else []
        updated['selected_NH_OH_response_scope'] = scope
        result.append(updated)
    assert immutable_digest(records) == immutable_digest(result)
    assert Counter(link['pool_id'] for row in result
                   for link in row['selected_BO_rows']) == {
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
        'selected_response_links': sum(len(row['selected_BO_rows']) for row in result),
        'selected_links_by_pair': {pair: len(next(
            row['selected_BO_rows'] for row in result
            if row['actual_pair_id'] == pair)) for pair in PAIR_POOLS},
        'active_pools': list(PAIR_POOLS.values()),
        'response_units': 'UV response',
        'unmodified_fields_sha256': immutable_digest(result),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
