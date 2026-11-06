#!/usr/bin/env python3
"""Recompute frozen scientific tables and compare them with supplied records."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[1]
ENV='REACTION_NOVELTY_OUTPUT'
SOURCE='novelty/apply_review.py'
EXPECTED='novelty/reviewed'
FILES=['novelty_candidates_100.json', 'novelty_hypotheses_115.json', 'novelty_product_options_124.json', 'novelty_actual_pairs_108.json']
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);a=p.parse_args()
 with tempfile.TemporaryDirectory(prefix='reaction-reproduction-') as tmp:
  env=dict(os.environ);env[ENV]=tmp
  result=subprocess.run([sys.executable,str(ROOT/SOURCE)],env=env,capture_output=True,text=True)
  if result.returncode:raise RuntimeError(result.stderr+'\n'+result.stdout)
  comparisons=[]
  for name in FILES:
   actual=(Path(tmp)/name).read_bytes();expected=(ROOT/'data'/EXPECTED/name).read_bytes()
   comparisons.append({'file':name,'byte_identical':actual==expected,'sha256':hashlib.sha256(actual).hexdigest()})
  assert all(x['byte_identical'] for x in comparisons),comparisons
 report={'status':'passed','network_calls':0,'model_calls':0,'comparisons':comparisons}
 if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report,indent=2))
if __name__=='__main__':main()
