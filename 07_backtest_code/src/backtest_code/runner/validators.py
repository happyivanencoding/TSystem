"""Validation des donnees et inspection des fichiers d'entree."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.api.types import is_numeric_dtype

from backtest_code.config.settings import AppSettings


WEIGHT_PREFIX = "Weight in "
PARQUET_INDEX_COLUMNS = {"__index_level_0__"}
CANONICAL_COLUMN_ALIASES: dict[str, list[str]] = {
    "Benchmark Market Value Millions in EUR ": [
        "Benchmark Market Value Millions in EUR ",
        "Benchmark Market Value Millions in EUR",
    ],
    " Benchmark ICB Supersector ": [
        " Benchmark ICB Supersector ",
        "Benchmark ICB Supersector",
    ],
    " Benchmark ICB Industry ": [
        " Benchmark ICB Industry ",
        "Benchmark ICB Industry",
    ],
}


@dataclass
class ValidationMessage:
    """Message de validation detaille."""

    level: str
    text: str


@dataclass
class ValidationReport:
    """Rapport de validation consolide."""

    errors: list[ValidationMessage] = field(default_factory=list)
    warnings: list[ValidationMessage] = field(default_factory=list)
    infos: list[ValidationMessage] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Indique si le rapport ne contient aucune erreur bloquante."""

        return not self.errors

    def add_error(self, text: str) -> None:
        """Ajoute une erreur."""

        self.errors.append(ValidationMessage(level="error", text=text))

    def add_warning(self, text: str) -> None:
        """Ajoute un avertissement."""

        self.warnings.append(ValidationMessage(level="warning", text=text))

    def add_info(self, text: str) -> None:
        """Ajoute une information."""

        self.infos.append(ValidationMessage(level="info", text=text))

    def as_text(self) -> str:
        """Retourne une vue texte compacte."""

        lines: list[str] = []
        for label, messages in (
            ("ERREUR", self.errors),
            ("WARNING", self.warnings),
            ("INFO", self.infos),
        ):
            for message in messages:
                lines.append(f"[{label}] {message.text}")
        return "\n".join(lines)


@dataclass
class DatasetInspection:
    """Informations utiles pour aider l'utilisateur a configurer un run."""

    file_path: str
    rows: int
    columns: list[str]
    detected_benchmarks: list[str] = field(default_factory=list)
    metric_candidates: list[str] = field(default_factory=list)
    available_dates: list[str] = field(default_factory=list)
    has_esg: bool = False
    has_sector_icb19: bool = False
    has_sector_icb11: bool = False
    has_market_cap: bool = False


def load_tabular_file(file_path: str | Path) -> pd.DataFrame:
    """Charge un fichier tabulaire supporte."""

    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"Format de fichier non supporte : {path.suffix}")


def normalise_screen_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les alias attendus par le moteur si necessaire."""

    frame = dataframe.copy()
    for canonical, aliases in CANONICAL_COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in frame.columns:
                if canonical not in frame.columns:
                    frame[canonical] = frame[alias]
                break
    return frame


def prepare_screen_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Prepare le screen pour le moteur de calcul."""

    frame = normalise_screen_columns(dataframe)
    if "Date" in frame.columns:
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    if frame.index.name != "ISIN" and "ISIN" in frame.columns:
        frame = frame.set_index("ISIN")
    return frame


