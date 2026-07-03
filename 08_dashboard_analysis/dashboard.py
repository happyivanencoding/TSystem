# =========================================================================
# ARCHITECTURE DU MODULE : PortfolioDashboard
# =========================================================================
# PortfolioDashboard
# ├── Initialisation (__init__)
# │   ├── _parse_fund_data()   : Parse les données du portefeuille (Excel/Parquet)
# │   ├── _parse_bench_data()  : Parse les données du benchmark
# │   ├── _align_snapshots()   : Synchronise PTF et Bench sur la même date
# │   └── _load_core_data()    : Charge CIQ, Facto, Screen
# │
# ├── Propriétés Lazy (Chargement à la demande pour optimiser la mémoire)
# │   ├── df_returns           : Rendements journaliers (canonical returns.parquet)
# │   ├── news_raw             : News FactSet brutes
# │   └── news_scored          : News avec score de sentiment
# │
# ├── Modules d'Analyse (Génération des métriques et visuels)
# │   ├── generate_vl_analysis()         : Calcule et trace l'historique VL
# │   ├── generate_sentiment_analysis()  : Calcule et trace le score de sentiment
# │   ├── compute_risk_metrics()         : Beta, Tracking Error, Volatilité
# │   ├── build_fund_full()              : Vue complète PTF/Bench (scores, CIQ, etc.)
# │   ├── build_screen_final()           : Screen factoriel final avec deltas
# │   ├── compute_performance()          : Performances 1W, 1M, YTD, 1Y (Top/Worst)
# │   ├── get_news_flow()                : Flux d'actualités récentes FactSet
# │   └── get_stock_deviation()          : Écarts de pondération PTF vs Bench
# │
# ├── Attribution de Performance
# │   ├── compute_bhb_attribution()      : BHB classique (Tables 1–4, méthode indépendante)
# │   │   ├── _bhb_group()               : Allocation/Sélection/Interaction par groupe
# │   │   ├── _factor_attribution()      : Régression OLS → Table 3 Facteurs
# │   │   └── _specific_return()         : Résidus → Table 4 Stock Picking
# │   ├── compute_ols_attribution()      : OLS unifié strict (Tables 1–4 sans double-comptage)
# │   │   └── _unified_ols_attribution() : Régression unique Secteur+Région+Facteurs
# │   └── compute_ml_bhb()               : Table 5 — BHB par quintile ML (indépendant)
# │
# └── Exportation
#     ├── export_to_excel()              : Orchestrateur d'export vers le template
#     │   ├── _export_data()             : Onglet [DATA]
#     │   ├── _export_fonds()            : Onglet [Fonds]
#     │   ├── _export_benchmark()        : Onglet [Benchmark]
#     │   ├── _export_analyse()          : Onglet [Analyse] (Risque, Déviations)
#     │   ├── _export_newsflow()         : Onglet [NewsFlow]
#     │   ├── _export_topworst()         : Onglet [TopWorst Perf]
#     │   ├── _export_analyse_2()        : Onglet [Analyse 2] (Images VL & Sentiment)
#     │   ├── _export_attribution()      : Onglet [Attribution]   — BHB classique
#     │   ├── _export_attribution_ml()   : Onglet [Attribution ML]   — BHB ML
#     │   └── _export_attribution_ols()  : Onglet [Attribution OLS] — OLS unifié strict
#     │
#     └── generate_pdf_report()          : Génération du rapport PDF final (Externe)
# =========================================================================

import pandas as pd
import copy
import numpy as np
import os
import sys
import warnings
from pathlib import Path
from math import isnan
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from openpyxl import load_workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Alignment
from openpyxl.drawing.image import Image as OpenpyxlImage

import xlwings as xw

from matplotlib.patches import Patch
from pandas.errors import SettingWithCopyWarning

warnings.simplefilter(action='ignore', category=SettingWithCopyWarning)
warnings.simplefilter(action='ignore', category=UserWarning)

_TP_ROOT = Path(__file__).resolve().parents[1]
if str(_TP_ROOT) not in sys.path:
    sys.path.insert(0, str(_TP_ROOT))

from tp_core.data_sources import RETURNS_PATH as CANONICAL_RETURNS_PATH
from tp_core.data_sources import SCREEN_AGGREGATE_PATH
from tp_core.data_sources import TRANSCO_FACTSET_ICB_PATH
from presentation_layer import PresentationDataRepository

