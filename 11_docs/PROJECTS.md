# TP 小项目地图

最后更新：2026-07-07

本文档记录当前目录结构下每个小项目的角色、文档入口、数据依赖和处置状态，也承接原 `00_项目主线索引/` 的编号主线视图。具体运行细节仍放在项目自己的 `README.md` 或 `11_docs/README.md` 中。


## 当前达成审计（2026-06-30）

| 诉求 | 当前状态 | 证据或剩余动作 |
| --- | --- | --- |
| 统一 `screen_aggregate` / `returns` 数据源 | 已达成 | 活跃代码不再引用旧 `.pkl` 或旧 `00_screen/monthly`、`00_screen/returns`、`00_screen/ciq` 生产入口；canonical 路径集中在 `00_screen/` 与 `tp_core.data_sources`。 |
| 月更入口切到 `production_inputs/incoming/YYYYMM/` | 已达成 | `00_screen/monthly_update.py --dry-run --input-month 202606` 通过；QA 报告 `qa_passed=True`。 |
| CIQ 合并进入月更且记录内容更新 | 已达成 | CIQ 按 `(ISIN, Date)` 只填空值，不覆盖非空值；202606 dry-run 匹配 3199 行、填充 251439 个单元格，行列数稳定。 |
| 备份目录收敛 | 已达成 | 当前活跃 screen 备份目录为 `00_screen/backups/`，未发现活跃 `bk` / `backup_screen`。 |
| EM Cluster 清理 | 已达成 | 活跃目录扫描未发现 EM Cluster 生产引用；数据契约将旧 EM cluster 列标为 deprecated。 |
| 编号目录和主线地图 | 已达成 | 根目录主线为 `00_` 到 `12_`，旧项目进入 `99_archive/` 或 `99_*_legacy/`。 |
| 回测只保留传统代码主线 | 已达成 | `07_backtest_code/` 为当前主线；Web/GUI legacy 保留历史参考。2026-06-30 已完成 default profile 真实全量回测，验收报告见 `10_pipeline_runs/manifests/run_backtest/full_backtest_validation_latest.json`。 |
| 统一信号表、候选池、组合产物 | 已达成第一版 | `04_signals/*.parquet`、`05_candidates/latest_candidates.parquet`、`06_portfolios/latest_target_weights.parquet` 已由 `02_pipelines.run_all --skip-refresh-data --skip-backtest` 生成。 |
| 测试输出不污染根目录 | 已补齐 | `test_output/` 和 `06_optimiser/test_output/` 已归档到 `99_archive/test_outputs_20260630/`；pytest 优化器测试改用临时目录。 |
| returns 极端收益治理 | 部分达成 | `tp-returns-audit` 已固定输出 `00_screen/qa/returns_anomaly_governance/` 下的摘要、完整异常明细和人工复核模板；尚未自动清洗或建立人工确认后的修正/白名单文件。 |
| notebook 合并和执行验收 | 部分达成 | `monthly_prod`、技术分析 3 个 notebook、公司分析模板、`Monitoring.ipynb` 已逐 cell 执行通过；`Pipeline.ipynb` 用 `tp-prod` kernel 跑满 2 小时后超时，已记录失败 manifest，需拆成区域/阶段 CLI 后再作为生产验收。 |
| `tp_core` 共享包抽取 | 部分达成 | 已新增展示层纯函数、Markdown formatter、回测兼容入口；优化器已切到 download_09 标准 `06_optimiser/optimizer_engine.py`。ML 训练/预测入口和展示应用仍需继续收敛。 |
| 展示/报告层合并 | 已达成 | `08_presentation_layer` 已成为统一 app/report 入口；Dash 公司展示、公司分析 FastAPI、组合 dashboard/PDF 的实现已迁入 `08_presentation_layer/legacy_apps/`，根目录不再保留三套并行展示项目。 |

## 编号主线视图

