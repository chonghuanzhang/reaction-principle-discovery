#!/usr/bin/env python3
"""Check the 112-pair release against its deposited source structures."""
from collections import Counter
from pathlib import Path
from zipfile import ZipFile
import csv
import hashlib
import json
import posixpath
import xml.etree.ElementTree as ET

from rdkit import Chem

ROOT = Path(__file__).resolve().parents[2]
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))


def canonical(smiles):
    molecule = Chem.MolFromSmiles(smiles)
    assert molecule is not None, f'Invalid structure: {smiles}'
    return Chem.MolToSmiles(molecule, isomericSmiles=True)


def display_label(value):
    return 'unresolved' if value is None else 'not applicable' if value == '不适用' else str(value)


def worksheet_cells(path, sheet_name):
    with ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        sheet = next(node for node in workbook.findall('s:sheets/s:sheet', NS)
                     if node.attrib['name'] == sheet_name)
        relationships = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        target = next(node.attrib['Target'] for node in relationships
                      if node.attrib['Id'] == sheet.attrib['{' + REL + '}id'])
        target = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(node.itertext()) for node in shared]
        cells = {}
        for node in ET.fromstring(archive.read(target)).findall('.//s:c', NS):
            kind = node.attrib.get('t')
            value = node.find('s:v', NS)
            if kind == 's':
                text = strings[int(value.text)]
            elif kind == 'inlineStr':
                text = ''.join(node.find('s:is', NS).itertext())
            else:
                text = value.text if value is not None else None
            cells[node.attrib['r']] = text
        return cells


def main():
    pairs = load('candidates/experiment_mapping/mapping_112.json')
    assert len(pairs) == 112
    assert {p['actual_pair_id'] for p in pairs} == {f'AP{i:03d}' for i in range(1, 113)}
    assert len({(canonical(p['electrophile_smiles']), canonical(p['actual_donor_smiles'])) for p in pairs}) == 112
    assert len({canonical(p['actual_donor_smiles']) for p in pairs}) == 102
    assert len({canonical(p['electrophile_smiles']) for p in pairs}) == 6
    assert Counter(p['route'] for p in pairs) == {'NH': 45, 'OH': 44, 'SH': 21, 'PH': 2}
    assert Counter(p['primary_relationship_category'] for p in pairs) == {
        'Exact identity': 27, 'Same scaffold, substituent or positional variation': 39,
        'Same donor family, different scaffold': 42, 'No reasonable counterpart': 4}

    for relative in ['code/data/mapping/mapping_112.json', 'code/data/structures/actual_pairs.json']:
        records = {p['actual_pair_id']: p for p in load(relative)}
        assert len(records) == 112
        for pair in pairs:
            for field in pair:
                assert records[pair['actual_pair_id']][field] == pair[field], (relative, pair['actual_pair_id'], field)
    with (ROOT / 'candidates/experiment_mapping/table_R1.csv').open(newline='', encoding='utf-8') as handle:
        csv_pairs = {p['actual_pair_id']: p for p in csv.DictReader(handle)}
    assert len(csv_pairs) == 112
    novelty = {p['actual_pair_id']: p for p in load('code/data/novelty/reviewed/novelty_actual_pairs_112.json')}
    assert len(novelty) == 112
    for pair in pairs:
        ident = pair['actual_pair_id']
        assert display_label(novelty[ident]['NP_label']) == str(pair['NP_label']) == csv_pairs[ident]['NP_label']
        assert display_label(novelty[ident]['NR']) == str(pair['NR_label']) == csv_pairs[ident]['NR_label']

    manifest = load('experiments/raw/product_structure_register_manifest.json')
    raw_path = ROOT / manifest['path']
    assert raw_path.stat().st_size == manifest['bytes']
    assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == manifest['sha256']
    cells = worksheet_cells(raw_path, manifest['sheet'])
    by_id = {p['actual_pair_id']: p for p in pairs}
    candidates = {c['display_id']: c for c in load('candidates/data/candidates_100.json')}
    for entry in manifest['pair_records']:
        pair = by_id[entry['actual_pair_id']]
        row = entry['row']
        assert cells[f'A{row}'] == entry['product_id'] == pair['product_identifiers'][0]
        assert canonical(cells[f'B{row}']) == pair['electrophile_smiles']
        assert canonical(cells[f'C{row}']) == pair['actual_donor_smiles']
        assert canonical(cells[f'D{row}']) == pair['recorded_product_smiles'][0]
        assert pair['sample_ids'] == [] and pair['unique_condition_recipe_count'] == 0
        assert len(pair['source_occurrences']) == 1
        occurrence = pair['source_occurrences'][0]
        assert occurrence['source_type'] == 'product_structure_register'
        assert occurrence['source_record_id'] == cells[f'A{row}']
        assert occurrence['experiment_id'] is None and occurrence['condition_id'] is None
        assert occurrence['row'] == row and occurrence['sheet'] == manifest['sheet']
        assert occurrence['workbook_sha256'] == manifest['sha256']
        assert occurrence['repository_path'] == manifest['path']
        assert pair['execution_status'] == 'executed'
        for link in pair['candidate_links']:
            reverse = [r for r in candidates[link['candidate_display_id']]['experimental_correspondence']
                       if r['actual_pair_id'] == pair['actual_pair_id']]
            assert len(reverse) == 1 and reverse[0]['relationship_category'] == link['relationship_category']
        options = novelty[pair['actual_pair_id']]['options']
        assessment = novelty[pair['actual_pair_id']]
        assert (ROOT / assessment['review_input']['file']).is_file()
        evidence_base = ROOT / assessment['assessment_evidence_base']
        assert all((evidence_base / option['pubchem_evidence_file']).is_file() for option in options)
        assert any(Chem.MolToSmiles(Chem.MolFromSmiles(o['product_smiles']), isomericSmiles=False)
                   == Chem.MolToSmiles(Chem.MolFromSmiles(pair['recorded_product_smiles'][0]), isomericSmiles=False)
                   for o in options)
    assert len(manifest['pair_records']) == 4
    evidence_base = ROOT / 'code/data/novelty/reviewed/pair_assessment_sources_20261126'
    evidence_manifest = json.loads((evidence_base / 'evidence_manifest.json').read_text())
    for relative, expected in evidence_manifest['files'].items():
        assert hashlib.sha256((evidence_base / relative).read_bytes()).hexdigest() == expected, relative
    assert hashlib.sha256((evidence_base / 'proposed_pair_records.json').read_bytes()).hexdigest() == evidence_manifest['review_record_sha256']
    assert hashlib.sha256((evidence_base / 'assessed_inputs.json').read_bytes()).hexdigest() == evidence_manifest['input_sha256']
    print(json.dumps({'status': 'PASS', 'experimental_pairs': 112, 'unique_donors': 102,
                      'unique_electrophiles': 6, 'source_register_pairs_verified': 4,
                      'invented_sample_or_condition_identifiers': 0}, indent=2))


if __name__ == '__main__':
    main()
