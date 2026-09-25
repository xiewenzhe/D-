"""Plot model-evaluation diagnostics from the audited Q2/Q3 result files."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "完整论文-LaTeX" / "figures"


def hard_slacks() -> tuple[dict[str, float], dict[str, float]]:
    with (ROOT / "results/q2_improved/deliveries.csv").open(encoding="utf-8-sig", newline="") as handle:
        q2 = {
            row["box"]: float(row["hard_s"]) - float(row["delivered_s"])
            for row in csv.DictReader(handle)
            if math.isfinite(float(row["hard_s"]))
        }
    with (ROOT / "results/q3/box_deliveries.csv").open(encoding="utf-8-sig", newline="") as handle:
        q3 = {
            row["box"]: float(row["hard_due_s"]) - float(row["delivery_s"])
            for row in csv.DictReader(handle)
            if row["hard_due_s"]
        }
    assert len(q2) == len(q3) == 31 and q2.keys() == q3.keys()
    assert min(q2.values()) > 0 and min(q3.values()) == 0
    return q2, q3


def plot_hard_slack() -> None:
    q2, q3 = hard_slacks()
    boxes = sorted(q3, key=lambda box: (q3[box], box))[:8]
    labels = [box.replace("-01", "").replace("-", " ") for box in boxes]
    y = np.arange(len(boxes))
    fig, ax = plt.subplots(figsize=(7.8, 3.8))
    ax.barh(y - 0.18, [q2[box] for box in boxes], 0.34, label="Q2", color="#457b9d")
    ax.barh(y + 0.18, [q3[box] for box in boxes], 0.34, label="Q3", color="#e69f00", hatch="//", edgecolor="#7d5900", linewidth=0.35)
    for idx, box in enumerate(boxes):
        if q3[box] == 0:
            ax.plot(0, idx + 0.18, marker="o", markersize=4, color="#9f3a24", zorder=5)
            ax.annotate("0", (0, idx + 0.18), xytext=(7, 0), textcoords="offset points", va="center", fontsize=8, color="#9f3a24")
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 2700)
    ax.set_xlabel("Hard-deadline slack (s)")
    ax.grid(axis="x", color="#d4d4d4", linewidth=0.45)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=2, loc="lower right")
    fig.tight_layout(pad=0.8)
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / "model_eval_hard_slack.pdf")
    fig.savefig(FIGURES / "model_eval_hard_slack.png", dpi=180)
    plt.close(fig)


def plot_link_margin() -> None:
    certificate = json.loads((ROOT / "results/q3/continuous_certificate.json").read_text(encoding="utf-8"))
    assert certificate["passed"] and not certificate["unresolved_intervals"]
    margins = np.array([row["margin_lower_bound_db"] for row in certificate["intervals"]])
    assert len(margins) == certificate["certified_intervals"] == 1317
    assert np.all(margins > 0)
    edges = np.array([0, 0.1, 0.5, 1, 3, 10, 20, 45], dtype=float)
    counts, _ = np.histogram(margins, bins=edges)
    assert counts.sum() == len(margins)
    labels = ["0–0.1", "0.1–0.5", "0.5–1", "1–3", "3–10", "10–20", "20–45"]
    fig, ax = plt.subplots(figsize=(7.8, 3.25))
    bars = ax.bar(np.arange(len(counts)), counts, color="#457b9d", edgecolor="#29475b", linewidth=0.4)
    for bar, count in zip(bars, counts):
        ax.annotate(str(count), (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8)
    ax.set_xticks(np.arange(len(counts)), labels)
    ax.set_ylabel("Certified intervals")
    ax.set_xlabel("Conservative link-margin lower bound (dB)")
    ax.set_ylim(0, max(counts) * 1.14)
    ax.grid(axis="y", color="#d4d4d4", linewidth=0.45)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(0.99, 0.94, f"Minimum: {margins.min():.6f} dB",
            transform=ax.transAxes, ha="right", va="top", fontsize=9,
            bbox={"facecolor": "white", "edgecolor": "#bbbbbb", "linewidth": 0.5})
    fig.tight_layout(pad=0.8)
    fig.savefig(FIGURES / "model_eval_link_margin.pdf")
    fig.savefig(FIGURES / "model_eval_link_margin.png", dpi=180)
    plt.close(fig)


def plot_loss_stress() -> None:
    certificate = json.loads((ROOT / "results/q3/continuous_certificate.json").read_text(encoding="utf-8"))
    assert certificate["passed"] and not certificate["unresolved_intervals"]
    intervals = certificate["intervals"]
    margins = np.array([row["margin_lower_bound_db"] for row in intervals])
    durations = np.array([row["end_s"] - row["start_s"] for row in intervals])
    guard = float(certificate["margin_guard_db"])
    assert len(intervals) == 1317 and abs(durations.sum() - certificate["certified_duration_s"]) < 1e-5
    extra_loss = np.linspace(0, 5, 501)
    retained = np.array([100 * durations[margins - loss >= guard].sum() / durations.sum() for loss in extra_loss])
    fig, ax = plt.subplots(figsize=(7.8, 3.15))
    ax.plot(extra_loss, retained, color="#457b9d", linewidth=2)
    ax.fill_between(extra_loss, retained, 0, color="#457b9d", alpha=0.12)
    for loss in (1, 3):
        value = 100 * durations[margins - loss >= guard].sum() / durations.sum()
        ax.plot(loss, value, "o", color="#ad6226", markersize=5)
        ax.annotate(f"{value:.1f}%", (loss, value), xytext=(8, 8),
                    textcoords="offset points", fontsize=8, color="#7d461c")
    ax.set_xlim(0, 5)
    ax.set_ylim(0, 105)
    ax.set_xlabel("Additional loss on each certified link (dB)")
    ax.set_ylabel("Retained certified duration (%)")
    ax.grid(color="#d4d4d4", linewidth=0.45)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.8)
    fig.savefig(FIGURES / "model_eval_loss_stress.pdf")
    fig.savefig(FIGURES / "model_eval_loss_stress.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    plot_hard_slack()
    plot_link_margin()
    plot_loss_stress()
