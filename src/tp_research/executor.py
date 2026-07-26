"""Cross-market raw, relative and synergy research execution rules.

This module is owned by the canonical :mod:`tp_research` package.  The old
Former ``backtest_code.research`` callers must import this public module.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


OFFICIAL_SIDES = ("Top", "Worst")
TERMINAL_SUCCESS_STATUSES = frozenset({"success", "skipped"})
STATUS_RANK = {"success": 3, "skipped": 2, "failed": 1}


@dataclass(frozen=True)
class GateThresholds:
    """Evidence thresholds applied equally to every raw or relative variable."""

    min_coverage: float = 0.75
    min_ratio_cagr: float = 0.0
    min_top_worst_ratio: float = 0.0
    min_robust_score: float = 0.0


@dataclass(frozen=True)
class RelativeLevelSpec:
    """One higher-is-better absolute-level variable eligible for relative tests."""

    raw_column: str
    score_column: str
    family: str
    direction: float = 1.0
    role: str = ""
    source: str = ""
    note: str = ""


def dedupe_official_results(results: pd.DataFrame) -> pd.DataFrame:
    """Keep the strongest terminal record for each metric and official side."""

    required = {"metric", "side", "status"}
    if results.empty or not required.issubset(results.columns):
        return results.copy()
    output = results.copy()
    output["_status_rank"] = output["status"].map(STATUS_RANK).fillna(0)
    output["_input_order"] = np.arange(len(output))
    output = output.sort_values(
        ["metric", "side", "_status_rank", "_input_order"],
        ascending=[True, True, False, True],
    )
    output = output.drop_duplicates(["metric", "side"], keep="first")
    return (
        output.drop(columns=["_status_rank", "_input_order"])
        .sort_values(["metric", "side"])
        .reset_index(drop=True)
    )


def read_official_results(paths: Iterable[str | Path]) -> pd.DataFrame:
    """Read and merge resumable main/shard CSVs without overwriting prior waves."""

    frames: list[pd.DataFrame] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists() or path.stat().st_size <= 0:
            continue
        try:
            frames.append(pd.read_csv(path))
        except pd.errors.EmptyDataError:
            continue
    if not frames:
        return pd.DataFrame()
    return dedupe_official_results(pd.concat(frames, ignore_index=True))


def incomplete_official_metrics(
    metrics: Iterable[str],
    completed: pd.DataFrame,
    *,
    terminal_failure_pattern: str | None = None,
) -> list[str]:
    """Return metrics missing a terminal official Top or Worst result."""

    metric_names = list(dict.fromkeys(str(metric) for metric in metrics))
    if completed.empty:
        return metric_names
    terminal_mask = completed["status"].isin(TERMINAL_SUCCESS_STATUSES)
    if terminal_failure_pattern:
        messages = completed.get(
            "message",
            pd.Series("", index=completed.index),
        ).astype(str)
        terminal_mask |= completed["status"].eq("failed") & messages.str.contains(
            terminal_failure_pattern,
            case=False,
            na=False,
        )
    terminal = completed[terminal_mask]
    done = set(zip(terminal["metric"].astype(str), terminal["side"].astype(str)))
    return [
        metric
        for metric in metric_names
        if any((metric, side) not in done for side in OFFICIAL_SIDES)
    ]


def shard_metric_names(
    metrics: Iterable[str],
    workers: int,
    shard_size: int = 0,
) -> list[list[str]]:
    """Create deterministic disjoint metric shards for process workers."""

    names = list(dict.fromkeys(str(metric) for metric in metrics))
    if shard_size > 0:
        return [
            names[index : index + shard_size]
            for index in range(0, len(names), shard_size)
        ]
    shards = [[] for _ in range(max(1, int(workers)))]
    for index, metric in enumerate(names):
        shards[index % len(shards)].append(metric)
    return [shard for shard in shards if shard]


def new_wave_id(requested: str | None = None, *, now: datetime | None = None) -> str:
    """Return a caller-supplied wave or a collision-resistant timestamp wave."""

    if requested and requested.strip():
        return requested.strip()
    timestamp = now or datetime.now()
    return timestamp.strftime("wave_%Y%m%d_%H%M%S_%f")


def shard_result_path(
    output_dir: str | Path,
    wave: str,
    shard_id: int,
    *,
    filename: str = "official_run_results.csv",
) -> Path:
    """Return the independent output path owned by one worker."""

    return (
        Path(output_dir)
        / "parallel_shards"
        / str(wave)
        / f"shard_{int(shard_id):02d}"
        / filename
    )


def evaluate_official_top_worst_gate(
    summary: pd.DataFrame,
    diagnostics: pd.DataFrame,
    *,
    thresholds: GateThresholds,
    metadata: pd.DataFrame | None = None,
    metrics: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Apply one evidence gate to raw, CIQ, FactSet, database and relative fields."""

    required = {"metric", "side", "status"}
    missing = required.difference(summary.columns)
    if missing:
        raise KeyError(f"official summary is missing columns: {sorted(missing)}")
    allowed = set(str(metric) for metric in metrics) if metrics is not None else None
    diagnostic_map = (
        diagnostics.drop_duplicates("metric", keep="last")
        .set_index("metric")
        .to_dict(orient="index")
        if not diagnostics.empty and "metric" in diagnostics.columns
        else {}
    )
    metadata_map = (
        metadata.drop_duplicates("metric", keep="last")
        .set_index("metric")
        .to_dict(orient="index")
        if metadata is not None and not metadata.empty and "metric" in metadata.columns
        else {}
    )
    grouped = {
        str(metric): group
        for metric, group in summary.groupby(
            summary["metric"].astype(str),
            sort=True,
        )
    }
    metric_names = sorted(allowed if allowed is not None else grouped)
    rows: list[dict[str, object]] = []
    for metric in metric_names:
        group = grouped.get(metric, summary.iloc[0:0])
        side_rows = {
            side: group[group["side"].astype(str).eq(side)]
            for side in OFFICIAL_SIDES
        }
        top = side_rows["Top"]
        top_row = top.iloc[-1] if not top.empty else pd.Series(dtype=object)
        top_complete = bool(
            not top.empty
            and top["status"].astype(str).isin(TERMINAL_SUCCESS_STATUSES).any()
        )
        worst = side_rows["Worst"]
        worst_complete = bool(
            not worst.empty
            and worst["status"].astype(str).isin(TERMINAL_SUCCESS_STATUSES).any()
        )
        diagnostic = diagnostic_map.get(metric, {})
        coverage = pd.to_numeric(top_row.get("coverage", np.nan), errors="coerce")
        if pd.isna(coverage):
            coverage = pd.to_numeric(
                diagnostic.get("coverage", np.nan),
                errors="coerce",
            )
        coverage = np.nan if pd.isna(coverage) else float(coverage)
        ratio_cagr = _as_float(top_row.get("ratio_cagr", np.nan))
        top_worst = _as_float(
            top_row.get("top_worst_ratio_return", np.nan)
        )
        robust = _as_float(top_row.get("robust_score", np.nan))
        failures: list[str] = []
        if not top_complete:
            failures.append("official_top_incomplete")
        if not worst_complete:
            failures.append("official_worst_incomplete")
        if not np.isfinite(coverage) or coverage < thresholds.min_coverage:
            failures.append(f"coverage<{thresholds.min_coverage:g}")
        if not np.isfinite(ratio_cagr) or ratio_cagr <= thresholds.min_ratio_cagr:
            failures.append(f"ratio_cagr<={thresholds.min_ratio_cagr:g}")
        if (
            not np.isfinite(top_worst)
            or top_worst <= thresholds.min_top_worst_ratio
        ):
            failures.append(
                f"top_worst_ratio_return<={thresholds.min_top_worst_ratio:g}"
            )
        if not np.isfinite(robust) or robust <= thresholds.min_robust_score:
            failures.append(f"robust_score<={thresholds.min_robust_score:g}")
        rows.append(
            {
                "metric": metric,
                **metadata_map.get(metric, {}),
                "coverage": coverage,
                "ratio_cagr": ratio_cagr,
                "top_worst_ratio_return": top_worst,
                "robust_score": robust,
                "ratio_max_drawdown": top_row.get("ratio_max_drawdown", np.nan),
                "tracking_error": top_row.get("tracking_error", np.nan),
                "annual_active_hit_rate": top_row.get(
                    "annual_active_hit_rate", np.nan
                ),
                "avg_turnover": top_row.get("avg_turnover", np.nan),
                "start_date": top_row.get("start_date", ""),
                "official_top_complete": top_complete,
                "official_worst_complete": worst_complete,
                "pass_gate": not failures,
                "fail_reasons": "; ".join(failures),
            }
        )
    gate = pd.DataFrame(rows)
    if gate.empty:
        return gate
    return gate.sort_values(
        ["pass_gate", "robust_score", "ratio_cagr"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def build_same_security_relative_variables(
    screen: pd.DataFrame,
    specs: Sequence[RelativeLevelSpec],
    *,
    lags: Sequence[int],
    transforms: Sequence[str],
    date_col: str,
    security_col: str,
    sector_col: str,
    raw_score: Callable[[pd.DataFrame, RelativeLevelSpec], pd.Series],
    sector_score: Callable[[pd.Series, pd.Series, pd.Series], pd.Series],
    winsorize: Callable[[pd.Series, pd.Series], pd.Series],
    column_name: Callable[[RelativeLevelSpec, str, int], str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create directional and score deltas using same-security screen lags."""

    unsupported = set(transforms).difference({"directional_delta", "score_delta"})
    if unsupported:
        raise ValueError(f"unsupported relative transforms: {sorted(unsupported)}")
    lag_values = sorted(set(int(lag) for lag in lags))
    if not lag_values or any(lag <= 0 for lag in lag_values):
        raise ValueError("relative lags must be positive screen-observation counts")
    output = screen.sort_values([security_col, date_col]).copy()
    entity = output[security_col].astype(str)
    definitions: list[dict[str, object]] = []
    for spec in specs:
        level = (
            pd.to_numeric(output[spec.raw_column], errors="coerce")
            * float(spec.direction)
        ).replace([np.inf, -np.inf], np.nan)
        score = raw_score(output, spec)
        for lag in lag_values:
            if "directional_delta" in transforms:
                values = level - level.groupby(entity).shift(lag)
                values = winsorize(values, output[date_col])
                metric = column_name(spec, "directional_delta", lag)
                output[metric] = sector_score(
                    values,
                    output[date_col],
                    output[sector_col],
                )
                definitions.append(
                    _relative_definition(spec, metric, "directional_delta", lag)
                )
            if "score_delta" in transforms:
                values = score - score.groupby(entity).shift(lag)
                metric = column_name(spec, "score_delta", lag)
                output[metric] = sector_score(
                    values,
                    output[date_col],
                    output[sector_col],
                )
                definitions.append(
                    _relative_definition(spec, metric, "score_delta", lag)
                )
    return (
        output.sort_values([date_col, security_col]).reset_index(drop=True),
        pd.DataFrame(definitions),
    )


def _relative_definition(
    spec: RelativeLevelSpec,
    metric: str,
    transform: str,
    lag: int,
) -> dict[str, object]:
    return {
        "metric": metric,
        "raw_column": spec.raw_column,
        "score_column": spec.score_column,
        "base_family": spec.family,
        "role": spec.role,
        "source": spec.source,
        "base_direction": spec.direction,
        "transform": transform,
        "lag_observations": lag,
        "base_note": spec.note,
    }


def build_synergy_candidate_matrix(
    screen: pd.DataFrame,
    legs: pd.DataFrame,
    *,
    bucket_order: Sequence[str],
    prefix: str,
    weighted_scores: Callable[[pd.DataFrame, Mapping[str, float], int], pd.Series],
    average_scores: Callable[[pd.DataFrame, Sequence[str], int], pd.Series],
    subset_sizes: Sequence[int] = (2, 3),
    include_individual_leave_one_out: bool = False,
    materialize: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build cross-bucket pairs, subsets, full model and leave-one-out evidence."""

    required = {"metric", "bucket"}
    missing = required.difference(legs.columns)
    if missing:
        raise KeyError(f"synergy legs are missing columns: {sorted(missing)}")
    output = screen.copy()
    rows: list[dict[str, object]] = []
    leg_metrics = legs["metric"].astype(str).tolist()
    leg_bucket = legs.set_index("metric")["bucket"].astype(str).to_dict()

    for left_index, left in enumerate(leg_metrics):
        for right in leg_metrics[left_index + 1 :]:
            if leg_bucket[left] == leg_bucket[right]:
                continue
            components = {left: 0.5, right: 0.5}
            metric = _candidate_name(prefix, "pair", sorted(components))
            if materialize:
                output[metric] = weighted_scores(output, components, 2)
            rows.append(
                _candidate_row(
                    metric,
                    "pair",
                    components,
                    [leg_bucket[left], leg_bucket[right]],
                )
            )

    bucket_columns: dict[str, str] = {}
    for bucket in bucket_order:
        metrics = legs.loc[legs["bucket"].astype(str).eq(str(bucket)), "metric"].astype(str).tolist()
        if not metrics:
            continue
        metric = f"{prefix}_bucket_{_slug(bucket)}"
        if materialize:
            output[metric] = average_scores(output, metrics, 1)
        bucket_columns[str(bucket)] = metric
        rows.append(
            _candidate_row(
                metric,
                "bucket_component",
                {name: 1.0 / len(metrics) for name in metrics},
                [str(bucket)],
            )
        )

    bucket_names = list(bucket_columns)
    for size in sorted(set(int(value) for value in subset_sizes)):
        if size < 2:
            continue
        for buckets in _combinations(bucket_names, size):
            components = {
                bucket_columns[bucket]: 1.0 / size for bucket in buckets
            }
            metric = _candidate_name(prefix, "subset", buckets, length=10)
            if materialize:
                output[metric] = weighted_scores(output, components, size)
            rows.append(
                _candidate_row(metric, "family_subset", components, buckets)
            )

    if bucket_columns:
        components = {
            metric: 1.0 / len(bucket_columns)
            for metric in bucket_columns.values()
        }
        full_metric = f"{prefix}_full_bucket_equal"
        if materialize:
            output[full_metric] = weighted_scores(
                output,
                components,
                max(2, min(4, len(components))),
            )
        rows.append(
            _candidate_row(
                full_metric,
                "full_model",
                components,
                bucket_names,
            )
        )
        for left_out, left_out_column in bucket_columns.items():
            kept = {
                bucket: column
                for bucket, column in bucket_columns.items()
                if bucket != left_out
            }
            if len(kept) < 2:
                continue
            components = {
                column: 1.0 / len(kept) for column in kept.values()
            }
            metric = f"{prefix}_loo_without_{_slug(left_out)}"
            if materialize:
                output[metric] = weighted_scores(
                    output,
                    components,
                    max(2, min(4, len(components))),
                )
            row = _candidate_row(
                metric,
                "leave_one_out",
                components,
                list(kept),
            )
            row["left_out_bucket"] = left_out
            row["full_model_metric"] = full_metric
            rows.append(row)

    if include_individual_leave_one_out and len(leg_metrics) >= 3:
        full_components = {
            metric: 1.0 / len(leg_metrics) for metric in leg_metrics
        }
        full_metric = f"{prefix}_full_individual_equal"
        if materialize:
            output[full_metric] = weighted_scores(
                output,
                full_components,
                max(2, min(4, len(full_components))),
            )
        rows.append(
            _candidate_row(
                full_metric,
                "individual_full_model",
                full_components,
                bucket_names,
            )
        )
        for left_out in leg_metrics:
            kept = [metric for metric in leg_metrics if metric != left_out]
            components = {metric: 1.0 / len(kept) for metric in kept}
            metric = _candidate_name(
                prefix,
                "loo_without_var",
                [left_out],
                length=10,
            )
            if materialize:
                output[metric] = weighted_scores(
                    output,
                    components,
                    max(2, min(4, len(components))),
                )
            row = _candidate_row(
                metric,
                "leave_one_variable_out",
                components,
                sorted({leg_bucket[name] for name in kept}),
            )
            row["left_out_metric"] = left_out
            row["full_model_metric"] = full_metric
            rows.append(row)
    return output, pd.DataFrame(rows)


def _candidate_row(
    metric: str,
    candidate_type: str,
    components: Mapping[str, float],
    buckets: Sequence[str],
) -> dict[str, object]:
    return {
        "metric": metric,
        "candidate_type": candidate_type,
        "component_count": len(components),
        "buckets": "|".join(str(bucket) for bucket in buckets),
        "components": "|".join(components),
        "component_weights": dict(components),
        "label": " + ".join(str(bucket) for bucket in buckets),
    }


def _as_float(value: object) -> float:
    numeric = pd.to_numeric(value, errors="coerce")
    return np.nan if pd.isna(numeric) else float(numeric)


def _candidate_name(
    prefix: str,
    kind: str,
    items: Sequence[str],
    *,
    length: int = 12,
) -> str:
    digest = hashlib.sha1("|".join(items).encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{kind}_{digest}"


def _slug(value: object) -> str:
    return "_".join(
        part for part in "".join(
            character.lower() if character.isalnum() else " "
            for character in str(value)
        ).split()
        if part
    )


def _combinations(values: Sequence[str], size: int) -> Iterable[list[str]]:
    if size == 0:
        yield []
        return
    for index, value in enumerate(values):
        for tail in _combinations(values[index + 1 :], size - 1):
            yield [value, *tail]
