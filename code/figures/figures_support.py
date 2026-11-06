"""Vector chemical drawing and PDF/SVG composition helpers."""
from pathlib import Path
import sys, os, csv, json, hashlib, shutil, io, copy, re
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('REACTION_FIGURE_OUTPUT',ROOT/'results/figures'))
FIG=OUT/'figures'; DATA=FIG/'source_data'; ASSETS=FIG/'structure_assets'; QA=FIG/'qa'
for d in [FIG,DATA,ASSETS,QA]: d.mkdir(parents=True,exist_ok=True)
os.environ['MPLCONFIGDIR']=str(QA/'mplconfig')
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch
from matplotlib.ticker import PercentFormatter, MultipleLocator
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors, rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D
import pymupdf as fitz
from PIL import Image

NAVY='#214DA0'; TEAL='#2FA4C3'; ORANGE='#268773'; BLACK='#202124'; GREY='#676B70'; LIGHT='#D9DCDF'
FONT=os.environ.get('REACTION_FONT_FILE',str(Path(matplotlib.get_data_path())/'fonts/ttf/DejaVuSans.ttf'))
font_manager.fontManager.addfont(FONT)
FONT_FAMILY=font_manager.FontProperties(fname=FONT).get_name()
plt.rcParams.update({'font.family':FONT_FAMILY,'font.size':8,'text.color':BLACK,'axes.labelcolor':BLACK,'xtick.color':BLACK,'ytick.color':BLACK,
    'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.65,'axes.edgecolor':BLACK,'axes.labelsize':8,
    'xtick.labelsize':7,'ytick.labelsize':7,'xtick.major.width':.6,'ytick.major.width':.6,'xtick.major.size':3,'ytick.major.size':3,
    'pdf.fonttype':42,'svg.fonttype':'none','savefig.facecolor':'white','legend.fontsize':7,'legend.frameon':False,
    'mathtext.fontset':'custom','mathtext.rm':FONT_FAMILY,'mathtext.it':FONT_FAMILY+':italic','mathtext.bf':FONT_FAMILY+':bold',
    'mathtext.cal':FONT_FAMILY,'mathtext.sf':FONT_FAMILY,'mathtext.tt':FONT_FAMILY})
PT_MM=72/25.4; WIDTH=180*PT_MM
NS='http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
STRUCTURES={
 'sh_amide': ('O=C(Nc1ccccc1)CC(F)(F)F','3,3,3-Trifluoro-N-phenylpropanamide','C9H8F3NO'),
 'sh_thiol': ('CC(C)(C)c1ccc(S)cc1','4-tert-Butylbenzenethiol','C10H14S'),
 'nh_oh_ketone': ('Cc1ccc(C(=O)CC(F)(F)F)cc1','3,3,3-Trifluoro-1-(p-tolyl)propan-1-one','C10H9F3O'),
 'nh_indoline': ('c1ccc2c(c1)CCN2','Indoline','C8H9N'),
 'oh_naphthol': ('Oc1cccc2ccccc12','1-Naphthol','C10H8O'),
 'sh_hypothesis': ('O=C(Nc1ccccc1)C=C(F)Sc1ccc(C(C)(C)C)cc1','Proposed S-linked connectivity','C19H20FNOS'),
 'nh_hypothesis': ('Cc1ccc(C(=O)C=C(F)N2CCc3ccccc32)cc1','Proposed N-linked connectivity','C18H16FNO'),
 'oh_hypothesis': ('Cc1ccc(C(=O)C=C(F)Oc2cccc3ccccc23)cc1','Proposed O-linked connectivity','C20H15FO2'),
}
structure_log=[]

def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def writecsv(path,records):
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def canvas(height_mm):
    h=height_mm*PT_MM
    f=plt.figure(figsize=(180/25.4,height_mm/25.4))
    a=f.add_axes([0,0,1,1]);a.set(xlim=(0,WIDTH),ylim=(0,h));a.axis('off')
    f._chem=[]
    return f,a,h

