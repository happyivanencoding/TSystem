# TP 文档治理规则

最后更新：2026-07-26

目标是让少数权威文档维护当前事实，项目 README 只说明局部职责，历史材料不再提供可复制的生产命令。

## 权威文档

| 主题 | 唯一权威文档 |
| --- | --- |
| 工作区入口 | 根目录 `README.md` |
| Canonical 数据路径 | 根目录 `DATA_SOURCES.md` |
| 数据主键与字段语义 | 根目录 `DATA_CONTRACT.md` |
| 已部署架构与项目职责 | `INVESTMENT_PLATFORM_MAINLINE.md` |
| 月更和生产流水线 | `PIPELINE_OPERATIONS.md` |
| Python 环境 | `ENVIRONMENT.md` |
| 回测 API 与运行 | `BACKTEST_ENGINE.md`、`BACKTEST_WORKSPACE.md` |
| 研究方法 | `RESEARCH_METHODS.md`、`FACTOR_RESEARCH_CODE_RULES.md` |
| 旧入口规则 | `LEGACY_POLICY.md` |
| 信号契约 | `SIGNAL_SCHEMA.md` |

原 `PROJECTS.md`、`CORE_LIBRARY.md` 已并入架构文档；原 `DATA_AND_PRODUCTION.md` 已并入生产运行手册。不得恢复第二份并行说明。

## 放置规则

| 文档类型 | 位置 |
| --- | --- |
| 工作区入口、数据权威契约 | 根目录固定文件 |
| 跨项目长期说明 | `11_docs/` |
| 项目局部说明 | 项目自己的 `README.md` 或 `docs/` |
| 当前接手状态 | `_context/` |
| 历史审计、旧计划、一次性 QA | `11_docs/archive/`、`99_archive/` 或机器证据目录 |
| 运行证据 | 优先 JSON/CSV/Parquet，位于 `qa/`、`artifacts/pipeline_runs/` 或专项 outputs |

根目录禁止新增普通计划、审计、notes、notebook 或数据片段。

## 内容规则

1. 面向使用者的当前文档使用中文。
2. 长期事实优先更新现有权威文档，不新建平行版本。
3. 不在 durable 文档中硬编码“当前行数、最新日期”等快速过期统计；这类信息由 profile、manifest 或 inspect 命令生成。
4. 项目 README 只写定位、输入、公共入口、输出、维护状态和正式文档链接。
5. Archive 必须在开头标记“历史参考”，不得作为当前操作手册。
6. Handoff 是任务完成时的快照；后续状态变化用“后续状态”补充，不把它当正式 runbook。
7. `_context` 不复制 `11_docs` 正文。
8. 每次目录、CLI 或公共 API 变化，都必须同步扫描 Markdown 旧命令和相对链接。

## 入口规则

- 生产操作优先使用 `pyproject.toml` 安装的 `tp-*` 控制台入口。
- 模型专项研究可以使用当前包的 `python -m tp_models...`。
- 禁止执行编号资源目录中的 Python 文件。
- 禁止恢复 `sitecustomize.py`、`.pth`、业务代码 `sys.path` 注入或按文件路径导入。
- 历史路径只允许在明确标记的 archive、handoff 或 `LEGACY_POLICY.md` 中出现，不得出现在快速开始代码块。

运行以下命令检查活跃代码、配置和 Markdown：

```powershell
.\.venv_tp\Scripts\tp-check-legacy-references.exe
```

## 当前结构

```text
TP/
├── README.md
├── DATA_SOURCES.md
├── DATA_CONTRACT.md
├── src/
├── tests/
├── config/
├── artifacts/
├── 00_screen/
├── 03_*/
├── 08_presentation_layer/
├── 11_docs/
│   ├── README.md
│   ├── INVESTMENT_PLATFORM_MAINLINE.md
│   ├── PIPELINE_OPERATIONS.md
│   ├── <其他专项权威文档>
│   └── archive/
├── 13_* ... 16_*/
├── _context/
└── 99_archive/
```

编号目录只保留数据、配置、notebook、前端和专项产物；活跃 Python 源码只位于 `src/`。

## 最小项目 README

项目 README 至少回答：

- 项目解决什么问题。
- 读取哪些 Canonical 或专项输入。
- 唯一公共运行入口是什么。
- 标准输出在哪里。
- 当前是生产、活跃研究、资源工作区还是历史冻结。

不得重新介绍全工作区架构、复制数据契约或给出旧脚本兼容命令。

## 定期审计

发生以下任一情况时运行文档审计：

- 目录、console script、包名或公共 API 改变。
- 某 README 命令执行失败。
- 新架构替代旧版本。
- 同一主题出现第二份长期文档。
- Durable 文档出现手工更新的最新日期、行数或性能快照。

审计结果只更新权威文档；过程证据进入 archive 或 JSON manifest，不创建新的长期 audit Markdown。
