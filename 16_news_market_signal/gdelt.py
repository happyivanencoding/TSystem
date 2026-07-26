"""Resumable GDELT BigQuery planning and optional execution."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError
from urllib.parse import unquote, urlparse
from urllib.request import urlopen

import pandas as pd
import numpy as np

if __package__:
    from . import config, data_pipeline
else:
    import config
    import data_pipeline


DIRECT_BASE_URL = "http://data.gdeltproject.org/events"
DIRECT_INDEX_URL = f"{DIRECT_BASE_URL}/index.html"

GDELT_V1_COLUMNS = {
    0: "source_record_id",
    1: "sql_date",
    6: "actor1",
    16: "actor2",
    28: "event_root_code",
    30: "direction_raw",
    31: "num_mentions",
    32: "source_count",
    33: "num_articles",
    34: "tone_raw",
    37: "actor1_geo_country",
    44: "actor2_geo_country",
    51: "action_geo_country",
    57: "url",
}

EVENT_ROOT_LABELS = {
    "01": "public statement",
    "02": "appeal",
    "03": "express intent",
    "04": "consult",
    "05": "diplomatic cooperation",
    "06": "material cooperation",
    "07": "aid",
    "08": "yield",
    "09": "investigate",
    "10": "demand",
    "11": "disapprove",
    "12": "reject",
    "13": "threaten",
    "14": "protest",
    "15": "force posture",
    "16": "reduce relations",
    "17": "coerce",
    "18": "assault",
    "19": "fight",
    "20": "mass violence",
}

DIRECT_MARKET_REGEX = re.compile(
    r"\b(?:markets|stocks?|shares?|equities|bonds|yields?|treasuries|fed|economy|economic|economics|gdp|"
    r"recession|inflation|currencies|dollars?|euros?|yen|yuan|tariffs?|commodities|earnings?|finance|"
    r"financial|debt|credit|bailout|stimulus|budget|unemployment|unemployed|sanctions?)\b|"
    r"stock\s+market|financial\s+market|bond\s+market|bond\s+yields?|yield\s+curve|federal\s+reserve|"
    r"central\s+bank|interest\s+rates?|oil\s+prices?|crude\s+oil|trade\s+(?:war|deal|talks)|"
    r"jobs?\s+(?:report|growth|losses)|tax\s+(?:cuts?|deferrals?)",
    flags=re.IGNORECASE,
)

DIRECT_FINANCIAL_ACTOR_REGEX = re.compile(
    r"\b(?:FEDERAL RESERVE|TREASURY SECRETARY|FINANCE MINISTER|CENTRAL BANK|EUROPEAN CENTRAL BANK|"
    r"BANK OF JAPAN|PEOPLES BANK OF CHINA|PEOPLE S BANK OF CHINA|ECB|BOJ|PBOC|IMF|WORLD BANK|"
    r"GOLDMAN SACHS|MORGAN STANLEY)\b",
    flags=re.IGNORECASE,
)

DIRECT_LEGACY_ACTOR_REGEX = re.compile(
    r"\b(?:BANK|FINANCIAL|FINANCE|STOCK|MARKET|CURRENCY|TREASURY|RESERVE|LEHMAN|AIG|MERRILL|"
    r"FANNIE|FREDDIE|IMF|WALL STREET|SECURITIES|CREDIT|DEBT|MORTGAGE|ECONOMY|ECONOMIC)\b",
    flags=re.IGNORECASE,
)

DIRECT_SYSTEMIC_REGEX = re.compile(
    r"\b(?:coronavirus|covid|pandemic|crisis|war|invasion|election|elections)\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryShard:
    market: str
    source_era: str
    start: str
    end: str
    sql_path: str
    output_path: str
    status: str = "pending"


def _quoted(values: Iterable[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def build_v2_query(market: str, start: str, end: str) -> str:
    spec = config.MARKET_SPECS[market]
    codes = "|".join(spec.gdelt_country_codes)
    return f"""-- GDELT 2.0 GKG finance subset for {market}
SELECT
  CAST(GKGRECORDID AS STRING) AS source_record_id,
  PARSE_TIMESTAMP('%Y%m%d%H%M%S', CAST(DATE AS STRING)) AS published_at_utc,
  SourceCommonName AS source_name,
  DocumentIdentifier AS url,
  V2Themes AS themes_raw,
  V2Locations AS locations_raw,
  V2Organizations AS organizations_raw,
  SAFE_CAST(SPLIT(V2Tone, ',')[SAFE_OFFSET(0)] AS FLOAT64) AS tone_raw
