"""Plot Q4 resource requirements from the audited partition result."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "results" / "q4" / "partitions.json"
OUTPUT = ROOT / "figures" / "result_q4_inventory_comparison.pdf"


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    keys = ["drone_A", "drone_B", "drone_C", "battery_A", "battery_B", "battery_C", "relay", "relay_component"]
    labels = ["A drone", "B drone", "C drone", "A battery", "B battery", "C battery", "Relay", "Relay pack"]
    rows = [
        ("Stock", data["stock"], "#b5b5b5", ""),
        ("2 groups", data["partitions"]["2"]["total_allocation"], "#457b9d", "//"),
        ("3 groups", data["partitions"]["3"]["total_allocation"], "#e69f00", "xx"),
    ]
    x = np.arange(len(keys), dtype=float)
    width = 0.25
    fig, ax = plt.subplots(figsize=(8.2, 3.5))
    for offset, (name, values, color, hatch) in zip((-width, 0.0, width), rows):
        ax.bar(x + offset, [values[key] for key in keys], width, label=name,
               color=color, hatch=hatch, edgecolor="#333333", linewidth=0.45)
    for idx in (2, 5):
        ax.axvspan(idx - 0.47, idx + 0.47, facecolor="#fae9d5", alpha=0.55, zorder=0)
    ax.set_ylim(0, 7.0)
    ax.set_yticks(range(0, 7))
    ax.set_ylabel("Required units")
    ax.set_xticks(x, labels, rotation=23, ha="right")
    ax.grid(axis="y", alpha=0.25, linewidth=0.5)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(ncol=3, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.12))
    fig.tight_layout(pad=0.5)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, bbox_inches="tight")
    fig.savefig(OUTPUT.with_suffix(".png"), dpi=220, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
