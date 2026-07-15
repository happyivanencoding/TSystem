"""Command-line entry point for the four-market news research system."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

import config
import data_pipeline
import gdelt
import research


def _markets(values: Iterable[str]) -> list[str]:
    result = [value.upper() for value in values]
    invalid = sorted(set(result) - set(config.MARKETS))
    if invalid:
        raise ValueError(f"未知市场: {invalid}")
    return result


def command_ingest(args: argparse.Namespace) -> dict[str, object]:
    markets = _markets(args.markets)
    if args.direct_download:
        return gdelt.ingest_direct_archives(
            args.start,
            args.end,
            markets,
            resume=args.resume,
            max_files=args.max_files,
        )
    shards = gdelt.plan_queries(args.start, args.end, markets)
    manifest_path = config.DATA_DIR / "ingest_manifest.json"
    if args.local_input:
        raw = data_pipeline.read_local_input(Path(args.local_input))
        normalized = data_pipeline.normalize_events(
            raw,
            market=args.input_market,
            source_era=args.input_source_era,
        )
        if config.ENTITY_HISTORY_PATH.exists():
            normalized = data_pipeline.enrich_event_sectors(
                normalized, pd.read_parquet(config.ENTITY_HISTORY_PATH)
            )
        paths = data_pipeline.write_event_partitions(normalized)
        return {
            "mode": "local_input",
            "event_rows": len(normalized),
            "partitions": list(map(str, paths)),
        }
    if not args.project:
        gdelt.write_manifest(shards, manifest_path)
        return {
            "mode": "query_plan",
            "query_shards": len(shards),
            "manifest": str(manifest_path),
            "next_action": "提供 --project 执行 BigQuery，或提供 --local-input 使用本地回退数据。",
        }

    completed = gdelt.execute_shards(
        shards,
        project=args.project,
        maximum_bytes_billed=args.maximum_bytes_billed,
        resume=args.resume,
    )
    event_paths: list[str] = []
    for shard in completed:
        raw_path = Path(shard.output_path)
        if not raw_path.exists():
            continue
        normalized = data_pipeline.normalize_events(
            pd.read_parquet(raw_path), market=shard.market, source_era=shard.source_era
        )
        if config.ENTITY_HISTORY_PATH.exists():
            normalized = data_pipeline.enrich_event_sectors(
                normalized, pd.read_parquet(config.ENTITY_HISTORY_PATH)
            )
        event_paths.extend(map(str, data_pipeline.write_event_partitions(normalized)))
    gdelt.write_manifest(completed, manifest_path)
    return {
        "mode": "bigquery",
        "query_shards": len(completed),
        "completed": sum(shard.status == "complete" for shard in completed),
        "event_partitions": sorted(set(event_paths)),
        "manifest": str(manifest_path),
    }


def command_build_labels(args: argparse.Namespace) -> dict[str, object]:
    markets = _markets(args.markets)
    universe = research.build_universe_panel(start=args.start, markets=markets)
    market_labels, sector_labels, _ = research.build_price_labels(universe)
    paths = research.write_label_outputs(universe, market_labels, sector_labels)
    return {
        "markets": markets,
        "universe_rows": len(universe),
        "market_label_rows": len(market_labels),
        "sector_label_rows": len(sector_labels),
        "outputs": paths,
    }


def _calendars_from_labels(labels: pd.DataFrame, markets: Iterable[str]) -> dict[str, pd.DatetimeIndex]:
    result = {}
    for market in markets:
        dates = labels.loc[
            labels["market"].eq(market) & labels["market_return"].notna(), "trading_date"
        ]
        result[market] = pd.DatetimeIndex(pd.to_datetime(dates)).normalize().unique().sort_values()
    return result


def command_build_daily(args: argparse.Namespace) -> dict[str, object]:
    markets = _markets(args.markets)
    label_path = config.OUTPUT_DIR / "market_labels.parquet"
    if not label_path.exists():
        raise FileNotFoundError("请先运行 build-labels")
    labels = pd.read_parquet(label_path)
    calendars = _calendars_from_labels(labels, markets)
    events = data_pipeline.read_event_partitions(start=args.start, end=args.end, markets=markets)
    covered_trading_dates = gdelt.direct_covered_trading_dates(calendars, markets)
    market_state, sector_state = data_pipeline.build_daily_states(
        events, calendars, covered_trading_dates=covered_trading_dates
    )
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    market_path = config.OUTPUT_DIR / "daily_market_state.parquet"
    sector_path = config.OUTPUT_DIR / "daily_sector_state.parquet"
    newly_covered_keys = 0
    if args.incremental:
        if not market_path.exists() or not sector_path.exists():
            raise FileNotFoundError("增量构建前必须先有完整 daily state")
        market_state, sector_state, newly_covered_keys = data_pipeline.merge_incremental_states(
            pd.read_parquet(market_path),
            pd.read_parquet(sector_path),
            market_state,
            sector_state,
            covered_trading_dates,
        )
    market_state.to_parquet(market_path, index=False)
    sector_state.to_parquet(sector_path, index=False)
    return {
        "event_rows": len(events),
        "incremental": bool(args.incremental),
        "newly_covered_market_dates": newly_covered_keys,
        "market_state_rows": len(market_state),
        "sector_state_rows": len(sector_state),
        "market_state": str(market_path),
        "sector_state": str(sector_path),
    }


def command_backtest(args: argparse.Namespace) -> dict[str, object]:
    state_path = config.OUTPUT_DIR / "daily_market_state.parquet"
    labels_path = config.OUTPUT_DIR / "market_labels.parquet"
    sector_state_path = config.OUTPUT_DIR / "daily_sector_state.parquet"
    sector_labels_path = config.OUTPUT_DIR / "sector_labels.parquet"
    if not all(path.exists() for path in [state_path, labels_path, sector_state_path, sector_labels_path]):
        raise FileNotFoundError("请先运行 build-labels 和 build-daily")
    daily_state = pd.read_parquet(state_path)
    market_labels = pd.read_parquet(labels_path)
    predictions = research.walk_forward_ridge(
        daily_state,
        market_labels,
        min_train=args.min_train,
        alpha=args.alpha,
    )
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = config.RUNS_DIR / f"walkforward_{stamp}"
    paths = research.write_backtest_outputs(
        predictions,
        run_dir,
        daily_state=daily_state,
        market_labels=market_labels,
        sector_state=pd.read_parquet(sector_state_path),
        sector_labels=pd.read_parquet(sector_labels_path),
        compare_existing=args.compare_existing,
    )
    return {"prediction_rows": len(predictions), "run_dir": str(run_dir), "outputs": paths}


def command_publish_report(args: argparse.Namespace) -> dict[str, object]:
    audit_path = config.OUTPUT_DIR / "coverage_audit.csv"
    state_path = config.OUTPUT_DIR / "daily_market_state.parquet"
    if not audit_path.exists() or not state_path.exists():
        raise FileNotFoundError("缺少覆盖审计或 daily state；请先运行 build-labels 和 build-daily")
    audit = pd.read_csv(audit_path)
    state = pd.read_parquet(state_path)
    state["year"] = state["trading_date"].dt.year
    source_audit = state.groupby(["year", "market"], as_index=False).agg(
        trading_days=("trading_date", "size"),
        covered_days=("ingestion_covered", "sum"),
        event_days=("event_count", lambda values: int(values.gt(0).sum())),
        events=("event_count", "sum"),
        average_quality=("quality_score", "mean"),
    )
    source_audit["coverage_rate"] = source_audit["covered_days"] / source_audit["trading_days"]
    source_audit_path = config.OUTPUT_DIR / "source_coverage_audit.csv"
    source_audit.to_csv(source_audit_path, index=False, encoding="utf-8-sig")

    manifest_path = config.DATA_DIR / "direct_ingest_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    complete_archives = sum(row.get("status") == "complete" for row in manifest)
    failed_archives = sum(row.get("status") == "failed" for row in manifest)
    modern_total = len(gdelt.direct_archives("2013-04-01", str(pd.Timestamp.today().date() + pd.Timedelta(days=1))))
    modern_complete = sum(
        row.get("status") == "complete" and ".export.CSV.zip" in str(row.get("archive", ""))
        for row in manifest
    )

    run_dirs = sorted(config.RUNS_DIR.glob("walkforward_*"))
    latest_run = run_dirs[-1] if run_dirs else None
    metrics = pd.read_csv(latest_run / "metrics.csv") if latest_run and (latest_run / "metrics.csv").exists() else pd.DataFrame()
    placebos = pd.read_csv(latest_run / "placebo_metrics.csv") if latest_run and (latest_run / "placebo_metrics.csv").exists() else pd.DataFrame()
    sector = pd.read_csv(latest_run / "sector_top_worst_summary.csv") if latest_run and (latest_run / "sector_top_worst_summary.csv").exists() else pd.DataFrame()
    risk = pd.read_csv(latest_run / "risk_state_metrics.csv") if latest_run and (latest_run / "risk_state_metrics.csv").exists() else pd.DataFrame()
    increment = pd.read_csv(latest_run / "existing_increment_comparison.csv") if latest_run and (latest_run / "existing_increment_comparison.csv").exists() else pd.DataFrame()

    chart_paths: list[str] = []
    try:
        import plotly.express as px

        coverage_chart = px.line(
            source_audit,
            x="year",
            y="coverage_rate",
            color="market",
            markers=True,
            title="四市场新闻源归档覆盖率（非状态骨架覆盖率）",
        )
        coverage_html = config.OUTPUT_DIR / "source_coverage_audit.html"
        coverage_chart.write_html(coverage_html, include_plotlyjs="cdn")
        chart_paths.append(str(coverage_html))
        if not metrics.empty:
            direction = metrics[metrics["target"].isin(["target_excess_return_1d", "target_excess_return_5d"])]
            metric_chart = px.bar(
                direction,
                x="market",
                y="spearman_ic",
                color="target",
                barmode="group",
                title="新闻方向模型样本外 Spearman IC（当前已覆盖期）",
            )
            metric_html = config.OUTPUT_DIR / "screening_direction_ic.html"
            metric_chart.write_html(metric_html, include_plotlyjs="cdn")
            chart_paths.append(str(metric_html))
    except ImportError:
        pass

    report_path = config.OUTPUT_DIR / "四市场历史新闻数据库研究进度.md"
    lines = [
        "# 四市场历史新闻数据库与新闻信号研究",
        "",
        f"生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
        "## 当前结论",
        "",
        "- 这是研究进度报告，不是生产晋级报告。当前结果未达到生产门槛。",
        "- 2007-01 至 2013-03 的 GDELT 1.0 月度归档已完整回填；2013-04 至今的日归档仍在断点回填。",
        "- 状态骨架覆盖全部交易日，但模型只使用 `ingestion_covered=true` 的真实归档日；未回填日不再被误当成安静日。",
        "- 2015 年后的 GDELT 2.0 BigQuery 增强尚未执行，当前直接下载回退仍明确标记 `gdelt_v1_direct`。",
        "",
        "## 归档进度",
        "",
        f"- manifest 完成归档：{complete_archives}；失败：{failed_archives}。",
        f"- 2013-04 至今日日归档：已完成 {modern_complete}/{modern_total}。",
        f"- 最新有效研究 run：`{latest_run}`。" if latest_run else "- 尚无有效研究 run。",
        "",
        "## 点时点股票池与价格标签",
        "",
        audit.to_markdown(index=False),
        "",
        "## 年度来源覆盖（最近 16 行）",
        "",
        source_audit.tail(16).to_markdown(index=False),
        "",
        "## 当前样本外方向/风险筛选",
        "",
        metrics.to_markdown(index=False) if not metrics.empty else "暂无。",
        "",
        "## 安慰剂测试",
        "",
        placebos.to_markdown(index=False) if not placebos.empty else "暂无。",
        "",
        "## 行业 Top/Worst",
        "",
        sector.to_markdown(index=False) if not sector.empty else "当前没有足够的行业截面日。",
        "",
        "## 风险状态",
        "",
        risk.to_markdown(index=False) if not risk.empty else "暂无。",
        "",
        "## 与 Country Model 的共同月末样本筛选",
        "",
        increment.to_markdown(index=False) if not increment.empty else "共同样本不足或尚未运行。",
        "",
        "## 证据状态",
        "",
        "- 当前回测只覆盖真实归档日，仍属于 `screening_walk_forward`，不可与完整现有模型 OOS 结果下最终结论。",
        "- 行业映射在旧 GDELT 1.0 时代很稀疏；必须依靠 2015+ GKG 组织字段和公开公司新闻补足后再评价。",
        "- 现有模型对齐文件已生成，但新闻单独 / 现有模型单独 / 组合的共同 OOS 增量矩阵仍待完整覆盖后正式运行。",
        "- 研究通过前不写入 `04_signals`，也不进入组合或仪表盘。",
        "- Bloomberg 只用于人工抽样验证，不执行批量抓取。",
        "",
        "## 关键产物",
        "",
        f"- 来源覆盖：`{source_audit_path}`",
        f"- 信号面板：`{config.OUTPUT_DIR / 'news_signal_panel.parquet'}`",
        *[f"- Plotly：`{path}`" for path in chart_paths],
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "report": str(report_path),
        "source_coverage_audit": str(source_audit_path),
        "latest_run": str(latest_run) if latest_run else None,
        "charts": chart_paths,
        "modern_archives_complete": modern_complete,
        "modern_archives_total": modern_total,
    }


def command_audit_existing_news(args: argparse.Namespace) -> dict[str, object]:
    audit, summary = research.audit_existing_news_mapping(Path(args.path))
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = config.OUTPUT_DIR / "existing_news_mapping_audit.csv"
    summary_path = config.OUTPUT_DIR / "existing_news_mapping_summary.json"
    audit.to_csv(audit_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"audit": str(audit_path), "summary": str(summary_path), **summary}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Four-market historical news database and signal research")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="plan or execute resumable GDELT ingestion")
    ingest.add_argument("--start", default=config.START_DATE)
    ingest.add_argument("--end", default=str(pd.Timestamp.today().normalize().date() + pd.Timedelta(days=1)))
    ingest.add_argument("--markets", nargs="+", default=list(config.MARKETS))
    ingest.add_argument("--project", help="Google Cloud project; omitted means query-plan only")
    ingest.add_argument("--local-input", help="CSV/JSON/JSONL/Parquet local fallback")
    ingest.add_argument("--input-market", choices=list(config.MARKETS))
    ingest.add_argument("--input-source-era", default="local_open")
    ingest.add_argument("--maximum-bytes-billed", type=int, default=50_000_000_000)
    ingest.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    ingest.add_argument("--direct-download", action="store_true", help="stream-filter official GDELT 1.0 archives")
    ingest.add_argument("--max-files", type=int, help="limit direct archives in this resumable batch")
    ingest.set_defaults(func=command_ingest)

    labels = sub.add_parser("build-labels", help="build point-in-time market and sector labels")
    labels.add_argument("--start", default=config.START_DATE)
    labels.add_argument("--markets", nargs="+", default=list(config.MARKETS))
    labels.set_defaults(func=command_build_labels)

    daily = sub.add_parser("build-daily", help="build daily market and sector news states")
    daily.add_argument("--start", default=config.START_DATE)
    daily.add_argument("--end")
    daily.add_argument("--markets", nargs="+", default=list(config.MARKETS))
    daily.add_argument("--incremental", action="store_true")
    daily.set_defaults(func=command_build_daily)

    backtest = sub.add_parser("backtest", help="run expanding yearly Ridge research")
    backtest.add_argument("--compare-existing", action=argparse.BooleanOptionalAction, default=True)
    backtest.add_argument("--min-train", type=int, default=252)
    backtest.add_argument("--alpha", type=float, default=10.0)
    backtest.set_defaults(func=command_backtest)

    report = sub.add_parser("publish-report", help="write current Chinese research status report")
    report.set_defaults(func=command_publish_report)

    existing = sub.add_parser("audit-existing-news", help="audit local 13-day news file as mapping data only")
    existing.add_argument(
        "--path",
        default=r"C:\GoogleDrive\笔记\Last_NEWS_3months.parquet",
    )
    existing.set_defaults(func=command_audit_existing_news)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    result = args.func(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
