"""Figures for the audited 24-sortie Q2 solution used in paper.tex."""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[1]
FIGURE_SCRIPTS = Path(r"C:/Users/xwz/Desktop/华为杯数学建模/2026/math_model_skill/math-modeling-skill/tools/figure/scripts")
sys.path.insert(0, str(FIGURE_SCRIPTS))
from export_figure import export_figure  # noqa: E402


def rows(filename: str) -> list[dict[str, str]]:
    with (ROOT / "results" / "q2_improved" / filename).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def timeline() -> None:
    sorties = rows("sorties.csv")
    batteries = rows("batteries.csv")
    assert len(sorties) == len(batteries) == 24
    colors = {"A": "#1674a8", "B": "#dc8b12", "C": "#4e8c62"}
    fig, (drone_ax, battery_ax) = plt.subplots(
        2, 1, figsize=(7.0, 5.6), sharex=True,
        gridspec_kw={"height_ratios": [1.0, 1.6], "hspace": 0.08},
    )
    drone_names = [f"U{i:02d}" for i in range(1, 9)]
    battery_names = sorted({row["battery"] for row in batteries})
    for row in sorties:
        y = drone_names.index(row["drone"])
        start, end = float(row["start_s"]) / 3600, float(row["return_s"]) / 3600
        drone_ax.barh(y, end - start, left=start, height=0.58,
                      color=colors[row["model"]], linewidth=0)
    for row in batteries:
        y = battery_names.index(row["battery"])
        start = float(row["start_s"]) / 3600
        ret = float(row["return_s"]) / 3600
        ready = float(row["ready_reserved_s"]) / 3600
        battery_ax.barh(y, ret - start, left=start, height=0.62,
                        color=colors[row["model"]], linewidth=0)
        battery_ax.barh(y, ready - ret, left=ret, height=0.62,
                        color=colors[row["model"]], alpha=0.32, linewidth=0)
    for ax, names in ((drone_ax, drone_names), (battery_ax, battery_names)):
        ax.set_yticks(range(len(names)), names)
        ax.invert_yaxis()
        ax.grid(axis="x", color="#d9d9d9", linewidth=0.55)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=7)
        ax.set_xlim(0, 2.55)
    drone_ax.set_ylabel("Transport drone", fontsize=8)
    battery_ax.set_ylabel("Shared battery", fontsize=8)
    battery_ax.set_xlabel("Time from task start (h)", fontsize=9)
    drone_ax.legend(handles=[Patch(facecolor=colors[g], label=f"Model {g}") for g in "ABC"],
                    ncol=3, frameon=False, loc="lower center",
                    bbox_to_anchor=(0.5, 1.01), fontsize=7)
    battery_ax.text(0.995, 0.02, "Solid: sortie    Pale: charging / reserved",
                    transform=battery_ax.transAxes, ha="right", va="bottom", fontsize=7)
    export_figure(fig, str(ROOT / "figures" / "result_q2_resources"),
                  formats=("pdf", "svg", "png"), size_inches=(7.0, 5.6),
                  dpi=300, grayscale_preview=True)
    plt.close(fig)


def deadline_margin() -> None:
    deliveries = rows("deliveries.csv")
    finite = []
    for row in deliveries:
        due = float(row["hard_s"])
        if math.isfinite(due):
            finite.append((row["site"], (due - float(row["delivered_s"])) / 60))
    assert len(deliveries) == 80 and finite and min(margin for _, margin in finite) > 0
    sites = sorted({site for site, _ in finite})
    fig, ax = plt.subplots(figsize=(6.7, 3.7))
    for site, margin in finite:
        ax.scatter(margin, sites.index(site), s=18, c="#1674a8", alpha=0.76,
                   edgecolors="none")
    minimum = min(finite, key=lambda row: row[1])
    ax.scatter(minimum[1], sites.index(minimum[0]), s=47,
               facecolors="none", edgecolors="#b25220", linewidths=1.3,
               label=f"Minimum: {minimum[1]:.2f} min")
    ax.axvline(0, color="#b25220", linestyle="--", linewidth=1)
    ax.set_yticks(range(len(sites)), sites)
    ax.invert_yaxis()
    ax.set_xlabel("Remaining time before hard deadline (min)", fontsize=9)
    ax.set_ylabel("Service area", fontsize=9)
    ax.grid(axis="x", color="#dedede", linewidth=0.5)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=7)
    ax.legend(frameon=False, loc="lower right", fontsize=7)
    export_figure(fig, str(ROOT / "figures" / "result_q2_hard_deadline_margin"),
                  formats=("pdf", "svg", "png"), size_inches=(6.7, 3.7),
                  dpi=300, grayscale_preview=True)
    plt.close(fig)


if __name__ == "__main__":
    timeline()
    deadline_margin()
