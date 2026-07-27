"""Compare causal regime-risk models, including leakage-safe stacking."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from tp_models.regime import vol_compare
from tp_research.workflows import (
    run_regime_direct_risk_challengers as v1,
)

EXPERIMENT_VERSION = "tp.regime.direct_risk_challengers:2.1.0"
ORIGINAL_MODELS = v1.MODELS
MODELS = (*ORIGINAL_MODELS, "stacked_meta_model")
CHALLENGERS = (*v1.CHALLENGERS, "stacked_meta_model")
REFERENCE_MODELS = ("current_hmm", "volatility_persistence")
STACK_BASE_MODELS = ORIGINAL_MODELS
MODEL_LABELS = {
    **v1.MODEL_LABELS,
    "stacked_meta_model": "因果 Stacked Meta Model",
}
MIN_EVALUATION_MONTHS = 10
META_MIN_TRAIN_MONTHS = 24
MSAR_RANDOM_SEEDS = {
    ("US", "fwd_vol"): 27_271,
    ("US", "fwd_mdd"): 27_272,
    ("EU", "fwd_vol"): 27_273,
    ("EU", "fwd_mdd"): 27_274,
}


def _causal_stack_features(
    base_predictions: pd.DataFrame,
) -> pd.DataFrame:
    """Normalize first-layer OOS outputs using only earlier predictions."""

    usable = base_predictions.copy()
    prediction_is_usable = pd.to_numeric(
        usable["prediction"],
        errors="coerce",
    ).notna()
    if "fit_success" in usable:
        prediction_is_usable &= usable["fit_success"].fillna(False).astype(
            bool
        )
    if "fit_converged" in usable:
        prediction_is_usable &= usable["fit_converged"].fillna(False).astype(
            bool
        )
    usable["usable_prediction"] = usable["prediction"].where(
        prediction_is_usable
    )
    pivot = (
        usable.pivot(
            index="Date",
            columns="model",
            values="usable_prediction",
        )
        .reindex(columns=STACK_BASE_MODELS)
        .sort_index()
    )
    rows: list[dict[str, object]] = []
    for position, date in enumerate(pivot.index):
        history = pivot.iloc[:position]
        current = pivot.iloc[position]
        row: dict[str, object] = {"Date": date}
        for model_name in STACK_BASE_MODELS:
            value = current[model_name]
            historical_values = history[model_name].dropna()
            available = bool(np.isfinite(value))
            if available and len(historical_values) >= 6:
                normalized = float(historical_values.le(value).mean())
            else:
                normalized = 0.5
            row[f"{model_name}__score"] = normalized
            row[f"{model_name}__available"] = float(available)
        rows.append(row)
    return pd.DataFrame(rows).set_index("Date")


def _fit_stacked_meta_model(
    base_predictions: pd.DataFrame,
    target: pd.Series,
    *,
    min_meta_train: int = META_MIN_TRAIN_MONTHS,
) -> pd.DataFrame:
    """Fit an online meta Ridge using only historical first-layer OOS outputs."""

    meta_features = _causal_stack_features(base_predictions)
    aligned_target = pd.to_numeric(
        target.reindex(meta_features.index),
        errors="coerce",
    )
    rows: list[dict[str, object]] = []
    for position in range(len(meta_features)):
        date = meta_features.index[position]
        train_y = aligned_target.iloc[:position].dropna()
        if len(train_y) < min_meta_train:
            continue
        train_x = meta_features.iloc[:position].reindex(train_y.index)
        log_y = np.log(train_y.clip(lower=1e-8))
        scaler = StandardScaler().fit(train_x)
        prediction_log = float(
            Ridge(alpha=1.0)
            .fit(scaler.transform(train_x), log_y)
            .predict(scaler.transform(meta_features.iloc[[position]]))[0]
        )
        prediction_log = v1._clip_log_prediction(prediction_log, log_y)
        prediction = float(np.exp(prediction_log))
        rows.append(
            {
                "Date": date,
                "model": "stacked_meta_model",
                "prediction": prediction,
                "train_months": len(train_y),
                "dynamic_high_risk_threshold": float(
                    train_y.quantile(2 / 3)
                ),
                "fit_success": bool(np.isfinite(prediction)),
                "fit_converged": True,
                "prediction_kind": "risk_level",
                "msar_fit_success": pd.NA,
            }
        )
    return pd.DataFrame(rows)


def _evaluate_pairwise_predictions(
    predictions: pd.DataFrame,
    risks: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Compare each challenger with both references on identical dates."""

    rows: list[dict[str, object]] = []
    for region in v1.REGIONS:
        for target_name in v1.TARGETS:
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
            for candidate in CHALLENGERS:
                compared_models = tuple(
                    dict.fromkeys((candidate, *REFERENCE_MODELS))
                )
                common_dates = (
                    pivot.reindex(columns=compared_models)
                    .dropna()
                    .index.intersection(actual.dropna().index)
                )
                for period_name, (start, end) in v1.COMMON_PERIODS.items():
                    period_dates = v1._select_dates(
                        common_dates,
                        start,
                        end,
                    )
                    for model_name in compared_models:
                        rows.append(
                            {
                                "region": region,
                                "target": target_name,
                                "period": period_name,
                                "comparison_candidate": candidate,
                                "model": model_name,
                                **v1._uniform_metrics(
                                    actual.reindex(period_dates),
                                    pivot[model_name].reindex(period_dates),
                                ),
                            }
                        )
    return pd.DataFrame(rows)


