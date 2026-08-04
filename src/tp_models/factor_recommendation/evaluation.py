"""按月分组的时间评估，不把同一月份拆到 train/test 两侧。"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .contracts import DATE_COLUMN, EvaluationResult
from .models import fit_model, predict_model


def same_month_grouped_folds(
    dates: Iterable[pd.Timestamp | str],
    *,
    n_splits: int = 5,
    expanding: bool = True,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """生成月度 group folds。

    默认 expanding 模式只用测试月份之前的月份训练；无论模式如何，同一
    月份的行都只会出现在 train 或 test 一侧。
    """

    if n_splits < 1:
        raise ValueError("n_splits must be >= 1")
    date_values = pd.to_datetime(pd.Series(list(dates)), errors="coerce")
    if date_values.isna().any():
        raise ValueError("dates contain invalid values")
    groups = date_values.dt.to_period("M")
    unique_groups = pd.Index(sorted(groups.unique()))
    if len(unique_groups) < 2:
        return []
    if expanding:
        test_groups = unique_groups[1:]
        chunks = np.array_split(test_groups.to_numpy(), min(n_splits, len(test_groups)))
    else:
        chunks = np.array_split(unique_groups.to_numpy(), min(n_splits, len(unique_groups)))
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for chunk in chunks:
        if len(chunk) == 0:
            continue
        test_mask = groups.isin(chunk).to_numpy()
        if expanding:
            first_test = chunk[0]
            train_mask = (groups < first_test).to_numpy()
        else:
            train_mask = ~test_mask
        train_index = np.flatnonzero(train_mask)
        test_index = np.flatnonzero(test_mask)
        if len(train_index) and len(test_index):
            folds.append((train_index, test_index))
    return folds


def _spearman(actual: pd.Series, predicted: pd.Series) -> float:
    if len(actual) < 2:
        return float("nan")
    return float(actual.rank().corr(predicted.rank()))


def _metric_payload(actual: pd.Series, predicted: pd.Series) -> dict[str, float]:
    if actual.empty:
        return {"mae": float("nan"), "rmse": float("nan"), "spearman": float("nan")}
    error = predicted - actual
    return {
        "mae": float(error.abs().mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "spearman": _spearman(actual, predicted),
    }


def evaluate_factor_models(
    frame: pd.DataFrame,
    factor_names: Iterable[str],
    *,
    feature_columns: Iterable[str] | None = None,
    target_prefix: str = "target_",
    model_type: str = "ridge",
    alpha: float = 1.0,
    l1_ratio: float = 0.5,
    n_splits: int = 5,
) -> EvaluationResult:
    """做严格月度 grouped walk-forward 评估。"""

    if DATE_COLUMN not in frame.columns:
        raise KeyError(f"frame must contain {DATE_COLUMN}")
    source = frame.copy()
    source[DATE_COLUMN] = pd.to_datetime(source[DATE_COLUMN], errors="coerce")
    if source[DATE_COLUMN].isna().any():
        raise ValueError("frame contains invalid evaluation dates")
    factor_names = tuple(factor_names)
    names = tuple(feature_columns or [
        column
        for column in source.columns
        if column not in {DATE_COLUMN, "target_date", "feature_as_of_date"}
        and not str(column).startswith(("target_", "long_", "short_", "coverage_"))
        and pd.api.types.is_numeric_dtype(source[column])
    ])
    folds = same_month_grouped_folds(source[DATE_COLUMN], n_splits=n_splits, expanding=True)
    prediction_rows: list[dict[str, object]] = []
    for fold_id, (train_index, test_index) in enumerate(folds):
        train = source.iloc[train_index]
        test = source.iloc[test_index]
        for factor in factor_names:
            target_column = f"{target_prefix}{factor}"
            if target_column not in source.columns:
                continue
            model = fit_model(
                train.loc[:, names],
                train[target_column],
                model_type=model_type,
                alpha=alpha,
                l1_ratio=l1_ratio,
                feature_names=names,
            )
            actual = pd.to_numeric(test[target_column], errors="coerce")
            valid = actual.notna()
            if not valid.any():
                continue
            predicted = predict_model(model, test.loc[:, names])
            for row_position, prediction, actual_value in zip(
                test.index[valid], predicted[valid.to_numpy()], actual.loc[valid]
            ):
                prediction_rows.append(
                    {
                        DATE_COLUMN: source.loc[row_position, DATE_COLUMN],
                        "factor": factor,
                        "fold": fold_id,
                        "prediction": float(prediction),
                        "actual": float(actual_value),
                        "model_backend": model.backend,
                        "probability": np.nan,
                        "probability_available": False,
                    }
                )
    predictions = pd.DataFrame(prediction_rows)
    metrics: dict[str, object] = {
        "fold_count": int(len(folds)),
        "prediction_count": int(len(predictions)),
        "probability_available": False,
        "probability_note": "regression outputs are not probabilities",
        "factors": {},
    }
    if not predictions.empty:
        for factor, group in predictions.groupby("factor", sort=True):
            metrics["factors"][factor] = _metric_payload(group["actual"], group["prediction"])
    for factor in factor_names:
        metrics["factors"].setdefault(
            factor,
            {"mae": float("nan"), "rmse": float("nan"), "spearman": float("nan")},
        )
    return EvaluationResult(
        metrics=metrics,
        predictions=predictions,
        probability_available=False,
        probability_note="regression outputs are not probabilities",
    )


evaluate_models = evaluate_factor_models
grouped_month_folds = same_month_grouped_folds


__all__ = [
    "evaluate_factor_models",
    "evaluate_models",
    "grouped_month_folds",
    "same_month_grouped_folds",
]
