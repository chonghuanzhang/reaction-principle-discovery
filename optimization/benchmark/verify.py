#!/usr/bin/env python3
"""Independently reconcile exported logs, batch metrics, sources and paired means."""
import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def key(row):
    return row['pool_id'], int(row['replicate_index']), row['strategy']


def check(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    for name, expected in manifest['output_sha256'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected, ('hash', name)
    sources = rows(directory / 'source_records_and_oracle.csv')
    assert len(sources) == 915
    inputs = rows(directory / 'optimizer_candidates.csv')
    assert len(inputs) == 915 and all('response' not in row for row in inputs)
    pool = defaultdict(dict)
    for row in sources:
        assert int(row['source_excel_row']) > 0
        assert row['source_response_cell'].endswith(row['source_excel_row'])
        pool[row['pool_id']][int(row['candidate_index'])] = row
    target = {r['pool_id']: set(r['candidate_indices']) for r in json.loads((directory / 'evaluation_targets.json').read_text())}
    selected = defaultdict(lambda: defaultdict(list))
    for row in rows(directory / 'all_selected_wells.csv'):
        selected[key(row)][int(row['round'])].append(row)
        original = pool[row['pool_id']][int(row['candidate_index'])]
        for field in ['well', 'response', 'source_sheet', 'source_excel_row', 'source_response_cell']:
            assert row[field] == original[field], ('source mismatch', field)
    assert len(selected) == 1600
    budget_rows = {key(row): row for row in rows(directory / 'run_budgets.csv')}
    trajectories = {(key(row), int(row['round'])): row for row in rows(directory / 'cumulative_best_trajectories.csv')}
    assert len(budget_rows) == 1600 and len(trajectories) == 15800
    for run_key, rounds in selected.items():
        p, rep, strategy = run_key
        assert sorted(rounds) == list(range(1, len(rounds) + 1))
        seen, budget, best = set(), 0, -float('inf')
        hit = {'near_budget': None, 'exact_budget': None, 'target_budget': None}
        ymax = max(float(r['response']) for r in pool[p].values())
        for round_num, batch in rounds.items():
            assert [int(r['within_batch_order']) for r in batch] == list(range(1, len(batch) + 1))
            ids = [int(r['candidate_index']) for r in batch]
            assert not (set(ids) & seen) and len(set(ids)) == len(ids)
            assert all(int(r['budget_before']) == budget for r in batch)
            budget += len(batch)
            assert all(int(r['budget_end']) == budget for r in batch)
            seen.update(ids)
            best = max(best, *(float(r['response']) for r in batch))
            for metric, reached in [('exact_budget', best >= ymax - 1e-12), ('near_budget', best >= .95 * ymax), ('target_budget', bool(seen & target[p]))]:
                if reached and hit[metric] is None:
                    hit[metric] = budget
            t = trajectories[(run_key, round_num)]
            assert int(t['budget_end']) == budget and float(t['cumulative_best_response']) == best
            assert all(float(r['cumulative_best_at_batch_end']) == best for r in batch)
        assert seen == set(pool[p])
        for metric, value in hit.items():
            assert budget_rows[run_key][metric] == (str(value) if value is not None else ''), (run_key, metric)
        other = selected[(p, rep, 'random' if strategy == 'BO-UCB' else 'BO-UCB')][1]
        assert [r['candidate_index'] for r in rounds[1]] == [r['candidate_index'] for r in other]
    reference = defaultdict(list)
    for row in rows(directory / 'reference_all_candidates.csv'):
        assert row['replicate_index'] == '0' and 'response' not in row
        reference[(key(row), int(row['round']))].append(row)
    histories = defaultdict(dict)
    for row in rows(directory / 'reference_observed_history.csv'):
        histories[(key(row), int(row['decision_round']))][int(row['candidate_index'])] = float(row['observed_response'])
    for (run_key, round_num), candidate_rows in reference.items():
        p, _, _ = run_key
        previous = {int(r['candidate_index']): float(r['response']) for b, batch in selected[run_key].items() if b < round_num for r in batch}
        assert histories[(run_key, round_num)] == previous
        assert {int(r['candidate_index']) for r in candidate_rows} == set(pool[p]) - set(previous)
        assert {int(r['candidate_index']) for r in candidate_rows if r['selected'] == '1'} == {int(r['candidate_index']) for r in selected[run_key][round_num]}
        assert all(int(r['observed_count']) == len(previous) for r in candidate_rows)
        for r in candidate_rows:
            assert np.isfinite(float(r['posterior_mean'])) and float(r['posterior_latent_std']) >= 0
            assert np.isclose(float(r['latent_ucb_without_jitter']), float(r['posterior_mean']) + 1.96 * float(r['posterior_latent_std']), rtol=0, atol=1e-12)
    summaries = json.loads((directory / 'pool_statistics.json').read_text())
    checked_metrics = 0
    for p, summary in summaries.items():
        for metric, values in summary['metrics'].items():
            if values is None:
                assert not target[p]
                continue
            b = np.array([int(budget_rows[(p, rep, 'BO-UCB')][metric]) for rep in range(100)])
            r = np.array([int(budget_rows[(p, rep, 'random')][metric]) for rep in range(100)])
            dif = r - b
            bootstrap_means = np.random.default_rng(42).choice(dif, (2000, 100), replace=True).mean(axis=1)
            assert values['bo_mean'] == b.mean() and values['random_mean'] == r.mean()
            assert values['bo_median'] == np.median(b) and values['random_median'] == np.median(r)
            assert values['bo_hits_by_48'] == int((b <= 48).sum())
            assert values['random_hits_by_48'] == int((r <= 48).sum())
            assert values['mean_saving_random_minus_bo'] == dif.mean()
            assert values['median_saving_random_minus_bo'] == np.median(dif)
            np.testing.assert_array_equal(values['paired_mean_saving_bootstrap_95ci'], np.quantile(bootstrap_means, [.025, .975]))
            checked_metrics += 1
    return {'status': 'passed', 'source_candidates': 915, 'runs': len(selected), 'selected_rows': 183000, 'batch_end_trajectory_rows': len(trajectories), 'reference_decisions': len(reference), 'checked_metric_sets': checked_metrics, 'checks': ['all output hashes', '915 sources and response-free candidate inputs', 'source row/response/cell joins', 'paired initial batches and unique full-pool exhaustion', 'all batch-end best trajectories and exact/near/target budgets', 'complete reference remaining candidates and observed histories', 'independent means/medians/48-hit counts and paired mean bootstrap intervals']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', nargs='?', type=Path, default=Path(__file__).parent / 'data')
    args = parser.parse_args()
    print(json.dumps(check(args.directory), ensure_ascii=False, indent=2))
