# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib as mpl
import os

mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
mpl.rcParams["axes.unicode_minus"] = False
mpl.rcParams["font.size"] = 10

# transport sorties T1..T24 (start, end) h, read from source
transport = [
    (0.05, 0.60), (0.05, 0.45), (0.05, 0.38), (0.05, 0.35),
    (0.05, 0.48), (0.05, 0.35), (0.05, 0.25), (0.05, 0.45),
    (0.45, 0.85),
    (0.60, 1.20), (0.60, 1.15), (0.60, 1.05), (0.60, 1.20), (0.60, 1.05),
    (0.60, 1.20),
    (1.00, 1.55), (1.00, 1.45),
    (1.15, 1.75), (1.15, 1.65), (1.15, 1.55),
    (1.30, 1.85), (1.30, 1.70),
    (1.55, 2.10), (1.70, 2.40),
]
# relay missions R1..R5 (bottom->top)
relay = [(0.10, 2.10), (0.10, 0.50), (0.60, 1.20), (1.30, 1.90), (1.95, 2.40)]
RELAY = "#c87b58"
TRANS = "#9c3a48"

fig, ax = plt.subplots(figsize=(10.5, 7.2), dpi=300)
fig.patch.set_facecolor("white")
ax.set_facecolor("white")

# transport bars (T1 at bottom)
for i, (s, e) in enumerate(transport):
    ax.barh(i, e - s, left=s, height=0.62, color=TRANS, edgecolor="none", zorder=3)

# relay bars above divider
off = len(transport) + 1
for j, (s, e) in enumerate(relay):
    ax.barh(off + j, e - s, left=s, height=0.62, color=RELAY, edgecolor="none", zorder=3)

# divider
ax.axhline(len(transport) + 0.5, color="#888888", lw=1.0, zorder=2)

# ticks: group labels (T1=row0, T6=row5, ... T24=row23)
major = {0: "T1", 5: "T6", 10: "T11", 15: "T16", 20: "T21", 23: "T24"}
ax.set_yticks(list(major.keys()))
ax.set_yticklabels(list(major.values()), fontsize=10)
ax.set_yticks([off + j for j in range(len(relay))], minor=True)
ax.set_yticklabels(["R1", "R2", "R3", "R4", "R5"], minor=True, fontsize=10)
ax.tick_params(axis="y", which="minor", pad=14)

ax.set_xlim(-0.08, 2.55)
ax.set_ylim(-0.7, off + len(relay) - 0.3)
ax.set_xticks([0, 0.5, 1.0, 1.5, 2.0, 2.5])
ax.set_xticklabels(["0.0", "0.5", "1.0", "1.5", "2.0", "2.5"], fontsize=10)
ax.set_xlabel("任务开始后时间（h）", fontsize=12, labelpad=8)
ax.set_ylabel("运输架次（下）／中继任务（上）", fontsize=12, labelpad=10)

ax.grid(axis="x", color="#e8e0e0", lw=0.7, zorder=0)
ax.set_axisbelow(True)
for sp in ["top", "right"]:
    ax.spines[sp].set_visible(False)

fig.tight_layout()
out_dir = r"C:\Users\xwz\Desktop\华为杯数学建模\2026\中文题目\D题\完整论文-LaTeX\figures"
png = os.path.join(out_dir, "result_q3_joint_timeline_cn.png")
pdf = os.path.join(out_dir, "result_q3_joint_timeline_cn.pdf")
fig.savefig(png, dpi=300, bbox_inches="tight")
fig.savefig(pdf, bbox_inches="tight")
print("saved", png)
