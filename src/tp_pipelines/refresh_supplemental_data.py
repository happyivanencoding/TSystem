"""刷新 TP 影子补充数据并写 pipeline manifest。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from argparse import Namespace
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
import pyarrow.parquet as pq

from tp_core.data_contract import CORE_WEIGHT_COLUMNS, ensure_isin_column, validate_screen_contract
from tp_core.data_sources import (
    LAST_SCREEN_PATH,
    SCREEN_AGGREGATE_PATH,
    SUPPLEMENTAL_DIR,
    SUPPLEMENTAL_NORMALIZED_DIR,
    SUPPLEMENTAL_QA_DIR,
    SUPPLEMENTAL_RAW_DIR,
    SUPPLEMENTAL_RESOLVED_DIR,
    TP_ROOT,
)
from tp_core.supplemental_data import (
    FAMILY_REQUIRED_COLUMNS,
    build_shadow_sidecar,
    coverage_by_market_field_year,
    materialize_point_in_time,
    normalize_records,
    provider_acceptance_gate,
    validate_resolved_values,
)
from tp_core.supplemental_providers import (
    AlphaVantageEstimatesProvider,
    DbnomicsSeriesProvider,
    EsefFilingsProvider,
    FredProvider,
    HttpClient,
    ImfDataMapperProvider,
    ProviderBatch,
    SdmxCsvProvider,
    SecCompanyFactsProvider,
    WorldBankProvider,
)

from .common import StepManifest, atomic_write_json, path_profile


DEFAULT_CONFIG = Path(__file__).with_name("supplemental_sources.json")
DEFAULT_SECURITY_MAP = SUPPLEMENTAL_DIR / "identifiers" / "security_identifiers.csv"
DEFAULT_CANDIDATES = TP_ROOT / "05_candidates" / "latest_candidates.parquet"
DEFAULT_HOLDINGS = TP_ROOT / "06_portfolios" / "latest_target_weights.parquet"
SOURCE_CHOICES = (
    "fred",
    "ecb",
    "oecd",
    "imf",
    "world_bank",
    "sec",
    "esef",
    "alpha_vantage",
)


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _hash(value: Any) -> str:
    data = value if isinstance(value, str) else _stable_json(value)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _atomic_write_parquet(path: Path, frame: pd.DataFrame, *, index: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
    frame.to_parquet(temp_path, index=index)
    temp_path.replace(path)


def _load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError(f"不支持的 supplemental config 版本：{payload.get('version')}")
    return payload


def _read_isin_set(path: Path) -> set[str]:
    if not path.exists():
        return set()
    frame = pd.read_parquet(path)
    try:
        frame = ensure_isin_column(frame)
    except ValueError:
        return set()
    return set(frame["ISIN"].dropna().astype(str))


def _load_security_map(
    path: Path,
    *,
    write_template: bool = False,
) -> tuple[pd.DataFrame, set[str], set[str]]:
    latest = ensure_isin_column(pd.read_parquet(LAST_SCREEN_PATH))
    candidate_isins = _read_isin_set(DEFAULT_CANDIDATES)
    holding_isins = _read_isin_set(DEFAULT_HOLDINGS)
    core_mask = pd.Series(False, index=latest.index)
    for column in CORE_WEIGHT_COLUMNS:
        if column in latest.columns:
            core_mask |= pd.to_numeric(latest[column], errors="coerce").fillna(0).gt(0)
    core_mask |= latest["ISIN"].astype(str).isin(candidate_isins | holding_isins)

    base_columns = [
        column
        for column in ("ISIN", "Symbol", "Name", "Exchange Country Name")
        if column in latest.columns
    ]
    securities = latest.loc[core_mask, base_columns].copy()
    is_us = securities.get("Exchange Country Name", pd.Series("", index=securities.index)).eq(
        "UNITED STATES"
    )
    symbol = securities.get("Symbol", pd.Series(pd.NA, index=securities.index)).astype(
        "string"
    )
    plain_ticker = symbol.str.fullmatch(r"[A-Za-z0-9.\-]+").fillna(False)
    securities["AlphaSymbol"] = pd.Series(
        pd.NA, index=securities.index, dtype="string"
    )
    securities.loc[is_us & plain_ticker, "AlphaSymbol"] = symbol
    securities["Currency"] = pd.Series(pd.NA, index=securities.index, dtype="string")
    securities.loc[is_us, "Currency"] = "USD"
    securities["CIK"] = pd.NA
    securities["LEI"] = pd.NA

    if path.exists():
        overrides = pd.read_csv(path, dtype="string")
        if "ISIN" not in overrides.columns:
            raise ValueError(f"证券映射缺少 ISIN：{path}")
        override_columns = [
            column
            for column in ("CIK", "LEI", "AlphaSymbol", "Currency")
            if column in overrides.columns
        ]
        overrides = overrides[["ISIN", *override_columns]].drop_duplicates(
            "ISIN", keep="last"
        )
        overrides = overrides.rename(
            columns={column: f"{column}_override" for column in override_columns}
        )
        securities = securities.merge(
            overrides,
            on="ISIN",
            how="left",
            validate="one_to_one",
        )
        for column in override_columns:
            override_column = f"{column}_override"
            securities[column] = securities[override_column].where(
                securities[override_column].notna(),
                securities[column],
            )
            securities = securities.drop(columns=override_column)
        generated_non_us_symbol = (
            ~securities.get(
                "Exchange Country Name", pd.Series("", index=securities.index)
            ).eq("UNITED STATES")
            & securities["AlphaSymbol"].astype("string").eq(
                securities.get("Symbol", pd.Series(pd.NA, index=securities.index)).astype(
                    "string"
                )
            )
        ).fillna(False)
        securities.loc[generated_non_us_symbol, "AlphaSymbol"] = pd.NA
    securities = securities.drop_duplicates("ISIN")
    if write_template and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp.csv")
        securities.to_csv(temp_path, index=False, encoding="utf-8-sig")
        temp_path.replace(path)
    return securities, candidate_isins, holding_isins


def _enabled_macro_jobs(config: Mapping[str, Any], source: str) -> list[dict[str, Any]]:
    return [
        dict(job)
        for job in config.get("macro_jobs", [])
        if job.get("enabled", True) and job.get("provider") == source
    ]


def _jobs_for_source(
    source: str,
    config: Mapping[str, Any],
    securities: pd.DataFrame,
    max_jobs: int | None,
) -> list[dict[str, Any]]:
    if source in {"fred", "ecb", "oecd", "imf", "world_bank"}:
        jobs = _enabled_macro_jobs(config, source)
    elif source == "sec":
        country = securities.get("Exchange Country Name", pd.Series("", index=securities.index))
        symbol = securities.get("Symbol", pd.Series(pd.NA, index=securities.index))
        has_identifier = securities["CIK"].notna() | (
            country.eq("UNITED STATES") & symbol.astype("string").str.fullmatch(r"[A-Za-z0-9.\-]+").fillna(False)
        )
        jobs = securities.loc[has_identifier].to_dict("records")
    elif source == "esef":
        jobs = securities.loc[securities["LEI"].notna()].to_dict("records")
    elif source == "alpha_vantage":
        jobs = securities.loc[securities["AlphaSymbol"].notna()].to_dict("records")
    else:
        raise ValueError(f"未知 supplemental source：{source}")

    configured_limit = int(config.get("source_options", {}).get(source, {}).get("max_jobs") or len(jobs))
    limit = configured_limit if max_jobs is None else min(configured_limit, max_jobs)
    return jobs[:limit]


def _job_key(source: str, job: Mapping[str, Any]) -> str:
    if source == "fred":
        return str(job["series_id"])
    if source in {"ecb", "oecd"}:
        return str(job["series_id"])
    if source in {"imf", "world_bank"}:
        return f"{job['indicator']}:{','.join(job.get('countries') or [])}"
    identifier = None
    for column in ("CIK", "LEI", "AlphaSymbol", "Symbol"):
        value = job.get(column)
        if value is not None and not pd.isna(value) and str(value).strip():
            identifier = value
            break
    return f"{job.get('ISIN')}:{identifier}"


def _checkpoint_path(source: str) -> Path:
    return SUPPLEMENTAL_QA_DIR / "checkpoints" / f"{source}.json"


def _load_completed(path: Path, signature: str, resume: bool) -> set[str]:
    if not resume or not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("signature") != signature:
        return set()
    return set(payload.get("completed_jobs") or [])


def _write_checkpoint(path: Path, signature: str, completed: set[str]) -> None:
    atomic_write_json(
        path,
        {
            "signature": signature,
            "completed_jobs": sorted(completed),
            "completed_count": len(completed),
        },
    )


def _write_raw_payload(source: str, job_key: str, payload: Any) -> tuple[Path, str]:
    serialized = payload if isinstance(payload, str) else _stable_json(payload)
    payload_hash = _hash(serialized)
    suffix = ".txt" if isinstance(payload, str) else ".json"
    path = SUPPLEMENTAL_RAW_DIR / source / f"{_hash(job_key)[:12]}_{payload_hash[:16]}{suffix}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
    return path, payload_hash


def _persist_batch(batch: ProviderBatch) -> dict[str, Any]:
    raw_path, payload_hash = _write_raw_payload(batch.source, batch.job_key, batch.raw_payload)
    normalized_path: Path | None = None
    rows = 0
    if not batch.records.empty:
        records = batch.records.copy()
        if "provider_priority" in records.columns:
            observed_column = {
                "fundamental": "period_end",
                "estimate": "estimate_as_of",
                "macro": "observation_date",
            }[batch.family]
            entity_column = "series_id" if batch.family == "macro" else "ISIN"
            records = (
                records.sort_values("provider_priority")
                .drop_duplicates(
                    [entity_column, "field", "source", observed_column, "available_at"],
                    keep="first",
                )
            )
        records = normalize_records(records, batch.family)
        rows = int(len(records))
        normalized_path = (
            SUPPLEMENTAL_NORMALIZED_DIR
            / batch.family
            / batch.source
            / f"part_{_hash(batch.job_key)[:12]}_{payload_hash[:16]}.parquet"
        )
        if rows and not normalized_path.exists():
            _atomic_write_parquet(normalized_path, records)
    return {
        "job_key": batch.job_key,
        "family": batch.family,
        "rows": rows,
        "raw_path": str(raw_path),
        "normalized_path": str(normalized_path) if normalized_path else None,
        "payload_hash": payload_hash,
    }


def _client_for_source(source: str, config: Mapping[str, Any], timeout_seconds: int) -> HttpClient:
    options = config.get("source_options", {}).get(source, {})
    if source == "sec":
        user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
        if not user_agent or "@" not in user_agent:
            raise ValueError("SEC_USER_AGENT 必须包含可联系邮箱，例如 'TP research name@example.com'")
    else:
        user_agent = "TP personal research supplemental-data/1.0"
    return HttpClient(
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
        min_interval_seconds=float(options.get("min_interval_seconds") or 0.0),
    )


def _fetch_batch(
    source: str,
    job: Mapping[str, Any],
    config: Mapping[str, Any],
    client: HttpClient,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    retrieved_at: pd.Timestamp,
) -> ProviderBatch:
    if source == "fred":
        return FredProvider(client).fetch(
            job,
            start=start,
            end=end,
            retrieved_at=retrieved_at,
            api_key=os.environ.get("FRED_API_KEY", ""),
        )
    if source in {"ecb", "oecd"}:
        return SdmxCsvProvider(source, client).fetch(
            job, start=start, end=end, retrieved_at=retrieved_at
        )
    if source == "imf":
        try:
            return ImfDataMapperProvider(client).fetch(
                job, start=start, end=end, retrieved_at=retrieved_at
            )
        except RuntimeError:
            fallback = job.get("fallback")
            if not fallback or fallback.get("provider") != "dbnomics":
                raise
            fallback_job = {
                **dict(fallback),
                "indicator": job["indicator"],
                "countries": job.get("countries") or [],
                "field_prefix": job.get("field_prefix"),
                "unit": job.get("unit"),
                "currency": job.get("currency"),
            }
            return DbnomicsSeriesProvider(client).fetch(
                fallback_job,
                start=start,
                end=end,
                retrieved_at=retrieved_at,
                original_provider="IMF",
            )
    if source == "world_bank":
        return WorldBankProvider(client).fetch(
            job, start=start, end=end, retrieved_at=retrieved_at
        )
    if source == "sec":
        return SecCompanyFactsProvider(client).fetch(
            job,
            start=start,
            end=end,
            retrieved_at=retrieved_at,
            concepts=list(config.get("sec_concepts") or []),
        )
    if source == "esef":
        return EsefFilingsProvider(client).fetch(
            job,
            start=start,
            end=end,
            retrieved_at=retrieved_at,
            concepts=list(config.get("esef_concepts") or []),
        )
    if source == "alpha_vantage":
        return AlphaVantageEstimatesProvider(client).fetch(
            job,
            retrieved_at=retrieved_at,
            api_key=os.environ.get("ALPHA_VANTAGE_API_KEY", ""),
            field_map=dict(config.get("alpha_vantage_field_map") or {}),
        )
    raise ValueError(f"未实现 supplemental source：{source}")


def _resolve_sec_ciks(
    jobs: list[dict[str, Any]],
    client: HttpClient,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    missing = [job for job in jobs if pd.isna(job.get("CIK"))]
    if not missing:
        return jobs, {"resolved": 0, "unresolved": 0}
    ticker_map, payload = SecCompanyFactsProvider(client).ticker_map()
    _write_raw_payload("sec_companyfacts", "company_tickers", payload)
    resolved = 0
    output: list[dict[str, Any]] = []
    for job in jobs:
        item = dict(job)
        if pd.isna(item.get("CIK")):
            symbol = str(item.get("Symbol") or "").upper().replace(".", "-")
            item["CIK"] = ticker_map.get(symbol)
        if item.get("CIK"):
            resolved += 1
            output.append(item)
    return output, {"resolved": resolved, "unresolved": len(jobs) - len(output)}


def _load_normalized_family(family: str) -> pd.DataFrame:
    paths = sorted((SUPPLEMENTAL_NORMALIZED_DIR / family).glob("*/*.parquet"))
    if not paths:
        return pd.DataFrame(columns=FAMILY_REQUIRED_COLUMNS[family])
    return pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)


def _screen_columns_for_qa(field_mappings: Mapping[str, Mapping[str, Any]]) -> list[str]:
    columns = ["Date", *CORE_WEIGHT_COLUMNS]
    columns.extend(
        str(mapping["reference_screen_column"])
        for mapping in field_mappings.values()
        if mapping.get("reference_screen_column")
    )
    return list(dict.fromkeys(columns))


def _expand_field_mappings(
    config: Mapping[str, Any],
    resolved_security: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    mappings = {
        str(field): dict(mapping)
        for field, mapping in (config.get("field_mappings") or {}).items()
    }
    fields = set(resolved_security.get("field", pd.Series(dtype="string")).dropna().astype(str))
    for pattern_mapping in config.get("field_mapping_patterns") or []:
        pattern = re.compile(str(pattern_mapping["pattern"]))
        mapping = {key: value for key, value in pattern_mapping.items() if key != "pattern"}
        for field in fields:
            if pattern.search(field):
                mappings.setdefault(field, dict(mapping))
    return mappings


def _materialize_outputs(
    config: Mapping[str, Any],
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    candidate_isins: set[str],
    holding_isins: set[str],
) -> dict[str, Any]:
    date_frame = pd.read_parquet(SCREEN_AGGREGATE_PATH, columns=["Date"])
    month_ends = pd.to_datetime(date_frame["Date"], errors="coerce").dropna()
    month_ends = month_ends.loc[(month_ends >= start) & (month_ends <= end)].unique()
    source_priority = config.get("source_priority") or {}

    macro = materialize_point_in_time(
        _load_normalized_family("macro"), "macro", month_ends, source_priority
    )
    fundamental = materialize_point_in_time(
        _load_normalized_family("fundamental"), "fundamental", month_ends, source_priority
    )
    estimate = materialize_point_in_time(
        _load_normalized_family("estimate"), "estimate", month_ends, source_priority
    )
    security_frames = [frame for frame in (fundamental, estimate) if not frame.empty]
    security = pd.concat(security_frames, ignore_index=True) if security_frames else pd.DataFrame()

    macro_path = SUPPLEMENTAL_RESOLVED_DIR / "macro_values_latest.parquet"
    security_path = SUPPLEMENTAL_RESOLVED_DIR / "security_values_latest.parquet"
    if not macro.empty:
        _atomic_write_parquet(macro_path, macro)
    if not security.empty:
        _atomic_write_parquet(security_path, security)

    field_mappings = _expand_field_mappings(config, security)
    qa_columns = _screen_columns_for_qa(field_mappings)
    available_columns = set(pq.read_schema(SCREEN_AGGREGATE_PATH).names)
    qa_columns = [column for column in qa_columns if column in available_columns]
    if "ISIN" in available_columns and "ISIN" not in qa_columns:
        qa_columns.append("ISIN")
    screen = ensure_isin_column(
        pd.read_parquet(SCREEN_AGGREGATE_PATH, columns=qa_columns)
    )
    screen["Date"] = pd.to_datetime(screen["Date"], errors="coerce")
    screen = screen.loc[screen["Date"].between(start, end)].copy()
    sidecar = build_shadow_sidecar(screen, security, field_mappings)
    sidecar_path = SUPPLEMENTAL_RESOLVED_DIR / "screen_sidecar_latest.parquet"
    if not sidecar.empty:
        _atomic_write_parquet(sidecar_path, sidecar)

    coverage = coverage_by_market_field_year(
        screen,
        sidecar,
        field_mappings,
        candidate_isins=candidate_isins,
        holding_isins=holding_isins,
    )
    coverage_path = SUPPLEMENTAL_QA_DIR / "coverage_latest.csv"
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(coverage_path, index=False, encoding="utf-8-sig")

    acceptance = config.get("acceptance_gate") or {}
    provider_gates: list[dict[str, Any]] = []
    for source in sorted(set(sidecar.get("auto_source", pd.Series(dtype="string")).dropna().astype(str))):
        source_coverage = coverage_by_market_field_year(
            screen,
            sidecar,
            field_mappings,
            candidate_isins=candidate_isins,
            holding_isins=holding_isins,
            source=source,
        )
        provider_gates.append(
            provider_acceptance_gate(
                source_coverage,
                sidecar,
                source,
                min_coverage_uplift=float(acceptance.get("min_coverage_uplift") or 0.15),
                min_consistency=float(acceptance.get("min_consistency") or 0.90),
            )
        )
    gate_path = SUPPLEMENTAL_QA_DIR / "provider_gate_latest.json"
    atomic_write_json(
        gate_path,
        {
            "definition": "各 market × field 的 ALL 年份覆盖率等权平均",
            "providers": provider_gates,
            "paid_candidates": config.get("paid_candidates") or [],
        },
    )

    macro_validation = validate_resolved_values(macro, "series_id")
    security_validation = validate_resolved_values(security, "ISIN")
    has_resolved_rows = bool(macro_validation["rows"] or security_validation["rows"])
    structural_passed = bool(
        has_resolved_rows and macro_validation["ok"] and security_validation["ok"]
    )
    period = pd.Timestamp(max(month_ends)).to_period("M") if len(month_ends) else end.to_period("M")
    period_path = SUPPLEMENTAL_QA_DIR / "period_status" / f"{period.strftime('%Y%m')}.json"
    atomic_write_json(
        period_path,
        {
            "period": str(period),
            "passed": structural_passed,
            "macro_validation": macro_validation,
            "security_validation": security_validation,
            "provider_gates": provider_gates,
            "config_hash": _hash(config),
        },
    )
    return {
        "macro_path": macro_path if macro_path.exists() else None,
        "security_path": security_path if security_path.exists() else None,
        "sidecar_path": sidecar_path if sidecar_path.exists() else None,
        "coverage_path": coverage_path,
        "gate_path": gate_path,
        "period_path": period_path,
        "macro_validation": macro_validation,
        "security_validation": security_validation,
        "field_mappings": field_mappings,
        "sidecar": sidecar,
    }


def _promotion_periods(
    config_hash: str,
    required_periods: int,
    required_sources: set[str],
) -> list[dict[str, Any]]:
    paths = sorted((SUPPLEMENTAL_QA_DIR / "period_status").glob("*.json"))
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    eligible = [
        payload
        for payload in payloads
        if payload.get("passed") and payload.get("config_hash") == config_hash
    ]
    latest = eligible[-required_periods:]
    if len(latest) != required_periods:
        return []
    periods = [pd.Period(payload["period"], freq="M") for payload in latest]
    if any(right.ordinal - left.ordinal != 1 for left, right in zip(periods, periods[1:])):
        return []
    for payload in latest:
        gates = {
            str(gate.get("source")): bool(gate.get("passed"))
            for gate in payload.get("provider_gates") or []
        }
        if any(not gates.get(source, False) for source in required_sources):
            return []
    return latest


def _promote_to_canonical(
    sidecar: pd.DataFrame,
    field_mappings: Mapping[str, Mapping[str, Any]],
    *,
    config_hash: str,
    required_periods: int,
) -> dict[str, Any]:
    enabled = {
        field: mapping
        for field, mapping in field_mappings.items()
        if mapping.get("promote_enabled") and mapping.get("promote_to_screen_column")
    }
    if not enabled:
        raise RuntimeError("配置中没有 promote_enabled=true 的字段")
    required_sources = set(
        sidecar.loc[
            sidecar["field"].isin(enabled) & sidecar["valid_auto"].fillna(False),
            "auto_source",
        ]
        .dropna()
        .astype(str)
    )
    if not required_sources:
        raise RuntimeError("没有可 promotion 的有效自动来源")
    periods = _promotion_periods(config_hash, required_periods, required_sources)
    if not periods:
        raise RuntimeError(
            f"尚未满足连续 {required_periods} 个影子周期结构 QA 与供应商门槛"
        )

    original_screen = pd.read_parquet(SCREEN_AGGREGATE_PATH)
    isin_was_index = (
        original_screen.index.name == "ISIN" and "ISIN" not in original_screen.columns
    )
    screen = ensure_isin_column(original_screen)
    screen["Date"] = pd.to_datetime(screen["Date"], errors="coerce").dt.to_period("M").dt.to_timestamp("M")
    before_contract = validate_screen_contract(screen)
    before_rows = len(screen)
    promoted_cells: dict[str, int] = {}
    for field, mapping in enabled.items():
        target = str(mapping["promote_to_screen_column"])
        values = sidecar.loc[
            sidecar["field"].eq(field) & sidecar["valid_auto"].fillna(False),
            ["ISIN", "Date", "auto_value"],
        ].drop_duplicates(["ISIN", "Date"], keep="last")
        values = values.rename(columns={"auto_value": "_supplemental"})
        screen = screen.merge(values, on=["ISIN", "Date"], how="left", validate="one_to_one")
        if target in screen.columns:
            missing_before = pd.to_numeric(screen[target], errors="coerce").isna()
            screen.loc[missing_before, target] = screen.loc[missing_before, "_supplemental"]
            promoted_cells[target] = int((missing_before & screen["_supplemental"].notna()).sum())
        else:
            screen[target] = screen["_supplemental"]
            promoted_cells[target] = int(screen[target].notna().sum())
        screen = screen.drop(columns="_supplemental")

    after_contract = validate_screen_contract(screen)
    if len(screen) != before_rows or not before_contract["ok"] or not after_contract["ok"]:
        raise RuntimeError("promotion 未保持 canonical screen 行数或主键契约")
    output_screen = screen.set_index("ISIN") if isin_was_index else screen
    _atomic_write_parquet(SCREEN_AGGREGATE_PATH, output_screen, index=isin_was_index)
    return {
        "qa_periods": [payload["period"] for payload in periods],
        "promoted_cells": promoted_cells,
        "rows": before_rows,
    }


def _inspect_existing() -> dict[str, Any]:
    families: dict[str, Any] = {}
    for family in FAMILY_REQUIRED_COLUMNS:
        paths = sorted((SUPPLEMENTAL_NORMALIZED_DIR / family).glob("*/*.parquet"))
        families[family] = {
            "partitions": len(paths),
            "rows": int(sum(len(pd.read_parquet(path, columns=["value"])) for path in paths)),
        }
    return {
        "families": families,
        "resolved": {
            "macro": path_profile(SUPPLEMENTAL_RESOLVED_DIR / "macro_values_latest.parquet", parquet=True),
            "security": path_profile(
                SUPPLEMENTAL_RESOLVED_DIR / "security_values_latest.parquet", parquet=True
            ),
            "sidecar": path_profile(
                SUPPLEMENTAL_RESOLVED_DIR / "screen_sidecar_latest.parquet", parquet=True
            ),
        },
    }


def run_refresh_supplemental_data(args: argparse.Namespace) -> Path:
    parameters = vars(args).copy()
    manifest = StepManifest("refresh_supplemental_data", parameters)
    config_path = Path(getattr(args, "config", DEFAULT_CONFIG))
    security_map_path = Path(getattr(args, "security_map", DEFAULT_SECURITY_MAP))
    start = pd.Timestamp(getattr(args, "from_date", None) or "2000-01-01").normalize()
    end = pd.Timestamp(getattr(args, "to_date", None) or pd.Timestamp.utcnow()).tz_localize(None).normalize()
    sources = list(dict.fromkeys(getattr(args, "source", None) or []))
    dry_run = bool(getattr(args, "dry_run", False))
    inspect_only = bool(getattr(args, "inspect_only", False))
    resume = bool(getattr(args, "resume", False))
    timeout_seconds = int(getattr(args, "timeout_seconds", 30))
    max_jobs = getattr(args, "max_jobs", None)
    promote = bool(getattr(args, "promote_to_canonical", False))

    manifest.inputs = {
        "config": path_profile(config_path),
        "security_map": path_profile(security_map_path),
        "canonical_screen": path_profile(SCREEN_AGGREGATE_PATH, parquet=True),
        "last_screen": path_profile(LAST_SCREEN_PATH, parquet=True),
    }
    try:
        config = _load_config(config_path)
        if start > end:
            raise ValueError("from-date 不能晚于 to-date")
        if inspect_only:
            manifest.details["inspect"] = _inspect_existing()
            manifest.add_validation("network_skipped", True, "inspect-only 未访问外部 API")
            return manifest.write("success")
        if not sources:
            raise ValueError("必须至少指定一个 --source；补充数据阶段不会隐式访问外部 API")

        securities, candidate_isins, holding_isins = _load_security_map(
            security_map_path,
            write_template=not dry_run,
        )
        plans = {
            source: _jobs_for_source(source, config, securities, max_jobs)
            for source in sources
        }
        manifest.details["job_plan"] = {
            source: {"jobs": len(jobs), "sample": [_job_key(source, job) for job in jobs[:5]]}
            for source, jobs in plans.items()
        }
        manifest.add_validation(
            "jobs_available",
            all(bool(jobs) for jobs in plans.values()),
            "所有指定来源均生成了 job" if all(plans.values()) else "至少一个来源没有可执行 job",
        )
        if any(not jobs for jobs in plans.values()):
            raise ValueError("指定来源没有可执行 job；检查 enabled 配置或证券 CIK/LEI/Symbol 映射")
        if dry_run:
            manifest.add_validation("network_skipped", True, "dry-run 未访问外部 API")
            manifest.add_validation("canonical_unchanged", True, "dry-run 未写补充数据或 canonical")
            return manifest.write("success")

        config_hash = _hash(config)
        run_results: list[dict[str, Any]] = []
        for source, jobs in plans.items():
            client = _client_for_source(source, config, timeout_seconds)
            if source == "sec":
                jobs, cik_result = _resolve_sec_ciks(jobs, client)
                manifest.details["sec_cik_resolution"] = cik_result
                if not jobs:
                    raise ValueError("SEC ticker 映射后没有可执行 CIK")
            signature = _hash(
                {
                    "source": source,
                    "from": str(start.date()),
                    "to": str(end.date()),
                    "config_hash": config_hash,
                    "jobs": [_job_key(source, job) for job in jobs],
                }
            )
            checkpoint_path = _checkpoint_path(source)
            completed = _load_completed(checkpoint_path, signature, resume)
            for job in jobs:
                key = _job_key(source, job)
                if key in completed:
                    run_results.append({"job_key": key, "status": "resume_skipped"})
                    continue
                retrieved_at = pd.Timestamp.utcnow().tz_localize(None)
                batch = _fetch_batch(
                    source,
                    job,
                    config,
                    client,
                    start=start,
                    end=end,
                    retrieved_at=retrieved_at,
                )
                result = _persist_batch(batch)
                result["status"] = "success"
                run_results.append(result)
                completed.add(key)
                _write_checkpoint(checkpoint_path, signature, completed)

        outputs = _materialize_outputs(
            config,
            start,
            end,
            candidate_isins=candidate_isins,
            holding_isins=holding_isins,
        )
        manifest.details["jobs"] = run_results
        manifest.details["macro_validation"] = outputs["macro_validation"]
        manifest.details["security_validation"] = outputs["security_validation"]
        manifest.outputs = {
            name: path_profile(path, parquet=str(path).endswith(".parquet"))
            for name, path in {
                "macro_resolved": outputs["macro_path"],
                "security_resolved": outputs["security_path"],
                "screen_sidecar": outputs["sidecar_path"],
                "coverage": outputs["coverage_path"],
                "provider_gate": outputs["gate_path"],
                "period_status": outputs["period_path"],
            }.items()
            if path is not None
        }
        manifest.add_validation(
            "resolved_values_structural_qa",
            outputs["macro_validation"]["ok"] and outputs["security_validation"]["ok"],
            "resolved 数据通过唯一性、元数据和无前视检查",
        )
        if not promote:
            manifest.add_validation("canonical_unchanged", True, "默认影子运行未改写 canonical")
        if promote:
            acceptance = config.get("acceptance_gate") or {}
            promotion = _promote_to_canonical(
                outputs["sidecar"],
                outputs["field_mappings"],
                config_hash=config_hash,
                required_periods=int(acceptance.get("required_shadow_periods") or 3),
            )
            manifest.details["promotion"] = promotion
            manifest.add_validation(
                "canonical_promotion_guard_passed",
                True,
                "已通过影子周期 promotion gate，并仅补 canonical 空值",
            )
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新 TP point-in-time 影子补充数据")
    parser.add_argument("--source", action="append", choices=SOURCE_CHOICES, help="数据来源，可重复")
    parser.add_argument("--from-date", default="2000-01-01")
    parser.add_argument("--to-date")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--security-map", default=str(DEFAULT_SECURITY_MAP))
    parser.add_argument("--max-jobs", type=int, help="本次每个来源最多执行的 job 数")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--promote-to-canonical", action="store_true")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    manifest_path = run_refresh_supplemental_data(args)
    print(f"refresh_supplemental_data manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
