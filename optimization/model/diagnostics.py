"""Independent SH diagnostic policies using the published model equations."""
import random
import numpy as np

def kernel(rows, pairs=True):
    levels = {k: sorted({r[k] for r in rows}) for k in ['base', 'solvent']}
    X = np.array([[*[r['base'] == v for v in levels['base']], *[r['solvent'] == v for v in levels['solvent']], *([r['base'] == b and r['solvent'] == s for b in levels['base'] for s in levels['solvent']] if pairs else [])] for r in rows], dtype=float)
    sd = X.std(axis=0)
    sd[sd <= 1e-12] = 1
    X = (X - X.mean(axis=0)) / sd
    return (X, X @ X.T)

def posterior(K, observed):
    ids = sorted(observed)
    ys = np.array([observed[i] for i in ids])
    mean = ys.mean()
    sd = ys.std()
    sd = 1 if sd <= 1e-12 else sd
    z = (ys - mean) / sd
    Ks = K[np.ix_(ids, ids)]
    A = np.eye(len(ids)) + Ks
    alpha = np.linalg.solve(A, z)
    variance = np.diag(K) - np.sum(K[:, ids] * np.linalg.solve(A, K[ids, :]).T, axis=1)
    a = 2 + len(ids) / 2
    b = 1 + 0.5 * (z @ z - z @ Ks @ alpha)
    return (mean + sd * (K[:, ids] @ alpha), sd * np.sqrt(np.maximum(variance, 0) * max(b / (a - 1), 1e-12)))

def campaign(rows, seed, strategy='bo', max_n=96, coef=1.96, pairs=True):
    X, K = kernel(rows, pairs)
    rng = random.Random(seed)
    observed = {}
    batches = []
    checks = []
    hist = []
    streak = 0
    while len(observed) < max_n:
        remaining = [i for i in range(len(rows)) if i not in observed]
        if not observed:
            pick = rng.sample(range(len(rows)), 12)
        elif strategy == 'random':
            rng.shuffle(remaining)
            pick = remaining[:12]
        else:
            mu, sd = posterior(K, observed)
            acq = mu + coef * sd + np.array([rng.random() for _ in rows]) * 1e-12
            pick = sorted(remaining, key=lambda i: (-float(acq[i]), i))[:12]
        batches.append(pick)
        observed.update({i: float(rows[i]['response']) for i in pick})
        best = max(observed.values())
        hist.append(best)
        if len(observed) == 12:
            delta = 0.1 * np.std(list(observed.values()))
        if max_n == 60:
            mu, sd = posterior(K, observed)
            rem = [i for i in range(len(rows)) if i not in observed]
            upper = max((mu[i] + 1.96 * sd[i] for i in rem))
            improvement = best - hist[-3] if len(hist) >= 3 else None
            joint = len(observed) >= 36 and delta > 1e-13 and (improvement <= delta) and (upper <= best + delta)
            streak = streak + 1 if joint else 0
            checks.append(dict(batch=len(batches), n=len(observed), best=best, delta=delta, improvement=improvement, ucb_gap=upper - best, joint=bool(joint), streak=streak))
            if streak >= 2:
                break
    y = np.array([float(r['response']) for r in rows])
    target = set(np.flatnonzero(y >= max(y) - 1e-12)) if max_n == 96 else set()
    budget = next((12 * (i + 1) for i, b in enumerate(batches) if target.intersection(b)), None)
    return (batches, checks, budget)
