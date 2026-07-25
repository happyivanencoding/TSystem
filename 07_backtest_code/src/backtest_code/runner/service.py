"""Orchestration des runs simples et des batches."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from itertools import product
import importlib.util
import sys
import io
from pathlib import Path
import traceback
from types import ModuleType
from typing import Callable, Any

import pandas as pd

from backtest_code.app_logging import get_logger
from backtest_code.config.settings import AppSettings
from .artifacts import (
    RunArtifacts,
    create_run_directory,
    save_config_snapshot,
    save_dataframe,
    save_manifest,
    save_series,
    save_text,
)
from .validators import (
    ValidationReport,
    load_tabular_file,
    normalise_screen_columns,
    prepare_returns_dataframe,
    prepare_screen_dataframe,
    validate_settings,
)


ProgressCallback = Callable[[str], None]


@dataclass
class SingleRunResult:
    """Resultat d'un run individuel."""

    name: str
    status: str
    message: str
    mode: str
    artifacts: RunArtifacts
    validation: ValidationReport


@dataclass
class ServiceResult:
    """Resultat global renvoye a la GUI."""

    is_batch: bool
    runs: list[SingleRunResult] = field(default_factory=list)

    @property
    def latest_run(self) -> SingleRunResult | None:
        """Retourne le run le plus recent du lot."""

        if not self.runs:
            return None
        return self.runs[-1]


class _StreamRelay(io.TextIOBase):
    """Redirige stdout/stderr vers le logger et la GUI."""

    def __init__(self, forward: Callable[[str], None]) -> None:
        self._forward = forward
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        normalized = self._buffer.replace("\r", "\n")
        chunks = normalized.split("\n")
        self._buffer = chunks.pop() if chunks else ""
        for chunk in chunks:
            cleaned = chunk.strip()
            if cleaned:
                self._forward(cleaned)
        return len(text)

    def flush(self) -> None:
        cleaned = self._buffer.strip()
        if cleaned:
            self._forward(cleaned)
        self._buffer = ""


