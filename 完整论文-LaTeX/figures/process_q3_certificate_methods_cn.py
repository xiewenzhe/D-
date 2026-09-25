# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib as mpl
import os

mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
mpl.rcParams["axes.unicode_minus"] = False
mpl.rcParams["font.size"] = 10

methods = ["最坏损失法", "扫掠 DEM 净空法"]
vals = [966, 351]
colors = ["#9c3a48", "#c05a4e"]

fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=300)
fig.patch.set_facecolor("white")
ax.set_facecolor("white")

bars = ax.bar(methods, vals, width=0.55, color=colors, edgecolor="none", zorder=3)
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width()/2, v + 18, f"{v}",
            ha="center", fontsize=11, fontweight="bold", color="#7a2a33")

ax.set_ylim(0, 1060)
ax.set_yticks([0, 200, 400, 600, 800, 1000])
ax.set_ylabel("已认证区间数", fontsize=11.5, labelpad=8)
ax.set_xlabel("认证方法", fontsize=11.5, labelpad=8)
ax.tick_params(axis="x", labelsize=10.5)

ax.grid(axis="y", color="#e8e0e0", lw=0.7, zorder=0)
ax.set_axisbelow(True)
for sp in ["top", "right"]:
    ax.spines[sp].set_visible(False)

fig.tight_layout()
out_dir = r"C:\Users\xwz\Desktop\华为杯数学建模\2026\中文题目\D题\完整论文-LaTeX\figures"
png = os.path.join(out_dir, "process_q3_certificate_methods_cn.png")
pdf = os.path.join(out_dir, "process_q3_certificate_methods_cn.pdf")
fig.savefig(png, dpi=300, bbox_inches="tight")
fig.savefig(pdf, bbox_inches="tight")
print("saved", png)
