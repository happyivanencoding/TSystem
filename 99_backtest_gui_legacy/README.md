# Backtest_GUI

## 当前状态

`Backtest_GUI` 已不再作为回测主线维护。PySide6 界面和启动脚本已移动到 `_quarantine_20260629/legacy_gui_frontend/`，只作为可回滚历史参考。

无界面的配置、校验、runner 和产物保存能力已经迁入 [`../backtest_code`](../backtest_code)。原 `src/` 源码副本已移动到 `_quarantine_20260629/legacy_gui_core/`。后续新回测请使用传统代码入口。

## 新入口

```powershell
python C:\GoogleDrive\TP\backtest_code\run_backtest.py inspect
python C:\GoogleDrive\TP\backtest_code\run_backtest.py run
```

## 保留内容

| 路径 | 说明 |
| --- | --- |
| `configs/` | 历史 GUI profile；已复制到 `backtest_code/configs/` |
| `logs/` | 历史 GUI 日志 |
| `runs/` | 历史 GUI 运行产物 |
| `_quarantine_20260629/legacy_gui_frontend/` | 已隔离的 PySide6 界面和启动脚本 |
| `_quarantine_20260629/legacy_gui_core/` | 已隔离的历史 runner/校验源码副本 |

## 数据来源

当前回测主线统一读取 TP canonical 数据：

- `C:\GoogleDrive\TP\screen\screen_aggregate.parquet`
- `C:\GoogleDrive\TP\screen\returns.parquet`
