# D 题四问代码、模型与结果

从项目上级目录运行：

```powershell
D:\anaconda\python.exe D-\code\run_all.py
```

程序读取 `D-/数据/` 的五份 Excel 和 30 米 GeoTIFF，通常需要数分钟；运行依赖 Python 3.13、numpy、scipy、openpyxl、tifffile、matplotlib。无需网络。

| 文件 | 用途 |
| --- | --- |
| `code/common.py` | 输入、DEM 几何、运输能量和时间 |
| `code/problem1.py` | 单点安全载荷、组批动态规划 |
| `code/problem2.py` | B/C 两种批次模板、多点路线与资源排程 |
| `code/problem3.py` | 重新组批候选、双向通信链路、中继联合排程 |
| `code/problem4.py` | 运输与中继固定任务图、严格分区枚举 |
| `code/run_all.py` | 一键求解、两级通信核验、报告和图表生成 |
| `code/plot_results.py` | 从结果 JSON 生成五张论文用 PDF 图 |
| `reports/ANALYSIS_MODELING_REPORT.md` | 四问数学模型、目标函数、约束和实际算法 |
| `reports/RESULTS_REPORT.md` | 数值、权衡、验证结果和边界 |
| `reports/FOUR_PROBLEM_DETAILS.md` | 运输、中继和分区明细 |
| `results/q1_reproduced/` 至 `results/q4/` | 可机器读取的各问方案、候选对照及逐点记录 |
| `figures/*.pdf` | 论文可引用的数据图 |
| `results/run_manifest.json` | 输入与代码哈希、依赖版本、核验参数 |

Q1 逐区动态规划为所述模型的精确解，并与已有 Q1 结果交叉核对。Q2 与 Q3 是有限候选中的可行启发式方案，候选间按明确的字典序准则比较。Q3 同时输出 1 s 和 0.5 s 通信采样核验；这不构成连续时间的形式证明。Q4 不复制中继任务，严格保持 Q3 已确定的运输路线、任务时间与通信保障关系；同型实体资源可在组内重新编号。
