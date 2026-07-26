---
name: tp-quant-research-workflow
description: "Use this skill for TP quantitative research: register hypotheses, run auditable experiments, review Run Cards and results, derive improved configurations, validate factors, and keep research separate from production promotion."
---

# TP Quant Research Workflow

## 目标

使用统一研究中心完成可复现、可查询、可追溯的 TP 量化研究。把研究意图写入 Hypothesis Registry，把执行证据写入 Run Card v3，并把改进作为有父子 lineage 的新假设运行。

不要把生产刷新、Dashboard 启停或生产模型晋升混入研究任务；这些工作使用对应的 TP 工作流。

## 当前唯一主线

从仓库根目录工作，并以这些位置为准：

- 假设配置：`config/research/hypotheses/<hypothesis-id>.json`
- 可复用研究流程：`src/tp_research/workflows/`
- 当前研究结果：`artifacts/research/runs/<hypothesis-id>/<run-id>/`
- 历史证据库：`artifacts/research/runs/historical/`，只读
- 版本化研究特征：`artifacts/research/features/`
- 迁移清单：`artifacts/research/migrations/`
- 方法约束：`11_docs/RESEARCH_METHODS.md`
- 代码约束：`11_docs/FACTOR_RESEARCH_CODE_RULES.md`

新研究只能通过 `tp_research.cli` 的 Registry 入口执行。不要恢复退役的编号 backtest 工作区，不要从文件路径启动研究脚本，不要动态修改 `sys.path`，也不要把新结果写入历史证据库。

## 标准实验生命周期

### 1. 预注册研究问题

先固定：

- hypothesis ID、可证伪 statement 和 owner；
- universe、benchmark、样本区间和 PIT cutoff；
- 信号方向、neutralization、weighting 和 rebalance；
- transaction cost、slippage 和执行引擎；
- trial family、effective trial count 和成功/否决门槛；
- official 指标、必须产物和预期比较对象。

先审计 screen、returns、fundamentals、estimates、risk、country/sector、宏观、News shadow 和已有模型输出的覆盖率与可用时间。经济直觉只能缩小候选范围，不能替代证据门。

### 2. 实现公共 workflow

把可复用代码放在 `src/tp_research/workflows/`。模块必须暴露普通的 `main(argv) -> int`，支持 `--output-dir`，并把所有结果写到该目录。Registry 只允许调用 `tp_research.workflows.*` 中的 `main`。

不要在 workflow 中自选最终运行目录。统一运行器拥有 `--output-dir`，负责创建结果目录、记录配置、输入 fingerprint、代码版本、运行环境、组件版本、状态、产物和系统决策。

### 3. 新建 Hypothesis 配置

为新研究新增 JSON，不要覆盖已经执行过的配置。使用如下骨架：

```json
{
  "schema_version": 1,
  "hypothesis_id": "example-factor-v1",
  "name": "Example factor research",
  "statement": "The signal improves robust official evidence versus the preregistered baseline.",
  "owner": "TP Research",
  "status": "research",
  "universe": "STOXX600",
  "sample_start": "2010-01-01",
  "sample_end": "2026-06-30",
  "pit_cutoff": "2026-06-30",
  "pit_policy": "available_at_or_before_decision_time",
  "cost_assumptions": {
    "transaction_cost": 0.0,
    "slippage": 0.0
  },
  "trial_family": "example-factor",
  "effective_trial_count": 1,
  "tags": ["research", "factor", "configured"],
  "runner": {
    "module": "tp_research.workflows.run_example_factor_research",
    "callable": "main",
    "default_args": [],
    "required_options": ["--market"]
  }
}
```

保持 `hypothesis_id` 与文件名一致。把稳定默认参数写入 `default_args`，把运行时必须显式给出的参数写入 `required_options`。不要在配置中伪造尚未实现的模块、指标或晋升状态。

### 4. 校验并运行

优先使用当前虚拟环境的模块入口：

```powershell
.\.venv_tp\Scripts\python.exe -m tp_research.cli validate
.\.venv_tp\Scripts\python.exe -m tp_research.cli list
.\.venv_tp\Scripts\python.exe -m tp_research.cli show example-factor-v1
.\.venv_tp\Scripts\python.exe -m tp_research.cli run example-factor-v1 -- --market stoxx600
```

如果项目已经以 editable mode 安装，也可使用 `tp-research` console entry point。`--` 后的参数传给 workflow。不得传入 `--output-dir`。

### 5. 查询和分析结果

先查询 Run Card：

```powershell
.\.venv_tp\Scripts\python.exe -m tp_experiments.cli `
  --root artifacts\research\runs `
  --hypothesis-id example-factor-v1 `
  --limit 20

.\.venv_tp\Scripts\python.exe -m tp_experiments.cli `
  --root artifacts\research\runs `
  --hypothesis-id example-factor-v1 `
  --full `
  --limit 5
