# 08_presentation_layer

`08_presentation_layer/` 是 TP 的统一展示/报告层。新代码、新启动命令和新报告入口都应优先从这里进入；原 `08_company_analysis/`、`08_dashboard_analysis/`、`08_web_app_des_companies/` 已迁入 `legacy_apps/`，不再作为根目录并行项目维护。

## 统一数据入口

```python
from presentation_layer import PresentationDataRepository

repo = PresentationDataRepository()
last_screen = repo.screen(last_only=True)
returns = repo.returns()
signals = repo.signals()
company_history = repo.company_history("FR0000120271")
```

## 统一应用入口

```powershell
C:\GoogleDrive\TP\.venv_tp\Scripts\python.exe -m presentation_layer.cli inventory
C:\GoogleDrive\TP\.venv_tp\Scripts\python.exe -m presentation_layer.cli system-checks
C:\GoogleDrive\TP\.venv_tp\Scripts\python.exe -m presentation_layer.cli system-dashboard --port 8060
C:\GoogleDrive\TP\.venv_tp\Scripts\python.exe -m presentation_layer.cli web-companies
C:\GoogleDrive\TP\.venv_tp\Scripts\python.exe -m presentation_layer.cli company-api --host 0.0.0.0 --port 8000
```

React job-control client:

```powershell
cd C:\GoogleDrive\TP\08_presentation_layer\frontend\system_dashboard
npm install
npm run dev
```

默认连接 `http://127.0.0.1:8060/api/dashboard/*`；本地访问 `http://127.0.0.1:8061/`。

| 入口 | 作用 | 当前实现来源 |
| --- | --- | --- |
| `presentation_layer.apps.system_dashboard` | TP 系统总控 dashboard：数据资产、manifest、QA 和 pipeline 控制 | `08_presentation_layer/apps/system_dashboard.py` |
| `frontend/system_dashboard` | React/Vite job-control 客户端：前端即时反馈、API 启动、SSE 状态订阅 | `08_presentation_layer/frontend/system_dashboard` |
| `presentation_layer.apps.system_checks` | 子项目 smoke/inspect 检查，输出 dashboard 可读验证 manifest | `08_presentation_layer/apps/system_checks.py` |
| `presentation_layer.apps.system_registry` | 控制塔项目/资产/lineage 注册表，供 dashboard 与检查器共享 | `08_presentation_layer/apps/system_registry.py` |
| `presentation_layer.apps.des_companies` | Dash 公司展示应用 | `08_presentation_layer/legacy_apps/web_app_des_companies/src` |
| `presentation_layer.apps.company_analysis_api` | 公司分析 FastAPI | `08_presentation_layer/legacy_apps/company_analysis/backend/analysis.py` |
| `presentation_layer.reports.portfolio_dashboard` | 组合 dashboard 和 PDF 报告 | `08_presentation_layer/legacy_apps/dashboard_analysis/dashboard.py`、`pdf_report_generator.py` |

Dashboard 的原因子研究入口为 `/reports/factor-explorer.html`，由
`09_reports/build_factor_explorer.py` 生成。页面保留四市场每个候选的
Top/Worst/Benchmark 收益曲线、Top/Worst ratio、Top/Benchmark ratio、
逐变量经济含义、时期图鉴和可审计证据，并补入 lag1/3/6/12、历史
out-of-period、pair/subset/leave-one-out 与 DSR 结果。兼容汇总页
`/reports/factor-research-app.html` 继续保留，但不替代 dashboard 主入口。

## 维护规则

- 新代码不得直接新建第四套展示/报告入口；需要新增页面或报告时，先接入 `presentation_layer.apps` 或 `presentation_layer.reports`。
- UI/callback/report 可以暂时留在 `legacy_apps/`，但数据读取必须优先走 `PresentationDataRepository`。
- `legacy_apps/` 中的 `app.py`、`backend/main.py` 等入口只保留兼容作用；真实 app factory 在 `presentation_layer.apps`。
- `system_dashboard` 默认只读已有 parquet、report 和 manifest；启动写入型工作必须通过既有 pipeline CLI，并由 `10_pipeline_runs/manifests` 留审计证据。
- 控制塔数据资产表包含注册资产和轻量自动发现资产；大体量核心库只做关键列质量统计，避免 dashboard 刷新触发全库扫描。
- 控制塔还读取 QA/profile/manifest 生成数据质量监控、配置中心、运行日志、信号组合监控、回测报告和审计日志视图。
- 控制塔的子项目启动默认走 `system-checks --project` 安全检查；需要启动注册命令时必须在 UI 中显式切换运行模式。
- 控制塔 lineage 图支持点击节点查看对应项目、输入输出、登记命令和最近 manifest 状态。
- 控制塔审计日志读取 `10_pipeline_runs/manifests`，支持按 step、status、日期范围、as-of 和 input-month 筛选历史运行。
- 控制塔可显式保存当前 pipeline / 子项目运行配置到 `.tmp_dashboard_work/dashboard_config.json`；保存配置不会启动 pipeline，也不会修改生产 parquet。
- 外部参考模板库已归档到 `99_archive/external_references_20260705/Inspiration_Claude`，不纳入生产展示/报告层。
