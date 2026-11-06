from pipeline import panel_coverage as m
from pipeline.exploration_panel import validate_candidate,merge_candidates
from tests.test_exploration_panel import item


def test_functional_coverage_distinguishes_precursors_and_preserves_evidence():
    rows=merge_candidates([validate_candidate(item(),{}),validate_candidate(item('dimethyl ether','COC',1),{})])
    tagged=m.enrich_coverage(rows)
    assert tagged[0]['hypotheses']==rows[0]['hypotheses']
    assert tagged[0]['coverage_tags']!=tagged[1]['coverage_tags']
    assert any(t.startswith('fragment:') for r in tagged for t in r['coverage_tags'])
    assert not any(t.startswith('fragment:') for r in rows for t in r['coverage_tags'])


def test_element_bond_types_are_not_collapsed_into_element_presence():
    rows=merge_candidates([validate_candidate(item('sulfide','CSC',1,'S'),{}),
                           validate_candidate(item('disulfide','CSSC',1,'S'),{})])
    enriched=m.enrich_coverage(rows)
    disulfide=next(r for r in enriched if r['canonical_smiles']=='CSSC')
    assert 'bond:S-S:SINGLE' in disulfide['coverage_tags']
