"""Integrity tests, not independent chemical validation or outcome accuracy."""
import copy,json,unittest
from pathlib import Path
from conditional_rules import evaluate
HERE=Path(__file__).resolve().parent

class RuleContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules=json.loads((HERE/'executable_rules.json').read_text())
        cls.evidence={e for r in cls.rules for e in r['evidence_ids']}
        cls.queries=json.loads((HERE/'rule_queries.json').read_text())

    def test_missing_core_features_abstain(self):
        for q in self.queries:
            for key in ['substrate','donor','activation','target_endpoint']:
                modified=copy.deepcopy(q);modified.pop(key,None)
                self.assertEqual(evaluate(modified,self.rules,self.evidence)['decision'],'unknown')

    def test_remove_all_evidence_abstains(self):
        for q in self.queries:
            self.assertEqual(evaluate(q,self.rules,set())['decision'],'unknown')

    def test_unseen_substrate_is_not_failure(self):
        for q in self.queries:
            modified={**q,'substrate':'project_unvalidated_fluorocarbonyl'}
            self.assertEqual(evaluate(modified,self.rules,self.evidence)['decision'],'unknown')

    def test_source_exclusion_cannot_retain_call_to_removed_evidence(self):
        for e in self.evidence:
            for q in self.queries:
                self.assertNotIn(e,evaluate(q,self.rules,self.evidence-{e})['called_evidence'])

    def test_permutation_and_duplicate_evidence_invariance(self):
        for q in self.queries:
            a=evaluate(q,self.rules,self.evidence)
            b=evaluate(q,list(reversed(self.rules)),self.evidence)
            c=evaluate(q,self.rules+self.rules,self.evidence)
            self.assertEqual(a['decision'],b['decision'])
            self.assertEqual(a['decision'],c['decision'])

    def test_engine_conflict_abstention(self):
        # Synthetic software-only conflict fixture, never a literature fact.
        r=copy.deepcopy(next(r for r in self.rules if r['observation']['status']=='reported_product'))
        q={key:values[0] for key,values in r['requires'].items()}
        q['target_endpoint']=r['observation']['endpoint']
        opposite=copy.deepcopy(r);opposite['rule_id']='SYNTHETIC_SOFTWARE_CONFLICT';opposite['observation']['status']='target_not_observed'
        result=evaluate(q,[r]*5+[opposite],self.evidence)
        self.assertEqual(result['decision'],'abstain_conflicting_evidence')

    def test_no_success_probabilities_or_unknown_zero_yields(self):
        for q in self.queries:
            out=evaluate(q,self.rules,self.evidence)
            self.assertNotIn('success_probability',out)
            self.assertNotIn('yield',out)

    def test_conditions_do_not_collapse_to_element_classes(self):
        for q in self.queries:
            modified={**q,'donor':'all_'+q['donor']+'_element_compounds'}
            self.assertEqual(evaluate(modified,self.rules,self.evidence)['decision'],'unknown')

if __name__=='__main__':unittest.main(verbosity=2)