FROM `gdelt-bq.gdeltv2.gkg_partitioned`
WHERE _PARTITIONTIME >= TIMESTAMP('{start}')
  AND _PARTITIONTIME < TIMESTAMP('{end}')
  AND REGEXP_CONTAINS(IFNULL(V2Locations, ''), r'#({codes})#')
  AND REGEXP_CONTAINS(UPPER(IFNULL(V2Themes, '')), r'({config.FINANCE_THEME_REGEX})')
"""


def build_v1_query(market: str, start: str, end: str) -> str:
    spec = config.MARKET_SPECS[market]
    codes = _quoted(spec.gdelt_country_codes)
    start_int = start.replace("-", "")
    end_int = end.replace("-", "")
    return f"""-- GDELT 1.0 event subset for {market}; publication time is day precision
SELECT
  CAST(GlobalEventID AS STRING) AS source_record_id,
  SQLDATE AS sql_date,
  Actor1Name AS actor1,
  Actor2Name AS actor2,
  EventRootCode AS event_root_code,
  GoldsteinScale AS direction_raw,
  AvgTone AS tone_raw,
  NumMentions AS num_mentions,
  NumSources AS source_count,
  SOURCEURL AS url,
  ActionGeo_FullName AS location_name,
  ActionGeo_CountryCode AS country_code
FROM `gdelt-bq.full.events_partitioned`
WHERE _PARTITIONTIME >= TIMESTAMP('{start}')
  AND _PARTITIONTIME < TIMESTAMP('{end}')
  AND SQLDATE >= {start_int}
  AND SQLDATE < {end_int}
  AND (
    ActionGeo_CountryCode IN ({codes})
    OR Actor1Geo_CountryCode IN ({codes})
    OR Actor2Geo_CountryCode IN ({codes})
  )
