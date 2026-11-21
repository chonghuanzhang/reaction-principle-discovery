#!/usr/bin/env python3
"""Label-blind, NumPy-only initialization, posterior and UCB recommendations.

No function loads experimental data, target labels or availability. New initial
batches sample the complete 13,920-condition space; later batches rank every
remaining condition. Historical verification reads its round-0 indices from the
deposited campaign records.
"""
from __future__ import annotations

import math
import sys

import numpy as np

sys.dont_write_bytecode = True

N = 145 * 8 * 12
N_INIT = 12
BATCH_SIZE = 4
C = np.repeat(np.arange(145), 96)
S = np.tile(np.repeat(np.arange(8), 12), 145)
B = np.tile(np.arange(12), 145 * 8)
FACTOR_CODES = np.column_stack((C, S, B))
EQUAL_WEIGHTS = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
CATALYST_WEIGHTS = (1.5, 0.3, 0.3, 1.8, 1.8, 0.3)
ALLOWED_RHOS = (0.8, 0.85, 0.9, 0.95)
ALLOWED_BETAS = (0.5, 1.0, 1.96, 3.0)


def _rng(seed_or_rng):
    if isinstance(seed_or_rng, np.random.Generator):
        assert isinstance(seed_or_rng.bit_generator, np.random.PCG64)
        return seed_or_rng
    return np.random.default_rng(int(seed_or_rng))


def _parameters(config):
    weights = tuple(map(float, config['weights']))
    assert len(weights) == 6 and all(math.isfinite(w) and w >= 0 for w in weights)
    assert math.isclose(sum(weights), 6.0, rel_tol=0, abs_tol=1e-12)
    assert weights in (EQUAL_WEIGHTS, CATALYST_WEIGHTS)
    rho, beta = float(config['rho']), float(config['beta'])
    assert rho in ALLOWED_RHOS and beta in ALLOWED_BETAS
    return weights, rho, beta


def initialize(rng):
    """Select 12 unique conditions uniformly from the full decision space."""
    return _rng(rng).choice(N, size=N_INIT, replace=False).tolist()


def kernel(left_codes, right_codes, config):
    """Weighted main/pairwise kernel plus independent whole-condition effect.

    Terms are ordered C,S,B,CS,CB,SB. The diagonal value of 6 is independent of the candidate,
    label status, rho and the two permitted shared-weight allocations.
    """
    weights, rho, _ = _parameters(config)
    left = np.asarray(left_codes, dtype=int)
    right = np.asarray(right_codes, dtype=int)
    assert left.ndim == right.ndim == 2 and left.shape[1] == right.shape[1] == 3
    eq = [left[:, j, None] == right[None, :, j] for j in range(3)]
    shared = sum(weights[j]*eq[j].astype(float) for j in range(3))
    shared += weights[3]*(eq[0] & eq[1]).astype(float)
    shared += weights[4]*(eq[0] & eq[2]).astype(float)
    shared += weights[5]*(eq[1] & eq[2]).astype(float)
    local = eq[0] & eq[1] & eq[2]
    return (1.0-rho)*shared + (6.0*rho)*local


def posterior(observed, config, compressed=True):
    """Full 13,920-condition latent posterior from currently selected responses only.

    Response centering/population-SD normalization, unit observation noise and
    the conjugate posterior match the recorded engine. Compression
    groups unseen catalyst classes by exact equality-kernel equivalence and
    expands the result before any acquisition ranking.
    """
    _parameters(config)
    selected = np.array(sorted(map(int, observed)), dtype=int)
    assert len(selected) > 0 and len(selected) == len(set(selected.tolist()))
    assert np.all((selected >= 0) & (selected < N))
    ys = np.array([observed[int(i)] for i in selected], dtype=float)
    assert np.isfinite(ys).all()
    center = float(ys.mean())
    scale = float(ys.std(ddof=0))
    if scale <= 1e-12:
        scale = 1.0
    z = (ys-center)/scale
    seen = FACTOR_CODES[selected]
    kss = kernel(seen, seen, config)
    inverse = np.linalg.solve(np.eye(len(selected))+kss, np.eye(len(selected)))
    alpha = inverse @ z
    if compressed:
        cats = np.unique(seen[:, 0])
        unseen = np.setdiff1d(np.arange(145), cats)
        classes = np.r_[cats, unseen[:1]]
        queries = np.repeat(classes, 96)*96 + np.tile(np.arange(96), len(classes))
        mapping = np.full(145, len(cats), dtype=int)
        mapping[cats] = np.arange(len(cats))
        expand = mapping[C]*96 + S*12 + B
    else:
        queries = np.arange(N)
        expand = queries
    cross = kernel(FACTOR_CODES[queries], seen, config)
    mean = center + scale*(cross @ alpha)
    latent = np.maximum(6.0-np.einsum('ij,ij->i', cross @ inverse, cross), 0.0)
    a = 2.0 + len(selected)/2.0
    b = 1.0 + 0.5*(float(z @ z)-float(z @ kss @ alpha))
    variance_scale = max(b/max(a-1.0, 1e-12), 1e-12)
    sd = scale*np.sqrt(variance_scale*latent)
    return mean[expand], sd[expand]


def propose(observed, config, rng):
    """Rank all unselected conditions and return the simultaneous top-four UCB batch.

    Jitter draws 13,920 PCG64 values each batch. Acquisition then excludes only
    previously selected indices; unselected responses are never model inputs.
    """
    _, _, beta = _parameters(config)
    mean, sd = posterior(observed, config)
    scores = mean + beta*sd + _rng(rng).random(N)*1e-12
    eligible_scores = scores.copy()
    eligible_scores[list(observed)] = -np.inf
    picks = np.argsort(-eligible_scores, kind='stable')[:BATCH_SIZE].tolist()
    return picks, mean[picks].tolist(), sd[picks].tolist(), scores[picks].tolist()
