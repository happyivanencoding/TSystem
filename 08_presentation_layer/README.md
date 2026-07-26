# TP Presentation Layer

`presentation_layer` 是 TP 唯一展示、API、控制塔和报告应用入口。活跃 Python 实现位于 `src/presentation_layer/`；`08_presentation_layer/` 只保存 React/Vite 前端和应用运行所需的数据、静态资产及 notebook。

## 公共数据入口

```python
from presentation_layer import PresentationDataRepository

repo = PresentationDataRepository()
last_screen = repo.screen(last_only=True)
returns = repo.returns()
signals = repo.signals()
```

UI、callback 和 API 不自行读取 Canonical 文件，统一经过 repository/domain service。

## 公共应用入口

```powershell
.\.venv_tp\Scripts\tp-presentation.exe inventory
.\.venv_tp\Scripts\tp-presentation.exe system-checks
.\.venv_tp\Scripts\tp-presentation.exe system-dashboard --port 8060
.\.venv_tp\Scripts\tp-presentation.exe web-companies
.\.venv_tp\Scripts\tp-presentation.exe company-api --host 0.0.0.0 --port 8000
```

不得直接执行 `legacy_apps` 中的 `app.py`、`backend/main.py`、PowerShell 启动器或报告脚本；这些兼容入口已退役。

## 当前模块

| 模块 | 职责 |
| --- | --- |
| `presentation_layer.data_repository` | Screen、returns、signals 和公司历史统一读取 |
| `presentation_layer.apps.system_dashboard` | 控制塔 API、页面和生产 job 控制 |
| `presentation_layer.apps.system_backtests` | 回测发现、指标和 Dashboard 行模型 |
| `presentation_layer.apps.system_jobs` | 受控任务队列与 worker |
| `presentation_layer.apps.system_registry` | 项目、资产、命令和 lineage |
| `presentation_layer.apps.des_companies` | Dash 公司浏览应用 factory |
| `presentation_layer.apps.company_analysis_api` | FastAPI 公司分析 factory |
| `presentation_layer.company_browser` | 公司浏览 domain/UI/callback |
| `presentation_layer.portfolio` | 组合 dashboard 与 PDF |
| `presentation_layer.reports` | 报告公共 facade |

三个原展示项目不再作为控制塔独立项目登记，统一归属 `08_presentation_layer`。

## 前端

```powershell
cd 08_presentation_layer\frontend\system_dashboard
npm install
npm run dev
```

Vite 本地页默认连接 `http://127.0.0.1:8060/api/dashboard/*`。生产构建：

```powershell
npm run build --prefix 08_presentation_layer\frontend\system_dashboard
```

## 内部资源

`legacy_apps/` 只保留尚待归档的历史展示实现，不含公共启动入口，也不被活跃代码、测试或构建读取。公司浏览静态资产和必要数据已经迁至正常前端、配置和 `artifacts/` 边界。说明见 `legacy_apps/README.md`。

## 维护规则

- 新应用、页面和报告只接入 `presentation_layer.apps`、`presentation_layer.company_browser`、`presentation_layer.portfolio` 或 `presentation_layer.reports`。
- Dashboard 写入型工作只能调用已登记的当前 pipeline 命令，并留下 manifest 和 Run Card。
- `artifacts/dashboard_work/` 保存配置、launch record 和检查结果。
- 生产数据与模型产物只读；保存 Dashboard 配置不会启动任务或修改 Canonical parquet。

## 验证

```powershell
python -m pytest tests\presentation -q
npm run test --prefix 08_presentation_layer\frontend\system_dashboard
npm run build --prefix 08_presentation_layer\frontend\system_dashboard
```

## 维护状态

生产展示层。旧入口不存在于活跃区；内部静态/数据资源从 Python、测试和 CRG discovery 排除。
