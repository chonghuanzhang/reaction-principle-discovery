"""Compose the main Fig. 5 and SI BO1 from frozen source data."""
from pathlib import Path
import csv, hashlib, json, os, shutil, sys

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('REACTION_FIGURE_OUTPUT',ROOT/'results/figures'))
SOURCE = ROOT / 'figures'
ARCH = ROOT / 'benchmark'
FIG = OUT / 'figures'; QA = OUT / 'qa'; DATA = OUT / 'source_data'
for p in (FIG, QA, DATA): p.mkdir(parents=True, exist_ok=True)
os.environ['MPLCONFIGDIR'] = str(QA / 'mplconfig_main')
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Patch,Rectangle
from matplotlib.legend_handler import HandlerTuple,HandlerBase
from matplotlib.text import Text
from matplotlib.ticker import MaxNLocator
from mpl_toolkits.mplot3d import proj3d

BLUE='#204DA0'; CYAN='#2FA4C3'; TEAL='#5EC0C1'; GREEN='#268773'
PURPLE='#9865B4'; GOLD='#D99329'; INK='#1D2730'; GREY='#66717A'
METHOD_BO='#1F6B59'; METHOD_RANDOM='#789C8E'; METHOD_TIE='#D6DEDA'
RESPONSE=LinearSegmentedColormap.from_list('response',['#FBFBF3','#E6EEE1','#A8CEB6','#68B39D',GREEN],N=512)
RELATIVE_NORM=Normalize(0,1)
SDMAP=LinearSegmentedColormap.from_list('uncertainty',['#FBFAFD','#E3D8EF','#BEA4D1',PURPLE,'#68438B'])
for p in (SOURCE/'qa/fonts').glob('Helvetica-*.ttf'): font_manager.fontManager.addfont(str(p))
plt.rcParams.update({'font.family':os.environ.get('REACTION_FONT','DejaVu Sans'),'font.size':7.5,'text.color':INK,
    'axes.labelcolor':INK,'axes.edgecolor':INK,'axes.labelsize':7.5,'axes.linewidth':.65,
    'axes.spines.top':True,'axes.spines.right':True,'xtick.color':INK,'ytick.color':INK,
    'xtick.labelsize':6.5,'ytick.labelsize':6.5,'xtick.major.width':.6,'ytick.major.width':.6,
    'legend.frameon':False,'legend.fontsize':6.4,'pdf.fonttype':42,'svg.fonttype':'none',
    'savefig.facecolor':'white','mathtext.fontset':'custom','mathtext.rm':os.environ.get('REACTION_FONT','DejaVu Sans'),
    'mathtext.it':os.environ.get('REACTION_FONT','DejaVu Sans')+':italic','mathtext.bf':os.environ.get('REACTION_FONT','DejaVu Sans')+':bold'})

def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

# Convex tensor Hermite display interpolation. Original category values are exact.
SUB=20
dx=np.linspace(0,7,7*SUB+1);dy=np.linspace(0,11,11*SUB+1)
DX,DY=np.meshgrid(dx,dy)
def smooth_display(z):
    ix=np.minimum(np.floor(dx).astype(int),6);tx=dx-ix;hx=tx*tx*(3-2*tx)
    iy=np.minimum(np.floor(dy).astype(int),10);ty=dy-iy;hy=ty*ty*(3-2*ty)
    lo=z[iy[:,None],ix[None,:]]*(1-hx)+z[iy[:,None],ix[None,:]+1]*hx
    hi=z[iy[:,None]+1,ix[None,:]]*(1-hx)+z[iy[:,None]+1,ix[None,:]+1]*hx
    dense=lo*(1-hy[:,None])+hi*hy[:,None]
    corners=np.array([z[iy[:,None]+a,ix[None,:]+b] for a,b in [(0,0),(0,1),(1,0),(1,1)]])
    assert np.max(np.abs(dense[::SUB,::SUB]-z))<1e-14
    assert np.all(dense>=corners.min(axis=0)-1e-14) and np.all(dense<=corners.max(axis=0)+1e-14)
    return dense

grid=sorted(read(SOURCE/'source_data/SH_PL40_full_measured_grid_seed5010.csv'),key=lambda r:int(r['candidate_index']))
y=np.array([float(r['measured_uv_response']) for r in grid])
sh=dict(pool='SH_PL40',channel='UV response',mean=y,obs=dict(enumerate(y)),selected=np.arange(96),
    other=np.array([],dtype=int),rounds={i:int(r['bo_selection_round']) for i,r in enumerate(grid)},
    best=int(y.argmax()),color=BLUE,norm=Normalize(0,y.max()),dz=smooth_display(y.reshape(12,8)),
    row_prefix='F',row_label='Formulation')
