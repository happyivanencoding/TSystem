"""Attribute and stress-test the two research-gated v1 model enhancements."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from tp_models.regime import config as regime_config
from tp_models.regime import model as regime_model
from tp_models.regime import vol_compare
from tp_models.sector import model as sector_model
from tp_research.workflows.run_regime_sector_factor_rotation_research import (
    REGIME_BASELINE_COLUMNS,
    _active_metrics,
    _regime_metrics,
    _safe_auc,
    _select_period,
    _walk_forward_states,
    build_sector_candidates,
)

DEEP_DIVE_VERSION = "tp.bottom_up_factor_rotation.deep_dive:2.0.0"
DEFAULT_PARENT_RESULTS = Path(
    "artifacts/research/runs/regime-sector-factor-rotation-v1/"
    "20260726T145612Z-4dda8e92/results"
)
PERIODS = {
    "early_oos_through_2021": (None, "2021-12-31"),
    "holdout_2022_latest": ("2022-01-01", None),
    "full_oos": (None, None),
}
US_EXTRA_COLUMNS = {
    "core_transition": "core_transition_breadth_ewma3",
    "confirmation_transition": "confirmation_transition_breadth_ewma3",
    "core_revision": "core_revision_breadth_ewma3",
    "core_rotation": "core_rotation_dispersion_ewma3",
}
US_MODEL_FEATURES = {
    "baseline_core": (),
    "core_transition_only": ("core_transition",),
    "confirmation_transition_only": ("confirmation_transition",),
    "dual_transition": ("core_transition", "confirmation_transition"),
    "all_without_revision": (
        "core_transition",
        "confirmation_transition",
        "core_rotation",
    ),
    "all_without_rotation": (
        "core_transition",
        "confirmation_transition",
        "core_revision",
    ),
    "all_bottom_up": tuple(US_EXTRA_COLUMNS),
}
EU_PRIMARY_CANDIDATE = "conditional_15_35"
EU_DIAGNOSTIC_CANDIDATES = (
    "baseline_rank",
    "fixed_diffusion_15",
    "fixed_diffusion_25",
    "fixed_diffusion_35",
    EU_PRIMARY_CANDIDATE,
    "conditional_10_30",
    "conditional_20_40",
    "conditional_threshold_45",
    "conditional_threshold_55",
    "quality_25",
    "deleveraging_25",
    "earnings_yield_25",
    "revision_25",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _period(
    frame: pd.DataFrame | pd.Series,
    start: str | None,
    end: str | None,
) -> pd.DataFrame | pd.Series:
    selected = frame
    if start is not None:
        selected = selected[selected.index >= pd.Timestamp(start)]
    if end is not None:
        selected = selected[selected.index <= pd.Timestamp(end)]
    return selected


def _risk_mean(metrics: Mapping[str, float | int]) -> float:
    return float(
        np.nanmean(
            [
                metrics["state_fwd_vol_spearman"],
                metrics["state_fwd_mdd_spearman"],
            ]
        )
    )


def _classification_metrics(
    states: pd.Series,
    risk: pd.DataFrame,
    *,
    high_state: int = 2,
) -> list[dict[str, float | int | str]]:
    joined = states.rename("state").to_frame().join(risk, how="inner")
    predicted = joined["state"].ge(high_state)
    rows: list[dict[str, float | int | str]] = []
    for target in ("fwd_vol", "fwd_mdd"):
        actual = joined[target].ge(joined[target].quantile(2 / 3))
        tp = int((predicted & actual).sum())
        fp = int((predicted & ~actual).sum())
        fn = int((~predicted & actual).sum())
        tn = int((~predicted & ~actual).sum())
        rows.append(
            {
                "target": target,
                "months": len(joined),
                "precision": tp / (tp + fp) if tp + fp else np.nan,
                "recall": tp / (tp + fn) if tp + fn else np.nan,
                "false_positive_rate": fp / (fp + tn) if fp + tn else np.nan,
                "predicted_high_rate": float(predicted.mean()),
            }
        )
    return rows


def _us_lead_diagnostics(
    market: pd.DataFrame,
    risk: pd.DataFrame,
) -> pd.DataFrame:
    work = market.set_index("Date").sort_index()
    stress_features = {
        "core_transition_stress": 1 - work["core_transition_breadth_ewma3"],
        "confirmation_transition_stress": (
            1 - work["confirmation_transition_breadth_ewma3"]
        ),
        "core_revision_stress": 1 - work["core_revision_breadth_ewma3"],
        "core_rotation_dispersion": work["core_rotation_dispersion_ewma3"],
    }
    stress_features["dual_transition_stress"] = pd.concat(
        [
            stress_features["core_transition_stress"],
            stress_features["confirmation_transition_stress"],
        ],
        axis=1,
    ).mean(axis=1)
    market_return = regime_model.market_fwd_return("US")
    rows = []
    for horizon in (1, 2, 3):
        shifted_risk = risk.shift(-(horizon - 1))
        shifted_return = market_return.shift(-(horizon - 1))
        for name, values in stress_features.items():
            rows.append(
                {
                    "feature": name,
                    "horizon_months": horizon,
                    "months": int(
                        values.notna().mul(shifted_risk["fwd_vol"].notna()).sum()
                    ),
                    "fwd_vol_spearman": values.corr(
                        shifted_risk["fwd_vol"],
                        method="spearman",
                    ),
                    "fwd_mdd_spearman": values.corr(
                        shifted_risk["fwd_mdd"],
                        method="spearman",
                    ),
                    "negative_fwd_return_spearman": values.corr(
                        -shifted_return,
                        method="spearman",
                    ),
                }
            )
    return pd.DataFrame(rows)


def _direct_score_metrics(
    market: pd.DataFrame,
    risk: pd.DataFrame,
) -> pd.DataFrame:
    indexed = market.set_index("Date").sort_index()
    score = 1 - indexed[
        [
            "core_transition_breadth_ewma3",
            "confirmation_transition_breadth_ewma3",
        ]
    ].mean(axis=1)
    rows = []
    for period_name, (start, end) in PERIODS.items():
        period_score = _period(score, start, end)
        period_risk = _period(risk, start, end)
        joined = period_score.rename("score").to_frame().join(
            period_risk,
            how="inner",
        )
        high_vol = joined["fwd_vol"].ge(joined["fwd_vol"].quantile(2 / 3))
        high_mdd = joined["fwd_mdd"].ge(joined["fwd_mdd"].quantile(2 / 3))
        rows.append(
            {
                "period": period_name,
                "months": len(joined),
                "fwd_vol_spearman": joined["score"].corr(
                    joined["fwd_vol"],
                    method="spearman",
                ),
                "fwd_mdd_spearman": joined["score"].corr(
                    joined["fwd_mdd"],
                    method="spearman",
                ),
                "high_vol_auc": _safe_auc(high_vol, joined["score"]),
                "high_mdd_auc": _safe_auc(high_mdd, joined["score"]),
            }
        )
    return pd.DataFrame(rows)


def _load_parent_us_states(parent_results: Path) -> dict[str, pd.Series]:
    frame = pd.read_csv(
        parent_results / "regime_walkforward_states.csv",
        parse_dates=["Date"],
    )
    frame = frame[frame["region"].eq("US")].set_index("Date").sort_index()
    return {
        "baseline_core": frame["baseline_state"].astype(int),
        "all_bottom_up": frame["enhanced_state"].astype(int),
    }


def _run_us_attribution(
    parent_results: Path,
    market_features: pd.DataFrame,
    *,
    min_train: int,
    hmm_n_init: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    us_market = market_features[market_features["region"].eq("US")].copy()
    us_market["Date"] = pd.to_datetime(us_market["Date"], errors="coerce")
    us_market = us_market.sort_values("Date")
    us_indexed = us_market.set_index("Date")

    production = regime_model.load_features("US")
    baseline_columns = [
        column for column in REGIME_BASELINE_COLUMNS if column in production
    ]
    baseline = production[baseline_columns].copy()
    extras = us_indexed[list(US_EXTRA_COLUMNS.values())].copy()
    full_matrix = baseline.join(extras, how="inner").ffill().dropna()
    baseline = baseline.reindex(full_matrix.index)

    states = _load_parent_us_states(parent_results)
    for model_name, feature_keys in US_MODEL_FEATURES.items():
        if model_name in states:
            continue
        columns = [US_EXTRA_COLUMNS[key] for key in feature_keys]
        feature_matrix = baseline.join(full_matrix[columns], how="inner")
        states[model_name] = _walk_forward_states(
            feature_matrix,
            k=regime_config.FIXED_K,
            min_train=min_train,
            n_init=hmm_n_init,
        )

    common = full_matrix.index
    for values in states.values():
        common = common.intersection(values.index)
    states = {name: values.reindex(common) for name, values in states.items()}
    risk = vol_compare.fwd_risk("US")

    metric_rows = []
    classification_rows = []
    for model_name, model_features in US_MODEL_FEATURES.items():
        for period_name, (start, end) in PERIODS.items():
            period_states = _period(states[model_name], start, end)
            period_risk = _period(risk, start, end)
            metrics = _regime_metrics(
                period_states.rename("state"),
                region="US",
                k=regime_config.FIXED_K,
                risk=period_risk,
            )
            metric_rows.append(
                {
                    "model": model_name,
                    "period": period_name,
                    "extra_feature_count": len(model_features),
                    **metrics,
                    "risk_spearman_mean": _risk_mean(metrics),
                }
            )
            for row in _classification_metrics(period_states, period_risk):
                classification_rows.append(
                    {
                        "model": model_name,
                        "period": period_name,
                        **row,
                    }
                )

    metrics_frame = pd.DataFrame(metric_rows)
    classification_frame = pd.DataFrame(classification_rows)
    state_frame = pd.DataFrame(states)
    state_frame.index.name = "Date"
    state_frame = state_frame.reset_index()

    full = metrics_frame[metrics_frame["period"].eq("full_oos")].set_index(
        "model"
    )
    holdout = metrics_frame[
        metrics_frame["period"].eq("holdout_2022_latest")
    ].set_index("model")
    baseline_full = full.loc["baseline_core"]
    baseline_holdout = holdout.loc["baseline_core"]
    eligible = []
    for model_name in US_MODEL_FEATURES:
        if model_name == "baseline_core":
            continue
        row = full.loc[model_name]
        holdout_row = holdout.loc[model_name]
        if (
            row["risk_spearman_mean"]
            >= baseline_full["risk_spearman_mean"] + 0.02
            and holdout_row["risk_spearman_mean"]
            >= baseline_holdout["risk_spearman_mean"]
            and row["high_vol_auc"] >= baseline_full["high_vol_auc"] - 0.02
            and row["high_mdd_auc"] >= baseline_full["high_mdd_auc"] - 0.02
        ):
            eligible.append(model_name)
    if eligible:
        selected = min(
            eligible,
            key=lambda name: (
                len(US_MODEL_FEATURES[name]),
                -float(full.loc[name, "risk_spearman_mean"]),
                name,
            ),
        )
        if selected == "all_bottom_up":
            status = "retain_full_shadow_candidate"
            reason = (
                "只有完整四变量组合通过完整 OOS、2022+ 稳定性和 AUC "
                "下限；当前证据不支持精简 HMM 输入。"
            )
        else:
            status = "minimal_shadow_candidate"
            reason = (
                "通过完整 OOS、2022+ 稳定性和 AUC 下限后，"
                "选择额外特征最少的候选。"
            )
    else:
        selected = "all_bottom_up"
        status = "retain_v1_shadow"
        reason = "没有精简候选通过预注册的完整 OOS、holdout 与 AUC 联合门。"
    decision = {
        "status": status,
        "selected": selected,
        "extra_features": list(US_MODEL_FEATURES[selected]),
        "reason": reason,
    }
    return (
        metrics_frame,
        classification_frame,
        state_frame,
        _us_lead_diagnostics(us_market, risk),
        {
            **decision,
            "direct_score_metrics": _direct_score_metrics(
                us_market,
                risk,
            ).to_dict(orient="records"),
        },
    )


def _blend(
    frame: pd.DataFrame,
    diffusion_weight: float | pd.Series | np.ndarray,
) -> pd.Series:
    return (
        (1 - diffusion_weight) * frame["baseline_rank"]
        + diffusion_weight * frame["diffusion_score"]
    )


def add_eu_diagnostic_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    """Add fixed, conditional and component diagnostic scores."""

    work = frame.copy()
    confirmation = work["confirmation_transition_breadth"]
    work["fixed_diffusion_15"] = _blend(work, 0.15)
    work["fixed_diffusion_25"] = _blend(work, 0.25)
    work["fixed_diffusion_35"] = _blend(work, 0.35)
    work[EU_PRIMARY_CANDIDATE] = _blend(
        work,
        np.where(confirmation.ge(0.5), 0.35, 0.15),
    )
    work["conditional_10_30"] = _blend(
        work,
        np.where(confirmation.ge(0.5), 0.30, 0.10),
    )
    work["conditional_20_40"] = _blend(
        work,
        np.where(confirmation.ge(0.5), 0.40, 0.20),
    )
    work["conditional_threshold_45"] = _blend(
        work,
        np.where(confirmation.ge(0.45), 0.35, 0.15),
    )
    work["conditional_threshold_55"] = _blend(
        work,
        np.where(confirmation.ge(0.55), 0.35, 0.15),
    )
    for factor in (
        "quality",
        "deleveraging",
        "earnings_yield",
        "revision",
    ):
        work[f"{factor}_25"] = (
            0.75 * work["baseline_rank"]
            + 0.25 * work[f"{factor}_breadth"]
        )
    return work


def build_tilt_weight_details(
    panel: pd.DataFrame,
    *,
    score_column: str,
    top_n: int = 3,
    bottom_n: int = 3,
    absolute_tilt: float = 0.05,
    relative_tilt: float = 0.20,
) -> pd.DataFrame:
    """Reproduce canonical sector tilt weights for attribution and costs."""

    records = []
    required = [score_column, "sector_forward_return", "sector_weight"]
    for date, group in panel.dropna(subset=required).groupby("Date"):
        if len(group) < max(top_n + bottom_n, 8):
            continue
        group = group.sort_values("sector_code", kind="mergesort").copy()
        group["_selection_score"] = group[score_column].round(12)
        top_codes = set(
            group.sort_values(
                ["_selection_score", "sector_code"],
                ascending=[False, True],
                kind="mergesort",
            )
            .head(top_n)["sector_code"]
            .tolist()
        )
        bottom_codes = set(
            group.sort_values(
                ["_selection_score", "sector_code"],
                ascending=[True, True],
                kind="mergesort",
            )
            .head(bottom_n)["sector_code"]
            .tolist()
        )
        group["benchmark_weight"] = (
            group["sector_weight"] / group["sector_weight"].sum()
        )
        group["tilted_weight_raw"] = group["benchmark_weight"]
        top = group["sector_code"].isin(top_codes)
        bottom = group["sector_code"].isin(bottom_codes)
        group.loc[top, "tilted_weight_raw"] = np.maximum(
            group.loc[top, "benchmark_weight"] * (1 + relative_tilt),
            group.loc[top, "benchmark_weight"] + absolute_tilt,
        )
        group.loc[bottom, "tilted_weight_raw"] = np.minimum(
            group.loc[bottom, "benchmark_weight"] * (1 - relative_tilt),
            np.maximum(
                0.0,
                group.loc[bottom, "benchmark_weight"] - absolute_tilt,
            ),
        )
        group["tilted_weight"] = (
            group["tilted_weight_raw"] / group["tilted_weight_raw"].sum()
        )
        group["active_weight"] = (
            group["tilted_weight"] - group["benchmark_weight"]
        )
        group["active_contribution"] = (
            group["active_weight"] * group["sector_forward_return"]
        )
        group["Date"] = date
        group["is_top"] = top
        group["is_bottom"] = bottom
        records.append(
            group[
                [
                    "Date",
                    "next_date",
                    "sector_code",
                    "sector_name",
                    "sector_forward_return",
                    "benchmark_weight",
                    "tilted_weight",
                    "active_weight",
                    "active_contribution",
                    "is_top",
                    "is_bottom",
                ]
            ]
        )
    if not records:
        return pd.DataFrame()
    return pd.concat(records, ignore_index=True)


def _monthly_from_details(details: pd.DataFrame) -> pd.DataFrame:
    monthly = (
        details.groupby("Date", observed=True)
        .agg(
            next_date=("next_date", "first"),
            active_return=("active_contribution", "sum"),
        )
        .reset_index()
        .sort_values("Date")
    )
    weights = details.pivot(
        index="Date",
        columns="sector_code",
        values="tilted_weight",
    ).fillna(0)
    turnover = weights.diff().abs().sum(axis=1) * 0.5
    if len(turnover):
        turnover.iloc[0] = 0.0
    monthly["one_way_turnover"] = monthly["Date"].map(turnover)
    return monthly


def _generic_block_bootstrap(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    start: str | None,
    end: str | None,
    samples: int,
    block_months: int = 6,
) -> dict[str, float | int]:
    joined = baseline[["Date", "active_return"]].merge(
        candidate[["Date", "active_return"]],
        on="Date",
        suffixes=("_baseline", "_candidate"),
    )
    if start is not None:
        joined = joined[joined["Date"].ge(pd.Timestamp(start))]
    if end is not None:
        joined = joined[joined["Date"].le(pd.Timestamp(end))]
    delta = (
        joined["active_return_candidate"] - joined["active_return_baseline"]
    ).to_numpy(dtype=float)
    if len(delta) < block_months:
        return {
            "months": len(delta),
            "annualized_arithmetic_delta": np.nan,
            "ci_2_5": np.nan,
            "ci_97_5": np.nan,
            "probability_delta_positive": np.nan,
        }
    rng = np.random.default_rng(20260726)
    starts = np.arange(len(delta) - block_months + 1)
    blocks_needed = int(np.ceil(len(delta) / block_months))
    draws = []
    for _ in range(samples):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        draw = np.concatenate(
            [delta[index : index + block_months] for index in chosen]
        )[: len(delta)]
        draws.append(float(draw.mean() * 12))
    return {
        "months": len(delta),
        "annualized_arithmetic_delta": float(delta.mean() * 12),
        "ci_2_5": float(np.quantile(draws, 0.025)),
        "ci_97_5": float(np.quantile(draws, 0.975)),
        "probability_delta_positive": float(
            np.mean(np.asarray(draws) > 0)
        ),
    }


def _selection_change_rates(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    start: str = "2022-01-01",
) -> dict[str, float | int]:
    baseline = baseline[baseline["Date"].ge(pd.Timestamp(start))]
    candidate = candidate[candidate["Date"].ge(pd.Timestamp(start))]

    def sets(frame: pd.DataFrame, column: str) -> pd.Series:
        selected = frame[frame[column]].groupby("Date")["sector_code"].agg(
            lambda values: frozenset(values)
        )
        return selected

    top = pd.concat(
        [
            sets(baseline, "is_top").rename("baseline"),
            sets(candidate, "is_top").rename("candidate"),
        ],
        axis=1,
    ).dropna()
    bottom = pd.concat(
        [
            sets(baseline, "is_bottom").rename("baseline"),
            sets(candidate, "is_bottom").rename("candidate"),
        ],
        axis=1,
    ).dropna()
    return {
        "months": len(top),
        "top_changed_months": int(top["baseline"].ne(top["candidate"]).sum()),
        "top_changed_rate": float(top["baseline"].ne(top["candidate"]).mean()),
        "bottom_changed_months": int(
            bottom["baseline"].ne(bottom["candidate"]).sum()
        ),
        "bottom_changed_rate": float(
            bottom["baseline"].ne(bottom["candidate"]).mean()
        ),
    }


def _eu_sector_contributions(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    start: str = "2022-01-01",
) -> pd.DataFrame:
    columns = [
        "Date",
        "sector_code",
        "sector_name",
        "sector_forward_return",
        "tilted_weight",
    ]
    joined = baseline[columns].merge(
        candidate[columns],
        on=["Date", "sector_code"],
        suffixes=("_baseline", "_candidate"),
    )
    joined = joined[joined["Date"].ge(pd.Timestamp(start))].copy()
    joined["incremental_weight"] = (
        joined["tilted_weight_candidate"]
        - joined["tilted_weight_baseline"]
    )
    joined["incremental_contribution"] = (
        joined["incremental_weight"]
        * joined["sector_forward_return_candidate"]
    )
    months = joined["Date"].nunique()
    result = (
        joined.groupby("sector_code", observed=True)
        .agg(
            sector_name=("sector_name_candidate", "last"),
            months=("Date", "nunique"),
            mean_incremental_weight=("incremental_weight", "mean"),
            total_incremental_contribution=(
                "incremental_contribution",
                "sum",
            ),
        )
        .reset_index()
    )
    result["annualized_arithmetic_contribution"] = (
        result["total_incremental_contribution"] / months * 12
    )
    return result.sort_values(
        "annualized_arithmetic_contribution",
        ascending=False,
    )


def _eu_condition_analysis(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    confirmation: pd.Series,
) -> pd.DataFrame:
    joined = baseline[["Date", "active_return"]].merge(
        candidate[["Date", "active_return"]],
        on="Date",
        suffixes=("_baseline", "_candidate"),
    )
    joined["confirmation_transition_breadth"] = joined["Date"].map(
        confirmation
    )
    joined["delta"] = (
        joined["active_return_candidate"] - joined["active_return_baseline"]
    )
    rows = []
    for period_name, (start, end) in {
        "validation_2018_2021": ("2018-01-01", "2021-12-31"),
        "holdout_2022_latest": ("2022-01-01", None),
    }.items():
        selected = joined[joined["Date"].ge(pd.Timestamp(start))]
        if end is not None:
            selected = selected[selected["Date"].le(pd.Timestamp(end))]
        for condition_name, mask in (
            (
                "low_confirmation",
                selected["confirmation_transition_breadth"].lt(0.5),
            ),
            (
                "high_confirmation",
                selected["confirmation_transition_breadth"].ge(0.5),
            ),
        ):
            values = selected.loc[mask, "delta"]
            rows.append(
                {
                    "period": period_name,
                    "condition": condition_name,
                    "months": len(values),
                    "monthly_mean_delta": float(values.mean()),
                    "annualized_arithmetic_delta": float(
                        values.mean() * 12
                    ),
                    "cumulative_arithmetic_delta": float(values.sum()),
                    "positive_month_rate": float(values.gt(0).mean()),
                }
            )
    return pd.DataFrame(rows)


def _run_eu_sector_analysis(
    market_features: pd.DataFrame,
    sector_features: pd.DataFrame,
    *,
    bootstrap_samples: int,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, object],
]:
    market = market_features[market_features["region"].eq("EU")].copy()
    market["Date"] = pd.to_datetime(market["Date"], errors="coerce")
    market = market.set_index("Date").sort_index()
    core_market = market[
        [column for column in market if column.startswith("core_")]
    ].copy()
    core_market.columns = [
        column.removeprefix("core_") for column in core_market
    ]
    confirmation_market = market[
        [
            column
            for column in market
            if column.startswith("confirmation_")
        ]
    ].copy()
    confirmation_market.columns = [
        column.removeprefix("confirmation_")
        for column in confirmation_market
    ]
    sectors = sector_features[sector_features["region"].eq("EU")].drop(
        columns="region"
    )
    panel = pd.read_parquet(
        sector_model.PROJECT_DIR / "outputs_eu" / "sector_scores_panel.parquet"
    )
    candidates = build_sector_candidates(
        panel,
        sectors,
        core_market,
        confirmation_market,
    )
    candidates = add_eu_diagnostic_candidates(candidates)

    comparison_rows = []
    backtests: dict[str, pd.DataFrame] = {}
    details: dict[str, pd.DataFrame] = {}
    for candidate in EU_DIAGNOSTIC_CANDIDATES:
        backtest = sector_model.run_sector_tilt_backtest(
            candidates,
            score_column=candidate,
        )
        backtests[candidate] = backtest
        for period_name, (start, end) in {
            "validation_2018_2021": ("2018-01-01", "2021-12-31"),
            "holdout_2022_latest": ("2022-01-01", None),
            "full_period": ("2010-01-01", None),
        }.items():
            comparison_rows.append(
                {
                    "candidate": candidate,
                    "period": period_name,
                    **_active_metrics(
                        _select_period(backtest, start, end)
                    ),
                }
            )
    comparison = pd.DataFrame(comparison_rows)

    for candidate in ("baseline_rank", EU_PRIMARY_CANDIDATE):
        detail = build_tilt_weight_details(
            candidates,
            score_column=candidate,
        )
        monthly = _monthly_from_details(detail)
        canonical = backtests[candidate][["Date", "active_return"]]
        check = monthly.merge(
            canonical,
            on="Date",
            suffixes=("_detail", "_canonical"),
        )
        max_difference = float(
            (
                check["active_return_detail"]
                - check["active_return_canonical"]
            )
            .abs()
            .max()
        )
        if max_difference > 1e-12:
            raise AssertionError(
                f"{candidate} weight reconstruction mismatch: "
                f"{max_difference}"
            )
        details[candidate] = detail

    baseline_monthly = _monthly_from_details(details["baseline_rank"])
    primary_monthly = _monthly_from_details(details[EU_PRIMARY_CANDIDATE])
    cost_rows = []
    for cost_bps in (0, 10, 25):
        cost_rate = cost_bps / 10_000
        for model_name, monthly in (
            ("baseline_rank", baseline_monthly),
            (EU_PRIMARY_CANDIDATE, primary_monthly),
        ):
            adjusted = monthly.copy()
            adjusted["active_return"] = (
                adjusted["active_return"]
                - adjusted["one_way_turnover"] * cost_rate
            )
            for period_name, (start, end) in {
                "validation_2018_2021": ("2018-01-01", "2021-12-31"),
                "holdout_2022_latest": ("2022-01-01", None),
            }.items():
                selected = _select_period(adjusted, start, end)
                cost_rows.append(
                    {
                        "candidate": model_name,
                        "cost_bps_one_way": cost_bps,
                        "period": period_name,
                        "mean_one_way_turnover": float(
                            selected["one_way_turnover"].mean()
                        ),
                        **_active_metrics(selected),
                    }
                )
    costs = pd.DataFrame(cost_rows)
    baseline_cost = costs[
        costs["candidate"].eq("baseline_rank")
    ].set_index(["cost_bps_one_way", "period"])
    primary_cost = costs[
        costs["candidate"].eq(EU_PRIMARY_CANDIDATE)
    ].set_index(["cost_bps_one_way", "period"])
    costs["active_annualized_delta_vs_baseline"] = costs.apply(
        lambda row: (
            row["active_annualized_return"]
            - baseline_cost.loc[
                (row["cost_bps_one_way"], row["period"]),
                "active_annualized_return",
            ]
            if row["candidate"] == EU_PRIMARY_CANDIDATE
            else 0.0
        ),
        axis=1,
    )

    bootstrap_rows = []
    for period_name, (start, end) in {
        "validation_2018_2021": ("2018-01-01", "2021-12-31"),
        "holdout_2022_latest": ("2022-01-01", None),
    }.items():
        bootstrap_rows.append(
            {
                "period": period_name,
                **_generic_block_bootstrap(
                    backtests["baseline_rank"],
                    backtests[EU_PRIMARY_CANDIDATE],
                    start=start,
                    end=end,
                    samples=bootstrap_samples,
                ),
            }
        )
    bootstraps = pd.DataFrame(bootstrap_rows)
    condition = _eu_condition_analysis(
        backtests["baseline_rank"],
        backtests[EU_PRIMARY_CANDIDATE],
        confirmation_market["transition_breadth_ewma3"],
    )
    contributions = _eu_sector_contributions(
        details["baseline_rank"],
        details[EU_PRIMARY_CANDIDATE],
    )

    indexed = comparison.set_index(["candidate", "period"])
    validation_pass = (
        indexed.loc[
            (EU_PRIMARY_CANDIDATE, "validation_2018_2021"),
            "active_annualized_return",
        ]
        > indexed.loc[
            ("baseline_rank", "validation_2018_2021"),
            "active_annualized_return",
        ]
    )
    holdout_pass = (
        indexed.loc[
            (EU_PRIMARY_CANDIDATE, "holdout_2022_latest"),
            "active_annualized_return",
        ]
        > indexed.loc[
            ("baseline_rank", "holdout_2022_latest"),
            "active_annualized_return",
        ]
    )
    cost_25_pass = (
        primary_cost.loc[
            (25, "holdout_2022_latest"),
            "active_annualized_return",
        ]
        >= baseline_cost.loc[
            (25, "holdout_2022_latest"),
            "active_annualized_return",
        ]
    )
    bootstrap_pass = (
        bootstraps.set_index("period").loc[
            "holdout_2022_latest",
            "probability_delta_positive",
        ]
        >= 0.7
    )
    decision = {
        "status": (
            "retain_shadow_candidate"
            if validation_pass
            and holdout_pass
            and cost_25_pass
            and bootstrap_pass
            else "insufficient_for_shadow_continuation"
        ),
        "selected": EU_PRIMARY_CANDIDATE,
        "validation_improvement": bool(validation_pass),
        "holdout_improvement": bool(holdout_pass),
        "survives_25bps_cost": bool(cost_25_pass),
        "holdout_bootstrap_pass": bool(bootstrap_pass),
        "selection_changes": _selection_change_rates(
            details["baseline_rank"],
            details[EU_PRIMARY_CANDIDATE],
        ),
    }
    return (
        comparison,
        costs,
        bootstraps,
        condition,
        contributions,
        decision,
    )


def _format_table(frame: pd.DataFrame, columns: list[str]) -> str:
    selected = frame[columns].copy()
    numeric = selected.select_dtypes(include=[np.number]).columns
    selected[numeric] = selected[numeric].round(4)
    return selected.to_markdown(index=False)


def _write_report(
    output_dir: Path,
    us_metrics: pd.DataFrame,
    us_leads: pd.DataFrame,
    us_decision: Mapping[str, object],
    eu_comparison: pd.DataFrame,
    eu_costs: pd.DataFrame,
    eu_condition: pd.DataFrame,
    eu_contributions: pd.DataFrame,
    eu_decision: Mapping[str, object],
) -> None:
    us_full = us_metrics[us_metrics["period"].eq("full_oos")].sort_values(
        "risk_spearman_mean",
        ascending=False,
    )
    eu_holdout = eu_comparison[
        eu_comparison["period"].eq("holdout_2022_latest")
    ].sort_values("active_annualized_return", ascending=False)
    top_contributors = pd.concat(
        [
            eu_contributions.head(4),
            eu_contributions.tail(4),
        ]
    )
    report = f"""# 两项模型研究发现的 v2 深挖

