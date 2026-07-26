# ML_Enhanced

## 定位

`03_ml_enhanced` 是当前主要的 ML 研究和生产候选目录，用于分区域训练、预测、监控和组合输出。

## 数据来源

应统一读取 TP canonical 数据：

- `C:\GoogleDrive\TP\00_screen\screen_aggregate.parquet`
- `C:\GoogleDrive\TP\00_screen\returns.parquet`

配置文件已逐步迁移到统一数据源规则。新脚本不要再依赖项目内旧数据副本，路径规则见 [`../DATA_SOURCES.md`](../DATA_SOURCES.md)。

旧的 `Input_files/screen_aggregate.parquet` 与 `Input_files/returns.parquet` 已移动到 `_quarantine_20260629/legacy_data_copies/`，只作为可回滚历史快照保留，不再作为默认输入。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `../src/tp_models/ml/` | 规范 ML 生产实现 |
| `Input_files/` | 项目派生输入；不存放 canonical screen/returns 副本 |
| `Output_files/` | 模型输出和中间结果 |
| `Portfolio_BT/` | 组合回测相关产物 |
| `SUIVI/` | 监控和跟踪材料 |
| `Monitoring.ipynb` | 当前监控 notebook；由原 `Monitoring - NEW.ipynb` 合并替换 |
| `../11_docs/archive/documentation_cleanup_20260726/ml_enhanced/` | 已归档的 2025 优化计划 |

## 运行入口

当前研究训练仍以 notebook 为主；稳定生产动作只通过已安装包入口：

```powershell
python -m tp_models.ml.cli inspect
python -m tp_models.ml.cli export-signals
```

默认输出 `C:\GoogleDrive\TP\artifacts/signals\ml_signals.parquet`。导出命令读取 canonical `screen_aggregate.parquet` 中最新有 `Score ML` 覆盖的日期，并导出 `signal_family=ML`、`signal_name=score_ml` 的标准信号表。

缺失月份的 Score ML 生产会写回 canonical screen，必须显式执行：

```powershell
python -m tp_models.ml.cli produce-score-ml --date YYYY-MM-DD
python -m tp_pipelines.refresh_ml --inspect-only
python -m tp_pipelines.refresh_ml --date YYYY-MM-DD
```

`tp_pipelines.refresh_ml` 会写 pipeline manifest；`run_all` 只有传入 `--refresh-ml` 时才会运行该步骤。

## 维护状态

主要 ML 版本。已固定统一信号表导出、Score ML 覆盖检查和缺失月份生产 CLI；后续继续把 notebook 中的训练/监控研究流程拆成更细的无写库命令。

旧的 `test_bench.ipynb` 已移动到 `_quarantine_20260629/legacy_notebooks/`，因为其中包含会写回主库的实验单元。旧 ptf 版 `Monitoring.ipynb` 已移动为 `_quarantine_20260629/legacy_notebooks/Monitoring_old_ptf_based.ipynb`，原 `Monitoring - NEW.ipynb` 已合并为当前 `Monitoring.ipynb`。`参考文件_EM/` 已移动到 `_quarantine_20260629/em_reference_legacy/`，只保留历史参考。
