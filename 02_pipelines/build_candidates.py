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
SECTOR_OUTPUTS = [
    ("US", TP_ROOT / "13_sector_score_model" / "outputs_fs_sector_default" / "sector_scores_latest.csv"),
    ("EU", TP_ROOT / "13_sector_score_model" / "outputs_eu" / "sector_scores_latest.csv"),
]
EMU_COUNTRIES = {
    "AUSTRIA",
    "BELGIUM",
    "FINLAND",
    "FRANCE",
    "GERMANY",
    "IRELAND",
    "ITALY",
    "NETHERLANDS",
    "PORTUGAL",
    "SPAIN",
}
SCREEN_COLUMNS = [
    "Company SEDOL",
    "ISIN",
    "Company Name",
    "Name",
    "Exchange Country Region",
    "Exchange Country Name",
    " Benchmark ICB Supersector ",
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


def _region_signals(repo: PresentationDataRepository, as_of: str | None) -> pd.DataFrame:
    signals = repo.signals()
    signals = signals[signals["scope"].eq("region")].copy()
    if as_of:
        signals = signals[pd.to_datetime(signals["Date"], errors="coerce") <= pd.Timestamp(as_of)].copy()
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


def _regime_component(signals: pd.DataFrame, as_of: str | None) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    regime_signals, regime_date = _latest_family(signals, "Regime", as_of)
    if regime_signals.empty:
        return pd.DataFrame(columns=["regime_region_key", "risk_budget_multiplier", "regime_state"]), regime_date
    frame = regime_signals[regime_signals["signal_name"].eq("risk_budget_multiplier")].copy()
    if frame.empty:
        frame = regime_signals.copy()
    frame["risk_budget_multiplier"] = pd.to_numeric(frame["score"], errors="coerce")
    regime_state = frame["raw_value"] if "raw_value" in frame.columns else frame.get("regime_state")
    return pd.DataFrame(
        {
            "regime_region_key": frame["region"],
            "risk_budget_multiplier": frame["risk_budget_multiplier"],
            "regime_state": regime_state,
        }
    ), regime_date


def _country_component(signals: pd.DataFrame, as_of: str | None) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    country_signals, country_date = _latest_family(signals, "country_model", as_of)
    if country_signals.empty:
        return pd.DataFrame(columns=["country_model_region", "country_score_pct", "country_recommendation"]), country_date
    frame = country_signals[country_signals["signal_name"].eq("country_global_score")].copy()
    if frame.empty:
        frame = country_signals.copy()
    frame["country_score_pct"] = _score_pct(frame)
    return frame.rename(columns={"region": "country_model_region", "raw_value": "country_recommendation"})[
        ["country_model_region", "country_score_pct", "country_recommendation"]
    ], country_date


def _sector_component(as_of: str | None) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    frames: list[pd.DataFrame] = []
    dates: list[pd.Timestamp] = []
    for region_key, path in SECTOR_OUTPUTS:
        if not path.exists():
            continue
        frame = pd.read_csv(path, encoding="utf-8-sig")
        try:
            latest_date = latest_on_or_before(frame, as_of)
        except ValueError:
            continue
        frame = frame[pd.to_datetime(frame["Date"], errors="coerce").eq(latest_date)].copy()
        if frame.empty:
            continue
        frame["sector_region_key"] = region_key
        frame["sector_code"] = pd.to_numeric(frame["sector_code"], errors="coerce").astype("Int64")
        frame["sector_score"] = pd.to_numeric(frame["score_final"], errors="coerce")
        frame["sector_score_pct"] = frame["sector_score"].rank(pct=True)
        frame["signal_date_sector"] = latest_date
        if "recommendation" not in frame.columns:
            frame["recommendation"] = pd.NA
        frames.append(
            frame[
                [
                    "sector_region_key",
                    "sector_code",
                    "sector_score",
                    "sector_score_pct",
                    "sector_name",
                    "recommendation",
                    "signal_date_sector",
                ]
            ].rename(columns={"recommendation": "sector_recommendation"})
        )
        dates.append(latest_date)
    if not frames:
        return (
            pd.DataFrame(
                columns=[
                    "sector_region_key",
                    "sector_code",
                    "sector_score",
                    "sector_score_pct",
                    "sector_name",
                    "sector_recommendation",
                    "signal_date_sector",
                ]
            ),
            None,
        )
    return pd.concat(frames, ignore_index=True), min(dates)


def _screen_snapshot(
    repo: PresentationDataRepository,
    as_of: pd.Timestamp | None,
) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    cutoff = pd.Timestamp(as_of).normalize() if as_of is not None and pd.notna(as_of) else None
    screen = repo.screen(last_only=True).copy()
    dates = pd.to_datetime(screen["Date"], errors="coerce") if "Date" in screen.columns else pd.Series(dtype="datetime64[ns]")
    snapshot_date = pd.Timestamp(dates.max()).normalize() if not dates.dropna().empty else None
    if cutoff is not None and (snapshot_date is None or snapshot_date > cutoff):
        screen = repo.screen(last_only=False).copy()
        dates = pd.to_datetime(screen["Date"], errors="coerce") if "Date" in screen.columns else pd.Series(dtype="datetime64[ns]")
        eligible_dates = dates[dates <= cutoff].dropna()
        if eligible_dates.empty:
            raise ValueError(f"找不到 {cutoff.date().isoformat()} 当日或之前的 Screen 截面")
        snapshot_date = pd.Timestamp(eligible_dates.max()).normalize()
        screen = screen[dates.eq(snapshot_date)].copy()
    if "Company SEDOL" not in screen.columns and screen.index.name == "Company SEDOL":
        screen = screen.reset_index()
    keep = [column for column in SCREEN_COLUMNS if column in screen.columns]
    if "Company SEDOL" not in keep:
        keep.insert(0, "Company SEDOL")
    return screen[keep].drop_duplicates(subset=["Company SEDOL"], keep="first"), snapshot_date


def _regime_region_key(region: object) -> str | None:
    value = str(region or "")
    if value == "North America":
        return "US"
    if value == "West Europe":
        return "EU"
    return None


def _country_model_region(row: pd.Series) -> str | None:
    country = str(row.get("Exchange Country Name") or "").upper()
    region = str(row.get("Exchange Country Region") or "")
    if country == "UNITED STATES":
        return "US"
    if country == "JAPAN":
        return "Japan"
    if country == "UNITED KINGDOM":
        return "UK"
    if country in EMU_COUNTRIES:
        return "EMU"
    if region in {"Africa", "Asia", "East Europe", "Mid East", "South America"}:
        return "EM"
    return None


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
    result["selection_reason"] = result.apply(
        lambda row: f"rank {int(row['rank'])} selected by composite_score" if row["selected"] else pd.NA,
        axis=1,
    )
    result["exclusion_reason"] = result.apply(
        lambda row: pd.NA if row["selected"] else f"rank {int(row['rank'])} outside selection cutoff",
        axis=1,
    )
    return result.sort_values(["selected", "rank"], ascending=[False, True])


def build_candidates(
    *,
    as_of: str | None,
    output: Path,
    top_n: int | None,
    top_pct: float,
    ml_weight: float,
    technical_weight: float,
    allocation_weight: float,
    candidate_date_policy: str,
    max_component_lag_days: int,
    allow_stale_technical: bool,
    by_region: bool,
) -> pd.DataFrame:
    repo = PresentationDataRepository()
    security_signals = _security_signals(repo, as_of)
    region_signals = _region_signals(repo, as_of)
    ml_signals, ml_date = _latest_family(security_signals, "ML", as_of)
    technical_signals, technical_date = _latest_family(security_signals, "Technical", as_of)
    regime, regime_date = _regime_component(region_signals, as_of)
    country, country_date = _country_component(region_signals, as_of)
    sector, sector_date = _sector_component(as_of)

    component_dates = {
        "ml": ml_date,
        "technical": technical_date,
        "regime": regime_date,
        "country": country_date,
        "sector": sector_date,
    }
    available_dates = [date for date in component_dates.values() if date is not None]
    if available_dates:
        candidate_date = min(available_dates) if candidate_date_policy == "min_component" else max(available_dates)
    else:
        candidate_date = pd.Timestamp(as_of) if as_of else pd.NaT

    if candidate_date_policy == "min_component" and pd.notna(candidate_date):
        cutoff = pd.Timestamp(candidate_date).date().isoformat()
        ml_signals, ml_date = _latest_family(security_signals, "ML", cutoff)
        technical_signals, technical_date = _latest_family(security_signals, "Technical", cutoff)
        regime, regime_date = _regime_component(region_signals, cutoff)
        country, country_date = _country_component(region_signals, cutoff)
        sector, sector_date = _sector_component(cutoff)
        component_dates = {
            "ml": ml_date,
            "technical": technical_date,
            "regime": regime_date,
            "country": country_date,
            "sector": sector_date,
        }

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
    candidates["security_alpha_score"] = weighted.div(denominator.replace(0.0, pd.NA))

    screen, screen_snapshot_date = _screen_snapshot(repo, candidate_date)
    candidates = candidates.merge(screen, on="Company SEDOL", how="left")
    candidates["region"] = candidates.get("Exchange Country Region")
    candidates["regime_region_key"] = candidates["region"].map(_regime_region_key)
    candidates = candidates.merge(regime, on="regime_region_key", how="left")
    candidates["risk_budget_multiplier"] = pd.to_numeric(candidates["risk_budget_multiplier"], errors="coerce").fillna(1.0)
    candidates["country_model_region"] = candidates.apply(_country_model_region, axis=1)
    candidates = candidates.merge(country, on="country_model_region", how="left")
    candidates["sector_region_key"] = candidates["region"].map(_regime_region_key)
    candidates["sector_code"] = pd.to_numeric(candidates.get(" Benchmark ICB Supersector "), errors="coerce").astype("Int64")
    candidates = candidates.merge(sector, on=["sector_region_key", "sector_code"], how="left")
    allocation_parts = [column for column in ["country_score_pct", "sector_score_pct"] if column in candidates.columns]
    candidates["allocation_score_pct"] = candidates[allocation_parts].mean(axis=1) if allocation_parts else pd.NA
    candidates["allocation_score_pct"] = pd.to_numeric(
        candidates["allocation_score_pct"],
        errors="coerce",
    )
    allocation_available = candidates["allocation_score_pct"].notna()
    weighted = weighted.add(candidates["allocation_score_pct"].fillna(0.0) * allocation_weight)
    denominator = denominator.add(allocation_available.astype(float) * allocation_weight)
    weights.append({"component": "allocation_score_pct", "weight": allocation_weight})
    candidates["composite_score_base"] = weighted.div(denominator.replace(0.0, pd.NA))
    candidates["composite_score"] = candidates["composite_score_base"] * candidates["risk_budget_multiplier"]
    candidates = candidates[candidates["composite_score"].notna()].copy()
    candidates["candidate_date"] = candidate_date
    candidates["screen_snapshot_date"] = screen_snapshot_date
    candidates["signal_date_ml"] = ml_date
    candidates["signal_date_technical"] = technical_date
    candidates["signal_date_regime"] = regime_date
    candidates["signal_date_country"] = country_date
    candidates["signal_date_sector"] = sector_date
    lag_reference = pd.Timestamp(candidate_date).normalize() if pd.notna(candidate_date) else None
    component_lag_days = {
        key: int((lag_reference - pd.Timestamp(date).normalize()).days)
        if lag_reference is not None and date is not None
        else None
        for key, date in component_dates.items()
    }
    future_components = [key for key, lag in component_lag_days.items() if lag is not None and lag < 0]
    if future_components:
        raise ValueError(f"候选池包含晚于 candidate_date 的组件：{future_components}")
    stale_components = [
        key
        for key, lag in component_lag_days.items()
        if lag is not None
        and lag > int(max_component_lag_days)
        and not (key == "technical" and allow_stale_technical)
    ]
    if stale_components:
        raise ValueError(
            "候选池组件过旧："
            f"components={stale_components}, lags={component_lag_days}, "
            f"max_component_lag_days={max_component_lag_days}"
        )

    technical_lag_days = component_lag_days["technical"]
    stale_technical = technical_lag_days is None or technical_lag_days > int(max_component_lag_days)
    candidate_lag_days = (
        int((lag_reference - screen_snapshot_date).days)
        if lag_reference is not None and screen_snapshot_date is not None
        else None
    )
    if (
        candidate_lag_days is None
        or candidate_lag_days < 0
        or candidate_lag_days > int(max_component_lag_days)
    ):
        raise ValueError(
            "Candidate date is invalid versus Screen snapshot: "
            f"candidate_date={candidate_date}, screen_snapshot_date={screen_snapshot_date}, "
            f"max_component_lag_days={max_component_lag_days}"
        )
    if stale_technical and not allow_stale_technical:
        raise ValueError(
            "Technical signal is missing or stale: "
            f"technical_date={technical_date}, candidate_date={candidate_date}, "
            f"max_component_lag_days={max_component_lag_days}"
        )
    candidates["freshness_warning"] = (
        f"screen_lag_days={candidate_lag_days}; component_lag_days={component_lag_days}; allowed={max_component_lag_days}"
        if stale_technical
        or (candidate_lag_days is not None and candidate_lag_days > 0)
        or any(lag is not None and lag > 0 for lag in component_lag_days.values())
        else pd.NA
    )
    candidates["candidate_model_version"] = "candidate_layered_v2"
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
            allocation_weight=args.allocation_weight,
            candidate_date_policy=getattr(args, "candidate_date_policy", "max_component"),
            max_component_lag_days=getattr(args, "max_component_lag_days", 31),
            allow_stale_technical=getattr(args, "allow_stale_technical", False),
            by_region=args.by_region,
        )
        duplicate_count = int(frame.duplicated(subset=["candidate_date", "Company SEDOL"], keep=False).sum())
        selected_count = int(frame["selected"].sum())
        manifest.outputs = {"candidates": path_profile(args.output, parquet=True)}
        manifest.details["candidate_summary"] = summarize_frame(frame, date_column="candidate_date")
        component_dates = {}
        for key, column in {
            "ml": "signal_date_ml",
            "technical": "signal_date_technical",
            "regime": "signal_date_regime",
            "country": "signal_date_country",
            "sector": "signal_date_sector",
        }.items():
            values = pd.to_datetime(frame[column], errors="coerce").dropna() if column in frame else pd.Series(dtype="datetime64[ns]")
            component_dates[key] = values.max() if not values.empty else None
        candidate_date = pd.to_datetime(frame["candidate_date"], errors="coerce").dropna().max()
        technical_date = pd.to_datetime(frame["signal_date_technical"], errors="coerce").dropna().max()
        screen_snapshot_dates = pd.to_datetime(frame["screen_snapshot_date"], errors="coerce").dropna()
        screen_snapshot_date = screen_snapshot_dates.max() if not screen_snapshot_dates.empty else None
        max_component_lag_days = getattr(args, "max_component_lag_days", 31)
        allow_stale_technical = getattr(args, "allow_stale_technical", False)
        component_lag_days = {
            key: int((candidate_date.normalize() - value.normalize()).days)
            if pd.notna(candidate_date) and value is not None and pd.notna(value)
            else None
            for key, value in component_dates.items()
        }
        technical_lag_days = component_lag_days["technical"]
        candidate_lag_days = (
            int((candidate_date.normalize() - screen_snapshot_date.normalize()).days)
            if screen_snapshot_date is not None and pd.notna(screen_snapshot_date) and pd.notna(candidate_date)
            else None
        )
        manifest.details["component_freshness"] = {
            "candidate_date_policy": getattr(args, "candidate_date_policy", "max_component"),
            "candidate_date": candidate_date.date().isoformat() if pd.notna(candidate_date) else None,
            "screen_snapshot_date": screen_snapshot_date.date().isoformat()
            if screen_snapshot_date is not None and pd.notna(screen_snapshot_date)
            else None,
            "candidate_lag_days": candidate_lag_days,
            "component_dates": {
                key: value.date().isoformat() if value is not None and pd.notna(value) else None
                for key, value in component_dates.items()
            },
            "component_lag_days": component_lag_days,
            "technical_lag_days": technical_lag_days,
            "max_component_lag_days": max_component_lag_days,
            "allow_stale_technical": allow_stale_technical,
        }
        manifest.add_validation("candidate_table_non_empty", not frame.empty, "候选池非空")
        manifest.add_validation("candidate_keys_unique", duplicate_count == 0, "候选池主键无重复", {"duplicate_rows": duplicate_count})
        manifest.add_validation("selected_candidates_non_empty", selected_count > 0, "入选候选证券非空", {"selected_count": selected_count})
        candidate_ok = (
            candidate_lag_days is not None
            and 0 <= candidate_lag_days <= max_component_lag_days
        )
        manifest.add_validation(
            "candidate_date_fresh",
            candidate_ok,
            "候选池日期相对 Screen 截面在允许窗口内"
            if candidate_ok
            else "候选池日期相对 Screen 截面无效或过旧",
            manifest.details["component_freshness"],
        )
        technical_ok = (
            technical_lag_days is not None
            and 0 <= technical_lag_days <= max_component_lag_days
        )
        manifest.add_validation(
            "technical_component_fresh",
            technical_ok or allow_stale_technical,
            "technical 组件日期在允许窗口内"
            if technical_ok
            else "technical 组件缺失或过旧",
            manifest.details["component_freshness"],
        )
        components_ok = all(
            lag is None
            or 0 <= lag <= max_component_lag_days
            or (key == "technical" and allow_stale_technical and lag >= 0)
            for key, lag in component_lag_days.items()
        )
        manifest.add_validation(
            "component_dates_causal_and_fresh",
            components_ok,
            "全部已使用组件均不晚于候选日期且在允许窗口内"
            if components_ok
            else "存在未来组件或过旧组件",
            manifest.details["component_freshness"],
        )
        return manifest.write("success")
    except Exception as exc:
        manifest.write("failed", error=exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从统一信号表生成候选池")
    parser.add_argument("--as-of", help="目标日期；默认使用各信号最新日期")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="候选池 parquet 输出路径")
    parser.add_argument("--run-type", choices=["production", "smoke", "inspect"], default="production")
    parser.add_argument("--top-n", type=int, help="选择前 N 名；传入后优先于 top-pct")
    parser.add_argument("--top-pct", type=float, default=0.10, help="默认选择前 10%%")
    parser.add_argument("--ml-weight", type=float, default=0.70, help="ML 分数组合权重")
    parser.add_argument("--technical-weight", type=float, default=0.30, help="技术分数组合权重")
    parser.add_argument("--allocation-weight", type=float, default=0.20, help="国家/行业配置分数组合权重")
    parser.add_argument("--candidate-date-policy", choices=["max_component", "min_component"], default="max_component")
    parser.add_argument("--max-component-lag-days", type=int, default=31, help="technical 相对候选日期允许滞后天数")
    parser.add_argument("--allow-stale-technical", action="store_true", help="允许 technical 缺失或过旧时仍生成候选池")
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
