# Research artifacts

- `runs/`：配置化研究的新 Run Card 与产物。
- `runs/historical/`：从 `07_backtest_code` 无损迁移的只读历史证据；禁止新写入。
- `migrations/`：迁移 manifest 和逐文件 inventory，永久保留。
- `features/`：版本化 shadow feature cache，由保留策略管理。

历史库中少量路径超过 Windows 普通 `MAX_PATH`。TP 的迁移和 Dashboard 发现代码使用长路径安全扫描；人工访问时优先从较短的上层目录进入，不要重命名历史文件来规避长度限制。
