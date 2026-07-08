# backtest_wep_app

## 当前状态

`backtest_wep_app` 已不再作为回测主线维护。回测主线已经迁到传统代码版 [`../backtest_code`](../backtest_code)，后续新回测、批量运行和产物保存应使用 `backtest_code/run_backtest.py` 或 `tp_core.backtesting`。

## 已迁移和隔离内容

- `BacktestEngine.py`、`core/`、`utils/`、`config/` 和 `tests/` 已复制到 `backtest_code/`。
- 原目录中的重复回测核心已移动到 `_quarantine_20260629/legacy_backtest_core/`，并保留 `manifest.json` 方便回滚核对。
- Streamlit、FastAPI、Docker 相关入口已移动到 `_quarantine_20260629/legacy_frontend/`。
- 根目录旧 `.pkl` 数据副本已移动到 `_quarantine_20260629/legacy_data_copies/`。

## 数据来源

仍保留的历史代码若被临时打开，必须读取 TP canonical 数据：

- `C:/GoogleDrive/TP/screen/screen_aggregate.parquet`
- `C:/GoogleDrive/TP/screen/returns.parquet`

推荐入口：

```python
from tp_core.io import read_screen_aggregate, read_returns
from tp_core.backtesting import PtfBuilder

screen = read_screen_aggregate()
returns = read_returns()
```

## 维护规则

不要在本目录新增 Web/API/Streamlit 功能。需要回测时，请在 `backtest_code/` 中维护传统代码入口；需要展示时，后续应由统一投资 dashboard 消费 `backtest_code/runs/` 的产物。
