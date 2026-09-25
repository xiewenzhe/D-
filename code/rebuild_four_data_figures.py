"""Rebuild four styled paper figures directly from the audited Q2--Q4 results.

Run with ``.venv/Scripts/python.exe code/rebuild_four_data_figures.py``.
The Q2 and Q4 solutions are read only; no optimization is rerun here.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np

from common import ROOT, distance_m
from problem3 import candidate_sites, direct_samples, link
from run_q3_joint import load


OUT = ROOT / "数模overleaf" / "figures"
DATA_OUT = OUT / "corrected_four_figures_data"
BLUE = "#a8d0ef"
RED = "#c65c60"
NAVY = "#143a5b"
PALE = "#f2f5f6"
INK = "#1d2831"
plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "pdf.fonttype": 42,
    "svg.fonttype": "none",
    "font.size": 10,
    "axes.edgecolor": "#3c4a54",
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": INK,
    "ytick.color": INK,
})


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def read_csv(path):
    with (ROOT / path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(name, columns, rows):
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    with (DATA_OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)


def save(fig, stem):
    OUT.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf", "svg"):
        fig.savefig(OUT / f"{stem}.{ext}", dpi=250, bbox_inches="tight",
                    facecolor="white")
    plt.close(fig)


def local_xy(point, home):
    east = distance_m(home, {**home, "lon": point["lon"]}) / 1000
    north = distance_m(home, {**home, "lat": point["lat"]}) / 1000
    return (math.copysign(east, point["lon"] - home["lon"]),
            math.copysign(north, point["lat"] - home["lat"]))


def dem_background(ax, physics, *, vmin=200, vmax=1200):
    dem = physics.terrain
    home = physics.nodes["O01"]
    left, bottom = local_xy({"lon": dem.x0, "lat": dem.y0 - dem.dy * dem.grid.shape[0]}, home)
    right, top = local_xy({"lon": dem.x0 + dem.dx * dem.grid.shape[1], "lat": dem.y0}, home)
    im = ax.imshow(dem.grid[::5, ::5], origin="upper",
                   extent=(left, right, bottom, top), cmap="RdYlBu_r",
                   vmin=vmin, vmax=vmax, alpha=.77, zorder=0, rasterized=True)
    ax.set_xlabel("相对 O01 东向距离（km）")
    ax.set_ylabel("相对 O01 北向距离（km）")
    ax.grid(color="white", alpha=.15, linewidth=.5)
    ax.set_axisbelow(True)
    return im


def node_label(ax, x, y, label, *, dx=.09, dy=.09, size=8.0, color=INK):
    ax.text(x + dx, y + dy, label, fontsize=size, weight="bold", color=color,
            path_effects=[] if color == "white" else None, zorder=8)


def figure_1(samples, schedule):
    """Sample-accurate outage raster, with rows sorted but IDs preserved."""
    by_route = defaultdict(list)
    for row in samples:
        by_route[row["sortie"]].append(row)
    routes = [r["sortie"] for r in schedule]
    assert len(routes) == 24 and set(routes) == set(by_route)
    counts = {rid: len(by_route[rid]) for rid in routes}
    failed = {rid: sum(not x["direct"] for x in by_route[rid]) for rid in routes}
    order = sorted(routes, key=lambda rid: (-failed[rid] / counts[rid], rid))
    frac = np.array([failed[rid] / counts[rid] for rid in order])
    write_csv("fig1_sortie_summary.csv",
              ("rank", "sortie", "failed_samples", "all_samples", "outage_fraction"),
              ((j + 1, rid, failed[rid], counts[rid], failed[rid] / counts[rid])
               for j, rid in enumerate(order)))
    write_csv("fig1_direct_samples.csv",
              ("sortie", "time_s", "progress_pct", "direct_available",
               "lon", "lat", "altitude_m"),
              ((rid, row["t"], 100 * (row["t"] - by_route[rid][0]["t"]) /
                (by_route[rid][-1]["t"] - by_route[rid][0]["t"]),
                int(row["direct"]), row["position"]["lon"],
                row["position"]["lat"], row["position"]["z"])
               for rid in order for row in by_route[rid]))
    cmap = LinearSegmentedColormap.from_list("link", [BLUE, RED], N=2)
    fig = plt.figure(figsize=(13.1, 9.1), constrained_layout=False)
    gs = fig.add_gridspec(1, 2, left=.12, right=.95, bottom=.21, top=.95,
                          width_ratios=(5.2, 1.35), wspace=.055)
    ax = fig.add_subplot(gs[0, 0])
    side = fig.add_subplot(gs[0, 1], sharey=ax)
    for i, rid in enumerate(order):
        rows = by_route[rid]
        times = np.array([x["t"] for x in rows])
        progress = 100 * (times - times[0]) / (times[-1] - times[0])
        edges = np.r_[0, (progress[:-1] + progress[1:]) / 2, 100]
        colors = np.array([1 if not x["direct"] else 0 for x in rows])
        ax.pcolormesh(edges, [i - .43, i + .43], colors[None, :], cmap=cmap,
                      norm=BoundaryNorm([-.5, .5, 1.5], 2), shading="flat",
                      edgecolors="white", linewidth=.09, rasterized=True)
    side.barh(np.arange(24), frac, height=.77, color=RED, edgecolor="none")
    for i, f in enumerate(frac):
        side.text(min(f + .025, 1.01), i, f"{f:.3f}", va="center", fontsize=8.0)
    ax.set_xlim(0, 100)
    ax.set_ylim(23.55, -.55)
    ax.set_yticks(np.arange(24), order)
    ax.set_xticks(np.arange(0, 101, 10))
    ax.set_xlabel("飞行进度（%）", fontsize=11)
    ax.set_ylabel("架次（按失效比例降序）", fontsize=11)
    side.set_xlim(0, 1.18)
    side.set_xticks(np.arange(0, 1.01, .2))
    side.set_xlabel("直连失效比例", fontsize=10)
    side.tick_params(axis="y", left=False, labelleft=False)
    side.grid(axis="x", color="#dbe1e4", linewidth=.5)
    side.set_axisbelow(True)
    ax.grid(axis="x", color="white", alpha=.55, linewidth=.4)
    fig.legend(handles=[Patch(facecolor=BLUE, label="直连可用"),
                        Patch(facecolor=RED, label="直连失效")],
               loc="lower center", bbox_to_anchor=(.5, .105), ncol=2,
               frameon=False, fontsize=10)
    fig.text(.12, .045, "按问题二原始架次编号标识；每行采用 20 s 级直连采样，右侧比例按采样点数计算。",
             fontsize=9, color="#50606b")
    save(fig, "corrected_5_11_direct_outage")
    return {rid: {"failed": failed[rid], "samples": counts[rid],
                  "fraction": failed[rid] / counts[rid]} for rid in routes}


def figure_2(deliveries, physics):
    """Spatial and rank views of actual minimum hard-deadline slack."""
    by_site = defaultdict(list)
    for row in deliveries:
        due = float(row["hard_s"])
        if math.isfinite(due):
            by_site[row["site"]].append((row["box"], due - float(row["delivered_s"])))
    assert sum(map(len, by_site.values())) == 31
    rows = sorted(((site, min(v, key=lambda x: x[1]), len(v))
                   for site, v in by_site.items()), key=lambda x: x[1][1])
    assert rows[0][1][0] == "S012-WAT-01" and abs(rows[0][1][1] - 220.524963) < .01
    assert abs(min(x[1][1] for x in rows if x[0] == "S002") - 550.684) < .1
    home = physics.nodes["O01"]
    write_csv("fig2_area_minimum_slack.csv",
              ("area", "minimum_box", "minimum_slack_s", "hard_box_count",
               "east_km", "north_km"),
              ((site, item[0], item[1], n, *local_xy(physics.nodes[site], home))
               for site, item, n in rows))
    write_csv("fig2_all_hard_boxes.csv",
              ("box", "area", "delivery_s", "hard_deadline_s", "slack_s"),
              ((row["box"], row["site"], row["delivered_s"], row["hard_s"],
                float(row["hard_s"]) - float(row["delivered_s"]))
               for row in deliveries if math.isfinite(float(row["hard_s"]))))
    fig = plt.figure(figsize=(13.4, 7.5))
    gs = fig.add_gridspec(1, 2, left=.07, right=.96, bottom=.18, top=.91,
                          width_ratios=(1.28, 1), wspace=.27)
    ax = fig.add_subplot(gs[0, 0])
    rank = fig.add_subplot(gs[0, 1])
    im = dem_background(ax, physics)
    vals = [r[1][1] for r in rows]
    norm = Normalize(vmin=200, vmax=max(1600, math.ceil(max(vals) / 200) * 200))
    cmap = plt.get_cmap("RdYlBu")
    for site, (_, slack), n in rows:
        x, y = local_xy(physics.nodes[site], home)
        ax.plot([0, x], [0, y], linestyle=(0, (4, 4)), color="#9d9692",
                alpha=.32, linewidth=.8, zorder=1)
        ax.scatter(x, y, s=105 + 20 * n, facecolor=cmap(norm(slack)),
                   edgecolor="white", linewidth=1.2, zorder=4)
        ax.scatter(x, y, s=105 + 20 * n, facecolor="none", edgecolor=NAVY,
                   linewidth=.7, zorder=5)
        node_label(ax, x, y, site, dy=.12)
    ax.scatter(0, 0, marker="*", s=350, color="black", edgecolor="white", zorder=6)
    node_label(ax, 0, 0, "O01", dy=-.36, dx=.10)
    ax.set_title("a  服务区硬截止任务交付余量的空间分布", loc="left", fontsize=12)
    ax.set_xlim(-7.0, 7.6)
    ax.set_ylim(-7.0, 8.3)
    for j, (site, (_, slack), _) in enumerate(rows):
        color = cmap(norm(slack))
        rank.hlines(j, 0, slack, color=color, linewidth=1.6, alpha=.9)
        rank.scatter(slack, j, s=72, color=color, edgecolor="white", linewidth=.5, zorder=3)
        rank.text(slack + 120, j, f"{slack:,.3f}", va="center", fontsize=8.5,
                  color="#901719" if j == 0 else INK,
                  weight="bold" if j == 0 else "normal")
    rank.set_yticks(range(len(rows)), [r[0] for r in rows])
    rank.set_ylim(len(rows) - .35, -.65)
    rank.set_xlim(0, max(vals) * 1.27)
    rank.set_xlabel("最小硬截止余量（s）", fontsize=10)
    rank.set_title("b  各服务区最小交付余量", loc="left", fontsize=12)
    rank.grid(axis="x", alpha=.25)
    rank.set_axisbelow(True)
    cax = fig.add_axes([.09, .075, .39, .025])
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax,
                      orientation="horizontal")
    cb.set_label("最小硬截止余量（s）", labelpad=3)
    fig.text(.55, .083, "圆点大小表示该区硬截止货箱数；虚线仅连接 O01 与服务区位置。",
             fontsize=9, color="#53616a")
    save(fig, "corrected_4_10_hard_slack")
    return {site: {"minimum_box": box, "minimum_slack_s": slack,
                   "hard_boxes": n} for site, (box, slack), n in rows}


def figure_3(samples, physics, relay_model, comm, solution):
    """Actual candidate cover matrix against the same 20 s Q2 outage samples."""
    gaps = [x for x in samples if not x["direct"]]
    assert gaps
    sites = candidate_sites(physics, relay_model, comm)
    coverage = {}
    by_sortie = defaultdict(list)
    for j, row in enumerate(gaps):
        by_sortie[row["sortie"]].append(j)
    for site in sites:
        covered = np.array([bool(link(row["position"], "transport", site,
                                      "relay_access", physics.terrain, comm)[0])
                            for row in gaps], dtype=bool)
        coverage[site["id"]] = covered
    ranked = sorted(sites, key=lambda s: (-int(coverage[s["id"]].sum()), s["id"]))[:15]
    ids = [s["id"] for s in ranked]
    route_ids = sorted({row["sortie"] for row in samples})
    matrix = np.array([[int(coverage[sid][by_sortie[rid]].sum()) for rid in route_ids]
                       for sid in ids], dtype=int)
    totals = matrix.sum(axis=1)
    assert np.array_equal(totals, [coverage[sid].sum() for sid in ids])
    assert len(route_ids) == 24
    write_csv("fig3_outage_samples.csv",
              ("sortie", "time_s", "lon", "lat", "altitude_m"),
              ((row["sortie"], row["t"], row["position"]["lon"],
                row["position"]["lat"], row["position"]["z"])
               for row in gaps))
    write_csv("fig3_coverage_matrix.csv",
              ("candidate_site", "covered_total", *route_ids),
              ((sid, int(totals[j]), *map(int, matrix[j]))
               for j, sid in enumerate(ids)))
    write_csv("fig3_candidate_positions.csv",
              ("candidate_site", "east_km", "north_km", "covered_total",
               "supported_sorties"),
              ((site["id"], *local_xy(site, physics.nodes["O01"]),
                int(totals[j]), int(np.count_nonzero(matrix[j])))
               for j, site in enumerate(ranked)))
    fig = plt.figure(figsize=(15.0, 8.3))
    gs = fig.add_gridspec(1, 2, left=.05, right=.96, bottom=.23, top=.88,
                          width_ratios=(1.05, 1.12), wspace=.18)
    mapax = fig.add_subplot(gs[0, 0])
    right = gs[0, 1].subgridspec(2, 2, height_ratios=(.16, 1),
                                 width_ratios=(1, .17), hspace=.025, wspace=.035)
    top = fig.add_subplot(right[0, 0])
    mat = fig.add_subplot(right[1, 0])
    sums = fig.add_subplot(right[1, 1], sharey=mat)
    terrain_im = dem_background(mapax, physics)
    home = physics.nodes["O01"]
    route_reach = [int(np.count_nonzero(matrix[j])) for j in range(15)]
    reach = Normalize(vmin=min(route_reach), vmax=max(route_reach) + 1)
    cmap_site = plt.get_cmap("RdYlBu_r")
    for site, total in zip(ranked, totals):
        x, y = local_xy(site, home)
        n_routes = route_reach[ids.index(site["id"])]
        mapax.scatter(x, y, s=36 + .28 * total, facecolor=cmap_site(reach(n_routes)),
                      edgecolor="white", linewidth=1.2, zorder=5)
        mapax.scatter(x, y, s=36 + .28 * total, facecolor="none", edgecolor=NAVY,
                      linewidth=.65, zorder=6)
    final_sites = {}
    for mission in solution["relays"]:
        final_sites[mission["site"]["id"]] = mission["site"]
    for sid, site in final_sites.items():
        x, y = local_xy(site, home)
        mapax.scatter(x, y, s=235, marker="*", facecolor="#c52731",
                      edgecolor="black", linewidth=.7, zorder=9)
        node_label(mapax, x, y, sid, dx=.12, dy=-.26, size=7.5)
    mapax.scatter(0, 0, s=235, marker="*", facecolor="black",
                  edgecolor="white", linewidth=.7, zorder=9)
    node_label(mapax, 0, 0, "O01", dx=.13, dy=-.25)
    mapax.set_xlim(-7, 7.5)
    mapax.set_ylim(-7.3, 7.5)
    mapax.set_title("a  候选中继点与最终任务位置", loc="left", fontsize=12)
    # Every matrix cell counts a covered outage sample for one Q2 sortie.
    cmap_matrix = LinearSegmentedColormap.from_list("cover", ["#eff5fb", "#f9ad8d", "#b21930"])
    vmax = max(15, int(np.quantile(matrix, .99)))
    heat = mat.imshow(matrix, aspect="auto", interpolation="nearest", cmap=cmap_matrix,
                      vmin=0, vmax=vmax)
    mat.set_xticks(range(24), route_ids, rotation=90, fontsize=7)
    mat.set_yticks(range(15), ids, fontsize=8)
    mat.set_xlabel("问题二运输架次", fontsize=9)
    mat.set_xticks(np.arange(-.5, 24, 1), minor=True)
    mat.set_yticks(np.arange(-.5, 15, 1), minor=True)
    mat.grid(which="minor", color="white", linewidth=1.5)
    mat.tick_params(which="minor", bottom=False, left=False)
    fig.text(.55, .93, "b  候选点对直连失效样本的覆盖", fontsize=12)
    top.bar(range(24), [len(by_sortie[rid]) for rid in route_ids], color="#9b9da0", width=.75)
    top.set_xlim(-.5, 23.5)
    top.tick_params(axis="x", bottom=False, labelbottom=False)
    top.set_ylabel("缺口\n样本", rotation=0, labelpad=20, fontsize=8)
    for j, total in enumerate(totals):
        sums.barh(j, total, height=.78, color=cmap_matrix(min(1, total / max(totals))),
                  edgecolor="none")
        sums.text(total + 5, j, str(total), va="center", fontsize=7.5)
    sums.set_ylim(14.5, -.5)
    sums.set_xlim(0, max(totals) * 1.30)
    sums.tick_params(axis="y", left=False, labelleft=False)
    sums.tick_params(axis="x", labelsize=7)
    sums.set_title("合计", fontsize=9)
    cax = fig.add_axes([.55, .085, .32, .017])
    cb = fig.colorbar(heat, cax=cax, orientation="horizontal")
    cb.set_label("单点对单架次覆盖的直连失效样本数", fontsize=8)
    fig.text(.05, .044,
             f"基于同一批 {len(gaps)} 个直连失效采样点；候选点覆盖可重叠，行合计不能相加。红色星标为实际中继任务位置。",
             fontsize=8.5, color="#53616a")
    save(fig, "corrected_5_12_relay_coverage")
    return {"outage_samples": len(gaps), "candidate_sites": len(sites),
            "top15": {sid: int(total) for sid, total in zip(ids, totals)},
            "final_sites": sorted(final_sites)}


def figure_4(physics, solution, partitions, certificate):
    """Three indivisible components and verified C resource gap."""
    q3_bytes = (ROOT / "results/q3/solution.json").read_bytes()
    assert hashlib.sha256(q3_bytes).hexdigest() == partitions["q3_sha256"]
    comps = partitions["components"]
    assert len(comps) == 3 and set(map(tuple, comps)) == {
        ("S001",), ("S006",), tuple(sorted(x for x in physics.nodes if x != "O01" and x not in {"S001", "S006"}))}
    groups = partitions["partitions"]
    stock = partitions["stock"]
    base = groups["2"]["total_allocation"]
    alt = groups["3"]["total_allocation"]
    assert (stock["drone_C"], base["drone_C"], alt["drone_C"]) == (2, 3, 4)
    assert (stock["battery_C"], base["battery_C"], alt["battery_C"]) == (4, 5, 6)
    route_by_id = {r["sortie"]: r for r in solution["transport"]}
    mission_support = defaultdict(set)
    for row in certificate["intervals"]:
        if row["mode"] == "relay":
            mission_support[row["mission"]].add(row["sortie"])
    transport_edges = set()
    for route in solution["transport"]:
        for a, b in combinations(sorted(route["order"]), 2):
            transport_edges.add((a, b))
    relay_edges = set()
    for served_routes in mission_support.values():
        areas = sorted({a for rid in served_routes for a in route_by_id[rid]["order"]})
        relay_edges.update(combinations(areas, 2))
    write_csv("fig4_resource_requirements.csv",
              ("resource", "stock", "two_groups", "three_groups",
               "two_group_shortage", "three_group_shortage"),
              ((key, stock[key], base[key], alt[key],
                max(0, base[key] - stock[key]), max(0, alt[key] - stock[key]))
               for key in ("drone_A", "drone_B", "drone_C", "battery_A",
                           "battery_B", "battery_C", "relay", "relay_component")))
    write_csv("fig4_dependency_edges.csv", ("dependency", "area_a", "area_b"),
              ((*[("shared_transport_sortie", a, b) for a, b in sorted(transport_edges)],
                *[("shared_relay_mission", a, b) for a, b in sorted(relay_edges)])))
    area_component = {area: j + 1 for j, comp in enumerate(comps) for area in comp}
    write_csv("fig4_area_positions.csv",
              ("area", "component", "east_km", "north_km"),
              ((area, area_component[area], *local_xy(physics.nodes[area],
                                                     physics.nodes["O01"]))
               for area in sorted(area_component)))
    fig = plt.figure(figsize=(14.1, 7.7))
    gs = fig.add_gridspec(1, 2, left=.055, right=.965, bottom=.19, top=.91,
                          width_ratios=(1.16, 1), wspace=.22)
    mapax = fig.add_subplot(gs[0, 0])
    right = gs[0, 1].subgridspec(2, 1, hspace=.22)
    top = fig.add_subplot(right[0])
    bottom = fig.add_subplot(right[1])
    dem_background(mapax, physics, vmax=1000)
    home = physics.nodes["O01"]
    xy = {sid: local_xy(node, home) for sid, node in physics.nodes.items()}
    for a, b in relay_edges:
        xa, ya = xy[a]
        xb, yb = xy[b]
        mapax.plot((xa, xb), (ya, yb), color="#1f3140", linewidth=.52,
                   alpha=.30, linestyle="--", zorder=2)
    for a, b in transport_edges:
        xa, ya = xy[a]
        xb, yb = xy[b]
        mapax.plot((xa, xb), (ya, yb), color="#182d3e", linewidth=1.4,
                   alpha=.75, zorder=3)
    color_by_area = {a: color for comp, color in zip(comps, ["#f4a55f", "#76d4f2", "#82c76b"])
                     for a in comp}
    for sid in sorted(set(physics.nodes) - {"O01"}):
        x, y = xy[sid]
        mapax.scatter(x, y, s=115 if sid in {"S001", "S006"} else 73,
                      facecolor=color_by_area[sid], edgecolor="#092c40",
                      linewidth=1.0, zorder=5)
        node_label(mapax, x, y, sid, dy=.12, dx=-.05, size=8)
    mapax.scatter(0, 0, s=250, marker="*", facecolor="#ffe2a3",
                  edgecolor="#193447", linewidth=1.1, zorder=8)
    node_label(mapax, 0, 0, "O01", dx=.12, dy=-.25)
    mapax.set_xlim(-7, 7.8)
    mapax.set_ylim(-7.4, 8.1)
    mapax.set_title("a  固定任务形成的三个不可拆服务区块", loc="left", fontsize=12)
    mapax.legend(handles=[Line2D([0], [0], color="#182d3e", lw=1.5,
                                 label="同一运输架次"),
                          Line2D([0], [0], color="#182d3e", lw=1.2,
                                 linestyle="--", label="同一中继任务"),
                          Patch(facecolor="#f4a55f", label="S001"),
                          Patch(facecolor="#82c76b", label="S006"),
                          Patch(facecolor="#76d4f2", label="其余 13 区")],
                  loc="lower left", ncol=2, fontsize=7.5, framealpha=.92)

    def resource_axis(ax, key, title, unit):
        values = [stock[key], base[key], alt[key]]
        colors = ["#6ba4d7", "#a9b1b5", "#d83730"]
        labels = ["现有库存", "两组方案", "三组方案"]
        y = 0
        ax.axhline(y, xmin=.08, xmax=.94, color="#718089", lw=.8)
        for value, color, label, offset in zip(values, colors, labels, [-.05, 0, .05]):
            ax.scatter(value, y + offset, s=185, color=color, edgecolor="white", zorder=3)
            ax.text(value, y + offset + .11, str(value), ha="center", fontsize=11,
                    color=INK, weight="bold")
        for requirement, level in ((base[key], -.27), (alt[key], -.44)):
            ax.annotate("", xy=(requirement, level), xytext=(stock[key], level),
                        arrowprops={"arrowstyle": "->", "color": "#da3032", "lw": 1.2})
            ax.text((stock[key] + requirement) / 2, level + .06,
                    f"缺口 +{requirement - stock[key]}", ha="center",
                    fontsize=9, color="#c31c23")
        ax.set_xlim(0, max(values) + 1.1)
        ax.set_ylim(-.6, .43)
        ax.set_yticks([])
        ax.set_xticks(range(0, max(values) + 2))
        ax.set_xlabel(f"数量（{unit}）")
        ax.set_title(title, loc="left", fontsize=12)
        ax.grid(axis="x", alpha=.2)
        ax.set_axisbelow(True)
        for spine in ("left", "right", "top"):
            ax.spines[spine].set_visible(False)

    resource_axis(top, "drone_C", "b  C 型运输机", "架")
    resource_axis(bottom, "battery_C", "c  C 型电池", "块")
    fig.legend(handles=[Line2D([0], [0], marker="o", linestyle="", color="#6ba4d7", label="现有库存"),
                        Line2D([0], [0], marker="o", linestyle="", color="#a9b1b5", label="两组方案"),
                        Line2D([0], [0], marker="o", linestyle="", color="#d83730", label="三组方案")],
               loc="lower center", bbox_to_anchor=(.76, .105), ncol=3,
               frameon=False, fontsize=9)
    fig.text(.055, .055, "两组方案需增加 C 型运输机与电池各 1；三组方案各增加 2。其余设备无库存缺口。",
             fontsize=8.7, color="#53616a")
    save(fig, "corrected_6_q4_components_inventory")
    return {"components": comps, "transport_dependency_edges": len(transport_edges),
            "relay_dependency_edges": len(relay_edges),
            "C_drone": [stock["drone_C"], base["drone_C"], alt["drone_C"]],
            "C_battery": [stock["battery_C"], base["battery_C"], alt["battery_C"]]}


def main():
    schedule, _, models, _, _, physics, relay_model, _, _, comm = load()
    samples = direct_samples(schedule, physics, models, comm, step=20)
    solution = read_json("results/q3/solution.json")
    partitions = read_json("results/q4/partitions.json")
    certificate = read_json("results/q3/continuous_certificate.json")
    deliveries = read_csv("results/q2_improved/deliveries.csv")
    report = {
        "source": {"q2": "results/q2_improved/schedule.json",
                   "q3": "results/q3/solution.json",
                   "q4": "results/q4/partitions.json"},
        "figure_1": figure_1(samples, schedule),
        "figure_2": figure_2(deliveries, physics),
        "figure_3": figure_3(samples, physics, relay_model, comm, solution),
        "figure_4": figure_4(physics, solution, partitions, certificate),
    }
    (OUT / "corrected_four_figures_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"generated": 4, "out": str(OUT),
                      "outage_samples": report["figure_3"]["outage_samples"],
                      "minimum_slack_s": min(x["minimum_slack_s"]
                                             for x in report["figure_2"].values()),
                      "C_drone": report["figure_4"]["C_drone"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
