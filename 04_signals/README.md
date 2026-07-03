# 04_signals

`04_signals/` 是统一信号表的默认输出目录。这里不存放原始数据，只存放从 ML、技术分析、Regime、基本面等模块导出的标准化信号表。

统一 schema 见 [`../11_docs/SIGNAL_SCHEMA.md`](../11_docs/SIGNAL_SCHEMA.md)。

建议文件：

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `ml_signals.parquet` | `03_ml_enhanced/export_signals.py` | 证券级 ML 分数 |
| `technical_signals.parquet` | `03_technical_analysis/export_technical_signals.py` | 证券级技术信号 |
| `regime_risk_budget.parquet` | `03_regime_model/export_risk_budget.py` | 区域级风险预算信号 |
