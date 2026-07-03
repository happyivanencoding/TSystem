## 关键瓶颈

* SHAP 计算对每个滚动窗口执行，耗时与样本量线性增长（Codes/ML\_PREDICTOR.py:108-117）。

* 回测使用多进程与 XGBoost 默认多线程叠加，出现过度并发（Codes/ML\_PREDICTOR.py:281-289 与 90-102）。

* 预处理中累计收益每次重复构造与 `expanding.std()` 计算代价高（Codes/ML\_PREPROCESS.py:82-87, 169-174）。

* 频繁深拷贝与重复 `reset_index()/set_index()` 增加开销（Codes/ML\_PREDICTOR.py:86-87, 180-183, 318-333；Codes/ML\_PREPROCESS.py 多处）。

## 最小改动优化建议

* 控制 SHAP：新增参数 `compute_shap`；生产开启，回测默认关闭或抽样（如随机抽取 `n_rows=2000`），或使用 `approximate=True/nsamples=128`（Codes/ML\_PREDICTOR.py:108-117）。

* XGBoost 加速：显式 `tree_method='hist'`；若有 NVIDIA GPU，改为 `gpu_hist` + `predictor='gpu_predictor'`（需确认 CUDA）（Codes/ML\_PREDICTOR.py:90-102）。

* 线程数治理：在多进程回测时设置模型 `n_jobs=1`，单进程（生产）设为 `os.cpu_count()-1`，避免过度并发（Codes/ML\_PREDICTOR.py:281-289, 90-102）。

* 使用 DMatrix：训练/预测改用 `xgb.DMatrix(float32)`，减少 DataFrame->Numpy 转换与内存占用（Codes/ML\_PREDICTOR.py:104, 120）。

* 预处理提速：将 `cum_returns=(1+df_returns).cumprod()` 提升至 `preprocess()` 一次性计算并传入 `_compute_returns()`，避免对每个 horizon 重算（Codes/ML\_PREPROCESS.py:82-87, 421-428）。

* 固定窗口波动率：如业务允许，将 `expanding.std()` 改为 `rolling(window=12).std()`；若需保持 expanding，可尝试 `engine="numba"`（已安装时有效）（Codes/ML\_PREPROCESS.py:169-174）。

* 减少拷贝与索引切换：将多处 `copy(deep=True)` 改为 `copy()` 或直接引用，合并连续的 `reset_index()/set_index()` 操作（Codes/ML\_PREDICTOR.py:86-87, 318-333）。

* 排名一次性计算：将多期 `groupby('Date').rank()` 合并为一次批量列处理，减少多次分组（Codes/ML\_PREDICTOR.py:341-351）。

* 日志精简：保留关键阶段的汇总打印，减少高频输出（Codes/ML\_PIPELINE.py:88）。

## 预计收益

* 生产模式：在 CPU 上预计 20–25 秒；启用 GPU 进一步下降。

* 回测模式：窗口数较多时提升 30–60%，取决于 SHAP 策略与并发治理。

## 验证与安全

* 在 `predict()` 与 SHAP 处加轻量计时（`time.perf_counter()`），输出阶段耗时摘要，确保不影响现有功能。

* 对比优化前后 `Score ML` 分布（均值/分位数）与行数一致性，验证无功能破坏。

## 需要你确认/配置

* 回测是否允许关闭 SHAP 或改为抽样/近似。

* 是否具备 NVIDIA GPU（CUDA 可用），以启用 `gpu_hist` 加速。

* 信息比率的波动率计算是否可改为固定窗口（如 12 个月）。

