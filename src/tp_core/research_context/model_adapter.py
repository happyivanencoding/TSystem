"""Minimal model adapters for qualitative report inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd


class ModelAdapter(Protocol):
    def load_rows(self) -> list[dict[str, object]]:
        """Return model rows normalized enough for qualitative workflows."""


@dataclass(frozen=True)
class LatestCsvSpec:
    market: str
    path: Path


@dataclass(frozen=True)
class LatestCsvModelAdapter:
    specs: tuple[LatestCsvSpec, ...]
    date_column: str = "Date"

    def load_rows(self) -> list[dict[str, object]]:
        frames: list[pd.DataFrame] = []
        for spec in self.specs:
            if not spec.path.exists():
                continue
            frame = pd.read_csv(spec.path, encoding="utf-8-sig")
            frame["market"] = spec.market
            frames.append(frame)
        if not frames:
            paths = ", ".join(str(spec.path) for spec in self.specs)
            raise FileNotFoundError(f"No latest model CSV files found: {paths}")
        latest = pd.concat(frames, ignore_index=True)
        if self.date_column in latest.columns:
            latest[self.date_column] = pd.to_datetime(latest[self.date_column], errors="coerce")
        return latest.to_dict(orient="records")


@dataclass(frozen=True)
class CountryModelAdapter:
    path: Path

    def load_rows(self) -> list[dict[str, object]]:
        rows = LatestCsvModelAdapter((LatestCsvSpec("GLOBAL", self.path),)).load_rows()
        for row in rows:
            row["model_region"] = str(row.get("country", ""))
            row["model_subject"] = str(row.get("country_label") or row.get("country") or "")
            row["model_view"] = str(row.get("recommendation", "Neutral"))
        return rows


@dataclass(frozen=True)
class CompanyAnalysisCsvAdapter:
    path: Path
    company_column: str = "Name"
    region_column: str = "COUNTRY"
    view_column: str = "recommendation"

    def load_rows(self) -> list[dict[str, object]]:
        rows = LatestCsvModelAdapter((LatestCsvSpec("COMPANY", self.path),)).load_rows()
        for row in rows:
            row["model_region"] = str(row.get(self.region_column, ""))
            row["model_subject"] = str(row.get(self.company_column, ""))
            row["model_view"] = str(row.get(self.view_column, "Neutral"))
        return rows
