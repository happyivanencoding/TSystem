# Factor Explorer 运行数据源

本目录与统一入口 `C:\GoogleDrive\TP\09_reports\factor-explorer.html` 属于同一当前项目，不是归档。

四个单市场 HTML 只作为旧基线 payload 的稳定输入，不再作为展示入口：

- `eu-small-factor-explorer.html`
- `sp500-factor-explorer.html`
- `stoxx600-factor-explorer.html`
- `nasdaq-factor-explorer.html`

`build_factor_explorer.py` 从本目录解析旧基线，再与四个新 extension run 合并，先刷新 `factor_model_archive/`，最后生成统一 HTML。

`09_reports/archive/` 不包含生成器依赖，可以独立清理。
