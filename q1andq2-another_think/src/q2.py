"""候选路线集合分割 + 双资源可选区间 CP-SAT 联合调度。

候选池有限：求解器下界仅适用于该候选池和整数秒模型，不能称全局最优。
"""
import math
import json
import time
from itertools import combinations, permutations
from collections import defaultdict
import numpy as np
from ortools.sat.python import cp_model
from core import Data, RESULTS, ROOT, dump, csv

def key(r): return (r['g'],tuple(r['boxes']),tuple(r['order']))

def make_pool(data,q1routes,seed=20260923,rounds=55):
    rng=np.random.default_rng(seed); pool={}
    def add(r):
        if r and r['latest_start']>=0: pool[key(r)]=r
    for r in q1routes: add(r)
    for ids in ([b] for b in data.boxes):
        for g in 'ABC': add(data.route(g,ids))
    # 全部同服务区双箱组合，为轻型机保留有竞争力的基本列。
    for s in data.sites:
        for bs in combinations(data.by_site[s],2):
            for g in 'ABC': add(data.route(g,[b.id for b in bs]))
    # 多次随机受限候选表构造。每次产生一个完整组批分割。
    for mode in ['direct','multi']:
        for trial in range(rounds):
            remaining=set(data.boxes)
            while remaining:
                first=min(sorted(remaining),key=lambda i:(data.boxes[i].hard if math.isfinite(data.boxes[i].hard) else data.boxes[i].desired)+rng.uniform(0,2000))
                g=str(rng.choice(list('ABC'),p=[0.22,0.28,0.50])); chosen=[first]; order=[data.boxes[first].site]
                r=data.route(g,chosen,order)
                if r is None: raise RuntimeError('Singleton infeasible')
                target=int(rng.integers(2,10)) if g=='C' else 2
                while len(chosen)<target:
                    candidates=[]
                    for b in sorted(remaining-set(chosen)):
                        s=data.boxes[b].site
                        if mode=='direct' and s!=order[0]: continue
                        if s not in order and len(order)>=3: continue
                        variants=[order] if s in order else [order[:i]+[s]+order[i:] for i in range(len(order)+1)]
                        best=None
                        for oo in variants:
                            nr=data.route(g,chosen+[b],oo)
                            if nr is None or nr['latest_start']<0: continue
                            # 优先减少额外飞行/交接时间，也计入新增箱等待和能耗。
                            score=(nr['duration']-r['duration'])+120*(nr['energy']-r['energy'])
                            score+=0.02*max(0,data.boxes[b].desired-3600)
                            if best is None or score<best[0]: best=(score,nr)
                        if best: candidates.append(best)
                    if not candidates: break
                    candidates.sort(key=lambda x:x[0]); pick=candidates[int(rng.integers(min(4,len(candidates))))]
                    r=pick[1];chosen=r['boxes'];order=r['order'];add(r)
                add(r); remaining-=set(chosen)
    # 不同机型可执行同一组批，允许优化器联合选择机型。
    snapshot=list(pool.values())
    for r in snapshot:
        for g in 'ABC': add(data.route(g,r['boxes'],r['order']))
    routes=sorted(pool.values(),key=key)
    dump(RESULTS/'q2/candidate_pool.json',routes)
    print('Q2 candidate pool',len(routes),'multi',sum(len(r['order'])>1 for r in routes),flush=True)
    return routes

def color_resources(data,items):
    for g in 'ABC':
        for field,ids,endfield in [('drone',data.units[g],'reserved_return'),('battery',[f'{g}-BAT-{i+1:02}' for i in range(data.drones[g].batteries)],'battery_ready')]:
            ready={u:0. for u in ids}
            for r in sorted((r for r in items if r['g']==g),key=lambda r:(r['start'],r['id'])):
                avail=[u for u in ids if ready[u]<=r['start']+1e-7]
                if not avail: raise RuntimeError(f'Interval coloring failed: {field} {g}')
                u=min(avail,key=lambda u:(ready[u],u));r[field]=u;ready[u]=r[endfield]
    return items

def summarize(data,items):
    deliveries={b:r['start']+off for r in items for b,off in r['completion'].items()}
    priorities=sum(b.priority for b in data.boxes.values())
    return dict(sorties=len(items),multi_stop_sorties=sum(len(r['order'])>1 for r in items),
        makespan_s=max(r['return'] for r in items),energy_kwh=sum(r['energy'] for r in items),
        operation_s=sum(r['duration'] for r in items),
        weighted_mean_delivery_s=sum(data.boxes[b].priority*t for b,t in deliveries.items())/priorities,
        weighted_tardiness_s=sum(data.boxes[b].priority*max(0,t-data.boxes[b].desired) for b,t in deliveries.items()),
        late_boxes=sum(t>data.boxes[b].desired+1e-6 for b,t in deliveries.items()),
        hard_violations=sum(t>data.boxes[b].hard+1e-6 for b,t in deliveries.items()),
        min_return_soc=min(r['soc'] for r in items),
        min_hard_slack_s=min(data.boxes[b].hard-t for b,t in deliveries.items() if math.isfinite(data.boxes[b].hard)),
        A=sum(r['g']=='A' for r in items),B=sum(r['g']=='B' for r in items),C=sum(r['g']=='C' for r in items))

