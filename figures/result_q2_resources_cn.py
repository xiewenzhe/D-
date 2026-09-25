# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.patches import Patch
import os

mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
mpl.rcParams["axes.unicode_minus"] = False
mpl.rcParams["font.size"] = 10

# colors
A = "#1f77b4"; B = "#e08a1e"; C = "#4a8c5a"
pale = {A: "#aecde3", B: "#f0d9b5", C: "#bdd7c2"}

# top: transport drones, solid only
top = [
    ("U01", A, [(0.00, 0.68), (0.82, 1.42)]),
    ("U02", A, [(0.00, 1.68)]),
    ("U03", A, [(0.00, 1.75)]),
    ("U04", A, [(0.00, 0.55), (0.58, 1.15)]),
    ("U05", B, [(0.00, 1.95)]),
    ("U06", B, [(0.00, 1.95)]),
    ("U07", C, [(0.00, 1.53)]),
    ("U08", C, [(0.00, 1.55)]),
]

# bottom: shared batteries, (start, end, solid?)
bottom = [
    ("A-BAT-01", A, [(0.00,0.65,1),(0.65,1.00,0),(1.02,1.65,1),(1.65,2.05,0)]),
    ("A-BAT-02", A, [(0.00,0.48,1),(0.48,0.82,0),(0.85,1.45,1),(1.45,1.85,0)]),
    ("A-BAT-03", A, [(0.00,0.35,1),(0.35,0.62,0),(0.65,1.20,1),(1.20,1.55,0)]),
    ("A-BAT-04", A, [(0.00,0.62,1),(0.62,0.92,0),(1.05,1.80,1),(1.80,2.15,0)]),
    ("A-BAT-05", A, [(0.35,1.00,1),(1.00,1.38,0)]),
    ("A-BAT-06", A, [(0.50,1.02,1),(1.02,1.42,0)]),
    ("B-BAT-01", B, [(0.00,0.45,1),(0.45,0.85,0),(0.88,1.40,1),(1.40,1.85,0)]),
    ("B-BAT-02", B, [(0.00,0.45,1),(0.45,0.85,0),(0.88,1.45,1),(1.45,1.98,0)]),
    ("B-BAT-03", B, [(0.48,0.85,1),(0.85,1.30,0),(1.45,1.95,1),(1.95,2.48,0)]),
    ("B-BAT-04", B, [(0.48,0.85,1),(0.85,1.28,0),(1.45,1.95,1),(1.95,2.45,0)]),
    ("C-BAT-01", C, [(0.00,0.48,1),(0.48,0.90,0),(1.05,1.55,1),(1.55,2.10,0)]),
    ("C-BAT-02", C, [(0.00,0.45,1),(0.45,0.88,0),(0.92,1.55,1),(1.55,2.28,0)]),
    ("C-BAT-03", C, [(0.50,1.05,1),(1.05,1.70,0)]),
    ("C-BAT-04", C, [(0.52,0.90,1),(0.90,1.35,0)]),
]

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 9), dpi=300, sharex=True,
                               gridspec_kw={"height_ratios": [8, 14], "hspace": 0.08})

H = 0.6

# top panel
for i, (name, color, segs) in enumerate(top):
    y = len(top) - 1 - i
    for (s, e) in segs:
        ax1.barh(y, e - s, left=s, height=H, color=color, edgecolor="none")
ax1.set_yticks([len(top)-1-i for i in range(len(top))])
ax1.set_yticklabels([t[0] for t in top], fontsize=9.5)
ax1.set_ylabel("运输无人机", fontsize=12, labelpad=8)
ax1.set_ylim(-0.6, len(top)-0.4)

# bottom panel
for i, (name, color, segs) in enumerate(bottom):
    y = len(bottom) - 1 - i
    for (s, e, solid) in segs:
        c = color if solid else pale[color]
        ax2.barh(y, e - s, left=s, height=H, color=c, edgecolor="none")
ax2.set_yticks([len(bottom)-1-i for i in range(len(bottom))])
ax2.set_yticklabels([b[0] for b in bottom], fontsize=9.5)
ax2.set_ylabel("共享电池", fontsize=12, labelpad=8)
ax2.set_ylim(-0.6, len(bottom)-0.4)

# x axis
ax2.set_xlim(0, 2.6)
ax2.set_xticks([0, 0.5, 1.0, 1.5, 2.0, 2.5])
ax2.set_xticklabels(["0.0", "0.5", "1.0", "1.5", "2.0", "2.5"], fontsize=10)
ax2.set_xlabel("任务开始后时间（h）", fontsize=12, labelpad=8)

for ax in (ax1, ax2):
    ax.grid(axis="x", color="#dddddd", lw=0.7)
    ax.set_axisbelow(True)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)

# legend
legend_elems = [
    Patch(facecolor=A, label="模型 A"),
    Patch(facecolor=B, label="模型 B"),
    Patch(facecolor=C, label="模型 C"),
]
ax1.legend(handles=legend_elems, loc="upper center", bbox_to_anchor=(0.5, 1.12),
          ncol=3, frameon=False, fontsize=10)

# note (bottom-right empty area of bottom panel)
ax2.text(0.99, 0.04, "实心：执行任务　　浅色：充电 / 备用",
         transform=ax2.transAxes, fontsize=10.5, va="bottom", ha="right")

fig.tight_layout()
out_dir = r"C:\Users\xwz\Desktop\华为杯数学建模\2026\中文题目\D题\figures"
os.makedirs(out_dir, exist_ok=True)
png = os.path.join(out_dir, "result_q2_resources_cn.png")
pdf = os.path.join(out_dir, "result_q2_resources_cn.pdf")
fig.savefig(png, dpi=300, bbox_inches="tight")
fig.savefig(pdf, bbox_inches="tight")
print("saved", png)
