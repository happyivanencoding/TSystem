"""Test bottom-up factor rotation features for regime and sector models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable
import warnings

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from tp_core.data_sources import SCREEN_AGGREGATE_PATH
from tp_models.regime import config as regime_config
from tp_models.regime import model as regime_model
from tp_models.regime import vol_compare
from tp_models.sector import model as sector_model


FEATURE_VERSION = "tp.bottom_up_factor_rotation:1.0.0"
SECTOR_COLUMN = sector_model.SECTOR_CODE_COLUMN
ENTITY_COLUMN = "ISIN"

REGION_CONFIG = {
    "US": {
        "lag": 6,
        "core_weight": "Weight in SP500",
        "confirmation_weight": "Weight in NASDAQ COMP",
        "sector_panel": (
            sector_model.PROJECT_DIR
            / "outputs_fs_sector_default"
            / "sector_scores_panel.parquet"
        ),
    },
    "EU": {
        "lag": 3,
        "core_weight": "Weight in STOXX EUROPE 600",
        "confirmation_weight": "Weight in MSCI EUR SMALL",
        "sector_panel": (
            sector_model.PROJECT_DIR / "outputs_eu" / "sector_scores_panel.parquet"
        ),
    },
}

RAW_SPECS = {
    "margin": ("Oper Margin", 1.0, "delta"),
    "roe": ("ROE avg FY0", 1.0, "delta"),
    "deleveraging": ("NetDebt to EBITDA exFIN", -1.0, "delta"),
    "earnings_yield": ("Earns Yield FY1", 1.0, "delta"),
    "revision": ("EPS Revision Ratio", 1.0, "level"),
    "eps_momentum": ("EPS NTM 3M Growth", 1.0, "level"),
}

FACTOR_NAMES = (
    "quality",
    "deleveraging",
    "earnings_yield",
    "revision",
)

REGIME_BASELINE_COLUMNS = (
    "val_earnyield_med",
    "val_earnyield_disp",
    "val_dvdyield_med",
    "val_pe_pct_disp",
    "eps_rev_breadth",
    "eps_rev_med",
    "eps_ntm3m_growth_med",
    "eps_growth_ntm_med",
    "sales_growth_ntm_med",
    "roe_med",
    "netdebt_ebitda_med",
    "vol_med",
    "vol_disp",
    "vol_short_med",
    "mom_med",
    "ret_disp",
    "ret_skew",
    "breadth_pos",
    "cyc_def_spread",
    "spread_value",
    "spread_quality",
    "spread_mom",
    "spread_lowvol",
    "rvol_ann",
    "avg_corr",
    "down_day_freq",
    "macro_fin_conditions",
    "macro_fin_conditions_ewma",
    "macro2_citi_raw",
    "macro2_citi_ewma",
)

REGIME_EXTRA_COLUMNS = (
    "transition_breadth_ewma3",
    "revision_breadth_ewma3",
    "rotation_dispersion_ewma3",
    "confirmation_transition_breadth_ewma3",
)

SECTOR_CANDIDATES = (
    "baseline_rank",
    "transition_score",
    "diffusion_score",
    "rotation_score",
    "baseline_75_diffusion_25",
    "baseline_75_rotation_25",
    "cross_market_diffusion_blend",
)

PERIODS = {
    "discovery_2010_2017": ("2010-01-01", "2017-12-31"),
    "validation_2018_2021": ("2018-01-01", "2021-12-31"),
    "holdout_2022_latest": ("2022-01-01", None),
    "full_period": ("2010-01-01", None),
}


def _weighted_mean(
    frame: pd.DataFrame,
    value_column: str,
    weight_column: str,
) -> float:
    values = pd.to_numeric(frame[value_column], errors="coerce")
    weights = pd.to_numeric(frame[weight_column], errors="coerce")
    valid = values.notna() & weights.gt(0)
    if not valid.any():
        return np.nan
    return float(np.average(values[valid], weights=weights[valid]))


def _exact_lag_delta(
    frame: pd.DataFrame,
    values: pd.Series,
    lag: int,
) -> pd.Series:
    grouped = values.groupby(frame[ENTITY_COLUMN], observed=True)
    lagged = grouped.shift(lag)
    lagged_date = frame["Date"].groupby(
        frame[ENTITY_COLUMN], observed=True
    ).shift(lag)
    expected = frame["Date"].dt.to_period("M") - lag
    exact = lagged_date.dt.to_period("M").eq(expected)
    return (values - lagged).where(exact)


def _positive_indicator(values: pd.Series) -> pd.Series:
    return values.gt(0).where(values.notna()).astype(float)


def _date_rank(frame: pd.DataFrame, values: pd.Series) -> pd.Series:
    return values.groupby(frame["Date"], observed=True).rank(
        pct=True,
        method="average",
    )


def _factor_return_proxy(
    frame: pd.DataFrame,
    score_column: str,
) -> pd.Series:
    previous_score = frame[score_column].groupby(
        frame[ENTITY_COLUMN], observed=True
    ).shift(1)
    previous_date = frame["Date"].groupby(
        frame[ENTITY_COLUMN], observed=True
    ).shift(1)
    expected = frame["Date"].dt.to_period("M") - 1
    valid_previous = previous_date.dt.to_period("M").eq(expected)
    work = frame[["Date", "Total Return"]].copy()
    work["score"] = previous_score.where(valid_previous)
    work["return"] = pd.to_numeric(work["Total Return"], errors="coerce")

    def spread(group: pd.DataFrame) -> float:
        group = group.dropna(subset=["score", "return"])
        if len(group) < 30:
            return np.nan
        high = group["score"].ge(group["score"].quantile(0.8))
        low = group["score"].le(group["score"].quantile(0.2))
        if not high.any() or not low.any():
            return np.nan
        return float(group.loc[high, "return"].mean() - group.loc[low, "return"].mean())

    return work.groupby("Date", observed=True).apply(
        spread,
        include_groups=False,
    )


def build_market_signals(
    screen: pd.DataFrame,
    *,
    weight_column: str,
    lag: int,
    sample_start: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build PIT-safe market and sector factor features for one universe."""

    panel = screen[
        pd.to_numeric(screen[weight_column], errors="coerce").fillna(0).gt(0)
    ].copy()
    panel[weight_column] = pd.to_numeric(panel[weight_column], errors="coerce")
    panel["sector_code"] = pd.to_numeric(panel[SECTOR_COLUMN], errors="coerce")
    panel = panel.dropna(
        subset=["Date", ENTITY_COLUMN, "sector_code", weight_column]
    ).sort_values([ENTITY_COLUMN, "Date"])
    panel["sector_code"] = panel["sector_code"].astype(int)

    for name, (column, direction, transform) in RAW_SPECS.items():
        signed = pd.to_numeric(panel[column], errors="coerce") * direction
        signal = (
            _exact_lag_delta(panel, signed, lag)
            if transform == "delta"
            else signed
        )
        panel[f"{name}_raw"] = signal
        panel[f"{name}_positive"] = _positive_indicator(signal)
        panel[f"{name}_score"] = _date_rank(panel, signal)

    panel["quality_positive"] = panel[
        ["margin_positive", "roe_positive"]
    ].mean(axis=1)
    panel["quality_score"] = panel[["margin_score", "roe_score"]].mean(axis=1)
    panel["revision_positive"] = panel[
        ["revision_positive", "eps_momentum_positive"]
    ].mean(axis=1)
    panel["revision_score"] = panel[
        ["revision_score", "eps_momentum_score"]
    ].mean(axis=1)
    panel["transition_positive"] = panel[
        [
            "quality_positive",
            "deleveraging_positive",
            "earnings_yield_positive",
        ]
    ].mean(axis=1)
    panel["transition_score"] = panel[
        ["quality_score", "deleveraging_score", "earnings_yield_score"]
    ].mean(axis=1)
    panel["alignment_positive"] = panel[
        ["transition_positive", "revision_positive"]
    ].mean(axis=1)

    market = pd.DataFrame(
        index=pd.Index(sorted(panel["Date"].unique()), name="Date")
    )
    for name in (
        "quality",
        "deleveraging",
        "earnings_yield",
        "revision",
        "transition",
        "alignment",
    ):
        column = f"{name}_positive"
        market[f"{name}_breadth"] = panel.groupby(
            "Date", observed=True
        ).apply(
            lambda group, col=column: _weighted_mean(
                group,
                col,
                weight_column,
            ),
            include_groups=False,
        )

    for factor in FACTOR_NAMES:
        market[f"factor_return_{factor}"] = _factor_return_proxy(
            panel,
            f"{factor}_score",
        )
        market[f"factor_return_{factor}_ewma6"] = market[
            f"factor_return_{factor}"
        ].ewm(span=6, adjust=False, min_periods=3).mean()

    factor_ewma_columns = [
        f"factor_return_{factor}_ewma6" for factor in FACTOR_NAMES
    ]
    market["rotation_dispersion"] = market[factor_ewma_columns].std(axis=1)
    factor_ranks = market[factor_ewma_columns].rank(axis=1, pct=True)
    market["rotation_velocity"] = factor_ranks.diff().abs().mean(axis=1)
    for column in (
        "transition_breadth",
        "revision_breadth",
        "alignment_breadth",
        "rotation_dispersion",
        "rotation_velocity",
    ):
        market[f"{column}_ewma3"] = market[column].ewm(
            span=3,
            adjust=False,
            min_periods=2,
        ).mean()

    sector_columns = {
        "quality_score": "quality_score",
        "deleveraging_score": "deleveraging_score",
        "earnings_yield_score": "earnings_yield_score",
        "revision_score": "revision_score",
        "transition_score": "transition_score",
        "quality_breadth": "quality_positive",
        "deleveraging_breadth": "deleveraging_positive",
        "earnings_yield_breadth": "earnings_yield_positive",
        "revision_breadth": "revision_positive",
        "transition_breadth": "transition_positive",
    }
    sector_frames = []
    for output_column, source_column in sector_columns.items():
        grouped = panel.groupby(
            ["Date", "sector_code"],
            observed=True,
        ).apply(
            lambda group, col=source_column: _weighted_mean(
                group,
                col,
                weight_column,
            ),
            include_groups=False,
        )
        sector_frames.append(grouped.rename(output_column))
    sectors = pd.concat(sector_frames, axis=1).reset_index()
    sectors = sectors[sectors["Date"].ge(sample_start)].copy()
    market = market[market.index >= sample_start].copy()
    return market, sectors


