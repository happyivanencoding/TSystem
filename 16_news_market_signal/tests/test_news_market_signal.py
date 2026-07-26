from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from urllib.error import HTTPError

import numpy as np
import pandas as pd


config = import_module("16_news_market_signal.config")
data_pipeline = import_module("16_news_market_signal.data_pipeline")
gdelt = import_module("16_news_market_signal.gdelt")
research = import_module("16_news_market_signal.research")


def test_direct_ingest_records_source_gaps_and_continues(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        gdelt,
        "direct_archives",
        lambda *_: ["20240101.export.CSV.zip", "20240103.export.CSV.zip"],
    )

    def missing_archive(url: str, **_: object) -> None:
        raise HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(gdelt, "urlopen", missing_archive)
    result = gdelt.ingest_direct_archives(
        "2024-01-01",
        "2024-01-04",
        ["US"],
        entity_history_path=tmp_path / "missing.parquet",
    )
    manifest = json.loads((tmp_path / "direct_ingest_manifest.json").read_text(encoding="utf-8"))

    assert result["processed"] == 0
    assert result["remaining"] == 0
    assert result["source_gaps"] == 3
    assert {row["status"] for row in manifest} == {"source_gap"}


def _event_frame(**overrides: object) -> pd.DataFrame:
    row = {
        "source_record_id": "event-1",
        "published_at_utc": "2024-01-02T20:00:00Z",
        "source_name": "public-source.example",
        "url": "https://public-source.example/a",
        "title": "Fed policy changes market expectations",
        "theme": "CENTRAL_BANK;INTEREST_RATE",
        "tone": -2.0,
        "direction": -0.4,
        "source_count": 3,
        "market": "US",
        "country": "US",
        "sector_code": 15,
        "novelty": 0.8,
        "importance": 0.9,
        "uncertainty": 0.7,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_gdelt_v1_day_precision_is_lagged_one_day() -> None:
    raw = pd.DataFrame(
        [{"source_record_id": "1", "sql_date": 20080915, "url": "https://example.com/lehman"}]
    )
    event = data_pipeline.normalize_events(raw, market="US", source_era="gdelt_v1").iloc[0]
    assert event["published_at_utc"] == pd.Timestamp("2008-09-15", tz="UTC")
    assert event["available_at_utc"] == pd.Timestamp("2008-09-16 11:00", tz="UTC")
    assert event["date_precision"] == "day"


def test_market_cutoff_assigns_after_cutoff_to_next_session() -> None:
    before = data_pipeline.normalize_events(_event_frame())
    after = data_pipeline.normalize_events(
        _event_frame(
            source_record_id="event-2",
            url="https://public-source.example/b",
            published_at_utc="2024-01-02T21:00:00Z",
        )
    )
    events = pd.concat([before, after], ignore_index=True)
    calendar = {"US": pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"])}
    assigned = data_pipeline.assign_trading_dates(events, calendar)
    assert assigned.loc[assigned["event_id"].eq("event-1"), "trading_date"].iloc[0] == pd.Timestamp("2024-01-02")
    assert assigned.loc[assigned["event_id"].eq("event-2"), "trading_date"].iloc[0] == pd.Timestamp("2024-01-03")


def test_each_market_morning_is_same_session_and_evening_is_next_session() -> None:
    timestamps = {
        "US": ("2024-01-02T14:00:00Z", "2024-01-02T23:00:00Z"),
        "EU": ("2024-01-02T08:00:00Z", "2024-01-02T18:00:00Z"),
        "JP": ("2024-01-02T00:00:00Z", "2024-01-02T10:00:00Z"),
        "CN_HK": ("2024-01-02T01:00:00Z", "2024-01-02T11:00:00Z"),
    }
    rows = []
    for market, (morning, evening) in timestamps.items():
        rows.extend(
            [
                _event_frame(source_record_id=f"{market}-am", market=market, published_at_utc=morning).iloc[0],
                _event_frame(source_record_id=f"{market}-pm", market=market, published_at_utc=evening).iloc[0],
            ]
        )
    events = data_pipeline.normalize_events(pd.DataFrame(rows))
    calendars = {
        market: pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-08"])
        for market in config.MARKETS
    }
    assigned = data_pipeline.assign_trading_dates(events, calendars)
    for market in config.MARKETS:
        assert assigned.loc[assigned["source_record_id"].eq(f"{market}-am"), "trading_date"].iloc[0] == pd.Timestamp("2024-01-02")
        assert assigned.loc[assigned["source_record_id"].eq(f"{market}-pm"), "trading_date"].iloc[0] == pd.Timestamp("2024-01-03")


def test_day_precision_and_weekend_never_use_unknown_intraday_time() -> None:
    raw = pd.DataFrame(
        [{"source_record_id": "friday", "sql_date": 20240105, "url": "https://example.com/market"}]
    )
    event = data_pipeline.normalize_events(raw, market="US", source_era="gdelt_v1")
    assigned = data_pipeline.assign_trading_dates(
        event,
        {"US": pd.DatetimeIndex(["2024-01-05", "2024-01-08", "2024-01-09"])},
    )
    assert event.iloc[0]["available_at_utc"] == pd.Timestamp("2024-01-06 11:00", tz="UTC")
    assert assigned.iloc[0]["trading_date"] == pd.Timestamp("2024-01-08")


def test_daily_state_keeps_quiet_trading_days_without_fabricating_events() -> None:
    events = data_pipeline.normalize_events(_event_frame())
    calendar = {"US": pd.DatetimeIndex(["2024-01-02", "2024-01-03"])}
    market, sector = data_pipeline.build_daily_states(events, calendar)
    assert len(market) == 2
    assert market.loc[market["trading_date"].eq(pd.Timestamp("2024-01-02")), "event_count"].iloc[0] == 1
    quiet = market.loc[market["trading_date"].eq(pd.Timestamp("2024-01-03"))].iloc[0]
    assert quiet["event_count"] == 0
    assert quiet["core_events_json"] == "[]"
    assert "没有达到入库阈值" in quiet["summary_zh"]
    assert len(sector) == 1


def test_manifest_coverage_distinguishes_quiet_day_from_unfilled_day(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '[{"archive":"20240102.export.CSV.zip","status":"complete"}]', encoding="utf-8"
    )
    calendars = {"US": pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"])}
    covered = gdelt.direct_covered_trading_dates(calendars, ["US"], manifest)
    assert covered["US"] == {pd.Timestamp("2024-01-03")}
    market, _ = data_pipeline.build_daily_states(
        pd.DataFrame(columns=data_pipeline.EVENT_COLUMNS), calendars, covered_trading_dates=covered
    )
    assert not market.loc[market["trading_date"].eq(pd.Timestamp("2024-01-02")), "ingestion_covered"].iloc[0]
    filled_quiet = market.loc[market["trading_date"].eq(pd.Timestamp("2024-01-03"))].iloc[0]
    assert filled_quiet["ingestion_covered"]
    assert filled_quiet["event_count"] == 0
    assert filled_quiet["quality_score"] == 0.5


def test_daily_archive_release_maps_asia_to_the_next_session(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '[{"archive":"20240102.export.CSV.zip","status":"complete"}]', encoding="utf-8"
    )
    calendars = {
        market: pd.DatetimeIndex(["2024-01-03", "2024-01-04"])
        for market in config.MARKETS
    }
    covered = gdelt.direct_covered_trading_dates(calendars, config.MARKETS, manifest)

    assert covered["US"] == {pd.Timestamp("2024-01-03")}
    assert covered["EU"] == {pd.Timestamp("2024-01-03")}
    assert covered["JP"] == {pd.Timestamp("2024-01-04")}
    assert covered["CN_HK"] == {pd.Timestamp("2024-01-04")}


def test_incremental_daily_merge_replaces_only_newly_covered_dates() -> None:
    calendars = {"US": pd.DatetimeIndex(["2024-01-02", "2024-01-03"])}
    first = data_pipeline.normalize_events(_event_frame())
    old_market, old_sector = data_pipeline.build_daily_states(
        first, calendars, covered_trading_dates={"US": {pd.Timestamp("2024-01-02")}}
    )
    second = data_pipeline.normalize_events(
        _event_frame(
            source_record_id="event-2",
            url="https://public-source.example/b",
            published_at_utc="2024-01-03T14:00:00Z",
        )
    )
    partial_market, partial_sector = data_pipeline.build_daily_states(
        second,
        calendars,
        covered_trading_dates={"US": {pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")}},
    )
    market, sector, new_keys = data_pipeline.merge_incremental_states(
        old_market,
        old_sector,
        partial_market,
        partial_sector,
        {"US": {pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")}},
    )
    assert new_keys == 1
    assert len(market) == 2
    assert market.set_index("trading_date")["event_count"].to_dict() == {
        pd.Timestamp("2024-01-02"): 1,
        pd.Timestamp("2024-01-03"): 1,
    }
    assert len(sector) == 2


def test_human_summary_prioritizes_direct_financial_events() -> None:
    group = pd.DataFrame(
        [
            {
                "event_id": f"finance-{index}",
                "title": f"finance story {index}",
                "importance": 0.4,
                "novelty": 0.5,
                "source_count": 2,
                "financial_focus": True,
            }
            for index in range(5)
        ]
        + [
            {
                "event_id": f"systemic-{index}",
                "title": f"systemic story {index}",
                "importance": 1.0,
                "novelty": 0.5,
                "source_count": 20,
                "financial_focus": False,
            }
            for index in range(5)
        ]
    )
    _, core_json = data_pipeline._summary(group)
    core = __import__("json").loads(core_json)
    assert sum(item.startswith("finance story") for item in core) >= 3


def test_query_planner_uses_partition_filters_and_source_eras(tmp_path: Path) -> None:
    shards = gdelt.plan_queries(
        "2015-01-01",
        "2015-03-01",
        ["JP"],
        query_dir=tmp_path / "queries",
        data_dir=tmp_path / "data",
    )
    assert {shard.source_era for shard in shards} == {"gdelt_v1", "gdelt_v2"}
    sql = "\n".join(Path(shard.sql_path).read_text(encoding="utf-8") for shard in shards)
    assert "_PARTITIONTIME" in sql
    assert "maximum" not in sql.lower()
    assert "JA" in sql


def test_direct_archive_intervals_cover_monthly_and_daily_files() -> None:
    monthly = gdelt._archive_interval("200809.zip")
    daily = gdelt._archive_interval("20200312.export.CSV.zip")
    assert monthly == (pd.Timestamp("2008-09-01"), pd.Timestamp("2008-10-01"))
    assert daily == (pd.Timestamp("2020-03-12"), pd.Timestamp("2020-03-13"))
    assert gdelt._archive_interval("README.txt") is None


def test_daily_archive_date_controls_first_availability_not_event_sqldate() -> None:
    raw = pd.DataFrame(
        [{"source_record_id": "late-report", "sql_date": 20200310, "url": "https://example.com/stock-market"}]
    )
    observed = gdelt._apply_archive_observation_date(raw, "20200312.export.CSV.zip")
    event = data_pipeline.normalize_events(observed, market="US", source_era="gdelt_v1_direct").iloc[0]
    assert event["published_at_utc"] == pd.Timestamp("2020-03-12", tz="UTC")
    assert event["available_at_utc"] == pd.Timestamp("2020-03-13 11:00", tz="UTC")

    monthly = gdelt._apply_archive_observation_date(raw, "200809.zip")
    assert "published_at_utc" not in monthly.columns


def test_pre_sourceurl_archive_reads_with_missing_url(tmp_path: Path) -> None:
    import zipfile

    values = [""] * 57
    values[0] = "legacy-1"
    values[1] = "20080915"
    values[6] = "LEHMAN BROTHERS"
    values[16] = "TREASURY"
    values[28] = "14"
    values[31] = "20"
    values[32] = "5"
    values[37] = "US"
    values[44] = "US"
    values[51] = "US"
    archive_path = tmp_path / "200809.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("200809.csv", "\t".join(values) + "\n")
    chunk = next(iter(gdelt._read_direct_archive(archive_path)))
    assert chunk.iloc[0]["source_record_id"] == "legacy-1"
    assert pd.isna(chunk.iloc[0]["url"])
    events = gdelt._direct_raw_events(chunk)
    assert not events.empty
    assert events["financial_focus"].all()


def test_direct_events_filter_noise_and_mark_cross_market_events() -> None:
    chunk = pd.DataFrame(
        [
            {
                "source_record_id": "major",
                "sql_date": 20200312,
                "actor1": "FED",
                "actor2": "ECB",
                "event_root_code": 13,
                "direction_raw": -5,
                "num_mentions": 10,
                "source_count": 3,
                "num_articles": 4,
                "tone_raw": -4,
                "actor1_geo_country": "US",
                "actor2_geo_country": "FR",
                "action_geo_country": "US",
                "url": "https://example.com/stock-market-major-event",
            },
            {
                "source_record_id": "noise",
                "sql_date": 20200312,
                "actor1": "SMALL",
                "actor2": "EVENT",
                "event_root_code": 1,
                "direction_raw": 0,
                "num_mentions": 1,
                "source_count": 1,
                "num_articles": 1,
                "tone_raw": 0,
                "actor1_geo_country": "US",
                "actor2_geo_country": "US",
                "action_geo_country": "US",
                "url": "https://example.com/noise",
            },
        ]
    )
    events = gdelt._direct_raw_events(chunk)
    assert set(events["source_record_id"]) == {"major"}
    assert set(events["market"]) == {"US", "EU"}
    assert events["global_flag"].all()
    assert events["uncertainty"].eq(1.0).all()


def test_direct_financial_story_outranks_equally_covered_systemic_story() -> None:
    base = {
        "sql_date": 20200312,
        "actor1": "GOVERNMENT",
        "actor2": "PUBLIC",
        "event_root_code": 1,
        "direction_raw": 0,
        "num_mentions": 20,
        "source_count": 5,
        "num_articles": 5,
        "tone_raw": -2,
        "actor1_geo_country": "US",
        "actor2_geo_country": "US",
        "action_geo_country": "US",
    }
    chunk = pd.DataFrame(
        [
            {**base, "source_record_id": "finance", "url": "https://example.com/fed-cuts-interest-rates"},
            {**base, "source_record_id": "systemic", "url": "https://example.com/coronavirus-pandemic-update"},
        ]
    )
    events = gdelt._direct_raw_events(chunk).set_index("source_record_id")
    assert events.loc["finance", "importance"] > events.loc["systemic", "importance"]
    assert gdelt._slug_title("https://example.com/news/article_9fc1-adf-df-ce.html") == ""

    false_positives = pd.DataFrame(
        [
            {**base, "source_record_id": "bond", "url": "https://example.com/james-bond-luggage"},
            {**base, "source_record_id": "tradeoff", "url": "https://example.com/algorithmic-trade-off-ethics"},
        ]
    )
    assert gdelt._direct_raw_events(false_positives).empty


def test_direct_events_consolidate_syndicated_story_and_cap_daily_rows() -> None:
    rows = []
    for index in range(4):
        rows.append(
            {
                "market": "US",
                "sql_date": 20200312,
                "source_record_id": str(index),
                "url": f"https://source{index}.example/fed-cuts-interest-rates",
                "title": "Fed cuts interest rates",
                "importance": 0.9 - index / 100,
                "source_count": 10 - index,
                "num_mentions": 20 - index,
            }
        )
    consolidated = gdelt._consolidate_direct_events(pd.DataFrame(rows), max_per_market_day=2)
    assert len(consolidated) == 1
    assert consolidated.iloc[0]["source_record_id"] == "0"

    distinct = pd.DataFrame(
        [
            {
                **rows[0],
                "source_record_id": f"distinct-{index}",
                "sql_date": 20200310 + index,
                "published_at_utc": "2020-03-12",
                "url": f"https://example.com/stock-market-story-{word}",
            }
            for index, word in enumerate(["alpha", "beta", "gamma"])
        ]
    )
    capped = gdelt._consolidate_direct_events(distinct, max_per_market_day=2)
    assert len(capped) == 2


def test_four_market_universe_rules_and_proxy_flag(tmp_path: Path) -> None:
    rows = []
    for date in [pd.Timestamp("2007-01-31"), pd.Timestamp("2009-03-31")]:
        base = {column: np.nan for column in research.SCREEN_COLUMNS}
        rows.extend(
            [
                {
                    **base,
                    "Date": date,
                    "Company SEDOL": "US0001",
                    "Exchange Country Name": "UNITED STATES",
                    "Exchange Country Region": "North America",
                    " Benchmark ICB Supersector ": 10,
                    "Benchmark Market Value Millions in EUR": 100,
                    "Weight in SP500": 1.0 if date.year >= 2009 else np.nan,
                },
                {
                    **base,
                    "Date": date,
                    "Company SEDOL": "EU0001",
                    "Exchange Country Name": "FRANCE",
                    "Exchange Country Region": "West Europe",
                    " Benchmark ICB Supersector ": 11,
                    "Benchmark Market Value Millions in EUR": 90,
                    "Weight in STOXX EUROPE 600": 1.0 if date.year >= 2009 else np.nan,
                },
                {
                    **base,
                    "Date": date,
                    "Company SEDOL": "JP0001",
                    "Exchange Country Name": "JAPAN",
                    "Exchange Country Region": "Asia",
                    " Benchmark ICB Supersector ": 12,
                    "Benchmark Market Value Millions in EUR": 80,
                    "Weight in NIKKEI": 1.0 if date.year >= 2009 else np.nan,
                },
                {
                    **base,
                    "Date": date,
                    "Company SEDOL": "CN0001",
                    "Exchange Country Name": "CHINA",
                    "Exchange Country Region": "Asia",
                    " Benchmark ICB Supersector ": 13,
                    "Benchmark Market Value Millions in EUR": 70,
                    "Weight in MSCI EM": 1.0,
                },
                {
                    **base,
                    "Date": date,
                    "Company SEDOL": "CA0001",
                    "Exchange Country Name": "CANADA",
                    "Exchange Country Region": "North America",
                    " Benchmark ICB Supersector ": 14,
                    "Benchmark Market Value Millions in EUR": 60,
                    "Weight in MSCI WORLD": 1.0,
                },
            ]
        )
    screen_path = tmp_path / "screen.parquet"
    pd.DataFrame(rows).to_parquet(screen_path, index=False)
    panel = research.build_universe_panel(screen_path=screen_path, markets=config.MARKETS)
    assert set(panel["market"]) == set(config.MARKETS)
    assert panel.loc[panel["market"].eq("CN_HK"), "Company SEDOL"].eq("CN0001").all()
    assert panel.loc[panel["Date"].eq(pd.Timestamp("2007-01-31")) & panel["market"].isin(["US", "EU", "JP"]), "universe_is_proxy"].all()
    assert not panel.loc[panel["market"].eq("CN_HK"), "universe_is_proxy"].any()


def test_price_labels_use_prior_snapshot_and_future_returns(tmp_path: Path) -> None:
    snapshots = pd.to_datetime(["2020-01-31", "2020-02-29"])
    universe = pd.DataFrame(
        [
            {
                "Date": date,
                "market": "US",
                "benchmark": "SP500",
                "Company SEDOL": sedol,
                "sector_code": sector,
                "weight": 0.5,
                "universe_is_proxy": False,
                "universe_is_stale": False,
                "weight_snapshot_date": date,
            }
            for date in snapshots
            for sedol, sector in [("AAA001", 10), ("BBB001", 11)]
        ]
    )
    dates = pd.bdate_range("2020-02-03", "2020-03-06")
    returns = pd.DataFrame({"AAA001-R": 0.01, "BBB001-R": 0.00}, index=dates)
    returns_path = tmp_path / "returns.parquet"
    returns.to_parquet(returns_path)
    market, sector, calendars = research.build_price_labels(universe, returns_path=returns_path)
    first = market.sort_values("trading_date").iloc[0]
    assert np.isclose(first["market_return"], 0.005)
    assert first["universe_snapshot"] == pd.Timestamp("2020-01-31")
    assert np.isclose(first["target_return_1d"], 0.005)
    assert len(sector) > 0
    assert len(calendars["US"]) == len(dates)


def test_forward_drawdown_is_zero_when_all_future_returns_are_positive() -> None:
    stats = research._forward_stats(pd.Series([0.0, 0.01, 0.02, 0.03, 0.04, 0.05]), 5)
    assert stats.iloc[0]["target_drawdown_5d"] == 0.0


def test_entity_sector_mapping_uses_only_prior_history() -> None:
    event = data_pipeline.normalize_events(
        _event_frame(entities="Acme Holdings,15", sector_code=np.nan)
    )
    history = pd.DataFrame(
        [
            {"Date": "2023-12-31", "market": "US", "alias": "acmeholdings", "sector_code": 10},
            {"Date": "2024-12-31", "market": "US", "alias": "acmeholdings", "sector_code": 18},
        ]
    )
    enriched = data_pipeline.enrich_event_sectors(event, history).iloc[0]
    assert enriched["sector_code"] == 10
    assert enriched["entity_match_count"] == 1


def test_causal_standardization_does_not_change_when_future_changes() -> None:
    values = pd.Series(np.arange(100, dtype=float))
    baseline = research._causal_z(values, min_periods=5)
    changed = values.copy()
    changed.iloc[-1] = 1_000_000
    revised = research._causal_z(changed, min_periods=5)
    pd.testing.assert_series_equal(baseline.iloc[:-1], revised.iloc[:-1])


def test_market_signal_fields_preserve_raw_forecast_direction() -> None:
    dates = pd.bdate_range("2020-01-01", periods=63)
    forecasts = np.r_[np.linspace(0.009, 0.011, 60), 0.001, 0.0, -0.001]
    predictions = pd.DataFrame(
        {
            "trading_date": dates,
            "market": "US",
            "universe_is_proxy": False,
            "coverage_score": 1.0,
            "pred_target_excess_return_1d": forecasts,
            "actual_target_excess_return_1d": 0.0,
            "train_end_target_excess_return_1d": dates - pd.offsets.BDay(1),
            "train_n_target_excess_return_1d": 756,
        }
    )

    panel = research.build_market_signal_panel(predictions)
    low_positive, zero, negative = panel.iloc[-3:].itertuples(index=False)

    assert np.isclose(low_positive.forecast_bp, 10.0)
    assert research._causal_z(pd.Series(forecasts)).iloc[-3] < 0
    assert (low_positive.position, zero.position, negative.position) == (1, 0, -1)
    assert low_positive.signal_strength > 0
    assert zero.signal_strength == 0
    assert negative.signal_strength < 0
    assert set(panel["position"].dropna().astype(int)) == {-1, 0, 1}


def test_sector_signal_top_worst_uses_current_news_and_future_label_only() -> None:
    dates = pd.to_datetime(["2020-01-02", "2020-01-03"])
    state_rows = []
    label_rows = []
    for date in dates:
        for sector in range(10, 16):
            score = float(sector - 10)
            state_rows.append(
                {
                    "trading_date": date,
                    "market": "US",
                    "sector_code": sector,
                    "event_count": 2,
                    "sentiment": score,
                    "uncertainty": 0.0,
                    "news_volume_z": 0.0,
                    "coverage_score": 1.0,
                }
            )
            label_rows.append(
                {
                    "trading_date": date,
                    "market": "US",
                    "sector_code": sector,
                    "target_return_5d": score / 100,
                    "target_return_20d": score / 50,
                    "universe_is_proxy": False,
                }
            )
    panel = research.build_sector_signal_panel(pd.DataFrame(state_rows), pd.DataFrame(label_rows))
    daily, summary = research.evaluate_sector_top_worst(panel)
    assert not daily.empty
    assert summary["average_top_worst_spread"].gt(0).all()
    second_day = panel[panel["trading_date"].eq(dates[1])]
    assert second_day["training_cutoff"].eq(dates[0]).all()


def test_existing_increment_matrix_uses_common_month_end_sample() -> None:
    dates = pd.date_range("2010-01-31", periods=36, freq="ME")
    alignment = pd.DataFrame(
        {
            "Date": dates,
            "market": "CN_HK",
            "pred_target_excess_return_1d": np.linspace(-1, 1, len(dates)),
            "actual_target_excess_return_1d": np.linspace(-0.5, 0.5, len(dates)),
            "pred_target_excess_return_5d": np.linspace(-1, 1, len(dates)),
            "actual_target_excess_return_5d": np.linspace(-0.5, 0.5, len(dates)),
            "existing_country_score": np.linspace(-0.8, 0.8, len(dates)),
        }
    )
    comparison = research.evaluate_existing_increment(alignment)
    assert set(comparison["variant"]) == {"news_only", "existing_only", "existing_plus_news"}
    assert comparison["country_baseline_is_proxy"].all()
    assert comparison["observations"].eq(24).all()
