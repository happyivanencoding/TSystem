# Regime Detection Model

## 定位

用 TP Canonical Screen/returns 为 US 与 EU 构建 bottom-up 市场状态、波动预测和组合风险预算。活跃实现位于 `src/tp_models/regime/`；本目录只保存模型输出、静态风险页面和资源。

## 数据

- Screen：通过当期 `Weight in SP500`、`Weight in STOXX EUROPE 600` 定义 PIT universe。
- Returns：计算实现波动、相关性、下跌频率和状态标签。
- Macro：`00_screen/macro_data.parquet` 及显式配置的宏观输入。
- 未来收益、波动和回撤只作为验证标签，不进入同日状态。

路径与契约见根目录 `DATA_SOURCES.md`、`DATA_CONTRACT.md`。

## 方法

- 将个股估值、修正、质量、风险、动量和收益分布聚合成区域月度特征。
- Gaussian HMM 使用对角协方差和粘滞转移先验；生产 US/EU 固定 K=4。
- 状态按压力排序为扩张、平稳、震荡、危机。
- Walk-forward 扩展窗口逐月重拟合，标准化器和 HMM 只使用当前已知样本。
- 风险预算默认 hybrid：US 使用 walk-forward HMM 映射，EU 使用 PIT 已实现波动连续缩放。

## 生产入口

```powershell
python -m tp_pipelines.refresh_regime
```

该入口负责生成模型专项输出、静态页面数据、标准风险预算信号、pipeline manifest 和 Run Card。

专项研究可以使用当前包模块：

```powershell
python -m tp_models.regime.build_features
python -m tp_models.regime.train_regime
python -m tp_models.regime.walkforward
python -m tp_models.regime.export_dashboard
python -m tp_models.regime.export_risk_budget
```

静态页面可用：

```powershell
python -m http.server 49231 --directory 03_regime_model/webapp
```

不得执行 `03_regime_model` 资源目录中的旧 Python 文件。

## 主要输出

| 输出 | 位置 |
| --- | --- |
| Features、状态、诊断和图片 | `03_regime_model/output/` |
| 静态页面数据 | `03_regime_model/webapp/data.js` |
| 标准风险预算信号 | `artifacts/signals/regime_risk_budget.parquet` |
| Pipeline manifest | `artifacts/pipeline_runs/manifests/refresh_regime/` |
| Experiment/Run Card | `artifacts/pipeline_runs/experiments/` |

标准信号包含 `signal_family=Regime`、`signal_name=risk_budget_multiplier` 和区域 scope。`--oos` 导出 walk-forward 版本；`--calibrated` 仅为研究开关。

## 包结构

| 模块 | 职责 |
| --- | --- |
| `tp_models.regime.config` | 地区、特征和模型参数 |
| `data_loader`、`returns_loader` | PIT Screen 与日频收益输入 |
| `features`、`build_features` | 月度市场特征 |
| `model`、`train_regime` | HMM、状态标注和验证 |
| `walkforward` | 严格样本外 nowcast |
| `risk_budget_model`、`export_risk_budget` | 风险预算公共出口 |
| `export_dashboard` | 静态页面数据 |

## 维护状态

活跃模型。资源目录中的 `output/` 从工程 discovery 排除；跨项目消费者只读取标准 signal 或显式公共 API。
