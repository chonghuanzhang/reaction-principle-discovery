from pathlib import Path
import json,csv
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
ROOT=Path(__file__).resolve().parent
OUT=ROOT
(OUT/'figures').mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'Arial','font.size':9,'axes.linewidth':.75,'pdf.fonttype':42,'svg.fonttype':'none'})
COL={'NH':'#4379a5','OH':'#d68d50','SH':'#5c9577'}
paths={s:json.loads((ROOT/'runs'/s/'trajectory.json').read_text()) for s in COL}
snaps={}
for s in COL:
 rows=list(csv.DictReader((ROOT/'runs'/s/'trajectory_conditions.csv').open(encoding='utf-8-sig')))
 z=np.load(ROOT/'verification'/f'{s}_posterior_snapshots.npz')
 snaps[s]={'observed_BO_round':np.array([int(r['batch_number']) for r in rows]),
           'observed_UV_response':np.array([float(r['UV_response']) for r in rows]),
           'observed_candidate_index':np.array([int(r['candidate_index']) for r in rows]),
           'latent_sd':z['sds'], 'completed_BO_round':np.arange(len(z['sds']))}
verification={}
def save(fig,n):
 fig.savefig(OUT/'figures'/f'Supplementary_Figure_{n}.png',dpi=300)
 fig.savefig(OUT/'figures'/f'Supplementary_Figure_{n}.pdf')
 plt.close(fig)
def base(ax,s,k):
 ax.text(-.095,1.04,chr(97+k),transform=ax.transAxes,weight='bold',size=12)
 ax.set_title(s[0]+'–H',loc='left',weight='bold',pad=7)
 ax.grid(axis='y',alpha=.2,lw=.5)
 ax.tick_params(direction='out',length=3)
# Every selected response, with cumulative best; round 0 denotes 12 observations.
fig,axs=plt.subplots(3,1,figsize=(7.05,7.7))
fig.subplots_adjust(left=.11,right=.965,bottom=.085,top=.94,hspace=.52)
records=[]
for k,(s,ax) in enumerate(zip(COL,axs)):
 d,z=paths[s],snaps[s];base(ax,s,k)
 rounds=z['observed_BO_round']; vals=z['observed_UV_response']; ids=z['observed_candidate_index'];stop=d['completed_BO_batches'];hit=d['first_target_BO_round']
 for r in range(stop+1):
  y=vals[rounds==r]; xx=r+np.linspace(-.24,.24,len(y));ax.vlines(xx,0,y,color=COL[s],alpha=.6,lw=2.2)
  for i,v in zip(ids[rounds==r],y): records.append({'system':s,'round':r,'candidate_index':int(i),'UV_response':float(v)})
 best=np.array([h['stop_check']['observed_best'] for h in d['history']]);ax.step(range(stop+1),best,where='post',color=COL[s],lw=1.6)
 ax.scatter([hit],[best[hit]],marker='*',s=95,c=COL[s],edgecolor='white',linewidth=.5,zorder=5)
 ax.scatter([stop],[best[-1]],marker='s',s=30,facecolor='white',edgecolor=COL[s],zorder=5)
 ax.set_xlim(-.5,stop+.5);ax.set_ylim(0,best[-1]*1.17);ax.set_xticks(range(stop+1));ax.set_ylabel('UV response');ax.set_xlabel('Bayesian optimization round')
 verification[s]={'n':len(vals),'hit':hit,'stop':stop,'unique':len(set(ids.tolist()))}
