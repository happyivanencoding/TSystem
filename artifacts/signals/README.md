# artifacts/signals

`artifacts/signals/` 是统一信号表的默认输出目录。这里不存放原始数据，只存放从 ML、技术分析、Regime、基本面等模块导出的标准化信号表。

统一 schema 见 [`../../11_docs/SIGNAL_SCHEMA.md`](../../11_docs/SIGNAL_SCHEMA.md)。

建议文件：

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `ml_signals.parquet` | `tp_models.ml.signals` | 证券级 ML 分数 |
| `technical_signals.parquet` | `tp_models.technical_signals` | 证券级技术信号 |
| `regime_risk_budget.parquet` | `tp_models.regime.export_risk_budget` | 区域级风险预算信号 |

