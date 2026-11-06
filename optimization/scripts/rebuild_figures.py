#!/usr/bin/env python3
"""Render Figure 5 and its three supporting figures from supplied source tables."""
from pathlib import Path
import argparse,json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--font',default='DejaVu Sans');a=p.parse_args()
 from matplotlib import font_manager
 font_manager.findfont(a.font,fallback_to_default=False)
 env=dict(os.environ);env['REACTION_FIGURE_OUTPUT']=str(a.output.resolve());env['REACTION_FONT']=a.font
 for name in ['build_main_and_posterior.py','build_supporting.py']:
  result=subprocess.run([sys.executable,str(ROOT/'figure_code'/name)],env=env,capture_output=True,text=True)
  if result.returncode:raise RuntimeError(result.stderr+'\n'+result.stdout)
  print(result.stdout.strip())
 print(json.dumps({'status':'rendered','font':a.font,'figures':4,'supplied_artwork':'figures/figures','output':str(a.output.resolve())},indent=2))
if __name__=='__main__':main()
