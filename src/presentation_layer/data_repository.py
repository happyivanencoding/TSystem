"""展示/报告层统一数据读取。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from tp_core.data_sources import SCREEN_AGGREGATE_PATH, TP_ROOT
from tp_core.io import read_last_screen, read_returns, read_screen_aggregate
from tp_core.signals import read_signal_frame, standardize_signal_frame


@dataclass
class PresentationDataRepository:
    """为展示、报告和公司分析提供统一数据入口。"""

    root: Path = TP_ROOT

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    @property
    def signals_dir(self) -> Path:
        return self.root / "artifacts" / "signals"

    def screen(self, *, last_only: bool = False) -> pd.DataFrame:
        """读取 screen 主表或最新截面。"""

        return read_last_screen() if last_only else read_screen_aggregate()

    def returns(self) -> pd.DataFrame:
        """读取 canonical returns。"""

        return read_returns()

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

        frame = self.screen(last_only=True).copy()
        if sedol is not None and "Company SEDOL" in frame.columns:
            frame = frame[frame["Company SEDOL"].astype(str).eq(str(sedol))].copy()
        if isin is not None:
            if "ISIN" in frame.columns:
                frame = frame[frame["ISIN"].astype(str).eq(str(isin))].copy()
            elif frame.index.name == "ISIN":
                frame = frame[frame.index.astype(str) == str(isin)].copy()
        return frame

    def company_history(self, isin: str) -> pd.DataFrame:
        """按 ISIN 读取单公司历史 screen 面板，供公司分析和报告层复用。"""

        frame = pd.read_parquet(SCREEN_AGGREGATE_PATH, filters=[("ISIN", "==", isin)])
        if frame.empty:
            return frame
        if "ISIN" not in frame.columns:
            frame = frame.reset_index()
        if "Date" in frame.columns:
            frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
            frame = frame.sort_values("Date")
        return frame.reset_index(drop=True)

