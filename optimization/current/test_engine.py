"""Focused tests for the current 13,920-condition recommendation engine."""

import unittest
from unittest.mock import patch

import numpy as np

import engine


def config(weights=engine.EQUAL_WEIGHTS, rho=0.9, beta=1.96):
    return {'weights': weights, 'rho': rho, 'beta': beta}


def observations():
    # Include both endpoints and separated catalysts, solvents and bases.
    return {0: 0.4, 11: 1.2, 12: 0.6, 95: 2.0, 17 * 96 + 7: 0.8,
            engine.N - 1: 1.4}


class InitializationTests(unittest.TestCase):
    def test_initialization_samples_full_space_without_replacement(self):
        first = engine.initialize(np.random.default_rng(17))
        second = engine.initialize(np.random.default_rng(17))

        self.assertEqual(first, second)
        self.assertEqual(len(first), engine.N_INIT)
        self.assertEqual(len(set(first)), engine.N_INIT)
        self.assertTrue(all(0 <= index < engine.N for index in first))
        self.assertGreater(max(first), engine.N // 2)


class PosteriorTests(unittest.TestCase):
    def test_compression_matches_direct_full_space_for_allowed_kernel_settings(self):
        observed = observations()
        for weights in (engine.EQUAL_WEIGHTS, engine.CATALYST_WEIGHTS):
            for rho in engine.ALLOWED_RHOS:
                with self.subTest(weights=weights, rho=rho):
                    settings = config(weights, rho)
                    compressed = engine.posterior(observed, settings)
                    direct = engine.posterior(observed, settings, compressed=False)
                    for actual, expected in zip(compressed, direct):
                        self.assertEqual(actual.shape, (engine.N,))
                        np.testing.assert_allclose(actual, expected, rtol=1e-11, atol=1e-12)

    def test_compression_matches_direct_when_every_catalyst_is_observed(self):
        observed = {catalyst * 96 + catalyst % 96: float(np.cos(catalyst))
                    for catalyst in range(145)}
        compressed = engine.posterior(observed, config(engine.CATALYST_WEIGHTS))
        direct = engine.posterior(observed, config(engine.CATALYST_WEIGHTS), compressed=False)

        for actual, expected in zip(compressed, direct):
            np.testing.assert_allclose(actual, expected, rtol=1e-11, atol=1e-12)

    def test_single_response_has_closed_form_mean_and_latent_uncertainty(self):
        mean, sd = engine.posterior({0: 42.0}, config())

        # Centering gives zero standardized feedback, with unit scale fallback.
        np.testing.assert_array_equal(mean, np.full(engine.N, 42.0))
        self.assertTrue(np.isfinite(sd).all())
        # Unit noise gives latent variance 6 - 6**2 / 7 at the observation;
        # the conjugate variance multiplier is 1 / (2.5 - 1) = 2/3.
        self.assertAlmostEqual(sd[0], np.sqrt(4.0 / 7.0))
        # Catalyst 1, solvent 1, base 1 shares no factor with condition 0.
        self.assertAlmostEqual(sd[96 + 12 + 1], 2.0)

    def test_posterior_respects_response_units_and_dictionary_order(self):
        observed = observations()
        original = observed.copy()
        mean, sd = engine.posterior(observed, config())
        shifted = {index: 4.0 * value + 10.0
                   for index, value in reversed(list(observed.items()))}
        shifted_mean, shifted_sd = engine.posterior(shifted, config())

        np.testing.assert_allclose(shifted_mean, 4.0 * mean + 10.0, rtol=1e-12)
        np.testing.assert_allclose(shifted_sd, 4.0 * sd, rtol=1e-12)
        self.assertEqual(observed, original)

    def test_invalid_observed_feedback_is_rejected(self):
        for observed in ({}, {-1: 1.0}, {engine.N: 1.0},
                         {0: np.nan}, {0: np.inf}, {0: -np.inf}):
            with self.subTest(observed=observed):
                with self.assertRaises(AssertionError):
                    engine.posterior(observed, config())


class RecommendationTests(unittest.TestCase):
    def test_simultaneous_batch_ranks_full_space_and_excludes_observations(self):
        observed = {3: 1.0, engine.N - 1: 2.0, engine.N - 3: 3.0}
        settings = config()
        mean = np.arange(engine.N, dtype=float)
        mean[list(observed)] = 1e6
        sd = np.zeros(engine.N)

        with patch.object(engine, 'posterior', return_value=(mean, sd)) as posterior:
            picks, means, sds, scores = engine.propose(observed, settings, 17)

        # One fit uses precisely the supplied observations for the entire batch.
        posterior.assert_called_once_with(observed, settings)
        self.assertEqual(picks, [engine.N - 2, engine.N - 4, engine.N - 5, engine.N - 6])
        self.assertFalse(set(picks).intersection(observed))
        self.assertEqual(means, mean[picks].tolist())
        self.assertEqual(sds, sd[picks].tolist())
        np.testing.assert_allclose(scores, mean[picks], rtol=0, atol=2e-12)

    def test_seeded_ties_consume_one_draw_per_full_space_candidate(self):
        seed = 29
        expected_rng = np.random.default_rng(seed)
        jitter = expected_rng.random(engine.N) * 1e-12
        observed = {int(np.argmax(jitter)): 1.0, 0: 0.5}
        expected = sorted((index for index in range(engine.N) if index not in observed),
                          key=lambda index: jitter[index], reverse=True)[:engine.BATCH_SIZE]
        rng = np.random.default_rng(seed)

        with patch.object(engine, 'posterior',
                          return_value=(np.zeros(engine.N), np.zeros(engine.N))):
            picks, _, _, scores = engine.propose(observed, config(), rng)

        self.assertEqual(picks, expected)
        self.assertEqual(scores, jitter[picks].tolist())
        self.assertEqual(rng.random(), expected_rng.random())

    def test_recommendations_are_reproducible_from_observed_feedback_only(self):
        observed = observations()
        original = observed.copy()
        settings = config(engine.CATALYST_WEIGHTS)
        first = engine.propose(observed, settings, 17)
        second = engine.propose(dict(reversed(list(observed.items()))), settings,
                                np.random.default_rng(17))

        self.assertEqual(first, second)
        self.assertEqual(observed, original)
        picks, means, sds, scores = first
        self.assertEqual(len(picks), engine.BATCH_SIZE)
        self.assertEqual(len(set(picks)), engine.BATCH_SIZE)
        self.assertFalse(set(picks).intersection(observed))
        # Check the actual recommendation against the uncompressed posterior.
        mean, sd = engine.posterior(observed, settings, compressed=False)
        np.testing.assert_allclose(means, mean[picks], rtol=1e-11, atol=1e-12)
        np.testing.assert_allclose(sds, sd[picks], rtol=1e-11, atol=1e-12)
        acquisition = mean + settings['beta'] * sd
        eligible = [index for index in range(engine.N) if index not in observed]
        threshold = sorted(acquisition[eligible], reverse=True)[engine.BATCH_SIZE - 1]
        self.assertGreaterEqual(min(acquisition[picks]), threshold - 1e-12)
        self.assertTrue(np.all(np.asarray(scores) >= acquisition[picks] - 1e-14))
        self.assertTrue(np.all(np.asarray(scores) < acquisition[picks] + 1.01e-12))


if __name__ == '__main__':
    unittest.main()
