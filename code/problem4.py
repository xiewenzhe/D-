"""Exact enumeration of two- and three-group rescue partitions for fixed Q3 tasks."""
from __future__ import annotations
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
import json
import math
from common import ROOT, EPS

RESOURCE_KEYS = ("drone_A", "drone_B", "drone_C", "battery_A", "battery_B", "battery_C", "relay", "relay_component")


def components(areas, schedule, missions=None, support=None):
    parent = {a: a for a in areas}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    def union(a, b):
        parent[find(a)] = find(b)
    for route in schedule:
        group = route["order"]
        for a in group[1:]:
            union(group[0], a)
    if missions is not None:
        assert support is not None
        route_by_id = {r["sortie"]: r for r in schedule}
        for i in range(len(missions)):
            served = sorted({a for rid in support[i] for a in route_by_id[rid]["order"]})
            for a in served[1:]:
                union(served[0], a)
    sets = defaultdict(list)
    for a in areas:
        sets[find(a)].append(a)
    return sorted((tuple(sorted(v)) for v in sets.values()), key=lambda x: x[0])


def relay_support(schedule, missions, coverage_rows):
    route = {r["sortie"]: r for r in schedule}
    support = {i: set() for i in range(len(missions))}
    for row in coverage_rows:
        if row["mode"] != "relay":
            continue
        found = [i for i, m in enumerate(missions) if m["relay"] == row["relay"]
                 and m["service_start"] - EPS <= row["time_s"] <= m["service_end"] + EPS]
        assert len(found) == 1
        support[found[0]].add(row["sortie"])
    assert all(support.values())
    return support


def peak(intervals):
    events = []
    for start, end in intervals:
        assert end + EPS >= start
        events.extend(((start, 1), (end, -1)))
    events.sort(key=lambda x: (x[0], x[1]))
    level = answer = 0
    for _, change in events:
        level += change
        answer = max(answer, level)
    assert level == 0
    return answer


def allocation(routes, relay_jobs):
    result = {}
    for model in ("A", "B", "C"):
        rr = [r for r in routes if r["model"] == model]
        result[f"drone_{model}"] = peak((r["start"], r["end"]) for r in rr)
        result[f"battery_{model}"] = peak((r["start"], r["battery_ready"]) for r in rr)
    result["relay"] = peak((m["launch"], m["end"] + m["turnaround"]) for m in relay_jobs)
    result["relay_component"] = peak((m["launch"], m["component_ready"]) for m in relay_jobs)
    return result


def inventory(drones, batteries, relays, energy_stock):
    counts = Counter(drones.values())
    return {**{f"drone_{g}": counts[g] for g in ("A", "B", "C")},
            **{f"battery_{g}": batteries[g]["count"] for g in ("A", "B", "C")},
            "relay": len(relays), "relay_component": energy_stock["count"]}


def enumerate_labels(n, k):
    labels = [0] * n
    def rec(i, high):
        if i == n:
            if high + 1 == k:
                yield tuple(labels)
            return
        for g in range(min(k - 1, high + 1) + 1):
            labels[i] = g
            yield from rec(i + 1, max(high, g))
    yield from rec(1, 0)


def evaluate_partition(groups, schedule, missions, support, boxes, stock, baseline):
    area_group = {a: j for j, group in enumerate(groups) for a in group}
    route_group = {}
    for route in schedule:
        labels = {area_group[a] for a in route["order"]}
        assert len(labels) == 1
        route_group[route["sortie"]] = next(iter(labels))
    group_routes = [[r for r in schedule if route_group[r["sortie"]] == j] for j in range(len(groups))]
    group_missions = [[] for _ in groups]
    for i, mission in enumerate(missions):
        labels = {route_group[rid] for rid in support[i]}
        assert len(labels) == 1, ("relay mission crosses task groups", i, labels)
        group_missions[next(iter(labels))].append(mission)
    configs = []
    total = Counter()
    work = []
    for j, group in enumerate(groups):
        cfg = allocation(group_routes[j], group_missions[j])
        total.update(cfg)
        workload = sum(r["duration"] for r in group_routes[j])
        work.append(workload)
        box_ids = {i for r in group_routes[j] for i in r["boxes"]}
        configs.append({"group": j + 1, "areas": list(group), "boxes": len(box_ids),
                        "transport_sorties": len(group_routes[j]), "relay_sorties": len(group_missions[j]),
                        "workload_s": workload, "transport_energy_kwh": sum(r["energy"] for r in group_routes[j]),
                        "allocation": cfg})
    shortage = {key: max(0, total[key] - stock[key]) for key in RESOURCE_KEYS}
    redundancy = {key: total[key] - baseline[key] for key in RESOURCE_KEYS}
    imbalance = (max(work) - min(work)) / (sum(work) / len(work))
    return {"groups": configs, "total_allocation": dict(total), "shortage": shortage,
            "shortage_total": sum(shortage.values()), "redundancy": redundancy,
            "redundancy_total": sum(redundancy.values()), "workload_imbalance": imbalance,
            "relay_mission_replicas": 0}