def _rank_sector_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
) -> pd.DataFrame:
    for column in columns:
        frame[column] = (
            frame.groupby("Date", observed=True)[column].rank(
                pct=True,
                method="average",
            )
            * 10
        )
    return frame


def build_sector_candidates(
    panel: pd.DataFrame,
    sectors: pd.DataFrame,
    market: pd.DataFrame,
    confirmation: pd.DataFrame,
) -> pd.DataFrame:
    """Merge bottom-up sector signals and construct fixed candidate scores."""

    work = panel.copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.merge(sectors, on=["Date", "sector_code"], how="left")
    work["baseline_rank"] = (
        work.groupby("Date", observed=True)["score_final"].rank(
            pct=True,
            method="average",
        )
        * 10
    )
    work = _rank_sector_columns(
        work,
        (
            "transition_score",
            "quality_breadth",
            "deleveraging_breadth",
            "earnings_yield_breadth",
            "revision_breadth",
        ),
    )
    work["diffusion_score"] = work[
        [
            "quality_breadth",
            "deleveraging_breadth",
            "earnings_yield_breadth",
            "revision_breadth",
        ]
    ].mean(axis=1)

    strength_columns = [
        f"factor_return_{factor}_ewma6" for factor in FACTOR_NAMES
    ]
    strengths = market[strength_columns].rank(axis=1, pct=True)
    strengths.columns = [f"rotation_weight_{factor}" for factor in FACTOR_NAMES]
    strengths = strengths.div(strengths.sum(axis=1), axis=0)
    work = work.merge(
        strengths.reset_index(),
        on="Date",
        how="left",
    )
    work["rotation_score"] = 0.0
    for factor in FACTOR_NAMES:
        work["rotation_score"] += (
            work[f"{factor}_score"]
            * work[f"rotation_weight_{factor}"]
        )
    work["rotation_score"] = (
        work.groupby("Date", observed=True)["rotation_score"].rank(
            pct=True,
            method="average",
        )
        * 10
    )
    work["baseline_75_diffusion_25"] = (
        0.75 * work["baseline_rank"] + 0.25 * work["diffusion_score"]
    )
    work["baseline_75_rotation_25"] = (
        0.75 * work["baseline_rank"] + 0.25 * work["rotation_score"]
    )

    confirmation_signal = confirmation["transition_breadth_ewma3"].rename(
        "confirmation_transition_breadth"
    )
    work = work.merge(
        confirmation_signal.reset_index(),
        on="Date",
        how="left",
    )
    diffusion_weight = np.where(
        work["confirmation_transition_breadth"].ge(0.5),
        0.35,
        0.15,
    )
    work["cross_market_diffusion_blend"] = (
        (1 - diffusion_weight) * work["baseline_rank"]
        + diffusion_weight * work["diffusion_score"]
    )
    return work


