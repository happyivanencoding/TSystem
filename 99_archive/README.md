# archive

`archive/` 存放已经冻结的历史项目。这里的内容只用于追溯，不作为生产入口，也不允许被新代码直接引用。

当前冻结批次：

- `frozen_20260629/`：旧 ML、旧回测、旧 FactSet/Excel、技术分析 V1、早期 `backtest/`、早期 `cyc/`、旧深度学习 pipeline。
- `notebook_cleanup_20260629/`：根目录旧测试 notebook 和临时实验产物。
- `external_references_20260705/`：外部参考模板库，原位于 `08_company_analysis/Inspiration_Claude`，不作为 TP 生产入口。
- `project_cleanup_20260707/`：原 `00_项目主线索引/`、`12_small_cap/`、`99_optimiseur_legacy/`、`99_backtest_gui_legacy/`、`99_backtest_web_app_legacy/` 的历史目录；编号索引已并入 `11_docs/PROJECTS.md`，其余目录不再作为根目录活跃项目。

如果确实需要复用冻结目录中的逻辑，应先把相关函数迁移到当前主线目录或 `tp_core/`，并补充测试和文档。
