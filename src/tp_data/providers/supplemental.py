"""Protocol adapters for the existing official supplemental data transports."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Mapping

import pandas as pd

from .adapters import (
    AlphaVantageEstimatesProvider,
    DbnomicsSeriesProvider,
    EsefFilingsProvider,
    FredProvider,
    ImfDataMapperProvider,
    ProviderBatch,
    SdmxCsvProvider,
    SecCompanyFactsProvider,
    WorldBankProvider,
)
from .models import (
    EstimateStandardModel,
    FundamentalStandardModel,
    MacroStandardModel,
    StandardModel,
)
from .protocol import ProviderContext, ProviderQuery, ProviderRegistry, ProviderResult

MODEL_BY_FAMILY: dict[str, type[StandardModel]] = {
    "macro": MacroStandardModel,
    "fundamental": FundamentalStandardModel,
    "estimate": EstimateStandardModel,
}


def _result(batch: ProviderBatch) -> ProviderResult:
    model = MODEL_BY_FAMILY[batch.family]
    records = tuple(
        model.model_validate(record)
        for record in batch.records.to_dict(orient="records")
    )
    return ProviderResult(
        family=batch.family,
        source=batch.source,
        job_key=batch.job_key,
        records=records,
        raw_payload=batch.raw_payload,
    )


def result_to_batch(result: ProviderResult) -> ProviderBatch:
    rows = []
    for record in result.records:
        row = record.model_dump()
        if not row.get("metadata"):
            row.pop("metadata", None)
        rows.append(row)
    return ProviderBatch(
        family=result.family,
        source=result.source,
        job_key=result.job_key,
        records=pd.DataFrame(rows),
        raw_payload=result.raw_payload,
    )


@dataclass
class SupplementalProtocolProvider:
    provider_id: str
    standard_model: type[StandardModel]
    config: Mapping[str, Any]

    def fetch(self, query: ProviderQuery, context: ProviderContext) -> ProviderResult:
        client = context.transport
        job = query.job
        start = pd.Timestamp(query.start)
        end = pd.Timestamp(query.end)
        retrieved_at = pd.Timestamp(context.retrieved_at)
        credentials = context.credentials
        if self.provider_id == "fred":
            batch = FredProvider(client).fetch(
                job,
                start=start,
                end=end,
                retrieved_at=retrieved_at,
                api_key=credentials.get("FRED_API_KEY", ""),
            )
        elif self.provider_id in {"ecb", "oecd"}:
            batch = SdmxCsvProvider(self.provider_id, client).fetch(
                job,
                start=start,
                end=end,
                retrieved_at=retrieved_at,
            )
        elif self.provider_id == "imf":
            batch = self._fetch_imf(job, client, start, end, retrieved_at)
        elif self.provider_id == "world_bank":
            batch = WorldBankProvider(client).fetch(
                job,
                start=start,
                end=end,
                retrieved_at=retrieved_at,
            )
        elif self.provider_id == "sec":
            batch = SecCompanyFactsProvider(client).fetch(
                job,
                start=start,
                end=end,
                retrieved_at=retrieved_at,
                concepts=list(self.config.get("sec_concepts") or []),
            )
        elif self.provider_id == "esef":
            batch = EsefFilingsProvider(client).fetch(
                job,
                start=start,
                end=end,
                retrieved_at=retrieved_at,
                concepts=list(self.config.get("esef_concepts") or []),
            )
        elif self.provider_id == "alpha_vantage":
            batch = AlphaVantageEstimatesProvider(client).fetch(
                job,
                retrieved_at=retrieved_at,
                api_key=credentials.get("ALPHA_VANTAGE_API_KEY", ""),
                field_map=dict(self.config.get("alpha_vantage_field_map") or {}),
            )
        else:
            raise KeyError(f"Provider 未实现：{self.provider_id}")
        return _result(batch)

    @staticmethod
    def _fetch_imf(job, client, start, end, retrieved_at) -> ProviderBatch:
        try:
            return ImfDataMapperProvider(client).fetch(
                job,
                start=start,
                end=end,
                retrieved_at=retrieved_at,
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


def build_supplemental_registry(config: Mapping[str, Any]) -> ProviderRegistry:
    registry = ProviderRegistry()
    for provider_id in ("fred", "ecb", "oecd", "imf", "world_bank"):
        registry.register(
            SupplementalProtocolProvider(provider_id, MacroStandardModel, config)
        )
    for provider_id in ("sec", "esef"):
        registry.register(
            SupplementalProtocolProvider(provider_id, FundamentalStandardModel, config)
        )
    registry.register(
        SupplementalProtocolProvider("alpha_vantage", EstimateStandardModel, config)
    )
    return registry


def environment_credentials() -> dict[str, str]:
    return {
        "FRED_API_KEY": os.environ.get("FRED_API_KEY", ""),
        "ALPHA_VANTAGE_API_KEY": os.environ.get("ALPHA_VANTAGE_API_KEY", ""),
    }


__all__ = [
    "SupplementalProtocolProvider",
    "build_supplemental_registry",
    "environment_credentials",
    "result_to_batch",
]