| 序号 | 主责目录 | 代表步骤 | 处置 |
| --- | --- | --- | --- |
| 00 | `00_screen/` | 可信数据生产 | 保留 |
| 01 | `01_tp_core/` | 共享规则、契约和算法入口 | 保留 |
| 02 | `02_pipelines/` | 单环和总流水线编排 | 保留 |
| 03 | `03_ml_enhanced/`、`03_regime_model/`、`03_technical_analysis/` | 产生标准化信号 | 保留，继续生产化 |
| 04 | `04_signals/`、`05_candidates/` | 信号和候选池标准产物 | 保留 |
| 05 | `06_optimiser/`、`06_portfolios/` | 组合优化和目标权重 | 保留 |
| 06 | `07_backtest_code/` | 唯一回测主线 | 保留 |
| 07 | `08_presentation_layer/`、apps、`09_reports/` | 展示、分析和报告 | 合并为展示/报告层 |
| 08 | `11_docs/`、`10_pipeline_runs/` | 文档和运行证据 | 保留 |
| 12 | `99_archive/project_cleanup_20260707/12_small_cap/` | 小盘研究片段 | 已归档 |
| 13 | `13_sector_score_model/` | 行业打分模型、Excel 方法论复刻和行业长期回测 | 活跃研究 |
| 14 | `14_country_model/` | 国家/地区打分模型和 country signal | 活跃研究 |
| 99 | `99_archive/`、`_quarantine_20260629/` | 旧项目和旧实验 | 只作历史参考 |

## 兼容层处置

根目录无编号兼容文件夹已经归档到 `99_archive/compat_wrappers_20260629/`，主线不再保留无编号项目文件夹。原 `00_项目主线索引/` 已并入本文档，历史目录保存在 `99_archive/project_cleanup_20260707/00_项目主线索引/`。

| 旧兼容入口 | 当前主线入口 | 说明 |
| --- | --- | --- |
| `screen/` | `00_screen/` | 月更直接运行 `python 00_screen/monthly_update.py` 或 pipeline |
| `tp_core/` | `01_tp_core/` | 运行命令使用 `python -m 01_tp_core...`；代码中的逻辑包 `tp_core` 由 `01_tp_core/tp_core/` 提供 |
| `pipelines/` | `02_pipelines/` | 运行命令使用 `python -m 02_pipelines...` |
| `backtest_code/` | `07_backtest_code/` | 运行 `python 07_backtest_code/run_backtest.py ...` |
| `optimiser/` | `06_optimiser/` | 代码中的逻辑包 `optimiser` 由 `06_optimiser/optimiser/` 提供 |
| `ML_Enhanced/` | `03_ml_enhanced/` | 运行 `python -m 03_ml_enhanced.cli export-signals` |
| `regime_model/` | `03_regime_model/` | 运行 `python -m 03_regime_model.export_risk_budget` |
| `technical_analysis_v2/` | `03_technical_analysis/` | 运行 `python -m 03_technical_analysis.export_technical_signals` |
| `presentation_layer/` | `08_presentation_layer/` | 代码中的逻辑包 `presentation_layer` 由 `08_presentation_layer/presentation_layer/` 提供 |

新代码不得再新增根目录无编号 wrapper；新增入口应放在对应编号目录、`02_pipelines/` 或 `08_presentation_layer/`。

## 生产核心

