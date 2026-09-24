"""Overall four-question method flow for the paper, tied to implemented stages."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

ROOT = Path(__file__).resolve().parents[1]
FIGURE_SCRIPTS = Path(r"C:/Users/xwz/Desktop/华为杯数学建模/2026/math_model_skill/math-modeling-skill/tools/figure/scripts")
sys.path.insert(0, str(FIGURE_SCRIPTS))
from export_figure import export_figure  # noqa: E402


def main() -> None:
    fig, ax = plt.subplots(figsize=(7.1, 3.0))
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    blue, pale, dark = "#356a84", "#eaf1f4", "#324b59"
    x_positions = (0.025, 0.275, 0.525, 0.775)
    width, height = 0.20, 0.285
    top, bottom = 0.61, 0.105
    top_nodes = (
        ("Inputs\nboxes / fleet / DEM", "terminal"),
        ("Flight model\nterrain / energy", "process"),
        ("Q1 payload\n+ batch DP", "process"),
        ("Q2 route pool\n+ CP-SAT schedule", "process"),
    )
    bottom_nodes = (
        ("Q3 relay sites\n+ beam / retiming", "process"),
        ("Q3 continuous\nlink certificate", "process"),
        ("Q4 task graph\n+ 2/3 groups", "process"),
        ("Outputs\nQ1-Q4 results\n+ checks", "terminal"),
    )
    for x, (label, kind) in zip(x_positions, top_nodes):
        shape = (FancyBboxPatch((x, top), width, height,
                                boxstyle="round,pad=0.005,rounding_size=0.025")
                 if kind == "terminal" else Rectangle((x, top), width, height))
        shape.set(facecolor=pale, edgecolor=blue, linewidth=1.1)
        ax.add_patch(shape)
        ax.text(x + width / 2, top + height / 2, label,
                ha="center", va="center", fontsize=7.0, color=dark, linespacing=1.15)
    for x, (label, kind) in zip(reversed(x_positions), bottom_nodes):
        shape = (FancyBboxPatch((x, bottom), width, height,
                                boxstyle="round,pad=0.005,rounding_size=0.025")
                 if kind == "terminal" else Rectangle((x, bottom), width, height))
        shape.set(facecolor=pale, edgecolor=blue, linewidth=1.1)
        ax.add_patch(shape)
        ax.text(x + width / 2, bottom + height / 2, label,
                ha="center", va="center", fontsize=7.0, color=dark, linespacing=1.15)
    def arrow(start: tuple[float, float], end: tuple[float, float]) -> None:
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>",
                                     mutation_scale=10, linewidth=1.1, color=blue))
    for index in range(3):
        arrow((x_positions[index] + width + 0.003, top + height / 2),
              (x_positions[index + 1] - 0.006, top + height / 2))
    arrow((x_positions[3] + width / 2, top - 0.009),
          (x_positions[3] + width / 2, bottom + height + 0.009))
    for index in (3, 2, 1):
        arrow((x_positions[index] - 0.003, bottom + height / 2),
              (x_positions[index - 1] + width + 0.006, bottom + height / 2))
    export_figure(fig, str(ROOT / "figures" / "flow_overall_model"),
                  formats=("pdf", "svg", "png"), size_inches=(7.1, 3.0),
                  dpi=300, grayscale_preview=True)
    plt.close(fig)


if __name__ == "__main__":
    main()
