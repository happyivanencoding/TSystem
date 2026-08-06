"""展示/报告层统一数据读取。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from tp_core.analytics.config import DuckDBConfig
from tp_core.data_sources import TP_ROOT
from tp_core.io import read_last_screen, read_returns, read_screen_aggregate
from tp_core.signals import read_signal_frame, standardize_signal_frame


@dataclass
class PresentationDataRepository:
    """为展示、报告和公司分析提供统一数据入口。"""

    root: Path = TP_ROOT
    engine: str | None = None

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    @property
    def signals_dir(self) -> Path:
        return self.root / "artifacts" / "signals"

    @property
    def data_engine(self) -> str:
        return self.engine or DuckDBConfig.from_env().data_engine

    def screen(
        self,
        *,
        last_only: bool = False,
        columns: Iterable[str] | None = None,
        date_from: date | datetime | None = None,
        date_to: date | datetime | None = None,
    ) -> pd.DataFrame:
        """读取 screen 主表或最新截面。"""

        screen_path = self.root / "00_screen" / "screen_aggregate.parquet"
        if last_only:
            return read_last_screen(
                self.root / "00_screen" / "last_screen.parquet",
                columns=columns,
                engine=self.engine,
            )
        return read_screen_aggregate(
            screen_path,
            columns=columns,
            date_from=date_from,
            date_to=date_to,
            engine=self.engine,
        )

    def returns(
        self,
        *,
        columns: Iterable[str] | None = None,
        date_from: date | datetime | None = None,
        date_to: date | datetime | None = None,
    ) -> pd.DataFrame:
        """读取 canonical returns。"""

        return read_returns(
            self.root / "00_screen" / "returns.parquet",
            columns=columns,
            date_from=date_from,
            date_to=date_to,
            engine=self.engine,
        )

    def signal_path(self, name: str) -> Path:
        """返回 signals 目录下的 parquet 路径。"""

        return self.signals_dir / name

    def signals(self, *, family: str | None = None, names: Iterable[str] | None = None) -> pd.DataFrame:
        """读取所有已存在的统一信号表，可按 family/name 过滤。"""

        frames: list[pd.DataFrame] = []
        for path in sorted(self.signals_dir.glob("*.parquet")):
            frames.append(read_signal_frame(path))
        if not frames:
            return standardize_signal_frame(pd.DataFrame())
        result = pd.concat(frames, ignore_index=True)
        if family is not None:
            result = result[result["signal_family"].eq(family)].copy()
        if names is not None:
            allowed = set(names)
            result = result[result["signal_name"].isin(allowed)].copy()
        return standardize_signal_frame(result)

    def ml_signals(self) -> pd.DataFrame:
        return read_signal_frame(self.signal_path("ml_signals.parquet"))

    def technical_signals(self) -> pd.DataFrame:
        return read_signal_frame(self.signal_path("technical_signals.parquet"))

    def regime_risk_budget(self) -> pd.DataFrame:
        return read_signal_frame(self.signal_path("regime_risk_budget.parquet"))

    def latest_company_snapshot(self, sedol: str | None = None, isin: str | None = None) -> pd.DataFrame:
        """读取最新公司截面，可按 SEDOL 或 ISIN 过滤。"""

        if self.data_engine == "hybrid":
            # The immutable partition mirror preserves Arrow half-float values;
            # use the compatibility latest file for the all-column company payload.
            frame = read_last_screen(
                self.root / "00_screen" / "last_screen.parquet",
                engine="legacy_parquet",
            ).copy()
        else:
            frame = self.screen(last_only=True).copy()
        if sedol is not None and "Company SEDOL" in frame.columns:
            frame = frame[frame["Company SEDOL"].astype(str).eq(str(sedol))].copy()
        if isin is not None:
            if "ISIN" in frame.columns:
                frame = frame[frame["ISIN"].astype(str).eq(str(isin))].copy()
            elif frame.index.name == "ISIN":
                frame = frame[frame.index.astype(str) == str(isin)].copy()
        return frame

    def company_history(
        self,
        isin: str,
        *,
        date_from: date | datetime | None = None,
        date_to: date | datetime | None = None,
        columns: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        """按 ISIN 读取单公司历史 screen 面板，供公司分析和报告层复用。"""

        screen_path = self.root / "00_screen" / "screen_aggregate.parquet"
        if self.data_engine in {"duckdb", "hybrid", "shadow_compare"}:
            frame = read_screen_aggregate(
                screen_path,
                isins=(isin,),
                columns=columns,
                date_from=date_from,
                date_to=date_to,
                engine=self.engine,
            )
        else:
            filters: list[tuple[str, str, object]] = [("ISIN", "==", isin)]
            if date_from is not None:
                filters.append(("Date", ">=", pd.Timestamp(date_from)))
            if date_to is not None:
                filters.append(("Date", "<=", pd.Timestamp(date_to)))
            frame = pd.read_parquet(
                screen_path,
                columns=list(columns) if columns is not None else None,
                filters=filters,
            )
        if frame.empty:
            return frame
        if "ISIN" not in frame.columns:
            frame = frame.reset_index()
        if "ISIN" in frame.columns:
            frame = frame.loc[:, ["ISIN", *[column for column in frame.columns if column != "ISIN"]]]
        if self.data_engine == "hybrid" and columns is None:
            # Some legacy half-float fields were written as nulls in the existing
            # mirror. Rehydrate only the degraded columns from the read-only
            # compatibility export while retaining partition routing for the query.
            compatibility_filters: list[tuple[str, str, object]] = [("ISIN", "==", isin)]
            if date_from is not None:
                compatibility_filters.append(("Date", ">=", pd.Timestamp(date_from)))
            if date_to is not None:
                compatibility_filters.append(("Date", "<=", pd.Timestamp(date_to)))
            compatibility = pd.read_parquet(screen_path, filters=compatibility_filters)
            if compatibility.index.name == "ISIN":
                compatibility = compatibility.reset_index()
            if "ISIN" in compatibility.columns and "Date" in compatibility.columns:
                keys = ["ISIN", "Date"]
                frame_keys = frame.loc[:, keys].astype({"ISIN": str})
                compatible = compatibility.set_index(keys).reindex(
                    pd.MultiIndex.from_frame(frame_keys)
                )
                for column in frame.columns:
                    if column in keys or column not in compatible.columns:
                        continue
                    if not frame[column].reset_index(drop=True).equals(
                        compatible[column].reset_index(drop=True)
                    ):
                        frame[column] = compatible[column].to_numpy()
        if "Date" in frame.columns:
            frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
            frame = frame.sort_values("Date")
        return frame.reset_index(drop=True)

