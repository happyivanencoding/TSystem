# Regime Detection Model (Bottom-Up)

用 `screen_aggregate`（月度个股横截面）+ `returns`（日度收益）为**美国(SP500)** 与 **欧洲(STOXX EUROPE 600)** 分别构建市场状态(regime)识别模型。

## 方法
Bottom-up：把指数成分的个股横截面信息聚合为"市场状态"月度特征，再做无监督状态识别（计划用 HMM）。

## 数据

数据路径统一来自 TP canonical 数据源；规则见 [`../DATA_SOURCES.md`](../DATA_SOURCES.md) 和 [`../DATA_CONTRACT.md`](../DATA_CONTRACT.md)。

- `screen_aggregate.parquet`：月度个股横截面，按 `Weight in SP500` / `Weight in STOXX EUROPE 600` > 0 做 point-in-time 成分筛选。
- `returns.parquet`：日度个股收益（2005~），列名去 `-R` 后对齐 `Company SEDOL` 前6位。
- 区间：**2009-03 ~ 2026-05**（指数权重最早可用月份），约 200 个月度样本。
- 月度收益用 `Total Return`（截至当月末已实现，无前视；`TTR_Fwd1M` 仅留作打标/验证）。

## 特征（US 37 个 / EU 32 个，按月按地区）
- screen 横截面：估值水平/分散、盈利修正广度/成长、质量/杠杆、波动水平/分散、动量、已实现收益分散/偏度/宽度。
- 因子多空价差(Value/Quality/Mom/LowVol)：每月在 区域×行业 组内做 rank 中性化(小组<5 剔除)，t-1 分位 × t 收益。
- 周期-防御板块价差 `cyc_def_spread`：周期板块月度收益均值 − 防御板块(食品饮料/医疗/电信/公用)均值，risk-on/off 信号。
- 日度衍生(`returns.parquet`)：年化已实现波动 `rvol_ann`、成分平均两两相关性 `avg_corr`、近月下跌交易日占比 `down_day_freq`。
- 宏观金融条件(`macro_data.parquet`)：US 使用 `BFCIUS Index` 与 EWMA，EU 使用 `BFCIEU Index` 与 EWMA；另从 `maj cycle macro2.xlsx` 统一接入 US/EU 的 Citi Economic Surprise 与 BNP Positioning raw/EWMA。macro2 缺失日期只在两个有效观测之间按时间线性插值，不做首尾外推。
- 选定的单股波动衍生变量：US K4 主模型接入 `Daily Vol 60J/90J/260J` 的短长波动比与短波动高于长波动占比；EU K4 测试变差，暂不接入。

## 模型
- 预处理：少量缺失前向填充；高偏特征(`ret_skew`,`spread_*`)稳健缩放(RobustScaler)，其余标准化(StandardScaler)。
- 模型：GaussianHMM(**diag 协方差**，避免 200 样本下 full 过参数化)。
- 粘滞度控制：`transmat_prior` 对角加权(`STICKINESS_KAPPA`)鼓励自转移，减少跳变。
- 选 K：提供 BIC 拐点(knee)法参考(BIC 常单调到边界，全局最小不可取)；生产环境 **EU/US 统一固定 K=4**(`config.FIXED_K`)，便于跨市场状态对应与向客户解释。
- 状态按"市场压力"(`rvol_ann`+`avg_corr`)升序排序命名：扩张/平稳/震荡/危机。
- 验证：用 `TTR_Fwd1M` 成分等权计算各状态前瞻月收益均值/波动/胜率。

## 样本外滚动 (`walkforward.py`)
扩展窗口逐月重拟合，标准化器与 HMM 仅在当前窗口内拟合(严格无前视)，每次按压力排序对齐标签，取末月作 OOS nowcast。更贴近实盘，可见中间态在 OOS 下有抖动(状态多+样本少的固有代价)，危机态识别稳健。

## 风险仪表盘 (Web App)
浅色 Material 风格静态网页，组合 **HMM 状态 + Ridge 波动预测**，重点在**可解释性**：
- 当前波动预测的逐变量贡献(标准化值×系数，红=推高风险/绿=压低)；
- Ridge 全局系数方向；当前 HMM 状态的特征画像；
- 配置信号：波动目标/预测波动→波动权重 ×状态系数→建议权益配置。

```bash
python export_dashboard.py        # 生成 webapp/data.js
# 直接双击 webapp/index.html 打开(需联网加载 Chart.js)，或起本地服务：
python -m http.server 49231 --directory webapp   # 浏览器访问 http://localhost:49231
```

## 范式对比脚本
- `ml_compare.py`：预测下月涨跌(方向) OOS 对比 基准/HMM/Logistic+ML_IF/GBM+ML_IF；`Score ML_IF` 接入测试有增量的监督模型。
- `vol_compare.py`：预测下月波动/回撤 OOS 对比 持续性/HMM/Ridge+ScreenVol/GBM+ML_IF+ScreenVol；`Score ML_IF` 与单股波动衍生变量按地区/目标选择性接入。
- 结论：方向几乎不可预测、ML 不优于买入持有；波动可预测但点预测用 Ridge/持续性更佳，HMM 强在离散状态识别与危机预警。
- `.codex_tmp/regime_macro_research/bottom_up_period_hmm_research.py`：post-2020 K3 regime-break 研究配置额外加入 `regime_break_mlif_selected` 与 `regime_break_screen_vol_selected`。

## 用法
```bash
pip install -r requirements.txt
python build_features.py   # 1) 生成 output/features_{US,EU}.parquet
python train_regime.py     # 2) 全样本HMM, 生成 output/regime_{US,EU}.parquet 与 .png
python walkforward.py      # 3) 样本外滚动, 生成 output/regime_oos_{US,EU}.parquet 与 .png
python export_dashboard.py # 4) 生成仪表盘数据 webapp/data.js
```

## 文件
- `config.py` 路径/地区/起始日期/特征字段配置
- `data_loader.py` 加载 screen 与 PIT 成分筛选
- `features.py` screen 横截面聚合特征
- `returns_loader.py` 日度收益衍生特征(波动/相关性/下跌频率)
- `build_features.py` 入口1，落地特征表
- `model.py` 预处理 + HMM(diag+粘滞+BIC选K) + 状态标注与验证
- `train_regime.py` 入口2，全样本状态序列、验证表与可视化
- `walkforward.py` 入口3，样本外滚动 OOS 状态序列与可视化


## 组合风险预算输出

Regime 模型接入组合层的标准出口是风险预算乘数：

```powershell
python C:\GoogleDrive\TP\03_regime_model\export_risk_budget.py
```

默认输出 `C:\GoogleDrive\TP\04_signals\regime_risk_budget.parquet`，其中 `signal_family=Regime`、`signal_name=risk_budget_multiplier`、`scope=region`。当前映射规则：扩张/Risk-On 为 1.10，震荡为 0.90，压力或 Risk-Off 为 0.70，其余为 1.00。

可用 `--oos` 导出 walk-forward 状态版本；`--calibrated` 会用历史同状态前瞻收益校准风险预算乘数，目前作为研究开关保留，未作为默认生产映射。
