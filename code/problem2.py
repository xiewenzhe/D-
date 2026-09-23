"""Construct and schedule multi-stop transport sorties for Problem 2."""
from __future__ import annotations
from collections import defaultdict, Counter
import json
import math
import random
import time
import statistics
from itertools import permutations
from pathlib import Path
from common import ROOT, Physics, charge_seconds, EPS


def hard_due(b):
    return min([x for x in (b["deadline"], b["desired"] if b["kind"] == "MED" else None) if x is not None], default=None)


def route_orders(areas, physics):
    """Enumerate only the small, configured set of distinct stops."""
    areas = tuple(sorted(set(areas)))
    if not 1 <= len(areas) <= 4:
        raise ValueError("Candidate route must contain 1 to 4 service areas")
    return list(permutations(areas))




def choose_order(ids, boxes, models, physics):
    selected = {i: boxes[i] for i in ids}
    areas = sorted({b["area"] for b in selected.values()})
    options = []
    for order in route_orders(areas, physics):
        for model in models.values():
            plan = physics.evaluate_route(model, selected, order)
            if plan is not None:
                options.append((plan["energy"], plan["duration"], model["id"], order))
    if not options:
        return None
    return min(options)[3]


def make_batches(boxes, models, physics, cap_model=None, max_stops=2):
    """Build capacity-aware batches, inserting at most max_stops distinct areas."""
    if not 1 <= max_stops <= 4:
        raise ValueError("max_stops must be between 1 and 4")
    urgent = []
    residual = defaultdict(list)
    for area in sorted({b["area"] for b in boxes.values()}):
        bs = sorted((b for b in boxes.values() if b["area"] == area),
                    key=lambda b: (hard_due(b) if hard_due(b) is not None else math.inf,
                                   b["desired"] if b["desired"] is not None else math.inf,
                                   -b["priority"], b["id"]))
        first = [b["id"] for b in bs if b["kind"] == "MED" or b["first"]]
        assert first and choose_order(first, boxes, models, physics)
        urgent.append({"boxes": first, "order": [area], "class": "urgent"})
        residual[area] = [b["id"] for b in bs if b["id"] not in first]
    routes = urgent[:]
    c = cap_model if isinstance(cap_model, dict) else models[cap_model or "C"]
    def fits(ids):
        return (sum(boxes[i]["mass"] for i in ids) <= c["capacity"] + EPS
                and sum(boxes[i]["volume"] for i in ids) <= c["volume"] + EPS)
    while any(residual.values()):
        area = min((a for a in residual if residual[a]), key=lambda a: (len(residual[a]), a))
        ids = []
        for bid in residual[area]:
            if fits(ids + [bid]) and choose_order(ids + [bid], boxes, models, physics) is not None:
                ids.append(bid)
        if not ids:
            raise RuntimeError(f"No feasible residual box at {area}")
        visited = {area}
        while len(visited) < max_stops:
            options = []
            for other in (a for a in residual if a not in visited and residual[a]):
                trial = ids[:]
                for bid in residual[other]:
                    if fits(trial + [bid]) and choose_order(trial + [bid], boxes, models, physics) is not None:
                        trial.append(bid)
                if len(trial) > len(ids):
                    order = choose_order(trial, boxes, models, physics)
                    distance = min(physics.legs[v, other]["distance"] for v in visited)
                    options.append((-(len(trial) - len(ids)), distance, other, trial, order))
            if not options:
                break
            _, _, added, ids, order = min(options)
            visited.add(added)
        order = choose_order(ids, boxes, models, physics)
        assert order is not None and len(order) <= max_stops
        routes.append({"boxes": ids[:], "order": list(order), "class": "regular"})
        for bid in ids:
            residual[boxes[bid]["area"]].remove(bid)
    assert Counter(i for r in routes for i in r["boxes"]) == Counter({i: 1 for i in boxes})
    return routes




def route_due(route, boxes):
    return min((hard_due(boxes[i]) for i in route["boxes"] if hard_due(boxes[i]) is not None), default=math.inf)


