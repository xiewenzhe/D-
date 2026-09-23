"""论文图：全部来自计算结果，输出 240 dpi PNG 与可编辑 SVG。"""
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from core import Data,ROOT,RESULTS

COLORS={'A':'#3476ad','B':'#df8b34','C':'#35846b'}
plt.rcParams.update({'font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],'axes.unicode_minus':False,
    'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white','savefig.facecolor':'white'})
FIG=ROOT/'figures';FIG.mkdir(exist_ok=True)

def save(fig,name):
    fig.savefig(FIG/f'{name}.png',dpi=240,bbox_inches='tight')
    fig.savefig(FIG/f'{name}.svg',bbox_inches='tight');plt.close(fig)

def terrain(ax,data):
    lo,hi=109.15,109.30;bot,top=22.998,23.089
    c=np.where((data.lon>=lo)&(data.lon<=hi))[0];r=np.where((data.lat>=bot)&(data.lat<=top))[0]
    im=ax.imshow(data.dem[np.ix_(r,c)],extent=[data.lon[c[0]],data.lon[c[-1]],data.lat[r[-1]],data.lat[r[0]]],cmap='terrain',alpha=.7,aspect=1/np.cos(np.deg2rad(23)))
    for s,n in data.nodes.items():
        ax.scatter(n['lon'],n['lat'],s=80 if s=='O01' else 20,c='#212e45',marker='*' if s=='O01' else 'o',zorder=5)
        ax.annotate(s,(n['lon'],n['lat']),xytext=(3,4),textcoords='offset points',fontsize=8,zorder=6)
    ax.set(xlabel='经度 / °',ylabel='纬度 / °',xlim=(lo,hi),ylim=(bot,top));ax.ticklabel_format(useOffset=False)
    return im

