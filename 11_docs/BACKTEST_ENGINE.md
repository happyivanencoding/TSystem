# 统一回测引擎说明

最后更新：2026-07-01  
状态：已建立通用核心，旧入口保留兼容层。

## 1. 结论

回测主线现在分成两层：

1. `01_tp_core/general_backtest.py` 是通用核心，适用于大多数项目。它只要求输入标准目标权重表和 canonical `returns` 矩阵。
2. `07_backtest_code/` 是传统代码版回测主线，继续保留 `PtfBuilder`、组合构建、benchmark、YAML 配置、批量运行和产物保存。

以后新模型、技术分析、候选池或优化器不要再复制一份 `BacktestEngine.py`。它们应该先输出标准权重表，再调用 `tp_core.general_backtest` 或 `tp_core.backtesting.BacktestEngine.run_weights()`。

## 2. 标准输入输出

### 2.1 输入：目标权重表

最低字段：

| 字段 | 说明 |
| --- | --- |
| `Date` | 信号或再平衡日期 |
| `Company SEDOL` | 与 `returns.parquet` 列名一致的证券键 |
| `Portfolio weight` | 目标权重；引擎会按日期重新归一化 |

可以附加字段，例如 `signal_name`、`Sector`、`Name`、`Selection Rank`。这些字段会在执行权重表中尽量保留，但回测计算只依赖最低字段。

### 2.2 输入：returns

`returns` 使用宽表：

| 结构 | 规则 |
| --- | --- |
| index | 交易日，转为 `DatetimeIndex` |
| columns | 证券 SEDOL，字符串 |
| value | 日收益率 |

生产默认读取 `C:\GoogleDrive\TP\00_screen\returns.parquet`。

### 2.3 输出

`backtest_weight_table()` 和 `GeneralBacktestEngine.run_weights()` 返回 `GeneralBacktestResult`：

| 属性 | 说明 |
| --- | --- |
| `nav` | 基数 100 的净值序列 |
| `daily_returns` | 组合日收益 |
| `rebalance_weights` | 清洗、过滤、归一化后的再平衡权重 |
| `execution_weights` | 映射到可交易日期后的权重，MultiIndex 为 `Date` + `Company SEDOL` |
| `turnover` | 目标权重之间的单向换手估算 |
| `metrics` | 年化收益、年化波动、类 Sharpe、最大回撤等 |
| `manifest` | 输入行数、丢弃行数、日期映射、数据覆盖等审计信息 |

## 3. 交易日期口径

默认口径是保守的：

1. 权重表中的 `Date` 映射到 returns 中严格晚于该日期的第一个交易日。
2. 权重在该交易日收盘后生效。
3. 因此第一天组合收益为 0，下一交易日开始承担组合暴露。

这个口径与原 `07_backtest_code` 和 `03_technical_analysis` 中的漂移回测习惯一致，避免信号日和可交易日混淆造成前视偏差。

## 4. 版本对比和处理结果

| 位置 | 原用途 | 问题 | 当前处理 |
| --- | --- | --- | --- |
| `01_tp_core/general_backtest.py` | 新增通用权重表回测核心 | 无历史包袱 | 作为大多数项目的共享核心 |
| `07_backtest_code/BacktestEngine.py` | 旧 `PtfBuilder` API 兼容入口 | 仍承担传统组合构建流程 | 保留为现役主入口 |
| `07_backtest_code/core/backtest_engine.py` | 传统 security-list 回测核心 | 有历史 API，不能立即删除 | 继承 `GeneralBacktestEngine`，新增 `run_weights()` 通用入口 |
| `07_backtest_code/core/backtest_engine_optimized.py` | 向量化优化草稿 | `_get_sector_weights()` 未实现，未接入主线 | 原文件归档，原路径改为兼容 wrapper |
| `03_ml_enhanced/Codes/BacktestEngine.py` | ML 本地复制的单体回测引擎 | 与主线重复，且带旧 country/sector 优化逻辑 | 原文件归档，原路径改为兼容层 |
| `03_technical_analysis/pattern_backtest_engine.py` | 技术形态专用信号回测 | 有一套重复漂移计算 | 选股和打分逻辑保留，漂移回测改用 `tp_core.general_backtest` |
| `99_archive/frozen_20260629/`、`99_backtest_*_legacy/` | 历史 Web/GUI/第一版回测 | 多版本重复、旧 pkl 读取、维护成本高 | 只作历史参考，新代码不得引用 |

归档位置：

- `99_archive/backtest_engine_versions_20260629/03_ml_enhanced/Codes/BacktestEngine.py`
- `99_archive/backtest_engine_versions_20260629/07_backtest_code/core/backtest_engine_optimized.py`

### 4.1 最新开发版功能迁入原则

`07_backtest_code/_quarantine_20260701/latest_engine_downloads/` 中的 `download_08_*` 到 `download_11_*` 是最新 monolithic 开发版本的归档参考文件，不是新的生产入口。当前已迁入主线的内容包括：

