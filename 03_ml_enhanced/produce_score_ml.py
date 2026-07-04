"""Production runner for missing Score ML monthly scores."""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import shutil
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd


ML_ROOT = Path(__file__).resolve().parent
TP_ROOT = ML_ROOT.parent
if str(TP_ROOT) not in sys.path:
    sys.path.insert(0, str(TP_ROOT))
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

import sitecustomize  # noqa: F401,E402

from tp_core.data_sources import LAST_SCREEN_PATH, SCREEN_AGGREGATE_PATH  # noqa: E402

DEFAULT_UNIVERSES = ("EU", "US", "OTHER", "EM")
SCORE_ML_NEUTRALIZATION_GROUP_COLUMNS = [
    "Date",
    " Benchmark ICB Supersector ",
    "Exchange Country Region",
]
UNIVERSE_CONFIGS = {
    "EU": "Config.config_EU",
    "US": "Config.config_US",
    "OTHER": "Config.config_OTHER",
    "EM": "Config.config_EM",
}
OUTPUT_DIR = ML_ROOT / "Output_files"
QA_DIR = TP_ROOT / "00_screen" / "qa"
BACKUP_DIR = TP_ROOT / "00_screen" / "backups" / "ml_score_update"


def _timestamp() -> str:
    return pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")


def _ensure_isin_column(frame: pd.DataFrame) -> pd.DataFrame:
    if "ISIN" in frame.columns:
        return frame
    if frame.index.name == "ISIN":
        return frame.reset_index()
    return frame.reset_index().rename(columns={"index": "ISIN"})


def _load_screen() -> pd.DataFrame:
    screen = pd.read_parquet(SCREEN_AGGREGATE_PATH)
    screen = _ensure_isin_column(screen)
    screen["Date"] = pd.to_datetime(screen["Date"], errors="coerce")
    return screen


def _resolve_config(config: dict) -> dict:
    resolved = copy.deepcopy(config)
    principal = resolved["PARAMETRES PRINCICALES"]
    for key in ("df_features_path", "score_ml_path", "shap_path"):
        if key not in principal:
            continue
        path = Path(principal[key])
        if not path.is_absolute():
            principal[key] = str(ML_ROOT / path)
    return resolved


def _parse_dates(values: Iterable[str] | None) -> list[pd.Timestamp]:
    if not values:
        return []
    return sorted({pd.Timestamp(value).normalize() for value in values})


def _missing_score_dates(screen: pd.DataFrame) -> list[pd.Timestamp]:
    latest_screen_date = pd.Timestamp(screen["Date"].max()).normalize()
    scored_dates = screen.loc[screen["Score ML"].notna(), "Date"].dropna()
    if scored_dates.empty:
        latest_scored_date = None
    else:
        latest_scored_date = pd.Timestamp(scored_dates.max()).normalize()
    by_date = (
        screen.groupby("Date")["Score ML"]
        .apply(lambda series: int(series.notna().sum()))
        .sort_index()
    )
    return [
        pd.Timestamp(date).normalize()
        for date, non_null in by_date.items()
        if pd.Timestamp(date).normalize() <= latest_screen_date
        and (latest_scored_date is None or pd.Timestamp(date).normalize() > latest_scored_date)
        and non_null == 0
    ]