def text(a,x,y,s,size=8,color=BLACK,ha='left',va='center',weight='normal',**kw):
    # Arial lacks Unicode subscript digits; use native vector math text instead.
    s=re.sub('[₀₁₂₃₄₅₆₇₈₉]+',lambda m:'$_{'+m.group().translate(str.maketrans('₀₁₂₃₄₅₆₇₈₉','0123456789'))+'}$',s)
    return a.text(x,y,s,fontsize=size,color=color,ha=ha,va=va,fontweight=weight,linespacing=1.3,**kw)

def panel(a,x,y,label,title=''):
    text(a,x,y,label,size=9,weight='bold')
    if title:text(a,x+13,y,title,size=8.5,weight='bold')

def molecule(f,key,x,y,w,h):
    """Coordinates in print points, lower-left origin; bond length 13.5 pt."""
    smi,name,expected=STRUCTURES[key]
    m=Chem.MolFromSmiles(smi)
    if m is None:raise ValueError(smi)
    formula=rdMolDescriptors.CalcMolFormula(m)
    assert formula==expected,(key,formula,expected)
    rdDepictor.Compute2DCoords(m)
    draw=rdMolDraw2D.MolDraw2DSVG(int(w),int(h))
    opt=draw.drawOptions();opt.useBWAtomPalette();opt.bondLineWidth=.7;opt.fixedBondLength=13.0
    opt.fixedFontSize=8;opt.minFontSize=8;opt.maxFontSize=8;opt.padding=.025;opt.fontFile=FONT
    opt.clearBackground=False;opt.addStereoAnnotation=False
    draw.DrawMolecule(m);draw.FinishDrawing();svg=draw.GetDrawingText()
    name_asset=f'{key}_{int(w)}x{int(h)}.svg'
    (ASSETS/name_asset).write_text(svg)
    f._chem.append({'svg':svg,'x':x,'y':y,'w':w,'h':h,'key':key})
    record={'key':key,'name':name,'smiles':smi,'canonical_smiles':Chem.MolToSmiles(m),'formula':formula,
        'formal_charge':Chem.GetFormalCharge(m),'F_atoms':sum(a.GetAtomicNum()==9 for a in m.GetAtoms()),
        'status':'proposed_connectivity_not_confirmed' if 'hypothesis' in key else 'documented_reaction_input'}
    if record not in structure_log:structure_log.append(record)

def save(f,name):
    """Compose molecule SVGs into both the SVG and PDF, without raster embedding."""
    w,h=f.get_size_inches()*72
    svg_io=io.StringIO();f.savefig(svg_io,format='svg')
    tree=ET.fromstring(svg_io.getvalue())
    pdf_io=io.BytesIO();f.savefig(pdf_io,format='pdf')
    doc=fitz.open(stream=pdf_io.getvalue(),filetype='pdf');page=doc[0]
    for chem in f._chem:
        svg_node=ET.fromstring(chem['svg'])
        svg_node.set('x',str(chem['x']));svg_node.set('y',str(h-chem['y']-chem['h']))
        svg_node.set('width',str(chem['w']));svg_node.set('height',str(chem['h']))
        tree.append(svg_node)
        sd=fitz.open(stream=chem['svg'].encode(),filetype='svg')
        pd=fitz.open(stream=sd.convert_to_pdf(),filetype='pdf')
        page.show_pdf_page(fitz.Rect(chem['x'],h-chem['y']-chem['h'],chem['x']+chem['w'],h-chem['y']),pd,0)
        pd.close();sd.close()
    (FIG/(name+'.svg')).write_bytes(ET.tostring(tree,encoding='utf-8',xml_declaration=True))
    doc.save(FIG/(name+'.pdf'),garbage=4,deflate=True)
    doc.close();plt.close(f)
    # Reopen after PDF object compaction: an existing page object can retain
    # stale xrefs and render a white pixmap after garbage=4 in PyMuPDF.
    with fitz.open(FIG/(name+'.pdf')) as rendered:
        page=rendered[0]
        assert len(page.get_images())==0,'PDF contains a raster image'
        assert page.get_text().strip() and page.get_drawings(),'PDF has no figure content'
        page.get_pixmap(dpi=600,alpha=False).save(FIG/(name+'.png'))
        preview=page.get_pixmap(dpi=150,alpha=False)
        assert min(preview.samples)<250,'Figure preview is blank'
        preview.save(QA/(name+'_preview.png'))
