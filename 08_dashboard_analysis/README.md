# dashboard_analysis

## 定位

`dashboard_analysis` 用于组合、指数和公司数据的分析展示，并可生成 PDF 报告。

## 数据来源

应从 TP canonical screen/returns 或其派生数据读取输入。数据源规则见 [`../DATA_SOURCES.md`](../DATA_SOURCES.md)。

## 主要文件

| 文件 | 作用 |
| --- | --- |
| `dashboard.py` | 主要 dashboard / 分析脚本 |
| `pdf_report_generator.py` | PDF 报告生成 |
| `analyse.xlsx` | 分析输入或示例文件 |

## 运行入口

```powershell
python dashboard.py
```

如需生成 PDF，查看 `pdf_report_generator.py` 中的入口函数和参数。

## 维护状态

工具型项目。建议后续把输入路径、输出目录和运行参数整理为配置文件。


## 共享展示/报告数据层

`dashboard_analysis` 现在应优先通过 `presentation_layer.PresentationDataRepository` 读取 screen、returns 和 signals，报告脚本不再单独硬编码主数据路径。

```python
from presentation_layer import PresentationDataRepository

repo = PresentationDataRepository()
last_screen = repo.screen(last_only=True)
signals = repo.signals()
```

## 统一展示/报告层状态

本目录现在是组合 dashboard 和 PDF 报告的实现目录。统一报告入口已迁入 `presentation_layer.reports.portfolio_dashboard`，推荐通过 `python -m presentation_layer.cli dashboard-smoke` 验证入口。


