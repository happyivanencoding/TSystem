from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

from presentation_layer.portfolio.dashboard import PortfolioDashboard
from tp_core.workspace import BACKTEST_RUNS_DIR


RUN_DIR = BACKTEST_RUNS_DIR / "ad_hoc" / "min_te_score_ml_202505_140_160_20260701_120512"
SEC_LIST_PATH = RUN_DIR / "sec_list_min_te_score_ml_202505_140_160.parquet"
OPT_RESULT_PATH = RUN_DIR / "optimizer_result_min_te_score_ml_202505_140_160.parquet"
APP_ROOT = Path(__file__).resolve().parent
TEMPLATE_PATH = APP_ROOT / "analyse.xlsx"
OUTPUT_DIR = APP_ROOT / "outputs"
OUTPUT_PATH = OUTPUT_DIR / "analyse_min_te_score_ml_202505_dashboard.xlsx"
INPUT_DIR = OUTPUT_DIR / "_dashboard_inputs"


class LocalRepository:
    def __init__(self, screen: pd.DataFrame, returns: pd.DataFrame):
        self._screen = screen
        self._returns = returns

    def screen(self, last_only: bool = False):
        if last_only:
            max_date = self._screen["Date"].max()
            return self._screen[self._screen["Date"] == max_date].copy()
        return self._screen.copy()

    def returns(self):
        return self._returns.copy()

    def signals(self):
        return pd.DataFrame()


def _build_inputs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    sec = pd.read_parquet(SEC_LIST_PATH).copy()
    opt = pd.read_parquet(OPT_RESULT_PATH).copy()
    if "Benchmark Market Value Millions in EUR " not in opt.columns:
        if "Benchmark Market Value Millions in EUR" in opt.columns:
            opt["Benchmark Market Value Millions in EUR "] = opt["Benchmark Market Value Millions in EUR"]
        elif "Benchmark Market Value Millions in EUR BK" in opt.columns:
            opt["Benchmark Market Value Millions in EUR "] = opt["Benchmark Market Value Millions in EUR BK"]
    returns = pd.read_parquet(ROOT / "00_screen" / "returns.parquet")

    # dashboard.py expects snapshot Excel files with ISIN/Name/Weight.
    fund = sec[["ISIN", "Name", "Weight"]].copy()
    fund["Weight"] = pd.to_numeric(fund["Weight"], errors="coerce").fillna(0.0)
    fund["Weight"] = fund["Weight"] / fund["Weight"].sum()

    bench_col = "Weight in STOXX EUROPE 600"
    bench = opt[pd.to_numeric(opt[bench_col], errors="coerce").fillna(0.0) > 0].copy()
    bench["Weight"] = pd.to_numeric(bench[bench_col], errors="coerce").fillna(0.0)
    bench["Weight"] = bench["Weight"] / bench["Weight"].sum()
    bench = bench[["ISIN", "Name", "Weight"]].copy()

    fund_path = INPUT_DIR / "fund_min_te_score_ml_202505.xlsx"
    bench_path = INPUT_DIR / "benchmark_stoxx600_202505.xlsx"
    fund.to_excel(fund_path, index=False)
    bench.to_excel(bench_path, index=False)

    # Use optimizer_result as the screen snapshot so dashboard enrichment matches this run date.
    screen = opt.copy()
    screen["Date"] = pd.to_datetime(screen["Date"])
    prev = screen.copy()
    prev["Date"] = screen["Date"].min() - pd.offsets.MonthEnd(1)
    screen_for_dashboard = pd.concat([prev, screen], ignore_index=True)
    screen_for_dashboard = screen_for_dashboard.reset_index(drop=True)

    # dashboard.py requires these external workbooks even when only basic modules are exported.
    reco_path = INPUT_DIR / "reco_facto_minimal.xlsx"
    reco = pd.DataFrame(
        {
            "Value Avg Percentile": [1.0, 1.0],
            "Growth Avg Percentile": [1.0, 1.0],
            "Quality Avg Percentile": [1.0, 1.0],
            "Mom Avg Percentile": [1.0, 1.0],
            "LowVol Avg Percentile": [1.0, 1.0],
            "Dividend Avg Percentile": [1.0, 1.0],
            "Multi Avg Percentile": [1.0, 1.0],
            "Score ML": [1.0, 1.0],
        },
        index=[pd.Timestamp("2025-06-01"), pd.Timestamp("2025-07-01")],
    )
    with pd.ExcelWriter(reco_path) as writer:
        reco.to_excel(writer, sheet_name="facto_eu")

    transco_path = INPUT_DIR / "transco_isin_fonds_minimal.xlsx"
    if not transco_path.exists():
        transco = pd.DataFrame(
            {
                "Nom": [],
                "ISIN": [],
                "Exchange Country Region": [],
                "ICB19 Supersector": [],
            }
        )
        transco.to_excel(transco_path, index=False)

    return fund_path, bench_path, screen_for_dashboard, returns, reco_path, transco_path


def main():
    fund_path, bench_path, screen, returns, reco_path, transco_path = _build_inputs()
    dashboard = PortfolioDashboard(
        fund_config={"type": "excel_snap", "path": str(fund_path)},
        bench_config={"type": "excel_snap", "path": str(bench_path)},
        path_output=str(OUTPUT_PATH),
        wb_input=str(TEMPLATE_PATH),
        repository=LocalRepository(screen, returns),
        reco_facto=str(reco_path),
        transco_ISIN_Fonds=str(transco_path),
    )
    dashboard.export_to_excel(modules=["Analyse", "TopWorst", "Fonds", "Benchmark", "DATA"])
    print(f"OUTPUT {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
