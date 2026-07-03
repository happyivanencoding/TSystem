# TP 项目主线编号索引

本目录是给人看的主线地图。现在已经完成物理编号改名：真实生产目录以 `00_`、`01_`、`02_` 等前缀排序；根目录无编号兼容文件夹已归档，不再作为主线入口。

## 主线步骤

| 序号 | 真实目录 | 职责 | 当前处置 |
| --- | --- | --- | --- |
| 00 | `00_screen/` | canonical 数据、月更、returns、CIQ、QA | 数据底座 |
| 01 | `01_tp_core/` | 数据路径、契约、IO、共享规则、回测入口 | 共享基础库 |
| 02 | `02_pipelines/` | 数据刷新、信号、候选池、组合、回测、报告编排 | 总入口 |
| 03 | `03_ml_enhanced/`、`03_regime_model/`、`03_technical_analysis/` | 模型和研究模块，输出统一信号表 | 信号生产层 |
| 04 | `04_signals/` | 标准化信号表 | 标准产物 |
| 05 | `05_candidates/` | 标准候选池 | 标准产物 |
| 06 | `06_optimiser/`、`06_portfolios/` | 组合优化逻辑和目标权重产物 | 优化层 |
| 07 | `07_backtest_code/` | 唯一传统代码版回测主线 | 回测层 |
| 08 | `08_presentation_layer/`、`08_web_app_des_companies/`、`08_company_analysis/`、`08_dashboard_analysis/` | 展示、公司分析和报告共享能力 | 展示/报告层 |
| 09 | `09_reports/` | 稳定命名报告产物 | 报告输出 |
| 10 | `10_pipeline_runs/` | 机器可读运行证据和 manifest | 审计证据 |
| 11 | `11_docs/` | 文档中枢 | 治理层 |
| 12 | `12_small_cap/` | 小盘研究片段 | 辅助研究 |
| 13 | `13_sector_score_model/` | 美股行业打分模型、Excel 方法论复刻、行业长期回测 | 活跃研究 |
| 99 | `99_archive/`、`99_*_legacy/`、各 `_quarantine_20260629/` | 冻结项目、旧实验、可回滚隔离区 | 只作历史参考 |

## 兼容层处置

根目录兼容文件夹已经归档到 `99_archive/compat_wrappers_20260629/`，主线不再保留无编号项目文件夹。

| 旧兼容入口 | 当前主线入口 | 说明 |
| --- | --- | --- |
| `screen/` | `00_screen/` | 月更直接运行 `python 00_screen/monthly_update.py` 或 pipeline |
| `tp_core/` | `01_tp_core/` | 运行命令使用 `python -m 01_tp_core...`；代码中的逻辑包 `tp_core` 由 `01_tp_core/tp_core/` 提供 |
| `pipelines/` | `02_pipelines/` | 运行命令使用 `python -m 02_pipelines...` |
| `backtest_code/` | `07_backtest_code/` | 运行 `python 07_backtest_code/run_backtest.py ...` |
| `optimiser/` | `06_optimiser/` | 代码中的逻辑包 `optimiser` 由 `06_optimiser/optimiser/` 提供 |
| `ML_Enhanced/` | `03_ml_enhanced/` | 运行 `python -m 03_ml_enhanced.export_signals` |
| `regime_model/` | `03_regime_model/` | 运行 `python -m 03_regime_model.export_risk_budget` |
| `technical_analysis_v2/` | `03_technical_analysis/` | 运行 `python -m 03_technical_analysis.export_technical_signals` |
| `presentation_layer/` | `08_presentation_layer/` | 代码中的逻辑包 `presentation_layer` 由 `08_presentation_layer/presentation_layer/` 提供 |

新代码不得再新增根目录无编号 wrapper；新增入口应放在对应编号目录或 `02_pipelines/`。
