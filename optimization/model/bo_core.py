"""Small dependency-free Bayesian batch-optimization core used by v2 replay."""
from __future__ import annotations

import random
import re
from typing import Iterable

import numpy as np


def smiles_counts(smiles: str):
    """Count elemental and aromatic atom tokens without a chemistry toolkit."""
    s = str(smiles or "")
    tokens = re.findall(r"Br|Cl|Si|Na|Mg|Ca|Li|Al|Fe|Co|Ni|Cu|Ag|Pd|Pt|Rh|Ru|Ir|Au|Zn|[BCNOPSFIbcnops]", s)
    out = {}
    for token in tokens:
        out[token] = out.get(token, 0) + 1
    return out


def first_hit_budget(batches: Iterable[Iterable[int]], target_indices: set[int]):
    """Return the end-of-batch budget of the first batch containing a target."""
    target = set(target_indices)
    if not target:
        return None
    budget = 0
    for batch in batches:
        batch = list(batch)
        budget += len(batch)
        if target.intersection(batch):
            return budget
    return None


def _posterior_components(K, selected, y):
    K = np.asarray(K, dtype=float)
    selected = list(selected)
    if selected:
        ys = np.asarray([y[i] for i in selected], dtype=float)
        center = float(np.mean(ys))
        scale = float(np.std(ys))
        if scale <= 1e-12:
            scale = 1.0
        z = (ys - center) / scale
        Kss = K[np.ix_(selected, selected)]
        A = np.eye(len(selected)) + Kss
        alpha = np.linalg.solve(A, z)
        latent = np.diag(K) - np.einsum("ij,ji->i", K[:, selected] @ np.linalg.solve(A, np.eye(len(selected))), K[selected, :])
        latent = np.maximum(latent, 0.0)
        a = 2.0 + len(selected) / 2.0
        b = 1.0 + 0.5 * (float(z @ z) - float(z @ Kss @ alpha))
        variance_scale = max(b / max(a - 1.0, 1e-12), 1e-12)
        mean = center + scale * (K[:, selected] @ alpha)
        std = scale * np.sqrt(variance_scale * latent)
        return mean, std
    center = 0.0
    scale = 1.0
    return center + np.zeros(K.shape[0]), np.sqrt(np.maximum(np.diag(K), 0.0))


def posterior(K, selected, y):
    """Posterior latent mean and standard deviation for all candidates."""
    return _posterior_components(K, selected, y)


def run_campaign(K, y, seed, strategy, n_init=12, batch_size=12):
    """Run a finite-pool batch policy while revealing labels only after selection."""
    K = np.asarray(K, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    rng = random.Random(int(seed))
    initial = rng.sample(range(n), min(n_init, n))
    selected = set(initial)
    batches = [list(initial)]
    scores = [{"round": 1, "indices": list(initial), "mean": [], "std": [], "acquisition": []}]
    while len(selected) < n:
        remaining = [i for i in range(n) if i not in selected]
        if strategy == "random":
            rng.shuffle(remaining)
            pick = remaining[: min(batch_size, len(remaining))]
            mean = std = acquisition = np.array([])
        elif strategy == "BO-UCB":
            mean_all, std_all = posterior(K, sorted(selected), y)
            jitter = np.asarray([rng.random() for _ in range(n)]) * 1e-12
            acquisition_all = mean_all + 1.96 * std_all + jitter
            pick = sorted(remaining, key=lambda i: (-float(acquisition_all[i]), i))[: min(batch_size, len(remaining))]
            mean, std, acquisition = mean_all[pick], std_all[pick], acquisition_all[pick]
        else:
            raise ValueError(f"unknown strategy: {strategy}")
        if not pick:
            break
        batches.append(list(pick))
        selected.update(pick)
        scores.append({"round": len(batches), "indices": list(pick), "mean": np.asarray(mean).tolist(), "std": np.asarray(std).tolist(), "acquisition": np.asarray(acquisition).tolist()})
    best = []
    running = -float("inf")
    for batch in batches:
        running = max(running, float(np.max(y[batch])))
        best.extend([running] * len(batch))
    return {"seed": int(seed), "strategy": strategy, "batches": batches, "scores": scores, "best_by_budget": best}
