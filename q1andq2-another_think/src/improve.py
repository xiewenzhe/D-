"""地理邻域破坏修复：保留可行解，在小候选子问题内联合改组与重排。

每个邻域仍用 CP-SAT 精确建模；有限运行时间仅得到改进可行解。
"""
import json
from itertools import permutations,combinations
import numpy as np
from core import Data,RESULTS,dump,csv
from q2 import optimize,key,export,PROFILES

def objective(data,rs,profile='balanced'):
    w=PROFILES[profile]
    value=w['makespan']*max(r['start']+int(np.ceil(r['duration'])) for r in rs)
    for r in rs:
        value+=w['wh']*round(r['energy']*1000)+w['sorties']
        for b,t in r['completion'].items():
            c=r['start']+int(np.ceil(t));box=data.boxes[b]
            value+=box.priority*(w['completion']*c+w['tardiness']*max(0,c-box.desired))
    return value

def run(data,iterations=18,seconds=6):
    pool=json.loads((RESULTS/'q2/candidate_pool.json').read_text(encoding='utf-8'))
    summaries=[];best_multi=None
    for mode in ['direct','multi']:
        initial=json.loads((RESULTS/'q2/direct_optimized/schedule.json').read_text(encoding='utf-8'))
        incumbent=initial;incvalue=objective(data,incumbent);rng=np.random.default_rng(20260923)
        history=[]
        for it in range(iterations):
            anchor=incumbent[int(rng.integers(len(incumbent)))]['order'][0]
            # 地理邻近 + 少量随机远处架次，避免邻域永远封闭。
            scores=[]
            for r in incumbent:
                dist=min(0 if anchor==s else data.legs[anchor,s]['distance'] for s in r['order'])
                scores.append(dist+rng.uniform(0,3000))
            count=min(len(incumbent),int(rng.integers(5,9)))
            selected=np.argsort(scores)[:count]
            destroyed=[incumbent[int(j)] for j in selected];boxes={b for r in destroyed for b in r['boxes']}
            candidates={key(r):r for r in incumbent}
            for r in pool:
                if mode=='direct' and len(r['order'])>1:continue
                if set(r['boxes']).issubset(boxes):candidates[key(r)]=r
            # 精确合并两个已有架次，补足随机候选池中未出现的可行组合。
            for r1,r2 in combinations(destroyed,2):
                ids=r1['boxes']+r2['boxes'];sites=sorted(set(r1['order']+r2['order']))
                if len(sites)>(1 if mode=='direct' else 3):continue
                for g in 'ABC':
                    for order in permutations(sites):
                        r=data.route(g,ids,order)
                        if r and r['latest_start']>=0:candidates[key(r)]=r
            name=f'lns_{mode}_{it:02}'
            sol,st=optimize(data,list(candidates.values()),name,seconds=seconds,seed=it+100,hint=incumbent)
            accepted=bool(sol) and st['objective']<incvalue-0.1
            if accepted:incumbent=sol;incvalue=st['objective']
            history.append(dict(iteration=it,mode=mode,accepted=accepted,incumbent_objective=incvalue,
                candidate_count=len(candidates),destroyed_routes=count,solver_wall_s=st['wall_s'],
                makespan_s=max(r['return'] for r in incumbent),energy_kwh=sum(r['energy'] for r in incumbent),
                sorties=len(incumbent),multi_stop_sorties=sum(len(r['order'])>1 for r in incumbent)))
        from q2 import summarize
        st=dict(name=f'lns_{mode}',profile='balanced',objective=incvalue,**summarize(data,incumbent),
                iterations=iterations,per_iteration_seconds=seconds,seed=20260923,
                status='HEURISTIC_FEASIBLE',global_bound=None,weights=PROFILES['balanced'])
        dump(RESULTS/f'q2/lns_{mode}/schedule.json',incumbent);dump(RESULTS/f'q2/lns_{mode}/summary.json',st)
        csv(f'q2/lns_{mode}/history.csv',history);summaries.append(st)
        if mode=='multi':best_multi=incumbent
    old=json.loads((RESULTS/'q2/selected/schedule.json').read_text(encoding='utf-8'))
    candidates=[old,best_multi,json.loads((RESULTS/'q2/lns_direct/schedule.json').read_text(encoding='utf-8'))]
    chosen=min(candidates,key=lambda rs:objective(data,rs))
    name='lns_multi' if chosen is best_multi else ('lns_direct' if chosen is candidates[-1] else 'previous_best')
    from q2 import summarize
    st=dict(name=name,profile='balanced',objective=objective(data,chosen),**summarize(data,chosen),status='HEURISTIC_FEASIBLE',
        global_bound=None,weights=PROFILES['balanced'])
    dump(RESULTS/'q2/selected/schedule.json',chosen);dump(RESULTS/'q2/selected/summary.json',st);export(data,chosen)
    csv('q2/lns_comparison.csv',summaries)
    return chosen

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--iterations',type=int,default=18);p.add_argument('--seconds',type=float,default=6)
    args=p.parse_args();run(Data(),args.iterations,args.seconds)
