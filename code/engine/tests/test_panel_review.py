import pytest
from pipeline.exploration_panel import validate_candidate,merge_candidates
from pipeline.panel_review import apply_review
from tests.test_exploration_panel import item


def test_review_requires_complete_identity_accounting_and_preserves_original():
    pool=merge_candidates([validate_candidate(item(),{})])
    with pytest.raises(ValueError): apply_review(pool,[])
    cid=pool[0]['candidate_id']
    review=[{'candidate_id':cid,'decision':'retain','display_name':'乙醇','reason':'structure agrees with name'}]
    result=apply_review(pool,review)
    assert result['eligible'][0]['name']=='乙醇'
    assert pool[0]['name']=='ethanol'
    assert result['eligible'][0]['success_probability'] is None


def test_identity_conflict_can_be_quarantined_without_chemical_failure():
    pool=merge_candidates([validate_candidate(item(),{})]); cid=pool[0]['candidate_id']
    result=apply_review(pool,[{'candidate_id':cid,'decision':'identity_unresolved','display_name':'ethanol','reason':'needs identity check'}])
    assert result['eligible']==[] and len(result['quarantine'])==1
    assert result['quarantine'][0]['review']['decision']=='identity_unresolved'