```

每次运行重点检查：

- `run.json` 的 config fingerprint、Git commit/dirty、parent run、PIT、输入 fingerprint、组件版本、状态和 decision；
- `results/` 中 workflow 生成的 official CSV/JSON/Parquet/HTML；
- baseline、Top、Worst、Benchmark、Top/Worst ratio、成本、换手、覆盖率和失败时期；
- 多次试验的 trial ledger 与 effective trial count；
- 数据缺口、不可比项、screening 结果和 official exact 结果是否被清晰分开。

Run Card 的通用 metrics 目前主要记录耗时和 exit code。绩效判断必须读取 `results/` 的确定性产物，不能只看 Run Card 摘要。当前 CLI 不提供 compare、derive 或人工改写 decision 的子命令；需要比较时用可复现分析代码读取多个 run 的结果。

不要手工修改完成后的 `run.json`。

### 6. 写入改进配置

把改进写成新配置，例如 `example-factor-v2.json`：

- 使用新的 `hypothesis_id`；
- 更新 statement、参数、门槛、样本或组件版本；
- 保留或明确变更 `trial_family`；
- 累计真实的 `effective_trial_count`；
- 在报告中说明相对父运行改变了什么、为什么改变；
- 不覆盖父配置和父结果。

从父运行的 `run.json` 或查询结果取得 `run_id`，再建立 lineage：

```powershell
.\.venv_tp\Scripts\python.exe -m tp_research.cli run example-factor-v2 `
  --parent-run-id <parent-run-id> `
  -- --market stoxx600
```

研究完成时系统 decision 为 `review_required`。配置中的 `validated` 或 `promoted` 状态不能绕过 TP 数据、模型、信号和生产晋升门；晋升必须是独立、明确授权的任务。

## 因子研究强制证据门

### Raw variable gate

- 先把方向统一为 higher-is-better，再做 winsorize 和预注册的 neutral rank。
- 每个 raw variable 在进入 family composite 前都必须跑 official Top/Worst。
- 默认至少要求可接受 coverage、正的 Top/Benchmark ratio CAGR、正的 Top/Worst ratio return 和正 robust score。
- 对 CIQ、FactSet、数据库和本地派生字段使用同一门槛。
- 没有通过变量的 family 不进入组合测试；失败变量仍保留在 diagnostics。

### Relative variable

- 把绝对水平变量的 same-security `directional_delta` 和 `score_delta` 视为新的 raw variable。
- 默认 lag 为 `1, 3, 6, 12` 个 screen observation；冻结既有预注册口径，新 lag 使用新运行。
- 不要机械地对 growth、revision、momentum、return、CAGR 或其他 change-like 字段再做二阶变化。
- 每个 relative variant 必须通过同一 official gate，并与原 level 变量比较。

### Synergy

- 先要求每条单腿具备 official 证据，再测 pair、subset 或 leave-one-out。
- 只有组合相对最好单腿改善 robust score 和风险证据，并且 coverage、turnover、overlap 可接受时，才称 `synergistic`。
- 否则分类为 `additive`、`redundant`、`harmful` 或待验证。
- 经济故事是待检验假设，不是 synergy 结论。

### LOPO/LORO

- 使用预先定义的连续经济时期，不随机打散月份。
- 每折只用 training periods 做 gate、选择和权重；holdout 只评价。
- 全历史发现候选后再做 LOPO 只能称历史阻塞验证，不能称真正未来 OOS。
- 冻结 regime definitions、candidate registry、输入 fingerprint、trial ledger 和最少 formation/coverage 门槛。

## 当前公共 API 边界

- 使用 `tp_research.executor` 处理 raw/relative/synergy gate、dedupe、gap detection、sharding 和 wave 路径。
- 使用 `tp_backtest.BacktestService` 编排标准回测。
- 使用 `tp_backtest.runner.input_loader.load_pruned_backtest_inputs` 规划裁剪后的 screen/returns 输入。
- 使用 `tp_core.backtesting` 暴露的 official facade 和证券级 NAV 契约；聚合收益序列使用 return-series NAV。
- 使用 `tp_core.portfolio_weights` 完成长仓归一、硬上限重分配、weighting transform 和 sector target matching。
- 组合优化只调用 `tp_portfolio.optimize_portfolio()`，并记录 optimizer ID/version、objective、solver 和 constraint policy。
- `fast_nav` 保持默认；只有研究问题需要订单、部分成交、成本或换手限制时才启用 `tp_backtest.execution` 模拟层。

不要按文件路径导入活跃模块，不要复制共享 executor、输入裁剪、权重或优化器语义到市场脚本。共享 DataFrame 视为只读。

## 结果与报告契约

保留确定性证据，不只保留最终图表。按研究范围至少包括：

- 配置快照、manifest、输入 provenance/PIT 和 trial ledger；
- official run results、performance summary、coverage 和 gate 表；
- Top、Worst、Benchmark 与 Top/Worst ratio；
- turnover、holdings、drawdown、rolling failure 和年度/时期证据；
- raw rejection、relative-vs-level、pair/subset/LOO 或 LOPO 诊断；
- 中文结论，分开 official evidence、screening、经济解释、未验证假设和缺失测试。

默认生成 Plotly Top/Worst/Benchmark 和 Top/Worst ratio 比较，但不要让图表替代 CSV/JSON 证据。任何近似筛选都必须明确标注；最终结论只使用 official exact evidence。

## 硬性边界

- 研究代码不得直接修改 production screen、canonical data、生产 signal、portfolio、Dashboard 或模型契约。
- 不覆盖历史运行目录，不写入只读历史证据库，不把生成资产纳入源码 discovery。
- 不因最高 CAGR 自动选赢家；优先评估 ratio drawdown、tracking error、rolling failure、annual hit rate、Top/Worst、turnover、coverage 和持仓数。
- 不前向填充缺失 signal snapshot 来伪造调仓。缺失期沿既有持仓漂移，或在尚未建仓时保持未投资，并写入 audit。
- 不删除优化器求解后的小权重再归一；落盘前重新验证全部约束。
- 发现旧路径、旧包导入、动态 path 注入或重复公共语义时，把它视为发布阻塞问题并修正。