| 项目 | 角色 | 文档入口 | 数据依赖 | 状态 |
| --- | --- | --- | --- | --- |
| `00_screen/` | Screen 月度主表、returns、CIQ 补字段、QA 与备份 | [`../00_screen/README.md`](../00_screen/README.md) | canonical 数据源本身 | 生产核心 |
| `01_tp_core/` | 共享数据路径、读取函数、数据契约、returns 审计、生产输入整理、共享回测工具 | [`../01_tp_core/README.md`](../01_tp_core/README.md) | `00_screen/` canonical parquet | 共享基础包 |
| `02_pipelines/` | 主流水线薄编排：数据刷新、信号、候选池、组合、回测、报告 | [`../02_pipelines/README.md`](../02_pipelines/README.md) | canonical 数据和各标准产物 | 编排主线 |
| `11_docs/` | 全工作区文档中枢 | [`README.md`](README.md) | 不直接读数据 | 文档入口 |
| `04_signals/` | 统一信号表输出目录 | [`../04_signals/README.md`](../04_signals/README.md) | ML/技术/Regime 导出信号 | 信号底座 |
| `05_candidates/` | 标准候选池输出目录 | [`../05_candidates/README.md`](../05_candidates/README.md) | `04_signals/`、`last_screen` | 候选池标准产物 |
| `06_portfolios/` | 标准目标权重输出目录 | [`../06_portfolios/README.md`](../06_portfolios/README.md) | `05_candidates/` | 组合标准产物 |
| `09_reports/` | 稳定命名报告产物 | [`../09_reports/README.md`](../09_reports/README.md) | pipeline manifest 和标准产物 | 报告输出 |
| `10_pipeline_runs/` | 流水线运行 manifest | [`../10_pipeline_runs/README.md`](../10_pipeline_runs/README.md) | 每个 pipeline 步骤 | 机器可读审计证据 |
| `08_presentation_layer/` | 展示/报告层统一入口：数据 repository、app factory、report wrapper、CLI，以及公司展示/公司分析/组合 dashboard 内部实现 | [`../08_presentation_layer/README.md`](../08_presentation_layer/README.md) | canonical screen/returns/signals | 展示/报告主线 |

## 活跃研究与应用

| 项目 | 角色 | 文档入口 | 数据依赖 | 状态 |
| --- | --- | --- | --- | --- |
| `07_backtest_code/` | 传统代码版回测主线：PtfBuilder、YAML 配置、批量运行、产物保存；通用权重表核心见 `tp_core.general_backtest` | [`../07_backtest_code/README.md`](../07_backtest_code/README.md)、[`BACKTEST_ENGINE.md`](BACKTEST_ENGINE.md) | canonical screen/returns | 活跃主线 |
| `99_archive/project_cleanup_20260707/99_backtest_web_app_legacy/` | 原 Streamlit/FastAPI 回测平台 | [`../99_archive/project_cleanup_20260707/99_backtest_web_app_legacy/README.md`](../99_archive/project_cleanup_20260707/99_backtest_web_app_legacy/README.md) | 已归档；当前主线为 `07_backtest_code/` |
| `03_regime_model/` | US/EU bottom-up regime 识别和风险仪表盘 | [`../03_regime_model/README.md`](../03_regime_model/README.md) | canonical screen/returns | 活跃研究 |
| `08_presentation_layer/legacy_apps/web_app_des_companies/` | Dash 公司与指数成分展示应用实现目录 | [`../08_presentation_layer/legacy_apps/web_app_des_companies/README.md`](../08_presentation_layer/legacy_apps/web_app_des_companies/README.md) | 通过 `presentation_layer` 读取 canonical screen | 已并入展示/报告层 |
| `08_presentation_layer/legacy_apps/company_analysis/` | 公司分析后端、前端和估值模板实现目录 | [`../08_presentation_layer/legacy_apps/company_analysis/README.md`](../08_presentation_layer/legacy_apps/company_analysis/README.md) | 通过 `presentation_layer` 读取 last_screen/screen/returns | 已并入展示/报告层；外部参考模板库已归档 |
| `08_presentation_layer/legacy_apps/dashboard_analysis/` | 组合/指数分析和 PDF 报告实现目录 | [`../08_presentation_layer/legacy_apps/dashboard_analysis/README.md`](../08_presentation_layer/legacy_apps/dashboard_analysis/README.md) | 通过 `presentation_layer` 读取 screen/returns | 已并入展示/报告层 |
| `03_ml_enhanced/` | 新版 ML 训练、预测、监控和组合输出 | [`../03_ml_enhanced/README.md`](../03_ml_enhanced/README.md) | canonical screen/returns，输出 `04_signals/ml_signals.parquet` | 主要 ML 版本；已固定 CLI 信号导出、覆盖检查和显式 Score ML 生产入口 |
| `03_technical_analysis/` | 技术指标和形态信号生产 | [`../03_technical_analysis/README.md`](../03_technical_analysis/README.md) | canonical screen/returns，输出 `patterns.parquet` 和 `04_signals/technical_signals.parquet` | 活跃技术信号；不再自带主回测核心 |
| `13_sector_score_model/` | 美股行业打分模型：沉淀 `Score_Sectoriel_US.xlsm` 方法论，并用 canonical screen/returns 做 Python 版行业评分、金融业特殊处理和长期行业回测 | [`../13_sector_score_model/README.md`](../13_sector_score_model/README.md) | canonical screen/returns、ICB mapping | 活跃研究 |

