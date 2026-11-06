"""Five scientific figures with vector chemical structures and auditable source data."""
from pathlib import Path
import json,sys,csv,collections,xml.etree.ElementTree as ET
import plotting as U
import numpy as np
from rdkit import Chem
from rdkit.Chem import rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D
from matplotlib.patches import FancyArrowPatch,Rectangle,Circle
from matplotlib.ticker import PercentFormatter,MaxNLocator
def arrow(a,x,y,xx,yy,dashed=False,color=U.BLACK,style='-|>'):
 a.add_patch(FancyArrowPatch((x,y),(xx,yy),arrowstyle=style,mutation_scale=8,lw=.85,linestyle=(0,(3,2)) if dashed else '-',color=color))

def chem(f,key,smi,x,y,w,h,labels=None):
 m=Chem.MolFromSmiles(smi);assert m is not None,(key,smi)
 rdDepictor.Compute2DCoords(m)
 d=rdMolDraw2D.MolDraw2DSVG(int(w),int(h));o=d.drawOptions();o.useBWAtomPalette();o.fontFile=U.FONT;o.bondLineWidth=.8;o.fixedBondLength=13;o.fixedFontSize=8;o.minFontSize=8;o.maxFontSize=8;o.padding=.035;o.clearBackground=False
 if labels:
  for at in m.GetAtoms():
   if at.GetAtomicNum()==0:o.atomLabels[at.GetIdx()]=labels.get(at.GetAtomMapNum(),'R')
 d.DrawMolecule(m);d.FinishDrawing();s=d.GetDrawingText();(U.ASSETS/(key+'.svg')).write_text(s)
 f._chem.append({'svg':s,'x':x,'y':y,'w':w,'h':h,'key':key})
 U.structure_log.append({'key':key,'smiles':smi,'dummy_labels':labels,'structure_type':'generic_relationship' if labels else 'input_structure','F_atoms':sum(a.GetAtomicNum()==9 for a in m.GetAtoms())})

def label(a,x,y,t,color=U.BLACK,size=8,**kw):return U.text(a,x,y,t,size=size,color=color,**kw)

def divider(a,y):a.plot([10,U.WIDTH-10],[y,y],color=U.LIGHT,lw=.6)

def tag(a,x,y,t,color=U.NAVY):label(a,x,y,t,color,8.3,weight='bold')

def fig2():
 f,a,H=U.canvas(183)
 U.panel(a,10,H-14,'a','RP1   Acceptor activation determines the accessible reaction channel')
 chem(f,'cf3_entry','[*:1]C(=O)CC(F)(F)F',18,H-93,123,60,{1:'R'})
 chem(f,'cf2_acceptor','[*:1]C(=O)C=C(F)F',240,H-93,120,60,{1:'R'})
 arrow(a,147,H-63,231,H-63,dashed=True)
 label(a,188,H-46,'Activation',size=7.6,ha='center');label(a,188,H-80,'Source-dependent',U.GREY,7,ha='center')
 label(a,377,H-48,'Capture at the activated site',U.NAVY,7.7)
 label(a,377,H-67,'versus carbonyl addition',U.GREY,7.2)
 label(a,377,H-82,'or scaffold fragmentation',U.GREY,7.2)
 label(a,25,H-111,'A saturated CF₃ precursor and a preformed CF₂ alkene require different entry steps.',U.GREY,7.5)
 divider(a,H-126)
 U.panel(a,10,H-144,'b','RP2   Reactive form controls capture across donor classes')
 chem(f,'donor_aniline','Nc1ccccc1',18,H-222,74,55)
 chem(f,'donor_phenol','Oc1ccccc1',103,H-222,74,55)
 chem(f,'donor_thiol','Sc1ccccc1',188,H-222,74,55)
 label(a,140,H-235,'N–H  /  O–H  /  S–H precursors',size=7.8,ha='center')
 arrow(a,279,H-195,352,H-195,style='<|-|>')
 label(a,315,H-178,'Base / medium',size=7.4,ha='center')
 label(a,315,H-213,'Counterion / metal',U.GREY,7,ha='center')
 label(a,374,H-189,'Effective donor',U.TEAL,9,weight='bold')
 label(a,374,H-207,r'Nu$^{-}$, Nu–M or neutral Nu',size=7.4)
 label(a,25,H-253,'Greater deprotonation can increase donor availability; resonance and solvation can reduce capture.',U.GREY,7.2)
 divider(a,H-267)
 U.panel(a,10,H-285,'c','RP3   Intermediate fate selects fluorine loss or retention')
 chem(f,'anionic_adduct','[*:1]C(=O)[CH-]C(F)(F)[*:2]',15,H-366,134,60,{1:'R',2:'Nu'})
 chem(f,'monofluoro_branch','[*:1]C(=O)C=C(F)[*:2]',340,H-340,138,48,{1:'R',2:'Nu'})
 chem(f,'difluoro_branch','[*:1]C(=O)CC(F)(F)[*:2]',340,H-398,138,48,{1:'R',2:'Nu'})
 arrow(a,156,H-339,325,H-315,color=U.NAVY)
 arrow(a,156,H-343,325,H-374,color=U.ORANGE)
 label(a,236,H-310,r'F$^{-}$ elimination',U.NAVY,7.8,ha='center');label(a,236,H-379,'Protonation',U.ORANGE,7.8,ha='center')
 label(a,80,H-379,'Anionic intermediate',size=7.5,ha='center')
 label(a,25,H-415,'A radical intermediate instead requires its own H-atom-transfer versus elimination assessment.',U.GREY,7.2)
 divider(a,H-429)
 U.panel(a,10,H-447,'d','RP4   Product persistence depends on the reaction environment')
 for x,t,c in [(25,'Product formation',U.NAVY),(212,'Target pool',U.TEAL),(384,'Further reaction',U.ORANGE)]:tag(a,x,H-475,t,c)
 arrow(a,139,H-475,198,H-475,color=U.NAVY);arrow(a,291,H-475,367,H-475,color=U.ORANGE)
 label(a,25,H-497,'Acid, donor and catalyst compatibility can alter formation and consumption independently.',U.GREY,7.2)
 U.save(f,'Figure_2')