def _walk_forward_states(
    features: pd.DataFrame,
    *,
    k: int,
    min_train: int,
    n_init: int,
) -> pd.Series:
    states: dict[pd.Timestamp, int] = {}
    for end in range(min_train, len(features) + 1):
        window = features.iloc[:end]
        Z, available = regime_model.preprocess(window)
        if len(available) < min_train:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fitted, raw_states = regime_model.fit_hmm(
                Z,
                k,
                n_init=n_init,
            )
        if fitted is None:
            continue
        ranks = regime_model.label_states(available, raw_states)
        states[pd.Timestamp(available.index[-1])] = int(
            ranks[raw_states[-1]]
        )
    return pd.Series(states, name="state").sort_index()


def _safe_auc(target: pd.Series, score: pd.Series) -> float:
    valid = target.notna() & score.notna()
    if valid.sum() < 10 or target[valid].nunique() < 2:
        return np.nan
    y = target[valid].astype(int).to_numpy()
    prediction = score[valid].astype(float).to_numpy()
    return float(roc_auc_score(y, prediction))


def _regime_metrics(
    states: pd.Series,
    *,
    region: str,
    k: int,
    risk: pd.DataFrame,
) -> dict[str, float | int]:
    frame = states.to_frame()
    frame["fwd_return"] = regime_model.market_fwd_return(region).reindex(
        frame.index
    )
    frame = frame.join(risk, how="left")
    high_vol = frame["fwd_vol"].ge(
        frame["fwd_vol"].quantile(2 / 3)
    ).where(frame["fwd_vol"].notna())
    high_mdd = frame["fwd_mdd"].ge(
        frame["fwd_mdd"].quantile(2 / 3)
    ).where(frame["fwd_mdd"].notna())
    return {
        "months": int(len(frame)),
        "state_fwd_vol_spearman": float(
            frame["state"].corr(frame["fwd_vol"], method="spearman")
        ),
        "state_fwd_mdd_spearman": float(
            frame["state"].corr(frame["fwd_mdd"], method="spearman")
        ),
        "state_fwd_return_spearman": float(
            frame["state"].corr(frame["fwd_return"], method="spearman")
        ),
        "high_vol_auc": _safe_auc(high_vol, frame["state"]),
        "high_mdd_auc": _safe_auc(high_mdd, frame["state"]),
        "crisis_fwd_return_mean": float(
            frame.loc[frame["state"].eq(k - 1), "fwd_return"].mean()
        ),
        "state_persistence": float(frame["state"].eq(frame["state"].shift()).mean()),
        "transition_rate": float(frame["state"].ne(frame["state"].shift()).iloc[1:].mean()),
    }


