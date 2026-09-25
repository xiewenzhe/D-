# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib as mpl
import os

mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
mpl.rcParams["axes.unicode_minus"] = False
mpl.rcParams["font.size"] = 10

# covered direct-failure samples per candidate site (top -> bottom as in source)
rows = [
    ("NS011", 509),
    ("WS011", 502),
    ("LS015-0.75", 500),
    ("LS005-0.75", 505),
    ("MS008", 496),
    ("LS008-0.25", 493),
    ("WS005", 489),
    ("LS011-0.75", 491),
    ("MS005", 487),
    ("ES015", 486),
    ("ES011", 489),
    ("MS011", 486),
    ("SS011", 484),
    ("LS004-0.25", 477),
    ("LS004-0.75", 477),
]
BASE = "#c05a4e"
TOP = "#9c3a48"

names = [r[0] for r in rows][::-1]
vals = [r[1] for r in rows][::-1]
colors = [TOP if v == max(vals) else BASE for v in vals]

fig, ax = plt.subplots(figsize=(8.6, 6.4), dpi=300)
fig.patch.set_facecolor("white")
ax.set_facecolor("white")

bars = ax.barh(names, vals, height=0.62, color=colors, edgecolor="none", zorder=3)
for b, v in zip(bars, vals):
    ax.text(v + 4, b.get_y() + b.get_height()/2, f"{v}", va="center",
            fontsize=8.2, color="#7a4a44")

ax.set_xlim(0, 545)
ax.set_xticks([0, 100, 200, 300, 400, 500])
ax.set_xlabel("覆盖的直接失效样本数（共 742）", fontsize=11.5, labelpad=8)
ax.set_ylabel("候选站点", fontsize=11.5, labelpad=8)

ax.grid(axis="x", color="#e8e0e0", lw=0.7, zorder=0)
ax.set_axisbelow(True)
for sp in ["top", "right"]:
    ax.spines[sp].set_visible(False)

fig.tight_layout()
out_dir = r"C:\Users\xwz\Desktop\华为杯数学建模\2026\中文题目\D题\完整论文-LaTeX\figures"
png = os.path.join(out_dir, "process_q3_candidate_coverage_cn.png")
pdf = os.path.join(out_dir, "process_q3_candidate_coverage_cn.pdf")
fig.savefig(png, dpi=300, bbox_inches="tight")
fig.savefig(pdf, bbox_inches="tight")
print("saved", png)