| 功能 | 当前落点 | 说明 |
| --- | --- | --- |
| monthly drift fill | `core/portfolio_builder.py` | `fill_method: drift` 会用 returns 对缺失月份 sec list 权重做 drift 补齐；`copy` 保留兼容行为 |
| benchmark-aware secondary ticker merge | `utils/data_utils.py` | 合并双上市证券时使用当前 benchmark 权重列 |
| ESG pivot score | `core/esg_pivot.py` + `core/portfolio_builder.py` | pivot 文件定位和解析独立成模块，PortfolioBuilder 只使用数值阈值 |
| top/bottom ratio plot | `utils/plotting.py` + `BacktestEngine.py` | 同时展示 Top、Bottom、Benchmark 以及三个 ratio |
| download_09 optimizer | `06_optimiser/optimizer_engine.py` | 已作为现役优化器标准接入，旧优化器文件已隔离 |
| optimized backtest bridge | `core/backtest_engine_optimized.py` | 可以消费优化器 `Wopt` 并转成标准权重表回测 |

尚未直接迁入的内容：`download_10_factor_pipeline_reference.py` factor pipeline 需要进入信号/模型层，不应扩大 `PortfolioBuilder` 的职责。

### 4.2 `07_backtest_code` 内部配置清理

`07_backtest_code` 现在只保留 `configs/default.yaml` 作为现役默认配置。旧版 `config/config.yaml`、`utils/config.py` 和 `configs/user1.yaml`、`configs/user2.yaml` 占位 profile 已移动到 `07_backtest_code/_quarantine_20260630/legacy_config_loader/`。新代码不得引用旧 `config/` 目录；需要新增 profile 时，只在 `configs/` 下创建有明确业务含义的 YAML 文件。

## 5. 新项目接入方式

### 5.1 直接使用通用核心

```python
from tp_core.general_backtest import backtest_weight_table

result = backtest_weight_table(
    weights=target_weights,
    returns=returns,
)

nav = result.nav
manifest = result.manifest
```

### 5.2 使用现役回测引擎

```python
from tp_core.backtesting import BacktestEngine

engine = BacktestEngine(returns)
result = engine.run_weights(target_weights)
```

### 5.3 普通 sec list 与优化器 sec list

`07_backtest_code.BacktestEngine.PtfBuilder` 保留两条入口：

| 入口 | 是否调用优化器 | 权重来源 | 结果字段 |
| --- | --- | --- | --- |
| `sec_list_spot()` | 否 | `ponderation` 规则，例如 Equalweight、Capweight 或已有组合构建规则 | `sec_list_monthly` |
| `sec_list_spot_optim()` | 是 | `06_optimiser/optimizer_engine.py` 输出的 `Wopt` | `sec_list_optimized_monthly`、`optimizer_result_monthly` |

设计原则是普通路径和优化路径互不覆盖。需要老版 sec list 时只运行 `sec_list_spot()`；需要优化后的 sec list 时再运行 `sec_list_spot_optim()`。优化后回测调用 `backtest_optimized_sec_list()`，它会把 `Wopt` 转为标准目标权重表再交给统一回测核心。

优化器内部仍保留部分历史列名假设，例如 `Weight in MSCI WORLD`。当前兼容层会根据当前 `bench` 自动补齐 `Weight in {bench}` 与 `Weight in MSCI WORLD` 的别名，避免普通 sec list 或非 MSCI benchmark 被硬编码污染。
### 5.4 技术分析或 ML 的推荐边界

| 项目 | 应负责 | 不应负责 |
| --- | --- | --- |
| `03_ml_enhanced/` | 训练、预测、信号解释、输出标准信号表 | 复制回测引擎 |
| `03_technical_analysis/` | 技术指标、形态识别、输出 technical signals 或目标权重 | 自带独立主回测核心 |
| `06_optimiser/` | 把候选名单和约束转成目标权重 | 重新计算 returns 或维护自己的数据副本 |
| `07_backtest_code/` | 回测、绩效、归因、批量运行和产物保存 | 训练模型或生成原始信号 |

## 6. 后续优化建议

1. 把 `07_backtest_code/core/backtest_engine.py` 中的旧 `calculate_portfolio_returns()` 逐步改成调用 `tp_core.general_backtest`，但要先用真实历史回测产物做数值对账。
2. 为 `GeneralBacktestResult.manifest` 增加文件级写盘函数，和 `10_pipeline_runs/manifests/run_backtest/` 对齐。
3. `06_optimiser/optimizer_engine.py` 已提供 `to_standard_weight_table()`；当前 `.venv_tp` 已覆盖安装 `cvxpy 1.7.5` 和 `ecos 2.0.14`，可以导入 `cvxpy` 并使用 `ECOS_BB` 求解 mixed-integer 小问题。
4. 对长周期、大 universe 回测再做向量化优化；优化版必须先通过通用核心的行为测试，不能再保留半成品第二引擎。





