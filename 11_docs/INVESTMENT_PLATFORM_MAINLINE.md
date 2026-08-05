# TP 已部署架构与项目地图

最后更新：2026-07-26

本文档是 TP 当前架构和项目职责的唯一总览。它合并了原 `PROJECTS.md`、`CORE_LIBRARY.md` 和旧版“项目整合计划”；路线图、迁移过程和历史审计不再作为生产操作依据。

## 权威层级

```text
代码与真实产物 > 数据契约/运行手册 > 项目 README > _context/handoffs > archive
```

- 数据路径以根目录 `DATA_SOURCES.md` 和 `tp_core.data_sources` 为准。
- 数据主键和字段语义以根目录 `DATA_CONTRACT.md` 为准。
- 生产命令、输入、输出和 manifest 以 `PIPELINE_OPERATIONS.md` 为准。
- 旧计划、旧审计和迁移证据只允许出现在 `11_docs/archive/`、`99_archive/` 或 handoff 中。

## 源码架构

所有活跃 Python 实现位于 `src/`，通过正常安装包、公共 API 和 `pyproject.toml` 控制台入口暴露。

| 包 | 职责 |
| --- | --- |
| `tp_core` | 数据路径、IO、契约、信号校验、保留策略和共享协议 |
| `tp_data` | Screen/returns 月更、技术指标和外部数据导入 |
| `tp_models` | ML、Regime、Technical、Sector、Country、Small Cap 和 News 模型 |
| `tp_pipelines` | typed step config、registry/DAG、单环及总流水线编排 |
| `tp_portfolio` | universe、权重、约束、求解器和组合优化公共 API |
| `tp_backtest` | 唯一代码版回测引擎、配置、运行和产物 |
| `tp_experiments` | Run Card、lineage、指标、产物和晋升/否决记录 |
| `tp_research` | 可复现研究 workflow |
| `tp_reporting` | 研究报告和可视化构建 |
| `tp_data.providers` | Provider protocol、StandardModel 和 shadow adapter |
| `presentation_layer` | repository、domain service、API、job controller、view model 和应用入口 |

测试统一位于 `tests/`，工程配置位于 `config/`，标准生成产物位于 `artifacts/`。编号目录不再承载活跃 Python 实现。

## 生产主线

```text
production_inputs
  -> refresh_data
  -> export_signals
  -> build_candidates
  -> optimize_portfolio
  -> run_backtest
  -> generate_report
```

| 环节 | 实现 | 标准产物 |
| --- | --- | --- |
| Canonical 数据 | `tp_data`、`tp_pipelines.refresh_data` | `00_screen/*.parquet`、QA |
| 模型信号 | `tp_models`、`tp_pipelines.export_signals` | `artifacts/signals/` |
| 候选池 | `tp_pipelines.build_candidates` | `artifacts/candidates/` |
| 组合优化 | `tp_portfolio`、`tp_pipelines.optimize_portfolio` | `artifacts/portfolios/` |
| 回测 | `tp_backtest`、`tp_pipelines.run_backtest` | `artifacts/backtests/runs/` |
| 报告 | `tp_reporting`、`tp_pipelines.generate_report` | `artifacts/reports/` |
| 运行证据 | `tp_experiments`、各 pipeline step | `artifacts/pipeline_runs/` |
| 展示与控制 | `presentation_layer` | API、Dashboard 和受控 job |

## 编号资源工作区

编号目录只保留不可直接装入 Python 包的真实资源。

| 工作区 | 保留内容 | 状态 |
| --- | --- | --- |
| `00_screen/` | Canonical parquet、月更 Excel、QA、备份和人工 notebook | 生产数据边界 |
| `03_ml_enhanced/` | ML notebook、模型输入输出和监控资源 | 活跃 |
| `03_regime_model/` | Regime 输出和静态风险页面 | 活跃 |
| `03_technical_analysis/` | Technical notebook、patterns 数据和方法文档 | 活跃 |
| `08_presentation_layer/` | React/Vite 前端及应用所需静态/数据资源 | 活跃 |
| `13_sector_score_model/` | Sector 配置、方法论和专项结果 | 活跃研究 |
| `14_country_model/` | Country 数据和专项结果 | 活跃研究 |
| `15_small_cap_model/` | Small Cap 配置和专项结果 | 活跃研究 |
| `16_news_market_signal/` | News 查询、分区数据和研究结果 | 活跃研究 |
| `artifacts/research/runs/historical/` | 历史回测与研究证据库 | 只读历史数据，不是入口 |
| `11_docs/` | 当前正式文档和 archive | 文档中枢 |
| `99_archive/` | 退役代码、旧实验和迁移证据 | 不参与运行 |

