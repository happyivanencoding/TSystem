> 当前入口：本文件保留 2026-06-29 的现场审计细节和处理笔记，不再作为日常运行手册。当前运行手册见 `00_screen/README.md`，全局数据入口见 `11_docs/DATA_AND_PRODUCTION.md`，最新验证见 `00_screen/production_inputs/manifests/workflow_switch_verification_latest.md`。

# screen_aggregate 月度更新管线历史审计

审查日期: 2026-06-29  
主入口: `C:\GoogleDrive\TP\00_screen\monthly_prod.ipynb`  
代码入口: `C:\GoogleDrive\TP\00_screen\monthly_update.py`, `C:\GoogleDrive\TP\00_screen\screen_func.py`  
当前生产输入: `00_screen/production_inputs/incoming/202606/screen|returns|ciq`

## 0. 2026-06-29 P0 落地状态

四个 P0 建议已经落到代码入口，并已完成一次 202606 真实月更验证；重复运行不会追加重复日期或重复月份，非目标月份未被误删。

| P0 项 | 当前状态 | 代码位置 |
| --- | --- | --- |
| CIQ merge 进入主管线 | `run_monthly_update()` 默认执行 CIQ 合并；可用 `--ciq-dir` 指定文件/目录，用 `--skip-ciq` 显式跳过 | `00_screen/monthly_update.py::merge_ciq_history`, `run_monthly_update` |
| 备份文件名加时间戳和操作名 | `create_backup()` 输出 `screen_aggregate_YYYYMMDD_HHMMSS_<operation>.parquet`；月更和 CIQ 各自备份 | `00_screen/screen_func.py::create_backup` |
| 月更后自动 QA | 每次运行写 `qa/monthly_update_YYYYMMDD_HHMMSS_<month>.json`，可用 `--qa-report` 覆盖路径 | `00_screen/monthly_update.py::build_monthly_qa_report` |
| VaR/Beta 风险列落库核对 | `merge_risk_data()` 会预创建 6 个风险字段；QA 记录每列 latest/total 非空数并对缺失或全空报警 | `00_screen/screen_func.py::RISK_COLUMN_MAPPING`, `merge_risk_data` |



## 0.1 2026-06-29 P1/P2 工程化落地状态

| 项 | 当前状态 | 代码/文档位置 |
| --- | --- | --- |
| P1 抽取共享 `tp_core` 包 | 已新增数据契约、统一 IO、returns 审计、PtfBuilder 单一入口 | `tp_core/data_contract.py`, `tp_core/io.py`, `tp_core/returns_audit.py`, `tp_core/backtesting.py` |
| P1 固化数据契约 | 已定义主键、日期、SEDOL join、weight 空值语义、字段族、deprecated 字段 | `DATA_CONTRACT.md`, `tp_core.data_contract` |
| P1 统一依赖和入口 | 已新增 `pyproject.toml`，声明基础/screen/backtest/web/ml 依赖和 `tp-returns-audit` 命令 | `pyproject.toml` |
| P2 清理 pkl/旧引用 | 活跃 `ML/Config` 和 `ML/Codes` 已转 parquet；archive/original 仍保留历史 pickle 参考 | `ML/Config/*`, `ML/Codes/*`, `DATA_SOURCES.md` |
| P2 returns 异常收益审计 | 已新增可 CLI 化审计，默认标记极端日收益 | `python -m tp_core.returns_audit` |
| P2 分区域 Beta benchmark | 已新增 `Beta vs Regional Benchmark (Rolling ewma 250D)`，同时保留旧 SXXP beta | `00_screen/Technicals.py`, `00_screen/screen_func.py` |
## 1. 当前实测状态

| 对象 | 当前状态 |
| --- | --- |
| `screen_aggregate.parquet` | 1,067.01 MB；3,443,235 行；277 个 schema 字段；日期 1999-12-31 至 2026-05-31；318 个 月末；唯一 ISIN 12,348；`(ISIN, Date)` 重复 0 |
| `last_screen.parquet` | 10,983 行；单一日期 2026-05-31；主键重复 0 |
| `screen_aggregate_5Y.parquet` | 257.32 MB；653,632 行；277 个 schema 字段 |
| `returns.parquet` | 272.38 MB；5,496 x 11,890；日期 2005-01-03 至 2026-06-11；日期重复 0 |
| `returns_202606` | 27 x 11,890；日期 2026-05-06 至 2026-06-11；已完整合入主 returns，重叠日期/列差异单元格 0 |
| `20260529.xlsx` | 11,189 行 x 175 数据列；ISIN 唯一值 10,988；重复 ISIN 行 200；原始日期 `5/29/2026` |
| CIQ `download (6)+(7)` | 合并后 230,326 行 x 84 列；日期 2009-01-31 至 2019-12-31；5,021 个 ISIN；无重复 `(ISIN, Date)` |

