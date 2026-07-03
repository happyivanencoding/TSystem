# 文档治理规则

最后更新：2026-06-30

本文档规定 `C:\GoogleDrive\TP` 以后如何新增、更新和归档说明文件。目标是让根目录轻、文档入口稳定、历史材料不误导当前生产流程。

## 根目录非文件夹规则

根目录可以出现的非文件夹文件只限以下几类：

| 类型 | 允许文件 | 规则 |
| --- | --- | --- |
| 工作区入口 | `README.md` | 只做导航和当前主线摘要，不写长篇运行细节 |
| 数据权威契约 | `DATA_SOURCES.md`、`DATA_CONTRACT.md` | 因为大量项目直接引用，暂时保留根目录；内容必须与 `tp_core` 和 `00_screen/` 同步 |
| Python/工程配置 | `pyproject.toml`、`environment.yml`、`sitecustomize.py` | 给工具链直接读取，不属于描述性文档 |
| 工具隐藏文件 | `.gitignore` 等标准工具文件 | 仅限工具自动识别文件 |

根目录不允许新增以下内容：

- 普通说明型 Markdown，例如 `xxx_plan.md`、`xxx_audit.md`、`xxx_notes.md`。
- notebook、临时测试文件、Excel/CSV/Parquet 数据片段。
- 一次性 QA 或运行证据文件。
- 项目局部 README 以外的跨项目说明。

如果确实需要新增根目录文件，必须先满足两个条件：它被工具链直接读取，或者它是全工作区入口/契约；并同步更新本文件。

## Markdown 放置规则

| 文档类型 | 放置位置 | 示例 |
| --- | --- | --- |
| 全工作区入口 | 根目录 `README.md` | 当前主线、先读哪些文档 |
| 跨项目长期说明 | `11_docs/` | `PROJECTS.md`、`DATA_AND_PRODUCTION.md`、`ENVIRONMENT.md` |
| 数据源和数据契约 | 根目录固定例外 | `DATA_SOURCES.md`、`DATA_CONTRACT.md` |
| 单项目说明 | 项目自己的 `README.md` | `08_presentation_layer/README.md` |
| 项目内部多文档 | 项目内 `说明文档/` 或 `docs/` | `00_screen/说明文档/` |
| 历史审计/旧计划 | `11_docs/archive/` 或 `99_archive/` | 根目录旧 cartographie、旧月更审计 |
| 机器运行证据 | `10_pipeline_runs/`、`qa/`、`manifests/` | JSON/CSV/Parquet 优先，固定 `*_latest.md` 可作为摘要 |

## 基本规则

1. 面向使用者的描述性文档统一使用中文。
2. 不再创建 `xxx_YYYYMMDD_HHMMSS.md` 这类一次性 Markdown。
3. 最新审计结论如需 Markdown 摘要，使用固定文件名，例如 `*_latest.md`，并放在项目 `manifests/` 或 `qa/` 下，不放根目录。
4. 每次运行的详细证据使用 JSON/CSV/Parquet，放在 `qa/`、`manifests/`、`10_pipeline_runs/` 或项目自己的 `output/`。
5. 历史文档可以保留，但必须进入 archive，并在中枢文档中标明“历史审计/历史实现记录/冻结参考”。
6. 新项目必须有最小 `README.md`：项目用途、运行入口、数据来源、输出位置、维护状态。
7. 新文档优先更新已有权威文档；只有出现新的长期职责边界时，才新增 Markdown 文件。

## 当前推荐文件结构

```text
TP/
├── README.md
├── DATA_SOURCES.md
├── DATA_CONTRACT.md
├── pyproject.toml
├── environment.yml
├── sitecustomize.py
├── 00_screen/
│   ├── README.md
│   ├── production_inputs/README.md
│   └── 说明文档/
├── 11_docs/
│   ├── README.md
│   ├── PROJECTS.md
│   ├── DATA_AND_PRODUCTION.md
│   ├── ENVIRONMENT.md
│   ├── RESEARCH_METHODS.md
│   ├── DOCUMENTATION_GOVERNANCE.md
│   └── archive/
└── <numbered_project>/
    └── README.md
```

## 什么时候更新哪份文档

| 变更 | 更新文件 |
| --- | --- |
| canonical 数据路径变化 | `DATA_SOURCES.md`、`11_docs/DATA_AND_PRODUCTION.md` |
| 主键、字段族、日期或 SEDOL 规则变化 | `DATA_CONTRACT.md` |
| 月更 CLI 或输入目录变化 | `00_screen/README.md`、`00_screen/production_inputs/README.md` |
| 新增/停用一个小项目 | `11_docs/PROJECTS.md` |
| Python 环境、kernel、依赖变化 | `11_docs/ENVIRONMENT.md`、必要时 `environment.yml`、`pyproject.toml` |
| 新增一类研究方法 | `11_docs/RESEARCH_METHODS.md` 或项目 `README.md` |
| 文档命名、根目录文件或归档规则变化 | 本文件 |

## 历史与隔离

- `_quarantine_YYYYMMDD/` 用于短期可回滚隔离，不是长期知识库。
- `11_docs/archive/` 存历史文档；`99_archive/` 存冻结项目、旧代码和旧数据。
- 生产入口切换后，旧路径只在“历史/兼容”段落出现，不应出现在快速开始命令中。
- 被归档的数据或文档必须有 manifest，记录原路径、目标路径和原因。

## 小项目 README 模板

```markdown
# 项目名

## 定位
一句话说明这个项目解决什么问题。

## 数据来源
说明是否读取 canonical `screen_aggregate.parquet` / `returns.parquet`，以及是否有项目派生数据。

## 运行入口
列出主要脚本、notebook 或应用启动命令。

## 输出
列出主要输出文件或目录。

## 维护状态
生产 / 活跃研究 / 工具型 / 历史冻结 / 待确认。
```

## 当前根目录整理状态

- 根目录保留：`README.md`、`DATA_SOURCES.md`、`DATA_CONTRACT.md`、`pyproject.toml`、`environment.yml`、`sitecustomize.py`。
- 已归档到 `11_docs/archive/`：`DOCUMENTATION_UPDATE_PLAN.md`、`TP_Projet_Cartographie.md`、`screen_monthly_update_audit.md`。
- 归档 manifest：`11_docs/archive/manifest.json`。
