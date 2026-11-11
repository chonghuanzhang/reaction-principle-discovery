"""Check the reference-informed library and physical measurement boundary."""
import copy
import unittest
from collections import Counter

import numpy as np
import mixed_oh_library as library


class MixedOHLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = library.read_csv(library.ROOT / 'benchmark/data/source_records_and_oracle.csv')
        cls.rows, cls.manifest = library.construct(cls.source)

    def test_exact_crossed_library_and_reference_recipes(self):
        self.assertEqual(len(self.rows), 96)
        self.assertEqual(len({r['well'] for r in self.rows}), 96)
        self.assertEqual(Counter(r['formulation_code'] for r in self.rows), {f'F{i}': 8 for i in range(1, 13)})
        self.assertEqual({r['cat'] for r in self.rows}, {'Cu66', 'Ni203'})
        self.assertTrue({'CFC124009-19-PL37-W2', 'CFC124009-19-PL38-W10'} <= {r['well'] for r in self.rows})
        self.assertEqual(sum(r['selection_method'] == 'mandatory_reference' for r in self.manifest['formulations']), 2)

    def test_random_ten_do_not_read_responses(self):
        altered = copy.deepcopy(self.source)
        for i, row in enumerate(altered):
            row['response'] = str(100000 - i)
        candidates, manifest = library.construct(altered)
        self.assertEqual(candidates, self.rows)
        self.assertEqual(manifest, self.manifest)
        self.assertEqual(candidates, library.construct(self.source)[0])

    def test_provenance_preserves_every_physical_recipe(self):
        source = {r['well']: r for r in self.source}
        for row in self.rows:
            raw = source[row['well']]
            self.assertNotIn('response', row)
            self.assertEqual(row['source_pool_id'], raw['pool_id'])
            self.assertEqual(row['source_candidate_index'], raw['candidate_index'])
            for key in ('cat', 'ligand', 'base', 'solvent', 'source_sheet', 'source_excel_row', 'source_response_cell', 'source_workbook_sha256'):
                self.assertEqual(row[key], raw[key])

    def test_features_encode_formulation_not_base_alone(self):
        rows = library.feature_rows(self.rows)
        columns = [k for k in rows[0] if k not in ('candidate_index', 'well')]
        X = np.asarray([[r[k] for k in columns] for r in rows])
        self.assertEqual(X.shape, (96, 116))
        np.testing.assert_allclose(X.mean(axis=0), 0, atol=1e-14)
        np.testing.assert_allclose(X.std(axis=0), 1, atol=1e-14)
        # Equal base/solvent under Cu and Ni must still have different features.
        indices = [i for i, r in enumerate(self.rows) if r['base'] == 'DIPEA' and r['solvent'] == 'DCE']
        self.assertEqual(len(indices), 2)
        self.assertFalse(np.array_equal(X[indices[0]], X[indices[1]]))


if __name__ == '__main__':
    unittest.main()