## 公共入口

先执行一次 `python -m pip install -e .`。生产操作优先使用 `.venv_tp\Scripts\` 下由 `pyproject.toml` 安装的 `tp-*` 控制台命令：

| 用途 | 控制台入口 |
| --- | --- |
| 整理生产输入 | `tp-organize-inputs` |
| 数据刷新 | `tp-pipeline-refresh-data` |
| 信号导出 | `tp-pipeline-export-signals` |
| 候选池 | `tp-pipeline-build-candidates` |
| 组合优化 | `tp-pipeline-optimize-portfolio` |
| 回测 | `tp-backtest`、`tp-pipeline-run-backtest` |
| 报告 | `tp-pipeline-generate-report` |
| 总流水线 | `tp-pipeline-run-all` |
| 展示与控制塔 | `tp-presentation` |
| 实验记录 | `tp-experiments` |
| 配置化研究 | `tp-research` |
| News shadow 特征 | `tp-news-shadow` |
| 公司确定性报告 | `tp-company-report` |
| 旧入口检查 | `tp-check-legacy-references` |

模型专项研究可以使用已安装包的 `python -m tp_models...` 模块入口；不得按资源目录中的文件路径执行脚本。

## 已退役边界

- `01_tp_core/`、`02_pipelines/`、`06_optimiser/`、`src/backtest_code/` 已删除。
- `00_screen/monthly_update.py` 及模型资源目录中的薄 wrapper 已退役。
- 展示应用只通过 `presentation_layer` 启动；内部资源目录中的 `app.py`、`backend/main.py`、`start_app.ps1` 等兼容入口已退役。
- 禁止恢复 `sitecustomize.py`、`.pth`、业务代码 `sys.path` 注入、文件路径导入或 `python path/to/legacy_script.py`。
- `artifacts/research/runs/historical/` 可以作为显式历史输入读取，但新运行不得写入该目录。

上述规则由 `tp-check-legacy-references`、测试、CI 和 CRG ignore 共同校验。

## 仍需持续治理

- 历史回测库已按逐文件 inventory 和抽样内容哈希无损迁至 `artifacts/research/runs/historical/`；该目录只读并受保留策略保护。
- 各模型资源目录中的 `outputs/runs` 是专项工作区，不属于标准跨项目产物；它们必须继续排除在 pytest、ruff、mypy、CRG 和 CI discovery 之外。
- Archive 和 handoff 可以保留旧路径作为历史证据，但不得提供可复制的旧运行命令。

## V2 数据架构边界

主线数据流现在还包括不可变分区 Canonical Lake、版本化 DuckDB catalog release 和只读
presentation marts：

```text
incoming/raw -> Canonical Lake partitions + manifests
             -> DuckDB canonical views/catalog release
             -> QuerySpec repositories / materialized marts
             -> models, backtest, candidates, portfolio, presentation
```

Canonical Lake 保存事实，DuckDB 保存 catalog metadata 与可重建 mart；signals、candidates、
portfolio、reports 仍属于 Artifact，研究过程和决定理由仍属于 Run Card。`screen_aggregate.parquet`
和 `returns.parquet` 在 authority switch 前是 `compatibility_export`，不是第二个权威数据集。
单 writer lock、read-only web、atomic manifest/pointer、release rollback 和 retention 规则见
[`DATA_ARCHITECTURE_V2.md`](DATA_ARCHITECTURE_V2.md)、[`DUCKDB_OPERATIONS.md`](DUCKDB_OPERATIONS.md)
和 [`DUCKDB_MIGRATION_RUNBOOK.md`](DUCKDB_MIGRATION_RUNBOOK.md)。

当前决策是 `WRITER_CUTOVER_READY`：生产默认仍 legacy，Phase 7/8 只允许通过 evidence gate
和显式用户批准逐步激活，不能因 catalog release 已生成就提前退役旧入口。
