# archive

`archive/` 存放已经冻结的历史项目。这里的内容只用于追溯，不作为生产入口，也不允许被新代码直接引用。

当前冻结批次：

- `frozen_20260629/`：旧 ML、旧回测、旧 FactSet/Excel、技术分析 V1、早期 `backtest/`、早期 `cyc/`、旧深度学习 pipeline。
- `notebook_cleanup_20260629/`：根目录旧测试 notebook 和临时实验产物。

如果确实需要复用冻结目录中的逻辑，应先把相关函数迁移到当前主线目录或 `tp_core/`，并补充测试和文档。
