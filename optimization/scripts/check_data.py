#!/usr/bin/env python3
"""Check recorded response cells, lossless workbook parts and figure dimensions."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import platform
import struct
import sys
import zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reassemble_workbook import verify as verify_parts


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for data in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def workbook_cells(path):
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as book:
        strings = [''.join(si.itertext()) for si in ET.fromstring(book.read('xl/sharedStrings.xml')).findall('m:si', ns)]
        relations = {r.attrib['Id']: r.attrib['Target'] for r in ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))}
        cells = {}
        for sheet in ET.fromstring(book.read('xl/workbook.xml')).find('m:sheets', ns):
            name = sheet.attrib['name']
            if name not in ('亲核试剂(SH)-条件筛选', '亲核试剂(NH)-条件筛选', '亲核试剂(OH)-条件筛选'):
                continue
            target = relations[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            target = target.lstrip('/') if target.startswith('/') else target if target.startswith('xl/') else 'xl/' + target
            for cell in ET.fromstring(book.read(target)).findall('.//m:sheetData/m:row/m:c', ns):
                value = cell.find('m:v', ns)
                if value is not None:
                    text = value.text
                    if cell.attrib.get('t') == 's':
                        text = strings[int(text)]
                    cells[name, cell.attrib['r']] = text
    return cells


def main(output):
    split = verify_parts()
    cells = workbook_cells(ROOT / 'raw/summary_workbook.xlsx')
    with (ROOT / 'benchmark/data/source_records_and_oracle.csv').open(encoding='utf-8-sig', newline='') as handle:
        records = list(csv.DictReader(handle))
    assert len(records) == 915
    counts = {}
    for row in records:
        actual = float(cells[row['source_sheet'], row['source_response_cell']])
        assert abs(actual - float(row['response'])) < 1e-12, row
        counts[row['pool_id']] = counts.get(row['pool_id'], 0) + 1
    current = {'SH_PL40': counts['SH_PL40'], 'NH_PL36': counts['NH_PL36'], 'OH_CuNi_96': 96}
    sys.path.insert(0, str(ROOT / 'model'))
    from mixed_oh_library import construct, feature_rows, POOL
    candidates, context = construct(records)
    deposited = json.loads((ROOT / f'selections/{POOL}/candidate_manifest.json').read_text())
    assert all(deposited[k] == value for k, value in context.items())
    with (ROOT / f'selections/{POOL}/candidates.csv').open(encoding='utf-8-sig', newline='') as handle:
        deposited_candidates = list(csv.DictReader(handle))
    assert deposited_candidates == [{k: str(v) for k, v in row.items()} for row in candidates]
    assert len(candidates) == 96 and len({(r['cat'], r['base']) for r in candidates}) == 12
    assert {r['cat'] for r in candidates} == {'Cu66', 'Ni203'}
    by_sample = {r['well']: r for r in records}
    assert {'CFC124009-19-PL37-W2', 'CFC124009-19-PL38-W10'} <= {r['well'] for r in candidates}
    selected = []
    summaries = {r['pool_id']: r for r in json.loads((ROOT / 'selections/plan_summary.json').read_text())}
    for pool in ('NH_PL36', POOL):
        with (ROOT / f'selections/{pool}/selected_conditions.csv').open(encoding='utf-8-sig', newline='') as handle:
            pool_rows = list(csv.DictReader(handle))
        assert len(pool_rows) == len({r['candidate_index'] for r in pool_rows}) == summaries[pool]['selected_count']
        assert {r['pool_id'] for r in pool_rows} == {pool}
        for row in pool_rows:
            raw = by_sample[row['sample_id']]
            assert row['catalyst_code'] == raw['cat']
            assert all(row[key] == raw[key] for key in ('base', 'solvent', 'source_sheet', 'source_excel_row', 'source_response_cell'))
            assert float(row['archived_response_revealed_after_computational_selection']) == float(raw['response'])
            if pool == POOL:
                assert row['source_pool_id'] == raw['pool_id']
                assert row['source_candidate_index'] == raw['candidate_index']
                logical = candidates[int(row['candidate_index'])]
                assert logical['well'] == row['sample_id'] and logical['formulation_code'] == row['formulation_code']
        selected.extend(pool_rows)
    assert len(selected) == sum(r['selected_count'] for r in summaries.values())
    # The source peak NMR value is a directly recorded cell, distinct from the
    # fitted-yield column. Preserve the analytical response/yield distinction.
    assert float(cells['亲核试剂(SH)-条件筛选', 'AD308']) == 0.37
    from pypdf import PdfReader
    expected = {'Main_Fig5_Bayesian_optimization': (180, 265), 'SI_BO1_posterior_landscapes': (180, 146),
                'SI_BO2_uncertainty_stopping': (180, 123), 'SI_BO3_SH_replay_diagnostics': (180, 180)}
    figures = []
    for stem, dimensions in expected.items():
        base = ROOT / 'figures/figures' / stem
        assert all(base.with_suffix(ext).exists() for ext in ('.png', '.pdf', '.svg'))
        png = base.with_suffix('.png').read_bytes()
        assert png[:8] == b'\x89PNG\r\n\x1a\n'
        pixels = struct.unpack('>II', png[16:24])
        page = PdfReader(base.with_suffix('.pdf')).pages[0]
        mm = [float(page.mediabox.width) * 25.4 / 72, float(page.mediabox.height) * 25.4 / 72]
        assert all(abs(a - b) < .01 for a, b in zip(mm, dimensions))
        assert all(abs(px - mm / 25.4 * 600) < 2 for px, mm in zip(pixels, dimensions))
        figures.append(dict(stem=stem, png_pixels=pixels, dimensions_mm=mm, exports=3))
    report = dict(status='passed', split_workbook=split, physical_response_cells_verified=len(records), historical_pool_counts=counts,
                  current_condition_libraries=current, conditions_in_current_three_libraries=288,
                  selected_NH_OH_responses_used_for_models=len(selected), OH_formulation_library=deposited,
                  figures=figures,
                  environment=dict(python=sys.version, platform=platform.platform()),
                  limitations=['Workbook metadata is not dated laboratory execution chronology.',
                               'Only SH peak has matched 37% NMR; analytical responses are not calibrated yields.',
                               '100 final candidate molecules, 100 paired SH seeds and 96-condition grids are different counting units.'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/reaction-data-check.json'))
    main(parser.parse_args().output)
