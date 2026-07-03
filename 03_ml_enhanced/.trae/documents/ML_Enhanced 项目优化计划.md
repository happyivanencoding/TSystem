## 快速收益
- 关闭或抽样计算 SHAP：生产默认关闭，或对 `X_predict` 抽样 1–2k 行；用 `pred_contribs=True` 近似替代 TreeExplainer，显著缩短时间（Codes/ML_PREDICTOR.py:107-117, 320-333）。
- 启用 XGBoost 快速树构建：设置 `tree_method='hist'`，并指定 `n_jobs=os.cpu_count()-1`；降精度为 `float32` 以减少内存与加速（Codes/ML_PREDICTOR.py:90-103）。
- 早停以减少迭代：加入 `early_stopping_rounds` 与一个轻量验证集（训练窗口末月），在回测/生产均有效（Codes/ML_PREDICTOR.py:104, 271-303）。

## 并行与线程
- 避免线程过度竞争：当使用 `multiprocessing.Pool` 时，将 XGBoost 的 `n_jobs=1`；当关闭 Pool（`allow_multiprocessing=False`）时，打开 `n_jobs=os.cpu_count()-1`，一般更快（Codes/ML_PREDICTOR.py:281-289, 299-303）。
- Windows 入口守卫：确保入口脚本/Notebook 含 `if __name__ == "__main__":` 防止子进程开销异常（现有并行位于回测路径）。

## 预处理加速
- 累计收益缓存：`cum_returns = (1 + self.df_returns).cumprod()` 现每个 horizon 重算，移动为类级缓存一次复用（Codes/ML_PREPROCESS.py:81-87, 421-427）。
- 合并对齐降成本：`merge_asof` 改为按月末直接 join（两侧已对齐到月末），或将 `tolerance` 改为配置参数以减少匹配计算量（Codes/ML_PIPELINE.py:80-83, 196-205）。
- 变化特征填充策略：对非股息变化不再 `fillna(0)`，统一在 `fill_nan_values` 做中位数填充，减少无效波动与后续计算量（Codes/ML_PREPROCESS.py:251-253, 340-347）。

## 训练/预测路径细化
- 数据类型优化：在 `split_train_test_set` 后，将 `X_train/X_predict/y_train` 转 `float32`；传 numpy 数组，降低 pandas 开销（Codes/ML_PREDICTOR.py:54-62）。
- 约束传参修正：将 `monotone_constraints` 由 dict 转成与 `features` 顺序对齐的列表/字符串，减少内部检查与提升稳定性（Codes/ML_PREDICTOR.py:90-103; Config/config_*.py:74-110）。

## I/O 与合并
- 避免频繁 reset/set_index：保留 MultiIndex 流转，减少重复构造索引的成本（Codes/ML_PIPELINE.py:81-84, 169-175）。
- 写出仅在需要时：生产模式只保存最近一月（现有已如此），回测批量写出尽量合并一次（Codes/ML_PREDICTOR.py:396-411）。

## 最小测试（运行后清理）
- `calculate_offset_change` 月频差分一致性与边界（Codes/ML_PREPROCESS.py:184-208）。
- `split_train_test_set` 切分无重叠与行列对齐（Codes/ML_PREDICTOR.py:47-63）。
- `update_screen_aggregate`：月末直接 join/降低 `tolerance` 下更新行数正确（Codes/ML_PIPELINE.py:146-252）。

## 实施顺序
1) 缓存累计收益与 SHAP 抽样/关闭；2) 启用 `hist` 与 `n_jobs`、`float32`；3) 加入早停与轻量验证集；4) 优化合并与索引操作；5) 修正约束传参；6) 补最小测试。