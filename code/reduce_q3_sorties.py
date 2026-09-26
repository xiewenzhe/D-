"""Reduce audited Q3 transport sorties while preserving full validation.

The default run builds Q4-compatible 23-, 22-, and 21-transport-sortie
alternatives.  An optional 20-sortie experiment passes Q3 checks but cannot
form the three indivisible groups required by Q4.  Relay count stays at five.
Original and retiming artifacts remain untouched.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import argparse
import json

from common import ROOT, charge_seconds
from problem3 import (gateway, hover_limit, link, sample_times,
                      transport_position, update_mission)
from optimize_q3_retiming import (read_json, shift_mission, shift_route,
                                  validate, write_candidate)
from run_q3_joint import load


SOURCE_DIR = ROOT / "results" / "q3_optimized"
ADVANCE_S = 25.0


def apply_plan(route, plan, start, drone, battery, batteries):
    route.update(
        boxes=plan["boxes"], order=plan["order"], mass=plan["mass"],
        volume=plan["volume"], energy=plan["energy"], soc=plan["soc"],
        duration=plan["duration"], stages=plan["stages"], start=start,
        end=start + plan["duration"],
        battery_ready=start + plan["duration"] + charge_seconds(
            plan["soc"], batteries["C"]["full_charge"]),
        delivery={bid: start + offset for bid, offset in plan["delivery_offsets"].items()},
        model="C", drone=drone, battery=battery,
    )


def build_23(source, context):
    _, boxes, models, _, batteries, physics, _, _, _, _ = context
    schedule = deepcopy(source["transport"])
    missions = deepcopy(source["relays"])
    by_id = {row["sortie"]: row for row in schedule}
    early, late = by_id["Q2-003"], by_id["Q2-021"]
    ids = early["boxes"] + late["boxes"]
    plan = physics.evaluate_route(models["C"], {bid: boxes[bid] for bid in ids}, ("S011", "S005"))
    if plan is None:
        raise ValueError("Q2-003 and Q2-021 cannot be merged")
    apply_plan(late, plan, late["start"], late["drone"], late["battery"], batteries)
    schedule.remove(early)
    return schedule, missions, {"removed_sortie": "Q2-003",
                                "merged_into": "Q2-021", "new_order": ["S011", "S005"]}


def required_relay_end(route, missions, physics, models, comm):
    gate = gateway(physics, comm)
    provider = missions[0]["site"]
    needed = []
    for t in sample_times(route, step=1):
        pos = transport_position(route, t, physics, models)
        if link(pos, "transport", gate, "gateway", physics.terrain, comm)[0]:
            continue
        if any(m["service_start"] <= t <= m["service_end"] and
               link(pos, "transport", m["site"], "relay_access", physics.terrain, comm)[0]
               for m in missions):
            continue
        if not link(pos, "transport", provider, "relay_access", physics.terrain, comm)[0]:
            raise ValueError(f"The long relay cannot serve Q2-021 at {t:.3f} s")
        needed.append(t)
    return max(needed, default=missions[0]["service_end"]) + 3.0


def build_22(schedule_23, missions_23, context):
    _, boxes, models, _, batteries, physics, relay_model, _, energy_stock, comm = context
    schedule = deepcopy(schedule_23)
    missions = deepcopy(missions_23)
    by_id = {row["sortie"]: row for row in schedule}

    # Shift the last user of relay mission 2, then bring relay mission 3 and
    # Q2-019 forward together.  This frees enough long-relay hover reserve.
    shift_route(by_id["Q2-015"], ADVANCE_S)
    missions[2]["service_end"] -= ADVANCE_S
    if not update_mission(missions[2], missions[2]["service_end"], relay_model, energy_stock):
        raise ValueError("Relay mission 2 cannot be shortened")
    shift_mission(missions[3], ADVANCE_S)
    shift_route(by_id["Q2-019"], ADVANCE_S)

    # Move the S011/S005 C sortie to U07 after Q2-019.  The vacated U08 slot
    # carries both late S003 batches as one C sortie before their desired time.
    late = by_id["Q2-021"]
    late_plan = physics.evaluate_route(
        models["C"], {bid: boxes[bid] for bid in late["boxes"]}, ("S011", "S005"))
    if late_plan is None:
        raise ValueError("The merged S011/S005 route became infeasible")
    apply_plan(late, late_plan, by_id["Q2-019"]["end"] + 0.01, "U07", "C04", batteries)

    old_a, old_b = by_id["Q2-022"], by_id["Q2-023"]
    ids = old_a["boxes"] + old_b["boxes"]
    plan = physics.evaluate_route(models["C"], {bid: boxes[bid] for bid in ids}, ("S003",))
    if plan is None:
        raise ValueError("The two S003 routes cannot be merged")
    combined = {"sortie": "Q3-M01", "class": "regular"}
    apply_plan(combined, plan, by_id["Q2-012"]["end"] + 0.01, "U08", "C01", batteries)
    schedule.remove(old_a)
    schedule.remove(old_b)
    schedule.append(combined)

    relay_end = required_relay_end(late, missions, physics, models, comm)
    maximum = missions[0]["service_start"] + hover_limit(missions[0]["site"], relay_model)
    if relay_end > maximum - 0.5:
        raise ValueError(f"Long relay requires {relay_end:.3f} s, max {maximum:.3f} s")
    missions[0]["service_end"] = relay_end
    if not update_mission(missions[0], relay_end, relay_model, energy_stock):
        raise ValueError("Long relay return reserve failed")
    return schedule, missions, {
        "removed_sorties": ["Q2-003", "Q2-022", "Q2-023"],
        "new_sortie": "Q3-M01", "Q2_015_and_Q2_019_advance_s": ADVANCE_S,
        "long_relay_service_end_s": relay_end,
    }


def build_21(schedule_22, missions_22, context):
    _, boxes, models, _, batteries, physics, _, _, _, _ = context
    schedule = deepcopy(schedule_22)
    missions = deepcopy(missions_22)
    by_id = {row["sortie"]: row for row in schedule}
    early, combined = by_id["Q2-001"], by_id["Q3-M01"]
    ids = early["boxes"] + combined["boxes"]
    plan = physics.evaluate_route(models["C"], {bid: boxes[bid] for bid in ids}, ("S003",))
    if plan is None:
        raise ValueError("Q2-001 cannot fit in the combined S003 sortie")
    apply_plan(combined, plan, combined["start"], combined["drone"],
               combined["battery"], batteries)
    schedule.remove(early)
    return schedule, missions, {"removed_sortie": "Q2-001",
                                "merged_into": "Q3-M01", "combined_S003_boxes": len(ids)}


def build_20(schedule_21, missions_21, context):
    _, boxes, models, _, batteries, physics, _, _, _, _ = context
    schedule = deepcopy(schedule_21)
    missions = deepcopy(missions_21)
    by_id = {row["sortie"]: row for row in schedule}

    def replan(rid, ids, order, start, drone, battery):
        route = by_id[rid]
        plan = physics.evaluate_route(models["C"], {bid: boxes[bid] for bid in ids}, order)
        if plan is None:
            raise ValueError(f"Infeasible 20-sortie route: {rid}")
        apply_plan(route, plan, start, drone, battery, batteries)
        return route

    # One C route now serves S006 and S007; R02 support for the former S007
    # sortie is no longer needed.  Reassign the later C routes and batteries.
    early = by_id["Q2-008"]
    replan("Q2-008", early["boxes"] + by_id["Q2-011"]["boxes"],
           ("S006", "S007"), early["start"], "U08", "C02")
    schedule.remove(by_id["Q2-011"])
    second = by_id["Q2-014"]
    replan("Q2-014", second["boxes"], ("S001",), early["end"] + 0.01,
           "U08", "C04")
    by_id["Q2-012"]["drone"] = "U07"
    fourth = by_id["Q2-019"]
    start_19 = max(fourth["start"], second["end"] + 0.01,
                   by_id["Q2-007"]["battery_ready"] + 0.01)
    replan("Q2-019", fourth["boxes"], ("S004",), start_19, "U08", "C01")
    fifth = by_id["Q2-021"]
    start_21 = max(fifth["start"], fourth["end"] + 0.01,
                   second["battery_ready"] + 0.01)
    replan("Q2-021", fifth["boxes"], ("S011", "S005"), start_21, "U08", "C04")
    merged = by_id["Q3-M01"]
    start_merged = max(merged["start"], by_id["Q2-012"]["end"] + 0.01,
                       early["battery_ready"] + 0.01)
    replan("Q3-M01", merged["boxes"], ("S003",), start_merged, "U07", "C02")
    return schedule, missions, {"removed_sortie": "Q2-011",
                                "merged_into": "Q2-008", "new_order": ["S006", "S007"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", choices=("fast", "timely"), default="fast")
    parser.add_argument("--q3-only-20", action="store_true",
                        help="Also validate and save the 20-transport Q3-only experiment")
    args = parser.parse_args()
    source_path = SOURCE_DIR / args.base / "solution.json"
    source = read_json(source_path)
    context = load()
    schedule_23, missions_23, changes_23 = build_23(source, context)
    name_23 = f"fewer_23_{args.base}"
    summary_23 = write_candidate(name_23, schedule_23, missions_23, changes_23,
                                 validate(schedule_23, missions_23, context))
    print(name_23, json.dumps(summary_23, ensure_ascii=False), flush=True)
    schedule_22, missions_22, changes_22 = build_22(schedule_23, missions_23, context)
    name_22 = f"fewer_22_{args.base}"
    summary_22 = write_candidate(name_22, schedule_22, missions_22, changes_22,
                                 validate(schedule_22, missions_22, context))
    print(name_22, json.dumps(summary_22, ensure_ascii=False), flush=True)
    schedule_21, missions_21, changes_21 = build_21(schedule_22, missions_22, context)
    name_21 = f"fewer_21_{args.base}"
    summary_21 = write_candidate(name_21, schedule_21, missions_21, changes_21,
                                 validate(schedule_21, missions_21, context))
    print(name_21, json.dumps(summary_21, ensure_ascii=False), flush=True)
    comparison = {"base": args.base, "source_sha256": sha256(source_path.read_bytes()).hexdigest(),
                  "source_metrics": {key: source["metrics"][key] for key in (
                      "sorties", "relay_sorties", "weighted_tardiness_s",
                      "joint_makespan_s", "total_energy_kwh")},
                  name_23: summary_23, name_22: summary_22,
                  name_21: summary_21}
    if args.q3_only_20:
        schedule_20, missions_20, changes_20 = build_20(schedule_21, missions_21, context)
        name_20 = f"q3_only_20_{args.base}"
        summary_20 = write_candidate(
            name_20, schedule_20, missions_20, changes_20,
            validate(schedule_20, missions_20, context, require_three_groups=False))
        print(name_20, json.dumps(summary_20, ensure_ascii=False), flush=True)
        comparison[name_20] = summary_20
    (SOURCE_DIR / f"sortie_comparison_{args.base}.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