def run(data):
    q1=json.loads((RESULTS/'q1/routes.json').read_text(encoding='utf-8'))
    rs=json.loads((RESULTS/'q2/selected/schedule.json').read_text(encoding='utf-8'))
    fig,axes=plt.subplots(1,2,figsize=(13,5),layout='constrained')
    for ax,routes,title in zip(axes,[q1,rs],['问题一 单点直接往返','问题二 联合调度路线']):
        im=terrain(ax,data)
        for r in routes:
            seq=['O01']+r['order']+['O01']
            xs=[data.nodes[n]['lon'] for n in seq];ys=[data.nodes[n]['lat'] for n in seq]
            ax.plot(xs,ys,c=COLORS[r['g']],lw=1,alpha=.6)
        ax.set_title(title)
    fig.colorbar(im,ax=axes,label='地面高程 / m',shrink=.8)
    axes[0].legend(handles=[Patch(color=c,label=g+' 型') for g,c in COLORS.items()],loc='lower left')
    save(fig,'01_terrain_routes')

    safe=pd.read_csv(RESULTS/'q1/safe_payload_sensitivity.csv')
    mat=safe[np.isclose(safe.reserve,.2)].pivot(index='model',columns='site',values='safe_payload_kg')
    fig,ax=plt.subplots(figsize=(13,3.4),layout='constrained');im=ax.imshow(mat.to_numpy(),cmap='YlGnBu',vmin=0,vmax=80,aspect='auto')
    for i in range(3):
        for j in range(15):ax.text(j,i,f'{mat.iloc[i,j]:.1f}',ha='center',va='center',color='white' if mat.iloc[i,j]>50 else '#182b36')
    ax.set_xticks(range(15),mat.columns,rotation=45);ax.set_yticks(range(3),mat.index)
    ax.set_title('20% 返航余量下最大安全载质量（不含货箱体积限制）');fig.colorbar(im,ax=ax,label='kg',shrink=.85)
    save(fig,'02_safe_payload')

    sens=pd.read_csv(RESULTS/'q1/reserve_sensitivity.csv');valid=sens[sens.feasible==True]
    fig,axes=plt.subplots(1,3,figsize=(13,3.8),layout='constrained')
    for g in 'ABC':
        ss=safe[safe.model==g].groupby('reserve').safe_payload_kg.min()
        axes[0].plot(ss.index*100,ss.values,'o-',label=g+' 型',c=COLORS[g])
    axes[0].set(xlabel='返航安全余量 / %',ylabel='最不利服务区安全载荷 / kg');axes[0].legend()
    axes[1].plot(valid.reserve*100,valid.sorties,'o-',c='#3476ad');axes[1].set(xlabel='返航安全余量 / %',ylabel='精确最少架次数')
    axes[2].plot(valid.reserve*100,valid.energy_kwh,'o-',c='#35846b');axes[2].set(xlabel='返航安全余量 / %',ylabel='能耗 / kWh')
    for ax in axes[1:]:ax.axvspan(37.5,40,color='#d67c7c',alpha=.15);ax.text(39,.95,'40%\n不可行',transform=ax.get_xaxis_transform(),va='top',ha='center',fontsize=8)
    fig.suptitle('返航余量敏感性：更保守的电量要求引发离散组批变化')
    save(fig,'03_reserve_sensitivity')

    comp=pd.read_csv(RESULTS/'q1/objective_comparison.csv').iloc[:3]
    fig,axes=plt.subplots(1,3,figsize=(12,3.5),layout='constrained')
    labels=['架次优先','能耗优先','作业时间优先']
    for ax,col,yl in zip(axes,['sorties','energy_kwh','total_operation_s'],['架次数','总能耗 / kWh','累计作业时间 / h']):
        values=comp[col].to_numpy()/(3600 if col=='total_operation_s' else 1)
        bars=ax.bar(labels,values,color=['#3476ad','#35846b','#df8b34']);ax.set_ylabel(yl);ax.bar_label(bars,fmt='%.2f',padding=3);ax.set_ylim(0,max(values)*1.16)
    save(fig,'04_q1_objective_tradeoff')

    fig,ax=plt.subplots(figsize=(13,5.4),layout='constrained')
    units=[u for ids in data.units.values() for u in ids]
    for r in rs:
        y=units.index(r['drone']);start=r['start']/60;duration=r['duration']/60
        prep=(data.drones[r['g']].prep+data.drones[r['g']].load*len(r['boxes']))/60
        ax.broken_barh([(start,duration)],(y-.32,.64),facecolors=COLORS[r['g']])
        ax.broken_barh([(start,prep)],(y-.32,.64),facecolors='#d8dde3')
        ax.text(start+duration/2,y,r['id'].replace('Q2-','')+'\n'+','.join(s[-3:] for s in r['order']),ha='center',va='center',fontsize=7,color='#182b36')
    ax.set_yticks(range(8),units);ax.set(xlabel='时间 / min',ylabel='实体运输无人机',title='运输无人机占用：灰色为固定准备与装载时间')
    ax.grid(axis='x',alpha=.2);save(fig,'05_drone_gantt')

    batteries=[f'{g}-BAT-{i+1:02}' for g in 'ABC' for i in range(data.drones[g].batteries)]
    fig,ax=plt.subplots(figsize=(13,7),layout='constrained')
    for r in rs:
        y=batteries.index(r['battery']);ax.broken_barh([(r['start']/60,r['duration']/60)],(y-.33,.66),facecolors=COLORS[r['g']])
        ax.broken_barh([(r['return']/60,r['charge']/60)],(y-.33,.66),facecolors='#e3e6eb',edgecolor='#929ca9',hatch='///',linewidth=.3)
        ax.text((r['start']+r['duration']/2)/60,y,r['id'][-3:],ha='center',va='center',fontsize=7)
    ax.set_yticks(range(len(batteries)),batteries);ax.set(xlabel='时间 / min',title='电池使用与两阶段等效充电：斜线段充至 100% 后方可复用')
    ax.legend(handles=[Patch(facecolor='#e3e6eb',hatch='///',label='充电')]);ax.grid(axis='x',alpha=.2);save(fig,'06_battery_gantt')

    delivery=pd.read_csv(RESULTS/'q2/selected/deliveries.csv');fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    for cat,sub in delivery.groupby('category'):
        ts=np.sort(sub.delivered_s.to_numpy()/60);axes[0].step(np.r_[0,ts],np.r_[0,np.arange(1,len(ts)+1)],where='post',label=cat)
    axes[0].set(xlabel='时间 / min',ylabel='累计送达箱数',title='按物资类别累计交付');axes[0].legend(fontsize=8)
    ss=delivery.sort_values(['desired_s','delivered_s']);x=np.arange(len(ss))
    axes[1].scatter(x,ss.delivered_s/60,s=12,label='实际交付');axes[1].scatter(x,ss.desired_s/60,s=10,marker='_',label='期望时间')
    hard=np.isfinite(ss.hard_s);axes[1].scatter(x[hard],ss.hard_s[hard]/60,s=20,facecolors='none',edgecolors='#c14c48',label='硬截止')
    axes[1].set(xlabel='货箱（按期望时间与实际交付排序）',ylabel='时间 / min',title='逐箱配送时限核验');axes[1].legend(fontsize=8)
    save(fig,'07_delivery_timeliness')

    exp=pd.read_csv(RESULTS/'q2/experiment_comparison.csv')
    if (RESULTS/'q2/lns_comparison.csv').exists():exp=pd.concat([exp,pd.read_csv(RESULTS/'q2/lns_comparison.csv')],ignore_index=True)
    good=exp.dropna(subset=['energy_kwh','makespan_s']);fig,ax=plt.subplots(figsize=(9,5),layout='constrained')
    for j,(_,r) in enumerate(good.iterrows()):
        ax.scatter(r.makespan_s/60,r.energy_kwh,s=r.sorties*7,alpha=.65)
        ax.annotate(r['name'],(r.makespan_s/60,r.energy_kwh),xytext=(6,7+(j%3)*10),textcoords='offset points',fontsize=7)
    ax.set(xlabel='最晚返回时间 / min',ylabel='总运输能耗 / kWh',title='第二题实验比较（圆面积与架次数成正比）');ax.grid(alpha=.2);save(fig,'08_q2_tradeoff')

    fig,ax=plt.subplots(figsize=(9,4),layout='constrained')
    for mode in ['direct','multi']:
        p=RESULTS/f'q2/lns_{mode}/history.csv'
        if p.exists():
            h=pd.read_csv(p);ax.step(h.iteration+1,h.incumbent_objective/1e6,where='post',label=mode)
    ax.set(xlabel='邻域迭代次数',ylabel='平衡目标值 / 10⁶',title='相同预算下地理邻域破坏修复收敛');ax.legend();ax.grid(alpha=.2);save(fig,'09_lns_convergence')

    # 展示地形约束，不把节点高差误当成途中爬升。
    fig,axes=plt.subplots(1,2,figsize=(12,3.8),layout='constrained')
    for ax,s in zip(axes,['S008','S015']):
        n1,n2=data.nodes['O01'],data.nodes[s];rr,cc,ts=data.cells(n1['lon'],n1['lat'],n2['lon'],n2['lat'])
        l=data.legs['O01',s];dist=ts*l['distance']/1000
        ax.fill_between(dist,data.dem[rr,cc],color='#b3c39d',alpha=.7,label='DEM 地面')
        ax.plot([0,0,l['distance']/1000,l['distance']/1000],[n1['z'],l['cruise_z'],l['cruise_z'],n2['z']+30],color='#3476ad',label='计划飞行剖面')
        ax.set(xlabel='距 O01 的水平距离 / km',ylabel='海拔 / m',title=f'O01 → {s} 航段');ax.legend(fontsize=8)
    save(fig,'10_dem_flight_profiles')
    print('Figures written to',FIG,flush=True)

if __name__=='__main__':run(Data())