def assign(routes, boxes, models, drones, batteries, physics, seed=0):
    rng = random.Random(seed)
    free_d = {did: 0.0 for did in drones}
    free_b = {g: {f"{g}{j:02d}": 0.0 for j in range(1, b["count"] + 1)} for g, b in batteries.items()}
    remaining = list(routes)
    scheduled = []
    while remaining:
        # Every urgent route is dispatched before regular routes with later due times.
        candidates = sorted(remaining, key=lambda r: (route_due(r, boxes),
                            min((boxes[i]["desired"] or math.inf) for i in r["boxes"]), rng.random()))[:8]
        options = []
        for route in candidates:
            selected = {i: boxes[i] for i in route["boxes"]}
            due = route_due(route, boxes)
            for order in route_orders(route["order"], physics):
                for g, model in models.items():
                    plan = physics.evaluate_route(model, selected, order)
                    if plan is None:
                        continue
                    for did in (d for d in drones if drones[d] == g):
                        bid = min(free_b[g], key=free_b[g].get)
                        start = max(free_d[did], free_b[g][bid])
                        delivery = {i: start + t for i, t in plan["delivery_offsets"].items()}
                        if any(delivery[i] > hard_due(boxes[i]) + EPS for i in route["boxes"] if hard_due(boxes[i]) is not None):
                            continue
                        tardy = sum(boxes[i]["priority"] * max(0, delivery[i] - boxes[i]["desired"])
                                    for i in route["boxes"] if boxes[i]["desired"] is not None)
                        finish = start + plan["duration"]
                        # Score is used for constructive search only; objective components remain separate in output.
                        score = (due, start,
                                 tardy / 1000 + 0.3 * finish + 60 * plan["energy"] - 70 * len(route["boxes"])
                                 + rng.random() * 30)
                        options.append((score, route, g, did, bid, start, plan, delivery))
        if not options:
            raise RuntimeError(f"No hard-deadline feasible dispatch, {len(remaining)} routes left")
        _, route, g, did, bid, start, plan, delivery = min(options, key=lambda x: x[0])
        finish = start + plan["duration"]
        free_d[did] = finish
        free_b[g][bid] = finish + charge_seconds(plan["soc"], batteries[g]["full_charge"])
        scheduled.append({"sortie": f"Q2-{len(scheduled)+1:03d}", "drone": did, "model": g,
                          "battery": bid, "start": start, "end": finish,
                          "battery_ready": free_b[g][bid], "order": plan["order"],
                          "boxes": plan["boxes"], "mass": plan["mass"], "volume": plan["volume"],
                          "energy": plan["energy"], "soc": plan["soc"], "duration": plan["duration"],
                          "delivery": delivery, "stages": plan["stages"], "class": route["class"]})
        remaining.remove(route)
    return scheduled


def validate(schedule, boxes, models, drones, batteries, physics):
    delivered = Counter(i for r in schedule for i in r["boxes"])
    assert delivered == Counter({i: 1 for i in boxes})
    delivery = {}
    for r in schedule:
        subset = {i: boxes[i] for i in r["boxes"]}
        assert drones[r["drone"]] == r["model"]
        p = physics.evaluate_route(models[r["model"]], subset, tuple(r["order"]))
        assert p is not None
        flights = [stage for stage in r["stages"] if stage["kind"] == "flight"]
        assert flights and flights[0]["from"] == "O01" and flights[-1]["to"] == "O01"
        assert r["stages"] == p["stages"]
        assert r["battery"].startswith(r["model"])
        assert abs(r["end"] - r["start"] - p["duration"]) < 1e-6
        assert abs(r["energy"] - p["energy"]) < 1e-7
        assert r["soc"] + EPS >= models[r["model"]]["reserve_pct"] / 100
        for i, offset in p["delivery_offsets"].items():
            t = r["start"] + offset
            assert abs(r["delivery"][i] - t) < 1e-6
            due = hard_due(boxes[i])
            if due is not None:
                assert t <= due + EPS, (i, t, due)
            delivery[i] = t
    for field in ("drone", "battery"):
        by = defaultdict(list)
        for r in schedule:
            by[r[field]].append(r)
        for events in by.values():
            events.sort(key=lambda x: x["start"])
            for previous, following in zip(events[:-1], events[1:]):
                next_free = previous["end"] if field == "drone" else previous["battery_ready"]
                assert next_free <= following["start"] + EPS, (field, previous["sortie"], following["sortie"])
    score = {"sorties": len(schedule), "energy_kwh": sum(r["energy"] for r in schedule),
             "makespan_s": max(r["end"] for r in schedule),
             "weighted_tardiness_s": sum(boxes[i]["priority"] * max(0, t - boxes[i]["desired"])
                                         for i, t in delivery.items() if boxes[i]["desired"] is not None),
             "late_boxes": sum(t > boxes[i]["desired"] + EPS for i, t in delivery.items() if boxes[i]["desired"] is not None),
             "hard_deadline_violations": 0, "unique_boxes": len(delivery),
             "multi_area_sorties": sum(len(r["order"]) > 1 for r in schedule), "resource_conflicts": 0}
    return score


