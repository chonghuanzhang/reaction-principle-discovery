"""Build source-scoped clauses and test queries from the reviewed evidence.

This is development/software verification on reviewed cases, not a holdout set.
Writes only to an explicitly selected directory outside the supplied package.
"""
import argparse,copy,csv,json
from pathlib import Path
from conditional_rules import evaluate
HERE=Path(__file__).resolve().parent
CHEM=HERE.parent/'chemistry'
DEST=None

def dump(n,x):(DEST/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')

def main():
    global DEST
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    DEST=args.output_dir.resolve()
    package=HERE.parent.resolve()
    if DEST==package or package in DEST.parents:
        parser.error('Choose an output directory outside the supplied evaluation package.')
    DEST.mkdir(parents=True,exist_ok=True)
    matrix=json.loads((CHEM/'pse_challenge_matrix.json').read_text())
    evidence={r['evidence_id']:r for r in json.loads((CHEM/'evidence.json').read_text())}
    cards={r['rp_id']:r for r in json.loads((CHEM/'principle_cards.json').read_text())}
    rules=[];queries=[]
    selected={'P01':'RP2','P02':'RP2','P05':'RP1','N01':'RP2','N03':'RP2','SE02':'RP3','SE03':'RP3','SE04':'RP3'}
    for c in matrix:
        if c['case_id'] not in selected:continue
        rp=selected[c['case_id']];card=cards[rp]
        substrate=c['substrate_smiles'] or 'source:'+c['substrate']
        activation='amide-directed NiH hydroselenylation' if c['case_id']=='SE04' else c['activation_mode']
        # Source identifiers retain incomplete structures instead of inventing SMILES.
        req={'substrate':[substrate],'donor':[c['donor']], 'activation':[activation]}
        req.update({'condition_'+k:[v] for k,v in c['conditions'].items()})
        obs={'status':'target_not_observed' if c['evidence_status']=='specified_target_not_detected' else 'reported_product',
             'endpoint':c['assessed_endpoint'],'source_case_id':c['case_id'],
             'source_reported_yield':c['yield_value'],'source_yield_basis':c['yield_basis']}
        clause={'rule_id':rp+'_'+c['case_id'],'principle_id':rp,'requires':req,
          'evidence_ids':c['evidence_ids'],'observation':obs,
          'effect':card['relation'],'direction':c['evidence_status']+': '+c['assessed_endpoint'],
          'boundary':c['limitations'],'access_level':evidence[c['evidence_ids'][0]]['access_level'],
          'missing_information':['Full phosphorus-specific recipe is not specified by source'] if c['case_id']=='P01' else ['Complete formed-intermediate connectivity/recipe not independently recorded'] if c['substrate_smiles'] is None else [],
          'inference_scope':'Curated source-observation clause, not a transferable prospective success predictor.'}
        rules.append(clause)
        queries.append({'query_id':'source_'+c['case_id'],**{k:v[0] for k,v in req.items()},'target_endpoint':c['assessed_endpoint']})
    # An endpoint switch asks a different chemical question of identical premises.
    p05=copy.deepcopy(next(q for q in queries if q['query_id']=='source_P05'))
    p05.update(query_id='P05_monoF_requested',target_endpoint='monofluorovinyl C-P target')
    queries.append(p05)
    # A donor-form swap with no matched observation stays unknown.
    ox=copy.deepcopy(next(q for q in queries if q['query_id']=='source_P05'))
    ox.update(query_id='P05_PIII_donor_swap',donor='Ph2PH, P(III)–H');queries.append(ox)
    for c in matrix:
        if c.get('project_exact_match') or c['case_id'] in ['SE_PROJECT','P_O_PROJECT']:
            queries.append({'query_id':c['case_id'],'substrate':c['substrate_smiles'] or 'source:'+c['substrate'],
               'donor':c['donor'],'activation':c['activation_mode'],'target_endpoint':c['assessed_endpoint'],
               **{'condition_'+k:v for k,v in c['conditions'].items()}})
    # Missing additive must not be silently defaulted to present or absent.
    q=copy.deepcopy(next(q for q in queries if q['query_id']=='source_SE03'))
    q.update(query_id='SE03_BnBr_unrecorded');q.pop('condition_BnBr_equiv');queries.append(q)
    dump('executable_rules.json',rules);dump('rule_queries.json',queries)
    # Preserve the supplied historical protocol; do not manufacture a new freeze.
    dump('rule_integrity_protocol.json',json.loads((HERE/'rule_integrity_protocol.json').read_text()))
    results=[evaluate(q,rules,set(evidence)) for q in queries]
    for out in results:
        out['missing_source_information']=[{'rule_id':r['rule_id'],'items':r['missing_information']} for r in rules if r['rule_id'] in out['applied_rules'] and r['missing_information']]
        out['reported_measurements']=[r['observation'] for r in rules if r['rule_id'] in out['applied_rules']]
    dump('rule_outputs.json',results)
    changes=[]
    for q,base in zip(queries,results):
        for e in sorted(set(base['called_evidence'])):
            changed=evaluate(q,rules,set(evidence)-{e})
            changes.append({'query_id':q['query_id'],'intervention':'remove_source_evidence','removed_evidence':e,
                 'before':base['decision'],'after':changed['decision'],
                 'decision_changed':base['decision']!=changed['decision'],
                 'interpretation':'Software evidence-dependency check; not a model ablation result'})
    with (DEST/'rule_evidence_interventions.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(changes[0]));w.writeheader();w.writerows(changes)
    with (DEST/'rule_decision_summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['query_id','decision','target_endpoint','applied_rules','called_evidence','scope'])
        w.writeheader()
        for r in results:w.writerow({**{k:r[k] for k in ['query_id','decision','target_endpoint']},'applied_rules':';'.join(r['applied_rules']),'called_evidence':';'.join(r['called_evidence']),'scope':'development/software integrity only'})
    print(json.dumps({'clauses':len(rules),'queries':len(queries),'evidence_deletion_interventions':len(changes),'project_cases_all_unknown':all(r['decision']=='unknown' for r in results if r['query_id'] in ['AP087','AP088','SE_PROJECT','P_O_PROJECT'])}))

if __name__=='__main__':main()
