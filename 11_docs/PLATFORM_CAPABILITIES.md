# TP 平台能力

最后更新：2026-07-26

本文档记录已经部署的平台能力、默认安全边界和唯一公共入口。它描述当前事实，不保留迁移中的旧命令。

## 研究与实验治理

- `tp-research list|validate|run` 是配置化研究的统一入口。
- Hypothesis 定义位于 `config/research/hypotheses/`；runner 只允许调用 `tp_research.workflows` 中登记的普通模块。
- Run Card schema v3 记录 hypothesis、配置和代码版本、输入 provenance/PIT、运行环境、指标、产物、状态、父运行和晋升决定。
- 新研究写入 `artifacts/research/runs/`；历史实验只读保存在 `artifacts/research/runs/historical/`。
- 原编号回测工作区已无损迁移并删除。迁移清单位于 `artifacts/research/migrations/`，新运行不得写回历史库。
- 实验默认 `save_plots=false`、`holdings_mode=minimal`；holdings 只保存 `Date`、`Weight`、`ISIN`。需要图形或完整 holdings 时必须在 Hypothesis 的 `artifact_policy` 中显式开启，并由 Run Card 记录有效策略。

```powershell
tp-research validate
tp-research list
tp-research run cross-market-lopo
```

## 回测执行层

`fast_nav` 仍是生产和研究默认值。可选 `weight_simulator` 在同一权重空间增加：

- 决策日至下一收益交易日执行；
- 订单、部分成交、剩余单和日换手上限；
- commission/slippage；
- gross/net NAV 和完整审计产物。

不设换手上限且成本为零时，gross NAV 与快速引擎精确一致。配置位于 `config/backtest/default.yaml`，外部调用继续使用 `optimize_portfolio` 和现有回测 facade。

## 数据 Provider 平台

`tp_data.providers` 提供：

- `Provider` protocol、`ProviderQuery`、`ProviderContext` 和 registry；
- Pydantic `StandardModel`；
- Macro、Fundamental、Estimate、News 标准模型；
- 现有补充数据源和只读 OKF News adapter。

Provider 结果只允许进入 `raw`、`normalized_shadow` 或 `shadow`。Provider 无权写 Canonical，也不能绕过 TP acceptance/promotion gate。新增数据源必须先实现协议和标准模型，再由独立晋升流程决定是否进入生产。

## News shadow research

- 新闻证据只读来自 `C:\GoogleDrive\笔记\卡片盒子\40_News_Room` 的 OKF manifest/notes。
- 仅 `privacy_level=public_internal` 的脱敏摘要可发送给模型。
- 版本化特征为 `glm51_news_sentiment_event_v1`，模型必须是 `glm-5.1`；不使用 FinBERT。
- 缺少 PIT available time 的记录被排除，标题/日期/正文和 canonical URL 用于去重。
- 人工整理新闻存在 selection bias，因此 `predictor_default=false`；它默认只作为报告证据、评价标签和 shadow 特征。
- `tp-news-shadow` 默认 dry-run；只有显式 `--apply` 才产生 API 请求。晋升必须使用同日期、fold、placebo、市场、年度和 sector 对照独立验证。

环境变量只使用 `AI_BASE_URL`、`AI_MODEL=glm-5.1`、`AI_API_KEY`。程序不读取其他项目的数据库或凭据。

## 公司研究与只读 Copilot

`tp-company-report` 先生成确定性 snapshot 和 Markdown：

- 每个数字带 fact ID、来源、as-of、单位、公式和输入 fingerprint；
- region/sector median 与差值由代码计算；
- LLM 只能引用已知 fact/evidence ID，不能引入 snapshot 外数字。

叙述默认关闭（`TP_NARRATIVE_ENABLED=0`）。开启后优先调用 `TP_FREE_TOKEN_ROUTER_SCRIPT` 指定的 stdin/JSON 子进程，失败时才使用 GLM-5.1；严格校验失败则退回确定性报告。公司研究 API 和 Copilot 只读，不提供交易、任务或 Canonical 写入能力。

## Presentation 边界

- `presentation_layer` 是唯一 Dashboard、API、公司浏览和报告入口。
- Dashboard 后端按 repository、domain service、API router、job controller、view model 和 backtest view service 分层。
- React 主页面已拆出 hooks、API client、domain contracts、Regime、Country 和 Sector 组件。
- 旧 `legacy_apps` 启动器、脚本和重复数据不参与运行；不得恢复或直接执行。

## 产物保留

`tp-prune-artifacts` 默认只输出 dry-run 计划，`--apply` 才删除。历史研究库和迁移清单受保护；Run Card、feature cache、pipeline manifest、Dashboard 记录、backtest ad-hoc、News run 和 scratch 分别使用独立规则。Git 跟踪文件永不由该命令删除。

```powershell
tp-prune-artifacts
tp-prune-artifacts --rule dashboard-launch-records
tp-prune-artifacts --apply --rule scratch-workspaces
```

## 工程验证

```powershell
tp-check-legacy-references
python -m pytest -q
npm run test --prefix 08_presentation_layer\frontend\system_dashboard
npm run build --prefix 08_presentation_layer\frontend\system_dashboard
```

Archive、runs、outputs 和生成资产继续从 pytest、ruff、mypy、CRG 和 CI discovery 中排除。

## Factor Recommendation dashboard panel

Presentation Layer 提供 `/api/dashboard/signals/factor-recommendation` 和对应的
React panel。它从 repository boundary 读取最新 panel、history、严格 signal、
summary/validation 和 manifest，展示 US/EU/ASIA、因子分数、覆盖率、证据、基线
与 promotion gate。响应即使产物缺失、损坏或过期也保持稳定 contract；状态
`research_only` 不代表已晋升，ASIA 的固定双组件定义和
`research_only_benchmark_unapproved` 必须在页面上保留。
