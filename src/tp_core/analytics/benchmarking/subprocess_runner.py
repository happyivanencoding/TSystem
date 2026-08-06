"""Cold/warm worker used by the benchmark parent process.

The worker reports measurements only. A separate parity pass can persist
frames in the run scratch directory.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd


def _prepare_import_path(repo_root: str | Path) -> None:
    source = str(Path(repo_root).resolve() / "src")
    sys.path = [item for item in sys.path if Path(item or ".").resolve() != Path(source).resolve()]
    sys.path.insert(0, source)


def _configure_environment(spec: dict[str, Any]) -> None:
    data_root = str(Path(spec["data_root"]).resolve())
    os.environ["TP_ROOT"] = data_root
    os.environ["TP_DATA_ROOT"] = data_root
    os.environ["TP_ARTIFACT_ROOT"] = str(Path(data_root) / "artifacts")
    os.environ["TP_DATA_ENGINE"] = (
        "duckdb" if spec["engine"] == "current_duckdb" else "legacy_parquet"
    )
    if spec.get("database"):
        os.environ["TP_DUCKDB_PATH"] = str(Path(spec["database"]).resolve())
    else:
        os.environ.pop("TP_DUCKDB_PATH", None)
    temp_directory = spec.get("temp_directory")
    if temp_directory:
        os.environ["TP_DUCKDB_TEMP_DIR"] = str(Path(temp_directory).resolve())
        Path(temp_directory).mkdir(parents=True, exist_ok=True)
    os.environ["TP_DUCKDB_LATEST_POINTER"] = str(
        Path(spec.get("latest_pointer") or (Path(data_root) / "does-not-exist.json"))
    )
    os.environ["TP_COMPAT_EXPORTS"] = "true"


def _as_date(value: Any) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    return pd.Timestamp(value)


def _frame_from_payload(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value
    if isinstance(value, pd.Series):
        return value.to_frame()
    if isinstance(value, dict):
        return pd.DataFrame({"payload_json": [json.dumps(value, ensure_ascii=False, default=str)]})
    if isinstance(value, (list, tuple)):
        return pd.DataFrame(value)
    return pd.DataFrame({"value": [value]})


def _filter_frame(
    frame: pd.DataFrame,
    *,
    date_from: pd.Timestamp | None = None,
    date_to: pd.Timestamp | None = None,
    isins: tuple[str, ...] = (),
) -> pd.DataFrame:
    result = frame
    if "Date" in result.columns:
        dates = pd.to_datetime(result["Date"], errors="coerce")
        if date_from is not None:
            result = result.loc[dates >= date_from]
            dates = dates.loc[result.index]
        if date_to is not None:
            result = result.loc[dates <= date_to]
    if isins:
        if "ISIN" in result.columns:
            result = result.loc[result["ISIN"].astype(str).isin(isins)]
        elif result.index.name == "ISIN":
            result = result.loc[result.index.astype(str).isin(isins)]
    return result.reset_index(drop=False) if result.index.name == "ISIN" else result


def _screen_operation(spec: dict[str, Any], io: Any, connection: Any) -> pd.DataFrame:
    operation = str(spec["operation"])
    root = Path(spec["data_root"])
    aggregate = root / "00_screen" / "screen_aggregate.parquet"
    latest = root / "00_screen" / "last_screen.parquet"
    five_year = root / "00_screen" / "screen_aggregate_5Y.parquet"
    columns = tuple(spec.get("input_columns") or ())
    resolved = spec.get("resolved") or {}
    pre = spec["engine"] == "pre_duckdb"
    if operation == "screen_full":
        if pre:
            return io.read_screen_aggregate(aggregate)
        if connection is not None:
            from tp_core.analytics.queries import ScreenQuery
            from tp_core.analytics.repositories import ScreenRepository

            return ScreenRepository(connection).query(ScreenQuery())
        return io.read_screen_aggregate(aggregate, engine="legacy_parquet")
    if operation == "screen_latest_all":
        if pre:
            return io.read_last_screen(latest)
        if connection is not None:
            from tp_core.analytics.repositories import ScreenRepository

            return ScreenRepository(connection).latest()
        return io.read_last_screen(engine="legacy_parquet")
    date_to = _as_date(spec.get("as_of") or (spec.get("input_date") or {}).get("as_of"))
    date_from = _as_date((spec.get("input_date") or {}).get("from"))
    if operation == "screen_5y":
        if pre:
            return io.read_screen_5y(five_year, columns=columns or None)
        if connection is not None:
            from tp_core.analytics.queries import ScreenQuery
            from tp_core.analytics.repositories import ScreenRepository

            return ScreenRepository(connection).query(
                ScreenQuery(columns=columns, date_from=date_from, date_to=date_to)
            )
        return io.read_screen_5y(columns=columns or None, engine="legacy_parquet")
    isins = tuple(str(value) for value in resolved.get("screen_isins") or ())
    if operation in {"screen_company_history", "screen_companies_history"}:
        if pre:
            frame = io.read_screen_aggregate(aggregate, columns=columns or None)
            return _filter_frame(frame, date_from=date_from, date_to=date_to, isins=isins)
        if connection is not None:
            from tp_core.analytics.queries import ScreenQuery
            from tp_core.analytics.repositories import ScreenRepository

            return ScreenRepository(connection).query(
                ScreenQuery(columns=columns, date_from=date_from, date_to=date_to, isins=isins)
            )
        return io.read_screen_aggregate(
            aggregate,
            columns=columns or None,
            date_from=date_from,
            date_to=date_to,
            isins=isins,
            engine="legacy_parquet",
        )
    if pre:
        frame = io.read_screen_aggregate(aggregate, columns=columns or None)
        frame = _filter_frame(frame, date_from=date_to, date_to=date_to)
    elif connection is not None:
        from tp_core.analytics.queries import ScreenQuery
        from tp_core.analytics.repositories import ScreenRepository

        frame = ScreenRepository(connection).query(
            ScreenQuery(columns=columns, date_from=date_to, date_to=date_to)
        )
    else:
        frame = io.read_screen_aggregate(
            aggregate,
            columns=columns or None,
            date_from=date_to,
            date_to=date_to,
            engine="legacy_parquet",
        )
    if operation == "screen_benchmark":
        weight_column = str((spec.get("universe") or {}).get("weight_column"))
        if weight_column in frame.columns:
            frame = frame.loc[pd.to_numeric(frame[weight_column], errors="coerce").fillna(0) > 0]
    return frame


def _returns_operation(spec: dict[str, Any], io: Any, connection: Any) -> pd.DataFrame:
    operation = str(spec["operation"])
    root = Path(spec["data_root"])
    returns_path = root / "00_screen" / "returns.parquet"
    pre = spec["engine"] == "pre_duckdb"
    resolved = spec.get("resolved") or {}
    columns = tuple(str(value) for value in resolved.get("returns_columns") or ())
    input_date = spec.get("input_date") or {}
    date_from = _as_date(input_date.get("from"))
    date_to = _as_date(input_date.get("to") or spec.get("as_of"))
    if operation == "returns_dates":
        if pre:
            frame = pd.read_parquet(returns_path, columns=[])
            return pd.DataFrame({"Date": pd.to_datetime(frame.index, errors="coerce")})
        if connection is not None:
            frame = connection.execute(
                'SELECT "Date" FROM "canonical"."returns_wide" ORDER BY "Date"'
            ).df()
            return frame
        dates = io.read_returns_dates(returns_path, engine="legacy_parquet")
        return pd.DataFrame({"Date": dates})
    if operation == "returns_official_backtest_input":
        loader = importlib.import_module("tp_backtest.runner.input_loader")
        kwargs = {
            "metrics": ("Quality Avg Percentile",),
            "benchmarks": ("STOXX EUROPE 600",),
            "start_date": "2020-01-31",
        }
        if not pre:
            kwargs["engine"] = "duckdb" if connection is not None else "legacy_parquet"
        _, frame = loader.load_pruned_backtest_inputs(
            root / "00_screen" / "screen_aggregate.parquet",
            returns_path,
            **kwargs,
        )
        return frame
    if operation == "returns_full":
        if pre:
            return io.read_returns(returns_path)
        if connection is not None:
            from tp_core.analytics.queries import ReturnsQuery
            from tp_core.analytics.repositories import ReturnsRepository

            return ReturnsRepository(connection).matrix(ReturnsQuery())
        return io.read_returns(returns_path, engine="legacy_parquet")
    if operation in {"returns_risk_window", "returns_cross_year", "returns_selected"}:
        if operation == "returns_risk_window":
            date_from = (
                date_to - pd.Timedelta(days=int(input_date.get("window_days", 280)))
                if date_to is not None
                else None
            )
        if pre:
            frame = io.read_returns(returns_path, columns=columns or None)
            if date_from is not None:
                frame = frame.loc[frame.index >= date_from]
            if date_to is not None:
                frame = frame.loc[frame.index <= date_to]
            return frame.sort_index()
        if connection is not None:
            from tp_core.analytics.queries import ReturnsQuery
            from tp_core.analytics.repositories import ReturnsRepository

            return ReturnsRepository(connection).matrix(
                ReturnsQuery(securities=columns, date_from=date_from, date_to=date_to)
            )
        return io.read_returns(
            returns_path,
            columns=columns,
            date_from=date_from,
            date_to=date_to,
            engine="legacy_parquet",
        )
    raise ValueError(f"unsupported returns operation: {operation}")


def _read_artifact(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _frame_from_payload(payload)
    return pd.DataFrame()


def _mart_operation(spec: dict[str, Any], connection: Any) -> pd.DataFrame:
    operation = str(spec["operation"])
    root = Path(spec["data_root"])
    resolved = spec.get("resolved") or {}
    mart_name = resolved.get("mart_name")
    if spec["engine"] == "current_duckdb" and connection is not None and mart_name:
        from tp_core.analytics.repositories import MartRepository

        where = None
        parameters: tuple[Any, ...] = ()
        if operation == "company_latest_payload":
            where = '"ISIN" = ?'
            parameters = (str(resolved.get("company_isin")),)
        return MartRepository(connection).query(str(mart_name), where=where, parameters=parameters)
    if operation in {"company_latest_payload", "company_history_payload"}:
        if spec["engine"] != "pre_duckdb":
            from presentation_layer.data_repository import PresentationDataRepository

            repository = PresentationDataRepository(root=root, engine="legacy_parquet")
            isin = str(resolved.get("company_isin"))
            return (
                repository.latest_company_snapshot(isin=isin)
                if operation == "company_latest_payload"
                else repository.company_history(isin)
            )
        frame = pd.read_parquet(root / "00_screen" / "screen_aggregate.parquet")
        frame = frame.reset_index() if frame.index.name == "ISIN" else frame
        frame = frame.loc[frame["ISIN"].astype(str).eq(str(resolved.get("company_isin")))]
        if operation == "company_latest_payload" and "Date" in frame.columns:
            latest = pd.to_datetime(frame["Date"], errors="coerce").max()
            frame = frame.loc[pd.to_datetime(frame["Date"], errors="coerce").eq(latest)]
        return frame
    if operation == "dashboard_overview_payload":
        try:
            dashboard = importlib.import_module("presentation_layer.apps.system_dashboard")
            return _frame_from_payload(dashboard._dashboard_state_payload())
        except Exception:
            pass
    if (
        operation == "dashboard_overview_payload"
        and spec["engine"] == "current_duckdb"
        and connection is not None
    ):
        from tp_core.analytics.repositories import MartRepository

        return MartRepository(connection).query("dashboard_overview")
    artifact_map = {
        "mart_latest_signals": root / "artifacts" / "signals" / "ml_signals.parquet",
        "mart_latest_regime": root / "artifacts" / "signals" / "regime_risk_budget.parquet",
        "mart_latest_country": root / "artifacts" / "signals" / "country_model_signals.parquet",
        "mart_latest_sector": root
        / "13_sector_score_model"
        / "outputs_eu"
        / "sector_scores_latest.csv",
        "mart_latest_factor": root
        / "artifacts"
        / "signals"
        / "factor_exposure_snapshot_signals.parquet",
        "mart_latest_candidates": root / "artifacts" / "candidates" / "latest_candidates.parquet",
        "mart_latest_portfolio": root
        / "artifacts"
        / "portfolios"
        / "latest_target_weights.parquet",
        "mart_factor_api_payload": root
        / "artifacts"
        / "signals"
        / "factor_recommendation_signals.parquet",
        "mart_backtest_summary": root
        / "artifacts"
        / "pipeline_runs"
        / "manifests"
        / "run_backtest"
        / "run_backtest_latest.json",
    }
    return _read_artifact(artifact_map.get(operation, Path("")))


def _restore_screen_output_order(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the legacy Parquet reader's ISIN-index projection contract."""

    if "ISIN" not in frame.columns:
        return frame
    columns = ["ISIN", *[column for column in frame.columns if column != "ISIN"]]
    return frame.loc[:, columns]


