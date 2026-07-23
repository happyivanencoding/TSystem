# TP 项目 Python 环境

最后更新：2026-06-30

本文档记录 `C:\GoogleDrive\TP` 当前推荐使用的项目专用 Python 环境。原则是：生产脚本、notebook、pytest 和临时验证都优先使用同一个项目环境，避免被系统 Python 或 Anaconda base 的全局状态影响。

## 当前环境

| 项目 | 路径或名称 |
| --- | --- |
| 虚拟环境 | `C:\GoogleDrive\TP\.venv_tp` |
| Python 可执行文件 | `C:\GoogleDrive\TP\.venv_tp\Scripts\python.exe` |
| Jupyter kernel | `tp-prod` |
| Kernel 显示名 | `TP Production Python` |
| 本地 kernel 配置 | `C:\GoogleDrive\TP\.jupyter\kernels\tp-prod\kernel.json` |
| 本地 IPython 目录 | `C:\GoogleDrive\TP\.ipython` |
| 可复现环境清单 | `C:\GoogleDrive\TP\environment.yml` |

该环境由 Anaconda Python 3.11 创建，并启用了 `--system-site-packages`。这样可以复用本机已经稳定安装的大型科学计算包，同时把 TP 项目专用的补充依赖和路径规则固定在 `.venv_tp` 内。

如果未来迁移机器或希望完全隔离 Anaconda base，可以用 `environment.yml` 重新创建 conda 环境：

```powershell
conda env create -f C:\GoogleDrive\TP\environment.yml
conda activate tp-prod
```

当前实际运行仍以 `.venv_tp` 为准，因为它已经通过核心导入、notebook kernel smoke 和 pytest 验收。

## 使用方式

PowerShell 中激活环境：

```powershell
C:\GoogleDrive\TP\.venv_tp\Scripts\Activate.ps1
```

不激活环境时，也可以直接指定 Python：

```powershell
C:\GoogleDrive\TP\.venv_tp\Scripts\python.exe -m pytest
```

启动或执行 notebook 前，建议让 Jupyter 读取项目本地 kernel：

```powershell
$env:JUPYTER_PATH = 'C:\GoogleDrive\TP\.jupyter'
```

然后在 Jupyter 中选择 `TP Production Python`。用 `nbclient` 或脚本执行 notebook 时，也应使用 `kernel_name='tp-prod'`。

## 项目路径规则

环境内的 `tp_project_paths.pth` 会把下列目录加入 Python 搜索路径：

```text
C:\GoogleDrive\TP
C:\GoogleDrive\TP\01_tp_core
C:\GoogleDrive\TP\02_pipelines
C:\GoogleDrive\TP\03_technical_analysis
C:\GoogleDrive\TP\03_ml_enhanced
C:\GoogleDrive\TP\06_optimiser
C:\GoogleDrive\TP\07_backtest_code
C:\GoogleDrive\TP\07_backtest_code\src
C:\GoogleDrive\TP\08_presentation_layer
```

因此新代码应优先使用标准导入，例如：

```python
from tp_core.io import read_screen_aggregate, read_returns
```

## 依赖说明

- `pandas`、`numpy`、`pyarrow`、`scipy`、`sklearn`、`xgboost`、`shap`、`numba`、`nbclient`、`ipykernel` 等由 Anaconda base 提供，当前通过 `.venv_tp` 可见。
- `fastapi`、`uvicorn` 已安装在 `.venv_tp` 中，用于 `presentation_layer` 的统一公司分析 API 入口。
- `xbbg` 已安装在 `.venv_tp` 中；导入可用，但真实 Bloomberg 数据拉取仍依赖本机 Bloomberg Terminal/API 会话。
- `pandas_ta` 当前使用 `03_technical_analysis/pandas_ta.py` 的本地兼容层，覆盖现有 notebook 需要的指标。历史 tar 包因为缺少离线 build dependency `hatchling`，没有作为正式 pip 包安装。

## 验收记录

当前环境已经完成一次 kernel smoke test，验证了 `.venv_tp`、`tp-prod` kernel、项目路径和核心依赖导入。

最新执行记录位于：

```text
C:\GoogleDrive\TP\10_pipeline_runs\notebook_execution\20260630_065823\manifest.json
```

后续若更新环境，应重新运行：

```powershell
C:\GoogleDrive\TP\.venv_tp\Scripts\python.exe -m pytest 06_optimiser/test_optimizer.py 07_backtest_code/tests/test_security_nav_engine.py 08_presentation_layer/legacy_apps/web_app_des_companies/tests/test_region_bucket.py 08_presentation_layer/legacy_apps/web_app_des_companies/tests/test_filters.py 08_presentation_layer/legacy_apps/web_app_des_companies/tests/test_markdown_format.py
```

并至少执行一个 `tp-prod` kernel smoke notebook。

## 维护原则

- 不再依赖系统默认 `python`；当前机器上的默认 `python` 可能指向其他版本。
- 新增依赖优先安装到 `.venv_tp`，不要直接污染系统 Python。
- 如果依赖很大且 Anaconda base 已有稳定版本，可以继续通过 `--system-site-packages` 复用，但必须在本文档说明。
- 生产 notebook 的 kernel 应逐步切到 `tp-prod`，避免在不同 notebook 中混用环境。
- 如果未来需要完全隔离环境，可以新建不带 `--system-site-packages` 的 `.venv_tp_strict`，但需要重新安装科学计算依赖，成本更高。



