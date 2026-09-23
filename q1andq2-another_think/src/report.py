"""从落盘结果生成中文论文材料，避免手工数字与代码结果脱节。"""
import json
import platform
import sys
from datetime import datetime
import pandas as pd
import markdown
from core import ROOT,RESULTS,Data,dump

def table(df,digits=3):return df.to_markdown(index=False,floatfmt=f'.{digits}f')
def load(p):return json.loads((RESULTS/p).read_text(encoding='utf-8'))

def run(data):
    q1=load('q1/summary.json');q2=load('q2/selected/summary.json');audit=load('validation/report.json')
    payload=pd.read_csv(RESULTS/'q1/safe_payload_sensitivity.csv');payload=payload[payload.reserve==.2].pivot(index='site',columns='model',values='safe_payload_kg').reset_index()
    sen=pd.read_csv(RESULTS/'q1/reserve_sensitivity.csv')[['reserve','feasible','sorties','energy_kwh','total_operation_s']]
    comp=pd.read_csv(RESULTS/'q2/experiment_comparison.csv')
    if (RESULTS/'q2/lns_comparison.csv').exists():comp=pd.concat([comp,pd.read_csv(RESULTS/'q2/lns_comparison.csv')],ignore_index=True)
    cols=['name','status','sorties','multi_stop_sorties','makespan_s','energy_kwh','weighted_mean_delivery_s','late_boxes']
    q1comp=pd.read_csv(RESULTS/'q1/objective_comparison.csv').iloc[:3][['objective','sorties','energy_kwh','total_operation_s']]
    sorties=pd.read_csv(RESULTS/'q2/selected/sorties.csv')
    q1b=pd.read_csv(RESULTS/'q1/batches.csv')
    direct=comp[comp.name=='direct_optimized'].iloc[0]
    gain_e=(direct.energy_kwh-q2['energy_kwh'])/direct.energy_kwh*100
    gain_t=(direct.makespan_s-q2['makespan_s'])/direct.makespan_s*100
    proof=pd.read_csv(RESULTS/'validation/q1_milp_crosscheck.csv')
    text=f'''# 山区洪涝灾害无人机运输优化研究材料

本材料完成题目第一、二问的数据处理、数学建模、可运行求解、实验对比及独立验证。原题和附件为计算依据，L 老师参考思路只用于理解问题结构。结果来自本地真实运行，未用示意图替代实验图。第三、四问尚未求解，提交模板相应部分保留空白；第二问方案不具有已经验证的通信保障。

默认 20% 返航安全余量下，第一问按架次数、能耗、累计作业时间的字典序求得 **{q1['sorties']} 架次、{q1['energy_kwh']:.6f} kWh、累计作业 {q1['total_operation_s']/3600:.6f} 小时**。第二问最终选择 `{q2['name']}`，共 **{q2['sorties']} 架次，其中 {q2['multi_stop_sorties']} 个多点架次；最晚返回 {q2['makespan_s']:.3f} 秒，即 {q2['makespan_s']/60:.3f} 分钟；能耗 {q2['energy_kwh']:.6f} kWh**。80 个货箱全部且仅交付一次，硬时限违约 {q2['hard_violations']} 箱，期望时间逾期 {q2['late_boxes']} 箱。第二问是验证可行的改进方案，不宣称全局最优。

## 1 数据来源与审计

场景包括 1 个调度中心、15 个服务区、80 个不可拆货箱，合计 {audit['inputs']['mass']} kg、{audit['inputs']['volume']:.3f} m³。31 箱带医疗或首批硬时限。运输机库存为 A 型 4 架、B 型 2 架、C 型 2 架，共享电池库存为 6、4、4 组，包含机上初始电池。按逐箱清单计算，另与需求汇总表核对数量。全部原始文件的 SHA256 位于 `results/data_audit/input_sha256.json`。

读取 MAT 版本 DEM，矩阵尺寸为 1309×1486，经纬度坐标系 EPSG:4326。经度按列递增、纬度按行递减；使用附件仿射变换定位像元，不把经纬度误当成米。全 DEM 无 NoData。节点作业高度采用节点表给定海拔，沿途地面最高高程采用 DEM。两种高程的差异完整保存在 `node_elevations.csv`，不擅自用 DEM 值覆盖题设节点海拔。

压缩包原文件名使用 GBK，解压时恢复中文，并检查路径没有越出数据目录。GeoTIFF 和 MAT 在附件说明中定义为一致数据，本次计算使用 MAT；道路与水体保留作地理背景，不作为无人机航线限制。

![地形与运输路线](../figures/01_terrain_routes.png)

图 1 同一 DEM 下第一问直接往返及第二问路线。服务区编号与附件保持 S001—S015。图中多条路线可能重合，详细访问顺序以逐架次表为准。

## 2 统一物理口径与显式假设

### 2.1 航段几何

对任意两节点，水平路线按经纬度栅格上的两点直线确定。使用 WGS84 椭球测地距离作为航段长度；在本区域的短航段上，此约定避免经纬度直接欧氏距离产生的尺度错误。沿线逐条计算栅格边界交点，把航段切成位于单一像元内的小段，访问每个穿越像元，取最高高程再加 50 m。正式计算不是每隔 30 m 取一个点，因后者可能漏掉短暂经过的高峰像元。

`H_ij = max(沿线 DEM 像元高程) + 50`

`z_O01 = h_O01；z_Si = h_Si + 30；h_up = H_ij - z_i；h_down = H_ij - z_j`

`t_gij = h_up/v_up + d_ij/v_cruise + h_down/v_down`

每次投送后都从服务区作业高度重新爬升，不能把整条多点路径看作只爬升一次。240 条有向航段均已预计算；另外用约 1 m 密集采样核对 120 条无向航段，差异见 `validation/dem_dense_crosscheck.csv`。边界遍历与密集采样不一致时，应保留前者的最高值，而非降低巡航高度。

![地形剖面](../figures/10_dem_flight_profiles.png)

图 2 两个典型航段的 DEM 剖面与计划飞行高度。途中山脊决定爬升量，端点之间的海拔差不能代替沿途净空约束。

### 2.2 载荷相关能耗

`L_g(q) = L0_g - (L0_g - LF_g)(q/Q_g)^(3/2)`

`E_hor = E_use × d_ij / L_g(q)`

`E_up = (m_empty + q) × 9.81 × h_up / (eta_up × 3.6×10^6)`

`E_route = sum(E_hor + E_up) <= (1-rho) E_use`

水平能耗按可用电池能量除以对应载荷标准航程标定；爬升能耗采用机械势能除以爬升效率，J 转 kWh 除以 3.6×10^6。原题给出了水平与爬升能耗之和，但未展开这两个分项的计算式，因此以上标定和势能换算属于本文明确写出的建模解释。重力加速度取 9.81 m/s²。空载总质量已含电池，不能再次加电池质量。返程载荷为零；多点路线在每个投送点卸货后更新剩余质量。

按原题下降能耗效率为 0，不另计下降附加能耗。不新增运输机交接悬停功率，因为附件未提供该功率，题目运输能耗预算按航段总和定义。准备、装载、交接仍必须计入作业时间。若后续获得悬停功率，应作为另一个物理场景重新求解，不能直接混入当前结果。

### 2.3 时间与资源

架次开始定义为开始固定准备和装载，而非离地。`D_p = 固定准备 + 每箱装载×箱数 + 各航段飞行 + 各服务区基础交接 + 每箱交接×箱数`。同一站点同一架次的货箱均在该站点全部交接结束时记为交付完成，这是保守且明确的口径。最终返回是下降至 O01 地面后的时刻。

题目未给运输机架次之间的额外冷却时间或有限装载工位数，因此只采用题设准备时间，不增设单工位限制。不同电池可并行充电；本模型不添加未给出的充电器数量上限。电池从准备开始即被该架次占用，这是保守约定。

`SOC_return = 1 - E_route/E_use`

`t_charge = T_full × [0.65(0.90-SOC)/0.90 + 0.35]，SOC<0.90`

`t_charge = T_full × 0.35(1-SOC)/0.10，SOC>=0.90`

再次开始准备前要求该电池已经充到 100%。最后一次使用后的充电可以继续，但不计入题目定义的运输任务完成时间。

## 3 第一问模型与算法

### 3.1 最大安全载荷

往返能耗为 `E_g,O01,Si(q)+E_g,Si,O01(0)`。它随载荷单调增加：等效航程随 q 下降，水平能耗上升；爬升项也随 q 增加。因此先检验满载可行性，不可行时在 `[0,Q_g]` 上求能耗安全边界根。如果连空载往返都不可行，报告不可达，不能把 0 kg 解释为可交付能力。

下表为连续质量意义的安全载荷，尚未加入具体货箱体积和不可拆分条件，单位 kg。

{table(payload)}

![最大安全载荷](../figures/02_safe_payload.png)

图 3 A 型在全部站点均达到额定 25 kg；B 型仅 S008 受能量约束降低；C 型在较远服务区出现明显能量约束。额定载重较大的机型不等于在任意地点都能满载往返。

### 3.2 可行模式与状态压缩动态规划

第一问不考虑时限，同服务区同品类、同质量体积的货箱可交换。用各品类剩余箱数构成状态，而非对每个箱号建立重复状态。枚举每种计数向量与三种机型，筛除超重、超体积和不满足返航能量的模式。

对于服务区 i、剩余需求向量 n、可行模式 a，递推：

`F_i(n) = lex_min_a {{ (1,E_a,D_a) + F_i(n-a) }}；F_i(0)=(0,0,0)`

每一步至少覆盖一个当前剩余品类，避免无关模式重复展开。保留最优前驱，再将同类真实箱号依次映射回所选模式。由于不同服务区不能跨区组批，且第一问没有共享资源耦合，各服务区精确解相加即为全问题字典序精确解。精确性相对于上述物理口径及浮点计算容差成立。

程序另使用 SciPy/HiGHS 整数规划独立求解每个服务区的“最少架次”和“固定最少架次后最小能耗”，15 个服务区全部与动态规划一致。证据见 `q1_milp_crosscheck.csv`，不是仅靠求解器打印成功来声明最优。

### 3.3 组批结果

{table(q1b[['sortie','site','model','mass_kg','volume_m3','operation_s','energy_kwh','soc']])}

逐箱编号在 `results/q1/batches.csv` 和提交工作簿中。默认方案使用 B 型 9 架次、C 型 9 架次，不用 A 型；这只反映第一问的目标与无资源约束条件，不能推导第二问无需 A 型。

### 3.4 目标权衡

{table(q1comp)}

![第一问目标比较](../figures/04_q1_objective_tradeoff.png)

图 4 最少架次与最少作业时间方案一致。能耗优先方案多 1 架次，仅节省约 0.097354 kWh，却增加约 1663.962 s 累计作业时间，说明在该实例上选架次数优先有实际依据。程序还执行 5 组加权目标，均回到默认方案；不能据此宣称完整 Pareto 前沿已经穷举。

### 3.5 安全余量敏感性

{table(sen)}

![安全余量敏感性](../figures/03_reserve_sensitivity.png)

图 5 安全余量从 10% 到 20% 不改变字典序最优组批；25%、30%、35% 分别增加到 19、20、25 架次；40% 下无法交付全部货箱。不可行时不提供虚假的零能耗值。质量安全上限连续变化，而货箱不可拆分使组批指标呈阶梯变化。

## 4 第二问联合优化模型

### 4.1 为什么不能固定第一问组批

实验 `fixed_q1` 固定第一问全部 18 个组批，只优化开始时刻，在库存和硬时限约束下求解器给出 INFEASIBLE。该结论只针对这一固定组批，不代表第二问题目不可行。第二问实际已获得完整可行方案，说明有必要把组批、机型选择和调度联动优化。

第一问继承到第二问的内容是基础数据、每段几何、物理能耗公式与可选组批参考。多点任务必须重新按逐段剩余载荷计算；不能把单点最大安全载荷当成多点路径的充分可行条件。

### 4.2 有限候选路线集合

候选路线记录机型、货箱集合、服务区顺序、起飞载荷、总体积、总能耗、各箱相对交付时刻、作业时长、返航 SOC 和充电时长。包含全部可行单箱路线、同站双箱路线、第一问方案，以及 55 轮单点和 55 轮多点随机受限构造，并补充同组批其他机型选择。

本次基础池共 3988 条候选路线，其中 2205 条多点路线；单点池 1783 条。初始生成最多访问 3 个服务区且同一区每架次只访问一次，随机过程种子为 20260923。这是控制规模的搜索限制，不是原题限制。局部改进还补充现有架次两两合并后可行的新列。因此结论不涵盖所有可能路线或四点及以上路线。

### 4.3 集合分割与资源区间

设 `x_p` 表示是否选择路线 p，`s_p` 为开始准备时刻。每个货箱必须恰在一条选中路线里：

`sum_{{p: b in p}} x_p = 1`

若选中路线 p，货箱完成时刻为 `C_b=s_p+delta_pb`。医疗物资要求 `C_b<=期望送达时间`；首批箱要求 `C_b<=首批截止时间`；同时属于两类时取两者最小值。其他货箱采用优先系数加权迟到量。

机型 g 的无人机占用区间为 `[s_p,s_p+D_p)`，电池占用区间为 `[s_p,s_p+D_p+t_charge,p)`。分别添加并发数量不超过对应库存的累计约束。相同机型的资源可互换，求得时间区间后按开始时刻进行区间着色，给出真实无人机编号和电池编号。区间图的最大重叠数等于所需颜色数，因此这种后分配不会降低在同型资源可交换前提下的可行性。

CP-SAT 使用整数秒：相对交付时间、返回时长、电池恢复时长向上取整，截止时间保持附件整数值，开始时刻为整数。一次区间的时间向上偏差小于 1 s；多次复用可能累积，不能宣称全调度误差也小于 1 s。最终导出和验证使用浮点物理时刻，整数模型为保守保障。求解时域为 24000 s，此时域也是搜索限制。

### 4.4 多目标标量化

硬约束始终必须满足。平衡方案优化下式，能量先转 Wh 并取整：

`J = 100 C_max + sum_b w_b C_b + 100 sum_b w_b max(0,C_b-d_b) + 10 sum_p E_p,Wh x_p + 10000 sum_p x_p`

该式是明确给定权重的多目标标量化，不是严格的“先零迟到、再完工时间”字典序。权重体现本实验偏好，不能当作现实货币成本。增加加权交付时间，是为了在全部按时送达时继续区分更早到达的方案。能量取整只用于目标函数，不用于能耗可行性判断。

对照偏好系数（顺序为完工时间、加权交付、加权迟到、Wh、架次）：平衡 `(100,1,100,10,10000)`；节时 `(400,2,100,2,2000)`；节能 `(30,1,100,45,10000)`；少架次 `(40,1,100,5,150000)`。不同权重下的目标值不可直接互比，应比较物理指标。

### 4.5 地理邻域破坏修复

大候选池在短时间内存在搜索困难。改进法从可行基线出发，每轮选择一个服务区作为中心，破坏 5—8 个地理邻近且带随机扰动的架次；从基础池筛出只服务这些货箱的路线，加入保留架次和两两合并候选，再用小规模 CP-SAT 子问题共同重排所有时间。仅接受平衡目标严格改善的方案，始终保留完整可行解。

单点限制与允许多点分别执行相同迭代数、同样单轮时间上限和相同随机种子，用于消融比较。该方法可称为“地形与共享电池约束下的地理邻域 matheuristic”，即数学规划辅助启发式；它是适用于本题的组合设计，未经过系统文献查新，不宣称算法学术首创。

## 5 第二问实验结果

{table(comp[cols])}

表中的空值表示该次实验无可行输出；固定第一问方案确认为不可行，不纳入性能排名。CP-SAT 每个大池场景设置 60 s，8 个搜索线程；实际墙钟时间包含停止和求解器开销，可能略超上限。不同种子使用 23、41、97；多线程调度和墙钟时间限制可能导致重新运行得到另一组同样可行的解，固定种子不代表逐字节确定性。

相对 `direct_optimized` 基线，最终方案能耗变化对应节省 {gain_e:.2f}%，最晚返回时间节省 {gain_t:.2f}%。这是当前实例和当前计算预算下的实测比较，不是所有实例上的普遍结论。更公平的邻域算法单点/多点对照见 `lns_comparison.csv`；大池求解及邻域算法不能只按目标值比较而忽略计算预算。

![实验指标权衡](../figures/08_q2_tradeoff.png)

![局部改进收敛](../figures/09_lns_convergence.png)

图 6—7 分别展示物理指标权衡与相同预算下的邻域改进过程。未改善的实验如实保留。只有找到更低目标值才能证明当前基线被改善；不能把未找到改进解释为已经最优。

### 5.1 最终架次安排

{table(sorties[['sortie','drone','model','battery','start_s','route','return_s','energy_kwh']])}

![无人机甘特图](../figures/05_drone_gantt.png)

图 8 灰色为准备和装载，彩色为飞行及交接。最晚返回是所有无人机最后一架次返回时刻的最大值，不是累计作业时间。

### 5.2 电池周转与配送及时性

![电池甘特图](../figures/06_battery_gantt.png)

![交付与时限](../figures/07_delivery_timeliness.png)

图 9 电池斜线区表示充电至 100% 的时间，下一次使用不会与其重叠。图 10 核对实际交付、期望时间和硬截止。最终方案最低返航 SOC 为 {q2['min_return_soc']*100:.3f}%，最小硬截止剩余裕度 {q2['min_hard_slack_s']:.3f} s。最小裕度是名义模型下的缓冲，不是对风雨扰动的概率可靠性保证。

逐箱交付 80 行见 `results/q2/selected/deliveries.csv`，电池占用与充电见 `batteries.csv`，每段实际载荷和能耗见 `legs.csv`。所有结果以完整精度保存，报告仅为显示作了小数位格式化。

## 6 独立验证与可复现性

验证程序从箱号清单、机型参数和航段几何重新计算质量、体积、逐段载荷、能量、交付和返回时刻。它不调用优化器路线评估函数取得真值，因此可捕捉部分实现错误，但共享了原始数据加载与航段几何；几何另用密集采样交叉验证。

- 80 箱无遗漏、无重复，服务区与编号一致。
- 第一问 15 个服务区的最少架次与最小能耗由第二种算法交叉验证。
- 第二问所有医疗与首批硬时限满足；所有路线返航能量满足。
- 每个具体无人机的任务区间无重叠；每块具体电池使用加充电区间无重叠。
- 电池初始为满电，复用前充满；返航 SOC 逐次复算。
- 5 项单元测试覆盖充电分段边界、安全载荷边界、反向航段几何、逐点卸载及体积约束。

完整检查状态：

```json
{json.dumps(audit,ensure_ascii=False,indent=2)}
```

代码目录 `src`，测试目录 `tests`，锁定依赖 `requirements-lock.txt`，优化迭代日志 `logs` 及各实验目录。运行方式见 README。主要输出均可由代码重新生成。

## 7 对参考思路的取舍

参考 PDF 第 3—5 页提出先算安全载荷再组批，以及第 7—10 页对异构资源与电池调度的总体分解，这些结构保留。参考材料没有提供本实例经过运行验证的数值结果，不把其中的一般公式当成实验结论。

本实现补足并纠正容易误用的部分：显式写出两种能耗分项及单位换算；把下降过程计入时间；区分单点安全载荷与多点逐段能量；区分医疗和首批硬时限与其他期望时限；不固定第一问组批；把充电时间放入电池占用区间；保留每个箱号和每块电池的可追溯明细。第一问采用可证明的状态压缩精确解，第二问采用候选路线与局部数学规划改进，没有笼统声称套用一种智能算法即可达到最优。

## 8 适用条件与后续问题接口

目前未引入风场、降雨导致的功耗变化、装载工位瓶颈、货箱几何装箱、禁飞区和载荷外形限制；这些数据未由题目给定。装载只按题设总质量和总体积约束。DEM 为数字表面模型，空间分辨率限制仍然存在，不是连续真实地形的绝对保证。

第二问没有通信约束，不能直接作为第三问答案。第三问需对爬升、巡航、下降和交接全过程进行双向链路检查，并共同优化中继位置、高度、建链时间、服务时间与能源组件。第四问必须以第三问已验证的完整联合方案为基础，冻结其组批和通信关系后再分区，不能从当前第二问方案直接跳到最终资源配置答案。

本项目保留每个航段的时刻、作业高度、巡航高度与逐箱卸载信息，为第三问按时间重建三维轨迹提供接口。未解出的题目不会用概念方案或空表冒充完成。

## 9 论文组织建议与来源

可按“数据与统一物理模型—单点能力与精确组批—双资源联合调度—算法对照与敏感性—验证与局限”组织第一、二问论文正文。结果表、图片和数字均以 `results` 为准；图提供 240 dpi PNG 和 SVG 两种格式，便于论文排版。

原始来源：用户提供的《D-山区洪涝灾害下无人机运输与通信协同优化.docx》及 D题.zip 内 5 张基础数据表、DEM 和提交模板。参考来源为用户提供的《2026研赛D题思路_L老师.pdf》第 3—5、7—10 页。

工具方法来源：[Google OR-Tools 调度建模文档](https://github.com/google/or-tools/blob/stable/ortools/sat/docs/scheduling.md)说明可选区间与累计资源约束的建模用法；[SciPy milp 官方文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html)说明混合整数线性规划接口、状态和最优间隙。软件版本以本项目锁定依赖为准，而非网页当前版本。本文算法组合与结果解释由本项目针对附件实例实现。
'''
    out=ROOT/'docs/paper_materials.md';out.write_text(text,encoding='utf-8')
    html=markdown.markdown(text,extensions=['tables','fenced_code','toc'])
    style='body{font:16px/1.85 "Microsoft YaHei",sans-serif;max-width:1100px;margin:45px auto;padding:0 24px;color:#22313c}h1,h2,h3{line-height:1.4;color:#19364a}h2{margin-top:48px}img{max-width:100%;height:auto}table{border-collapse:collapse;font-size:12px;display:block;overflow-x:auto}th,td{border:1px solid #cdd6de;padding:7px 9px;text-align:right}th{background:#eaf0f4}pre{background:#f2f5f7;padding:18px;overflow:auto}code{font-family:Consolas,monospace}a{color:#226797}@media print{body{font-size:11pt}h2{break-after:avoid}img,table{break-inside:avoid}}'
    (ROOT/'docs/paper_materials.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>无人机运输优化研究材料</title><style>'+style+'</style><body>'+html+'</body></html>',encoding='utf-8')
    print('Report written',out,flush=True)

if __name__=='__main__':run(Data())
