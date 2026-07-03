# 冻结目录与引用规则

## 当前冻结目录

以下目录已经移动到 `99_archive/frozen_20260629/`，只保留历史追溯价值：

| 原目录 | 当前位置 | 状态 |
| --- | --- | --- |
| `ML/` | `99_archive/frozen_20260629/ML/` | 冻结 |
| `ML第一版/` | `99_archive/frozen_20260629/ML第一版/` | 冻结 |
| `回测第一版/` | `99_archive/frozen_20260629/回测第一版/` | 冻结 |
| `factsetProd第一版/` | `99_archive/frozen_20260629/factsetProd第一版/` | 冻结 |
| `技术分析和深度学习/技术分析_V1/` | `99_archive/frozen_20260629/技术分析和深度学习__技术分析_V1/` | 冻结 |

详细回滚信息见 `99_archive/frozen_20260629/manifest.json`。

## 规则

- 新代码不得直接 import、读取或依赖冻结目录。
- 新 notebook 不得从冻结目录复制路径作为输入。
- 如需复用旧逻辑，先迁移到当前主线目录或 `01_tp_core/`，再补测试和中文说明。
- 文档可以提到冻结目录，但必须明确其历史状态，不能把它写成当前入口。

## 检查命令

```powershell
python -m 01_tp_core.legacy_policy
```

或安装为脚本后运行：

```powershell
tp-check-legacy-references
```
