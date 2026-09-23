"""Detailed, reproducible Markdown tables for all four questions."""
from common import ROOT


def val(x, digits=2):
    return "—" if x is None else f"{x:.{digits}f}"


def write(q1, q2, q3, missions, q4):
    lines = ["# 四问详细方案表", "",
             "本文件由 `code/run_all.py` 根据已验证的结构化结果生成。时间单位为灾后统一起点后的秒；载荷、能耗和海拔分别采用 kg、kWh、m。", "",
             "## 问题一：机型—服务区最大安全载荷", "",
             "返航余量为 20%；表内数值为质量上限，实际货箱组批还须满足体积限制。", "",
             "| 服务区 | A kg | B kg | C kg |", "| --- | ---: | ---: | ---: |"]
    caps = {(r["area"], r["model"]): r["max_safe_kg"] for r in q1["capacities"]}
    for area in sorted({a for a, _ in caps}):
        lines.append(f"| {area} | {val(caps[area,'A'],3)} | {val(caps[area,'B'],3)} | {val(caps[area,'C'],3)} |")
    lines += ["", "## 问题二：运输架次", "",
              "| 架次 | 机型 | 无人机 | 电池 | 访问服务区 | 箱数 | 开始 s | 返航 s | 能耗 kWh | 返航 SOC % |",
              "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for r in q2:
        lines.append(f"| {r['sortie']} | {r['model']} | {r['drone']} | {r['battery']} | {'→'.join(r['order'])} | {len(r['boxes'])} | {val(r['start'],1)} | {val(r['end'],1)} | {val(r['energy'],3)} | {val(100*r['soc'],2)} |")
    lines += ["", "每架次的完整货箱编号及逐箱交付时刻见 `results/q2/sorties.csv` 和 `results/q2/deliveries.csv`。", "",
              "## 问题三：中继架次", "",
              "| 中继机 | 组件 | 悬停点 | 经度 | 纬度 | 悬停海拔 m | 发射 s | 建链完成 s | 服务结束 s | 返航 s | 能耗 kWh | 返航 SOC % |",
              "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for m in sorted(missions, key=lambda x: x["launch"]):
        s = m["site"]
        lines.append(f"| {m['relay']} | {m['component']} | {s['id']} | {val(s['lon'],6)} | {val(s['lat'],6)} | {val(s['z'],2)} | {val(m['launch'],1)} | {val(m['service_start'],1)} | {val(m['service_end'],1)} | {val(m['end'],1)} | {val(m['energy'],3)} | {val(100*m['soc'],2)} |")
    lines += ["", "问题三从多种组批方案中选出可严格分区的联合方案，运输路线与问题二时效优先方案可能不同；起飞时刻及逐箱交付时刻还受中继保障约束。完整联合时序见 `results/q3/solution.json`，逐采样点保障方式见 `results/q3/communication_samples.csv`。", "",
              "## 问题四：分区与资源配置", "",
              "资源次序为 A/B/C 运输机、A/B/C 电池、中继机、中继能源组件。缺口按所有任务组需求相加后与库存比较。", ""]
    for k in (2, 3):
        result = q4["partitions"][k]
        lines += [f"### {k} 个任务组：库存缺口优先方案", "",
                  f"总缺口 {result['shortage_total']} 单位；资源增量 {result['redundancy_total']} 单位；工作量不均衡 {val(result['workload_imbalance'],3)}。", "",
                  "| 组 | 服务区 | 箱数 | 运输架次 | 中继架次 | 累计作业 s | 运输机 A/B/C | 电池 A/B/C | 中继机/组件 |",
                  "| ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- |"]
        for group in result["groups"]:
            a = group["allocation"]
            lines.append(f"| {group['group']} | {', '.join(group['areas'])} | {group['boxes']} | {group['transport_sorties']} | {group['relay_sorties']} | {val(group['workload_s'],1)} | {a['drone_A']}/{a['drone_B']}/{a['drone_C']} | {a['battery_A']}/{a['battery_B']}/{a['battery_C']} | {a['relay']}/{a['relay_component']} |")
        shortage = ", ".join(f"{r}: {n}" for r, n in result["shortage"].items() if n)
        lines += ["", "库存缺口：" + (shortage or "无") + "。", ""]
        alternative = q4["alternatives"][k]["balanced"]
        lines += [f"均衡优先备选：工作量不均衡 {val(alternative['workload_imbalance'],3)}，库存缺口 {alternative['shortage_total']} 单位；完整配置见 `results/q4/partitions.json`。", ""]
    (ROOT / "reports" / "FOUR_PROBLEM_DETAILS.md").write_text("\n".join(lines), encoding="utf-8")