def _target_dates(
    screen: pd.DataFrame,
    *,
    dates: Iterable[str] | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[pd.Timestamp]:
    targets = _parse_dates(dates)
    if not targets:
        targets = _missing_score_dates(screen)
    if from_date:
        start = pd.Timestamp(from_date).normalize()
        targets = [date for date in targets if date >= start]
    if to_date:
        end = pd.Timestamp(to_date).normalize()
        targets = [date for date in targets if date <= end]
    return sorted(targets)


def _load_config(universe: str) -> dict:
    module = importlib.import_module(UNIVERSE_CONFIGS[universe])
    return _resolve_config(module.CONFIG)


def _run_universe(universe: str, target_date: pd.Timestamp, run_id: str) -> dict[str, object]:
    from Codes.ML_PIPELINE import ML_MonthlyProdPipeline

    config = _load_config(universe)
    ymd = target_date.strftime("%Y%m%d")
    pipeline = ML_MonthlyProdPipeline(
        config,
        mode="production",
        preprocessing=True,
        output_path=str(OUTPUT_DIR),
        output_file=f"SCORE_ML_{universe}_{ymd}",
        allow_multiprocessing=False,
        update_score_ML=True,
        max_date=target_date,
    )
    result = pipeline.run()
    output_path = Path(pipeline.score_ml_path)
    rows = int(len(result)) if result is not None else None
    return {
        "universe": universe,
        "target_date": target_date.date().isoformat(),
        "score_path": str(output_path),
        "shap_path": str(Path(pipeline.shap_path)),
        "rows": rows,
    }


def _read_score_outputs(generated: list[dict[str, object]]) -> pd.DataFrame:
    parts = []
    for item in generated:
        path = Path(str(item["score_path"]))
        score = _ensure_isin_column(pd.read_parquet(path))
        score["Date"] = pd.to_datetime(score["Date"], errors="coerce")
        score = score[["ISIN", "Date", "Score ML"]].dropna(subset=["ISIN", "Date", "Score ML"])
        parts.append(score)
    if not parts:
        return pd.DataFrame(columns=["ISIN", "Date", "Score ML"])
    combined = pd.concat(parts, ignore_index=True)
    return combined.sort_values(["ISIN", "Date"]).drop_duplicates(["ISIN", "Date"], keep="last")


def _neutralize_score_ml_for_database(screen: pd.DataFrame, affected_dates: list[pd.Timestamp]) -> pd.DataFrame:
    out = screen.copy()
    rank_mask = out["Date"].dt.normalize().isin(affected_dates)
    out.loc[rank_mask, "Score ML"] = (
        out.loc[rank_mask]
        .groupby(SCORE_ML_NEUTRALIZATION_GROUP_COLUMNS)["Score ML"]
        .rank(pct=True, ascending=True)
        * 10
    )
    return out


def _validate_score_ml_neutrality(screen: pd.DataFrame, affected_dates: list[pd.Timestamp]) -> dict[str, object]:
    scoped = screen.loc[screen["Date"].dt.normalize().isin(affected_dates)].copy()
    scored = scoped.dropna(subset=["Score ML"]).copy()
    expected = (
        scored.groupby(SCORE_ML_NEUTRALIZATION_GROUP_COLUMNS)["Score ML"]
        .rank(pct=True, ascending=True)
        * 10
    )
    diff = (scored["Score ML"] - expected).abs()
    max_abs_diff = float(diff.max()) if not diff.empty else 0.0
    return {
        "required": True,
        "group_columns": SCORE_ML_NEUTRALIZATION_GROUP_COLUMNS,
        "checked_rows": int(len(scored)),
        "group_count": int(scored[SCORE_ML_NEUTRALIZATION_GROUP_COLUMNS].drop_duplicates().shape[0]),
        "max_abs_diff": max_abs_diff,
        "ok": max_abs_diff < 1e-12,
    }


def _backup_file(path: Path, run_id: str, label: str) -> str | None:
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"{path.stem}_{run_id}_before_{label}{path.suffix}"
    shutil.copy2(path, target)
    return str(target)


def _refresh_derived_outputs(screen: pd.DataFrame) -> dict[str, object]:
    screen_dir = TP_ROOT / "00_screen"
    if str(screen_dir) not in sys.path:
        sys.path.insert(0, str(screen_dir))
    from monthly_update import refresh_derived_screen_outputs

    return refresh_derived_screen_outputs(screen, SCREEN_AGGREGATE_PATH, LAST_SCREEN_PATH, write=True)


def _export_ml_signals() -> Path:
    path = ML_ROOT / "export_signals.py"
    spec = importlib.util.spec_from_file_location("ml_enhanced_export_signals", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load ML signal exporter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.export_ml_signals(output=module.DEFAULT_OUTPUT, latest_only=True)


def _comparison(screen: pd.DataFrame, target_dates: list[pd.Timestamp], run_id: str) -> dict[str, object]:
    rows = []
    scoped = screen[screen["Date"].isin(target_dates)].copy()
    scoped = scoped.dropna(subset=["Score ML", "Score ML_IF"])
    group_cols = ["Date"]
    if "Exchange Country Region" in scoped.columns:
        group_cols.append("Exchange Country Region")
    for keys, group in scoped.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        score_ml = pd.to_numeric(group["Score ML"], errors="coerce")
        score_if = pd.to_numeric(group["Score ML_IF"], errors="coerce")
        valid = score_ml.notna() & score_if.notna()
        score_ml = score_ml[valid]
        score_if = score_if[valid]
        if score_ml.empty:
            continue
        top_ml = score_ml >= score_ml.quantile(0.9)
        top_if = score_if >= score_if.quantile(0.9)
        top_base = int(min(top_ml.sum(), top_if.sum()))
        rows.append(
            {
                "Date": pd.Timestamp(keys[0]).date().isoformat(),
                "region": keys[1] if len(keys) > 1 else "ALL",
                "rows_both": int(len(score_ml)),
                "score_ml_mean": float(score_ml.mean()),
                "score_ml_if_mean": float(score_if.mean()),
                "pearson_corr": float(score_ml.corr(score_if)) if len(score_ml) > 1 else None,
                "spearman_corr": float(score_ml.rank().corr(score_if.rank())) if len(score_ml) > 1 else None,
                "top_decile_overlap": float((top_ml & top_if).sum() / top_base) if top_base else None,
            }
        )
    comparison = pd.DataFrame(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"score_ml_vs_score_ml_if_{run_id}.csv"
    comparison.to_csv(output, index=False)
    return {
        "path": str(output),
        "rows": int(len(comparison)),
    }


def _write_screen(screen: pd.DataFrame) -> None:
    screen.set_index("ISIN").to_parquet(SCREEN_AGGREGATE_PATH)


def produce_score_ml(
    *,
    dates: Iterable[str] | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    universes: Iterable[str] = DEFAULT_UNIVERSES,
) -> dict[str, object]:
    run_id = _timestamp()
    screen = _load_screen()
    targets = _target_dates(screen, dates=dates, from_date=from_date, to_date=to_date)
    universes = tuple(universe.upper() for universe in universes)
    if not targets:
        return {
            "action": "skipped",
            "reason": "no_missing_score_ml_dates",
            "run_id": run_id,
        }

    unknown = sorted(set(universes) - set(UNIVERSE_CONFIGS))
    if unknown:
        raise ValueError(f"Unknown Score ML universe(s): {unknown}")

    generated = []
    for target in targets:
        for universe in universes:
            generated.append(_run_universe(universe, target, run_id))

    score_updates = _read_score_outputs(generated)
    if score_updates.empty:
        raise ValueError("Score ML production generated no rows")

    backups = {
        "screen_aggregate": _backup_file(SCREEN_AGGREGATE_PATH, run_id, "score_ml_update"),
        "last_screen": _backup_file(LAST_SCREEN_PATH, run_id, "score_ml_update"),
        "screen_aggregate_5y": _backup_file(
            SCREEN_AGGREGATE_PATH.with_name(f"{SCREEN_AGGREGATE_PATH.stem}_5Y{SCREEN_AGGREGATE_PATH.suffix}"),
            run_id,
            "score_ml_update",
        ),
    }

    screen_idx = screen.set_index(["ISIN", "Date"])
    updates_idx = score_updates.set_index(["ISIN", "Date"])
    before_non_null = int(screen_idx["Score ML"].notna().sum())
    screen_idx.update(updates_idx[["Score ML"]])
    screen = screen_idx.reset_index()

    affected_dates = sorted(score_updates["Date"].dropna().dt.normalize().unique())
    screen = _neutralize_score_ml_for_database(screen, affected_dates)
    neutrality_validation = _validate_score_ml_neutrality(screen, affected_dates)
    if not neutrality_validation["ok"]:
        raise ValueError(f"Score ML neutrality validation failed: {neutrality_validation}")

    _write_screen(screen)
    derived_outputs = _refresh_derived_outputs(screen)
    ml_signals_path = _export_ml_signals()
    comparison = _comparison(screen, [pd.Timestamp(date) for date in affected_dates], run_id)

    by_date = (
        screen[screen["Date"].dt.normalize().isin(affected_dates)]
        .groupby("Date")["Score ML"]
        .apply(lambda series: int(series.notna().sum()))
        .to_dict()
    )
    result = {
        "action": "updated",
        "run_id": run_id,
        "target_dates": [date.date().isoformat() for date in targets],
        "universes": list(universes),
        "generated": generated,
        "score_update_rows": int(len(score_updates)),
        "score_ml_non_null_before": before_non_null,
        "score_ml_non_null_after": int(screen["Score ML"].notna().sum()),
        "score_ml_rows_by_date": {pd.Timestamp(key).date().isoformat(): value for key, value in by_date.items()},
        "backups": backups,
        "derived_outputs": derived_outputs,
        "ml_signals_path": str(ml_signals_path),
        "comparison": comparison,
        "score_ml_database_requirement": {
            "neutralized_before_database_update": True,
            "neutralization_group_columns": SCORE_ML_NEUTRALIZATION_GROUP_COLUMNS,
        },
        "score_ml_neutrality_validation": neutrality_validation,
    }

    QA_DIR.mkdir(parents=True, exist_ok=True)
    qa_path = QA_DIR / f"score_ml_update_{run_id}.json"
    with qa_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, default=str)
    result["qa_report_path"] = str(qa_path)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and write missing production Score ML")
    parser.add_argument("--date", action="append", help="Target month-end date; repeatable")
    parser.add_argument("--from-date", help="Only process missing dates on or after this date")
    parser.add_argument("--to-date", help="Only process missing dates on or before this date")
    parser.add_argument("--universe", action="append", choices=DEFAULT_UNIVERSES, help="Universe to run; repeatable")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = produce_score_ml(
        dates=args.date,
        from_date=args.from_date,
        to_date=args.to_date,
        universes=args.universe or DEFAULT_UNIVERSES,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
