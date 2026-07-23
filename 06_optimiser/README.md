# optimizer

## 定位

`06_optimiser/` 是 TP 唯一 Python 组合优化器。公开入口只有：

```python
from optimizer import OptimizerConfig, OptimizerObjective, optimize_portfolio
```

`optimizer.py` 接收候选证券、benchmark 权重、score、协方差、当前权重、
上下界、分组约束和任意线性暴露约束，返回 `target_weight`、求解状态、
约束审计和完整 optimizer metadata。

普通因子选股由
`tp_core.backtesting.SecurityListConstructor` 完成；只有显式调用
`OfficialPortfolioBacktest.build_optimized_monthly_security_list()` 或
`02_pipelines.optimize_portfolio` 时才进入优化器。

## 当前模块

| 文件 | 作用 |
| --- | --- |
| `optimizer.py` | 唯一求解 API、目标函数、约束、solver fallback 和审计 |
| `test_optimizer.py` | 目标函数、TE、换手、分组、线性、基数与 metadata 测试 |

旧 `optimizer_engine.py`、`optimiser` package shim、`01_tp_core/optimisation.py`
和 `FRAIS.py` 已从活动代码删除。

## 支持能力

- 目标：min tracking error、max score、min turnover、min variance、blended
- 约束：单股上下界、主动偏离、TE、换手、score、持仓数、forced/forbidden
- 分组：行业、国家、地区、规模桶或任意类别上下界
- 线性暴露：beta、dividend、carbon、ESG、liquidity 或任意系数矩阵
- 求解：按可用 solver 顺序回退，结果记录实际 solver 和失败尝试

详细契约见
[`../11_docs/PORTFOLIO_OPTIMIZER.md`](../11_docs/PORTFOLIO_OPTIMIZER.md)。

## 与回测边界

优化器不计算 NAV。`OptimizerBacktestAdapter` 把 `target_weight` 转成
标准权重后委托 `SecurityNavEngine`。优化产物必须保留
`optimizer_id`、`optimizer_version`、objective、solver、objective policy
和 constraint policy。
