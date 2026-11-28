"""Verify current condition provenance directly against the original XLSX.

Only the Python standard library is required. Cached workbook response values
are read without recalculating formulas or rewriting the original workbook.
"""

from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
SYSTEMS = ('NH', 'OH', 'SH')
POOLS = {'NH': ('PL35', 'PL36'), 'OH': ('PL34', 'PL37', 'PL38'),
         'SH': ('PL33', 'PL39', 'PL40')}
CONDITION_FIELDS = ('cat', 'catalyst_equiv', 'ligand', 'ligand_equiv',
                    'base', 'solvent')
SOURCE_FIELDS = ('source_pool', 'source_stage', 'source_sheet',
                 'source_excel_row', 'source_response_cell', 'source_well')


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def _same_number(actual, expected, context):
    left, right = float(actual), float(expected)
    _require(math.isfinite(left) and math.isfinite(right)
             and math.isclose(left, right, rel_tol=0, abs_tol=1e-12),
             f'{context}: {actual!r} != {expected!r}')


def _unique(rows, fields, context):
    keyed = {tuple(row[field] for field in fields): row for row in rows}
    _require(len(keyed) == len(rows), f'{context}: duplicate {fields}')
    return keyed


def _workbook_cells(path):
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    relationship = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
    sheets = {f'亲核试剂({system})-条件筛选' for system in SYSTEMS}
    cells = {}
    with zipfile.ZipFile(path) as book:
        strings = []
        if 'xl/sharedStrings.xml' in book.namelist():
            strings = [''.join(node.itertext()) for node in
                       ET.fromstring(book.read('xl/sharedStrings.xml')).findall('m:si', ns)]
        relations = {node.attrib['Id']: node.attrib['Target'] for node in
                     ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))}
        for sheet in ET.fromstring(book.read('xl/workbook.xml')).find('m:sheets', ns):
            name = sheet.attrib['name']
            if name not in sheets:
                continue
            target = relations[sheet.attrib[relationship]]
            member = (target.lstrip('/') if target.startswith('/') else
                      posixpath.normpath(posixpath.join('xl', target)))
            for cell in ET.fromstring(book.read(member)).findall('.//m:sheetData/m:row/m:c', ns):
                value = cell.find('m:v', ns)
                if cell.attrib.get('t') == 'inlineStr':
                    text = ''.join(node.text or '' for node in cell.findall('m:is//m:t', ns))
                elif value is not None:
                    text = value.text or ''
                    if cell.attrib.get('t') == 's':
                        text = strings[int(text)]
                else:
                    continue
                cells[name, cell.attrib['r']] = text
    _require({sheet for sheet, _ in cells} == sheets, 'Missing current workbook source sheet')
    return cells


def _physical_records(cells, system):
    sheet = f'亲核试剂({system})-条件筛选'
    columns = {'NH': 'J M N P Q R S T', 'OH': 'I K L N O P Q R',
               'SH': 'I K L M N O P Q'}[system].split()
    fields = dict(zip(('ligand', 'ligand_equiv', 'base', 'base_equiv', 'solvent',
                       'solvent_volume_uL', 'time_h', 'temperature_C'), columns))
    fields.update(cat='D', catalyst_CAS='E', catalyst_SMILES_as_recorded='G', catalyst_equiv='H')
    records = []
    for (source_sheet, address), well in cells.items():
        if source_sheet != sheet or not re.fullmatch(r'A[0-9]+', address):
            continue
        match = re.fullmatch(r'(?:CFC124009-19-)?(PL[0-9]+)-W([0-9]+)', well)
        if not match or match[1] not in POOLS[system]:
            continue
        row_number = address[1:]
        response_cell = ('AG' if system == 'SH' else 'AJ') + row_number
        record = {field: cells.get((sheet, column + row_number), '').strip()
                  for field, column in fields.items()}
        record['catalyst_CAS'] = record['catalyst_CAS'].lstrip("‘'")
        # This source label correction is explicitly documented in protocol.json.
        if record['base'] == 'CsOH/2':
            record['base'] = 'CsOH'
        record.update(
            source_pool=f'{system}_{match[1]}',
            source_stage='catalyst_panel' if match[1] == POOLS[system][0] else 'condition_grid',
            source_sheet=sheet, source_excel_row=row_number,
            source_response_cell=response_cell, source_well=well,
            UV_response=cells[sheet, response_cell])
        _same_number(record['UV_response'], record['UV_response'], f'{sheet}!{response_cell}')
        records.append(record)
    _unique(records, ('source_well',), f'{system} physical source records')
    for index, pool in enumerate(POOLS[system]):
        expected = 145 if index == 0 else 96
        _require(sum(r['source_pool'] == f'{system}_{pool}' for r in records) == expected,
                 f'{system}_{pool}: expected {expected} physical source records')
    return records


