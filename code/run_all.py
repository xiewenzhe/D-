"""Reproduce all four D-problem solutions and checked deliverables.

Run from any directory: D:\\anaconda\\python.exe D-\\code\\run_all.py
Dependencies: numpy, scipy, openpyxl, tifffile. No web access required.
"""
from __future__ import annotations
import csv
import hashlib
import json
import platform
import time
from collections import Counter
import sys
from pathlib import Path
import numpy
import scipy
import openpyxl
import tifffile
from common import ROOT, read_inputs, Terrain, Physics
import problem1
import problem2
import problem3
import problem4
import write_details
import plot_results
import continuous_validation
import model_checks


def csv_file(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def source_hashes():
    files = [next((ROOT / "数据").rglob("*.tif")), *sorted((ROOT / "数据").rglob("*.xlsx")),
             *sorted((ROOT / "code").glob("*.py"))]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def write_markdown(q1, q2, q2c, q3, q4):
    p2 = q4["partitions"][2]
    p3 = q4["partitions"][3]
    def rd(x, n=2):
        return f"{x:.{n}f}"
    lines = [
        "# 四问计算结果与核验记录", "",
        "本报告由 `code/run_all.py` 从本地题目附件重新计算。目标采用分层优先序：先满足全部硬约束，再比较加权超期、完工时间、能耗和架次数；所得调度为可行启发式方案，不声称全局最优。问题一的逐区组批采用精确动态规划，问题四在运输与中继固定任务形成的不可拆分连通块上完整枚举。", "",
        "## 运行环境与输入", "",
        "- Python " + platform.python_version() + "；numpy " + numpy.__version__ + "；scipy " + scipy.__version__ + "；openpyxl " + openpyxl.__version__ + "；tifffile " + tifffile.__version__ + "。",
        "- 读取 1 个中心、15 个服务区、80 个不可拆货箱、3 种运输机型、8 架实体运输机、2 架中继机、5 份 Excel 参数表与 30 米 DEM。",
        "- DEM 采用 PixelIsPoint 的半像元换算；问题一与原有结果的总能耗差约 " + rd(abs(q1["metrics"]["energy_kwh"] - json.loads((ROOT / "results" / "q1" / "solution.json").read_text(encoding="utf-8"))["totals"]["E"]), 8) + " kWh。",
        "- 输入与代码 SHA-256 见 `results/run_manifest.json`。", "",
        "## 问题一：单点往返能力与组批", "",
        f"在 20% 返航余量下，45 个机型—服务区组合的最大安全载荷见 `results/q1_reproduced/solution.json`。80 箱由 {q1['metrics']['sorties']} 架次交付，总运输能耗 {rd(q1['metrics']['energy_kwh'], 6)} kWh，累计作业时间 {rd(q1['metrics']['cumulative_work_s'], 3)} s；最小返航 SOC 为 {rd(100*q1['metrics']['min_soc'], 3)}%。逐区类型计数动态规划按（架次数、能耗、作业时间）字典序求解，所有货箱唯一交付。同区同类箱的质量和体积同质性已由程序断言；每档余量的 45 个安全载荷与具体组批均写入 sensitivity。",
        "", "安全余量情景：", "", "| 余量 | 可行 | 最少架次 | 运输能耗 kWh | 累计作业时间 s | 不可行服务区 |", "| ---: | :---: | ---: | ---: | ---: | :--- |",
    ]
    for r in q1["sensitivity"]:
        lines.append(f"| {rd(100*r['reserve'], 0)}% | {'是' if r['feasible'] else '否'} | {r['sorties'] if r['feasible'] else '—'} | {rd(r['energy_kwh'], 3) if r['feasible'] else '—'} | {rd(r['cumulative_work_s'], 1) if r['feasible'] else '—'} | {','.join(r['infeasible_areas']) or '—'} |")
    lines += ["", "## 问题二：异构多点运输调度", "",
              f"主方案交付 80 箱，使用 {q2['sorties']} 架次，其中 {q2['multi_area_sorties']} 架次访问多个服务区。运输能耗 {rd(q2['energy_kwh'], 3)} kWh，全部运输机返航完工时间 {rd(q2['makespan_s'], 1)} s。医疗期望时限及首批截止时间违反数为 {q2['hard_deadline_violations']}；其他期望时刻按优先系数加权，超期量为 {rd(q2['weighted_tardiness_s'], 1)} 优先系数·s，超期箱数 {q2['late_boxes']}。逐架次与逐箱结果见 `results/q2/`。", "",
              f"对照方案按 C 型容量组批，得到 {q2c['sorties']} 架次、{rd(q2c['energy_kwh'],3)} kWh、{rd(q2c['makespan_s'],1)} s、加权超期 {rd(q2c['weighted_tardiness_s'],1)} 优先系数·s。主方案在 B/C 容量模板、1/2/3 站上限及各 15 个调度起点中按加权超期、完工时间、能耗、架次数的顺序选出；C 型两站对照方案节约能量和架次，展示可行的权衡，但不称其为时效最优。", "",
              "回代检查：80 个编号各出现一次；所有架次的质量、体积、返航余量有效；同一实体无人机占用时段及同一共享电池的占用—充电时段没有重叠。", "",
              "## 问题三：运输与通信中继联合调度", "",
              f"联合方案由 {q3['candidate']} 组批候选生成，重新确定运输架次及起飞时刻，并安排 {q3['relay_sorties']} 个中继架次；共有 {q3['sorties']} 个运输架次。运输能耗 {rd(q3['energy_kwh'],3)} kWh，中继能耗 {rd(q3['relay_energy_kwh'],3)} kWh，合计 {rd(q3['total_energy_kwh'],3)} kWh；联合任务完成时间 {rd(q3['joint_makespan_s'],1)} s。加权超期为 {rd(q3['weighted_tardiness_s'],1)} 优先系数·s，医疗与首批硬时限仍全部满足。", "",
              f"采用题面 8 dB 衰落裕量之外额外 1 dB 设计裕量。沿爬升、巡航、下降和交接阶段以 1 s 间隔回代 {q3['communication_samples']} 个时空点，其中直连 {q3['direct_samples']} 点、中继 {q3['relayed_samples']} 点、通信中断 {q3['communication_breaks']} 点。相对于更严格门限的最小剩余裕量 {rd(q3['minimum_link_margin_db'],4)} dB；相对于题面门限至少多 1 dB。建模时以不大于 7.5 m 的水平间隔预检视线；最终改用 DEM 逐像元保守遮挡判断。另以 0.5 s 间隔复核 {q3['refined_samples_0p5s']} 个点，中断 {q3['refined_breaks_0p5s']} 点；更严格门限下最小裕量 {rd(q3['refined_min_margin_db'],4)} dB。两种时间离散核验均不能当作连续时间的数学证明；结果字段 continuous_validation_passed 为 false。", "",
              "中继任务计入建链期间的悬停和通信耗能、返航 20% 余量、架次周转以及能源组件两阶段充电。中继水平巡航采用沿线最高地形加 50 m；当悬停海拔更高时，在航段端点继续垂直爬升至悬停位置。悬停点位于 DEM 范围内，离地不超过 300 m。运输与中继资源冲突数均为 0。逐时空点记录见 `results/q3/communication_samples.csv`。", "",
              "## 问题四：两组与三组分区", "",
              "将同一运输架次访问的服务区及同一中继架次保障的服务区合并为不可拆分连通块。分区不复制、拆分或改时任何运输和中继任务。各组同型资源的最小需求按固定占用和充电区间的最大并发数计算，实体编号可在组内重新指定。选方案的优先序为最小库存缺口、再最小工作量不均衡、最后最小资源增量。", "",
              "| 分组数 | 枚举方案数 | 最小库存缺口 单位 | 资源增量 单位 | 工作量不均衡 |", "| ---: | ---: | ---: | ---: | ---: |",
              f"| 2 | {q4['search'][2]['enumerated_partitions']} | {p2['shortage_total']} | {p2['redundancy_total']} | {rd(p2['workload_imbalance'],3)} |",
              f"| 3 | {q4['search'][3]['enumerated_partitions']} | {p3['shortage_total']} | {p3['redundancy_total']} | {rd(p3['workload_imbalance'],3)} |", "",
              "工作量不均衡定义为（组间最大累计运输作业时间－最小值）／组平均值。资源增量为各组独立配置之和相对第三问联合执行最小并发需求的差。具体服务区分配、各型无人机和能源资源需求、库存缺口，以及最小缺口、最均衡、最小冗余备选见 `results/q4/partitions.json`。", "",
              "## 论文可用图表", "",
              "五张数据驱动 PDF 图位于 `figures/`：返航余量敏感性、问题二时效—能耗权衡、问题三联合候选、运输与中继时间轴、问题四库存与需求。作图脚本为 `code/plot_results.py`，数据直接来自上述 JSON。", "",
              "## 约束、一致性与复现", "",
              "- 问题一的 DEM 最高高程及总能耗与已有 `results/q1/solution.json` 交叉核对；差异仅来自局部椭球距离近似。",
              "- 问题二、三逐箱唯一交付，硬时限与资源占用按原始附件回代；问题三以 1 s 和 0.5 s 两档采样检查双向链路、悬停高度、中继电量和充电周转，不能据此宣称连续时间严格可行。",
              "- 问题四枚举 2 组和 3 组全部非同构分区，每个服务区恰属一组；跨组运输或中继任务数为 0，中继任务复制数为 0。",
              "- 运行命令：`D:\\anaconda\\python.exe D-\\code\\run_all.py`。程序从当前项目附件读取输入，覆盖本报告及 `results/q1_reproduced`、`results/q2`、`results/q3`、`results/q4` 中由本次代码生成的结果。", "",
              "## 适用边界", "",
              "运输水平能耗与爬升能耗沿用问题一分析报告中对附录 2 的显式解释。问题二、三为有限候选批次、悬停点、高度和时间搜索的可行启发式，不提供全局最优证书。通信最终采用 DEM 逐像元遮挡判定，但仍存在 1 s 时间离散误差；若用于实际飞行，应增加风、天气、设备容差和现场链路实测。", ""]
    report = ROOT / "reports" / "RESULTS_REPORT.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")


