#!/usr/bin/env python3
"""Replay exact saved candidate responses in a temporary copy; no API call."""
from pathlib import Path
import argparse,json,shutil,subprocess,sys,tempfile
R=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);a=p.parse_args()
 results=[]
 with tempfile.TemporaryDirectory(prefix='reaction-candidate-replay-') as tmp:
  d=Path(tmp)/'candidate_workflow';shutil.copytree(R/'candidate_workflow',d)
  for config,run in [('config.json','primary'),('compact_expansion_config.json','expansion')]:
   cmd=[sys.executable,'engine/scripts/replay_exploration_run.py','--config','inputs/'+config,'--run','artifacts/'+run]
   r=subprocess.run(cmd,cwd=d,text=True,capture_output=True)
   results.append({'run':run,'command':cmd[1:],'exit_code':r.returncode,'stdout':r.stdout.strip(),'stderr':r.stderr.strip()})
   if r.returncode:raise RuntimeError(json.dumps(results,indent=2))
  out={'status':'passed','network_calls':0,'model_calls':0,'results':results,'scope':'Exact saved model outputs are revalidated against frozen input, prompt, model and core-code digests; no new generation is performed. The primary and expansion pools are separate historical stages; the reviewed combined final collection remains 100 molecules.'}
 if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
