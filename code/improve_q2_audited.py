"""Improve the audited Q2 schedule without replacing its selected baseline.

The search optimizes small route-replacement neighborhoods using the original
CP-SAT model. It reports feasible improvements only; no global-optimality claim.
"""

from __future__ import annotations

from itertools import combinations, permutations
from pathlib import Path
import argparse
import json
import sys
import time

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OTHER_SRC = ROOT / "q1andq2-another_think/src"
sys.path.insert(0, str(OTHER_SRC))

from core import Data, RESULTS as OTHER_RESULTS, dump  # noqa: E402
from q2 import key, optimize, summarize, PROFILES  # noqa: E402


def objective(data, routes):
    w = PROFILES["balanced"]
    value = w["makespan"] * max(r["start"] + int(np.ceil(r["duration"])) for r in routes)
    for r in routes:
        value += w["wh"] * round(r["energy"] * 1000) + w["sorties"]
        for b, offset in r["completion"].items():
            completion = r["start"] + int(np.ceil(offset))
            box = data.boxes[b]
            value += box.priority * (
                w["completion"] * completion
                + w["tardiness"] * max(0, completion - box.desired)
            )
    return value


def neighborhood(data, pool, incumbent, rng, iteration):
    anchor = incumbent[int(rng.integers(len(incumbent)))]["order"][0]
    ranked = []
    for i, r in enumerate(incumbent):
        near = min(0 if anchor == s else data.legs[anchor, s]["distance"] for s in r["order"])
        # Every third iteration includes more distant routes to escape clusters.
        noise = 5000 if iteration % 3 == 2 else 1800
        ranked.append((near + rng.uniform(0, noise), i))
    count = int(rng.integers(5, 10))
    destroyed = [incumbent[i] for _, i in sorted(ranked)[:count]]
    box_ids = set(b for r in destroyed for b in r["boxes"])
    candidates = {key(r): r for r in incumbent}
    for r in pool:
        if set(r["boxes"]).issubset(box_ids):
            candidates[key(r)] = r
    # Exact unions of current route pairs may be missing from the random pool.
    for first, second in combinations(destroyed, 2):
        ids = first["boxes"] + second["boxes"]
        sites = sorted(set(first["order"] + second["order"]))
        if len(sites) > 3:
            continue
        for g in "ABC":
            for order in permutations(sites):
                r = data.route(g, ids, order)
                if r is not None and r["latest_start"] >= 0:
                    candidates[key(r)] = r
    return list(candidates.values()), count, len(box_ids)


def export_tables(data, routes, output):
    output.mkdir(parents=True, exist_ok=True)
    def write(name, records):
        pd.DataFrame(records).to_csv(output / name, index=False, encoding="utf-8-sig")

    write("sorties.csv", [dict(
        sortie=r["id"], drone=r["drone"], model=r["g"], battery=r["battery"],
        start_s=r["start"],
        takeoff_s=r["start"] + data.drones[r["g"]].prep + len(r["boxes"]) * data.drones[r["g"]].load,
        route="O01>" + ">".join(r["order"]) + ">O01", return_s=r["return"],
        energy_kwh=r["energy"], soc=r["soc"], mass_kg=r["mass"],
        volume_m3=r["volume"], boxes=";".join(r["boxes"])) for r in routes])
    write("deliveries.csv", [dict(
        box=b, sortie=r["id"], site=data.boxes[b].site,
        category=data.boxes[b].category, delivered_s=r["start"] + offset,
        desired_s=data.boxes[b].desired, hard_s=data.boxes[b].hard,
        lateness_s=max(0, r["start"] + offset - data.boxes[b].desired),
        priority=data.boxes[b].priority)
        for r in routes for b, offset in r["completion"].items()])
    write("batteries.csv", [dict(
        battery=r["battery"], sortie=r["id"], model=r["g"], start_s=r["start"],
        return_s=r["return"], soc_start=1, soc_return=r["soc"],
        charge_start_s=r["return"], charge_end_s=r["return"] + r["charge"],
        ready_reserved_s=r["battery_ready"], charge_duration_s=r["charge"])
        for r in routes])
    write("legs.csv", [dict(
        sortie=r["id"], model=r["g"], origin=leg["origin"],
        destination=leg["destination"], load_kg=leg["load"],
        start_s=r["start"] + leg["start_offset"],
        end_s=r["start"] + leg["end_offset"], energy_kwh=leg["energy"],
        **{k: v for k, v in data.legs[leg["origin"], leg["destination"]].items()
           if k not in {"origin", "destination"}})
        for r in routes for leg in r["legs"]])


def run(iterations, seconds, seed):
    data = Data()
    pool = json.loads((OTHER_RESULTS / "q2/candidate_pool.json").read_text(encoding="utf-8"))
    original = json.loads((OTHER_RESULTS / "q2/selected/schedule.json").read_text(encoding="utf-8"))
    fixed_path = OTHER_RESULTS / "q2/audit_fixed_routes/schedule.json"
    fixed = json.loads(fixed_path.read_text(encoding="utf-8")) if fixed_path.exists() else original
    incumbent = min((original, fixed), key=lambda rs: objective(data, rs))
    best = objective(data, incumbent)
    rng = np.random.default_rng(seed)
    rows = []
    output = ROOT / "results/q2_improved"
    output.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    for i in range(iterations):
        candidates, destroyed, affected_boxes = neighborhood(data, pool, incumbent, rng, i)
        solution, stats = optimize(data, candidates, f"audit_lns_{seed}_{i:02}",
                                   seconds=seconds, seed=seed + i, hint=incumbent)
        accepted = bool(solution) and objective(data, solution) < best
        if accepted:
            incumbent = solution
            best = objective(data, solution)
            dump(output / "schedule.json", incumbent)
        row = dict(iteration=i, candidate_count=len(candidates), destroyed_routes=destroyed,
                   affected_boxes=affected_boxes, solver_status=stats["status"],
                   solver_objective=stats.get("objective"), accepted=accepted,
                   incumbent_objective=best, sorties=len(incumbent),
                   energy_kwh=sum(r["energy"] for r in incumbent),
                   makespan_s=max(r["return"] for r in incumbent))
        rows.append(row)
        dump(output / "history.json", rows)
        print(json.dumps(row), flush=True)
    if not (output / "schedule.json").exists():
        dump(output / "schedule.json", incumbent)
    final = dict(name="audited_LNS_improvement", status="HEURISTIC_FEASIBLE",
                 objective=best, baseline_objective=objective(data, original),
                 global_optimality_proven=False, iterations=iterations,
                 seconds_per_iteration=seconds, seed=seed,
                 elapsed_s=time.perf_counter() - start,
                 **summarize(data, incumbent))
    dump(output / "summary.json", final)
    export_tables(data, incumbent, output)
    print(json.dumps(final), flush=True)
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=24)
    parser.add_argument("--seconds", type=float, default=8)
    parser.add_argument("--seed", type=int, default=20260923)
    args = parser.parse_args()
    run(args.iterations, args.seconds, args.seed)
