"""Country model database and signal exporter derived from modele_pays.xlsb."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Iterable

import numpy as np
import pandas as pd


TP_ROOT = Path(__file__).resolve().parents[2]
if str(TP_ROOT) not in sys.path:
    sys.path.insert(0, str(TP_ROOT))

import sitecustomize  # noqa: F401,E402
from tp_core.signals import validate_signal_frame, write_signal_frame  # noqa: E402


PROJECT_DIR = Path(__file__).resolve().parents[1]
SOURCE_WORKBOOK = TP_ROOT / "00_screen" / "production_inputs" / "modele_pays.xlsb"
DATA_DIR = PROJECT_DIR / "data"
OUTPUT_DIR = PROJECT_DIR / "outputs"
COUNTRY_DATABASE_PATH = DATA_DIR / "country_model_database.parquet"
DEFAULT_SIGNAL_OUTPUT = TP_ROOT / "04_signals" / "country_model_signals.parquet"
SINGLE_COUNTRY_SCORE_OUTPUT = OUTPUT_DIR / "country_model_single_country_scores.parquet"

MODEL_VERSION = "country_model_excel_replica_v1"
SOURCE_PROJECT = "14_country_model"
MODEL_WEIGHTS = {
    "margin_score": 0.20,
    "profitability_score": 0.20,
    "growth_score": 0.15,
    "value_score": 0.20,
    "momentum_score": 0.25,
}
COUNTRY_COLUMNS = {
    "UK": {
        "label": "FTSE UK",
        "margin_score": "C",
        "profitability_score": "J",
        "growth_score": "Q",
        "value_score": "X",
        "momentum_score": "AE",
        "excel_score": "AS",
        "excel_rank": "AZ",
    },
    "US": {
        "label": "FTSE US",
        "margin_score": "D",
        "profitability_score": "K",
        "growth_score": "R",
        "value_score": "Y",
        "momentum_score": "AF",
        "excel_score": "AT",
        "excel_rank": "BA",
    },
    "EM": {
        "label": "FTSE All-World Emerging",
        "margin_score": "E",
        "profitability_score": "L",
        "growth_score": "S",
        "value_score": "Z",
        "momentum_score": "AG",
        "excel_score": "AU",
        "excel_rank": "BB",
    },
    "Japan": {
        "label": "FTSE Japan",
        "margin_score": "F",
        "profitability_score": "M",
        "growth_score": "T",
        "value_score": "AA",
        "momentum_score": "AH",
        "excel_score": "AV",
        "excel_rank": "BC",
    },
    "EMU": {
        "label": "EMU",
        "margin_score": "G",
        "profitability_score": "N",
        "growth_score": "U",
        "value_score": "AB",
        "momentum_score": "AI",
        "excel_score": "AW",
        "excel_rank": "BD",
    },
}
FACTOR_COLUMNS = list(MODEL_WEIGHTS)
SINGLE_COUNTRY_LABELS = {
    "France": "FTSE France",
    "Germany": "FTSE Germany",
    "Spain": "FTSE Spain",
    "Italy": "FTSE Italy",
    "UK": "FTSE UK",
    "US": "FTSE US",
    "EM": "FTSE All-World Emerging",
    "Japan": "FTSE Japan",
}
SINGLE_COUNTRY_FACTOR_SOURCES = {
    "margin_score": {
        "sheet": "FS_Margin_Pctl",
        "columns": {
            "France": "BT",
            "Germany": "BU",
            "Spain": "BV",
            "Italy": "BW",
            "UK": "BX",
            "US": "BY",
            "EM": "BZ",
            "Japan": "CA",
        },
    },
    "profitability_score": {
        "sheet": "FS_Profit_Pctl",
        "columns": {
            "France": "BT",
            "Germany": "BU",
            "Spain": "BV",
            "Italy": "BW",
            "UK": "BX",
            "US": "BY",
            "EM": "BZ",
            "Japan": "CA",
        },
    },
    "growth_score": {
        "sheet": "FS_Growth_Pctl",
        "columns": {
            "France": "AZ",
            "Germany": "BA",
            "Spain": "BB",
            "Italy": "BC",
            "UK": "BD",
            "US": "BE",
            "EM": "BF",
            "Japan": "BG",
        },
    },
    "value_score": {
        "sheet": "FS_Value_Pctl",
        "columns": {
            "France": "BT",
            "Germany": "BU",
            "Spain": "BV",
            "Italy": "BW",
            "UK": "BX",
            "US": "BY",
            "EM": "BZ",
            "Japan": "CA",
        },
    },
    "momentum_score": {
        "sheet": "FS_Mom_Pctl",
        "columns": {
            "France": "AZ",
            "Germany": "BA",
            "Spain": "BB",
            "Italy": "BC",
            "UK": "BD",
            "US": "BE",
            "EM": "BF",
            "Japan": "BG",
        },
    },
}
SINGLE_COUNTRY_OUTPUT_COLUMNS = [
    "Date",
    "country",
    "country_label",
    *FACTOR_COLUMNS,
    "score",
    "rank",
    "source_workbook",
    "source_project",
    "model_version",
    "extracted_at",
]


def _excel_column_index(column: str) -> int:
    index = 0
    for char in column.upper():
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def _as_float(value: Any) -> float:
    if value in (None, "", "-"):
        return float("nan")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    if number < -1_000_000_000:
        return float("nan")
    return number


def _coerce_dates(values: pd.Series) -> pd.Series:
    dates = pd.to_datetime(values, errors="coerce")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert(None)
    return dates


def _coerce_excel_date(value: Any) -> pd.Timestamp:
    if value in (None, ""):
        return pd.NaT
    if all(hasattr(value, attr) for attr in ("year", "month", "day")):
        return pd.Timestamp(datetime(int(value.year), int(value.month), int(value.day)))
    return pd.to_datetime(value, errors="coerce")


def _range_values(workbook: Any, sheet_name: str, range_name: str) -> list[list[Any]]:
    raw = workbook.Worksheets(sheet_name).Range(range_name).Value
    rows = raw if isinstance(raw, tuple) else ((raw,),)
    return [list(row if isinstance(row, tuple) else (row,)) for row in rows]


def _open_workbook_values(workbook_path: Path) -> list[list[Any]]:
    try:
        import win32com.client as win32
    except ImportError as exc:  # pragma: no cover - depends on Windows Office runtime
        raise RuntimeError("读取 .xlsb 需要 Windows Excel COM: win32com.client 不可用") from exc

    excel = win32.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.EnableEvents = False
    try:
        excel.AutomationSecurity = 3
    except Exception:
        pass

    workbook = None
    try:
        workbook = excel.Workbooks.Open(
            str(workbook_path),
            UpdateLinks=0,
            ReadOnly=True,
            IgnoreReadOnlyRecommended=True,
            AddToMru=False,
        )
        used = workbook.Worksheets("GLOBAL_MODEL").UsedRange
        last_row = int(used.Rows.Count)
        return _range_values(workbook, "GLOBAL_MODEL", f"A1:BD{last_row}")
    finally:
        if workbook is not None:
            workbook.Close(False)
        excel.Quit()


def _open_single_country_factor_values(workbook_path: Path) -> dict[str, list[list[Any]]]:
    try:
        import win32com.client as win32
    except ImportError as exc:  # pragma: no cover - depends on Windows Office runtime
        raise RuntimeError("读取 .xlsb 需要 Windows Excel COM: win32com.client 不可用") from exc

    excel = win32.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.EnableEvents = False
    try:
        excel.AutomationSecurity = 3
    except Exception:
        pass

    workbook = None
    try:
        workbook = excel.Workbooks.Open(
            str(workbook_path),
            UpdateLinks=0,
            ReadOnly=True,
            IgnoreReadOnlyRecommended=True,
            AddToMru=False,
        )
        values: dict[str, list[list[Any]]] = {}
        for factor, source in SINGLE_COUNTRY_FACTOR_SOURCES.items():
            sheet_name = str(source["sheet"])
            columns = dict(source["columns"])
            sheet = workbook.Worksheets(sheet_name)
            used = sheet.UsedRange
            last_row = int(used.Row + used.Rows.Count - 1)
            last_column = max(columns.values(), key=lambda column: _excel_column_index(str(column)))
            values[factor] = _range_values(workbook, sheet_name, f"A1:{last_column}{last_row}")
        return values
    finally:
        if workbook is not None:
            workbook.Close(False)
        excel.Quit()


def build_country_database(workbook_path: Path = SOURCE_WORKBOOK) -> pd.DataFrame:
    rows = _open_workbook_values(workbook_path)
    records: list[dict[str, Any]] = []
    extracted_at = datetime.now().isoformat(timespec="seconds")

    for excel_row_number, row in enumerate(rows, start=1):
        date = _coerce_excel_date(row[0]) if row else pd.NaT
        if pd.isna(date):
            continue

        for country, columns in COUNTRY_COLUMNS.items():
            record: dict[str, Any] = {
                "Date": date,
                "country": country,
                "country_label": columns["label"],
                "source_workbook": str(workbook_path),
                "source_sheet": "GLOBAL_MODEL",
                "source_row": excel_row_number,
                "extracted_at": extracted_at,
            }
            for factor in FACTOR_COLUMNS:
                record[factor] = _as_float(row[_excel_column_index(columns[factor])])
            record["excel_score"] = _as_float(row[_excel_column_index(columns["excel_score"])])
            record["excel_rank"] = _as_float(row[_excel_column_index(columns["excel_rank"])])
            factor_values = [record[factor] for factor in FACTOR_COLUMNS]
            has_factor = any(pd.notna(value) for value in factor_values)
            factors_in_range = all(pd.isna(value) or 0 <= float(value) <= 10 for value in factor_values)
            if has_factor and factors_in_range:
                records.append(record)

    database = pd.DataFrame(records)
    if database.empty:
        return database
    database["Date"] = _coerce_dates(database["Date"])
    database = database.dropna(subset=["Date"]).sort_values(["Date", "country"]).reset_index(drop=True)
    return database


def build_single_country_scores(workbook_path: Path = SOURCE_WORKBOOK) -> pd.DataFrame:
    sheet_values = _open_single_country_factor_values(workbook_path)
    extracted_at = datetime.now().isoformat(timespec="seconds")
    frames: list[pd.DataFrame] = []

    for factor, values in sheet_values.items():
        source = SINGLE_COUNTRY_FACTOR_SOURCES[factor]
        columns = dict(source["columns"])
        records: list[dict[str, Any]] = []
        for row in values:
            date = _coerce_excel_date(row[0]) if row else pd.NaT
            if pd.isna(date):
                continue
            for country, column in columns.items():
                column_index = _excel_column_index(str(column))
                value = _as_float(row[column_index]) if column_index < len(row) else float("nan")
                if pd.isna(value) or value < 0 or value > 10:
                    continue
                records.append(
                    {
                        "Date": date,
                        "country": country,
                        "country_label": SINGLE_COUNTRY_LABELS[country],
                        factor: value,
                    }
                )
        frames.append(pd.DataFrame(records))

    if not frames:
        return pd.DataFrame(columns=SINGLE_COUNTRY_OUTPUT_COLUMNS)

    detail = frames[0]
    for frame in frames[1:]:
        detail = detail.merge(frame, on=["Date", "country", "country_label"], how="outer")
    if detail.empty:
        return pd.DataFrame(columns=SINGLE_COUNTRY_OUTPUT_COLUMNS)

    detail["Date"] = _coerce_dates(detail["Date"])
    detail = detail.dropna(subset=["Date"]).copy()
    for column in FACTOR_COLUMNS:
        detail[column] = pd.to_numeric(detail[column], errors="coerce")
    detail = detail[detail[FACTOR_COLUMNS].notna().all(axis=1)].copy()
    if detail.empty:
        return pd.DataFrame(columns=SINGLE_COUNTRY_OUTPUT_COLUMNS)

    detail["score"] = sum(detail[column] * weight for column, weight in MODEL_WEIGHTS.items())
    detail["rank"] = detail.groupby("Date", dropna=False)["score"].rank(ascending=False, method="min")
    detail["source_workbook"] = str(workbook_path)
    detail["source_project"] = SOURCE_PROJECT
    detail["model_version"] = MODEL_VERSION
    detail["extracted_at"] = extracted_at
    detail = detail[SINGLE_COUNTRY_OUTPUT_COLUMNS].sort_values(["Date", "rank", "country"]).reset_index(drop=True)
    return detail


def write_country_database(
    workbook_path: Path = SOURCE_WORKBOOK,
    output: Path = COUNTRY_DATABASE_PATH,
) -> Path:
    database = build_country_database(workbook_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    database.to_parquet(output, index=False)
    return output


def build_country_model_panel(database: pd.DataFrame) -> pd.DataFrame:
    panel = database.copy()
    for column in FACTOR_COLUMNS + ["excel_score", "excel_rank"]:
        panel[column] = pd.to_numeric(panel[column], errors="coerce")
    panel = panel[panel[FACTOR_COLUMNS].notna().all(axis=1)].copy()
    panel["score"] = sum(panel[column] * weight for column, weight in MODEL_WEIGHTS.items())
    panel["rank"] = panel.groupby("Date", dropna=False)["score"].rank(ascending=False, method="min")
    coverage = panel.groupby("Date", dropna=False)["score"].transform("count")
    panel["recommendation"] = "Neutral"
    panel.loc[panel["rank"].le(1), "recommendation"] = "Positive"
    panel.loc[panel["rank"].ge(coverage), "recommendation"] = "Negative"
    panel = panel.sort_values(["country", "Date"]).reset_index(drop=True)
    panel["previous_score"] = panel.groupby("country")["score"].shift(1)
    panel["previous_rank"] = panel.groupby("country")["rank"].shift(1)
    panel["rank_delta"] = panel["previous_rank"] - panel["rank"]
    panel["score_diff_vs_excel"] = panel["score"] - panel["excel_score"]
    panel["rank_match_excel"] = (
        panel["rank"].round(8).eq(panel["excel_rank"].round(8))
        | (panel["rank"].isna() & panel["excel_rank"].isna())
    )
    panel = panel.sort_values(["Date", "rank", "country"]).reset_index(drop=True)
    return panel


def _validation_payload(panel: pd.DataFrame, signal: pd.DataFrame) -> dict[str, Any]:
    score_diff = panel["score_diff_vs_excel"].abs().dropna()
    validation = validate_signal_frame(signal)
    dates = pd.to_datetime(panel["Date"], errors="coerce").dropna()
    rank_comparable = panel["rank"].notna() & panel["excel_rank"].notna()
    rank_mismatch = rank_comparable & panel["rank"].round(8).ne(panel["excel_rank"].round(8))
    return {
        "rows": int(len(panel)),
        "dates": int(dates.nunique()),
        "latest_date": dates.max().date().isoformat() if not dates.empty else None,
        "max_abs_score_diff_vs_excel": float(score_diff.max()) if not score_diff.empty else None,
        "rank_mismatch_count": int(rank_mismatch.sum()),
        "signal_schema_valid": validation.is_valid,
        "signal_schema_errors": validation.errors,
        "signal_schema_warnings": validation.warnings,
    }


def make_country_signal_frame(panel: pd.DataFrame, *, latest_only: bool = True) -> pd.DataFrame:
    source = panel.copy()
    if latest_only and not source.empty:
        source = source[source["Date"].eq(source["Date"].max())].copy()
    source["score_pct"] = source.groupby("Date", dropna=False)["score"].rank(pct=True)
    signal = pd.DataFrame(
        {
            "Date": source["Date"],
            "signal_family": "country_model",
            "signal_name": "country_global_score",
            "scope": "region",
            "score": source["score"],
            "direction": "higher_is_better",
            "coverage_flag": source[FACTOR_COLUMNS].notna().all(axis=1) & source["score"].notna(),
            "model_version": MODEL_VERSION,
            "source_project": SOURCE_PROJECT,
            "region": source["country"],
            "benchmark": "MSCI World ACWI",
            "universe": "FTSE country regions",
            "score_pct": source["score_pct"],
            "raw_value": source["recommendation"],
            "as_of_date": source["Date"],
            "effective_date": source["Date"],
            "horizon": "1M",
            "signal_description": "Python replica of modele_pays.xlsb country global score.",
            "country_label": source["country_label"],
            "rank": source["rank"],
            "recommendation": source["recommendation"],
            "rank_delta": source["rank_delta"],
            "margin_score": source["margin_score"],
            "profitability_score": source["profitability_score"],
            "growth_score": source["growth_score"],
            "value_score": source["value_score"],
            "momentum_score": source["momentum_score"],
            "excel_score": source["excel_score"],
            "excel_rank": source["excel_rank"],
            "score_diff_vs_excel": source["score_diff_vs_excel"],
        }
    )
    return signal


def run_model(
    *,
    workbook_path: Path = SOURCE_WORKBOOK,
    database_output: Path = COUNTRY_DATABASE_PATH,
    output_dir: Path = OUTPUT_DIR,
    signal_output: Path = DEFAULT_SIGNAL_OUTPUT,
    latest_only: bool = True,
    rebuild_database: bool = True,
) -> dict[str, Any]:
    if rebuild_database or not database_output.exists():
        write_country_database(workbook_path, database_output)
    database = pd.read_parquet(database_output)
    panel = build_country_model_panel(database)
    signal = make_country_signal_frame(panel, latest_only=latest_only)

    output_dir.mkdir(parents=True, exist_ok=True)
    panel_path = output_dir / "country_model_panel.parquet"
    latest_path = output_dir / "country_model_latest.csv"
    single_country_path = output_dir / SINGLE_COUNTRY_SCORE_OUTPUT.name
    single_country_latest_path = output_dir / "country_model_single_country_latest.csv"
    validation_path = output_dir / "country_model_validation.json"
    panel.to_parquet(panel_path, index=False)
    latest = panel[panel["Date"].eq(panel["Date"].max())].copy() if not panel.empty else panel
    latest.to_csv(latest_path, index=False, encoding="utf-8-sig")
    if rebuild_database or not single_country_path.exists():
        single_country = build_single_country_scores(workbook_path)
        single_country.to_parquet(single_country_path, index=False)
    else:
        single_country = pd.read_parquet(single_country_path)
    single_country_latest = (
        single_country[single_country["Date"].eq(single_country["Date"].max())].copy()
        if not single_country.empty
        else single_country
    )
    single_country_latest.to_csv(single_country_latest_path, index=False, encoding="utf-8-sig")
    signal_path = write_signal_frame(signal, signal_output)
    validation = _validation_payload(panel, signal)
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "database": str(database_output),
        "panel": str(panel_path),
        "latest": str(latest_path),
        "single_country_scores": str(single_country_path),
        "single_country_latest": str(single_country_latest_path),
        "signal": str(signal_path),
        "validation": str(validation_path),
        "rows": int(len(panel)),
        "single_country_rows": int(len(single_country)),
        "latest_date": validation["latest_date"],
        "rank_mismatch_count": validation["rank_mismatch_count"],
        "max_abs_score_diff_vs_excel": validation["max_abs_score_diff_vs_excel"],
    }


def export_country_signals(
    *,
    output: Path = DEFAULT_SIGNAL_OUTPUT,
    workbook: Path = SOURCE_WORKBOOK,
    database: Path = COUNTRY_DATABASE_PATH,
    latest_only: bool = True,
) -> Path:
    result = run_model(
        workbook_path=workbook,
        database_output=database,
        signal_output=output,
        latest_only=latest_only,
    )
    return Path(result["signal"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build country model database and signals.")
    parser.add_argument("--workbook", default=str(SOURCE_WORKBOOK), help="source modele_pays.xlsb")
    parser.add_argument("--database-output", default=str(COUNTRY_DATABASE_PATH), help="country database parquet")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="model output directory")
    parser.add_argument("--signal-output", default=str(DEFAULT_SIGNAL_OUTPUT), help="standard signal parquet")
    parser.add_argument("--all-history", action="store_true", help="export all historical signal rows")
    parser.add_argument("--use-existing-database", action="store_true", help="skip Excel extraction when database exists")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = run_model(
        workbook_path=Path(args.workbook),
        database_output=Path(args.database_output),
        output_dir=Path(args.output_dir),
        signal_output=Path(args.signal_output),
        latest_only=not args.all_history,
        rebuild_database=not args.use_existing_database,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
