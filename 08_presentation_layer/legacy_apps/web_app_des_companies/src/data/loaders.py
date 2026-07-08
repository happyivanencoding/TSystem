"""Low-level parquet loaders.

Only this module is allowed to read raw files. Upper layers must not
reference parquet paths directly. Results are cached in memory for the
lifetime of the process.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from presentation_layer import PresentationDataRepository

from config import settings
from src.data.schemas import COL_DATE, EXPECTED_COLUMNS
from src.data.schemas_ciq import (
    CIQ_COL_BENCHMARK_ICB_SUPERSECTOR,
    CIQ_COL_DATE,
    CIQ_COL_ICB_SUPERSECTOR,
    CIQ_COL_ISIN,
    CIQ_MIN_REQUIRED,
)
from src.data.schemas_ptf import PTF_COL_DATE, PTF_COL_ISIN, PTF_COL_PTF, PTF_COL_WEIGHT


def _ciq_col_by_stripped(cols: list, want: str) -> str | None:
    """Colonne réelle si l'en-tête parquet diffère par espaces."""
    w = want.strip()
    for c in cols:
        if isinstance(c, str) and c.strip() == w:
            return c
    return None


def _icb_benchmark_code_to_label(path: Path) -> dict[int, str]:
    if not path.exists():
        raise FileNotFoundError(f"ICB mapping file not found: {path}")
    mdf = pd.read_csv(path)
    out: dict[int, str] = {}
    for _, r in mdf.iterrows():
        c = r.get("code")
        if pd.isna(c):
            continue
        lab = r.get("icb19_supersector")
        if pd.isna(lab):
            continue
        k = int(round(float(c)))
        out[k] = str(lab).strip()
    return out


def _apply_icb_benchmark_supersector_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Remplit ``ICQ_COL_ICB_SUPERSECTOR`` à partir du code Benchmark + ``ICB_mapping.csv``."""
    b_col = _ciq_col_by_stripped(list(df.columns), CIQ_COL_BENCHMARK_ICB_SUPERSECTOR)
    if not b_col:
        raise ValueError(
            f"Colonne « {CIQ_COL_BENCHMARK_ICB_SUPERSECTOR} » introuvable dans le parquet CIQ."
        )
    if b_col != CIQ_COL_BENCHMARK_ICB_SUPERSECTOR:
        df = df.rename(columns={b_col: CIQ_COL_BENCHMARK_ICB_SUPERSECTOR})
    cmap = _icb_benchmark_code_to_label(settings.ICB_MAPPING_CSV)
    codes = pd.to_numeric(df[CIQ_COL_BENCHMARK_ICB_SUPERSECTOR], errors="coerce").round()
    code_int = codes.astype("Int64")
    from_bench = code_int.map(cmap)
    orig = df[CIQ_COL_ICB_SUPERSECTOR]
    df[CIQ_COL_ICB_SUPERSECTOR] = from_bench.where(from_bench.notna(), orig)
    return df


def _load_parquet(path: Path) -> pd.DataFrame:
    """Read a parquet file and normalize its column order / date column."""
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    df = pd.read_parquet(path)

    # Ensure expected columns exist; ignore extras (forward-compatible)
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns {missing} in {path.name}")

    # Normalize date dtype (safety net, parquet already stores datetime64[ns])
    df[COL_DATE] = pd.to_datetime(df[COL_DATE], errors="coerce")

    # Reorder for predictable iteration
    return df[list(EXPECTED_COLUMNS)].reset_index(drop=True)


@lru_cache(maxsize=1)
def load_des() -> pd.DataFrame:
    """Return the descriptions dataset (cached singleton)."""
    return _load_parquet(settings.DES_PARQUET)


@lru_cache(maxsize=1)
def load_news() -> pd.DataFrame:
    """Return the 3-month news dataset (cached singleton)."""
    return _load_parquet(settings.NEWS_PARQUET)


@lru_cache(maxsize=1)
def load_screen_aggregate_ciq() -> pd.DataFrame:
    """Return the ``screen_aggregateCIQ`` panel dataset (cached singleton).

    Raw parquet has ``ISIN`` as index; we reset to have it as a regular column
    and normalize the Date column. Other columns are passed through.
    """
    df = PresentationDataRepository().screen(last_only=False)
    if df.index.name == CIQ_COL_ISIN or CIQ_COL_ISIN not in df.columns:
        df = df.reset_index()
    missing = [c for c in CIQ_MIN_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns {missing} in canonical screen_aggregate")
    df[CIQ_COL_DATE] = pd.to_datetime(df[CIQ_COL_DATE], errors="coerce")
    df = _apply_icb_benchmark_supersector_labels(df)
    return df.reset_index(drop=True)


# PTF : cache invalidé par mtime (fichier remplacé = nouveaux PTF visibles sans redémarrer le serveur).
_ptf_cache_mtime: float | None = None
_ptf_cache_frame: pd.DataFrame | None = None


def _normalize_ptf_excel_header(c: object) -> str:
    """En-tête Excel : retire le BOM et les espaces en bout, fusionne les espaces consécutifs, puis majuscules (pour les noms logiques)."""
    s = str(c).strip().lstrip("\ufeff").strip()
    s = " ".join(s.split())
    return s.upper()


def load_ptf() -> pd.DataFrame:
    """Charge ``PTF_IA_WORLD.xlsx`` : colonnes ``PTF``, ``Date``, ``Weight``, ``ISIN`` (noms normalisés)."""
    path = settings.PTF_XLSX
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")
    mtime = path.stat().st_mtime
    global _ptf_cache_mtime, _ptf_cache_frame
    if _ptf_cache_frame is not None and _ptf_cache_mtime == mtime:
        return _ptf_cache_frame
    raw = pd.read_excel(path, engine="openpyxl")
    # Noms logiques : PTF / Date / Weight / ISIN (variante WEIGHTS acceptée)
    colmap: dict[str, str] = {}
    for c in raw.columns:
        key = _normalize_ptf_excel_header(c)
        if key == "PTF":
            colmap[c] = PTF_COL_PTF
        elif key == "ISIN":
            colmap[c] = PTF_COL_ISIN
        elif key in ("WEIGHT", "WEIGHTS"):
            colmap[c] = PTF_COL_WEIGHT
        elif key == "DATE":
            colmap[c] = PTF_COL_DATE
    df = raw.rename(columns=colmap)
    for req in (PTF_COL_PTF, PTF_COL_ISIN, PTF_COL_WEIGHT):
        if req not in df.columns:
            seen = [_normalize_ptf_excel_header(x) for x in raw.columns]
            raise ValueError(
                f"Missing column {req} in {path.name}; "
                f"normalized headers: {seen}"
            )
    if PTF_COL_DATE in df.columns:
        df[PTF_COL_DATE] = pd.to_datetime(df[PTF_COL_DATE], errors="coerce")
    df[PTF_COL_ISIN] = df[PTF_COL_ISIN].astype(str).str.strip()
    df = df.reset_index(drop=True)
    _ptf_cache_frame = df
    _ptf_cache_mtime = mtime
    return df


