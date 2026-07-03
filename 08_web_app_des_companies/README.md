# web_app_des_companies

## 定位

`web_app_des_companies` 是一个 Dash 公司展示应用，用于查看公司描述、新闻、行业和指数成分相关信息。

## 数据来源

应用应优先读取 TP canonical 数据或由 canonical 数据生成的项目派生 parquet。核心规则见 [`../DATA_SOURCES.md`](../DATA_SOURCES.md)。

## 运行入口

```powershell
pip install -r requirements.txt
python app.py
```

默认访问地址：`http://127.0.0.1:8050`。

## 架构

| 目录 | 作用 |
| --- | --- |
| `src/data/` | parquet loader 和 `CompanyRepository` |
| `src/services/` | 过滤、Markdown 摘要等纯函数 |
| `src/ui/` | 主题、布局、组件和页面 |
| `src/callbacks/` | Dash callbacks |
| `src/assets/` | 全局 CSS |

## 测试

```powershell
pytest
```

## 维护状态

可维护应用。扩展新数据集时应先在 repository 层封装读取，不要让 UI 直接读取 DataFrame。


## 共享展示/报告数据层

`web_app_des_companies` 现在应优先通过 `presentation_layer.PresentationDataRepository` 读取公司截面和信号数据，UI 不直接维护路径规则。

```python
from presentation_layer import PresentationDataRepository

repo = PresentationDataRepository()
last_screen = repo.screen(last_only=True)
signals = repo.signals()
```

## 统一展示/报告层状态

本目录现在是 Dash 公司展示应用的实现目录和兼容入口。统一启动入口已迁入 `presentation_layer.apps.des_companies`，推荐使用 `python -m presentation_layer.cli web-companies`。


