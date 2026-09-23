"""Create data-driven PDF figures from the verified D-question results."""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "figures"
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["pdf.fonttype"] = 42


def read(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, bbox_inches="tight")
    (OUT / "previews").mkdir(exist_ok=True)
    fig.savefig(OUT / "previews" / name.replace(".pdf", ".png"), dpi=120, bbox_inches="tight")
    plt.close(fig)


def q1_reserve():
    rows = read("results/q1_reproduced/solution.json")["sensitivity"]
    x = [int(100 * r["reserve"]) for r in rows]
    y = [r["sorties"] if r["feasible"] else np.nan for r in rows]
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    ax.plot(x, y, color="#166A83", marker="o", linewidth=2)
    for xi, yi in zip(x, y):
        if np.isfinite(yi):
            ax.annotate(str(int(yi)), (xi, yi), xytext=(0, 7), textcoords="offset points", ha="center")
        else:
            ax.annotate("不可行", (xi, 16.5), ha="center", va="center", color="#A94442", fontsize=9)
    ax.set_xlabel("返航安全余量（%）")
    ax.set_ylabel("最少运输架次")
    ax.set_xticks(x)
    ax.set_ylim(16, 22)
    ax.grid(axis="y", alpha=.25)
    save(fig, "q1_reserve_sensitivity.pdf")


def q2_tradeoff():
    d = read("results/q2/tradeoff_comparison.json")
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    for key, label, color in [
        ("time_priority", "时效优先（B 型容量）", "#1E6F9E"),
        ("economy_priority", "能耗与架次较低（C 型容量）", "#DA7635"),
    ]:
        m = d[key]
        x, y = m["weighted_tardiness_s"] / 1e6, m["energy_kwh"]
        ax.scatter(x, y, s=190, color=color, zorder=3)
        ax.annotate(f"{label}\n{m['sorties']} 架次", (x, y), xytext=(8, 7),
                    textcoords="offset points", fontsize=9)
    ax.set_xlabel("加权超期（百万优先系数·s）")
    ax.set_ylabel("运输能耗（kWh）")
    ax.grid(alpha=.25)
    ax.set_xlim(.3, 1.65)
    ax.set_ylim(78, 118)
    save(fig, "q2_time_energy_tradeoff.pdf")


def q3_candidates():
    d = read("results/q3/candidate_comparison.json")
    rows = d["candidates"]
    fig, axes = plt.subplots(1, 2, figsize=(10.0, 6.5), sharey=True)
    y = np.arange(len(rows))
    for i, row in enumerate(rows):
        if "metrics" not in row:
            axes[0].text(.02, i, "未找到可行解", transform=axes[0].get_yaxis_transform(),
                         va="center", fontsize=8, color="#9B5555")
            continue
        m = row["metrics"]
        selected = row["candidate"] == d["selected"]
        color = "#187B59" if row["strict_three_group_feasible"] else "#9A9A9A"
        marker = "*" if selected else "o"
        size = 160 if selected else 45
        axes[0].scatter(m["weighted_tardiness_s"]/1e6, i, color=color, marker=marker,s=size)
        axes[1].scatter(m["total_energy_kwh"], i, color=color, marker=marker,s=size)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([row["id"] for row in rows])
    axes[0].invert_yaxis()
    axes[0].set_ylabel("实验编号（对应报告中的实验设置）")
    axes[0].set_xlabel("加权超期（百万优先系数·s）")
    axes[1].set_xlabel("运输与中继总能耗（kWh）")
    for ax in axes: ax.grid(axis="x",alpha=.25)
    fig.tight_layout()
    save(fig,"q3_joint_candidates.pdf")


def q2_search():
    m = read("results/q2/schedule.json")["metrics"]
    rows = m["search_summary"]
    fig,axes = plt.subplots(1,2,figsize=(10.0,3.8))
    x = np.arange(len(rows))
    means = [r["mean_weighted_tardiness_s"]/1e6 for r in rows]
    std = [r["stdev_weighted_tardiness_s"]/1e6 for r in rows]
    best = [r["best_score"][0]/1e6 for r in rows]
    axes[0].errorbar(x,means,yerr=std,fmt="o",capsize=4,label="均值±标准差",color="#35799A")
    axes[0].scatter(x,best,marker="x",label="最好值",color="#D57936")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([f"{r['cap_model']}/{r['max_stops']}站" for r in rows])
    axes[0].set_xlabel("容量模板 / 停靠上限")
    axes[0].set_ylabel("加权超期（百万优先系数·s）")
    axes[0].legend(frameon=False,fontsize=8)
    history=m["local_search"]
    values=[history["initial_score"][0]]+[r["score"][0] for r in history["accepted_moves"]]
    axes[1].plot(range(len(values)),np.array(values)/1e6,"o-",color="#187B59")
    axes[1].set_xticks(range(len(values)))
    axes[1].set_xlabel("接受的局部改进次数")
    axes[1].set_ylabel("加权超期（百万优先系数·s）")
    for ax in axes: ax.grid(axis="y",alpha=.25)
    fig.tight_layout()
    save(fig,"q2_multistart_local_search.pdf")


def q3_timeline():
    d = read("results/q3/solution.json")
    fig, ax = plt.subplots(figsize=(10.5, 6.5))
    transport = d["transport"]
    for i, route in enumerate(transport):
        ax.barh(i, (route["end"] - route["start"]) / 3600, left=route["start"] / 3600,
                height=.7, color="#277DA1")
    offset = len(transport) + 1
    for i, mission in enumerate(d["relays"]):
        ax.barh(offset + i, (mission["end"] - mission["launch"]) / 3600,
                left=mission["launch"] / 3600, height=.7, color="#E49145")
    ax.axhline(len(transport) - .1, color="#555555", linewidth=.8)
    ax.set_xlabel("统一时间起点后（小时）")
    ax.set_ylabel("运输架次（蓝） / 中继架次（橙）")
    ax.set_yticks([0, len(transport)-1, offset, offset+len(d["relays"])-1])
    ax.set_yticklabels(["运输 1", f"运输 {len(transport)}", "中继 1", f"中继 {len(d['relays'])}"])
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=.25)
    save(fig, "q3_joint_timeline.pdf")


def q4_inventory():
    d = read("results/q4/partitions.json")
    names = ["运输机 A", "运输机 B", "运输机 C", "电池 A", "电池 B",
             "电池 C", "中继机", "中继组件"]
    keys = ["drone_A", "drone_B", "drone_C", "battery_A", "battery_B",
            "battery_C", "relay", "relay_component"]
    x = np.arange(len(keys))
    fig, ax = plt.subplots(figsize=(9.3, 4.0))
    width = .25
    stock = d["stock"]
    a = d["partitions"]["2"]["total_allocation"]
    b = d["partitions"]["3"]["total_allocation"]
    ax.bar(x-width, [stock[k] for k in keys], width, label="现有库存", color="#7FAF89")
    ax.bar(x, [a[k] for k in keys], width, label="两组需求", color="#247BA0")
    ax.bar(x+width, [b[k] for k in keys], width, label="三组需求", color="#E18A49")
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=25, ha="right")
    ax.set_ylabel("设备或能源组件数量")
    ax.legend(frameon=False, ncol=3)
    ax.grid(axis="y", alpha=.25)
    save(fig, "q4_inventory_gap.pdf")


def main():
    q1_reserve()
    q2_tradeoff()
    q2_search()
    q3_candidates()
    q3_timeline()
    q4_inventory()
    print("PDF figures:", *(p.name for p in sorted(OUT.glob("*.pdf"))))


if __name__ == "__main__":
    main()
