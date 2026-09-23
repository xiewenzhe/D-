"""Independent geometric checks and a complete small-instance dispatch benchmark."""
from __future__ import annotations
import math
import random
from itertools import permutations
from time import perf_counter
import numpy as np
from common import distance_m,charge_seconds
import problem2
from continuous_validation import swept_clear,distance_upper,breakpoints
from problem3 import transport_position,los_obstructed_exact


def geometric_checks():
    class Grid:
        grid=np.zeros((6,6))
        def rc(self,lon,lat): return lat,lon
        def cells(self,lon1,lat1,lon2,lat2):
            return [(r,c) for r in range(6) for c in range(6)]
    terrain=Grid()
    a0={"lon":0.5,"lat":0.5,"z":10.0}
    a1={"lon":4.5,"lat":0.5,"z":10.0}
    b={"lon":2.5,"lat":4.5,"z":10.0}
    assert swept_clear(a0,a1,b,terrain)[0]
    terrain.grid[2,2]=20
    assert not los_obstructed_exact(a0,b,terrain)
    assert not los_obstructed_exact(a1,b,terrain)
    assert not swept_clear(a0,a1,b,terrain)[0]
    midpoint={k:(a0[k]+a1[k])/2 for k in a0}
    assert los_obstructed_exact(midpoint,b,terrain)
    rng=random.Random(619)
    checks=0
    for _ in range(1000):
        p0={"lon":108+rng.random()*.2,"lat":22+rng.random()*.2,"z":rng.random()*1000}
        p1={"lon":108+rng.random()*.2,"lat":22+rng.random()*.2,"z":rng.random()*1000}
        target={"lon":108+rng.random()*.2,"lat":22+rng.random()*.2,"z":rng.random()*1000}
        upper=distance_upper(p0,p1,target)
        for j in range(11):
            p={k:p0[k]+j/10*(p1[k]-p0[k]) for k in p0}
            actual=math.hypot(distance_m(p,target),p["z"]-target["z"])
            assert actual<=upper
            checks+=1
    clear_checks=0
    for _ in range(100):
        terrain.grid=rng.random()*np.ones((6,6))*8
        points=[{"lon":0.2+rng.random()*5.5,"lat":0.2+rng.random()*5.5,
                 "z":9+rng.random()*20} for _ in range(3)]
        assert swept_clear(*points,terrain)[0]
        for j in range(21):
            p={k:points[0][k]+j/20*(points[1][k]-points[0][k]) for k in points[0]}
            assert not los_obstructed_exact(p,points[2],terrain)
            clear_checks+=1
    return {"passed":True,"ridge_inside_swept_triangle_detected":True,
            "endpoint_only_los_adversarial_case":True,
            "distance_bound_point_checks":checks,"swept_clearance_point_checks":clear_checks}


def affine_checks(schedule,missions,physics,models):
    count=0
    for route in schedule:
        points=breakpoints(route,missions,physics,models,30)
        for left,right in zip(points,points[1:]):
            a=transport_position(route,left,physics,models)
            b=transport_position(route,right,physics,models)
            for fraction in (.25,.5,.75):
                p=transport_position(route,left+(right-left)*fraction,physics,models)
                assert abs(p["lon"]-(a["lon"]+fraction*(b["lon"]-a["lon"])))<1e-8
                assert abs(p["lat"]-(a["lat"]+fraction*(b["lat"]-a["lat"])))<1e-8
                assert abs(p["z"]-(a["z"]+fraction*(b["z"]-a["z"])))<1e-5
                count+=1
    return {"passed":True,"affine_interpolation_checks":count}


def small_exact_benchmark(boxes,models,batteries,physics):
    begin=perf_counter()
    ids=[f"{a}-WAT-{j:02d}" for a in ("S001","S006") for j in (1,2,3)]
    data={i:dict(boxes[i],deadline=None,first=False) for i in ids}
    model={"B":models["B"]}
    drones={"B-test":"B"}
    stock={"B":dict(batteries["B"],count=1)}
    options={}
    n=len(ids)
    for mask in range(1,1<<n):
        subset={ids[j]:data[ids[j]] for j in range(n) if mask>>j&1}
        areas=sorted({b["area"] for b in subset.values()})
        choices=[]
        for order in permutations(areas):
            p=physics.evaluate_route(model["B"],subset,order)
            if p is not None:
                choices.append(p)
        if choices: options[mask]=choices
    best=None
    examined=leaves=0
    def dfs(remaining,start,records,tardy,energy):
        nonlocal best,examined,leaves
        if best is not None and tardy>best[0][0]:
            return
        if remaining==0:
            leaves+=1
            score=(tardy,records[-1]["end"],energy,len(records))
            if best is None or score<best[0]:
                best=(score,records)
            return
        for mask,plans in options.items():
            if mask&remaining!=mask: continue
            for p in plans:
                examined+=1
                end=start+p["duration"]
                delivered={i:start+t for i,t in p["delivery_offsets"].items()}
                delay=sum(data[i]["priority"]*max(0,t-data[i]["desired"]) for i,t in delivered.items())
                ready=end+charge_seconds(p["soc"],stock["B"]["full_charge"])
                record={**p,"sortie":f"EX-{len(records)+1:03d}","drone":"B-test","model":"B",
                        "battery":"B01","start":start,"end":end,"battery_ready":ready,
                        "delivery":delivered,"class":"regular"}
                dfs(remaining^mask,ready,records+[record],tardy+delay,energy+p["energy"])
    dfs((1<<n)-1,0,[],0,0)
    checked=problem2.validate(best[1],data,model,drones,stock,physics)
    assert all(abs(a-b)<1e-6 for a,b in zip(best[0],problem2.objective(checked)))
    batches=[{"boxes":[i],"order":[data[i]["area"]],"class":"regular"} for i in ids]
    trials=[]
    for seed in range(15):
        s=problem2.assign(batches,data,model,drones,stock,physics,seed)
        m=problem2.validate(s,data,model,drones,stock,physics)
        trials.append((problem2.objective(m),s,m))
    _,s,m=min(trials,key=lambda x:x[0])
    baseline=problem2.objective(m)
    s,m,_,local=problem2.improve(s,m,batches,data,model,drones,stock,physics,
                                rounds=4,limit=60,seeds=(0,1,2))
    score=problem2.objective(m)
    assert score[0]>=best[0][0]-1e-6
    return {"scope":"derived six-water-box instance, two areas, one B drone and one B battery; first-batch deadlines removed",
            "boxes":ids,"global_optimum_score":best[0],"singleton_multistart_score":baseline,
            "local_search_score":score,"weighted_tardiness_gap_s":score[0]-best[0][0],
            "complete_schedules_examined":leaves,"route_extensions_examined":examined,
            "exact_schedule":best[1],"local_search":local,
            "elapsed_s":perf_counter()-begin,"validation":{"passed":True,"violations":[]}}