class PortfolioDashboard:
    """
    Classe principale pour la génération du tableau de bord de gestion actions.
    Intègre l'analyse cross-sectionnelle (snapshot) et l'analyse historique (VL).
    """

    # -------------------------------------------------------------------------
    # Chemins par défaut
    # -------------------------------------------------------------------------
    _DEFAULT_PATHS = {
        "wb_input":       r"\\groupe-ufg.com\Commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\2_TBB_EQUITY\Template\TBB_Gestion_Action.xlsx",
        "returns":        str(CANONICAL_RETURNS_PATH),
        "ciq":            str(SCREEN_AGGREGATE_PATH),
        "news":           r"\\groupe-ufg.com\Commun\Prive\GestionAM\Ingenierie_Financiere\PROD\MAJ_news_factset_daily\0_DATA\Base_news_facset_BRUTE.parquet",
        "news_scored":    r"\\groupe-ufg.com\Commun\Prive\GestionAM\Ingenierie_Financiere\PROD\MAJ_news_factset_daily\0_DATA\current_scored_news2.parquet",
        "reco_facto":     r"\\groupe-ufg.com\Commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\0_PTF_BLOOM\reco_secto_facto.xlsx",
        "transco":        str(TRANSCO_FACTSET_ICB_PATH),
        "transco_ISIN_Fonds": r"\\groupe-ufg.com\commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\0_PTF_BLOOM\Transco_ISIN_Fonds.xlsx"
    }

    _DICT_FACTEURS = {
        'Value Avg Percentile':  "Score Value",
        'Growth Avg Percentile': "Score Growth",
        'Quality Avg Percentile':"Score Quality",
        'Mom Avg Percentile':    "Score Momentum",
        'LowVol Avg Percentile': "Score Volatility",
        'Dividend Avg Percentile': "Score Dividend",
        'Multi Avg Percentile':  "Score Multifacteur",
        'Score ML': 'Score ML'
    }

    _ATTRIB_FACTORS = [
        "Score Value",
        "Score Growth",
        "Score Quality",
        "Score Momentum",
        "Score Volatility"
    ]

    _ICB_SUPERSECTORS_MAPPING = {
        1:"Auto & Parts", 2:"Banks", 3:"Basic Resources", 4:"Chemicals",
        5:"Construction", 6:"Financial Services", 7:"Food, Beverage & Tobacco",
        8:"Health Care", 9:"Industrial Goods & Services", 10:"Insurance",
        11:"Media", 12:"Energy", 13:"Personal & Household Goods",
        14:"Real Estate", 15:"Retail", 16:"Technology",
        17:"Telecommunications", 18:"Travel & Leisure", 19:"Utilities"
    }

    # Pour Excel
    _MODULE_MAP = {

        "Analyse":           ("Analyse",          "_export_analyse"),
        "NewsFlow":          ("NewsFlow",         "_export_newsflow"),
        "TopWorst":          ("TopWorst Perf",    "_export_topworst"),
        "Analyse 2":         ("Analyse 2",        "_export_analyse_2"),
        "Attribution":       ("Attribution",      "_export_attribution"),      # BHB classique
        "Attribution ML":    ("Attribution ML",   "_export_attribution_ml"),   # BHB ML
        "Attribution MF":    ("Attribution MF",   "_export_attribution_mf"),   # BHB MF
        "Attribution OLS":   ("Attribution OLS",  "_export_attribution_ols"),  # OLS unifié strict

        # Ecriture à la fin avant que les autres onglets finissent la génération des données
        "Fonds":             ("Fonds",            "_export_fonds"),
        "Benchmark":         ("Benchmark",        "_export_benchmark"),
        "DATA":              ("DATA",             "_export_data"),
    }

    # -------------------------------------------------------------------------
    # Initialisation & Parsing des configurations
    # -------------------------------------------------------------------------
    def __init__(self, fund_config: dict, bench_config: dict, path_output: str, **kwargs):
        """
        Initialise le dashboard.
   
        fund_config attendu :
        - type: 'excel_snap', 'excel_ts', ou 'parquet_ts'
        - path: chemin du fichier
        - sheet: nom de l'onglet (si excel)
        - fonds_name: filtre du nom de fonds (si parquet_ts)
       
        bench_config attendu :
        - type: 'excel_snap' ou 'parquet_ts'
        - path: chemin du fichier
        - fonds_name: filtre du nom de l'indice (si parquet_ts)
        """
        self.path_output = path_output
        self.repository = kwargs.pop("repository", PresentationDataRepository())
        self.paths = {**self._DEFAULT_PATHS, **kwargs}

        # Attributs lazy (initialisés à None)
        self._df_returns   = None
        self._news_raw     = None
        self._news_scored  = None

        # Image de l'analyse VL et Sentiment
        self.vl_image_path = None
        self.sentiment_image_path = None

        print("⏳ Chargement et parsing des inputs...")
        self._parse_fund_data(fund_config)
        self._parse_bench_data(bench_config)
        self._align_snapshots()

        # Chargement immédiat des données légères externes (Screen, CIQ, etc.)
        self._load_core_data()

        print("✅ PortfolioDashboard initialisé.")
        print(f"   → Output  : {os.path.basename(path_output)}")


    def _parse_fund_data(self, config: dict):
        """Parse les données du portefeuille selon le type fourni."""
        c_type = config.get("type")
        path = config.get("path")

        self.fund_ts = None # Historique par défaut vide

        if c_type == "excel_snap":
            # Cas 1 : Excel classique un seul point dans le temps
            df = pd.read_excel(path)
            self.fund = df.rename(columns={"Name": "LIBELLE", "Weight": "%ACTIF"})
            self.fund_name = "Portfolio"

        elif c_type == "excel_ts":
            # Cas 2 : Excel séries temporelles (format analyse_histo)
            sheet = config.get("sheet")
            df = pd.read_excel(path, sheet_name=sheet, header=0, usecols="A:D")
            df.columns = ["Date", "ISIN", "%ACTIF", "Valorisation"]
            df["Date"] = pd.to_datetime(df["Date"])
            self.fund_ts = df
            self.fund_name = sheet

        elif c_type == "parquet_ts":
            # Cas 3 : Parquet séries temporelles
            fonds_name = config.get("fonds_name")
            df = pd.read_parquet(path)
            df = df[df["Fonds Name"] == fonds_name].copy()
            df = df.rename(columns={"datePos": "Date", "ident": "ISIN", "weight": "%ACTIF"})
            df["Date"] = pd.to_datetime(df["Date"])
            # Pour simuler la valorisation si absente, on utilise le poids comme base
            if "Valorisation" not in df.columns:
                df["Valorisation"] = df["%ACTIF"]
            self.fund_ts = df[df['type'] == 'equity']
            self.fund_name = fonds_name
        else:
            raise ValueError(f"Type de fund_config inconnu : {c_type}")

    def _parse_bench_data(self, config: dict):
        """Parse les données du benchmark selon le type fourni."""
        c_type = config.get("type")
        path = config.get("path")

        self.bench_ts = None

        if c_type == "excel_snap":
            df = pd.read_excel(path)
            self.bench_df = df.rename(columns={
                "MAIN_SECURITY_CODE": "ISIN", "Weight": "%ACTIF", "Name": "LIBELLE"
            })
            self.bench_name = "Benchmark"

        elif c_type == "parquet_ts":
            fonds_name = config.get("fonds_name")
            df = pd.read_parquet(path)
            df = df[df["Fonds Name"] == fonds_name].copy()
            df = df.rename(columns={"datePos": "Date", "ident": "ISIN", "weight": "%ACTIF"})
            df["Date"] = pd.to_datetime(df["Date"])
            self.bench_ts = df[df['type'] == 'equity']
            self.bench_name = fonds_name
        else:
            raise ValueError(f"Type de bench_config inconnu : {c_type}")

    def _align_snapshots(self):
        """
        Extrait le dernier snapshot disponible pour le dashboard classique.
        Si ts (Time Series) existe pour les deux, on prend la dernière date commune.
        Stocke également le snapshot de début de période (fund_start / bench_start)
        utilisé par compute_bhb_attribution() et compute_ols_attribution().
        """
        if self.fund_ts is not None and self.bench_ts is not None:
            # Intersection des dates disponibles entre PTF et Benchmark
            common_dates = self.fund_ts["Date"].dropna().unique()
            common_dates = np.intersect1d(common_dates, self.bench_ts["Date"].dropna().unique())

            if len(common_dates) == 0:
                raise ValueError("Aucune date commune entre le Portfolio TS et le Benchmark TS.")

            latest_date = pd.to_datetime(common_dates[-1])
            print(f"   → Date de snapshot retenue pour l'analyse : {latest_date.strftime('%Y-%m-%d')}")

            # Extraction du snapshot courant (fin de période)
            self.fund = self.fund_ts[self.fund_ts["Date"] == latest_date].copy()
            if "LIBELLE" not in self.fund.columns: self.fund["LIBELLE"] = "N/A"

            self.bench_df = self.bench_ts[self.bench_ts["Date"] == latest_date].copy()
            if "LIBELLE" not in self.bench_df.columns: self.bench_df["LIBELLE"] = "N/A"

            # --- Snapshot de début de période pour l'attribution BHB ---
            # On prend la date commune la plus proche d'il y a 1 mois
            target_start = latest_date - pd.DateOffset(months=1)
            common_dt    = pd.to_datetime(common_dates)
            start_date   = common_dt[common_dt <= target_start].max() if (common_dt <= target_start).any() else common_dt[0]
            print(f"   → Date de début BHB (≈ 1M) : {start_date.strftime('%Y-%m-%d')}")

            self.fund_start   = self.fund_ts[self.fund_ts["Date"] == start_date].copy()
            self.bench_start  = self.bench_ts[self.bench_ts["Date"] == start_date].copy()
            self.attrib_start = start_date
            self.attrib_end   = latest_date

        else:
            # Si un des deux n'est pas TS, on extrait le max date de celui qui l'est
            if self.fund_ts is not None:
                latest_date = self.fund_ts["Date"].max()
                self.fund = self.fund_ts[self.fund_ts["Date"] == latest_date].copy()
                if "LIBELLE" not in self.fund.columns: self.fund["LIBELLE"] = "N/A"

            if self.bench_ts is not None:
                latest_date = self.bench_ts["Date"].max()
                self.bench_df = self.bench_ts[self.bench_ts["Date"] == latest_date].copy()
                if "LIBELLE" not in self.bench_df.columns: self.bench_df["LIBELLE"] = "N/A"

            # Snapshots de début non disponibles en mode snapshot statique
            self.fund_start   = None
            self.bench_start  = None
            self.attrib_start = None
            self.attrib_end   = None


    def _load_core_data(self):
        """Charge les données de base (Screen, CIQ, Transco) disponibles rapidement."""
        screen_agg = self.repository.screen(last_only=False)
        screen_agg.reset_index(inplace=True)
        screen_agg = screen_agg.rename(columns=self._DICT_FACTEURS)

        # Mettre Reco Analyst en bon format
        if "Reco Analyst" not in screen_agg.columns:
            screen_agg["Reco Analyst"] = pd.NA
        screen_agg["Reco Analyst"] = screen_agg["Reco Analyst"].astype(str)
        if "Unnamed: 0" in screen_agg.columns:
            screen_agg.drop(columns=["Unnamed: 0"], inplace=True)
        screen_agg["Reco Analyst"] = screen_agg["Reco Analyst"].str.split("(", expand=True)[0].str.strip()
        screen_agg = screen_agg.drop_duplicates(
                                                subset=["Date", "ISIN"],
                                                keep="first"
                                                )


        self.screen_agg   = screen_agg.copy(deep=True)
        self.spot_date    = screen_agg["Date"].unique()[-1]
        self.last_date    = screen_agg["Date"].unique()[-2]

        self.df_reco_facto = pd.read_excel(
            self.paths["reco_facto"], sheet_name="facto_eu", index_col=0
        )
        self.df_reco_facto = self.df_reco_facto.rename(columns=self._DICT_FACTEURS)

        self.last_screen  = screen_agg[screen_agg['Date'] == self.spot_date]

    # -------------------------------------------------------------------------
    # Lazy loading
    # -------------------------------------------------------------------------
    @property
    def df_returns(self) -> pd.DataFrame:
        if self._df_returns is None:
            print("⏳ Chargement des rendements (canonical returns.parquet)...")
            self._df_returns = self.repository.returns()
            self._df_returns.index = pd.to_datetime(self._df_returns.index)
            print("✅ Rendements chargés.")
        return self._df_returns

    @property
    def news_raw(self) -> pd.DataFrame:
        if self._news_raw is None:
            print("⏳ Chargement des news FactSet...")
            self._news_raw = pd.read_parquet(self.paths["news"])
            print("✅ News chargées.")
        return self._news_raw

    @property
    def news_scored(self) -> pd.DataFrame:
        """Chargement lazy de la base de news scorées (sentiment)."""
        if self._news_scored is None:
            print("⏳ Chargement des news scorées...")
            self._news_scored = pd.read_parquet(self.paths["news_scored"])
            print("✅ News scorées chargées.")
        return self._news_scored

    # =========================================================================
    # MODULE : Analyse Historique VL
    # =========================================================================

    def generate_vl_analysis(self, save_filename="temp_vl_chart.png"):
        """
        Calcule et trace la VL historique du portefeuille et du benchmark si
        les données Time Series sont disponibles pour les deux.
        """
        if self.fund_ts is None or self.bench_ts is None:
            print("ℹ️ Module VL ignoré : Données Time Series manquantes pour PTF ou BENCH.")
            return False

        print("⏳ Calcul de l'historique VL en cours...")
        returns_df = self.df_returns

        # --- Recherche de la première date commune ---
        common_dates = np.intersect1d(self.fund_ts["Date"].dropna().unique(), self.bench_ts["Date"].dropna().unique())

        if len(common_dates) == 0:
            print("⚠️ Impossible de calculer VL : Aucune date commune entre le portefeuille et le benchmark.")
            return False

        # La date de départ est la plus ancienne date en commun
        start_date = pd.to_datetime(common_dates[0])
        print(f"   → Date de départ alignée pour le calcul VL : {start_date.strftime('%Y-%m-%d')}")

        # 1. Calcul VL PTF (Tronqué pour commencer à la date commune)
        fund_ts_filtered = self.fund_ts[self.fund_ts["Date"] >= start_date]
        vl_ptf_raw = fund_ts_filtered.groupby("Date")["Valorisation"].sum().sort_index()
        ptf_vl = (vl_ptf_raw / vl_ptf_raw.iloc[0]) * 100

        # 2. Setup Benchmark Drift à la date de départ commune
        bench_snap = self.bench_ts[self.bench_ts["Date"] == start_date][["ISIN", "%ACTIF"]].copy()

        # Sécurité additionnelle (normalement toujours faux car on a pris common_dates)
        if bench_snap.empty:
            print(f"⚠️ Impossible de calculer VL Bench : Pas de position à la date {start_date}")
            return False
   
        bench_snap["weight_norm"] = bench_snap["%ACTIF"] / bench_snap["%ACTIF"].sum()

        sedol_map = self.last_screen.set_index("ISIN")["Company SEDOL"].to_dict()
        bench_snap["SEDOL"] = bench_snap["ISIN"].map(sedol_map)
   
        avail_sedols = returns_df.columns.tolist()
        bench_snap = bench_snap[bench_snap["SEDOL"].isin(avail_sedols)].copy()
        bench_snap["weight_norm"] = bench_snap["weight_norm"] / bench_snap["weight_norm"].sum()
   
        # 3. Calcul VL Bench par drift
        sedols = bench_snap["SEDOL"].tolist()
        date_range = ptf_vl.index
        ret_slice = returns_df.loc[returns_df.index.isin(date_range), sedols].copy()
        ret_slice = ret_slice.reindex(date_range).fillna(0)
   
        weights_series = bench_snap.set_index("SEDOL")["weight_norm"]
        weighted_ret = ret_slice.multiply(weights_series, axis=1).sum(axis=1)
        bench_vl = (1 + weighted_ret).cumprod() * 100
        bench_vl.name = "Benchmark_VL"
   
        # 4. Génération du graphique
        fig = self._plot_ytd_comparison(ptf_vl, bench_vl)
   
        # 5. Sauvegarde
        save_path = os.path.join(os.path.dirname(self.path_output), save_filename)
        fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
   
        self.vl_image_path = save_path
        print(f"✅ Analyse VL générée et sauvegardée : {save_filename}")
        return True


    def _plot_ytd_comparison(self, ptf_vl, bench_vl, figsize=(14, 5)):
        """Méthode interne pour tracer le graphique de VL."""
        common_idx = ptf_vl.index.intersection(bench_vl.index)
        ptf_vl   = ptf_vl.reindex(common_idx)
        bench_vl = bench_vl.reindex(common_idx)

        ptf_return_pct   = ptf_vl.iloc[-1] - 100
        bench_return_pct = bench_vl.iloc[-1] - 100
        ratio = ptf_vl / bench_vl

        plt.style.use("default")
        fig = plt.figure(figsize=figsize)
        gs  = fig.add_gridspec(
            nrows=2, ncols=2, height_ratios=[3, 2], width_ratios=[1, 1],
            hspace=0.35, wspace=0.35
        )

        ax1       = fig.add_subplot(gs[:, 0])
        ax2       = fig.add_subplot(gs[0, 1])
        ax_ratio  = fig.add_subplot(gs[1, 1])

        fig.patch.set_facecolor("white")
        for ax in [ax1, ax2, ax_ratio]:
            ax.set_facecolor("white")
            for spine in ax.spines.values(): spine.set_edgecolor("#cccccc")

        # Courbes
        ax1.plot(ptf_vl.index, ptf_vl - 100, color="#00a8b5", linewidth=1.8, label=self.fund_name)
        ax1.plot(bench_vl.index, bench_vl - 100, color="#c82060", linewidth=1.8, linestyle="--", label=self.bench_name)
        ax1.axhline(0, color="#cccccc", linewidth=0.8, linestyle="--")

        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.2f}%"))
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m/%Y"))
        for label in ax1.get_xticklabels():
            label.set_rotation(30)
            label.set_ha("right")

        ax1.set_title(f"Historique (Rebasé)\n({common_idx[0].strftime('%d/%m/%Y')} – {common_idx[-1].strftime('%d/%m/%Y')})", fontsize=9, fontweight="bold")
        ax1.legend(fontsize=7, loc='upper left')

        # Barres Mensuelles
        def safe_monthly_return(cum_series):
            rets = cum_series.pct_change() * 100
            rets.iloc[0] = cum_series.iloc[0] - 100.0
            return rets

        monthly_ptf_cum   = ptf_vl.resample("ME").last()
        monthly_bench_cum = bench_vl.resample("ME").last()
        monthly_ptf_ret   = safe_monthly_return(monthly_ptf_cum)
        monthly_bench_ret = safe_monthly_return(monthly_bench_cum)

        x = np.arange(len(monthly_ptf_ret))
        width = 0.35

        ax2.bar(x - width / 2, monthly_ptf_ret.values, width, label="PTF", color="#00a8b5", alpha=0.85)
        ax2.bar(x + width / 2, monthly_bench_ret.values, width, label="Bench", color="#c82060", alpha=0.85)
        ax2.set_xticks(x)
        ax2.set_xticklabels([d.strftime("%m/%y") for d in monthly_ptf_ret.index], rotation=30, ha="right", fontsize=7)
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1f}%"))
        ax2.set_title("Décomposition mensuelle", fontsize=9, fontweight="bold")
        ax2.legend(fontsize=6, loc="upper left")

        # Ratio
        ax_ratio.plot(ratio.index, ratio, color="#7b5ea7", linewidth=1.5)
        ax_ratio.axhline(1.0, color="#cccccc", linewidth=0.8, linestyle="--")
        ax_ratio.fill_between(ratio.index, ratio, 1.0, where=(ratio >= 1.0), interpolate=True, color="#00a8b5", alpha=0.15)
        ax_ratio.fill_between(ratio.index, ratio, 1.0, where=(ratio < 1.0), interpolate=True, color="#c82060", alpha=0.15)

        ax_ratio.set_ylabel("Ratio PTF/Bench", fontsize=7)
        ax_ratio.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m/%Y"))
        for label in ax_ratio.get_xticklabels():
            label.set_rotation(30)
            label.set_ha("right")

        fig.align_ylabels([ax2, ax_ratio])
        plt.tight_layout(pad=2.0)
        return fig

    # =========================================================================
    # MODULE : Analyse Sentiment (News)
    # =========================================================================

    def generate_sentiment_analysis(self, days=30, save_filename="temp_sentiment_chart.png"):
        """
        Calcule et trace la distribution des sentiments des news pour le portefeuille.
        """
        if not hasattr(self, "fund_full"):
            self.build_fund_full()

        print("⏳ Calcul de l'analyse des sentiments en cours...")

        # 1. Chargement et préparation de dfscored
        df_scored = self.news_scored.copy()
        df_scored['story_time'] = pd.to_datetime(df_scored['story_time'], utc=True)

        # 2. Filtrage temporel (par défaut sur les 3 derniers jours)
        cutoff_date = pd.Timestamp.today(tz='UTC') - pd.Timedelta(days=days)
        df_scored = df_scored[df_scored['story_time'] >= cutoff_date]

        # 3. Filtrage des news StreetAccount et sur les ISIN du portefeuille
        if 'headlines' in df_scored.columns:
            df_scored = df_scored[~df_scored['headlines'].str.contains('StreetAccount', na=False)]

        isin_list = self.fund_full["ISIN"].unique()
        df_scored = df_scored[df_scored["ISIN"].isin(isin_list)]

        if df_scored.empty:
            print("⚠️ Aucune news scorée trouvée pour la période et le portefeuille donnés.")
            return False

        df_scored = df_scored.merge(
            self.fund_full[["ISIN", "LIBELLE"]],
            on="ISIN",
            how="left"
        ).rename(columns={"LIBELLE": "securityName"})

        # Déduplication basée sur headlines et ISIN
        if 'headlines' in df_scored.columns:
            df_scored = df_scored.drop_duplicates(subset=["headlines", "ISIN"])

        # 5. Génération du graphique
        fig, _ = self._plot_sentiment_score_bars(
            wordcloud_news=df_scored,
            sort_by="total",  
            top_n=15,          
            title=f"Sentiment des News (Derniers {days} jours)"
        )

        # 6. Sauvegarde locale temporaire
        save_path = os.path.join(os.path.dirname(self.path_output), save_filename)
        fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)

        self.sentiment_image_path = save_path
        print(f"✅ Analyse Sentiment générée et sauvegardée : {save_filename}")
        return True

    def _plot_sentiment_score_bars(
        self,
        wordcloud_news: pd.DataFrame,
        positive_labels=('Positive','Positif','POS','positive'),
        negative_labels=('Negative','Négatif','NEG','negative'),
        neutral_bucket_name="Other",
        top_n=15,
        sort_by="total",  
        figsize=(12, 8),
        title="Score de Sentiment",
        show_counts=True,
        label_fontsize=10,
    ):
        """Méthode interne pour tracer les barres de sentiment."""
        df = wordcloud_news.copy()
        df["ISIN"] = df["ISIN"].astype(str).str.strip()

        # # Suppression de doublons
        df = df.loc[:, ~df.columns.duplicated()].copy()
           
        df["securityName"] = df["securityName"].astype(str).str.strip()

        # Sécurité si la colonne sentiment n'existe pas
        if "sentiment" not in df.columns:
            df["sentiment"] = "Neutral"

        df["sentiment_norm"] = df["sentiment"].astype(str).str.lower().str.strip()

        pos_set = set(s.lower() for s in positive_labels)
        neg_set = set(s.lower() for s in negative_labels)

        df["sentiment_mapped"] = df["sentiment_norm"].map(
            lambda s: "Positive" if s in pos_set else ("Negative" if s in neg_set else neutral_bucket_name)
        )

        counts = df.groupby(["ISIN","sentiment_mapped"]).size().unstack(fill_value=0)
        for c in ("Positive","Negative",neutral_bucket_name):
            if c not in counts.columns:
                counts[c] = 0
        counts["total"] = counts[["Positive","Negative"]].sum(axis=1)

        # score = (Pos - Neg) / (Pos + Neg)
        pos = counts["Positive"].astype(float)
        neg = counts["Negative"].astype(float)
        denom = pos + neg
        score = np.divide(pos - neg, denom, out=np.zeros_like(pos, dtype=float), where=denom!=0)
        counts["score"] = score

        # Proportions (parmi les non-neutres)
        share_pos = np.divide(pos, denom, out=np.zeros_like(pos, dtype=float), where=denom!=0)
        share_neg = np.divide(neg, denom, out=np.zeros_like(neg, dtype=float), where=denom!=0)
        counts["share_pos"] = share_pos
        counts["share_neg"] = share_neg
        counts["non_neutral"] = denom

        # Label d'affichage
        label_df = df.groupby("ISIN")["securityName"].agg(lambda s: s.mode().iloc[0] if len(s.mode())>0 else s.iloc[0])
        counts = counts.merge(label_df.rename("label_name"), left_index=True, right_index=True)

        # Filtre et tri
        counts = counts[counts["total"] > 0].copy()

        if sort_by == "total":
            order_idx = counts["total"].sort_values(ascending=False).index
        elif sort_by == "non_neutral":
            order_idx = counts["non_neutral"].sort_values(ascending=False).index
        elif sort_by == "score":
            order_idx = counts["score"].abs().sort_values(ascending=False).index
        else:
            order_idx = counts["non_neutral"].sort_values(ascending=False).index

        counts = counts.reindex(order_idx)
        counts = counts.head(top_n)

        # Tracé
        fig, ax = plt.subplots(figsize=figsize)
        y = np.arange(len(counts))
        labels = counts["label_name"].values

        ax.set_xlim(-1.20, 1.20)
        ax.axvline(0, color="#222", lw=0.8)

        color_pos = "#2E7D32"  # vert
        color_neg = "#C23B3B"  # rouge

        for i, row in enumerate(counts.itertuples(index=False)):
            s = float(row.score)
            L = abs(s)
            sp = float(row.share_pos)
            sn = float(row.share_neg)

            if L == 0:
                if show_counts:
                    nn = int(row.non_neutral)
                    ax.text(1.07, y[i], f"Nombre de news : {nn}",
                            va="center", ha="left", fontsize=8, color="#666", transform=ax.get_yaxis_transform())
                continue

            if s >= 0:
                # Barre droite
                ax.barh(y[i], width=L*sn, left=0,     color=color_neg, alpha=0.9, edgecolor="none")
                ax.barh(y[i], width=L*sp, left=L*sn,  color=color_pos, alpha=0.9, edgecolor="none")
                ax.text(L + 0.02, y[i], f"{s:+.2f}", va="center", ha="left", fontsize=9, color="#333")
            else:
                # Barre gauche
                ax.barh(y[i], width=L*sn, left=-L,            color=color_neg, alpha=0.9, edgecolor="none")
                ax.barh(y[i], width=L*sp, left=-L + L*sn,     color=color_pos, alpha=0.9, edgecolor="none")
                ax.text(-L - 0.02, y[i], f"{s:+.2f}", va="center", ha="right", fontsize=9, color="#333")

            if show_counts:
                nn = int(row.non_neutral)
                ax.text(1.07, y[i], f"Nombre de news : {nn}",
                        va="center", ha="left", fontsize=8, color="#666", transform=ax.get_yaxis_transform())

        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=label_fontsize)
        ax.set_xlabel("Score de Sentiment", fontsize=11)
        ax.set_title(title, fontsize=13)
        ax.grid(True, axis="x", linestyle="--", alpha=0.3)

        # Inversion pour avoir le plus grand EN HAUT
        ax.invert_yaxis()

        legend_handles = [
            Patch(facecolor=color_pos, edgecolor='none', label="% News positive"),
            Patch(facecolor=color_neg, edgecolor='none', label="% News négative"),
        ]
        ax.legend(
            handles=legend_handles,
            loc="upper left",
            bbox_to_anchor=(-0.3, 1.10),
            borderaxespad=0.0,
            frameon=False
        )

        plt.tight_layout()
        return fig, counts

    # =========================================================================
    # MÉTHODES PRIVÉES
    # =========================================================================

    @staticmethod
    def _normalize_by_sector(df: pd.DataFrame, colonnes: list,
                            secteur_colonne: str) -> pd.DataFrame:
        """Normalise les scores factoriels par secteur ICB (rang percentile → 0-10)."""
        df_transforme = df.copy()
        for secteur in df[secteur_colonne].unique():
            secteur_df = df[df[secteur_colonne] == secteur]
            for colonne in colonnes:
                rangs = secteur_df[colonne].rank(pct=True)
                df_transforme.loc[df[secteur_colonne] == secteur, colonne] = rangs * 10
        return df_transforme

    @staticmethod
    def _compute_bench_returns(bench: pd.DataFrame, returns: pd.DataFrame,
                            col_weights: str = "Weight",
                            col_sort: str = "SEDOL") -> pd.Series:
        """Calcule la série de rendements pondérés du benchmark (rebalancement backward)."""
        bench = bench[bench[col_sort].notna()]
        list_sedol = list(set(bench[col_sort].values).intersection(set(returns.columns)))
        returns    = returns[list_sedol]
        bench      = bench[bench[col_sort].isin(list_sedol)].drop_duplicates()
        returns    = returns.loc[:, ~returns.columns.duplicated()]
        returns.sort_index(axis=1, inplace=True)
        weights    = bench.sort_values(by=col_sort)[col_weights]
        weights_t  = np.zeros(shape=(len(returns), len(weights)))
        for i in range(len(returns) - 1, -1, -1):
            if i == len(returns) - 1:
                weights_t[i] = weights.values
            else:
                weights_t[i] = weights_t[i+1] / (1 + returns.iloc[i, :].values)
                weights_t[i] = weights_t[i] / weights_t[i].sum()
        return (returns * weights_t).sum(axis=1)

    @staticmethod
    def _compute_te_and_contrib(
        w_ptf: pd.DataFrame,
        w_bench: pd.DataFrame,
        cov: pd.DataFrame,
        *,
        isin_col: str = "ISIN",
        sedol_col: str = "SEDOL",
        col_weight: str = "weight",
        return_full_active_universe: bool = True  # include off-benchmark
    ):
        """
        Compute TE and Euler contributions per security.
        Returns: te (float), contrib_df (DataFrame indexed by ISIN with 'contrib_te').

        Assumes 'cov' is keyed by sedol_col (index = columns = SEDOL).
        """

        # 1) Build the union universe (portfolio ∪ benchmark) on a consistent key set.
        cols_needed = [isin_col, sedol_col, col_weight]
        w_ptf_ = w_ptf[cols_needed].drop_duplicates(subset=[isin_col]).copy()
        w_bch_ = w_bench[cols_needed].drop_duplicates(subset=[isin_col]).copy()

        # 2) Merge weights side-by-side on ISIN to avoid accidental row replication.
        uni = (w_ptf_[[isin_col, sedol_col, col_weight]]
            .rename(columns={col_weight: "w_ptf"}))
        uni = uni.merge(w_bch_[[isin_col, sedol_col, col_weight]]
                        .rename(columns={col_weight: "w_bench"}),
                        on=[isin_col, sedol_col], how="outer")
        uni[["w_ptf","w_bench"]] = uni[["w_ptf","w_bench"]].fillna(0.0)
        uni["active"] = uni["w_ptf"] - uni["w_bench"]

        # 3) Keep only names that exist in the covariance matrix (by SEDOL).
        in_cov = uni[sedol_col].isin(cov.index)
        uni = uni.loc[in_cov].copy()

        # Optional: if you want the 'benchmark-only' universe, set return_full_active_universe=False
        if not return_full_active_universe:
            # This reproduces your benchmark-left behavior (not recommended if you want off-benchmark names)
            uni = uni.loc[uni["w_bench"] != 0].copy()

        # 4) Align with covariance
        uni = uni.set_index(sedol_col)
        Sigma = cov.loc[uni.index, uni.index].values
        a = uni["active"].to_numpy()

        # 5) TE and Euler contributions
        quad = float(a.T @ Sigma @ a)
        te = float(np.sqrt(max(quad, 0.0)))

        if te == 0.0:
            uni["contrib_te"] = 0.0
        else:
            marg = Sigma @ a                # (Σ a)
            uni["contrib_te"] = (a * marg) / te

        # 6) Return contributions by ISIN (group in case of accidental duplicates)
        contrib_df = (uni.reset_index()[[sedol_col, isin_col, "contrib_te"]]
                        .groupby(isin_col, as_index=True, sort=False)["contrib_te"]
                        .sum()
                        .to_frame())

        # Sanity check (should be true up to tiny float error)
        # assert np.isclose(contrib_df["contrib_te"].sum(), te, rtol=1e-10, atol=1e-12)

        return te, contrib_df

    # =========================================================================
    # MÉTHODES PUBLIQUES — Calcul des modules d'analyse
    # =========================================================================

    @staticmethod
    def ewma_covariance(returns_df: pd.DataFrame,
                        lam: float = 0.94,
                        demean: bool = False,
                        init: str = "sample") -> pd.DataFrame:
        """
        RiskMetrics-style multivariate EWMA covariance:
        S_t = λ S_{t-1} + (1-λ) x_t x_t^T  (with optional de-meaning)
       
        Parameters
        ----------
        returns_df : pd.DataFrame
            T×N returns, index = dates, columns = securities (your SEDOLs).
            Make sure columns are unique and aligned with your weights.
        lam : float
            Decay factor λ in (0,1). Higher λ = longer memory (slower reaction).
        demean : bool
            If True, subtract global sample mean from each column before recursion.
            Often set to False at daily frequency.
        init : {"sample","zero"}
            Initialization for S_0.
       
        Returns
        -------
        Sigma : pd.DataFrame (N×N)
            EWMA covariance (per-period units, NOT annualized).
        """
        R = returns_df.copy()
        R = R.dropna(how="any")

        cols = R.columns
        X = R.values  # T×N
        T, N = X.shape

        if demean:
            mu = X.mean(axis=0, keepdims=True)
            X = X - mu

        # Initialize S_0
        if init == "sample" and T > 1:
            S = np.cov(X, rowvar=False, bias=False)  # N×N
        else:
            S = np.zeros((N, N), dtype=float)

        one_minus_lam = 1.0 - lam
        for t in range(T):
            x = X[t:t+1, :]           # 1×N
            S = lam * S + one_minus_lam * (x.T @ x)

        return pd.DataFrame(S, index=cols, columns=cols)


    def compute_risk_metrics(self, freq: int = 252,
                            col_isin: str = "ISIN",
                            col_sedol: str = "Company SEDOL",
                            col_weight: str = "weight",
                            col_weight_ptf: str = "%ACTIF",
                            method_cov = "ewma",
                            cov_lambda = 0.94):
        """
        Calcule les métriques de risque : Beta, Tracking Error, Contrib TE,
        Vol portefeuille, Vol benchmark.
        """
        returns = self.df_returns

        # Préparation des poids portefeuille depuis le snapshot
        ptf = self.fund.copy().rename(columns={"Name": "LIBELLE", "Weight": col_weight_ptf})
        ptf = ptf[["ISIN", "LIBELLE", col_weight_ptf]]
        ptf["ISIN"] = ptf["ISIN"].str.split(" ").str[0]

        # Ajout du SEDOL
        ptf = ptf.merge(
            self.last_screen[["ISIN", col_sedol]].drop_duplicates(subset=["ISIN"]),
            on="ISIN",
            how="left"
        )

        # Préparation des poids benchmark depuis le snapshot
        bench = self.last_screen.copy()
        bench = bench.merge(
            self.bench_df[["ISIN", "%ACTIF"]].drop_duplicates(subset=["ISIN"]),
            on="ISIN", how="inner"
        )
        bench.rename(columns={"%ACTIF": col_weight}, inplace=True)
        bench = bench[bench[col_weight] > 0]

        ptf[col_weight_ptf] = ptf[col_weight_ptf].fillna(0)
        bench[col_weight]   = bench[col_weight].fillna(0)
        bench["Weight"]     = bench[col_weight]

        ptf_w = ptf.rename(columns={col_weight_ptf: col_weight}).copy()
        ind_w = bench.copy()

        ptf_w = ptf_w[ptf_w[col_sedol].isin(returns.columns)]
        ind_w  = ind_w[ind_w[col_sedol].isin(returns.columns)]
        ptf_w[col_weight] = ptf_w[col_weight] / ptf_w[col_weight].sum()
        ind_w[col_weight] = ind_w[col_weight] / ind_w[col_weight].sum()

        # Calcul de la série de rendements du marché (benchmark)
        market_df = ind_w.dropna(subset=[col_sedol]).copy()
        market_df[col_weight] /= market_df[col_weight].sum()
        market_weights       = market_df.set_index(col_sedol)[col_weight]
        market_returns_agg   = returns[market_df[col_sedol]].dot(market_weights)
        market_returns_agg.name = "market_return"
        market_variance      = market_returns_agg.var()

        # Calcul des bêtas individuels des titres en portefeuille
        ptf_w.dropna(subset=[col_sedol], inplace=True)
        ptf_w[col_weight] /= ptf_w[col_weight].sum()

        # Use benchmark universe
        sedol_in_bench = ind_w[col_sedol].unique()
        cov_with_market_bench = returns[sedol_in_bench].apply(lambda x: x.cov(market_returns_agg))
        security_betas_bench  = (cov_with_market_bench / market_variance)
        security_betas_bench.name = "beta"

        # Map to ISIN for benchmark names
        betas_bench = (ind_w[[col_sedol, "ISIN"]].drop_duplicates()
                    .merge(security_betas_bench.rename_axis(col_sedol).reset_index(),
                            on=col_sedol, how="left")
                    .drop_duplicates(subset=["ISIN"])
                    .set_index("ISIN")[["beta"]])


        vol_bench = self._compute_bench_returns(ind_w, returns, col_weight, col_sedol).std() * np.sqrt(freq)

        # Volatilité individuelle des titres
        ptf_wo_na  = ptf_w[ptf_w[col_sedol].notna()]
        vol        = ptf_wo_na.set_index(col_isin)[col_sedol].apply(
                        lambda x: returns[x].std() * np.sqrt(freq))

        # Tracking Error et contribution par titre
        missing = list(set(ptf_wo_na[col_isin]) - set(ind_w[col_isin]))
        if missing:
            add_rows = ptf_wo_na[ptf_wo_na[col_isin].isin(missing)].copy()
            # add_rows["Weight"] = 0
            # univ = pd.concat([ind_w, add_rows])
            add_rows[col_weight] = 0
            cols_to_keep = [col_isin, col_sedol, col_weight]
            univ = pd.concat([ind_w[cols_to_keep], add_rows[cols_to_keep]], ignore_index=True)
        else:
            cols_to_keep = [col_isin, col_sedol, col_weight]
            univ = copy.deepcopy(ind_w)

        univ       = univ[univ[col_sedol].isin(returns.columns)]
        ptf_wo_na  = ptf_wo_na[ptf_wo_na[col_sedol].isin(returns.columns)]

        if method_cov == "ewma":
            print("EWMA method is used for calculating Covariance")
            cov_univ = self.ewma_covariance(returns[univ[col_sedol]], lam=cov_lambda, demean=False) * freq
            cov_ptf  = self.ewma_covariance(returns[ptf_wo_na[col_sedol]], lam=cov_lambda, demean=False) * freq

        else:
            cov_univ = returns[univ[col_sedol]].cov() * freq
            cov_ptf  = returns[ptf_wo_na[col_sedol]].cov() * freq

        # duplicate-column/index cleanup
        for c in [cov_univ, cov_ptf]:
            c.drop(columns=c.columns[c.columns.duplicated()], inplace=True)
            c.drop(index=c.index[c.index.duplicated()], inplace=True)

        w_ptf_te  = ptf_wo_na[[col_sedol, col_isin, col_weight]].drop_duplicates()
        w_univ_te = univ[[col_sedol, col_isin, col_weight]].drop_duplicates()

        te, contrib_te = self._compute_te_and_contrib(
            w_ptf_te, w_univ_te, cov_univ, isin_col=col_isin, col_weight=col_weight, sedol_col=col_sedol
        )
        vol_ptf = np.sqrt(
            w_ptf_te[col_weight].values.T @ cov_ptf.values @ w_ptf_te[col_weight].values
        )

        self.betas      = betas_bench
        self.te         = te
        self.contrib_te = contrib_te
        self.vol_ptf    = vol_ptf
        self.vol_bench  = vol_bench
        self.vol        = vol
        self._bench_for_risk = bench

        print("✅ compute_risk_metrics() terminé.")
        print("   Attributs stockés :")
        print("   → self.betas       (Beta par ISIN)")
        print("   → self.te          (Tracking Error scalaire)")
        print("   → self.contrib_te  (Contribution TE par ISIN)")
        print("   → self.vol_ptf     (Volatilité portefeuille)")
        print("   → self.vol_bench   (Volatilité benchmark)")
        print("   → self.vol         (Volatilité individuelle par ISIN)")

    def build_fund_full(self):
        """
        Construit la vue complète du portefeuille et de l'indice avec :
        scores factoriels, métriques CIQ, Beta, Contrib TE, flag Hors Indice.
        """
        if not hasattr(self, "betas"):
            self.compute_risk_metrics()

        # Fonction de nettoyage stricte pour PTF et Bench
        def _clean_base_df(df_in):
            df = df_in.copy()

            # 1. Purger le LIBELLE "N/A" factice s'il existe déjà une vraie colonne "Name"
            if "Name" in df.columns and "LIBELLE" in df.columns:
                df = df.drop(columns=["LIBELLE"])

            # 2. Renommer les colonnes cibles
            df = df.rename(columns={"Name": "LIBELLE", "Weight": "%ACTIF"})

            # 3. Sécurité anti-doublon (au cas où)
            df = df.loc[:, ~df.columns.duplicated(keep='first')]

            # 4. S'assurer que LIBELLE existe, sinon "N/A"
            if "LIBELLE" not in df.columns:
                df["LIBELLE"] = "N/A"

            # --- NOUVEAU 1 : Rapatriement des noms (LIBELLE) manquants ---
            # Si la source (ex: excel_ts) ne contient pas de noms, on les récupère via l'ISIN dans FactSet
            screen_names = self.last_screen.reset_index()[["ISIN", "Name"]].drop_duplicates("ISIN").set_index("ISIN")["Name"]
            df["LIBELLE"] = np.where(
                (df["LIBELLE"] == "N/A") | (df["LIBELLE"].isna()) | (df["LIBELLE"] == 0),
                df["ISIN"].map(screen_names).fillna("N/A"),
                df["LIBELLE"]
            )

            # --- NOUVEAU 2 : Normalisation universelle des poids ---
            # Convertir en float de manière sécurisée
            df["%ACTIF"] = pd.to_numeric(
                df["%ACTIF"].astype(str).replace(r"^([A-Za-z]|[0-9]|_)+$", 0, regex=True),
                errors="coerce"
            ).fillna(0).astype(float)

            # Division par la somme pour forcer la somme exacte à 1.0 (100%)
            # Évite les erreurs d'affichage Excel (ex: 5.23 au lieu de 0.0523 -> 523%)
            total_w = df["%ACTIF"].sum()
            if total_w != 0:
                df["%ACTIF"] = df["%ACTIF"] / total_w

            # 5. ISOLATION STRICTE
            return df[["ISIN", "LIBELLE", "%ACTIF"]]

        # Application du nettoyage strict sur le Portefeuille
        fund = _clean_base_df(self.fund)
        fund["ISIN"]         = fund["ISIN"].astype(str).str.split(" ").str[0]
        # Le poids est désormais parfaitement normalisé à 1.0
        fund["%ACTIF 100%"]  = fund["%ACTIF"]

        # Application du nettoyage strict sur le Benchmark
        bench_df = _clean_base_df(self.bench_df)
        # Le poids est désormais parfaitement normalisé à 1.0
        bench_df["%ACTIF 100%"] = bench_df["%ACTIF"]

        # screen = self.last_screen
        ciq = self.last_screen

        screen_cols = ["ISIN","ICB19 Supersector","Exchange Country Region",
                    "Benchmark Market Value Millions in EUR ",
                    "Score Dividend","Score Value",
                    "Score Quality","Score Momentum",
                    "Score Volatility","Score Growth", "Reco Analyst"]
        ciq_cols_full = ["ISIN","Score ML","Daily Vol 90J","EBITDAm FY1","Gross Margin",
                        "Earns Yield FY1","DVD Payout FY0","DVD Yield FY1","FCF Conversion",
                        "CFO Div Cov Ratio","FCF Div Cov Ratio","PE FY1","Price to Book FY1",
                        "EV to Sales FY1","EV To EBITDA FY1","EV to Ebit FY1","Sales Growth FY1",
                        "EBITDA Growth FY1 CIQ","Gross Income Growth FY1","EPS Growth FY1",
                        "Sales_5Y_growth","EPS_5Y_growth","EPS Revision Ratio",
                        "Pct_Short_Interest","SP Price Target CIQ"]

        cols_added = ['ISIN', 'Exchange Country Name', 'Date']

        fund_full   = fund.merge(ciq[screen_cols], on="ISIN", how="left")
        indice_full = bench_df.merge(ciq[screen_cols], on="ISIN", how="left")

        fund_full.drop_duplicates(subset=["ISIN"], keep="first", inplace=True)
        indice_full.drop_duplicates(subset=["ISIN"], keep="first", inplace=True)
        fund_full.set_index("ISIN", inplace=True)
        indice_full.set_index("ISIN", inplace=True)

        fund_full["Beta"]       = self.betas
        fund_full["Contrib TE"] = self.contrib_te
        indice_full["Beta"]     = self.betas
        indice_full["Contrib TE"] = self.contrib_te

        fund_full.reset_index(inplace=True)
        indice_full.reset_index(inplace=True)

        for df in [fund_full, indice_full]:
            df["Score Dividend"] = df["Score Dividend"].fillna(0)

        hors_id = list(set(fund_full["ISIN"]) - set(indice_full["ISIN"]))
        fund_full["Hors indice"]    = fund_full["ISIN"].isin(hors_id).astype(int)
        indice_full["Hors indice"]  = 0

        # Chargement du mapping fonds internes (Nom, Region, Secteur)
        transco_fi = pd.read_excel(self.paths['transco_ISIN_Fonds'], index_col=1)

        mapping_nom     = transco_fi["Nom"].to_dict()
        mapping_region  = transco_fi["Exchange Country Region"].to_dict() if "Exchange Country Region" in transco_fi.columns else {}
        mapping_sector  = transco_fi["ICB19 Supersector"].to_dict()       if "ICB19 Supersector"        in transco_fi.columns else {}

        # Enrichissement de fund_full (source unique de vérité)
        fund_full["LIBELLE"] = fund_full["LIBELLE"].replace('N/A', pd.NA)
        fund_full["LIBELLE"] = fund_full["LIBELLE"].fillna(
            fund_full["ISIN"].map(mapping_nom)
        )

        # Complétion Region et Sector pour les fonds internes hors indice
        if "Exchange Country Region" in fund_full.columns:
            fund_full["Exchange Country Region"] = fund_full["Exchange Country Region"].fillna(
                fund_full["ISIN"].map(mapping_region)
            )

        if "ICB19 Supersector" in fund_full.columns:
            fund_full["ICB19 Supersector"] = fund_full["ICB19 Supersector"].fillna(
                fund_full["ISIN"].map(mapping_sector)
            )

        
        hors_indice_df = fund_full.loc[fund_full["Hors indice"] == 1,
                                    ["ISIN","LIBELLE","%ACTIF"]]

        fund_full   = fund_full.merge(ciq[ciq_cols_full], on="ISIN", how="left")
        indice_full = indice_full.merge(ciq[ciq_cols_full], on="ISIN", how="left")

        if len(cols_added) > 0:
            fund_full   = fund_full.merge(ciq[cols_added], on="ISIN", how="left")
            indice_full = indice_full.merge(ciq[cols_added], on="ISIN", how="left")

        for df in [fund_full, indice_full]:
            df["EPS Growth FY1"]  = df["EPS Growth FY1"].clip(lower=-100, upper=1000)
            df["FCF Conversion"]  = df["FCF Conversion"].clip(lower=-100, upper=1000)

        fund_full   = fund_full.sort_values(by=["%ACTIF"], ascending=False)
        indice_full = indice_full.sort_values(by=["%ACTIF"], ascending=False)

        self.fund_full      = fund_full
        self.indice_full    = indice_full
        self.hors_indice_df = hors_indice_df

        print("✅ build_fund_full() terminé.")

    def build_screen_final(self):
        """
        Construit le tableau screen final avec colonnes spot, last et delta.
        """
        isin_fund  = self.fund_full["ISIN"].unique() if hasattr(self, "fund_full") else self.fund["ISIN"].unique()
        isin_bench = self.indice_full["ISIN"].unique() if hasattr(self, "indice_full") else self.bench_df["ISIN"].unique()
        all_isin   = pd.Series(pd.concat([pd.Series(isin_fund),
                                        pd.Series(isin_bench)])).unique()

        screen_agg  = self.screen_agg
        spot_date   = self.spot_date
        last_date   = self.last_date
        sector_col  = " Benchmark ICB Supersector "
        if sector_col not in screen_agg.columns or screen_agg[sector_col].isna().all():
            for candidate_col in [" Benchmark ICB Industry ", "ICB19 Supersector", "ICB20 Supersector", "ICB11 Industry"]:
                if candidate_col in screen_agg.columns and screen_agg[candidate_col].notna().any():
                    screen_agg = screen_agg.copy()
                    screen_agg[sector_col] = screen_agg[candidate_col]
                    break

        filtered    = screen_agg[screen_agg["ISIN"].isin(all_isin)].drop_duplicates()
        screen_spot = filtered[filtered["Date"] == spot_date]
        screen_last = filtered[filtered["Date"] == last_date]

        # Colonnes factorielles à calculer
        factor_cols = list(self._DICT_FACTEURS.values())
        value_columns = ["Score Value","PE FY1","Price to Book FY1","Price to FreeCF FY1",
                            "EV to Ebit FY1","EV to Sales FY1","EV To EBITDA FY1",
                            "PE LTM","PB LTM","PFCF LTM","EV to Sales LTM","EV To EBITDA LTM"]
        growth_columns   = ["Score Growth","5Y_Hist EPS TrendStab",
                            "5Y_Hist GrossInc TrendStab","5Y_Hist Sales TrendStab"]
        quality_columns  = ["Score Quality","ROE avg FY0","Oper Margin","Asset TO exFIN",
                            "NetDebt to EBITDA exFIN","TIER1 Ratio FY0",
                            "ROTE avg FY1","Combined Ratio FY1"]
        momentum_columns = ["Score Momentum","PMOM 12M1M","EPS NTM 3M Growth","EPS Revision Ratio"]
        lowvol_columns   = ["Score Volatility","Daily Vol 60J","Daily Vol 90J","Daily Vol 260J"]
        div_columns = ["Score Dividend", "DVD Yield FY0", "DVD Yield FY1", "DPS FY1", "Earns Yield FY0", "Earns Yield FY1"]
        multi_score      = ["Score Multifacteur"]

        columns_to_compute = multi_score + value_columns + growth_columns + quality_columns + momentum_columns + lowvol_columns + div_columns
        columns_classique  = ["ISIN","Name",sector_col]

        screen_spot_norm = self._normalize_by_sector(screen_spot, factor_cols, sector_col)
        screen_last_norm = self._normalize_by_sector(screen_last, factor_cols, sector_col)

        # Fusion spot + last avec colonnes _LAST et _DELTA
        screen_final = pd.merge(screen_spot_norm, screen_last_norm,
                                on="ISIN", how="left", suffixes=("","_LAST"))
        order_columns = []
        for x in columns_to_compute:
            screen_final[x + "_DELTA"] = screen_final[x] - screen_final.get(x + "_LAST", 0)
            order_columns += [x, x + "_LAST", x + "_DELTA"]

        ###### Cela va décider l'affichage dans le sheet "DATA"
        order_columns  = columns_classique + order_columns + ['Score ML']
        existing_cols  = [c for c in order_columns if c in screen_final.columns]
        screen_final   = screen_final[existing_cols]
        screen_final[sector_col] = screen_final[sector_col].map(self._ICB_SUPERSECTORS_MAPPING).fillna(screen_final[sector_col])

        # Ajout du Score Multifacteur Tilt (pondération factorielle mensuelle)
        spot_date_bis       = spot_date + pd.offsets.MonthBegin(1)
        reco_spot           = self.df_reco_facto[self.df_reco_facto.index == spot_date_bis]
        screen_final.index  = screen_final["ISIN"]
        common_cols         = [c for c in reco_spot.columns if c in screen_final.columns]
        score_tilt          = (reco_spot.iloc[0][common_cols] * screen_final[common_cols]).sum(axis=1)
        score_tilt          = score_tilt.reset_index().rename(columns={0:"Score Multiffacteur Tilt"})
        screen_final        = screen_final.reset_index(drop=True)
        screen_final        = pd.merge(screen_final, score_tilt, on="ISIN", how="left")
        screen_final        = self._normalize_by_sector(screen_final, ["Score Multiffacteur Tilt"], sector_col)

        # Réorganisation finale des colonnes
        colonne_order = list(screen_final.columns[:4]) + ["Score Multiffacteur Tilt"] + list(screen_final.columns[4:-1])
        screen_final  = screen_final[[c for c in colonne_order if c in screen_final.columns]]
        screen_final  = screen_final.loc[:, ~screen_final.columns.duplicated()]
        screen_final  = screen_final.sort_values(
            by=[sector_col, "Score Multiffacteur Tilt"], ascending=[True, False]
        )

        screen_final = screen_final.rename(columns = {"Score ML" : "Score ML rebased"})
        screen_final["Score ML rebased"] = screen_final["Score ML rebased"].fillna(-1)

        # Remplacement des Perf statiques (screen_agg) par des Perf calculées en temps réel
        returns   = self.df_returns
        today     = returns.index[-1]

        def _perf(start, end):
            return (1 + returns.loc[start:end]).prod() - 1

        perf_live = pd.DataFrame({
            "Perf5D":  _perf(today - pd.offsets.BDay(5),   today),
            "Perf1M":  _perf(today - pd.offsets.BDay(21),  today),
            "Perf3M":  _perf(today - pd.offsets.BDay(63),  today),
            "Perf6M":  _perf(today - pd.offsets.BDay(126), today),
        }).reset_index().rename(columns={"index": "Company SEDOL"})

        # Jointure via SEDOL
        screen_final = screen_final.merge(
            self.last_screen[["ISIN", "Company SEDOL"]].drop_duplicates("ISIN"),
            on="ISIN", how="left"
        ).merge(perf_live, on="Company SEDOL", how="left").drop(columns=["Company SEDOL"])


        self.screen_final = screen_final
        print("✅ build_screen_final() terminé.")
        print("   Attributs stockés :")
        print("   → self.screen_final  (Screen spot/last/delta avec Score Tilt)")

    def compute_performance(self, freq: int = 252):
        """Calcule les performances 1W, 1M, YTD, 1Y."""
        returns = self.df_returns
        today   = returns.index[-1]

        def _perf(start, end):
            return (1 + returns.loc[start:end]).prod() - 1

        perf_1w  = _perf(today - pd.offsets.BDay(5),   today)
        perf_1m  = _perf(today - pd.offsets.BDay(21),  today)
        perf_ytd = _perf(pd.Timestamp(today.year, 1, 1), today)
        perf_1y  = _perf(today - pd.offsets.BDay(252), today)

        perf_df = pd.DataFrame({
            "Perf 1W":  perf_1w,
            "Perf 1M":  perf_1m,
            "Perf YTD": perf_ytd,
            "Perf 1Y":  perf_1y,
        }).reset_index().rename(columns={"index": "Company SEDOL"})

        if not hasattr(self, "fund_full"):
            self.build_fund_full()

        export_cols = ["ISIN", "%ACTIF", "LIBELLE", "ICB19 Supersector",
                    "Perf 1W", "Perf 1M", "Perf YTD", "Perf 1Y"]

        fund_perf = self.fund_full[["ISIN", "LIBELLE", "%ACTIF", "ICB19 Supersector"]].merge(
            self.last_screen[["ISIN", "Company SEDOL"]].drop_duplicates("ISIN"),
            on="ISIN", how="left"
        ).merge(perf_df, on="Company SEDOL", how="left")

        bench_perf = self.indice_full[["ISIN", "LIBELLE", "%ACTIF", "ICB19 Supersector"]].merge(
            self.last_screen[["ISIN", "Company SEDOL"]].drop_duplicates("ISIN"),
            on="ISIN", how="left"
        ).merge(perf_df, on="Company SEDOL", how="left")

        self.top10_fund    = fund_perf.nlargest(10,   "Perf 1W")[export_cols]
        self.worst10_fund  = fund_perf.nsmallest(10,  "Perf 1W")[export_cols]
        self.top20_bench   = bench_perf.nlargest(20,  "Perf 1W")[export_cols]
        self.worst20_bench = bench_perf.nsmallest(20, "Perf 1W")[export_cols]
        self.perf_df       = fund_perf
        print("✅ compute_performance() terminé.")
        print("   Attributs stockés :")
        print("   → self.perf_df        (Performances complètes du portefeuille)")
        print("   → self.top10_fund     (Top 10 fonds sur 1W)")
        print("   → self.worst10_fund   (Worst 10 fonds sur 1W)")
        print("   → self.top20_bench    (Top 20 benchmark sur 1W)")
        print("   → self.worst20_bench  (Worst 20 benchmark sur 1W)")

    def get_news_flow(self, days: int = 7):
        """Filtre les news FactSet récentes."""
        if not hasattr(self, "fund_full"):
            self.build_fund_full()

        isin_list   = list(self.fund_full["ISIN"].unique())
        today       = datetime.today().date()
        cutoff      = pd.Timestamp(today - timedelta(days=days), tz="UTC")

        news_recent = self.news_raw[self.news_raw["story_time"] >= cutoff]
        news_filt   = news_recent[news_recent["ISIN"].isin(isin_list)]
        news_filt   = news_filt.merge(self.fund_full[["ISIN","LIBELLE"]], on="ISIN", how="left")
        news_filt   = news_filt[["ISIN","LIBELLE","story_time","headlines","subjects","story_body_clean"]].sort_values(by="story_time", ascending=False)

        news_filt["subjects"]   = news_filt["subjects"].apply(
            lambda x: ", ".join(map(str, x)) if isinstance(x, list) else x
        )
        news_filt["story_time"] = pd.to_datetime(news_filt["story_time"], errors="coerce").dt.tz_localize(None)

        self.news_flow = news_filt
        print(f"✅ get_news_flow() terminé.")

        print(f"✅ get_news_flow() terminé ({len(news_filt)} articles sur {days} jours).")
        print("   Attributs stockés :")
        print("   → self.news_flow  (Newsflow filtré sur le portefeuille)")

    def get_stock_deviation(self, top_n: int = 5):
        """Calcule l'écart de pondération PTF vs Bench."""
        if not hasattr(self, "fund_full"):
            self.build_fund_full()

        bench_w = self.bench_df.copy()
        if "LIBELLE" not in bench_w.columns and "Name" in bench_w.columns:
            bench_w["LIBELLE"] = bench_w["Name"]
        bench_w = bench_w.rename(columns={"%ACTIF": "Weight Bench"})
        bench_w = bench_w[["ISIN", "Weight Bench", "LIBELLE"]]
        bench_w["Weight Bench"] /= bench_w["Weight Bench"].sum()

        fund_w  = self.fund_full[["ISIN","%ACTIF 100%", "LIBELLE"]].copy()
        fund_w.rename(columns={"%ACTIF 100%": "Weight Fund"}, inplace=True)

        # 1. Utiliser OUTER JOIN (Union) pour ne pas rater les valeurs "Hors Indice" du PTF
        df_dev  = bench_w.merge(fund_w, on="ISIN", how="outer", suffixes=('_bench', '_fund')).fillna(0)
        df_dev = df_dev[df_dev['ISIN'] != "CASH"]

        # 2. Récupérer le bon nom (LIBELLE)
        # On prend en priorité le nom du fonds, sinon celui du benchmark
        df_dev["LIBELLE"] = np.where(
            (df_dev["LIBELLE_fund"] != 0) & (df_dev["LIBELLE_fund"] != "N/A"),
            df_dev["LIBELLE_fund"],
            df_dev["LIBELLE_bench"]
        )

        df_dev["Weight Bench"] /= df_dev["Weight Bench"].sum()
        df_dev["Deviation"]    = df_dev["Weight Fund"] - df_dev["Weight Bench"]
        df_dev = df_dev.sort_values("Deviation")

        self.deviation_df    = df_dev
        self.top_surexpo     = df_dev.iloc[-top_n:][["LIBELLE","Deviation"]]
        self.top_sousexpo    = df_dev.iloc[:top_n][["LIBELLE","Deviation"]]
        self.surexpo_total   = df_dev.iloc[-top_n:]["Deviation"].sum()
        self.sousexpo_total  = df_dev.iloc[:top_n]["Deviation"].sum()
        print(f"✅ get_stock_deviation() terminé.")




    # =========================================================================
    # MODULE : Attribution de Performance
    # =========================================================================
    #
    # Deux approches disponibles, indépendantes et complémentaires :
    #
    #   1) compute_bhb_attribution()  — BHB classique par dimension (Tables 1-4)
    #      • Chaque table (Sector / Region / Factor / Specific) est calculée
    #        indépendamment avec la formule BHB standard.
    #      • ⚠️  Tables 1 et 2 couvrent chacune 100 % de l'excès → double-comptage
    #        si on les additionne. À utiliser pour une lecture analytique par dimension.
    #
    #   2) compute_ols_attribution()  — OLS unifié strict (Tables 1-4)
    #      • Une seule régression OLS inclut simultanément les dummies Secteur,
    #        les dummies Région et les scores factoriels.
    #      • Les quatre tables sont orthogonales par construction (propriété OLS).
    #      • Table1 + Table2 + Table3 + Table4 = Total Active Return exact.
    #
    # =========================================================================

    # -------------------------------------------------------------------------
    # ① BHB CLASSIQUE
    # -------------------------------------------------------------------------

    def compute_bhb_attribution(self, start_date=None, end_date=None):
        """
        Calcule la décomposition BHB classique (Tables 1-4).

        Chaque table est calculée de façon indépendante avec la formule BHB
        standard. Tables 1 et 2 couvrent chacune 100 % de l'excès de rendement ;
        elles sont destinées à une lecture analytique par dimension séparée.
        Pour une décomposition strictement additive, utiliser compute_ols_attribution().

        Paramètres
        ----------
        start_date : date-like ou None — début de la fenêtre (défaut : ≈ 1M en arrière)
        end_date   : date-like ou None — fin   de la fenêtre (défaut : dernier snapshot)

        Attributs stockés
        -----------------
        self.attrib_table1   — BHB par Sector (ICB19 Supersector)
        self.attrib_table2   — BHB par Region (Exchange Country Region)
        self.attrib_table3   — Attribution par Facteur (OLS cross-sectionnel)
        self.attrib_table4   — Retour spécifique résiduel par titre
        self.attrib_total    — dict scalaire récapitulatif
        self.attrib_dates    — (start_date, end_date) effectivement utilisés
        """
        t0, t1 = self._resolve_attrib_dates(start_date, end_date)
        print(f"⏳ Attribution BHB classique [{t0.strftime('%Y-%m-%d')} → {t1.strftime('%Y-%m-%d')}]")

        w_fund, w_bench = self._get_attribution_weights(t0)
        isin_to_sedol   = self._build_isin_sedol_map()
        w_fund["SEDOL"]  = w_fund["ISIN"].map(isin_to_sedol)
        w_bench["SEDOL"] = w_bench["ISIN"].map(isin_to_sedol)

        period_ret = self._period_returns(self.df_returns, t0, t1)
        meta       = self._get_meta_at_date(t0)
        base       = self._build_base_frame(w_fund, w_bench, period_ret, meta)

        # Tables 1 et 2 : BHB classique (chacune = 100 % de l'excès)
        self.attrib_table1 = self._bhb_group(base, group_col="ICB19 Supersector")
        print("   ✅ Table 1 (Sector BHB) calculée.")

        self.attrib_table2 = self._bhb_group(base, group_col="Exchange Country Region")
        print("   ✅ Table 2 (Region BHB) calculée.")

        # Table 3 : Attribution factorielle (OLS cross-sectionnel)
        self.attrib_table3 = self._factor_attribution(base, self.df_returns, t0, t1)
        print("   ✅ Table 3 (Factor Attribution) calculée.")

        # Table 4 : Résidu spécifique
        self.attrib_table4 = self._specific_return(base, self.attrib_table3)
        print("   ✅ Table 4 (Specific Return) calculée.")

        # Récapitulatif indicatif (⚠️ pas une somme stricte — voir compute_ols_attribution)
        t1_tot = self.attrib_table1["Active Contrib"].sum()
        t3_tot = self.attrib_table3["Factor Contrib"].sum() if not self.attrib_table3.empty else 0.0
        t4_tot = self.attrib_table4["Specific Contrib"].sum()

        self.attrib_total = {
            "Sector BHB (indicatif)":  round(t1_tot, 6),
            "Region BHB (indicatif)":  round(self.attrib_table2["Active Contrib"].sum(), 6),
            "Factor Return":           round(t3_tot, 6),
            "Specific Return":         round(t4_tot, 6),
            "Note": "Tables 1 et 2 ne sont pas additives. Utiliser Attribution OLS pour la somme stricte.",
        }
        self.attrib_dates = (t0, t1)

        print(f"✅ Attribution BHB classique terminée.")
        print(f"   → Sector BHB  : {t1_tot:.4%}  (= R_p - R_b, lecture sectorielle)")
        print(f"   → Region BHB  : {self.attrib_table2['Active Contrib'].sum():.4%}  (= R_p - R_b, lecture régionale)")
        print(f"   → Factor Ret  : {t3_tot:.4%}")
        print(f"   → Specific    : {t4_tot:.4%}")

    # -------------------------------------------------------------------------
    # ② OLS UNIFIÉ STRICT
    # -------------------------------------------------------------------------

    def compute_ols_attribution(self, start_date=None, end_date=None):
        """
        Calcule la décomposition OLS unifiée strict (Tables 1-4 orthogonales).

        Une seule régression OLS incluant simultanément les dummies Secteur,
        les dummies Région et les scores factoriels. Les quatre composantes
        sont orthogonales par construction et s'additionnent exactement au
        Total Active Return :
            Table1 + Table2 + Table3 + Table4 = R_p - R_b

        Paramètres
        ----------
        start_date : date-like ou None — début de la fenêtre (défaut : ≈ 1M en arrière)
        end_date   : date-like ou None — fin   de la fenêtre (défaut : dernier snapshot)

        Attributs stockés
        -----------------
        self.ols_table1    — Contribution Secteur par titre et par groupe
        self.ols_table2    — Contribution Région par titre et par groupe
        self.ols_table3    — Contribution Facteur (beta × active tilt)
        self.ols_table4    — Contribution Spécifique résiduelle par titre
        self.ols_total     — dict scalaire (additivité stricte vérifiée)
        self.ols_dates     — (start_date, end_date) effectivement utilisés
        self.ols_r2        — R² de la régression OLS
        """
        t0, t1 = self._resolve_attrib_dates(start_date, end_date)
        print(f"⏳ Attribution OLS unifiée [{t0.strftime('%Y-%m-%d')} → {t1.strftime('%Y-%m-%d')}]")

        w_fund, w_bench = self._get_attribution_weights(t0)
        isin_to_sedol   = self._build_isin_sedol_map()
        w_fund["SEDOL"]  = w_fund["ISIN"].map(isin_to_sedol)
        w_bench["SEDOL"] = w_bench["ISIN"].map(isin_to_sedol)

        period_ret = self._period_returns(self.df_returns, t0, t1)
        meta       = self._get_meta_at_date(t0)
        base       = self._build_base_frame(w_fund, w_bench, period_ret, meta)

        t1_grp, t2_grp, t3_fac, t4_stock, total, r2 = self._unified_ols_attribution(base)

        self.ols_table1 = t1_grp
        self.ols_table2 = t2_grp
        self.ols_table3 = t3_fac
        self.ols_table4 = t4_stock
        self.ols_total  = total
        self.ols_dates  = (t0, t1)
        self.ols_r2     = r2

        print(f"✅ Attribution OLS unifiée terminée (R² = {r2:.4f}).")
        print(f"   → Sector OLS  : {total['Sector Contrib']:.4%}")
        print(f"   → Region OLS  : {total['Region Contrib']:.4%}")
        print(f"   → Factor OLS  : {total['Factor Contrib']:.4%}")
        print(f"   → Specific    : {total['Specific Contrib']:.4%}")
        print(f"   → Total Active: {total['Total Active']:.4%}  ✔ (additivité stricte)")

    # -------------------------------------------------------------------------
    # ③ TABLE 5 — ML Score BHB (indépendant, hors total)
    # -------------------------------------------------------------------------

    def compute_ml_bhb(self, start_date=None, end_date=None):
        """
        Table 5 : Décomposition BHB selon les quintiles du Score ML.

        Indépendante des Tables 1-4. Non incluse dans le total.
        Les quintiles Q1-Q5 sont calculés sur l'univers complet de screen_agg
        à la date t0 (Q1 = meilleur Score ML, Q5 = moins bon).

        Attributs stockés
        -----------------
        self.attrib_table5 — BHB par quintile ML (Q1–Q5)
        """
        t0, t1 = self._resolve_attrib_dates(start_date, end_date)
        print(f"⏳ ML BHB (Table 5) [{t0.strftime('%Y-%m-%d')} → {t1.strftime('%Y-%m-%d')}]")

        w_fund, w_bench = self._get_attribution_weights(t0)
        isin_to_sedol   = self._build_isin_sedol_map()
        w_fund["SEDOL"]  = w_fund["ISIN"].map(isin_to_sedol)
        w_bench["SEDOL"] = w_bench["ISIN"].map(isin_to_sedol)

        period_ret = self._period_returns(self.df_returns, t0, t1)
        meta       = self._get_meta_at_date(t0)
        base       = self._build_base_frame(w_fund, w_bench, period_ret, meta)

        # Quintiles ML sur l'univers complet à t0 (distribution large, non biaisée)
        dates_agg = pd.to_datetime(self.screen_agg["Date"].unique())
        best_date = dates_agg[np.argmin(np.abs(dates_agg - t0))]
        screen_t0 = (
            self.screen_agg[self.screen_agg["Date"] == best_date][["ISIN", "Score ML"]]
            .dropna(subset=["Score ML"])
        )
        screen_t0 = screen_t0.copy()
        screen_t0["ML_Quintile"] = pd.qcut(
            screen_t0["Score ML"],
            q=5,
            labels=["Q5 (Bas)", "Q4", "Q3", "Q2", "Q1 (Haut)"],
            duplicates="drop",
        )
        quintile_map = screen_t0.set_index("ISIN")["ML_Quintile"].to_dict()
        base["ML_Quintile"] = base["ISIN"].map(quintile_map).fillna("Non classé")

        self.attrib_table5 = self._bhb_group(base, group_col="ML_Quintile")
        print("✅ Table 5 (ML BHB) calculée — self.attrib_table5")


    def compute_mf_bhb(self, start_date=None, end_date=None):
        """
        Table 6 : Décomposition BHB selon les quintiles du Score Multifacteur.
        Logique identique à compute_ml_bhb(), Score ML remplacé par Score Multifacteur.
        Indépendant — non inclus dans le total BHB/OLS.

        Attributs stockés
        -----------------
        self.attrib_table6 — BHB par quintile MF (Q1–Q5)
        """
        t0, t1 = self._resolve_attrib_dates(start_date, end_date)
        print(f"⏳ MF BHB (Table 6) [{t0.strftime('%Y-%m-%d')} → {t1.strftime('%Y-%m-%d')}]")

        w_fund, w_bench = self._get_attribution_weights(t0)
        isin_to_sedol   = self._build_isin_sedol_map()
        w_fund["SEDOL"]  = w_fund["ISIN"].map(isin_to_sedol)
        w_bench["SEDOL"] = w_bench["ISIN"].map(isin_to_sedol)

        period_ret = self._period_returns(self.df_returns, t0, t1)
        meta       = self._get_meta_at_date(t0)
        base       = self._build_base_frame(w_fund, w_bench, period_ret, meta)

        # Quintiles MF sur l'univers complet à t0
        dates_agg = pd.to_datetime(self.screen_agg["Date"].unique())
        best_date = dates_agg[np.argmin(np.abs(dates_agg - t0))]
        screen_t0 = (
            self.screen_agg[self.screen_agg["Date"] == best_date][["ISIN", "Score Multifacteur"]]
            .dropna(subset=["Score Multifacteur"])
            .copy()
        )
        screen_t0["MF_Quintile"] = pd.qcut(
            screen_t0["Score Multifacteur"],
            q=5,
            labels=["Q5 (Bas)", "Q4", "Q3", "Q2", "Q1 (Haut)"],
            duplicates="drop",
        )
        quintile_map = screen_t0.set_index("ISIN")["MF_Quintile"].to_dict()
        base["MF_Quintile"] = base["ISIN"].map(quintile_map).fillna("Non classé")

        self.attrib_table6 = self._bhb_group(base, group_col="MF_Quintile")
        print("✅ Table 6 (MF BHB) calculée — self.attrib_table6")


    # -------------------------------------------------------------------------
    # Helpers partagés (BHB classique + OLS)
    # -------------------------------------------------------------------------

    def _resolve_attrib_dates(self, start_date, end_date):
        """Résout les dates d'attribution avec fallback sur les attributs d'instance."""
        t0 = pd.to_datetime(start_date) if start_date is not None else self.attrib_start
        t1 = pd.to_datetime(end_date)   if end_date   is not None else self.attrib_end
        if t0 is None or t1 is None:
            raise ValueError(
                "Dates d'attribution introuvables. "
                "Fournissez start_date/end_date ou utilisez des données Time Series."
            )
        return t0, t1

    def _build_isin_sedol_map(self) -> dict:
        """Construit le dictionnaire ISIN → SEDOL depuis screen_agg."""
        return (
            self.screen_agg[["ISIN", "Company SEDOL"]]
            .drop_duplicates("ISIN")
            .set_index("ISIN")["Company SEDOL"]
            .to_dict()
        )

    def _get_attribution_weights(self, t0: pd.Timestamp):
        """
        Extrait les snapshots PTF et Benchmark à la date t0 (ou la plus proche).
        Retourne deux DataFrames [ISIN, SEDOL, w] normalisés (somme = 1).
        """
        def _snap(ts_df, t):
            if ts_df is None or ts_df.empty:
                return pd.DataFrame(columns=["ISIN", "w"])
            avail = pd.to_datetime(ts_df["Date"].unique())
            best  = avail[np.argmin(np.abs(avail - t))]
            snap  = ts_df[ts_df["Date"] == best][["ISIN", "%ACTIF"]].copy()
            snap  = snap.rename(columns={"%ACTIF": "w"})
            snap["ISIN"] = snap["ISIN"].astype(str).str.strip()
            snap["w"]    = pd.to_numeric(snap["w"], errors="coerce").fillna(0)
            total = snap["w"].sum()
            if total > 0:
                snap["w"] /= total
            return snap.reset_index(drop=True)

        if self.fund_ts is not None:
            w_fund = _snap(self.fund_ts, t0)
        else:
            snap_f = self.fund[["ISIN", "%ACTIF"]].copy().rename(columns={"%ACTIF": "w"})
            snap_f["w"] /= snap_f["w"].sum()
            w_fund = snap_f.reset_index(drop=True)

        if self.bench_ts is not None:
            w_bench = _snap(self.bench_ts, t0)
        else:
            snap_b = self.bench_df[["ISIN", "%ACTIF"]].copy().rename(columns={"%ACTIF": "w"})
            snap_b["w"] /= snap_b["w"].sum()
            w_bench = snap_b.reset_index(drop=True)

        return w_fund, w_bench

    @staticmethod
    def _period_returns(returns_df: pd.DataFrame, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.Series:
        """
        Rendement cumulatif par titre (SEDOL) entre t0 et t1.
        Convention : lendemain de t0 jusqu'à t1 inclus (ex-ante).
        Formule : r_i = ∏(1 + r_t) − 1
        """
        mask   = (returns_df.index > t0) & (returns_df.index <= t1)
        slice_ = returns_df.loc[mask].fillna(0)
        if slice_.empty:
            return pd.Series(dtype=float)
        return (1 + slice_).prod() - 1

    def _get_meta_at_date(self, t0: pd.Timestamp) -> pd.DataFrame:
        """
        Récupère les méta-données (Sector, Region, Scores) à la date de screen_agg
        la plus proche de t0. Retourne un DataFrame indexé par ISIN.
        """
        dates_agg = pd.to_datetime(self.screen_agg["Date"].unique())
        best_date = dates_agg[np.argmin(np.abs(dates_agg - t0))]
        meta = self.screen_agg[self.screen_agg["Date"] == best_date].copy()

        if "Exchange Country Region" in meta.columns:
            meta["Exchange Country Region"] = meta["Exchange Country Region"].replace(
                ["@NA", "Pacific", "Mid East", "South America", "0", "East Europe", "Africa"],
                "Others"
            )
        return meta.set_index("ISIN")

    def _build_base_frame(
        self,
        w_fund:     pd.DataFrame,
        w_bench:    pd.DataFrame,
        period_ret: pd.Series,
        meta:       pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Construit le DataFrame de base pour le calcul BHB/OLS.
        Colonnes résultantes :
            ISIN, SEDOL, w_p, w_b, r_i,
            ICB19 Supersector, Exchange Country Region,
            Score Value, Score Growth, Score Quality,
            Score Momentum, Score Volatility

        Exclusions appliquées :
            - CASH (rendement non comparable, pas de classification)
            - Non classé (ICB19 Supersector introuvable → pollution des groupes)
        Le CASH est conservé avec r_i = 0 et classé "Liquidités" pour préserver
        l'intégrité des poids. Les titres "Non classé" sont exclus et les poids
        sont renormalisés.
        """
        # --- Union PTF ∪ Benchmark ---
        merged = (
            w_fund[["ISIN", "SEDOL", "w"]].rename(columns={"w": "w_p"})
            .merge(
                w_bench[["ISIN", "SEDOL", "w"]].rename(columns={"w": "w_b"}),
                on=["ISIN", "SEDOL"], how="outer",
            )
            .fillna({"w_p": 0.0, "w_b": 0.0})
        )

        # --- Jointure rendements via SEDOL ---
        merged["r_i"] = merged["SEDOL"].map(period_ret)
        median_ret = period_ret.median() if not period_ret.empty else 0.0
        merged["r_i"] = merged["r_i"].fillna(median_ret)

        # --- Méta-données (Sector, Region, Facteurs) ---
        factor_cols = list(self._ATTRIB_FACTORS)
        meta_cols   = ["ICB19 Supersector", "Exchange Country Region",
                    "Company SEDOL"] + factor_cols
        available   = [c for c in meta_cols if c in meta.columns]
        merged      = merged.merge(meta[available], left_on="ISIN", right_index=True, how="left")

        # Fallback SEDOL depuis meta
        if "Company SEDOL" in merged.columns:
            merged["SEDOL"] = merged["SEDOL"].fillna(merged["Company SEDOL"])
            merged.drop(columns=["Company SEDOL"], inplace=True)

        merged["ICB19 Supersector"]       = merged["ICB19 Supersector"].fillna("Non classé")
        merged["Exchange Country Region"] = merged["Exchange Country Region"].fillna("Others")

        # --- Enrichissement depuis fund_full pour les fonds internes ---
        if hasattr(self, "fund_full"):
            ff = (
                self.fund_full[["ISIN", "ICB19 Supersector", "Exchange Country Region"]]
                .drop_duplicates("ISIN")
                .rename(columns={
                    "ICB19 Supersector":       "ICB19_ff",
                    "Exchange Country Region": "Region_ff",
                })
            )
            merged = merged.merge(ff, on="ISIN", how="left")

            merged["ICB19 Supersector"] = (
                merged["ICB19 Supersector"].replace("Non classé", pd.NA)
                .fillna(merged["ICB19_ff"])
                .fillna("Non classé")
            )
            merged["Exchange Country Region"] = (
                merged["Exchange Country Region"].replace("Others", pd.NA)
                .fillna(merged["Region_ff"])
                .fillna("Others")
            )
            merged.drop(columns=["ICB19_ff", "Region_ff"], inplace=True)

        # --- Traitement du CASH ---
        # Conservé avec r_i = 0 et classé "Liquidités" pour préserver l'intégrité des poids
        mask_cash = merged["ISIN"].str.upper() == "CASH"
        merged.loc[mask_cash, "r_i"]                    = 0.0
        merged.loc[mask_cash, "ICB19 Supersector"]       = "Liquidités"
        merged.loc[mask_cash, "Exchange Country Region"] = "Liquidités"

        # --- Exclusion des titres Non classé ---
        # Ces titres ne peuvent pas être attribués à un groupe → pollution des résultats
        mask_exclude = merged["ICB19 Supersector"] == "Non classé"
        n_excluded   = mask_exclude.sum()
        if n_excluded > 0:
            excluded_isins = merged.loc[mask_exclude, "ISIN"].tolist()
            print(f"   ℹ️ {n_excluded} titre(s) exclus de l'attribution (Non classé) : {excluded_isins}")
        merged = merged[~mask_exclude].copy()

        # --- Renormalisation des poids après exclusion des Non classé ---
        if merged["w_p"].sum() > 0:
            merged["w_p"] = merged["w_p"] / merged["w_p"].sum()
        if merged["w_b"].sum() > 0:
            merged["w_b"] = merged["w_b"] / merged["w_b"].sum()

        return merged.reset_index(drop=True)


    @staticmethod
    def _bhb_group(base: pd.DataFrame, group_col: str) -> pd.DataFrame:
        """
        Décomposition BHB classique (Brinson-Hood-Beebower) par groupe.

        Formules :
            Allocation  = (w_p^g − w_b^g) × (R_b^g − R_b)
            Selection   =  w_b^g           × (R_p^g − R_b^g)
            Interaction = (w_p^g − w_b^g) × (R_p^g − R_b^g)

        Retourne un DataFrame par groupe avec colonnes :
            Group, w_p, w_b, R_p_group, R_b_group, R_bench_total,
            Allocation, Selection, Interaction, Active Contrib, _company_detail
        """
        r_bench_total = (base["w_b"] * base["r_i"]).sum()

        agg = (
            base.groupby(group_col, observed=True)
            .apply(lambda g: pd.Series({
                "w_p":       g["w_p"].sum(),
                "w_b":       g["w_b"].sum(),
                "R_p_group": (g["w_p"] * g["r_i"]).sum() / g["w_p"].sum() if g["w_p"].sum() > 0 else 0.0,
                "R_b_group": (g["w_b"] * g["r_i"]).sum() / g["w_b"].sum() if g["w_b"].sum() > 0 else 0.0,
            }))
            .reset_index()
            .rename(columns={group_col: "Group"})
        )

        agg["R_bench_total"] = r_bench_total
        agg["Allocation"]    = (agg["w_p"] - agg["w_b"]) * (agg["R_b_group"] - r_bench_total)
        agg["Selection"]     =  agg["w_b"]                * (agg["R_p_group"] - agg["R_b_group"])
        agg["Interaction"]   = (agg["w_p"] - agg["w_b"]) * (agg["R_p_group"] - agg["R_b_group"])
        agg["Active Contrib"]= agg["Allocation"] + agg["Selection"] + agg["Interaction"]

        # Drill-down par titre : contribution active différentielle
        detail = base[["ISIN", group_col, "w_p", "w_b", "r_i"]].copy()
        detail.rename(columns={group_col: "Group"}, inplace=True)
        detail["Active Contrib Company"] = (detail["w_p"] - detail["w_b"]) * detail["r_i"]
        agg["_company_detail"] = agg["Group"].map(
            detail.groupby("Group")
            .apply(lambda g: g[["ISIN", "w_p", "w_b", "r_i", "Active Contrib Company"]].to_dict("records"))
            .to_dict()
        )
        return agg

    def _factor_attribution(
        self,
        base:       pd.DataFrame,
        returns_df: pd.DataFrame,
        t0:         pd.Timestamp,
        t1:         pd.Timestamp,
    ) -> pd.DataFrame:
        """
        Table 3 BHB classique — Attribution factorielle via OLS cross-sectionnel.

        Régression : r_i = α + Σ_k β_k × score_ik + ε_i
        Contribution du facteur k = β_k × (tilt_ptf_k − tilt_bench_k)

        Retourne un DataFrame :
            Factor, Beta_OLS, Tilt_PTF, Tilt_Bench, Active_Tilt, Factor Contrib
        """
        from sklearn.linear_model import LinearRegression

        factor_cols = [c for c in self._ATTRIB_FACTORS if c in base.columns]
        if not factor_cols:
            return pd.DataFrame()

        reg_data = base[["ISIN", "w_p", "w_b", "r_i"] + factor_cols].dropna(
            subset=factor_cols + ["r_i"]
        ).copy()

        if len(reg_data) < len(factor_cols) + 2:
            print("   ⚠️ Pas assez d'observations pour la régression OLS (Table 3 BHB).")
            return pd.DataFrame()

        ols = LinearRegression(fit_intercept=True)
        ols.fit(reg_data[factor_cols].values, reg_data["r_i"].values)
        betas = dict(zip(factor_cols, ols.coef_))

        rows = []
        for fac in factor_cols:
            tilt_ptf    = (reg_data["w_p"] * reg_data[fac]).sum()
            tilt_bench  = (reg_data["w_b"] * reg_data[fac]).sum()
            active_tilt = tilt_ptf - tilt_bench
            rows.append({
                "Factor":         fac,
                "Beta_OLS":       betas[fac],
                "Tilt_PTF":       tilt_ptf,
                "Tilt_Bench":     tilt_bench,
                "Active_Tilt":    active_tilt,
                "Factor Contrib": betas[fac] * active_tilt,
            })
        return pd.DataFrame(rows)

    def _specific_return(self, base: pd.DataFrame, table3: pd.DataFrame) -> pd.DataFrame:
        """
        Table 4 BHB classique — Retour spécifique résiduel par titre.

        r_specific_i = r_i − Σ_k (β_k × score_ik)
        Specific Contrib_i = (w_p_i − w_b_i) × r_specific_i
        """
        factor_cols = [c for c in self._ATTRIB_FACTORS if c in base.columns]
        detail = base[["ISIN", "w_p", "w_b", "r_i"] + factor_cols].copy()

        if table3.empty or not factor_cols:
            detail["r_factor_hat"] = 0.0
        else:
            betas = table3.set_index("Factor")["Beta_OLS"].to_dict()
            detail["r_factor_hat"] = sum(
                detail[fac] * betas.get(fac, 0.0) for fac in factor_cols
            )

        detail["r_factor_hat"] = detail["r_factor_hat"].fillna(0.0)
        detail["r_specific"]   = detail["r_i"] - detail["r_factor_hat"]
        detail["Specific Contrib"] = (detail["w_p"] - detail["w_b"]) * detail["r_specific"]

        return detail.sort_values("Specific Contrib", ascending=False).reset_index(drop=True)

    # -------------------------------------------------------------------------
    # Méthode interne OLS unifié
    # -------------------------------------------------------------------------

    def _unified_ols_attribution(self, base: pd.DataFrame):
        """
        Régression OLS unique incluant simultanément :
            • dummies Secteur  (ICB19 Supersector)
            • dummies Région   (Exchange Country Region)
            • scores factoriels continus (_DICT_FACTEURS)

        L'orthogonalité des colonnes de design (propriété OLS) garantit que :
            Contrib Secteur + Contrib Région + Contrib Facteur + Contrib Spécifique
            = R_p − R_b  (exactement, aux arrondis float près)

        Retourne
        --------
        t1_grp   : DataFrame — contribution OLS par Secteur (Group, OLS Contrib)
        t2_grp   : DataFrame — contribution OLS par Région  (Group, OLS Contrib)
        t3_fac   : DataFrame — contribution OLS par Facteur (Factor, Beta_OLS, ...)
        t4_stock : DataFrame — contribution spécifique par titre (ISIN, ...)
        total    : dict      — scalaires récapitulatifs + vérification additivité
        r2       : float     — R² de la régression
        """
        from sklearn.linear_model import LinearRegression

        factor_cols  = [c for c in self._ATTRIB_FACTORS if c in base.columns]
        sector_col   = "ICB19 Supersector"
        region_col   = "Exchange Country Region"

        # --- Filtrer les lignes exploitables ---
        reg = base[["ISIN", "w_p", "w_b", "r_i", sector_col, region_col] + factor_cols].dropna(
            subset=["r_i"] + factor_cols
        ).copy()

        if len(reg) < 5:
            raise ValueError("Pas assez d'observations pour la régression OLS unifiée.")

        # --- Encodage des dummies (drop_first pour éviter la multicolinéarité parfaite) ---
        sector_dummies = pd.get_dummies(reg[sector_col], prefix="SEC", drop_first=True, dtype=float)
        region_dummies = pd.get_dummies(reg[region_col], prefix="REG", drop_first=True, dtype=float)

        # Noms des colonnes par bloc (utiles pour la décomposition post-régression)
        sec_cols = list(sector_dummies.columns)
        reg_cols = list(region_dummies.columns)

        X = pd.concat([sector_dummies, region_dummies, reg[factor_cols]], axis=1)
        y = reg["r_i"].values

        ols = LinearRegression(fit_intercept=True)
        ols.fit(X.values, y)

        # R²
        ss_res = np.sum((y - ols.predict(X.values)) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2     = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        # Coefficients par bloc
        all_features = list(X.columns)
        coef_map     = dict(zip(all_features, ols.coef_))

        # --- Résidu par titre ---
        reg["y_hat"]     = ols.predict(X.values)
        reg["residual"]  = reg["r_i"] - reg["y_hat"]

        # --- Contribution Spécifique (Table 4 OLS) ---
        reg["Specific Contrib"] = (reg["w_p"] - reg["w_b"]) * reg["residual"]
        t4_stock = reg[["ISIN", "w_p", "w_b", "r_i", "residual", "Specific Contrib"]].copy()
        t4_stock = t4_stock.rename(columns={"residual": "r_specific_ols"})
        t4_stock = t4_stock.sort_values("Specific Contrib", ascending=False).reset_index(drop=True)

        # --- Contribution Factorielle (Table 3 OLS) ---
        fac_rows = []
        for fac in factor_cols:
            beta        = coef_map.get(fac, 0.0)
            tilt_ptf    = (reg["w_p"] * reg[fac]).sum()
            tilt_bench  = (reg["w_b"] * reg[fac]).sum()
            active_tilt = tilt_ptf - tilt_bench
            fac_rows.append({
                "Factor":         fac,
                "Beta_OLS":       beta,
                "Tilt_PTF":       tilt_ptf,
                "Tilt_Bench":     tilt_bench,
                "Active_Tilt":    active_tilt,
                "Factor Contrib": beta * active_tilt,
            })
        t3_fac = pd.DataFrame(fac_rows)

        # --- Contribution Sectorielle (Table 1 OLS) ---
        # Reconstruction des rendements "purs secteur" : ŷ_secteur_i = Σ γ_s × D_s_i
        # La catégorie de référence (drop_first) a un rendement implicite = intercept
        reg["y_hat_sector"] = sector_dummies[sec_cols].values @ np.array([coef_map[c] for c in sec_cols])
        reg["y_hat_sector"] += ols.intercept_ / 3   # intercept partagé équitablement entre 3 blocs

        # Contribution active sectorielle par titre
        reg["Sector Contrib Company"] = (reg["w_p"] - reg["w_b"]) * reg["y_hat_sector"]

        t1_grp = (
            reg.groupby(sector_col, observed=True)
            .agg(
                w_p=("w_p", "sum"),
                w_b=("w_b", "sum"),
                OLS_Contrib=("Sector Contrib Company", "sum"),
            )
            .reset_index()
            .rename(columns={sector_col: "Group"})
        )

        # --- Contribution Régionale (Table 2 OLS) ---
        reg["y_hat_region"] = region_dummies[reg_cols].values @ np.array([coef_map[c] for c in reg_cols])
        reg["y_hat_region"] += ols.intercept_ / 3

        reg["Region Contrib Company"] = (reg["w_p"] - reg["w_b"]) * reg["y_hat_region"]

        t2_grp = (
            reg.groupby(region_col, observed=True)
            .agg(
                w_p=("w_p", "sum"),
                w_b=("w_b", "sum"),
                OLS_Contrib=("Region Contrib Company", "sum"),
            )
            .reset_index()
            .rename(columns={region_col: "Group"})
        )

        # --- Récapitulatif scalaire ---
        c_sector   = t1_grp["OLS_Contrib"].sum()
        c_region   = t2_grp["OLS_Contrib"].sum()
        c_factor   = t3_fac["Factor Contrib"].sum() if not t3_fac.empty else 0.0
        c_specific = t4_stock["Specific Contrib"].sum()
        c_total    = c_sector + c_region + c_factor + c_specific

        # Vérification : R_p - R_b observable
        r_p = (base["w_p"] * base["r_i"]).sum()
        r_b = (base["w_b"] * base["r_i"]).sum()
        r_active_true = r_p - r_b

        total = {
            "Sector Contrib":   round(c_sector,   6),
            "Region Contrib":   round(c_region,   6),
            "Factor Contrib":   round(c_factor,   6),
            "Specific Contrib": round(c_specific, 6),
            "Total Active":     round(c_total,    6),
            "R_p - R_b (vérifié)": round(r_active_true, 6),
            "Écart (float)":    round(abs(c_total - r_active_true), 10),
        }

        return t1_grp, t2_grp, t3_fac, t4_stock, total, r2

    # -------------------------------------------------------------------------
    # Exports Excel
    # -------------------------------------------------------------------------

    def _export_attribution(self, ws):
        """
        Écrit l'onglet [Attribution] — BHB classique (Tables 1-4 indépendantes + Table 5 ML).

        Disposition :
            A1   : Note méthodologique
            A3   : Table 1 — Sector BHB
            A28  : Table 2 — Region BHB
            A37  : Table 3 — Factor Attribution (OLS cross-sectionnel)
            A46  : Table 4 — Specific Return
            A123 : Récapitulatif indicatif
        """
        if not hasattr(self, "attrib_table1"):
            self.compute_bhb_attribution()

        self._clear_used(ws)

        # Affichage du Total Active Contrib et de la fenêtre en E1/F1
        t0, t1 = self.attrib_dates
        ws.range("E3").value = "Total Active Contrib (BHB)"
        ws.range("F3").value = (
            f"{self.attrib_table1['Active Contrib'].sum():.4%}"
            f"  [{t0.strftime('%Y-%m-%d')} → {t1.strftime('%Y-%m-%d')}]"
        )

        t0, t1 = self.attrib_dates
        ws.range("A1").value = (
            f"Attribution BHB classique — Fenêtre : {t0.strftime('%Y-%m-%d')} → {t1.strftime('%Y-%m-%d')}"
            " | ⚠️ Tables 1 et 2 sont chacune = R_p−R_b (lecture par dimension, non additive)."
        )

        ws.range("A3").value  = "Table 1 — Sector BHB (Allocation / Sélection / Interaction)"
        t1e = self.attrib_table1.drop(columns=["_company_detail"], errors="ignore")
        self._write_df(ws, "A4", t1e, header=True, index=False)

        ws.range("A28").value = "Table 2 — Region BHB (Allocation / Sélection / Interaction)"
        t2e = self.attrib_table2.drop(columns=["_company_detail"], errors="ignore")
        self._write_df(ws, "A29", t2e, header=True, index=False)

        ws.range("A37").value = "Table 3 — Factor Attribution (OLS cross-sectionnel, indépendant)"
        self._write_df(ws, "A38", self.attrib_table3, header=True, index=False)

        ws.range("A46").value = "Table 4 — Specific Return (résidu factoriel, par titre)"
        t4c = ["ISIN", "w_p", "w_b", "r_i", "r_specific", "Specific Contrib"]
        t4e = self.attrib_table4[[c for c in t4c if c in self.attrib_table4.columns]]
        self._write_df(ws, "A47", t4e, header=True, index=False)

        # ws.range("A123").value = "Récapitulatif indicatif (Tables 1 et 2 non additives)"
        # summary_rows = [
        #     {"Composante": "Sector BHB",  "Valeur": self.attrib_total.get("Sector BHB (indicatif)", "")},
        #     {"Composante": "Region BHB",  "Valeur": self.attrib_total.get("Region BHB (indicatif)", "")},
        #     {"Composante": "Factor Ret",  "Valeur": self.attrib_total.get("Factor Return", "")},
        #     {"Composante": "Specific",    "Valeur": self.attrib_total.get("Specific Return", "")},
        # ]
        # self._write_df(ws, "A124", pd.DataFrame(summary_rows), header=True, index=False)
        # ws.autofit()

    def _export_attribution_ml(self, ws):
        """
        Écrit l'onglet [Attribution ML] — Table 5 ML Score BHB (indépendant).
        """
        if not hasattr(self, "attrib_table5"):
            self.compute_ml_bhb()

        self._clear_used(ws)


        # Affichage du Total Active Contrib ML/MF et fenêtre en E1/F1
        t0, t1 = getattr(self, "attrib_dates", (None, None))
        if t0 and t1:
            ws.range("G3").value = "Total Active Contrib (ML BHB)"   # ou "MF BHB"
            ws.range("H3").value = (
                f"{self.attrib_table5['Active Contrib'].sum():.4%}"  # table6 pour MF
                f"  [{t0.strftime('%Y-%m-%d')} → {t1.strftime('%Y-%m-%d')}]"
            )


        t0, t1 = getattr(self, "attrib_dates", self.ols_dates if hasattr(self, "ols_dates") else (None, None))
        if t0 and t1:
            ws.range("A1").value = (
                f"Table 5 — ML Score BHB — Fenêtre : {t0.strftime('%Y-%m-%d')} → {t1.strftime('%Y-%m-%d')}"
                " | Indépendant — hors total BHB/OLS"
            )

        ws.range("A3").value = "Quintile ML (Q1 = meilleur Score ML, Q5 = moins bon)"
        t5e = self.attrib_table5.drop(columns=["_company_detail"], errors="ignore")
        self._write_df(ws, "A4", t5e, header=True, index=False)
        ws.autofit() 

    def _export_attribution_mf(self, ws):
        """
        Écrit l'onglet [Attribution MF] — Table 6 Score Multifacteur BHB (indépendant).
        """
        if not hasattr(self, "attrib_table6"):
            self.compute_mf_bhb()

        self._clear_used(ws)

        t0, t1 = getattr(self, "attrib_dates", self.ols_dates if hasattr(self, "ols_dates") else (None, None))
        if t0 and t1:
            ws.range("A1").value = (
                f"Table 6 — Score Multifacteur BHB — Fenêtre : {t0.strftime('%Y-%m-%d')} → {t1.strftime('%Y-%m-%d')}"
                " | Indépendant — hors total BHB/OLS"
            )

        ws.range("A3").value = "Quintile MF (Q1 = meilleur Score Multifacteur, Q5 = moins bon)"
        t6e = self.attrib_table6.drop(columns=["_company_detail", "R_bench_total"], errors="ignore")
        self._write_df(ws, "A4", t6e, header=True, index=False)
        ws.autofit()

    def _export_attribution_ols(self, ws):
        """
        Écrit l'onglet [Attribution OLS] — OLS unifié strict (Tables 1-4 additives).

        Disposition :
            A1   : Note + R² + vérification additivité
            A3   : Table 1 OLS — Contribution Secteur par groupe
            A28  : Table 2 OLS — Contribution Région par groupe
            A37  : Table 3 OLS — Contribution Facteur
            A47  : Table 4 OLS — Contribution Spécifique par titre
            I3  : Récapitulatif strict (somme = R_p − R_b)
        """
        if not hasattr(self, "ols_table1"):
            self.compute_ols_attribution()

        self._clear_used(ws)

        t0, t1 = self.ols_dates
        ws.range("A1").value = (
            f"Attribution OLS unifiée — Fenêtre : {t0.strftime('%Y-%m-%d')} → {t1.strftime('%Y-%m-%d')}"
            f" | R² = {self.ols_r2:.4f}"
            f" | ✔ Table1 + Table2 + Table3 + Table4 = R_p − R_b (additivité stricte)"
        )

        ws.range("A3").value  = "Table 1 OLS — Contribution Sectorielle (Secteur, w_p, w_b, OLS Contrib)"
        self._write_df(ws, "A4",  self.ols_table1, header=True, index=False)

        ws.range("A28").value = "Table 2 OLS — Contribution Régionale (Région, w_p, w_b, OLS Contrib)"
        self._write_df(ws, "A29", self.ols_table2, header=True, index=False)

        ws.range("A37").value = "Table 3 OLS — Contribution Factorielle (Factor, Beta, Tilt, Contrib)"
        self._write_df(ws, "A38", self.ols_table3, header=True, index=False)

        ws.range("A47").value = "Table 4 OLS — Contribution Spécifique par titre (ISIN, résidu OLS)"
        t4c = ["ISIN", "w_p", "w_b", "r_i", "r_specific_ols", "Specific Contrib"]
        t4e = self.ols_table4[[c for c in t4c if c in self.ols_table4.columns]]
        self._write_df(ws, "A48", t4e, header=True, index=False)

        ws.range("I3").value  = "Récapitulatif strict (additivité vérifiée)"
        summary_rows = [
            {"Composante": k, "Valeur": v}
            for k, v in self.ols_total.items()
        ]
        self._write_df(ws, "I4", pd.DataFrame(summary_rows), header=True, index=False)
        # ws.autofit()

    # =========================================================================
    # EXPORT EXCEL
    # =========================================================================


    def export_to_excel(self, modules: list = None):
        """Exporte les données vers le template Excel via xlwings."""
        # Génération des images si nécessaire
        if "Analyse 2" in (modules or self._MODULE_MAP.keys()):
            if not getattr(self, "vl_image_path", None):
                self.generate_vl_analysis()
            if not getattr(self, "sentiment_image_path", None):
                self.generate_sentiment_analysis()

        if modules is None:
            modules = list(self._MODULE_MAP.keys())

        print(f"⏳ Export Excel (xlwings) démarré → {os.path.basename(self.path_output)}")

        app = xw.App(visible=False, add_book=False)
        # Optimisations de performance
        app.display_alerts = False
        app.screen_updating = False
        try:
            app.calculation = xw.constants.Calculation.xlCalculationManual
        except Exception:
            pass  # Option parfois indisponible selon versions

        try:
            # wb = xw.Book(self.paths["wb_input"])
            wb = app.books.open(self.paths["wb_input"])

            for module in modules:
                if module in self._MODULE_MAP:
                    sheet_name, method_name = self._MODULE_MAP[module]
                    print(f"   → Export onglet : {sheet_name} ...")

                    if sheet_name in [s.name for s in wb.sheets]:
                        ws = wb.sheets[sheet_name]
                        getattr(self, method_name)(ws)  # appelle les méthodes ci-dessous
                    else:
                        print(f"   ⚠️ Onglet {sheet_name} introuvable dans le template.")

            wb.save(self.path_output)
            print(f"✅ Export terminé : {self.path_output}")

        finally:
            try:
                wb.close()
            except Exception:
                pass
            app.display_alerts = True
            app.screen_updating = True
            try:
                app.calculation = xw.constants.Calculation.xlCalculationAutomatic
            except Exception:
                pass
            app.quit()

    # --------------------------
    # Helpers xlwings
    # --------------------------
    def _clear_used(self, ws):
        """Efface uniquement le contenu des cellules utilisées (pas les formats)."""
        used = ws.used_range
        if used is not None:
            used.clear_contents()

    def _write_df(self, ws, top_left_cell: str, df: pd.DataFrame, header=True, index=False):
        """Écrit un DataFrame en une fois."""
        anchor = ws.range(top_left_cell)
        anchor.options(index=index, header=header).value = df

    def _format_percent_col(self, ws, start_cell: str, nrows: int):
        """Applique un format pour une colonne % à partir d'une cellule de départ."""
        r = ws.range(start_cell)
        ws.range(r.row, r.column).resize(nrows, 1).number_format = "0.00%"

    # --------------------------
    # Équivalents des méthodes d'export
    # --------------------------
    def _export_data(self, ws):
        if not hasattr(self, "screen_final"):
            self.build_screen_final()

        # Fusion du Contrib Alpha (OLS) si disponible
        df = self.screen_final.copy()
        if hasattr(self, "ols_table4") and not self.ols_table4.empty:
            alpha_map = self.ols_table4.set_index("ISIN")['Specific Contrib'].rename("Contrib Alpha")
            df = df.merge(alpha_map, on="ISIN", how="left")

        # Fusion du Contrib TE si disponible
        if hasattr(self, "contrib_te") and not self.contrib_te.empty:
            df = df.merge(self.contrib_te.rename(columns={"contrib_te" : "Contrib TE"}),
                            on = "ISIN", how = "left")

        self._clear_used(ws)
        # Écrit depuis A1 avec header
        self._write_df(ws, "A1", df, header=True, index=False)
        ws.autofit()

    def _export_fonds(self, ws):
        if not hasattr(self, "fund_full"):
            self.build_fund_full()

        df = self.fund_full.copy()

        # Fusion du Contrib Alpha (OLS) si disponible
        if hasattr(self, "ols_table4") and not self.ols_table4.empty:
            alpha_map = self.ols_table4.set_index("ISIN")['Specific Contrib'].rename("Contrib Alpha")
            df = df.merge(alpha_map, on="ISIN", how="left")

        self._clear_used(ws)

        cols_round = [
            "Score Dividend","Score Value", "Score Quality","Score Momentum", "Score Volatility","Score Growth",
            "Beta"
        ]

        for c in cols_round:
            if c in df.columns:
                df[c] = df[c].round(2)

        # Écriture en A1
        self._write_df(ws, "A1", df, header=True, index=False)

        # Format pour la colonne 16 (comme ton code) → 0.00%
        # On repère A1, puis (row=2..n) pour ignorer l'entête si souhaité
        nrows = df.shape[0] + 1  # +1 si header écrit
        # Si tu veux appliquer aux données hors entête seulement:
        # start_cell = ws.range("A1").offset(1, 15)  # ligne 2, colonne 16
        start_cell = ws.range("A1").offset(0, 15)     # inclut l'entête si besoin
        self._format_percent_col(ws, start_cell.get_address(), nrows)

        # Centrer les lignes de données (hors entête)
        data_range = ws.range("A2").expand()
        try:
            data_range.api.HorizontalAlignment = xw.constants.HAlign.xlHAlignCenter
        except Exception:
            pass

        # ws.autofit()

    def _export_benchmark(self, ws):
        if not hasattr(self, "indice_full"):
            self.build_fund_full()

        df = self.indice_full.copy()

        # Fusion du Contrib Alpha (OLS) si disponible
        if hasattr(self, "ols_table4") and not self.ols_table4.empty:
            alpha_map = self.ols_table4.set_index("ISIN")['Specific Contrib'].rename("Contrib Alpha")
            df = df.merge(alpha_map, on="ISIN", how="left")
    
        self._clear_used(ws)
        self._write_df(ws, "A1", df, header=True, index=False)
        # ws.autofit()

    def _export_analyse(self, ws):
        if not hasattr(self, "fund_full"):
            self.build_fund_full()
        if not hasattr(self, "deviation_df"):
            self.get_stock_deviation()

        # Petites valeurs dans des cellules précises
        ws.range((1, 4)).value = "Ptf"        # D1
        ws.range((1, 5)).value = "Benchmark"  # E1
        ws.range((2, 17)).value = getattr(self, "te", None)  # Q2

        # hors_indice_df → H76 (header=False)
        hors = self.hors_indice_df.sort_values(by=["%ACTIF"], ascending=False)
        self._write_df(ws, "H54", hors, header=False, index=False)
        # Somme %ACTIF → J74
        ws.range("J52").value = hors["%ACTIF"].sum()

        # worst_ml → H82 (header=False), 2 colonnes
        worst_ml = self.fund_full[self.fund_full["Score ML"] < 1][["LIBELLE","Score ML"]].sort_values("Score ML")
        self._write_df(ws, "L54", worst_ml, header=False, index=False)

        # top_surexpo → M66 (header=False), total M65
        self._write_df(ws, "L45", self.top_surexpo, header=False, index=False)
        ws.range("M43").value = getattr(self, "surexpo_total", None)

        # top_sousexpo → I66 (header=False), total I65
        self._write_df(ws, "H45", self.top_sousexpo, header=False, index=False)
        ws.range("I43").value = getattr(self, "sousexpo_total", None)

    def _export_newsflow(self, ws):
        if not hasattr(self, "news_flow"):
            self.get_news_flow()
        self._clear_used(ws)
        self._write_df(ws, "A1", self.news_flow, header=True, index=False)

    def _export_topworst(self, ws):
        if not hasattr(self, "perf_df"):
            self.compute_performance()

        cols = ["ISIN", "%ACTIF", "LIBELLE", "ICB19 Supersector", "Perf 1W", "Perf 1M", "Perf YTD", "Perf 1Y"]

        # Top 10 fund → C4
        self._write_df(ws, "C4", self.top10_fund[cols], header=True, index=False)
        # Worst 10 fund → L4
        self._write_df(ws, "L4", self.worst10_fund[cols], header=True, index=False)
        # Top 20 benchmark → C20
        self._write_df(ws, "C20", self.top20_bench[cols], header=True, index=False)
        # Worst 20 benchmark → L20
        self._write_df(ws, "L20", self.worst20_bench[cols], header=True, index=False)

    def _export_analyse_2(self, ws):
        """Insertion d'images VL (B2) et Sentiment (Q2) via xlwings."""
        # Optionnel: supprimer d’anciennes images pour éviter les doublons
        try:
            for p in list(ws.pictures):
                if p.name in {"VL_IMG", "SENT_IMG"}:
                    p.delete()
        except Exception:
            pass

        # 1) Image VL en B2
        if hasattr(self, "vl_image_path") and self.vl_image_path and os.path.exists(self.vl_image_path):
            anchor = ws.range("B2")
            ws.pictures.add(
                self.vl_image_path,
                name="VL_IMG",
                left=anchor.left,
                top=anchor.top,
                scale=1.0  # ajuste si besoin (ex: 0.8)
            )
            print("   → Image historique VL insérée (B2).")
        else:
            print("   ℹ️ Pas d'image VL à insérer.")

        # 2) Image Sentiment en B15
        if hasattr(self, "sentiment_image_path") and self.sentiment_image_path and os.path.exists(self.sentiment_image_path):
            anchor = ws.range("Q2")
            ws.pictures.add(
                self.sentiment_image_path,
                name="SENT_IMG",
                left=anchor.left,
                top=anchor.top,
                scale=1.0
            )
            print("   → Image Sentiment insérée (Q2).")
        else:
            print("   ℹ️ Pas d'image Sentiment à insérer.")

from pdf_report_generator import add_pdf_generation_to_dashboard
PortfolioDashboard.generate_pdf_report = add_pdf_generation_to_dashboard()