PROFILES={
    'balanced':dict(makespan=100,completion=1,tardiness=100,wh=10,sorties=10000),
    'fast':dict(makespan=400,completion=2,tardiness=100,wh=2,sorties=2000),
    'energy':dict(makespan=30,completion=1,tardiness=100,wh=45,sorties=10000),
    'few_sorties':dict(makespan=40,completion=1,tardiness=100,wh=5,sorties=150000)}

class History(cp_model.CpSolverSolutionCallback):
    def __init__(self,path): super().__init__();self.path=path;self.rows=[]
    def on_solution_callback(self):
        self.rows.append(dict(wall_s=self.wall_time,objective=self.objective_value,bound=self.best_objective_bound))

def optimize(data,pool,name,profile='balanced',seconds=60,seed=23,hint=None,battery_limits=None,fixed=False):
    model=cp_model.CpModel(); horizon=24000
    starts=[]; selects=[]; intervals=defaultdict(list); bi=defaultdict(list); bybox=defaultdict(list)
    w=PROFILES[profile];cost=[]; ends=[]
    completion={b:model.new_int_var(0,horizon,'completion_'+b) for b in data.boxes}
    tardiness={b:model.new_int_var(0,horizon,'tardiness_'+b) for b in data.boxes}
    for b,box in data.boxes.items():
        model.add(tardiness[b]>=completion[b]-int(box.desired))
        if math.isfinite(box.hard): model.add(completion[b]<=int(box.hard))
        cost.append(int(box.priority)*(w['completion']*completion[b]+w['tardiness']*tardiness[b]))
    for k,r in enumerate(pool):
        latest=min(horizon-math.ceil(r['duration']),math.floor(r['latest_start']) if math.isfinite(r['latest_start']) else horizon)
        if latest<0: raise ValueError('Infeasible candidate')
        s=model.new_int_var(0,latest,f's{k}'); y=model.new_bool_var(f'y{k}')
        if fixed: model.add(y==1)
        model.add(s==0).only_enforce_if(y.Not())
        dur=math.ceil(r['duration']);bdur=math.ceil(r['duration']+r['charge'])
        intervals[r['g']].append(model.new_optional_fixed_size_interval_var(s,dur,y,f'I{k}'))
        bi[r['g']].append(model.new_optional_fixed_size_interval_var(s,bdur,y,f'B{k}'))
        end=model.new_int_var(0,horizon,f'e{k}')
        model.add(end==s+dur).only_enforce_if(y);model.add(end==0).only_enforce_if(y.Not());ends.append(end)
        for b,off in r['completion'].items():
            bybox[b].append(y);model.add(completion[b]==s+math.ceil(off)).only_enforce_if(y)
        starts.append(s);selects.append(y)
        cost.append((w['wh']*round(r['energy']*1000)+w['sorties'])*y)
    for b in data.boxes: model.add_exactly_one(bybox[b])
    for g,d in data.drones.items():
        model.add_cumulative(intervals[g],[1]*len(intervals[g]),d.count)
        model.add_cumulative(bi[g],[1]*len(bi[g]),(battery_limits or {}).get(g,d.batteries))
    cmax=model.new_int_var(0,horizon,'Cmax');model.add_max_equality(cmax,ends);cost.append(w['makespan']*cmax)
    model.minimize(sum(cost))
    if hint:
        lookup={key(r):r for r in hint}
        for r,s,y in zip(pool,starts,selects):
            h=lookup.get(key(r)); model.add_hint(y,int(h is not None));model.add_hint(s,int(h['start']) if h else 0)
        for b in data.boxes:
            rr=next(r for r in hint if b in r['boxes']);c=int(rr['start'])+math.ceil(rr['completion'][b])
            model.add_hint(completion[b],c);model.add_hint(tardiness[b],max(0,c-int(data.boxes[b].desired)))
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=seconds
    solver.parameters.num_search_workers=8;solver.parameters.random_seed=seed
    history=History(name);t0=time.perf_counter();status=solver.solve(model,history)
    stats=dict(name=name,profile=profile,weights=w,status=solver.status_name(status),wall_s=time.perf_counter()-t0,
        candidate_count=len(pool),seed=seed,threads=8,time_limit_s=seconds,best_bound=solver.best_objective_bound,
        scope='restricted candidate pool, integer-second conservative intervals')
    items=[]
    if status in [cp_model.OPTIMAL,cp_model.FEASIBLE]:
        for r,s,y in zip(pool,starts,selects):
            if solver.value(y):
                st=solver.value(s)
                items.append(dict(r,start=st,**{'return':st+r['duration']},reserved_return=st+math.ceil(r['duration']),
                                  battery_ready=st+math.ceil(r['duration']+r['charge'])))
        items.sort(key=lambda r:(r['start'],r['g'],r['boxes']))
        for i,r in enumerate(items): r['id']=f'Q2-{i+1:03}'
        if battery_limits is None: color_resources(data,items)
        stats.update(summarize(data,items));stats['objective']=solver.objective_value
        stats['relative_gap']=(solver.objective_value-solver.best_objective_bound)/max(1,abs(solver.objective_value))
    dump(RESULTS/f'q2/{name}/schedule.json',items);dump(RESULTS/f'q2/{name}/summary.json',stats)
    csv(f'q2/{name}/convergence.csv',history.rows)
    (RESULTS/f'q2/{name}/solver_response.txt').write_text(solver.response_stats(),encoding='utf-8')
    print('Q2',name,stats,flush=True)
    return items,stats

