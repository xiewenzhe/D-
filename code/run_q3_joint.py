"""Adapt the audited 24-sortie Q2 schedule and solve Q3 relay coverage.

The Q2 source is read-only. This program writes only results/q3_joint/.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from time import perf_counter

from common import ROOT, Physics, Terrain, read_inputs, charge_seconds
from problem2 import validate as validate_transport
from problem3 import (candidate_sites, direct_samples, gateway, link,
                      los_obstructed_exact, plan_relay, validate_joint)
from continuous_validation import certify_schedule

SOURCE = ROOT / "results" / "q2_improved" / "schedule.json"
OUT = ROOT / "results" / "q3_joint"


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
        # The two codebases use slightly different local WGS84 distance
        # approximations (roughly 25 microseconds on this example).
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


def probe(context):
    schedule, boxes, models, drones, batteries, physics, relay_model, relays, energy_stock, comm = context
    route = schedule[5]  # Q2-006: first direct outage at about 744 s.
    samples = direct_samples([route], physics, models, comm, step=20)
    gaps = [s for s in samples if not s["direct"]]
    sites = candidate_sites(physics, relay_model, comm, height_levels=(1.0,))
    if not gaps:
        raise RuntimeError("Expected a real direct-communication gap")
    covers = []
    for site in sites:
        if any(link(g["position"], "transport", site, "relay_access",
                    physics.terrain, comm, los_test=los_obstructed_exact)[0] for g in gaps):
            covers.append(site["id"])
    result = {"source": str(SOURCE.relative_to(ROOT)), "source_sha256": sha256(SOURCE),
              "source_sorties": len(schedule), "source_boxes": len(boxes),
              "route": route["sortie"], "samples": len(samples), "direct_gaps": len(gaps),
              "first_gap_s": gaps[0]["t"], "relay_sites": len(sites),
              "covering_sites": covers, "gateway": gateway(physics, comm)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("covering_sites", "gateway")}, ensure_ascii=False))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_q9(context):
    """Move Q2-009's nonurgent S009 box to a later independent sortie.

    This frees the urgent S012 delivery from a communications-incompatible
    two-stop path; the route and its resource use are recomputed from inputs.
    """
    schedule, boxes, models, drones, batteries, physics, relay_model, relays, energy_stock, comm = context
    base = next(r for r in schedule if r["sortie"] == "Q2-009")
    urgent_id = "S012-MED-01"
    regular_id = "S009-FOD-01"
    if set(base["boxes"]) != {urgent_id, regular_id}:
        raise ValueError("Unexpected Q2-009 contents")
    for r, bid, order in ((base, urgent_id, ("S012",)),):
        plan = physics.evaluate_route(models[r["model"]], {bid: boxes[bid]}, order)
        if plan is None:
            raise ValueError("Split urgent route infeasible")
        r.update(boxes=[bid], order=list(order), duration=plan["duration"],
                 end=r["start"] + plan["duration"], energy=plan["energy"],
                 soc=plan["soc"], stages=plan["stages"],
                 delivery={bid: r["start"] + plan["delivery_offsets"][bid]},
                 battery_ready=r["start"] + plan["duration"] +
                 charge_seconds(plan["soc"], batteries[r["model"]]["full_charge"]))
    plan = physics.evaluate_route(models[base["model"]],
                                  {regular_id: boxes[regular_id]}, ("S009",))
    if plan is None:
        raise ValueError("Split regular route infeasible")
    last_drone = max(r["end"] for r in schedule if r["drone"] == base["drone"])
    last_battery = max(r["battery_ready"] for r in schedule if r["battery"] == base["battery"])
    start = max(last_drone, last_battery, max(r["start"] for r in schedule))
    extra = dict(base, sortie="Q3-025", boxes=[regular_id], order=["S009"],
                 start=start, end=start + plan["duration"], duration=plan["duration"],
                 energy=plan["energy"], soc=plan["soc"], stages=plan["stages"],
                 delivery={regular_id: start + plan["delivery_offsets"][regular_id]},
                 battery_ready=start + plan["duration"] +
                 charge_seconds(plan["soc"], batteries[base["model"]]["full_charge"]),
                 **{"class": "regular"})
    schedule.append(extra)
    schedule.sort(key=lambda r: (r["start"], r["sortie"]))
    validate_transport(schedule, boxes, models, drones, batteries, physics)
    return context


def run(context, sample_step: float, pair_limit: int):
    schedule, boxes, models, drones, batteries, physics, relay_model, relays, energy_stock, comm = context
    began = perf_counter()
    solution, missions, sites, profiles, pair = plan_relay(
        schedule, boxes, models, drones, batteries, physics, relay_model, relays,
        energy_stock, comm, sample_step=sample_step, pair_limit=pair_limit,
        height_levels=(0.5, 0.75, 1.0), allow_start_shift=True)
    metrics, rows = validate_joint(solution, missions, boxes, models, drones,
                                   batteries, physics, relay_model, relays,
                                   energy_stock, comm, step=2)
    certificate = certify_schedule(solution, missions, physics, models, comm,
                                   initial_step=30, min_step=1e-4)
    metrics["continuous_validation_passed"] = certificate["passed"]
    metrics["continuous_certified_duration_s"] = certificate["certified_duration_s"]
    metrics["continuous_required_duration_s"] = certificate["required_duration_s"]
    metrics["continuous_unresolved_intervals"] = len(certificate["unresolved_intervals"])
    metrics["elapsed_s"] = perf_counter() - began
    metrics["source_sha256"] = sha256(SOURCE)
    metrics["relay_candidate_sites"] = len(sites)
    metrics["initial_pair"] = [s["id"] for s in pair]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "solution.json").write_text(json.dumps({"metrics": metrics, "transport": solution,
                                                     "relays": missions}, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    (OUT / "continuous_certificate.json").write_text(
        json.dumps(certificate, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "communication_samples.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def verify_existing(context, transport=None, missions=None, source=None, method="existing_incumbent"):
    """Independently re-evaluate a joint heuristic on current inputs.

    This is a feasible incumbent for Q3, not a claim that the source metrics
    were correct or that the joint problem was solved to global optimality.
    """
    schedule, boxes, models, drones, batteries, physics, relay_model, relays, energy_stock, comm = context
    if transport is None or missions is None:
        source = ROOT / "results" / "q3" / "solution.json"
        old = json.loads(source.read_text(encoding="utf-8"))
        transport, missions = old["transport"], old["relays"]
    metrics, rows = validate_joint(transport, missions, boxes, models, drones,
                                   batteries, physics, relay_model, relays,
                                   energy_stock, comm, step=1)
    certificate = certify_schedule(transport, missions, physics, models, comm,
                                   initial_step=30, min_step=1e-4)
    if not certificate["passed"]:
        raise RuntimeError(f"Continuous communication not proven: {len(certificate['unresolved_intervals'])} intervals")
    if not (metrics["unique_boxes"] == len(boxes) and
            metrics["hard_deadline_violations"] == 0 and
            metrics["resource_conflicts"] == 0 and metrics["relay_resource_conflicts"] == 0 and
            metrics["communication_breaks"] == 0):
        raise RuntimeError("Q3 incumbent violates a hard constraint")
    metrics.update(status="FEASIBLE_HEURISTIC", method=method,
                   source=str(source.relative_to(ROOT)),
                   source_sha256=sha256(source),
                   q2_source_sha256=sha256(SOURCE),
                   effective_fade_margin_db=comm["margin_db"],
                   continuous_validation_passed=True,
                   continuous_certified_duration_s=certificate["certified_duration_s"],
                   continuous_required_duration_s=certificate["required_duration_s"],
                   continuous_intervals=certificate["certified_intervals"],
                   continuous_min_margin_lower_bound_db=certificate["minimum_margin_lower_bound_db"],
                   global_optimality_proven=False)
    input_paths = sorted((ROOT / "数据").rglob("*.xlsx")) + sorted((ROOT / "数据").rglob("*.tif"))
    metrics["input_sha256"] = {str(p.relative_to(ROOT)): sha256(p) for p in input_paths}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "solution.json").write_text(json.dumps({"metrics": metrics, "transport": transport,
                                                     "relays": missions}, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    (OUT / "continuous_certificate.json").write_text(
        json.dumps(certificate, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "communication_samples.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    with (OUT / "transport_sorties.csv").open("w", newline="", encoding="utf-8-sig") as f:
        columns = ["sortie", "model", "drone", "battery", "order", "boxes", "start_s", "end_s", "energy_kwh", "return_soc"]
        writer = csv.DictWriter(f, fieldnames=columns); writer.writeheader()
        for r in transport:
            writer.writerow(dict(sortie=r["sortie"], model=r["model"], drone=r["drone"], battery=r["battery"],
                                 order=";".join(r["order"]), boxes=";".join(r["boxes"]),
                                 start_s=r["start"], end_s=r["end"], energy_kwh=r["energy"], return_soc=r["soc"]))
    with (OUT / "relay_sorties.csv").open("w", newline="", encoding="utf-8-sig") as f:
        columns = ["relay", "component", "site", "lon", "lat", "ground_m", "altitude_m", "agl_m",
                   "launch_s", "service_start_s", "service_end_s", "return_s", "energy_kwh", "return_soc", "component_ready_s"]
        writer = csv.DictWriter(f, fieldnames=columns); writer.writeheader()
        for m in missions:
            s = m["site"]
            writer.writerow(dict(relay=m["relay"], component=m["component"], site=s["id"],
                                 lon=s["lon"], lat=s["lat"], ground_m=s["ground"], altitude_m=s["z"],
                                 agl_m=s["z"]-s["ground"], launch_s=m["launch"],
                                 service_start_s=m["service_start"], service_end_s=m["service_end"],
                                 return_s=m["end"], energy_kwh=m["energy"], return_soc=m["soc"],
                                 component_ready_s=m["component_ready"]))
    with (OUT / "box_deliveries.csv").open("w", newline="", encoding="utf-8-sig") as f:
        columns = ["box", "area", "kind", "sortie", "delivery_s", "hard_due_s", "desired_s", "priority", "lateness_s"]
        writer = csv.DictWriter(f, fieldnames=columns); writer.writeheader()
        for r in transport:
            for bid, t in r["delivery"].items():
                b = boxes[bid]
                due = min([v for v in (b["deadline"], b["desired"] if b["kind"] == "MED" else None)
                           if v is not None], default=None)
                writer.writerow(dict(box=bid, area=b["area"], kind=b["kind"], sortie=r["sortie"],
                                     delivery_s=t, hard_due_s=due, desired_s=b["desired"],
                                     priority=b["priority"],
                                     lateness_s=max(0.0, t-b["desired"]) if b["desired"] is not None else 0.0))
    print(json.dumps({k: metrics[k] for k in ("status", "sorties", "unique_boxes", "relay_sorties",
                                             "joint_makespan_s", "total_energy_kwh", "weighted_tardiness_s",
                                             "late_boxes", "continuous_validation_passed",
                                             "continuous_intervals", "continuous_min_margin_lower_bound_db")},
                     ensure_ascii=False, indent=2))


def solve_from_q2_artifact(context):
    """Re-solve relay sites, service times and transport starts from Q2 routes."""
    schedule, boxes, models, drones, batteries, physics, relay_model, relays, energy_stock, comm = context
    source = ROOT / "results" / "q2" / "schedule.json"
    base = json.loads(source.read_text(encoding="utf-8"))["schedule"]
    validate_transport(base, boxes, models, drones, batteries, physics)
    comm["margin_db"] += 1.0  # robust design beyond the attachment's 8 dB requirement
    transport, missions, _, _, _ = plan_relay(
        base, boxes, models, drones, batteries, physics, relay_model, relays,
        energy_stock, comm, sample_step=5, pair_limit=30,
        height_levels=(0.25, 0.5, 0.75, 1.0), allow_start_shift=True)
    verify_existing(context, transport=transport, missions=missions, source=source,
                    method="q2_candidate_relay_joint_search")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("probe", "full", "verify-existing", "solve-from-q2"), default="probe")
    parser.add_argument("--sample-step", type=float, default=10)
    parser.add_argument("--pair-limit", type=int, default=20)
    parser.add_argument("--split-q9", action="store_true")
    args = parser.parse_args()
    ctx = load()
    if args.split_q9:
        ctx = split_q9(ctx)
    if args.mode == "probe":
        probe(ctx)
    elif args.mode == "full":
        run(ctx, args.sample_step, args.pair_limit)
    elif args.mode == "verify-existing":
        verify_existing(ctx)
    else:
        solve_from_q2_artifact(ctx)
