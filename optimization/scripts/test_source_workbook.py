"""Exercise current provenance checks against isolated copies of real records."""

import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CurrentSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        files = [
            'optimization/raw/summary_workbook.xlsx',
            'optimization/raw/workbooks_manifest.json',
            'optimization/current/protocol.json',
            'optimization/current/source_data/selected_response_source.csv',
            'experiments/selected_responses/selected_responses.csv',
            'experiments/selected_responses/selected_responses.json',
        ]
        files += [str(p.relative_to(ROOT)) for p in
                  (ROOT / 'optimization/current/data').rglob('*.csv')]
        for system in ('NH', 'OH', 'SH'):
            files += [f'optimization/current/runs/{system}/{name}' for name in
                      ('trajectory.json', 'trajectory_conditions.csv')]
        module = ROOT / 'optimization/scripts/source_workbook.py'
        if module.exists():
            files.append(str(module.relative_to(ROOT)))
        for name in files:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)

    def check(self):
        return subprocess.run(
            [sys.executable, '-B', '-c',
             'import json,sys;sys.path.insert(0,sys.argv[1]);'
             'from source_workbook import check_current_sources;'
             'print(json.dumps(check_current_sources()))',
             str(self.root / 'optimization/scripts')],
            capture_output=True, text=True, check=False)

    def edit_csv(self, name, edit):
        path = self.root / name
        with path.open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
        edit(rows)
        with path.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def assert_rejected(self, diagnostic):
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(diagnostic, result.stderr)

    def test_checks_current_records_without_archived_tables(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['measured_candidates_by_system'],
                         {'NH': 240, 'OH': 335, 'SH': 335})
        self.assertEqual(report['physical_source_records_verified'], 915)
        self.assertEqual(report['measured_candidates_verified'], 910)
        self.assertEqual(report['selected_trajectory_rows_verified'], 164)
        self.assertEqual(report['table_R4_rows_verified'], 164)

    def test_rejects_changed_candidate_response(self):
        def alter(rows):
            rows[16]['UV_response'] = '123456.789'
        self.edit_csv('optimization/current/data/NH/candidate_space.csv', alter)
        self.assert_rejected('UV_response')

    def test_rejects_matching_response_from_wrong_physical_condition(self):
        def alter(rows):
            rows[16].update(source_excel_row='3', source_response_cell='AJ3',
                            UV_response='1.54697139066581', source_well='PL35-W2')
        self.edit_csv('optimization/current/data/NH/candidate_space.csv', alter)
        self.assert_rejected('source')

    def test_rejects_duplicate_table_R4_condition(self):
        def alter(rows):
            rows[-1] = dict(rows[0])
        self.edit_csv('experiments/selected_responses/selected_responses.csv', alter)
        self.assert_rejected('duplicate')

    def test_rejects_table_R4_json_disagreement(self):
        path = self.root / 'experiments/selected_responses/selected_responses.json'
        rows = json.loads(path.read_text(encoding='utf-8'))
        rows[0]['UV_response'] = '123456.789'
        path.write_text(json.dumps(rows), encoding='utf-8')
        self.assert_rejected('Table R4 JSON')

    def test_rejects_changed_trajectory_identity(self):
        def alter(rows):
            rows[0]['cat'] = 'wrong-catalyst'
        self.edit_csv('optimization/current/runs/OH/trajectory_conditions.csv', alter)
        self.assert_rejected('cat')

    def test_rejects_changed_superseded_source_response(self):
        def alter(rows):
            rows[0]['UV_response'] = '123456.789'
        self.edit_csv('optimization/current/data/source_conflicts.csv', alter)
        self.assert_rejected('UV_response')


if __name__ == '__main__':
    unittest.main()