assert sh['best']==65
post=read(SOURCE/'source_data/NH_OH_posteriors_by_round.csv')
systems=[]
oh_candidates=sorted(read(ROOT/'selections/OH_CuNi_96/candidates.csv'),key=lambda r:int(r['candidate_index']))
assert len(oh_candidates)==96
oh_library=json.loads((ROOT/'selections/OH_CuNi_96/candidate_manifest.json').read_text())
assert oh_library['solvents']==['n-hexane','DCE','MeCN','THF','1,4-dioxane','toluene','HFIP','DMF']
assert [r['solvent'] for r in oh_candidates[:8]]==oh_library['solvents']
formulations=[]
for row in range(12):
    block=oh_candidates[row*8:(row+1)*8]
    assert len({r['formulation'] for r in block})==1
    assert [r['solvent'] for r in block]==[r['solvent'] for r in oh_candidates[:8]]
    rec=block[0]
    formulations.append(dict(formulation_key=f'F{row+1}',formulation=rec['formulation'],
        catalyst_code=rec['cat'],base=rec['base'],source_pool_id=rec['source_pool_id']))
assert len({r['formulation'] for r in formulations})==12
with (DATA/'OH_formulation_key.csv').open('w',encoding='utf-8',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(formulations[0]));writer.writeheader();writer.writerows(formulations)
condition_key=sorted(read(SOURCE/'source_data/condition_key.csv'),key=lambda r:int(r['candidate_index']))
assert len(condition_key)==96
fixed_formulations=[]
for pool,catalyst_code,catalyst in [('SH_PL40','Cu9','CuCl'),('NH_PL36','Ag13','Ag2SO4')]:
    for row in range(12):
        base=condition_key[row*8]['base']
        fixed_formulations.append(dict(pool_id=pool,formulation_key=f'F{row+1}',
            formulation=f'{catalyst}/PPh3 | {base}',catalyst_code=catalyst_code,
            catalyst=catalyst,ligand='PPh3',base=base))
with (DATA/'NH_SH_formulation_key.csv').open('w',encoding='utf-8',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(fixed_formulations[0]));writer.writeheader();writer.writerows(fixed_formulations)
for pool,label,color,channel in [('NH_PL36','N–H',BLUE,'UV response'),
    ('OH_CuNi_96','O–H',GREEN,'UV response')]:
    rr=sorted([r for r in post if r['pool']==pool and int(r['after_round'])==5],key=lambda r:int(r['candidate_index']))
    sel=read(ROOT/f'selections/{pool}/selected_conditions.csv')
    obs={int(r['candidate_index']):float(r['archived_response_revealed_after_computational_selection']) for r in sel}
    rounds={int(r['candidate_index']):int(r['batch_number']) for r in sel}
    ids=np.array(sorted(obs));other=np.array([i for i in range(96) if i not in obs])
    mean=np.array([float(r['posterior_mean']) for r in rr]);sd=np.array([float(r['latent_posterior_sd']) for r in rr])
    assert len(ids)==60 and len(other)==36 and len(rr)==96
    assert all(sum(v==r for v in rounds.values())==12 for r in range(1,6))
    assert all(rr[i]['revealed_response']=='' for i in other)
    row_prefix='F'
    row_label='Formulation'
    systems.append(dict(pool=pool,label=label,color=color,channel=channel,mean=mean,sd=sd,obs=obs,
        row_prefix=row_prefix,row_label=row_label,
        selected=ids,other=other,rounds=rounds,best=max(obs,key=obs.get),
        norm=Normalize(min(0,mean.min()),max(mean.max(),max(obs.values()))),dz=smooth_display(mean.reshape(12,8))))

def letter(fig,x,y,t): fig.text(x,y,t,fontsize=10.5,fontweight='bold',va='top')
class RoundKeyHandler(HandlerBase):
    def create_artists(self,legend,orig_handle,xdescent,ydescent,width,height,fontsize,trans):
        return [Text(width/2-xdescent,height/2-ydescent,'1–5',ha='center',va='center',
            fontsize=fontsize*.95,fontfamily=os.environ.get('REACTION_FONT','DejaVu Sans'),color=INK,transform=trans)]
