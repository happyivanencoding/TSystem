"""Factor-level panel, genuine M0--M4 models, allocation and gate helpers."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .v2_sleeves import V2_FACTOR_DEFINITIONS

V2_FACTOR_NAMES = tuple(str(item["name"]) for item in V2_FACTOR_DEFINITIONS)

MODEL_IDS = (
    "M0_equal_factor",
    "M1_trailing_12m",
    "M2_transparent_composite",
    "M3_pooled_ridge",
    "M4_pooled_elastic_net",
)
SELECTION_MODEL_IDS = MODEL_IDS[1:]
NO_VALID_MODEL = "no_valid_model"

FEATURE_COLUMNS = (
    "trailing_12m_active_return",
    "trailing_6m_active_return",
    "ewma_active_return",
    "ewma_3m_active_return",
    "ewma_6m_active_return",
    "volatility_12m",
    "drawdown_12m",
    "hit_rate_12m",
    "spread_12m",
    "turnover_12m",
    "holdings_count_z",
    "coverage",
    "weight_coverage",
    "rank_persistence_12m",
    "breadth_12m",
    "dispersion_12m",
    "score_delta_1m",
    "score_delta_3m",
    "score_delta_6m",
    "score_delta_12m",
    "directional_delta_1m",
    "directional_delta_3m",
    "directional_delta_6m",
    "directional_delta_12m",
    "cross_region_confirmation",
    "regime_alignment",
    "factor_rotation_proxy",
    "region_fixed_effect",
    "factor_fixed_effect",
    "region_factor_interaction",
    "factor_regime_interaction",
    "missing_indicator",
)


def _numeric(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if np.isfinite(number) else default


def _compound(values: pd.Series) -> float:
    values = pd.to_numeric(values, errors="coerce").dropna()
    return float((1.0 + values).prod() - 1.0) if len(values) else np.nan


def _rolling_compound(series: pd.Series, window: int) -> pd.Series:
    return series.shift(1).rolling(window, min_periods=1).apply(
        lambda values: _compound(pd.Series(values)), raw=False
    )


def _rolling_drawdown(series: pd.Series, window: int) -> pd.Series:
    prior = series.shift(1)
    wealth = (1.0 + prior.fillna(0.0)).cumprod()
    running = wealth.rolling(window, min_periods=1).max()
    return wealth / running - 1.0


def _rank_by_date(frame: pd.DataFrame, column: str, ascending: bool = True) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return frame.groupby(["Date", "region"], sort=False)[column].rank(
        pct=True, ascending=ascending, method="average"
    )


def cross_region_confirmation_feature(panel: pd.DataFrame) -> pd.Series:
    """Return prior-only confirmation for each Date x region x factor row.

    A row at decision date ``t`` can only see realised active returns from a
    *different* region at dates strictly before ``t``.  The current date is
    scored first and appended to history only after every region has been
    evaluated, so row order cannot introduce same-month target leakage.
    """

    if panel.empty:
        return pd.Series(dtype=float, index=panel.index)
    values = pd.Series(np.nan, index=panel.index, dtype=float)
    history: dict[str, list[tuple[str, str, float]]] = {}
    ordered = panel.sort_values(["Date", "factor", "region"], kind="stable")
    for date, date_rows in ordered.groupby("Date", sort=True):
        for index, row in date_rows.iterrows():
            factor = str(row["factor"])
            region = str(row["region"])
            prior = [value for prior_date, prior_region, value in history.get(factor, []) if prior_region != region and prior_date < str(pd.Timestamp(date)) and np.isfinite(value)]
            values.loc[index] = float(np.mean(np.asarray(prior, dtype=float) > 0.0)) if prior else np.nan
        for _, row in date_rows.iterrows():
            target = _numeric(row.get("next_month_top_sleeve_net_active_return"))
            if np.isfinite(target):
                history.setdefault(str(row["factor"]), []).append((str(pd.Timestamp(date)), str(row["region"]), target))
    return values.reindex(panel.index)


def build_factor_panel(sleeve_returns: pd.DataFrame) -> pd.DataFrame:
    """Build Date x Region x Factor features without a security identifier."""

    if sleeve_returns is None or sleeve_returns.empty:
        return pd.DataFrame(columns=["Date", "region", "factor", *FEATURE_COLUMNS])
    frame = sleeve_returns.copy()
    required = {"Date", "region_component", "factor", "sleeve_side", "net_return", "active_return"}
    missing = required - set(frame.columns)
    if missing:
        raise KeyError(f"sleeve returns missing panel columns: {sorted(missing)}")
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce").dt.normalize()
    frame = frame.loc[frame["sleeve_side"].eq("Top")].copy()
    if "sleeve_version" in frame.columns:
        primary = frame["sleeve_version"].astype(str).str.contains("p20", case=False, na=False)
        if primary.any():
            frame = frame.loc[primary].copy()
    frame = frame.sort_values(["region_component", "factor", "Date"], kind="stable")
    rows: list[pd.DataFrame] = []
    for (region, factor), group in frame.groupby(["region_component", "factor"], sort=False):
        current = group.sort_values("Date", kind="stable").copy()
        active = pd.to_numeric(current["active_return"], errors="coerce")
        net = pd.to_numeric(current["net_return"], errors="coerce")
        spread = pd.to_numeric(current.get("spread", pd.Series(np.nan, index=current.index)), errors="coerce")
        score = pd.to_numeric(current.get("factor_score", pd.Series(np.nan, index=current.index)), errors="coerce")
        current["region"] = str(region)
        current["next_month_top_sleeve_net_active_return"] = active
        current["next_month_top_sleeve_net_return"] = net
        current["next_month_top_sleeve_gross_return"] = pd.to_numeric(current.get("gross_return"), errors="coerce")
        current["next_month_top_sleeve_internal_cost"] = pd.to_numeric(current.get("internal_cost"), errors="coerce")
        current["next_month_region_benchmark_return"] = pd.to_numeric(current.get("benchmark_return"), errors="coerce")
        current["target_date"] = pd.to_datetime(current.get("target_date"), errors="coerce")
        current["trailing_12m_active_return"] = _rolling_compound(active, 12)
        current["trailing_6m_active_return"] = _rolling_compound(active, 6)
        current["ewma_3m_active_return"] = active.shift(1).ewm(span=3, min_periods=1, adjust=False).mean()
        current["ewma_6m_active_return"] = active.shift(1).ewm(span=6, min_periods=1, adjust=False).mean()
        current["ewma_active_return"] = current["ewma_6m_active_return"]
        current["volatility_12m"] = active.shift(1).rolling(12, min_periods=2).std()
        current["drawdown_12m"] = _rolling_drawdown(active, 12)
        current["hit_rate_12m"] = active.shift(1).gt(0).rolling(12, min_periods=1).mean()
        current["spread_12m"] = spread.shift(1).rolling(12, min_periods=1).mean()
        current["turnover_12m"] = pd.to_numeric(current.get("turnover"), errors="coerce").shift(1).rolling(12, min_periods=1).mean()
        holdings = pd.to_numeric(current.get("holdings_count"), errors="coerce")
        current["holdings_count_z"] = (holdings - holdings.shift(1).rolling(12, min_periods=2).mean()) / holdings.shift(1).rolling(12, min_periods=2).std().replace(0, np.nan)
        current["rank_persistence_12m"] = current["trailing_12m_active_return"].rank(pct=True)
        current["breadth_12m"] = current["hit_rate_12m"]
        current["dispersion_12m"] = active.shift(1).rolling(12, min_periods=2).std()
        for lag in (1, 3, 6, 12):
            current[f"score_delta_{lag}m"] = score - score.shift(lag)
            current[f"directional_delta_{lag}m"] = np.sign(current[f"score_delta_{lag}m"])
        current["coverage"] = pd.to_numeric(current.get("coverage"), errors="coerce")
        current["weight_coverage"] = pd.to_numeric(current.get("weight_coverage"), errors="coerce")
        missing_columns = [column for column in FEATURE_COLUMNS if column not in {"cross_region_confirmation", "regime_alignment", "missing_indicator"} and column in current.columns]
        current["missing_indicator"] = current[missing_columns].isna().mean(axis=1) if missing_columns else 1.0
        rows.append(current)
    panel = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if panel.empty:
        return panel
    panel["cross_region_confirmation"] = cross_region_confirmation_feature(panel)
    panel["regime_alignment"] = panel.groupby(["Date", "region"], sort=False)["trailing_12m_active_return"].rank(pct=True)
    panel["rank_persistence_12m"] = panel.groupby(["Date", "region"], sort=False)["trailing_12m_active_return"].rank(pct=True)
    panel["factor_rotation_proxy"] = panel.groupby(["Date", "region"], sort=False)["score_delta_1m"].transform(lambda values: values - values.mean())
    region_codes = {value: index for index, value in enumerate(sorted(panel["region"].astype(str).unique()))}
    factor_codes = {value: index for index, value in enumerate(sorted(panel["factor"].astype(str).unique()))}
    panel["region_fixed_effect"] = panel["region"].astype(str).map(region_codes).astype(float)
    panel["factor_fixed_effect"] = panel["factor"].astype(str).map(factor_codes).astype(float)
    panel["region_factor_interaction"] = panel["region_fixed_effect"] * (panel["factor_fixed_effect"] + 1.0)
    panel["factor_regime_interaction"] = panel["factor_fixed_effect"] * pd.to_numeric(panel["regime_alignment"], errors="coerce")
    panel["factor_description"] = panel["factor"].map({item["name"]: item["definition"] for item in V2_FACTOR_DEFINITIONS})
    panel["research_unit"] = "Date x Region x Factor"
    panel["target_definition"] = "next_month_top_sleeve_net_active_return"
    panel["feature_as_of_date"] = pd.to_datetime(panel.get("feature_as_of_date", panel["Date"]), errors="coerce").fillna(panel["Date"])
    panel["target_date"] = pd.to_datetime(panel.get("target_date"), errors="coerce")
    panel["target_date"] = panel["target_date"].fillna(panel["Date"] + pd.offsets.MonthEnd(1))
    panel["target_after_decision"] = panel["target_date"] > panel["Date"]
    panel = panel.drop(columns=[column for column in ("ISIN", "Company SEDOL", "security_id") if column in panel.columns])
    return panel.sort_values(["Date", "region", "factor"], kind="stable").reset_index(drop=True)


def make_smoke_sleeve_returns(
    *,
    months: int = 12,
    regions: Sequence[str] = ("US", "EUROPE", "JAPAN"),
    factors: Sequence[str] = V2_FACTOR_NAMES,
) -> pd.DataFrame:
    """Deterministic fixture used only by ``--smoke`` and unit tests."""

    dates = pd.date_range("2015-01-31", periods=max(2, months + 1), freq="ME")
    rows: list[dict[str, Any]] = []
    for region_index, region in enumerate(regions):
        for factor_index, factor in enumerate(factors):
            for side in ("Top", "Worst"):
                for date_index, date in enumerate(dates[:-1]):
                    base = 0.004 * ((factor_index + 1) / 8.0) + 0.001 * (date_index % 4)
                    top = base + 0.002 * (region_index + 1)
                    value = top if side == "Top" else -top * 0.7
                    score_factor_index = 5 if factor in {"size", "small_size"} else factor_index
                    raw_score = 50.0 + score_factor_index * 3.0 + date_index
                    size_score = raw_score / 10.0
                    small_size_score = 10.0 - size_score
                    rows.append(
                        {
                            "Date": date,
                            "feature_as_of_date": date,
                            "effective_start_date": date + pd.Timedelta(days=1),
                            "effective_end_date": dates[date_index + 1],
                            "target_date": dates[date_index + 1],
                            "region": region,
                            "region_component": region,
                            "benchmark": f"{region}_BENCHMARK",
                            "factor": factor,
                            "factor_source_column": "fixture",
                            "sleeve_side": side,
                            "sleeve_version": "v2-p20",
                            "gross_return": value + 0.0005,
                            "internal_cost": 0.0005,
                            "net_return": value,
                            "benchmark_return": 0.001,
                            "active_return": value - 0.001,
                            "spread": top - (-top * 0.7),
                            "top_worst_spread": top - (-top * 0.7),
                            "turnover": 0.1 + 0.01 * (factor_index % 3),
                            "holdings_count": 20,
                            "formation_available": True,
                            "coverage": 0.95,
                            "factor_coverage": 0.95,
                            "weight_coverage": 0.95,
                            "benchmark_weight_coverage": 0.95,
                            "benchmark_coverage": 0.95,
                            "minimum_constituents": 10,
                            "factor_score": small_size_score if factor == "small_size" else size_score,
                            "size_score": size_score if factor in {"size", "small_size"} else np.nan,
                            "small_size_score": small_size_score if factor in {"size", "small_size"} else np.nan,
                            "universe_count": 100,
                            "eligible_universe_rows": 100,
                            "valid_factor_rows": 100,
                            "factor_row_coverage": 1.0,
                            "eligible_benchmark_weight": 1.0,
                            "valid_factor_benchmark_weight": 1.0,
                            "factor_weight_coverage": 1.0,
                            "raw_benchmark_weight": 1.0,
                            "retained_country_weight": 1.0,
                            "retained_benchmark_coverage": 1.0,
                            "return_available_weight": 1.0,
                            "return_weight_coverage": 1.0,
                            "return_cell_coverage": 1.0,
                            "benchmark_return_coverage": 1.0,
                            "engine_id": "fixture.official_like",
                            "engine_version": "test",
                            "execution_policy": "strictly_after_rebalance; apply_weights_at_close",
                            "fingerprint": f"fixture-{region}-{factor}-{side}",
                        }
                    )
    return pd.DataFrame(rows)


@dataclass
class ModelFitRecord:
    model_id: str
    backend: str
    feature_columns: tuple[str, ...]
    train_rows: int
    train_start: str
    train_end: str
    imputer_medians: dict[str, float]
    scaler_mean: dict[str, float]
    scaler_scale: dict[str, float]
    coefficients: list[float]
    intercept: float
    hyperparameters: dict[str, Any]


def _model_formula_features(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    for column in FEATURE_COLUMNS:
        if column not in out.columns:
            out[column] = np.nan
    return out


def _m1_prediction(rows: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(rows["trailing_12m_active_return"], errors="coerce")


def _m2_prediction(rows: pd.DataFrame) -> pd.Series:
    def pct(column: str, ascending: bool = True) -> pd.Series:
        values = pd.to_numeric(rows[column], errors="coerce")
        return values.groupby([rows["Date"], rows["region"]], sort=False).rank(pct=True, ascending=ascending)

    formula = (
        0.35 * pct("trailing_12m_active_return")
        + 0.20 * pct("trailing_6m_active_return")
        + 0.15 * pct("breadth_12m")
        + 0.10 * pd.to_numeric(rows["coverage"], errors="coerce")
        + 0.10 * pct("drawdown_12m")
        + 0.10 * pd.to_numeric(rows["regime_alignment"], errors="coerce")
    )
    return formula.replace([np.inf, -np.inf], np.nan)


def _rank_ic(prediction: pd.Series, target: pd.Series) -> float:
    frame = pd.DataFrame({"prediction": prediction, "target": target}).dropna()
    if len(frame) < 3 or frame["prediction"].nunique() < 2 or frame["target"].nunique() < 2:
        return np.nan
    return float(frame["prediction"].corr(frame["target"], method="spearman"))


def _sklearn_fit(
    model_id: str,
    train: pd.DataFrame,
    *,
    ridge_alpha: float = 1.0,
    elastic_alpha: float = 0.01,
    l1_ratio: float = 0.5,
) -> tuple[Any, ModelFitRecord]:
    try:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import ElasticNet, Ridge
        from sklearn.preprocessing import StandardScaler
    except ImportError as error:
        raise RuntimeError("v2 M3/M4 require sklearn; no silent fallback is allowed") from error
    if model_id == "M3_pooled_ridge":
        estimator = Ridge(alpha=float(ridge_alpha))
        backend = "sklearn.linear_model.Ridge"
        hyperparameters = {"alpha": float(ridge_alpha)}
    elif model_id == "M4_pooled_elastic_net":
        estimator = ElasticNet(alpha=float(elastic_alpha), l1_ratio=float(l1_ratio), max_iter=20_000, random_state=1729)
        backend = "sklearn.linear_model.ElasticNet"
        hyperparameters = {"alpha": float(elastic_alpha), "l1_ratio": float(l1_ratio)}
    else:
        raise ValueError(f"not a sklearn candidate: {model_id}")
    features = _model_formula_features(train)
    target = pd.to_numeric(train["next_month_top_sleeve_net_active_return"], errors="coerce")
    valid = target.notna()
    features = features.loc[valid]
    target = target.loc[valid]
    feature_frame = features[list(FEATURE_COLUMNS)].copy()
    all_missing_features = [column for column in FEATURE_COLUMNS if feature_frame[column].notna().sum() == 0]
    if all_missing_features:
        feature_frame.loc[:, all_missing_features] = 0.0
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    x_imputed = imputer.fit_transform(feature_frame)
    x_scaled = scaler.fit_transform(x_imputed)
    estimator.fit(x_scaled, target.to_numpy(dtype=float))
    medians = dict(zip(FEATURE_COLUMNS, imputer.statistics_.astype(float)))
    means = dict(zip(FEATURE_COLUMNS, scaler.mean_.astype(float)))
    scales = dict(zip(FEATURE_COLUMNS, scaler.scale_.astype(float)))
    record = ModelFitRecord(
        model_id=model_id,
        backend=backend,
        feature_columns=tuple(FEATURE_COLUMNS),
        train_rows=len(target),
        train_start=str(pd.Timestamp(train["Date"].min()).date()),
        train_end=str(pd.Timestamp(train["Date"].max()).date()),
        imputer_medians=medians,
        scaler_mean=means,
        scaler_scale=scales,
        coefficients=[float(value) for value in np.asarray(estimator.coef_).ravel()],
        intercept=float(estimator.intercept_),
        hyperparameters={**hyperparameters, "all_missing_feature_fill": all_missing_features},
    )
    return (imputer, scaler, estimator), record


def _sklearn_predict(fit: tuple[Any, Any, Any], rows: pd.DataFrame) -> pd.Series:
    imputer, scaler, estimator = fit
    features = _model_formula_features(rows)
    values = scaler.transform(imputer.transform(features[list(FEATURE_COLUMNS)]))
    return pd.Series(estimator.predict(values), index=rows.index, dtype=float)


def select_champion(metrics: Mapping[str, Any]) -> str:
    """Select only among valid non-baseline candidates, with NaN last."""

    valid = [
        (str(model_id), float(value))
        for model_id, value in metrics.items()
        if str(model_id) in SELECTION_MODEL_IDS and np.isfinite(_numeric(value))
    ]
    if not valid:
        return NO_VALID_MODEL
    return max(valid, key=lambda item: (item[1], -SELECTION_MODEL_IDS.index(item[0])))[0]


def _hyperparameter_candidates(model_id: str, grid: Mapping[str, Any] | None) -> list[dict[str, float]]:
    values = grid or {}
    if model_id == "M3_pooled_ridge":
        return [{"ridge_alpha": float(value)} for value in values.get("ridge_alpha", (0.1, 1.0, 10.0))]
    if model_id == "M4_pooled_elastic_net":
        return [
            {"elastic_alpha": float(alpha), "l1_ratio": float(l1_ratio)}
            for alpha in values.get("elastic_net_alpha", (0.001, 0.01, 0.1))
            for l1_ratio in values.get("elastic_net_l1_ratio", (0.1, 0.5, 0.9))
        ]
    return [{}]


def _inner_rule_score(train: pd.DataFrame, model_id: str, *, purge_months: int, validation_months: int) -> float:
    dates = sorted(pd.Timestamp(value) for value in train["Date"].dropna().unique())
    folds: list[float] = []
    for validation_date in dates[-max(1, int(validation_months)) :]:
        cutoff = validation_date - pd.offsets.MonthEnd(int(purge_months))
        inner_dates = [date for date in dates if date < cutoff]
        if not inner_dates:
            continue
        validation = train.loc[train["Date"].eq(validation_date)]
        prediction = _m1_prediction(validation) if model_id == "M1_trailing_12m" else _m2_prediction(validation)
        folds.append(_rank_ic(prediction, pd.to_numeric(validation["next_month_top_sleeve_net_active_return"], errors="coerce")))
    numeric = pd.to_numeric(pd.Series(folds), errors="coerce").dropna()
    return float(numeric.mean()) if len(numeric) else np.nan


def select_hyperparameters(
    train: pd.DataFrame,
    model_id: str,
    *,
    hyperparameter_grid: Mapping[str, Any] | None,
    purge_months: int,
    validation_months: int,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Run every registered combo on expanding inner validation folds."""

    candidates = _hyperparameter_candidates(model_id, hyperparameter_grid)
    dates = sorted(pd.Timestamp(value) for value in train["Date"].dropna().unique())
    validation_dates = dates[-max(1, int(validation_months)) :]
    records: list[dict[str, Any]] = []
    scores: list[float] = []
    for candidate_index, params in enumerate(candidates):
        fold_scores: list[float] = []
        executed_folds = 0
        for validation_date in validation_dates:
            cutoff = validation_date - pd.offsets.MonthEnd(int(purge_months))
            training_dates = [date for date in dates if date < cutoff]
            inner_train = train.loc[train["Date"].isin(training_dates)].copy()
            validation = train.loc[train["Date"].eq(validation_date)].copy()
            if len(inner_train) < 3 or validation.empty:
                continue
            try:
                fit, _ = _sklearn_fit(
                    model_id,
                    inner_train,
                    ridge_alpha=params.get("ridge_alpha", 1.0),
                    elastic_alpha=params.get("elastic_alpha", 0.01),
                    l1_ratio=params.get("l1_ratio", 0.5),
                )
                score = _rank_ic(_sklearn_predict(fit, validation), pd.to_numeric(validation["next_month_top_sleeve_net_active_return"], errors="coerce"))
            except (RuntimeError, ValueError, TypeError):
                score = np.nan
            if np.isfinite(score):
                fold_scores.append(float(score))
            executed_folds += 1
            records.append(
                {
                    "model_id": model_id,
                    "candidate_index": candidate_index,
                    "params": json.dumps(params, sort_keys=True),
                    "inner_score": float(score) if np.isfinite(score) else np.nan,
                    "training_start": str(training_dates[0].date()) if training_dates else "",
                    "training_end": str(training_dates[-1].date()) if training_dates else "",
                    "validation_start": str(validation_date.date()),
                    "validation_end": str(validation_date.date()),
                    "executed": True,
                }
            )
        aggregate = float(np.mean(fold_scores)) if fold_scores else np.nan
        scores.append(aggregate)
    valid_scores = [(index, score) for index, score in enumerate(scores) if np.isfinite(score)]
    selected_index = max(valid_scores, key=lambda item: (item[1], -item[0]))[0] if valid_scores else 0
    selected = dict(candidates[selected_index]) if candidates else {}
    for record in records:
        record["selected"] = bool(record["candidate_index"] == selected_index)
        record["selection_status"] = "selected" if record["selected"] else "challenger"
    if not records:
        records.append(
            {
                "model_id": model_id,
                "candidate_index": selected_index,
                "params": json.dumps(selected, sort_keys=True),
                "inner_score": np.nan,
                "training_start": str(dates[0].date()) if dates else "",
                "training_end": str(dates[-1].date()) if dates else "",
                "validation_start": "",
                "validation_end": "",
                "executed": False,
                "selected": True,
                "selection_status": "no_inner_fold",
            }
        )
    return selected, records


