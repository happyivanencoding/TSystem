# 统一信号表 Schema

统一信号表用于承接 ML、技术指标、Regime、基本面和人工信号。目标是让候选池、组合优化、回测和报告层读取同一种结构，而不是每个模型各自发明字段。

## 必填字段

| 字段 | 含义 |
| --- | --- |
| `Date` | 信号日期，月末、周末或交易日 |
| `signal_family` | 信号族：`ML`、`Technical`、`Regime`、`country_model`、`Sector`、`Fundamental`、`Manual` 等 |
| `signal_name` | 具体信号名，例如 `score_ml`、`structure_signal`、`risk_budget_multiplier` |
| `scope` | 信号粒度：`security`、`region`、`portfolio`、`market`、`universe` |
| `score` | 机器可读分数或乘数 |
| `direction` | 分数方向：`higher_is_better`、`lower_is_better`、`binary_positive`、`binary_negative`、`neutral_midpoint`、`higher_risk_budget` |
| `coverage_flag` | 该行信号是否可用 |
| `model_version` | 模型或导出版本 |
| `source_project` | 来源项目 |

## 常用可选字段

| 字段 | 含义 |
| --- | --- |
| `Company SEDOL` | 证券级信号主键，`scope=security` 时必填 |
| `ISIN` | 可选证券标识 |
| `region` | 区域级或证券区域标签 |
| `benchmark` | benchmark 名称 |
| `universe` | universe 名称 |
| `score_pct` | 同日期横截面分位 |
| `raw_value` | 原始值或原始标签 |
| `as_of_date` | 数据可见日期 |
| `effective_date` | 信号生效日期 |
| `horizon` | 预测或持有期限 |
| `confidence` | 置信度 |
| `signal_description` | 简短说明 |

## 当前默认导出

| 来源 | 默认输出 | 粒度 |
| --- | --- | --- |
| `python -m tp_models.ml.cli export-signals` | `artifacts/signals/ml_signals.parquet` | security |
| `python -m tp_models.technical_signals` | `artifacts/signals/technical_signals.parquet` | security |
| `python -m tp_models.regime.export_risk_budget` | `artifacts/signals/regime_risk_budget.parquet` | region |
| `python -m tp_models.country` | `artifacts/signals/country_model_signals.parquet` | region |
| `python -m tp_models.sector.model` | `13_sector_score_model/outputs_*/sector_scores_panel.parquet` | sector |

## 校验命令

```powershell
python -m tp_core.signals C:\GoogleDrive\TP\artifacts/signals\ml_signals.parquet
```
