# optimiser

## 定位

`06_optimiser/` 是当前唯一 Python 组合优化器主线。现役标准已经切换为从 `download_09_optimizer_reference.py` 迁入的 `optimizer_engine.py`，用于把候选证券名单、Score ML、benchmark 权重、旧组合漂移权重、上下限、行业/地区目标和协方差矩阵转成优化后的目标权重。

旧 `portfolio_generator.py`、`turnover_optimization.py`、`sec_list_generation.py` 功能不完善且重复，已移动到 `_quarantine_20260701/legacy_optimizer/`，只作为可回滚历史参考。

注意：`06_optimiser/` 不替代普通 sec list 生成逻辑。普通组合仍由 `07_backtest_code.PtfBuilder.sec_list_spot()` 按 `ponderation` 生成；只有显式调用 `sec_list_spot_optim()` 时才进入本优化器。

## 当前模块

| 文件 | 作用 |
| --- | --- |
| `optimizer_engine.py` | 现役 download_09 优化器：screen 准备、协方差、sector/geo target、lb/ub、heuristique、cvxpy MIP 优化、约束报告 |
| `test_optimizer_engine.py` | 现役优化器的导入、heuristique、标准权重转换和 cvxpy 环境测试 |
| `optimiser/__init__.py` | 兼容逻辑包入口，导出 `optimizer_engine.py` 的现役函数 |
| `_quarantine_20260701/legacy_optimizer/` | 旧优化器文件和旧测试，可回滚但不作为主线 |

## 标准入口

```python
from optimizer_engine import (
    generate_screen_for_optim,
    generate_covariance_matrix,
    define_secto_target_and_geo_target2,
    define_lb_ub,
    verifier_contraintes,
    selection_repechage,
    optimize,
    generate_exposure_reports,
    to_standard_weight_table,
)
```

`optimize()` 返回含 `Wopt` 的 dataframe。回测前用：

```python
weights = to_standard_weight_table(result_df)
```

然后交给 `tp_core.backtesting.OptimizerBacktestAdapter`；适配器只负责标准化权重，NAV 始终由 `tp_core.general_backtest` 计算。

## 环境注意

该优化器使用 `cvxpy` 混合整数优化，优先使用 SCIP solver；若本机没有 SCIP，会尝试 `ECOS_BB`、`CBC`、`GLPK_MI`、`HIGHS`。当前代码已改成 cvxpy 懒加载：模块可以导入，但调用 `optimize()` 时必须有可用 cvxpy/solver 环境。

当前 `.venv_tp` 已在本地环境层覆盖安装 `cvxpy 1.7.5` 和 `ecos 2.0.14`，保留项目现有 `numpy 1.26.4` 约束。已验证 `cvxpy` 可以导入，且 `ECOS_BB` mixed-integer solver 可以求解小型问题。由于 `.venv_tp` 是 `--system-site-packages` 环境，`pip check` 仍会看到 Anaconda 历史包的其他冲突；这些冲突和当前优化器依赖无关。

## 数据来源

新入口应读取：

- canonical `00_screen/` 数据；
- `04_signals/` 下的统一信号表或包含 `Score ML` 的候选名单；
- `07_backtest_code/runs/` 或当前组合持仓作为旧组合输入；
- canonical `00_screen/returns.parquet` 用于 drift 和 covariance。

不要读取冻结目录，也不要从 Excel notebook 流程开始新工作。



