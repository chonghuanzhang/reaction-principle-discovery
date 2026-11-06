#!/usr/bin/env python3
"""Draw Figures 2 and 4 using source structures and vector chemical diagrams."""
from pathlib import Path
import argparse,json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--font-file',type=Path);a=p.parse_args()
 env=dict(os.environ);env['REACTION_FIGURE_OUTPUT']=str(a.output_dir.resolve())
 if a.font_file:env['REACTION_FONT_FILE']=str(a.font_file.resolve())
 command="import sys;sys.path.insert(0,"+repr(str(ROOT/'figures'))+");import figures_gaoge as f;f.fig2();f.fig4()"
 result=subprocess.run([sys.executable,'-c',command],env=env,capture_output=True,text=True)
 if result.returncode:raise RuntimeError(result.stderr+'\n'+result.stdout)
 import pymupdf
 pages=[]
 for n in [2,4]:
  with pymupdf.open(a.output_dir/'figures'/f'Figure_{n}.pdf') as doc:
   assert len(doc)==1 and len(doc[0].get_images())==0
   assert doc[0].get_text().strip() and doc[0].get_drawings()
   from PIL import Image, ImageStat
   extrema=ImageStat.Stat(Image.open(a.output_dir/'figures'/f'Figure_{n}.png')).extrema
   assert any(lo<hi for lo,hi in extrema),'Rendered PNG is blank'
   pages.append({'figure':n,'pages':len(doc),'raster_images_in_pdf':0})
 print(json.dumps({'status':'passed','network_calls':0,'model_calls':0,'figures':pages,'font':'User-supplied font or Matplotlib DejaVu Sans','scope':'Scientific drawing functions and source structures; typography may vary across systems.'},indent=2))
if __name__=='__main__':main()