def check_current_sources():
    """Read current files, raise on disagreement, and return a JSON-safe summary.

    Repository paths are inferred from this module. No file is written and no
    historical derived table is required. The complete split workbook is checked
    separately by ``check_data.py`` via ``reassemble_workbook.verify``.
    """
    current = ROOT / 'optimization/current'
    workbook = ROOT / 'optimization/raw/summary_workbook.xlsx'
    manifest = json.loads((ROOT / 'optimization/raw/workbooks_manifest.json').read_text(encoding='utf-8'))
    workbook_hash = hashlib.sha256(workbook.read_bytes()).hexdigest()
    _require(workbook.stat().st_size == manifest['summary_workbook']['bytes']
             and workbook_hash == manifest['summary_workbook']['sha256'],
             'Original summary workbook checksum or size differs from its manifest')
    cells = _workbook_cells(workbook)
    protocol = json.loads((current / 'protocol.json').read_text(encoding='utf-8'))
    campaigns = {row['system']: row for row in protocol['campaigns']}
    _require(set(campaigns) == set(SYSTEMS), 'Current protocol system IDs differ')
    expected_selected = {'NH': 60, 'OH': 56, 'SH': 48}
    formulations = _read_csv(current / 'data/catalyst_ligand_formulations.csv')
    solvents = _read_csv(current / 'data/solvents.csv')
    bases = _read_csv(current / 'data/bases.csv')
    for axis, field, expected in ((formulations, 'catalyst_index', 145),
                                  (solvents, 'solvent_index', 8), (bases, 'base_index', 12)):
        _require([row[field] for row in axis] == list(map(str, range(expected))),
                 f'{field}: expected unique ordered axis IDs')
    measured_counts, candidate_counts, selected_counts = {}, {}, {}
    physical_count = 0
    trajectories = []
    expected_conflicts = []
    for system in SYSTEMS:
        physical = _physical_records(cells, system)
        physical_count += len(physical)
        by_condition = defaultdict(list)
        for row in physical:
            by_condition[tuple(row[field] for field in CONDITION_FIELDS)].append(row)
        candidates = _read_csv(current / f'data/{system}/candidate_space.csv')
        _require(len(candidates) == protocol['candidate_count_per_system'] == 13920,
                 f'{system}: candidate condition count differs')
        _require([row['candidate_index'] for row in candidates] == list(map(str, range(13920))),
                 f'{system}: candidate IDs are not unique and complete')
        _unique(candidates, ('catalyst_index', 'solvent_index', 'base_index'), f'{system} candidates')
        measured = []
        for row in candidates:
            context = f"{system} candidate {row['candidate_index']}"
            indices = [int(row[field]) for field in ('catalyst_index', 'solvent_index', 'base_index')]
            _require(all(0 <= value < size for value, size in zip(indices, (145, 8, 12))),
                     f'{context}: axis index outside current condition space')
            _require(int(row['candidate_index']) == indices[0] * 96 + indices[1] * 12 + indices[2],
                     f'{context}: encoded candidate ID disagrees with axes')
            for axis, index in zip((formulations, solvents, bases), indices):
                for field, value in axis[index].items():
                    _require(row[field] == value, f'{context}: {field} differs from condition axis')
            _require(row['system'] == system, f'{context}: system identity differs')
            _require(row['response_metric'] == ('UV Peak1+Peak2' if system == 'SH' else 'UV response'),
                     f'{context}: response metric differs')
            source_records = by_condition.get(tuple(row[field] for field in CONDITION_FIELDS), [])
            _require(row['measured'] == str(bool(source_records)), f'{context}: measured flag differs from workbook')
            _require(row['source_record_count'] == str(len(source_records)), f'{context}: source record count differs')
            if not source_records:
                _require(all(row[field] == '' for field in (*SOURCE_FIELDS, 'UV_response')),
                         f'{context}: unmeasured condition carries response or source coordinates')
                continue
            # Grid measurements take precedence irrespective of response magnitude.
            source = min(source_records, key=lambda item: item['source_stage'] != 'condition_grid')
            for field, value in source.items():
                if field == 'UV_response':
                    _same_number(row[field], value, f'{context}: UV_response at {source["source_response_cell"]}')
                else:
                    _require(row[field] == value, f'{context}: source {field} {row[field]!r} != {value!r}')
            if len(source_records) > 1:
                for record in source_records:
                    conflict = {field: record[field] for field in (
                        'cat', 'ligand', 'base', 'solvent', 'source_pool',
                        'source_excel_row', 'source_response_cell', 'UV_response')}
                    conflict.update(system=system, candidate_index=row['candidate_index'],
                                    selected=str(record is source))
                    expected_conflicts.append(conflict)
            measured.append(row)
        _require(len(measured) == len(by_condition), f'{system}: workbook conditions missing from candidate table')
        measured_counts[system], candidate_counts[system] = len(measured), len(candidates)

        selected = _read_csv(current / f'runs/{system}/trajectory_conditions.csv')
        _unique(selected, ('candidate_index',), f'{system} selected trajectory')
        _require(len(selected) == campaigns[system]['unique_conditions'] == expected_selected[system],
                 f'{system}: selected trajectory count differs')
        for row in selected:
            index = int(row['candidate_index'])
            _require(0 <= index < len(candidates), f'{system}: selected candidate ID outside condition space')
            _require(row['measured'] == 'True', f'{system}: selected condition lacks measured feedback')
            for field, value in candidates[index].items():
                _require(row[field] == value, f'{system} selected {index}: {field} differs from candidate source')
        history = json.loads((current / f'runs/{system}/trajectory.json').read_text(encoding='utf-8'))
        sequence = []
        for batch_number, batch in enumerate(history['history']):
            _require(batch['batch_number'] == batch_number, f'{system}: trajectory batch ID differs')
            _require(len(batch['indices']) == (12 if batch_number == 0 else 4), f'{system}: trajectory batch size differs')
            _require(batch['feedback_assimilated'] and not batch['missing_indices'], f'{system}: incomplete trajectory feedback')
            for position, index in enumerate(batch['indices'], start=1):
                sequence.append((str(batch_number), str(position), str(index), str(batch['feedback_assimilated'])))
        _require(sequence == [(r['batch_number'], r['within_batch_display_order'], r['candidate_index'],
                               r['feedback_assimilated']) for r in selected],
                 f'{system}: trajectory JSON identities/order differ from selected CSV')
        _require(history['observed_count'] == len(selected), f'{system}: trajectory observed count differs')
        selected_counts[system] = len(selected)
        trajectories.extend(selected)

    conflicts = _read_csv(current / 'data/source_conflicts.csv')
    conflict_fields = ('system', 'candidate_index', 'source_response_cell')
    conflict_lookup = _unique(conflicts, conflict_fields, 'Current source conflicts')
    expected_lookup = _unique(expected_conflicts, conflict_fields, 'Workbook source conflicts')
    _require(conflict_lookup.keys() == expected_lookup.keys(), 'Current source conflict identities differ from workbook')
    for key, expected in expected_lookup.items():
        for field, value in expected.items():
            if field == 'UV_response':
                _same_number(conflict_lookup[key][field], value, f'Source conflict {key}: UV_response')
            else:
                _require(conflict_lookup[key][field] == value, f'Source conflict {key}: {field} differs from workbook')

    table_r4 = _read_csv(ROOT / 'experiments/selected_responses/selected_responses.csv')
    _unique(table_r4, ('system', 'candidate_index'), 'Table R4')
    _require(table_r4 == trajectories, 'Table R4 CSV differs from current selected trajectories')
    table_r4_json = json.loads((ROOT / 'experiments/selected_responses/selected_responses.json').read_text(encoding='utf-8'))
    _require(table_r4_json == table_r4, 'Table R4 JSON differs from current CSV')
    selected_source = _read_csv(current / 'source_data/selected_response_source.csv')
    source_lookup = _unique(selected_source, ('system', 'candidate_index'), 'Selected response figure source')
    _require(len(source_lookup) == len(trajectories), 'Selected response figure source count differs')
    for row in trajectories:
        key = (row['system'], row['candidate_index'])
        _require(key in source_lookup, f'Selected response figure source missing {key}')
        source = source_lookup[key]
        _require(source['round'] == row['batch_number'], f'Selected response figure source round differs for {key}')
        _same_number(source['UV_response'], row['UV_response'], f'Selected response figure source UV_response for {key}')
    # Retain the distinction between the source NMR yield and analytical response.
    _same_number(cells['亲核试剂(SH)-条件筛选', 'AD308'], 0.37, 'Source NMR yield at AD308')
    return dict(
        status='passed', source_workbook='optimization/raw/summary_workbook.xlsx',
        source_workbook_sha256=workbook_hash,
        physical_source_records_verified=physical_count,
        measured_candidates_verified=sum(measured_counts.values()),
        measured_candidates_by_system=measured_counts,
        source_conflict_records_verified=len(conflicts),
        candidate_conditions_by_system=candidate_counts,
        selected_trajectory_rows_verified=len(trajectories),
        selected_conditions_by_system=selected_counts,
        table_R4_rows_verified=len(table_r4),
        selected_response_source_rows_verified=len(selected_source))