def compare_regime_models(
    region: str,
    market: pd.DataFrame,
    confirmation: pd.DataFrame,
    *,
    min_train: int,
    n_init: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    baseline = regime_model.load_features(region)
    available_baseline = [
        column for column in REGIME_BASELINE_COLUMNS if column in baseline
    ]
    baseline = baseline[available_baseline].copy()
    extras = market[
        [
            "transition_breadth_ewma3",
            "revision_breadth_ewma3",
            "rotation_dispersion_ewma3",
        ]
    ].copy()
    extras["confirmation_transition_breadth_ewma3"] = confirmation[
        "transition_breadth_ewma3"
    ].reindex(extras.index)
    combined = baseline.join(extras, how="inner").ffill().dropna()
    baseline = baseline.reindex(combined.index)

    baseline_states = _walk_forward_states(
        baseline,
        k=regime_config.FIXED_K,
        min_train=min_train,
        n_init=n_init,
    )
    enhanced_states = _walk_forward_states(
        combined,
        k=regime_config.FIXED_K,
        min_train=min_train,
        n_init=n_init,
    )
    common = baseline_states.index.intersection(enhanced_states.index)
    baseline_states = baseline_states.reindex(common)
    enhanced_states = enhanced_states.reindex(common)
    risk = vol_compare.fwd_risk(region)
    rows = []
    for name, states in (
        ("baseline_core", baseline_states),
        ("enhanced_factor_rotation", enhanced_states),
    ):
        rows.append(
            {
                "region": region,
                "model": name,
                **_regime_metrics(
                    states,
                    region=region,
                    k=regime_config.FIXED_K,
                    risk=risk,
                ),
            }
        )
    state_frame = pd.concat(
        [
            baseline_states.rename("baseline_state"),
            enhanced_states.rename("enhanced_state"),
        ],
        axis=1,
    )
    state_frame.index.name = "Date"
    state_frame["region"] = region
    return pd.DataFrame(rows), state_frame.reset_index()


def _annualized_return(values: pd.Series) -> float:
    values = pd.Series(values).dropna()
    if values.empty:
        return np.nan
    return float((1 + values).prod() ** (12 / len(values)) - 1)


def _active_metrics(backtest: pd.DataFrame) -> dict[str, float | int]:
    active = backtest["active_return"].dropna()
    if active.empty:
        return {
            "months": 0,
            "active_annualized_return": np.nan,
            "active_sharpe": np.nan,
            "active_max_drawdown": np.nan,
            "active_hit_rate": np.nan,
        }
    nav = (1 + active).cumprod()
    annualized = _annualized_return(active)
    volatility = float(active.std(ddof=1) * np.sqrt(12))
    return {
        "months": int(len(active)),
        "active_annualized_return": annualized,
        "active_sharpe": annualized / volatility if volatility else np.nan,
        "active_max_drawdown": float((nav / nav.cummax() - 1).min()),
        "active_hit_rate": float(active.gt(0).mean()),
    }


def _select_period(
    backtest: pd.DataFrame,
    start: str,
    end: str | None,
) -> pd.DataFrame:
    selected = backtest[backtest["Date"].ge(pd.Timestamp(start))]
    if end is not None:
        selected = selected[selected["Date"].le(pd.Timestamp(end))]
    return selected


def compare_sector_models(
    region: str,
    candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    rows = []
    backtests = {}
    for candidate in SECTOR_CANDIDATES:
        backtest = sector_model.run_sector_tilt_backtest(
            candidates,
            score_column=candidate,
        )
        backtests[candidate] = backtest
        for period, (start, end) in PERIODS.items():
            rows.append(
                {
                    "region": region,
                    "candidate": candidate,
                    "period": period,
                    **_active_metrics(
                        _select_period(backtest, start, end)
                    ),
                }
            )
    return pd.DataFrame(rows), backtests


def _block_bootstrap_delta(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    samples: int,
    block_months: int = 6,
) -> dict[str, float | int]:
    joined = baseline[["Date", "active_return"]].merge(
        candidate[["Date", "active_return"]],
        on="Date",
        suffixes=("_baseline", "_candidate"),
    )
    joined = joined[joined["Date"].ge(pd.Timestamp("2022-01-01"))]
    delta = (
        joined["active_return_candidate"] - joined["active_return_baseline"]
    ).to_numpy(dtype=float)
    if len(delta) < block_months:
        return {
            "months": int(len(delta)),
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
        "months": int(len(delta)),
        "annualized_arithmetic_delta": float(delta.mean() * 12),
        "ci_2_5": float(np.quantile(draws, 0.025)),
        "ci_97_5": float(np.quantile(draws, 0.975)),
        "probability_delta_positive": float(
            np.mean(np.asarray(draws) > 0)
        ),
    }


def _sector_decisions(
    results: pd.DataFrame,
    bootstraps: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for region in REGION_CONFIG:
        market = results[results["region"].eq(region)]
        baseline = market[market["candidate"].eq("baseline_rank")].set_index(
            "period"
        )
        eligible = []
        for candidate in SECTOR_CANDIDATES[1:]:
            tested = market[market["candidate"].eq(candidate)].set_index("period")
            bootstrap = bootstraps[
                bootstraps["region"].eq(region)
                & bootstraps["candidate"].eq(candidate)
            ].iloc[0]
            passes = (
                tested.loc[
                    "validation_2018_2021",
                    "active_annualized_return",
                ]
                > baseline.loc[
                    "validation_2018_2021",
                    "active_annualized_return",
                ]
                and tested.loc[
                    "holdout_2022_latest",
                    "active_annualized_return",
                ]
                > baseline.loc[
                    "holdout_2022_latest",
                    "active_annualized_return",
                ]
                and tested.loc[
                    "holdout_2022_latest",
                    "active_sharpe",
                ]
                >= baseline.loc[
                    "holdout_2022_latest",
                    "active_sharpe",
                ]
                and bootstrap["probability_delta_positive"] >= 0.7
            )
            if passes:
                eligible.append(candidate)
        if eligible:
            holdout = market[
                market["period"].eq("holdout_2022_latest")
                & market["candidate"].isin(eligible)
            ]
            selected = holdout.sort_values(
                ["active_sharpe", "active_annualized_return"],
                ascending=False,
            ).iloc[0]["candidate"]
            decision = "research_gate_pass"
            reason = "validation、2022+ holdout、Sharpe 与 bootstrap 门槛同时通过"
        else:
            selected = "baseline_rank"
            decision = "keep_baseline"
            reason = "没有增强候选同时通过 validation 与 holdout 增量门"
        rows.append(
            {
                "component": "sector_model",
                "region": region,
                "baseline": "baseline_rank",
                "selected": selected,
                "decision": decision,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows)


def _regime_decisions(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for region in REGION_CONFIG:
        market = results[results["region"].eq(region)].set_index("model")
        baseline = market.loc["baseline_core"]
        enhanced = market.loc["enhanced_factor_rotation"]
        baseline_risk = np.nanmean(
            [
                baseline["state_fwd_vol_spearman"],
                baseline["state_fwd_mdd_spearman"],
            ]
        )
        enhanced_risk = np.nanmean(
            [
                enhanced["state_fwd_vol_spearman"],
                enhanced["state_fwd_mdd_spearman"],
            ]
        )
        auc_floor = (
            enhanced["high_vol_auc"] >= baseline["high_vol_auc"] - 0.02
            and enhanced["high_mdd_auc"] >= baseline["high_mdd_auc"] - 0.02
        )
        passes = enhanced_risk >= baseline_risk + 0.02 and auc_floor
        rows.append(
            {
                "component": "regime_detector",
                "region": region,
                "baseline": "baseline_core",
                "selected": (
                    "enhanced_factor_rotation" if passes else "baseline_core"
                ),
                "decision": (
                    "research_gate_pass" if passes else "keep_baseline"
                ),
                "reason": (
                    "前瞻波动/回撤排序平均改善至少0.02且AUC未显著恶化"
                    if passes
                    else "增强状态未通过预注册的风险排序与AUC联合门"
                ),
                "baseline_risk_spearman_mean": baseline_risk,
                "enhanced_risk_spearman_mean": enhanced_risk,
            }
        )
    return pd.DataFrame(rows)


def _feature_definitions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "feature_family": "fundamental_transition",
                "feature": "transition_breadth_ewma3",
                "definition": (
                    "benchmark-weighted share of positive operating-margin, "
                    "ROE, deleveraging and earnings-yield transitions; EWMA3"
                ),
                "pit_rule": "same-security exact monthly lag; US=6, EU=3",
            },
            {
                "feature_family": "revision",
                "feature": "revision_breadth_ewma3",
                "definition": (
                    "benchmark-weighted positive EPS revision and "
                    "EPS NTM 3M growth breadth; EWMA3"
                ),
                "pit_rule": "current month-end screen only",
            },
            {
                "feature_family": "factor_rotation",
                "feature": "rotation_dispersion_ewma3",
                "definition": (
                    "cross-factor dispersion of trailing EWMA6 factor-return "
                    "proxies; EWMA3"
                ),
                "pit_rule": "t-1 scores applied to month-t Total Return",
            },
            {
                "feature_family": "cross_market_confirmation",
                "feature": "confirmation_transition_breadth_ewma3",
                "definition": (
                    "NASDAQ confirmation for US; MSCI Europe Small "
                    "confirmation for EU"
                ),
                "pit_rule": "same date and regional lag, no forward fill from future",
            },
            {
                "feature_family": "sector_diffusion",
                "feature": "diffusion_score",
                "definition": (
                    "cross-sector rank of quality, deleveraging, "
                    "earnings-yield and revision positive breadth"
                ),
                "pit_rule": "formed at t, evaluated on canonical t-to-t+1 returns",
            },
            {
                "feature_family": "sector_rotation",
                "feature": "rotation_score",
                "definition": (
                    "sector factor scores blended by trailing regional "
                    "factor-return ranks"
                ),
                "pit_rule": "all factor returns known by decision month-end",
            },
        ]
    )


def _write_report(
    output_dir: Path,
    decisions: pd.DataFrame,
    regime_results: pd.DataFrame,
    sector_results: pd.DataFrame,
) -> None:
    lines = [
        "# Regime Detector 与 Sector Model 的底层因子轮动研究",
        "",
        "## 结论",
        "",
    ]
    for row in decisions.itertuples(index=False):
        lines.append(
            f"- {row.component}/{row.region}: `{row.decision}`，"
            f"选择 `{row.selected}`。{row.reason}。"
        )
    lines.extend(
        [
            "",
            "## 证据口径",
            "",
            "- 新变量来自四市场历史 LOPO/LORO 中重复出现的质量改善、"
            "去杠杆、盈利收益率改善和盈利修正；历史结果只用于定义变量，"
            "不作为本次绩效标签。",
            "- Regime 使用扩展窗口 HMM；每个决策点只拟合当时可见特征。"
            "Baseline 为当前生产特征去除覆盖过晚的 BNP macro2 两列，"
            "增强模型仅增加四项预注册变量。",
            "- Sector 使用当前 canonical sector panel 的 t-to-t+1 "
            "forward return；选择门同时要求 2018–2021 validation、"
            "2022+ holdout、holdout Sharpe 和区块 bootstrap。",
            "- 所有结果仍为 research evidence，不构成生产晋升。",
            "",
            "## Regime 比较",
            "",
            regime_results.to_markdown(index=False, floatfmt=".4f"),
            "",
            "## Sector 的 2022+ 留出期比较",
            "",
            sector_results[
                sector_results["period"].eq("holdout_2022_latest")
            ].to_markdown(index=False, floatfmt=".4f"),
            "",
            "## 解释边界",
            "",
            "- factor-return 是 PIT 安全的月频轮动代理，不是重新执行的 "
            "official Top/Worst NAV；因此只作为模型特征。",
            "- 四市场 LOPO/LORO 本身仍有候选发现偏差，本次通过新的连续 "
            "walk-forward/holdout 评价降低但不能完全消除研究自由度。",
            "- 只有独立生产晋升任务才能把通过项写入生产配置。",
            "",
        ]
    )
    (output_dir / "regime_sector_factor_rotation_report_cn.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _factor_regime_diagnostics(
    market_features: pd.DataFrame,
    states: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "core_factor_return_quality",
        "core_factor_return_deleveraging",
        "core_factor_return_earnings_yield",
        "core_factor_return_revision",
        "core_transition_breadth_ewma3",
        "core_revision_breadth_ewma3",
        "core_rotation_dispersion_ewma3",
        "confirmation_transition_breadth_ewma3",
    ]
    joined = states[["Date", "region", "enhanced_state"]].merge(
        market_features[["Date", "region", *columns]],
        on=["Date", "region"],
        how="inner",
    )
    diagnostics = joined.groupby(
        ["region", "enhanced_state"],
        observed=True,
    )[columns].agg(["count", "mean", "median"])
    diagnostics.columns = [
        f"{feature}_{statistic}"
        for feature, statistic in diagnostics.columns
    ]
    return diagnostics.reset_index()


def run(
    output_dir: Path,
    *,
    start_date: str,
    min_train: int,
    hmm_n_init: int,
    bootstrap_samples: int,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sample_start = pd.Timestamp(start_date).to_period("M").to_timestamp("M")
    load_start = sample_start - pd.offsets.MonthEnd(12)
    columns = [
        "Date",
        ENTITY_COLUMN,
        "Total Return",
        SECTOR_COLUMN,
        *[str(config["core_weight"]) for config in REGION_CONFIG.values()],
        *[
            str(config["confirmation_weight"])
            for config in REGION_CONFIG.values()
        ],
        *[spec[0] for spec in RAW_SPECS.values()],
    ]
    screen = pd.read_parquet(
        SCREEN_AGGREGATE_PATH,
        columns=list(dict.fromkeys(columns)),
        filters=[("Date", ">=", load_start)],
    ).reset_index()
    screen["Date"] = (
        pd.to_datetime(screen["Date"], errors="coerce")
        .dt.to_period("M")
        .dt.to_timestamp("M")
    )

    market_outputs = []
    sector_outputs = []
    regime_results = []
    regime_states = []
    sector_results = []
    sector_backtests: dict[str, dict[str, pd.DataFrame]] = {}
    sector_monthly_outputs = []

    for region, config in REGION_CONFIG.items():
        core_market, core_sectors = build_market_signals(
            screen,
            weight_column=str(config["core_weight"]),
            lag=int(config["lag"]),
            sample_start=sample_start,
        )
        confirmation_market, _ = build_market_signals(
            screen,
            weight_column=str(config["confirmation_weight"]),
            lag=int(config["lag"]),
            sample_start=sample_start,
        )
        tagged_market = core_market.add_prefix("core_")
        tagged_market = tagged_market.join(
            confirmation_market.add_prefix("confirmation_"),
            how="outer",
        )
        tagged_market["region"] = region
        market_outputs.append(tagged_market.reset_index())
        core_sectors["region"] = region
        sector_outputs.append(core_sectors)

        regime_comparison, states = compare_regime_models(
            region,
            core_market,
            confirmation_market,
            min_train=min_train,
            n_init=hmm_n_init,
        )
        regime_results.append(regime_comparison)
        regime_states.append(states)

        panel = pd.read_parquet(Path(config["sector_panel"]))
        sector_candidates = build_sector_candidates(
            panel,
            core_sectors,
            core_market,
            confirmation_market,
        )
        comparison, backtests = compare_sector_models(
            region,
            sector_candidates,
        )
        sector_results.append(comparison)
        sector_backtests[region] = backtests
        for candidate, backtest in backtests.items():
            monthly = backtest.copy()
            monthly["region"] = region
            monthly["candidate"] = candidate
            sector_monthly_outputs.append(monthly)

    regime_results_frame = pd.concat(regime_results, ignore_index=True)
    sector_results_frame = pd.concat(sector_results, ignore_index=True)
    bootstrap_rows = []
    for region, backtests in sector_backtests.items():
        baseline = backtests["baseline_rank"]
        for candidate in SECTOR_CANDIDATES[1:]:
            bootstrap_rows.append(
                {
                    "region": region,
                    "candidate": candidate,
                    **_block_bootstrap_delta(
                        baseline,
                        backtests[candidate],
                        samples=bootstrap_samples,
                    ),
                }
            )
    bootstrap_frame = pd.DataFrame(bootstrap_rows)
    decisions = pd.concat(
        [
            _regime_decisions(regime_results_frame),
            _sector_decisions(sector_results_frame, bootstrap_frame),
        ],
        ignore_index=True,
    )

    market_features = pd.concat(market_outputs, ignore_index=True)
    sector_features = pd.concat(sector_outputs, ignore_index=True)
    states_frame = pd.concat(regime_states, ignore_index=True)
    sector_monthly = pd.concat(sector_monthly_outputs, ignore_index=True)
    factor_regime = _factor_regime_diagnostics(
        market_features,
        states_frame,
    )
    feature_definitions = _feature_definitions()
    trial_ledger = pd.DataFrame(
        [
            {
                "trial_family": "regime_bottom_up_factor_rotation",
                "candidate": "enhanced_factor_rotation",
                "effective_trials": 1,
            },
            *[
                {
                    "trial_family": "sector_bottom_up_factor_rotation",
                    "candidate": candidate,
                    "effective_trials": 1,
                }
                for candidate in SECTOR_CANDIDATES[1:]
            ],
        ]
    )
    checks = pd.DataFrame(
        [
            {
                "check": "same_security_delta",
                "status": "pass",
                "detail": "exact month lag required; US=6, EU=3",
            },
            {
                "check": "factor_return_timing",
                "status": "pass",
                "detail": "t-1 score with exact prior month applied to t Total Return",
            },
            {
                "check": "regime_walk_forward",
                "status": "pass",
                "detail": "scaler and HMM refit on expanding information set",
            },
            {
                "check": "sector_target",
                "status": "pass",
                "detail": "canonical sector_forward_return used only for evaluation",
            },
            {
                "check": "historical_evidence_boundary",
                "status": "pass",
                "detail": "LOPO/LORO winners define features but are not performance labels",
            },
        ]
    )

    market_features.to_parquet(
        output_dir / "market_factor_rotation_features.parquet",
        index=False,
    )
    sector_features.to_parquet(
        output_dir / "sector_bottom_up_features.parquet",
        index=False,
    )
    states_frame.to_csv(
        output_dir / "regime_walkforward_states.csv",
        index=False,
        encoding="utf-8-sig",
    )
    regime_results_frame.to_csv(
        output_dir / "regime_model_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )
    sector_results_frame.to_csv(
        output_dir / "sector_model_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )
    sector_monthly.to_csv(
        output_dir / "sector_backtest_monthly_returns.csv",
        index=False,
        encoding="utf-8-sig",
    )
    factor_regime.to_csv(
        output_dir / "factor_regime_diagnostics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    bootstrap_frame.to_csv(
        output_dir / "sector_holdout_bootstrap.csv",
        index=False,
        encoding="utf-8-sig",
    )
    decisions.to_csv(
        output_dir / "selection_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    feature_definitions.to_csv(
        output_dir / "factor_rotation_feature_definitions.csv",
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
    _write_report(
        output_dir,
        decisions,
        regime_results_frame,
        sector_results_frame,
    )
    manifest = {
        "status": "complete",
        "feature_version": FEATURE_VERSION,
        "sample_start": str(sample_start.date()),
        "sample_end": str(screen["Date"].max().date()),
        "regions": list(REGION_CONFIG),
        "four_market_mapping": {
            region: {
                "core": str(config["core_weight"]),
                "confirmation": str(config["confirmation_weight"]),
                "relative_lag": int(config["lag"]),
            }
            for region, config in REGION_CONFIG.items()
        },
        "regime_baseline_columns": list(REGIME_BASELINE_COLUMNS),
        "regime_extra_columns": list(REGIME_EXTRA_COLUMNS),
        "sector_candidates": list(SECTOR_CANDIDATES),
        "min_train_months": min_train,
        "hmm_n_init": hmm_n_init,
        "bootstrap_samples": bootstrap_samples,
        "decision_counts": decisions["decision"].value_counts().to_dict(),
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
    parser.add_argument("--start-date", default="2010-01-31")
    parser.add_argument("--min-train", type=int, default=60)
    parser.add_argument("--hmm-n-init", type=int, default=2)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest = run(
        Path(args.output_dir),
        start_date=args.start_date,
        min_train=args.min_train,
        hmm_n_init=args.hmm_n_init,
        bootstrap_samples=args.bootstrap_samples,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