最新月质量切片:

| 检查 | 结果 |
| --- | --- |
| 最新月日期 | 2026-05-31 |
| 最新月行数 | 10,983 |
| 有效 SEDOL 行数 | 10,960 |
| 有效 SEDOL 在 `returns.columns` 缺失 | 0 |
| `Weight in MSCI WORLD/SP500/STOXX EUROPE 600/MSCI EM` 最新月权重和 | 均为 1.0 |
| `Weight in Univ ML EU/US/OTHER` 最新月权重和 | 均为 1.0 |
| `Volatilite Rolling ewma 250D` 最新月非空 | 10,656 / 10,983 |
| `VaR 1% Rolling 250D` 最新月非空 | 10,656 / 10,983 |
| `Maximum Drawdown Rolling 250D` 最新月非空 | 10,656 / 10,983 |
| `Beta vs SXXP (Rolling ewma 250D)` 最新月非空 | 10,656 / 10,983 |
| `Beta vs Regional Benchmark (Rolling ewma 250D)` 最新月非空 | 10,656 / 10,983 |
| `Perf5D/1M/3M/6M` 最新月非空 | 10,960 / 10,917 / 10,906 / 10,821 |

## 2. 主管线总览

`monthly_prod.ipynb` 的正式入口先设置 `update_mode`, `screen_excel`, `returns_delta`，然后调用:

```python
result = run_monthly_update(
    update_mode=update_mode,
    screen_excel=screen_excel,
    returns_delta=returns_delta,
)
```

`run_monthly_update()` 现在把月度、returns、风险/Perf、CIQ 与 QA 收敛到同一入口。核心步骤:

1. 解析默认路径和 `update_mode`。
2. 读取 `returns.parquet` 和 returns 增量。
3. `merge_returns_history()` 合并日收益。
4. `read_new_FS_screen()` 读取并去重月度 Excel。
5. `FactSet_ICB_Mapping()` 做行业映射和日期月末化。
6. `add_score_multifacteur()` 生成 `Multi Avg Percentile`。
7. `rebalance_weight_sum_to_1()` 把指数权重从 sum 约 100 归一到 1。
8. `add_univ_ml()` 生成 EU/US/OTHER ML universe 权重。
9. `normalize_benchmark_market_value_column()` 统一市值列。
11. 合并历史主表、计算风险指标、计算 Perf。
12. 写回 `returns.parquet`, `last_screen.parquet`, `screen_aggregate.parquet`, `screen_aggregate_5Y.parquet` 和备份。

CIQ 融合已迁入 `run_monthly_update()`；notebook 后面的历史手动 cell 只作为旧逻辑参考，不应再作为生产步骤。

## 3. 每一步关键处理细节

### 3.1 输入路径和自动发现

`build_default_paths()` 以 `00_screen/` 为 base，固定查找:

- `monthly/*.xlsx`
- `returns/` 下最新文件，后缀允许 `''` 或 `.parquet`，排除 `returns.pkl`
- `screen_aggregate.parquet`
- `last_screen.parquet`
- `returns.parquet`
- `Transco_FactSet_ICB.xlsx`

风险点: 自动发现按最后修改时间，不按文件名月份。建议生产运行显式传入 `screen_excel` 和 `returns_delta`。

### 3.2 Returns 增量合并

函数: `ScreenProcessor.merge_returns_history()`

处理逻辑:

```python
history.index = pd.to_datetime(history.index)
delta.index = pd.to_datetime(delta.index)
merged = pd.concat([history, delta], axis=0, sort=False)
merged = merged.sort_index()
merged = merged.groupby(level=0, sort=True).last()
```

含义:

- 同一交易日重复时保留最后一版。
- 如果 delta 修正历史日期，delta 会覆盖历史同日值。
- 当前 `returns_202606` 与主 returns 的 27 个重叠日期已经完全一致。

### 3.3 Excel 读取

函数: `ScreenProcessor.read_new_FS_screen()`

固定读取参数:

```python
pd.read_excel(
    screen_excel,
    header=0,
    index_col=4,
    skiprows=[0, 1, 2, 3, 5],
    na_values=["@NA", "#N/A"],
)
```

