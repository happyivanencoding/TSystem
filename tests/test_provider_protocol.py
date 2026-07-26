from __future__ import annotations

from datetime import datetime

import pytest

from tp_data.providers import (
    MacroStandardModel,
    ProviderContext,
    ProviderQuery,
    ProviderRegistry,
    ProviderResult,
)


class FakeProvider:
    provider_id = "fake"
    standard_model = MacroStandardModel

    def fetch(self, query, context):
        record = MacroStandardModel(
            source="fake",
            field="GDP",
            value=1.2,
            available_at=context.retrieved_at,
            retrieved_at=context.retrieved_at,
            unit="percent",
            series_id="GDP",
            observation_date=datetime(2025, 12, 31),
            vintage_at=context.retrieved_at,
        )
        return ProviderResult("macro", "fake", "GDP", (record,), {"raw": True})


def test_registry_resolves_standard_model_provider() -> None:
    registry = ProviderRegistry()
    registry.register(FakeProvider())
    now = datetime(2026, 1, 15)

    result = registry.fetch(
        ProviderQuery(source="fake", job={}),
        ProviderContext(retrieved_at=now),
    )

    assert result.records[0].series_id == "GDP"
    assert registry.describe() == [
        {"provider_id": "fake", "standard_model": "MacroStandardModel"}
    ]
    assert result.layer == "normalized_shadow"


def test_provider_cannot_claim_canonical_layer() -> None:
    with pytest.raises(ValueError, match="raw/normalized/shadow"):
        ProviderResult("macro", "fake", "GDP", (), {}, layer="canonical")
