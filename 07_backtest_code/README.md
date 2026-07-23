# 07_backtest_code

## 定位

`07_backtest_code` 是当前回测主线，替代原来的 Web app 和 GUI 入口。它保留回测引擎、组合构建、指标、归因、YAML 配置、批量运行和运行产物保存，但不维护前端界面。

## 数据来源

默认读取 TP canonical 数据：

- `C:\GoogleDrive\TP\00_screen\screen_aggregate.parquet`
- `C:\GoogleDrive\TP\00_screen\returns.parquet`

代码入口仍可通过命令行参数覆盖路径，但生产和研究默认应使用 canonical 数据。

## 快速运行

先检查输入文件和可用字段：

```powershell
python C:\GoogleDrive\TP\07_backtest_code\run_backtest.py inspect
```

执行默认 profile：

```powershell
python C:\GoogleDrive\TP\07_backtest_code\run_backtest.py run
```

覆盖 benchmark、metric 和开始日期：

```powershell
python C:\GoogleDrive\TP\07_backtest_code\run_backtest.py run `
  --bench "STOXX EUROPE 600" `
  --metric "Quality Avg Percentile" `
  --start-date 2020-01-31 `
  --percentile 0.05
```

运行产物默认写入 `runs/<user>/<timestamp>_<run_label>/`，包含配置快照、manifest、组合成分、排除清单、组合表现、benchmark 表现、HTML 图和日志。

## 当前已接入的新引擎功能

`_quarantine_20260701/latest_engine_downloads/` 中的 `download_08_*` 到 `download_11_*` 是最新开发版本归档参考，但不作为现役入口直接运行。已确认并迁入当前主线的功能：

- `fill_method: drift`：当调仓频率低于月度时，用 `returns` 对缺失月份的 sec list 权重做 drift 补齐；`fill_method: copy` 仍保留直接复制上月清单的兼容行为。
- benchmark-aware secondary ticker merge：双上市证券合并使用当前 benchmark 的 `Weight in {bench}` 列，不再硬编码 MSCI WORLD。
- ESG pivot threshold：`score_pivot_esg` 可以直接给数值阈值，也可以给 pivot 文件中的 `sec_id` 文本键，并通过 `score_pivot_esg_path` 解析最新 pivot 文件。
- top/bottom/benchmark 对比图：提供 Top、Bottom、Benchmark 三条净值线，以及 `Top/Benchmark`、`Bottom/Benchmark`、`Top/Bottom` ratio。

统一回测核心说明见 [`../11_docs/BACKTEST_ENGINE.md`](../11_docs/BACKTEST_ENGINE.md)。新项目如果已经有目标权重表，只调用 `tp_core.general_backtest.backtest_weight_table()` 或 `GeneralBacktestEngine.run_weights()`。`PtfBuilder` 只负责组合构造和 official artifacts。

## 两种 sec list 入口

当前保留两条兼容路径：

1. 普通 sec list：调用 `PtfBuilder.sec_list_spot()`。这条路径不调用优化器，`Weight` 由 `ponderation` 决定，例如 `Equalweight`、`Capweight` 或已有规则。
2. 优化器 sec list：调用 `PtfBuilder.sec_list_spot_optim()`。这条路径会先生成候选池和约束输入，再调用 `06_optimiser/optimizer_engine.py`，用优化器输出的 `Wopt` 生成单独的优化版 `Weight`。

两条路径的结果分开保存：普通结果在 `sec_list_monthly`，优化版结果在 `sec_list_optimized_monthly`，优化器原始结果在 `optimizer_result_monthly`。普通 sec list 不会被优化器权重覆盖。

最小示例：

```python
from tp_core.backtesting import PtfBuilder

builder = PtfBuilder(
    screen=screen,
    returns=returns,
    bench="STOXX EUROPE 600",
    metrics="EPS Growth FY1 CIQ",
    ponderation="Equalweight",
    optimizer_config={
        "current_params": {
            "margin_title": 0.005,
            "margin_country": 0.03,
            "margin_sector": 0.02,
            "nb_max_titres": 120,
            "nb_min_titres": 20,
            "max_turnover": 0.30,
            "min_score_target": 0.0,
            "te_max": 0.03,
        }
    },
)

normal_sec_list, exclusions = builder.sec_list_spot()
optimized_sec_list = builder.sec_list_spot_optim(init=True, drift=False)
optimized_perf = builder.backtest_optimized_sec_list()
```

注意：优化器真实求解依赖 `cvxpy` 和 MIP solver；如果只是生成普通 sec list，不需要这些依赖。
## 配置规则

当前只保留一个现役配置入口：`configs/default.yaml`。以后新增研究或生产参数时，应该在 `configs/` 下新增有明确业务含义的 profile，例如 `monthly_research.yaml`，不要恢复旧的 `config/config.yaml`。

旧版 `config/config.yaml`、`utils/config.py` 和 `user1/user2` 占位 profile 已移动到 `_quarantine_20260630/legacy_config_loader/`，仅作回滚参考。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `core/ptf_builder.py` | 组合构造 facade；通过 `tp_core.backtesting.PtfBuilder` 导入 |
| `core/portfolio_builder.py` | 传统选股、过滤、组合构建逻辑，仍由 `PtfBuilder` 使用 |
| `core/weight_table_adapter.py` | 将 security list 和 benchmark 转为标准权重表 |
| `core/optimizer_backtest_adapter.py` | 将优化器结果转为标准权重；不计算第二套 NAV |
| `core/esg_pivot.py` | ESG pivot 文件定位和阈值解析；PortfolioBuilder 只接收解析后的阈值 |
| `utils/` | 绘图、常量、数据工具；旧 `utils/config.py` 已隔离 |
| `configs/` | YAML profile；`default.yaml` 是默认代码运行配置 |
| `src/backtest_code/` | CLI、配置加载、校验、runner 和产物保存 |
| `runs/` | 回测运行产物 |
| `logs/` | 运行日志 |
| `tests/` | 从原 web app 迁入的回归测试 |
| `_quarantine_20260630/` | 本目录内确认不再参与主线的可回滚隔离内容 |

## 前端状态

原 `backtest_wep_app` 的 Streamlit/API/Docker 入口已移动到 `99_backtest_web_app_legacy/_quarantine_20260629/legacy_frontend/`，重复回测核心已移动到 `99_backtest_web_app_legacy/_quarantine_20260629/legacy_backtest_core/`。原 `Backtest_GUI` 的 PySide6 界面和启动脚本已移动到 `99_backtest_gui_legacy/_quarantine_20260629/legacy_gui_frontend/`，历史 runner/校验源码副本已移动到 `99_backtest_gui_legacy/_quarantine_20260629/legacy_gui_core/`。这些内容只作为可回滚历史参考，不再作为主线维护。

## 功能拆分规则

- `download_09_optimizer_reference.py` 的优化器逻辑不得直接并入 `PortfolioBuilder`。它应迁入 `06_optimiser/` 或后续 `tp_core.optimization`，并以候选名单、约束配置和目标权重表作为输入输出。
- `download_10_factor_pipeline_reference.py` 的 factor pipeline 不应放进回测引擎。它应迁入信号/模型层，输出统一 signal schema 或标准目标权重表。
- `download_08_legacy_ptfbuilder.py` 只作为旧 monolithic 参考；若某段行为仍有价值，必须先拆成小函数、补测试，再接入主线。
- `download_11_latest_ptfbuilder_reference.py` 只作历史参考；现役入口是 `tp_core.backtesting.PtfBuilder` + `src/backtest_code/runner`，不得新增第二套 PtfBuilder 或 NAV 内核。