fig.legend(handles=[Line2D([0],[0],color='#666666',lw=2,label='Individual response'),Line2D([0],[0],color='#666666',lw=1.4,label='Cumulative best'),Line2D([0],[0],color='none',marker='*',markerfacecolor='#666666',markeredgecolor='#666666',label='First highest response'),Line2D([0],[0],color='none',marker='s',markerfacecolor='white',markeredgecolor='#666666',label='Stopping round')],loc='upper center',ncol=2,frameon=False,bbox_to_anchor=(.52,1.01),fontsize=8)
save(fig,7)
with (OUT/'source_data'/'selected_response_source.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
# Actual stopping values, raw units, includes ineligible checks as grey markers.
fig,axs=plt.subplots(3,1,figsize=(7.05,7.2));fig.subplots_adjust(left=.12,right=.965,bottom=.085,top=.95,hspace=.55)
checks=[]
for k,(s,ax) in enumerate(zip(COL,axs)):
 d=paths[s];base(ax,s,k);hs=d['history']; rr=[];yy=[]
 for h in hs:
  c=h['stop_check'];r=h['batch_number'];v=c['improvement_over_last_two_batches']
  if v is not None:
   rr.append(r);yy.append(v);checks.append({'system':s,'round':r,'n':c['observed_count'],'improvement':v,'delta':c['delta_response_units'],'eligible':c['minimum_observations_met'],'stop':c['model_stop_criterion_met']})
 delta=hs[0]['stop_check']['delta_response_units'];ax.plot(rr,yy,color=COL[s],lw=1.6,marker='o',ms=3.5)
 ax.axhline(delta,ls='--',color='#555555',lw=1);ax.scatter([d['completed_BO_batches']],[yy[-1]],marker='s',s=45,facecolor='white',edgecolor=COL[s],zorder=5)
 ax.axvspan(-.5,2.5,facecolor='#eeeeee',zorder=0)
 ax.set_xlim(-.5,d['completed_BO_batches']+.5);ax.set_xticks(range(d['completed_BO_batches']+1));ax.set_ylim(-max(yy)*.045,max(yy)*1.16)
 ax.set_ylabel('Two-round best-response gain');ax.set_xlabel('Bayesian optimization round')
fig.legend([Line2D([0],[0],color='#555555',ls='--'),Line2D([0],[0],color='none',marker='s',markerfacecolor='white',markeredgecolor='#555555')],['Stopping tolerance δ','First eligible stopping round'],loc='upper center',ncol=2,frameon=False,bbox_to_anchor=(.52,1.005),fontsize=8)
save(fig,8)
with (OUT/'source_data'/'stopping_source.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(checks[0]));w.writeheader();w.writerows(checks)
# Mean latent uncertainty at the same fixed set of eventually selected identities.
fig,axs=plt.subplots(3,1,figsize=(7.05,7.2));fig.subplots_adjust(left=.12,right=.965,bottom=.085,top=.94,hspace=.55)
records=[]
for k,(s,ax) in enumerate(zip(COL,axs)):
 d,z=paths[s],snaps[s];base(ax,s,k);ids=z['observed_candidate_index'];sd=z['latent_sd']
 selected=sd[:,ids].mean(axis=1);full=sd.mean(axis=1);rounds=z['completed_BO_round']
 ax.plot(rounds,selected,color=COL[s],lw=1.8,marker='o',ms=3,label='Fixed final selected set')
 ax.plot(rounds,full,color='#888888',lw=1.2,ls='--',label='Full decision space')
 ax.axvline(d['first_target_BO_round'],color=COL[s],alpha=.4,lw=.8)
 ax.set_xticks(rounds);ax.set_xlim(-.25,rounds[-1]+.25);ax.set_ylim(0,max(full.max(),selected.max())*1.13)
 ax.set_ylabel('Mean latent posterior SD');ax.set_xlabel('Bayesian optimization round')
 for r,a,b in zip(rounds,selected,full):records.append({'system':s,'round':int(r),'fixed_selected_mean_SD':float(a),'full_space_mean_SD':float(b)})
fig.legend([Line2D([0],[0],color='#555555',lw=1.8),Line2D([0],[0],color='#888888',ls='--'),Line2D([0],[0],color='#555555',alpha=.4)],['Fixed final selected set','Full decision space','First highest response'],loc='upper center',ncol=3,frameon=False,bbox_to_anchor=(.52,1.005),fontsize=8)
save(fig,9)
with (OUT/'source_data'/'uncertainty_source.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
(OUT/'source_data'/'figure_verification.json').write_text(json.dumps(verification,indent=2))
print(json.dumps(verification))