class BacktestService:
    """Service principal utilise par la GUI."""

    def __init__(self) -> None:
        self._engine_module: ModuleType | None = None
        self._prepared_screen_source_id: int | None = None
        self._prepared_screen: pd.DataFrame | None = None
        self._prepared_returns_source_id: int | None = None
        self._prepared_returns: pd.DataFrame | None = None
        self._monthly_base_cache: dict = {}
        self._benchmark_cache: dict = {}

    def _project_root(self) -> Path:
        """Retourne la racine du projet."""

        return Path(__file__).resolve().parents[3]

    def _engine_path(self) -> Path:
        """Retourne le chemin du moteur interne."""

        return self._project_root() / "BacktestEngine.py"

    def _load_engine_module(self) -> ModuleType:
        """Charge dynamiquement le module BacktestEngine interne."""

        if self._engine_module is not None:
            return self._engine_module

        project_root = self._project_root()
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        engine_path = self._engine_path()
        if not engine_path.exists():
            raise FileNotFoundError(f"BacktestEngine.py est introuvable : {engine_path}")

        spec = importlib.util.spec_from_file_location("internal_backtest_engine", engine_path)
        if spec is None or spec.loader is None:
            raise ImportError("Impossible de charger BacktestEngine.py")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._engine_module = module
        return module

    def inspect_inputs(
        self,
        screen_path: str,
        returns_path: str,
    ) -> tuple[dict[str, Any], ValidationReport]:
        """Charge les deux fichiers et retourne des informations utiles a la GUI."""

        report = ValidationReport()
        payload: dict[str, Any] = {
            "screen_benchmarks": [],
            "screen_metrics": [],
            "screen_columns": [],
            "returns_columns": [],
            "screen_rows": 0,
            "returns_rows": 0,
            "available_dates": [],
        }

        try:
            if screen_path:
                screen_df = prepare_screen_dataframe(load_tabular_file(screen_path))
                payload["screen_rows"] = len(screen_df)
                payload["screen_columns"] = list(screen_df.columns)
                payload["screen_benchmarks"] = sorted(
                    column.replace("Weight in ", "", 1)
                    for column in screen_df.columns
                    if column.startswith("Weight in ")
                )
                payload["screen_metrics"] = sorted(
                    column
                    for column in screen_df.columns
                    if pd.api.types.is_numeric_dtype(screen_df[column])
                    and not column.startswith("Weight in ")
                    and column not in {
                        "ESG_ANALYST_SCORE",
                        "Benchmark Market Value Millions in EUR ",
                        "Benchmark Market Value Millions in EUR",
                    }
                )
                if "Date" in screen_df.columns:
                    payload["available_dates"] = sorted(
                        pd.Timestamp(value).strftime("%Y-%m-%d")
                        for value in pd.to_datetime(screen_df["Date"], errors="coerce").dropna().unique()
                    )
        except Exception as exc:  # pragma: no cover - gestion defensive
            report.add_error(f"Inspection du screen impossible : {exc}")

        try:
            if returns_path:
                returns_df = prepare_returns_dataframe(load_tabular_file(returns_path))
                payload["returns_rows"] = len(returns_df)
                payload["returns_columns"] = [str(column) for column in returns_df.columns]
        except Exception as exc:  # pragma: no cover - gestion defensive
            report.add_error(f"Inspection des returns impossible : {exc}")

        return payload, report

    def run(
        self,
        settings: AppSettings,
        *,
        force_batch: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> ServiceResult:
        """Lance un run simple ou un batch selon la configuration."""

        if force_batch or settings.run.mode == "batch":
            return self._run_batch(settings, progress_callback=progress_callback)
        return ServiceResult(is_batch=False, runs=[self._run_single(settings, progress_callback=progress_callback)])

    def _emit(
        self,
        message: str,
        *,
        logger,
        progress_callback: ProgressCallback | None,
        collector: list[str],
    ) -> None:
        """Diffuse un message vers toutes les sorties voulues."""

        collector.append(message)
        logger.info(message)
        if progress_callback is not None:
            progress_callback(message)

    def _build_run_label(self, settings: AppSettings) -> str:
        """Construit un nom lisible pour un run."""

        metrics_label = "-".join(settings.run.metrics) if settings.run.metrics else "metric"
        start_date = settings.run.start_date or "no-date"
        return f"{settings.run.mode}_{settings.run.bench}_{metrics_label}_{start_date}"

    def _parse_score_pivot(self, value: Any) -> Any:
        """Convertit un score pivot texte en float si possible."""

        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return text

    def _prepare_screen_for_engine(self, screen_df: pd.DataFrame, engine_module: ModuleType) -> pd.DataFrame:
        """Prepare le screen avant instanciation du moteur."""

        source_id = id(screen_df)
        if (
            self._prepared_screen_source_id == source_id
            and self._prepared_screen is not None
        ):
            return self._prepared_screen

        frame = prepare_screen_dataframe(screen_df)
        if hasattr(engine_module, "drop_duplicates_keep_less_missing"):
            duplicate_mask = frame.reset_index().duplicated(subset=["ISIN", "Date"], keep=False)
            if duplicate_mask.any():
                frame = engine_module.drop_duplicates_keep_less_missing(frame)
        prepared = normalise_screen_columns(frame)
        self._prepared_screen_source_id = source_id
        self._prepared_screen = prepared
        self._monthly_base_cache.clear()
        self._benchmark_cache.clear()
        return prepared

    def _prepare_returns_for_engine(self, returns_df: pd.DataFrame) -> pd.DataFrame:
        """Prepare les rendements une seule fois pour un batch partage."""

        source_id = id(returns_df)
        if (
            self._prepared_returns_source_id == source_id
            and self._prepared_returns is not None
        ):
            return self._prepared_returns
        prepared = prepare_returns_dataframe(returns_df)
        self._prepared_returns_source_id = source_id
        self._prepared_returns = prepared
        self._benchmark_cache.clear()
        return prepared

    def _create_artifact_container(self, run_dir: Path) -> RunArtifacts:
        """Instancie les chemins des artefacts standards."""

        return RunArtifacts(
            run_dir=run_dir,
            config_snapshot=run_dir / "config_snapshot.yaml",
            manifest=run_dir / "manifest.yaml",
            sec_list=run_dir / "sec_list.parquet",
            exclusions=run_dir / "exclusions.parquet",
            perf_ptf=run_dir / "perf_ptf.parquet",
            perf_bench=run_dir / "perf_bench.parquet",
            plot=run_dir / "plot.html",
            run_log=run_dir / "run.log",
        )

    def _run_single(
        self,
        settings: AppSettings,
        *,
        progress_callback: ProgressCallback | None = None,
        screen_df: pd.DataFrame | None = None,
        returns_df: pd.DataFrame | None = None,
    ) -> SingleRunResult:
        """Execute un run individuel."""

        user_name = settings.user.name or settings.app.default_user
        logger = get_logger(user_name)
        log_lines: list[str] = []
        run_label = self._build_run_label(settings)
        run_dir = create_run_directory(user_name, run_label)
        artifacts = self._create_artifact_container(run_dir)
        save_config_snapshot(settings, run_dir)

        try:
            if screen_df is None:
                screen_df = load_tabular_file(settings.paths.screen)
            if returns_df is None:
                returns_df = load_tabular_file(settings.paths.returns)
        except Exception as exc:
            summary = f"{type(exc).__name__}: {exc}"
            details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
            report = ValidationReport()
            report.add_error(f"Lecture des fichiers impossible : {summary}")
            self._emit(
                f"Lecture des fichiers impossible : {summary}",
                logger=logger,
                progress_callback=progress_callback,
                collector=log_lines,
            )
            self._emit(
                f"Traceback complet :\n{details}",
                logger=logger,
                progress_callback=progress_callback,
                collector=log_lines,
            )
            save_text("\n".join(log_lines), artifacts.run_log)
            save_manifest(
                run_dir,
                {
                    "status": "failed",
                    "message": summary,
                    "mode": settings.run.mode,
                    "bench": settings.run.bench,
                    "metrics": settings.run.metrics,
                },
            )
            return SingleRunResult(
                name=run_label,
                status="failed",
                message=summary,
                mode=settings.run.mode,
                artifacts=artifacts,
                validation=report,
            )

        validation = validate_settings(settings, screen_df=screen_df, returns_df=returns_df)
        if not validation.is_valid:
            self._emit(
                "Validation bloquante detectee. Le run est annule.",
                logger=logger,
                progress_callback=progress_callback,
                collector=log_lines,
            )
            if validation.as_text():
                self._emit(
                    validation.as_text(),
                    logger=logger,
                    progress_callback=progress_callback,
                    collector=log_lines,
                )
            save_text("\n".join(log_lines), artifacts.run_log)
            save_manifest(
                run_dir,
                {
                    "status": "failed",
                    "message": "Validation bloquante",
                    "mode": settings.run.mode,
                    "bench": settings.run.bench,
                    "metrics": settings.run.metrics,
                },
            )
            return SingleRunResult(
                name=run_label,
                status="failed",
                message="Validation bloquante",
                mode=settings.run.mode,
                artifacts=artifacts,
                validation=validation,
            )

        engine_module = self._load_engine_module()
        prepared_screen = self._prepare_screen_for_engine(screen_df, engine_module)
        prepared_returns = self._prepare_returns_for_engine(returns_df)

        relay = _StreamRelay(
            lambda line: self._emit(
                line,
                logger=logger,
                progress_callback=progress_callback,
                collector=log_lines,
            )
        )

        self._emit(
            f"Demarrage du run : {run_label}",
            logger=logger,
            progress_callback=progress_callback,
            collector=log_lines,
        )

        try:
            with redirect_stdout(relay), redirect_stderr(relay):
                builder = engine_module.PtfBuilder(
                    screen=prepared_screen,
                    returns=prepared_returns,
                    bench=settings.run.bench,
                    percentile=settings.run.percentile,
                    metrics=settings.run.metrics if len(settings.run.metrics) > 1 else settings.run.metrics[0],
                    ptf_name=settings.run.ptf_name,
                    ponderation=settings.run.ponderation,
                    esg_exclusion=settings.run.esg_exclusion,
                    cut_mkt_cap=settings.run.cut_mkt_cap,
                    liste_noire=settings.paths.liste_noire or None,
                    reco_secto=settings.run.reco_secto,
                    reco_facto=settings.run.reco_facto,
                    score_neutral=settings.run.score_neutral,
                    weight_neutral=settings.run.weight_neutral,
                    Top=settings.run.top,
                    top_mandatory=settings.run.top_mandatory,
                    multiprocessing=False,
                    mode_monthly_prod=settings.run.mode_monthly_prod,
                    output_dir=settings.paths.output_dir or None,
                    cap_weight_threshold=settings.run.cap_weight_threshold,
                    score_pivot_esg=self._parse_score_pivot(settings.run.score_pivot_esg),
                    score_pivot_esg_path=settings.paths.score_pivot_esg_path or None,
                    copy_inputs=False,
                    monthly_base_cache=self._monthly_base_cache,
                    benchmark_cache=self._benchmark_cache,
                )

                builder.generic_histo_seclist(
                    start_date=pd.to_datetime(settings.run.start_date),
                    freq_rebal=settings.run.freq_rebal,
                    screen_start_date=settings.run.screen_start_date,
                    fill_method=settings.run.fill_method,
                )
                builder.backtest(
                    max_weight=settings.run.max_weight,
                    sector_neutral=settings.run.sector_neutral,
                )
                builder.backtest_get_bench_perf(prepared_screen, builder.start_date, settings.run.bench)
                builder.backtest_plot_ptf_bench(
                    title=run_label,
                    save_path=str(artifacts.plot),
                    show_plot=False,
                )

            artifacts.sec_list = save_dataframe(builder.sec_list_historical, artifacts.sec_list)
            artifacts.exclusions = save_dataframe(builder.list_exclusion_histo, artifacts.exclusions)
            artifacts.perf_ptf = save_series(builder.perf_ptf, artifacts.perf_ptf)
            artifacts.perf_bench = save_series(builder.perf_bench, artifacts.perf_bench)
            if getattr(builder, "buy_list", None) is not None and not builder.buy_list.empty:
                artifacts.extra["buy_list"] = save_dataframe(builder.buy_list, run_dir / "buy_list.xlsx")  # type: ignore[arg-type]

            save_text("\n".join(log_lines), artifacts.run_log)
            save_manifest(
                run_dir,
                {
                    "status": "success",
                    "message": "Run termine avec succes",
                    "mode": settings.run.mode,
                    "bench": settings.run.bench,
                    "metrics": settings.run.metrics,
                    "start_date": settings.run.start_date,
                },
            )
            return SingleRunResult(
                name=run_label,
                status="success",
                message="Run termine avec succes",
                mode=settings.run.mode,
                artifacts=artifacts,
                validation=validation,
            )

        except Exception as exc:  # pragma: no cover - execution dependante des donnees
            summary = f"{type(exc).__name__}: {exc}"
            details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
            self._emit(
                f"Echec du run : {summary}",
                logger=logger,
                progress_callback=progress_callback,
                collector=log_lines,
            )
            self._emit(
                f"Traceback complet :\n{details}",
                logger=logger,
                progress_callback=progress_callback,
                collector=log_lines,
            )
            save_text("\n".join(log_lines), artifacts.run_log)
            save_manifest(
                run_dir,
                {
                    "status": "failed",
                    "message": summary,
                    "mode": settings.run.mode,
                    "bench": settings.run.bench,
                    "metrics": settings.run.metrics,
                    "start_date": settings.run.start_date,
                },
            )
            return SingleRunResult(
                name=run_label,
                status="failed",
                message=summary,
                mode=settings.run.mode,
                artifacts=artifacts,
                validation=validation,
            )

    def _build_batch_settings(self, settings: AppSettings) -> list[AppSettings]:
        """Genere la liste des configurations unitaires a partir du batch."""

        benches = settings.batch.benches or [settings.run.bench]
        metrics = settings.batch.metrics or settings.run.metrics or [""]
        percentiles = settings.batch.percentiles or [settings.run.percentile]
        start_dates = settings.batch.start_dates or [settings.run.start_date]
        top_values = settings.batch.top_values or [settings.run.top]

        generated: list[AppSettings] = []
        for bench, metric, percentile, start_date, top_value in product(
            benches,
            metrics,
            percentiles,
            start_dates,
            top_values,
        ):
            clone = settings.copy()
            clone.run.mode = "batch"
            clone.run.bench = bench
            clone.run.metrics = [metric] if isinstance(metric, str) else list(metric)
            clone.run.percentile = float(percentile)
            clone.run.start_date = str(start_date)
            clone.run.top = bool(top_value)
            generated.append(clone)
        return generated

    def _run_batch(
        self,
        settings: AppSettings,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> ServiceResult:
        """Execute un batch sequentiel de runs."""

        logger = get_logger(settings.user.name or settings.app.default_user)
        generated_settings = self._build_batch_settings(settings)
        results: list[SingleRunResult] = []
        total = len(generated_settings)
        try:
            shared_screen_df = load_tabular_file(settings.paths.screen)
            shared_returns_df = load_tabular_file(settings.paths.returns)
        except Exception:
            shared_screen_df = None
            shared_returns_df = None

        for index, one_settings in enumerate(generated_settings, start=1):
            if progress_callback is not None:
                progress_callback(f"Lancement du batch {index}/{total}")
            logger.info("Lancement du batch %s/%s", index, total)
            results.append(
                self._run_single(
                    one_settings,
                    progress_callback=progress_callback,
                    screen_df=shared_screen_df,
                    returns_df=shared_returns_df,
                )
            )

        return ServiceResult(is_batch=True, runs=results)