## 辅助或遗留项目

| 项目 | 角色 | 文档入口 | 状态 |
| --- | --- | --- | --- |
| `99_archive/frozen_20260629/backtest/` | 早期回测引擎和 notebook | [`../99_archive/frozen_20260629/README.md`](../99_archive/frozen_20260629/README.md) | 已冻结；当前主线为 `07_backtest_code/` |
| `99_archive/frozen_20260629/ML/` | ML 上一版 | [`../99_archive/frozen_20260629/README.md`](../99_archive/frozen_20260629/README.md) | 已冻结 |
| `99_archive/frozen_20260629/ML第一版/` | 第一代 ML 目录 | [`../99_archive/frozen_20260629/README.md`](../99_archive/frozen_20260629/README.md) | 已冻结 |
| `99_archive/frozen_20260629/factsetProd第一版/` | 旧 FactSet/Excel 生产链路 | [`../99_archive/frozen_20260629/README.md`](../99_archive/frozen_20260629/README.md) | 已冻结 |
| `99_archive/frozen_20260629/回测第一版/` | 第一代回测目录 | [`../99_archive/frozen_20260629/README.md`](../99_archive/frozen_20260629/README.md) | 已冻结 |
| `06_optimiser/` | Python 组合优化器主线 | [`../06_optimiser/README.md`](../06_optimiser/README.md) | 候选池、signals、旧组合、约束 | 活跃主线 |
| `99_archive/project_cleanup_20260707/99_backtest_gui_legacy/` | 原 PySide6 桌面回测入口 | [`../99_archive/project_cleanup_20260707/99_backtest_gui_legacy/README.md`](../99_archive/project_cleanup_20260707/99_backtest_gui_legacy/README.md) | 已归档；当前主线为 `07_backtest_code/` |
| `99_archive/project_cleanup_20260707/99_optimiseur_legacy/` | 旧 notebook/xlsm 优化器说明 | [`../99_archive/project_cleanup_20260707/99_optimiseur_legacy/README.md`](../99_archive/project_cleanup_20260707/99_optimiseur_legacy/README.md) | 已归档；当前主线为 `06_optimiser/` |
| `99_archive/project_cleanup_20260707/12_small_cap/` | 小盘研究片段 | [`../99_archive/project_cleanup_20260707/12_small_cap/README.md`](../99_archive/project_cleanup_20260707/12_small_cap/README.md) | 已归档；历史字段快照不是 canonical 字典 |
| `99_archive/frozen_20260629/cyc/` | 早期周期研究片段 | [`../99_archive/frozen_20260629/README.md`](../99_archive/frozen_20260629/README.md) | 已冻结；有价值逻辑后续并入 `03_regime_model/` |
| `99_archive/frozen_20260629/技术分析和深度学习__深度学习/` | 旧深度学习 pipeline | [`../99_archive/frozen_20260629/README.md`](../99_archive/frozen_20260629/README.md) | 已冻结；职责并入 `03_ml_enhanced/` |
| `99_archive/notebook_cleanup_20260629/` | 根目录旧测试 notebook 和临时产物 | [`../99_archive/notebook_cleanup_20260629/manifest.json`](../99_archive/notebook_cleanup_20260629/manifest.json) | 已归档，不作为生产入口 |

