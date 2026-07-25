"""TP 补充数据的 point-in-time 契约、解析与质量门槛。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .data_contract import CORE_WEIGHT_COLUMNS, ensure_isin_column


@dataclass(frozen=True)
class MacroObservation:
    series_id: str
    observation_date: pd.Timestamp
    vintage_at: pd.Timestamp
    source: str
    field: str
    value: float
    available_at: pd.Timestamp
    retrieved_at: pd.Timestamp
    unit: str
    currency: str | None = None
    availability_method: str = "source"


@dataclass(frozen=True)
class FundamentalFact:
    ISIN: str
    period_end: pd.Timestamp
    available_at: pd.Timestamp
    source: str
    field: str
    value: float
    retrieved_at: pd.Timestamp
    unit: str
    currency: str | None = None
    fiscal_period: str | None = None
    provider_field: str | None = None
    availability_method: str = "source"


@dataclass(frozen=True)
class EstimateObservation:
    ISIN: str
    estimate_as_of: pd.Timestamp
    fiscal_period_end: pd.Timestamp
    horizon: str
    available_at: pd.Timestamp
    source: str
    field: str
    value: float
    retrieved_at: pd.Timestamp
    unit: str
    currency: str | None = None
    analyst_count: float | None = None
    provider_field: str | None = None
    availability_method: str = "source"


@dataclass(frozen=True)
class ResolvedValue:
    Date: pd.Timestamp
    field: str
    resolved_value: float
    resolved_source: str
    available_at: pd.Timestamp
    observed_at: pd.Timestamp
    retrieved_at: pd.Timestamp
    unit: str
    currency: str | None = None
    ISIN: str | None = None
    series_id: str | None = None


FAMILY_REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "macro": (
        "series_id",
        "observation_date",
        "vintage_at",
        "source",
        "field",
        "value",
        "available_at",
        "retrieved_at",
        "unit",
    ),
    "fundamental": (
        "ISIN",
        "period_end",
        "available_at",
        "source",
        "field",
        "value",
        "retrieved_at",
        "unit",
    ),
    "estimate": (
        "ISIN",
        "estimate_as_of",
        "fiscal_period_end",
        "horizon",
        "available_at",
        "source",
        "field",
        "value",
        "retrieved_at",
        "unit",
    ),
}

FAMILY_DATE_COLUMNS: dict[str, tuple[str, ...]] = {
    "macro": ("observation_date", "vintage_at", "available_at", "retrieved_at"),
    "fundamental": ("period_end", "available_at", "retrieved_at"),
    "estimate": (
        "estimate_as_of",
        "fiscal_period_end",
        "available_at",
        "retrieved_at",
    ),
}

FAMILY_ENTITY_COLUMNS: dict[str, str] = {
    "macro": "series_id",
    "fundamental": "ISIN",
    "estimate": "ISIN",
}

FAMILY_OBSERVED_COLUMNS: dict[str, str] = {
    "macro": "observation_date",
    "fundamental": "period_end",
    "estimate": "estimate_as_of",
}

SOURCE_PRIORITY_DEFAULT: tuple[str, ...] = (
    "bloomberg_manual",
    "factset_manual",
    "ciq_manual",
    "sec_companyfacts",
    "esef_filings",
    "alpha_vantage",
    "fred",
    "ecb",
    "oecd",
    "imf",
    "world_bank",
    "dbnomics",
)

FAMILY_TOLERANCES: dict[str, float] = {
    "fundamental": 0.01,
    "estimate": 0.05,
    "macro": 0.001,
}


def _currency_required(unit: pd.Series) -> pd.Series:
    text = unit.astype("string")
    return (
        text.str.contains("currency", case=False, na=False)
        | text.str.contains("iso4217:", case=False, na=False)
        | text.str.fullmatch(r"[A-Z]{3}(?:[-/].*)?", na=False)
    )


def records_frame(records: Iterable[object]) -> pd.DataFrame:
    """将 dataclass 或 dict 记录转换为 DataFrame。"""
    rows = [
        asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)
        for item in records
    ]
    return pd.DataFrame(rows)


def normalize_records(frame: pd.DataFrame, family: str) -> pd.DataFrame:
    """验证并标准化一个补充数据族；无可用时间的记录不会进入有效层。"""
    if family not in FAMILY_REQUIRED_COLUMNS:
        raise ValueError(f"未知补充数据族：{family}")
    missing = [column for column in FAMILY_REQUIRED_COLUMNS[family] if column not in frame.columns]
    if missing:
        raise ValueError(f"{family} 记录缺少字段：{missing}")

    result = frame.copy()
    for column in FAMILY_DATE_COLUMNS[family]:
        result[column] = pd.to_datetime(result[column], errors="coerce").dt.tz_localize(None)
    result["value"] = pd.to_numeric(result["value"], errors="coerce")
    for column in ("source", "field", "unit"):
        result[column] = result[column].astype("string").str.strip()
    entity_column = FAMILY_ENTITY_COLUMNS[family]
    result[entity_column] = result[entity_column].astype("string").str.strip()
    result["family"] = family

    required_non_null = list(FAMILY_REQUIRED_COLUMNS[family])
    valid = result[required_non_null].notna().all(axis=1)
    valid &= np.isfinite(result["value"].astype(float))
    valid &= result["available_at"].notna()
    result = result.loc[valid].copy()

    key_columns = [
        entity_column,
        "field",
        "source",
        FAMILY_OBSERVED_COLUMNS[family],
        "available_at",
        "value",
    ]
    return (
        result.sort_values(key_columns)
        .drop_duplicates(key_columns, keep="last")
        .reset_index(drop=True)
    )


def _priority_for_field(
    field: str,
    source_priority: Mapping[str, Sequence[str]] | None,
) -> Sequence[str]:
    if not source_priority:
        return SOURCE_PRIORITY_DEFAULT
    return source_priority.get(field) or source_priority.get("*") or SOURCE_PRIORITY_DEFAULT


def materialize_point_in_time(
    records: pd.DataFrame,
    family: str,
    month_ends: Iterable[pd.Timestamp],
    source_priority: Mapping[str, Sequence[str]] | None = None,
) -> pd.DataFrame:
    """按月末解析每个实体/字段当时可获得的最高优先级值。"""
    normalized = normalize_records(records, family)
    if normalized.empty:
        return pd.DataFrame()

    dates = pd.DataFrame(
        {
            "Date": pd.DatetimeIndex(pd.to_datetime(list(month_ends), errors="coerce"))
            .dropna()
            .to_period("M")
            .to_timestamp("M")
            .unique()
            .sort_values()
        }
    )
    if dates.empty:
        return pd.DataFrame()

    entity_column = FAMILY_ENTITY_COLUMNS[family]
    observed_column = FAMILY_OBSERVED_COLUMNS[family]
    candidates: list[pd.DataFrame] = []
    group_columns = [entity_column, "field", "source"]
    for keys, group in normalized.groupby(group_columns, sort=False, dropna=False):
        entity, field, source = keys
        if family == "macro":
            selected_rows: list[pd.Series] = []
            for date in dates["Date"]:
                eligible = group.loc[
                    group["available_at"].le(date)
                    & group[observed_column].le(date)
                ]
                if eligible.empty:
                    continue
                row = eligible.sort_values(
                    [observed_column, "available_at", "retrieved_at"]
                ).iloc[-1].copy()
                row["Date"] = date
                selected_rows.append(row)
            if selected_rows:
                selected = pd.DataFrame(selected_rows)
                selected[entity_column] = entity
                selected["field"] = field
                selected["source"] = source
                candidates.append(selected)
            continue
        releases = (
            group.sort_values(["available_at", observed_column, "retrieved_at"])
            .drop_duplicates("available_at", keep="last")
            .sort_values("available_at")
        )
        selected = pd.merge_asof(
            dates,
            releases,
            left_on="Date",
            right_on="available_at",
            direction="backward",
            allow_exact_matches=True,
        ).dropna(subset=["value"])
        if selected.empty:
            continue
        selected[entity_column] = entity
        selected["field"] = field
        selected["source"] = source
        candidates.append(selected)

    if not candidates:
        return pd.DataFrame()
    resolved = pd.concat(candidates, ignore_index=True)
    priority_maps = {
        field: {
            source: rank
            for rank, source in enumerate(_priority_for_field(field, source_priority))
        }
        for field in resolved["field"].dropna().astype(str).unique()
    }
    resolved["_source_rank"] = [
        priority_maps[str(field)].get(str(source), len(priority_maps[str(field)]) + 100)
        for field, source in zip(resolved["field"], resolved["source"])
    ]
    resolved = (
        resolved.sort_values([entity_column, "Date", "field", "_source_rank", "available_at"])
        .drop_duplicates([entity_column, "Date", "field"], keep="first")
        .drop(columns="_source_rank")
    )
    resolved = resolved.rename(
        columns={
            "value": "resolved_value",
            "source": "resolved_source",
            observed_column: "observed_at",
        }
    )
    output_columns = [
        entity_column,
        "Date",
        "field",
        "resolved_value",
        "resolved_source",
        "available_at",
        "observed_at",
        "retrieved_at",
        "unit",
        "currency",
        "availability_method",
        "family",
    ]
    for column in output_columns:
        if column not in resolved:
            resolved[column] = pd.NA
    return resolved[output_columns].reset_index(drop=True)


def build_shadow_sidecar(
    screen: pd.DataFrame,
    resolved_security: pd.DataFrame,
    field_mappings: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    """构造手工源优先的影子结果，但不改写 canonical screen。"""
    if resolved_security.empty:
        return pd.DataFrame()
    canonical = ensure_isin_column(screen)
    canonical["Date"] = (
        pd.to_datetime(canonical["Date"], errors="coerce")
        .dt.to_period("M")
        .dt.to_timestamp("M")
    )
    automatic = resolved_security.copy()
    automatic["Date"] = (
        pd.to_datetime(automatic["Date"], errors="coerce")
        .dt.to_period("M")
        .dt.to_timestamp("M")
    )

    pieces: list[pd.DataFrame] = []
    for field, mapping in field_mappings.items():
        auto = automatic.loc[automatic["field"].eq(field)].copy()
        if auto.empty:
            continue
        reference_column = mapping.get("reference_screen_column")
        keys = canonical[["ISIN", "Date"]].copy()
        if reference_column and reference_column in canonical.columns:
            keys["manual_value"] = pd.to_numeric(
                canonical[reference_column], errors="coerce"
            ).replace([np.inf, -np.inf], np.nan)
        else:
            keys["manual_value"] = np.nan
        auto = auto.rename(
            columns={
                "resolved_value": "auto_value_raw",
                "resolved_source": "auto_source",
            }
        )
        auto["auto_value"] = auto["auto_value_raw"] * float(
            mapping.get("auto_multiplier") or 1.0
        )
        merged = keys.merge(auto, on=["ISIN", "Date"], how="inner", validate="one_to_many")
        merged["selected_value"] = merged["manual_value"].combine_first(merged["auto_value"])
        merged["selected_source"] = np.where(
            merged["manual_value"].notna(),
            "canonical_manual",
            merged["auto_source"],
        )
        family = str(mapping.get("family") or merged["family"].iloc[0])
        tolerance = float(mapping.get("tolerance", FAMILY_TOLERANCES.get(family, 0.01)))
        denominator = (
            pd.concat([merged["manual_value"].abs(), merged["auto_value"].abs()], axis=1)
            .max(axis=1)
            .clip(lower=1e-12)
        )
        merged["relative_diff"] = (
            merged["manual_value"] - merged["auto_value"]
        ).abs() / denominator
        overlap = merged["manual_value"].notna() & merged["auto_value"].notna()
        merged["conflict"] = overlap & merged["relative_diff"].gt(tolerance)
        merged["valid_auto"] = (
            merged["auto_value"].notna()
            & merged["available_at"].notna()
            & merged["available_at"].le(merged["Date"])
            & merged["unit"].notna()
            & merged["auto_source"].notna()
        )
        if "currency" in merged.columns:
            merged["valid_auto"] &= ~_currency_required(merged["unit"]) | merged[
                "currency"
            ].notna()
        merged["reference_screen_column"] = reference_column
        merged["promote_to_screen_column"] = mapping.get("promote_to_screen_column")
        merged["tolerance"] = tolerance
        pieces.append(merged)
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def _market_masks(
    screen: pd.DataFrame,
    candidate_isins: set[str] | None = None,
    holding_isins: set[str] | None = None,
) -> dict[str, pd.Series]:
    masks: dict[str, pd.Series] = {}
    market_names = ("MSCI_WORLD", "SP500", "STOXX600", "MSCI_EM")
    for market, column in zip(market_names, CORE_WEIGHT_COLUMNS):
        if column in screen.columns:
            masks[market] = pd.to_numeric(screen[column], errors="coerce").fillna(0).gt(0)
    isin = screen["ISIN"].astype("string")
    if candidate_isins:
        masks["CURRENT_CANDIDATES"] = isin.isin(candidate_isins)
    if holding_isins:
        masks["CURRENT_HOLDINGS"] = isin.isin(holding_isins)
    return masks


def coverage_by_market_field_year(
    screen: pd.DataFrame,
    sidecar: pd.DataFrame,
    field_mappings: Mapping[str, Mapping[str, Any]],
    *,
    candidate_isins: set[str] | None = None,
    holding_isins: set[str] | None = None,
    source: str | None = None,
) -> pd.DataFrame:
    """计算各市场、字段和年份的手工基线与影子覆盖率。"""
    canonical = ensure_isin_column(screen)
    canonical["Date"] = (
        pd.to_datetime(canonical["Date"], errors="coerce")
        .dt.to_period("M")
        .dt.to_timestamp("M")
    )
    canonical["_year"] = canonical["Date"].dt.year.astype("Int64")
    masks = _market_masks(canonical, candidate_isins, holding_isins)
    automatic = sidecar.copy()
    if automatic.empty:
        automatic = pd.DataFrame(
            columns=[
                "ISIN",
                "Date",
                "field",
                "auto_value",
                "auto_source",
                "valid_auto",
            ]
        )
    if source is not None and not automatic.empty:
        automatic = automatic.loc[automatic["auto_source"].eq(source)]

    rows: list[dict[str, Any]] = []
    for field, mapping in field_mappings.items():
        reference_column = mapping.get("reference_screen_column")
        if not reference_column or reference_column not in canonical.columns:
            continue
        field_auto = automatic.loc[
            automatic["field"].eq(field),
            ["ISIN", "Date", "auto_value", "valid_auto"],
        ]
        field_auto = field_auto.drop_duplicates(["ISIN", "Date"], keep="last")
        joined = canonical[["ISIN", "Date", "_year", reference_column]].copy()
        auto_index = field_auto.set_index(["ISIN", "Date"])
        canonical_index = pd.MultiIndex.from_frame(joined[["ISIN", "Date"]])
        joined["auto_value"] = auto_index["auto_value"].reindex(canonical_index).to_numpy()
        joined["valid_auto"] = auto_index["valid_auto"].reindex(canonical_index).to_numpy()
        baseline_value = pd.to_numeric(joined[reference_column], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        joined["_baseline"] = baseline_value.notna()
        valid_auto = joined["valid_auto"].astype("boolean").fillna(False)
        joined["_shadow"] = joined["_baseline"] | (
            joined["auto_value"].notna() & valid_auto
        )
        for market, mask in masks.items():
            sample = joined.loc[mask.to_numpy()]
            for year, period in [(None, sample), *list(sample.groupby("_year", dropna=True))]:
                if period.empty:
                    continue
                baseline = float(period["_baseline"].mean())
                shadow = float(period["_shadow"].mean())
                rows.append(
                    {
                        "market": market,
                        "field": field,
                        "year": "ALL" if year is None else int(year),
                        "eligible_cells": int(len(period)),
                        "baseline_coverage": baseline,
                        "shadow_coverage": shadow,
                        "coverage_uplift": shadow - baseline,
                        "source": source or "all_automatic",
                    }
                )
    return pd.DataFrame(rows)


def provider_acceptance_gate(
    coverage: pd.DataFrame,
    sidecar: pd.DataFrame,
    source: str,
    *,
    min_coverage_uplift: float = 0.15,
    min_consistency: float = 0.90,
) -> dict[str, Any]:
    """评估一个候选供应商是否达到付费试用门槛。"""
    all_years = (
        coverage.loc[coverage["year"].astype(str).eq("ALL")]
        if not coverage.empty
        else coverage
    )
    coverage_uplift = float(all_years["coverage_uplift"].mean()) if not all_years.empty else 0.0
    overlap = sidecar.loc[
        sidecar["auto_source"].eq(source)
        & sidecar["manual_value"].notna()
        & sidecar["auto_value"].notna()
    ]
    consistency = float((~overlap["conflict"]).mean()) if not overlap.empty else None
    passed = coverage_uplift >= min_coverage_uplift
    passed &= consistency is not None and consistency >= min_consistency
    return {
        "source": source,
        "coverage_uplift": coverage_uplift,
        "required_coverage_uplift": min_coverage_uplift,
        "overlap_cells": int(len(overlap)),
        "consistency": consistency,
        "required_consistency": min_consistency,
        "passed": bool(passed),
    }


def validate_resolved_values(frame: pd.DataFrame, entity_column: str) -> dict[str, Any]:
    """验证 resolved sidecar 的唯一性、元数据及无前视偏差。"""
    if frame.empty:
        return {
            "rows": 0,
            "duplicate_keys": 0,
            "lookahead_rows": 0,
            "metadata_incomplete_rows": 0,
            "ok": True,
        }
    keys = [entity_column, "Date", "field"]
    duplicate_keys = int(frame.duplicated(keys, keep=False).sum())
    date = pd.to_datetime(frame["Date"], errors="coerce")
    available = pd.to_datetime(frame["available_at"], errors="coerce")
    observed = pd.to_datetime(frame["observed_at"], errors="coerce")
    lookahead_rows = int(
        (available.gt(date) | observed.gt(date) | available.isna() | observed.isna()).sum()
    )
    metadata_columns = ["resolved_source", "unit", "retrieved_at", "available_at"]
    metadata_incomplete_mask = frame[metadata_columns].isna().any(axis=1)
    if "currency" in frame.columns:
        metadata_incomplete_mask |= _currency_required(frame["unit"]) & frame[
            "currency"
        ].isna()
    metadata_incomplete = int(metadata_incomplete_mask.sum())
    return {
        "rows": int(len(frame)),
        "duplicate_keys": duplicate_keys,
        "lookahead_rows": lookahead_rows,
        "metadata_incomplete_rows": metadata_incomplete,
        "ok": duplicate_keys == 0 and lookahead_rows == 0 and metadata_incomplete == 0,
    }