def _evaluate_all_model_common(
    predictions: pd.DataFrame,
    risks: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Retain an all-eight-model common-window diagnostic."""

    rows: list[dict[str, object]] = []
    for region in v1.REGIONS:
        for target_name in v1.TARGETS:
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
            for period_name, (start, end) in v1.COMMON_PERIODS.items():
                period_dates = v1._select_dates(common_dates, start, end)
                for model_name in MODELS:
                    rows.append(
                        {
                            "region": region,
                            "target": target_name,
                            "period": period_name,
                            "model": model_name,
                            **v1._uniform_metrics(
                                actual.reindex(period_dates),
                                pivot[model_name].reindex(period_dates),
                            ),
                        }
                    )
    return pd.DataFrame(rows)


def _evaluate_available_predictions(
    predictions: pd.DataFrame,
    risks: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for region in v1.REGIONS:
        for target_name in v1.TARGETS:
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
            for model_name in MODELS:
                model_prediction = pivot[model_name].dropna()
                available_dates = model_prediction.index.intersection(
                    actual.dropna().index
                )
                rows.append(
                    {
                        "region": region,
                        "target": target_name,
                        "period": "available_full",
                        "model": model_name,
                        **v1._uniform_metrics(
                            actual.reindex(available_dates),
                            model_prediction.reindex(available_dates),
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _joint_summary_strict(
    metrics: pd.DataFrame,
    *,
    extra_group_columns: Sequence[str] = (),
) -> pd.DataFrame:
    """Aggregate both targets without silently skipping a missing target."""

    group_columns = [
        "region",
        "period",
        *extra_group_columns,
        "model",
    ]
    summary = (
        metrics.groupby(group_columns, observed=True)
        .agg(
            targets=("target", "nunique"),
            minimum_months=("months", "min"),
            finite_spearman_targets=(
                "spearman",
                lambda values: int(np.isfinite(values).sum()),
            ),
            finite_auc_targets=(
                "high_risk_auc",
                lambda values: int(np.isfinite(values).sum()),
            ),
            mean_spearman=("spearman", "mean"),
            mean_high_risk_auc=("high_risk_auc", "mean"),
            mean_precision=("precision", "mean"),
            mean_recall=("recall", "mean"),
            mean_false_positive_rate=("false_positive_rate", "mean"),
        )
        .reset_index()
    )
    summary["target_metrics_complete"] = (
        summary["targets"].eq(len(v1.TARGETS))
        & summary["minimum_months"].ge(MIN_EVALUATION_MONTHS)
        & summary["finite_spearman_targets"].eq(len(v1.TARGETS))
        & summary["finite_auc_targets"].eq(len(v1.TARGETS))
    )
    metric_columns = [
        "mean_spearman",
        "mean_high_risk_auc",
        "mean_precision",
        "mean_recall",
        "mean_false_positive_rate",
    ]
    incomplete = ~summary["target_metrics_complete"]
    summary.loc[incomplete, metric_columns] = np.nan
    summary["joint_score"] = (
        summary["mean_high_risk_auc"]
        + 0.5
        + 0.5 * summary["mean_spearman"]
    ) / 2
    return summary


def _fit_reliability(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for period_name, (start, end) in v1.COMMON_PERIODS.items():
        dates = pd.DatetimeIndex(predictions["Date"].dropna().unique())
        selected_dates = v1._select_dates(dates, start, end)
        selected = predictions[predictions["Date"].isin(selected_dates)]
        grouped = (
            selected.groupby(
                ["region", "target", "model"],
                observed=True,
            )
            .agg(
                attempted_months=("Date", "nunique"),
                successful_months=("fit_success", "sum"),
                convergence_rate=("fit_converged", "mean"),
            )
            .reset_index()
        )
        grouped["period"] = period_name
        grouped["success_rate"] = (
            grouped["successful_months"]
            / grouped["attempted_months"]
        )
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True)


def _candidate_reliable(
    reliability: pd.DataFrame,
    model_name: str,
    period: str,
) -> bool:
    selected = reliability[
        reliability["region"].eq("US")
        & reliability["period"].eq(period)
        & reliability["model"].eq(model_name)
    ]
    return bool(
        selected["target"].nunique() == len(v1.TARGETS)
        and selected["attempted_months"].ge(
            MIN_EVALUATION_MONTHS
        ).all()
        and selected["success_rate"].ge(0.95).all()
        and selected["convergence_rate"].ge(0.90).all()
    )


def _selection_decision(
    pairwise_summary: pd.DataFrame,
    reliability: pd.DataFrame,
) -> dict[str, object]:
    validation_period = "common_validation_2018_2021"
    candidate_rows = pairwise_summary[
        pairwise_summary["region"].eq("US")
        & pairwise_summary["period"].eq(validation_period)
        & pairwise_summary["model"].eq(
            pairwise_summary["comparison_candidate"]
        )
        & pairwise_summary["target_metrics_complete"]
    ].copy()
    candidate_rows["reliability_gate_pass"] = candidate_rows[
        "model"
    ].map(
        lambda model: _candidate_reliable(
            reliability,
            str(model),
            validation_period,
        )
    )
    eligible = candidate_rows[candidate_rows["reliability_gate_pass"]]
    if eligible.empty:
        return {
            "status": "no_validation_candidate_passed_reliability_gate",
            "selection_rule": "No candidate eligible for holdout review.",
            "validation_selected": None,
            "holdout_gate_pass": False,
            "full_common_gate_pass": False,
            "production_promotion_allowed": False,
        }
    selected = str(
        eligible.sort_values(
            [
                "joint_score",
                "mean_high_risk_auc",
                "mean_spearman",
            ],
            ascending=False,
            kind="mergesort",
        ).iloc[0]["model"]
    )

    def period_gate(period: str) -> bool:
        selected_comparison = pairwise_summary[
            pairwise_summary["region"].eq("US")
            & pairwise_summary["period"].eq(period)
            & pairwise_summary["comparison_candidate"].eq(selected)
        ].set_index("model")
        required = (selected, *REFERENCE_MODELS)
        if not all(name in selected_comparison.index for name in required):
            return False
        if not selected_comparison.loc[
            list(required),
            "target_metrics_complete",
        ].all():
            return False
        if not _candidate_reliable(reliability, selected, period):
            return False
        reference_floor = max(
            float(selected_comparison.loc[name, "joint_score"])
            for name in REFERENCE_MODELS
        )
        return bool(
            float(selected_comparison.loc[selected, "joint_score"])
            >= reference_floor + 0.02
        )

    holdout_pass = period_gate("common_holdout_2022_latest")
    full_pass = period_gate("common_full")
    return {
        "status": (
            "research_gate_pass_shadow_only"
            if holdout_pass and full_pass
            else "validation_winner_failed_joint_holdout_gate"
        ),
        "selection_rule": (
            "Highest US 2018-2021 validation joint score among challengers "
            "that pass both-target fit reliability; on candidate-specific "
            "identical dates, 2022+ holdout and full windows must beat both "
            "current HMM and volatility persistence by at least 0.02."
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
    if "model" in selected:
        selected["model"] = selected["model"].map(MODEL_LABELS)
    return selected.to_markdown(index=False)


def _write_report(
    output_dir: Path,
    pairwise_summary: pd.DataFrame,
    all_common_summary: pd.DataFrame,
    available_summary: pd.DataFrame,
    reliability: pd.DataFrame,
    decision: Mapping[str, object],
) -> None:
    candidate_rows = pairwise_summary[
        pairwise_summary["model"].eq(
            pairwise_summary["comparison_candidate"]
        )
    ]
    us_validation = candidate_rows[
        candidate_rows["region"].eq("US")
        & candidate_rows["period"].eq(
            "common_validation_2018_2021"
        )
    ].sort_values("joint_score", ascending=False)
    us_holdout = candidate_rows[
        candidate_rows["region"].eq("US")
        & candidate_rows["period"].eq(
            "common_holdout_2022_latest"
        )
    ].sort_values("joint_score", ascending=False)
    eu_full = candidate_rows[
        candidate_rows["region"].eq("EU")
        & candidate_rows["period"].eq("common_full")
    ].sort_values("joint_score", ascending=False)
    selected_model = decision["validation_selected"]
    selected_benchmarks = pairwise_summary.iloc[0:0]
    if selected_model is not None:
        selected_benchmarks = pairwise_summary[
            pairwise_summary["region"].eq("US")
            & pairwise_summary["comparison_candidate"].eq(selected_model)
            & pairwise_summary["period"].isin(
                [
                    "common_holdout_2022_latest",
                    "common_full",
                ]
            )
        ].sort_values(["period", "joint_score"], ascending=[True, False])
    us_all_common = all_common_summary[
        all_common_summary["region"].eq("US")
        & all_common_summary["period"].eq("common_full")
    ]
    reliability_view = reliability[
        reliability["region"].eq("US")
        & reliability["model"].isin(CHALLENGERS)
        & reliability["period"].isin(
            [
                "common_validation_2018_2021",
                "common_holdout_2022_latest",
            ]
        )
    ]
    report = f"""# Regime 风险预测 Challenger v2

## 结论

- validation 选出的模型：`{selected_model}`
- 研究门状态：`{decision["status"]}`
- v1 的选择结论因缺失目标被平均时跳过而无效；v1 Run Card 只保留审计。
- v2 的 MS-AR 随机初始化未固定；v2 Run Card 只保留审计，不作为稳定结论。
- 本实验不修改生产 Regime 或风险预算，最多进入 shadow。

## 真正使用其他模型输出的方式

`stacked_meta_model` 读取七个第一层模型的历史逐月 OOS 输出。每个输出先
用严格早于预测月的历史预测转成因果分位数，并附带可用性标记；第二层
Ridge 只用已经实现目标的历史 OOS 行训练。MS-AR 缺失时用中性 0.5 加
可用性 0 标记，不使用未来信息，也不使用第一层模型的样本内拟合值。

## US 2018–2021 validation 候选比较

{_format_table(
    us_validation,
    [
        "model",
        "minimum_months",
        "target_metrics_complete",
        "mean_spearman",
        "mean_high_risk_auc",
        "joint_score",
    ],
)}

## US 2022+ holdout 候选比较

{_format_table(
    us_holdout,
    [
        "model",
        "minimum_months",
        "target_metrics_complete",
        "mean_spearman",
        "mean_high_risk_auc",
        "joint_score",
    ],
)}

## validation 胜者与基准的严格同窗比较

{_format_table(
    selected_benchmarks,
    [
        "period",
        "model",
        "minimum_months",
        "mean_spearman",
        "mean_high_risk_auc",
        "joint_score",
    ],
)}

## EU 跨市场复核

{_format_table(
    eu_full,
    [
        "model",
        "minimum_months",
        "target_metrics_complete",
        "mean_spearman",
        "mean_high_risk_auc",
        "joint_score",
    ],
)}

## 八模型完整共同窗口诊断

{_format_table(
    us_all_common,
    [
        "model",
        "minimum_months",
        "target_metrics_complete",
        "mean_spearman",
        "mean_high_risk_auc",
        "joint_score",
    ],
)}

如果 MS-AR 令完整共同窗口为空，本表会明确显示不完整且不计算联合分数，
不会再用另一个目标的成绩替代。

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
        "target_metrics_complete",
        "mean_spearman",
        "mean_high_risk_auc",
        "joint_score",
    ],
)}

