# TP 统一数据源

最后更新：2026-07-25

## 总规则

所有仍在使用的 TP 项目都必须读取同一套 canonical 数据文件：

| 逻辑数据源 | Canonical 路径 |
| --- | --- |
| 月度 Screen 全历史面板 | `C:\GoogleDrive\TP\00_screen\screen_aggregate.parquet` |
| 最新月度 Screen 快照 | `C:\GoogleDrive\TP\00_screen\last_screen.parquet` |
| 日频收益矩阵 | `C:\GoogleDrive\TP\00_screen\returns.parquet` |
| 近 5 年 Screen 子集 | `C:\GoogleDrive\TP\00_screen\screen_aggregate_5Y.parquet` |
| 月更映射表 | `C:\GoogleDrive\TP\00_screen\Transco_FactSet_ICB.xlsx` |
| CIQ 月更输入目录 | `C:\GoogleDrive\TP\00_screen\production_inputs\incoming\YYYYMM\ciq` |
| 生产输入根目录 | `C:\GoogleDrive\TP\00_screen\production_inputs` |
| 补充数据影子层 | `C:\GoogleDrive\TP\00_screen\supplemental` |

统一声明位于：

```python
from tp_core.data_sources import (
    SCREEN_AGGREGATE_PATH,
    RETURNS_PATH,
    LAST_SCREEN_PATH,
    SUPPLEMENTAL_DIR,
)
```

新代码应从 `tp_core.data_sources` 导入路径。不要在各项目里硬编码本地副本，例如 `Input_files/screen_aggregate.parquet`、`screen_aggregateCIQ.parquet`、`screen_aggregate.pkl` 或 `returns.pkl`。

当前生产月更入口已经切到 `00_screen/production_inputs/incoming/YYYYMM/`。旧的 `00_screen/monthly`、`00_screen/returns`、`00_screen/ciq` 已移动到 `00_screen/_quarantine_20260629/`，只作为短期回滚来源，不再作为生产入口。

## 数据契约

canonical 数据集的语义见 `DATA_CONTRACT.md`，可执行校验逻辑位于 `tp_core.data_contract` 与 `tp_core.io`。

```python
from tp_core.io import read_screen_aggregate, read_returns
from tp_core.data_contract import validate_screen_contract, validate_returns_contract
```

## 允许的覆盖方式

临时实验只能通过统一环境变量覆盖路径：

| 环境变量 | 含义 |
| --- | --- |
| `TP_ROOT` | TP 工作区根目录 |
| `TP_SCREEN_DIR` | Screen 数据目录 |
| `TP_SCREEN_AGGREGATE_PATH` | Screen 全历史面板 |
| `TP_RETURNS_PATH` | 日频收益矩阵 |
| `TP_LAST_SCREEN_PATH` | 最新 Screen 快照 |
| `TP_SCREEN_AGGREGATE_5Y_PATH` | 近 5 年 Screen 子集 |
| `TP_CIQ_NEW_DIR` | 兼容旧代码的 CIQ 输入覆盖；默认指向 `production_inputs/incoming` |
| `TP_PRODUCTION_INPUTS_DIR` | 生产输入根目录 |
| `TP_SUPPLEMENTAL_DIR` | 补充数据影子层根目录 |

像 `TA_SCREEN_PATH` 这类项目特定变量可以为兼容旧代码继续存在，但默认值必须来自 `tp_core.data_sources`。

## 共享入口

| 需求 | 导入或命令 |
| --- | --- |
| 读取 canonical screen | `from tp_core.io import read_screen_aggregate` |
| 读取 canonical returns | `from tp_core.io import read_returns` |
| 数据契约校验 | `from tp_core.data_contract import validate_screen_contract, validate_returns_contract` |
| 共享 PtfBuilder | `from tp_core.backtesting import PtfBuilder` |
| 生产输入整理 | `python -m tp_core.production_inputs` |
| 主流水线总入口 | `python -m pipelines.run_all --input-month YYYYMM --as-of YYYY-MM-DD` |
| 单独刷新信号 | `python -m pipelines.export_signals --as-of YYYY-MM-DD` |
| 单独生成候选池 | `python -m pipelines.build_candidates --as-of YYYY-MM-DD` |
| 单独生成目标权重 | `python -m pipelines.optimize_portfolio --as-of YYYY-MM-DD` |
| returns 异常收益审计 | `python -m tp_core.returns_audit --report-path 00_screen/qa/returns_anomaly_audit.json` |
| 补充数据 dry-run | `python -m tp_pipelines.refresh_supplemental_data --source ecb --dry-run` |

补充数据目录不是第三张 canonical 表。默认刷新只生成不可变 raw、标准化记录、point-in-time
月末结果和 QA，不会改写 `screen_aggregate.parquet`。

## 迁移状态

已更新的活跃或默认入口：

- `03_regime_model/config.py`
- `03_regime_model/merge_ciq_history.py`
- `08_presentation_layer/legacy_apps/company_analysis/backend/analysis.py`
- `99_archive/project_cleanup_20260707/99_backtest_web_app_legacy/utils/config.py`
- `99_archive/project_cleanup_20260707/99_backtest_web_app_legacy/streamlit_app/app.py`
- `99_archive/project_cleanup_20260707/99_backtest_web_app_legacy/streamlit_app/test_app.py`
- `99_archive/project_cleanup_20260707/99_backtest_web_app_legacy/tests/test_refactored_system.py`
- `08_presentation_layer/legacy_apps/web_app_des_companies/config/settings.py`
- `08_presentation_layer/legacy_apps/dashboard_analysis/dashboard.py`
- `03_ml_enhanced/Config/config_EU.py`
- `03_ml_enhanced/Config/config_US.py`
- `03_ml_enhanced/Config/config_OTHER.py`
- `03_ml_enhanced/Config/config_EM.py`
- `ML/Config/config_EU.py`
- `ML/Config/config_US.py`
- `ML/Config/config_OTHER.py`
- `03_technical_analysis/Main.py`
- `技术分析和深度学习/深度学习/config_EU_test_backtest.py`
- `ML/Codes/*` 活跃 parquet 迁移
- `99_archive/project_cleanup_20260707/99_backtest_web_app_legacy/*` 活跃 `PtfBuilder` 导入已改为 `tp_core.backtesting`

已冻结或只保留历史价值的 legacy/archive 引用：

- `99_archive/frozen_20260629/factsetProd第一版/`
- `99_archive/frozen_20260629/ML第一版/`
- `99_archive/frozen_20260629/回测第一版/`
- `99_archive/frozen_20260629/ML/`
- `99_archive/frozen_20260629/技术分析和深度学习__技术分析_V1/`
- `06_optimiser/sec_list_generation.py`
- 含历史硬编码路径的 notebook
- `FINAL_IMPLEMENTATION_SUMMARY.md` 等历史实现记录

这些内容应视作归档参考；只有重新纳入活跃流程时才需要继续迁移。

## 快速检查

冻结目录引用检查：

```powershell
python -m tp_core.legacy_policy
```

数据源存在性检查：

```python
from tp_core.data_sources import data_sources, validate_data_sources

print(data_sources(as_strings=True))
print(validate_data_sources())
```

生产环境预期结果：

```python
{"screen_aggregate": True, "returns": True}
```
