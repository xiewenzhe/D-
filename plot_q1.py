"""Publication figures generated exclusively from the computed Q1 results."""
from pathlib import Path
import sys,json,shutil
from collections import Counter
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from PIL import Image,ImageOps,ImageDraw
import rasterio
ROOT=Path(__file__).resolve().parent
SKILL=ROOT.parents[1]/'math_model_skill'/'math-modeling-skill'
sys.path.insert(0,str(SKILL/'tools'/'figure'/'scripts'))
from export_figure import export_figure
from visual_qa import audit_layout,render_preview
from utils.plot_style import apply_publication_style,PALETTE,COLOR_SEQUENCE
from solve_q1 import read_inputs,energy
apply_publication_style('zh','report')
plt.rcParams.update({'font.size':10,'axes.labelsize':10,'xtick.labelsize':9,'ytick.labelsize':9,'legend.fontsize':9,'pdf.fonttype':42})
OUT=ROOT/'figures';QA=OUT/'_qa';OUT.mkdir(exist_ok=True);QA.mkdir(exist_ok=True)
r=json.loads((ROOT/'results/q1/solution.json').read_text(encoding='utf-8'))
nodes,models,boxes,attrs=read_inputs();areas=sorted(r['geometry']);cols=list(COLOR_SEQUENCE)
audits={}
def canvas(h=3.65):return plt.subplots(figsize=(6.3,h),layout='constrained')
def save(fig,name):
    fig.canvas.draw();issues=audit_layout(fig);audits[name]=issues
    export_figure(fig,str(OUT/name),formats=['pdf','svg','png'],dpi=300,size_inches=tuple(fig.get_size_inches()),tight=False)
    render_preview(fig,str(QA/(name+'.png')),dpi=120)
    with Image.open(OUT/(name+'.png')) as im:ImageOps.grayscale(im).save(QA/(name+'_gray.png'),dpi=(300,300))
    plt.close(fig)

# Raw data: geography, zone counts and the mass-volume structure of boxes.
fig,ax=canvas(4.1)
with rasterio.open(next((ROOT/'数据').rglob('*.tif'))) as ds:
    x0,x1=109.16,109.29;y0,y1=22.997,23.085
    win=rasterio.windows.from_bounds(x0,y0,x1,y1,ds.transform).round_offsets().round_lengths()
    z=ds.read(1,window=win);tr=ds.window_transform(win)
    cc,rr=np.meshgrid(np.arange(0,z.shape[1],3),np.arange(0,z.shape[0],3));xx,yy=tr*(cc,rr)
    cs=ax.contourf(xx,yy,z[::3,::3],levels=np.arange(50,951,100),cmap='terrain',extend='both')
home=nodes['O01']
for sid in areas:
    s=nodes[sid];ax.plot([home['lon'],s['lon']],[home['lat'],s['lat']],color='#333333',lw=.7,alpha=.65)
    ax.scatter(s['lon'],s['lat'],s=18,c='white',edgecolor='#222222',zorder=3)
    ax.annotate(sid,(s['lon'],s['lat']),xytext=(3,4),textcoords='offset points',fontsize=8)
ax.scatter(home['lon'],home['lat'],marker='*',s=115,color=cols[3],edgecolor='white',zorder=4)
ax.annotate('O01',(home['lon'],home['lat']),xytext=(-24,-13),textcoords='offset points')
ax.set(xlim=(x0,x1),ylim=(y0,y1),xlabel='经度 / °E',ylabel='纬度 / °N')
ax.ticklabel_format(useOffset=False);ax.set_aspect(1/np.cos(np.deg2rad(23.04)))
fig.colorbar(cs,ax=ax,label='地形高程 / m',shrink=.85);save(fig,'raw_q1_map')

fig,ax=canvas();bottom=np.zeros(15)
for k,c,label in zip(('MED','WAT','FOD','HYG'),cols,('医疗物资','饮用水','应急食品','生活卫生用品')):
    values=np.array([sum(b['area']==sid and b['kind']==k for b in boxes) for sid in areas])
    ax.bar(areas,values,bottom=bottom,label=label,color=c,width=.7);bottom+=values
ax.set(ylabel='需求货箱数 / 箱',ylim=(0,18));ax.tick_params(axis='x',rotation=55)
ax.legend(ncol=2,loc='upper right',frameon=False);save(fig,'raw_q1_demand')