def solve(schedule, missions, coverage_rows, boxes, drones, batteries, relays, energy_stock, relay_model):
    areas = sorted({b["area"] for b in boxes.values()})
    stock = inventory(drones, batteries, relays, energy_stock)
    decorated = [{**m, "turnaround": relay_model["turnaround"]} for m in missions]
    baseline = allocation(schedule, decorated)
    support = relay_support(schedule, missions, coverage_rows)
    atoms = components(areas, schedule, missions, support)
    if len(atoms) < 3:
        raise ValueError(f"Q3 fixed transport and relay missions form only {len(atoms)} indivisible groups")
    results = {}
    stats = {}
    alternatives = {}
    for k in (2, 3):
        best = None
        evaluated = 0
        shortage_hist = Counter()
        frontier = {}
        most_balanced = None
        least_redundant = None
        for labels in enumerate_labels(len(atoms), k):
            groups = [tuple(sorted(a for atom, label in zip(atoms, labels) if label == j for a in atom)) for j in range(k)]
            result = evaluate_partition(groups, schedule, decorated, support, boxes, stock, baseline)
            evaluated += 1
            assert len(groups) == k and all(groups)
            assert sorted(a for group in groups for a in group) == areas
            assert sum(result["shortage"].values()) == result["shortage_total"]
            assert all(result["shortage"][key] == max(0, count - stock[key])
                       for key, count in result["total_allocation"].items())
            balanced_score = (result["workload_imbalance"], result["shortage_total"],
                              result["redundancy_total"], tuple(labels))
            redundant_score = (result["redundancy_total"], result["shortage_total"],
                               result["workload_imbalance"], tuple(labels))
            if most_balanced is None or balanced_score < most_balanced[0]:
                most_balanced = (balanced_score, result)
            if least_redundant is None or redundant_score < least_redundant[0]:
                least_redundant = (redundant_score, result)
            shortage_hist[result["shortage_total"]] += 1
            short = result["shortage_total"]
            if short not in frontier or (result["workload_imbalance"], result["redundancy_total"]) < (frontier[short]["workload_imbalance"], frontier[short]["redundancy_total"]):
                frontier[short] = result
            score = (result["shortage_total"], result["workload_imbalance"],
                     result["redundancy_total"], tuple(labels))
            if best is None or score < best[0]:
                best = (score, result)
        results[k] = best[1]
        best_short = best[1]["shortage_total"]
        alternatives[k] = {"min_shortage": best[1],
                           "most_balanced": most_balanced[1],
                           "min_redundancy": least_redundant[1],
                           "balanced": most_balanced[1],
                           "one_extra_shortage": frontier.get(best_short + 1)}
        stats[k] = {"enumerated_partitions": evaluated, "shortage_histogram": dict(sorted(shortage_hist.items()))}
    return {"alternatives": alternatives, "components": [list(a) for a in atoms], "stock": stock, "global_minimum": baseline,
            "partitions": results, "search": stats,
            "priority": "minimize shortage count, then workload imbalance, then added resource count",
            "validation": {"passed": True, "violations": [], "areas_checked": len(areas),
                           "partitions_checked": sum(stats[k]["enumerated_partitions"] for k in stats)}}


def save(solution):
    out = ROOT / "results" / "q4"
    out.mkdir(parents=True, exist_ok=True)
    (out / "partitions.json").write_text(json.dumps(solution, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