def main():
    nodes, boxes, models, drones, batteries, relay_model, relays, relay_energy, comm = read_inputs()
    physics = Physics(nodes, Terrain())
    model_check_results = {"geometry": model_checks.geometric_checks(),
                           "small_exact_benchmark": model_checks.small_exact_benchmark(boxes,models,batteries,physics)}
    (ROOT / "results" / "model_checks.json").write_text(json.dumps(model_check_results,indent=2),encoding="utf-8")
    q1 = problem1.solve(boxes, models, physics)
    problem1.save(q1)

    # Question 2: compare both capacity templates under one lexicographic objective.
    q2_bank = {}
    q2_schedule, q2_metrics, batches = problem2.solve(
        boxes, models, drones, batteries, physics, trials=15,
        cap_models=("B", "C"), max_stops_options=(1, 2, 3), candidate_store=q2_bank)
    problem2.save(q2_schedule, q2_metrics, batches)
    q2c_schedule, q2c_metrics, q2c_batches = problem2.solve(
        boxes, models, drones, batteries, physics, trials=15,
        cap_models=("C",), max_stops_options=(2,), local_search_rounds=0)
    problem2.save(q2c_schedule, q2c_metrics, q2c_batches, ROOT / "results" / "q2" / "capacity_C")
    (ROOT / "results" / "q2" / "tradeoff_comparison.json").write_text(
        json.dumps({"time_priority": q2_metrics, "economy_priority": q2c_metrics},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "results" / "q2" / "small_batch_comparison.json").unlink(missing_ok=True)
    csv_file(ROOT / "results" / "q2" / "sorties.csv", [
        {"sortie": r["sortie"], "drone": r["drone"], "model": r["model"], "battery": r["battery"],
         "start_s": r["start"], "end_s": r["end"], "areas": ";".join(r["order"]),
         "boxes": ";".join(r["boxes"]), "energy_kwh": r["energy"], "return_soc_pct": 100*r["soc"]}
        for r in q2_schedule])
    csv_file(ROOT / "results" / "q2" / "deliveries.csv", [
        {"box": i, "sortie": r["sortie"], "area": boxes[i]["area"], "delivery_s": t,
         "desired_s": boxes[i]["desired"], "hard_due_s": problem2.hard_due(boxes[i])}
        for r in q2_schedule for i, t in r["delivery"].items()])

    # Q3 ablation and transport alternatives reuse the same physical and relay solvers.
    comm["margin_db"] += 1.0
    split_batches, split_info = problem3.partition_aware_batches(
        q2c_schedule, boxes, physics, models, comm)
    split_starts=[]
    for seed in range(15):
        try:
            schedule=problem2.assign(split_batches,boxes,models,drones,batteries,physics,seed)
            metric=problem2.validate(schedule,boxes,models,drones,batteries,physics)
            split_starts.append((problem2.objective(metric)+(seed,),schedule,metric))
        except RuntimeError:
            pass
    if not split_starts:
        raise RuntimeError("No hard-feasible partition-aware transport schedule")
    _,split_schedule,split_metrics=min(split_starts,key=lambda x:x[0])
    levels=(.25,.5,.75,1.0)
    specs=[]
    def add(name,transport,category="transport_alternative",heights=levels,shift=True,seed=None):
        specs.append({"name":name,"transport":transport,"category":category,
                      "height_levels":heights,"allow_start_shift":shift,"transport_seed":seed})
    add("time_priority_B",q2_schedule,"fixed_transport_multilevel")
    add("fixed_transport_fixed_times",q2_schedule,"fixed_times_baseline",shift=False)
    add("height_300",q2_schedule,"height_ablation",heights=(1.0,))
    add("height_225_300",q2_schedule,"height_ablation",heights=(.75,1.0))
    add("height_150_225_300",q2_schedule,"height_ablation",heights=(.5,.75,1.0))
    add("before_local_B1",q2_bank["B_stops1"]["schedule"],seed=q2_bank["B_stops1"]["seed"])
    add("B_stops2",q2_bank["B_stops2"]["schedule"],seed=q2_bank["B_stops2"]["seed"])
    add("C_stops1",q2_bank["C_stops1"]["schedule"],seed=q2_bank["C_stops1"]["seed"])
    add("economy_priority_C",q2c_schedule,seed=q2c_metrics["selected_seed"])
    add("C_stops3",q2_bank["C_stops3"]["schedule"],seed=q2_bank["C_stops3"]["seed"])
    add("partition_aware_C",split_schedule)
    for seed in (0,1,2):
        add(f"B1_seed{seed}",problem2.assign(q2_bank["B_stops1"]["batches"],
            boxes,models,drones,batteries,physics,seed),"multistart",seed=seed)
    candidate_summary=[]
    all_joint=[]
    experiment_dir=ROOT/"results"/"q3"/"experiments"
    experiment_dir.mkdir(parents=True,exist_ok=True)
    for index,spec in enumerate(specs,1):
        name=spec["name"]
        print(f"Q3 experiment {index}/{len(specs)}: {name}",flush=True)
        tick=time.perf_counter()
        params={k:v for k,v in spec.items() if k!="transport"}
        row={"id":f"J{index:02d}","candidate":name,"parameters":params}
        try:
            joint,relay_jobs,sites,_,pair=problem3.plan_relay(
                spec["transport"],boxes,models,drones,batteries,physics,relay_model,
                relays,relay_energy,comm,sample_step=5,pair_limit=30,
                height_levels=spec["height_levels"],allow_start_shift=spec["allow_start_shift"])
            sampled_los=problem3.los_obstructed
            problem3.los_obstructed=problem3.los_obstructed_exact
            try:
                metrics,coverage=problem3.validate_joint(
                    joint,relay_jobs,boxes,models,drones,batteries,physics,
                    relay_model,relays,relay_energy,comm,step=1)
            finally:
                problem3.los_obstructed=sampled_los
            allowed=problem4.relay_support(joint,relay_jobs,coverage)
            certificate=continuous_validation.certify_schedule(
                joint,relay_jobs,physics,models,comm,allowed_support=allowed)
            if not certificate["passed"]:
                (experiment_dir/f"{name}_unresolved.json").write_text(
                    json.dumps(certificate,indent=2),encoding="utf-8")
                raise RuntimeError(f"Continuous certificate has {len(certificate['unresolved_intervals'])} unresolved intervals")
            used=sorted({r["mission"] for r in certificate["intervals"] if r["mission"]>=0})
            if len(used)<len(relay_jobs):
                remap={old:new for new,old in enumerate(used)}
                relay_jobs=[relay_jobs[j] for j in used]
                for record in certificate["intervals"]:
                    if record["mission"]>=0:
                        record["mission"]=remap[record["mission"]]
                sampled_los=problem3.los_obstructed
                problem3.los_obstructed=problem3.los_obstructed_exact
                try:
                    metrics,coverage=problem3.validate_joint(
                        joint,relay_jobs,boxes,models,drones,batteries,physics,
                        relay_model,relays,relay_energy,comm,step=1)
                finally:
                    problem3.los_obstructed=sampled_los
            relation_rows=continuous_validation.support_rows(certificate)
            support=problem4.relay_support(joint,relay_jobs,relation_rows)
            atoms=problem4.components(sorted({b["area"] for b in boxes.values()}),
                                      joint,relay_jobs,support)
            eligible=len(atoms)>=3
            metrics.update({"continuous_validation_passed":True,
                            "continuous_intervals":certificate["certified_intervals"],
                            "continuous_margin_lower_bound_db":certificate["minimum_margin_lower_bound_db"],
                            "continuous_scope":certificate["scope"],
                            "certificate_margin_db":certificate["communication_margin_db"],
                            "fixed_task_components":len(atoms),"candidate":name,
                            "validation":{"passed":True,"violations":[],
                                          "continuous_validation_passed":True}})
            score=(metrics["weighted_tardiness_s"],metrics["joint_makespan_s"],
                   metrics["total_energy_kwh"],metrics["sorties"]+metrics["relay_sorties"])
            row.update({"strict_three_group_feasible":eligible,"components":atoms,
                        "metrics":metrics,"site_count":len(sites),
                        "site_height_histogram":dict(Counter(
                            round(s["z"]-s["ground"],4) for s in sites)),
                        "elapsed_s":time.perf_counter()-tick,"status":"certified",
                        "score":score})
            all_joint.append((score,name,joint,relay_jobs,metrics,coverage,pair,certificate,relation_rows))
            (experiment_dir/f"{name}.json").write_text(
                json.dumps({"summary":row,"transport":joint,"relays":relay_jobs,
                            "certificate":certificate},ensure_ascii=False,indent=2),encoding="utf-8")
        except (RuntimeError,AssertionError,ValueError) as exc:
            row.update({"status":"search_or_validation_failed","error":str(exc),
                        "error_type":type(exc).__name__,"elapsed_s":time.perf_counter()-tick,
                        "mathematical_infeasibility_proven":False})
            (experiment_dir/f"{name}.json").write_text(
                json.dumps({"summary":row},ensure_ascii=False,indent=2),encoding="utf-8")
        candidate_summary.append(row)
        print(f"  {row['status']}, {row['elapsed_s']:.2f} s",flush=True)
    compatible=[x for x in all_joint if x[4]["fixed_task_components"]>=3]
    comparison={"selection_rule":"report unrestricted Q3 winner; choose Q4-compatible candidate separately",
                "split_rule":split_info,"split_transport_metrics":split_metrics,
                "candidates":candidate_summary,
                "best_unrestricted":min(all_joint,key=lambda x:x[0])[1] if all_joint else None,
                "selected":min(compatible,key=lambda x:x[0])[1] if compatible else None}
    (ROOT/"results"/"q3"/"candidate_comparison.json").write_text(
        json.dumps(comparison,ensure_ascii=False,indent=2),encoding="utf-8")
    if not compatible:
        raise RuntimeError("No certified candidate permits three fixed-task groups; candidate failures are recorded")
    _,selected_name,q3_schedule,missions,q3_metrics,communication_rows,pair,certificate,relation_rows=min(
        compatible,key=lambda x:x[0])
    geometry_affine=model_checks.affine_checks(q3_schedule,missions,physics,models)
    sampled_los=problem3.los_obstructed
    problem3.los_obstructed=problem3.los_obstructed_exact
    refinements=[]
    try:
        for step in (5,2,.5):
            refined,refined_rows=problem3.validate_joint(
                q3_schedule,missions,boxes,models,drones,batteries,physics,
                relay_model,relays,relay_energy,comm,step=step)
            refinements.append({"time_step_s":step,"communication_samples":refined["communication_samples"],
                                "communication_breaks":refined["communication_breaks"],
                                "minimum_link_margin_db":refined["minimum_link_margin_db"]})
            if step==.5:
                q3_metrics["refined_samples_0p5s"]=refined["communication_samples"]
                q3_metrics["refined_breaks_0p5s"]=refined["communication_breaks"]
                q3_metrics["refined_min_margin_db"]=refined["minimum_link_margin_db"]
    finally:
        problem3.los_obstructed=sampled_los
    refinements.append({"time_step_s":1,"communication_samples":q3_metrics["communication_samples"],
                        "communication_breaks":q3_metrics["communication_breaks"],
                        "minimum_link_margin_db":q3_metrics["minimum_link_margin_db"]})
    (ROOT/"results"/"q3"/"validation_refinement.json").write_text(
        json.dumps({"sampling":sorted(refinements,key=lambda x:x["time_step_s"],reverse=True),
                    "continuous":{k:v for k,v in certificate.items() if k!="intervals"},
                    "affine_checks":geometry_affine},ensure_ascii=False,indent=2),encoding="utf-8")
    (ROOT/"results"/"q3"/"continuous_certificate.json").write_text(
        json.dumps(certificate,ensure_ascii=False,indent=2),encoding="utf-8")
    csv_file(ROOT/"results"/"q3"/"continuous_intervals.csv",certificate["intervals"])
    q3_metrics["relay_height_levels_tested"]=list(levels)
    q3_metrics["relay_agl_m_selected"]=[m["site"]["z"]-m["site"]["ground"] for m in missions]
    problem3.save_joint(q3_schedule,missions,q3_metrics,communication_rows)
    csv_file(ROOT/"results"/"q3"/"relay_sorties.csv",[
        {"relay":m["relay"],"component":m["component"],"site":m["site"]["id"],
         "lon":m["site"]["lon"],"lat":m["site"]["lat"],"hover_altitude_m":m["site"]["z"],
         "launch_s":m["launch"],"service_start_s":m["service_start"],"service_end_s":m["service_end"],
         "return_s":m["end"],"energy_kwh":m["energy"],"return_soc_pct":100*m["soc"]} for m in missions])
    q4 = problem4.solve(q3_schedule, missions, relation_rows, boxes, drones, batteries,
                        relays, relay_energy, relay_model)
    problem4.save(q4)
    validations = {"q1": q1["validation"], "q2": q2_metrics["validation"],
                   "q3": q3_metrics["validation"], "q4": q4["validation"]}
    assert all(item["passed"] and not item["violations"] for item in validations.values())
    validations["q3"]["continuous_validation_passed"] = certificate["passed"]
    (ROOT / "results" / "validation_summary.json").write_text(
        json.dumps(validations, ensure_ascii=False, indent=2), encoding="utf-8")
    write_details.write(q1, q2_schedule, q3_schedule, missions, q4)
    manifest = {"solver_version": "D-2026-09-23-complete",
                "algorithm": "Q1 count-state DP; Q2 bounded 1/2/3-stop templates and 15 starts; Q3 transport alternatives plus relay search; Q4 exact fixed-task partition enumeration",
                "seed": q2_metrics["selected_seed"],
                "parameters": {"q2_max_stops": [1, 2, 3], "q2_trials": 15,
                               "q3_sample_step_s": 5, "relay_height_levels": [0.25, 0.5, 0.75, 1.0],
                               "relay_grid_stride": None, "validation_step_s": [1, 0.5]},
                "q2_starts": 90, "q3_candidates": [x["name"] for x in specs],
                "q3_sample_step_s": 5, "validation_step_s": 1, "refined_validation_step_s": 0.5,
                "los_planning_step_m": 7.5, "los_validation": "exact DEM supercover", "extra_design_margin_db": 1.0,
                "q3_initial_sites": [pair[0]["id"], pair[1]["id"]],
                "continuous_certificate": "swept DEM triangles plus analytic distance bounds",
                "q2_local_search_rounds": 2, "q2_neighbour_limit": 24,
                "geometry_checks": model_check_results["geometry"],
                "python": platform.python_version(), "numpy": numpy.__version__, "scipy": scipy.__version__,
                "openpyxl": openpyxl.__version__, "tifffile": tifffile.__version__,
                "sha256": source_hashes()}
    (ROOT / "results" / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(q1, q2_metrics, q2c_metrics, q3_metrics, q4)
    plot_results.main()
    print(json.dumps({"q1": q1["metrics"], "q2": q2_metrics, "q2_economy": q2c_metrics,
                      "q3": q3_metrics, "q4": {k: {"shortage": q4["partitions"][k]["shortage_total"],
                                                   "imbalance": q4["partitions"][k]["workload_imbalance"]} for k in (2, 3)}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
