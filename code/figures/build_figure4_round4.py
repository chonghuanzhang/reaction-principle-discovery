"""Draw the five-panel Figure 4 from deposited candidate and mapping records.

No model calls or network access. Structures are read from the same records as
candidate pages. Distributions describe different record populations, not a
paired retention analysis. Run via the project scientific Python environment.
"""
from pathlib import Path
import argparse, collections, csv, hashlib, json, os, shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Patch
import figures_support as U
from figures_gaoge import chem as _chem, label, arrow, panel

def chem(*args, **kwargs):
    _chem(*args, **kwargs)
    item=args[0]._chem[-1]
    scale=getattr(args[0], '_molecule_scale', 1.0)
    item['x'] += item['w'] * (1-scale) / 2
    item['y'] += item['h'] * (1-scale) / 2
    item['w'] *= scale
    item['h'] *= scale
    col=kwargs.get("all_color")
    if col:
        item["svg"]=item["svg"].replace("#000000",col).replace("#000;",col+";")

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BLUE='#214DA0'; MID='#3288B7'; CYAN='#39A8BF'; DONOR='#268773'
TEAL='#5ABDBB'; GREEN='#A1D7B7'; LIGHT='#DFE7EC'; INK='#202124'; GREY='#66717A'
W=U.WIDTH
M=U.PT_MM
HEIGHT=210
CAPTION='''Fig. 4 | Candidate diversity, experimental associations and novelty classifications. a, Mutually exclusive reacting-centre label sets for 100 recommended molecules; mixed C/O and C/N categories each contain one molecule. Radial bar lengths represent molecule counts. b, Representative neutral, ionic and precursor forms in the recommendation set. c, The collection contains 100 molecules, 115 site or pathway hypotheses and 124 proposed product options. d, Expert assessment considered structural relationships, commercial accessibility and separate product-connectivity (NP) and reaction-precedent (NR) classifications before the final experimental donor list was chosen. The examples associate C048 aniline with indoline (AP039; also AP044), C051 phenol with 1-naphthol (AP048), and C082 benzenethiol with 4-tert-butylbenzenethiol (AP090). All three are structural analogues. Arrows denote structural associations, not chemical transformations or independently documented replacement decisions; NP2/NR2 labels refer to the proposed endpoint of each actual electrophile–donor pair. e, NP and NR category distributions for 100 candidate molecules and 108 recorded experimental pairs. Bar lengths show category fractions within each population; numerals label counts for categories containing at least five records. Mixed, unresolved and not-applicable records remain explicit. NP and NR are separate ordinal classifications from bounded searches; the different record units and endpoints preclude interpreting these distributions as novelty retention, improvement or reaction-success probabilities.'''


def source():
    candidates=json.loads((ROOT/'candidates/data/candidates_100.json').read_text())
    mapping=json.loads((ROOT/'candidates/experiment_mapping/mapping_108.json').read_text())
    novelty=json.loads((ROOT/'code/data/mapping/novelty_summary.json').read_text())
    c={r['display_id']:r for r in candidates}; p={r['actual_pair_id']:r for r in mapping}
    counts=collections.Counter('/'.join(r['centers']) for r in candidates)
    expected={'C':32,'N':16,'O':15,'S':17,'P':17,'Se':1,'C/O':1,'C/N':1}
    assert dict(counts)==expected,(counts,expected)
    for cid,ap in [('C048','AP039'),('C051','AP048'),('C082','AP090')]:
        assert int(cid[1:]) in p[ap]['structural_analogue_candidate_numbers']
        assert p[ap]['primary_mapping_class']=='Structural Analogue'
    return c,p,novelty,expected


