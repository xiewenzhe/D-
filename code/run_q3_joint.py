"""Canonical Q3 solver: Q2 adaptation, beam search, certified retiming, and Q4 refresh."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from math import inf
from time import perf_counter
import csv
import hashlib
import json
from pathlib import Path

from common import ROOT, Physics, Terrain, read_inputs, charge_seconds, EPS
from problem2 import hard_due, validate as validate_transport
import problem3
from problem3 import (candidate_sites, profiles, initial_pairs, new_mission,
                      update_mission, _asset_choice, _try_existing, BUFFER,
                      hover_limit, los_obstructed_exact, validate_joint, direct_samples)
from continuous_validation import certify_schedule

SOURCE = ROOT / "results" / "q2_improved" / "schedule.json"
OUT = ROOT / "results" / "q3"
BEAM = OUT / "beam_solution.json"


def load():
    nodes, boxes, models, drones, batteries, relay_model, relays, energy_stock, comm = read_inputs()
    physics = Physics(nodes, Terrain())
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    schedule = []
    for item in raw:
        plan = physics.evaluate_route(models[item["g"]],
                                      {bid: boxes[bid] for bid in item["boxes"]},
                                      tuple(item["order"]))
        if plan is None:
            raise ValueError(f"Invalid Q2 route {item['id']}")
        if abs(plan["duration"] - item["duration"]) > 1e-3 or abs(plan["energy"] - item["energy"]) > 1e-5:
            raise ValueError(f"Q2 physical mismatch {item['id']}")
        start = float(item["start"])
        battery = item["battery"].replace("-BAT-", "")
        schedule.append({"sortie": item["id"], "boxes": item["boxes"],
                         "order": item["order"], "model": item["g"],
                         "drone": item["drone"], "battery": battery,
                         "start": start, "end": start + plan["duration"],
                         "duration": plan["duration"], "energy": plan["energy"],
                         "soc": plan["soc"], "stages": plan["stages"],
                         "delivery": {bid: start + offset for bid, offset in plan["delivery_offsets"].items()},
                         "battery_ready": float(item["battery_ready"]),
                         "class": "urgent" if any(boxes[bid]["first"] or boxes[bid]["kind"] == "MED"
                                                   for bid in item["boxes"]) else "regular"})
    schedule.sort(key=lambda r: (r["start"], r["sortie"]))
    validate_transport(schedule, boxes, models, drones, batteries, physics)
    return schedule, boxes, models, drones, batteries, physics, relay_model, relays, energy_stock, comm


def due_start(route, boxes):
    offsets={i:t-route["start"] for i,t in route["delivery"].items()}
    return min((hard_due(boxes[i])-offsets[i] for i in route["boxes"]
                if hard_due(boxes[i]) is not None),default=inf)


def relay_score(missions):
    return sum(m["energy"] for m in missions)


def make_first_states(routes, prof, sites, relay_model, relays, energy_stock,
                      drones, batteries, boxes):
    first=routes[:8]
    assert len(first)==8 and all(abs(r["start"])<EPS for r in first)
    free_d={did:0.0 for did in drones}
    free_b={g:{f"{g}{j:02d}":0.0 for j in range(1,b["count"]+1)}
            for g,b in batteries.items()}
    for r in first:
        free_d[r["drone"]]=r["end"]
        free_b[r["model"]][r["battery"]]=r["battery_ready"]
    base_tardy=sum(boxes[i]["priority"]*max(0,t-boxes[i]["desired"])
                   for r in first for i,t in r["delivery"].items()
                   if boxes[i]["desired"] is not None)
    future={site["id"]:sum(len(p["cover"][site["id"]]) for p in prof.values()) for site in sites}
    initial=initial_pairs(first,prof,sites,relay_model)
    states=[]
    for pair_index,(a,b) in enumerate(initial):
        for favoured in (a["id"],b["id"]):
            assigned={a["id"]:[],b["id"]:[]}
            for route in first:
                p=prof[route["sortie"]]
                for j,(t,_) in enumerate(p["gaps"]):
                    available=[sid for sid in assigned if j in p["cover"][sid]]
                    if not available:
                        break
                    chosen=favoured if favoured in available else available[0]
                    assigned[chosen].append(t)
                else:
                    continue
                break
            else:
                missions=[]
                components={f"RE{k:02d}":[] for k in range(1,energy_stock["count"]+1)}
                for rid,site in zip(relays,(a,b)):
                    need=assigned[site["id"]]
                    if not need:continue
                    component=next(k for k,h in components.items() if not h)
                    mission=new_mission(site,min(need),max(need),rid,component,0,0,
                                        relay_model,energy_stock)
                    if mission is None:
                        break
                    missions.append(mission)
                    components[component].append(mission)
                else:
                    states.append({"todo":tuple(r["sortie"] for r in routes[8:]),
                                   "scheduled":list(first),"missions":missions,
                                   "components":components,"free_d":dict(free_d),
                                   "free_b":deepcopy(free_b),"last_start":0.0,
                                   "tardy":base_tardy,"pair":pair_index,
                                   "pair_sites":(a["id"],b["id"]),"choices":[]})
    return states,len(initial),future


def start_candidates(route, state, prof, boxes, drones, relays, relay_model,
                     energy_stock, sites, future):
    p=prof[route["sortie"]]
    earliest=max(state["last_start"],state["free_d"][route["drone"]],
                 state["free_b"][route["model"]][route["battery"]])
    latest=due_start(route,boxes)
    if earliest>latest+EPS:
        return []
    offsets={i:t-route["start"] for i,t in route["delivery"].items()}
    def delay(start):
        delivery={i:start+t for i,t in offsets.items()}
        if any(delivery[i]>hard_due(boxes[i])+EPS for i in route["boxes"]
               if hard_due(boxes[i]) is not None):
            return inf
        return sum(boxes[i]["priority"]*max(0,t-boxes[i]["desired"])
                   for i,t in delivery.items() if boxes[i]["desired"] is not None)
    if not p["gaps"]:
        return [(earliest, "none", None, delay(earliest), 0)]
    gap_first,gap_last=p["gaps"][0][0],p["gaps"][-1][0]
    attempts={earliest}
    for m in state["missions"]:
        attempts.add(max(earliest,m["service_start"]+BUFFER-gap_first))
    urgent_remaining=[rid for rid in state["todo"] if rid!=route["sortie"]]
    scores={}
    for site in sites:
        sid=site["id"]
        if len(p["cover"][sid])!=len(p["gaps"]):
            continue
        hard=sum(1 for rid in urgent_remaining
                 if due_start(prof[rid]["route"],boxes)<3500
                 and len(prof[rid]["cover"][sid])==len(prof[rid]["gaps"]))
        broad=sum(len(prof[rid]["cover"][sid]) for rid in urgent_remaining)
        scores[sid]=(hard,broad)
    ranked=sorted((site for site in sites if site["id"] in scores),
                  key=lambda s:(-scores[s["id"]][0],-scores[s["id"]][1],
                                s["flight_energy"],s["id"]))[:18]
    # Milestone starts account for relay return, turnaround, preparation and flight.
    for site in ranked:
        approach=relay_model["prepare"]+site["outbound_s"]+relay_model["link_time"]
        for rid in relays:
            own=[m for m in state["missions"] if m["relay"]==rid]
            ready=own[-1]["end"]+relay_model["turnaround"] if own else 0.0
            for comp,hist in state["components"].items():
                ready_c=hist[-1]["component_ready"] if hist else 0.0
                attempts.add(max(earliest,max(ready,ready_c)+approach+BUFFER-gap_first))
    if latest<inf:
        attempts.add(latest)
    for increment in (30,90,180,360):
        attempts.add(earliest+increment)
    attempts=sorted(t for t in attempts if earliest-EPS<=t<=latest+EPS and t<25000)
    options=[]
    for start in attempts:
        tardy=delay(start)
        if tardy==inf:continue
        existing=_try_existing(p,start,state["missions"],relay_model,energy_stock)
        if existing is not None:
            options.append((start,"extend",tuple(m["site"]["id"] for m,_ in existing),
                            tardy,0))
        for site in ranked:
            first,last=start+gap_first,start+gap_last
            plan=_asset_choice(site,first,last,state["missions"],relays,
                               state["components"],relay_model,energy_stock)
            if plan is not None:
                hard,broad=scores[site["id"]]
                options.append((start,"new",site["id"],tardy,
                                hard*100000+broad))
    # Keep different sites and different times, including a delay that repairs resource availability.
    by_key={}
    for option in options:
        key=(option[1],option[2])
        by_key.setdefault(key,[]).append(option)
    diverse=[]
    for key,items in by_key.items():
        diverse.extend(sorted(items,key=lambda x:(x[3],x[0]))[:2])
    return sorted(diverse,key=lambda x:(x[3],-x[4],x[0]))[:20]


def apply_option(state,route,option,prof,boxes,models,batteries,relay_model,
                 relays,energy_stock,sites):
    start,action,sid,tardy,future=option
    nxt=deepcopy(state)
    p=prof[route["sortie"]]
    if action=="extend":
        extension=_try_existing(p,start,nxt["missions"],relay_model,energy_stock)
        if extension is None:return None
        for mission,end in extension:
            if not update_mission(mission,end,relay_model,energy_stock):
                return None
    elif action=="new":
        site=sites[sid]
        first=start+p["gaps"][0][0]
        last=start+p["gaps"][-1][0]
        plan=_asset_choice(site,first,last,nxt["missions"],relays,
                           nxt["components"],relay_model,energy_stock)
        if plan is None:return None
        nxt["missions"].append(plan)
        nxt["components"][plan["component"]].append(plan)
    rec=dict(route)
    offsets={i:t-route["start"] for i,t in route["delivery"].items()}
    rec["start"]=start
    rec["end"]=start+route["duration"]
    rec["delivery"]={i:start+t for i,t in offsets.items()}
    rec["battery_ready"]=rec["end"]+charge_seconds(rec["soc"],
                                  batteries[rec["model"]]["full_charge"])
    nxt["scheduled"].append(rec)
    nxt["free_d"][rec["drone"]]=rec["end"]
    nxt["free_b"][rec["model"]][rec["battery"]]=rec["battery_ready"]
    nxt["last_start"]=start
    nxt["tardy"]+=tardy
    nxt["todo"]=tuple(rid for rid in nxt["todo"] if rid!=route["sortie"])
    nxt["choices"].append({"sortie":route["sortie"],"start":start,
                           "relay_action":action,"site":sid})
    return nxt


def rank_state(state,route_by_id,boxes,prof):
    lb=state["tardy"]
    for rid in state["todo"]:
        r=route_by_id[rid]
        earliest=max(state["last_start"],state["free_d"][r["drone"]],
                     state["free_b"][r["model"]][r["battery"]])
        if earliest>due_start(r,boxes)+EPS:
            return None
        for bid,t in r["delivery"].items():
            b=boxes[bid]
            if b["desired"] is not None:
                lb+=b["priority"]*max(0,earliest+t-r["start"]-b["desired"])
    future_support=0.0
    scarcity_risk=0.0
    active_sites={m["site"]["id"] for m in state["missions"]}
    for rid in state["todo"]:
        route=route_by_id[rid]
        latest=due_start(route,boxes)
        if latest==inf:
            continue
        feasible_sites=sum(len(cover)==len(prof[rid]["gaps"])
                           for cover in prof[rid]["cover"].values())
        if latest>4500:
            scarcity_risk+=180000*max(0.0, state["last_start"]-latest+2200)/2200/max(1,feasible_sites/6)
        if any(len(prof[rid]["cover"][sid])==
               len(prof[rid]["gaps"]) for sid in active_sites):
            future_support+=1/max(60,latest-state["last_start"])
    return (lb+scarcity_risk,lb,-future_support,state["last_start"],
            relay_score(state["missions"]),len(state["missions"]))


def beam_plan(routes, boxes, models, drones, batteries, physics,
              relay_model, relays, energy_stock, comm,
              width=160, route_branches=5, sample_step=10, time_limit_s=90):
    began=perf_counter()
    sites=candidate_sites(physics,relay_model,comm,height_levels=(.5,.75,1))
    by_site={s["id"]:s for s in sites}
    prof=profiles(routes,physics,models,sites,comm,step=sample_step)
    by_id={r["sortie"]:r for r in routes}
    for r in routes:prof[r["sortie"]]["route"]=r
    beam,pair_count,future=make_first_states(routes,prof,sites,relay_model,relays,
                                             energy_stock,drones,batteries,boxes)
    if not beam:raise RuntimeError("No feasible initial relay pair")
    beam=sorted(beam,key=lambda s:rank_state(s,by_id,boxes,prof))[:width]
    history=[]
    for depth in range(len(routes)-8):
        if perf_counter()-began>time_limit_s:break
        previous_beam=beam
        expanded=[]
        for state in beam:
            todo=sorted(state["todo"],key=lambda rid:(due_start(by_id[rid],boxes),
                              by_id[rid]["start"],rid))
            finite=[rid for rid in todo if due_start(by_id[rid],boxes)<inf]
            if finite:
                nearest=due_start(by_id[finite[0]],boxes)
                selectable=[rid for rid in finite if due_start(by_id[rid],boxes)<=nearest+1200]
            else:
                selectable=todo
            if depth>=5 and depth<9:
                selectable=sorted(selectable,key=lambda rid:(
                    sum(len(cover)==len(prof[rid]["gaps"])
                        for cover in prof[rid]["cover"].values()),
                    due_start(by_id[rid],boxes)))[:1]
            for rid in selectable[:route_branches]:
                route=by_id[rid]
                for option in start_candidates(route,state,prof,boxes,drones,relays,
                                               relay_model,energy_stock,sites,future):
                    child=apply_option(state,route,option,prof,boxes,models,batteries,
                                       relay_model,relays,energy_stock,by_site)
                    if child is None:continue
                    score=rank_state(child,by_id,boxes,prof)
                    if score is not None:
                        expanded.append((score,child))
        expanded.sort(key=lambda row:row[0])
        selected=[]
        per_pair=Counter()
        per_site=Counter()
        fingerprints=set()
        for score,state in expanded:
            signature=(tuple(sorted(state["todo"])),round(state["last_start"],1),
                       tuple((m["site"]["id"],round(m["service_end"]/60))
                             for m in state["missions"]))
            lead=next((c["site"] for c in state["choices"] if c["relay_action"]=="new"),"none")
            if (signature in fingerprints or per_pair[state["pair"]]>=max(20,width//6)
                    or per_site[lead]>=max(30,width//3)):
                continue
            fingerprints.add(signature)
            per_pair[state["pair"]]+=1
            per_site[lead]+=1
            selected.append(state)
            if len(selected)>=width:break
        beam=selected
        history.append({"depth":depth+1,"expanded":len(expanded),
                        "retained":len(beam),"best_lower_bound":expanded[0][0][0] if expanded else None,
                        "route_prefixes":Counter(tuple(c["sortie"] for c in st["choices"])
                                                 for st in beam).most_common(8)})
        if not beam:
            history[-1]["failed_states"]=[{"choices":st["choices"],"todo":st["todo"],"last_start":st["last_start"],"missions":[(m["site"]["id"],m["service_start"],m["service_end"]) for m in st["missions"]]} for st in previous_beam[:3]]
            break
    complete=[s for s in beam if not s["todo"]]
    return complete,{"initial_pairs":pair_count,"initial_states":len(beam),
                     "profiles":len(prof),"history":history,"elapsed_s":perf_counter()-began}


def validate_candidates(states, boxes, models, drones, batteries, physics,
                        relay_model, relays, energy_stock, comm, limit=20):
    results=[]
    errors=Counter()
    for state in sorted(states,key=lambda s:(s["tardy"],
                            max(r["end"] for r in s["scheduled"]),
                            relay_score(s["missions"])))[:limit]:
        schedule=sorted(state["scheduled"],key=lambda r:(r["start"],r["sortie"]))
        missions=state["missions"]
        try:
            validate_transport(schedule,boxes,models,drones,batteries,physics)
            old=problem3.los_obstructed
            problem3.los_obstructed=los_obstructed_exact
            try:
                metrics,rows=validate_joint(schedule,missions,boxes,models,drones,
                    batteries,physics,relay_model,relays,energy_stock,comm,step=1)
            finally:
                problem3.los_obstructed=old
            certificate=certify_schedule(schedule,missions,physics,models,comm)
            if not certificate["passed"]:
                raise ValueError("Unresolved continuous communication")
            score=(metrics["weighted_tardiness_s"],metrics["joint_makespan_s"],
                   metrics["total_energy_kwh"],metrics["sorties"]+metrics["relay_sorties"])
            results.append((score,schedule,missions,metrics,certificate,state,rows))
        except (AssertionError,ValueError,RuntimeError) as exc:
            errors[type(exc).__name__+":"+str(exc)[:140]]+=1
    results.sort(key=lambda x:x[0])
    return results,dict(errors)


def run_cli():
    import argparse
    import csv
    import hashlib
    import json
    from pathlib import Path
    from common import ROOT

    parser=argparse.ArgumentParser(description="Optimize Q3 using the audited 24-sortie Q2 source")
    parser.add_argument("--width",type=int,default=160)
    parser.add_argument("--sample-step",type=float,default=10.0)
    parser.add_argument("--seconds",type=float,default=120.0)
    parser.add_argument("--validate",type=int,default=12)
    args=parser.parse_args()
    context=load()
    routes,boxes,models,drones,batteries,physics,relay_model,relays,energy_stock,comm=context
    routes=deepcopy(routes)
    route=next(r for r in routes if r["sortie"]=="Q2-009")
    plan=physics.evaluate_route(models[route["model"]],
                                {bid:boxes[bid] for bid in route["boxes"]},
                                ("S012","S009"))
    if plan is None:raise RuntimeError("Q2-009 reversed route is physically infeasible")
    route.update(order=list(plan["order"]),energy=plan["energy"],soc=plan["soc"],
                 stages=plan["stages"],duration=plan["duration"],
                 delivery={bid:route["start"]+t
                           for bid,t in plan["delivery_offsets"].items()},
                 end=route["start"]+plan["duration"],
                 battery_ready=route["start"]+plan["duration"]+
                 charge_seconds(plan["soc"],batteries[route["model"]]["full_charge"]))
    validate_transport(routes,boxes,models,drones,batteries,physics)
    states,trace=beam_plan(routes,boxes,models,drones,batteries,physics,
                           relay_model,relays,energy_stock,comm,
                           width=args.width,sample_step=args.sample_step,
                           time_limit_s=args.seconds)
    print("beam_complete",len(states),"seconds",trace["elapsed_s"],flush=True)
    if not states:
        print(json.dumps(trace["history"][-1],ensure_ascii=False,default=str)[:5000])
        raise RuntimeError("No complete candidate")
    accepted,errors=validate_candidates(states,boxes,models,drones,batteries,
                                         physics,relay_model,relays,energy_stock,
                                         comm,limit=args.validate)
    print("certified",len(accepted),"rejected",errors,flush=True)
    if not accepted:raise RuntimeError("No candidate passed exact link and continuous checks")
    score,schedule,missions,metrics,certificate,state,rows=accepted[0]
    metrics.update(status="FEASIBLE_HEURISTIC",method="deadline_and_site_scarcity_beam",
                   source="results/q2_improved/schedule.json",
                   source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                   continuous_validation_passed=True,
                   continuous_certified_duration_s=certificate["certified_duration_s"],
                   continuous_required_duration_s=certificate["required_duration_s"],
                   continuous_min_margin_lower_bound_db=certificate["minimum_margin_lower_bound_db"],
                   global_optimality_proven=False,
                   search_width=args.width,search_sample_step_s=args.sample_step,
                   search_elapsed_s=trace["elapsed_s"],
                   q2_009_order_changed=True)
    out=ROOT/"results"/"q3"
    out.mkdir(parents=True,exist_ok=True)
    (out/"solution.json").write_text(json.dumps(
        {"metrics":metrics,"transport":schedule,"relays":missions},
        ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"continuous_certificate.json").write_text(
        json.dumps(certificate,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"beam_solution.json").write_bytes((out/"solution.json").read_bytes())
    (out/"search_trace.json").write_text(
        json.dumps(trace,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    with (out/"communication_samples.csv").open("w",newline="",encoding="utf-8-sig") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary={k:metrics[k] for k in
             ("sorties","relay_sorties","weighted_tardiness_s","joint_makespan_s",
              "energy_kwh","relay_energy_kwh","total_energy_kwh",
              "continuous_validation_passed","continuous_min_margin_lower_bound_db")}
    (out/"summary.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gap_window(route,physics,models,comm):
    zero=dict(route,start=0.0,end=route["duration"])
    gap=[row["t"] for row in direct_samples([zero],physics,models,comm,step=10)
         if not row["direct"]]
    if not gap:
        raise ValueError("Route has no direct gap: "+route["sortie"])
    return min(gap),max(gap)


def refine():
    schedule0,boxes,models,drones,batteries,physics,relay_model,relays,energy_stock,comm=load()
    beam=json.loads(BEAM.read_text(encoding="utf-8"))
    schedule=deepcopy(beam["transport"])
    old_missions=deepcopy(beam["relays"])
    by_id={r["sortie"]:r for r in schedule}

    def shift(rid,start):
        route=by_id[rid]
        delta=start-route["start"]
        route["start"]=start
        route["end"]+=delta
        route["battery_ready"]+=delta
        route["delivery"]={bid:t+delta for bid,t in route["delivery"].items()}

    shift("Q2-014",by_id["Q2-007"]["end"]+0.01)
    shift("Q2-013",2143.0)
    shift("Q2-022",by_id["Q2-013"]["end"]+0.01)
    shift("Q2-021",4500.0)
    shift("Q2-017",by_id["Q2-011"]["end"]+0.01)
    shift("Q2-018",by_id["Q2-010"]["end"]+0.01)
    shift("Q2-023",by_id["Q2-018"]["end"]+0.01)
    shift("Q2-024",by_id["Q2-017"]["end"]+0.01)
    shift("Q2-020",6175.0)

    first_four=old_missions[:4]
    first=first_four[0]
    last_service=max(by_id[rid]["start"]+gap_window(by_id[rid],physics,models,comm)[1]
                     for rid in ("Q2-023","Q2-024"))+BUFFER
    if not update_mission(first,last_service,relay_model,energy_stock):
        raise RuntimeError("Long first relay exceeds its return reserve")
    previous=first_four[3]
    gap_first,gap_last=gap_window(by_id["Q2-020"],physics,models,comm)
    late=new_mission(old_missions[4]["site"],
                     by_id["Q2-020"]["start"]+gap_first,
                     by_id["Q2-020"]["start"]+gap_last,
                     "R02","RE04",
                     previous["end"]+relay_model["turnaround"],0.0,
                     relay_model,energy_stock)
    if late is None:
        raise RuntimeError("Final S010 relay cannot be redeployed")
    missions=first_four+[late]
    schedule.sort(key=lambda r:(r["start"],r["sortie"]))
    validate_transport(schedule,boxes,models,drones,batteries,physics)
    old_test=problem3.los_obstructed
    problem3.los_obstructed=los_obstructed_exact
    try:
        metrics,rows=validate_joint(schedule,missions,boxes,models,drones,batteries,
                                    physics,relay_model,relays,energy_stock,comm,step=1)
    finally:
        problem3.los_obstructed=old_test
    certificate=certify_schedule(schedule,missions,physics,models,comm)
    if not certificate["passed"]:
        raise RuntimeError("Continuous communication certificate failed")
    if (metrics["hard_deadline_violations"] or metrics["resource_conflicts"] or
        metrics["relay_resource_conflicts"] or metrics["communication_breaks"] or
        metrics["unique_boxes"]!=len(boxes)):
        raise RuntimeError("Hard constraint failed")
    metrics.update(status="FEASIBLE_HEURISTIC",
                   method="beam_plus_certified_window_retiming",
                   source="results/q2_improved/schedule.json",
                   source_sha256=sha(SOURCE),
                   beam_sha256=sha(BEAM),
                   word_sha256=sha(next(ROOT.glob("D-*.docx"))),
                   continuous_validation_passed=True,
                   continuous_certified_duration_s=certificate["certified_duration_s"],
                   continuous_required_duration_s=certificate["required_duration_s"],
                   continuous_min_margin_lower_bound_db=certificate["minimum_margin_lower_bound_db"],
                   global_optimality_proven=False,
                   q2_009_order_changed=True)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"solution.json").write_text(json.dumps(
        {"metrics":metrics,"transport":schedule,"relays":missions},
        ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"continuous_certificate.json").write_text(json.dumps(
        certificate,ensure_ascii=False,indent=2),encoding="utf-8")
    with (OUT/"communication_samples.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader();w.writerows(rows)
    summary={key:metrics[key] for key in
             ("sorties","relay_sorties","weighted_tardiness_s","joint_makespan_s",
              "energy_kwh","relay_energy_kwh","total_energy_kwh",
              "hard_deadline_violations","resource_conflicts",
              "relay_resource_conflicts","communication_breaks",
              "continuous_validation_passed",
              "continuous_min_margin_lower_bound_db")}
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),
                                    encoding="utf-8")
    with (OUT/"transport_sorties.csv").open("w",newline="",encoding="utf-8-sig") as f:
        cols=("sortie","model","drone","battery","order","start_s","end_s","energy_kwh","return_soc")
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for r in schedule:
            w.writerow(dict(sortie=r["sortie"],model=r["model"],drone=r["drone"],
                            battery=r["battery"],order=";".join(r["order"]),
                            start_s=r["start"],end_s=r["end"],
                            energy_kwh=r["energy"],return_soc=r["soc"]))
    with (OUT/"relay_sorties.csv").open("w",newline="",encoding="utf-8-sig") as f:
        cols=("relay","component","site","launch_s","service_start_s","service_end_s",
              "return_s","energy_kwh","return_soc")
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for r in missions:
            w.writerow(dict(relay=r["relay"],component=r["component"],
                            site=r["site"]["id"],launch_s=r["launch"],
                            service_start_s=r["service_start"],
                            service_end_s=r["service_end"],return_s=r["end"],
                            energy_kwh=r["energy"],return_soc=r["soc"]))
    with (OUT/"box_deliveries.csv").open("w",newline="",encoding="utf-8-sig") as f:
        cols=("box","area","kind","sortie","delivery_s","hard_due_s",
              "desired_s","priority","lateness_s")
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for route in schedule:
            for bid,t in route["delivery"].items():
                box=boxes[bid]
                desired=box["desired"]
                w.writerow(dict(box=bid,area=box["area"],kind=box["kind"],
                                sortie=route["sortie"],delivery_s=t,
                                hard_due_s=hard_due(box),desired_s=desired,
                                priority=box["priority"],
                                lateness_s=max(0.0,t-desired)
                                if desired is not None else 0.0))
    print(json.dumps(summary,ensure_ascii=False,indent=2))

def refresh_q4():
    _,boxes,_,drones,batteries,_,relay_model,relays,stock,_=load()
    q3dir=ROOT/"results"/"q3"
    source=q3dir/"solution.json"
    certpath=q3dir/"continuous_certificate.json"
    data=json.loads(source.read_text(encoding="utf-8"))
    certificate=json.loads(certpath.read_text(encoding="utf-8"))
    if not certificate["passed"]:
        raise RuntimeError("Q3 continuous certificate required")
    from problem4 import solve
    from continuous_validation import support_rows
    result=solve(data["transport"],data["relays"],support_rows(certificate),
                 boxes,drones,batteries,relays,stock,relay_model)
    result["q3_source"]="results/q3/solution.json"
    result["q3_sha256"]=hashlib.sha256(source.read_bytes()).hexdigest()
    out=ROOT/"results"/"q4"
    out.mkdir(parents=True,exist_ok=True)
    (out/"partitions.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"components":result["components"],
      "two_group_shortage":result["partitions"][2]["shortage_total"],
      "three_group_shortage":result["partitions"][3]["shortage_total"]},
      ensure_ascii=False,indent=2))


def record_project_state():
    q1=json.loads((ROOT/"results"/"q1_reproduced"/"solution.json").read_text(encoding="utf-8"))
    q2=json.loads((ROOT/"results"/"q2_improved"/"summary.json").read_text(encoding="utf-8"))
    q3=json.loads((OUT/"solution.json").read_text(encoding="utf-8"))
    q4=json.loads((ROOT/"results"/"q4"/"partitions.json").read_text(encoding="utf-8"))
    certificate=json.loads((OUT/"continuous_certificate.json").read_text(encoding="utf-8"))
    checks={
        "q1":q1["validation"],
        "q2":{"passed":q2["hard_violations"]==0,"hard_violations":q2["hard_violations"]},
        "q3":{"passed":bool(certificate["passed"]) and
              q3["metrics"]["hard_deadline_violations"]==0 and
              q3["metrics"]["resource_conflicts"]==0 and
              q3["metrics"]["relay_resource_conflicts"]==0 and
              q3["metrics"]["communication_breaks"]==0,
              "continuous_validation_passed":certificate["passed"],
              "unresolved_intervals":len(certificate["unresolved_intervals"])},
        "q4":q4["validation"]
    }
    if not all(item["passed"] for item in checks.values()):
        raise RuntimeError("Project validation summary contains a failed question")
    (ROOT/"results"/"validation_summary.json").write_text(
        json.dumps(checks,ensure_ascii=False,indent=2),encoding="utf-8")
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    manifest={
        "version":"D-current-Q3",
        "q3_method":q3["metrics"]["method"],
        "q3_source":"results/q2_improved/schedule.json",
        "q3_source_sha256":digest(SOURCE),
        "q3_solution_sha256":digest(OUT/"solution.json"),
        "q3_certificate_sha256":digest(OUT/"continuous_certificate.json"),
        "q4_solution_sha256":digest(ROOT/"results"/"q4"/"partitions.json"),
        "word_sha256":q3["metrics"]["word_sha256"],
        "search_width":q3["metrics"].get("search_width",160),
        "sample_step_s":10,
        "communication_margin_db":certificate["communication_margin_db"],
        "global_optimality_proven":False
    }
    (ROOT/"results"/"run_manifest.json").write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")


def main():
    run_cli()
    refine()
    refresh_q4()
    record_project_state()


if __name__ == "__main__":
    main()
