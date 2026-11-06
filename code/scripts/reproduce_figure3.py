#!/usr/bin/env python3
"""Reconstruct the Figure 3 SVG from the frozen complete network drawing."""
from pathlib import Path
import argparse,json,shutil,subprocess,xml.etree.ElementTree as E
R=Path(__file__).resolve().parents[2]/'knowledge_graph'
REMOVE=['line2d_1','line2d_2','line2d_3','line2d_4','line2d_7','text_10','text_100','text_101','text_11','text_12','text_13','text_14','text_15','text_16','text_17','text_18','text_19','text_2','text_4','text_6','text_7','text_8','text_9','text_90','text_91','text_92','text_93','text_94','text_95','text_96','text_97','text_98','text_99']
def canonical(e):
 return (e.tag,tuple(sorted(e.attrib.items())),(e.text or '').strip(),tuple(canonical(c) for c in e))
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--render',action='store_true');a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
 base=R/'figures/network_full.svg'
 master=R/'figures/Figure_3.svg'
 root=E.fromstring(base.read_bytes());ids={e.get('id') for e in root.iter()}
 assert set(REMOVE)<=ids
 for parent in root.iter():
  for child in list(parent):
   if child.get('id') in REMOVE:parent.remove(child)
 root.set('height','457pt');root.set('viewBox','0 63 510.236 457')
 assert canonical(root)==canonical(E.fromstring(master.read_bytes())), 'SVG artwork differs from supplied master'
 E.register_namespace('','http://www.w3.org/2000/svg');E.register_namespace('xlink','http://www.w3.org/1999/xlink')
 svg=a.output_dir/'Figure_3.svg';svg.write_bytes(E.tostring(root,encoding='utf-8',xml_declaration=True))
 rendering=None
 if a.render:
  import pymupdf
  renderer=shutil.which('rsvg-convert')
  if renderer is None:raise SystemExit('Figure 3 PDF/PNG export requires rsvg-convert (librsvg); see code/README.md.')
  pdf=a.output_dir/'Figure_3.pdf'
  subprocess.run([renderer,'--format=pdf','--output',str(pdf),str(svg)],check=True)
  with pymupdf.open(pdf) as document:
   assert len(document)==1 and not document[0].get_images(), 'Expected one vector PDF page'
   expected_dashes=sum('stroke-dasharray:' in node.get('style','') for node in root.iter())
   rendered_dashes=sum(item['dashes'] not in (None,'','[] 0') for item in document[0].get_drawings())
   assert rendered_dashes==expected_dashes, 'Rendered PDF changed dashed edge styles'
   document[0].get_pixmap(dpi=600,alpha=False).save(a.output_dir/'Figure_3.png')
  rendering={'svg_to_pdf':subprocess.check_output([renderer,'--version'],text=True).splitlines()[0],'pdf_to_png':'PyMuPDF '+pymupdf.VersionBind,'dashed_paths_preserved':rendered_dashes,'pdf_pages':1,'raster_images_in_pdf':0}
 report={'status':'passed','network_calls':0,'groups_removed':len(REMOVE),'surviving_svg_tree_matches_supplied_figure':True,'rendered':a.render,'rendering':rendering,'output_svg':str(svg),'description':'Removes four tier banners, three grey header subtitles, the focus note, the current P/Se review band and its rule, then crops. Core geometry, source tags, three headings and legend retain the frozen artwork.'}
 (a.output_dir/'reproduction_report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