当前 `20260529.xlsx`:

- 读入后 11,189 行 x 175 列。
- `index_col=4` 是 ISIN。
- 原始日期是字符串 `5/29/2026`。
- 重复 ISIN 行 200。
- ISIN 唯一值 10,988。

### 3.4 ISIN 去重和主行选择

函数: `consolidate_duplicate_isin_with_tracking()`

规则:

- 按 `ISIN` groupby。
- 如果单行，直接保留。
- 如果多行，用 `Company Main Exchange` 和 `Exchange Country Name` 的硬编码映射找主上市行。
- 找不到主行时，取第一行。
- 对 `columns_to_fill` 列表中的字段，如果主行为空，则用副行的非空值补齐。
- `changes_log` 记录每个 ISIN 哪些列被副行填充。

当前结果理解:

- 11,189 原始行通过去重变成约 10,988 个唯一 ISIN。
- 行业映射阶段会过滤 `FactSet Ind` 为空的证券，最终 latest snapshot 为 10,983 行。
- 当前 Excel 中有 5 个非空 ISIN 的 `FactSet Ind` 全为空: `US9778521024`, `US71922G3083`, `BRLATMBDR001`, `TH102705R8R5`, `PLSOFTB00156`。

注意: `read_new_FS_screen()` 中 `consolidated_df.loc[consolidated_df.index.notna()]` 实际检查的是重置后的数值 index，不是 ISIN 列。如果未来出现 `ISIN` 为空但 `FactSet Ind` 不为空的行，可能漏过滤。建议改成显式 `df = consolidated_df[consolidated_df['ISIN'].notna()]`。

### 3.5 ICB 映射和日期规范化

函数: `FactSet_ICB_Mapping()`

处理顺序:

1. 过滤 `FactSet Ind` 为空的行。
2. 保留原始 `ICB11 Industry` 和 `ICB20 Supersector`。
3. 读取 `Transco_FactSet_ICB.xlsx` 的 `Mapping` sheet。
4. 验证 FactSet Ind 和 ICB supersector 都在映射表中。
5. `FactSet Ind -> ICB19`。
6. `ICB19 -> ICB11`。
7. 日期转换为月末:

```python
df['Date'] = pd.to_datetime(df['Date'])
df['Date'] = df['Date'] + pd.offsets.MonthBegin(1)
df['Date'] = df['Date'] + pd.offsets.MonthEnd(-1)
```

当前 `5/29/2026` 被标准化为 `2026-05-31`。

风险点: 新的 FactSet Ind 或 ICB 名称不在映射表时直接 `ValueError` 中断。这对生产安全是好的，但需要在报错中输出可操作的缺失清单，并把 mapping 更新作为月更前置检查。

### 3.6 Multi factor 分数

函数: `add_score_multifacteur()`

计算:

```python
Multi Avg Percentile = mean(
    Growth Avg Percentile,
    LowVol Avg Percentile,
    Mom Avg Percentile,
    Quality Avg Percentile,
    Value Avg Percentile,
)
```

然后在 `(Date, Benchmark ICB Supersector, Exchange Country Region)` 内做 `rank(pct=True) * 10`。

注意: Dividend 和 Size 不参与 `Multi Avg Percentile`。

### 3.7 权重归一化

函数: `rebalance_weight_sum_to_1()`

把 18 个指数权重列按 `Date` groupby 后除以当月总和。当前最新月主要权重列 sum 均为 1.0。

注意:

- 原始 FactSet 权重常是百分比口径，sum 约 100。
- 下游判断成分应使用 `Weight in XXX.fillna(0) > 0`。
- 权重列为空通常表示非成分股，不是坏数据。

### 3.8 ML Universe

函数: `add_univ_ml()`

规则:

- EU: 优先 `Weight in STOXX EUROPE 600`；否则用 `MSCI WORLD` 中 `Exchange Country Region == 'West Europe'` 的股票。
- US: 优先 `Weight in SP500`；否则用 `MSCI WORLD` 中 `Exchange Country Name == 'UNITED STATES'` 的股票。
- OTHER: `MSCI WORLD` 中非 US、非 West Europe。
- 每个 universe 按 `Date` 独立归一化到 sum=1。

notebook Cell 8 会对全历史重算并回写这三列，带时间戳备份。

### 3.9 已移除的 MSCI EM 国家分组派生逻辑

2026-06-29 已按最新决策从代码和生产流程中移除该派生逻辑。后续月更不再生成这些字段，主表保存时会主动丢弃历史遗留的分组派生列。