def export(data,items):
    csv('q2/selected/sorties.csv',[dict(sortie=r['id'],drone=r['drone'],model=r['g'],battery=r['battery'],start_s=r['start'],
        takeoff_s=r['start']+data.drones[r['g']].prep+len(r['boxes'])*data.drones[r['g']].load,
        route='O01>'+'>'.join(r['order'])+'>O01',return_s=r['return'],energy_kwh=r['energy'],soc=r['soc'],
        mass_kg=r['mass'],volume_m3=r['volume'],boxes=';'.join(r['boxes'])) for r in items])
    csv('q2/selected/deliveries.csv',[dict(box=b,sortie=r['id'],site=data.boxes[b].site,category=data.boxes[b].category,
        delivered_s=r['start']+v,desired_s=data.boxes[b].desired,hard_s=data.boxes[b].hard,
        lateness_s=max(0,r['start']+v-data.boxes[b].desired),priority=data.boxes[b].priority) for r in items for b,v in r['completion'].items()])
    csv('q2/selected/batteries.csv',[dict(battery=r['battery'],sortie=r['id'],model=r['g'],start_s=r['start'],return_s=r['return'],
        soc_start=1,soc_return=r['soc'],charge_start_s=r['return'],charge_end_s=r['return']+r['charge'],
        ready_reserved_s=r['battery_ready'],charge_duration_s=r['charge']) for r in items])
    csv('q2/selected/legs.csv',[dict(sortie=r['id'],model=r['g'],origin=l['origin'],destination=l['destination'],
        load_kg=l['load'],start_s=r['start']+l['start_offset'],end_s=r['start']+l['end_offset'],energy_kwh=l['energy'],
        **{k:v for k,v in data.legs[l['origin'],l['destination']].items() if k not in ['origin','destination']}) for r in items for l in r['legs']])

def run(data,seconds=60):
    q1routes=json.loads((RESULTS/'q1/routes.json').read_text(encoding='utf-8'))
    initial,base=optimize(data,q1routes,'fixed_q1',seconds=15,fixed=True)
    pool=make_pool(data,q1routes)
    direct=[r for r in pool if len(r['order'])==1]
    directsol,directstat=optimize(data,direct,'direct_optimized',seconds=seconds,hint=initial)
    balanced,balstat=optimize(data,pool,'multi_balanced',seconds=seconds,hint=directsol)
    solutions=[(directsol,directstat),(balanced,balstat)]; comparisons=[base,directstat,balstat]
    for profile in ['fast','energy','few_sorties']:
        sol,stat=optimize(data,pool,'multi_'+profile,profile,seconds,hint=balanced or directsol)
        comparisons.append(stat);solutions.append((sol,stat))
    # 不同种子给出搜索波动，不能用单次运行宣称稳定优势。
    for seed in [41,97]:
        sol,stat=optimize(data,pool,f'multi_balanced_seed{seed}','balanced',seconds,seed,hint=balanced or directsol)
        comparisons.append(stat);solutions.append((sol,stat))
    candidates=[(sol,st) for sol,st in solutions if sol and st['profile']=='balanced']
    chosen,st=min(candidates,key=lambda ss:ss[1]['objective'])
    dump(RESULTS/'q2/selected/schedule.json',chosen);dump(RESULTS/'q2/selected/summary.json',st);export(data,chosen)
    csv('q2/experiment_comparison.csv',comparisons)
    return chosen

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,default=60);a=p.parse_args()
    run(Data(),a.seconds)
