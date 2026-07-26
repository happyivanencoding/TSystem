# Technical Analysis

## 定位

从 TP Canonical returns 和 Screen 计算证券技术形态、指标及可交易 Technical 信号。活跃实现位于 `src/tp_models/technical/` 和 `src/tp_models/technical_signals.py`；本目录只保存 notebook、方法文档、模型资源和专项输出。

## 输入

- `00_screen/returns.parquet`
- `00_screen/screen_aggregate.parquet`
- 当期 PIT universe 与证券标识映射

项目私有旧数据副本只在 quarantine 中保留，不是默认输入。统一规则见根目录 `DATA_SOURCES.md`、`DATA_CONTRACT.md`。

## 运行入口

生成完整 patterns 面板：

```powershell
python -m tp_models.technical.Main
```

导出标准 Technical 信号：

```powershell
python -m tp_models.technical_signals
```

生产流水线应使用：

```powershell
.\.venv_tp\Scripts\tp-pipeline-export-signals.exe
```

不得执行 `03_technical_analysis` 资源目录中的旧 Python 文件。

## 时间口径

- Pattern 标签日期与可交易日期分开保存。
- Weekly pattern 只有在完整周数据形成后才可用。
- 标准信号 `effective_date` 使用可用日；`as_of_date`、`technical_pattern_date` 保留原始标签日期。
- 最新导出日期不得超过 Canonical Screen 的已知上限。

## 输出

| 输出 | 路径 |
| --- | --- |
| 完整专项面板 | `03_technical_analysis/output/patterns.parquet` |
| 标准信号 | `artifacts/signals/technical_signals.parquet` |
| Pipeline manifest | `artifacts/pipeline_runs/manifests/export_signals/` |
| Run Card | `artifacts/pipeline_runs/experiments/` |

## Notebook 与文档

- `Tradin_patterns.ipynb`：分步查看 patterns 生成。
- `Pattern_backtest.ipynb`：Technical 信号研究回测。
- `Pattern_visual_guide.ipynb`：形态可视化说明。
- `data/screen_returns_context.md`：patterns 专项契约和 PIT 对齐。
- `docs/pattern_backtest_score_guide.md`：score、方向和权重配置。

Notebook 应导入 `tp_models`、`tp_core` 公共包，不导入资源目录脚本。

## 维护状态

活跃技术信号模型。专项 outputs 从 pytest、ruff、mypy、CRG 和 CI discovery 排除。
