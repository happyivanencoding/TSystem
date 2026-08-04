"""Typed query specifications and safe identifier/value helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime


class QuerySpecError(ValueError):
    """Raised when a typed query cannot be represented safely."""


def quote_identifier(identifier: str) -> str:
    if not isinstance(identifier, str) or not identifier or "\x00" in identifier:
        raise QuerySpecError(f"invalid SQL identifier: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


def validate_relation_name(name: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise QuerySpecError(f"relation name is not whitelisted: {name!r}")
    return name


DateLike = date | datetime


@dataclass(frozen=True)
class ScreenQuery:
    columns: tuple[str, ...] = ()
    date_from: DateLike | None = None
    date_to: DateLike | None = None
    as_of: DateLike | None = None
    isins: tuple[str, ...] = ()
    sedols: tuple[str, ...] = ()
    benchmark: str | None = None
    positive_weight_only: bool = False
    countries: tuple[str, ...] = ()
    limit: int | None = None

    def __post_init__(self) -> None:
        _validate_dates(self.date_from, self.date_to)
        _validate_limit(self.limit)
        _validate_strings(self.isins, "isins")
        _validate_strings(self.sedols, "sedols")
        _validate_strings(self.countries, "countries")


@dataclass(frozen=True)
class ReturnsQuery:
    securities: tuple[str, ...] = ()
    date_from: DateLike | None = None
    date_to: DateLike | None = None
    preserve_wide: bool = True

    def __post_init__(self) -> None:
        _validate_dates(self.date_from, self.date_to)
        _validate_strings(self.securities, "securities")


@dataclass(frozen=True)
class SignalQuery:
    families: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    as_of: DateLike | None = None
    latest_only: bool = False

    def __post_init__(self) -> None:
        _validate_strings(self.families, "families")
        _validate_strings(self.names, "names")
        _validate_strings(self.scopes, "scopes")


def _validate_dates(date_from: DateLike | None, date_to: DateLike | None) -> None:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise QuerySpecError("date_from must not be after date_to")


def _validate_limit(limit: int | None) -> None:
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        raise QuerySpecError("limit must be a positive integer")


def _validate_strings(values: tuple[str, ...], field_name: str) -> None:
    if any(not isinstance(value, str) or not value for value in values):
        raise QuerySpecError(f"{field_name} must contain non-empty strings")


__all__ = [
    "QuerySpecError",
    "ReturnsQuery",
    "ScreenQuery",
    "SignalQuery",
    "quote_identifier",
    "validate_relation_name",
]
