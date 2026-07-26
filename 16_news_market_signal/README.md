# 16_news_market_signal

四市场历史新闻数据库与新闻信号研究子系统。覆盖：

- `US`：S&P 500 point-in-time 成分
- `EU`：STOXX Europe 600 point-in-time 成分
- `JP`：NIKKEI point-in-time 成分
- `CN_HK`：中国/香港上市地且属于 MSCI EM 或 MSCI World

历史目标区间为 2007-01-01 至今。研究通过前，本项目不会写入 `artifacts/signals`、候选池、组合或仪表盘。

## 数据层

- `source_events`：事件、可用时间、来源、主题、情绪、重要度、新颖度、行业与许可元数据；不保存 Bloomberg 或其他受限来源全文。
- `daily_market_state`：交易日 × 市场，包含结构化特征和 3–7 个核心事件的确定性中文短摘要。
- `daily_sector_state`：交易日 × 市场 × ICB19 行业。
- `market_labels` / `sector_labels`：完全来自 TP canonical screen/returns 的点时点未来收益、波动与回撤标签。
- `news_signal_panel`：市场信号明确输出 `forecast_bp`、`position`（-1/0/+1）和保持预测方向的因果标准化 `signal_strength`；行业信号继续使用 `sector_score`。

首次真实指数权重之前的 US/EU/JP 月份使用明确标记的市值代理池；季度权重之间的月份只沿用最近一次已知真实快照，并标记 `universe_is_stale` 和 `weight_snapshot_date`。所有后续报告必须同时给出剔除代理期结果。GDELT 1.0 只有日级发布时间时，`available_at_utc` 自动滞后一整天。

`daily_market_state` 的全交易日骨架不等于新闻源已回填。`ingestion_covered=true` 才表示对应交易日已有完整归档；已覆盖但无事件是合法安静日，未覆盖日禁止进入训练。`quality_score` 同时反映归档覆盖与来源广度。

`curated/official_events.csv` 只保存可审计的一手机构元数据补充。例如 GDELT 1.0 没有识别 Lehman Brothers 实体时，使用 SEC 官方声明补足压力日；仍不保存网页全文。

## 命令

```powershell
# 1. 只生成按月、按市场的 GDELT BigQuery 查询和断点清单（不联网执行）
python C:\GoogleDrive\TP\16_news_market_signal\run.py ingest `
  --start 2007-01-01 --end 2026-07-12 --markets US EU JP CN_HK

# 2. 安装可选依赖后执行 BigQuery；已有分片自动跳过
pip install -e "C:\GoogleDrive\TP[news]"
python C:\GoogleDrive\TP\16_news_market_signal\run.py ingest `
  --project YOUR_GCP_PROJECT --resume

# 无 Google Cloud 凭据时，直接流式处理官方 GDELT 1.0 历史归档
python C:\GoogleDrive\TP\16_news_market_signal\run.py ingest `
  --direct-download --start 2007-01-01 --end 2026-07-12 --resume --max-files 100

# 3. 构建四市场点时点价格标签
python C:\GoogleDrive\TP\16_news_market_signal\run.py build-labels

# 4. 构建每日新闻状态；需要 source_events 分区和 market_labels
python C:\GoogleDrive\TP\16_news_market_signal\run.py build-daily

# 日归档分批下载后，只合并本批新增覆盖日并重算滚动特征
python C:\GoogleDrive\TP\16_news_market_signal\run.py build-daily `
  --incremental --start 2013-04-01 --end 2013-07-11

# 5. 扩展窗口 Ridge 筛选证据，并按月对齐现有 Country/Regime 输出
python C:\GoogleDrive\TP\16_news_market_signal\run.py backtest --compare-existing

# 现有 13 天公司新闻只做市场/行业映射审计，不写入历史事件主表
python C:\GoogleDrive\TP\16_news_market_signal\run.py audit-existing-news
```

长任务输出写入本项目 `data/`、`outputs/`、`runs/`，均由本地 `.gitignore` 排除。历史 run 目录不会被覆盖。

## 验证

```powershell
python -m pytest C:\GoogleDrive\TP\16_news_market_signal\tests -q
```

测试覆盖旧数据保守滞后、各市场收盘前 30 分钟截断、安静日与未回填日区分、增量 daily 合并、GDELT 新旧归档格式、四市场 universe 与代理标记、未来收益/回撤标签、因果标准化和行业 Top/Worst。