## US 候选拟合可靠性

{reliability_view.round(4).to_markdown(index=False)}

候选排名使用“候选＋当前 HMM＋波动持续性”三者都有预测的完全相同月份；
validation 只负责选型，2022+ holdout 只负责门控。
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

    feature_outputs: list[pd.DataFrame] = []
    prediction_outputs: list[pd.DataFrame] = []
    feature_checks: list[dict[str, object]] = []
    risks: dict[str, pd.DataFrame] = {}
    for region in v1.REGIONS:
        features, checks = v1._load_feature_matrix(
            region,
            parent_features,
        )
        feature_checks.append(checks)
        tagged = features.reset_index()
        tagged["region"] = region
        feature_outputs.append(tagged)
        risks[region] = vol_compare.fwd_risk(region)
        for target_name in v1.TARGETS:
            random_state = np.random.get_state()
            np.random.seed(MSAR_RANDOM_SEEDS[(region, target_name)])
            try:
                direct = v1._fit_direct_models(
                    features,
                    risks[region][target_name],
                    min_train=min_train,
                )
            finally:
                np.random.set_state(random_state)
            hmm = v1._current_hmm_predictions(
                region,
                risks[region][target_name],
                pd.DatetimeIndex(
                    sorted(direct["Date"].dropna().unique())
                ),
            )
            first_layer = pd.concat([direct, hmm], ignore_index=True)
            stack = _fit_stacked_meta_model(
                first_layer,
                risks[region][target_name],
            )
            combined = pd.concat(
                [first_layer, stack],
                ignore_index=True,
            )
            combined["region"] = region
            combined["target"] = target_name
            prediction_outputs.append(combined)

    features_frame = pd.concat(feature_outputs, ignore_index=True)
    predictions = pd.concat(prediction_outputs, ignore_index=True)
    pairwise_metrics = _evaluate_pairwise_predictions(predictions, risks)
    all_common_metrics = _evaluate_all_model_common(predictions, risks)
    available_metrics = _evaluate_available_predictions(
        predictions,
        risks,
    )
    pairwise_summary = _joint_summary_strict(
        pairwise_metrics,
        extra_group_columns=("comparison_candidate",),
    )
    all_common_summary = _joint_summary_strict(all_common_metrics)
    available_summary = _joint_summary_strict(available_metrics)
    reliability = _fit_reliability(predictions)
    decision = _selection_decision(pairwise_summary, reliability)

    trial_ledger = pd.DataFrame(
        [
            {
                "trial_family": "regime_direct_risk_challengers_v2",
                "candidate": model_name,
                "effective_trials": 1,
            }
            for model_name in MODELS
        ]
    )
    checks = pd.DataFrame(
        [
            {
                "check": "first_layer_oos_only",
                "status": "pass",
                "detail": (
                    "meta features are generated from monthly first-layer "
                    "walk-forward predictions"
                ),
            },
            {
                "check": "meta_target_timing",
                "status": "pass",
                "detail": (
                    "meta prediction at t trains only on OOS prediction "
                    "rows and targets dated before t"
                ),
            },
            {
                "check": "causal_output_normalization",
                "status": "pass",
                "detail": (
                    "each first-layer score at t uses only output history "
                    "strictly before t"
                ),
            },
            {
                "check": "missing_model_output",
                "status": "pass",
                "detail": (
                    "missing or non-converged base output is neutral 0.5 "
                    "with availability flag 0"
                ),
            },
            {
                "check": "deterministic_msar_initialization",
                "status": "pass",
                "detail": (
                    "fixed per-market and per-target NumPy seeds isolate "
                    "statsmodels random parameter search"
                ),
            },
            {
                "check": "strict_both_target_summary",
                "status": "pass",
                "detail": (
                    "joint score is unavailable unless both risk targets "
                    "have at least 10 valid months and finite metrics"
                ),
            },
            {
                "check": "pairwise_common_date_comparison",
                "status": "pass",
                "detail": (
                    "each candidate and both references use identical dates"
                ),
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
    pairwise_metrics.to_csv(
        output_dir / "pairwise_common_window_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pairwise_summary.to_csv(
        output_dir / "pairwise_joint_model_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    all_common_metrics.to_csv(
        output_dir / "eight_model_common_window_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    all_common_summary.to_csv(
        output_dir / "eight_model_joint_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    available_metrics.to_csv(
        output_dir / "available_window_metrics.csv",
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
        pairwise_summary,
        all_common_summary,
        available_summary,
        reliability,
        decision,
    )
    manifest = {
        "status": "complete",
        "experiment_version": EXPERIMENT_VERSION,
        "pit_cutoff": "2026-06-30",
        "invalidated_predecessor_run_id": "20260726T221502Z-b481d8bb",
        "parent_features": str(parent_features_path),
        "parent_features_sha256": v1._sha256(parent_features_path),
        "regions": list(v1.REGIONS),
        "targets": list(v1.TARGETS),
        "models": list(MODELS),
        "feature_columns": list(v1.FEATURE_COLUMNS),
        "feature_checks": feature_checks,
        "min_train_months": min_train,
        "meta_min_train_months": META_MIN_TRAIN_MONTHS,
        "fixed_parameters": {
            "first_layer": {
                "ridge_alpha": 10.0,
                "elastic_net_alpha": 0.05,
                "elastic_net_l1_ratio": 0.25,
                "logistic_c": 0.3,
                "markov_regimes": 2,
                "simple_ensemble_weights": {
                    "ridge_train_cdf_percentile": 0.5,
                    "logistic_probability": 0.5,
                },
            },
            "stacked_meta_model": {
                "base_models": list(STACK_BASE_MODELS),
                "normalization": "strictly_prior_oos_prediction_cdf",
                "missing_score": 0.5,
                "availability_indicators": True,
                "requires_converged_base_fit": True,
                "meta_model": "Ridge",
                "meta_ridge_alpha": 1.0,
            },
            "msar_random_seeds": {
                f"{region}_{target}": seed
                for (region, target), seed in MSAR_RANDOM_SEEDS.items()
            },
        },
        "decision": decision,
        "artifact_policy": {
            "plots": "none",
            "holdings": "none",
        },
        "promotion_boundary": "research_only_review_required",
        "holdout_interpretation": (
            "retrospective_only_after_v1_v2_exposure; prospective shadow "
            "evidence required before production review"
        ),
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
        default=v1.DEFAULT_PARENT_FEATURES,
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
