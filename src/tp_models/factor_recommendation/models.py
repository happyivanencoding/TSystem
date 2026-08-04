"""推荐模型与透明 fallback。

Ridge/ElasticNet 仅在调用时尝试导入 scikit-learn。缺少可选依赖时，
Ridge 使用 numpy 闭式实现；ElasticNet 明确降级到 numpy ridge，而不是
伪造一个概率或静默改变模型名称。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from .contracts import DATE_COLUMN, ModelFit


def _feature_frame(frame: pd.DataFrame, feature_names: Iterable[str]) -> pd.DataFrame:
    names = tuple(feature_names)
    missing = [name for name in names if name not in frame.columns]
    if missing:
        raise KeyError(f"model feature columns missing: {missing}")
    out = frame.loc[:, names].apply(pd.to_numeric, errors="coerce")
    return out


class NumpyRidgeRegressor:
    """没有 sklearn 时使用的确定性 ridge 回归。"""

    def __init__(self, feature_names: tuple[str, ...], alpha: float = 1.0) -> None:
        self.feature_names = feature_names
        self.alpha = float(alpha)
        self.fill_values = np.zeros(len(feature_names), dtype=float)
        self.coef_ = np.zeros(len(feature_names), dtype=float)
        self.intercept_ = 0.0

    def fit(self, x: pd.DataFrame, y: pd.Series) -> "NumpyRidgeRegressor":
        numeric = _feature_frame(x, self.feature_names)
        self.fill_values = numeric.median(axis=0).fillna(0.0).to_numpy(dtype=float)
        matrix = numeric.fillna(pd.Series(self.fill_values, index=self.feature_names)).to_numpy()
        target = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
        design = np.column_stack([np.ones(len(matrix)), matrix])
        penalty = np.eye(design.shape[1], dtype=float) * self.alpha
        penalty[0, 0] = 0.0
        solution = np.linalg.pinv(design.T @ design + penalty) @ design.T @ target
        self.intercept_ = float(solution[0])
        self.coef_ = np.asarray(solution[1:], dtype=float)
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        numeric = _feature_frame(x, self.feature_names)
        matrix = numeric.fillna(pd.Series(self.fill_values, index=self.feature_names)).to_numpy()
        return self.intercept_ + matrix @ self.coef_


class MeanRegressor:
    """数据不足时的透明 baseline，不产生概率。"""

    def __init__(self, feature_names: tuple[str, ...], value: float = 0.0) -> None:
        self.feature_names = feature_names
        self.value = float(value)

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return np.full(len(x), self.value, dtype=float)


@dataclass(frozen=True)
class ModelSpec:
    model_type: str = "ridge"
    alpha: float = 1.0
    l1_ratio: float = 0.5


def _infer_features(frame: pd.DataFrame, target_column: str | None = None) -> tuple[str, ...]:
    excluded = {
        DATE_COLUMN,
        "target_date",
        "feature_as_of_date",
        "region",
        "research_only",
        "benchmark_approved",
    }
    if target_column:
        excluded.add(target_column)
    return tuple(
        column
        for column in frame.columns
        if column not in excluded
        and not str(column).startswith(("target_", "long_", "short_", "coverage_"))
        and pd.api.types.is_numeric_dtype(frame[column])
    )


def fit_model(
    x: pd.DataFrame,
    y: pd.Series,
    *,
    model_type: str = "ridge",
    alpha: float = 1.0,
    l1_ratio: float = 0.5,
    feature_names: Iterable[str] | None = None,
    require_real_backend: bool = False,
) -> ModelFit:
    """拟合单个回归模型并返回 backend/fallback 元数据。"""

    model_name = str(model_type).lower()
    if model_name not in {"ridge", "elasticnet", "mean"}:
        raise ValueError("model_type must be ridge, elasticnet or mean")
    names = tuple(feature_names or _infer_features(x))
    if not names:
        names = ("__intercept_only__",)
        x = pd.DataFrame({names[0]: np.zeros(len(x))}, index=x.index)
    values = _feature_frame(x, names)
    target = pd.to_numeric(y, errors="coerce")
    valid = target.notna()
    values = values.loc[valid]
    target = target.loc[valid]
    if target.empty:
        return ModelFit(
            model_name=model_name,
            backend="mean_fallback",
            feature_names=names,
            estimator=MeanRegressor(names, 0.0),
            trained_rows=0,
            fallback_reason="no finite training targets",
        )
    if model_name == "mean":
        return ModelFit(
            model_name=model_name,
            backend="mean",
            feature_names=names,
            estimator=MeanRegressor(names, float(target.mean())),
            trained_rows=int(len(target)),
        )
    try:
        from sklearn.linear_model import ElasticNet, Ridge
    except ImportError as exc:
        if require_real_backend:
            raise RuntimeError(
                f"{model_name} requires the declared sklearn backend; fallback is disabled"
            ) from exc
        estimator = NumpyRidgeRegressor(names, alpha=max(float(alpha), 0.0)).fit(values, target)
        return ModelFit(
            model_name=model_name,
            backend="numpy_ridge_fallback",
            feature_names=names,
            estimator=estimator,
            trained_rows=int(len(target)),
            fallback_reason=f"scikit-learn unavailable: {exc}",
        )
    fill_values = values.median(axis=0).fillna(0.0)
    filled = values.fillna(fill_values)
    if model_name == "ridge":
        estimator = Ridge(alpha=float(alpha))
    else:
        estimator = ElasticNet(alpha=float(alpha), l1_ratio=float(l1_ratio), max_iter=10000)
    estimator.fit(filled, target)

    class _ImputedEstimator:
        def predict(self, frame: pd.DataFrame) -> np.ndarray:
            prepared = _feature_frame(frame, names).fillna(fill_values)
            return np.asarray(estimator.predict(prepared), dtype=float)

    return ModelFit(
        model_name=model_name,
        backend="sklearn",
        feature_names=names,
        estimator=_ImputedEstimator(),
        trained_rows=int(len(target)),
    )


def predict_model(model: ModelFit, frame: pd.DataFrame) -> np.ndarray:
    return np.asarray(model.estimator.predict(frame), dtype=float)


def fit_factor_models(
    frame: pd.DataFrame,
    factor_names: Iterable[str],
    *,
    feature_columns: Iterable[str] | None = None,
    target_prefix: str = "target_",
    model_type: str = "ridge",
    alpha: float = 1.0,
    l1_ratio: float = 0.5,
) -> dict[str, ModelFit]:
    """为每个因子目标训练一个模型；缺少目标列时保留 fallback 记录。"""

    names = tuple(feature_columns or _infer_features(frame))
    x = frame if names else pd.DataFrame(index=frame.index)
    models: dict[str, ModelFit] = {}
    for factor in tuple(factor_names):
        target_column = f"{target_prefix}{factor}"
        target = frame[target_column] if target_column in frame.columns else pd.Series(
            np.nan, index=frame.index
        )
        models[factor] = fit_model(
            x,
            target,
            model_type=model_type,
            alpha=alpha,
            l1_ratio=l1_ratio,
            feature_names=names,
        )
        if target_column not in frame.columns:
            models[factor] = ModelFit(
                model_name=models[factor].model_name,
                backend=models[factor].backend,
                feature_names=models[factor].feature_names,
                estimator=models[factor].estimator,
                trained_rows=models[factor].trained_rows,
                fallback_reason=f"missing target column: {target_column}",
            )
    return models


def predict_factor_recommendations(
    models: Mapping[str, ModelFit],
    latest_features: pd.DataFrame,
    *,
    region: str | None = None,
    as_of_date: pd.Timestamp | str | None = None,
    model_version: str = "factor_recommendation_v1",
) -> pd.DataFrame:
    """输出预测排序；回归模型不提供 probability，字段保持 NA。"""

    if latest_features.empty:
        return pd.DataFrame(
            columns=[
                "region",
                DATE_COLUMN,
                "factor",
                "model_version",
                "prediction",
                "rank",
                "probability",
                "probability_available",
                "model_backend",
                "fallback_reason",
            ]
        )
    date_value = as_of_date
    if date_value is None and DATE_COLUMN in latest_features.columns:
        date_value = latest_features[DATE_COLUMN].iloc[0]
    predictions: list[dict[str, object]] = []
    for factor, model in sorted(models.items()):
        prediction = float(predict_model(model, latest_features)[0])
        predictions.append(
            {
                "region": region,
                DATE_COLUMN: pd.Timestamp(date_value) if date_value is not None else pd.NaT,
                "factor": factor,
                "model_version": model_version,
                "prediction": prediction,
                "probability": np.nan,
                "probability_available": False,
                "model_backend": model.backend,
                "fallback_reason": model.fallback_reason,
            }
        )
    result = pd.DataFrame(predictions)
    result["rank"] = result["prediction"].rank(ascending=False, method="min").astype(int)
    return result.sort_values(["rank", "factor"]).reset_index(drop=True)


# 简短别名，方便 CLI / notebook 使用。
fit_factor_recommendation_models = fit_factor_models
predict_recommendations = predict_factor_recommendations


__all__ = [
    "ModelSpec",
    "NumpyRidgeRegressor",
    "fit_factor_models",
    "fit_factor_recommendation_models",
    "fit_model",
    "predict_factor_recommendations",
    "predict_model",
    "predict_recommendations",
]
