import numpy as np
import pandas as pd
import scipy
import datetime
import os
import copy
import math
# from scipy import stats
from multiprocessing import Pool
from dateutil.relativedelta import relativedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
from typing import Optional, Tuple
from pathlib import Path
import cvxpy as cp
from sklearn.decomposition import PCA
from Codes.Utils_avec_repech_modif_esg import *
import matplotlib.pyplot as plt
import seaborn as sns

pd.options.mode.chained_assignment = None 


class OfficialPortfolioBacktest:
    def __init__(self,
                screen, 
                returns, 
                bench, 
                metrics, 
                ptf_name = "PTF TEST", 
                ponderation='Racine cube',
                esg_exclusion=0,
                liste_noire=r"\\groupe-ufg.com\commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_BASE\_ ESG DATA\Liste_Noire_Exclusion.xlsx",
                score_neutral="ICB 19", 
                weight_neutral="ICB 19",
                Top=True,
                top_mandatory = None, 
                multiprocessing=False,
                mode_monthly_prod=False, 
                output_dir=None,
                score_pivot_esg=None,    # score_pivot_esg = "INDEX MSCI WORLD_vs_1330696"
                score_pivot_esg_path=r"\\groupe-ufg.com\commun\Public\DIRR\Data\riskindics\notes pivots",
                secto_reco_path = r"\\groupe-ufg.com\Commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\0_PTF_BLOOM\reco_secto_facto.xlsx",
                path_output=None,
                obj_func="Min_TE",
                TE_constraint=None,
                te_threshold=None,

                current_params = {
                                    "margin_title": 0.0020,
                                    "margin_sector": 0.004,
                                    "margin_country": 0.005,
                                    "max_turnover": 0.50,
                                    "min_score_target": 6,
                                    "nb_max_titres" : 170,
                                    "nb_min_titres" : 150,
                                    
                                },
                lb_title = {
                                "North America": 0.0020,
                                "West Europe": 0.0010,
                                "Others": 0.0010
                            },
                CONFIG_UB_actif = {
                                    "North America": {
                                        "bins":   [0,     0.002,   float('inf')],
                                        "values": [0.01,  0.0125]
                                    },
                                    "West Europe": {
                                        "bins":   [0,     0.001,   float('inf')],
                                        "values": [0.005, 0.0075]
                                    },
                                    "Others": {
                                        "bins":   [0,     0.0005,   0.001,  float('inf')],
                                        "values": [0.003, 0.004,    0.005]
                                    }
                                },
                scip_options = {
                                    "limits/time": 60,
                                    "limits/gap": 0.01,
                                    "presolving/maxrounds": -1,
                                    "heuristics/actconsdiving/freq": 1,
                                    "randomization/randomseedshift" : 42,
                                },
                ordre_elargissement_contrainte = [
                                                    "ouvir_ub_title", 
                                                    "ouvrir_ub_secto_geo", 
                                                    "ouvrir_ub_country",
                                                    "augmenter_turnover", 
                                                    "diminuer_score_ml"
                                                ], 
                incr_contrainte = {     "ouvir_ub_title" : 0.0010,
                                        "ouvrir_ub_secto_geo": 0.0010,
                                        "ouvrir_ub_country": 0.0010,
                                        "augmenter_turnover" : 0.05,
                                        "diminuer_score_ml" : -0.10
                                    },
                mois_rebal_europe = [1,2,3,4,5,6,7,8,9,10,11,12],
                mois_rebal_us = [1,2,3,4,5,6,7,8,9,10,11,12],
                mode ="backtest",
                ptf_last = None,        
                model_cov = "norm",
                RAPPORT_PAYS = None,
                RAPPORT_SECTO = None,
                path_score_ml_ref = r"\\groupe-ufg.com\commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\1_FACTEUR_ML\4_TEST_OPTIM\Backtest\PTF_historique\score_ml_referent.parquet"           
                                ):
                
        """
        initialisation des paramètres de la classe 

        order for "reco_secto" :
            1: "Auto & Parts",  
            2: "Banks",  
            3: "Basic Resources",  
            4: "Chemicals",  
            5: "Construction",  
            6: "Financial Services",  
            7: "Food, Beverage & Tobacco",  
            8: "Health Care",  
            9: "Industrial Goods & Services",  
            10: "Insurance",  
            11: "Media",  
            12: "Energy",  
            13: "Personal & Household Goods",  
            14: "Real Estate",  
            15: "Retail",  
            16: "Technology",  
            17: "Telecommunications",  
            18: "Travel & Leisure",  
            19: "Utilities"  
        
        order for "reco_facto" :
            1: "Growth",
            2: "Low Vol",
            3: "Momentum",
            4: "Quality",
            5: "Value"

        """
        if ponderation not in ["Racine cube","Racine carrée", "Market cap","Log","Equalweight"]:
            print(" ponderation must be Racine cube, Racine carrée, Market cap, Log or Equalweight")
        else:
            self.ponderation=ponderation

        self.bench=bench
        self.metrics=metrics
        self.ptf_name=ptf_name
        self.score_neutral=score_neutral
        self.weight_neutral=weight_neutral
        self.esg_exclusion=esg_exclusion
        self._liste_noire=liste_noire
        self.top_mandatory=top_mandatory
        self.multiprocessing=multiprocessing
        self.sec_list_monthly=None
        self.path_output=path_output
        self.sec_list_historical=None
        self.list_exclusion_monthly =None
        self.perf_ptf=None
        self.perf_bench=None
        self.buy_list=None
        self.Top = Top
        self.mode_monthly_prod = mode_monthly_prod
        self.output_dir = output_dir
        self.score_pivot_esg = score_pivot_esg
        self.score_pivot_esg_path = score_pivot_esg_path
        self.ptf_last = ptf_last
        self.mode = mode
        self.secto_reco_path = secto_reco_path
        self.current_params = current_params
        self.lb_title = lb_title
        self.CONFIG_UB_actif = CONFIG_UB_actif
        self.scip_options = scip_options
        self.df_constraint = None
        self.ordre_elargissement_contrainte = ordre_elargissement_contrainte
        self.incr_contrainte = incr_contrainte
        self.mois_rebal_europe = mois_rebal_europe
        self.mois_rebal_us = mois_rebal_us
        self.df_plot = None
        self.model_cov = model_cov 
        self.RAPPORT_PAYS = RAPPORT_PAYS
        self.RAPPORT_SECTO = RAPPORT_SECTO 
        self.path_score_ml_ref = path_score_ml_ref
        self.obj_func=obj_func
        self.TE_constraint=TE_constraint
        self.te_threshold=te_threshold 


        if type(screen) not in [str,type(pd.DataFrame())]:
            print("screen must be string or DataFrame")
        else:
            self.screen=copy.deepcopy(screen)

        if type(returns) !=type(pd.DataFrame()):
            print("returns must be DataFrame")
        else:
            self.returns=copy.deepcopy(returns)


    
    def filtrage_esg_liste_noire(self, df, date):
        """
        Filtrage en fonction des performances ESG et de la liste noire.
        Retourne le DataFrame filtré, la liste des exclusions ESG, et la liste noire.
        """
        import copy
        df_esg = copy.deepcopy(df)
        Worst_ESG = []
        Blacklisted = []

        # ESG filtering
        if date.year >= 2014 and isinstance(self.score_pivot_esg, float):
            df_esg = df[df['ESG_ANALYST_SCORE'] > self.score_pivot_esg]
            Worst_ESG = df.loc[~df.index.isin(df_esg.index)].index.tolist() # Toutes les lignes exclues (non dans df_esg) sont les "Worst ESG"

        elif date.year >= 2014 and self.esg_exclusion > 0:  # this will entrer only when if date.year >= 2014 and isinstance(self.score_pivot_esg, float) is FALSE
            esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
            df_esg = df.loc[esg_pct >= self.esg_exclusion]
            Worst_ESG = df.loc[~df.index.isin(df_esg.index)].index.tolist()


        # Blacklist filtering
        if self._liste_noire != None:
            if isinstance(self._liste_noire, str):
                self._liste_noire = read_liste_noire(self._liste_noire, [], [])

            if 'ISIN' in df_esg.columns:
                Blacklisted = df_esg[df_esg['ISIN'].isin(self._liste_noire)].index.tolist()
                df_esg = df_esg[~df_esg['ISIN'].isin(self._liste_noire)]
            elif df_esg.index.name == 'ISIN':
                Blacklisted = df_esg[df_esg.index.isin(self._liste_noire)].index.tolist()
                df_esg = df_esg[~df_esg.index.isin(self._liste_noire)]

        # Save companies excluded beaucause of ESG reason 
        titles_excluded = self.save_esg_blacklist(df, Worst_ESG, Blacklisted)

        return df_esg, titles_excluded


    def find_esg_pivot_file_path(self):
        """
        Trouver le dernier fichier à jour pour le score pivot ESG
        """
        DATE_8DIG_RE = re.compile(r"(\d{8})")

        def parse_yyyymmdd(s: str) -> Optional[datetime.date]:
            """Parse YYYYMMDD string into date, return None if invalid."""
            from datetime import datetime
            try:
                return datetime.strptime(s, "%Y%m%d").date()
            except ValueError:
                return None

        def first_date_in_name(name: str) -> Optional[datetime.date]:
            """
            Return the first valid YYYYMMDD date found in a string (first 8 consecutive digits).
            If no valid 8-digit date exists, return None.
            """
            m = DATE_8DIG_RE.search(name)
            if not m:
                return None
            return parse_yyyymmdd(m.group(1))

        def get_most_recent_dated_subfolder(base_dir: Path) -> Tuple[Optional[Path], Optional[datetime.date], str]:
            """
            Among immediate subfolders of base_dir, select the one with the largest date
            extracted from the first 8 digits in the folder name.

            Fallback: if no subfolder has a valid 8-digit date in the name, pick the
            most recently modified subfolder.

            Returns: (folder_path, extracted_date_or_None, selection_mode)
                    selection_mode in {"by_name_date", "by_mtime", "none"}
            """
            if not base_dir.exists():
                raise FileNotFoundError(f"Base directory does not exist: {base_dir}")
            if not base_dir.is_dir():
                raise NotADirectoryError(f"Not a directory: {base_dir}")

            dated = []
            subdirs = []

            with os.scandir(base_dir) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        subdirs.append(entry)
                        d = first_date_in_name(entry.name)
                        if d:
                            dated.append((d, Path(entry.path)))

            if dated:
                dated.sort(key=lambda x: x[0], reverse=True)
                chosen_date, chosen_path = dated[0][0], dated[0][1]
                return chosen_path, chosen_date, "by_name_date"

            # Fallback: choose most recently modified directory
            if subdirs:
                latest = max(subdirs, key=lambda e: e.stat().st_mtime)
                return Path(latest.path), None, "by_mtime"

            return None, None, "none"

        def get_most_recent_file_by_first_date(folder: Path) -> Tuple[Optional[Path], Optional[datetime.date]]:
            """
            Inside 'folder', pick the file whose FIRST 8-digit date (YYYYMMDD) in its name is the largest.
            If no files contain a valid first 8-digit date, returns (None, None).
            """
            if not folder.exists() or not folder.is_dir():
                raise NotADirectoryError(f"Folder not found or not a directory: {folder}")

            best_date = None
            best_file = None

            with os.scandir(folder) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=False):
                        d = first_date_in_name(entry.name)  # STRICT: first 8 digits only
                        if d is not None:
                            if best_date is None or d > best_date:
                                best_date = d
                                best_file = Path(entry.path)

            return best_file, best_date

        base = Path(self.score_pivot_esg_path)

        # 1) Pick subfolder
        folder, folder_date, mode = get_most_recent_dated_subfolder(base)
        if mode == "none" or folder is None:
            print(f"[!] No subfolders found under: {base}")
            return

        # if mode == "by_name_date":
            # print(f"[OK] Selected folder by date in name: {folder.name} (date={folder_date})")
        # else:
        #     mtime = datetime.fromtimestamp(folder.stat().st_mtime)
        #     print(f"[OK] Selected folder by last modified time: {folder.name} (mtime={mtime})")

        # 2) Pick file inside folder using first 8 digits as date
        file_path, file_date = get_most_recent_file_by_first_date(folder)
        if not file_path:
            print(f"[!] No files with a valid first 8-digit date found in folder: {folder}")
            return

        # print(f"[OK] Selected file by first-8-digit date: {file_path.name} (date={file_date})")
        print(f"[RESULT] Full path for ESG Score Pivot File: {file_path}")
        return file_path

    def get_esg_pivot_score(self, bench_name_in_excel="INDEX MSCI WORLD_vs_1330696"):
        """
        Trouver le score pivot avec le mot clé choisi ()
        """
        path = self.find_esg_pivot_file_path()
        ficher_ESG = pd.read_csv(path,
                                encoding="cp1252",
                                sep="|",   # or "\t", "|", etc.
                                engine="python"
                                )
        note_pivot = ficher_ESG[ficher_ESG['sec_id'] == bench_name_in_excel]['note_pivot'].values[0]
        note_pivot = float(note_pivot)
        return note_pivot


    def neutralise_score_by_secteur(self, df, list_score_col):
        """
        Neutraliser sectoriellement le score pour piocher les tops par secteur par la suite
        """
        df = df.copy()
        df.loc[:, list_score_col] = df[list_score_col].rank(pct=True)
        df.loc[:, list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min()) # min max scaler

        if self.score_neutral == "ICB 11":
            for secto in df[' Benchmark ICB Industry '].unique():
                df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].rank(pct=True)
                df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())
        elif self.score_neutral == "ICB 19":
            for secto in df[' Benchmark ICB Supersector '].unique():
                df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].rank(pct=True)
                df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())
        return df


    def get_portfolio_name(self, style):
        """
        Automatically select portfolio name based on investment style, benchmark, and ranking position
        
        Parameters:
        style (str): Investment style, choose from list_style
        bench (str): Benchmark, supports "SP500" and "STOXX EUROPE 600"
        top (bool): True for Q1 (top 25%), False for Q5 (bottom 25%)
        
        Returns:
        str: Corresponding portfolio name
        """
        
        if self.mode_monthly_prod:
            if self.ptf_name == "PTF TEST":
                # Define investment style list
                list_style = ['Size Avg Percentile', 'Value Avg Percentile','Quality Avg Percentile',
                            'Mom Avg Percentile','LowVol Avg Percentile','Growth Avg Percentile', 
                            'Multi Avg Percentile']
                
                # Define benchmark to region mapping
                bench_to_region = {
                    'SP500': 'US',
                    'MSCI US': 'US',
                    'STOXX EUROPE 600': 'EU'
                }
                
                # Define style to portfolio type mapping
                style_to_type = {
                    'Size Avg Percentile': 'SIZE',
                    'Value Avg Percentile': 'VALUE',  
                    'Quality Avg Percentile': 'QUALITY',
                    'Mom Avg Percentile': 'MOM',
                    'LowVol Avg Percentile': 'LOWVOL',
                    'Growth Avg Percentile': 'GROWTH',
                    'Multi Avg Percentile': 'MF'
                }
                
                # Validate input parameters
                if style not in list_style:
                    raise ValueError(f"Style '{style}' not in supported style list: {list_style}")
                
                if self.bench not in bench_to_region:
                    raise ValueError(f"Benchmark '{self.bench}' not supported. Supported benchmarks: {list(bench_to_region.keys())}")
                
                # Get region and portfolio type
                region = bench_to_region[self.bench]
                portfolio_type = style_to_type[style]
                
                # Select Q1 or Q5 based on top parameter
                quintile = 'Q1' if self.Top else 'Q5'
                
                # Construct portfolio name
                ptf_name = f"FS_{region}_{portfolio_type}_{quintile}"

                if ptf_name == 'FS_EU_MF_Q1' and self.esg_exclusion>0:
                    ptf_name = "FS_EU_MF_ESG_Q1"
                if ptf_name == 'FS_EU_MF_Q5' and self.esg_exclusion>0:
                    ptf_name = "FS_EU_MF_ESG_Q5"
            
            if self.ptf_name != "PTF TEST":
                ptf_name = self.ptf_name

        if self.mode_monthly_prod != True:
            ptf_name = self.ptf_name

        return ptf_name

    def save_portfolio_data_incremental(self, df_concat, output_dir, date_obj=None):
        """
        Save portfolio data to Excel file incrementally.
        Creates file if it doesn't exist, otherwise appends new data.
        
        Parameters:
        df_concat (DataFrame): New data to save
        output_dir (str): Output directory path
        date_obj (datetime.date): Date object for folder naming (default: current date)
        """
        
        if date_obj is None:
            date_obj = pd.to_datetime(df_concat['Date']).iloc[0]
        
        # Create output file path
        # folder_name = date_obj.strftime("%B %Y")
        folder_name = date_obj.strftime("%m %Y")
        folder_path = os.path.join(output_dir, f"Pour {folder_name}")
        output_file = os.path.join(folder_path, "PTFS TO PUSH.xlsx")
        # Create directory if it doesn't exist
        os.makedirs(folder_path, exist_ok=True)
        
        # Prepare new data
        new_data = df_concat[['PTF', 'ISIN', 'Weight', 'Date']].copy()
        
        # Check if file exists
        if os.path.exists(output_file):
            try:
                # Read existing data
                existing_data = pd.read_excel(output_file)
                print(f"Found existing file with {len(existing_data)} records")
                # Supprimer les lignes de existing_data dont 'PTF' est présent dans new_data
                existing_data = existing_data[~existing_data['PTF'].isin(new_data['PTF'])]


                # Combine existing and new data
                combined_data = pd.concat([existing_data, new_data], ignore_index=True, axis=0)
                
                # Remove duplicates based on all columns (optional)
                # You might want to modify this logic based on your needs
                combined_data = combined_data.drop_duplicates(subset=['PTF', 'ISIN', 'Date'], keep='last')
                
                print(f"After combining and deduplicating: {len(combined_data)} records")
                
            except Exception as e:
                print(f"Error reading existing file: {e}")
                print("Creating new file with current data only")
                combined_data = new_data
        else:
            print("File doesn't exist, creating new file")
            combined_data = new_data
        
        # Write combined data to Excel
        try:
            with pd.ExcelWriter(output_file, datetime_format='dd/mm/yyyy') as writer:
                combined_data.to_excel(writer, index=False)
            
            print(f"Successfully saved {len(combined_data)} records to: {output_file}")
            
        except Exception as e:
            print(f"Error writing to file: {e}")
            raise

  

    def save_esg_blacklist(self, screen: pd.DataFrame, Worst_ESG: list, Blacklisted: list) -> pd.DataFrame:
        """
        Filters the screen DataFrame to include only ISINs present in Worst_ESG or Blacklisted.
        Adds a 'Raison Exclusion' column indicating the reason(s) for exclusion.
        Keeps only rows where at least one of these flags is True.

        Parameters:
        - screen: pd.DataFrame with ISINs as index and a 'Date' column.
        - Worst_ESG: list of ISINs flagged for worst ESG.
        - Blacklisted: list of ISINs that are blacklisted.

        Returns:
        - pd.DataFrame with 'Date' and 'Raison Exclusion' columns.
        """
        # Combine ISINs from both lists
        filtered_isins = set(Worst_ESG).union(set(Blacklisted))

        # Filter the screen DataFrame to include only relevant ISINs
        filtered_df = screen.loc[screen.index.intersection(filtered_isins)].copy()

        # Determine reasons for exclusion
        reasons = []
        for isin in filtered_df.index:
            reason = []
            if isin in Worst_ESG:
                reason.append("ESG Reason")
            if isin in Blacklisted:
                reason.append("Blacklisted")
            reasons.append(", ".join(reason))

        # Assign the reasons to a new column
        filtered_df["Raison Exclusion"] = reasons

        # Keep only the required columns
        final_df = filtered_df[["Date", "Raison Exclusion"]]

        return final_df



    def build_optimized_monthly_security_list(self, drift, screen_agg_monthly=None, init = False,alpha_=0):
        """
        Generate Best Scored Sec List for 1 Month, According to the Metrics Chosen
        """

        print("###############################################")
        print("CONSTRUCTION DU PORTEFEUILLE")
        print("###############################################")
        screen=copy.deepcopy(screen_agg_monthly)
        print("Yohan")
        liste_noire = read_liste_noire(self._liste_noire, [], [])
        screen = generate_screen_for_optim(screen, 
                                           self.ptf_last, 
                                           self.returns, 
                                           self.bench, 
                                           liste_noire, 
                                           init, 
                                           drift)
        date = pd.to_datetime(screen['Date'].max())
        self.bool_rebal_Europe, self.bool_rebal_US = define_bool_rebal(date, 
                                                                        self.mois_rebal_europe, self.mois_rebal_us)

        print(f"alpha shift pour score ref = {alpha_}")
        # Score ML Referent
        score_ml_ref = pd.read_parquet(self.path_score_ml_ref)
        score_ml_ref['Date'] = pd.to_datetime(score_ml_ref['str_date'], format='%Y%m')
        try:
            target_row = score_ml_ref[score_ml_ref["Date"] == date]["score_ml_referent"]
            self.current_params["min_score_target"] = target_row.iloc[0] + alpha_
        except Exception as e:
            print("pas de score referenct trouvé")
            self.current_params["min_score_target"] = 0


        
        # self.current_params["min_score_target"] = 6
        print("Score ML Referent : ", self.current_params["min_score_target"])

        # Def poids secteur et pays cibles
        df_sector_cible, df_pays_cible, result_df = define_secto_target_and_geo_target2(secto_reco_path = self.secto_reco_path, 
                                                                                    df = screen, 
                                                                                    date = date, 
                                                                                    bench = self.bench, 
                                                                                    bool_rebal_Europe = self.bool_rebal_Europe, 
                                                                                    bool_rebal_US = self.bool_rebal_US,
                                                                                    seuil_petit_secteur = 0.0015,
                                                                                    pct_dev_secto = 2,
                                                                                    )

        # Def lb et ub titres
        result_df =  define_lb_ub(df_full = result_df, 
                                lb_title = self.lb_title, 
                                CONFIG_UB = self.CONFIG_UB_actif, 
                                bench_4_ub = self.bench, 
                                margin_title = self.current_params["margin_title"], 
                                top_mandatory = self.top_mandatory,
                                bool_rebal_Europe = self.bool_rebal_Europe, 
                                bool_rebal_US = self.bool_rebal_US
                                )


        # Verification des contraintes (renvoie la liste des secteurs et pays ou il manquent de titres)
        prob_secto_add, prob_pays_add = verifier_contraintes(result_df, self.current_params["margin_country"], self.current_params["margin_sector"], df_sector_cible, df_pays_cible, name_col = "Weight in "+ self.bench)
        
        # Repechage sur les secteur et pays ou il manque des titres
        while len(prob_secto_add + prob_pays_add) > 0 :
            K_eligible = len(result_df[result_df["ub"] > 0.0010])
            result_df = selection_repechage(result_df, prob_secto_add, prob_pays_add, self.bench, self.CONFIG_UB_actif, self.lb_title)
            prob_secto_add, prob_pays_add = verifier_contraintes(result_df, self.current_params["margin_country"], self.current_params["margin_sector"], df_sector_cible, df_pays_cible, name_col = "Weight in "+ self.bench)
            if K_eligible == len(result_df[result_df["ub"] > 0.0010]) :  # Condition qui permet de verifier si le repechage n'a pas trouvé de titres à repecher on sort de la boucle
                print("Repechage fini")
                break

        df_sector_cibletemp=df_sector_cible.rename(columns={'Weight in ' + self.bench : "PoidsSectGeo"})
        result_df = result_df.merge(df_sector_cibletemp[["Key_Secto_Geo",'PoidsSectGeo', "Before tilt W in MSCI WORLD"]],how="left",on="Key_Secto_Geo")
        result_df.loc[result_df['PoidsSectGeo'] == 0, 'lb'] = 0
        result_df.loc[result_df['PoidsSectGeo'] == 0, 'ub'] = 10e-6


        report_quality_on_ISIN_SEDOl=check_data_integrity(result_df)
        print(report_quality_on_ISIN_SEDOl)

        
        sigma = generate_covariance_matrix(result_df, self.returns , self.model_cov)    

        #####
        # 1. Définition du chemin racine (utilisation de r"" pour éviter les problèmes d'anti-slashs Windows)
        output_folder = r"PTF_historique"

        # 2. Extraction de la date depuis le DataFrame
        # On récupère la première valeur de la colonne 'Date' et on la convertit en chaîne
        date_val = result_df["Date"].iloc[0].strftime('%Y-%m-%d')

        # 3. Construction du nom du fichier
        file_name = f"result_df_{date_val}.pkl" # ou .xlsx selon votre besoin
        full_path = os.path.join(self.path_output, file_name)
        result_df.to_pickle(full_path) 

        #####

        result_df, state = optimize(result_df, sigma, df_sector_cible, df_pays_cible, self.bench, self.current_params, init, self.scip_options, self.bool_rebal_Europe, self.bool_rebal_US,path_output=self.path_output,obj_func=self.obj_func,TE_constraint=self.TE_constraint,te_threshold=self.te_threshold) 

        new_params = self.current_params.copy()
        while state not in ["optimal", "optimal_inaccurate"] :

            # while state not in ["optimal"] :
            print("ECHEC")
            print(self.incr_contrainte)
            for theme_to_adjust in self.ordre_elargissement_contrainte :
                result_df, new_params= adjust_constraint(result_df, 
                                                                theme_to_adjust, 
                                                                self.incr_contrainte, 
                                                                new_params)

            if new_params["min_score_target"] < self.current_params["min_score_target"] - 0.39 :
                new_params["max_turnover"] += 0.10

            result_df, state = optimize(result_df, sigma, df_sector_cible, df_pays_cible, self.bench, new_params, init, self.scip_options, self.bool_rebal_Europe, self.bool_rebal_US,path_output=self.path_output,obj_func=self.obj_func,TE_constraint=self.TE_constraint,te_threshold=self.te_threshold)       
                
        result_df2, self.RAPPORT_PAYS, self.RAPPORT_SECTO = generate_exposure_reports(result_df, df_pays_cible, df_sector_cible)

        self.df_constraint = log_constraints(
                                                self.df_constraint, 
                                                result_df2,
                                                date, 
                                                self.RAPPORT_SECTO, 
                                                self.RAPPORT_PAYS, 
                                                self.current_params,
                                                sigma,
                                                self.bench
                                            )

        result_df2 = result_df2.rename(columns = {"Wopt" : 'Weight'})
        result_df2 = result_df2[result_df2["Weight"] > 0.0001]
        self.ptf_last = result_df2

        file_name = f"df_contraintes{date_val}.pkl" # ou .xlsx selon votre besoin
        full_path = os.path.join(self.path_output, file_name)
        self.df_constraint.to_pickle(full_path)
        result_df2["PTF"] = "PTF IA"
        result_sec_list = result_df2[["PTF", "Name", 'ISIN', 'Weight', 'Exchange Country Region', "Key_Secto_Geo", 'Date', 'Secto', 'Score ML', "Raison Exclusion", "lb", "ub", "Weight_last_drift" ]]

        return result_sec_list



    def update_ptf_with_monthly_drift(self, df):
        """
        For every month present in the portfolio (including the first and last),
        check whether the following month already exists.   
        If it does **not** exist, drift the weight of the current month until the
        date forward by one month, and append it to the dataframe.
        """
        ptf = df.copy()

        # Add SEDOL for drift using returns df ######## raise error if not completly mapping
        sedol_to_isin = dict(zip(self.screen.index, self.screen['Company SEDOL'])) 
        ptf['SEDOL'] = ptf['ISIN'].map(sedol_to_isin)


        existing_dates = ptf.sort_values('Date')['Date'].unique()
        print("Longueur sec_list avant : ", len(existing_dates))

        today = datetime.datetime.now()
        
        for date in existing_dates:  # premier du mois
            next_month = date + pd.DateOffset(months=1)
            date_fin_drifter = date + pd.DateOffset(months=1)
            # print(f"for {date}, date_fin_drifter is {date_fin_drifter}")

            # Si on entre dans le if suivant, c'est à dire, on commence à drifter
            if next_month not in existing_dates:
                if next_month <= today:  # Condition pour sortir : si next month est superieur 
                    # Get the current month's portfolio data
                    current_month_data = ptf[ptf["Date"] == date].copy()
                    
                    # Prepare parameters for drift function
                    col_id = "SEDOL"
                    col_weight = "Weight"
                    col_date = "Date"
                    
                    # Use drift logic to adjust weights
                    next_month_df = drift_weight(
                        current_month_data,
                        col_id,
                        self.returns.copy(),
                        col_date,
                        col_weight,
                        date_fin_drifter
                    )
                    # print(next_month_df['Date'].unique())

                    next_month_df['Date'] = date_fin_drifter
                    # print(next_month_df['Date'].unique())
                    # Append the drifted month to the main dataframe
                    ptf = pd.concat([ptf, next_month_df], axis=0).sort_values("Date")
                else:
                    print("Longueur sec_list après : ", len(existing_dates))
                    return ptf
            else:
                return ptf
        return ptf

    def update_ptf_with_monthly_additions(self, df):
        """
        For every month present in the portfolio (including the first and last),
        check whether the following month already exists.  
        If it does **not** exist, create a copy of the current month, shift the
        date forward by one month, and append it to the dataframe.
        """
        # keep a set for O(1) membership checks
        ptf = df.copy()

        existing_dates = set(ptf["Date"].unique())
        print("Longueur sec_list avant : " , len(existing_dates))

        sorted_existing_dates = sorted(existing_dates)  # Exemple : 01-10 , 03-10 , 05-10 ect
        today = datetime.datetime.now()
        for date in sorted_existing_dates:  
            
            next_month = date + pd.DateOffset(months=1)
            
            # Continue adding months until there are no more gaps
            while next_month not in existing_dates :
                if  next_month > today : # Condition pour sortir : si next month est superieur 
                    break
                else :    
                    prev_ptf = ptf[ptf["Date"] == date].copy()
                    prev_ptf["Date"] = next_month
                    ptf = pd.concat([ptf, prev_ptf]).sort_values("Date").reset_index(drop=True)
                    
                    # Update the set so that we don't add the same month twice
                    existing_dates.add(next_month)
                    
                    # Move to the newly added month for further checks
                    date = next_month
                    next_month += pd.DateOffset(months=1)
                
            if next_month > today  :
                break
        
        print("Longueur sec_list après : ", len(existing_dates))
        return ptf
    

    def find_next_closest_date(self, start_date, offset):
        """
        Finds the next closest date to start_date from the given DataFrame.

        Parameters:
        - start_date (datetime): The reference date.
        - screen_agg (pd.DataFrame): A DataFrame containing a 'Date' column with datetime objects.

        Returns:
        - datetime: The next closest date that satisfies the conditions.
        
        Raises:
        - ValueError: If start_date is not a datetime object or if no valid dates are found.
        """
        screen_agg = copy.deepcopy(self.screen)
        
        # Calculer les différences absolues entre chaque date et la start_date
        screen_agg = screen_agg[screen_agg["Date"]>=start_date]
        dates = screen_agg["Date"].unique()
        dates = pd.to_datetime(dates)

        closest_date = min(dates, key=lambda d: abs(d - start_date)) # Prend la date du screen_agg après start_date la plus proche


        # Si offset = 0, je rentre dans le if si closest_date est un mois pair cela permettra de prendre la date d'apres qui est forcement un mois impair
        # Si offset = 1, je rentre dans le if si closest_date est un mois impair cela permettra de prendre la date d'apres qui est forcement un mois pair
        if closest_date.month%2==offset:   
            dates = screen_agg[screen_agg["Date"]>closest_date]["Date"].unique()
            dates = pd.to_datetime(dates)

            closest_date = min(dates, key=lambda d: abs(d - start_date))

        return closest_date

    def build_historical_security_lists(self, start_date = None, end_date = None, screen_start_date = "mois_impair", drift = True, alpha_=0):
        """
        Apply a function to subsets of financial data based on specified frequency.
        
        Parameters:
        -----------
        func : function
            The function to apply to each subset of data
        start_date : str or datetime
            The earliest date to include in the analysis
        *args : 
            First argument is screen_agg (DataFrame or path to parquet file)
            Remaining arguments are passed to func
        freq : int, optional
            The frequency in months for selecting dates
        rebalancing_start_backward : datetime, optional
            If provided, the latest date will be the date in the month before this date
        
        Returns:
        --------
        DataFrame
            Combined results from the function applied to each subset
        """
        
        screen_agg = copy.deepcopy(self.screen)
        if type(screen_agg) == str:
            screen_agg = pd.read_parquet(screen_agg)
        
        if start_date is not None : 
            #START DATE commence en  mois pair
            if screen_start_date == "mois_pair" :
                self.start_date  = self.find_next_closest_date(start_date,1)
            elif screen_start_date == "mois_impair" :
                self.start_date  = self.find_next_closest_date(start_date,0)
            else:
                self.start_date = start_date

            print( "Premiere date du screen_agg prise en compte : " , self.start_date)

            # Filter by start_date
            screen_agg = screen_agg[(screen_agg['Date'] >= self.start_date) & (screen_agg['Date'] <= end_date)]


        all_dates = sorted(screen_agg['Date'].unique())
        
        if not all_dates:
            return pd.DataFrame()  # Return empty DataFrame if no dates
        
        self.df_constraint = pd.DataFrame(columns=["ecart_max_secto", "ecart_max_pays", "nb_titres_under_lb", "nb_titres_over_ub", "turnover", "score_ml_agg", "nb_titres", "Tracking Error"])

        # Apply function - handle possible parallelization issues
        result_sec_list=[]

        
        # Create subsets for each date
        if self.mode == "spot":
            screen_list = [screen_agg.loc[screen_agg['Date'] == date_] for date_ in [all_dates[-1]]] 
            screen_temp = screen_list[0]
            screen_temp["Date"] = pd.to_datetime(screen_temp["Date"])
            date_screen = screen_temp["Date"].max()
            date_screen_lag = screen_agg[screen_agg["Date"] < date_screen]["Date"].max()
            screen_temp_lag = screen_agg[screen_agg["Date"] == date_screen_lag].reset_index()[["ISIN", "Company SEDOL", "Score ML", " Benchmark ICB Supersector ", 'Exchange Country Region', 'Name']]
            dict_map_geo = {"West Europe" : "West Europe",
                            "North America" : "North America",
                            "Mid East" : "Others" ,
                            "Asia" : "Others",
                            "Pacific" : "Others",
                            "Africa" : "Others",
                            "East Europe" : "Others",
                            "South America":"Others",
                            "Others":"Others",
                            }
            screen_temp_lag["Exchange Country Region"] = screen_temp_lag["Exchange Country Region"].map(dict_map_geo)
            screen_temp_lag["Secto"] = screen_temp_lag[" Benchmark ICB Supersector "]

            self.ptf_last = pd.merge(self.ptf_last, screen_temp_lag, on = "ISIN", how = "left")
            result = self.build_optimized_monthly_security_list(screen_agg_monthly=screen_list[0], drift = drift, alpha_ =alpha_) 
        else : 
            screen_list = [screen_agg.loc[screen_agg['Date'] == date_] for date_ in all_dates]
            result = self.build_optimized_monthly_security_list(screen_agg_monthly=screen_list[0], init = True, drift = drift, alpha_ =alpha_) 
        
        result_sec_list.append(result)

        if len(screen_list)>1:
            for screen in screen_list[1:]:
                result = self.build_optimized_monthly_security_list(screen_agg_monthly=screen, drift = drift, alpha_ =alpha_)  # result[0] is sec_list, result[1] is liste exclusion
                result_sec_list.append(result)

            
        # Concatenate seclist results
        if result_sec_list and isinstance(result_sec_list[0], pd.DataFrame):
            df = pd.concat(result_sec_list, ignore_index=True)
        else:
            # Handle the case where func doesn't return DataFrames
            df = pd.DataFrame(result_sec_list)


        # for bimestriel situation
        self.sec_list_historical = df.copy()


        print(f"Historical sec list is generated, you can check 'self.sec_list_historical' attribute for more details.")
        print(f"Historical exclusion list is generated, you can check 'self.list_exclusion' attribute for more details.")
        
        return df
    

    def backtest_calcul_all_portfolio(self,df_rebal, df_returns, col_weight,col_sector = ' Benchmark ICB Supersector ', col_date='Date', col_id = 'Company SEDOL'):
        """
        permet de générer les returns des portfolios
        df_rebal: contient les coefficients de poids 
        df_returns: returns des actifs
        """
        
        # Creating a list of available date in sec list (MONTHLY) - premier jour du mois
        liste_rebal_date = list(df_rebal.index.get_level_values(col_date).unique())
        # Creating a list of date (DAILY), but from returns dataframe, starting from the first date of the sec list
        liste_date_returns = list(df_returns[df_returns.index>=liste_rebal_date[0]].index)

        #filtrer pour avoir la période du portefeuille
        df_rebal.reset_index(inplace=True)
    
        df_rebal = df_rebal[df_rebal[col_id].isin(df_returns.columns)] #SUPPRESSION DES TITRES QUI NE SONT PAS DS LE RETURN
        df_rebal.set_index(col_date,inplace=True)

        # Normalisation
        df_rebal['Portfolio weight'] = (
                                        df_rebal.groupby(col_date)['Portfolio weight']
                                        .transform(lambda x: x / x.sum())
                                        )
        
        df_rebal.reset_index(inplace=True)
    
    
        # Boucle dans le cas d'une date de rebalancement non présente dans df_returns -> changement de la date de rebalancement avec la 2eme date future la plus proche
        for i in range(len(liste_rebal_date)) :
            if  liste_rebal_date[i] not in liste_date_returns :

                try:
                    # Try pour chercher la 2eme date future la plus proche

                    # Supposons que liste_date_returns soit une liste de pd.Timestamp
                    serie_date_returns = pd.Series(liste_date_returns)

                    new_date_rebal = serie_date_returns[serie_date_returns > liste_rebal_date[i]].iloc[1]

                except ValueError:
                    # Si pas de future date trouvée, on prend la date antérieure la plus proche (cas frequency=1 dernière date est une date de rebalancement)
                    new_date_rebal = max(d for d in liste_date_returns if d < liste_rebal_date[i])



            else :
                # Supposons que liste_date_returns soit une liste de pd.Timestamp
                serie_date_returns = pd.Series(liste_date_returns)

                new_date_rebal = serie_date_returns[serie_date_returns > liste_rebal_date[i]].iloc[0]

            df_rebal = df_rebal.replace(liste_rebal_date[i], new_date_rebal)
            liste_rebal_date[i] = new_date_rebal

        # Tri avec la fonction sorted()
        liste_date_all = list(set(liste_rebal_date).union(set(liste_date_returns)))
        nouvelle_liste_dates = sorted(liste_date_all)
    
        #df_rebal = df_rebal.set_index([col_id,col_date])
    
        new_df = pd.DataFrame(data=nouvelle_liste_dates, columns=['Date_returns']) #INSTANCIATION dataframe AVEC COLONNE DE DATE DAILY
        
        #ON MET DS LE DF DAILY LES DATES DE REBAL POUR ENSUITE PRENDRE LES POIDS REBAL SANS LES FAIRE DRIFTER. A chaque date du mois on a la derniere date de rebal
        """
        This code does the following:
        For each date in the "Date_returns" column of the new_df dataframe, it searches in the df_rebal dataframe for all dates in the 
        col_date column that are less than or equal to the given date. 
        Then, it selects the maximum of these dates, representing the most recent REBALACING date before or on that date. 
        This value is then assigned to the "Date_screen" column in new_df.
        """
        new_df['Date_screen'] = new_df['Date_returns'].apply(lambda x: df_rebal.loc[df_rebal[col_date]<=x, col_date].max())
        
        #ON DUPPLIQUE LES DATES DE SCREEN MENSUEL POUR CHAQUE DATE de new DF dont la colonne Date Screen = col_date de df_rebal (date de rebalancement)
        df_merge = pd.merge(df_rebal,new_df, how='left', left_on=col_date, right_on = 'Date_screen')
        df_merge.drop(columns=col_date, inplace=True)
        df_merge.rename(columns={'Date_returns':col_date},inplace=True) #BONNE COLONNE DE DATE
        df_merge.sort_values(by=col_date, inplace=True)
    
        df_returns = df_returns[new_df['Date_screen'].min():] # ON garde LES RETURN A PARTIR DE LA PREMIERE DATE des returns
        returns_cum = (1+df_returns).cumprod() # On a le ttr calculé pour à partir de la 1ère date de rebalancement
        
        #ON REBASE LES DRIFT CUMULE à 1 à chaque date de rebal
        returns_drift = returns_cum.apply(lambda x:x/returns_cum.loc[(new_df.loc[new_df['Date_screen']<=x.name,'Date_screen'].max())], axis=1)
        """
        Date	Asset_A (drift_multiplicator)	Asset_B (drift_multiplicator)
        2021-01-01	1.00	1.00
        2021-01-02	1.10	0.95
        2021-01-03	1.15	1.05
        XXXXXXXXXX
        2021-02-01  1.00    1.00
        """

        #ON FLATTEN POUR METTRE EN 1 COLONNE
        returns_drift_flat = returns_drift.stack().to_frame().reset_index(names=[col_date, col_id])
        returns_drift_flat.columns=[col_date, col_id, 'drift_multiplicator']
        """
        Date	    Asset	drift_multiplicator
        2021-01-01	Asset_A	    1.00
        2021-01-01	Asset_B	    1.00
        2021-01-02	Asset_A	    1.10
        2021-01-02	Asset_B	    0.95
        2021-01-03	Asset_A	    1.15
        2021-01-03	Asset_B	    1.05
        """

        returns_flat=df_returns.stack().to_frame().reset_index()
        returns_flat.columns=[col_date, col_id, 'Return']
        """
        Date		Asset		Return
        2021-01-01	Asset_A		0.00
        2021-01-01	Asset_B		0.00
        2021-01-02	Asset_A		0.10
        2021-01-02	Asset_B		-0.05
        2021-01-03	Asset_A		0.05
        2021-01-03	Asset_B		0.10
        """

    
        df_merge = df_merge.merge(returns_drift_flat, how='left', on = [col_date, col_id]) #AJOUT DE 'drift_multiplicator'
        df_merge = df_merge.merge(returns_flat, how='left', on = [col_date, col_id])
        
        #CHAQUE POIDS DAILY est DRIFTé dont celui du rebal qui est aussi drifté par 1
        df_merge[col_weight+'_drifted'] = df_merge[col_weight]*df_merge['drift_multiplicator'] 
        """ EX. the weight af asset A is 0.6, drift_multiplicator is 1.1, then drifted weight : 0.6 * 1.1 = 0.66 """
        

        # Select the date, asset identifier, original weight, drift-adjusted weight, sector (or segment), 
        # and return data to form a new data frame `portfolio_tet`, facilitating subsequent calculations by date and asset.
        columns = [col_date, col_id, col_weight, col_weight+'_drifted', col_sector, 'Return']
        portfolio_tet=df_merge[columns]
        
        # Sum the drifted weights of all assets by date to obtain the total drift weight of all assets for that day
        weight_sum_date = portfolio_tet.groupby(col_date,group_keys=False)[[col_weight+'_drifted']].sum()
        weight_sum_date.columns = ['Weight_sum']
        weight_sum_date.reset_index(inplace=True)
        
        # Merge this total drift weight into portfolio_tet
        portfolio_tet = portfolio_tet.merge(weight_sum_date, how='left', on = col_date)
        
        # Divide the drifted weight of each asset by the total drift weight of that day to obtain the normalized weight W_rebased. 
        # This ensures that the sum of the normalized weights of all assets for each date equals 1.
        portfolio_tet['W_rebased'] = portfolio_tet[col_weight+'_drifted'] / portfolio_tet['Weight_sum']

        """
        Ex:
        Suppose on a given day, the drifted weight of Asset A is 0.66, and the drifted weight of Asset B is 0.38. The total drifted weight is 0.66 + 0.38 = 1.04.

        The normalized weight of Asset A: 0.66 / 1.04 ≈ 0.635  
        The normalized weight of Asset B: 0.38 / 1.04 ≈ 0.365
        """

        # For each asset (grouped by col_id), shift the normalized weight W_rebased down by one row, i.e., retrieve the normalized weight from the previous day.
        # This is typically done to calculate the daily contribution of each asset by multiplying the previous day's weight BY the current day's return, 
        # thereby determining the asset's contribution to the portfolio's daily return.
        portfolio_tet['W_rebased_shift1'] = portfolio_tet.groupby(col_id)['W_rebased'].shift(1)
        
        # Calculate the contribution of each asset: multiply the previous day's normalized weight by the current day's return.
        # Then, sum the contributions of all assets by date to obtain the total return contribution of the portfolio for each day.
        portfolio_tet['Contrib'] = portfolio_tet['W_rebased_shift1'] * portfolio_tet['Return']
        total_return_by_date = portfolio_tet.groupby(col_date)['Contrib'].sum()
        """
        Ex.
        If on a given day, Asset A's previous day weight is 0.635 and its current day return is 0.10, its contribution is 0.0635.
        If Asset B's previous day weight is 0.365 and its current day return is -0.05, its contribution is -0.01825.
        Total contribution = 0.0635 + (-0.01825) ≈ 0.04525.
        """

        # Starting with an initial value of 1, add the daily total return contribution (filling missing values with 0) and calculate the cumulative product to obtain the cumulative return of the entire portfolio
        total_return_by_date.sort_index(inplace=True)
        serie_ttr=(1 + total_return_by_date.fillna(0)).cumprod() * 100 
        """
        Example:
        Assume the cumulative calculation is as follows:
        Contribution on the first day is 0.00 → (1 + 0.00) = 1.00
        Contribution on the second day is 0.04525 → Cumulative return is 1.00 × 1.04525 ≈ 1.04525
        Contribution on the third day is 0.02 → Cumulative return is 1.04525 × 1.02 ≈ 1.06516
        Multiplying by 100, the cumulative return is 106.516%, representing a growth of 6.516% relative to the initial value.
        """    

        return serie_ttr
        
    def backtest_create_ptf_weight(self,sec_list, 
                        indice_name, 
                        screen_agg,
                        max_weight ,  
                        col_mkt_cap='Benchmark Market Value Millions in EUR ', 
                        col_date = 'Date', 
                        col_sector = ' Benchmark ICB Supersector ', 
                        sector_neutral=False, method='mkt_cap', 
                        col_sedol = 'Company SEDOL', 
                        col_isin= 'ISIN'
                        ):
        """
        Générer les ptfs en duplicant les poids de l'indice => pour backtest la perf de l'indice par la suite
        C'est une version simplifiée de la fonction "build_monthly_security_list"       
        """
        # INDICE, SCREENAGGREGATE et SECLIST SERONT INVESTI AU 1er du mois
        # Filter Bench related securities and take the weight of bench as sec list
        screen_agg=copy.deepcopy(screen_agg)
        indice = screen_agg.loc[screen_agg['Weight in '+indice_name]>0, [col_date, col_sedol,col_sector,'Weight in '+indice_name]].reset_index()
        indice.rename(columns={'Weight in '+indice_name:'Indice weight'}, inplace= True)
    
        indice.sort_values(by=col_date,inplace=True)
        sec_list.sort_values(by=col_date,inplace=True)

        indice[col_date] = indice[col_date] + pd.offsets.MonthBegin(1)
        screen_agg[col_date] = screen_agg[col_date] + pd.offsets.MonthBegin(1)

        # Add some columns of screen in sec list
        sec_list = sec_list.merge(right = screen_agg.reset_index()[[col_date,col_isin,col_sedol,col_sector, col_mkt_cap]], on=[col_date,col_isin], how='left')
        sec_list = sec_list[sec_list[col_sedol].notna()]
    
        if method=='EW': # Equal weight
            sec_list.set_index(col_date,inplace=True)
            sec_list['Portfolio weight'] = sec_list.groupby(col_date, group_keys=False).apply(lambda x: 1/len(x))
            sec_list.reset_index(inplace=True)
        else:
            sec_list = sec_list[sec_list[col_mkt_cap].notna()]                                                                      
            if method == "Racine cube":
                sec_list[col_mkt_cap] = sec_list[col_mkt_cap]**(1/3)
            elif method == "Racine carrée":
                sec_list[col_mkt_cap] = sec_list[col_mkt_cap]**(1/2)
            elif method == "Log":
                sec_list[col_mkt_cap] = np.log(sec_list[col_mkt_cap])
            sec_list.set_index(col_date,inplace=True)
            sec_list['Portfolio weight'] = sec_list[col_mkt_cap]/sec_list.groupby(col_date)[col_mkt_cap].sum()
            sec_list.reset_index(inplace=True)
    
        # Calculate the ratio of the benchmark index's total sector weight to the portfolio's total sector weight, which serves as the adjustment factor for each sector.  
        # Adjust the weight of each stock in the portfolio according to this ratio, ensuring that the total sector weight in the adjusted portfolio matches the sector weight of the benchmark index.
        if sector_neutral:
            indice.set_index(col_date,inplace=True)
            indice['Indice weight'] /= indice.groupby(col_date)['Indice weight'].sum()
            indice.reset_index(inplace=True)
            weight_secto_bench = (indice.groupby([col_date,col_sector])['Indice weight'].sum()).reset_index()
        
            sec_list.set_index(col_date,inplace=True)
            sec_list['Portfolio weight'] /= sec_list.groupby(col_date)['Portfolio weight'].sum()
            sec_list.reset_index(inplace=True)
            sec_list.set_index([col_date,col_sector],inplace=True)
            sec_list['weight_secto_ptf'] = sec_list.groupby([col_date,col_sector],group_keys=False)['Portfolio weight'].sum()
            sec_list.reset_index(inplace=True)
    
            sec_list = sec_list.merge(weight_secto_bench[[col_date,col_sector,'Indice weight']], on=[col_date,col_sector], how='left')
            sec_list['Portfolio weight'] = sec_list['Portfolio weight'] * (sec_list['Indice weight']/sec_list['weight_secto_ptf'])
    
        # Handle outliers
        sec_list.set_index(col_date,inplace=True)
        sec_list['Portfolio weight'] /= sec_list.groupby(col_date)['Portfolio weight'].sum()
        sec_list['Portfolio weight'] = sec_list['Portfolio weight'].apply(lambda x : min(x,max_weight))
        sec_list['Portfolio weight'] /= sec_list.groupby(col_date)['Portfolio weight'].sum()
        sec_list.reset_index(inplace=True)
        
        return sec_list[[col_date, col_sedol,col_isin, 'Portfolio weight', col_sector]].set_index([col_date,col_sedol])
    
    def run_portfolio_nav(self,sec_list=None,
                indice_name=None,
                method=None,    
                max_weight = 1, 
                col_sector= ' Benchmark ICB Supersector ', 
                col_sedol='Company SEDOL', 
                col_isin='ISIN', 
                col_date = 'Date', 
                col_mkt_cap = 'Benchmark Market Value Millions in EUR ', 
                sector_neutral=False,
                sec_list_=True, 
                ponderation='mkt_cap', critere='Score ML',
                max_weights= [0.025,0.015,0.02,0.02,0.02,0.02,0.02,0.03,0.015,0.02,0.02,0.035,0.03,0.02,0.02,0.02,0.02,0.02,0.02], 
                list_secto=[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], repechage_filter=['Sector ICB19'], 
                nb_titres= 150, te_max= 0.03,rebalancing_start_backward=None):
        # if sec_list is not provided used self.sec_list
        if  sec_list is None:
                if self.sec_list_historical != None:
                    sec_list=self.sec_list_historical
                else:
                    sec_list=self.build_historical_security_lists( method=method, critere=critere,max_weights= max_weights, 
                            list_secto=list_secto, repechage_filter=repechage_filter, 
                            nb_titres= nb_titres, te_max=te_max,rebalancing_start_backward=rebalancing_start_backward, alpha_=0)

        # if input is path, then read the parquet, if it's a df, then use it directly
        if type(self.screen)==str:
            screen_agg = pd.read_parquet(self.screen)
        else:
            screen_agg=copy.deepcopy(self.screen)
    
        if type(self.returns)==str:
            df_returns = pd.read_parquet(self.returns)
        else:
            df_returns=copy.deepcopy(self.returns)

        # Loading sec_list
        buy_list = copy.deepcopy(sec_list)
        
        # For a normal ptf that weight column is included
        if sec_list_ :
            if 'Weight' in buy_list.columns:
                # AVOIR UNE SECLIST AU 1ER DU MOIS pour MATCHER AVEC SCREEN AGGREGATE QUI SERA SHIFTé du 31 du mois au 1er du mois suivant
                sec_list_full = buy_list[[col_date,col_isin,'Weight']].copy()  ## COPY for avoid warning

                ### Rebalancing weight for each date ###
                sec_list_full['Weight'] = (
                                            sec_list_full.groupby(col_date)['Weight']
                                            .transform(lambda w: w / w.sum())
                                            )
                
                # Outliers transformation into [0, 1]
                sec_list_full['Weight'] = sec_list_full['Weight'].apply(lambda x : max(x,0))
                sec_list_full['Weight'] = sec_list_full['Weight'].apply(lambda x : min(x,max_weight))


                ### Redo rebalancing
                sec_list_full["WeightSum"] = sec_list_full.groupby("Date")["Weight"].transform("sum")
                sec_list_full['Weight'] /= sec_list_full["WeightSum"]

                sec_list_full.reset_index(inplace=True)

                sec_list_full.rename(columns={'Weight':'Portfolio weight'},inplace=True) # Rename column of weight

                # Make sure that column of date is datetime format
                screen_agg[col_date] = pd.to_datetime(screen_agg[col_date])

                # Then push the date to the first day of the next month
                screen_agg[col_date] = screen_agg[col_date] + pd.offsets.MonthBegin(1)

                # Generating final seclist
                sec_list_full = sec_list_full.merge(right = screen_agg.reset_index()[[col_date,col_isin,col_sedol,col_sector, col_mkt_cap]], on=[col_date,col_isin], how='left')
                sec_list_full = sec_list_full[sec_list_full[col_sedol].notna()] # Remove empty sedol companies
                sec_list_full = sec_list_full[[col_date, col_sedol,col_isin, 'Portfolio weight', col_sector]].set_index([col_date,col_sedol])
                
                # Calcule TTR
                perf_ttr = self.backtest_calcul_all_portfolio(sec_list_full, df_returns, 'Portfolio weight', col_sector, col_date, col_sedol)
                self.perf_ptf, self.buy_list=perf_ttr, sec_list_full[[col_date,col_isin,'Portfolio weight', col_sector]]
                print('Performance of sec_list is calculated, please check attribute "self.perf_ptf" for more details')
            else:
                print("Is not a sec_list")
            
        # For generating all titles sec list for a BENCHMARK
        else:
            # AVOIR UNE SECLIST AU 1ER DU MOIS pour MATCHER AVEC SCREEN AGGREGATE QUI SERA SHIFTé du 31 du mois au 1er du mois suivant
            sec_list_full = self.backtest_create_ptf_weight(buy_list, indice_name, screen_agg, max_weight, col_mkt_cap, col_date, col_sector, sector_neutral,ponderation,col_sedol, col_isin)
            perf_ttr = self.backtest_calcul_all_portfolio(sec_list_full, df_returns, 'Portfolio weight', col_sector, col_date, col_sedol)
            
            self.perf_bench = perf_ttr
            print('Performance of benchmark is calculated, please check attribute "self.perf_bench" for more details')

        return perf_ttr, self.buy_list

    def run_benchmark_nav(self,screen,start_date,bench):
        """
        Calculer la perf de l'indice choisi
        """
        indice_ref = screen[(screen['Date']>=start_date) & (screen['Weight in '+bench]>0)].reset_index()[['Date','ISIN']]
        indice_ref["Date"] = pd.to_datetime(indice_ref["Date"])
        indice_ref["Date"] = indice_ref["Date"] + pd.offsets.MonthBegin(1)
        self.run_portfolio_nav(sec_list=indice_ref,indice_name=bench,sec_list_=False)

    def plot_portfolio_vs_benchmark(self, perf_ptf=None, perf_bench=None, title=None, save_path="portfolio_performance.html", show_plot=True):
        """
        - Avoir tous les perfs : ptf et bench
        - Ploter les perfs
        """
        if self.perf_ptf is None:
            perf_ptf, buy_list = self.run_portfolio_nav(self.sec_list_historical)
        perf_ptf, buy_list = self.perf_ptf, self.buy_list

        if self.perf_bench is None:
            self.run_benchmark_nav(self.screen, self.start_date, self.bench)
        perf_bench = self.perf_bench
        
        # Concatenate dataframes
        df_plot = pd.concat([perf_ptf, perf_bench], axis=1)

        # Create subplots
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                            subplot_titles=("Performance", "Ratio"))

        # Add traces for performance
        for i, col in enumerate(df_plot.columns):
            label = 'Perf PTF' if i == 0 else 'Perf Bench'

            # Add line trace
            fig.add_trace(go.Scatter(
                x=df_plot.index,
                y=df_plot.iloc[:, i],
                mode='lines',
                name=label,
                line=dict(width=2)
            ), row=1, col=1)

            # Add annotation for last value
            last_x = df_plot.index[-1]
            last_y = df_plot.iloc[:, i].iloc[-1]

            fig.add_annotation(
                x=last_x,
                y=last_y,
                text=f'{last_y:.2f}',
                showarrow=False,
                xanchor='left',
                font=dict(size=10),
                bgcolor='rgba(255,255,255,0.8)',
                bordercolor='rgba(0,0,0,0.2)',
                borderwidth=1
            )

        # Add trace for the ratio
        ratio = df_plot.iloc[:, 0] / df_plot.iloc[:, 1]
        fig.add_trace(go.Scatter(
            x=df_plot.index,
            y=ratio,
            mode='lines',
            name='Ratio',
            line=dict(width=2, color='red')
        ), row=2, col=1)

        # Add annotation for last value of the ratio
        last_ratio = ratio.iloc[-1]
        fig.add_annotation(
            x=last_x,
            y=last_ratio,
            text=f'{last_ratio:.2f}',
            showarrow=False,
            xanchor='left',
            font=dict(size=10),
            bgcolor='rgba(255,255,255,0.8)',
            bordercolor='rgba(0,0,0,0.2)',
            borderwidth=1
        )

        # Update layout
        fig.update_layout(
            title=title if title else "",
            width=700,
            height=600,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            margin=dict(l=50, r=50, t=50, b=50),
            plot_bgcolor='white',
            paper_bgcolor='white'
        )

        # Update axes
        fig.update_xaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor='lightgray',
            showline=True,
            linewidth=1,
            linecolor='black'
        )

        fig.update_yaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor='lightgray',
            showline=True,
            linewidth=1,
            linecolor='black'
        )

        # Handle different environments
        if save_path:
            # Save as HTML file
            fig.write_html(save_path)
            print(f"Plot saved as HTML to: {save_path}")

        if show_plot:
            try:
                # Try to show in browser
                fig.show()
            except Exception as e:
                print(f"Cannot display plot directly: {e}")
                # Save as temporary HTML file and provide instructions
                temp_path = "temp_plot.html"
                fig.write_html(temp_path)
                print(f"Plot saved as HTML to: {temp_path}")
                print("Please open this file in your web browser to view the plot.")

        df_plot.columns = ['Portfolio', 'Benchmark']

        self.df_plot = df_plot

        return df_plot
    

    def plot_tracking_error(self, window=21):
        """
        Calcule la Tracking Error glissante sur une période donnée.
        
        Args:
            df_plot (pd.DataFrame): DataFrame contenant les prix/valeurs du 
                                    portefeuille et du benchmark (2 colonnes).
            window (int): Fenêtre glissante en jours (par défaut 30).
            
        Returns:
            pd.Series: La Tracking Error annualisée glissante.
        """
        const_histo = self.df_constraint
        df_plot = self.df_plot
        # 1. Calcul des rendements quotidiens (pct_change)
        returns = df_plot.pct_change().dropna()
        
        # On s'assure d'avoir seulement deux colonnes et on les nomme pour plus de clarté
        # Supposons que la col 0 est le PTF et la col 1 est le BENCH
        ptf_ret = returns.iloc[:, 0]
        bench_ret = returns.iloc[:, 1]
        
        # 2. Calcul de l'Active Return (différence des rendements)
        active_return = ptf_ret - bench_ret
        
        # 3. Calcul de l'écart-type glissant (Rolling Std)
        # On multiplie par sqrt(252) pour annualiser la Tracking Error
        rolling_te = active_return.rolling(window=window).std() * np.sqrt(252)
        rolling_te.name = "TE realise"
        result = pd.merge(rolling_te, const_histo["Tracking Error"], left_index=True, right_index=True, how='outer')

        result["Tracking Error"] = result["Tracking Error"].ffill()
        result.columns = ["TE realise", "TE ex-ante"]

        sns.set_theme(style="whitegrid")
        plt.figure(figsize=(12, 6))

        result.plot(linewidth=2)

        # --- FIXATION DES LIMITES DE L'AXE Y ---
        plt.ylim(0, 0.07) 
        # --------------------------------------

        plt.title("Evolution du Tracking Error", fontsize=15)
        plt.ylabel("Tracking Error")
        plt.show()
        return result