relative_color_checks=[]
def landscape(ax,s,large=False,compact=False,relative_colors=False):
    ax.computed_zorder=False
    if compact:ax.patch.set_alpha(0)
    surf=ax.plot_surface(DX,DY,s['dz'],cmap=RESPONSE,
        norm=RELATIVE_NORM if relative_colors else s['norm'],rstride=1,cstride=1,
        linewidth=0,edgecolor='none',antialiased=False,shade=False,zorder=1)
    if relative_colors:
        reference=max(s['obs'].values())
        relative=s['dz']/reference
        assert relative.min()>=0 and relative.max()<=1
        raw_face_values=np.array(surf.get_array())
        surf.set_array(raw_face_values/reference)
        assert np.allclose(surf.get_array()*reference,raw_face_values,atol=1e-14,rtol=1e-14)
        assert np.array_equal(RESPONSE(RELATIVE_NORM(relative)),RESPONSE(s['norm'](s['dz'])))
        relative_color_checks.append(dict(pool=s['pool'],channel=s['channel'],
            reference_kind='complete measured grid maximum' if s is sh else 'highest selected measured response',
            normalization_reference=reference,raw_surface_min=float(s['mean'].min()),
            raw_surface_max=float(s['mean'].max()),relative_surface_min=float(relative.min()),
            relative_surface_max=float(relative.max()),clipped_values=0,
            original_vertex_height_max_error=float(np.max(np.abs(s['dz'][::SUB,::SUB]-s['mean'].reshape(12,8))))))
    ids=s['selected'];obs=s['obs'];b=s['best']
    if s is sh:
        for lo,hi,c,size in [(1,1,BLUE,13),(2,2,CYAN,16),(3,8,'#BAC7CA',7)]:
            ii=np.array([i for i in ids if lo<=s['rounds'][i]<=hi])
            ax.scatter(ii%8,ii//8,[obs[i] for i in ii],s=size,c=c,edgecolors='white',lw=.3,depthshade=False,zorder=4)
    else:
        ax.scatter(ids%8,ids//8,[obs[i] for i in ids],s=8,c=GREY,edgecolors='white',lw=.25,depthshade=False,zorder=4)
        ii=s['other'];ax.scatter(ii%8,ii//8,s['mean'][ii],s=8,facecolors='white',edgecolors=s['color'],lw=.5,depthshade=False,zorder=3)
    ax.scatter([b%8],[b//8],[obs[b]],marker='*',s=95 if large else 55,facecolors=GOLD,edgecolors=INK,lw=.4,depthshade=False,zorder=6)
    ax.view_init(elev=24,azim=-55);ax.set_box_aspect((1,1.22,.85))
    ax.set_xticks([0,3,7],['S1','S4','S8'])
    prefix=s.get('row_prefix','F')
    ax.set_yticks([0,3,7,11],[f'{prefix}{i}' for i in [1,4,8,12]])
    low=min(0,float(s['mean'].min()),min(obs.values()));high=max(float(s['mean'].max()),max(obs.values()))
    ax.set_zlim(low-.015*(high-low),high*1.12);ax.zaxis.set_major_locator(MaxNLocator(3))
    if s is sh:ax.set_zlim(0,3.5);ax.set_zticks([0,1,2,3])
    fs=8 if large else (5.9 if compact else 6.5)
    ax.set_xlabel('Solvent',fontsize=fs,labelpad=-5)
    ax.set_ylabel(s.get('row_label','Formulation'),fontsize=fs,labelpad=-5)
    ax.set_zlabel(s['channel'],fontsize=fs,labelpad=0 if large else (-5 if compact else -2))
    ax.tick_params(pad=-3,labelsize=6.6 if large else (5.3 if compact else 5.8))
    for axis in (ax.xaxis,ax.yaxis,ax.zaxis):
        axis.pane.fill=False;axis.pane.set_edgecolor('#E6E9EB')
        axis._axinfo['grid'].update(color='#E7EBED',linewidth=.4)
    if s is sh:
        px,py,_=proj3d.proj_transform(b%8,b//8,obs[b],ax.get_proj())
        ax.annotate('37% NMR yield',xy=(px,py),xytext=(10,12),textcoords='offset points',
            fontsize=7.5,color=INK,ha='left',va='bottom',zorder=10,
            arrowprops=dict(arrowstyle='-',color=GREY,lw=.6,shrinkA=2,shrinkB=6))
    return surf

def boxed(ax):
    for spine in ax.spines.values():
        spine.set_visible(True);spine.set_linewidth(.7);spine.set_edgecolor('#4C555A')
    ax.tick_params(direction='in',top=True,right=True,length=2.8,width=.6,pad=4)
    ax.set_axisbelow(True)

batch_summaries=[]
def summarize_batches(s):
    batches=[]
    for r in range(1,6):
        ii=sorted(i for i in s['selected'] if s['rounds'][i]==r)
        values=[s['obs'][i] for i in ii];batches.append(values)
        assert len(values)==12
        q1,med,q3=np.quantile(values,[.25,.5,.75])
        batch_summaries.append(dict(pool=s['pool'],round=r,n=12,minimum=min(values),q1=float(q1),
            median=float(med),q3=float(q3),maximum=max(values)))
    return batches

def response_progress(ax,s):
    batches=summarize_batches(s)
    bp=ax.boxplot(batches,positions=np.arange(1,6)-.08,widths=.28,whis=(0,100),
        patch_artist=True,showfliers=False,manage_ticks=False,
        boxprops=dict(edgecolor=s['color'],facecolor=matplotlib.colors.to_rgba(s['color'],.16),lw=.85),
        medianprops=dict(color=INK,lw=1.0),whiskerprops=dict(color=s['color'],lw=.7),
        capprops=dict(color=s['color'],lw=.7))
    for r,values in enumerate(batches,1):
        jitter=np.linspace(-.21,.21,12)
        ax.scatter(r+jitter,values,s=13,c=s['color'],alpha=.68,edgecolors='white',lw=.3,zorder=3)
    best=[max(v for i,v in s['obs'].items() if s['rounds'][i]<=r) for r in range(1,6)]
    ax.scatter(np.arange(1,6)+.11,best,marker='o',s=19,facecolors='white',edgecolors=INK,lw=.85,zorder=5)
    ax.set(xlim=(.6,5.4),xticks=range(1,6),xlabel='Selection batch',ylabel=s['channel'],ylim=(-.025*max(best),max(best)*1.17))
    ax.text(.045,.94,s['label'],transform=ax.transAxes,va='top',fontsize=8,fontweight='bold')
    ax.yaxis.set_major_locator(MaxNLocator(4));boxed(ax)

def cbar(fig,im,bounds,label):
    cb=fig.colorbar(im,cax=fig.add_axes(bounds));cb.outline.set_linewidth(.35)
    cb.ax.tick_params(length=2,width=.4,labelsize=5.7,pad=2)
    cb.locator=MaxNLocator(3);cb.update_ticks();cb.set_label(label,fontsize=6.4,labelpad=3)

def matrix(ax,values,cmap,norm,row_prefix='F'):
    cmap=cmap.copy();cmap.set_bad('#E8ECEF')
    im=ax.imshow(values,cmap=cmap,norm=norm,aspect='auto',interpolation='nearest')
    ax.set_xticks(range(8),[f'S{i}' for i in range(1,9)],rotation=90,fontsize=5.7)
    ax.set_yticks(range(12),[f'{row_prefix}{i}' for i in range(1,13)],fontsize=5.7)
    ax.tick_params(length=0,pad=2)
    ax.set_xticks(np.arange(-.5,8,1),minor=True);ax.set_yticks(np.arange(-.5,12,1),minor=True)
    ax.grid(which='minor',color='white',lw=.4);ax.tick_params(which='minor',length=0)
    for sp in ax.spines.values():sp.set_visible(True);sp.set_linewidth(.5);sp.set_edgecolor('#87939A')
    return im

map_source=ROOT/'figures/source_data/SH_seed5010_selection_map_annotations.csv'
map_rows=sorted(read(map_source),key=lambda r:int(r['candidate_index']))
assert len(map_rows)==96
assert all(float(r['measured_uv_response'])==y[i] for i,r in enumerate(map_rows))
assert sum(bool(r['bo_displayed_selection_round']) for r in map_rows)==24
assert sum(bool(r['random_displayed_selection_round']) for r in map_rows)==48
assert sum(r['common_initial_batch']=='1' for r in map_rows)==12
BASE_LABELS=['K₃PO₄','DIPEA','KHCO₃','NaHCO₃','K₂CO₃','K₂HPO₄','NaOH',
    'Na₃PO₄·12H₂O','CsOH/2','CsF','NaH','KOtBu']
SOL_LABELS=['n-hexane','DCE','MeCN','THF','1,4-dioxane','toluene','HFIP','DMF']
def selection_map(ax,method):
    field='bo_displayed_selection_round' if method=='Bayesian' else 'random_displayed_selection_round'
    color=METHOD_BO if method=='Bayesian' else METHOD_RANDOM
    ax.imshow((y/y.max()).reshape(12,8),cmap=RESPONSE,norm=RELATIVE_NORM,aspect='auto',interpolation='nearest')
    ax.set(xticks=range(8),yticks=range(12),xticklabels=SOL_LABELS,yticklabels=BASE_LABELS,xlabel='Solvent')
    ax.set_ylabel('Formulation',labelpad=5,fontsize=7)
    ax.tick_params(length=0,pad=3,labelsize=6.3)
    plt.setp(ax.get_xticklabels(),rotation=45,ha='right',rotation_mode='anchor')
    ax.set_xticks(np.arange(-.5,8,1),minor=True);ax.set_yticks(np.arange(-.5,12,1),minor=True)
    ax.grid(which='minor',color='white',lw=.5);ax.tick_params(which='minor',length=0)
    for spine in ax.spines.values():spine.set_visible(True);spine.set_linewidth(.65)
    for i,row in enumerate(map_rows):
        x,yy=i%8,i//8
        ax.text(x,yy+.16,f'{y[i]:.2f}',ha='center',va='center',fontsize=6.4,
            color='white' if i==65 else INK,zorder=5)
        if row[field]:
            shared=row['common_initial_batch']=='1'
            style=(0,(1.15,1.5)) if shared else ('solid' if method=='Bayesian' else (0,(3.2,1.65)))
            outline=Rectangle((x-.455,yy-.455),.91,.91,fill=False,edgecolor=GREY if shared else color,
                lw=1.05 if shared else 1.15,linestyle=style,zorder=6)
            if not shared:outline.set_path_effects([path_effects.Stroke(linewidth=1.9,foreground='white'),path_effects.Normal()])
            ax.add_patch(outline)
            ax.text(x-.29,yy-.28,row[field],ha='center',va='center',fontsize=5.6,
                fontweight='bold',color='white' if i==65 else INK,zorder=7)
    ax.scatter([65%8+.29],[65//8-.28],marker='*',s=22,c=GOLD,edgecolors=INK,lw=.35,zorder=8)

exports=[]
def save(fig,name):
    if '--main-only' in sys.argv and name=='SI_BO1_posterior_landscapes':
        plt.close(fig);exports.append(name);return
    for ext in ('pdf','svg','png'):fig.savefig(FIG/f'{name}.{ext}',dpi=600,facecolor='white')
    fig.savefig(QA/f'{name}_preview.png',dpi=180,facecolor='white')
    plt.close(fig);exports.append(name);print('Exported',name,flush=True)

# Main: surface, aggregate evidence, two illustrative maps, two condition-selection surfaces.
budgets=read(ARCH/'data/run_budgets.csv')
paired={}
for r in budgets:
    if r['pool_id']=='SH_PL40' and 5000<=int(r['seed'])<=5099:
        paired.setdefault(int(r['seed']),{})[r['strategy']]=int(r['exact_budget'])
assert len(paired)==100 and all(set(v)=={'BO-UCB','random'} for v in paired.values())
bo=np.array([paired[k]['BO-UCB'] for k in sorted(paired)]);rand=np.array([paired[k]['random'] for k in sorted(paired)])
savings=rand-bo;steps=np.arange(12,97,12)
counts={p:[int(np.sum(v<=b)) for b in steps] for p,v in [('BO',bo),('random',rand)]}
assert counts=={'BO':[15,72,96,100,100,100,100,100],'random':[15,29,44,51,63,77,89,100]}
assert np.median(bo)==24 and np.median(rand)==48 and abs(savings.mean()-25.8)<1e-10
fig=plt.figure(figsize=(180/25.4,265/25.4))
letter(fig,.035,.985,'a')
surf=landscape(fig.add_axes([-.035,.600,.66,.400],projection='3d'),sh,True,relative_colors=True)
cb=fig.colorbar(matplotlib.cm.ScalarMappable(norm=RELATIVE_NORM,cmap=RESPONSE),
    cax=fig.add_axes([.095,.955,.23,.007]),orientation='horizontal',ticks=[0,.25,.5,.75,1])
cb.outline.set_linewidth(.4);cb.ax.tick_params(labelsize=5.8,length=1.8,width=.4,pad=1)
cb.ax.set_title('Relative response',fontsize=6.4,pad=4)
handles=[Line2D([],[],marker='o',ls='none',color=c,ms=3.7,label=t) for c,t in
    [(BLUE,'Round 1'),(CYAN,'Round 2'),('#BAC7CA','Rounds 3–8')]]
handles.append(Line2D([],[],marker='*',ls='none',mfc=GOLD,mec=INK,mew=.4,ms=6,label='Recorded maximum'))
fig.legend(handles=handles,loc='center',bbox_to_anchor=(.32,.615),ncol=4,columnspacing=.9,handletextpad=.3,fontsize=6.1)
letter(fig,.645,.985,'b')
ax=fig.add_axes([.705,.815,.265,.155])
ecdf_file=ROOT/'figures/source_data/SH_hit_budget_ecdf.csv'
ecdf=read(ecdf_file)
for vals,c,label,method,marker in [(bo,METHOD_BO,'Bayesian','BO','o'),(rand,METHOD_RANDOM,'Random','random','s')]:
    rr=sorted([r for r in ecdf if r['method']==method],key=lambda r:int(r['budget']))
    assert [int(r['budget']) for r in rr]==list(steps)
    assert all(int(r['hit_count'])==int(np.sum(vals<=int(r['budget']))) for r in rr)
    xx=np.r_[0,steps];yy=np.r_[0,[(vals<=b).mean() for b in steps]]
    ax.fill_between(xx,np.r_[0,[float(r['bootstrap_ci_low']) for r in rr]],
        np.r_[0,[float(r['bootstrap_ci_high']) for r in rr]],step='post',color=c,alpha=.18,lw=0,zorder=1)
    ax.step(xx,yy,where='post',lw=1.45,color=c,label=label,
        ls='solid' if method=='BO' else (0,(3,1.8)))
    ax.scatter(steps,yy[1:],s=12,c=c,marker=marker,edgecolors='white',lw=.25,zorder=3)
ax.set(xlim=(0,99),ylim=(-.025,1.06),xticks=[0,24,48,72,96],yticks=[0,.5,1],
    xlabel='Conditions evaluated',ylabel='Fraction discovering maximum')
boxed(ax)
ax.legend(handles=[Line2D([],[],color=METHOD_BO,lw=1.45,marker='o',ms=3,label='Bayesian'),
    Line2D([],[],color=METHOD_RANDOM,lw=1.45,ls=(0,(3,1.8)),marker='s',ms=3,label='Random'),
    Patch(facecolor=matplotlib.colors.to_rgba(GREY,.18),edgecolor='none',label='95% bootstrap CI')],
    loc='lower right',fontsize=5.9,handlelength=1.6,handletextpad=.45,labelspacing=.3,
    frameon=True,facecolor='white',edgecolor='none',framealpha=.92)
letter(fig,.645,.790,'c')
ax=fig.add_axes([.705,.628,.265,.128])
vals=np.arange(-24,73,12);freq=np.array([np.sum(savings==v) for v in vals])
ax.bar(vals,freq,width=8.7,color=[METHOD_RANDOM if v<0 else METHOD_TIE if v==0 else METHOD_BO for v in vals],lw=0)
ax.axvline(savings.mean(),color=GOLD,lw=1.2,ls=(0,(3,2)))
ax.legend(handles=[Patch(facecolor=METHOD_BO,label='Bayesian earlier'),
    Patch(facecolor=METHOD_TIE,label='Same batch'),Patch(facecolor=METHOD_RANDOM,label='Random earlier'),
    Line2D([],[],color=GOLD,lw=1.2,ls=(0,(3,2)),label='Mean 25.8')],
    loc='upper right',fontsize=6,handlelength=1.25,handletextpad=.45,labelspacing=.25,
    borderpad=.3,frameon=True,facecolor='white',edgecolor='none',framealpha=1)
ax.set(xlim=(-32,81),ylim=(0,46),xticks=[-24,0,24,48,72],yticks=[0,15,30,45],
    xlabel='Conditions saved (random − BO)',ylabel='Paired runs')
boxed(ax)
for x,method,label,title in [(.145,'Bayesian','d','Bayesian: 24 conditions / 2 rounds'),
    (.645,'Random','e','Random: 48 conditions / 4 rounds')]:
    letter(fig,x-.11,.595,label)
    fig.text(x,.592,title,fontsize=7.6,fontweight='bold',va='top')
    selection_map(fig.add_axes([x,.345,.325,.230]),method)
map_handles=[Patch(facecolor='none',edgecolor=GREY,lw=1.05,ls=(0,(1.15,1.5)),label='Shared initial 12'),
    Patch(facecolor='none',edgecolor=METHOD_BO,lw=1.15,label='Bayesian: subsequent 12'),
    Patch(facecolor='none',edgecolor=METHOD_RANDOM,lw=1.15,ls=(0,(3.2,1.65)),label='Random: subsequent 36')]
fig.legend(handles=map_handles,loc='center',bbox_to_anchor=(.56,.275),ncol=3,
    handlelength=1.7,handleheight=1.2,columnspacing=1.7,handletextpad=.5,fontsize=6.2)
fig.legend(handles=[Line2D([],[],marker='*',ls='none',mfc=GOLD,mec=INK,mew=.35,ms=5.5,label='Highest response'),
    Patch(facecolor='none',edgecolor='none',label='Corner digit: selection round')],
    loc='center',bbox_to_anchor=(.56,.252),ncol=2,columnspacing=1.8,handletextpad=.5,fontsize=6.2)
handles=[Line2D([],[],marker='o',ls='none',color=GREY,ms=3,label='Selected response'),
    Line2D([],[],marker='o',ls='none',mfc='white',mec=INK,mew=.6,ms=3,label='Other model mean'),
    Line2D([],[],marker='*',ls='none',mfc=GOLD,mec=INK,mew=.35,ms=5.5,label='Best selected')]
fig.legend(handles=handles,loc='center',bbox_to_anchor=(.51,.233),ncol=3,
    columnspacing=2.0,handletextpad=.5,fontsize=6.2)
for j,s in enumerate(systems):
    x=j/2
    summarize_batches(s)
    letter(fig,x+.025,.219,'fgh'[j])
    fig.text(x+.085,.216,s['label'],fontsize=7.6,fontweight='bold',va='top')
    left=x+.035
    surf=landscape(fig.add_axes([left,.013,.43,.195],projection='3d'),s,compact=True,relative_colors=True)
save(fig,'Main_Fig5_Bayesian_optimization')

# SI: selected archived responses / final posterior surface / SD and round map.
fig=plt.figure(figsize=(180/25.4,146/25.4))
for row,(s,yp) in enumerate(zip(systems,[.585,.13])):
    for col,x in enumerate([.035,.335,.72]):letter(fig,x,yp+.355,'abcdefghi'[row*3+col])
    selected=np.full(96,np.nan)
    for i,v in s['obs'].items():selected[i]=v
    ax=fig.add_axes([.085,yp+.035,.17,.305])
    im=matrix(ax,np.ma.masked_invalid(selected.reshape(12,8)),RESPONSE,Normalize(0,max(s['obs'].values())),s['row_prefix'])
    ax.text(0,1.04,s['label'],transform=ax.transAxes,fontsize=7,fontweight='bold',va='bottom')
    b=s['best'];ax.scatter(b%8,b//8,s=37,marker='*',c=GOLD,edgecolors=INK,lw=.35,zorder=5)
    ax.set_xlabel('Solvent',labelpad=3,fontsize=6.5);ax.set_ylabel(s['row_label'],labelpad=3,fontsize=6.5)
    cbar(fig,im,[.276,yp+.060,.010,.245],s['channel'])
    landscape(fig.add_axes([.305,yp-.015,.42,.425],projection='3d'),s)
    ax=fig.add_axes([.758,yp+.035,.145,.305])
    im=matrix(ax,s['sd'].reshape(12,8),SDMAP,Normalize(0,float(s['sd'].max())),s['row_prefix'])
    for i,r in s['rounds'].items():
        ax.text(i%8,i//8,str(r),ha='center',va='center',fontsize=5.8,
            color='white' if s['sd'][i]/s['sd'].max()>.65 else INK)
    ax.set_xlabel('Solvent',labelpad=3,fontsize=6.5)
    cbar(fig,im,[.922,yp+.060,.008,.245],'Latent SD')
handles=[Line2D([],[],marker='o',ls='none',color=GREY,ms=3,label='Selected response'),
    Line2D([],[],marker='o',ls='none',mfc='white',mec=BLUE,ms=3,label='Other model mean'),
    Line2D([],[],marker='*',ls='none',mfc=GOLD,mec=INK,mew=.4,ms=6,label='Best selected')]
fig.legend(handles=handles,loc='center',bbox_to_anchor=(.51,.052),ncol=3,columnspacing=1.8,handletextpad=.4)
round_key=object()
fig.legend(handles=[Patch(facecolor='#E8ECEF',edgecolor='none'),round_key],
    labels=['Not used in posterior fit (response maps)','Selection round (SD maps)'],
    handler_map={round_key:RoundKeyHandler()},loc='center',bbox_to_anchor=(.51,.026),
    ncol=2,columnspacing=2,handletextpad=.5,fontsize=6.3)
save(fig,'SI_BO1_posterior_landscapes')

sources=[SOURCE/'source_data/SH_PL40_full_measured_grid_seed5010.csv',
    SOURCE/'source_data/NH_OH_posteriors_by_round.csv',SOURCE/'source_data/condition_key.csv',
    ARCH/'data/run_budgets.csv',ROOT/'figures/source_data/SH_reanalysis_summary.json',ecdf_file]
sources += [ROOT/f'selections/{s["pool"]}/selected_conditions.csv' for s in systems]+[map_source,
    ROOT/'selections/OH_CuNi_96/candidates.csv',ROOT/'selections/OH_CuNi_96/candidate_manifest.json']
for p in sources:
    output_name=f'{p.parent.name}_{p.name}' if p.name=='selected_conditions.csv' else p.name
    shutil.copy2(p,DATA/output_name)
with (DATA/'NH_OH_batch_response_summary.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(batch_summaries[0]));w.writeheader();w.writerows(batch_summaries)
with (DATA/'Main_shared_color_scale.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(relative_color_checks[0]));w.writeheader();w.writerows(relative_color_checks)
with (DATA/'SH_100_paired_budgets.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['seed','bo_exact_budget','random_exact_budget','random_minus_bo'])
    for k in sorted(paired):w.writerow([k,paired[k]['BO-UCB'],paired[k]['random'],paired[k]['random']-paired[k]['BO-UCB']])
manifest=dict(figures=exports,font=os.environ.get('REACTION_FONT','DejaVu Sans'),width_mm=180,main_height_mm=265,png_dpi=600,
    main_panel_map=dict(a='SH measured surface',b='100-pair discovery CDF',c='Paired budget savings',
        d='Bayesian selection map, seed5010,24conditions',e='Random selection map, seed5010,48conditions',
        f='NH formulation / solvent final posterior surface',g='OH formulation / solvent final posterior surface'),
    source_sha256={str(p):sha(p) for p in sources},
    SH=dict(n_conditions=96,n_seed_pairs=100,seeds=[5000,5099],bo_hit_counts=counts['BO'],random_hit_counts=counts['random'],
        median_budgets=[float(np.median(bo)),float(np.median(rand))],mean_conditions_saved=float(savings.mean()),
        earlier_tied_later=[int(np.sum(savings>0)),int(np.sum(savings==0)),int(np.sum(savings<0))],
        mean_saving_bootstrap_interval=[20.88,30.72],surface_replay_seed=5010,nmr_peak_annotation='37% NMR yield',
        discovery_band='Archived 95% pointwise percentile bootstrap interval, 20000 paired-seed resamples, seed20261025'),
    formulation_axis=dict(label='Formulation',category_codes='F1–F12; identities are system-specific',
        definition='Catalyst, ligand when present, and base/additive as one formulation identity',
        NH_SH_fixed_formulations=fixed_formulations,OH_formulations=formulations,
        SH_matrix_tick_labels='Base/additive names within fixed CuCl/PPh3 background'),
    OH_formulations=formulations,
    OH_library_construction=dict(mandatory_reference_formulations=oh_library['mandatory_formulations'],
        sampled_other_formulations=10,formulation_selection_seed=oh_library['formulation_selection_seed'],
        information_boundary=oh_library['candidate_library_information_boundary']),
    NH_OH=[dict(pool=s['pool'],selected=60,other_model_predictions=36,channel=s['channel'],
        row_axis=s['row_label'],row_key_prefix=s['row_prefix'],
        vertex_error=float(np.max(np.abs(s['dz'][::SUB,::SUB]-s['mean'].reshape(12,8))))) for s in systems],
    surface_interpolation='Bounded tensor Hermite; display only; original category vertices exact; no continuous chemistry claim',
    batch_record_scope='Numerical analysis of N–H/O–H Bayesian condition selection; exported batches are not primary laboratory execution logs',
    batch_response_summaries=batch_summaries,
    batch_plot='Not in final main artwork; numerical summaries retained for provenance only',
    main_posterior_surfaces='Final batch-5 latent posterior means over96 candidates; conditioned on60 selected responses; grey points=selected measured responses, open points=other model means, stars=best selected measured response',
    main_shared_color_scale=dict(label='Relative response',limits=[0,1],
        panels=['a','d','e','f','g'],formula='raw response or posterior mean / within-system highest selected measured response',
        raw_z_axes_and_cell_values_preserved=True,SI_color_scales_unchanged=True,
        interpretation='within-system relative response; no equivalent cross-system absolute response or yield',
        systems=relative_color_checks),
    main_method_palette=dict(Bayesian=METHOD_BO,Random=METHOD_RANDOM,Same_batch=METHOD_TIE,
        panels=['b','c','d','e'],bayesian_line='solid with circles',random_line='dashed with squares',
        map_outline_white_halo=True,response_colormap_preserved=True))
(OUT/'main_posterior_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Verified all main source counts, response channels, preserved surface vertices and SH statistics.',flush=True)