"""


def month_ranges(start: str, end: str) -> list[tuple[str, str]]:
    first = pd.Timestamp(start).normalize()
    stop = pd.Timestamp(end).normalize()
    if first >= stop:
        raise ValueError("start 必须早于 end")
    edges = list(pd.date_range(first.to_period("M").to_timestamp(), stop, freq="MS"))
    if not edges or edges[0] > first:
        edges.insert(0, first)
    else:
        edges[0] = first
    if edges[-1] != stop:
        edges.append(stop)
    cutover = pd.Timestamp("2015-02-19")
    if first < cutover < stop and cutover not in edges:
        edges.append(cutover)
        edges = sorted(set(edges))
    return [(str(a.date()), str(b.date())) for a, b in zip(edges[:-1], edges[1:]) if a < b]


def plan_queries(
    start: str,
    end: str,
    markets: Iterable[str],
    query_dir: Path = config.GENERATED_QUERY_DIR,
    data_dir: Path = config.DATA_DIR,
) -> list[QueryShard]:
    query_dir.mkdir(parents=True, exist_ok=True)
    shards: list[QueryShard] = []
    for market in markets:
        if market not in config.MARKET_SPECS:
            raise KeyError(f"未知市场: {market}")
        for shard_start, shard_end in month_ranges(start, end):
            era = "gdelt_v1" if pd.Timestamp(shard_start) < pd.Timestamp("2015-02-19") else "gdelt_v2"
            sql = (
                build_v1_query(market, shard_start, shard_end)
                if era == "gdelt_v1"
                else build_v2_query(market, shard_start, shard_end)
            )
            stem = f"{market}_{shard_start}_{shard_end}_{era}"
            sql_path = query_dir / f"{stem}.sql"
            output_path = data_dir / "raw_gdelt" / f"year={shard_start[:4]}" / f"market={market}" / f"{stem}.parquet"
            sql_path.write_text(sql, encoding="utf-8")
            shards.append(QueryShard(market, era, shard_start, shard_end, str(sql_path), str(output_path)))
    return shards


def write_manifest(shards: Iterable[QueryShard], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(shard) for shard in shards]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def execute_shards(
    shards: Iterable[QueryShard],
    project: str,
    maximum_bytes_billed: int,
    resume: bool = True,
) -> list[QueryShard]:
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError(
            "缺少 google-cloud-bigquery；请安装项目的 news 可选依赖后重试。"
        ) from exc

    client = bigquery.Client(project=project)
    completed: list[QueryShard] = []
    for shard in shards:
        output = Path(shard.output_path)
        if resume and output.exists():
            completed.append(QueryShard(**{**asdict(shard), "status": "skipped_existing"}))
            continue
        sql = Path(shard.sql_path).read_text(encoding="utf-8")
        config_job = bigquery.QueryJobConfig(maximum_bytes_billed=maximum_bytes_billed)
        rows = client.query(sql, job_config=config_job).result()
        frame = pd.DataFrame([dict(row.items()) for row in rows])
        output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(output, index=False)
        completed.append(QueryShard(**{**asdict(shard), "status": "complete"}))
    return completed


def _archive_interval(filename: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    daily = re.fullmatch(r"(\d{8})\.export\.CSV\.zip", filename, flags=re.IGNORECASE)
    if daily:
        start = pd.to_datetime(daily.group(1), format="%Y%m%d")
        return start, start + pd.Timedelta(days=1)
    monthly = re.fullmatch(r"(\d{6})\.zip", filename, flags=re.IGNORECASE)
    if monthly:
        start = pd.to_datetime(monthly.group(1), format="%Y%m")
        return start, start + pd.offsets.MonthBegin(1)
    return None


def direct_archives(start: str, end: str) -> list[str]:
    html = urlopen(DIRECT_INDEX_URL, timeout=30).read().decode("utf-8", "ignore")
    filenames = re.findall(r'href="([^"]+\.zip)"', html, flags=re.IGNORECASE)
    lower = pd.Timestamp(start)
    upper = pd.Timestamp(end)
    selected = []
    for filename in filenames:
        interval = _archive_interval(filename)
        if interval is None:
            continue
        archive_start, archive_end = interval
        if archive_end > lower and archive_start < upper:
            selected.append(filename)
    return sorted(set(selected), key=lambda name: _archive_interval(name)[0])


def direct_covered_trading_dates(
    calendars: dict[str, pd.DatetimeIndex],
    markets: Iterable[str],
    manifest_path: Path | None = None,
) -> dict[str, set[pd.Timestamp]]:
    manifest_path = manifest_path or (config.DATA_DIR / "direct_ingest_manifest.json")
    result = {market: set() for market in markets}
    if not manifest_path.exists():
        return result
    rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_days: set[pd.Timestamp] = set()
    for row in rows:
        if row.get("status") != "complete":
            continue
        interval = _archive_interval(str(row.get("archive", "")))
        if interval is None:
            continue
        source_days.update(pd.date_range(interval[0], interval[1], inclusive="left", freq="D"))
    for market in result:
        calendar = pd.DatetimeIndex(calendars[market]).normalize().unique().sort_values()
        for source_day in source_days:
            available = pd.Timestamp(source_day, tz="UTC") + pd.Timedelta(
                days=1,
                hours=config.GDELT_V1_DAILY_RELEASE_UTC_HOUR,
            )
            trading_date = data_pipeline._next_session(available, market, calendar)
            if pd.notna(trading_date):
                result[market].add(pd.Timestamp(trading_date))
    return result


def _event_theme(row: pd.Series) -> str:
    text = " ".join(str(row.get(column, "")) for column in ["actor1", "actor2", "url"])
    normalized = re.sub(r"[-_/]+", " ", unquote(text)).upper()
    for theme, keywords in config.TOPIC_KEYWORDS.items():
        if any(keyword.replace("_", " ") in normalized for keyword in keywords):
            return theme
    return f"EVENT_{str(row.get('event_root_code', '')).zfill(2)}"


def _slug_title(url: object) -> str:
    parsed = urlparse("" if pd.isna(url) else str(url))
    parts = [part for part in unquote(parsed.path).split("/") if part]
    if not parts:
        return ""
    candidate = re.sub(r"\.(?:html?|php|aspx?)$", "", parts[-1], flags=re.IGNORECASE)
    candidate = re.sub(r"[_-]+", " ", candidate)
    candidate = re.sub(r"\b\d{6,}\b", "", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip()
    words = re.findall(r"[A-Za-z][A-Za-z']+", candidate)
    if words and words[0].casefold() in {"article", "story", "content", "index", "post"} and len(words) <= 6:
        return ""
    non_generic = [word.casefold() for word in words if word.casefold() not in {"article", "story", "news"}]
    if non_generic and all(re.fullmatch(r"[a-f]+", word) for word in non_generic):
        return ""
    return " ".join(words) if len(words) >= 4 else ""


def _story_key(row: pd.Series) -> str:
    title = _slug_title(row.get("url"))
    if title:
        tokens = [token for token in re.findall(r"[a-z0-9]+", title.casefold()) if len(token) > 2]
        if len(tokens) >= 4:
            return " ".join(tokens)
    raw_url = row.get("url", "")
    url = "" if pd.isna(raw_url) else str(raw_url).casefold().strip()
    if url:
        return url
    return "|".join(
        str(row.get(column, "")).casefold().strip()
        for column in ["actor1", "event_root_code", "actor2"]
    )


def _market_masks(chunk: pd.DataFrame) -> dict[str, pd.Series]:
    geo_columns = ["actor1_geo_country", "actor2_geo_country", "action_geo_country"]
    masks = {}
    for market, spec in config.MARKET_SPECS.items():
        mask = pd.Series(False, index=chunk.index)
        for column in geo_columns:
            mask |= chunk[column].isin(spec.gdelt_country_codes)
        masks[market] = mask
    return masks


def _direct_raw_events(chunk: pd.DataFrame) -> pd.DataFrame:
    rows = []
    masks = _market_masks(chunk)
    match_count = sum(mask.astype(int) for mask in masks.values())
    for market, mask in masks.items():
        selected = chunk[mask].copy()
        if selected.empty:
            continue
        mentions = pd.to_numeric(selected["num_mentions"], errors="coerce").fillna(0)
        sources = pd.to_numeric(selected["source_count"], errors="coerce").fillna(0)
        selected = selected[(sources >= 2) | (mentions >= 5)].copy()
        if selected.empty:
            continue
        url_text = selected["url"].fillna("").astype(str).map(
            lambda value: re.sub(r"[-_/]+", " ", unquote(value))
        )
        actor_text = selected["actor1"].fillna("").astype(str) + " " + selected["actor2"].fillna("").astype(str)
        relevance_text = actor_text + " " + url_text
        market_focus = url_text.str.contains(DIRECT_MARKET_REGEX, na=False) | actor_text.str.contains(
            DIRECT_FINANCIAL_ACTOR_REGEX, na=False
        )
        systemic_focus = relevance_text.str.contains(DIRECT_SYSTEMIC_REGEX, na=False)
        legacy_actor_focus = selected["url"].fillna("").astype(str).str.strip().eq("") & actor_text.str.contains(
            DIRECT_LEGACY_ACTOR_REGEX, na=False
        )
        financial_focus = market_focus | legacy_actor_focus
        selected = selected[financial_focus | systemic_focus].copy()
        if selected.empty:
            continue
        selected["market"] = market
        selected["country"] = selected["action_geo_country"]
        selected["theme"] = selected.apply(_event_theme, axis=1)
        selected["entities"] = selected["actor1"].fillna("").astype(str).str.cat(
            selected["actor2"].fillna("").astype(str), sep=";"
        ).str.strip(";")
        roots = selected["event_root_code"].fillna("").astype(str).str.zfill(2)
        labels = roots.map(EVENT_ROOT_LABELS).fillna("reported event")
        fallback_title = (
            selected["actor1"].fillna("Unknown actor").astype(str)
            + " — "
            + labels
            + " — "
            + selected["actor2"].fillna("Unknown counterparty").astype(str)
        )
        slug_titles = selected["url"].map(_slug_title)
        selected["title"] = slug_titles.where(slug_titles.ne(""), fallback_title)
        selected["summary"] = fallback_title
        selected["source_name"] = selected["url"].map(lambda value: urlparse(str(value)).netloc.casefold())
        base_importance = (
            np.log1p(pd.to_numeric(selected["num_mentions"], errors="coerce").fillna(1))
            / np.log(101)
        ).clip(0, 1)
        selected["importance"] = (
            base_importance * (0.70 + 0.30 * financial_focus.reindex(selected.index).astype(float))
        ).clip(0, 1)
        tone = pd.to_numeric(selected["tone_raw"], errors="coerce").fillna(0)
        root_numbers = pd.to_numeric(roots, errors="coerce")
        selected["uncertainty"] = (
            root_numbers.between(13, 20)
            | tone.lt(-3)
        ).astype(float)
        selected["novelty"] = 0.5
        selected["source_era"] = "gdelt_v1_direct"
        selected["date_precision"] = "day"
        selected["global_flag"] = match_count.loc[selected.index].gt(1)
        selected["financial_focus"] = financial_focus.reindex(selected.index).fillna(False)
        rows.append(selected)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _consolidate_direct_events(raw: pd.DataFrame, max_per_market_day: int = 250) -> pd.DataFrame:
    if raw.empty:
        return raw.copy()
    result = raw.copy()
    result["story_key"] = result.apply(_story_key, axis=1)
    result["_mentions"] = pd.to_numeric(result["num_mentions"], errors="coerce").fillna(0)
    result["_sources"] = pd.to_numeric(result["source_count"], errors="coerce").fillna(0)
    observed = (
        pd.to_datetime(result["published_at_utc"], errors="coerce")
        if "published_at_utc" in result
        else pd.Series(pd.NaT, index=result.index)
    )
    event_day = pd.to_datetime(result["sql_date"].astype(str), format="%Y%m%d", errors="coerce")
    result["_observation_day"] = observed.fillna(event_day).dt.normalize()
    result = result.sort_values(
        ["market", "_observation_day", "importance", "_sources", "_mentions", "source_record_id"],
        ascending=[True, True, False, False, False, True],
        kind="mergesort",
    )
    result = result.drop_duplicates(["market", "_observation_day", "story_key"], keep="first")
    result = result.groupby(["market", "_observation_day"], sort=False, group_keys=False).head(max_per_market_day)
    return result.drop(columns=["story_key", "_mentions", "_sources", "_observation_day"]).reset_index(drop=True)


def _purge_direct_interval(start: pd.Timestamp, end: pd.Timestamp, markets: Iterable[str]) -> None:
    root = config.DATA_DIR / "source_events"
    if not root.exists():
        return
    wanted = set(markets)
    for path in root.rglob("events.parquet"):
        market = path.parent.name.removeprefix("market=")
        if market not in wanted:
            continue
        frame = pd.read_parquet(path)
        published = pd.to_datetime(frame["published_at_utc"], utc=True)
        direct = frame["source_era"].eq("gdelt_v1_direct")
        remove = direct & published.ge(start.tz_localize("UTC")) & published.lt(end.tz_localize("UTC"))
        if not remove.any():
            continue
        kept = frame[~remove]
        if kept.empty:
            path.unlink()
        else:
            kept.to_parquet(path, index=False)


def _read_direct_archive(path: Path) -> Iterable[pd.DataFrame]:
    with zipfile.ZipFile(path) as archive:
        members = [member for member in archive.namelist() if not member.endswith("/")]
        if not members:
            return
        with archive.open(members[0]) as probe:
            column_count = len(probe.readline().rstrip(b"\r\n").split(b"\t"))
        usecols = [index for index in sorted(GDELT_V1_COLUMNS) if index < column_count]
        names = [GDELT_V1_COLUMNS[index] for index in usecols]
        with archive.open(members[0]) as handle:
            for chunk in pd.read_csv(
                handle,
                sep="\t",
                header=None,
                usecols=usecols,
                names=names,
                chunksize=200_000,
                low_memory=False,
                on_bad_lines="skip",
            ):
                for column in GDELT_V1_COLUMNS.values():
                    if column not in chunk:
                        chunk[column] = pd.NA
                yield chunk


def _apply_archive_observation_date(chunk: pd.DataFrame, filename: str) -> pd.DataFrame:
    """Use daily archive availability, never the possibly earlier event SQLDATE."""

    result = chunk.copy()
    interval = _archive_interval(filename)
    if interval and re.fullmatch(r"\d{8}\.export\.CSV\.zip", filename, flags=re.IGNORECASE):
        result["published_at_utc"] = interval[0]
    return result


def ingest_direct_archives(
    start: str,
    end: str,
    markets: Iterable[str],
    *,
    resume: bool = True,
    max_files: int | None = None,
    entity_history_path: Path = config.ENTITY_HISTORY_PATH,
) -> dict[str, object]:
    wanted = set(markets)
    archives = direct_archives(start, end)
    manifest_path = config.DATA_DIR / "direct_ingest_manifest.json"
    manifest: dict[str, dict[str, object]] = {}
    if manifest_path.exists():
        manifest = {
            row["archive"]: row
            for row in json.loads(manifest_path.read_text(encoding="utf-8"))
        }
    lower = max(pd.Timestamp(start).normalize(), pd.Timestamp("2013-04-01"))
    upper = min(
        pd.Timestamp(end).normalize(),
        pd.Timestamp.now(tz="UTC").normalize().tz_localize(None) - pd.Timedelta(days=2),
    )
    indexed = set(archives)
    if lower < upper:
        for source_day in pd.date_range(lower, upper, inclusive="left", freq="D"):
            filename = f"{source_day:%Y%m%d}.export.CSV.zip"
            if filename not in indexed and manifest.get(filename, {}).get("status") != "complete":
                manifest[filename] = {
                    "archive": filename,
                    "status": "source_gap",
                    "error": "missing_from_official_index",
                    "processed_at": pd.Timestamp.now(tz="UTC").isoformat(),
                }
    terminal = {"complete", "source_gap"}
    all_pending = [
        name for name in archives
        if not (resume and manifest.get(name, {}).get("status") in terminal)
    ]
    pending = all_pending
    if max_files is not None:
        pending = pending[:max_files]
    cache_dir = config.DATA_DIR / "download_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    entity_history = pd.read_parquet(entity_history_path) if entity_history_path.exists() else pd.DataFrame()
    processed = 0
    attempted = 0
    event_rows = 0
    for filename in pending:
        temp_path = cache_dir / filename
        try:
            archive_interval = _archive_interval(filename)
            if archive_interval is None:
                raise ValueError(f"无法识别归档日期: {filename}")
            archive_start, archive_end = archive_interval
            daily_archive = bool(re.fullmatch(r"\d{8}\.export\.CSV\.zip", filename, flags=re.IGNORECASE))
            with urlopen(f"{DIRECT_BASE_URL}/{filename}", timeout=120) as response, temp_path.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            filtered_chunks = []
            for chunk in _read_direct_archive(temp_path):
                if daily_archive:
                    chunk = _apply_archive_observation_date(chunk, filename)
                direct = _direct_raw_events(chunk)
                if direct.empty:
                    continue
                direct = direct[direct["market"].isin(wanted)]
                if not direct.empty:
                    filtered_chunks.append(direct)
            raw = pd.concat(filtered_chunks, ignore_index=True) if filtered_chunks else pd.DataFrame()
            raw = _consolidate_direct_events(raw)
            normalized = data_pipeline.normalize_events(raw) if not raw.empty else pd.DataFrame(columns=data_pipeline.EVENT_COLUMNS)
            if not normalized.empty and not entity_history.empty:
                normalized = data_pipeline.enrich_event_sectors(normalized, entity_history)
            _purge_direct_interval(archive_start, archive_end, markets=wanted)
            if not normalized.empty:
                data_pipeline.write_event_partitions(normalized)
            event_rows += len(normalized)
            processed += 1
            manifest[filename] = {
                "archive": filename,
                "status": "complete",
                "event_rows": len(normalized),
                "processed_at": pd.Timestamp.now(tz="UTC").isoformat(),
            }
        except HTTPError as exc:
            if exc.code != 404:
                raise
            manifest[filename] = {
                "archive": filename,
                "status": "source_gap",
                "error": f"HTTPError: {exc}",
                "processed_at": pd.Timestamp.now(tz="UTC").isoformat(),
            }
        except Exception as exc:
            manifest[filename] = {
                "archive": filename,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "processed_at": pd.Timestamp.now(tz="UTC").isoformat(),
            }
            raise
        finally:
            attempted += 1
            if temp_path.exists():
                temp_path.unlink()
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(sorted(manifest.values(), key=lambda row: row["archive"]), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    return {
        "archives_in_range": len(archives),
        "processed": processed,
        "remaining": max(0, len(all_pending) - attempted),
        "source_gaps": sum(row.get("status") == "source_gap" for row in manifest.values()),
        "event_rows": event_rows,
        "manifest": str(manifest_path),
    }
