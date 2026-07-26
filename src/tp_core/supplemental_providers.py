"""TP 补充数据的官方公开来源适配器。

本模块只负责下载与标准化单个 job，不负责目录写入或 canonical 合并。
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .supplemental_data import (
    EstimateObservation,
    FundamentalFact,
    MacroObservation,
    records_frame,
)


@dataclass
class ProviderBatch:
    family: str
    source: str
    job_key: str
    records: pd.DataFrame
    raw_payload: Any


class HttpClient:
    """带明确 User-Agent、重试和最小请求间隔的轻量 HTTP 客户端。"""

    def __init__(
        self,
        *,
        timeout_seconds: int = 30,
        user_agent: str = "TP personal research",
        min_interval_seconds: float = 0.0,
        retries: int = 3,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self.retries = max(1, retries)
        self._last_request_at = 0.0

    def _wait_for_slot(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait_seconds = self.min_interval_seconds - elapsed
        if wait_seconds > 0:
            time.sleep(wait_seconds)

    def get_text(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> str:
        query = urlencode(
            {key: value for key, value in (params or {}).items() if value is not None},
            doseq=True,
        )
        target = f"{url}{'&' if '?' in url else '?'}{query}" if query else url
        request_headers = {"User-Agent": self.user_agent, **dict(headers or {})}
        last_error: BaseException | None = None
        for attempt in range(self.retries):
            self._wait_for_slot()
            try:
                request = Request(target, headers=request_headers)
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = response.read().decode("utf-8-sig")
                self._last_request_at = time.monotonic()
                return payload
            except (HTTPError, URLError, TimeoutError) as exc:
                self._last_request_at = time.monotonic()
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"HTTP 请求失败：{target}") from last_error

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        return json.loads(self.get_text(url, params=params, headers=headers))


def _as_timestamp(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize(None)


def _parse_period(value: Any) -> pd.Timestamp:
    text = str(value)
    quarter = re.fullmatch(r"(\d{4})-?Q([1-4])", text, re.IGNORECASE)
    if quarter:
        return pd.Period(f"{quarter.group(1)}Q{quarter.group(2)}", freq="Q").end_time.normalize()
    month = re.fullmatch(r"(\d{4})-?M(\d{1,2})", text, re.IGNORECASE)
    if month:
        return pd.Period(f"{month.group(1)}-{int(month.group(2)):02d}", freq="M").end_time.normalize()
    calendar_month = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if calendar_month:
        return pd.Period(text, freq="M").end_time.normalize()
    if re.fullmatch(r"\d{4}", text):
        return pd.Timestamp(f"{text}-12-31")
    return pd.Timestamp(text).tz_localize(None)


def _numeric(value: Any) -> float | None:
    if value in (None, "", ".", "NA", "N/A", "null"):
        return None
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if pd.notna(parsed) else None


class FredProvider:
    source = "fred"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(
        self,
        job: Mapping[str, Any],
        *,
        start: pd.Timestamp,
        end: pd.Timestamp,
        retrieved_at: pd.Timestamp,
        api_key: str,
    ) -> ProviderBatch:
        if not api_key:
            raise ValueError("FRED_API_KEY 未配置")
        series_id = str(job["series_id"])
        payload = self.client.get_json(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "observation_start": start.date().isoformat(),
                "observation_end": end.date().isoformat(),
                "realtime_start": start.date().isoformat(),
                "realtime_end": end.date().isoformat(),
                "output_type": 2,
                "limit": 100000,
            },
        )
        records: list[MacroObservation] = []
        for item in payload.get("observations", []):
            value = _numeric(item.get("value"))
            if value is None:
                continue
            vintage = _as_timestamp(item.get("realtime_start") or retrieved_at)
            records.append(
                MacroObservation(
                    series_id=series_id,
                    observation_date=_as_timestamp(item["date"]),
                    vintage_at=vintage,
                    source=self.source,
                    field=str(job.get("field") or series_id),
                    value=value,
                    available_at=vintage,
                    retrieved_at=retrieved_at,
                    unit=str(job.get("unit") or payload.get("units") or "unknown"),
                    currency=job.get("currency"),
                    availability_method="source_vintage",
                )
            )
        return ProviderBatch("macro", self.source, series_id, records_frame(records), payload)


class SdmxCsvProvider:
    """ECB/OECD 等官方 SDMX CSV 端点的配置驱动适配器。"""

    def __init__(self, source: str, client: HttpClient) -> None:
        self.source = source
        self.client = client

    def fetch(
        self,
        job: Mapping[str, Any],
        *,
        start: pd.Timestamp,
        end: pd.Timestamp,
        retrieved_at: pd.Timestamp,
    ) -> ProviderBatch:
        url = str(job["url"])
        text = self.client.get_text(
            url,
            params={
                str(job.get("start_parameter") or "startPeriod"): start.date().isoformat(),
                str(job.get("end_parameter") or "endPeriod"): end.date().isoformat(),
                **dict(job.get("parameters") or {}),
            },
            headers={"Accept": str(job.get("accept") or "text/csv")},
        )
        rows = list(csv.DictReader(io.StringIO(text)))
        date_column = str(job.get("date_column") or "TIME_PERIOD")
        value_column = str(job.get("value_column") or "OBS_VALUE")
        available_column = job.get("available_column")
        lag_days = int(job.get("publication_lag_days") or 0)
        records: list[MacroObservation] = []
        for row in rows:
            value = _numeric(row.get(value_column))
            if value is None or not row.get(date_column):
                continue
            observation_date = _parse_period(row[date_column])
            available_value = row.get(str(available_column)) if available_column else None
            if available_value:
                available_at = _as_timestamp(available_value)
                availability_method = "source_update"
            elif lag_days:
                available_at = observation_date + pd.Timedelta(days=lag_days)
                availability_method = "configured_conservative_lag"
            else:
                available_at = retrieved_at
                availability_method = "retrieval_only"
            records.append(
                MacroObservation(
                    series_id=str(job["series_id"]),
                    observation_date=observation_date,
                    vintage_at=available_at,
                    source=self.source,
                    field=str(job.get("field") or job["series_id"]),
                    value=value,
                    available_at=available_at,
                    retrieved_at=retrieved_at,
                    unit=str(job.get("unit") or row.get("UNIT") or "unknown"),
                    currency=job.get("currency"),
                    availability_method=availability_method,
                )
            )
        return ProviderBatch(
            "macro",
            self.source,
            str(job["series_id"]),
            records_frame(records),
            text,
        )


class WorldBankProvider:
    source = "world_bank"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(
        self,
        job: Mapping[str, Any],
        *,
        start: pd.Timestamp,
        end: pd.Timestamp,
        retrieved_at: pd.Timestamp,
    ) -> ProviderBatch:
        indicator = str(job["indicator"])
        countries = ";".join(job.get("countries") or ["all"])
        payload = self.client.get_json(
            f"https://api.worldbank.org/v2/country/{countries}/indicator/{indicator}",
            params={
                "format": "json",
                "per_page": 20000,
                "date": f"{start.year}:{end.year}",
            },
        )
        observations = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        lag_days = int(job.get("publication_lag_days") or 365)
        records: list[MacroObservation] = []
        for item in observations or []:
            value = _numeric(item.get("value"))
            if value is None:
                continue
            country = str(item.get("countryiso3code") or item.get("country", {}).get("id"))
            observation_date = _parse_period(item["date"])
            available_at = observation_date + pd.Timedelta(days=lag_days)
            series_id = f"WB:{indicator}:{country}"
            records.append(
                MacroObservation(
                    series_id=series_id,
                    observation_date=observation_date,
                    vintage_at=available_at,
                    source=self.source,
                    field=f"{job.get('field_prefix') or indicator}:{country}",
                    value=value,
                    available_at=available_at,
                    retrieved_at=retrieved_at,
                    unit=str(job.get("unit") or "unknown"),
                    currency=job.get("currency"),
                    availability_method="configured_conservative_lag",
                )
            )
        return ProviderBatch(
            "macro",
            self.source,
            f"{indicator}:{countries}",
            records_frame(records),
            payload,
        )


class ImfDataMapperProvider:
    source = "imf"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(
        self,
        job: Mapping[str, Any],
        *,
        start: pd.Timestamp,
        end: pd.Timestamp,
        retrieved_at: pd.Timestamp,
    ) -> ProviderBatch:
        indicator = str(job["indicator"])
        countries = list(job.get("countries") or [])
        suffix = "/".join([indicator, *countries])
        payload = self.client.get_json(f"https://www.imf.org/external/datamapper/api/v1/{suffix}")
        values = payload.get("values", {}).get(indicator, {})
        lag_days = int(job.get("publication_lag_days") or 365)
        records: list[MacroObservation] = []
        for country, annual_values in values.items():
            for year, raw_value in annual_values.items():
                if int(year) < start.year or int(year) > end.year:
                    continue
                value = _numeric(raw_value)
                if value is None:
                    continue
                observation_date = _parse_period(year)
                available_at = observation_date + pd.Timedelta(days=lag_days)
                records.append(
                    MacroObservation(
                        series_id=f"IMF:{indicator}:{country}",
                        observation_date=observation_date,
                        vintage_at=available_at,
                        source=self.source,
                        field=f"{job.get('field_prefix') or indicator}:{country}",
                        value=value,
                        available_at=available_at,
                        retrieved_at=retrieved_at,
                        unit=str(job.get("unit") or "unknown"),
                        currency=job.get("currency"),
                        availability_method="configured_conservative_lag",
                    )
                )
        return ProviderBatch(
            "macro",
            self.source,
            f"{indicator}:{','.join(countries)}",
            records_frame(records),
            payload,
        )


class DbnomicsSeriesProvider:
    """保留原始机构代码的 DBnomics 备用传输。"""

    source = "dbnomics"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(
        self,
        job: Mapping[str, Any],
        *,
        start: pd.Timestamp,
        end: pd.Timestamp,
        retrieved_at: pd.Timestamp,
        original_provider: str,
    ) -> ProviderBatch:
        provider_code = str(job["provider_code"])
        dataset_code = str(job["dataset_code"])
        countries = list(job.get("countries") or [])
        indicator = str(job["indicator"])
        payloads: dict[str, Any] = {}
        records: list[MacroObservation] = []
        for country in countries:
            series_code = str(
                job.get("series_code_template") or "{country}.{indicator}"
            ).format(country=country, indicator=indicator)
            payload = self.client.get_json(
                f"https://api.db.nomics.world/v22/series/"
                f"{provider_code}/{dataset_code}/{series_code}",
                params={"observations": 1},
            )
            payloads[country] = payload
            documents = payload.get("series", {}).get("docs", [])
            if not documents:
                continue
            document = documents[0]
            indexed_at = (
                payload.get("dataset", {}).get("indexed_at")
                or document.get("indexed_at")
                or retrieved_at
            )
            available_at = _as_timestamp(indexed_at)
            for period, raw_value in zip(
                document.get("period", []),
                document.get("value", []),
            ):
                observation_date = _parse_period(period)
                if observation_date < start or observation_date > end:
                    continue
                value = _numeric(raw_value)
                if value is None:
                    continue
                records.append(
                    MacroObservation(
                        series_id=f"{original_provider}:{indicator}:{country}",
                        observation_date=observation_date,
                        vintage_at=available_at,
                        source=self.source,
                        field=f"{job.get('field_prefix') or indicator}:{country}",
                        value=value,
                        available_at=available_at,
                        retrieved_at=retrieved_at,
                        unit=str(job.get("unit") or "unknown"),
                        currency=job.get("currency"),
                        availability_method="dbnomics_dataset_indexed_at",
                    )
                )
        return ProviderBatch(
            "macro",
            self.source,
            f"{original_provider}:{indicator}:{','.join(countries)}",
            records_frame(records),
            {
                "transport": "dbnomics",
                "original_provider": original_provider,
                "dataset_code": dataset_code,
                "responses": payloads,
            },
        )


class SecCompanyFactsProvider:
    source = "sec_companyfacts"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def ticker_map(self) -> tuple[dict[str, str], Any]:
        payload = self.client.get_json("https://www.sec.gov/files/company_tickers.json")
        mapping = {
            str(item["ticker"]).upper().replace(".", "-"): f"{int(item['cik_str']):010d}"
            for item in payload.values()
        }
        return mapping, payload

    def fetch(
        self,
        job: Mapping[str, Any],
        *,
        start: pd.Timestamp,
        end: pd.Timestamp,
        retrieved_at: pd.Timestamp,
        concepts: list[Mapping[str, Any]],
    ) -> ProviderBatch:
        cik = f"{int(str(job['CIK'])):010d}"
        payload = self.client.get_json(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        )
        facts = payload.get("facts", {})
        records: list[dict[str, Any]] = []
        for provider_priority, mapping in enumerate(concepts):
            taxonomy = str(mapping.get("taxonomy") or "us-gaap")
            concept = str(mapping["concept"])
            concept_data = facts.get(taxonomy, {}).get(concept, {})
            for unit, observations in concept_data.get("units", {}).items():
                for item in observations:
                    period_end = pd.to_datetime(item.get("end"), errors="coerce")
                    filed = pd.to_datetime(item.get("filed"), errors="coerce")
                    value = _numeric(item.get("val"))
                    if (
                        pd.isna(period_end)
                        or pd.isna(filed)
                        or value is None
                        or period_end < start
                        or period_end > end
                    ):
                        continue
                    if mapping.get("forms") and item.get("form") not in mapping["forms"]:
                        continue
                    currency = unit if re.fullmatch(r"[A-Z]{3}", str(unit)) else None
                    records.append(
                        {
                            **FundamentalFact(
                                ISIN=str(job["ISIN"]),
                                period_end=_as_timestamp(period_end),
                                available_at=_as_timestamp(filed),
                                source=self.source,
                                field=str(mapping["field"]),
                                value=value,
                                retrieved_at=retrieved_at,
                                unit=str(unit),
                                currency=currency or job.get("Currency"),
                                fiscal_period=item.get("fp"),
                                provider_field=f"{taxonomy}:{concept}",
                                availability_method="filing_date",
                            ).__dict__,
                            "provider_priority": provider_priority,
                            "accession": item.get("accn"),
                            "form": item.get("form"),
                        }
                    )
        return ProviderBatch(
            "fundamental",
            self.source,
            f"{job['ISIN']}:{cik}",
            pd.DataFrame(records),
            payload,
        )


def _xbrl_period_end(value: Any) -> pd.Timestamp | None:
    if not value:
        return None
    text = str(value)
    endpoint = text.split("/")[-1]
    parsed = pd.to_datetime(endpoint, errors="coerce")
    if pd.isna(parsed):
        return None
    timestamp = _as_timestamp(parsed)
    if "/" in text:
        timestamp -= timedelta(days=1)
    return timestamp.normalize()


class EsefFilingsProvider:
    source = "esef_filings"
    base_url = "https://filings.xbrl.org"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(
        self,
        job: Mapping[str, Any],
        *,
        start: pd.Timestamp,
        end: pd.Timestamp,
        retrieved_at: pd.Timestamp,
        concepts: list[Mapping[str, Any]],
    ) -> ProviderBatch:
        lei = str(job["LEI"])
        index_payload = self.client.get_json(
            f"{self.base_url}/api/entities/{lei}/filings",
            params={"page[size]": 200, "sort": "-processed"},
            headers={"Accept": "application/vnd.api+json"},
        )
        concept_map = {
            str(mapping["concept"]): (priority, mapping)
            for priority, mapping in enumerate(concepts)
        }
        filing_payloads: dict[str, Any] = {}
        records: list[dict[str, Any]] = []
        for filing in index_payload.get("data", []):
            attributes = filing.get("attributes", {})
            report_period = pd.to_datetime(attributes.get("period_end"), errors="coerce")
            if pd.isna(report_period) or report_period < start or report_period > end:
                continue
            json_url = attributes.get("json_url")
            if not json_url:
                continue
            document = self.client.get_json(f"{self.base_url}{json_url}")
            filing_payloads[str(filing.get("id"))] = document
            available_at = _as_timestamp(attributes.get("date_added") or retrieved_at)
            for fact_id, fact in document.get("facts", {}).items():
                dimensions = fact.get("dimensions", {})
                concept = dimensions.get("concept")
                if concept not in concept_map:
                    continue
                extra_dimensions = set(dimensions) - {"concept", "entity", "period", "unit"}
                if extra_dimensions:
                    continue
                value = _numeric(fact.get("value"))
                period_end = _xbrl_period_end(dimensions.get("period"))
                if value is None or period_end is None:
                    continue
                provider_priority, mapping = concept_map[concept]
                unit = str(dimensions.get("unit") or mapping.get("unit") or "unknown")
                currency_match = re.search(r"(?:iso4217:)?([A-Z]{3})$", unit)
                records.append(
                    {
                        **FundamentalFact(
                            ISIN=str(job["ISIN"]),
                            period_end=period_end,
                            available_at=available_at,
                            source=self.source,
                            field=str(mapping["field"]),
                            value=value,
                            retrieved_at=retrieved_at,
                            unit=unit,
                            currency=(
                                currency_match.group(1)
                                if currency_match
                                else job.get("Currency")
                            ),
                            fiscal_period=str(report_period.year),
                            provider_field=concept,
                            availability_method="repository_date_added",
                        ).__dict__,
                        "provider_priority": provider_priority,
                        "fact_id": fact_id,
                        "filing_id": filing.get("id"),
                    }
                )
        raw_payload = {"index": index_payload, "filings": filing_payloads}
        return ProviderBatch(
            "fundamental",
            self.source,
            f"{job['ISIN']}:{lei}",
            pd.DataFrame(records),
            raw_payload,
        )


class AlphaVantageEstimatesProvider:
    source = "alpha_vantage"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(
        self,
        job: Mapping[str, Any],
        *,
        retrieved_at: pd.Timestamp,
        api_key: str,
        field_map: Mapping[str, str],
    ) -> ProviderBatch:
        if not api_key:
            raise ValueError("ALPHA_VANTAGE_API_KEY 未配置")
        symbol = str(job["AlphaSymbol"])
        payload = self.client.get_json(
            "https://www.alphavantage.co/query",
            params={
                "function": "EARNINGS_ESTIMATES",
                "symbol": symbol,
                "apikey": api_key,
            },
        )
        for error_key in ("Error Message", "Information", "Note"):
            if payload.get(error_key):
                raise RuntimeError(f"Alpha Vantage：{payload[error_key]}")
        records: list[EstimateObservation] = []
        for estimate in payload.get("estimates", []):
            fiscal_period_end = pd.to_datetime(
                estimate.get("date") or estimate.get("fiscal_period_end"),
                errors="coerce",
            )
            if pd.isna(fiscal_period_end):
                continue
            horizon = str(estimate.get("horizon") or "unspecified")
            for provider_field, field in field_map.items():
                value = _numeric(estimate.get(provider_field))
                if value is None:
                    continue
                if "analyst_count" in provider_field:
                    unit = "count"
                    currency = None
                elif provider_field.startswith("eps_"):
                    unit = "currency_per_share"
                    currency = job.get("Currency")
                elif provider_field.startswith("revenue_"):
                    unit = "currency"
                    currency = job.get("Currency")
                else:
                    unit = "pure"
                    currency = None
                analyst_key = (
                    "eps_estimate_analyst_count"
                    if provider_field.startswith("eps_")
                    else "revenue_estimate_analyst_count"
                )
                records.append(
                    EstimateObservation(
                        ISIN=str(job["ISIN"]),
                        estimate_as_of=retrieved_at.normalize(),
                        fiscal_period_end=_as_timestamp(fiscal_period_end),
                        horizon=horizon,
                        available_at=retrieved_at,
                        source=self.source,
                        field=f"{field}__{horizon}",
                        value=value,
                        retrieved_at=retrieved_at,
                        unit=unit,
                        currency=currency,
                        analyst_count=_numeric(estimate.get(analyst_key)),
                        provider_field=provider_field,
                        availability_method="retrieval_snapshot",
                    )
                )
        return ProviderBatch(
            "estimate",
            self.source,
            f"{job['ISIN']}:{symbol}",
            records_frame(records),
            payload,
        )
