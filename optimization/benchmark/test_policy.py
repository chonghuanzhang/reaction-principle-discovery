"""Meaningful policy-boundary and archive checks; upstream tests are retained separately."""
import importlib.util
import inspect
import unittest

import numpy as np


class ArchiveTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.find_spec('replay')
        self.assertIsNotNone(spec, 'archive replay module must implement the observable-only interface')
        import replay
        return replay

    def test_policy_matches_upstream_campaign(self):
        a = self.module()
        X = np.array([[1, i / 30, np.sin(i)] for i in range(29)])
        K = X @ X.T
        y = np.arange(29, dtype=float)
        for strategy in ['BO-UCB', 'random']:
            for seed in [3, 42]:
                expected = a.v2.bo_core.run_campaign(K, y, seed, strategy, 6, 6)
                actual, _ = a.replay(K, y, seed, strategy, 6, 6, reference=True)
                self.assertEqual(expected, actual)

    def test_optimizer_interface_has_only_observed_labels(self):
        a = self.module()
        self.assertEqual(list(inspect.signature(a.ObservablePolicy).parameters), ['K', 'seed', 'strategy', 'n_init', 'batch_size'])
        p = a.ObservablePolicy(np.eye(25), 3, 'BO-UCB', 6, 6)
        pick, _ = p.propose()
        with self.assertRaises(ValueError):
            p.observe({i: 100.0 for i in range(25)})
        p.observe({i: float(i) for i in pick})
        self.assertEqual(set(p.observed), set(pick))
        self.assertFalse(hasattr(p, 'y'))
        self.assertFalse(hasattr(p, 'oracle'))

    def test_hidden_labels_cannot_change_current_decision_or_candidate_scores(self):
        a = self.module()
        K = 2 + np.eye(30)
        y = np.arange(30, dtype=float)
        r1, d1 = a.replay(K, y, 11, 'BO-UCB', 6, 6, reference=True)
        mutated = y.copy()
        for i in set(range(30)) - set(r1['batches'][0]):
            mutated[i] = -1e8 * i
        r2, d2 = a.replay(K, mutated, 11, 'BO-UCB', 6, 6, reference=True)
        self.assertEqual(r1['batches'][:2], r2['batches'][:2])
        self.assertEqual(d1[:2], d2[:2])
        for rows in d1:
            for row in rows:
                self.assertNotIn('response', row)

    def test_exact_target_does_not_alias_unverified_names(self):
        a = self.module()
        lhs = {'cat': 'Cu9', 'ligand': 'PPh3', 'base': 'CsOH', 'solvent': 'DCE'}
        rhs = dict(lhs, base='CsOH/2')
        self.assertNotEqual(a.exact_key(lhs), a.exact_key(rhs))
        self.assertNotEqual(a.exact_key(dict(lhs, solvent='DIO')), a.exact_key(dict(lhs, solvent='1,4-dioxane')))

    def test_bootstrap_is_interval_for_paired_mean_not_median(self):
        a = self.module()
        bo = [12, 12, 12, 12, 12]
        rnd = [12, 12, 12, 12, 96]
        s = a.extended_metric(bo, rnd, 96)
        dif = np.array(rnd) - bo
        means = np.random.default_rng(42).choice(dif, size=(2000, 5), replace=True).mean(axis=1)
        np.testing.assert_array_equal(s['paired_mean_saving_bootstrap_95ci'], np.quantile(means, [0.025, 0.975]))
        self.assertEqual(s['mean_saving_random_minus_bo'], 16.8)
        self.assertEqual(s['median_saving_random_minus_bo'], 0.0)

    def test_reference_has_all_remaining_candidates_and_batch_trajectories(self):
        a = self.module()
        run, rows = a.replay(np.eye(25), np.arange(25), 7, 'BO-UCB', 6, 6, reference=True)
        seen = set()
        budget = 0
        for batch, candidates in zip(run['batches'], rows):
            self.assertEqual({r['candidate_index'] for r in candidates}, set(range(25)) - seen)
            self.assertEqual({r['candidate_index'] for r in candidates if r['selected']}, set(batch))
            self.assertTrue(all(r['observed_count'] == budget for r in candidates))
            seen.update(batch)
            budget += len(batch)
        self.assertEqual(sorted(seen), list(range(25)))

    def test_physical_rows_resolve_only_screening_sheets(self):
        a = self.module()
        if not a.v2.v1.BOOK.exists():
            self.skipTest('physical Excel row verification requires the original workbook')
        lookup = a.workbook_row_lookup(a.v2.v1.BOOK)
        self.assertTrue(lookup)
        self.assertEqual({sheet for sheet, well in lookup}, {v['sheet'] for v in a.v2.ROUTES.values()})

    def test_portable_records_rebuild_original_pools(self):
        a = self.module()
        initial = [{'well': 'PL33-W1', 'response': .5, 'catalyst': 'Cu9', 'smiles': '[Cu]', 'condition': {'cat': 'Cu9', 'ligand': 'PPh3', 'base': 'CsOH', 'solvent': 'DIO'}}]
        grids = {'PL39': [{'well': 'PL39-W1', 'response': .3, 'catalyst': 'Ag6', 'smiles': '[Ag]', 'cat': 'Ag6', 'ligand': 'PPh3', 'base': 'CsOH/2', 'solvent': 'DCE'}], 'PL40': [{'well': 'PL40-W1', 'response': .6, 'catalyst': 'Cu9', 'smiles': '[Cu]', 'cat': 'Cu9', 'ligand': 'PPh3', 'base': 'CsOH/2', 'solvent': 'DCE'}]}
        rows = []
        for stage, plate, records in [('catalyst_panel', 'PL33', initial)] + [('condition_grid', p, r) for p, r in grids.items()]:
            for i, record in enumerate(records):
                conditions = record['condition'] if stage == 'catalyst_panel' else {k: record[k] for k in ['cat', 'ligand', 'base', 'solvent']}
                rows.append({'route': 'SH', 'stage': stage, 'plate': plate, 'candidate_index': str(i), 'well': record['well'], 'response': str(record['response']), 'catalyst': record['catalyst'], 'smiles': record['smiles'], **conditions})
        self.assertTrue(hasattr(a, 'pools_from_records'), 'portable source CSV reader required')
        rebuilt = a.pools_from_records(rows, 'SH')
        self.assertEqual((initial, grids), rebuilt)


if __name__ == '__main__':
    unittest.main()
