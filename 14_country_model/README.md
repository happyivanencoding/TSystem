# 14_country_model

## 定位

`14_country_model` 是国家/地区层面的打分模型。它把 `modele_pays.xlsb` 中的国家模型复刻为 Python 产物，并导出统一信号表，供 `04_signals/`、候选池、组合风险预算和展示层后续消费。

当前模型不修改 `00_screen/` canonical 数据，只读取本项目下的 Excel 工作簿或已生成的 parquet 数据库，并在本项目和 `04_signals/` 下写派生产物。

## 数据来源

| 输入 | 说明 |
| --- | --- |
| `modele_pays.xlsb` | 原始国家模型工作簿，默认读取 `GLOBAL_MODEL` 以及单国家因子 sheet |
| `data/country_model_database.parquet` | 从 `GLOBAL_MODEL` 抽取后的国家模型数据库 |

重建数据库需要 Windows Excel COM 支持；日常 smoke check 可用 `--use-existing-database` 或直接读取 parquet，避免重新打开 Excel。

## 模型口径

主模型覆盖 5 个国家/区域标签：

- `UK`
- `US`
- `EM`
- `Japan`
- `EMU`

综合分使用以下权重：

| 因子 | 权重 |
| --- | ---: |
| `margin_score` | 20% |
| `profitability_score` | 20% |
| `growth_score` | 15% |
| `value_score` | 20% |
| `momentum_score` | 25% |

模型版本：`country_model_excel_replica_v1`。

## 运行入口

完整刷新：

```powershell
python C:\GoogleDrive\TP\14_country_model\src\country_model.py
```

使用已生成数据库，避免重新抽取 Excel：

```powershell
python C:\GoogleDrive\TP\14_country_model\src\country_model.py --use-existing-database
```

通过统一信号导出入口只刷新国家模型信号：

```powershell
python -m 02_pipelines.export_signals --skip-ml --skip-technical --skip-regime
```

## 输出

| 输出 | 说明 |
| --- | --- |
| `data/country_model_database.parquet` | Excel 复刻后的国家模型数据库 |
| `outputs/country_model_panel.parquet` | 全历史国家模型面板、综合分、排名和推荐 |
| `outputs/country_model_latest.csv` | 最新一期国家模型摘要 |
| `outputs/country_model_single_country_scores.parquet` | 单国家细分因子分数 |
| `outputs/country_model_single_country_latest.csv` | 最新一期单国家摘要 |
| `outputs/country_model_validation.json` | 与 Excel 分数/排名的对账和信号 schema 校验 |
| `../04_signals/country_model_signals.parquet` | 标准统一信号表输出 |

## 统一信号表

默认信号输出为 `04_signals/country_model_signals.parquet`：

| 字段 | 当前值 |
| --- | --- |
| `signal_family` | `country_model` |
| `signal_name` | `country_global_score` |
| `scope` | `region` |
| `direction` | `higher_is_better` |
| `source_project` | `14_country_model` |
| `horizon` | `1M` |

保留的解释字段包括 `country_label`、`rank`、`recommendation`、`rank_delta`、五个因子分、Excel 原始分数/排名和 `score_diff_vs_excel`。

## 健康检查

控制塔 smoke check：

```powershell
python -m presentation_layer.cli system-checks --project 14_country_model
```

该检查读取已有 `country_model_database.parquet`，构建临时信号表到 `.tmp_dashboard_work/system_checks/outputs/`，不重建 Excel 数据库，也不覆盖生产信号。

## 维护状态

活跃研究/信号项目。当前已接入 `02_pipelines.export_signals` 和 `08_presentation_layer.apps.system_registry`。后续若要进入组合决策，应在候选池或优化器层明确国家分数如何转化为国家/区域主动权重或风险预算调整。
