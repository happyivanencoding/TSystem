# Company_Analysis

## 定位

`Company_Analysis` 包含公司分析后端、前端组件、估值模板和外部灵感材料，用于公司级信息整理和分析。

## 数据来源

活跃代码应读取 TP canonical 数据或其派生表，尤其是：

- `00_screen/last_screen.parquet`
- `00_screen/screen_aggregate.parquet`
- `00_screen/returns.parquet`

统一路径规则见 [`../DATA_SOURCES.md`](../DATA_SOURCES.md)。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `backend/` | 公司分析后端逻辑 |
| `frontend/` | 前端相关文件 |
| `Company_Valo.jsx` | 公司估值/展示组件 |
| `Inspiration_Claude/` | 外部参考模板库，不纳入 TP 生产文档体系 |
| `start_app.ps1` | 本地启动脚本 |

## 运行入口

优先查看 `start_app.ps1` 和 `backend/` 中的应用入口。若要把该项目纳入稳定生产流程，应在本 README 中补充明确启动命令、输入数据和输出位置。

## 维护状态

应用/模板型项目。`Inspiration_Claude` 只作为参考资料，默认不改写其中的第三方文档。


## 共享展示/报告数据层

`Company_Analysis` 现在应优先通过 `presentation_layer.PresentationDataRepository` 读取公司截面、returns 和统一信号表，避免后端/前端各自维护路径规则。

```python
from presentation_layer import PresentationDataRepository

repo = PresentationDataRepository()
last_screen = repo.screen(last_only=True)
signals = repo.signals()
```

## 统一展示/报告层状态

本目录现在是公司分析前后端实现目录和兼容入口。FastAPI 统一入口已迁入 `presentation_layer.apps.company_analysis_api`，推荐使用 `python -m presentation_layer.cli company-api`。


