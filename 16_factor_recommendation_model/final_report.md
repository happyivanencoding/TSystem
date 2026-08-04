# 月度因子推荐模型 v1 交付报告（已拒绝，仅审计留档）

> v1 不再是可选模型。它的 Run Card `20260804T141711Z-e7a212e5` 保持不变，但因 security-level research unit、模型候选别名、未执行 promotion thresholds、错误的 iid bootstrap 标签、研究时序与 dirty commit 问题被拒绝。拒绝记录：`config/research/model_candidates/monthly-factor-recommendation-v1-rejected.json`。v2 不继承本报告中的任何 Sharpe 或推荐结论。

## 结论

已完成 `16_factor_recommendation_model` 的 research-only 端到端实现，并用真实 canonical 数据完成一次 full 研究。生产候选池、optimizer、`export_signals` 和现有生产模型均未被接入或改写；ASIA 仍明确为 `research_only_benchmark_unapproved`。

## 数据与审计

- Git 基线：`0684f587e47e6b7bb47b7875d42f615680104dd8`，branch `main`，Run Card 记录工作树 dirty。
- Screen：`00_screen/screen_aggregate.parquet`，当前审计为 3,465,456 行、301 列、320 个日期，键 `(ISIN, Date)` 无重复。
- Returns：`00_screen/returns.parquet`，当前审计为 5,533 个交易日、12,021 个字段，日期无重复。
- 最新 screen 日期：`2026-07-31`。US/STOXX Europe/NIKKEI/MSCI World 最新正权重成员数分别为 503/599/389/1,280。
- ASIA 不是 `Univ ML OTHER` 改名，也不是整张 MSCI EM：JAPAN 使用 NIKKEI 正权重且 `Exchange Country Iso2=JP`；ASIA_EX_JAPAN 使用 MSCI EM 正权重和固定 `CN/HK/IN/KR/TW/SG/MY/TH/ID/PH` allowlist；聚合权重固定 0.5/0.5。
- 五项固定审计位于 `16_factor_recommendation_model/audit/`：`repository_audit.json`、`data_audit.json`、`universe_audit.csv`、`factor_column_audit.csv`、`integration_map.json`。

## 实现与产物

- 核心包：`src/tp_models/factor_recommendation/`，包含 typed contracts、PIT universe、Value/Quality/Growth/Momentum/LowVol/Size/Small Size/Dividend、next-month target、grouped expanding walk-forward、模型 fallback、幂等 persistence 和官方 sleeve adapter。
- Size 语义已拆开：`size` 为大盘暴露，`small_size` 为显式 `10 - Size` 反向分数。
- 官方 adapter 唯一入口登记为 `tp_core.backtesting.OfficialPortfolioBacktest`；不在新包内实现本地 NAV。ASIA 只返回组件结果，不伪造合成 benchmark NAV。
- pipeline step：`refresh_factor_recommendation` 默认关闭，独立写 `16_factor_recommendation_model/outputs/` 与 `artifacts/signals/factor_recommendation_signals.parquet`，strict signal schema 校验通过且重复键为 0。
- 最新生产刷新：`2026-07-31`，历史面板 7,888 行、262 个日期、8 因子×5 区域；signal 同步 7,888 行。
- signal 使用 `signal_family=FactorRecommendation`、`scope=region`、`score` 0--100、`score_pct` 0--1，并保留 `as_of_date`/`effective_date`/`horizon`/`confidence` 和审批状态。

## Full 研究证据

最新 Run Card：
`artifacts/research/runs/monthly-factor-recommendation-v1/20260804T141711Z-e7a212e5/run.json`

结果目录：
`artifacts/research/runs/monthly-factor-recommendation-v1/20260804T141711Z-e7a212e5/results/`

- `status=success`、`run_mode=full`、`is_full=true`、decision=`review_required`。
- 40 个要求工件全部存在；包括 prompt 级 repository/universe/factor/raw-relative gate、feature coverage、M0--M4 candidate registry、walk-forward predictions/metrics、LOPO/LORO、strategy/sleeve returns、cost sensitivity、block bootstrap、deflated Sharpe、trial ledger、selection audit、promotion gate 和 report。
- walk-forward：5 个 grouped folds；每个 fold 60 个月起步并记录 1 个月 purge；同一月份证券不跨 train/test。
- OOS strategy metrics：199 个观察；gross Sharpe 1.123，net Sharpe 1.061，benchmark Sharpe 0.962。它们是研究证据，不是交易建议或晋升结论。
- 成本敏感性真实覆盖 0/10/25/50 bps；50 bps 下 Sharpe 为 0.915。
- promotion gate：12/13 检查项通过，但 `promotion_decision` 仍为 `review_required`；ASIA benchmark approval 和 12 个月 forward shadow 尚未完成，不能自动晋升。

## 验证结果

- 核心模型/审计定向测试：7 passed。
- pipeline、Presentation API、研究 runner 合计定向回归：通过；最新研究 runner 测试 6 passed，pipeline/API/entrypoint 24 passed。
- 注册研究：`tp_research.cli validate` 通过（11 个定义有效）；smoke 与 full 均生成独立 Run Card。
- 前端 Factor Recommendation 定向测试：6 个文件、12 tests passed；Vite build passed。
- `presentation_layer.cli inventory` passed；factor 项目 scoped `system-checks` 返回 success。全量 `system-checks` 在 124 秒窗口超时，未将其误报为通过。
- `git diff --check` 无内容错误；仅有 Windows 换行和历史超长路径 warning。

## 未完成/边界

该交付保持 research-only。官方 adapter 的调用边界和 fake-engine contract 已测试，full Run Card 的 OOS metrics 仍由研究 runner 的 PIT target/strategy evidence 产生，未声称已完成生产晋升。下一步必须由独立 gate 审核 cost、LOPO/LORO、DSR、bootstrap、forward shadow，并单独批准 ASIA benchmark 定义后，才可讨论 promotion。
