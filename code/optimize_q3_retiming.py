"""Improve the audited Q3 schedule by tightening relay windows and retiming routes.

The original Q3 files stay untouched.  Two validated alternatives are written
to results/q3_optimized/: a faster original-order schedule and a schedule that
visits S014 first on Q2-020 to reduce weighted tardiness.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from math import ceil
from pathlib import Path
import argparse
import csv
import json

from common import ROOT, charge_seconds
from continuous_validation import certify_schedule, support_rows
from problem2 import validate as validate_transport
from problem3 import update_mission, validate_joint, los_obstructed_exact
from problem4 import solve as solve_partitions
from run_q3_joint import load, gap_window
import problem3


SOURCE = ROOT / "results" / "q3"
OUTPUT = ROOT / "results" / "q3_optimized"
TIME_GUARD_S = 0.02
SUPPORT_GUARD_S = 0.05


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def support_bounds(certificate, mission_index):
    rows = [row for row in certificate["intervals"] if row["mission"] == mission_index]
    if not rows:
        raise ValueError(f"Mission {mission_index} has no certified support")
    return min(row["start_s"] for row in rows), max(row["end_s"] for row in rows)


def shift_route(route, seconds):
    for key in ("start", "end", "battery_ready"):
        route[key] -= seconds
    route["delivery"] = {bid: t - seconds for bid, t in route["delivery"].items()}


def shift_mission(mission, seconds):
    for key in ("launch", "service_start", "service_end", "end", "component_ready"):
        mission[key] -= seconds


def build_fast(source, old_certificate, relay_model, energy_stock):
    schedule = deepcopy(source["transport"])
    missions = deepcopy(source["relays"])
    by_id = {route["sortie"]: route for route in schedule}
    if len(missions) != 5 or set(("Q2-019", "Q2-020")) - by_id.keys():
        raise ValueError("This retiming applies to the audited five-relay Q3 schedule")

    # Mission 2 ends after its final certified support interval.
    _, last_2 = support_bounds(old_certificate, 2)
    missions[2]["service_end"] = last_2 + TIME_GUARD_S
    if not update_mission(missions[2], missions[2]["service_end"], relay_model, energy_stock):
        raise ValueError("Mission 2 cannot be shortened")

    # Bring mission 3 forward to the earliest free R02 time, then move the
    # only route it supports until its first support almost touches the window.
    earlier_3 = missions[3]["launch"] - (
        missions[2]["end"] + relay_model["turnaround"] + TIME_GUARD_S
    )
    if earlier_3 < 0:
        raise ValueError("Mission 3 has no earlier launch window")
    missions[3]["launch"] -= earlier_3
    missions[3]["service_start"] -= earlier_3
    first_3, last_3 = support_bounds(old_certificate, 3)
    earlier_19 = first_3 - missions[3]["service_start"] - SUPPORT_GUARD_S
    if earlier_19 < 0:
        raise ValueError("Q2-019 has no earlier communication window")
    shift_route(by_id["Q2-019"], earlier_19)
    missions[3]["service_end"] = last_3 - earlier_19 + TIME_GUARD_S
    if not update_mission(missions[3], missions[3]["service_end"], relay_model, energy_stock):
        raise ValueError("Mission 3 cannot be shortened")

    # R02 can now perform its final mission earlier.  Keep Q2-020 aligned
    # with the same relay service interval, preserving its flight trajectory.
    earlier_4 = missions[4]["launch"] - (
        missions[3]["end"] + relay_model["turnaround"] + TIME_GUARD_S
    )
    if earlier_4 < 0:
        raise ValueError("Mission 4 has no earlier launch window")
    shift_mission(missions[4], earlier_4)
    shift_route(by_id["Q2-020"], earlier_4)
    return schedule, missions, {
        "mission_3_launch_advance_s": earlier_3,
        "Q2_019_advance_s": earlier_19,
        "mission_4_and_Q2_020_advance_s": earlier_4,
    }


def set_reversed_route(route, start, boxes, models, batteries, physics):
    selected = {bid: boxes[bid] for bid in route["boxes"]}
    if set(route["order"]) != {"S011", "S014"}:
        raise ValueError("Unexpected Q2-020 stops")
    plan = physics.evaluate_route(models[route["model"]], selected, ("S014", "S011"))
    if plan is None:
        raise ValueError("The reversed Q2-020 route is physically infeasible")
    route.update(
        order=list(plan["order"]), start=start, end=start + plan["duration"],
        duration=plan["duration"], energy=plan["energy"], soc=plan["soc"],
        stages=plan["stages"], mass=plan["mass"], volume=plan["volume"],
        battery_ready=start + plan["duration"] + charge_seconds(
            plan["soc"], batteries[route["model"]]["full_charge"]
        ),
        delivery={bid: start + offset for bid, offset in plan["delivery_offsets"].items()},
    )


def build_timely(fast_schedule, fast_missions, context):
    _, boxes, models, _, batteries, physics, _, _, _, comm = context
    schedule = deepcopy(fast_schedule)
    missions = deepcopy(fast_missions)
    route = next(row for row in schedule if row["sortie"] == "Q2-020")
    set_reversed_route(route, route["start"], boxes, models, batteries, physics)
    gap_first, _ = gap_window(route, physics, models, comm)

    # Align the new first-stop gap with the existing S010 relay and leave a
    # short timing guard.  Full certification follows; this is not an exact
    # earliest-start search.
    selected = 10 * ceil((missions[4]["service_start"] - gap_first + 4) / 10)
    set_reversed_route(route, selected, boxes, models, batteries, physics)
    proof = certify_schedule(schedule, missions, physics, models, comm)
    if not proof["passed"]:
        raise RuntimeError("The guarded reversed route failed certification")
    return schedule, missions, {"Q2_020_reversed_start_s": selected,
                                "sampled_direct_gap_first_offset_s": gap_first}


def validate(schedule, missions, context, *, require_three_groups=True):
    _, boxes, models, drones, batteries, physics, relay_model, relays, energy_stock, comm = context
    validate_transport(schedule, boxes, models, drones, batteries, physics)
    original = problem3.los_obstructed
    problem3.los_obstructed = los_obstructed_exact
    try:
        metrics, samples = validate_joint(
            schedule, missions, boxes, models, drones, batteries, physics,
            relay_model, relays, energy_stock, comm, step=1,
        )
    finally:
        problem3.los_obstructed = original
    certificate = certify_schedule(schedule, missions, physics, models, comm)
    if not certificate["passed"] or certificate["unresolved_intervals"]:
        raise RuntimeError("Continuous communication certificate failed")
    metrics.update(
        status="FEASIBLE_HEURISTIC", method="audited_relay_window_retiming",
        continuous_validation_passed=True,
        continuous_min_margin_lower_bound_db=certificate["minimum_margin_lower_bound_db"],
        global_optimality_proven=False,
    )
    try:
        partitions = solve_partitions(
            schedule, missions, support_rows(certificate), boxes, drones,
            batteries, relays, energy_stock, relay_model,
        )
    except ValueError as exc:
        if require_three_groups or "indivisible groups" not in str(exc):
            raise
        from problem4 import components, relay_support
        areas = sorted({box["area"] for box in boxes.values()})
        support = relay_support(schedule, missions, support_rows(certificate))
        atoms = components(areas, schedule, missions, support)
        partitions = {"validation": {"passed": False, "reason": str(exc)},
                      "components": atoms}
    return metrics, samples, certificate, partitions


def write_candidate(name, schedule, missions, changes, checked):
    metrics, samples, certificate, partitions = checked
    target = OUTPUT / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "solution.json").write_text(json.dumps(
        {"metrics": metrics, "transport": schedule, "relays": missions},
        ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "continuous_certificate.json").write_text(json.dumps(
        certificate, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "partitions.json").write_text(json.dumps(
        partitions, ensure_ascii=False, indent=2), encoding="utf-8")
    with (target / "communication_samples.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(samples[0]))
        writer.writeheader()
        writer.writerows(samples)
    summary = {key: metrics[key] for key in (
        "weighted_tardiness_s", "joint_makespan_s", "energy_kwh",
        "relay_energy_kwh", "total_energy_kwh", "sorties", "relay_sorties",
        "hard_deadline_violations", "resource_conflicts", "relay_resource_conflicts",
        "communication_breaks", "continuous_validation_passed",
        "continuous_min_margin_lower_bound_db",
    )}
    if "partitions" in partitions:
        summary.update(changes=changes, q4_three_group_feasible=True,
                       q4_two_group_shortage=partitions["partitions"][2]["shortage_total"],
                       q4_three_group_shortage=partitions["partitions"][3]["shortage_total"])
    else:
        summary.update(changes=changes, q4_three_group_feasible=False,
                       q4_indivisible_groups=len(partitions["components"]))
    (target / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-timely", action="store_true", help="Only write the faster original-order alternative")
    args = parser.parse_args()
    source_path = SOURCE / "solution.json"
    original = read_json(source_path)
    certificate = read_json(SOURCE / "continuous_certificate.json")
    if not certificate["passed"]:
        raise ValueError("The audited Q3 source has no continuous certificate")
    context = load()
    fast, missions, changes = build_fast(original, certificate, context[6], context[8])
    fast_summary = write_candidate("fast", fast, missions, changes, validate(fast, missions, context))
    print("fast", json.dumps(fast_summary, ensure_ascii=False), flush=True)
    comparison = {"baseline_source_sha256": sha256(source_path.read_bytes()).hexdigest(),
                  "baseline": {key: original["metrics"][key] for key in (
                      "weighted_tardiness_s", "joint_makespan_s", "total_energy_kwh")},
                  "fast": fast_summary}
    if not args.skip_timely:
        timely, relay_jobs, changes = build_timely(fast, missions, context)
        timely_summary = write_candidate(
            "timely", timely, relay_jobs, changes, validate(timely, relay_jobs, context))
        print("timely", json.dumps(timely_summary, ensure_ascii=False), flush=True)
        comparison["timely"] = timely_summary
        comparison["preferred_under_objective_order"] = "timely"
    comparison["objective_order"] = ["weighted_tardiness_s", "joint_makespan_s",
                                     "total_energy_kwh", "sorties_plus_relay_sorties"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "comparison.json").write_text(json.dumps(
        comparison, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
