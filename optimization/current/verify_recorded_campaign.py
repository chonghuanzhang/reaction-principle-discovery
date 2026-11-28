#!/usr/bin/env python3
"""Verify the three recorded sequential Bayesian campaign histories.

This post-run integrity check validates the recorded round-0 indices within the
complete decision space and recomputes each later recommendation using only the
UV responses available through the preceding completed round.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import numpy as np
import engine

HERE = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def verify_campaign(system, protocol, output):
    config = protocol['system_configs'][system]
    saved = read_json(HERE / 'runs' / system / 'trajectory.json')
    grid = read_csv(HERE / 'data' / system / 'candidate_space.csv')
    assert len(grid) == engine.N
    assert [int(r['candidate_index']) for r in grid] == list(range(engine.N))
    assert len({(r['catalyst_index'], r['solvent_index'], r['base_index']) for r in grid}) == engine.N
    assert [len({r[key] for r in grid}) for key in (
        'catalyst_index', 'solvent_index', 'base_index')] == [145, 8, 12]
    selected = read_csv(HERE / 'runs' / system / 'trajectory_conditions.csv')
    feedback = {int(row['candidate_index']): float(row['UV_response']) for row in selected}
    assert len(feedback) == len(selected)
    assert all(float(grid[i]['UV_response']) == value for i, value in feedback.items())
    initial = saved['history'][0]['indices']
    assert len(initial) == engine.N_INIT and len(set(initial)) == engine.N_INIT
    assert all(isinstance(i, int) and 0 <= i < engine.N for i in initial)
    assert all(i in feedback for i in initial), (system, 'initial feedback missing')
    observed = {i: feedback[i] for i in initial}
    initial_sd = float(np.std(list(observed.values()), ddof=0))
    tolerance = 0.1 * initial_sd if initial_sd > 1e-12 else 0.0
    best_by_n = {}
    checks, means, sds = [], [], []
    final_campaign_best = max(float(row['UV_response']) for row in selected)
    first_best_round = 0 if final_campaign_best in observed.values() else None
    for round_no in range(len(saved['history'])):
        record = saved['history'][round_no]
        if round_no:
            picks = record['indices']
            assert len(picks) == 4 and not set(picks).intersection(observed)
            assert all(i in feedback for i in picks), (system, round_no, 'missing feedback')
            mean, sd = engine.posterior(observed, config)
            base_acquisition = mean + float(config['beta']) * sd
            eligible = base_acquisition.copy()
            eligible[list(observed)] = -np.inf
            unselected = np.setdiff1d(np.arange(engine.N), np.array(picks, dtype=int))
            assert float(eligible[unselected].max()) <= float(eligible[picks].min()) + 1e-12
            np.testing.assert_allclose(mean[picks], record['posterior_mean'], rtol=1e-10, atol=1e-11)
            np.testing.assert_allclose(sd[picks], record['posterior_sd'], rtol=1e-10, atol=1e-11)
            recorded_jitter = np.asarray(record['acquisition']) - base_acquisition[picks]
            assert np.all(recorded_jitter >= -1e-14)
            assert np.all(recorded_jitter < 1.01e-12)
            observed.update({i: feedback[i] for i in picks})
            if first_best_round is None and final_campaign_best in observed.values():
                first_best_round = round_no
        n = len(observed)
        best_by_n[n] = max(observed.values())
        gain = best_by_n[n] - best_by_n[n-8] if n-8 in best_by_n else None
        stop = n >= 24 and initial_sd > 1e-12 and gain is not None and gain <= tolerance
        expected = record['stop_check']
        assert n == record['observed_count_after_feedback'] == expected['observed_count']
        assert stop == expected['model_stop_criterion_met']
        np.testing.assert_allclose([initial_sd, tolerance, best_by_n[n]],
            [expected['initial_batch_sd'], expected['delta_response_units'], expected['observed_best']],
            rtol=1e-12, atol=1e-12)
        if gain is not None:
            np.testing.assert_allclose(gain, expected['improvement_over_last_two_batches'], atol=1e-12)
        assert stop == (round_no == len(saved['history'])-1), 'Must stop at first qualifying check'
        mu, sigma = engine.posterior(observed, config)
        means.append(mu); sds.append(sigma)
        checks.append(dict(system=system, round=round_no, n_observed=n,
            best_UV_response=best_by_n[n], improvement_last_two_rounds=gain,
            tolerance=tolerance, criterion_met=bool(stop)))
    expected_summary = next(r for r in protocol['campaigns'] if r['system'] == system)
    assert first_best_round == expected_summary['first_best_round']
    assert len(observed) == expected_summary['unique_conditions']
    assert round_no == expected_summary['stopping_round']
    assert max(observed.values()) == final_campaign_best
    assert len(selected) == len(observed)
    assert {int(r['candidate_index']) for r in selected} == set(observed)
    assert all(float(r['UV_response']) == feedback[int(r['candidate_index'])] for r in selected)
    # Independently compare the compressed equality classes to direct full-space posterior.
    direct_mean, direct_sd = engine.posterior(observed, config, compressed=False)
    np.testing.assert_allclose(means[-1], direct_mean, rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(sds[-1], direct_sd, rtol=1e-11, atol=1e-12)
    if output:
        output.mkdir(parents=True, exist_ok=True)
        (output / f'{system}_stopping_checks.json').write_text(json.dumps(checks, indent=2)+'\n')
        np.savez_compressed(output / f'{system}_posterior_snapshots.npz',
                            means=np.asarray(means), sds=np.asarray(sds))
    return dict(system=system, candidate_count=engine.N, recorded_feedback_records=len(feedback),
        selected_unique_conditions=len(observed), initialization=12, batch_size=4,
        first_best_round=first_best_round, stopping_round=round_no,
        highest_measured_UV_response=final_campaign_best, tolerance=tolerance,
        recorded_initialization_indices_valid_in_full_space=True,
        all_full_space_recommendation_rankings_match=True, all_feedback_is_measured=True,
        recorded_campaign_history_verified=True, first_eligible_stop_verified=True,
        direct_posterior_match=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Write checks and posterior arrays here')
    args = parser.parse_args()
    protocol = read_json(HERE / 'protocol.json')
    for rel, digest in protocol['sha256'].items():
        assert hashlib.sha256((HERE/rel).read_bytes()).hexdigest() == digest, rel
    assert protocol['execution_mode'] == 'recorded sequential campaign history'
    results = [verify_campaign(s, protocol, args.output) for s in ('NH', 'OH', 'SH')]
    report = dict(status='PASS', selected_response_count=sum(r['selected_unique_conditions'] for r in results),
                  systems=results)
    if args.output:
        (args.output / 'campaign_verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
