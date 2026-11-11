#!/usr/bin/env python3
"""Compute explicitly labelled plans; keep full responses outside the policy.

Campaign and stopping-rule functions used by scripts/reproduce_analysis.py.
The frozen 2026-10-16 policy and posterior are imported without modification.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import platform
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1] / 'selections'
ROOT = HERE.parent
ARCHIVE = ROOT / 'benchmark'
DATA = ARCHIVE / 'data'
PROTOCOL = json.loads((HERE / 'stopping_protocol.json').read_text())
spec = importlib.util.spec_from_file_location('frozen_archive', ARCHIVE / 'replay.py')
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def csv_write(path, rows):
    if not rows:
        return
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_unlabelled_pool(pool):
    if pool == 'OH_CuNi_96':
        candidates = read_csv(HERE / pool / 'candidates.csv')
        feature_rows = read_csv(HERE / pool / 'standardized_features.csv')
    else:
        candidates = sorted((r for r in read_csv(DATA / 'optimizer_candidates.csv') if r['pool_id'] == pool),
                            key=lambda r: int(r['candidate_index']))
        feature_rows = read_csv(DATA / f'{pool}_standardized_features.csv')
    assert len(candidates) == 96
    assert all('response' not in r for r in candidates)
    columns = [key for key in feature_rows[0] if key not in ['candidate_index', 'well']]
    X = np.array([[float(row[c]) for c in columns] for row in feature_rows])
    assert [r['well'] for r in feature_rows] == [r['well'] for r in candidates]
    return candidates, X @ X.T


class StopMonitor:
    """State contains only observed best values and a first-batch scale."""
    def __init__(self):
        self.best_history = []
        self.initial_scale = None
        self.delta = None
        self.streak = 0

    def check(self, policy):
        n = len(policy.observed)
        if self.initial_scale is None:
            self.initial_scale = float(np.std(list(policy.observed.values()), ddof=0))
            self.delta = (PROTOCOL['normalized_practical_delta'] * self.initial_scale
                          if self.initial_scale > 1e-12 else 0.0)
        best = max(policy.observed.values())
        self.best_history.append(best)
        mean, sd = archive.v2.bo_core.posterior(policy.K, sorted(policy.observed), policy.observed)
        remaining = [i for i in range(policy.n) if i not in policy.observed]
        max_ucb = float(max(mean[i] + 1.96 * sd[i] for i in remaining)) if remaining else None
        improvement = (best - self.best_history[-3]) if len(self.best_history) >= 3 else None
        eligible = n >= PROTOCOL['minimum_observations_for_eligible_check']
        scale_valid = self.initial_scale > 1e-12
        plateau = improvement is not None and improvement <= self.delta
        bound_ok = max_ucb is not None and max_ucb <= best + self.delta
        joint = eligible and scale_valid and plateau and bound_ok
        self.streak = self.streak + 1 if joint else 0
        rule_met = self.streak >= PROTOCOL['consecutive_joint_checks_required']
        cap = n >= PROTOCOL['maximum_budget']
        status = (PROTOCOL['stop_result_label'] if rule_met else
                  PROTOCOL['cap_result_label'] if cap else 'CONTINUE')
        return {
            'observed_count': n, 'batch_number': len(self.best_history),
            'observed_best': best, 'initial_batch_sd': self.initial_scale,
            'delta_response_units': self.delta, 'scale_guard_active': not scale_valid,
            'improvement_over_last_two_batches': improvement,
            'minimum_observations_met': eligible, 'plateau_met': plateau,
            'max_unobserved_pointwise_model_ucb': max_ucb,
            'ucb_minus_observed_best': max_ucb - best if max_ucb is not None else None,
            'unobserved_bound_met': bound_ok, 'joint_check_met': joint,
            'consecutive_joint_passes': self.streak,
            'model_stop_criterion_met': rule_met,
            'budget_limit_reached': cap, 'decision': status,
        }


def campaign(pool, oracle):
    """Driver owns archived labels; policy/monitor only see revealed observations."""
    candidates, K = load_unlabelled_pool(pool)
    seed = PROTOCOL['pools_and_actual_seeds'][pool]
    policy = archive.ObservablePolicy(K, seed, 'BO-UCB', n_init=12, batch_size=12)
    monitor = StopMonitor()
    batches, selected_rows, checks = [], [], []
    while True:
        before = len(policy.observed)
        picks, _ = policy.propose()
        score = policy.score
        revealed = {i: float(oracle[i]) for i in picks}
        policy.observe(revealed)
        check = monitor.check(policy)
        batch_records = []
        for order, i in enumerate(picks):
            row = {
                'record_type': 'COMPUTATIONAL_PLAN', 'pool_id': pool, 'seed': seed,
                'batch_number': policy.round, 'within_batch_order': order + 1,
                'budget_before': before, 'budget_end': len(policy.observed),
                'candidate_index': i, 'sample_id': candidates[i]['well'],
                'catalyst_code': candidates[i]['cat'], 'ligand': candidates[i]['ligand'],
                'base': candidates[i]['base'], 'solvent': candidates[i]['solvent'],
                'archived_response_revealed_after_computational_selection': revealed[i],
                'selection_method': 'uniform_random_initial' if policy.round == 1 else 'frozen_posterior_top_12_ucb',
                'posterior_mean_before_selection': score['mean'][order] if score['mean'] else None,
                'posterior_latent_sd_before_selection': score['std'][order] if score['std'] else None,
                'acquisition_score_before_selection': score['acquisition'][order] if score['acquisition'] else None,
                'observed_best_at_batch_end': check['observed_best'],
                'source_sheet': candidates[i]['source_sheet'],
                'source_excel_row': int(candidates[i]['source_excel_row']),
                'source_response_cell': candidates[i]['source_response_cell'],
                'actual_lab_batch_date': '',
                'execution_status': 'NOT_AN_ACTUAL_BATCH_EXECUTION_RECORD',
            }
            if pool == 'OH_CuNi_96':
                row.update(formulation_code=candidates[i]['formulation_code'],
                    formulation=candidates[i]['formulation'],
                    source_pool_id=candidates[i]['source_pool_id'],
                    source_candidate_index=int(candidates[i]['source_candidate_index']))
            batch_records.append(row)
            selected_rows.append(row)
        check = {'record_type': 'COMPUTATIONAL_PLAN', 'pool_id': pool, 'seed': seed, **check}
        checks.append(check)
        batches.append({'record_type': 'COMPUTATIONAL_PLAN', 'pool_id': pool,
                        'batch_number': policy.round, 'selected_records': batch_records,
                        'post_batch_stop_check': check})
        if check['decision'] != 'CONTINUE':
            break
    best_i = min(policy.observed, key=lambda i: (-policy.observed[i], i))
    summary = {
        'record_type': 'COMPUTATIONAL_PLAN', 'pool_id': pool, 'seed': seed,
        'pool_size': policy.n, 'selected_count': len(policy.observed),
        'unselected_count': policy.n - len(policy.observed), 'number_of_batches': policy.round,
        'best_selected_sample_id': candidates[best_i]['well'],
        'best_selected_response': policy.observed[best_i],
        'best_selected_conditions': {k: candidates[best_i][k] for k in ['cat', 'ligand', 'base', 'solvent']},
        'initial_batch_sd': monitor.initial_scale, 'delta_response_units': monitor.delta,
        'final_stop_check': checks[-1],
        'conclusion': '当前已选条件中的工作候选；预算上限不等于证明已找到全局最优' if not checks[-1]['model_stop_criterion_met'] else '模型操作停止规则满足；化学结论仍需独立确认',
    }
    return {'summary': summary, 'batches': batches, 'selected_rows': selected_rows, 'checks': checks}


def benchmark_sh():
    """Reconcile existing 100 paired runs; no new fitted benchmark or seed search."""
    rows = [r for r in read_csv(DATA / 'run_budgets.csv') if r['pool_id'] == 'SH_PL40']
    pairs = []
    for rep in range(100):
        p = {r['strategy']: r for r in rows if int(r['replicate_index']) == rep}
        assert set(p) == {'BO-UCB', 'random'}
        assert int(p['BO-UCB']['seed']) == int(p['random']['seed']) == 5000 + rep
        pairs.append({'replicate_index': rep, 'seed': 5000 + rep,
                      'bo_exact_budget': int(p['BO-UCB']['exact_budget']),
                      'random_exact_budget': int(p['random']['exact_budget'])})
    bo = np.array([r['bo_exact_budget'] for r in pairs])
    rnd = np.array([r['random_exact_budget'] for r in pairs])
    dif = rnd - bo
    rng = np.random.default_rng(42)
    ci = np.percentile([rng.choice(dif, 100, replace=True).mean() for _ in range(2000)], [2.5, 97.5])
    all_picks = [r for r in read_csv(DATA / 'all_selected_wells.csv') if r['pool_id'] == 'SH_PL40']
    for rep in range(100):
        first = {}
        for strategy in ['BO-UCB', 'random']:
            rr = sorted((r for r in all_picks if int(r['replicate_index']) == rep and r['strategy'] == strategy and r['round'] == '1'), key=lambda r: int(r['within_batch_order']))
            first[strategy] = [r['well'] for r in rr]
        assert len(first['BO-UCB']) == 12 and first['BO-UCB'] == first['random']
    result = {'pool_id': 'SH_PL40', 'pool_size': 96, 'paired_runs': 100,
              'actual_seeds': '5000–5099', 'identical_initial_batch_verified_all_100': True,
              'batch_size': 12, 'target': 'maximum archived SH response in the complete 96-condition measured pool',
              'bo_median_exact_hit_budget': float(np.median(bo)),
              'random_median_exact_hit_budget': float(np.median(rnd)),
              'bo_mean_exact_hit_budget': float(bo.mean()),
              'random_mean_exact_hit_budget': float(rnd.mean()),
              'paired_mean_saving': float(dif.mean()), 'paired_mean_saving_95ci': ci.tolist(),
              'bo_hit_count_at_48': int(sum(bo <= 48)), 'random_hit_count_at_48': int(sum(rnd <= 48)),
              'interpretation': 'algorithmic seed variation conditional on fixed measured responses; retrospective benchmark, not lab execution savings',
              'verification_scope': 'recomputed aggregates and all shared initial batches from archived selections; independent 2026-10-22 audit had already rerun all 1600 campaigns',
              'benchmark_stopping': 'full-pool archival replay; exact hit is an evaluator endpoint, never an unknown-ground-truth stop rule'}
    csv_write(HERE / 'SH_PL40_100_paired_budgets.csv', pairs)
    dump(HERE / 'SH_PL40_benchmark.json', result)
    return result


def catalyst_context(source_rows):
    mappings = [('SH_PL39', 'SH_PL33', 'Ag6', 'AgF'), ('SH_PL40', 'SH_PL33', 'Cu9', 'CuCl'),
                ('NH_PL36', 'NH_PL35', 'Ag13', 'Ag2SO4'), ('OH_PL37', 'OH_PL34', 'Cu66', 'Cu(MeCN)4PF6'),
                ('OH_PL38', 'OH_PL34', 'Ni203', 'NiCl2·DME')]
    result = []
    for grid, panel, code, name in mappings:
        rows = sorted((r for r in source_rows if r['pool_id'] == panel), key=lambda r: -float(r['response']))
        chosen = [(rank, r) for rank, r in enumerate(rows, 1) if r['cat'] == code]
        assert len(chosen) == 1
        rank, row = chosen[0]
        result.append({'condition_grid': grid, 'historical_panel': panel, 'catalyst_code': code,
                       'catalyst_name': name, 'rank_in_original_complete_panel': rank,
                       'panel_response': float(row['response']), 'source_sheet': row['source_sheet'],
                       'source_response_cell': row['source_response_cell'],
                       'selection_reason_status': 'historical choice; exact contemporaneous decision rationale not available',
                       'allowed_inference': 'candidate had a relatively high recorded response; rank alone does not reconstruct why chosen'})
    csv_write(HERE / 'five_catalyst_context.csv', result)
    dump(HERE / 'five_catalyst_context.json', result)
    return result