def objective(metrics):
    return (metrics["weighted_tardiness_s"], metrics["makespan_s"],
            metrics["energy_kwh"], metrics["sorties"])


def batch_neighbours(batches, boxes, models, physics, max_stops=3, limit=30):
    """Bounded merge, box-relocation and area-split moves; preserve urgent batches."""
    output, seen = [], set()
    def add(candidate, move):
        key = tuple(sorted(tuple(sorted(r["boxes"])) for r in candidate))
        if key not in seen:
            seen.add(key)
            output.append((move,candidate))
    regular = [j for j,r in enumerate(batches) if r["class"] != "urgent"]
    for j in regular:
        route = batches[j]
        if len(route["order"]) > 1:
            parts = []
            for area in route["order"]:
                ids = [i for i in route["boxes"] if boxes[i]["area"] == area]
                parts.append({"boxes":ids,"order":[area],"class":"regular"})
            add(batches[:j]+parts+batches[j+1:],"split_area")
    pairs = sorted(((i,j) for i in regular for j in regular if i<j),
                   key=lambda pair:min(0.0 if a==b else physics.legs[a,b]["distance"]
                     for a in batches[pair[0]]["order"] for b in batches[pair[1]]["order"]))
    for i,j in pairs:
        left,right=batches[i],batches[j]
        union=left["boxes"]+right["boxes"]
        if len({boxes[k]["area"] for k in union}) <= max_stops:
            order=choose_order(union,boxes,models,physics)
            if order is not None:
                new=[r for k,r in enumerate(batches) if k not in (i,j)]
                new.append({"boxes":union,"order":list(order),"class":"regular"})
                add(new,"merge")
        for source,target in ((i,j),(j,i)):
            if len(batches[source]["boxes"]) <= 1:
                continue
            for bid in batches[source]["boxes"]:
                remaining=[k for k in batches[source]["boxes"] if k!=bid]
                expanded=batches[target]["boxes"]+[bid]
                if len({boxes[k]["area"] for k in expanded}) > max_stops:
                    continue
                order1=choose_order(remaining,boxes,models,physics)
                order2=choose_order(expanded,boxes,models,physics)
                if order1 is not None and order2 is not None:
                    new=list(batches)
                    new[source]={"boxes":remaining,"order":list(order1),"class":"regular"}
                    new[target]={"boxes":expanded,"order":list(order2),"class":"regular"}
                    add(new,"relocate_box")
                if len(output)>=limit:
                    return output[:limit]
        if len(output)>=limit:
            break
    return output[:limit]


def improve(schedule,metrics,batches,boxes,models,drones,batteries,physics,
            rounds=2,limit=24,seeds=(0,1)):
    initial=objective(metrics)
    history=[]
    tested=feasible=0
    for iteration in range(rounds):
        best=None
        for move,candidate in batch_neighbours(batches,boxes,models,physics,3,limit):
            for seed in seeds:
                tested+=1
                try:
                    trial=assign(candidate,boxes,models,drones,batteries,physics,seed)
                    checked=validate(trial,boxes,models,drones,batteries,physics)
                except RuntimeError:
                    continue
                feasible+=1
                score=objective(checked)
                if score<objective(metrics) and (best is None or score<best[0]):
                    best=(score,trial,checked,candidate,move,seed)
        if best is None:
            break
        score,schedule,metrics,batches,move,seed=best
        history.append({"iteration":iteration+1,"move":move,"seed":seed,"score":score})
    return schedule,metrics,batches,{"initial_score":initial,"best_score":objective(metrics),
             "weighted_tardiness_improvement_s":initial[0]-objective(metrics)[0],
             "neighbour_schedules_tested":tested,"feasible_neighbour_schedules":feasible,
             "accepted_moves":history,"round_limit":rounds,"neighbour_limit":limit}


