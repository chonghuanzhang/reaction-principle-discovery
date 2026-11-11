#!/usr/bin/env python3
"""Build N–H and 12-formulation O–H selected-response analyses.

Original measurements remain immutable; O–H has 12 catalyst–base formulations
(two mandatory references plus ten seeded random identities) × 8 solvents.
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
    sys.path.insert(0, str(ROOT / 'model'))
    import mixed_oh_library as library
    oh_candidates, manifest = library.build(source)
    by_sample = {r['well']: r for r in source}
    summaries, posterior_rows, diagnostics, display_rows = [], [], [], []
    for pool in ('NH_PL36', library.POOL):
        records = (oh_candidates if pool == library.POOL else
                   sorted((r for r in source if r['pool_id'] == pool),
                          key=lambda r: int(r['candidate_index'])))
        assert len(records) == 96
        oracle = {int(r['candidate_index']): float(by_sample[r['well']]['response']) for r in records}
        result = model.campaign(pool, oracle)
        target = ROOT / 'selections' / pool
        write(target / 'selected_conditions.csv', result['selected_rows'])
        write(target / 'stopping_checks.csv', result['checks'])
        summaries.append(result['summary'])
        candidates, kernel = model.load_unlabelled_pool(pool)
        for rnd in range(1, result['summary']['number_of_batches'] + 1):
            selected = {r['candidate_index']: r['archived_response_revealed_after_computational_selection']
                        for r in result['selected_rows'] if r['batch_number'] <= rnd}
            mu, sd = model.archive.v2.bo_core.posterior(kernel, sorted(selected), selected)
            for i, rec in enumerate(candidates):
                posterior_rows.append(dict(
                    pool=pool, after_round=rnd, candidate_index=i, sample_id=rec['well'],
                    base=rec['base'], solvent=rec['solvent'],
                    catalyst_code=rec['cat'], formulation_code=rec.get('formulation_code', ''),
                    formulation=rec.get('formulation', rec['base']),
                    source_pool_id=rec.get('source_pool_id', pool), selected_by_this_round=int(i in selected),
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
                                     catalyst_code=rec['catalyst_code'],
                                     formulation_code=rec.get('formulation_code', ''),
                                     formulation=rec.get('formulation', rec['base']),
                                     base=rec['base'], solvent=rec['solvent'],
                                     source_pool_id=rec.get('source_pool_id', pool),
                                     sample_id=rec['sample_id'],
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
    assert len(display_rows) == sum(s['selected_count'] for s in summaries)
    assert len(posterior_rows) == 96 * sum(s['number_of_batches'] for s in summaries)
    subprocess.run([
        sys.executable,
        str(ROOT.parent / 'code/scripts/sync_selected_response_links.py'),
    ], check=True)
    print(json.dumps(dict(active_pools=['NH_PL36', library.POOL], selected_rows=len(display_rows),
                         posterior_rows=len(posterior_rows), candidate_library=manifest,
                         summaries=summaries), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
