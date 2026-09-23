"""Exact single-service-area batching and safe payload calculation for Problem 1."""
from __future__ import annotations
from collections import Counter
from functools import lru_cache
from itertools import product
import json
from common import ROOT, KINDS, EPS


def direct_energy(physics, model, area, payload):
    e1, _ = physics.transport_leg(physics.legs["O01", area], model, payload)
    e2, _ = physics.transport_leg(physics.legs[area, "O01"], model, 0)
    return e1 + e2


def safe_payload(physics, model, area, reserve):
    budget = model["battery"] * (1 - reserve)
    if direct_energy(physics, model, area, 0) > budget + EPS:
        return None
    upper = float(model["capacity"])
    if direct_energy(physics, model, area, upper) <= budget + EPS:
        return upper
    lo, hi = 0.0, upper
    while hi - lo > 1e-8:
        mid = (lo + hi) / 2
        if direct_energy(physics, model, area, mid) <= budget:
            lo = mid
        else:
            hi = mid
    return lo


def solve_area(area, boxes, models, physics, reserve):
    area_boxes = [b for b in boxes.values() if b["area"] == area]
    queues = {kind: sorted([b["id"] for b in area_boxes if b["kind"] == kind]) for kind in KINDS}
    for kind in KINDS:
        signatures = {(boxes[i]["mass"], boxes[i]["volume"]) for i in queues[kind]}
        assert len(signatures) <= 1, ("count-state DP requires homogeneous area-kind boxes", area, kind)
    demand = tuple(len(queues[k]) for k in KINDS)
    patterns = []
    for count in product(*(range(x + 1) for x in demand)):
        if not sum(count):
            continue
        ids = [i for kind, n in zip(KINDS, count) for i in queues[kind][:n]]
        selected = {i: boxes[i] for i in ids}
        for gid, g in models.items():
            adjusted = dict(g, reserve_pct=reserve * 100)
            plan = physics.evaluate_route(adjusted, selected, (area,))
            if plan is not None:
                patterns.append({"counts": count, "model": gid, "energy": plan["energy"],
                                 "duration": plan["duration"]})
    predecessor = {}
    @lru_cache(None)
    def dp(state):
        if not any(state):
            return (0, 0.0, 0.0)
        best = None
        for p in patterns:
            if any(x > y for x, y in zip(p["counts"], state)):
                continue
            rest = tuple(y - x for x, y in zip(p["counts"], state))
            old = dp(rest)
            if old is None:
                continue
            value = (old[0] + 1, old[1] + p["energy"], old[2] + p["duration"])
            if best is None or value < best:
                best = value
                predecessor[state] = (rest, p)
        return best
    optimum = dp(demand)
    if optimum is None:
        return None
    state = demand
    out = []
    while any(state):
        state, pat = predecessor[state]
        ids = []
        for kind, n in zip(KINDS, pat["counts"]):
            ids += queues[kind][:n]
            queues[kind] = queues[kind][n:]
        plan = physics.evaluate_route(dict(models[pat["model"]], reserve_pct=reserve * 100),
                                      {i: boxes[i] for i in ids}, (area,))
        assert plan is not None
        out.append({"area": area, "model": pat["model"], "boxes": ids,
                    "mass": plan["mass"], "volume": plan["volume"],
                    "energy": plan["energy"], "duration": plan["duration"], "soc": plan["soc"]})
    assert not any(queues.values())
    return out