## Notebook 处置状态

| Notebook | 当前状态 | 说明 |
| --- | --- | --- |
| `00_screen/monthly_prod.ipynb` | 保留 | screen 月更人工面板；底层调用 `monthly_update.py` |
| `03_ml_enhanced/Pipeline.ipynb` | 保留 | 当前 ML 训练/预测主 notebook；生产 Score ML 已有 CLI，研究训练流程后续再拆 |
| `03_ml_enhanced/Monitoring.ipynb` | 保留 | 已由 `Monitoring - NEW.ipynb` 合并替换，作为当前监控 notebook；CLI 已覆盖轻量 inspect |
| `03_technical_analysis/Tradin_patterns.ipynb` | 保留 | 技术形态生产和说明入口 |
| `03_technical_analysis/Pattern_backtest.ipynb` | 保留 | 技术形态信号回测研究入口 |
| `03_technical_analysis/Pattern_visual_guide.ipynb` | 保留 | 技术形态可视化说明 |
| `08_presentation_layer/legacy_apps/company_analysis/日常分析模板.ipynb` | 保留 | 公司分析日常模板；最新截面读取已接入 `PresentationDataRepository` |
| 根目录 `test*.ipynb` 和 `test.parquet` | 已归档 | 移入 `99_archive/notebook_cleanup_20260629/root_experiments/` |
| `99_archive/frozen_20260629/backtest/backtest_test.ipynb` | 已冻结 | 随早期 `backtest/` 移入 `99_archive/frozen_20260629/backtest/` |
| `99_archive/frozen_20260629/cyc/main.ipynb` | 已冻结 | 移入 `99_archive/frozen_20260629/cyc/`，有价值逻辑后续并入 `03_regime_model` |
| `技术分析和深度学习/深度学习/Main_pipeline_europe.ipynb` | 已冻结 | 移入 `99_archive/frozen_20260629/技术分析和深度学习__深度学习/` |
| `03_ml_enhanced/参考文件_EM/pipeline_em.ipynb` | 已隔离 | 移入 `03_ml_enhanced/_quarantine_20260629/em_reference_legacy/` |
| `03_ml_enhanced` 旧 ptf 版 `Monitoring.ipynb` | 已隔离 | 移入 `03_ml_enhanced/_quarantine_20260629/legacy_notebooks/Monitoring_old_ptf_based.ipynb` |

## 下一步整理建议

1. `backtest_wep_app` 根目录旧 `.pkl` 数据副本、Web/API/Streamlit/Docker 入口和重复回测核心已随 `99_backtest_web_app_legacy/` 归档到 `99_archive/project_cleanup_20260707/`，主线改为 `07_backtest_code/`。
2. `03_ml_enhanced` 的旧 `test_bench.ipynb`、旧 ptf 版 `Monitoring.ipynb` 和 EM 参考 notebook 已隔离；当前保留 `Pipeline.ipynb`、标准 `Monitoring.ipynb` 和 `export_signals.py`。
3. `02_pipelines/` 已建立第一版单环和总入口；后续继续把 ML 训练/预测、复杂优化约束和报告生成收敛到 `02_pipelines/` 入口。
4. 逐步把英文/法文面向用户的 README 改为中文，代码注释和第三方参考模板可以保持原语言。

5. 已清理根目录旧测试 notebook、早期 `backtest/`、早期 `cyc/` 和旧深度学习 pipeline；回滚证据见 `99_archive/notebook_cleanup_20260629/manifest.json` 与 `99_archive/frozen_20260629/manifest.json`。



