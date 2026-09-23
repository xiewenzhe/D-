"""Reproduce Q3 data, process and result figures from verified evidence."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from PIL import Image

from common import ROOT, Physics, Terrain, read_inputs
from problem3 import candidate_sites, direct_samples, link
from run_q3_joint import load

FIG = ROOT / "figures"
BLUE, ORANGE, GREEN, GREY = "#0072B2", "#E69F00", "#009E73", "#666666"
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "pdf.fonttype": 42, "svg.fonttype": "none"})


def save(fig, name, size=(6.6, 3.8)):
    fig.set_size_inches(*size)
    for suffix in ("pdf", "svg", "png"):
        fig.savefig(FIG / f"{name}.{suffix}", dpi=300, bbox_inches="tight")
    preview = FIG / "previews"
    preview.mkdir(exist_ok=True)
    Image.open(FIG / f"{name}.png").convert("L").save(preview / f"{name}_grayscale.png", dpi=(300, 300))
    plt.close(fig)


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    data = json.loads((ROOT / "results" / "q3" / "solution.json").read_text(encoding="utf-8"))
    cert = json.loads((ROOT / "results" / "q3" / "continuous_certificate.json").read_text(encoding="utf-8"))
    box = pd.read_csv(ROOT / "results" / "q3" / "box_deliveries.csv")
    trs, rel = data["transport"], data["relays"]
    q2, boxes, models, drones, batteries, phys, relay_model, relays, stocks, comm = load()

    # Raw 1: DEM and task geography.
    fig, ax = plt.subplots()
    dem = phys.terrain
    extent = [dem.x0, dem.x0 + dem.dx * dem.grid.shape[1],
              dem.y0 - dem.dy * dem.grid.shape[0], dem.y0]
    stride = 4  # display-only decimation; all geometry calculations use the full DEM
    lons = dem.x0 + (np.arange(0, dem.grid.shape[1], stride)+.5)*dem.dx
    lats = dem.y0 - (np.arange(0, dem.grid.shape[0], stride)+.5)*dem.dy
    im = ax.contourf(lons, lats, dem.grid[::stride, ::stride], levels=12, cmap="terrain")
    for nid, n in phys.nodes.items():
        ax.scatter(n["lon"], n["lat"], s=27 if nid == "O01" else 13,
                   c=ORANGE if nid == "O01" else BLUE, edgecolor="white", linewidth=.4)
    ax.set(xlabel="Longitude (deg)", ylabel="Latitude (deg)")
    fig.colorbar(im, ax=ax, label="DEM elevation (m)", shrink=.8)
    save(fig, "raw_q3_dem_nodes")

    # Raw 2: due-time/priority structure, showing every box rather than group means.
    fig, ax = plt.subplots()
    kinds = ["MED", "WAT", "FOD", "HYG"]
    for j, kind in enumerate(kinds):
        subset = box[box.kind == kind]
        ax.scatter(subset.desired_s / 3600, np.full(len(subset), j) +
                   np.linspace(-.17, .17, len(subset)), s=subset.priority*2,
                   color=BLUE, edgecolor="none", alpha=.85)
    ax.set(xlabel="Desired delivery time (h)", yticks=range(4), yticklabels=kinds)
    ax.grid(axis="x", alpha=.2)
    for w in (4, 12, 24):
        ax.scatter([], [], s=w*2, color=BLUE, label=f"priority {w}")
    ax.legend(frameon=False, fontsize=7, loc="upper right")
    save(fig, "raw_q3_box_time_priority")

    # Raw 3: direct-link outage fractions on the audited transport schedule.
    samples = direct_samples(q2, phys, models, comm, step=20)
    counts = Counter(s["sortie"] for s in samples)
    misses = Counter(s["sortie"] for s in samples if not s["direct"])
    names = [r["sortie"] for r in q2]
    frac = [misses[n] / counts[n] for n in names]
    fig, ax = plt.subplots()
    ax.bar(range(len(names)), frac, color=[ORANGE if f else BLUE for f in frac])
    ax.set(xlabel="Q2 sortie index", ylabel="Direct outage fraction", ylim=(0, 1),
           xticks=range(0, len(names), 3), xticklabels=range(1, len(names)+1, 3))
    save(fig, "raw_q3_q2_direct_outages")

    # Process 1: spatial set-cover reach of candidate relay sites.
    sites = candidate_sites(phys, relay_model, comm, height_levels=(1.0,))
    gaps = [s for s in samples if not s["direct"]]
    coverage = []
    for site in sites:
        n = sum(link(g["position"], "transport", site, "relay_access",
                     phys.terrain, comm)[0] for g in gaps)
        coverage.append((site["id"], n))
    best = sorted(coverage, key=lambda x: x[1], reverse=True)[:15]
    fig, ax = plt.subplots()
    ax.barh([x[0] for x in best[::-1]], [x[1] for x in best[::-1]], color=BLUE)
    ax.set(xlabel=f"Covered direct-failure samples (of {len(gaps)})", ylabel="Candidate site")
    save(fig, "process_q3_candidate_coverage", (6.6, 4.3))

    # Process 2: relay sites and service intervals from actual missions.
    fig, ax = plt.subplots()
    for j, m in enumerate(rel):
        ax.broken_barh([(m["service_start"]/3600,
                         (m["service_end"]-m["service_start"])/3600)],
                       (j-.35,.7), facecolors=BLUE if m["relay"] == relays[0] else ORANGE)
        ax.text(m["service_start"]/3600, j+.36, m["site"]["id"], fontsize=5)
    ax.set(xlabel="Time from start (h)", ylabel="Relay mission", yticks=range(len(rel)),
           yticklabels=[f"{m['relay']}-{j+1}" for j,m in enumerate(rel)])
    save(fig, "process_q3_relay_service", (6.6, 5.0))

    # Process 3: proof routes and lower bounds for all certified intervals.
    iv = cert["intervals"]
    methods = Counter(x["method"] for x in iv)
    fig, ax = plt.subplots()
    ax.bar(methods.keys(), methods.values(), color=[BLUE, ORANGE][:len(methods)])
    ax.set(ylabel="Certified intervals", xlabel="Certification method")
    for i, (k,v) in enumerate(methods.items()):
        ax.text(i, v+10, str(v), ha="center", fontsize=8)
    save(fig, "process_q3_certificate_methods")

    # Result 1: simultaneous transport and relay service occupancy.
    fig, ax = plt.subplots()
    for j,r in enumerate(trs):
        ax.broken_barh([(r["start"]/3600,(r["end"]-r["start"])/3600)],
                       (j-.39,.76), facecolors=BLUE, alpha=.75)
    for j,m in enumerate(rel):
        y = len(trs)+j
        ax.broken_barh([(m["launch"]/3600,(m["end"]-m["launch"])/3600)],
                       (y-.39,.76), facecolors=ORANGE, alpha=.85)
    ax.axhline(len(trs)-.5, color=GREY, linewidth=.8)
    ax.set(xlabel="Time from start (h)", ylabel="Transport sorties (lower), relay sorties (upper)",
           ylim=(-1,len(trs)+len(rel)), yticks=[0,10,20,30,40,50,57],
           yticklabels=["T1","T11","T21","T31","T41","R7","R14"])
    save(fig, "result_q3_joint_timeline", (6.6, 5.0))

    # Result 2: delivery performance as observed box-level points.
    fig, ax = plt.subplots()
    for kind, marker, color in zip(kinds,["o","s","^","D"],[BLUE,ORANGE,GREEN,GREY]):
        b = box[box.kind == kind]
        ax.scatter(b.desired_s/3600,b.delivery_s/3600,s=25,marker=marker,
                   label=f"{kind} (n={len(b)})",alpha=.8,color=color)
    ax.plot([0,5.5],[0,5.5],"k--",lw=.8,label="On time")
    ax.set(xlabel="Desired delivery (h)",ylabel="Actual delivery (h)",xlim=(.7,5.3),ylim=(0,5.3))
    ax.legend(frameon=False,ncol=2,fontsize=7)
    save(fig,"result_q3_box_delivery")

    # Result 3: scenario trade-off; Q2 is explicitly the no-communication benchmark.
    q2metrics = json.loads((ROOT/"results"/"q2_improved"/"summary.json").read_text(encoding="utf-8"))
    labels=["Sorties","Makespan (h)","Energy (kWh)","Late boxes"]
    q2vals=[q2metrics["sorties"],q2metrics["makespan_s"]/3600,q2metrics["energy_kwh"],q2metrics["late_boxes"]]
    q3vals=[data["metrics"]["sorties"]+data["metrics"]["relay_sorties"],
            data["metrics"]["joint_makespan_s"]/3600,data["metrics"]["total_energy_kwh"],
            data["metrics"]["late_boxes"]]
    fig,axs=plt.subplots(1,4,figsize=(7.3,2.8))
    for i,ax in enumerate(axs):
        ax.bar([0,1],[q2vals[i],q3vals[i]],color=[BLUE,ORANGE])
        ax.set(title=labels[i],xticks=[0,1],xticklabels=["Q2","Q3"])
        ax.tick_params(axis="y",labelsize=7)
    save(fig,"result_q3_q2_comparison",(7.3,2.8))

    # Flow chart: actual source, physics, relay search, validation and outputs.
    fig,ax=plt.subplots(figsize=(7,2.9)); ax.axis("off")
    boxes_flow=[("Inputs\n5 XLSX + DEM",.02), ("Route\nheuristic",.185),
                ("DEM / link\ncoverage",.35),("Relay\nsearch",.515),
                ("Continuous\nvalidation",.68),("Q3 tables\n+ certificate",.845)]
    for label,x in boxes_flow:
        patch=FancyBboxPatch((x,.36),.135,.31,boxstyle="round,pad=0.005",
                             edgecolor=BLUE,facecolor="#E8F1F7",lw=1)
        ax.add_patch(patch); ax.text(x+.0675,.515,label,ha="center",va="center",fontsize=7)
    for x in [.155,.32,.485,.65,.815]:
        ax.add_patch(FancyArrowPatch((x+.004,.515),(x+.025,.515),arrowstyle="->",
                                     mutation_scale=10,color=GREY,linewidth=1))
    ax.set(xlim=(0,1),ylim=(0,1))
    save(fig,"flow_overall_model",(7,2.9))


if __name__ == "__main__":
    main()