def solve(boxes, models, drones, batteries, physics, trials=30,
          cap_models=("B", "C"), max_stops_options=(1, 2, 3),
          local_search_rounds=2, candidate_store=None):
    """Bounded candidate construction, multistart dispatch and validated local search."""
    feasible=[]
    trial_summary=[]
    all_starts=[]
    started=time.perf_counter()
    for cap_model in cap_models:
        for max_stops in max_stops_options:
            batches=make_batches(boxes,models,physics,cap_model,max_stops)
            scores=[]
            template=[]
            for seed in range(trials):
                tick=time.perf_counter()
                try:
                    schedule=assign(batches,boxes,models,drones,batteries,physics,seed)
                    metrics=validate(schedule,boxes,models,drones,batteries,physics)
                    score=objective(metrics)
                    record=(score+(str(cap_model),max_stops,seed),
                            schedule,metrics,batches,cap_model,max_stops,seed)
                    feasible.append(record)
                    template.append(record)
                    scores.append(score)
                    all_starts.append({"cap_model":cap_model,"max_stops":max_stops,"seed":seed,
                                       "score":score,"elapsed_s":time.perf_counter()-tick,"feasible":True})
                except RuntimeError as exc:
                    all_starts.append({"cap_model":cap_model,"max_stops":max_stops,"seed":seed,
                                       "elapsed_s":time.perf_counter()-tick,"feasible":False,"error":str(exc)})
            trial_summary.append({"cap_model":cap_model,"max_stops":max_stops,
                                  "starts_tested":trials,"feasible_starts":len(scores),
                                  "initial_score":scores[0] if scores else None,
                                  "best_score":min(scores) if scores else None,
                                  "mean_weighted_tardiness_s":statistics.mean(x[0] for x in scores) if scores else None,
                                  "stdev_weighted_tardiness_s":statistics.pstdev(x[0] for x in scores) if scores else None})
            if candidate_store is not None and template:
                best=min(template,key=lambda x:x[0])
                candidate_store[f"{cap_model}_stops{max_stops}"]={"schedule":best[1],"metrics":dict(best[2]),
                                                               "batches":best[3],"seed":best[-1]}
    if not feasible:
        raise RuntimeError("No feasible schedule in the configured deterministic starts")
    score,schedule,metrics,batches,cap_model,max_stops,seed=min(feasible,key=lambda x:x[0])
    before=objective(metrics)
    schedule,metrics,batches,local=improve(schedule,metrics,batches,boxes,models,drones,batteries,
                                         physics,rounds=local_search_rounds,seeds=(seed,0,1))
    metrics.update({"starts_tested":trials*len(cap_models)*len(max_stops_options),
                    "feasible_starts":len(feasible),"selected_seed":seed,
                    "batch_cap_model":cap_model,"construction_max_stops":max_stops,
                    "max_stops":max(len(r["order"]) for r in schedule),
                    "initial_score":before,"best_score":objective(metrics),
                    "search_summary":trial_summary,"start_records":all_starts,"local_search":local,
                    "elapsed_s":time.perf_counter()-started,
                    "validation":{"passed":True,"violations":[]}})
    return schedule,metrics,batches


def save(schedule, metrics, batches, out=None):
    out = out or ROOT / "results" / "q2"
    out.mkdir(parents=True, exist_ok=True)
    (out / "schedule.json").write_text(json.dumps({"metrics": metrics, "batches": batches, "schedule": schedule},
                                                   ensure_ascii=False, indent=2), encoding="utf-8")
    return out
