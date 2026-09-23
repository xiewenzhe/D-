"""Independent, read-only audit of q1andq2-another_think's selected Q2 result.

Uses this repository's separate GeoTIFF/physics implementation, not the solver's
MAT-based core. The command does not modify either Q2 result.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from csv import DictReader
from hashlib import sha256
from pathlib import Path
import argparse
import json
import math

from common import Physics, Terrain, charge_seconds, read_inputs


ROOT = Path(__file__).resolve().parents[1]
OTHER = ROOT / "q1andq2-another_think"
SELECTED = OTHER / "results/q2/selected"


def same(actual, expected, tolerance, label):
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"{label}: actual={actual}, exported={expected}")


def rows(name, result_dir):
    path = result_dir / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(DictReader(stream))


def main(result_dir=SELECTED):
    nodes, boxes, models, units, batteries, _, _, _, _ = read_inputs()
    physics = Physics(nodes, Terrain())
    scheduled = json.loads((result_dir / "schedule.json").read_text(encoding="utf-8"))
    summary = json.loads((result_dir / "summary.json").read_text(encoding="utf-8"))
    pool = json.loads((OTHER / "results/q2/candidate_pool.json").read_text(encoding="utf-8"))
    assert summary["status"] in {"FEASIBLE", "HEURISTIC_FEASIBLE"}
    assert len(pool) == 3988
    if result_dir == SELECTED:
        assert summary["candidate_count"] == len(pool)
    keys = [(r["g"], tuple(r["boxes"]), tuple(r["order"])) for r in pool]
    assert len(set(keys)) == len(keys), "duplicate candidate routes"
    pool_keys = set(keys)
    candidate_energy_error = candidate_duration_error = 0.0
    for r in pool:
        candidate = physics.evaluate_route(models[r["g"]],
                                           {b: boxes[b] for b in r["boxes"]},
                                           tuple(r["order"]))
        assert candidate is not None, (r["g"], r["boxes"], r["order"])
        candidate_energy_error = max(candidate_energy_error, abs(candidate["energy"] - r["energy"]))
        candidate_duration_error = max(candidate_duration_error, abs(candidate["duration"] - r["duration"]))
        same(candidate["energy"], r["energy"], 1e-5, "candidate energy")
        same(candidate["duration"], r["duration"], 1e-3, "candidate duration")
        assert r["latest_start"] >= -1e-8
    assert Counter(b for r in scheduled for b in r["boxes"]) == Counter(boxes.keys())

    # The alternative folder contains copies of the authoritative workbooks.
    input_matches = {}
    for label, name in (("nodes", "调度中心与服务区.xlsx"),
                        ("demand", "物资需求与配送时限.xlsx"),
                        ("transport", "运输无人机数据.xlsx")):
        paths = [next((ROOT / "数据").rglob(name)), next((OTHER / "data/raw").rglob(name))]
        digests = [sha256(p.read_bytes()).hexdigest() for p in paths]
        assert digests[0] == digests[1], name
        input_matches[label] = digests[0]

    by_drone = defaultdict(list)
    by_battery = defaultdict(list)
    deliveries = {}
    route_energy = 0.0
    leg_count = 0
    max_energy_delta = max_duration_delta = max_altitude_delta = 0.0
    for r in scheduled:
        g = r["g"]
        model = models[g]
        assert (g, tuple(r["boxes"]), tuple(r["order"])) in pool_keys, r["id"]
        assert r["drone"] in units and units[r["drone"]] == g
        assert r["battery"] in {f"{g}-BAT-{i+1:02}" for i in range(batteries[g]["count"])}
        assert r["start"] >= 0 and r["start"] == int(r["start"])
        chosen = {b: boxes[b] for b in r["boxes"]}
        independently = physics.evaluate_route(model, chosen, tuple(r["order"]))
        assert independently is not None, (r["id"], "payload, volume, or energy")
        assert len(independently["stages"]) == len(r["legs"]) + len(r["order"])
        max_energy_delta = max(max_energy_delta, abs(independently["energy"] - r["energy"]))
        max_duration_delta = max(max_duration_delta, abs(independently["duration"] - r["duration"]))
        same(independently["energy"], r["energy"], 1e-5, r["id"] + " energy")
        same(independently["duration"], r["duration"], 1e-3, r["id"] + " duration")
        same(r["return"], r["start"] + r["duration"], 1e-7, r["id"] + " return")
        same(independently["soc"], r["soc"], 1e-6, r["id"] + " SOC")
        same(charge_seconds(independently["soc"], batteries[g]["full_charge"]), r["charge"], 1e-3, r["id"] + " charge")
        same(r["reserved_return"], r["start"] + math.ceil(r["duration"]), 1e-7, r["id"] + " reserved return")
        same(r["battery_ready"], r["start"] + math.ceil(r["duration"] + r["charge"]), 1e-7, r["id"] + " battery ready")
        same(r["mass"], independently["mass"], 1e-8, r["id"] + " mass")
        same(r["volume"], independently["volume"], 1e-8, r["id"] + " volume")
        for b, off in independently["delivery_offsets"].items():
            same(off, r["completion"][b], 1e-3, r["id"] + " delivery offset")
            actual = r["start"] + off
            hard = min(boxes[b]["deadline"] if boxes[b]["first"] else math.inf,
                       boxes[b]["desired"] if boxes[b]["kind"] == "MED" else math.inf)
            assert actual <= hard + 1e-5, (b, actual, hard)
            deliveries[b] = actual
        by_drone[r["drone"]].append((r["start"], r["reserved_return"], r["id"]))
        by_battery[r["battery"]].append((r["start"], r["battery_ready"], r["id"]))
        route_energy += independently["energy"]
        flight_stages = [st for st in independently["stages"] if st["kind"] == "flight"]
        for leg, stage in zip(r["legs"], flight_stages):
            assert (leg["origin"], leg["destination"]) == (stage["from"], stage["to"])
            same(leg["load"], stage["payload"], 1e-8, r["id"] + " leg payload")
            same(leg["start_offset"], stage["begin"], 1e-3, r["id"] + " leg start")
            same(leg["end_offset"], stage["end"], 1e-3, r["id"] + " leg end")
            same(leg["energy"], stage["energy"], 1e-5, r["id"] + " leg energy")
            leg_count += 1
    assert len(deliveries) == 80

    transitions = 0
    min_drone_gap = min_battery_gap = math.inf
    for inventory, kind in ((by_drone, "drone"), (by_battery, "battery")):
        for resource, intervals in inventory.items():
            intervals.sort()
            for earlier, later in zip(intervals, intervals[1:]):
                gap = later[0] - earlier[1]
                assert gap >= 0, (kind, resource, earlier, later)
                transitions += 1
                if kind == "drone":
                    min_drone_gap = min(min_drone_gap, gap)
                else:
                    min_battery_gap = min(min_battery_gap, gap)

    # Reconstruct the exact integer objective used by CP-SAT.
    w = summary.get("weights", {"makespan": 100, "completion": 1,
                                "tardiness": 100, "wh": 10, "sorties": 10000})
    objective = w["makespan"] * max(r["start"] + math.ceil(r["duration"]) for r in scheduled)
    for b, actual in deliveries.items():
        completion = math.ceil(actual - next(r["start"] for r in scheduled if b in r["boxes"]))
        start = next(r["start"] for r in scheduled if b in r["boxes"])
        completion += start
        tardiness = max(0, completion - int(boxes[b]["desired"]))
        objective += int(boxes[b]["priority"]) * (w["completion"] * completion + w["tardiness"] * tardiness)
    objective += sum(w["wh"] * round(r["energy"] * 1000) + w["sorties"] for r in scheduled)
    same(objective, summary["objective"], 1e-7, "solver objective")

    sortie_csv = rows("sorties.csv", result_dir)
    delivery_csv = rows("deliveries.csv", result_dir)
    battery_csv = rows("batteries.csv", result_dir)
    leg_csv = rows("legs.csv", result_dir)
    if any((sortie_csv, delivery_csv, battery_csv, leg_csv)):
        assert (len(sortie_csv), len(delivery_csv), len(battery_csv), len(leg_csv)) == (
            len(scheduled), 80, len(scheduled), leg_count)
    for row in sortie_csv:
        r = next(r for r in scheduled if r["id"] == row["sortie"])
        assert (row["drone"], row["model"], row["battery"]) == (r["drone"], r["g"], r["battery"])
        assert row["route"] == "O01>" + ">".join(r["order"]) + ">O01"
        assert row["boxes"].split(";") == r["boxes"]
        same(float(row["start_s"]), r["start"], 1e-7, r["id"] + " CSV start")
        same(float(row["takeoff_s"]), r["start"] + models[r["g"]]["prepare"] + len(r["boxes"]) * models[r["g"]]["load_per_box"], 1e-7, r["id"] + " CSV takeoff")
        same(float(row["return_s"]), r["return"], 1e-7, r["id"] + " CSV return")
        same(float(row["energy_kwh"]), r["energy"], 1e-7, r["id"] + " CSV energy")
        same(float(row["soc"]), r["soc"], 1e-7, r["id"] + " CSV SOC")
        same(float(row["mass_kg"]), r["mass"], 1e-7, r["id"] + " CSV mass")
        same(float(row["volume_m3"]), r["volume"], 1e-7, r["id"] + " CSV volume")
    for row in delivery_csv:
        b = row["box"]
        r = next(r for r in scheduled if b in r["boxes"])
        assert (row["sortie"], row["site"]) == (r["id"], boxes[b]["area"])
        same(float(row["desired_s"]), boxes[b]["desired"], 1e-7, b + " CSV desired")
        same(float(row["delivered_s"]), deliveries[row["box"]], 1e-3, row["box"] + " CSV delivery")
        same(float(row["lateness_s"]), max(0, deliveries[b] - boxes[b]["desired"]), 1e-3, b + " CSV lateness")
        same(float(row["priority"]), boxes[b]["priority"], 1e-7, b + " CSV priority")
    for row in battery_csv:
        r = next(r for r in scheduled if r["id"] == row["sortie"])
        assert (row["battery"], row["model"]) == (r["battery"], r["g"])
        same(float(row["start_s"]), r["start"], 1e-7, r["id"] + " CSV battery start")
        same(float(row["return_s"]), r["return"], 1e-7, r["id"] + " CSV battery return")
        same(float(row["soc_start"]), 1, 1e-7, r["id"] + " CSV SOC start")
        same(float(row["soc_return"]), r["soc"], 1e-7, r["id"] + " CSV battery SOC")
        same(float(row["charge_start_s"]), r["return"], 1e-7, r["id"] + " CSV charge start")
        same(float(row["charge_duration_s"]), r["charge"], 1e-7, r["id"] + " CSV charge duration")
        same(float(row["charge_end_s"]), r["return"] + r["charge"], 1e-7, r["id"] + " CSV charge end")
        same(float(row["ready_reserved_s"]), r["battery_ready"], 1e-7, r["id"] + " CSV battery")
    for row, (r, source_leg) in zip(leg_csv, ((r, leg) for r in scheduled for leg in r["legs"])):
        assert (row["sortie"], row["model"], row["origin"], row["destination"]) == (
            r["id"], r["g"], source_leg["origin"], source_leg["destination"])
        leg = physics.legs[row["origin"], row["destination"]]
        same(float(row["load_kg"]), source_leg["load"], 1e-8, r["id"] + " CSV leg load")
        same(float(row["start_s"]), r["start"] + source_leg["start_offset"], 1e-3, r["id"] + " CSV leg start")
        same(float(row["end_s"]), r["start"] + source_leg["end_offset"], 1e-3, r["id"] + " CSV leg end")
        same(float(row["energy_kwh"]), source_leg["energy"], 1e-7, r["id"] + " CSV leg energy")
        max_altitude_delta = max(max_altitude_delta, abs(float(row["cruise_z"]) - leg["cruise"]))
        same(float(row["cruise_z"]), leg["cruise"], 1e-8, row["sortie"] + " cruise height")
        same(float(row["distance"]), leg["distance"], 1e-3, r["id"] + " CSV leg distance")
        same(float(row["climb"]), leg["up"], 1e-8, r["id"] + " CSV leg climb")
        same(float(row["descent"]), leg["down"], 1e-8, r["id"] + " CSV leg descent")

    values = {
        "result_dir": str(result_dir),
        "input_hashes_match": input_matches,
        "candidates": len(pool), "sorties": len(scheduled), "boxes": len(deliveries),
        "maximum_candidate_energy_difference_kwh": candidate_energy_error,
        "maximum_candidate_duration_difference_s": candidate_duration_error,
        "legs": leg_count, "resource_transitions": transitions,
        "used_drones": len(by_drone), "used_batteries": len(by_battery),
        "min_reserved_drone_gap_s": min_drone_gap,
        "min_reserved_battery_gap_s": min_battery_gap,
        "max_independent_energy_difference_kwh": max_energy_delta,
        "max_independent_duration_difference_s": max_duration_delta,
        "max_independent_cruise_altitude_difference_m": max_altitude_delta,
        "independent_energy_kwh": route_energy,
        "latest_return_s": max(r["return"] for r in scheduled),
        "late_boxes": sum(deliveries[b] > boxes[b]["desired"] + 1e-6 for b in boxes),
        "hard_violations": 0,
        "minimum_hard_slack_s": min(
            min(boxes[b]["deadline"] if boxes[b]["first"] else math.inf,
                boxes[b]["desired"] if boxes[b]["kind"] == "MED" else math.inf) - t
            for b, t in deliveries.items()
            if boxes[b]["first"] or boxes[b]["kind"] == "MED"),
        "reconstructed_integer_objective": objective,
        "status": "PASS",
    }
    print(json.dumps(values, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", type=Path, default=SELECTED)
    args = parser.parse_args()
    main(args.result_dir.resolve())
