"""Publication figures from archived measurements and author-supplied structures.

Run using the bundled Python runtime. All quantities are read from source data.
No product percentages from the author JPG are inferred to be isolated yields.
"""
from pathlib import Path
import sys,json,csv,collections,copy,shutil,re,hashlib,xml.etree.ElementTree as ET
import figures_support as U
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle,Rectangle,FancyArrowPatch,FancyBboxPatch
from matplotlib.ticker import PercentFormatter,MaxNLocator
from rdkit import Chem
from rdkit.Chem import rdDepictor,rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D
from PIL import Image

ROOT=U.ROOT
OLD=ROOT/'data'
BLUE='#214DA0';MID='#1F7AB4';CYAN='#2FA4C3';TEAL='#5EC0C1';GREEN='#A0DAB9';PALE='#D6EFB2'
PURPLE='#7B4AAF';DONOR='#268773';GREY='#66717A';INK='#1D2730';LIGHT='#DFE7EC'
DOCLOG=[]

def label(a,x,y,t,size=8,color=INK,**kw):return U.text(a,x,y,t.replace('→',r'$\rightarrow$'),size=size,color=color,**kw)

def panel(a,x,y,k,t):
 label(a,x,y,k,size=10,weight='bold');label(a,x+15,y,t,size=9.2,weight='bold')

def arrow(a,x,y,xx,yy,color=GREY,dashed=False):
 a.add_patch(FancyArrowPatch((x,y),(xx,yy),arrowstyle='-|>',mutation_scale=8,lw=.85,color=color,linestyle=(0,(3,2)) if dashed else '-'))

def divider(a,y):a.plot([13,U.WIDTH-13],[y,y],color=LIGHT,lw=.65)

def chem(f,key,smi,x,y,w,h,labels=None,fragment=False,all_color=None,font=8,bond=13.0):
 m=Chem.MolFromSmiles(smi);assert m is not None,(key,smi)
 rdDepictor.Compute2DCoords(m)
 if key.startswith('G') or key=='overview_target':
  ref=Chem.MolFromSmiles('C(=O)C=CF');query=Chem.MolFromSmarts('[C](=[O])-[C]=[C]-[F]')
  conf=Chem.Conformer(ref.GetNumAtoms());conf.Set3D(False)
  for i,(xx,yy) in enumerate([(0,0),(0,1.5),(1.3,-.75),(2.6,0),(2.6,1.5)]):conf.SetAtomPosition(i,(xx,yy,0))
  ref.RemoveAllConformers();ref.AddConformer(conf)
  match=m.GetSubstructMatch(query);assert len(match)==5,(key,match)
  rdDepictor.GenerateDepictionMatching2DStructure(m,ref,list(enumerate(match)))
 if key in ['overview_electrophile','cf3_entry','anionic_adduct','difluoro_branch']:
  conf=m.GetConformer()
  for i in range(m.GetNumAtoms()):
   p=conf.GetAtomPosition(i);conf.SetAtomPosition(i,(-p.x,-p.y,p.z))
 d=rdMolDraw2D.MolDraw2DSVG(int(w),int(h));o=d.drawOptions();o.useBWAtomPalette();o.fontFile=U.FONT;o.bondLineWidth=.8;o.fixedBondLength=bond;o.fixedFontSize=int(font);o.minFontSize=int(font);o.maxFontSize=int(font);o.padding=.04;o.clearBackground=False;o.addStereoAnnotation=False
 if labels:
  for at in m.GetAtoms():
   if at.GetAtomicNum()==0:o.atomLabels[at.GetIdx()]=labels.get(at.GetAtomMapNum(),'R')
 d.DrawMolecule(m);d.FinishDrawing();tree=ET.fromstring(d.GetDrawingText())
 atomcolors={i:all_color for i in range(m.GetNumAtoms())} if all_color else {}
 if fragment:
  roots=[]
  for at in m.GetAtoms():
   if at.GetSymbol()=='C' and any(n.GetSymbol()=='F' for n in at.GetNeighbors()):
    if any(b.GetBondType()==Chem.BondType.DOUBLE for b in at.GetBonds()):
     roots=[(at.GetIdx(),n.GetIdx()) for n in at.GetNeighbors() if n.GetSymbol() in ('N','O','S','Se','P','*')]
  assert len(roots)==1,(key,roots)
  blocked,start=roots[0];don=set();todo=[start]
  while todo:
   i=todo.pop()
   if i in don or i==blocked:continue
   don.add(i);todo.extend(n.GetIdx() for n in m.GetAtomWithIdx(i).GetNeighbors())
  atomcolors={i:DONOR if i in don else PURPLE for i in range(m.GetNumAtoms())}
 if atomcolors:
  for el in tree.iter():
   cls=el.get('class','');atoms=[int(n) for n in re.findall(r'atom-(\d+)',cls)]
   if not atoms:continue
   col=atomcolors[atoms[0]]
   if 'bond-' in cls and len(atoms)>1 and atomcolors[atoms[0]]!=atomcolors[atoms[1]]:col=atomcolors[atoms[-1]]
   for attr in ('style','fill','stroke'):
    if el.get(attr):el.set(attr,el.get(attr).replace('#000000',col).replace('#000',col))
 svg=ET.tostring(tree,encoding='unicode')
 (U.ASSETS/(key+'.svg')).write_text(svg)
 f._chem.append({'svg':svg,'x':x,'y':y,'w':w,'h':h,'key':key})
 DOCLOG.append({'id':key,'smiles':smi,'canonical_smiles':Chem.MolToSmiles(m),'formula':rdMolDescriptors.CalcMolFormula(m),'dummy_labels':labels,'fragment_colours':fragment,'stereochemistry_inferred':False})

