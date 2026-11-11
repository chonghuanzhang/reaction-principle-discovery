#!/usr/bin/env python3
"""Build the current N–H and Ni-catalysed O–H selected-response analyses.

The immutable experimental source records and historical benchmark remain intact.
The O–H catalyst is selected by the largest response in the 145-catalyst panel;
its condition policy then sees only the fixed 96-candidate Ni condition library.
"""
from pathlib import Path
import csv
import importlib.util
import json
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('batch_selection', ROOT / 'model/batch_selection.py')
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    source = model.read_csv(ROOT / 'benchmark/data/source_records_and_oracle.csv')
    panel = sorted((r for r in source if r['pool_id'] == 'OH_PL34'),
                   key=lambda r: (-float(r['response']), int(r['candidate_index'])))
    assert len(panel) == 145 and panel[0]['cat'] == 'Ni203'
    winner = panel[0]
    catalyst_selection = dict(
        analysis='O–H catalyst screen followed by fixed-catalyst condition selection',
        catalyst_screen='OH_PL34', catalyst_screen_size=145,
        selection_rule='largest recorded UV response in the complete catalyst screen',
        catalyst_code=winner['cat'], catalyst_name='NiCl2·DME',
        catalyst_screen_response=float(winner['response']),
        catalyst_screen_sample=winner['well'], source_sheet=winner['source_sheet'],
        source_response_cell=winner['source_response_cell'],
        condition_pool='OH_PL38', condition_candidates=96,
        condition_factors=dict(bases_or_additives=12, solvents=8),
        acquisition='posterior latent mean + 1.96 * posterior latent SD',
        seed=8000, seed_rationale='retained reference seed; no outcome-based seed search',
        response_units='UV response; product/internal-standard peak area ratio',
        computation_scope='selected-label numerical condition-selection analysis; not a dated laboratory execution log')
    model.dump(ROOT / 'selections/OH_catalyst_selection.json', catalyst_selection)
    summaries, posterior_rows, diagnostics, display_rows = [], [], [], []
    for pool in ('NH_PL36', 'OH_PL38'):
        records = sorted((r for r in source if r['pool_id'] == pool),
                         key=lambda r: int(r['candidate_index']))
        assert len(records) == 96
        oracle = {int(r['candidate_index']): float(r['response']) for r in records}
        result = model.campaign(pool, oracle)
        target = ROOT / 'selections' / pool
        write(target / 'selected_conditions.csv', result['selected_rows'])
        write(target / 'stopping_checks.csv', result['checks'])
        summaries.append(result['summary'])
        candidates, kernel = model.load_unlabelled_pool(pool)
        for rnd in range(1, 6):
            selected = {r['candidate_index']: r['archived_response_revealed_after_computational_selection']
                        for r in result['selected_rows'] if r['batch_number'] <= rnd}
            mu, sd = model.archive.v2.bo_core.posterior(kernel, sorted(selected), selected)
            for i, rec in enumerate(candidates):
                posterior_rows.append(dict(
                    pool=pool, after_round=rnd, candidate_index=i, sample_id=rec['well'],
                    base=rec['base'], solvent=rec['solvent'], selected_by_this_round=int(i in selected),
                    revealed_response=selected.get(i, ''), posterior_mean=float(mu[i]),
                    latent_posterior_sd=float(sd[i]), latent_ucb=float(mu[i] + 1.96 * sd[i]),
                    latent_lower_range=float(mu[i] - 1.96 * sd[i])))
            check = result['checks'][rnd - 1]
            remaining = [i for i in range(96) if i not in selected]
            best = min(selected, key=lambda i: (-selected[i], i))
            diagnostics.append(dict(
                pool=pool, round=rnd, selected_count=len(selected), best_observed=selected[best],
                best_sample=candidates[best]['well'], mean_latent_sd_all_96=float(np.mean(sd)),
                mean_latent_sd_unselected=float(np.mean(sd[remaining])),
                max_unselected_ucb_gap=check['ucb_minus_observed_best'],
                delta=check['delta_response_units'], joint_check=check['joint_check_met'],
                decision=check['decision']))
        for rec in result['selected_rows']:
            display_rows.append(dict(pool_id=pool, batch_number=rec['batch_number'],
                                     base=rec['base'].replace('CsOH/2', 'CsOH'),
                                     solvent=rec['solvent'],
                                     archived_response=rec['archived_response_revealed_after_computational_selection']))
    model.dump(ROOT / 'selections/plan_summary.json', summaries)
    flattened = []
    for s in summaries:
        flattened.append({k: s[k] for k in ('record_type', 'pool_id', 'seed', 'pool_size',
                         'selected_count', 'unselected_count', 'number_of_batches',
                         'best_selected_sample_id', 'best_selected_response', 'initial_batch_sd',
                         'delta_response_units')} | dict(
                         decision=s['final_stop_check']['decision'],
                         model_stop_criterion_met=s['final_stop_check']['model_stop_criterion_met'],
                         final_ucb_gap=s['final_stop_check']['ucb_minus_observed_best']))
    write(ROOT / 'selections/plan_summary.csv', flattened)
    write(ROOT / 'figures/source_data/NH_OH_posteriors_by_round.csv', posterior_rows)
    write(ROOT / 'figures/source_data/NH_OH_round_diagnostics.csv', diagnostics)
    write(ROOT.parent / 'experiments/selected_responses/selected_responses.csv', display_rows)
    model.dump(ROOT.parent / 'experiments/selected_responses/selected_responses.json', display_rows)
    assert len(posterior_rows) == 960 and len(display_rows) == 120
    subprocess.run([
        sys.executable,
        str(ROOT.parent / 'code/scripts/sync_selected_response_links.py'),
    ], check=True)
    print(json.dumps(dict(active_pools=['NH_PL36', 'OH_PL38'], selected_rows=120,
                         posterior_rows=960, catalyst_selection=catalyst_selection,
                         summaries=summaries), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
