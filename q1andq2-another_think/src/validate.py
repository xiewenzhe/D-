"""独立回放已导出的方案，核对逐箱、能耗、时限和资源区间。

不用 route() 计算结果作真值：从清单、航段几何、机型参数重新计算。
"""
import json
import math
from collections import Counter, defaultdict
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from core import Data, RESULTS, dump, csv
from q1 import patterns

def replay(data,r):
    g=data.drones[r['g']];bs=[data.boxes[i] for i in r['boxes']]
    q=sum(b.mass for b in bs);volume=sum(b.volume for b in bs)
    t=g.prep+g.load*len(bs);E=0.;deliveries={}
    assert q<=g.capacity+1e-8 and volume<=g.volume+1e-8
    seq=['O01']+r['order']+['O01']
    assert len(set(r['order']))==len(r['order'])
    assert set(r['order'])=={b.site for b in bs}
    for a,b in zip(seq[:-1],seq[1:]):
        geo=data.legs[a,b]
        L=g.range0-(g.range0-g.rangeF)*math.pow(q/g.capacity,1.5)
        E+=g.battery*geo['distance']/L+(g.mass+q)*9.81*geo['climb']/g.efficiency/3600000
        t+=geo['climb']/g.up+geo['distance']/g.speed+geo['descent']/g.down
        deliveries_here=[x for x in bs if x.site==b]
        if b!='O01':
            t+=g.service+g.unload*len(deliveries_here)
            for box in deliveries_here: deliveries[box.id]=t
            q-=sum(box.mass for box in deliveries_here)
    assert q==0
    assert E<=(1-g.reserve)*g.battery+1e-8
    assert abs(E-r['energy'])<1e-8 and abs(t-r['duration'])<1e-7
    assert all(abs(deliveries[b]-r['completion'][b])<1e-7 for b in deliveries)
    return E,t,deliveries

def validate_q1(data):
    routes=json.loads((RESULTS/'q1/routes.json').read_text(encoding='utf-8'))
    allids=[b for r in routes for b in r['boxes']]
    assert Counter(allids)==Counter(data.boxes.keys())
    for r in routes:
        assert len(r['order'])==1;replay(data,r)
    # 用另一种算法 MILP 独立验证最小架次数，以及固定该架次数后的最小能耗。
    checks=[]
    for s in data.sites:
        groups,counts,pool=patterns(data,s,0.2)
        A=np.array([cnt for cnt,r in pool],dtype=float).T
        one=np.ones(len(pool));energy=np.array([r['energy'] for cnt,r in pool])
        count=milp(one,integrality=one,bounds=Bounds(0,np.inf),constraints=LinearConstraint(A,counts,counts))
        assert count.success
        n=round(count.fun)
        Ae=np.vstack([A,one]);rhs=np.r_[counts,n]
        en=milp(energy,integrality=one,bounds=Bounds(0,np.inf),constraints=LinearConstraint(Ae,rhs,rhs),options={'mip_rel_gap':0.})
        rr=[r for r in routes if r['order']==[s]]
        assert en.success and n==len(rr) and abs(en.fun-sum(r['energy'] for r in rr))<1e-7
        checks.append(dict(site=s,min_sorties=n,energy_kwh=en.fun,milp_gap=en.mip_gap,pass_check=True))
    csv('validation/q1_milp_crosscheck.csv',checks)
    return dict(boxes=len(allids),sorties=len(routes),independent_milp_sites=len(checks),passed=True)

def validate_q2(data):
    rs=json.loads((RESULTS/'q2/selected/schedule.json').read_text(encoding='utf-8'))
    assert rs
    assert Counter(b for r in rs for b in r['boxes'])==Counter(data.boxes.keys())
    bydrone=defaultdict(list);bybattery=defaultdict(list);checks=[]
    for r in rs:
        E,t,delivery=replay(data,r);g=data.drones[r['g']]
        assert r['start']>=0 and abs(r['return']-r['start']-t)<1e-7
        assert r['drone'] in data.units[r['g']]
        assert r['battery'] in [f'{r["g"]}-BAT-{i+1:02}' for i in range(g.batteries)]
        soc=1-E/g.battery
        charge=g.charge_full*(.65*(.9-soc)/.9+.35) if soc<.9 else g.charge_full*.35*(1-soc)/.1
        assert abs(charge-r['charge'])<1e-7
        bydrone[r['drone']].append((r['start'],r['return'],r['id']))
        bybattery[r['battery']].append((r['start'],r['return']+charge,r['id']))
        for b,off in delivery.items():
            actual=r['start']+off;hard=data.boxes[b].hard
            assert actual<=hard+1e-7,(b,actual,hard)
            checks.append(dict(box=b,delivery_s=actual,hard_deadline_s=hard,hard_slack_s=hard-actual,passed=True))
    gaps=[]
    for kind,res in [('drone',bydrone),('battery',bybattery)]:
        for name,intervals in res.items():
            intervals.sort()
            for a,b in zip(intervals[:-1],intervals[1:]):
                gap=b[0]-a[1];assert gap>=-1e-7,(kind,name,a,b)
                gaps.append(dict(kind=kind,resource=name,previous=a[2],next=b[2],gap_s=gap,passed=True))
    csv('validation/q2_resource_gaps.csv',gaps);csv('validation/q2_box_checks.csv',checks)
    return dict(boxes=len(checks),sorties=len(rs),used_drones=len(bydrone),used_batteries=len(bybattery),
        checked_resource_transitions=len(gaps),hard_violations=0,energy_violations=0,resource_overlaps=0,passed=True)

def validate_geometry(data):
    comparisons=[]
    # 独立使用约 1 m 间距的密集采样检查最高地形；以边界遍历法为正式值。
    dx,_,ox,_,dy,oy=data.transform
    for (a,b),l in data.legs.items():
        if a>b: continue
        n1,n2=data.nodes[a],data.nodes[b];num=int(l['distance'])+2
        x=np.linspace(n1['lon'],n2['lon'],num);y=np.linspace(n1['lat'],n2['lat'],num)
        rr=np.floor((y-oy)/dy).astype(int);cc=np.floor((x-ox)/dx).astype(int)
        top=float(data.dem[rr,cc].max());diff=l['dem_max']-top
        assert diff>=-1e-7
        comparisons.append(dict(origin=a,destination=b,exact_max_m=l['dem_max'],dense_max_m=top,difference_m=diff))
    csv('validation/dem_dense_crosscheck.csv',comparisons)
    return dict(undirected_legs=len(comparisons),dense_disagreements=sum(x['difference_m']>1e-6 for x in comparisons),passed=True)

def run(data):
    result=dict(inputs=data.audit_inputs(),geometry=validate_geometry(data),q1=validate_q1(data),q2=validate_q2(data))
    dump(RESULTS/'validation/report.json',result);print('VALIDATION',result,flush=True);return result

if __name__=='__main__':run(Data())
