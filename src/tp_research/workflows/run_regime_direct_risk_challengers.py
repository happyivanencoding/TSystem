"""Compare seven causal monthly regime-risk forecasting approaches."""

from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from collections.abc import Iterable, Mapping
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNet, LogisticRegression, Ridge
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

from tp_models.regime import config as regime_config
from tp_models.regime import model as regime_model
from tp_models.regime import vol_compare

EXPERIMENT_VERSION = "tp.regime.direct_risk_challengers:1.0.0"
DEFAULT_PARENT_FEATURES = Path(
    "artifacts/research/runs/regime-sector-factor-rotation-v1/"
    "20260726T145612Z-4dda8e92/results/"
    "market_factor_rotation_features.parquet"
)
REGIONS = ("US", "EU")
TARGETS = ("fwd_vol", "fwd_mdd")
MODELS = (
    "volatility_persistence",
    "current_hmm",
    "ridge",
    "elastic_net",
    "logistic",
    "markov_switching_ar",
    "ridge_logistic_ensemble",
)
CHALLENGERS = (
    "ridge",
    "elastic_net",
    "logistic",
    "markov_switching_ar",
    "ridge_logistic_ensemble",
)
FEATURE_COLUMNS = (
    "rvol_ann",
    "vol_med",
    "vol_short_med",
    "avg_corr",
    "down_day_freq",
    "breadth_pos",
    "ret_disp",
    "macro_fin_conditions",
    "macro_fin_conditions_ewma",
    "eps_rev_breadth",
    "bottom_up_transition_stress",
    "bottom_up_confirmation_available",
)
MODEL_LABELS = {
    "volatility_persistence": "波动持续性",
    "current_hmm": "当前 HMM",
    "ridge": "Ridge",
    "elastic_net": "Elastic Net",
    "logistic": "Logistic",
    "markov_switching_ar": "Markov-Switching AR(1)",
    "ridge_logistic_ensemble": "Ridge＋Logistic",
}
COMMON_PERIODS = {
    "common_validation_2018_2021": ("2018-01-01", "2021-12-31"),
    "common_holdout_2022_latest": ("2022-01-01", None),
    "common_full": (None, None),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_feature_matrix(
    region: str,
    parent_features: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    production = regime_model.load_features(region)
    missing = [
        column
        for column in FEATURE_COLUMNS[:10]
        if column not in production.columns
    ]
    if missing:
        raise KeyError(f"{region} production features missing: {missing}")
    work = production[list(FEATURE_COLUMNS[:10])].copy().ffill()

    bottom_up = parent_features[parent_features["region"].eq(region)].copy()
    bottom_up["Date"] = pd.to_datetime(bottom_up["Date"], errors="coerce")
    bottom_up = bottom_up.set_index("Date").sort_index()
    core = 1 - pd.to_numeric(
        bottom_up["core_transition_breadth_ewma3"],
        errors="coerce",
    ).ffill()
    confirmation_raw = 1 - pd.to_numeric(
        bottom_up["confirmation_transition_breadth_ewma3"],
        errors="coerce",
    )
    confirmation = confirmation_raw.ffill()
    confirmation_available = confirmation.notna().astype(float)
    effective_confirmation = confirmation.fillna(core)
    transition_stress = pd.concat(
        [core, effective_confirmation],
        axis=1,
    ).mean(axis=1)

    work = work.join(
        transition_stress.rename("bottom_up_transition_stress"),
        how="inner",
    )
    work = work.join(
        confirmation_available.rename(
            "bottom_up_confirmation_available"
        ),
        how="left",
    )
    work = work.ffill().dropna()
    checks = {
        "region": region,
        "rows": len(work),
        "start": str(work.index.min().date()),
        "end": str(work.index.max().date()),
        "confirmation_first_available": (
            str(confirmation.dropna().index.min().date())
            if confirmation.notna().any()
            else None
        ),
        "feature_count": len(work.columns),
    }
    return work, checks


def _clip_log_prediction(value: float, history: pd.Series) -> float:
    return float(np.clip(value, history.min(), history.max()))


def _risk_percentile(value: float, history: pd.Series) -> float:
    return float(history.le(value).mean())


def _markov_switching_ar_forecast(
    log_target: pd.Series,
    *,
    previous_params: np.ndarray | None = None,
) -> tuple[float, np.ndarray | None, bool, bool]:
    """Fit a two-state switching-intercept/variance AR(1) and forecast once."""

    values = pd.to_numeric(log_target, errors="coerce").dropna()
    if len(values) < 30:
        return np.nan, previous_params, False, False
    endog = values.iloc[1:].to_numpy(dtype=float)
    lagged = values.iloc[:-1].to_numpy(dtype=float).reshape(-1, 1)
    model = MarkovRegression(
        endog,
        k_regimes=2,
        trend="c",
        exog=lagged,
        switching_trend=True,
        switching_exog=False,
        switching_variance=True,
    )
    fit_options: dict[str, object] = {
        "disp": False,
        "maxiter": 75,
        "em_iter": 5,
    }
    if (
        previous_params is not None
        and len(previous_params) == model.k_params
        and np.isfinite(previous_params).all()
    ):
        fit_options["start_params"] = previous_params
    else:
        fit_options["search_reps"] = 5
        fit_options["search_iter"] = 5
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fitted = model.fit(**fit_options)
    except (ValueError, RuntimeError, np.linalg.LinAlgError):
        return np.nan, previous_params, False, False

    params = np.asarray(fitted.params, dtype=float)
    names = model.param_names
    named = dict(zip(names, params, strict=True))
    transition = np.asarray(fitted.regime_transition, dtype=float)[:, :, -1]
    filtered = np.asarray(
        fitted.filtered_marginal_probabilities,
        dtype=float,
    )[-1]
    forecast_probabilities = transition @ filtered
    ar_names = [name for name in names if name.startswith("x1")]
    if len(ar_names) != 1:
        return np.nan, params, False, False
    ar_coefficient = named[ar_names[0]]
    conditional = np.asarray(
        [
            named[f"const[{regime}]"]
            + ar_coefficient * float(values.iloc[-1])
            for regime in range(2)
        ]
    )
    forecast = float(forecast_probabilities @ conditional)
    converged = bool(fitted.mle_retvals.get("converged", False))
    return forecast, params, True, converged


def _fit_direct_models(
    features: pd.DataFrame,
    target: pd.Series,
    *,
    min_train: int,
) -> pd.DataFrame:
    rows = []
    previous_ms_params: np.ndarray | None = None
    aligned_target = pd.to_numeric(
        target.reindex(features.index),
        errors="coerce",
    )
    for position in range(min_train, len(features)):
        date = features.index[position]
        train_x = features.iloc[:position].copy()
        train_y = aligned_target.iloc[:position].dropna()
        train_x = train_x.reindex(train_y.index)
        if len(train_y) < min_train:
            continue
        log_y = np.log(train_y.clip(lower=1e-8))
        scaler = StandardScaler().fit(train_x)
        scaled_train = scaler.transform(train_x)
        scaled_test = scaler.transform(features.iloc[[position]])

        ridge_log = float(
            Ridge(alpha=10.0)
            .fit(scaled_train, log_y)
            .predict(scaled_test)[0]
        )
        ridge_log = _clip_log_prediction(ridge_log, log_y)
        elastic_log = float(
            ElasticNet(
                alpha=0.05,
                l1_ratio=0.25,
                max_iter=10_000,
            )
            .fit(scaled_train, log_y)
            .predict(scaled_test)[0]
        )
        elastic_log = _clip_log_prediction(elastic_log, log_y)

        high_threshold = float(train_y.quantile(2 / 3))
        high_target = train_y.ge(high_threshold).astype(int)
        logistic_probability = float(
            LogisticRegression(
                C=0.3,
                class_weight="balanced",
                max_iter=2_000,
            )
            .fit(scaled_train, high_target)
            .predict_proba(scaled_test)[0, 1]
        )
        (
            markov_log,
            previous_ms_params,
            markov_fit_success,
            markov_converged,
        ) = _markov_switching_ar_forecast(
            log_y,
            previous_params=previous_ms_params,
        )
        if np.isfinite(markov_log):
            markov_log = _clip_log_prediction(markov_log, log_y)

        ridge_prediction = float(np.exp(ridge_log))
        ridge_percentile = _risk_percentile(
            ridge_prediction,
            train_y,
        )
        ensemble = 0.5 * ridge_percentile + 0.5 * logistic_probability
        predictions = {
            "volatility_persistence": float(
                features.iloc[position]["rvol_ann"]
            ),
            "ridge": ridge_prediction,
            "elastic_net": float(np.exp(elastic_log)),
            "logistic": logistic_probability,
            "markov_switching_ar": (
                float(np.exp(markov_log))
                if np.isfinite(markov_log)
                else np.nan
            ),
            "ridge_logistic_ensemble": ensemble,
        }
        for model_name, prediction in predictions.items():
            rows.append(
                {
                    "Date": date,
                    "model": model_name,
                    "prediction": prediction,
                    "train_months": len(train_y),
                    "dynamic_high_risk_threshold": high_threshold,
                    "fit_success": bool(np.isfinite(prediction)),
                    "fit_converged": (
                        markov_converged
                        if model_name == "markov_switching_ar"
                        else True
                    ),
                    "prediction_kind": (
                        "probability"
                        if model_name
                        in ("logistic", "ridge_logistic_ensemble")
                        else "risk_level_or_score"
                    ),
                    "msar_fit_success": (
                        markov_fit_success
                        if model_name == "markov_switching_ar"
                        else pd.NA
                    ),
                }
            )
    return pd.DataFrame(rows)


def _current_hmm_predictions(
    region: str,
    target: pd.Series,
    dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    states_path = regime_config.OUTPUT_DIR / f"regime_oos_{region}.parquet"
    states = pd.read_parquet(states_path)["state"].sort_index()
    target = pd.to_numeric(target, errors="coerce")
    rows = []
    for date in dates:
        current_state = states.get(date, np.nan)
        prediction = np.nan
        history_months = 0
        if pd.notna(current_state):
            past_states = states[states.index < date]
            past_target = target.reindex(past_states.index).dropna()
            past_states = past_states.reindex(past_target.index)
            same = past_target[past_states.eq(current_state)]
            prediction = float(
                same.mean() if len(same) else past_target.mean()
            )
            history_months = len(past_target)
        rows.append(
            {
                "Date": date,
                "model": "current_hmm",
                "prediction": prediction,
                "train_months": history_months,
                "dynamic_high_risk_threshold": np.nan,
                "fit_success": bool(np.isfinite(prediction)),
                "fit_converged": True,
                "prediction_kind": "risk_level",
                "msar_fit_success": pd.NA,
            }
        )
    return pd.DataFrame(rows)


def _safe_auc(actual: pd.Series, score: pd.Series) -> float:
    valid = actual.notna() & score.notna()
    if valid.sum() < 10 or actual[valid].nunique() < 2:
        return np.nan
    return float(
        roc_auc_score(
            actual[valid].astype(int),
            score[valid].astype(float),
        )
    )


def _uniform_metrics(
    actual: pd.Series,
    prediction: pd.Series,
) -> dict[str, float | int]:
    joined = pd.concat(
        [actual.rename("actual"), prediction.rename("prediction")],
        axis=1,
    ).dropna()
    if joined.empty:
        return {
            "months": 0,
            "spearman": np.nan,
            "high_risk_auc": np.nan,
            "precision": np.nan,
            "recall": np.nan,
            "false_positive_rate": np.nan,
            "predicted_high_realized_ratio": np.nan,
        }
    high_actual = joined["actual"].ge(
        joined["actual"].quantile(2 / 3)
    )
    high_prediction = joined["prediction"].ge(
        joined["prediction"].quantile(2 / 3)
    )
    tp = int((high_actual & high_prediction).sum())
    fp = int((~high_actual & high_prediction).sum())
    fn = int((high_actual & ~high_prediction).sum())
    tn = int((~high_actual & ~high_prediction).sum())
    overall_mean = float(joined["actual"].mean())
    predicted_high_mean = float(
        joined.loc[high_prediction, "actual"].mean()
    )
    return {
        "months": len(joined),
        "spearman": float(
            joined["actual"].corr(
                joined["prediction"],
                method="spearman",
            )
        ),
        "high_risk_auc": _safe_auc(
            high_actual,
            joined["prediction"],
        ),
        "precision": tp / (tp + fp) if tp + fp else np.nan,
        "recall": tp / (tp + fn) if tp + fn else np.nan,
        "false_positive_rate": fp / (fp + tn) if fp + tn else np.nan,
        "predicted_high_realized_ratio": (
            predicted_high_mean / overall_mean
            if overall_mean > 0
            else np.nan
        ),
    }


def _select_dates(
    dates: pd.DatetimeIndex,
    start: str | None,
    end: str | None,
) -> pd.DatetimeIndex:
    selected = dates
    if start is not None:
        selected = selected[selected >= pd.Timestamp(start)]
    if end is not None:
        selected = selected[selected <= pd.Timestamp(end)]
    return selected


def _evaluate_predictions(
    predictions: pd.DataFrame,
    risks: Mapping[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    common_rows = []
    available_rows = []
    for region in REGIONS:
        for target_name in TARGETS:
            selected = predictions[
                predictions["region"].eq(region)
                & predictions["target"].eq(target_name)
            ]
            pivot = selected.pivot(
                index="Date",
                columns="model",
                values="prediction",
            )
            actual = risks[region][target_name]
            common_dates = (
                pivot.reindex(columns=MODELS)
                .dropna()
                .index.intersection(actual.dropna().index)
            )
            for period_name, (start, end) in COMMON_PERIODS.items():
                period_dates = _select_dates(common_dates, start, end)
                for model_name in MODELS:
                    common_rows.append(
                        {
                            "region": region,
                            "target": target_name,
                            "period": period_name,
                            "model": model_name,
                            **_uniform_metrics(
                                actual.reindex(period_dates),
                                pivot[model_name].reindex(period_dates),
                            ),
                        }
                    )
            for model_name in MODELS:
                model_prediction = pivot[model_name].dropna()
                available_dates = model_prediction.index.intersection(
                    actual.dropna().index
                )
                available_rows.append(
                    {
                        "region": region,
                        "target": target_name,
                        "period": "available_full",
                        "model": model_name,
                        **_uniform_metrics(
                            actual.reindex(available_dates),
                            model_prediction.reindex(available_dates),
                        ),
                    }
                )
    return pd.DataFrame(common_rows), pd.DataFrame(available_rows)


def _joint_summary(metrics: pd.DataFrame) -> pd.DataFrame:
    summary = (
        metrics.groupby(["region", "period", "model"], observed=True)
        .agg(
            targets=("target", "nunique"),
            minimum_months=("months", "min"),
            mean_spearman=("spearman", "mean"),
            mean_high_risk_auc=("high_risk_auc", "mean"),
            mean_precision=("precision", "mean"),
            mean_recall=("recall", "mean"),
            mean_false_positive_rate=("false_positive_rate", "mean"),
        )
        .reset_index()
    )
    summary["joint_score"] = (
        summary["mean_high_risk_auc"]
        + 0.5
        + 0.5 * summary["mean_spearman"]
    ) / 2
    return summary


def _selection_decision(
    summary: pd.DataFrame,
) -> dict[str, object]:
    us = summary[summary["region"].eq("US")].set_index(
        ["period", "model"]
    )
    validation = us.loc["common_validation_2018_2021"]
    eligible_validation = validation.reindex(CHALLENGERS).dropna(
        subset=["joint_score"]
    )
    selected = str(
        eligible_validation.sort_values(
            ["joint_score", "mean_high_risk_auc", "mean_spearman"],
            ascending=False,
            kind="mergesort",
        ).index[0]
    )
    holdout = us.loc["common_holdout_2022_latest"]
    full = us.loc["common_full"]
    reference_models = ("current_hmm", "volatility_persistence")
    holdout_floor = max(
        float(holdout.loc[name, "joint_score"])
        for name in reference_models
    )
    full_floor = max(
        float(full.loc[name, "joint_score"])
        for name in reference_models
    )
    holdout_pass = (
        float(holdout.loc[selected, "joint_score"])
        >= holdout_floor + 0.02
    )
    full_pass = (
        float(full.loc[selected, "joint_score"]) >= full_floor + 0.02
    )
    return {
        "status": (
            "research_gate_pass_shadow_only"
            if holdout_pass and full_pass
            else "validation_winner_failed_joint_holdout_gate"
        ),
        "selection_rule": (
            "Highest US validation joint score among five challengers; "
            "holdout and full common windows must beat both current HMM "
            "and volatility persistence by at least 0.02."
        ),
        "validation_selected": selected,
        "holdout_gate_pass": bool(holdout_pass),
        "full_common_gate_pass": bool(full_pass),
        "production_promotion_allowed": False,
    }


def _format_table(frame: pd.DataFrame, columns: list[str]) -> str:
    selected = frame[columns].copy()
    numeric = selected.select_dtypes(include=[np.number]).columns
    selected[numeric] = selected[numeric].round(4)
    selected["model"] = selected["model"].map(MODEL_LABELS)
    return selected.to_markdown(index=False)


def _write_report(
    output_dir: Path,
    summary: pd.DataFrame,
    available_summary: pd.DataFrame,
    reliability: pd.DataFrame,
    decision: Mapping[str, object],
) -> None:
    us_full = summary[
        summary["region"].eq("US")
        & summary["period"].eq("common_full")
    ].sort_values("joint_score", ascending=False)
    us_validation = summary[
        summary["region"].eq("US")
        & summary["period"].eq("common_validation_2018_2021")
    ].sort_values("joint_score", ascending=False)
    us_holdout = summary[
        summary["region"].eq("US")
        & summary["period"].eq("common_holdout_2022_latest")
    ].sort_values("joint_score", ascending=False)
    eu_full = summary[
        summary["region"].eq("EU")
        & summary["period"].eq("common_full")
    ].sort_values("joint_score", ascending=False)
    report = f"""# Regime 风险预测七模型 Challenger

## 结论

- validation 选出的模型：`{decision["validation_selected"]}`
- 研究门状态：`{decision["status"]}`
- 所有结果均为 research/shadow evidence，没有修改生产 Regime 或风险预算。

## US 完整共同窗口

{_format_table(
    us_full,
    [
        "model",
        "minimum_months",
        "mean_spearman",
        "mean_high_risk_auc",
        "mean_precision",
        "mean_recall",
        "mean_false_positive_rate",
        "joint_score",
    ],
)}

## US 2018–2021 validation

{_format_table(
    us_validation,
    [
        "model",
        "minimum_months",
        "mean_spearman",
        "mean_high_risk_auc",
        "joint_score",
    ],
)}

## US 2022+ holdout

{_format_table(
    us_holdout,
    [
        "model",
        "minimum_months",
        "mean_spearman",
        "mean_high_risk_auc",
        "mean_recall",
        "mean_false_positive_rate",
        "joint_score",
    ],
)}

## EU 跨市场复核

{_format_table(
    eu_full,
    [
        "model",
        "minimum_months",
        "mean_spearman",
        "mean_high_risk_auc",
        "joint_score",
    ],
)}

## 各模型可用全窗口

{_format_table(
    available_summary.sort_values(
        ["region", "joint_score"],
        ascending=[True, False],
    ),
    [
        "region",
        "model",
        "minimum_months",
        "mean_spearman",
        "mean_high_risk_auc",
        "joint_score",
    ],
)}

## 拟合可靠性

{reliability.round(4).to_markdown(index=False)}

`common_*` 表只使用七个模型同时有预测的完全相同月份，是正式横向比较。
`available_full` 只用于观察直接模型的更长历史，不用于击败 HMM 的结论。
"""
    (output_dir / "regime_direct_risk_challenger_report_cn.md").write_text(
        report,
        encoding="utf-8",
    )


def run(
    output_dir: Path,
    *,
    parent_features_path: Path,
    min_train: int,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    parent_features_path = parent_features_path.resolve()
    if not parent_features_path.is_file():
        raise FileNotFoundError(parent_features_path)
    parent_features = pd.read_parquet(parent_features_path)

    feature_outputs = []
    prediction_outputs = []
    feature_checks = []
    risks: dict[str, pd.DataFrame] = {}
    for region in REGIONS:
        features, checks = _load_feature_matrix(region, parent_features)
        feature_checks.append(checks)
        tagged = features.reset_index()
        tagged["region"] = region
        feature_outputs.append(tagged)
        risks[region] = vol_compare.fwd_risk(region)
        for target_name in TARGETS:
            direct = _fit_direct_models(
                features,
                risks[region][target_name],
                min_train=min_train,
            )
            hmm = _current_hmm_predictions(
                region,
                risks[region][target_name],
                pd.DatetimeIndex(
                    sorted(direct["Date"].dropna().unique())
                ),
            )
            combined = pd.concat([direct, hmm], ignore_index=True)
            combined["region"] = region
            combined["target"] = target_name
            prediction_outputs.append(combined)

    features_frame = pd.concat(feature_outputs, ignore_index=True)
    predictions = pd.concat(prediction_outputs, ignore_index=True)
    common_metrics, available_metrics = _evaluate_predictions(
        predictions,
        risks,
    )
    summary = _joint_summary(common_metrics)
    available_summary = _joint_summary(available_metrics)
    decision = _selection_decision(summary)
    reliability = (
        predictions.groupby(["region", "target", "model"], observed=True)
        .agg(
            attempted_months=("Date", "nunique"),
            successful_months=("fit_success", "sum"),
            convergence_rate=("fit_converged", "mean"),
        )
        .reset_index()
    )
    reliability["success_rate"] = (
        reliability["successful_months"]
        / reliability["attempted_months"]
    )
    trial_ledger = pd.DataFrame(
        [
            {
                "trial_family": "regime_direct_risk_challengers",
                "candidate": model_name,
                "effective_trials": 1,
            }
            for model_name in MODELS
        ]
    )
    checks = pd.DataFrame(
        [
            {
                "check": "walk_forward_target_timing",
                "status": "pass",
                "detail": "prediction at t trains only on target rows dated before t",
            },
            {
                "check": "walk_forward_scaling",
                "status": "pass",
                "detail": "StandardScaler fitted separately on each expanding train window",
            },
            {
                "check": "logistic_threshold",
                "status": "pass",
                "detail": "top-tercile threshold estimated from each train window only",
            },
            {
                "check": "ensemble_definition",
                "status": "pass",
                "detail": "50% train-CDF Ridge percentile plus 50% Logistic probability",
            },
            {
                "check": "common_date_comparison",
                "status": "pass",
                "detail": "common metrics require valid predictions from all seven models",
            },
        ]
    )

    features_frame.to_parquet(
        output_dir / "challenger_feature_matrix.parquet",
        index=False,
    )
    predictions.to_parquet(
        output_dir / "walkforward_predictions.parquet",
        index=False,
    )
    common_metrics.to_csv(
        output_dir / "common_window_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    available_metrics.to_csv(
        output_dir / "available_window_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    summary.to_csv(
        output_dir / "joint_model_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    available_summary.to_csv(
        output_dir / "available_joint_model_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    reliability.to_csv(
        output_dir / "fit_reliability.csv",
        index=False,
        encoding="utf-8-sig",
    )
    trial_ledger.to_csv(
        output_dir / "trial_ledger.csv",
        index=False,
        encoding="utf-8-sig",
    )
    checks.to_csv(
        output_dir / "data_construction_checks.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (output_dir / "selection_audit.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_report(
        output_dir,
        summary,
        available_summary,
        reliability,
        decision,
    )
    manifest = {
        "status": "complete",
        "experiment_version": EXPERIMENT_VERSION,
        "pit_cutoff": "2026-06-30",
        "parent_features": str(parent_features_path),
        "parent_features_sha256": _sha256(parent_features_path),
        "regions": list(REGIONS),
        "targets": list(TARGETS),
        "models": list(MODELS),
        "feature_columns": list(FEATURE_COLUMNS),
        "feature_checks": feature_checks,
        "min_train_months": min_train,
        "fixed_parameters": {
            "ridge_alpha": 10.0,
            "elastic_net_alpha": 0.05,
            "elastic_net_l1_ratio": 0.25,
            "logistic_c": 0.3,
            "logistic_class_weight": "balanced",
            "markov_regimes": 2,
            "markov_ar_order": 1,
            "ensemble_weights": {
                "ridge_train_cdf_percentile": 0.5,
                "logistic_probability": 0.5,
            },
        },
        "decision": decision,
        "artifact_policy": {
            "plots": "none",
            "holdings": "none",
        },
        "promotion_boundary": "research_only_review_required",
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--parent-features",
        type=Path,
        default=DEFAULT_PARENT_FEATURES,
    )
    parser.add_argument("--min-train", type=int, default=60)
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest = run(
        Path(args.output_dir),
        parent_features_path=args.parent_features,
        min_train=args.min_train,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
