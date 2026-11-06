import unittest
import numpy as np

import bo_core as bo


class BOIntegrityTests(unittest.TestCase):
    def test_batch_budget_counts_initial_and_tail(self):
        batches = [[0, 1, 2], [3, 4, 5], [6]]
        self.assertEqual(bo.first_hit_budget(batches, {1}), 3)
        self.assertEqual(bo.first_hit_budget(batches, {3}), 6)
        self.assertEqual(bo.first_hit_budget(batches, {6}), 7)
        self.assertIsNone(bo.first_hit_budget(batches, set()))

    def test_threshold_first_hit_distinct_from_exact(self):
        y = np.array([0.96, 0, 0.3, 1, 0, 0])
        batches = [[0, 1, 2], [3, 4, 5]]
        self.assertEqual(bo.first_hit_budget(batches, set(np.where(y >= 0.95)[0])), 3)
        self.assertEqual(bo.first_hit_budget(batches, {3}), 6)

    def test_paired_initial_and_unique_exhaustion(self):
        K = 10 + np.eye(29)
        y = np.arange(29, dtype=float)
        for seed in range(5):
            a = bo.run_campaign(K, y, seed, 'BO-UCB', n_init=6, batch_size=6)
            b = bo.run_campaign(K, y, seed, 'random', n_init=6, batch_size=6)
            self.assertEqual(a['batches'][0], b['batches'][0])
            self.assertEqual(sorted(sum(a['batches'], [])), list(range(29)))
            self.assertEqual(sorted(sum(b['batches'], [])), list(range(29)))
            self.assertEqual(len(a['batches'][-1]), 5)

    def test_future_labels_cannot_change_current_batch(self):
        X = np.array([[1, i / 30, np.sin(i)] for i in range(30)])
        K = X @ X.T + np.eye(30)
        y = np.arange(30, dtype=float)
        a = bo.run_campaign(K, y, 3, 'BO-UCB', n_init=6, batch_size=6)
        altered = y.copy()
        hidden = sorted(set(range(30)) - set(a['batches'][0]))
        altered[hidden] = 10000 - altered[hidden]
        b = bo.run_campaign(K, altered, 3, 'BO-UCB', n_init=6, batch_size=6)
        self.assertEqual(a['batches'][:2], b['batches'][:2])
        np.testing.assert_allclose(a['scores'][1]['mean'], b['scores'][1]['mean'])

    def test_reproducibility(self):
        K = 10 + np.eye(25)
        y = np.linspace(0, 1, 25)
        a = bo.run_campaign(K, y, 2, 'BO-UCB', n_init=5, batch_size=5)
        b = bo.run_campaign(K, y, 2, 'BO-UCB', n_init=5, batch_size=5)
        self.assertEqual(a['batches'], b['batches'])

    def test_kernel_posterior_matches_primal(self):
        X = np.array([[1, 0], [1, 1], [1, 2]], dtype=float)
        K = X @ X.T
        idx = [0, 1]
        y = np.array([2., 4.])
        m, s = bo.posterior(K, idx, y)
        z = (y - y.mean()) / y.std()
        V = np.linalg.inv(np.eye(2) + X[idx].T @ X[idx])
        beta = V @ X[idx].T @ z
        a = 2 + len(idx) / 2
        b = 1 + (z @ z - beta @ np.linalg.inv(V) @ beta) / 2
        np.testing.assert_allclose(m, y.mean() + y.std() * X @ beta, atol=1e-10)
        np.testing.assert_allclose(s, y.std() * np.sqrt(b / (a - 1) * np.einsum('ij,jk,ik->i', X, V, X)), atol=1e-10)

    def test_smiles_case_and_contiguous_atoms(self):
        counts = bo.smiles_counts('COCCOC.[Ni+2].[Cl-].[Cl-]')
        self.assertEqual(counts['C'], 4)
        self.assertEqual(counts['O'], 2)
        self.assertEqual(counts['Ni'], 1)
        self.assertEqual(counts['Cl'], 2)
        self.assertEqual(bo.smiles_counts('c1ccccc1')['c'], 6)
        self.assertEqual(bo.smiles_counts('[Co+2]')['Co'], 1)

    def test_ties_do_not_favor_first_rows(self):
        K = 10 + np.eye(60)
        y = np.zeros(60)
        selections = []
        for seed in range(30):
            r = bo.run_campaign(K, y, seed, 'BO-UCB', n_init=6, batch_size=6)
            selections.extend(r['batches'][1])
        self.assertGreater(len(set(selections)), 40)


if __name__ == '__main__':
    unittest.main()