### 3.10 月度切片合并

函数: `merge_monthly_snapshot()`

规则:

- 确保 old/new 都有 `ISIN` 列。
- 找出 new_base 中的目标月份。
- 从历史主表删除同月份旧记录。
- concat old + new。
- 按 `Date, ISIN` 排序并对 `(ISIN, Date)` 去重，保留最后一条。
- 写回前校验主键唯一。

这使得重复跑同一月会覆盖该月，而不是追加重复行。

### 3.11 风险指标

函数: `calculate_risk_metrics()` + `prepare_risk_data_for_merge()` + `merge_risk_data()`

当前代码计算字典包含:

- `volatility`: `Volatilite Rolling ewma 250D`
- `var`: `VaR 1% Rolling 250D`
- `max_drawdown`: `Maximum Drawdown Rolling 250D`
- `beta`: `Beta vs SXXP (Rolling ewma 250D)`
- `beta_up`: `Beta Up vs SXXP (252D)`
- `beta_down`: `Beta Down vs SXXP (252D)`

技术细节:

- `add_bench_return()` 用 STOXX Europe 600 权重和个股 returns 构造 `SXXP Bench`。
- EWMA Vol 只用 returns 最后 280 个交易日，rolling 252，decay 0.98，年化乘 `sqrt(252)`。
- Max Drawdown 用全历史 returns 的 252 日滚动窗口。
- Beta 用 `SXXP Bench` 做单一 benchmark。
- `prepare_risk_data_for_merge()` 会取 `<= target month-end` 的最近可用日，并把日期替换成目标月末。

当前发现:

- 主表实际只存在 `Volatilite Rolling ewma 250D` 和 `Maximum Drawdown Rolling 250D`。
- VaR/Beta 代码路径需要专门验证，不能默认认为已落库。

### 3.12 Perf 字段

函数: `_build_perf_frame()` + `add_perf()`

窗口:

- `Perf5D`: 5 个交易日
- `Perf1M`: 20 个交易日
- `Perf3M`: 60 个交易日
- `Perf6M`: 120 个交易日

算法:

```python
nav = (1 + returns).cumprod()
current_nav = nav.reindex(target_month_end, method='ffill')
lagged_nav = nav.shift(lag).reindex(target_month_end, method='ffill')
perf = current_nav / lagged_nav - 1
```

当前只对目标月份增量计算，不重算全历史。如果历史 returns 被修正，老月份 Perf 不会自动刷新。

### 3.13 保存和备份

主管线:

- `create_backup()` 写入 `backups/screen_aggregate/screen_aggregate_YYYYMMDD_HHMMSS_<operation>.parquet`。
- `save_results()` 写入 `screen_aggregate.parquet`。
- 同时生成 `screen_aggregate_5Y.parquet`。
- `returns.parquet` 在 `update_returns=True` 时覆写。
- `last_screen.parquet` 在月度 Excel 处理后写出。

风险点:

- `create_backup()` 只到日期粒度，同一天多跑会覆盖。
- 旧 CIQ 手动 cell 固定备份到 `bk/screen_aggregate.parquet`，会覆盖；新主流程改为 `backup_00_screen/screen_aggregate_YYYYMMDD_HHMMSS_before_ciq_merge.parquet`。

## 4. Notebook 手动段落

### Cell 7: 缺失值审核

当前 notebook 已经使用 `result['month_date']` 推断 latest date，不是旧版文档中的裸 `result` bug。它会按四个口径展示最新月和历史缺失率差异:

- 全量公司
- MSCI WORLD
- SP500
- STOXX EUROPE 600

限制: 仍依赖前面 Cell 4 已经生成 `result`。如果 kernel 重启后只跑 Cell 7，会失败。

### Cell 8: 全历史 Univ ML 回写

- 读取全量 `screen_aggregate.parquet`。
- 备份到 `backup_00_screen/screen_aggregate_before_rewrite_univ_ml_YYYYMMDD_HHMMSS.parquet`。
- 调用 `add_univ_ml()`。
- 写回主表和 `screen_aggregate_5Y.parquet`。
- 同步刷新 `last_screen.parquet`。
- 验证最近 12 个月 EU/US/OTHER 权重和。

### Cell 9: 已移除的 MSCI EM 国家分组回写

该旧 notebook 回写步骤已删除，不再作为月更或历史修复步骤。

### Cell 10: CIQ 融合（旧手动逻辑，已由 CLI 取代）

