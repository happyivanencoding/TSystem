"""Provider protocol and registry; no provider is allowed to mutate canonical data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, runtime_checkable

from .models import StandardModel


@dataclass(frozen=True)
class ProviderQuery:
    source: str
    job: Mapping[str, Any]
    start: datetime | None = None
    end: datetime | None = None
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderContext:
    retrieved_at: datetime
    credentials: Mapping[str, str] = field(default_factory=dict)
    transport: Any = None


@dataclass(frozen=True)
class ProviderResult:
    family: str
    source: str
    job_key: str
    records: tuple[StandardModel, ...]
    raw_payload: Any
    layer: str = "normalized_shadow"

    def __post_init__(self) -> None:
        if self.layer not in {"raw", "normalized_shadow", "shadow"}:
            raise ValueError("Provider 结果只能进入 raw/normalized/shadow 层")


@runtime_checkable
class Provider(Protocol):
    provider_id: str
    standard_model: type[StandardModel]

    def fetch(self, query: ProviderQuery, context: ProviderContext) -> ProviderResult: ...


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        if provider.provider_id in self._providers:
            raise ValueError(f"Provider 已注册：{provider.provider_id}")
        self._providers[provider.provider_id] = provider

    def resolve(self, provider_id: str) -> Provider:
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise KeyError(f"Provider 未注册：{provider_id}") from error

    def fetch(self, query: ProviderQuery, context: ProviderContext) -> ProviderResult:
        return self.resolve(query.source).fetch(query, context)

    def describe(self) -> list[dict[str, str]]:
        return [
            {
                "provider_id": provider_id,
                "standard_model": provider.standard_model.__name__,
            }
            for provider_id, provider in sorted(self._providers.items())
        ]


__all__ = [
    "Provider",
    "ProviderContext",
    "ProviderQuery",
    "ProviderRegistry",
    "ProviderResult",
]
