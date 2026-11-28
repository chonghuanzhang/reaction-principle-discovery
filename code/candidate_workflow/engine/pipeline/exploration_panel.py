"""Portable evidence-to-reagent panel logic. Coverage is not reaction probability."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator
from pydantic import BaseModel, ConfigDict, Field


class Citation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    evidence_id: str
    quote: str


class Candidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1)
    smiles: str = Field(min_length=1)
    atom_indices: list[int] = Field(min_length=1)
    center: str = Field(min_length=1)
    family: str = Field(min_length=1)
    reactive_form: str = Field(min_length=1)
    route: str = Field(min_length=1)
    lens: str = Field(min_length=1)
    basis: str
    citations: list[Citation]
    reason: str = Field(min_length=1)
    activation: str = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    diagnostic: str = Field(min_length=1)


class CandidatePayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidates: list[Candidate] = Field(min_length=1, max_length=24)
    uncovered: list[str]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_candidate(raw, evidence):
    row = Candidate.model_validate(raw).model_dump()
    if row['basis'] not in {'local_analogy', 'source_system', 'model_hypothesis'}:
        raise ValueError('Unknown evidence role')
    if row['basis'] != 'model_hypothesis' and not row['citations']:
        raise ValueError('Non-hypothesis requires traceable quotation')
    for c in row['citations']:
        if c['evidence_id'] not in evidence or len(c['quote'].strip()) < 15 or c['quote'] not in evidence[c['evidence_id']]['quotation']:
            raise ValueError('Citation is not an exact supplied quotation')
    mol = Chem.MolFromSmiles(row['smiles'])
    if mol is None or mol.GetNumAtoms() == 0:
        raise ValueError('Invalid molecular structure')
    if len(set(row['atom_indices'])) != len(row['atom_indices']):
        raise ValueError('Repeated reactive atom index')
    for i in row['atom_indices']:
        if i < 0 or i >= mol.GetNumAtoms() or mol.GetAtomWithIdx(i).GetSymbol() != row['center']:
            raise ValueError('Reactive atom index/element mismatch')
    canonical = Chem.MolToSmiles(mol, isomericSmiles=True)
    return {**row, 'canonical_smiles': canonical, 'structure_key': digest(canonical)[:16],
            'success_probability': None, 'identity_status': 'SMILES validated; name association requires review'}


def merge_candidates(rows):
    groups = {}
    for row in sorted(rows, key=lambda x:(x['structure_key'], x['lens'],x['name'],digest(x))):
        key = row['structure_key']
        if key not in groups:
            groups[key] = {'candidate_id': 'CP-'+key, 'structure_key': key,
                'canonical_smiles': row['canonical_smiles'], 'name': row['name'],
                'hypotheses': [], 'success_probability': None}
        if row not in groups[key]['hypotheses']:
            groups[key]['hypotheses'].append(row)
    for row in groups.values():
        row['coverage_tags'] = sorted({f"center:{h['center']}" for h in row['hypotheses']} |
                                      {f"lens:{h['lens']}" for h in row['hypotheses']})
    return list(groups.values())


def select_panel(pool, budget):
    if type(budget) is not int or budget < 1:
        raise ValueError('Positive integer panel budget required')
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=2,fpSize=2048)
    fingerprints = {r['candidate_id']:generator.GetFingerprint(Chem.MolFromSmiles(r['canonical_smiles'])) for r in pool}
    pending = sorted(pool,key=lambda r:r['candidate_id'])
    selected, covered, trace = [], set(), []
    while pending and len(selected) < budget:
        def utility(row):
            new = len(set(row['coverage_tags'])-covered)
            novelty = 1.0 if not selected else 1-max(DataStructs.TanimotoSimilarity(fingerprints[row['candidate_id']],fingerprints[s['candidate_id']]) for s in selected)
            has_citation = any(h['citations'] for h in row['hypotheses'])
            return (new, round(novelty,8), int(has_citation))
        best = max(pending,key=utility)
        trace.append({'candidate_id':best['candidate_id'],'new_tags':sorted(set(best['coverage_tags'])-covered),
                      'selection_tuple':list(utility(best))})
        covered.update(best['coverage_tags']); selected.append(best); pending.remove(best)
    available = set().union(*(set(r['coverage_tags']) for r in pool)) if pool else set()
    return {'selected':selected,'reserve':pending,'coverage_tags':sorted(covered),
            'uncovered_tags':sorted(available-covered),'selection_trace':trace,
            'selection_meaning':'mechanism-lens/center coverage then structural diversity; not likelihood ranking',
            'budget':budget}


def experiment_plan(panel, config):
    rows=[]
    for candidate in panel['selected']:
        for mode in ['screen','no_catalyst','no_base']:
            rows.append({'experiment_id':f"{config['study_id']}-{candidate['candidate_id']}-{mode}",
                'candidate_id':candidate['candidate_id'],'role':mode,'fixed_component':config['fixed_component'],
                'target':config['target'],'reagent_smiles':candidate['canonical_smiles'],
                'recipe':{'substrate_umol':None,'partner_equivalents':None,'catalyst':None,'catalyst_loading':None,
                          'base':None,'base_loading':None,'solvent':None,'temperature_C':None,'time_h':None},
                'instrument_ready':False,'activation_hypotheses':[h['activation'] for h in candidate['hypotheses']],
                'interpretation':'Absent target signal is condition-specific; controls do not prove an elementary mechanism.'})
    for mode in ['seed_positive_1','seed_positive_2','analytical_blank']:
        rows.append({'experiment_id':f"{config['study_id']}-{mode}",'role':mode,
                     'instrument_ready':False,'recipe':None,'target':config['target']})
    return rows


def summarize_feedback(experiments, measurements):
    known={r['experiment_id']:r for r in experiments}
    if len(known)!=len(experiments): raise ValueError('Duplicate planned experiment IDs')
    seen=set(); outcomes=Counter()
    for row in measurements:
        eid=row.get('experiment_id')
        if eid not in known or eid in seen: raise ValueError('Unknown or duplicate experiment ID')
        seen.add(eid)
        if row.get('outcome') not in {'target_detected','target_not_detected','inconclusive'}:
            raise ValueError('Explicit measured outcome required')
        if not row.get('assay') or not row.get('conditions'):
            raise ValueError('Actual assay and conditions required')
        if row['outcome']=='target_detected' and not row.get('target_identity'):
            raise ValueError('Target identity evidence required')
        if row['outcome']=='target_not_detected' and not row.get('detection_limit'):
            raise ValueError('Detection limit required for a negative target observation')
        if known[eid]['role']=='screen': outcomes[row['outcome']]+=1
    tested=outcomes['target_detected']+outcomes['target_not_detected']
    return {'measured_screen_outcomes':dict(outcomes),'observed_hit_rate':outcomes['target_detected']/tested if tested else None,
            'unmeasured_count':len(known)-len(seen),'comparison_to_baseline':'not estimated without matched baseline data',
            'inconclusive_not_counted_as_failure':True}
