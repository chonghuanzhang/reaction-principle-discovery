"""Configurable upper workflow: prepare, propose/replay, panel and measured feedback."""
import argparse
import concurrent.futures
import json
import sys
import re
from pathlib import Path
from dataclasses import asdict

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pipeline.exploration_panel import (CandidatePayload, digest,validate_candidate,merge_candidates,
                                       select_panel,experiment_plan,summarize_feedback)
from pipeline.model_proposals import _strict_schema
from pipeline.evidence_registry import _atomic_json


def read(p): return json.loads(p.read_text())


def prepare(config, bundle):
    rows=bundle['evidence']; result=[]
    ids=[r['evidence_id'] for r in rows]
    if len(ids)!=len(set(ids)): raise ValueError('Evidence IDs must be globally unique')
    for lens in config['lenses']:
        patterns=[re.compile(p,re.I) for p in lens['patterns']]
        ranked=[]
        for row in rows:
            text=row['claim']+'\n'+row['quotation']
            hits=[bool(p.search(text)) for p in patterns]
            if hits[0]: ranked.append((sum(hits),row))
        chosen=[]; counts={}
        for _,row in sorted(ranked,key=lambda x:(-x[0],x[1]['evidence_id'])):
            key=row['source_id']
            if counts.get(key,0)>=config['per_source_cap']: continue
            chosen.append(row);counts[key]=counts.get(key,0)+1
            if len(chosen)>=config['evidence_per_lens']: break
        result.append({'study':{k:config[k] for k in ('study_id','fixed_component','target','variable_role')},
            'requested_candidate_count':config.get('candidate_count',12),
            'lens':lens,'seed':bundle['seed'],'principles':bundle['principles'],
            'source_corrections':bundle.get('corrections',[]),'evidence':chosen,
            'retrieval_count':len(ranked),'evidence_role_notice':'Source facts/analogy are not proof of new reaction success.'})
    return result


PROMPT = '''You are a synthetic chemist designing a finite exploratory reagent panel.
Propose the requested_candidate_count concrete, simple, diverse reagent molecules within the supplied mechanism lens.
The objective is experimental search coverage, NOT a list restricted to known successes.
Do not require the original Seed partner/catalytic cycle for new bond types. Keep fixed target connectivity.
Consider neutral pi nucleophiles, lone-pair donors, anions, metal-transfer precursors and sigma-bond donors
when pertinent to this lens. Distinguish the atom forming the bond from other heteroatoms in the molecule.
Include boundary probes as chemically reasoned hypotheses when evidence is uncertain.
No candidate must be included to reproduce a known result. No desired named family list is supplied.
Use exact valid SMILES and ZERO-BASED RDKit atom indices in that submitted SMILES for possible bond-forming atoms.
center is the element symbol at each cited atom. If multiple atoms/elements may react, use separate proposals.
Each proposal lens must exactly equal supplied lens.id. Do not propose unspecified groups or metal intermediates
as purchasable reagents. Unknown commercial availability is acceptable; do not invent CAS, stock or prices.
Write name (standard reagent name) and all explanations in readable Chinese where possible.
basis: local_analogy, source_system, or model_hypothesis. Cite only exact supplied evidence_id and
UNCHANGED quotation substrings. A proposed exact molecule need not have been used in the source:
explicitly describe extrapolation. Hypotheses may have no citations. Never invent references.
Report activation need, condition-sensitive risks and a discriminating test, not fabricated ready-to-run dosing.
Unknown condition compatibility is not a rejection. Return uncovered areas honestly.
No reaction probability, guaranteed success, or intrinsic family-failure statements.
'''