当前逻辑:

1. 读取 `ciq/new/` 目录下所有文件，不筛选后缀。
2. concat 成一个 CIQ 表。
3. `Date = pd.to_datetime(Date) + MonthEnd(0)`。
4. `drop_duplicates(['ISIN', 'Date'], keep='last')`。
5. 旧逻辑复制主表到 `bk/screen_aggregate.parquet`；新主流程改用时间戳 CIQ 备份。
6. `screen.reset_index()` 后和 CIQ 做 left merge on `['ISIN', 'Date']`。
7. 对同名列用 `screen_col.combine_first(ciq_col_y)`，即只填补 screen 空值。
8. `m.set_index('ISIN').to_parquet(screen_path)`。

当前 CIQ 文件的 82 个非键字段都已经存在于 screen schema 中，没有新增 CIQ-only 字段。

限制:

- 已迁入 `run_monthly_update()`，默认读取 `ciq/new/`；也可通过 `--ciq-dir` 指定单个 parquet 或目录。
- 主流程在 CIQ 后会从最终 `screen_aggregate.parquet` 刷新 `last_screen.parquet` 和 `screen_aggregate_5Y.parquet`。
- CIQ 前备份使用 `backup_00_screen/screen_aggregate_YYYYMMDD_HHMMSS_before_ciq_merge.parquet`，不再覆盖固定文件。
- `parts = [pd.read_parquet(f) for f in ciq_new_dir.iterdir() if f.is_file()]` 会读取目录下所有文件，若混入非 parquet 会失败。

## 5. 发现的问题

| 优先级 | 问题 | 影响 | 建议 |
| --- | --- | --- | --- |
| P0 | CIQ 融合不在主管线 | 已修复：`run_monthly_update()` 默认执行 CIQ merge | 保留 `--skip-ciq` 作为显式例外 |
| P0 | 主管线备份同日覆盖，CIQ 备份固定名覆盖 | 已修复：备份名包含 `YYYYMMDD_HHMMSS` 和操作名 | 月更/CIQ 各有独立备份 |
| P0 | VaR/Beta 当前未在 parquet 落库 | 已加防护：风险列会被预创建，QA 记录非空率 | 下次真实月更后用 QA JSON 确认是否有有效值 |
| P1 | 自动选最新文件按 mtime | 容易选到临时文件或错误月份 | 生产运行显式传参，并校验 Excel 日期和文件名月份 |
| P1 | returns delta 后缀允许空字符串 | 目录中非 parquet 无后缀文件可能被误读 | 文件名白名单或 parquet magic/schema 校验 |
| P1 | `read_new_FS_screen()` 未显式过滤空 ISIN 列 | 极端情况下空 ISIN 行可进入后续 | 改成 `consolidated_df['ISIN'].notna()` |
| P1 | `check_screen_index_in_returns_columns()` 使用未定义 `sedols` | 辅助 QA 函数不可用 | 取消注释并清理字符串 `'nan'` |
| P1 | 风险 benchmark 固定 SXXP | US/OTHER Beta 解释不准确 | 按区域使用 SP500/STOXX/MSCI WORLD 或增加字段名说明 |
| P2 | Notebook 手动 cell 会全量重写 1GB 主表 | 慢且有写坏风险 | 改成 CLI 子命令，先输出 dry-run QA |
| P2 | 旧文档和 live 数据不一致 | 未来脚本/LLM 容易误判 | 定期用脚本生成 live stats 并覆盖文档 |
| P2 | 多处下游仍引用 `.pkl` | 路径混乱 | 全局迁移到 parquet 并保留兼容 shim |

## 6. 建议改造路线

### P0: 把月更变成可复现 CLI

目标命令:

```bash
python monthly_update.py \
  --update-mode both \
  --screen-excel "C:\GoogleDrive\TP\00_screen\monthly\20260529.xlsx" \
  --returns-delta "C:\GoogleDrive\TP\00_screen\returns\returns_202606" \
  --ciq-dir "C:\GoogleDrive\TP\00_screen\ciq\new" \
  --qa-report "C:\GoogleDrive\TP\00_screen\monthly\qa_20260531.json"
```

建议新增函数:

- `merge_ciq_history(screen_path, ciq_dir, processor=...)`
- `validate_monthly_inputs(screen_excel, returns_delta)`
- `build_monthly_qa_report(screen_df, returns_df, latest_date, ...)`
- `ScreenProcessor.create_backup(path, operation)`

### P0: 月更后 QA 固化

