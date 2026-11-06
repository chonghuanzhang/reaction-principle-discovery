#!/usr/bin/env python3
"""Reproduce current Figure 5 analysis using frozen code and selected observations.

Adapters change filesystem locations only. They do not alter posterior, acquisition,
RNG, stopping rules, or recorded measurements. Outputs are written separately.
"""
from pathlib import Path
import argparse
import csv
import importlib.util
import json
import platform
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'benchmark'))
import replay as archive


def rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def write(path, values):
    with Path(path).open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(values[0]))
        writer.writeheader()
        writer.writerows(values)


def load_plan_code():
    path = ROOT / 'model/batch_selection.py'
    source = path.read_text()
    module = {'__name__': 'portable_original_plan', '__file__': str(path)}
    exec(compile(source, str(path), 'exec'), module)
    return module


def close(actual, expected, label):
    np.testing.assert_allclose(actual, expected, atol=1e-10, rtol=1e-10, err_msg=label)


def features(pool):
    data = rows(ROOT / f'benchmark/data/{pool}_standardized_features.csv')
    columns = [key for key in data[0] if key not in ('candidate_index', 'well')]
    X = np.asarray([[float(r[key]) for key in columns] for r in data])
    assert X.shape == (96, 116)
    return X @ X.T


def main(out, replay_sh=True, ablations=True):
    out.mkdir(parents=True, exist_ok=True)
    code = load_plan_code()
    source = rows(ROOT / 'benchmark/data/source_records_and_oracle.csv')
    post_saved = rows(ROOT / 'figures/source_data/NH_OH_posteriors_by_round.csv')
    all_post = []
    plan_report = []
    for pool, seed in [('NH_PL36', 6000), ('OH_PL37', 7000), ('OH_PL38', 8000)]:
        original = sorted((r for r in source if r['pool_id'] == pool), key=lambda r: int(r['candidate_index']))
        oracle = {int(r['candidate_index']): float(r['response']) for r in original}
        result = code['campaign'](pool, oracle)
        selected = result['selected_rows']
        saved = rows(ROOT / f'selections/{pool}/selected_conditions.csv')
        assert [(r['candidate_index'], r['batch_number']) for r in selected] == [(int(r['candidate_index']), int(r['batch_number'])) for r in saved]
        assert len(selected) == len({r['candidate_index'] for r in selected}) == 60
        for actual, expected in zip(selected, saved):
            assert actual['sample_id'] == expected['sample_id']
            assert actual['execution_status'] == 'NOT_AN_ACTUAL_BATCH_EXECUTION_RECORD'
            assert not actual['actual_lab_batch_date']
            close(actual['archived_response_revealed_after_computational_selection'], float(expected['archived_response_revealed_after_computational_selection']), pool)
        stops = rows(ROOT / f'selections/{pool}/stopping_checks.csv')
        for actual, expected in zip(result['checks'], stops):
            for key in ('observed_best', 'delta_response_units', 'ucb_minus_observed_best'):
                close(actual[key], float(expected[key]), pool + ':' + key)
            assert actual['decision'] == expected['decision']
            assert actual['consecutive_joint_passes'] == int(expected['consecutive_joint_passes'])
        assert result['checks'][-1]['decision'] == 'BUDGET_REACHED_CRITERION_NOT_MET'
        write(out / f'{pool}_selected_conditions.csv', selected)
        write(out / f'{pool}_stopping_checks.csv', result['checks'])
        K = features(pool)
        error = 0.0
        for rnd in range(1, 6):
            # Only these selected responses enter the posterior. Oracle is not passed.
            obs = {r['candidate_index']: r['archived_response_revealed_after_computational_selection'] for r in selected if r['batch_number'] <= rnd}
            mean, sd = archive.v2.bo_core.posterior(K, sorted(obs), obs)
            expected = sorted((r for r in post_saved if r['pool'] == pool and int(r['after_round']) == rnd), key=lambda r: int(r['candidate_index']))
            close(mean, [float(r['posterior_mean']) for r in expected], pool + ':posterior mean')
            close(sd, [float(r['latent_posterior_sd']) for r in expected], pool + ':latent SD')
            error = max(error, float(np.max(np.abs(mean - [float(r['posterior_mean']) for r in expected]))))
            for i, row in enumerate(expected):
                assert (row['revealed_response'] == '') == (i not in obs)
                all_post.append(dict(pool=pool, after_round=rnd, candidate_index=i, selected=int(i in obs),
                                     revealed_response=obs.get(i, ''), posterior_mean=float(mean[i]),
                                     latent_posterior_sd=float(sd[i]), latent_ucb=float(mean[i] + 1.96 * sd[i])))
        plan_report.append(dict(pool=pool, seed=seed, selected=60, batches=5, posterior_rows=480,
                                max_posterior_mean_error=error, final_decision=result['checks'][-1]['decision']))
    write(out / 'NH_OH_posteriors_by_round.csv', all_post)
    sh = sorted((r for r in source if r['pool_id'] == 'SH_PL40'), key=lambda r: int(r['candidate_index']))
    y = np.array([float(r['response']) for r in sh])
    K = features('SH_PL40')
    saved = rows(ROOT / 'figures/source_data/SH_100_paired_budgets.csv')
    budgets = []
    for row in saved:
        seed = int(row['seed'])
        pair = dict(seed=seed)
        initials = []
        for method, field in [('BO-UCB', 'bo_exact_budget'), ('random', 'random_exact_budget')]:
            if replay_sh:
                run, _ = archive.replay(K, y, seed, method)
                initials.append(run['batches'][0])
                target = set(np.flatnonzero(y >= y.max() - 1e-12))
                budget = archive.v2.bo_core.first_hit_budget(run['batches'], target)
                assert budget == int(row[field]), (seed, method)
            else:
                budget = int(row[field])
            pair[field] = budget
        if replay_sh:
            assert initials[0] == initials[1]
        pair['random_minus_bo'] = pair['random_exact_budget'] - pair['bo_exact_budget']
        budgets.append(pair)
    assert [r['seed'] for r in budgets] == list(range(5000, 5100))
    write(out / 'SH_100_paired_budgets.csv', budgets)
    bo = np.array([r['bo_exact_budget'] for r in budgets])
    random = np.array([r['random_exact_budget'] for r in budgets])
    difference = random - bo
    indices = np.random.default_rng(20261025).integers(0, 100, (20000, 100))
    ci = np.quantile(difference[indices].mean(axis=1), [.025, .975])
    close(ci, [20.88, 30.72], 'current paired-mean interval')
    ecdf = []
    saved_ecdf = rows(ROOT / 'figures/source_data/SH_hit_budget_ecdf.csv')
    for budget in range(12, 97, 12):
        for method, values in [('BO', bo), ('random', random)]:
            lo, hi = np.quantile((values[indices] <= budget).mean(axis=1), [.025, .975])
            record = dict(method=method, budget=budget, hit_count=int((values <= budget).sum()), runs=100,
                          hit_fraction=float((values <= budget).mean()), bootstrap_ci_low=float(lo), bootstrap_ci_high=float(hi))
            expected = next(r for r in saved_ecdf if r['method'] == method and int(r['budget']) == budget)
            for key in ('hit_count', 'hit_fraction', 'bootstrap_ci_low', 'bootstrap_ci_high'):
                close(record[key], float(expected[key]), 'CDF:' + key)
            ecdf.append(record)
    write(out / 'SH_hit_budget_ecdf.csv', ecdf)
    diagnostic_results = []
    if ablations:
        path = ROOT / 'model/diagnostics.py'
        # Only pure mathematical functions are reused; original audit main is not run.
        text = path.read_text().replace('from openpyxl import load_workbook', '')
        module = {'__name__': 'portable_independent_audit', '__file__': str(path)}
        exec(compile(text, str(path), 'exec'), module)
        expected = json.loads((ROOT / 'figures/source_data/SH_audit_diagnostics.json').read_text())
        for label, interaction, coefficient in [('additive_UCB', False, 1.96), ('same_model_greedy_mean', True, 0.0)]:
            values = [module['campaign'](sh, seed, pairs=interaction, coef=coefficient)[2] for seed in range(5000, 5100)]
            record = dict(diagnostic=label, median=float(np.median(values)), mean=float(np.mean(values)), hits_at_48=int(sum(v <= 48 for v in values)))
            assert record == next(r for r in expected if r['diagnostic'] == label)
            diagnostic_results.append(record)
    report = dict(status='passed', current_SH_campaigns_replayed=200 if replay_sh else 0,
                  current_SH_median_budgets=[float(np.median(bo)), float(np.median(random))],
                  paired_mean_saved=float(difference.mean()), paired_mean_95ci=ci.tolist(),
                  earlier_tied_later=[int((difference > 0).sum()), int((difference == 0).sum()), int((difference < 0).sum())],
                  bootstrap_resamples=20000, bootstrap_seed=20261025, NH_OH=plan_report,
                  audit_ablations=diagnostic_results, posterior_rows_checked=len(all_post),
                  environment=dict(python=sys.version, numpy=np.__version__, platform=platform.platform()),
                  limitation='Retrospective computational replay; no dated prospective laboratory executions reconstructed.')
    (out / 'reproduction_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'reproduced_analysis')
    parser.add_argument('--statistics-only', action='store_true', help='Skip 200 SH policy replays; still recompute selected-only posteriors and statistics.')
    parser.add_argument('--skip-ablations', action='store_true')
    args = parser.parse_args()
    main(args.output, not args.statistics_only, not args.skip_ablations)