def run(config_path, output, live=False):
    config=read(config_path)
    bundle_path=(config_path.parent/config['bundle']).resolve()
    bundle=read(bundle_path)
    code=[Path(__file__),Path(__file__).resolve().parents[1]/'pipeline/exploration_panel.py']
    binding={'config':config,'bundle_digest':digest(bundle),'code':{p.name:digest(p.read_text()) for p in code},
             'model':config['model'],'schema':_strict_schema(CandidatePayload),'prompt':PROMPT}
    run_id=digest(binding)
    out=output/run_id
    _atomic_json(out/'manifest.json',{'binding':binding,'run_id':run_id,'mode':'exploratory_panel_not_success_prediction'})
    inputs=prepare(config,bundle)
    def one(payload):
        lens=payload['lens']['id']; path=out/'lenses'/lens
        _atomic_json(path/'input.json',payload)
        prompt=PROMPT+'\n'+json.dumps(payload,ensure_ascii=False)
        key=digest({'prompt':prompt,'schema':binding['schema'],'model':config['model']})
        raw_path=path/'raw.json'
        if raw_path.exists():
            raw=read(raw_path)
            if raw['input_digest']!=key: raise ValueError('Stale model response')
        elif not live:
            raise ValueError('No saved response for offline replay: '+lens)
        else:
            from pipeline.run_pilot import _default_client
            response=_default_client(config['model']).create_structured(config['model'],prompt,binding['schema'],'exploratory_reagents')
            raw={'input_digest':key,'status':response.status,'response_id':response.response_id,
                 'returned_model':response.returned_model,'usage':asdict(response.usage),'model_output':response.parsed_output}
            _atomic_json(raw_path,raw)
        if raw['status']!='completed': raise ValueError('Incomplete model response')
        parsed=CandidatePayload.model_validate(raw['model_output'])
        accepted=[]; rejected=[]
        evidence={r['evidence_id']:r for r in payload['evidence']}
        for candidate in parsed.candidates:
            try:
                row=validate_candidate(candidate.model_dump(),evidence)
                if row['lens']!=lens: raise ValueError('Wrong lens identity')
                accepted.append(row)
            except ValueError as exc:
                rejected.append({'candidate':candidate.model_dump(),'reason':str(exc)})
        result={'accepted':accepted,'rejected':rejected,'uncovered':parsed.uncovered,'input_digest':key}
        _atomic_json(path/'validated.json',result)
        print('LENS',lens,'accepted',len(accepted),'rejected',len(rejected),flush=True)
        return result
    results=[]; failures=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.get('workers',3)) as pool:
        futures={pool.submit(one,p):p['lens']['id'] for p in inputs}
        for future in concurrent.futures.as_completed(futures):
            try: results.append(future.result())
            except Exception as exc: failures.append({'lens':futures[future],'error':str(exc)[:1000]})
    if failures:
        _atomic_json(out/'failures.json',failures)
        raise ValueError('Incomplete lens coverage; no panel published: '+str(failures))
    candidates=merge_candidates([r for result in results for r in result['accepted']])
    panel=select_panel(candidates,config['panel_budget'])
    experiments=experiment_plan(panel,config)
    evidence_index={r['evidence_id']:r for r in bundle['evidence']}
    selected_ids={c['evidence_id'] for r in panel['selected'] for h in r['hypotheses'] for c in h['citations']}
    _atomic_json(out/'panel.json',panel)
    _atomic_json(out/'selected_evidence.json',{i:evidence_index[i] for i in sorted(selected_ids)})
    _atomic_json(out/'experiments.json',experiments)
    summary={'run_id':run_id,'directory':str(out.resolve()),'pool_size':len(candidates),
             'selected_count':len(panel['selected']),'rejected_proposals':sum(len(r['rejected']) for r in results),
             'uncovered_tags':panel['uncovered_tags'],'generated_lenses':len(results),
             'experimental_success_claimed':False,'instrument_ready':False}
    _atomic_json(out/'summary.json',summary);_atomic_json(output/'latest.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return out


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--feedback',type=Path)
    args=parser.parse_args()
    if args.feedback:
        latest=read(args.output/'latest.json'); root=Path(latest['directory'])
        report=summarize_feedback(read(root/'experiments.json'),read(args.feedback))
        _atomic_json(root/'feedback'/f'{digest(read(args.feedback))}.json',{'measurements':read(args.feedback),'summary':report})
        print(report)
    else: run(args.config.resolve(),args.output.resolve(),args.live)