def solve(boxes, models, physics, sensitivity=(0, .1, .2, .3, .4, .5)):
    areas = sorted({b["area"] for b in boxes.values()})
    capacities = [{"area": a, "model": gid, "max_safe_kg": safe_payload(physics, g, a, .2)}
                  for a in areas for gid, g in models.items()]
    records = []
    for area in areas:
        solution = solve_area(area, boxes, models, physics, .2)
        if solution is None:
            raise RuntimeError(f"Problem 1 infeasible at {area}")
        records.extend(solution)
    for j, rec in enumerate(records, 1):
        rec["sortie"] = f"Q1-{j:03d}"
    assert Counter(i for r in records for i in r["boxes"]) == Counter({i: 1 for i in boxes})
    assert all(r["soc"] >= .2 - EPS for r in records)
    scenarios = []
    for reserve in sensitivity:
        by_area = {a: solve_area(a, boxes, models, physics, reserve) for a in areas}
        feasible = all(x is not None for x in by_area.values())
        chosen = [r for area in areas for r in (by_area[area] or [])] if feasible else []
        for j, rec in enumerate(chosen, 1):
            rec["sortie"] = f"Q1-{j:03d}"
        scenario_caps = [{"area": a, "model": gid,
                          "max_safe_kg": safe_payload(physics, g, a, reserve)}
                         for a in areas for gid, g in models.items()]
        scenarios.append({"reserve": reserve, "feasible": feasible,
                          "sorties": len(chosen) if feasible else None,
                          "energy_kwh": sum(r["energy"] for r in chosen) if feasible else None,
                          "cumulative_work_s": sum(r["duration"] for r in chosen) if feasible else None,
                          "infeasible_areas": [a for a in areas if by_area[a] is None],
                          "capacities": scenario_caps, "schedule": chosen})
    metrics = {"boxes": len(boxes), "sorties": len(records), "energy_kwh": sum(r["energy"] for r in records),
               "cumulative_work_s": sum(r["duration"] for r in records),
               "min_soc": min(r["soc"] for r in records), "constraint_violations": 0}
    result = {"metrics": metrics, "capacities": capacities, "schedule": records, "sensitivity": scenarios}
    result["validation"] = validate_solution(result, boxes, models, physics)
    return result


def validate_solution(solution, boxes, models, physics):
    """Independently check every feasible reserve scenario and count-state assumption."""
    areas = sorted({b["area"] for b in boxes.values()})
    scenarios = solution["sensitivity"]
    assert len(scenarios) > 0
    for row in scenarios:
        reserve = row["reserve"]
        assert len(row["capacities"]) == len(areas) * len(models)
        if not row["feasible"]:
            assert row["infeasible_areas"] and not row["schedule"]
            continue
        schedule = row["schedule"]
        assert Counter(i for r in schedule for i in r["boxes"]) == Counter({i: 1 for i in boxes})
        assert len({r["sortie"] for r in schedule}) == len(schedule)
        for route in schedule:
            area = route["area"]
            assert all(boxes[i]["area"] == area for i in route["boxes"])
            selected = {i: boxes[i] for i in route["boxes"]}
            plan = physics.evaluate_route(dict(models[route["model"]], reserve_pct=100 * reserve),
                                          selected, (area,))
            assert plan is not None
            assert abs(plan["energy"] - route["energy"]) < 1e-7
            assert abs(plan["duration"] - route["duration"]) < 1e-6
            assert abs(plan["mass"] - route["mass"]) < 1e-8
            assert abs(plan["volume"] - route["volume"]) < 1e-8
            assert route["soc"] + EPS >= reserve
        assert row["sorties"] == len(schedule)
        assert abs(row["energy_kwh"] - sum(r["energy"] for r in schedule)) < 1e-7
        assert abs(row["cumulative_work_s"] - sum(r["duration"] for r in schedule)) < 1e-6
    for earlier, later in zip(scenarios, scenarios[1:]):
        if earlier["reserve"] <= later["reserve"]:
            left = {(r["area"], r["model"]): r["max_safe_kg"] for r in earlier["capacities"]}
            for r in later["capacities"]:
                old, now = left[r["area"], r["model"]], r["max_safe_kg"]
                assert old is None or now is None or now <= old + 1e-6
    return {"passed": True, "violations": [], "feasible_scenarios_checked": sum(r["feasible"] for r in scenarios),
            "box_homogeneity_checked": True}


def save(solution):
    out = ROOT / "results" / "q1_reproduced"
    out.mkdir(parents=True, exist_ok=True)
    (out / "solution.json").write_text(json.dumps(solution, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
