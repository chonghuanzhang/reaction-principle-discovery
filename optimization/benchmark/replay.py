#!/usr/bin/env python3
"""Auditable v2 replay archive; immutable upstream snapshot supplies the mathematics.

The policy constructor receives only the unlabeled kernel.  Its observe() boundary
accepts exactly the batch it just proposed. Full responses stay with replay/evaluator.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import random
import sys
import time
import warnings
import zipfile
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE.parent / 'model'
sys.dont_write_bytecode = True
sys.path[:0] = [str(SNAPSHOT)]
import run_replay_v2 as v2

SEEDS = {'SH_PL33': 1000, 'NH_PL35': 2000, 'OH_PL34': 3000,
         'SH_PL39': 4000, 'SH_PL40': 5000, 'NH_PL36': 6000,
         'OH_PL37': 7000, 'OH_PL38': 8000}
STRATEGIES = ['BO-UCB', 'random']
NS = v2.v1.NS
ELEMENTS = ['Br', 'Cl', 'Si', 'Na', 'Mg', 'Ca', 'Li', 'Al', 'Fe', 'Co', 'Ni', 'Cu', 'Ag', 'Pd', 'Pt', 'Rh', 'Ru', 'Ir', 'Au', 'Zn', 'B', 'C', 'N', 'O', 'P', 'S', 'F', 'I', 'b', 'c', 'n', 'o', 'p', 's']


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def exact_key(record):
    """No aliasing: retain CsOH, CsOH/2, and DIO exactly as recorded."""
    return tuple(record.get(k, '') for k in ['cat', 'ligand', 'base', 'solvent'])


class ObservablePolicy:
    def __init__(self, K, seed, strategy, n_init=12, batch_size=12):
        if strategy not in STRATEGIES:
            raise ValueError(strategy)
        self.K = np.asarray(K, dtype=float)
        self.n = len(K)
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.strategy = strategy
        self.n_init = n_init
        self.batch_size = batch_size
        self.observed = {}
        self.pending = None
        self.round = 0

    def propose(self, diagnostics=False):
        if self.pending is not None:
            raise ValueError('must observe the pending batch before another decision')
        remaining = [i for i in range(self.n) if i not in self.observed]
        if not remaining:
            return [], []
        count = len(self.observed)
        mean = std = acquisition = None
        selection_rank = {}
        if self.round == 0:
            pick = self.rng.sample(range(self.n), min(self.n_init, self.n))
            mode = 'outcome_blind_uniform_without_replacement'
            if diagnostics:
                mean, std = v2.bo_core.posterior(self.K, [], {})
        elif self.strategy == 'random':
            self.rng.shuffle(remaining)
            pick = remaining[:min(self.batch_size, len(remaining))]
            selection_rank = {i: k + 1 for k, i in enumerate(remaining)}
            mode = 'uniform_random_remaining'
            if diagnostics:
                mean, std = v2.bo_core.posterior(self.K, sorted(self.observed), self.observed)
        else:
            mean, std = v2.bo_core.posterior(self.K, sorted(self.observed), self.observed)
            jitter = np.asarray([self.rng.random() for _ in range(self.n)]) * 1e-12
            acquisition = mean + 1.96 * std + jitter
            order = sorted(remaining, key=lambda i: (-float(acquisition[i]), i))
            selection_rank = {i: k + 1 for k, i in enumerate(order)}
            pick = order[:min(self.batch_size, len(remaining))]
            mode = 'frozen_posterior_top_ucb'
        self.round += 1
        self.pending = list(pick)
        self.score = {
            'round': self.round, 'indices': list(pick),
            'mean': mean[pick].tolist() if acquisition is not None else [],
            'std': std[pick].tolist() if acquisition is not None else [],
            'acquisition': acquisition[pick].tolist() if acquisition is not None else [],
        }
        rows = []
        if diagnostics:
            for i in sorted(remaining):
                rows.append({
                    'round': self.round, 'candidate_index': i, 'observed_count': count,
                    'selected': int(i in pick), 'selection_rank': selection_rank.get(i),
                    'selection_mode': mode,
                    'posterior_mean': float(mean[i]), 'posterior_latent_std': float(std[i]),
                    'latent_ucb_without_jitter': float(mean[i] + 1.96 * std[i]),
                    'decision_score': float(acquisition[i]) if acquisition is not None else None,
                    'score_used_for_selection': acquisition is not None,
                })
        return pick, rows

    def observe(self, responses):
        if self.pending is None or set(responses) != set(self.pending):
            raise ValueError('responses must contain exactly the pending batch; hidden labels are rejected')
        if not all(np.isfinite(float(x)) for x in responses.values()):
            raise ValueError('responses must be finite')
        self.observed.update({int(i): float(value) for i, value in responses.items()})
        self.pending = None


def replay(K, oracle, seed, strategy, n_init=12, batch_size=12, reference=False):
    """Evaluator owns oracle; the policy sees only selected-batch mappings."""
    policy = ObservablePolicy(K, seed, strategy, n_init, batch_size)
    batches, scores, all_candidates = [], [], []
    while len(policy.observed) < policy.n:
        pick, candidates = policy.propose(diagnostics=reference)
        batches.append(list(pick))
        scores.append(policy.score)
        if reference:
            all_candidates.append(candidates)
        policy.observe({i: float(oracle[i]) for i in pick})
    best = []
    running = -float('inf')
    for batch in batches:
        running = max(running, float(np.max(np.asarray(oracle)[batch])))
        best.extend([running] * len(batch))
    return {'seed': int(seed), 'strategy': strategy, 'batches': batches,
            'scores': scores, 'best_by_budget': best}, all_candidates


def extended_metric(bo, rnd, n):
    """Retain v2 statistics and name the bootstrap estimand unambiguously."""
    base = v2.paired_summary(bo, rnd, n)
    base['paired_mean_saving_bootstrap_95ci'] = base.pop('paired_bootstrap_95ci_saving')
    for label, values in [('bo', bo), ('random', rnd)]:
        vec = [v2.budget_or_sentinel(v, n) for v in values]
        base[label + '_mean_budget_bootstrap_95ci'] = v2.bootstrap_ci(vec)
        base[label + '_hits_by_48'] = sum(x <= 48 for x in vec)
        base[label + '_n_replicates'] = len(vec)
    base['bootstrap_estimand'] = 'mean of paired per-replicate (random budget - BO budget)'
    return base


def workbook_row_lookup(path):
    """Recover physical Excel row numbers without changing upstream parsing."""
    with zipfile.ZipFile(path) as z:
        shared = [''.join(t.text or '' for t in si.findall('.//m:t', NS)) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS)]
        rels = {r.attrib['Id']: r.attrib['Target'] for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        out = {}
        for sh in ET.fromstring(z.read('xl/workbook.xml')).find('m:sheets', NS):
            if sh.attrib['name'] not in {cfg['sheet'] for cfg in v2.ROUTES.values()}:
                continue
            target = rels[sh.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            target = target.lstrip('/') if target.startswith('/') else target if target.startswith('xl/') else 'xl/' + target
            for row in ET.fromstring(z.read(target)).findall('.//m:sheetData/m:row', NS):
                for c in row.findall('m:c', NS):
                    if c.attrib['r'] != 'A' + row.attrib['r']:
                        continue
                    value = c.find('m:v', NS)
                    value = value.text if value is not None else ''
                    if c.attrib.get('t') == 's' and value:
                        value = shared[int(value)]
                    elif c.attrib.get('t') == 'inlineStr':
                        value = ''.join(t.text or '' for t in c.findall('.//m:t', NS))
                    if value and value != 'Name':
                        key = (sh.attrib['name'], v2.v1.clean(value))
                        if key in out:
                            raise ValueError(f'duplicate sheet/well: {key}')
                        out[key] = int(row.attrib['r'])
        return out


def feature_names(records, stage):
    if stage == 'catalyst_panel':
        return ['family=' + f for f in sorted({v2.family(r['catalyst']) for r in records})] + ['SMILES_token=' + e for e in ELEMENTS] + ['log1p_SMILES_length', 'SMILES_dot_count', 'SMILES_plus_count', 'SMILES_minus_count']
    levels = {k: sorted({str(r.get(k, '')) for r in records}) for k in ['base', 'solvent']}
    return ['base=' + b for b in levels['base']] + ['solvent=' + s for s in levels['solvent']] + ['pair=' + b + '|' + s for b in levels['base'] for s in levels['solvent']]


def pools_from_records(rows, route):
    """Reconstruct the exact upstream records from the portable 915-row export."""
    cfg = v2.ROUTES[route]
    pools = {}
    for plate in [cfg['initial']] + cfg['grids']:
        selected = sorted((r for r in rows if r['route'] == route and r['plate'] == plate), key=lambda r: int(r['candidate_index']))
        if [int(r['candidate_index']) for r in selected] != list(range(len(selected))):
            raise ValueError(f'{route}/{plate}: candidate indices not contiguous')
        records = []
        for row in selected:
            rec = {'well': row['well'], 'response': float(row['response']), 'catalyst': row['catalyst'], 'smiles': row['smiles']}
            cond = {k: row[k] for k in ['cat', 'ligand', 'base', 'solvent']}
            if plate == cfg['initial']:
                rec['condition'] = cond
            else:
                rec.update(cond)
            records.append(rec)
        pools[plate] = records
    return pools[cfg['initial']], {p: pools[p] for p in cfg['grids']}


def compare_json(a, b, path=''):
    differences = []
    if type(a) != type(b):
        return [{'path': path, 'original': a, 'rerun': b}]
    if isinstance(a, dict):
        if set(a) != set(b):
            return [{'path': path, 'original_keys': list(a), 'rerun_keys': list(b)}]
        for k in a:
            differences.extend(compare_json(a[k], b[k], path + '/' + str(k)))
    elif isinstance(a, list):
        if len(a) != len(b):
            return [{'path': path, 'original_length': len(a), 'rerun_length': len(b)}]
        for i, (x, y) in enumerate(zip(a, b)):
            differences.extend(compare_json(x, y, path + '/' + str(i)))
    elif a != b:
        differences.append({'path': path, 'original': a, 'rerun': b})
    return differences


def csv_writer(path, fields):
    handle = Path(path).open('w', newline='', encoding='utf-8-sig')
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    return handle, writer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workbook', type=Path, default=HERE.parents[2] / '实验结果' / '三氟乙基羰基+N\\O\\S\\P数据总结.xlsx')
    parser.add_argument('--source-records', type=Path, help='Portable source_records_and_oracle.csv; no workbook required')
    parser.add_argument('--output', type=Path, default=HERE / 'data')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = json.loads((SNAPSHOT / 'bo_v2_results.json').read_text())
    portable_rows = None
    portable_input_hash = None
    if args.source_records:
        portable_input_hash = sha256(args.source_records)
        bundled_manifest = HERE / 'data/manifest.json'
        if bundled_manifest.exists():
            expected_hash = json.loads(bundled_manifest.read_text())['output_sha256']['source_records_and_oracle.csv']
            if portable_input_hash != expected_hash:
                raise ValueError('portable source CSV SHA256 differs from the audited workbook export')
        with args.source_records.open(encoding='utf-8-sig', newline='') as f:
            portable_rows = list(csv.DictReader(f))
        if len(portable_rows) != 915:
            raise ValueError('portable input must contain exactly 915 candidates')
        source_hashes = {r['source_workbook_sha256'] for r in portable_rows}
        if source_hashes != {original['source_sha256']}:
            raise ValueError('portable source provenance differs from v2')
        book = Path(portable_rows[0]['source_workbook'])
        source_hash = original['source_sha256']
        row_lookup = {(r['source_sheet'], r['well']): int(r['source_excel_row']) for r in portable_rows}
        if len(row_lookup) != 915:
            raise ValueError('portable source contains duplicate sheet/well records')
        sheets = None
    else:
        book = args.workbook.resolve()
        source_hash = sha256(book)
        sheets = v2.v1.read_workbook(book)
        row_lookup = workbook_row_lookup(book)
    if source_hash != original['source_sha256']:
        raise ValueError('input workbook SHA256 differs from v2; no silent replacement allowed')
    results = {k: value for k, value in original.items() if k != 'routes'}
    results['routes'] = {}
    # Keep original source string in comparison object; actual portable path is in manifest.
    identity = ['pool_id', 'route', 'stage', 'plate', 'source_workbook', 'source_workbook_sha256', 'source_sheet', 'source_excel_row', 'source_response_cell', 'well', 'candidate_index']
    run_identity = ['pool_id', 'route', 'stage', 'plate', 'replicate_index', 'seed', 'strategy']
    handles = []
    def writer(filename, fields):
        h, w = csv_writer(out / filename, fields); handles.append(h); return w
    selection = writer('all_selected_wells.csv', run_identity + identity[4:] + ['round', 'within_batch_order', 'budget_before', 'budget_end', 'response', 'posterior_mean', 'posterior_latent_std', 'decision_score', 'cumulative_best_at_batch_end'])
    reference = writer('reference_all_candidates.csv', run_identity + identity[4:] + ['round', 'observed_count', 'selected', 'selection_rank', 'selection_mode', 'posterior_mean', 'posterior_latent_std', 'latent_ucb_without_jitter', 'decision_score', 'score_used_for_selection'])
    trajectory = writer('cumulative_best_trajectories.csv', run_identity + ['round', 'budget_end', 'cumulative_best_response', 'exact_best_hit', 'near_95pct_hit', 'actual_target_hit'])
    budgets = writer('run_budgets.csv', run_identity + ['n_records', 'observed_best', 'near_threshold', 'target_count', 'exact_budget', 'near_budget', 'target_budget', 'exact_hit_by_48', 'near_hit_by_48', 'target_hit_by_48'])
    source = writer('source_records_and_oracle.csv', identity + ['catalyst', 'smiles', 'cat', 'ligand', 'base', 'solvent', 'response', 'solvent_identity_status'])
    candidates = writer('optimizer_candidates.csv', identity + ['catalyst', 'smiles', 'cat', 'ligand', 'base', 'solvent'])
    history = writer('reference_observed_history.csv', run_identity + ['decision_round', 'candidate_index', 'observed_response'])
    summaries, targets, feature_manifest, audit, counters = {}, [], {}, [], {'runs': 0, 'selected_rows': 0, 'round_rows': 0, 'reference_candidate_rows': 0}
    start = time.perf_counter()
    for route in ['SH', 'NH', 'OH']:
        cfg = v2.ROUTES[route]
        initial, grids = pools_from_records(portable_rows, route) if portable_rows is not None else v2.v1.route_data(sheets, route)
        ranked_initial = sorted(initial, key=lambda r: (-r['response'], r['well']))
        rank = {r['catalyst']: i + 1 for i, r in enumerate(ranked_initial)}
        route_result = {'condition_grids': {}, 'final_condition': cfg['final']}
        for stage, plate, records in [('catalyst_panel', cfg['initial'], initial)] + [('condition_grid', p, records) for p, records in grids.items()]:
            pool_id = route + '_' + plate
            if stage == 'catalyst_panel':
                target_indices = [i for i, r in enumerate(records) if r['catalyst'] in set(cfg['followup_catalysts'])]
                normalized_targets = target_indices
                X = v2.panel_matrix(records)
            else:
                target_indices = [i for i, r in enumerate(records) if exact_key(r) == exact_key(cfg['final'])]
                normalized_targets = [i for i, r in enumerate(records) if v2.key_condition(r) == v2.v1.normalize_condition(cfg['final'])]
                X = v2.grid_matrix(records)
            if target_indices != normalized_targets:
                raise ValueError(f'{pool_id}: exact raw targets differ from legacy normalized targets; explicit review required')
            K = X @ X.T
            names = feature_names(records, stage)
            with (out / (pool_id + '_standardized_features.csv')).open('w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f); w.writerow(['candidate_index', 'well'] + names)
                w.writerows([[i, r['well']] + X[i].tolist() for i, r in enumerate(records)])
            feature_manifest[pool_id] = {'n_records': len(records), 'n_features': X.shape[1], 'columns': names, 'standardized_matrix_sha256': sha256(out / (pool_id + '_standardized_features.csv')), 'kernel': 'K=X@X.T; no independent intercept term'}
            metadata = []
            for i, record in enumerate(records):
                excel_row = row_lookup[(cfg['sheet'], record['well'])]
                meta = {'pool_id': pool_id, 'route': route, 'stage': stage, 'plate': plate, 'source_workbook': str(book), 'source_workbook_sha256': source_hash, 'source_sheet': cfg['sheet'], 'source_excel_row': excel_row, 'source_response_cell': cfg['metric'] + str(excel_row), 'well': record['well'], 'candidate_index': i}
                metadata.append(meta)
                conditions = record['condition'] if stage == 'catalyst_panel' else {k: record[k] for k in ['cat', 'ligand', 'base', 'solvent']}
                inputs = {**meta, 'catalyst': record['catalyst'], 'smiles': record['smiles'], **conditions}
                candidates.writerow(inputs)
                source.writerow({**inputs, 'response': record['response'], 'solvent_identity_status': 'DIO abbreviation unresolved; no identity mapping applied' if conditions['solvent'] == 'DIO' else 'raw source label; no identity verification asserted'})
            targets.append({'pool_id': pool_id, 'definition': 'any historically followed catalyst code' if stage == 'catalyst_panel' else 'exact raw cat/ligand/base/solvent within this grid', 'target': cfg['followup_catalysts'] if stage == 'catalyst_panel' else cfg['final'], 'candidate_indices': target_indices, 'wells': [records[i]['well'] for i in target_indices], 'legacy_normalization_same_indices': True})
            oracle = np.asarray([r['response'] for r in records], dtype=float)
            runs = {s: [] for s in STRATEGIES}
            metric_values = {s: {k: [] for k in ['near_budget', 'exact_budget', 'target_budget']} for s in STRATEGIES}
            for rep in range(100):
                seed = SEEDS[pool_id] + rep
                for strategy in STRATEGIES:
                    run, ref = replay(K, oracle, seed, strategy, reference=rep == 0)
                    upstream_run = v2.bo_core.run_campaign(K, oracle, seed, strategy, 12, 12)
                    if run != upstream_run:
                        raise ValueError(f'{pool_id}/{rep}/{strategy}: interface run differs from v2 campaign')
                    runs[strategy].append(run)
                    run_key = {'pool_id': pool_id, 'route': route, 'stage': stage, 'plate': plate, 'replicate_index': rep, 'seed': seed, 'strategy': strategy}
                    stat = v2.batch_end_budget(run, records, target_indices, .95 * max(oracle))
                    for metric, val in stat.items():
                        metric_values[strategy][metric].append(val)
                    budgets.writerow({**run_key, 'n_records': len(records), 'observed_best': max(oracle), 'near_threshold': .95 * max(oracle), 'target_count': len(target_indices), **stat, 'exact_hit_by_48': stat['exact_budget'] <= 48, 'near_hit_by_48': stat['near_budget'] <= 48, 'target_hit_by_48': stat['target_budget'] <= 48 if target_indices else None})
                    running, budget, seen = -float('inf'), 0, []
                    for round_number, (batch, scores) in enumerate(zip(run['batches'], run['scores']), 1):
                        budget_before = budget
                        budget += len(batch)
                        running = max(running, float(np.max(oracle[batch])))
                        for j, i in enumerate(batch):
                            selection.writerow({**run_key, **{k: v for k, v in metadata[i].items() if k not in run_key}, 'round': round_number, 'within_batch_order': j + 1, 'budget_before': budget_before, 'budget_end': budget, 'response': float(oracle[i]), 'posterior_mean': scores['mean'][j] if scores['mean'] else None, 'posterior_latent_std': scores['std'][j] if scores['std'] else None, 'decision_score': scores['acquisition'][j] if scores['acquisition'] else None, 'cumulative_best_at_batch_end': running})
                            counters['selected_rows'] += 1
                        trajectory.writerow({**run_key, 'round': round_number, 'budget_end': budget, 'cumulative_best_response': running, 'exact_best_hit': running >= max(oracle) - 1e-12, 'near_95pct_hit': running >= .95 * max(oracle), 'actual_target_hit': bool(set(seen + batch) & set(target_indices)) if target_indices else None})
                        counters['round_rows'] += 1
                        if rep == 0:
                            for observed_index in sorted(seen):
                                history.writerow({**run_key, 'decision_round': round_number, 'candidate_index': observed_index, 'observed_response': float(oracle[observed_index])})
                            for candidate in ref[round_number - 1]:
                                i = candidate['candidate_index']
                                reference.writerow({**run_key, **{k: v for k, v in metadata[i].items() if k not in run_key}, **candidate})
                                counters['reference_candidate_rows'] += 1
                        seen += batch
                    counters['runs'] += 1
            summary = v2.summarize_stage(records, K, runs, target_indices)
            summaries[pool_id] = {'pool_id': pool_id, 'route': route, 'stage': stage, 'plate': plate, 'seed_base': SEEDS[pool_id], 'n_records': len(records), 'observed_best': float(max(oracle)), 'near_threshold': float(.95 * max(oracle)), 'actual_target_count': len(target_indices), 'metrics': {metric: extended_metric(metric_values['BO-UCB'][metric], metric_values['random'][metric], len(records)) if metric != 'target_budget' or target_indices else None for metric in metric_values['BO-UCB']}}
            if stage == 'catalyst_panel':
                route_result['initial_panel'] = {'plate': cfg['initial'], 'n_records': len(initial), 'actual_followup_catalyst_ranks': [{'catalyst': c, 'rank': rank.get(c)} for c in cfg['followup_catalysts']], 'summary': summary}
            else:
                vals = sorted(records, key=lambda r: (-r['response'], r['well']))
                final_rank = next((i + 1 for i, r in enumerate(vals) if exact_key(r) == exact_key(cfg['final'])), None)
                route_result['condition_grids'][plate] = {'summary': summary, 'observed_best': max(records, key=lambda r: r['response']), 'final_condition_rank': final_rank, 'final_condition_rows': [records[i] for i in target_indices]}
            audit.append({'pool_id': pool_id, 'replicates': 100, 'strategies': 2, 'all_campaign_dicts_exactly_match_v2': True, 'exact_raw_targets_equal_v2_targets': True})
            print(f'{pool_id}: 200 runs, full campaign objects equal to v2; elapsed {time.perf_counter() - start:.1f}s', flush=True)
        results['routes'][route] = route_result
    for handle in handles:
        handle.close()
    differences = compare_json(original, results)
    dump(out / 'v2_recomputed_results.json', results)
    dump(out / 'pool_statistics.json', summaries)
    dump(out / 'evaluation_targets.json', targets)
    dump(out / 'feature_manifest.json', feature_manifest)
    dump(out / 'verification.json', {'source_sha256_matches_v2': True, 'all_1600_campaign_objects_equal_upstream_v2': True, 'all_v2_result_fields_exactly_equal': not differences, 'differences': differences, 'pool_checks': audit, 'counts': counters, 'elapsed_seconds': time.perf_counter() - start})
    if differences:
        raise ValueError(f'{len(differences)} result differences; see verification.json; no silent replacement')
    with (out / 'pool_metrics.csv').open('w', newline='', encoding='utf-8-sig') as f:
        flat = [{**{k: p[k] for k in ['pool_id', 'route', 'stage', 'plate', 'n_records', 'seed_base']}, 'metric': metric, **{k: json.dumps(v) if isinstance(v, list) else v for k, v in values.items()}} for p in summaries.values() for metric, values in p['metrics'].items() if values is not None]
        w = csv.DictWriter(f, fieldnames=list(flat[0])); w.writeheader(); w.writerows(flat)
    config = io.StringIO()
    with redirect_stdout(config), warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Install `pyyaml` for better output', category=UserWarning)
        np.show_config()
    dump(out / 'environment.json', {'python': sys.version, 'executable': sys.executable, 'numpy': np.__version__, 'platform': platform.platform(), 'machine': platform.machine(), 'numpy_config': config.getvalue(), 'environment_thread_limits': {k: os.environ.get(k) for k in ['OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS']}, 'dependencies': ['Python standard library', 'numpy=='+np.__version__]})
    manifest = {'workbook': str(book), 'workbook_sha256': source_hash, 'analysis_entry_sha256': sha256(__file__), 'input_snapshot_hashes': {str(p.relative_to(HERE.parent)): sha256(p) for p in sorted(SNAPSHOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}, 'output_sha256': {p.name: sha256(p) for p in sorted(out.iterdir()) if p.is_file() and p.name != 'manifest.json'}}
    manifest['input_mode'] = 'extracted_csv' if portable_rows is not None else 'original_workbook'
    manifest['portable_input_sha256'] = portable_input_hash
    dump(out / 'manifest.json', manifest)
    print(json.dumps({'status': 'passed', **counters, 'all_v2_statistics_exactly_equal': True}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