## 一句话结论

- US Regime：`{us_decision["selected"]}`；状态为
  `{us_decision["status"]}`。底层扩散首先是风险温度计，不是收益方向信号。
- EU Sector：`{eu_decision["selected"]}`；状态为
  `{eu_decision["status"]}`。它是原行业评分的小幅确认层，不应替代主模型。

## US：哪些变量真的有用

{_format_table(
    us_full,
    [
        "model",
        "extra_feature_count",
        "months",
        "state_fwd_vol_spearman",
        "state_fwd_mdd_spearman",
        "high_vol_auc",
        "high_mdd_auc",
        "risk_spearman_mean",
    ],
)}

### 提前量

{_format_table(
    us_leads,
    [
        "feature",
        "horizon_months",
        "fwd_vol_spearman",
        "fwd_mdd_spearman",
        "negative_fwd_return_spearman",
    ],
)}

解释：正相关表示公司层面的压力越高，随后风险越高。对负未来收益的相关性弱，
意味着该信号更适合状态识别、风险预算和防守触发，不适合直接预测指数涨跌。

## EU：权重和机制

{_format_table(
    eu_holdout,
    [
        "candidate",
        "months",
        "active_annualized_return",
        "active_sharpe",
        "active_max_drawdown",
        "active_hit_rate",
    ],
)}

