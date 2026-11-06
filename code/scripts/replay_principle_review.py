#!/usr/bin/env python3
"""Replay original principle proposal admission and review with exact saved responses."""
from pathlib import Path
import argparse,ast,json,shutil,sys,tempfile
R=Path(__file__).resolve().parents[1];D=R/'data/principle_calls'
def read(p):return json.loads(p.read_text())
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);a=p.parse_args()
 sys.path.insert(0,str(R/'principles'));sys.path.insert(0,str(R/'engine'))
 import proposal_admission as historical
 from pipeline.principle_models import SeedMechanism,TransferabilityAssessment
 from scripts.synthesize_tier_supplement_principles import build_review_prompt,validate_review
 seed=SeedMechanism.model_validate(read(D/'seed_mechanism.json'))
 rows=read(D/'transfer_assessments.json')['assessments']
 assessments={x.assessment_id:x for x in map(TransferabilityAssessment.model_validate,rows)}
 assert len(rows)==len(assessments)
 config=historical.CONFIG
 expected=read(D/'proposals.json');receipt=read(D/'review.json')
 with tempfile.TemporaryDirectory(prefix='reaction-principle-replay-') as tmp:
  t=Path(tmp);historical.DEST=t
  key=expected['cache_key'];q=t/'principles/cache'/key/'raw.json';q.parent.mkdir(parents=True);shutil.copy2(D/'proposal_response.json',q)
  result=historical.recover_current_proposals(seed,assessments,config)
  assert result is not None and result.cache_key==key
  proposals=[x.model_dump(mode='json') for x in result.principles]
  assert proposals==expected['principles']
  prompt=build_review_prompt(seed.model_dump(mode='json'),proposals,{k:v.model_dump(mode='json') for k,v in assessments.items()})
  review_digest=historical.digest({'seed':seed.model_dump(mode='json'),'proposals':proposals,'transfers':{k:v.model_dump(mode='json') for k,v in assessments.items()},'prompt':prompt,'model':'gpt-5.6-sol'})
  assert review_digest==receipt['input_digest'],'Original review input binding changed'
  accepted,rejected=validate_review(receipt['model_output'],result.principles,seed,assessments)
  prior=read(D/'reviewed.json')
  assert [x.model_dump(mode='json') for x in accepted]==prior['accepted']
  assert [x.model_dump(mode='json') for x in rejected]==prior['rejected']
 out={'status':'passed','network_calls':0,'model_calls':0,'proposal_input_digest':key,'review_input_digest':review_digest,'transfer_records':len(assessments),'admitted_proposals':len(result.principles),'review_accepted':len(accepted),'review_rejected':len(rejected),'original_proposal_and_review_outputs_equal':True,'scope':'Replays historical five-working-constraint proposal/review admission. Does not regenerate model responses or imply that current four-card synthesis was the original prompt.'}
 if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2)+'\n')
 print(json.dumps(out,indent=2))
if __name__=='__main__':main()
