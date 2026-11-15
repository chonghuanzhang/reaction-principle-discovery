#!/usr/bin/env python3
"""Figure 5: 2x2 overview plus a 2x3 N-H posterior evolution panel.

All plot nodes come from frozen source data. No optimization is rerun.
"""
import csv
import hashlib
from types import SimpleNamespace
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.cm import ScalarMappable
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
from scipy.interpolate import PchipInterpolator

HERE=Path(__file__).resolve().parent
OUT=HERE/'figures';OUT.mkdir(exist_ok=True)
DATA=HERE/'source_data'
CURRENT=HERE.parent
REPO=CURRENT.parents[1]
SYSTEMS=['NH','OH','SH']
LABEL={'NH':'N–H','OH':'O–H','SH':'S–H'}
COLOR={'NH':'#0865FB','OH':'#D42D6A','SH':'#F29A00'}
EXPECTED={'NH':(10,12,60),'OH':(9,11,56),'SH':(7,9,48)}
SNAP=DATA/'NH_posterior_snapshots.npz'
SOURCE=CURRENT/'runs/NH/trajectory_conditions.csv'


def inputs():
    paths={}
    for system in SYSTEMS:
        source_csv=CURRENT/'runs'/system/'trajectory_conditions.csv'
        rows=read(source_csv)
        candidate_path=CURRENT/'data'/system/'candidate_space.csv'
        candidates=read(candidate_path)
        assert len(candidates)==13920
        assert [len({r[f] for r in candidates}) for f in
                ['catalyst_index','solvent_index','base_index']]==[145,8,12]
        ids=[int(r['candidate_index']) for r in rows]
        assert len(set(ids))==len(rows)
        for row,idx in zip(rows,ids):
            candidate=candidates[idx]
            assert row['measured']=='True' and row['feedback_assimilated']=='True'
            for field in ['candidate_index','catalyst_index','solvent_index','base_index',
                          'cat','ligand','solvent','base']:
                assert candidate[field]==row[field],(system,idx,field)
            assert float(row['UV_response'])==float(candidate['UV_response'])
        stop=max(int(r['batch_number']) for r in rows)
        assert [sum(int(r['batch_number'])==b for r in rows)
                for b in range(stop+1)]==[12]+[4]*stop
        maximum=max(float(r['UV_response']) for r in rows)
        hit=min(int(r['batch_number']) for r in rows if float(r['UV_response'])==maximum)
        assert (hit,stop,len(rows))==EXPECTED[system]
        assert maximum==max(float(r['UV_response']) for r in candidates if r['measured']=='True')
        paths[system]={'rows':rows,'candidate_path':candidate_path,'candidates':candidates,
            'source_csv':source_csv,'maximum':maximum,'hit':hit,'stop':stop,
            'best_by_round':[max(float(r['UV_response']) for r in rows
                                if int(r['batch_number'])<=b) for b in range(stop+1)]}
    return paths


def get_coordinates(all_rows):
    # Response-blind factor projection, centred on the fixed first 24 conditions.
    first=[r for r in all_rows if int(r['batch_number'])<=3]
    displayed=[r for r in all_rows if int(r['batch_number'])<=3 or int(r['batch_number']) in [10,12]]
    assert len(first)==24 and len(displayed)==32
    w=np.load(str(DATA/'projection_weights.npz'))
    factors=[('catalyst_weights','catalyst_index'),('solvent_weights','solvent_index'),('base_weights','base_index')]
    def raw(rows):return np.array([[w[name][int(r[field])] for name,field in factors] for r in rows])
    old_raw=raw(first);center,scale=old_raw.mean(axis=0),old_raw.std(axis=0)
    old_proj=((old_raw-center)/scale).sum(axis=1)/np.sqrt(3)
    proj=(((raw(displayed)-center)/scale).sum(axis=1)/np.sqrt(3))/old_proj.std()
    assert len(set(np.round(proj,12)))==32
    previous={int(r['candidate_index']):float(r['joint_projection'])
              for r in read(DATA/'initial_joint_coordinates.csv')}
    for r,p in zip(displayed,proj):
        if int(r['candidate_index']) in previous:assert abs(float(p)-previous[int(r['candidate_index'])])<1e-12
    order=np.argsort(proj)
    return [displayed[i] for i in order],proj[order]


