"""Optional recorded chemical-identity review before panel release."""
import copy


def apply_review(pool, reviews):
    ids={r['candidate_id'] for r in pool}
    decisions={r['candidate_id']:r for r in reviews}
    if len(ids)!=len(pool) or len(decisions)!=len(reviews) or set(decisions)!=ids:
        raise ValueError('Identity review must cover every distinct candidate exactly once')
    eligible=[]; quarantine=[]
    for original in pool:
        review=decisions[original['candidate_id']]
        if review['decision'] not in {'retain','name_corrected','identity_unresolved'}:
            raise ValueError('Unsupported review disposition')
        if not review.get('reason') or not review.get('display_name'):
            raise ValueError('Name and recorded rationale required')
        row=copy.deepcopy(original)
        row.update(name=review['display_name'],review=review)
        if review['decision']=='identity_unresolved': quarantine.append(row)
        else: eligible.append(row)
    return {'eligible':eligible,'quarantine':quarantine,
            'review_does_not_establish_reaction_success':True}