每次运行至少输出:

- 主表行数、列数、日期范围、latest rows。
- `(ISIN, Date)` 重复数。
- latest 有效 SEDOL 在 returns 中缺失数。
- 关键权重列 sum 是否为 1。
- ML universe 权重 sum 是否为 1。
- EM cluster 权重 sum 是否为 1。
- 风险/Perf 字段 latest 非空率。
- CIQ merge 覆盖行数和字段数。
- 本次备份路径清单。

### P1: 数据契约

建议建立 `00_screen/说明文档/data_contract.md` 或在本文件维护固定契约:

- 主键: `(ISIN, Date)`。
- `Date`: 月末日期。
- `returns.index`: 交易日。
- `screen.Company SEDOL -> returns.columns`。
- 权重列空值: 通常表示非成分股。
- ICB 列名保留首尾空格: ` Benchmark ICB Industry `, ` Benchmark ICB Supersector `。
- `ISIN` 在 parquet 中常作为 index，读后需要 `reset_index()`。

## 7. 下次月更 checklist

### 运行前

1. 确认 Excel 文件路径和评价日期，例如 `monthly/20260630.xlsx`。
2. 确认 returns 增量文件路径，例如 `returns/returns_202607`。
3. 打开 Excel 后确认原始 `Date` 只有一个值。
4. 确认 `Transco_FactSet_ICB.xlsx` 已覆盖新 `FactSet Ind`。
5. 确认 `ciq/new/` 只放本次需要读取的 parquet 文件。
6. 手动复制一份主表或确认自动备份路径有足够空间。

### 运行

1. 在 `monthly_prod.ipynb` 显式设置 `screen_excel` 和 `returns_delta`。
2. 执行 `run_monthly_update(update_mode='both', ...)`。
3. 记录 `result` 中的 `month_date`, `new_rows`, `total_rows`, `returns_last_date`, `backup_path`。
4. 执行缺失值审核 cell。
5. 如有全历史 universe/EM 逻辑变化，再执行 Cell 8/9；否则不需要每月都跑。
6. 确认 `result["ciq_result"]` 非空，或确认本次确实使用了 `--skip-ciq`。

### 运行后

1. 验证 `screen_aggregate.parquet` 最新日期等于目标月末。
2. 验证 `last_screen.parquet` 只有目标月末。
3. 验证主键无重复。
4. 验证 latest 有效 SEDOL 在 returns 中缺失为 0。
5. 验证核心权重列 sum 为 1。
6. 验证 Perf 和风险字段非空率没有异常跳变。
7. 确认 `screen_aggregate_5Y.parquet` 已刷新。
8. 确认备份文件不被覆盖，并记录 `backup_path`、`ciq_result.backup_path` 与 `qa_report_path`。

## 8. 快速验证代码片段

```python
from pathlib import Path
import pandas as pd

base = Path(r"C:\GoogleDrive\TP\00_screen")
screen = pd.read_parquet(base / "screen_aggregate.parquet")
if "ISIN" not in screen.columns and screen.index.name == "ISIN":
    screen = screen.reset_index()
screen["Date"] = pd.to_datetime(screen["Date"])
latest = screen["Date"].max()
last = screen[screen["Date"] == latest].copy()

print("latest", latest.date(), "rows", len(last))
print("duplicate keys", screen.duplicated(["ISIN", "Date"]).sum())

returns = pd.read_parquet(base / "returns.parquet")
ret_cols = set(map(str, returns.columns))
sedol = last["Company SEDOL"]
valid = sedol.notna() & ~sedol.astype(str).str.lower().isin(["nan", "none", ""])
missing = sorted(set(sedol[valid].astype(str)) - ret_cols)
print("missing sedol in returns", len(missing))

weight_cols = [
    "Weight in MSCI WORLD",
    "Weight in SP500",
    "Weight in STOXX EUROPE 600",
    "Weight in MSCI EM",
    "Weight in Univ ML EU",
    "Weight in Univ ML US",
    "Weight in Univ ML OTHER",
]
print(last[weight_cols].sum(min_count=1).round(8))
```

## 9. 结论

当前 2026-05 月更结果在主键、权重归一、returns 合入和 SEDOL 覆盖上是健康的。本次已把 CIQ merge、时间戳备份和月更 QA 固化进 CLI；剩余结构性风险主要是全历史 universe 回写仍偏 notebook 化，以及下次真实月更后需要用 QA JSON 确认 VaR/Beta/Regional Beta 的有效非空率。