original=SimpleNamespace(inputs=inputs,SYSTEMS=SYSTEMS,LABEL=LABEL,COLOR=COLOR)
posterior=SimpleNamespace(SNAP=SNAP,SOURCE=SOURCE,get_coordinates=get_coordinates)

INK='#25343D';GREY='#70808B';BLUE='#386BA5';GOLD='#E5A93D'
RESPONSE=LinearSegmentedColormap.from_list('response',
    ['#FBFBF3','#E6EEE1','#A8CEB6','#68B39D','#268773'],N=512)


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def write(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def style():
    plt.rcParams.update({'font.family':'Arial','font.size':7.1,'axes.labelsize':7.1,
        'axes.titlesize':7.4,'xtick.labelsize':6.1,'ytick.labelsize':6.1,
        'axes.linewidth':.65,'text.color':INK,'axes.labelcolor':INK,
        'xtick.color':'#3C4B56','ytick.color':'#3C4B56','figure.facecolor':'white',
        'savefig.facecolor':'white','pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none',
        'mathtext.fontset':'custom','mathtext.rm':'Arial','mathtext.it':'Arial:italic',
        'mathtext.bf':'Arial:bold','legend.frameon':False})


def panel_label(fig,letter,x,y,title):
    fig.text(x,y,letter,fontsize=13,fontweight='bold',va='baseline')
    fig.text(x+.048,y,title,fontsize=8.6,fontweight='bold',va='baseline')


def boxed(ax):
    for sp in ax.spines.values():sp.set_visible(True);sp.set_color('#82909A');sp.set_linewidth(.65)
    ax.tick_params(length=2.6,width=.6,direction='out')


def draw_progress(fig,paths):
    panel_label(fig,'a',.025,.978,'Bayesian optimization')
    ax=fig.add_axes([.085,.755,.390,.184])
    ax.axvspan(-.46,.46,color='#F0F3F5',zorder=0)
    records=[];summaries=[];offsets={'NH':-.21,'OH':0,'SH':.21}
    for system in original.SYSTEMS:
        p=paths[system];col=original.COLOR[system]
        for batch in range(p['stop']+1):
            rows=[r for r in p['rows'] if int(r['batch_number'])==batch]
            yy=np.array([float(r['UV_response']) for r in rows])
            xx=batch+offsets[system]
            mean=float(yy.mean());low=float(yy.min());high=float(yy.max())
            ax.bar([xx],[mean],width=.18,color=col,edgecolor=col,lw=.45,alpha=.27,zorder=2)
            ax.errorbar([xx],[mean],yerr=np.array([[mean-low],[high-mean]]),fmt='none',
                        ecolor=col,elinewidth=.5,capsize=1.3,capthick=.5,alpha=.62,zorder=3)
            records.extend(dict(system=system,BO_round=batch,candidate_index=int(r['candidate_index']),
                UV_response=float(r['UV_response']),x_display=float(xx)) for r in rows)
            summaries.append(dict(system=system,BO_round=batch,n=len(rows),mean_UV=mean,
                                  minimum_UV=low,maximum_UV=high,x_display=float(xx)))
        rr=range(p['stop']+1)
        ax.step(rr,p['best_by_round'],where='post',color=col,lw=1.6,zorder=4)
        ax.scatter([p['hit']],[p['maximum']],marker='*',s=78,c=col,edgecolors=INK,lw=.5,zorder=7)
        ax.scatter([p['stop']],[p['maximum']],marker='s',s=28,facecolors='white',edgecolors=col,lw=1.1,zorder=7)
    for s,xy in [('SH',(9.32,3.25)),('NH',(11.9,1.86)),('OH',(10.4,1.08))]:
        p=paths[s]
        ax.annotate('{:.3f}'.format(p['maximum']),xy=(p['stop'],p['maximum']),xytext=xy,
                    color=original.COLOR[s],fontsize=6.7,ha='left',va='center',
                    arrowprops=dict(arrowstyle='-',color=original.COLOR[s],lw=.55))
    ax.set_xlim(-.60,13.6);ax.set_ylim(-.07,3.60)
    ax.set_xticks(range(0,13,2));ax.set_yticks([0,1,2,3])
    ax.set_xlabel('Bayesian optimization round',labelpad=4)
    ax.set_ylabel('UV response',labelpad=4)
    ax.grid(axis='y',color='#E6EBEF',lw=.45,zorder=0);boxed(ax)
    fig.legend(handles=[Line2D([],[],color=original.COLOR[s],lw=1.6,label=original.LABEL[s])
                        for s in original.SYSTEMS],loc='center',bbox_to_anchor=(.275,.955),
               ncol=3,fontsize=7.0,handlelength=1.5,columnspacing=1.6,handletextpad=.5)
    range_key=ax.errorbar([],[],yerr=[],fmt='none',ecolor=GREY,elinewidth=.6,capsize=1.5)
    keys=[Patch(facecolor=GREY,edgecolor=GREY,alpha=.3,label='Batch mean'),
          range_key,
          Line2D([],[],marker='*',ls='none',color=GREY,ms=6,label='First best'),
          Line2D([],[],marker='s',ls='none',mfc='white',mec=GREY,ms=3.8,label='Stop')]
    fig.legend(handles=keys,labels=['Batch mean','Min–max','First best','Stop'],
               loc='center',bbox_to_anchor=(.273,.708),ncol=4,
               fontsize=5.8,handletextpad=.3,columnspacing=.85)
    assert len(records)==164 and len(summaries)==35
    for summary in summaries:
        values=[r['UV_response'] for r in records if r['system']==summary['system'] and r['BO_round']==summary['BO_round']]
        assert len(values)==summary['n']
        assert abs(sum(values)/len(values)-summary['mean_UV'])<1e-12
        assert min(values)==summary['minimum_UV'] and max(values)==summary['maximum_UV']
    write(DATA/'panel_a_points.csv',records)
    write(DATA/'panel_a_batch_bars.csv',summaries)
    return dict(source_values=164,bars=35,bar_height='Arithmetic mean of measured responses in each batch',
        whiskers='Observed minimum–maximum across different conditions, not replicate uncertainty',
        initial_per_system=12,per_BO_round=4,
        systems={s:dict(hit=paths[s]['hit'],stop=paths[s]['stop'],n=len(paths[s]['rows']),
                       maximum=paths[s]['maximum']) for s in original.SYSTEMS})


def smooth_grid(z,sub=18):
    # Bounded tensor Hermite matches the original figure's display connector.
    x=np.linspace(0,7,7*sub+1);y=np.linspace(0,11,11*sub+1)
    ix=np.minimum(np.floor(x).astype(int),6);tx=x-ix;hx=tx*tx*(3-2*tx)
    iy=np.minimum(np.floor(y).astype(int),10);ty=y-iy;hy=ty*ty*(3-2*ty)
    low=z[iy[:,None],ix[None,:]]*(1-hx)+z[iy[:,None],ix[None,:]+1]*hx
    high=z[iy[:,None]+1,ix[None,:]]*(1-hx)+z[iy[:,None]+1,ix[None,:]+1]*hx
    dense=low*(1-hy[:,None])+high*hy[:,None]
    assert np.max(np.abs(dense[::sub,::sub]-z))<1e-12
    assert dense.min()>=z.min()-1e-12 and dense.max()<=z.max()+1e-12
    X,Y=np.meshgrid(x+1,y+1)
    return X,Y,dense


def draw_surface(fig,system,letter,rect,title_y,bar_y,all_rows):
    left=.025 if rect[0]<.5 else .525
    panel_label(fig,letter,left,title_y,original.LABEL[system])
    rows=sorted([r for r in all_rows if r['system']==system],key=lambda r:(int(r['row']),int(r['column'])))
    assert len(rows)==96
    z=np.array([float(r['UV_response']) for r in rows]).reshape(12,8)
    assert len(set(r['candidate_index'] for r in rows))==96
    X,Y,dense=smooth_grid(z)
    ax=fig.add_axes(rect,projection='3d')
    ax.view_init(elev=27,azim=-58);ax.dist=10.25
    norm=Normalize(0,float(z.max()))
    surf=ax.plot_surface(X,Y,dense,cmap=RESPONSE,norm=norm,rstride=2,cstride=2,
                         linewidth=0,antialiased=True,shade=False)
    surf.set_rasterized(True)
    xnodes,ynodes=np.meshgrid(np.arange(1,9),np.arange(1,13))
    ax.scatter(xnodes.ravel(),ynodes.ravel(),z.ravel(),s=4.5,c='#87969C',
               edgecolors='white',lw=.25,alpha=.8,depthshade=False)
    ri,ci=np.unravel_index(np.argmax(z),z.shape)
    ax.scatter([ci+1],[ri+1],[z[ri,ci]],marker='*',s=65,facecolors=GOLD,
               edgecolors='#4E4B3E',lw=.55,depthshade=False)
    ax.set_xlim(.8,8.2);ax.set_ylim(.8,12.2)
    top={'NH':1.22,'OH':1.68,'SH':3.75}[system]
    ticks={'NH':[0,.5,1.0],'OH':[0,.5,1,1.5],'SH':[0,1,2,3]}[system]
    ax.set_zlim(0,top);ax.set_zticks(ticks)
    ax.set_xticks([1,4,8]);ax.set_xticklabels(['S1','S4','S8'])
    ax.set_yticks([1,6,12]);ax.set_yticklabels(['F1','F6','F12'])
    ax.set_xlabel('Solvent',labelpad=1)
    ax.set_ylabel('Formulation',labelpad=1)
    ax.set_zlabel('UV response',labelpad=2)
    ax.tick_params(pad=0,length=2,labelsize=6)
    for axis in [ax.xaxis,ax.yaxis,ax.zaxis]:
        axis.pane.fill=False;axis.pane.set_edgecolor('#E3E9ED')
        axis._axinfo['grid']['color']=(.86,.89,.92,.65)
        axis._axinfo['grid']['linewidth']=.45;axis.line.set_color('#78858F')
    cbx=rect[0]+.12
    cb=fig.colorbar(ScalarMappable(norm=Normalize(0,1),cmap=RESPONSE),
                   cax=fig.add_axes([cbx,bar_y,.215,.006]),orientation='horizontal',ticks=[0,.5,1])
    cb.ax.set_title('Relative UV response',fontsize=6.1,pad=2)
    cb.ax.tick_params(labelsize=5.6,length=1.6,width=.45,pad=1.5);cb.outline.set_linewidth(.4)
    return dict(system=system,values='measured UV response',nodes=96,shape=[12,8],
        local_maximum=float(z.max()),local_minimum=float(z.min()),
        maximum_candidate_index=int(rows[ri*8+ci]['candidate_index']),
        maximum_row=int(ri+1),maximum_column=int(ci+1),
        colour='Within-displayed-grid response divided by its maximum; 0..1',
        raw_height_preserved=True,all_original_nodes_preserved=True)


def draw_posterior(fig):
    panel_label(fig,'e',.025,.395,'N–H posterior evolution')
    a=np.load(str(posterior.SNAP))
    rows,coords=posterior.get_coordinates(read(posterior.SOURCE))
    ids=np.array([int(r['candidate_index']) for r in rows])
    batches=np.array([int(r['batch_number']) for r in rows])
    x=np.arange(1,33);xd=np.linspace(1,32,1241)
    target=int(np.flatnonzero(ids==112)[0])
    handles=[Line2D([],[],color=BLUE,lw=1.1,label='Mean'),
        Patch(facecolor='#9BB8DE',alpha=.32,label='±2 SD'),
        Line2D([],[],color='#AEB8C1',ls='--',lw=.6,label='Previous band'),
        Line2D([],[],ls='none',marker='o',mfc=BLUE,mec='white',ms=3.8,label='Evaluated'),
        Line2D([],[],ls='none',marker='o',mfc='#F3BC67',mec='#947443',ms=4,label='New'),
        Line2D([],[],ls='none',marker='*',mfc=GOLD,mec='#6E532C',ms=6,label='Best')]
    fig.legend(handles=handles,loc='center',bbox_to_anchor=(.52,.370),ncol=6,
               fontsize=6.1,handletextpad=.35,columnspacing=1.35,handlelength=1.45)
    rounds=[0,1,2,3,10,12];output=[];checks=[]
    for k,batch in enumerate(rounds):
        rr,cc=divmod(k,3)
        left=[.085,.395,.705][cc];bottom=[.213,.052][rr]
        ax=fig.add_axes([left,bottom,.25,.12])
        mu=a['mean'][batch,ids];sd=a['latent_sd'][batch,ids]
        m=PchipInterpolator(x,mu)(xd);s=PchipInterpolator(x,sd)(xd)
        assert s.min()>=0
        assert np.max(np.abs(PchipInterpolator(x,mu)(x)-mu))<1e-12
        if batch:
            pm=PchipInterpolator(x,a['mean'][batch-1,ids])(xd)
            ps=PchipInterpolator(x,a['latent_sd'][batch-1,ids])(xd)
            ax.plot(xd,pm-2*ps,lw=.5,color='#ADB6BF',ls=(0,(2,2)),zorder=1)
            ax.plot(xd,pm+2*ps,lw=.5,color='#ADB6BF',ls=(0,(2,2)),zorder=1)
        ax.fill_between(xd,m-2*s,m+2*s,color='#9BB8DE',alpha=.32,lw=0,zorder=2)
        ax.plot(xd,m,color=BLUE,lw=1.1,zorder=3)
        evaluated=batches<=batch;new=batches==batch
        ax.scatter(x[evaluated],mu[evaluated],s=8,c=BLUE,edgecolors='white',lw=.25,zorder=5)
        if batch:ax.scatter(x[new],mu[new],s=17,facecolors='#F3BC67',edgecolors='#947443',lw=.4,zorder=6)
        if batch>=10:ax.scatter([x[target]],[mu[target]],marker='*',s=58,c=GOLD,edgecolors='#6E532C',lw=.5,zorder=8)
        title='Initialization' if batch==0 else 'After round {}'.format(batch)
        title_y=bottom+.134 if rr==0 else bottom+.144
        fig.text(left,title_y,title,fontsize=7.0,fontweight='bold')
        if batch in [10,12]:
            fig.text(left,bottom+.131,'Best condition found' if batch==10 else 'Stopping round',fontsize=6.1,color='#62727C')
        ax.set_xlim(.5,32.5);ax.set_ylim(-.8,2.05)
        ax.set_xticks([1,8,16,24,32]);ax.set_yticks([0,1,2])
        ax.grid(axis='y',color='#ECF0F3',lw=.4,zorder=0);boxed(ax)
        if cc==0:ax.set_ylabel('UV response',labelpad=4)
        else:ax.tick_params(labelleft=False)
        ax.tick_params(labelsize=5.8)
        if rr==0:ax.tick_params(labelbottom=False)
        checks.append(dict(BO_round=batch,full_model_n=int(a['observed_count'][batch]),
            displayed_evaluated=int(evaluated.sum()),displayed_conditions=32,new=int(new.sum()),
            target_mean=float(mu[target]),target_SD=float(sd[target]),marker_Y='posterior mean'))
        for j,idx in enumerate(ids):
            output.append(dict(BO_round=batch,candidate_index=int(idx),coordinate_rank=int(x[j]),
                posterior_mean=float(mu[j]),posterior_latent_SD=float(sd[j]),
                evaluated=bool(evaluated[j]),new_this_round=bool(new[j])))
    fig.text(.52,.020,'Joint three-factor coordinate',ha='center',fontsize=7.0)
    write(DATA/'panel_e_posterior_points.csv',output)
    write(DATA/'panel_e_coordinates.csv',[dict(candidate_index=int(idx),coordinate_rank=int(xi),
        original_joint_projection=float(c),BO_round_added=int(b)) for idx,xi,c,b in zip(ids,x,coords,batches)])
    return dict(grid=[2,3],rounds=rounds,source_prediction_changes=False,
        uncertainty='Plus/minus two latent posterior SD',points='Posterior mean at evaluated conditions',
        interpolation='PCHIP connectors between categorical nodes only',checks=checks)


def main():
    paths=original.inputs();grid=read(DATA/'grids_96.csv');assert len(grid)==288
    for row in grid:
        candidate=paths[row['system']]['candidates'][int(row['candidate_index'])]
        assert candidate['measured']=='True'
        assert float(candidate['UV_response'])==float(row['UV_response'])
        assert (candidate['cat'],candidate['base'],candidate['solvent'])==(row['cat'],row['base'],row['solvent'])
    style()
    fig=plt.figure(figsize=(190/25.4,255/25.4))
    progress=draw_progress(fig,paths)
    surfaces=[]
    for args in [('NH','b',[.515,.714,.44,.235],.978,.950),
                 ('OH','c',[.015,.427,.44,.235],.691,.663),
                 ('SH','d',[.515,.427,.44,.235],.691,.663)]:
        surfaces.append(draw_surface(fig,*args,all_rows=grid))
    post=draw_posterior(fig)
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    clipped=[]
    for t in fig.findobj(match=matplotlib.text.Text):
        if not t.get_visible() or not t.get_text():continue
        # 3-D axis formatters create hidden/out-of-range z tick artists.
        bb=t.get_window_extent(renderer)
        if bb.x0 < -2 or bb.y0 < -2 or bb.x1 > fig.bbox.x1+2 or bb.y1 > fig.bbox.y1+2:
            clipped.append(dict(text=t.get_text(),bbox=[float(v) for v in bb.extents]))
    stem='Figure_5_composite'
    for ext in ['png','pdf','svg']:fig.savefig(OUT/(stem+'.'+ext),dpi=450)
    svg_path=OUT/(stem+'.svg')
    svg_path.write_text('\n'.join(line.rstrip() for line in svg_path.read_text().splitlines())+'\n')
    fig.savefig(OUT/(stem+'_preview.png'),dpi=220)
    plt.close(fig)
    report=dict(status='PASS' if not clipped else 'CHECK_TEXT',figure_size_mm=[190,255],
        layout={'top':'2x2: a progress, b NH, c OH, d SH','bottom':'e 2x3 posterior snapshots'},
        panel_a=progress,panels_bcd=surfaces,panel_e=post,text_outside_canvas=clipped,
        individual_colour_bars={'count':3,'panels':['b','c','d'],'limits':[0,1]},
        sources={str(p.relative_to(REPO)):sha(p) for p in [DATA/'grids_96.csv',posterior.SNAP,posterior.SOURCE,DATA/'projection_weights.npz',Path(__file__).resolve()]},
        outputs={str(p.relative_to(REPO)):sha(p) for p in OUT.glob('Figure_5_composite*')})
    (HERE/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(status=report['status'],outside_text=clipped,figure=str(OUT/(stem+'.png'))),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
