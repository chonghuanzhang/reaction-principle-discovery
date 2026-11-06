"""Conservative, executable, source-conditioned chemical evidence layer.

This is a newly authored rule interpreter, not a learned chemical predictor.
Source observations and conditional extrapolations remain distinct.
"""
from __future__ import annotations
import json
from pathlib import Path

def evaluate(query: dict, rules: list[dict], available_evidence: set[str]) -> dict:
    required = ['substrate', 'donor', 'activation', 'target_endpoint']
    missing_input = [k for k in required if query.get(k) is None]
    audits=[]; active=[]
    for rule in rules:
        failed=[]; unknown=[]
        for name, expected in rule['requires'].items():
            actual=query.get(name)
            if actual is None:
                unknown.append(name)
            elif actual not in expected:
                failed.append({'feature':name,'actual':actual,'allowed':expected})
        absent=[e for e in rule['evidence_ids'] if e not in available_evidence]
        state='not_satisfied' if failed else 'unknown' if unknown or absent else 'satisfied'
        audit={'rule_id':rule['rule_id'],'principle_id':rule['principle_id'],
               'premise_state':state,'mismatches':failed,'missing_features':unknown,
               'missing_evidence':absent,'evidence_ids':rule['evidence_ids']}
        audits.append(audit)
        if state=='satisfied':active.append(rule)
    # No majority vote: contradictory claims about the same endpoint abstain,
    # even if one direction has more copies or a higher citation count.
    supported=set(); not_observed=set()
    for r in active:
        if r['observation']['status']=='reported_product':supported.add(r['observation']['endpoint'])
        if r['observation']['status']=='target_not_observed':not_observed.add(r['observation']['endpoint'])
    conflict=sorted(supported & not_observed)
    target=query.get('target_endpoint')
    if conflict:
        decision='abstain_conflicting_evidence'
    elif target in supported:
        decision='reported_target_in_matched_source_system'
    elif target in not_observed:
        decision='target_not_observed_in_matched_source_system'
    elif supported:
        decision='reported_other_endpoint_target_unresolved'
    else:
        decision='unknown'
    output={
      'query_id':query.get('query_id'),'decision':decision,
      'target_endpoint':target,'reported_endpoints':sorted(supported),
      'explicitly_not_observed_endpoints':sorted(not_observed),
      'conflicting_endpoints':conflict,'missing_required_input':missing_input,
      'rule_audit':audits,'applied_rules':[r['rule_id'] for r in active],
      'called_evidence':sorted({e for r in active for e in r['evidence_ids']}),
      'local_chemical_relations':[{'principle_id':r['principle_id'],
         'effect':r['effect'],'direction':r['direction'],'boundary':r['boundary']} for r in active],
      'source_reliability':[{'evidence_id':e,'access_level':r['access_level']} for r in active for e in r['evidence_ids']],
      'transfer_distance':'matched source context' if active else 'outside an executable source-conditioned clause or missing premises',
      'prediction_uncertainty':'This interpreter has no calibrated reaction-success probability.',
      'scope':'Reported source-system evidence. Matching is on explicitly supplied curated descriptors; this does not establish prospective reactivity.'}
    if missing_input:
        output['decision']='unknown'
    return output

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('queries',type=Path)
    p.add_argument('--rules',type=Path,default=Path(__file__).with_name('executable_rules.json'))
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    rules=json.loads(args.rules.read_text())
    available={e for r in rules for e in r['evidence_ids']}
    rows=[evaluate(q,rules,available) for q in json.loads(args.queries.read_text())]
    out=json.dumps(rows,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.write_text(out)
    else:print(out)

if __name__=='__main__':main()
