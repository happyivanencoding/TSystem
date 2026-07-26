"""Table de correspondance : code numérique Benchmark ICB Supersector → libellé ICB19 (sans ISIN)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from presentation_layer import PresentationDataRepository

from presentation_layer.company_browser.settings import DATA_DIR
from presentation_layer.company_browser.data.schemas_ciq import CIQ_COL_DATE, CIQ_COL_ICB_SUPERSECTOR, CIQ_COL_ISIN

# Fichiers générés sous data/ (une ligne par code distinct quand le couple code+libellé est cohérent)
CODEBOOK_PARQUET: str = "benchmark_icb_supersector_codebook.parquet"
CODEBOOK_CSV: str = "benchmark_icb_supersector_codebook.csv"


def _col_by_stripped(cols: list[str], want: str) -> str | None:
    """Colonne réelle si l'en-tête a des espaces, comparaison par nom rogné."""
    w = want.strip()
    for c in cols:
        if c.strip() == w:
            return c
    return None


def _latest_per_isin(df: pd.DataFrame, date_col: str, isin_col: str) -> pd.DataFrame:
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d = d.sort_values(date_col, ascending=False)
    return d.drop_duplicates(subset=[isin_col], keep="first")


def build_bench_icb_supersector_codebook() -> pd.DataFrame:
    """Paires (code, libellé) uniques, dérivées du dernier point CIQ par ISIN."""
    ciq = PresentationDataRepository().screen(last_only=False)
    if ciq.index.name == CIQ_COL_ISIN or CIQ_COL_ISIN not in ciq.columns:
        ciq = ciq.reset_index()

    b_code = _col_by_stripped(list(ciq.columns), "Benchmark ICB Supersector")
    if not b_code or b_code not in ciq.columns:
        raise ValueError("Colonne « Benchmark ICB Supersector » introuvable dans le parquet CIQ.")
    if CIQ_COL_ICB_SUPERSECTOR not in ciq.columns:
        raise ValueError("Colonne « ICB19 Supersector » introuvable dans le parquet CIQ.")

    ciq_l = _latest_per_isin(ciq, CIQ_COL_DATE, CIQ_COL_ISIN)
    raw = ciq_l[[b_code, CIQ_COL_ICB_SUPERSECTOR]].copy()
    s = pd.to_numeric(raw[b_code], errors="coerce")
    out = pd.DataFrame(
        {
            "code": s.round().astype("Int64"),
            "icb19_supersector": raw[CIQ_COL_ICB_SUPERSECTOR].map(
                lambda x: str(x).strip()
                if pd.notna(x) and str(x).strip() and str(x).strip().lower() != "nan"
                else pd.NA
            ),
        }
    )
    out = out.dropna(subset=["code", "icb19_supersector"])
    out = out.drop_duplicates().sort_values("code", kind="mergesort").reset_index(drop=True)
    return out


def build_bench_icb_supersector_mapping() -> pd.DataFrame:
    """Alias : même que ``build_bench_icb_supersector_codebook``."""
    return build_bench_icb_supersector_codebook()


def write_des_ciq_mapping(
    out_dir: str | None = None, *, write_csv: bool = True
) -> tuple[str, str | None]:
    """Écrit le codebook sous data/ ; retourne (chemin .parquet, chemin .csv ou None)."""
    base = Path(out_dir) if out_dir else DATA_DIR
    base.mkdir(parents=True, exist_ok=True)
    df = build_bench_icb_supersector_codebook()
    p_parquet = base / CODEBOOK_PARQUET
    df.to_parquet(p_parquet, index=False)
    p_csv: str | None = None
    if write_csv:
        p = base / CODEBOOK_CSV
        df.to_csv(p, index=False, encoding="utf-8-sig")
        p_csv = str(p)
    return str(p_parquet), p_csv


build_des_ciq_mapping = build_bench_icb_supersector_codebook


if __name__ == "__main__":
    pp, pc = write_des_ciq_mapping()
    print("written:", pp)
    if pc:
        print("written:", pc)
    m = build_bench_icb_supersector_codebook()
    print("rows:", len(m), "cols:", list(m.columns))