def execute_workload(spec: dict[str, Any], connection: Any = None) -> pd.DataFrame:
    _prepare_import_path(spec["repo_root"])
    _configure_environment(spec)
    io = importlib.import_module("tp_core.io")
    operation = str(spec["operation"])
    if operation.startswith("screen_"):
        frame = _screen_operation(spec, io, connection)
        return _restore_screen_output_order(frame) if spec["engine"] == "current_duckdb" else frame
    if operation.startswith("returns_"):
        return _returns_operation(spec, io, connection)
    if (
        operation.startswith("mart_")
        or operation.startswith("dashboard_")
        or operation.startswith("company_")
    ):
        return _mart_operation(spec, connection)
    raise ValueError(f"unsupported benchmark operation: {operation}")


class _RssSampler:
    def __init__(self) -> None:
        self.peak = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import psutil

        process = psutil.Process()

        def sample() -> None:
            while not self._stop.is_set():
                try:
                    self.peak = max(self.peak, int(process.memory_info().rss))
                except psutil.Error:
                    pass
                self._stop.wait(0.01)

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)


def _measure_once(spec: dict[str, Any], connection: Any = None) -> dict[str, Any]:
    import psutil

    process = psutil.Process()
    before_io = process.io_counters()
    sampler = _RssSampler()
    sampler.start()
    started = time.perf_counter()
    try:
        frame = execute_workload(spec, connection)
        status = "passed"
        error = None
    except Exception as exc:  # noqa: BLE001 - failed measurements are retained
        frame = pd.DataFrame()
        status = "failed"
        error = repr(exc)
    elapsed = time.perf_counter() - started
    sampler.stop()
    after_io = process.io_counters()
    peak = max(sampler.peak, int(process.memory_info().rss))
    result = {
        "status": status,
        "error": error,
        "elapsed_seconds": float(elapsed),
        "peak_rss_bytes": peak,
        "read_bytes": max(0, int(after_io.read_bytes - before_io.read_bytes)),
        "write_bytes": max(0, int(after_io.write_bytes - before_io.write_bytes)),
        "rows": len(frame),
        "columns": len(frame.columns),
        "column_names": [str(value) for value in frame.columns[:80]],
        "schema_columns": [str(value) for value in frame.columns]
        if spec.get("result_path")
        else [],
        "result_preview": frame.iloc[:3, :20].to_dict(orient="records")
        if status == "passed"
        else [],
        "_frame": frame,
    }
    return result