def fig2():
 # Preserve the established chemical relationships while aligning colour and typography.
 sys.path.insert(0,str(Path(__file__).resolve().parent))
 import build_figures as prior
 prior.U=U
 oldchem=prior.chem
 prior.chem=lambda f,key,smi,x,y,w,h,labels=None:chem(f,key,smi,x,y,w,h,labels=labels)
 oldpanel=U.panel
 names={'a':'RP1   Acceptor activation','b':'RP2   Donor speciation and capture','c':'RP3   Intermediate branching','d':'RP4   Product persistence'}
 U.panel=lambda a,x,y,k,title='':oldpanel(a,x,y,k,names.get(k,title))
 prior.fig2()
 U.panel=oldpanel

def fig4():
 rows=U.rows(OLD/'figures/candidate_centres.csv');counts={x['centre_set']:int(x['molecules']) for x in rows}
 cs=json.loads((OLD/'structures/candidates.json').read_text())
 f,a,H=U.canvas(136)
 panel(a,13,H-15,'a','Candidate diversity across reacting centres')
 ax=f.add_axes([.115,.325,.36,.555]);groups=['C','N','O','S','P','Se','C/O','C/N'];cols=[BLUE,MID,CYAN,DONOR,TEAL,GREEN,'#83A2C8','#A0BFC8']
 for i,(g,col) in enumerate(zip(groups,cols)):
  ax.hlines(i,0,counts[g],color=col,lw=1.5);ax.scatter([counts[g]],[i],s=49,color=col,zorder=3);ax.text(counts[g]+1.1,i,str(counts[g]),fontsize=8,va='center',color=INK)
 ax.set(yticks=range(8),yticklabels=groups,ylim=(7.6,-.6),xlim=(0,36),xticks=[0,10,20,30],xlabel='Candidate molecules')
 ax.spines['left'].set_visible(False);ax.tick_params(axis='y',length=0);ax.grid(axis='x',color=LIGHT,lw=.5);ax.set_axisbelow(True)
 panel(a,267,H-15,'b','Donor form expands the search')
 examples=[('N–H and N salts',[(48,'Aniline'),(45,'Lithium anilide')]),('O–H and O salts',[(51,'Phenol'),(64,'Sodium phenoxide')]),('S–H and S–S',[(82,'Thiophenol'),(78,'Diphenyl disulfide')])]
 for j,(title,items) in enumerate(examples):
  yy=H-45-j*77;label(a,285,yy,title,8,[MID,CYAN,DONOR][j],weight='bold')
  for k,(num,name) in enumerate(items):
   rr=cs[num-1];chem(f,f'candidate_{num}',rr['candidate_smiles'],280+k*105,yy-53,94,45,all_color=[MID,CYAN,DONOR][j])
   label(a,327+k*105,yy-61,f'C{num:03}  {name}',6.9,ha='center')
 divider(a,86)
 panel(a,13,67,'c','Each molecule retains a chemical hypothesis')
 for j,(n,desc) in enumerate([('100','candidate molecules'),('115','route or site hypotheses'),('124','proposed product options')]):
  x=27+j*167;label(a,x,37,n,18,[BLUE,MID,DONOR][j],weight='bold');label(a,x+44,38,desc,7.5)
 U.save(f,'Figure_4');shutil.copy2(OLD/'figures/candidate_centres.csv',U.DATA/'candidate_centres.csv')