fig,ax=canvas(3.3)
for k,c,label in zip(attrs,cols,('医疗物资','饮用水','应急食品','生活卫生用品')):
    mass,vol=attrs[k];n=sum(b['kind']==k for b in boxes)
    ax.scatter(mass,vol*1000,s=n*14,color=c,edgecolor='#333333',lw=.5)
    ax.annotate(f'{label} ({n}箱)',(mass,vol*1000),xytext=(8,6),textcoords='offset points',fontsize=9)
ax.set(xlabel='单箱质量 / kg',ylabel='单箱体积 / L',xlim=(0,20),ylim=(5,42));ax.grid(alpha=.2)
save(fig,'raw_q1_boxes')

sid=max(areas,key=lambda s:r['geometry'][s]['cruise_m']);route=r['geometry'][sid]
fig,ax=canvas(3.25);x=np.array(route['profile_distance_m'])/1000;z=route['profile_terrain_m']
ax.fill_between(x,0,z,color='#D3D5CD');ax.plot(x,z,color='#626958',lw=1,label='DEM 剖面（显示间隔约10 m）')
ax.axhline(route['cruise_m'],color=cols[0],ls='--',label='巡航高度：沿途最高栅格 + 50 m')
ax.plot([0,0,x[-1],x[-1]],[home['z'],route['cruise_m'],route['cruise_m'],nodes[sid]['z']+30],color=cols[3],lw=1.8,label=f'O01—{sid} 去程')
ax.set(xlabel='距调度中心水平距离 / km',ylabel='绝对高程 / m',ylim=(0,route['cruise_m']+150));ax.legend(fontsize=8,loc='upper left',frameon=False)
save(fig,'process_q1_profile')

sid=max(areas,key=lambda s:r['geometry'][s]['distance_m']);route=r['geometry'][sid]
fig,ax=canvas(3.25)
for (gid,g),c,ls in zip(models.items(),cols,('-','--','-.')):
    qs=np.linspace(0,g['capacity'],200);ys=[100*energy(route,g,q)/g['battery'] for q in qs]
    ax.plot(qs,ys,color=c,ls=ls,label=f'{gid} 型')
ax.axhline(80,color='#333333',ls=':',label='20% 余量对应能耗上限')
ax.set(xlabel='去程载荷 / kg',ylabel='往返耗能占可用电量 / %',title=f'最远服务区 {sid}');ax.legend(frameon=False)
save(fig,'process_q1_energy')

fig,ax=canvas(3.4);x=np.arange(15)
for j,gid in enumerate(models):ax.bar(x+(j-1)*.24,[p[gid] for p in r['pattern_stats']],width=.23,color=cols[j],label=f'{gid} 型')
ax.set(xticks=x,xticklabels=areas,ylabel='可行装载模式数');ax.tick_params(axis='x',rotation=55);ax.legend(frameon=False)
save(fig,'process_q1_patterns')

fig,ax=canvas(4.65)
mat=np.array([[next(p['max_safe_kg'] for p in r['capacities'] if p['area']==sid and p['model']==gid) for gid in models] for sid in areas])
pc=ax.pcolormesh(np.arange(4),np.arange(16),mat,cmap='Blues',vmin=0,vmax=80,edgecolors='white',linewidth=1)
for i in range(15):
    for j in range(3):ax.text(j+.5,i+.5,f'{mat[i,j]:.2f}',ha='center',va='center',color='white' if mat[i,j]>50 else '#222222',fontsize=9)
ax.set(xticks=np.arange(3)+.5,xticklabels=['A 型','B 型','C 型'],yticks=np.arange(15)+.5,yticklabels=areas);ax.invert_yaxis()
fig.colorbar(pc,ax=ax,label='最大安全载荷 / kg',shrink=.85);save(fig,'result_q1_payload')

fig,ax=canvas(3.4);bottom=np.zeros(15)
for gid,c in zip(models,cols):
    v=np.array([sum(s['area']==sid and s['model']==gid for s in r['schedule']) for sid in areas]);ax.bar(areas,v,bottom=bottom,color=c,label=f'{gid} 型');bottom+=v
ax.set(ylabel='选用架次数 / 次',ylim=(0,max(bottom)+1));ax.tick_params(axis='x',rotation=55);ax.set_yticks(range(int(max(bottom))+2));ax.legend(frameon=False,ncol=3)
save(fig,'result_q1_allocation')

