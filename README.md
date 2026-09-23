# D 题四问代码、模型与结果

项目以题目 Word 与配套数据附件为输入。当前正式结果目录为 `results/q1_reproduced/`、`results/q2_improved/`、`results/q3/`、`results/q4/`；问题三只保留一套经验证方案。

从 `D:\mathcom` 运行第三、四问并刷新第三问图表：

```powershell
D:\anaconda\python.exe -B D-\code\run_all.py --width 160 --sample-step 10 --seconds 120 --validate 12
```

`run_all.py` 以已审计的问题一、二结果为上游输入；若只需要第三、四问，直接运行 `code/run_q3_joint.py`，参数相同。程序读取 `D-/数据/` 中的 Excel 和 30 m DEM，依赖 numpy、scipy、openpyxl、tifffile、matplotlib、Pillow，无需网络。

| 文件 | 用途 |
|---|---|
| `code/common.py` | 输入、DEM、运输飞行与充电计算 |
| `code/problem1.py` | 单点安全载荷和组批 |
| `code/problem2.py`、`code/improve_q2_audited.py` | 多点运输与当前问题二改进方案 |
| `code/problem3.py` | 双向链路、中继任务、资源和验证基础函数 |
| `code/run_q3_joint.py` | 第三问搜索、窗口细化、验证和写出 |
| `code/problem4.py`、`code/run_q3_joint.py` | 固定第三问任务的两组/三组枚举 |
| `code/q3_figures.py` | 从当前第三问结果生成论文用 PDF/SVG/PNG 图 |
| `reports/ANALYSIS_MODELING_REPORT.md` | 四问数学模型与算法 |
| `reports/Q3_WORD_MODEL_AND_SEARCH.md` | 第三问公式与题目 Word、参考文献的对应关系 |
| `reports/RESULTS_REPORT.md` | 当前四问结果汇总 |
| `reports/Q3_OPTIMIZATION_RESULTS.md` | 第三问指标、证书及对照分析 |

第三问正式数值为 24 个运输架次、5 个中继架次，加权迟到 8,546.904，联合完工 8,772.339 s，总能耗 73.835382 kWh。80 箱唯一交付，硬约束与资源冲突均为 0；逐秒检查和连续通信区间证书通过。完整排程、逐箱与逐架次明细、逐秒链路记录、证书均在 `results/q3/`。第四问必须读取同一第三问证书中的实际中继保障关系，当前结果在 `results/q4/partitions.json`。
