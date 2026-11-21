"""Focused tests for the current 13,920-condition recommendation engine."""

import unittest

import numpy as np

import engine


class InitializationTests(unittest.TestCase):
    def test_initialization_samples_full_space_without_replacement(self):
        first = engine.initialize(np.random.default_rng(17))
        second = engine.initialize(np.random.default_rng(17))

        self.assertEqual(first, second)
        self.assertEqual(len(first), engine.N_INIT)
        self.assertEqual(len(set(first)), engine.N_INIT)
        self.assertTrue(all(0 <= index < engine.N for index in first))
        self.assertGreater(max(first), 335)


if __name__ == '__main__':
    unittest.main()