def prepare_returns_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Prepare la matrice de returns."""

    frame = dataframe.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        if "Date" in frame.columns:
            frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
            frame = frame.set_index("Date")
        else:
            first_column = frame.columns[0]
            converted = pd.to_datetime(frame[first_column], errors="coerce")
            if converted.notna().sum() > 0:
                frame[first_column] = converted
                frame = frame.set_index(first_column)
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame.sort_index()
    return frame


def detect_benchmarks(columns: list[str]) -> list[str]:
    """Detecte les benchmarks presents dans un screen."""

    benches: list[str] = []
    for column in columns:
        if column.startswith(WEIGHT_PREFIX):
            benches.append(column.replace(WEIGHT_PREFIX, "", 1))
    return benches


def detect_metric_candidates(dataframe: pd.DataFrame) -> list[str]:
    """Detecte les colonnes numeriques candidates pour les metrics."""

    excluded_exact = {
        "ESG_ANALYST_SCORE",
        "Benchmark Market Value Millions in EUR ",
        "Benchmark Market Value Millions in EUR",
    }
    candidates: list[str] = []
    for column in dataframe.columns:
        if column in excluded_exact:
            continue
        if column.startswith(WEIGHT_PREFIX):
            continue
        if column in {"Date", "Company SEDOL"}:
            continue
        if is_numeric_dtype(dataframe[column]):
            candidates.append(column)
    return sorted(candidates)


def detect_metric_candidates_from_columns(columns: list[str], numeric_columns: set[str]) -> list[str]:
    excluded_exact = {
        "ESG_ANALYST_SCORE",
        "Benchmark Market Value Millions in EUR ",
        "Benchmark Market Value Millions in EUR",
    }
    candidates: list[str] = []
    for column in columns:
        if column in excluded_exact:
            continue
        if column.startswith(WEIGHT_PREFIX):
            continue
        if column in {"Date", "Company SEDOL"}:
            continue
        if column in numeric_columns:
            candidates.append(column)
    return sorted(candidates)


def _columns_with_aliases(columns: list[str]) -> list[str]:
    result = list(columns)
    for canonical, aliases in CANONICAL_COLUMN_ALIASES.items():
        if canonical in result:
            continue
        if any(alias in result for alias in aliases):
            result.append(canonical)
    return result


def _parquet_columns_and_numeric(path: Path) -> tuple[int, list[str], set[str]]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    parquet_file = pq.ParquetFile(path)
    schema = parquet_file.schema_arrow
    columns: list[str] = []
    numeric_columns: set[str] = set()
    for field in schema:
        name = str(field.name)
        if name in PARQUET_INDEX_COLUMNS:
            continue
        columns.append(name)
        if pa.types.is_integer(field.type) or pa.types.is_floating(field.type) or pa.types.is_decimal(field.type):
            numeric_columns.add(name)
    return int(parquet_file.metadata.num_rows), columns, numeric_columns


def inspect_screen_parquet(path: Path) -> DatasetInspection:
    rows, columns, numeric_columns = _parquet_columns_and_numeric(path)
    columns = _columns_with_aliases(columns)
    available_dates: list[str] = []
    if "Date" in columns:
        dates = pd.to_datetime(pd.read_parquet(path, columns=["Date"])["Date"], errors="coerce").dropna()
        available_dates = sorted({value.strftime("%Y-%m-%d") for value in dates})
    return DatasetInspection(
        file_path=str(path),
        rows=rows,
        columns=columns,
        detected_benchmarks=detect_benchmarks(columns),
        metric_candidates=detect_metric_candidates_from_columns(columns, numeric_columns),
        available_dates=available_dates,
        has_esg="ESG_ANALYST_SCORE" in columns,
        has_sector_icb19=" Benchmark ICB Supersector " in columns,
        has_sector_icb11=" Benchmark ICB Industry " in columns,
        has_market_cap="Benchmark Market Value Millions in EUR " in columns,
    )


def inspect_returns_parquet(path: Path) -> DatasetInspection:
    rows, columns, _ = _parquet_columns_and_numeric(path)
    frame = pd.read_parquet(path, columns=[])
    dates = pd.to_datetime(frame.index, errors="coerce").dropna()
    return DatasetInspection(
        file_path=str(path),
        rows=rows,
        columns=columns,
        available_dates=[
            value.strftime("%Y-%m-%d")
            for value in dates
            if isinstance(value, pd.Timestamp) and pd.notna(value)
        ],
    )


def inspect_screen(dataframe: pd.DataFrame, file_path: str) -> DatasetInspection:
    """Construit une inspection de screen."""

    frame = normalise_screen_columns(dataframe)
    available_dates: list[str] = []
    if "Date" in frame.columns:
        dates = pd.to_datetime(frame["Date"], errors="coerce").dropna()
        available_dates = sorted({value.strftime("%Y-%m-%d") for value in dates})
    columns = list(frame.columns)
    return DatasetInspection(
        file_path=file_path,
        rows=len(frame),
        columns=columns,
        detected_benchmarks=detect_benchmarks(columns),
        metric_candidates=detect_metric_candidates(frame),
        available_dates=available_dates,
        has_esg="ESG_ANALYST_SCORE" in columns,
        has_sector_icb19=" Benchmark ICB Supersector " in columns,
        has_sector_icb11=" Benchmark ICB Industry " in columns,
        has_market_cap="Benchmark Market Value Millions in EUR " in columns,
    )


def inspect_returns(dataframe: pd.DataFrame, file_path: str) -> DatasetInspection:
    """Construit une inspection de returns."""

    frame = prepare_returns_dataframe(dataframe)
    available_dates = [
        value.strftime("%Y-%m-%d")
        for value in frame.index
        if isinstance(value, pd.Timestamp) and pd.notna(value)
    ]
    return DatasetInspection(
        file_path=file_path,
        rows=len(frame),
        columns=[str(column) for column in frame.columns],
        available_dates=available_dates,
    )


def inspect_file_pair(screen_path: str, returns_path: str) -> tuple[DatasetInspection | None, DatasetInspection | None, ValidationReport]:
    """Charge et inspecte les deux fichiers principaux."""

    report = ValidationReport()
    screen_info: DatasetInspection | None = None
    returns_info: DatasetInspection | None = None

    if screen_path:
        try:
            screen_file = Path(screen_path)
            if screen_file.suffix.lower() == ".parquet":
                screen_info = inspect_screen_parquet(screen_file)
            else:
                screen_df = load_tabular_file(screen_file)
                screen_info = inspect_screen(screen_df, screen_path)
        except Exception as exc:  # pragma: no cover - gestion defensive
            report.add_error(f"Impossible de lire le screen : {exc}")

    if returns_path:
        try:
            returns_file = Path(returns_path)
            if returns_file.suffix.lower() == ".parquet":
                returns_info = inspect_returns_parquet(returns_file)
            else:
                returns_df = load_tabular_file(returns_file)
                returns_info = inspect_returns(returns_df, returns_path)
        except Exception as exc:  # pragma: no cover - gestion defensive
            report.add_error(f"Impossible de lire les returns : {exc}")

    return screen_info, returns_info, report


def _score_pivot_requires_lookup(score_pivot_esg: Any) -> bool:
    """Indique si le score pivot demande un acces au fichier pivot."""

    if score_pivot_esg is None:
        return False
    if isinstance(score_pivot_esg, (int, float)):
        return False
    text = str(score_pivot_esg).strip()
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return True
    return False


def validate_settings(
    settings: AppSettings,
    screen_df: pd.DataFrame | None = None,
    returns_df: pd.DataFrame | None = None,
) -> ValidationReport:
    """Valide la configuration avant execution."""

    report = ValidationReport()
    screen_path = settings.paths.screen.strip()
    returns_path = settings.paths.returns.strip()

    if not screen_path:
        report.add_error("Le chemin du screen est obligatoire.")
    elif not Path(screen_path).exists():
        report.add_error("Le fichier screen n'existe pas.")

    if not returns_path:
        report.add_error("Le chemin des returns est obligatoire.")
    elif not Path(returns_path).exists():
        report.add_error("Le fichier returns n'existe pas.")

    if not settings.run.bench:
        report.add_error("Le benchmark doit etre renseigne.")

    if not settings.run.metrics:
        report.add_error("Au moins une metric doit etre selectionnee.")

    if not settings.run.start_date:
        report.add_error("La date de debut est obligatoire.")

    if settings.run.fill_method not in {"drift", "copy"}:
        report.add_error("La valeur de fill_method doit etre 'drift' ou 'copy'.")

    if settings.run.score_neutral not in {"ICB 11", "ICB 19"}:
        report.add_error("score_neutral doit valoir 'ICB 11' ou 'ICB 19'.")

    if settings.run.weight_neutral not in {"ICB 11", "ICB 19"}:
        report.add_error("weight_neutral doit valoir 'ICB 11' ou 'ICB 19'.")

    if settings.run.mode_monthly_prod and not settings.paths.output_dir.strip():
        report.add_error("output_dir est obligatoire en mode production.")

    if settings.paths.output_dir and not Path(settings.paths.output_dir).exists():
        report.add_warning("Le repertoire de sortie n'existe pas encore ; il sera cree si possible.")

    if _score_pivot_requires_lookup(settings.run.score_pivot_esg):
        if not settings.paths.score_pivot_esg_path.strip():
            report.add_error("score_pivot_esg_path est obligatoire pour resoudre un score pivot ESG textuel.")
        elif not Path(settings.paths.score_pivot_esg_path).exists():
            report.add_error("Le dossier score_pivot_esg_path n'existe pas.")

    if screen_df is not None:
        frame = prepare_screen_dataframe(screen_df)
        columns = list(frame.columns)
        required_columns = ["Date", "Company SEDOL", "Benchmark Market Value Millions in EUR "]
        for column in required_columns:
            if column not in columns:
                report.add_error(f"Colonne screen manquante : {column}")

        bench_column = f"{WEIGHT_PREFIX}{settings.run.bench}"
        if bench_column not in columns:
            report.add_error(f"Colonne benchmark manquante : {bench_column}")

        sector_column = " Benchmark ICB Supersector " if settings.run.weight_neutral == "ICB 19" else " Benchmark ICB Industry "
        if sector_column not in columns:
            report.add_error(f"Colonne secteur manquante : {sector_column}")

        if (settings.run.esg_exclusion > 0 or settings.run.score_pivot_esg is not None) and "ESG_ANALYST_SCORE" not in columns:
            report.add_error("La colonne ESG_ANALYST_SCORE est obligatoire pour le filtrage ESG.")

        for metric in settings.run.metrics:
            if metric not in columns and metric != "Multi Avg Percentile":
                report.add_error(f"La metric '{metric}' est absente du screen.")

    if returns_df is not None:
        frame = prepare_returns_dataframe(returns_df)
        if not isinstance(frame.index, pd.DatetimeIndex):
            report.add_error("Les returns doivent etre indexes par date.")
        if frame.empty:
            report.add_error("Le fichier de returns est vide.")

    if settings.run.mode_monthly_prod and settings.run.ptf_name == "PTF TEST" and settings.run.bench not in {"SP500", "MSCI US", "STOXX EUROPE 600"}:
        report.add_warning("Le nommage auto production ne couvre pas explicitement ce benchmark.")

    return report
