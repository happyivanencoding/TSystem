# Sector qualitative report workflow

## 目标

第一版只服务 `13_sector_score_model`，每月读取 US/EU 最新
`sector_scores_latest.csv`，默认解释全部行业：US 19 个、EU 19 个，共 38 个
行业 commentary，并把 evidence 反哺到 Obsidian。

## 默认约束

- 输出语言：中文
- 新闻窗口：最近 30 天
- Obsidian vault：`C:\GoogleDrive\笔记\卡片盒子`
- 每条新闻：生成一条 clipping note
- 每个行业每个月：生成一个 evidence block
- 中性行业：生成 commentary 和 evidence block；如果缺少最近 30 天 evidence，会标记 `needs_review`

## Codex-assisted 月度流程

1. 先生成查询主题和缺口报告：

```powershell
python 13_sector_score_model/src/sector_qualitative_report.py --month auto
```

默认会生成 38 个行业包。如果只想回到旧版“只看 Positive / Negative”的口径：

```powershell
python 13_sector_score_model/src/sector_qualitative_report.py --month auto --active-only
```

2. 查看：

- `13_sector_score_model/outputs_qualitative/<YYYY-MM>/query_topics.csv`
- `13_sector_score_model/outputs_qualitative/<YYYY-MM>/report.md`
- `13_sector_score_model/outputs_qualitative/<YYYY-MM>/evidence_packs.json`

3. 由 Codex 联网研究最近 30 天证据，整理成 JSONL。每行结构：

```json
{"id":"manual-tech-ai-capex","kind":"manual","region":"US","subject":"Technology","view":"Positive","stance":"支持","title":"AI资本开支继续支撑美国科技","summary":"大型云厂商继续维持高强度AI资本开支，云收入与AI基础设施需求仍然支撑科技行业的增长和利润预期。","source":"https://example.com/ai-capex","source_date":"2026-07-01","captured_at":"2026-07-05T20:00:00","links":["https://example.com/ai-capex"],"related_notes":["[[AI Capex]]","[[Cloud Infrastructure]]"],"tags":["AI Capex","Technology"]}
```

4. 带 evidence 复跑并写入正式 Obsidian：

```powershell
python 13_sector_score_model/src/sector_qualitative_report.py `
  --month auto `
  --evidence-jsonl .codex_tmp/sector_qualitative_evidence.jsonl `
  --write-vault `
  --overwrite-vault
```

## 无 key RSS 补充

可以用公开 RSS 做补充输入：

```powershell
python 13_sector_score_model/src/sector_qualitative_report.py --month auto --collect-rss
```

公开网页也可以用同一个配置做轻抓取：

```powershell
python 13_sector_score_model/src/sector_qualitative_report.py --month auto --collect-rss --collect-public-pages
```

RSS 和公开网页配置在 `13_sector_score_model/config/qualitative_sources.yaml`。这些来源只作为补充，
质量不足时报告会保留 `needs_review` 和 evidence 缺口。抓取失败、疑似付费墙、内容不足会写入
`run_manifest.json` 的 `web_collection_issues`。

## 输出文件

- `report.md`：带 evidence block 的月度中文报告
- `final_commentary_no_citations.md`：无引用版中文 commentary
- `evidence.jsonl`：所有模型、Obsidian、web/manual、缺口 evidence
- `evidence_packs.json`：按行业聚合后的 evidence pack
- `query_topics.csv`：每个行业的联网检索主题
- `sources.csv`：来源清单
- `run_manifest.json`：运行清单与写入的 Obsidian 文件

`outputs_qualitative/` 是生成物，已在 repo `.gitignore` 中排除。

## 复用到 country / company

共享层 `tp_core.research_context.model_adapter` 已提供：

- `CountryModelAdapter`：读取 `14_country_model/outputs/country_model_latest.csv`
- `CompanyAnalysisCsvAdapter`：读取公司分析导出的 CSV 或 manifest 表
- `LatestCsvModelAdapter`：读取任意多市场 latest CSV

后续 country/company qualitative 入口应复用这些 adapter，以及同一套 evidence、
Obsidian 和 source manifest 逻辑。
