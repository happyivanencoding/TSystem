# 03_technical_analysis

## 项目说明
本项目用于从 `returns.parquet` 和 `screen_aggregate.parquet` 计算技术形态与技术指标，并输出 `patterns.parquet`。

主运行入口是 `Main.py`，`Tradin_patterns.ipynb` 仅用于分步查看和本地分析，不是主运行入口。

## 本地启动
推荐使用 Python 3.12。
不支持 Python 3.14，因为 `pandas-ta` / `numba` 依赖链目前只支持 `< 3.14`。

1. 创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. 准备输入数据：

默认情况下，`Main.py` 和 notebook 应读取 TP canonical parquet；路径规则见 [`../DATA_SOURCES.md`](../DATA_SOURCES.md)。项目内旧 `data/returns.parquet` 与 `data/screen_aggregate.parquet` 已移动到 `_quarantine_20260629/legacy_data_copies/`，不再作为默认输入。
如果你要在本地运行其他数据或复现实验快照，请先用环境变量覆盖输入输出路径：

```powershell
$env:TA_RETURNS_PATH="D:\data\returns.parquet"
$env:TA_SCREEN_PATH="D:\data\screen_aggregate.parquet"
$env:TA_OUTPUT_PATH="D:\data\patterns.parquet"
```

3. 在项目根目录执行：

```powershell
python Main.py
```

运行完成后，会生成 `patterns.parquet`。

## Notebook
- `Tradin_patterns.ipynb` 适合分步查看中间结果和验证流程。
- `Pattern_backtest.ipynb` 适合对 `patterns.parquet` 做信号回测。
- notebook 默认应与 `Main.py` 使用同一套 parquet 输入。

## 数据文档
- screen/returns 的 canonical 语义以 [`../00_screen/说明文档/screen_returns_context.md`](../00_screen/说明文档/screen_returns_context.md)、[`../DATA_SOURCES.md`](../DATA_SOURCES.md) 和 [`../DATA_CONTRACT.md`](../DATA_CONTRACT.md) 为准。
- `data/screen_returns_context.md` 保留 technical_analysis 项目的扩展上下文，尤其是 `patterns.parquet` 的结构和使用注意事项。
- `docs/pattern_backtest_score_guide.md` 说明了 `Pattern_backtest.ipynb` 中 `score_columns`、`score_weights`、`higher_is_better` 的含义，以及当前可用的常见 score 选项。

## 统一信号表导出

technical_analysis 的标准信号导出入口：

```powershell
python C:\GoogleDrive\TP\03_technical_analysis\export_technical_signals.py
```

默认读取 `output/patterns.parquet` 的最新日期，并输出 `C:\GoogleDrive\TP\04_signals\technical_signals.parquet`。该输出使用 `tp_core.signals` 的统一 schema，不再让技术信号自带一套独立回测核心。


## 迁移记录

本项目已从 `C:\GoogleDrive\TP\技术分析和深度学习\技术分析_V2` 提升到根目录 `C:\GoogleDrive\TP\03_technical_analysis`。迁移证据见 `relocation_manifest.json`。旧父目录已移除，后续新引用统一使用 `03_technical_analysis/`。
