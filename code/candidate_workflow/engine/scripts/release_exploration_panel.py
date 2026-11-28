"""Release a source-bound reviewed panel and optional answer-independent structure views."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pipeline.exploration_panel import digest, select_panel, experiment_plan, merge_candidates, summarize_feedback
from pipeline.panel_review import apply_review
from pipeline.panel_coverage import enrich_coverage
from rdkit import rdBase
from pipeline.evidence_registry import _atomic_json


def read(path): return json.loads(path.read_text())


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--extra-run',type=Path,action='append',default=[])
    parser.add_argument('--functional-coverage',action='store_true')
    parser.add_argument('--measurements',type=Path)
    args=parser.parse_args()
    original=read(args.run/'panel.json'); config=read(args.run/'manifest.json')['binding']['config']
    source_panels=[original]+[read(p/'panel.json') for p in args.extra_run]
    pool=merge_candidates([h for panel in source_panels for r in panel['selected']+panel['reserve'] for h in r['hypotheses']])
    review=read(args.review)
    if review['input_pool_digest']!=digest(sorted(pool,key=lambda r:r['candidate_id'])):
        raise ValueError('Review does not match current candidate pool')
    reviewed=apply_review(pool,review['decisions'])
    eligible=enrich_coverage(reviewed['eligible']) if args.functional_coverage else reviewed['eligible']
    panel=select_panel(eligible,config['panel_budget'])
    result={'review_digest':digest(review),'source_run':str(args.run.resolve()),
            'extra_runs':[str(p.resolve()) for p in args.extra_run],
            'source_panel_digests':[digest(p) for p in source_panels],
            'functional_coverage':args.functional_coverage,
            'rdkit_version':rdBase.rdkitVersion,
            'software_digest':digest({p.name:p.read_text() for p in [Path(__file__),Path(__file__).resolve().parents[1]/'pipeline/panel_review.py',Path(__file__).resolve().parents[1]/'pipeline/panel_coverage.py']}),
            'panel':panel,'quarantine':reviewed['quarantine'],
            'review_scope':'analyst reagent identity check, not chemical success or commercial confirmation'}
    out=args.run/'released'/digest(result)
    _atomic_json(out/'panel.json',result)
    _atomic_json(out/'experiments.json',experiment_plan(panel,config))
    if args.measurements:
        measurements=read(args.measurements)
        _atomic_json(out/'feedback'/f'{digest(measurements)}.json',
                     {'measurements':measurements,'summary':summarize_feedback(read(out/'experiments.json'),measurements)})
    _atomic_json(args.run/'released/latest.json',{'directory':str(out.resolve())})
    print(json.dumps({'directory':str(out.resolve()),'selected':len(panel['selected']),
                      'reserve':len(panel['reserve']),'quarantine':len(reviewed['quarantine'])}))
