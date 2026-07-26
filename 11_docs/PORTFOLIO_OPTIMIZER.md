# TP 唯一组合优化 API

最后更新：2026-07-23

## 唯一入口

活动代码只能调用：

```python
from tp_portfolio import OptimizerConfig, OptimizerObjective, optimize_portfolio

result = optimize_portfolio(
    candidates,
    id_col="Company SEDOL",
    benchmark_weights="benchmark_weight",
    scores="score",
    covariance=covariance,
    config=OptimizerConfig(
        objective=OptimizerObjective.MIN_TRACKING_ERROR,
    ),
)
```

物理入口为 `src/tp_portfolio/`。`tp_pipelines` 和
`SecurityListConstructor` 都必须调用该函数，不得调用求解器内部函数。
`01_tp_core/optimisation.py`、`optimizer_engine.py`、`optimiser` package
shim 和旧 `FRAIS.py` 已从活动代码删除。

## 目标函数

`OptimizerObjective` 支持：

- `min_tracking_error`
- `max_score`
- `min_turnover`
- `min_variance`
- `blended`

`blended` 可同时设置 score reward、tracking-error penalty、turnover
penalty 和 active-weight L2 penalty。协方差矩阵的频率与单位由调用方
明确提供；优化器不猜测年化口径。

## 约束

`OptimizerConfig` 支持：

- long-only 或调用方提供的多空上下界
- 单股 lower/upper bounds
- benchmark 单股主动偏离上限
- 最大 tracking error
- 最大双边 turnover
- 候选池外旧持仓 `external_current_weight`，计入强制卖出与 turnover
- 最低或最高 portfolio score
- 最少/最多持仓数
- 入选持仓最低权重
- forced/forbidden securities

`GroupConstraint` 支持行业、国家、地区、规模桶或任意类别的上下界。
`LinearConstraint` 支持任意线性暴露：

```text
lower <= coefficients @ weights <= upper
```

因此 beta、dividend、carbon、ESG、duration、liquidity、factor exposure
和自定义推荐约束都使用同一对象；等式约束令 lower 等于 upper。

## 产物契约

`PortfolioOptimizationResult.to_frame()` 至少写：

- `target_weight`
- `optimizer_id`
- `optimizer_version`
- `optimizer_objective`
- `optimizer_solver`
- `optimizer_status`

`metadata` 必须保存 objective policy 和 constraint policy；`audit`
必须保存权重合计、上下界偏离、持仓数、tracking error、score、
turnover、active share、group constraints 和 linear constraints 的实际值。

求解后必须按统一容差复核全部证券上下界、TE、turnover、score、
持仓数、forced/forbidden、group 和一般线性约束。不得在 optimizer
返回后删除小权重再归一；这种后处理会使已满足的约束失效。

## 与回测的边界

优化器只生成目标权重，不计算 NAV。`OptimizerBacktestAdapter` 将
`target_weight` 转成标准权重表后委托 `SecurityNavEngine`。任何优化器
产物进入 official 回测前都必须保留 optimizer metadata。