def walk_forward_predictions(
    panel: pd.DataFrame,
    *,
    minimum_train_months: int = 60,
    purge_months: int = 1,
    ridge_alpha: float = 1.0,
    elastic_alpha: float = 0.01,
    l1_ratio: float = 0.5,
    hyperparameter_grid: Mapping[str, Any] | None = None,
    selection_metric: str = "rank_ic",
    inner_validation_months: int = 3,
    smoke: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Expanding monthly walk-forward with a real sklearn M3/M4 backend."""

    if panel.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, {"minimum_train_months": minimum_train_months}
    source = _model_formula_features(panel).copy()
    source["Date"] = pd.to_datetime(source["Date"], errors="coerce").dt.normalize()
    source = source.sort_values(["Date", "region", "factor"], kind="stable")
    dates = sorted(pd.Timestamp(value) for value in source["Date"].dropna().unique())
    min_train = min(int(minimum_train_months), 3) if smoke else int(minimum_train_months)
    predictions: list[dict[str, Any]] = []
    fit_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    hyperparameter_records: list[dict[str, Any]] = []
    for test_date in dates:
        cutoff = test_date - pd.offsets.MonthEnd(int(purge_months))
        train_dates = [date for date in dates if date < cutoff]
        if len(train_dates) < min_train:
            continue
        train = source.loc[source["Date"].isin(train_dates)].copy()
        test = source.loc[source["Date"].eq(test_date)].copy()
        if test.empty:
            continue
        candidate_predictions: dict[str, pd.Series] = {
            "M0_equal_factor": pd.Series(0.0, index=test.index),
            "M1_trailing_12m": _m1_prediction(test),
            "M2_transparent_composite": _m2_prediction(test),
        }
        candidate_train: dict[str, pd.Series] = {
            "M0_equal_factor": pd.Series(0.0, index=train.index),
            "M1_trailing_12m": _m1_prediction(train),
            "M2_transparent_composite": _m2_prediction(train),
        }
        fits: dict[str, tuple[Any, Any, Any]] = {}
        inner_scores: dict[str, float] = {
            "M0_equal_factor": np.nan,
            "M1_trailing_12m": _inner_rule_score(train, "M1_trailing_12m", purge_months=purge_months, validation_months=inner_validation_months),
            "M2_transparent_composite": _inner_rule_score(train, "M2_transparent_composite", purge_months=purge_months, validation_months=inner_validation_months),
        }
        for model_id in ("M3_pooled_ridge", "M4_pooled_elastic_net"):
            selected_params, candidate_records = select_hyperparameters(
                train,
                model_id,
                hyperparameter_grid=hyperparameter_grid,
                purge_months=purge_months,
                validation_months=inner_validation_months,
            )
            for candidate_record in candidate_records:
                hyperparameter_records.append({"outer_test_date": test_date, **candidate_record})
            selected_inner_scores = [
                _numeric(record.get("inner_score"))
                for record in candidate_records
                if bool(record.get("selected")) and np.isfinite(_numeric(record.get("inner_score")))
            ]
            inner_scores[model_id] = float(np.mean(selected_inner_scores)) if selected_inner_scores else np.nan
            fit, record = _sklearn_fit(
                model_id,
                train,
                ridge_alpha=selected_params.get("ridge_alpha", ridge_alpha),
                elastic_alpha=selected_params.get("elastic_alpha", elastic_alpha),
                l1_ratio=selected_params.get("l1_ratio", l1_ratio),
            )
            fits[model_id] = fit
            candidate_predictions[model_id] = _sklearn_predict(fit, test)
            candidate_train[model_id] = _sklearn_predict(fit, train)
            fit_rows.append({"test_date": test_date, **record.__dict__, "selected_inner_score": inner_scores[model_id], "feature_columns": json.dumps(list(record.feature_columns)), "imputer_medians": json.dumps(record.imputer_medians), "scaler_mean": json.dumps(record.scaler_mean), "scaler_scale": json.dumps(record.scaler_scale), "coefficients": json.dumps(record.coefficients), "hyperparameters": json.dumps(record.hyperparameters)})
        metrics = dict(inner_scores)
        selected_model = select_champion(metrics)
        fallback = selected_model == NO_VALID_MODEL
        reason = f"inner_{selection_metric}_selection; winner={selected_model}; metrics={metrics}; m0_baseline_excluded=True"
        selection_rows.append({"test_date": test_date, "selected_model": selected_model, "selection_metric": selection_metric, "fallback": fallback, "model_unavailable": fallback, "selection_reason": reason, **{f"{model_id}_rank_ic": metrics[model_id] for model_id in MODEL_IDS}})
        selected_values = candidate_predictions.get(selected_model, pd.Series(np.nan, index=test.index))
        selected_std = float(pd.to_numeric(selected_values, errors="coerce").std())
        for model_id, values in candidate_predictions.items():
            for index, value in values.items():
                row = test.loc[index]
                numeric = _numeric(value)
                confidence = abs(numeric) / selected_std if np.isfinite(numeric) and selected_std > 0 else 0.0
                predictions.append(
                    {
                        "Date": test_date,
                        "feature_as_of_date": row.get("feature_as_of_date", test_date),
                        "region": row["region"],
                        "factor": row["factor"],
                        "model_id": model_id,
                        "prediction": numeric,
                        "target": _numeric(row.get("next_month_top_sleeve_net_active_return")),
                        "next_month_top_sleeve_net_return": _numeric(row.get("next_month_top_sleeve_net_return")),
                        "next_month_region_benchmark_return": _numeric(row.get("next_month_region_benchmark_return")),
                        "selected_model": selected_model,
                        "confidence": min(1.0, confidence),
                        "backend": "rule" if model_id in {"M0_equal_factor", "M1_trailing_12m", "M2_transparent_composite"} else ("sklearn.linear_model.Ridge" if model_id == "M3_pooled_ridge" else "sklearn.linear_model.ElasticNet"),
                        "train_start": train_dates[0],
                        "train_end": train_dates[-1],
                        "n_train_months": len(train_dates),
                        "purge_months": purge_months,
                        "selection_reason": reason,
                    }
                )
    return pd.DataFrame(predictions), pd.DataFrame(fit_rows), pd.DataFrame(selection_rows), {
        "minimum_train_months": min_train,
        "purge_months": purge_months,
        "candidate_models": list(MODEL_IDS),
        "selection_model_ids": list(SELECTION_MODEL_IDS),
        "selection_metric": selection_metric,
        "hyperparameter_grid": hyperparameter_grid or {},
        "inner_validation_months": int(inner_validation_months),
        "hyperparameter_records": hyperparameter_records,
    }


def _weight_rows(selected: pd.DataFrame, panel: pd.DataFrame, cost_bps: float, minimum_coverage: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    previous: dict[tuple[str, str], dict[str, float]] = {}
    selected = selected.sort_values(["Date", "region", "factor"], kind="stable")
    for (date, region), group in selected.groupby(["Date", "region"], sort=True):
        all_group = group.copy()
        group = group.dropna(subset=["prediction"]).copy()
        panel_rows = panel.loc[panel["Date"].eq(date) & panel["region"].eq(region)].copy()
        coverage_column = "factor_weight_coverage" if "factor_weight_coverage" in panel_rows.columns else ("factor_coverage" if "factor_coverage" in panel_rows.columns else "coverage")
        if not panel_rows.empty:
            coverage_values = pd.to_numeric(panel_rows[coverage_column], errors="coerce") if coverage_column in panel_rows.columns else pd.Series(1.0, index=panel_rows.index)
            formation_values = panel_rows["formation_available"].astype(bool) if "formation_available" in panel_rows.columns else pd.Series(True, index=panel_rows.index)
            eligible = panel_rows.loc[coverage_values.ge(float(minimum_coverage)) & formation_values, "factor"]
        else:
            eligible = pd.Series(dtype=object)
        valid = group.loc[group["factor"].isin(set(eligible))].copy()
        output_factors = sorted(set(all_group["factor"].astype(str)))
        neutral = {str(factor): 1.0 / len(valid) for factor in valid["factor"]}
        ranked = valid.sort_values("prediction", ascending=False, kind="stable")
        confidence = float(pd.to_numeric(ranked["confidence"], errors="coerce").max()) if not ranked.empty else 0.0
        no_view = len(ranked) < 2
        fallback = no_view or confidence < 0.25
        if fallback:
            weights = neutral if not no_view else {}
            stance = "NO_VIEW" if no_view else "NEUTRAL_FALLBACK"
        else:
            top = ranked.head(2)["factor"].astype(str).tolist()
            weights = {factor: (0.5 if factor in top else 0.0) for factor in valid["factor"].astype(str)}
            stance = "RECOMMENDED"
        returns = panel.loc[(panel["Date"].eq(date)) & (panel["region"].eq(region))].set_index("factor")
        top1_factors = ranked.head(1)["factor"].astype(str).tolist()
        top1_weights = {factor: (1.0 if factor in top1_factors else 0.0) for factor in valid["factor"].astype(str)}
        target_series = returns["next_month_top_sleeve_net_return"] if "next_month_top_sleeve_net_return" in returns.columns else pd.Series(dtype=float)
        target_values = pd.to_numeric(target_series, errors="coerce").dropna()
        realized_winner = str(target_values.idxmax()) if not target_values.empty else None
        top2_factors = set(ranked.head(2)["factor"].astype(str))
        top2_winner_capture = float(realized_winner in top2_factors) if realized_winner is not None else np.nan
        top2_capture_baseline = min(1.0, 2.0 / len(valid)) if len(valid) else np.nan
        top2_capture_uplift = top2_winner_capture - top2_capture_baseline if np.isfinite(top2_winner_capture) and np.isfinite(top2_capture_baseline) else np.nan
        top1_hit = float(realized_winner in set(top1_factors)) if realized_winner is not None else np.nan
        winner_regret = float(target_values.max() - target_values.get(top1_factors[0], np.nan)) if realized_winner is not None and top1_factors else np.nan
        positive_scores = pd.to_numeric(valid["prediction"], errors="coerce").clip(lower=0.0)
        score_total = float(positive_scores.sum())
        score_weights = {
            str(factor): (float(score) / score_total if score_total > 0 else neutral.get(str(factor), 0.0))
            for factor, score in zip(valid["factor"].astype(str), positive_scores)
        }
        confidence_weights = weights if not no_view and not fallback else neutral if not no_view else {}
        def variant_return(variant_weights: Mapping[str, float], returns_frame: pd.DataFrame = returns) -> float:
            return float(sum(weight * _numeric(returns_frame.loc[factor, "next_month_top_sleeve_net_return"]) for factor, weight in variant_weights.items() if factor in returns_frame.index)) if variant_weights else np.nan
        top1_return = variant_return(top1_weights)
        score_weighted_return = variant_return(score_weights)
        confidence_gated_return = variant_return(confidence_weights)
        neutral_return = float(sum(weight * _numeric(returns.loc[factor, "next_month_top_sleeve_net_return"]) for factor, weight in neutral.items() if factor in returns.index)) if neutral else np.nan
        before_cost = float(sum(weight * _numeric(returns.loc[factor, "next_month_top_sleeve_net_return"]) for factor, weight in weights.items() if factor in returns.index)) if weights else np.nan
        gross_before_cost = float(sum(weight * _numeric(returns.loc[factor, "next_month_top_sleeve_gross_return"]) for factor, weight in weights.items() if factor in returns.index)) if weights and "next_month_top_sleeve_gross_return" in returns.columns else np.nan
        internal_cost = float(sum(weight * _numeric(returns.loc[factor, "next_month_top_sleeve_internal_cost"]) for factor, weight in weights.items() if factor in returns.index)) if weights and "next_month_top_sleeve_internal_cost" in returns.columns else np.nan
        previous_weights = previous.get((str(region), "primary"), {})
        all_factors = set(previous_weights) | set(weights)
        turnover = 0.5 * sum(abs(weights.get(factor, 0.0) - previous_weights.get(factor, 0.0)) for factor in all_factors)
        allocator_cost = turnover * float(cost_bps) / 10_000.0
        after_cost = before_cost - allocator_cost if np.isfinite(before_cost) else np.nan
        previous[(str(region), "primary")] = dict(weights)
        for factor in sorted(set(neutral) | set(weights) | set(output_factors)):
            row = {
                "Date": date,
                "region": region,
                "factor": factor,
                "model_id": ranked.iloc[0]["selected_model"] if not ranked.empty else (str(all_group["selected_model"].dropna().iloc[0]) if "selected_model" in all_group.columns and not all_group["selected_model"].dropna().empty else NO_VALID_MODEL),
                "allocator_variant": "top2_equal",
                "prediction": _numeric(valid.loc[valid["factor"].eq(factor), "prediction"].iloc[0]) if (valid["factor"].eq(factor)).any() else np.nan,
                "rank": int(ranked["factor"].tolist().index(factor) + 1) if factor in ranked["factor"].tolist() else np.nan,
                "confidence": confidence,
                "stance": stance,
                "neutral_weight": neutral.get(factor, 0.0),
                "recommended_weight": weights.get(factor, 0.0),
                "equal_factor_weight": neutral.get(factor, 0.0),
                "top1_weight": top1_weights.get(factor, 0.0),
                "score_weighted_weight": score_weights.get(factor, 0.0),
                "confidence_gated_weight": confidence_weights.get(factor, 0.0),
                "valid_factor_count": len(valid),
                "coverage": float(pd.to_numeric(panel_rows.loc[panel_rows["factor"].eq(factor), coverage_column], errors="coerce").iloc[0]) if coverage_column in panel_rows.columns and not panel_rows.loc[panel_rows["factor"].eq(factor)].empty else np.nan,
                "factor_coverage": float(pd.to_numeric(panel_rows.loc[panel_rows["factor"].eq(factor), coverage_column], errors="coerce").iloc[0]) if coverage_column in panel_rows.columns and not panel_rows.loc[panel_rows["factor"].eq(factor)].empty else np.nan,
                "top1_hit": top1_hit,
                "top2_winner_capture": top2_winner_capture,
                "top2_capture_baseline": top2_capture_baseline,
                "top2_capture_uplift": top2_capture_uplift,
                "ndcg_at_2": top2_winner_capture,
                "winner_regret": winner_regret,
                "fallback": fallback,
                "no_view": no_view,
                "cost_bps": float(cost_bps),
                "allocator_turnover": turnover,
                "allocator_cost": allocator_cost,
                "sleeve_internal_cost": float(sum(weights.get(name, 0.0) * _numeric(returns.loc[name, "internal_cost"]) for name in weights if name in returns.index)),
                "gross_sleeve_return": gross_before_cost,
                "internal_sleeve_cost": internal_cost,
                "total_cost_drag": gross_before_cost - after_cost if np.isfinite(gross_before_cost) and np.isfinite(after_cost) else np.nan,
                "net_return_before_allocator_cost": before_cost,
                "net_return": after_cost,
                "equal_factor_basket_net_return": neutral_return,
                "top1_net_return": top1_return,
                "score_weighted_net_return": score_weighted_return,
                "confidence_gated_net_return": confidence_gated_return,
                "regional_benchmark_return": float(pd.to_numeric(returns["next_month_region_benchmark_return"], errors="coerce").dropna().iloc[0]) if "next_month_region_benchmark_return" in returns.columns and not pd.to_numeric(returns["next_month_region_benchmark_return"], errors="coerce").dropna().empty else np.nan,
                "primary_active_return": after_cost - neutral_return if np.isfinite(after_cost) and np.isfinite(neutral_return) else np.nan,
                "warning": "NO_VIEW" if no_view else ("low_confidence_neutral_fallback" if fallback else ""),
            }
            rows.append(row)
    return rows


def allocate_top2(
    predictions: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    cost_grid_bps: Iterable[float] = (0, 10, 25, 50),
    minimum_coverage: float = 0.8,
) -> pd.DataFrame:
    """Allocate per Date x Region and expose neutral/NO_VIEW fallbacks."""

    if predictions.empty or panel.empty:
        return pd.DataFrame()
    selected = predictions.loc[
        predictions["model_id"].eq(predictions["selected_model"])
        & predictions["selected_model"].isin(SELECTION_MODEL_IDS)
    ].copy()
    decision_keys = predictions[["Date", "region"]].drop_duplicates()
    selected_keys = selected[["Date", "region"]].drop_duplicates() if not selected.empty else pd.DataFrame(columns=["Date", "region"])
    missing_keys = decision_keys.merge(selected_keys, on=["Date", "region"], how="left", indicator=True)
    missing_keys = missing_keys.loc[missing_keys["_merge"].eq("left_only"), ["Date", "region"]]
    if not missing_keys.empty:
        fallback = panel.merge(missing_keys, on=["Date", "region"], how="inner")[["Date", "region", "factor"]].drop_duplicates()
        fallback["model_id"] = NO_VALID_MODEL
        fallback["selected_model"] = NO_VALID_MODEL
        fallback["prediction"] = np.nan
        fallback["confidence"] = 0.0
        selected = pd.concat([selected, fallback], ignore_index=True, sort=False)
    frames = [_weight_rows(selected, panel, float(cost), float(minimum_coverage)) for cost in cost_grid_bps]
    return pd.DataFrame([row for rows in frames for row in rows])


def alternative_allocator_results(allocations: pd.DataFrame, *, cost_bps: float = 25.0) -> pd.DataFrame:
    """Recompute turnover and cost independently for every allocator variant."""

    if allocations.empty:
        return pd.DataFrame()
    source = allocations.loc[allocations["cost_bps"].eq(float(cost_bps))].copy()
    if source.empty:
        return pd.DataFrame()
    variants = {
        "top1": ("top1_weight", "top1_net_return"),
        "top2_equal": ("recommended_weight", "net_return_before_allocator_cost"),
        "score_weighted": ("score_weighted_weight", "score_weighted_net_return"),
        "confidence_gated": ("confidence_gated_weight", "confidence_gated_net_return"),
        "equal_factor": ("equal_factor_weight", "equal_factor_basket_net_return"),
    }
    previous: dict[tuple[str, str], dict[str, float]] = {}
    rows: list[dict[str, Any]] = []
    for (date, region), group in source.groupby(["Date", "region"], sort=True):
        group = group.drop_duplicates("factor").copy()
        benchmark_values = pd.to_numeric(group.get("regional_benchmark_return"), errors="coerce").dropna()
        benchmark = float(benchmark_values.iloc[0]) if not benchmark_values.empty else np.nan
        for variant, (weight_column, return_column) in variants.items():
            weights = {str(row.factor): _numeric(getattr(row, weight_column, np.nan), 0.0) for row in group.itertuples()}
            weights = {factor: (weight if np.isfinite(weight) else 0.0) for factor, weight in weights.items()}
            previous_weights = previous.get((str(region), variant), {})
            all_factors = set(weights) | set(previous_weights)
            turnover = 0.5 * sum(abs(weights.get(factor, 0.0) - previous_weights.get(factor, 0.0)) for factor in all_factors)
            allocator_cost = turnover * float(cost_bps) / 10_000.0
            previous[(str(region), variant)] = dict(weights)
            before_cost = float(sum(weights.get(str(row.factor), 0.0) * _numeric(getattr(row, return_column, np.nan)) for row in group.itertuples())) if any(weights.values()) else np.nan
            net_return = before_cost - allocator_cost if np.isfinite(before_cost) else np.nan
            equal_values = pd.to_numeric(group.get("equal_factor_basket_net_return"), errors="coerce").dropna()
            equal_return = float(equal_values.iloc[0]) if not equal_values.empty else np.nan
            for row in group.itertuples():
                factor = str(row.factor)
                rows.append(
                    {
                        "Date": date,
                        "region": region,
                        "factor": factor,
                        "allocator_variant": variant,
                        "variant_weight": weights.get(factor, 0.0),
                        "allocator_turnover": turnover,
                        "allocator_cost": allocator_cost,
                        "pre_allocator_net_return": before_cost,
                        "net_return": net_return,
                        "active_return": net_return - benchmark if np.isfinite(net_return) and np.isfinite(benchmark) else np.nan,
                        "active_vs_equal_factor": net_return - equal_return if np.isfinite(net_return) and np.isfinite(equal_return) else np.nan,
                        "equal_factor_comparable_net_return": equal_return,
                        "regional_benchmark_return": benchmark,
                        "stance": getattr(row, "stance", "NO_VIEW"),
                        "no_view": bool(getattr(row, "no_view", False)),
                        "cost_bps": float(cost_bps),
                    }
                )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    group_values = result.drop_duplicates(["Date", "region", "allocator_variant"]).sort_values(["region", "allocator_variant", "Date"], kind="stable")
    group_values["wealth"] = group_values.groupby(["region", "allocator_variant"], sort=False)["net_return"].transform(lambda values: (1.0 + pd.to_numeric(values, errors="coerce").fillna(0.0)).cumprod())
    group_values["drawdown"] = group_values["wealth"] / group_values.groupby(["region", "allocator_variant"], sort=False)["wealth"].cummax() - 1.0
    result = result.merge(group_values[["Date", "region", "allocator_variant", "wealth", "drawdown"]], on=["Date", "region", "allocator_variant"], how="left")
    return result


def candidate_prediction_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame(columns=["model_id", "rank_ic", "ic_std", "icir", "positive_ic_rate", "pairwise_accuracy", "top1_hit", "top2_winner_capture", "top2_capture_uplift", "ndcg_at_2", "winner_regret", "rank_turnover", "observations"])
    rows: list[dict[str, Any]] = []
    for model_id, group in predictions.groupby("model_id", sort=False):
        fold_rows: list[dict[str, float]] = []
        for _, values in group.groupby(["Date", "region"], sort=False):
            frame = values.dropna(subset=["prediction", "target"])
            if frame.empty:
                continue
            rank_ic = _rank_ic(frame["prediction"], frame["target"])
            ranked = frame.sort_values("prediction", ascending=False, kind="stable")
            realized = frame.sort_values("target", ascending=False, kind="stable")["factor"].astype(str).tolist()
            predicted = ranked["factor"].astype(str).tolist()
            valid_count = len(frame)
            winner = realized[0] if realized else None
            top2_capture = float(winner in set(predicted[:2])) if winner is not None else np.nan
            baseline = min(1.0, 2.0 / valid_count) if valid_count else np.nan
            gains = frame["target"].astype(float) - float(frame["target"].min())
            gains = gains.clip(lower=0.0)
            discounts = np.log2(np.arange(2, len(ranked) + 2, dtype=float))
            dcg = float(gains.loc[ranked.index[:2]].to_numpy(dtype=float).dot(1.0 / discounts[: min(2, len(ranked))])) if len(ranked) else np.nan
            ideal = frame.sort_values("target", ascending=False, kind="stable")
            ideal_discounts = np.log2(np.arange(2, len(ideal) + 2, dtype=float))
            idcg = float(gains.loc[ideal.index[:2]].to_numpy(dtype=float).dot(1.0 / ideal_discounts[: min(2, len(ideal))])) if len(ideal) else np.nan
            fold_rows.append({
                "rank_ic": rank_ic,
                "top1_hit": float(winner == predicted[0]) if winner is not None and predicted else np.nan,
                "top2_winner_capture": top2_capture,
                "top2_capture_uplift": top2_capture - baseline if np.isfinite(top2_capture) and np.isfinite(baseline) else np.nan,
                "ndcg_at_2": dcg / idcg if np.isfinite(dcg) and idcg > 0 else np.nan,
                "winner_regret": float(frame["target"].max() - frame.loc[ranked.index[0], "target"]) if len(ranked) else np.nan,
            })
        fold_metrics = pd.DataFrame(fold_rows)
        ics = pd.to_numeric(fold_metrics.get("rank_ic"), errors="coerce").dropna() if not fold_metrics.empty else pd.Series(dtype=float)
        pairwise = group.dropna(subset=["prediction", "target"])
        pairwise_accuracy = np.nan
        if len(pairwise) >= 2:
            pairwise_accuracy = float((pairwise["prediction"].rank() == pairwise["target"].rank()).mean())
        top1_sequence = group.sort_values(["region", "Date", "prediction"], ascending=[True, True, False], kind="stable").groupby(["region", "Date"], sort=False).head(1)
        rank_turnover = float(top1_sequence.groupby("region", sort=False)["factor"].apply(lambda values: values.astype(str).ne(values.astype(str).shift()).iloc[1:].mean() if len(values) > 1 else np.nan).mean()) if not top1_sequence.empty else np.nan
        rows.append({
            "model_id": model_id,
            "rank_ic": float(ics.mean()) if len(ics) else np.nan,
            "ic_std": float(ics.std()) if len(ics) > 1 else np.nan,
            "icir": float(ics.mean() / ics.std() * np.sqrt(12)) if len(ics) > 1 and ics.std() > 0 else np.nan,
            "positive_ic_rate": float(ics.gt(0).mean()) if len(ics) else np.nan,
            "pairwise_accuracy": pairwise_accuracy,
            "top1_hit": float(fold_metrics["top1_hit"].mean()) if not fold_metrics.empty else np.nan,
            "top2_winner_capture": float(fold_metrics["top2_winner_capture"].mean()) if not fold_metrics.empty else np.nan,
            "top2_capture_uplift": float(fold_metrics["top2_capture_uplift"].mean()) if not fold_metrics.empty else np.nan,
            "ndcg_at_2": float(fold_metrics["ndcg_at_2"].mean()) if not fold_metrics.empty else np.nan,
            "winner_regret": float(fold_metrics["winner_regret"].mean()) if not fold_metrics.empty else np.nan,
            "rank_turnover": rank_turnover,
            "observations": len(group),
            "date_count": int(group["Date"].nunique()),
        })
    return pd.DataFrame(rows)


def economic_metrics(allocations: pd.DataFrame, *, cost_bps: float = 25.0) -> pd.DataFrame:
    if allocations.empty:
        return pd.DataFrame()
    source = allocations.loc[allocations["cost_bps"].eq(float(cost_bps))].copy()
    rows: list[dict[str, Any]] = []
    for region, group in source.groupby("region", sort=False):
        period = group.drop_duplicates(["Date"]).sort_values("Date")
        values = pd.to_numeric(period["primary_active_return"], errors="coerce").dropna()
        net = pd.to_numeric(period["net_return"], errors="coerce").dropna()
        active_std = float(values.std()) if len(values) > 1 else np.nan
        net_std = float(net.std()) if len(net) > 1 else np.nan
        wealth = (1.0 + net).cumprod() if len(net) else pd.Series(dtype=float)
        drawdown = wealth / wealth.cummax() - 1.0 if len(wealth) else pd.Series(dtype=float)
        cagr = float((1.0 + net).prod() ** (12.0 / len(net)) - 1.0) if len(net) and (1.0 + net).prod() > 0 else np.nan
        downside = values.loc[values < 0]
        rolling12 = values.rolling(12, min_periods=12).apply(lambda x: float((1.0 + x).prod() - 1.0), raw=True).dropna()
        rolling36 = values.rolling(36, min_periods=36).apply(lambda x: float((1.0 + x).prod() - 1.0), raw=True).dropna()
        ir = float(values.mean() / active_std * math.sqrt(12)) if len(values) > 1 and active_std > 0 else np.nan
        rows.append({
            "scope": "region",
            "region": region,
            "cost_bps": float(cost_bps),
            "observations": len(values),
            "mean_active_return": float(values.mean()) if len(values) else np.nan,
            "mean_net_return": float(net.mean()) if len(net) else np.nan,
            "cagr": cagr,
            "volatility": float(net_std * math.sqrt(12)) if np.isfinite(net_std) else np.nan,
            "sharpe": float(net.mean() / net_std * math.sqrt(12)) if len(net) > 1 and net_std > 0 else np.nan,
            "sortino": float(values.mean() / downside.std() * math.sqrt(12)) if len(downside) > 1 and downside.std() > 0 else np.nan,
            "max_drawdown": float(drawdown.min()) if len(drawdown) else np.nan,
            "calmar": float(cagr / abs(drawdown.min())) if len(drawdown) and drawdown.min() < 0 and np.isfinite(cagr) else np.nan,
            "tracking_error": float(active_std * math.sqrt(12)) if np.isfinite(active_std) else np.nan,
            "net_ir": ir,
            "information_ratio": ir,
            "hit_rate": float(values.gt(0).mean()) if len(values) else np.nan,
            "turnover": float(pd.to_numeric(period["allocator_turnover"], errors="coerce").mean()) if not period.empty and "allocator_turnover" in period.columns else np.nan,
            "sleeve_internal_cost": float(pd.to_numeric(period["internal_sleeve_cost"], errors="coerce").mean()) if not period.empty and "internal_sleeve_cost" in period.columns else np.nan,
            "allocator_cost": float(pd.to_numeric(period["allocator_cost"], errors="coerce").mean()) if not period.empty and "allocator_cost" in period.columns else np.nan,
            "cost_drag": float(pd.to_numeric(period["total_cost_drag"], errors="coerce").mean()) if not period.empty and "total_cost_drag" in period.columns else np.nan,
            "worst_12m": float(rolling12.min()) if len(rolling12) else np.nan,
            "worst_36m": float(rolling36.min()) if len(rolling36) else np.nan,
            "time_underwater": float((drawdown < 0).mean()) if len(drawdown) else np.nan,
            "max_concentration": float(pd.to_numeric(period["recommended_weight"], errors="coerce").max()) if not period.empty else np.nan,
        })
    return pd.DataFrame(rows)


def block_bootstrap(values: Sequence[float] | pd.Series, *, block_length: int, samples: int = 2000, seed: int = 1729) -> dict[str, Any]:
    data = pd.to_numeric(pd.Series(values), errors="coerce").dropna().to_numpy(dtype=float)
    if len(data) == 0:
        return {"block_length": int(block_length), "samples": int(samples), "probability_mean_gt_zero": np.nan, "ci_low": np.nan, "ci_high": np.nan, "seed": int(seed), "method": "moving_block_bootstrap"}
    rng = np.random.default_rng(seed)
    length = max(1, min(int(block_length), len(data)))
    starts = np.arange(0, max(1, len(data) - length + 1))
    means = []
    for _ in range(int(samples)):
        blocks: list[float] = []
        while len(blocks) < len(data):
            start = int(rng.choice(starts))
            blocks.extend(data[start : start + length].tolist())
        means.append(float(np.mean(blocks[: len(data)])))
    bootstrap = np.asarray(means)
    return {"block_length": int(block_length), "samples": int(samples), "probability_mean_gt_zero": float(np.mean(bootstrap > 0)), "ci_low": float(np.quantile(bootstrap, 0.025)), "ci_high": float(np.quantile(bootstrap, 0.975)), "seed": int(seed), "method": "moving_block_bootstrap"}


def deflated_sharpe(observed: Sequence[float] | pd.Series, *, effective_trials: int, candidate: str, block_length: int = 12) -> dict[str, Any]:
    values = pd.to_numeric(pd.Series(observed), errors="coerce").dropna().to_numpy(dtype=float)
    sharpe = float(values.mean() / values.std() * math.sqrt(12)) if len(values) > 1 and values.std() > 0 else np.nan
    effective_trial_count = max(2, int(effective_trials))
    selection_bias_adjustment = math.sqrt(2.0 * math.log(effective_trial_count))
    lag1 = float(np.corrcoef(values[:-1], values[1:])[0, 1]) if len(values) > 2 and np.std(values[:-1]) > 0 and np.std(values[1:]) > 0 else 0.0
    block = max(1, min(int(block_length), len(values)))
    long_run_variance = float(np.var(values) * (1.0 + 2.0 * max(-0.99, min(0.99, lag1)) * min(block - 1, max(0, len(values) - 1)))) if len(values) else np.nan
    sharpe_variance = float(max(0.0, 12.0 * long_run_variance / (len(values) * max(values.var(), 1e-12)))) if len(values) else np.nan
    se = math.sqrt(sharpe_variance) if np.isfinite(sharpe_variance) and sharpe_variance > 0 else 1.0 / math.sqrt(max(1, len(values)))
    z = (sharpe - selection_bias_adjustment) / se if np.isfinite(sharpe) else np.nan
    probability = 0.5 * (1.0 + math.erf(float(z) / math.sqrt(2.0))) if np.isfinite(z) else np.nan
    skew = float(pd.Series(values).skew()) if len(values) > 2 else np.nan
    kurtosis = float(pd.Series(values).kurt()) if len(values) > 3 else np.nan
    return {
        "metric": "approximate_deflated_sharpe",
        "credible": False,
        "dsr_gate_eligible": False,
        "candidate": candidate,
        "sample_length": len(values),
        "observations": len(values),
        "observed_sharpe": sharpe,
        "variance": float(np.var(values)) if len(values) else np.nan,
        "sharpe_variance": sharpe_variance,
        "skewness": skew,
        "skew": skew,
        "kurtosis": kurtosis,
        "effective_trials": effective_trial_count,
        "selection_bias_adjustment": selection_bias_adjustment,
        "expected_max_null_sharpe": selection_bias_adjustment,
        "autocorrelation_lag1": lag1,
        "block_length": block,
        "autocorrelation_block_treatment": "lag1_adjusted_approximation; not a validated block DSR",
        "probability_deflated_sharpe_gt_zero": probability,
        "formula_version": "approximate-dsr.v2.1.unvalidated",
        "limitation": "Candidate-specific OOS returns are present, but the small-sample skew/kurtosis and block correction have not passed known-example validation; DSR gate must fail.",
    }


def coverage_gate_frame(panel: pd.DataFrame, *, minimum_factor_coverage: float, minimum_benchmark_coverage: float) -> pd.DataFrame:
    """Evaluate coverage at the registered Date x Region x Factor grain."""

    if panel.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for _, row in panel.iterrows():
        factor_row = _numeric(row.get("factor_row_coverage", row.get("factor_coverage")), 0.0)
        factor_weight = _numeric(row.get("factor_weight_coverage", row.get("factor_coverage")), 0.0)
        benchmark = _numeric(row.get("retained_benchmark_coverage", row.get("weight_coverage")), 0.0)
        return_coverage = _numeric(row.get("return_weight_coverage"), 0.0)
        formation = bool(row.get("formation_available", True))
        passed = bool(
            formation
            and factor_row >= float(minimum_factor_coverage)
            and factor_weight >= float(minimum_factor_coverage)
            and benchmark >= float(minimum_benchmark_coverage)
            and return_coverage >= float(minimum_benchmark_coverage)
        )
        rows.append(
            {
                "Date": row.get("Date"),
                "region": row.get("region", row.get("region_component")),
                "factor": row.get("factor"),
                "eligible_universe_rows": row.get("eligible_universe_rows"),
                "valid_factor_rows": row.get("valid_factor_rows"),
                "factor_row_coverage": factor_row,
                "eligible_benchmark_weight": row.get("eligible_benchmark_weight"),
                "valid_factor_benchmark_weight": row.get("valid_factor_benchmark_weight"),
                "factor_weight_coverage": factor_weight,
                "raw_benchmark_weight": row.get("raw_benchmark_weight"),
                "retained_country_weight": row.get("retained_country_weight"),
                "retained_benchmark_coverage": benchmark,
                "return_available_weight": row.get("return_available_weight"),
                "return_weight_coverage": return_coverage,
                "formation_available": formation,
                "passed": passed,
                "gate_name": "date_region_factor_coverage",
                "scope": "Date x Region x Factor",
                "failure_reason": "" if passed else "factor/benchmark/return coverage or official formation availability below threshold",
            }
        )
    return pd.DataFrame(rows)


def promotion_gates(
    *,
    panel: pd.DataFrame,
    predictions: pd.DataFrame,
    allocations: pd.DataFrame,
    thresholds: Mapping[str, Any],
    bootstrap_rows: pd.DataFrame,
    dsr_rows: pd.DataFrame,
    clean_provenance: bool,
    asia_approved: bool = False,
    forward_shadow_months: int = 0,
    champion_model: str = NO_VALID_MODEL,
    champion_allocations: pd.DataFrame | None = None,
    coverage_results: pd.DataFrame | None = None,
    wealth_curves: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Create pooled and regional gates using one frozen champion only."""

    primary_source = champion_allocations if champion_allocations is not None else allocations
    primary = primary_source.loc[primary_source["cost_bps"].eq(25.0)].copy() if not primary_source.empty and "cost_bps" in primary_source.columns else pd.DataFrame()
    champion_predictions = predictions.loc[predictions["model_id"].eq(champion_model)].copy() if not predictions.empty and champion_model in SELECTION_MODEL_IDS else pd.DataFrame()
    pred_metrics = candidate_prediction_metrics(champion_predictions)
    champion_metric = pred_metrics.iloc[0] if not pred_metrics.empty else pd.Series(dtype=object)
    econ = economic_metrics(primary_source, cost_bps=25.0)
    active = pd.to_numeric(primary.drop_duplicates(["Date", "region"]).get("primary_active_return"), errors="coerce").dropna() if not primary.empty else pd.Series(dtype=float)
    allocator_active = active
    region_values = econ["mean_active_return"].dropna() if not econ.empty and "mean_active_return" in econ.columns else pd.Series(dtype=float)
    rank_ic = _numeric(champion_metric.get("rank_ic"))
    positive_ic = _numeric(champion_metric.get("positive_ic_rate"))
    capture_uplift = _numeric(champion_metric.get("top2_capture_uplift"))
    net_ir = float(econ["net_ir"].mean()) if not econ.empty else np.nan
    valid_region_status = True
    region_statuses: dict[str, str] = {}
    region_rows = []
    if not panel.empty:
        for region, region_panel in panel.groupby("region", sort=True):
            observations = int(region_panel["Date"].nunique())
            status = "ok" if observations >= int(thresholds.get("minimum_monthly_observations", 120)) else "insufficient_history"
            region_statuses[str(region)] = status
            valid_region_status &= status == "ok"
            region_rows.append((str(region), region_panel, observations, status))
    consistency = float(region_values.gt(0).mean()) if len(region_values) else np.nan
    max_concentration = float(primary["recommended_weight"].max()) if not primary.empty and "recommended_weight" in primary.columns else np.nan
    if coverage_results is not None and not coverage_results.empty:
        factor_coverage = float(pd.to_numeric(coverage_results["factor_weight_coverage"], errors="coerce").min())
        benchmark_coverage = float(pd.to_numeric(coverage_results["retained_benchmark_coverage"], errors="coerce").min())
        coverage_pass = bool(coverage_results["passed"].all())
    else:
        factor_coverage = float(pd.to_numeric(panel.get("factor_weight_coverage", panel.get("coverage")), errors="coerce").min()) if not panel.empty else np.nan
        benchmark_coverage = float(pd.to_numeric(panel.get("retained_benchmark_coverage", panel.get("weight_coverage")), errors="coerce").min()) if not panel.empty else np.nan
        coverage_pass = True
    valid_factor_count = float(panel.groupby(["Date", "region"])["factor"].nunique().min()) if not panel.empty else np.nan
    observations = int(panel["Date"].nunique()) if not panel.empty else 0
    stress_source = primary_source.loc[primary_source["cost_bps"].eq(50.0)].copy() if not primary_source.empty and "cost_bps" in primary_source.columns else pd.DataFrame()
    stress_active = float(stress_source.drop_duplicates(["Date", "region"])["primary_active_return"].mean()) if not stress_source.empty and "primary_active_return" in stress_source.columns else np.nan
    mdd_top2 = np.nan
    mdd_equal = np.nan
    if wealth_curves is not None and not wealth_curves.empty:
        top_curve = wealth_curves.loc[wealth_curves["allocator_variant"].eq("top2_equal") & wealth_curves["cost_bps"].eq(50.0)]
        equal_curve = wealth_curves.loc[wealth_curves["allocator_variant"].eq("equal_factor") & wealth_curves["cost_bps"].eq(50.0)]
        mdd_top2 = float(pd.to_numeric(top_curve.get("drawdown"), errors="coerce").min()) if not top_curve.empty else np.nan
        mdd_equal = float(pd.to_numeric(equal_curve.get("drawdown"), errors="coerce").min()) if not equal_curve.empty else np.nan
    mdd_deterioration = abs(mdd_top2) - abs(mdd_equal) if np.isfinite(mdd_top2) and np.isfinite(mdd_equal) else np.nan
    boot6 = float(bootstrap_rows.loc[bootstrap_rows["block_length"].eq(6), "probability_mean_gt_zero"].iloc[0]) if not bootstrap_rows.empty and bool(bootstrap_rows["block_length"].eq(6).any()) else np.nan
    boot12 = float(bootstrap_rows.loc[bootstrap_rows["block_length"].eq(12), "probability_mean_gt_zero"].iloc[0]) if not bootstrap_rows.empty and bool(bootstrap_rows["block_length"].eq(12).any()) else np.nan
    dsr_row = dsr_rows.loc[dsr_rows["candidate"].eq(champion_model)] if not dsr_rows.empty and "candidate" in dsr_rows.columns else pd.DataFrame()
    dsr_prob = float(dsr_row["probability_deflated_sharpe_gt_zero"].iloc[0]) if not dsr_row.empty else np.nan
    dsr_eligible = bool(dsr_row["dsr_gate_eligible"].iloc[0]) if not dsr_row.empty and "dsr_gate_eligible" in dsr_row.columns else False

    specs = [
        ("observations", observations, thresholds.get("minimum_monthly_observations", 120), ">=", "factor_panel.parquet", "pooled"),
        ("valid_factors", valid_factor_count, thresholds.get("minimum_valid_factors_per_month", 5), ">=", "factor_panel.parquet", "pooled"),
        ("factor_coverage", factor_coverage, thresholds.get("minimum_factor_coverage", 0.8), ">=", "factor_sleeve_coverage.csv", "date_region_factor"),
        ("benchmark_coverage", benchmark_coverage, thresholds.get("minimum_benchmark_coverage", 0.8), ">=", "factor_sleeve_coverage.csv", "date_region_factor"),
        ("mean_rank_ic", rank_ic, thresholds.get("minimum_mean_rank_ic", 0.05), ">=", "walk_forward_metrics.csv", "champion"),
        ("positive_ic_rate", positive_ic, thresholds.get("minimum_positive_ic_rate", 0.55), ">=", "walk_forward_metrics.csv", "champion"),
        ("top2_capture_uplift", capture_uplift, thresholds.get("minimum_top2_uplift", 0.0), ">=", "walk_forward_metrics.csv", "champion"),
        ("allocator_mean_active_return", float(allocator_active.mean()) if len(allocator_active) else np.nan, 0.0, ">=", "allocation_results.parquet", "top2_equal"),
        ("25bps_net_ir", net_ir, thresholds.get("minimum_25bps_net_ir", 0.0), ">=", "strategy_metrics.csv", "top2_equal"),
        ("region_consistency", consistency if valid_region_status else np.nan, thresholds.get("minimum_region_consistency", 0.5), ">=", "region_gate_results.csv", "pooled"),
        ("50bps_stress", stress_active, 0.0, ">=", "allocation_results.parquet", "top2_equal"),
        ("mdd_deterioration_50bps", mdd_deterioration, thresholds.get("maximum_50bps_stress_drawdown_deterioration", 0.05), "<=", "mdd_comparison.csv", "top2_equal_vs_equal_factor"),
        ("allocation_max_weight", max_concentration, thresholds.get("maximum_concentration", 0.5), "<=", "allocation_results.parquet", "top2_equal"),
        ("bootstrap_6m", boot6, thresholds.get("minimum_bootstrap_probability_6", 0.75), ">=", "bootstrap_results.csv", "champion"),
        ("bootstrap_12m", boot12, thresholds.get("minimum_bootstrap_probability_12", 0.75), ">=", "bootstrap_results.csv", "champion"),
        ("dsr", dsr_prob if dsr_eligible else np.nan, thresholds.get("minimum_dsr_probability", 0.8), ">=", "deflated_sharpe_results.csv", "champion"),
        ("asia_approval", 1.0 if asia_approved else 0.0, 1.0 if thresholds.get("asia_approval_required", False) else 0.0, ">=", "universe_definitions.csv", "pooled"),
        ("forward_shadow_12m", forward_shadow_months, thresholds.get("forward_shadow_months_required", 12), ">=", "component_status.json", "pooled"),
        ("clean_provenance", 1.0 if clean_provenance else 0.0, 1.0 if thresholds.get("clean_provenance_required", True) else 0.0, ">=", "repository_data_audit.json", "pooled"),
    ]
    rows: list[dict[str, Any]] = []

    def add_gate(name: str, actual: Any, threshold: Any, operator: str, evidence: str, scope: str, *, region: str = "pooled", status: str = "ok", force_fail: bool = False, variant: str = "pooled") -> None:
        numeric = _numeric(actual)
        passed = bool(np.isfinite(numeric) and (numeric >= float(threshold) if operator == ">=" else numeric <= float(threshold))) and not force_fail
        if name == "asia_approval" and not thresholds.get("asia_approval_required", False):
            passed = True
        rows.append(
            {
                "gate_name": name,
                "metric_source_model": champion_model,
                "metric_source_variant": variant,
                "scope": scope,
                "evidence_path": evidence,
                "actual": actual,
                "threshold": threshold,
                "operator": operator,
                "passed": passed,
                "region": region,
                "region_status": status,
                "production_eligible": bool(passed and status != "insufficient_history"),
                "failure_reason": "" if passed else ("region has insufficient history" if status == "insufficient_history" else f"actual={actual!r} does not satisfy {operator} {threshold!r}"),
            }
        )

    for name, actual, threshold, operator, evidence, variant in specs:
        add_gate(name, actual, threshold, operator, evidence, "pooled", force_fail=(name in {"factor_coverage", "benchmark_coverage"} and not coverage_pass), variant=variant)
    for region, region_panel, region_observations, status in region_rows:
        region_predictions = champion_predictions.loc[champion_predictions["region"].eq(region)] if not champion_predictions.empty else pd.DataFrame()
        region_metric = candidate_prediction_metrics(region_predictions)
        region_rank_ic = _numeric(region_metric.iloc[0].get("rank_ic")) if not region_metric.empty else np.nan
        region_oos = int(region_predictions["Date"].nunique()) if not region_predictions.empty else 0
        region_valid = float(region_panel.groupby("Date")["factor"].nunique().min()) if not region_panel.empty else np.nan
        region_factor = float(pd.to_numeric(region_panel.get("factor_weight_coverage", region_panel.get("coverage")), errors="coerce").min()) if not region_panel.empty else np.nan
        region_benchmark = float(pd.to_numeric(region_panel.get("retained_benchmark_coverage", region_panel.get("weight_coverage")), errors="coerce").min()) if not region_panel.empty else np.nan
        region_ir = _numeric(econ.loc[econ["region"].eq(region), "net_ir"].iloc[0]) if not econ.empty and bool(econ["region"].eq(region).any()) else np.nan
        region_active = _numeric(econ.loc[econ["region"].eq(region), "mean_active_return"].iloc[0]) if not econ.empty and bool(econ["region"].eq(region).any()) else np.nan
        region_stress = _numeric(stress_source.loc[stress_source["region"].eq(region), "primary_active_return"].mean()) if not stress_source.empty and bool(stress_source["region"].eq(region).any()) else np.nan
        region_mdd = _numeric(econ.loc[econ["region"].eq(region), "max_drawdown"].iloc[0]) if not econ.empty and bool(econ["region"].eq(region).any()) else np.nan
        prefix = f"region_{region}_"
        add_gate(prefix + "available_history_months", region_observations, thresholds.get("minimum_monthly_observations", 120), ">=", "region_gate_results.csv", f"region:{region}", region=region, status=status, force_fail=status == "insufficient_history")
        add_gate(prefix + "oos_months", region_oos, 1, ">=", "region_gate_results.csv", f"region:{region}", region=region, status=status, force_fail=status == "insufficient_history")
        add_gate(prefix + "valid_factors_per_month", region_valid, thresholds.get("minimum_valid_factors_per_month", 5), ">=", "region_gate_results.csv", f"region:{region}", region=region, status=status, force_fail=status == "insufficient_history")
        add_gate(prefix + "factor_coverage", region_factor, thresholds.get("minimum_factor_coverage", 0.8), ">=", "region_gate_results.csv", f"region:{region}", region=region, status=status, force_fail=status == "insufficient_history")
        add_gate(prefix + "benchmark_coverage", region_benchmark, thresholds.get("minimum_benchmark_coverage", 0.8), ">=", "region_gate_results.csv", f"region:{region}", region=region, status=status, force_fail=status == "insufficient_history")
        add_gate(prefix + "rank_ic", region_rank_ic, thresholds.get("minimum_mean_rank_ic", 0.05), ">=", "region_gate_results.csv", f"region:{region}", region=region, status=status, force_fail=status == "insufficient_history")
        add_gate(prefix + "net_ir", region_ir, thresholds.get("minimum_25bps_net_ir", 0.0), ">=", "region_gate_results.csv", f"region:{region}", region=region, status=status, force_fail=status == "insufficient_history")
        add_gate(prefix + "active_return", region_active, 0.0, ">=", "region_gate_results.csv", f"region:{region}", region=region, status=status, force_fail=status == "insufficient_history")
        add_gate(prefix + "50bps_stress", region_stress, 0.0, ">=", "region_gate_results.csv", f"region:{region}", region=region, status=status, force_fail=status == "insufficient_history")
        add_gate(prefix + "mdd", abs(region_mdd) if np.isfinite(region_mdd) else np.nan, thresholds.get("maximum_50bps_stress_drawdown_deterioration", 0.05), "<=", "region_gate_results.csv", f"region:{region}", region=region, status=status, force_fail=status == "insufficient_history")
    return pd.DataFrame(rows)


def _fit_candidate_for_holdout(model_id: str, train: pd.DataFrame, test: pd.DataFrame) -> pd.Series:
    if model_id == "M1_trailing_12m":
        return _m1_prediction(test)
    if model_id == "M2_transparent_composite":
        return _m2_prediction(test)
    if model_id in {"M3_pooled_ridge", "M4_pooled_elastic_net"}:
        fit, _ = _sklearn_fit(model_id, train)
        return _sklearn_predict(fit, test)
    return pd.Series(np.nan, index=test.index)


def run_lopo_loro(
    panel: pd.DataFrame,
    *,
    economic_periods: Sequence[Mapping[str, Any]] = (),
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Retrain candidates for leave-one-period and leave-one-region tests."""

    if panel.empty:
        empty = pd.DataFrame(columns=["method", "held_out", "model_id", "rank_ic", "observations", "retrained"])
        return empty.copy(), empty.copy(), empty.copy()
    source = panel.copy()
    source["Date"] = pd.to_datetime(source["Date"], errors="coerce").dt.normalize()
    model_ids = list(SELECTION_MODEL_IDS)

    def evaluate(method: str, held_out: str, train_mask: pd.Series, test_mask: pd.Series, train_label: str, test_label: str) -> list[dict[str, Any]]:
        train = source.loc[train_mask].copy()
        test = source.loc[test_mask].copy()
        rows: list[dict[str, Any]] = []
        if train.empty or test.empty:
            return rows
        for model_id in model_ids:
            try:
                prediction = _fit_candidate_for_holdout(model_id, train, test)
                frame = pd.DataFrame({"prediction": prediction, "target": pd.to_numeric(test["next_month_top_sleeve_net_active_return"], errors="coerce")}).dropna()
                rank_ic = _rank_ic(frame["prediction"], frame["target"]) if not frame.empty else np.nan
            except (RuntimeError, ValueError, TypeError):
                rank_ic = np.nan
                frame = pd.DataFrame()
            rows.append(
                {
                    "method": method,
                    "held_out": held_out,
                    "held_out_period": held_out if method == "LOPO" else "",
                    "held_out_region": held_out if method == "LORO" else "",
                    "model_id": model_id,
                    "rank_ic": rank_ic,
                    "observations": len(frame),
                    "retrained": True,
                    "train_start": train["Date"].min(),
                    "train_end": train["Date"].max(),
                    "test_start": test["Date"].min(),
                    "test_end": test["Date"].max(),
                    "train_scope": train_label,
                    "test_scope": test_label,
                    "selection_scope": "held_out_train_only",
                }
            )
        return rows

    lopo_rows: list[dict[str, Any]] = []
    for period in economic_periods:
        name = str(period.get("name", "period"))
        if name == "full":
            continue
        start = pd.Timestamp(period.get("start"))
        end = pd.Timestamp(period.get("end"))
        holdout = source["Date"].between(start, end)
        lopo_rows.extend(evaluate("LOPO", name, ~holdout, holdout, f"all_periods_except_{name}", name))
    loro_rows: list[dict[str, Any]] = []
    for region in sorted(source["region"].astype(str).unique()):
        holdout = source["region"].astype(str).eq(region)
        loro_rows.extend(evaluate("LORO", region, ~holdout, holdout, f"all_regions_except_{region}", region))
    lopo = pd.DataFrame(lopo_rows)
    loro = pd.DataFrame(loro_rows)
    combined = pd.concat([lopo, loro], ignore_index=True) if not lopo.empty or not loro.empty else pd.DataFrame()
    summary = (
        combined.groupby(["method", "model_id"], dropna=False, sort=False)
        .agg(folds=("held_out", "nunique"), mean_rank_ic=("rank_ic", "mean"), observations=("observations", "sum"), all_retrained=("retrained", "all"))
        .reset_index()
        if not combined.empty
        else pd.DataFrame(columns=["method", "model_id", "folds", "mean_rank_ic", "observations", "all_retrained"])
    )
    return lopo, loro, summary


def pit_mutation_audit(sleeves: pd.DataFrame, *, fit_records: pd.DataFrame | None = None) -> pd.DataFrame:
    """Run structural and mutation-based PIT checks; no hard-coded pass flag."""

    panel = build_factor_panel(sleeves)
    rows: list[dict[str, Any]] = []
    availability_status = "snapshot_assumption"
    structural = {
        "feature_as_of_le_decision": bool(not panel.empty and (pd.to_datetime(panel["feature_as_of_date"], errors="coerce") <= pd.to_datetime(panel["Date"], errors="coerce")).all()),
        "target_strictly_after_decision": bool(not panel.empty and (pd.to_datetime(panel["target_date"], errors="coerce") > pd.to_datetime(panel["Date"], errors="coerce")).all()),
        "current_target_not_feature": not bool(set(FEATURE_COLUMNS) & {"next_month_top_sleeve_net_active_return", "next_month_top_sleeve_net_return"}),
        "train_transforms_before_test": bool(fit_records is None or fit_records.empty or (pd.to_datetime(fit_records["train_end"], errors="coerce") < pd.to_datetime(fit_records["test_date"], errors="coerce")).all()),
    }
    for check, passed in structural.items():
        rows.append({"check": check, "passed": bool(passed), "availability_status": availability_status, "audit_status": "pass_with_snapshot_assumption" if passed else "fail", "evidence": "panel dates / fit records"})
    if not panel.empty and not sleeves.empty:
        baseline = build_factor_panel(sleeves)
        mutation_index = sleeves.loc[sleeves["sleeve_side"].eq("Top"), "Date"].dropna().sort_values().iloc[len(sleeves.loc[sleeves["sleeve_side"].eq("Top"), "Date"].dropna()) // 2]
        mutated = sleeves.copy()
        mask = mutated["Date"].eq(mutation_index) & mutated["sleeve_side"].eq("Top")
        mutated.loc[mask, "active_return"] = pd.to_numeric(mutated.loc[mask, "active_return"], errors="coerce") + 1.0
        changed = build_factor_panel(mutated)
        key = ["Date", "region", "factor"]
        left = baseline.set_index(key)[list(FEATURE_COLUMNS)].sort_index()
        right = changed.set_index(key)[list(FEATURE_COLUMNS)].reindex(left.index).sort_index()
        current_mask = left.index.get_level_values("Date") <= pd.Timestamp(mutation_index)
        before_unchanged = bool(np.allclose(left.loc[current_mask].to_numpy(dtype=float), right.loc[current_mask].to_numpy(dtype=float), equal_nan=True))
        after_changed = bool(not np.allclose(left.loc[~current_mask].to_numpy(dtype=float), right.loc[~current_mask].to_numpy(dtype=float), equal_nan=True)) if bool((~current_mask).any()) else True
        rows.extend(
            [
                {"check": "future_target_mutation_current_features_unchanged", "passed": before_unchanged, "availability_status": availability_status, "audit_status": "pass_with_snapshot_assumption" if before_unchanged else "fail", "evidence": "mutated active_return at one historical target month"},
                {"check": "future_target_mutation_only_after_realization_changes", "passed": after_changed, "availability_status": availability_status, "audit_status": "pass_with_snapshot_assumption" if after_changed else "fail", "evidence": "same mutation and next-period feature comparison"},
            ]
        )
        same_date_change = changed.loc[changed["Date"].eq(mutation_index), list(FEATURE_COLUMNS)].to_numpy(dtype=float) if not changed.loc[changed["Date"].eq(mutation_index)].empty else np.empty((0, len(FEATURE_COLUMNS)))
        base_date = baseline.loc[baseline["Date"].eq(mutation_index), list(FEATURE_COLUMNS)].to_numpy(dtype=float) if not baseline.loc[baseline["Date"].eq(mutation_index)].empty else np.empty((0, len(FEATURE_COLUMNS)))
        cross_region_safe = bool(np.allclose(base_date, same_date_change, equal_nan=True))
        rows.append({"check": "cross_region_confirmation_no_same_month_target", "passed": cross_region_safe, "availability_status": availability_status, "audit_status": "pass_with_snapshot_assumption" if cross_region_safe else "fail", "evidence": "cross-region feature mutation"})
    else:
        rows.append({"check": "mutation_suite", "passed": False, "availability_status": availability_status, "audit_status": "fail", "evidence": "empty panel"})
    return pd.DataFrame(rows)


__all__ = [
    "FEATURE_COLUMNS",
    "MODEL_IDS",
    "NO_VALID_MODEL",
    "SELECTION_MODEL_IDS",
    "allocate_top2",
    "alternative_allocator_results",
    "block_bootstrap",
    "build_factor_panel",
    "candidate_prediction_metrics",
    "coverage_gate_frame",
    "cross_region_confirmation_feature",
    "deflated_sharpe",
    "economic_metrics",
    "make_smoke_sleeve_returns",
    "pit_mutation_audit",
    "promotion_gates",
    "run_lopo_loro",
    "select_champion",
    "select_hyperparameters",
    "walk_forward_predictions",
]
