"""Build the explicitly defined 12 formulation × 8 solvent O–H library.

Two author-requested reference formulations are mandatory. The other ten are
sampled from formulation identities without consulting their response values.
Candidate-library construction and sequential BO observations are separate.
"""
from collections import Counter
from pathlib import Path
import csv
import hashlib
import json
import random
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
POOL = 'OH_CuNi_96'
FORMULATION_SEED = 20261111
MANDATORY = [('Cu66', 'K3PO4'), ('Ni203', 'DIPEA')]
CATALYST_NAMES = {'Cu66': '[Cu(MeCN)4]PF6', 'Ni203': 'NiCl2·DME'}


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def construct(source):
    original = [r for r in source if r['pool_id'] in ('OH_PL37', 'OH_PL38')]
    assert len(original) == 192
    universe = sorted({(r['cat'], r['base']) for r in original})
    assert len(universe) == 24
    solvents = list(dict.fromkeys(r['solvent'] for r in sorted(
        (r for r in original if r['pool_id'] == 'OH_PL37'),
        key=lambda r: int(r['candidate_index']))))
    assert len(solvents) == 8
    eligible = [key for key in universe if key not in MANDATORY]
    # This draw receives formulation identities only, never their responses.
    draw = random.Random(FORMULATION_SEED).sample(eligible, 10)
    selected = sorted(MANDATORY + draw)
    lookup = {(r['cat'], r['base'], r['solvent']): r for r in original}
    assert len(lookup) == 192
    formulations, candidates = [], []
    for row_index, (cat, base) in enumerate(selected):
        code = f'F{row_index + 1}'
        label = f'{cat} | {base}'
        formulations.append(dict(formulation_code=code, formulation=label,
            catalyst_code=cat, catalyst_name=CATALYST_NAMES[cat], base=base,
            selection_method='mandatory_reference' if (cat, base) in MANDATORY else 'uniform_random_without_replacement',
            random_draw_order='' if (cat, base) in MANDATORY else draw.index((cat, base)) + 1))
        for solvent in solvents:
            raw = lookup[cat, base, solvent]
            record = {k: v for k, v in raw.items() if k != 'response'}
            record.update(pool_id=POOL, source_pool_id=raw['pool_id'],
                source_candidate_index=raw['candidate_index'], candidate_index=len(candidates),
                formulation_code=code, formulation=label)
            candidates.append(record)
    assert len(candidates) == len({r['well'] for r in candidates}) == 96
    manifest = dict(pool_id=POOL, response_units='UV response',
        design='12 catalyst–base formulations crossed with 8 solvents',
        formulation_selection_seed=FORMULATION_SEED,
        formulation_rng='Python random.Random; sample without replacement from lexicographically sorted eligible (catalyst_code, literal_base) tuples',
        selection_rule='two mandatory reference formulations plus ten uniformly sampled from the other 22 formulation identities; no outcome-based seed search',
        candidate_library_information_boundary='The two mandatory formulations were chosen using known best Cu and Ni recipes at the author’s request. The remaining ten formulation identities were sampled without reading their responses. Therefore library construction is reference-informed; only the subsequent BO initial batch and acquisition are response-blind to unselected labels.',
        source_measurement_boundary='Every candidate is a distinct measured catalyst/base/solvent recipe. No response pooling, per-key maximum, imputation or prediction substitutes for a measurement.',
        candidate_order='formulations sorted lexicographically by (catalyst_code, literal_base), then solvents in original source-grid order (n-hexane, DCE, MeCN, THF, 1,4-dioxane, toluene, HFIP, DMF); candidate_index is a new logical index and source_candidate_index preserves the physical-grid index',
        mandatory_formulations=[dict(catalyst_code=cat, base=base) for cat, base in MANDATORY],
        eligible_formulations=[dict(catalyst_code=cat, base=base) for cat, base in eligible],
        random_formulations_in_draw_order=[dict(catalyst_code=cat, base=base) for cat, base in draw],
        formulations=formulations, solvents=solvents,
        catalyst_counts=dict(Counter(r['catalyst_code'] for r in formulations)),
        conditions=96, n_formulations=12, n_solvents=8,
        source_measurements=[dict(candidate_index=r['candidate_index'], formulation_code=r['formulation_code'],
            formulation=r['formulation'], catalyst_code=r['cat'], base=r['base'], solvent=r['solvent'],
            source_pool_id=r['source_pool_id'], source_candidate_index=r['source_candidate_index'],
            sample_id=r['well'], source_sheet=r['source_sheet'], source_excel_row=r['source_excel_row'],
            source_response_cell=r['source_response_cell'], source_workbook_sha256=r['source_workbook_sha256'])
            for r in candidates])
    return candidates, manifest


def feature_rows(candidates):
    formulations = sorted({r['formulation'] for r in candidates})
    solvents = sorted({r['solvent'] for r in candidates})
    names = ['formulation=' + f for f in formulations] + ['solvent=' + s for s in solvents] + [
        'pair=' + f + '|' + s for f in formulations for s in solvents]
    raw = np.asarray([[float(r['formulation'] == f) for f in formulations] +
        [float(r['solvent'] == s) for s in solvents] +
        [float(r['formulation'] == f and r['solvent'] == s) for f in formulations for s in solvents]
        for r in candidates])
    scale = raw.std(axis=0)
    scale[scale == 0] = 1
    X = (raw - raw.mean(axis=0)) / scale
    assert X.shape == (96, 116)
    return [dict(candidate_index=r['candidate_index'], well=r['well'], **dict(zip(names, X[i].tolist())))
        for i, r in enumerate(candidates)]


def build(source):
    target = ROOT / 'selections' / POOL
    candidates, manifest = construct(source)
    write_csv(target / 'candidates.csv', candidates)
    write_csv(target / 'standardized_features.csv', feature_rows(candidates))
    references = []
    for cat, base in MANDATORY:
        measured = [r for r in source if r['pool_id'] in ('OH_PL37', 'OH_PL38') and r['cat'] == cat]
        best = min(measured, key=lambda r: (-float(r['response']), int(r['candidate_index'])))
        assert best['base'] == base and best['well'] in {r['well'] for r in candidates}
        references.append(dict(catalyst_code=cat, base=base, solvent=best['solvent'],
            sample_id=best['well'], source_pool_id=best['pool_id'],
            source_response_cell=best['source_response_cell'], UV_response=float(best['response']),
            verification_scope='Post-construction source audit only; this label is not passed to the BO policy before selection.'))
    manifest['mandatory_reference_recipe_verification'] = references
    manifest['candidates_sha256'] = hashlib.sha256((target / 'candidates.csv').read_bytes()).hexdigest()
    manifest['standardized_features_sha256'] = hashlib.sha256((target / 'standardized_features.csv').read_bytes()).hexdigest()
    manifest['feature_dimensions'] = 116
    manifest['feature_definition'] = '12 formulation indicators + 8 solvent indicators + 96 formulation×solvent indicators; standardized over the unlabelled candidate library, no independent intercept'
    (target / 'candidate_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return candidates, manifest