### 小盘确认条件

{_format_table(
    eu_condition,
    [
        "period",
        "condition",
        "months",
        "monthly_mean_delta",
        "annualized_arithmetic_delta",
        "positive_month_rate",
    ],
)}

### 成本

{_format_table(
    eu_costs[
        eu_costs["candidate"].isin(
            ["baseline_rank", EU_PRIMARY_CANDIDATE]
        )
    ],
    [
        "candidate",
        "cost_bps_one_way",
        "period",
        "mean_one_way_turnover",
        "active_annualized_return",
        "active_sharpe",
        "active_annualized_delta_vs_baseline",
    ],
)}

### 2022+ 行业增量贡献

{_format_table(
    top_contributors,
    [
        "sector_code",
        "sector_name",
        "mean_incremental_weight",
        "annualized_arithmetic_contribution",
    ],
)}

## 模型接入边界

1. US 只进入 Regime 的 shadow 特征层；优先采用通过联合门的最小特征集合。
   生产接入后可影响风险状态、风险预算或换仓确认，但不得直接变成选股分数。
2. EU 保持条件式 15%/35% overlay：大多数月份只给 15%，MSCI Europe
   Small 公司扩散同步确认时才升到 35%。继续 shadow，不覆盖主行业分。
3. 两项都必须在 2026-06-30 之后积累至少 12 个真正未来月份，再单独申请晋升。
"""
    (output_dir / "deep_dive_report_cn.md").write_text(
        report,
        encoding="utf-8",
    )


def run(
    output_dir: Path,
    *,
    parent_results: Path,
    min_train: int,
    hmm_n_init: int,
    bootstrap_samples: int,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    parent_results = parent_results.resolve()
    required_parent = (
        "manifest.json",
        "market_factor_rotation_features.parquet",
        "sector_bottom_up_features.parquet",
        "regime_walkforward_states.csv",
    )
    missing = [
        name for name in required_parent if not (parent_results / name).is_file()
    ]
    if missing:
        raise FileNotFoundError(f"v1 parent results missing: {missing}")

    market_features = pd.read_parquet(
        parent_results / "market_factor_rotation_features.parquet"
    )
    sector_features = pd.read_parquet(
        parent_results / "sector_bottom_up_features.parquet"
    )
    (
        us_metrics,
        us_classification,
        us_states,
        us_leads,
        us_decision,
    ) = _run_us_attribution(
        parent_results,
        market_features,
        min_train=min_train,
        hmm_n_init=hmm_n_init,
    )
    us_direct = pd.DataFrame(us_decision.pop("direct_score_metrics"))
    (
        eu_comparison,
        eu_costs,
        eu_bootstraps,
        eu_condition,
        eu_contributions,
        eu_decision,
    ) = _run_eu_sector_analysis(
        market_features,
        sector_features,
        bootstrap_samples=bootstrap_samples,
    )

    outputs = {
        "us_regime_attribution.csv": us_metrics,
        "us_regime_classification.csv": us_classification,
        "us_regime_states.csv": us_states,
        "us_feature_lead_diagnostics.csv": us_leads,
        "us_direct_transition_score.csv": us_direct,
        "eu_sector_sensitivity.csv": eu_comparison,
        "eu_sector_cost_sensitivity.csv": eu_costs,
        "eu_sector_bootstrap.csv": eu_bootstraps,
        "eu_confirmation_condition.csv": eu_condition,
        "eu_sector_incremental_contributions.csv": eu_contributions,
    }
    for name, frame in outputs.items():
        frame.to_csv(
            output_dir / name,
            index=False,
            encoding="utf-8-sig",
        )

    decisions = {
        "us_regime": us_decision,
        "eu_sector": eu_decision,
        "production_promotion": {
            "allowed": False,
            "reason": (
                "Research-only deep dive; requires at least 12 genuinely future "
                "months after 2026-06-30 and an explicit promotion task."
            ),
        },
    }
    (output_dir / "shadow_decisions.json").write_text(
        json.dumps(decisions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_report(
        output_dir,
        us_metrics,
        us_leads,
        us_decision,
        eu_comparison,
        eu_costs,
        eu_condition,
        eu_contributions,
        eu_decision,
    )
    manifest = {
        "status": "complete",
        "deep_dive_version": DEEP_DIVE_VERSION,
        "parent_results": str(parent_results),
        "parent_manifest_sha256": _sha256(
            parent_results / "manifest.json"
        ),
        "pit_cutoff": "2026-06-30",
        "us_models": {
            name: list(features)
            for name, features in US_MODEL_FEATURES.items()
        },
        "eu_candidates": list(EU_DIAGNOSTIC_CANDIDATES),
        "hmm_min_train": min_train,
        "hmm_n_init": hmm_n_init,
        "bootstrap_samples": bootstrap_samples,
        "decisions": decisions,
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
        "--parent-results-dir",
        type=Path,
        default=DEFAULT_PARENT_RESULTS,
    )
    parser.add_argument("--min-train", type=int, default=60)
    parser.add_argument("--hmm-n-init", type=int, default=2)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest = run(
        Path(args.output_dir),
        parent_results=args.parent_results_dir,
        min_train=args.min_train,
        hmm_n_init=args.hmm_n_init,
        bootstrap_samples=args.bootstrap_samples,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
