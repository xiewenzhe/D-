"""同品类计数状态压缩 + 完全可行模式枚举 + 精确动态规划。"""
from itertools import product
from functools import lru_cache
import time
from core import Data, RESULTS, csv, dump

def patterns(data,site,reserve):
    groups={}
    for b in data.by_site[site]: groups.setdefault((b.category,b.mass,b.volume),[]).append(b.id)
    groups=list(groups.values()); counts=tuple(map(len,groups)); pool=[]
    for cnt in product(*(range(n+1) for n in counts)):
        if not sum(cnt): continue
        ids=[b for group,n in zip(groups,cnt) for b in group[:n]]
        for g in 'ABC':
            route=data.route(g,ids,[site],reserve)
            if route: pool.append((cnt,route))
    return groups,counts,pool

def solve_site(data,site,reserve=0.2,objective='lex',weights=None):
    groups,counts,pool=patterns(data,site,reserve)
    def cost(r):
        n,e,t=1,r['energy'],r['duration']
        if objective=='lex': return (n,e,t)
        if objective=='energy': return (e,n,t)
        if objective=='time': return (t,n,e)
        return (weights[0]*n+weights[1]*e+weights[2]*t/3600,n,e,t)
    @lru_cache(None)
    def dp(state):
        if not sum(state): return ((0.,)*len(cost(pool[0][1])),())
        first=next(i for i,n in enumerate(state) if n)
        best=None
        for j,(cnt,r) in enumerate(pool):
            if cnt[first]==0 or any(a>b for a,b in zip(cnt,state)): continue
            residual=tuple(b-a for a,b in zip(cnt,state)); tail=dp(residual)
            if tail is None: continue
            value=tuple(a+b for a,b in zip(cost(r),tail[0]))
            if best is None or value<best[0]: best=(value,(j,)+tail[1])
        return best
    result=dp(counts)
    if result is None: return None,dict(site=site,patterns=len(pool),feasible=False)
    allocated=[0]*len(groups); routes=[]
    for j in result[1]:
        cnt,r=pool[j]; ids=[]
        for k,n in enumerate(cnt):
            ids.extend(groups[k][allocated[k]:allocated[k]+n]); allocated[k]+=n
        routes.append(data.route(r['g'],ids,[site],reserve))
    return routes,dict(site=site,patterns=len(pool),states=dp.cache_info().currsize,feasible=True)

def solve(data,reserve=0.2,objective='lex',weights=None):
    routes=[]; stats=[]
    for s in data.sites:
        r,stat=solve_site(data,s,reserve,objective,weights); stats.append(stat)
        if r is None: return None,stats
        routes+=r
    return routes,stats

def metrics(routes):
    if routes is None: return dict(feasible=False)
    return dict(feasible=True,sorties=len(routes),energy_kwh=sum(r['energy'] for r in routes),
        total_operation_s=sum(r['duration'] for r in routes),flight_s=sum(r['flight'] for r in routes),
        A=sum(r['g']=='A' for r in routes),B=sum(r['g']=='B' for r in routes),C=sum(r['g']=='C' for r in routes))

def run(data):
    begin=time.perf_counter(); routes,stats=solve(data)
    dump(RESULTS/'q1/routes.json',routes); dump(RESULTS/'q1/exact_dp_certificate.json',stats)
    csv('q1/batches.csv',[dict(sortie=f'Q1-{i+1:03}',site=r['order'][0],model=r['g'],boxes=';'.join(r['boxes']),
        mass_kg=r['mass'],volume_m3=r['volume'],flight_s=r['flight'],operation_s=r['duration'],energy_kwh=r['energy'],soc=r['soc']) for i,r in enumerate(routes)])
    payload=[dict(site=s,model=g,reserve=rho,safe_payload_kg=data.safe_payload(g,s,rho)) for rho in [0.1,0.15,0.2,0.25,0.3,0.35,0.4] for s in data.sites for g in 'ABC']
    csv('q1/safe_payload_sensitivity.csv',payload)
    sensitivity=[]
    for rho in [0.1,0.15,0.2,0.25,0.3,0.35,0.4]:
        rr,_=solve(data,rho); sensitivity.append(dict(reserve=rho,**metrics(rr)))
    csv('q1/reserve_sensitivity.csv',sensitivity)
    comparisons=[]
    for obj in ['lex','energy','time']:
        rr,_=solve(data,objective=obj); comparisons.append(dict(objective=obj,**metrics(rr)))
        dump(RESULTS/f'q1/{obj}_routes.json',rr)
    for w in [(1,0.1,0.1),(1,1,1),(0.2,1,0.2),(0.2,0.2,1),(0.05,1,2)]:
        rr,_=solve(data,objective='weighted',weights=w)
        comparisons.append(dict(objective='weighted_'+str(w),**metrics(rr)))
    csv('q1/objective_comparison.csv',comparisons)
    summary=dict(**metrics(routes),runtime_s=time.perf_counter()-begin)
    dump(RESULTS/'q1/summary.json',summary); print('Q1',summary,flush=True)
    return routes

if __name__=='__main__': run(Data())