def render(output, molecule_scale=0.5, source_output=None, compact=True):
    if not 0 < molecule_scale <= 1:
        raise ValueError('Molecule scale must be in (0, 1].')
    c,p,n,counts=source()
    U.OUT=Path(output)
    U.FIG=U.OUT/'figures'; U.DATA=U.FIG/'source_data'; U.ASSETS=U.FIG/'structure_assets'; U.QA=U.FIG/'qa'
    for directory in [U.FIG,U.DATA,U.ASSETS,U.QA]:directory.mkdir(parents=True,exist_ok=True)
    height_mm=175 if compact else HEIGHT
    f,a,h=U.canvas(height_mm)
    f._molecule_scale=molecule_scale
    # a: radial counts closely following the supplied reference, in the article font.
    panel(a,13,h-15,'a','Candidate diversity across reacting centres')
    polar_box=[.075,1-(1-.743)*HEIGHT/height_mm,.350,.185*HEIGHT/height_mm] if compact else [.075,.723,.350,.205]
    polar=f.add_axes(polar_box,projection='polar')
    polar.set_theta_offset(np.pi/2);polar.set_theta_direction(-1)
    names=list(counts);vals=list(counts.values());theta=np.arange(8)*2*np.pi/8
    colors=[BLUE,MID,CYAN,DONOR,TEAL,GREEN,'#83A6C6','#ACCBD0']
    polar.bar(theta,vals,width=2*np.pi/8*.88,bottom=2.5,color=colors,edgecolor='white',linewidth=.55,zorder=2)
    polar.set_ylim(0,38);polar.set_yticks([12.5,22.5,32.5]);polar.set_yticklabels(['10','20','30'],fontsize=6.1)
    polar.set_rlabel_position(318)
    for tick in polar.get_yticklabels():
        tick.set_zorder(10)
        tick.set_bbox(dict(facecolor='white',edgecolor='none',pad=.15,alpha=.85))
    polar.set_xticks(theta);polar.set_xticklabels([f'{k}\n({v})' for k,v in zip(names,vals)],fontsize=7.2)
    polar.tick_params(axis='x',pad=2)
    polar.xaxis.grid(True,color='#D3D9DD',linewidth=.55)
    polar.yaxis.grid(True,color='#B7C1C7',linewidth=.55,linestyle=(0,(4,4)))
    polar.spines['polar'].set_color('#BBC3C8');polar.spines['polar'].set_linewidth(.65)
    polar.scatter([0],[0],s=42,color='white',edgecolors='#ADB8BE',linewidth=.6,zorder=4)
    polar.text(0,0,'0',ha='center',va='center',fontsize=5.5,zorder=5)
    # b: forms, independently labelled without suggesting identical reactivity.
    panel(a,260,h-15,'b','Donor form expands the search')
    formrows=[('N–H and N salts','C048','Aniline','C045','Lithium anilide',MID),
              ('O–H and O salts','C051','Phenol','C064','Sodium phenoxide',CYAN),
              ('S–H and S–S','C082','Benzenethiol','C078','Diphenyl disulfide',DONOR)]
    for i,(title,ci,ni,cj,nj,col) in enumerate(formrows):
        yy=h-(51+i*41 if compact else 53+i*52)
        label(a,280,yy+11,title,size=7.1,color=col,weight='bold')
        chem(f,'f4_form_'+ci,c[ci]['input_smiles'],278,yy-24,80,30,all_color=col,font=7,bond=10.5)
        chem(f,'f4_form_'+cj,c[cj]['input_smiles'],380 if compact else 391,yy-24,90,30,all_color=col,font=7,bond=10.5)
        label(a,318,yy-(22 if compact else 32),f'{ci} {ni}',ha='center',size=6.0)
        label(a,425 if compact else 436,yy-(22 if compact else 32),f'{cj} {nj}',ha='center',size=6.0)
    # c: compact accounting, without repeating the donor schematic.
    cy=h-(206 if compact else 220)
    panel(a,13,cy+21,'c','Molecules retain alternative sites, pathways and endpoints')
    countitems=[(86,'100','Candidate molecules',BLUE),(256,'115','Site or pathway hypotheses',DONOR),(427,'124','Proposed product options','#9C760D')]
    for xx,number,name,col in countitems:
        label(a,xx,cy-2,number,size=19,color=col,weight='bold',ha='center')
        label(a,xx,cy-20,name,size=7.1,ha='center')
    arrow(a,158,cy-5,181,cy-5,color='#98A5AD');arrow(a,330,cy-5,352,cy-5,color='#98A5AD')
    divider_y=cy-(32 if compact else 37)
    a.plot([13,W-13],[divider_y,divider_y],color=LIGHT,lw=.6)
    # d: assessment process and experimentally recorded N/O/S model donors.
    dy=cy-(44 if compact else 57)
    panel(a,13,dy,'d','From recommended molecules to experimental donors')
    label(a,52,dy-29,'100 recommended\nmolecules',ha='center',size=7.0,color=BLUE,weight='bold')
    arrow(a,94,dy-29,119,dy-29)
    label(a,248,dy-22,'Expert assessment',ha='center',size=7.3,weight='bold')
    label(a,248,dy-36,'Structural relationships  ·  Commercial accessibility  ·  NP / NR',ha='center',size=6.4)
    arrow(a,372,dy-29,397,dy-29)
    label(a,449,dy-23,'100 final donors',ha='center',size=7.0,color=DONOR,weight='bold')
    label(a,449,dy-38,'108 recorded input pairs',ha='center',size=6.3)
    examples=[('N–H','C048','Aniline','AP039','Indoline',MID),('O–H','C051','Phenol','AP048','1-Naphthol',CYAN),('S–H','C082','Benzenethiol','AP090','4-tert-Butylbenzenethiol',DONOR)]
    for i,(route,cid,cname,apid,aname,col) in enumerate(examples):
        x=14+i*165
        mol_y=dy-(89 if compact else 113)
        name_y=dy-(87 if compact else 122)
        left_center=42 if compact else 29
        right_center=111 if compact else 122
        arrow_y=dy-(67.5 if compact else 91)
        label(a,x+78,dy-(46 if compact else 61),route+' model',ha='center',size=7.2,color=col,weight='bold')
        chem(f,'f4_assoc_'+cid,c[cid]['input_smiles'],x+left_center-29,mol_y,58,43,all_color=col,font=7,bond=10.5)
        chem(f,'f4_assoc_'+apid,p[apid]['actual_donor_smiles'],x+right_center-29,mol_y,58,43,all_color=col,font=7,bond=10.5)
        arrow(a,x+60,arrow_y,x+91,arrow_y,color=GREY)
        label(a,x+75,dy-(55 if compact else 77),'Analogue',ha='center',size=5.5,color=GREY)
        label(a,x+left_center,name_y,cid+' '+cname,ha='center',size=6.1)
        if i==2:
            label(a,x+right_center,name_y,apid+' 4-tert-Butyl-\nbenzenethiol',ha='center',size=5.4)
        else: label(a,x+right_center,name_y,apid+' '+aname,ha='center',size=6.1)
        label(a,x+79,dy-(109 if compact else 144),'Actual-pair endpoint: NP2 / NR2',ha='center',size=6.0)
        if i<2:a.plot([x+162,x+162],[dy-(40 if compact else 57),dy-(119 if compact else 152)],color=LIGHT,lw=.5)
    # e: separate NP and NR categories for the two populations.
    ey=dy-(135 if compact else 177)
    a.plot([13,W-13],[ey+15,ey+15],color=LIGHT,lw=.6)
    panel(a,13,ey,'e','Novelty classifications by record unit')
    datasets=[('NP','Product connectivity',n['candidate_molecule_NP_label_set_distribution'],n['experimental_pair_NP'],['1R','1T','2','3','3/2','unresolved','not applicable']),
              ('NR','Reaction precedent',n['candidate_molecule_NR_label_set_distribution'],n['experimental_pair_NR'],['1','2','3','mixed','unresolved','not applicable'])]
    colmap={'1R':'#8BA5C7','1T':'#BDD5E5','1':'#8BA5C7','2':BLUE,'3':TEAL,'3/2':'#E6B86B','mixed':'#E6B86B','unresolved':'#B6BDC2','not applicable':'#F3F5F6'}
    out=[]
    for j,(kind,title,d1,d2,order) in enumerate(datasets):
        x=13+j*250
        label(a,x,ey-19,kind+'  '+title,size=7.0,weight='bold')
        barx=x+69;barw=162
        for k,(population,data,total) in enumerate([('Candidates',d1,100),('Input pairs',d2,108)]):
            yy=ey-39-k*21
            label(a,x,yy+3,population+'\n(n = '+str(total)+')',size=6.0)
            if kind=='NR':data={('mixed' if key in ('2 | 3','2–3') else key):v for key,v in data.items()}
            assert sum(data.values())==total
            left=barx
            for key in order:
                count=data.get(key,0)
                if not count:continue
                width=barw*count/total
                a.add_patch(Rectangle((left,yy-3),width,11,facecolor=colmap[key],edgecolor='white',linewidth=.35,hatch='////' if key=='not applicable' else None))
                if count>=5:label(a,left+width/2,yy+2.5,str(count),ha='center',size=5.7,color='white' if key=='2' else INK)
                out.append({'assessment':kind,'population':population,'denominator':total,'category':key,'original_label':(('2 | 3' if total==100 else '2–3') if key=='mixed' else key),'count':count,'fraction':count/total})
                left+=width
        # A compact legend retains every category, including zero-only alternatives.
        legend_entries=[(key, {'unresolved':'Unresolved','not applicable':'Not applicable','mixed':'Mixed / range'}.get(key,key)) for key in order]
        for z,(key,text) in enumerate(legend_entries):
            row=z//4;col=z%4;xx=x+col*58;yy=ey-82-row*12
            a.add_patch(Rectangle((xx,yy-2),6,5,facecolor=colmap[key],edgecolor='#8C959C',linewidth=.3,hatch='////' if key=='not applicable' else None))
            label(a,xx+9,yy,text,size=5.3)
    U.save(f,'Figure_4')
    sourceout=Path(source_output) if source_output is not None else ROOT/'figures/source/round4_figure4'
    sourceout.mkdir(parents=True,exist_ok=True)
    with (sourceout/'novelty_panel_e.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(out[0]));writer.writeheader();writer.writerows(out)
    (sourceout/'caption.txt').write_text(CAPTION+'\n')
    payload={'reacting_centre_label_sets':counts,'mapping_examples':[{'candidate_id':ci,'actual_pair_id':ap,'relation':'Structural Analogue','candidate_smiles':c[ci]['input_smiles'],'actual_donor_smiles':p[ap]['actual_donor_smiles'],'actual_NP':'2','actual_NR':'2'} for ci,ap in [('C048','AP039'),('C051','AP048'),('C082','AP090')]],'sources':['candidates/data/candidates_100.json','candidates/experiment_mapping/mapping_108.json','code/data/mapping/novelty_summary.json'],'figure_dimensions_mm':[180,HEIGHT],'font':U.FONT_FAMILY,'novelty_plot_units':'category fractions, counts labelled for n>=5','source_data_sha256':{str(q.relative_to(ROOT)):hashlib.sha256(q.read_bytes()).hexdigest() for q in [ROOT/'candidates/data/candidates_100.json',ROOT/'candidates/experiment_mapping/mapping_108.json',ROOT/'code/data/mapping/novelty_summary.json']}}
    payload['figure_dimensions_mm']=[180,height_mm]
    payload['molecule_scale']=molecule_scale
    payload['compact_layout']=compact
    (sourceout/'figure_data.json').write_text(json.dumps(payload,indent=2)+'\n')
    (U.QA/'molecule_scale.json').write_text(json.dumps({'linear_scale':molecule_scale,'placement':'compact rows with centred structures' if compact else 'original centres preserved','structures':12,'compact_layout':compact,'figure_dimensions_mm':[180,height_mm]},indent=2)+'\n')
    # Article raster derivatives are from the vector PDF at 600 dpi.
    figs=U.FIG
    with Image.open(figs/'Figure_4.png') as im:
        im.convert('RGB').save(figs/'Figure_4.jpeg',quality=100,subsampling=0,dpi=(600,600))
    return {'figure':4,'vector_pdf':str(figs/'Figure_4.pdf'),'source_data':str(sourceout/'figure_data.json')}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=U.OUT)
    parser.add_argument('--molecule-scale',type=float,default=0.5)
    parser.add_argument('--source-output',type=Path)
    parser.add_argument('--compact',action=argparse.BooleanOptionalAction,default=True)
    options=parser.parse_args()
    print(json.dumps(render(options.output,options.molecule_scale,options.source_output,options.compact),indent=2))