def _write_result(
    frame: pd.DataFrame,
    result_path: str | Path,
    *,
    parity_keys: tuple[str, ...] = (),
) -> None:
    target = Path(result_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    output = frame
    if parity_keys and len(frame) * len(frame.columns) > 1_000_000:
        normalized = frame.reset_index(drop=False)
        if (
            "Date" in parity_keys
            and "Date" not in normalized.columns
            and isinstance(frame.index, pd.DatetimeIndex)
        ):
            normalized = normalized.rename(columns={normalized.columns[0]: "Date"})
        selected = [key for key in parity_keys if key in normalized.columns]
        if selected:
            output = normalized.loc[:, selected]
    output.to_pickle(target)


def worker_main() -> int:
    import gc

    spec = json.loads(sys.stdin.read())
    repetitions = max(1, int(spec.get("repetitions", 1)))
    warm = str(spec.get("cache_mode")) == "warm"
    connection = None
    connection_context = None
    try:
        if spec.get("engine") == "current_duckdb":
            _prepare_import_path(spec["repo_root"])
            _configure_environment(spec)
            from tp_core.analytics.config import DuckDBConfig
            from tp_core.analytics.connection import connect

            connection_context = connect(DuckDBConfig.from_env(read_only=True))
            connection = connection_context.__enter__()
        if warm:
            warmup = _measure_once(spec, connection)
            del warmup
            gc.collect()
        results: list[dict[str, Any]] = []
        for _ in range(repetitions):
            measured = _measure_once(spec, connection)
            frame = measured.pop("_frame")
            result_path = spec.get("result_path")
            if result_path:
                _write_result(
                    frame,
                    result_path,
                    parity_keys=tuple(str(value) for value in spec.get("parity_keys", ())),
                )
            results.append(measured)
            del frame, measured
        payload = {"status": "passed", "results": results}
    except Exception as exc:  # pragma: no cover - retained as a failed subprocess result
        payload = {"status": "failed", "error": repr(exc), "results": []}
    finally:
        if connection_context is not None:
            connection_context.__exit__(None, None, None)
    print("BENCHMARK_RESULT=" + json.dumps(payload, ensure_ascii=False, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    return parser


if __name__ == "__main__":
    arguments = build_parser().parse_args()
    raise SystemExit(worker_main() if arguments.worker else 2)


__all__ = ["execute_workload", "worker_main"]
