# 四市场新旧因子模型结果档案

本目录由 `artifacts/reports/build_factor_explorer.py` 生成；先整理旧基线与新扩展结果，再用同一 payload 生成 `factor-explorer.html`。

## 查询文件

- `model_registry.csv`：每个可绘图配置一行，含版本、指标、解释和来源。
- `nav_series.csv`：所有配置的 Top / Worst / Benchmark 时间序列。
- `components.csv`：每个配置的底层变量、bucket 与权重。
- `all_result_rows.csv`：旧/新 run 的 Gate、subset、LOO、synergy 与 performance 原始结果合并表。
- `source_files.csv`：原始结果文件索引，不复制或覆盖历史 run。
- `model_archive.json`：HTML 使用的完整四市场 payload。
- `<market>/`：每个市场独立的同名 CSV，便于单市场查询。

## 市场与版本

- `eu-small`：旧基线 96 个可绘图配置；新扩展 40 个；old=`C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\eu_small_relative_synergy_20260709`；new=`C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\eu_small_factor_extension_20260711`。
- `sp500`：旧基线 88 个可绘图配置；新扩展 62 个；old=`C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\sp500_relative_synergy_20260710`；new=`C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\sp500_factor_extension_20260711`。
- `stoxx600`：旧基线 10 个可绘图配置；新扩展 50 个；old=`C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\stoxx600_relative_synergy_20260709`；new=`C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\stoxx600_factor_extension_20260711`。
- `nasdaq`：旧基线 5 个可绘图配置；新扩展 23 个；old=`C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\nasdaq_extended_factor_research_20260709`；new=`C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\nasdaq_tech_factor_extension_20260710`。

默认候选只是页面打开入口，不代表唯一最优模型。比较配置时应同时阅读主动 CAGR、Top/Worst、Robust、Coverage、回撤、换手与经济机制。

