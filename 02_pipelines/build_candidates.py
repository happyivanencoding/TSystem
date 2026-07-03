"""从统一信号表生成标准候选池。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

from presentation_layer import PresentationDataRepository
from tp_core.data_sources import LAST_SCREEN_PATH, TP_ROOT

from .common import CANDIDATES_DIR, StepManifest, latest_on_or_before, path_profile, summarize_frame


DEFAULT_OUTPUT = CANDIDATES_DIR / "latest_candidates.parquet"
SCREEN_COLUMNS = [
    "Company SEDOL",
    "ISIN",
    "Company Name",
    "Name",
    "Exchange Country Region",
    "Exchange Country Name",
    "FactSet Ind",
    "FactSet Sector",
    "Weight in STOXX EUROPE 600",
    "Weight in SP500",
    "Weight in MSCI WORLD",
]


def _security_signals(repo: PresentationDataRepository, as_of: str | None) -> pd.DataFrame:
    signals = repo.signals()
    signals = signals[signals["scope"].eq("security")].copy()
    if as_of:
        signals = signals[pd.to_datetime(signals["Date"], errors="coerce") <= pd.Timestamp(as_of)].copy()
    if signals.empty:
        raise ValueError("没有可用的证券级信号")
    return signals


def _latest_family(signals: pd.DataFrame, family: str, as_of: str | None) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    subset = signals[signals["signal_family"].eq(family)].copy()
    if subset.empty:
        return subset, None
    latest_date = latest_on_or_before(subset, as_of)
    subset = subset[pd.to_datetime(subset["Date"], errors="coerce").eq(latest_date)].copy()
    return subset, latest_date


def _score_pct(frame: pd.DataFrame) -> pd.Series:
    score_pct = pd.to_numeric(frame["score_pct"], errors="coerce")
    if score_pct.notna().any():
        return score_pct
    return pd.to_numeric(frame["score"], errors="coerce").rank(pct=True)


def _ml_component(signals: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame(columns=["Company SEDOL", "ml_score_pct"])
    frame = signals[signals["signal_name"].eq("score_ml")].copy()
    if frame.empty:
        frame = signals.copy()
    frame["ml_score_pct"] = _score_pct(frame)
    return frame.groupby("Company SEDOL", as_index=False)["ml_score_pct"].mean()


def _technical_component(signals: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame(columns=["Company SEDOL", "technical_score_pct", "technical_signal_count"])
    frame = signals.copy()
    frame["component_score_pct"] = _score_pct(frame)
    grouped = frame.groupby("Company SEDOL", as_index=False).agg(
        technical_score_pct=("component_score_pct", "mean"),
        technical_signal_count=("signal_name", "nunique"),
    )
    return grouped


def _screen_snapshot(repo: PresentationDataRepository) -> pd.DataFrame:
    screen = repo.screen(last_only=True).copy()
    if "Company SEDOL" not in screen.columns and screen.index.name == "Company SEDOL":
        screen = screen.reset_index()
    keep = [column for column in SCREEN_COLUMNS if column in screen.columns]
    if "Company SEDOL" not in keep:
        keep.insert(0, "Company SEDOL")
    return screen[keep].drop_duplicates(subset=["Company SEDOL"], keep="first")


def _rank_and_select(candidates: pd.DataFrame, *, top_n: int | None, top_pct: float, by_region: bool) -> pd.DataFrame:
    result = candidates.copy()
    group_cols = ["region"] if by_region and "region" in result.columns else []
    if group_cols:
        result["rank"] = result.groupby(group_cols)["composite_score"].rank(method="first", ascending=False)
        result["rank_pct"] = result.groupby(group_cols)["composite_score"].rank(method="max", pct=True)
    else:
        result["rank"] = result["composite_score"].rank(method="first", ascending=False)
        result["rank_pct"] = result["composite_score"].rank(method="max", pct=True)

    if top_n is not None:
        result["selected"] = result["rank"].le(top_n)
    else:
        threshold = max(0.0, min(1.0, float(top_pct)))
        if group_cols:
            counts = result.groupby(group_cols)["Company SEDOL"].transform("count")
            min_rank = (counts * threshold).round().clip(lower=1)
            result["selected"] = result["rank"].le(min_rank)
        else:
            min_rank = max(1, round(len(result) * threshold))
            result["selected"] = result["rank"].le(min_rank)
    return result.sort_values(["selected", "rank"], ascending=[False, True])


def build_candidates(
    *,
    as_of: str | None,
    output: Path,
    top_n: int | None,
    top_pct: float,
    ml_weight: float,
    technical_weight: float,
    by_region: bool,
) -> pd.DataFrame:
    repo = PresentationDataRepository()
    signals = _security_signals(repo, as_of)
    ml_signals, ml_date = _latest_family(signals, "ML", as_of)
    technical_signals, technical_date = _latest_family(signals, "Technical", as_of)

    ml = _ml_component(ml_signals)
    technical = _technical_component(technical_signals)
    candidates = pd.merge(ml, technical, on="Company SEDOL", how="outer")
    if candidates.empty:
        raise ValueError("ML 和技术信号没有生成任何候选证券")

    weights = []
    weighted = pd.Series(0.0, index=candidates.index)
    denominator = pd.Series(0.0, index=candidates.index)
    if "ml_score_pct" in candidates.columns:
        ml_available = candidates["ml_score_pct"].notna()
        weighted = weighted.add(candidates["ml_score_pct"].fillna(0.0) * ml_weight)
        denominator = denominator.add(ml_available.astype(float) * ml_weight)
        weights.append({"component": "ml_score_pct", "weight": ml_weight})
    if "technical_score_pct" in candidates.columns:
        technical_available = candidates["technical_score_pct"].notna()
        weighted = weighted.add(candidates["technical_score_pct"].fillna(0.0) * technical_weight)
        denominator = denominator.add(technical_available.astype(float) * technical_weight)
        weights.append({"component": "technical_score_pct", "weight": technical_weight})
    candidates["composite_score"] = weighted.div(denominator.replace(0.0, pd.NA))
    candidates = candidates[candidates["composite_score"].notna()].copy()

    screen = _screen_snapshot(repo)
    candidates = candidates.merge(screen, on="Company SEDOL", how="left")
    candidates["region"] = candidates.get("Exchange Country Region")
    candidates["candidate_date"] = pd.Timestamp(as_of) if as_of else max(date for date in [ml_date, technical_date] if date is not None)
    candidates["signal_date_ml"] = ml_date
    candidates["signal_date_technical"] = technical_date
    candidates["candidate_model_version"] = "candidate_composite_v1"
    candidates["component_weights"] = str(weights)

    candidates = _rank_and_select(candidates, top_n=top_n, top_pct=top_pct, by_region=by_region)
    output.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_parquet(output, index=False)
    return candidates


def run_build_candidates(args: argparse.Namespace) -> Path:
    manifest = StepManifest("build_candidates", vars(args).copy())
    manifest.inputs = {
        "signals_dir": path_profile(Path(args.signals_dir)),
        "last_screen": path_profile(Path(args.last_screen), parquet=True),
    }
    try:
        frame = build_candidates(
            as_of=args.as_of,
            output=Path(args.output),
            top_n=args.top_n,
            top_pct=args.top_pct,
            ml_weight=args.ml_weight,
            technical_weight=args.technical_weight,
            by_region=args.by_region,
        )
        duplicate_count = int(frame.duplicated(subset=["candidate_date", "Company SEDOL"], keep=False).sum())
        selected_count = int(frame["selected"].sum())
        manifest.outputs = {"candidates": path_profile(args.output, parquet=True)}
        manifest.details["candidate_summary"] = summarize_frame(frame, date_column="candidate_date")
        manifest.add_validation("candidate_table_non_empty", not frame.empty, "候选池非空")
        manifest.add_validation("candidate_keys_unique", duplicate_count == 0, "候选池主键无重复", {"duplicate_rows": duplicate_count})
        manifest.add_validation("selected_candidates_non_empty", selected_count > 0, "入选候选证券非空", {"selected_count": selected_count})
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从统一信号表生成候选池")
    parser.add_argument("--as-of", help="目标日期；默认使用各信号最新日期")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="候选池 parquet 输出路径")
    parser.add_argument("--top-n", type=int, help="选择前 N 名；传入后优先于 top-pct")
    parser.add_argument("--top-pct", type=float, default=0.10, help="默认选择前 10%%")
    parser.add_argument("--ml-weight", type=float, default=0.70, help="ML 分数组合权重")
    parser.add_argument("--technical-weight", type=float, default=0.30, help="技术分数组合权重")
    parser.add_argument("--by-region", action="store_true", help="按 region 分组选择候选")
    parser.add_argument("--signals-dir", default=str(TP_ROOT / "04_signals"), help="仅用于 manifest 记录")
    parser.add_argument("--last-screen", default=str(LAST_SCREEN_PATH), help="仅用于 manifest 记录")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest_path = run_build_candidates(args)
    print(f"build_candidates manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
