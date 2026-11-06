"""Score supplied completed calls offline; preserve null results when none exist.

NumPy is needed only for the full paired five-repeat bootstrap.
"""
import argparse,csv,json
from collections import defaultdict
from pathlib import Path
from run_llm_diagnostic import validate_output
HERE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,required=True,help='Completed response JSON records only; no model is called.')
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    output=args.output_dir.resolve()
    package=HERE.parent.resolve()
    if output==package or package in output.parents:
        parser.error('Choose an output directory outside the supplied evaluation package.')
    output.mkdir(parents=True,exist_ok=True)
    answers={r['claim_id']:r for r in json.loads((HERE/'llm_answers_sealed_from_prompts.json').read_text())}
    valid_ids={r['evidence_id'] for r in json.loads((HERE/'llm_evidence.json').read_text())}
    raw=[];calls=[]
    for p in sorted(args.input_dir.glob('*.json')):
        x=json.loads(p.read_text())
        if x['status']!='completed':continue
        validate_output(x['result']['parsed_output']);rows=x['result']['parsed_output']['judgments']
        for r in rows:
            gold=answers[r['claim_id']]
            raw.append({'arm':x['arm'],'replicate':x['replicate'],'claim_id':r['claim_id'],
              'source_group':gold['source_group'],'expected_label':gold['label'],'observed_label':r['label'],
              'correct':int(r['label']==gold['label']),'citation_ids_valid':all(e in valid_ids for e in r['evidence_ids']),
              'unsupported_claim_accepted':int(gold['label']=='insufficient' and r['label']=='supported')})
        scored=raw[-len(rows):]
        calls.append({'arm':x['arm'],'replicate':x['replicate'],'label_agreement':sum(r['correct'] for r in scored)/len(scored),
          'valid_evidence_id_fraction':None if x['arm']=='no_retrieval' else sum(r['citation_ids_valid'] for r in scored)/len(scored),
          'elapsed_seconds':x['elapsed_seconds'],**x['result']['usage']})
    if not calls:
        out={'status':'NO_SUCCESSFUL_NEW_CALLS','successful_experimental_calls':0,'label_accuracy':None,
             'RP_incremental_effect':None,'claim':'No RP-versus-baseline performance result is available.'}
        (output/'llm_results_status.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out));return
    for name,rows in [('llm_per_claim.csv',raw),('llm_per_call.csv',calls)]:
        with (output/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    # Family-balanced primary effect: preserve paired repetition and source
    # identity; neither questions nor model repeats count as new chemistry.
    by_group=defaultdict(list)
    for r in raw:by_group[(r['arm'],r['replicate'],r['source_group'])].append(r['correct'])
    grouped={k:sum(v)/len(v) for k,v in by_group.items()}
    families=sorted({r['source_group'] for r in raw})
    paired=[i for i in range(1,6) if all((a,i,g) in grouped for a in ['RP_explicit','same_evidence_direct'] for g in families)]
    primary={'complete_paired_repeats':len(paired),'source_families':len(families),'difference':None,'ci_low':None,'ci_high':None}
    if len(paired)==5:
        import numpy as np
        differences=np.array([[grouped[('RP_explicit',i,g)]-grouped[('same_evidence_direct',i,g)] for g in families] for i in paired])
        rng=np.random.default_rng(20261025)
        repeat_ix=rng.integers(0,len(paired),(10000,len(paired)))
        family_ix=rng.integers(0,len(families),(10000,len(families)))
        samples=differences[repeat_ix[:,:,None],family_ix[:,None,:]].mean(axis=(1,2))
        low,high=np.quantile(samples,[.025,.975])
        primary.update(difference=float(differences.mean()),ci_low=float(low),ci_high=float(high))
    primary['estimand']='Difference in source-family-balanced label agreement; full RP minus same-evidence direct'
    primary['interval_scope']='Descriptive two-way paired bootstrap over six curated source families and five generation repeats; not a population-general chemical accuracy interval.'
    status={'status':'completed' if len(calls)==20 else 'partial','successful_experimental_calls':len(calls),
      'primary_comparison':primary,'total_reported_input_tokens':sum(c['input_tokens'] or 0 for c in calls),
      'total_reported_output_tokens':sum(c['output_tokens'] or 0 for c in calls),
      'any_missing_token_usage':any(c['input_tokens'] is None or c['output_tokens'] is None for c in calls),
      'elapsed_call_seconds':sum(c['elapsed_seconds'] for c in calls),'monetary_cost':None,
      'citation_metric_limit':'Checks identifier membership only; source entailment and rationale quality require a separate blinded human review.',
      'interpretation_limit':'Author-constructed source-evidence interpretation. No independent reaction-outcome holdout or chemical discovery accuracy.'}
    (output/'llm_results_status.json').write_text(json.dumps(status,indent=2)+'\n')
    print(json.dumps({'successful_calls':len(calls),'claim_assessments':len(raw),'status':status['status']}))

if __name__=='__main__':main()
