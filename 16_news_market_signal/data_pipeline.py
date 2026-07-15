"""Normalize source events and build point-in-time daily market/sector states."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import numpy as np
import pandas as pd

import config


EVENT_COLUMNS = [
    "event_id",
    "source_record_id",
    "source_era",
    "date_precision",
    "published_at_utc",
    "available_at_utc",
    "market",
    "country",
    "sector_code",
    "theme",
    "direction",
    "tone",
    "uncertainty",
    "importance",
    "novelty",
    "source_count",
    "source_name",
    "entities",
    "url",
    "title",
    "summary",
    "license_type",
    "global_flag",
    "financial_focus",
    "matched_entities_json",
    "entity_match_count",
    "content_hash",
]

NUMERIC_EVENT_COLUMNS = [
    "direction",
    "tone",
    "uncertainty",
    "importance",
    "novelty",
    "source_count",
]

DAILY_FEATURE_COLUMNS = [
    "event_count",
    "source_breadth",
    "importance_sum",
    "novelty_mean",
    "sentiment",
    "local_sentiment",
    "global_sentiment",
    "uncertainty",
    "disagreement",
    "coverage_score",
    "quality_score",
    "news_volume_z",
]


@dataclass
class ValidationResult:
    errors: list[str]
    warnings: list[str]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def _clip(series: pd.Series, lower: float, upper: float) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").clip(lower, upper)


def _domain(url: object) -> str:
    try:
        return urlparse(str(url)).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


def classify_theme(raw: object) -> str:
    text = "" if pd.isna(raw) else str(raw).upper()
    for theme, keywords in config.TOPIC_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return theme
    if text.startswith("EVENT_"):
        return "geopolitics_trade"
    return "other_finance"


def _stable_hash(*parts: object) -> str:
    payload = "|".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_events(raw: pd.DataFrame, *, market: str | None = None, source_era: str | None = None) -> pd.DataFrame:
    """Convert local/GDELT-like rows into the stable source_events contract."""

    frame = raw.copy()
    aliases = {
        "source_record_id": ["source_record_id", "GKGRECORDID", "GlobalEventID"],
        "published_at_utc": ["published_at_utc", "published_at", "sql_date", "SQLDATE", "Date", "date"],
        "source_name": ["source_name", "SourceCommonName", "source"],
        "entities": ["entities", "entities_raw", "organizations_raw", "V2Organizations", "Organizations"],
        "url": ["url", "DocumentIdentifier", "SOURCEURL"],
        "title": ["title", "Title"],
        "summary": ["summary", "snippet", "description"],
        "theme_raw": ["theme", "themes_raw", "V2Themes", "event_root_code"],
        "tone_raw": ["tone", "tone_raw", "AvgTone"],
        "direction_raw": ["direction", "direction_raw", "GoldsteinScale"],
        "source_count": ["source_count", "NumSources", "num_sources"],
        "market": ["market"],
        "country": ["country", "country_code", "location_name"],
        "sector_code": ["sector_code", "ICB19", "icb19_sector"],
        "novelty": ["novelty"],
        "uncertainty": ["uncertainty"],
        "importance": ["importance"],
        "global_flag": ["global_flag"],
        "financial_focus": ["financial_focus"],
        "license_type": ["license_type", "license"],
        "date_precision": ["date_precision"],
        "available_at_utc": ["available_at_utc", "available_at"],
    }

    def coalesce(names: list[str], default: object = pd.NA) -> pd.Series:
        result = pd.Series(default, index=frame.index, dtype="object")
        for name in names:
            if name in frame.columns:
                result = result.where(result.notna(), frame[name])
        return result

    out = pd.DataFrame(index=frame.index)
    for target, names in aliases.items():
        out[target] = coalesce(names)
    if market is not None:
        out["market"] = market
    if source_era is not None:
        out["source_era"] = source_era
    elif "source_era" in frame.columns:
        out["source_era"] = frame["source_era"]
    else:
        out["source_era"] = "local_open"

    published_raw = out["published_at_utc"]
    published_text = published_raw.astype("string").str.replace(r"\.0$", "", regex=True)
    day_mask = published_text.str.fullmatch(r"\d{8}", na=False)
    published = pd.to_datetime(published_raw.where(~day_mask), utc=True, errors="coerce")
    published.loc[day_mask] = pd.to_datetime(
        published_text.loc[day_mask], format="%Y%m%d", utc=True, errors="coerce"
    )
    out["published_at_utc"] = published
    default_precision = pd.Series(
        np.where(out["source_era"].astype(str).str.startswith("gdelt_v1"), "day", "timestamp"),
        index=out.index,
    )
    out["date_precision"] = out["date_precision"].where(out["date_precision"].notna(), default_precision)
    available = pd.to_datetime(out["available_at_utc"], utc=True, errors="coerce")
    precise_default = out["published_at_utc"]
    conservative_day_default = out["published_at_utc"].dt.normalize() + pd.Timedelta(days=1)
    default_available = precise_default.where(out["date_precision"].ne("day"), conservative_day_default)
    out["available_at_utc"] = available.fillna(default_available)

    out["market"] = out["market"].astype("string").str.upper()
    out["country"] = out["country"].astype("string")
    out["sector_code"] = pd.to_numeric(out["sector_code"], errors="coerce").astype("Int64")
    out["theme"] = out["theme_raw"].map(classify_theme)

    raw_tone = pd.to_numeric(out["tone_raw"], errors="coerce")
    out["tone"] = (raw_tone / 10.0).clip(-1, 1).fillna(0.0)
    raw_direction = pd.to_numeric(out["direction_raw"], errors="coerce")
    out["direction"] = raw_direction.where(raw_direction.abs().le(1), raw_direction / 10.0).clip(-1, 1).fillna(0.0)
    out["source_count"] = pd.to_numeric(out["source_count"], errors="coerce").fillna(1).clip(lower=1).astype(int)
    out["novelty"] = _clip(out["novelty"], 0, 1).fillna(0.5)
    out["uncertainty"] = _clip(out["uncertainty"], 0, 1).fillna(0.0)
    inferred_importance = np.log1p(out["source_count"]) / np.log(11)
    out["importance"] = _clip(out["importance"], 0, 1).fillna(pd.Series(inferred_importance, index=out.index).clip(0, 1))
    out["global_flag"] = out["global_flag"].map(lambda value: False if pd.isna(value) else bool(value))
    focus_default = out["source_era"].astype(str).str.startswith("gdelt_v2")
    out["financial_focus"] = out["financial_focus"].where(
        out["financial_focus"].notna(), focus_default
    ).map(bool)

    out["url"] = out["url"].fillna("").astype(str)
    out["source_name"] = out["source_name"].fillna("").astype(str)
    missing_source = out["source_name"].str.strip().eq("")
    out.loc[missing_source, "source_name"] = out.loc[missing_source, "url"].map(_domain)
    out["title"] = out["title"].fillna("").astype(str).str.strip()
    out["summary"] = out["summary"].fillna("").astype(str).str.strip()
    if "actor1" in frame.columns or "actor2" in frame.columns:
        actor1 = frame.get("actor1", pd.Series("", index=frame.index)).fillna("").astype(str)
        actor2 = frame.get("actor2", pd.Series("", index=frame.index)).fillna("").astype(str)
        actor_entities = actor1.str.cat(actor2, sep=";").str.strip(";")
        out["entities"] = out["entities"].where(out["entities"].notna(), actor_entities)
    out["entities"] = out["entities"].fillna("").astype(str)
    out["license_type"] = out["license_type"].fillna("metadata_only").astype(str)
    out["source_record_id"] = out["source_record_id"].astype("string").fillna("").astype(str)
    out["content_hash"] = [
        _stable_hash(url, title, published)
        for url, title, published in zip(out["url"], out["title"], out["published_at_utc"])
    ]
    out["event_id"] = [
        record if record else digest[:24]
        for record, digest in zip(out["source_record_id"], out["content_hash"])
    ]
    out["matched_entities_json"] = "[]"
    out["entity_match_count"] = 0
    out = out.drop(columns=["theme_raw", "tone_raw", "direction_raw"], errors="ignore")
    for column in EVENT_COLUMNS:
        if column not in out.columns:
            out[column] = pd.NA
    return out[EVENT_COLUMNS].drop_duplicates(
        subset=["event_id", "market", "sector_code", "content_hash"], keep="first"
    ).reset_index(drop=True)


def validate_events(events: pd.DataFrame) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    missing = [column for column in EVENT_COLUMNS if column not in events.columns]
    if missing:
        return ValidationResult([f"缺少事件字段: {missing}"], warnings)
    if events["event_id"].isna().any() or events["event_id"].astype(str).str.strip().eq("").any():
        errors.append("event_id 存在空值")
    if events["published_at_utc"].isna().any() or events["available_at_utc"].isna().any():
        errors.append("发布时间或可用时间存在空值")
    published = pd.to_datetime(events["published_at_utc"], utc=True, errors="coerce")
    available = pd.to_datetime(events["available_at_utc"], utc=True, errors="coerce")
    if (available < published).any():
        errors.append("available_at_utc 早于 published_at_utc")
    invalid_markets = sorted(set(events["market"].dropna()) - set(config.MARKETS))
    if invalid_markets:
        errors.append(f"未知 market: {invalid_markets}")
    duplicate_count = int(events.duplicated(["event_id", "market", "sector_code", "content_hash"]).sum())
    if duplicate_count:
        errors.append(f"存在 {duplicate_count} 个重复事件键")
    if events["title"].fillna("").astype(str).str.strip().eq("").mean() > 0.5:
        warnings.append("超过一半事件没有标题；摘要将退化为结构化事件模板")
    return ValidationResult(errors, warnings)


def write_event_partitions(events: pd.DataFrame, root: Path = config.DATA_DIR / "source_events") -> list[Path]:
    validation = validate_events(events)
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))
    frame = events.copy()
    available = pd.to_datetime(frame["available_at_utc"], utc=True)
    frame["_year"] = available.dt.year
    frame["_month"] = available.dt.month
    paths: list[Path] = []
    for (year, month, market), group in frame.groupby(["_year", "_month", "market"], dropna=False):
        path = root / f"year={int(year):04d}" / f"month={int(month):02d}" / f"market={market}" / "events.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        clean = group.drop(columns=["_year", "_month"])
        if path.exists():
            clean = pd.concat([pd.read_parquet(path), clean], ignore_index=True)
            clean = clean.drop_duplicates(["event_id", "market", "sector_code", "content_hash"], keep="last")
        clean.to_parquet(path, index=False)
        paths.append(path)
    return paths


def read_event_partitions(
    root: Path = config.DATA_DIR / "source_events",
    start: str | None = None,
    end: str | None = None,
    markets: Iterable[str] = config.MARKETS,
) -> pd.DataFrame:
    wanted = set(markets)
    frames: list[pd.DataFrame] = []
    for path in root.rglob("events.parquet") if root.exists() else []:
        if path.parent.name.removeprefix("market=") not in wanted:
            continue
        frames.append(pd.read_parquet(path))
    if not frames:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    result = pd.concat(frames, ignore_index=True)
    available = pd.to_datetime(result["available_at_utc"], utc=True)
    if start:
        result = result[available >= pd.Timestamp(start, tz="UTC")]
        available = pd.to_datetime(result["available_at_utc"], utc=True)
    if end:
        result = result[available < pd.Timestamp(end, tz="UTC")]
    return result.reset_index(drop=True)


def _parse_entities(value: object) -> list[str]:
    names = []
    text = "" if pd.isna(value) else str(value)
    for item in text.split(";"):
        name = item.split(",", 1)[0].strip()
        tokens = re.findall(r"[a-z0-9]+", name.casefold())
        normalized = "".join(tokens)
        suffixes = {
            "ag", "co", "company", "corp", "corporation", "group", "holding", "holdings",
            "inc", "incorporated", "limited", "ltd", "nv", "plc", "sa", "sas", "se", "spa",
        }
        while len(tokens) > 1 and tokens[-1] in suffixes:
            tokens.pop()
        canonical = "".join(tokens)
        for alias in (normalized, canonical):
            if len(alias) >= 4:
                names.append(alias)
    return list(dict.fromkeys(names))


def enrich_event_sectors(events: pd.DataFrame, entity_history: pd.DataFrame) -> pd.DataFrame:
    """Exact point-in-time organization matching; ambiguous/fuzzy matches are deliberately skipped."""

    if events.empty or entity_history.empty:
        return events.copy()
    history = entity_history.dropna(subset=["alias", "market", "Date", "sector_code"]).copy()
    history["Date"] = pd.to_datetime(history["Date"])
    lookup: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
    for (market, alias), group in history.groupby(["market", "alias"], sort=False):
        group = group.sort_values("Date").drop_duplicates("Date", keep="last")
        lookup[(str(market), str(alias))] = (
            group["Date"].to_numpy(dtype="datetime64[ns]"),
            group["sector_code"].to_numpy(dtype=int),
        )

    result = events.copy()
    available_dates = pd.to_datetime(result["available_at_utc"], utc=True).dt.tz_localize(None).dt.normalize()
    sectors = result["sector_code"].copy()
    matched_json = []
    match_counts = []
    for idx, (market, entities, available_date) in enumerate(
        zip(result["market"], result["entities"], available_dates)
    ):
        matches: list[tuple[str, int]] = []
        for alias in _parse_entities(entities):
            values = lookup.get((str(market), alias))
            if values is None:
                continue
            dates, sector_values = values
            pos = int(np.searchsorted(dates, np.datetime64(available_date), side="right") - 1)
            if pos >= 0:
                matches.append((alias, int(sector_values[pos])))
        if pd.isna(sectors.iloc[idx]) and matches:
            counts = pd.Series([sector for _, sector in matches]).value_counts()
            if len(counts) and (len(counts) == 1 or counts.iloc[0] > counts.iloc[1]):
                sectors.iloc[idx] = int(counts.index[0])
        matched_json.append(json.dumps([alias for alias, _ in matches], ensure_ascii=False))
        match_counts.append(len(matches))
    result["sector_code"] = pd.to_numeric(sectors, errors="coerce").astype("Int64")
    result["matched_entities_json"] = matched_json
    result["entity_match_count"] = match_counts
    return result


def _next_session(available_at: pd.Timestamp, market: str, calendar: pd.DatetimeIndex) -> pd.Timestamp | pd.NaT:
    spec = config.MARKET_SPECS[market]
    local = available_at.tz_convert(spec.timezone)
    local_day = pd.Timestamp(local.date())
    cutoff = spec.signal_cutoff
    candidate = local_day if local.time().replace(tzinfo=None) <= cutoff else local_day + pd.Timedelta(days=1)
    pos = calendar.searchsorted(candidate, side="left")
    return pd.NaT if pos >= len(calendar) else pd.Timestamp(calendar[pos])


def assign_trading_dates(events: pd.DataFrame, calendars: dict[str, pd.DatetimeIndex]) -> pd.DataFrame:
    result = events.copy()
    available = pd.to_datetime(result["available_at_utc"], utc=True)
    assigned: list[pd.Timestamp | pd.NaT] = []
    for timestamp, market in zip(available, result["market"]):
        calendar = pd.DatetimeIndex(pd.to_datetime(calendars[str(market)])).normalize().unique().sort_values()
        assigned.append(_next_session(timestamp, str(market), calendar))
    result["trading_date"] = pd.to_datetime(assigned)
    return result.dropna(subset=["trading_date"]).reset_index(drop=True)


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna() & weights.gt(0)
    if not mask.any():
        return float("nan")
    return float(np.average(values[mask], weights=weights[mask]))


def _weighted_std(values: pd.Series, weights: pd.Series) -> float:
    mean = _weighted_mean(values, weights)
    mask = values.notna() & weights.notna() & weights.gt(0)
    if not mask.any() or math.isnan(mean):
        return float("nan")
    return float(np.sqrt(np.average((values[mask] - mean) ** 2, weights=weights[mask])))


def _event_display(row: pd.Series) -> str:
    if str(row.get("title", "")).strip():
        return str(row["title"]).strip()
    place = str(row.get("country", "")).strip()
    theme = str(row.get("theme", "other_finance")).replace("_", " ")
    return f"{place + '：' if place else ''}{theme}相关事件"


def _summary(group: pd.DataFrame) -> tuple[str, str]:
    if group.empty:
        return "当日没有达到入库阈值的核心事件。", "[]"
    ranked = group.assign(
        _rank=group["importance"] * group["novelty"] * np.log1p(group["source_count"])
    ).sort_values(["_rank", "event_id"], ascending=[False, True], kind="mergesort")
    ranked["_display"] = [_event_display(row) for _, row in ranked.iterrows()]
    ranked["_display_key"] = ranked["_display"].str.casefold().str.replace(r"\W+", "", regex=True)
    ranked = ranked.drop_duplicates("_display_key", keep="first")
    count = min(7, max(3, int(np.ceil(np.sqrt(len(ranked))))))
    source_era = ranked.get("source_era", pd.Series("", index=ranked.index))
    primary = ranked[source_era.eq("official_primary")].head(min(2, count))
    remaining = ranked.drop(index=primary.index)
    focus = remaining[remaining["financial_focus"].fillna(False).astype(bool)]
    focus_count = min(len(focus), max(1, int(np.ceil((count - len(primary)) * 0.60))))
    selected_focus = focus.head(focus_count)
    selected = pd.concat(
        [
            primary,
            selected_focus,
            remaining.drop(index=selected_focus.index).head(count - len(primary) - focus_count),
        ]
    )
    items = selected["_display"].tolist()
    return "；".join(items) + "。", json.dumps(items, ensure_ascii=False)


def _aggregate_group(group: pd.DataFrame) -> dict[str, object]:
    weights = (group["importance"] * group["novelty"] * np.log1p(group["source_count"])).clip(lower=1e-6)
    event_sentiment = 0.6 * group["direction"] + 0.4 * group["tone"]
    local_mask = ~group["global_flag"]
    summary_zh, core_events_json = _summary(group)
    result: dict[str, object] = {
        "event_count": int(group["event_id"].nunique()),
        "source_breadth": int(group["source_name"].replace("", pd.NA).nunique()),
        "importance_sum": float(group["importance"].sum()),
        "novelty_mean": float(group["novelty"].mean()),
        "sentiment": _weighted_mean(event_sentiment, weights),
        "local_sentiment": _weighted_mean(event_sentiment[local_mask], weights[local_mask]),
        "global_sentiment": _weighted_mean(event_sentiment[~local_mask], weights[~local_mask]),
        "uncertainty": _weighted_mean(group["uncertainty"], weights),
        "disagreement": _weighted_std(event_sentiment, weights),
        "coverage_score": float(min(1.0, np.log1p(group["source_name"].nunique()) / np.log(11))),
        "summary_zh": summary_zh,
        "core_events_json": core_events_json,
        "source_era": "mixed" if group["source_era"].nunique() > 1 else str(group["source_era"].iloc[0]),
    }
    for theme in config.TOPIC_KEYWORDS:
        mask = group["theme"].eq(theme)
        result[f"topic_{theme}"] = _weighted_mean(event_sentiment[mask], weights[mask]) if mask.any() else 0.0
        result[f"topic_{theme}_count"] = int(mask.sum())
    return result


def _rolling_features(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    result = frame.sort_values(keys + ["trading_date"]).copy()
    group_keys = keys
    pieces = []
    for _, group in result.groupby(group_keys, dropna=False, sort=False):
        group = group.copy()
        eligible = group.get("ingestion_covered", pd.Series(True, index=group.index)).fillna(False).astype(bool)
        covered = group.loc[eligible].copy()
        history_mean = covered["event_count"].shift(1).rolling(60, min_periods=20).mean()
        history_std = covered["event_count"].shift(1).rolling(60, min_periods=20).std().replace(0, np.nan)
        group["news_volume_z"] = np.nan
        group.loc[eligible, "news_volume_z"] = (
            (covered["event_count"] - history_mean) / history_std
        ).fillna(0.0).clip(-5, 5)
        for span in (3, 5, 20):
            group[f"sentiment_ewm_{span}"] = np.nan
            group[f"uncertainty_ewm_{span}"] = np.nan
            group.loc[eligible, f"sentiment_ewm_{span}"] = covered["sentiment"].ewm(
                span=span, adjust=False
            ).mean()
            group.loc[eligible, f"uncertainty_ewm_{span}"] = covered["uncertainty"].ewm(
                span=span, adjust=False
            ).mean()
        pieces.append(group)
    return pd.concat(pieces, ignore_index=True) if pieces else result


def _empty_state_row() -> dict[str, object]:
    row: dict[str, object] = {
        "event_count": 0,
        "source_breadth": 0,
        "importance_sum": 0.0,
        "novelty_mean": 0.0,
        "sentiment": 0.0,
        "local_sentiment": 0.0,
        "global_sentiment": 0.0,
        "uncertainty": 0.0,
        "disagreement": 0.0,
        "coverage_score": 0.0,
        "summary_zh": "当日没有达到入库阈值的核心事件。",
        "core_events_json": "[]",
        "source_era": "none",
    }
    for theme in config.TOPIC_KEYWORDS:
        row[f"topic_{theme}"] = 0.0
        row[f"topic_{theme}_count"] = 0
    return row


def build_daily_states(
    events: pd.DataFrame,
    calendars: dict[str, pd.DatetimeIndex],
    covered_trading_dates: dict[str, set[pd.Timestamp]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    validation = validate_events(events)
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))
    assigned = assign_trading_dates(events, calendars)
    market_rows = []
    sector_rows = []
    for (trading_date, market), group in assigned.groupby(["trading_date", "market"], sort=True):
        market_rows.append({"trading_date": trading_date, "market": market, **_aggregate_group(group)})
    sector_events = assigned.dropna(subset=["sector_code"])
    for (trading_date, market, sector_code), group in sector_events.groupby(
        ["trading_date", "market", "sector_code"], sort=True
    ):
        sector_rows.append(
            {"trading_date": trading_date, "market": market, "sector_code": int(sector_code), **_aggregate_group(group)}
        )

    empty = _empty_state_row()
    full_market_index = pd.DataFrame(
        [
            {"trading_date": pd.Timestamp(day), "market": market}
            for market, calendar in calendars.items()
            for day in pd.DatetimeIndex(calendar).normalize().unique().sort_values()
        ]
    )
    market_aggregated = pd.DataFrame(market_rows)
    market = (
        full_market_index.copy()
        if market_aggregated.empty
        else full_market_index.merge(market_aggregated, on=["trading_date", "market"], how="left")
    )
    for column, value in empty.items():
        if column not in market:
            market[column] = value
        else:
            market[column] = market[column].fillna(value)
    if covered_trading_dates is None:
        market["ingestion_covered"] = True
    else:
        market["ingestion_covered"] = [
            pd.Timestamp(day) in covered_trading_dates.get(str(market_code), set())
            for day, market_code in zip(market["trading_date"], market["market"])
        ]
    market["quality_score"] = np.where(
        market["ingestion_covered"],
        np.where(market["event_count"].gt(0), 0.5 + 0.5 * market["coverage_score"], 0.5),
        0.0,
    )
    market = _rolling_features(market, ["market"])

    sector = pd.DataFrame(sector_rows)
    if not sector.empty:
        sector["ingestion_covered"] = True
        sector["quality_score"] = 0.5 + 0.5 * sector["coverage_score"]
        sector = _rolling_features(sector, ["market", "sector_code"])
    return market.sort_values(["trading_date", "market"]).reset_index(drop=True), sector


def merge_incremental_states(
    existing_market: pd.DataFrame,
    existing_sector: pd.DataFrame,
    partial_market: pd.DataFrame,
    partial_sector: pd.DataFrame,
    covered_trading_dates: dict[str, set[pd.Timestamp]],
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    old_flag = (
        existing_market["ingestion_covered"].fillna(False)
        if "ingestion_covered" in existing_market
        else pd.Series(False, index=existing_market.index)
    )
    old_covered = {
        market: set(
            pd.to_datetime(
                existing_market.loc[
                    existing_market["market"].eq(market)
                    & old_flag,
                    "trading_date",
                ]
            )
        )
        for market in covered_trading_dates
    }
    new_keys = {
        (pd.Timestamp(day), market)
        for market, dates in covered_trading_dates.items()
        for day in dates - old_covered.get(market, set())
    }
    if not new_keys:
        return existing_market.copy(), existing_sector.copy(), 0

    partial_keys = pd.MultiIndex.from_frame(partial_market[["trading_date", "market"]])
    wanted_index = pd.MultiIndex.from_tuples(sorted(new_keys), names=["trading_date", "market"])
    replacement = partial_market[partial_keys.isin(wanted_index)].copy()
    existing_keys = pd.MultiIndex.from_frame(existing_market[["trading_date", "market"]])
    market = pd.concat([existing_market[~existing_keys.isin(wanted_index)], replacement], ignore_index=True)
    market["ingestion_covered"] = [
        pd.Timestamp(day) in covered_trading_dates.get(str(market_code), set())
        for day, market_code in zip(market["trading_date"], market["market"])
    ]
    market["quality_score"] = np.where(
        market["ingestion_covered"],
        np.where(market["event_count"].gt(0), 0.5 + 0.5 * market["coverage_score"], 0.5),
        0.0,
    )
    rolling = [
        column
        for column in market
        if column == "news_volume_z"
        or column.startswith("sentiment_ewm_")
        or column.startswith("uncertainty_ewm_")
    ]
    market = _rolling_features(market.drop(columns=rolling), ["market"])

    sector_key_index = pd.MultiIndex.from_tuples(sorted(new_keys), names=["trading_date", "market"])
    if partial_sector.empty:
        replacement_sector = partial_sector.copy()
    else:
        partial_sector_keys = pd.MultiIndex.from_frame(partial_sector[["trading_date", "market"]])
        replacement_sector = partial_sector[partial_sector_keys.isin(sector_key_index)].copy()
    if existing_sector.empty:
        sector = replacement_sector
    else:
        existing_sector_keys = pd.MultiIndex.from_frame(existing_sector[["trading_date", "market"]])
        sector = pd.concat(
            [
                existing_sector[~existing_sector_keys.isin(sector_key_index)],
                replacement_sector,
            ],
            ignore_index=True,
        ).drop_duplicates(["trading_date", "market", "sector_code"], keep="last")
    if not sector.empty:
        sector["ingestion_covered"] = True
        sector["quality_score"] = 0.5 + 0.5 * sector["coverage_score"]
        rolling = [
            column
            for column in sector
            if column == "news_volume_z"
            or column.startswith("sentiment_ewm_")
            or column.startswith("uncertainty_ewm_")
        ]
        sector = _rolling_features(sector.drop(columns=rolling), ["market", "sector_code"])
    return (
        market.sort_values(["trading_date", "market"]).reset_index(drop=True),
        sector.sort_values(["trading_date", "market", "sector_code"]).reset_index(drop=True)
        if not sector.empty
        else sector,
        len(new_keys),
    )


def read_local_input(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".jsonl", ".ndjson"}:
        return pd.read_json(path, lines=True)
    if suffix == ".json":
        return pd.read_json(path)
    raise ValueError(f"不支持的本地输入格式: {suffix}")
