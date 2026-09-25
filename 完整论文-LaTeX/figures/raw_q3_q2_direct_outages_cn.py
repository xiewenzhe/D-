# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib as mpl
import os

mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
mpl.rcParams["axes.unicode_minus"] = False
mpl.rcParams["font.size"] = 10

# direct outage fraction per Q2 sortie index (read from source figure)
data = {
    1: 0.485, 2: 0.405,
    4: 0.392, 5: 0.350, 6: 0.345,
    9: 0.583, 10: 0.345, 11: 0.335, 12: 0.560, 13: 0.510,
    16: 0.500, 17: 0.485, 18: 0.505, 19: 0.408, 20: 0.280,
    22: 0.485, 23: 0.485, 24: 0.482, 25: 0.500,
}
BAR = "#d98a2b"
ACCENT = "#b5651d"

fig, ax = plt.subplots(figsize=(9.2, 4.6), dpi=300)
fig.patch.set_facecolor("white")
ax.set_facecolor("white")

xs = list(data.keys())
ys = list(data.values())
ax.bar(xs, ys, width=0.68, color=BAR, edgecolor="none", zorder=3)
# highlight the max and min
imax = max(data, key=data.get)
imin = min(data, key=data.get)
ax.bar([imax], [data[imax]], width=0.68, color=ACCENT, edgecolor="none", zorder=4)
ax.text(imax, data[imax] + 0.02, f"{data[imax]:.2f}", ha="center",
        fontsize=8, color=ACCENT, fontweight="bold")
ax.text(imin, data[imin] + 0.02, f"{data[imin]:.2f}", ha="center",
        fontsize=8, color="#888888")

ax.set_xlim(0.2, 25.8)
ax.set_ylim(0, 1.0)
ax.set_xticks([1, 4, 7, 10, 13, 16, 19, 22, 25])
ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
ax.set_yticklabels(["0.0", "0.2", "0.4", "0.6", "0.8", "1.0"])
ax.set_xlabel("Q2 架次序号", fontsize=11.5, labelpad=8)
ax.set_ylabel("直接断电比例", fontsize=11.5, labelpad=8)

ax.grid(axis="y", color="#e8e8e8", lw=0.7, zorder=0)
ax.set_axisbelow(True)
for sp in ["top", "right"]:
    ax.spines[sp].set_visible(False)

fig.tight_layout()
out_dir = r"C:\Users\xwz\Desktop\华为杯数学建模\2026\中文题目\D题\完整论文-LaTeX\figures"
png = os.path.join(out_dir, "raw_q3_q2_direct_outages_cn.png")
pdf = os.path.join(out_dir, "raw_q3_q2_direct_outages_cn.pdf")
fig.savefig(png, dpi=300, bbox_inches="tight")
fig.savefig(pdf, bbox_inches="tight")
print("saved", png)