fig,ax=canvas(3.6)
labels={'NET':'架次→能耗→时间','ENT':'能耗→架次→时间','TNE':'时间→架次→能耗','NTE':'架次→时间→能耗'}
for j,(key,v) in enumerate(r['policies'].items()):
    ax.scatter(v['E'],v['T']/3600,s=80,marker=['o','s','^','D'][j],color=cols[j],label=f"{labels[key]}：{v['N']} 次")
ax.set(xlabel='总能耗 / kWh',ylabel='累计作业时间 / h');ax.margins(.25);ax.legend(loc='upper right',fontsize=8,frameon=False);ax.grid(alpha=.2)
save(fig,'result_q1_tradeoff')

fig,(ax,bx)=plt.subplots(2,1,figsize=(6.3,4.8),layout='constrained',sharex=True)
ss=r['sensitivity'];xx=[v['rho']*100 for v in ss]
ax.step(xx,[v['N'] if v['feasible'] else np.nan for v in ss],where='post',color=cols[0]);ax.set(ylabel='最少架次数 / 次')
for gid,c,ls in zip(models,cols,('-','--','-.')):
    seq=[v for v in r['sensitivity_capacities'] if v['area']==sid and v['model']==gid]
    bx.plot([v['rho']*100 for v in seq],[v['max_safe_kg'] if v['max_safe_kg'] is not None else np.nan for v in seq],c=c,ls=ls,label=f'{sid} / {gid} 型')
bx.set(xlabel='返航安全能量余量 / %',ylabel='最大安全载荷 / kg');bx.legend(frameon=False,fontsize=8)
for a in (ax,bx):a.axvline(20,color='#777777',ls=':',lw=1);a.grid(alpha=.2)
save(fig,'result_q1_reserve')

def flow(name,labels):
    fig,ax=plt.subplots(figsize=(6.3,2.3),layout='constrained');ax.set_xlim(0,10);ax.set_ylim(0,3);ax.axis('off')
    for j,label in enumerate(labels):
        row=j//3;col=j%3;x=.1+col*3.35;y=1.8-row*1.45
        ax.add_patch(FancyBboxPatch((x,y),3,1,boxstyle='round,pad=0.03,rounding_size=0.07',fc='#EEF5FA',ec=cols[0],lw=1))
        ax.text(x+1.5,y+.5,label,ha='center',va='center',fontsize=9)
        if col<2:ax.annotate('',xy=(x+3.3,y+.5),xytext=(x+3,y+.5),arrowprops=dict(arrowstyle='->',color='#444444'))
    ax.annotate('',xy=(1.6,1.4),xytext=(8.3,1.75),arrowprops=dict(arrowstyle='->',color='#444444',connectionstyle='angle,angleA=-90,angleB=90,rad=10'))
    save(fig,name)
flow('flow_overall_model',['输入核对\nDEM、节点、货箱、机型','物理计算\n航高、能量、作业时间','连续能力\n最大安全载荷','离散组批\n可行模式与动态规划','方案验证\n逐箱约束与整数规划','方案解释\n目标权衡与余量敏感性'])
flow('flow_q1_model',['按服务区提取需求\n四类货箱计数','枚举装载计数组合\n检验质量、体积、能量','状态：尚未配送数量\n零状态费用为零','递推比较三维目标\n保存最优模式与前驱','回溯组批及箱号\n合并15个服务区方案','交叉核对优化结果\n输出逐架次清单'])
(QA/'layout_audit.json').write_text(json.dumps(audits,ensure_ascii=False,indent=2),encoding='utf-8')
thumbs=[]
for p in sorted(QA.glob('*.png')):
    if p.stem.endswith('_gray'):continue
    im=Image.open(p).convert('RGB');im.thumbnail((504,390));tile=Image.new('RGB',(520,420),'white');tile.paste(im,((520-im.width)//2,24));ImageDraw.Draw(tile).text((8,5),p.stem,fill='black');thumbs.append(tile)
sheet=Image.new('RGB',(1040,420*((len(thumbs)+1)//2)),'white')
for i,im in enumerate(thumbs):sheet.paste(im,((i%2)*520,(i//2)*420))
sheet.save(QA/'contact_sheet.png')
print(json.dumps(audits,ensure_ascii=False))
