"""Recompute paper diagnostics from the audited Q2/Q3 output files."""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def read_csv(path: str):
    with (ROOT / path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def peak(intervals):
    events = sorted((t, delta) for a, b in intervals for t, delta in ((a, 1), (b, -1)))
    active = high = 0
    for _, delta in sorted(events, key=lambda row: (row[0], row[1])):
        active += delta
        high = max(high, active)
    return high


def q2_objective(routes, boxes):
    makespan = 100 * max(int(r["start"]) + math.ceil(r["duration"]) for r in routes)
    completion = 0
    tardiness = 0
    for route in routes:
        for box, offset in route["completion"].items():
            when = int(route["start"]) + math.ceil(offset)
            weight, desired = boxes[box]
            completion += weight * when
            tardiness += 100 * weight * max(0, when - desired)
    energy = sum(10 * round(1000 * r["energy"]) for r in routes)
    sortie = 10000 * len(routes)
    return dict(makespan=makespan, weighted_completion=completion,
                weighted_tardiness=tardiness, energy=energy, sortie=sortie,
                total=makespan + completion + tardiness + energy + sortie)


def main():
    final = read_json("results/q2_improved/schedule.json")
    original = read_json("q1andq2-another_think/results/q2/selected/schedule.json")
    deliveries = read_csv("results/q2_improved/deliveries.csv")
    boxes = {row["box"]: (int(float(row["priority"])), int(float(row["desired_s"])))
             for row in deliveries}
    objective = {"original": q2_objective(original, boxes), "final": q2_objective(final, boxes)}
    assert objective["original"]["total"] == 4290638
    assert objective["final"]["total"] == 4281382
    resources = {}
    for model in "ABC":
        subset = [r for r in final if r["g"] == model]
        resources[model] = {
            "sorties": len(subset),
            "boxes": sum(len(r["boxes"]) for r in subset),
            "energy_kwh": sum(r["energy"] for r in subset),
            "peak_drones": peak((r["start"], r["return"]) for r in subset),
            "peak_batteries": peak((r["start"], r["battery_ready"]) for r in subset),
        }
    multistop = [{"id": r["id"], "order": r["order"], "boxes": len(r["boxes"]),
                  "energy_kwh": r["energy"], "duration_s": r["duration"]}
                 for r in final if len(r["order"]) > 1]
    candidates = read_json("q1andq2-another_think/results/q2/candidate_pool.json")
    candidate_counts = {"total": len(candidates),
                        "single_area": sum(len(r["order"]) == 1 for r in candidates),
                        "multi_area": sum(len(r["order"]) > 1 for r in candidates)}

    q3 = read_json("results/q3/solution.json")
    certificate = read_json("results/q3/continuous_certificate.json")
    relay_rows = []
    for index, mission in enumerate(q3["relays"]):
        segments = [r for r in certificate["intervals"] if r["mission"] == index]
        relay_rows.append({
            "index": index + 1, "relay": mission["relay"],
            "site": mission["site"]["id"] if isinstance(mission["site"], dict) else mission["site"],
            "transport_sorties_supported": len({r["sortie"] for r in segments}),
            "certified_support_s": sum(r["end_s"] - r["start_s"] for r in segments),
            "energy_kwh": mission["energy"], "return_soc": mission["soc"],
        })
    by_sortie = defaultdict(lambda: Counter())
    for item in certificate["intervals"]:
        by_sortie[item["sortie"]][item["mode"]] += item["end_s"] - item["start_s"]
    relay_dependence = sorted(({
        "sortie": sortie, "relay_s": counter["relay"],
        "direct_s": counter["direct"],
        "relay_fraction": counter["relay"] / sum(counter.values()),
    } for sortie, counter in by_sortie.items()), key=lambda row: -row["relay_fraction"])
    q2_by_id = {r["id"]: r for r in final}
    start_changes = sorted(({
        "sortie": r["sortie"], "q2_start_s": q2_by_id[r["sortie"]]["start"],
        "q3_start_s": r["start"], "change_s": r["start"] - q2_by_id[r["sortie"]]["start"],
    } for r in q3["transport"]), key=lambda row: -row["change_s"])
    q3_deliveries = read_csv("results/q3/box_deliveries.csv")
    hard_slack = sorted(({
        "box": row["box"], "sortie": row["sortie"],
        "slack_s": float(row["hard_due_s"]) - float(row["delivery_s"]),
    } for row in q3_deliveries if row["hard_due_s"]), key=lambda row: row["slack_s"])
    tightest_link = min(certificate["intervals"], key=lambda row: row["margin_lower_bound_db"])
    result = {"q2_objective": objective, "q2_resources": resources,
              "q2_multistop": multistop, "q2_candidates": candidate_counts,
              "q3_relay_missions": relay_rows,
              "q3_most_relay_dependent": relay_dependence[:6],
              "q3_start_changes": start_changes,
              "q3_hard_slack": hard_slack[:8], "q3_tightest_link": tightest_link}
    out = ROOT / "results" / "q23_paper_diagnostics.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
