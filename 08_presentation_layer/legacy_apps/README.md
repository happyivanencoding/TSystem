# Presentation 内部资源

本目录只保存尚待归档的历史设计输入、模板、人工 notebook 和旧构建副本，不是应用入口，也不被活跃代码读取。

| 子目录 | 当前用途 |
| --- | --- |
| `company_analysis/` | 历史公司分析模板、图标和前端参考构建 |
| `dashboard_analysis/` | 历史组合分析模板及 outputs |

公共 Python 实现已经迁入 `src/presentation_layer/`。启动应用只能使用：

```powershell
.\.venv_tp\Scripts\tp-presentation.exe web-companies
.\.venv_tp\Scripts\tp-presentation.exe company-api
.\.venv_tp\Scripts\tp-presentation.exe system-dashboard
```

本目录不得新增 `app.py`、`main.py`、`wsgi.py`、启动脚本或可直接运行的报告入口。公司浏览运行资源已经迁出；剩余内容只在确认无审计价值后逐步归档。
