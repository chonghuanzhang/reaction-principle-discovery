"""Saved principle proposal admission and exact prompt configuration."""

from pathlib import Path

import hashlib,json

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def read(path):
    return json.loads(path.read_text())

def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

DEST=Path()

CONFIG={'model': 'gpt-5.6-sol', 'prompt_version': 'admitted-principles-v1', 'max_assessments': 120, 'max_per_paper': 1, 'prompt_text': 'Induce a compact falsifiable Reaction Principle set from source-grounded Seed features and qualified Knowledge Transfer only. Include seed_specific and transferable_super layers. Do not propose named target families, use later project outcomes or assume the proposed Seed mechanism is established. Preserve conditions, contradictory Seed scope statements, negative and unknown evidence. Every principle needs supplied Seed and transfer evidence IDs, experimental consequence and falsifier. Use proposed/pending status and freeze_version=null.'}

def partition_principles(proposals, seed_ids, assessments):
    from pipeline.principle_induction import validate_principle_candidate, PrincipleInductionError
    accepted, rejected = [], []
    for proposal in proposals:
        try:
            if proposal.status != 'proposed' or proposal.review_status != 'pending':
                raise PrincipleInductionError('Model candidate cannot self-accept')
            accepted.append(validate_principle_candidate(proposal, known_seed_evidence_ids=seed_ids, transfer_assessments=assessments))
        except PrincipleInductionError as exc:
            rejected.append({'principle': proposal.model_dump(mode='json'), 'reason': str(exc), 'disposition': 'excluded; caution only, not a transferred principle'})
    return accepted, rejected

def recover_current_proposals(seed, assessments, config):
    from pipeline.model_proposals import select_principle_evidence, _digest, _strict_schema, PrincipleProposalPayload, PrincipleProposalResult
    selection = select_principle_evidence(seed, assessments, max_assessments=config['max_assessments'], max_per_paper=config['max_per_paper'], exploration_brief=None)
    selected = {key: assessments[key] for key in selection.assessment_ids}
    key = _digest({'seed': seed.model_dump(mode='json'), 'assessments': {k: v.model_dump(mode='json') for k, v in selected.items()}, 'selection': selection.model_dump(mode='json'), 'config': config, 'schema': _strict_schema(PrincipleProposalPayload)})
    path = DEST/'principles/cache'/key/'raw.json'
    if not path.exists():
        return None
    raw = read(path)
    if raw.get('cache_key') != key:
        raise ValueError('Raw proposal receipt input mismatch')
    payload = PrincipleProposalPayload.model_validate(raw['model_output'])
    accepted, rejected = partition_principles(payload.principles, set(seed.evidence_ids), selected)
    write(DEST/'principles/per_candidate_admission.json', {'cache_key': key, 'raw_path': str(path), 'raw_digest': digest(raw), 'selected_assessments': list(selected), 'accepted_ids': [p.principle_id for p in accepted], 'rejected': rejected, 'formal_validation_complete': False})
    if not accepted:
        raise ValueError('No proposal meets unchanged admission gate')
    return PrincipleProposalResult(status='validated', cache_key=key, principles=tuple(accepted), usage=raw['api']['usage'])
