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

import warnings 
warnings.simplefilter(action='ignore')


def drop_duplicates_keep_less_missing(screen):
    """
    This function removes duplicate rows based on ISIN and Date, 
    keeping the version of each duplicate that has the fewest missing values (i.e., the most complete data).
    """
    screen = screen.reset_index()

    subset = ['ISIN', 'Date']  # columns that define duplicates

    # Score rows: higher = better (fewer NaNs)
    score = screen.notna().sum(axis=1)

    # Sort so the "best" row in each duplicate group comes first
    df_best = (
        screen.assign(_score=score)
            .sort_values(subset + ['_score'], ascending=[True] * len(subset) + [False])
            .drop_duplicates(subset=subset, keep='first')
            .drop(columns='_score')
    )

    df_best = df_best.set_index("ISIN")

    return df_best


def  read_liste_noire(file_list_noire, override_exclusion=[], override_inclusion=[], key="ISIN", exclu_type=["ex_all"]):
    """
    Cette fonction va sortir les ISINs exclus par le groupe.
    exclu_type = ["ex_all"] or ["ex_all", "Controverse"]
    """
    liste_noire = pd.read_excel(file_list_noire)

    # Filtrer les lignes où au moins une des colonnes de exclu_type vaut 1
    filtre = liste_noire[exclu_type].fillna(0).astype(int).any(axis=1)
    liste_noire = liste_noire[filtre]

    liste_noire = liste_noire.dropna(subset=key)[key].tolist()
    if len(override_exclusion) > 0 :
        liste_noire = np.concatenate([liste_noire,np.array(override_exclusion)])
    liste_noire_unique = np.unique(liste_noire)
    liste_noire_finale = list(set(liste_noire_unique) - set(override_inclusion))
    return liste_noire_finale

def merge_weight_by_pairs(df: pd.DataFrame,
                        pairs,
                        weight_col='Weight in MSCI WORLD',
                        drop_second=True): 
    """
    Combiner le poids des entreprises doublons dans le benchmark choisi (par défaut MSCI WORLD)
    Liste à complérer manuellement une fois constatée
    """
    # Ensure "ISIN" is the index of df
    if df.index.name != "ISIN" and "ISIN" in df.columns:
        df.set_index("ISIN", inplace=True)

    # Ensure the weight column is numeric (coerce errors to NaN)
    if weight_col not in df.columns:
        raise KeyError(f"Column '{weight_col}' not found in DataFrame.")

    for keep, drop in pairs:
        has_keep = keep in df.index
        has_drop = drop in df.index

        if has_keep and has_drop: # Only when entreprisese existent dans le screen
            w_keep = df.at[keep, weight_col]
            w_drop = df.at[drop, weight_col] # same as loc but only for one value

            df.at[keep, weight_col] = w_keep + w_drop

            if drop_second:
                # errors='ignore' avoids exceptions if it was dropped elsewhere
                df.drop(index=drop, inplace=True, errors='ignore')
    return df

def merge_ticker_secondaire(df, bench):
        """
        Préparer les merges des ISINs doublons
        Combiner le poids des entreprises doublons dans le benchmark choisi (par défaut MSCI WORLD)
        Liste à complérer manuellement une fois constatée

        """
        isin_pairs = [
                        "US02079K3059", # Google
                        "US02079K1079",

                        "DK0010244508", # A.P. Moller
                        "DK0010244425", 
                        
                        "SE0017486889", # Atlas Copco
                        "SE0017486897",

                        "DE0005190003", # Bayerische Motoren Werke
                        "DE0005190037",

                        "SE0015658109", # Epiroc
                        "SE0015658117",

                        "CH1499059983",
                        "CH0012032113", # Roche Holding

                        "CH0024638196",
                        "CH0024638212", # Schindler


                        "CH0010570767", # Lindt
                        "CH0010570759",

                        "DE0006048432", # Henkel
                        "DE0006048408",

                        "SE0000107203", # Industrivarden
                        "SE0000190126"
                ]

        # Convert to list of (keep, drop) pairs in order
        if len(isin_pairs) % 2 != 0:
                raise ValueError("The ISIN list length must be even (pairs of 2).")

        pairs = list(zip(isin_pairs[::2], isin_pairs[1::2]))

        df = merge_weight_by_pairs(
                        df=df,
                        pairs=pairs,
                        weight_col=f'Weight in {bench}',
                        drop_second=True    # drop the second ISIN after merging
                        )
        return df

class OfficialPortfolioBacktest:
    def __init__(self,
                screen, 
                returns, 
                bench, 
                percentile, 
                metrics, 
                ptf_name = "PTF TEST", 
                ponderation='Racine cube',
                esg_exclusion=0.2,
                cut_mkt_cap=0,
                liste_noire=r"\\groupe-ufg.com\commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_BASE\_ ESG DATA\Liste_Noire_Exclusion.xlsx",
                reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                reco_facto = [0,0,0,0,0],
                score_neutral="ICB 19", 
                weight_neutral="ICB 19",
                Top=True,
                top_mandatory = None, 
                multiprocessing=False,
                mode_monthly_prod=False, 
                output_dir=None,
                cap_weight_threshold=None,
                score_pivot_esg=None,    # score_pivot_esg = "INDEX MSCI WORLD_vs_1330696"
                score_pivot_esg_path=r"\\groupe-ufg.com\commun\Public\DIRR\Data\riskindics\notes pivots"):
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
        self.percentile=percentile
        self.cut_mkt_cap=cut_mkt_cap
        self.metrics=metrics
        self.ptf_name=ptf_name
        self.score_neutral=score_neutral
        self.weight_neutral=weight_neutral
        self.esg_exclusion=esg_exclusion
        self._liste_noire=liste_noire
        self.top_mandatory=top_mandatory
        self.multiprocessing=multiprocessing
        self.sec_list_monthly=None
        self.sec_list_historical=None
        self.list_exclusion_monthly =None
        self.list_exclusion_histo=None
        self.perf_ptf=None
        self.perf_bench=None
        self.buy_list=None
        self.Top = Top
        self.mode_monthly_prod = mode_monthly_prod
        self.output_dir = output_dir
        self.cap_weight_threshold = cap_weight_threshold
        self.score_pivot_esg = score_pivot_esg
        self.score_pivot_esg_path = score_pivot_esg_path

        if type(screen) not in [str,type(pd.DataFrame())]:
            print("screen must be string or DataFrame")
        else:
            self.screen=copy.deepcopy(screen)

        if type(returns) !=type(pd.DataFrame()):
            print("returns must be DataFrame")
        else:
            self.returns=copy.deepcopy(returns)

        if type(reco_secto) not in [str, list, type(pd.DataFrame())]:
            print("reco_secto must be list or DataFrame")
        else:
            self.reco_secto=copy.deepcopy(reco_secto)

        if type(reco_facto) not in [str, list, type(pd.DataFrame())]:
            print("reco_facto must be list or DataFrame")
        else:
            self.reco_facto=copy.deepcopy(reco_facto)


    def adjust_companies_ponderation(self,df):
        """
        pondération des Benchmarck Market Value pour réduire les effets de taille
        
        """
        df = df.copy()

        if self.ponderation == "Racine cube":
            df.loc[:, 'Benchmark Market Value Millions in EUR '] = df['Benchmark Market Value Millions in EUR ']**(1/3)
        elif self.ponderation == "Racine carrée":
            df.loc[:, 'Benchmark Market Value Millions in EUR '] = df['Benchmark Market Value Millions in EUR ']**(1/2)
        elif self.ponderation == "Market cap":
            df.loc[:, 'Benchmark Market Value Millions in EUR '] = df['Benchmark Market Value Millions in EUR ']
        elif self.ponderation == "Log":
            df.loc[:, 'Benchmark Market Value Millions in EUR '] = np.log(df['Benchmark Market Value Millions in EUR '])
        elif self.ponderation == "Equalweight":
            df['Benchmark Market Value Millions in EUR '] = 1/len(df)

        return df
    
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


    def adjust_bench_weight_with_recommandation(self, df, reco_secto, date):
        """
        1 - Calculer les weights sectoriels du bench 
        2 - Appliquer les reco sectorielles si besoin
        """
        if self.weight_neutral == "ICB 19":
            weight_secto_bench = \
                    df.groupby(' Benchmark ICB Supersector ')['Weight in ' + self.bench].sum() / df['Weight in ' + self.bench].sum()
            icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
            if len(icb_missing) > 0:
                print(f"Warning: follwing sectors are missing in benchmark: {list(icb_missing)}")
                try:
                    indices_to_delete = [int(icb)-1 for icb in icb_missing] # find out where need to be deleted and then mark it as 1
                    reco_secto = np.delete(np.array(reco_secto), indices_to_delete) # delete function can delete several values at a same time, no need to do iteration
                except:
                    print(date)

            # Recommandation sectorielle
            weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1)   

            # Adjust small weight sectors
            small_weight_mask = weight_secto_bench < 0.0025
            sectors_to_be_adjusted = weight_secto_bench[small_weight_mask].index
            if not sectors_to_be_adjusted.empty:
                # print(f"Warning: follwing sectors have weight lower than 0.0025, their weight will be replace as 0.0025: {sectors_to_be_adjusted.tolist()}")
                weight_secto_bench[small_weight_mask] = 0.0025

        elif self.weight_neutral == "ICB 11":
            weight_secto_bench = \
                    df.groupby(' Benchmark ICB Industry ')['Weight in ' + self.bench].sum() / df['Weight in ' + self.bench].sum()
        
        return weight_secto_bench

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

    def cap_weight_by_sector(self, ptf, n_iteration=30):
        """
        Cap individual stock weights while redistributing excess weight proportionally
        to other companies within the same sector
    
        Parameters:
        ptf: DataFrame with columns ['Date', 'Secto', 'Weight']
        threshold: Maximum weight limit for individual stocks
        n_iteration: Maximum number of iterations
    
        Returns:
        DataFrame with adjusted weights
        """
        threshold = self.cap_weight_threshold

        result = ptf.copy()
    
        for iteration in range(n_iteration):
            
            # Track if any adjustment was made for early termination
            has_adjustment = False
        
            # Process each date separately
            for date in result['Date'].unique():
                date_mask = result['Date'] == date
                date_data = result[date_mask].copy()
                
                # Process each sector separately
                for sector in date_data['Secto'].unique():
                    sector_mask = date_data['Secto'] == sector
                    sector_data = date_data[sector_mask].copy()
                
                    # Find overweight stocks
                    overweight_mask = sector_data['Weight'] > threshold
                
                    if overweight_mask.any():
                        has_adjustment = True
                    
                        # Calculate total excess weight
                        excess_weight = (sector_data.loc[overweight_mask, 'Weight'] - threshold).sum()
                    
                        # Cap overweight stocks to threshold
                        sector_data.loc[overweight_mask, 'Weight'] = threshold
                    
                        # Find underweight stocks (those not exceeding threshold)
                        underweight_mask = ~overweight_mask
                        underweight_data = sector_data[underweight_mask]
                    
                        if len(underweight_data) > 0:
                            # Calculate total weight of underweight stocks
                            underweight_total = underweight_data['Weight'].sum()
                        
                            if underweight_total > 0:
                                # Distribute excess weight proportionally to underweight stocks
                                allocation_ratio = excess_weight / underweight_total
                                sector_data.loc[underweight_mask, 'Weight'] = (
                                    sector_data.loc[underweight_mask, 'Weight'] * (1 + allocation_ratio)
                                )
                    
                        # Update results
                        result.loc[date_mask & (result['Secto'] == sector), 'Weight'] = sector_data['Weight'].values
        
            # Early termination if no adjustments were made
            if not has_adjustment:
                break
        
        return result

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


    def select_titles(self, group, max_weight_threshold, column):
        """
            Sélectionne un nombre minimum de titres dans un secteur afin de respecter
            une contrainte de poids maximum par titre.
        
            Cette fonction calcule le poids total du secteur, détermine le nombre
            minimal de titres nécessaires pour que chacun ne dépasse pas le seuil
            de poids maximum défini, puis sélectionne les titres ayant les valeurs
            les plus élevées en mérique choisie (ex. Score ML).
        
            Paramètres
            ----------
            group : pandas.DataFrame
                Sous-ensemble du DataFrame contenant uniquement les titres du secteur
                considéré. Doit contenir au minimum la colonne :
                - "Weight in <benchmark>" : poids de chaque titre dans le benchmark.
        
            max_weight_threshold : float
                Poids maximum toléré pour un titre dans le portefeuille. Le nombre
                minimal de titres est calculé de manière à ce qu'aucun ne dépasse ce seuil.
        
            column : str
                Nom de la colonne utilisée pour sélectionner les titres avec les valeurs
                les plus élevées (utilisée avec `nlargest`).
        
            Retour
            ------
            pandas.DataFrame
                Un DataFrame contenant uniquement les titres sélectionnés selon la
                contrainte de poids et la logique de ranking sur la colonne donnée.
        
            Notes
            -----
            - Le nombre minimal de titres est arrondi à l’entier supérieur.
            - Si le secteur a un poids total de 0, aucun titre ne sera sélectionné.
        
        """
        sector_weight = group['Weight in ' + self.bench].sum()  # Get the sector's total weight
        min_titles_needed = (sector_weight // max_weight_threshold) + (1 if sector_weight % max_weight_threshold != 0 else 0) # Division euclidienne pour connaitre le min de titre a avoir
        
        # sector = group[" Benchmark ICB Supersector "].unique()

        # Choisir les minimum de titres pour respecter la contrainte
        selected_titles = group.nlargest(int(min_titles_needed), column)  
        
        return selected_titles

    def build_monthly_security_list(self,screen_agg_monthly=None):
        """
        Generate Best Scored Sec List for 1 Month, According to the Metrics Chosen
        """

        if isinstance(screen_agg_monthly, pd.DataFrame):
            screen=copy.deepcopy(screen_agg_monthly)
        elif screen_agg_monthly==None: # If single month dataframe is not defined, then use the last month data to generate ptf
            screen = self.screen[self.screen['Date'] == self.screen['Date'].max()] 

        
        if type(self.metrics)==str:
            list_score_col = [self.metrics]
        else:
            list_score_col = self.metrics


        ################ use only the last month's screen (production mode) ################ 
        date = pd.to_datetime(screen['Date'].max())
        # screen=screen[screen['Date']==date]

        if screen.index.duplicated().any():
            screen = screen[~screen.index.duplicated(keep='first')]

        ################ Merging les tickers secondaires ################
        screen = merge_ticker_secondaire(screen, self.bench)

        ################ Filtrage Bench ################
        df = screen[screen['Weight in ' + self.bench]>0] # on conserve que les weights positifs
        list_exclusion_bench = screen.loc[~screen.index.isin(df.index)].index.to_list() # For later merge with other list of exclusion

        ################ Fixer le nombre de boite à choisir pour plus tard avant que le df soit modifié ################
        if self.percentile > 1:   ##### If percentile is bigger than 1, then this variable means exact number of securities to pick
            nb_securities=self.percentile
        else: ##### If percentile is less than 1, then this variable means the percentage of securities in investable univers to pick
            nb_securities = round(len(df) * self.percentile)

        ################ donne le 1er jour du mois suivant ################
        date +=pd.offsets.MonthBegin(1)

        ################################################################################################################################
        if self.metrics == "Multi Avg Percentile":  ### Reco facto will only activated when using "Multi Avg Percentile" as metric
            # Recommandtions Sectorielles à la date donnée
            if isinstance(self.reco_facto, list):
                reco_facto =np.array(self.reco_facto)
            elif isinstance(self.reco_facto, pd.DataFrame):
                try:
                    reco_facto = self.reco_facto.loc[date] 
                except : 
                    print(f"{date} not in reco_facto")
                    raise KeyError
                
            if (reco_facto.sum() == 0) : 
                reco_facto = np.array([0.2]*5)
            else:
                reco_facto = np.array(reco_facto/reco_facto.sum())

            list_style = ['Growth Avg Percentile','LowVol Avg Percentile','Mom Avg Percentile','Quality Avg Percentile','Value Avg Percentile']
            df.loc[:, 'Multi Avg Percentile'] = df[list_style].dot(reco_facto)

        ################################################################################################################################
        # regression de Benchmark value sur weight in bench pour compléter les valeurs manquantes
        fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR ']) == False, 'Weight in ' + self.bench],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR ']) == False, 'Benchmark Market Value Millions in EUR '], deg = 1)
        func = np.poly1d(fit)
        df.loc[pd.isna(df['Benchmark Market Value Millions in EUR ']),'Benchmark Market Value Millions in EUR '] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR ']),'Weight in ' + self.bench])
        # Market cut filtrage
        df.loc[df['Benchmark Market Value Millions in EUR '] <= self.cut_mkt_cap, list_score_col] = np.nan
        list_exclusion_market_cut = df[df['Benchmark Market Value Millions in EUR '] <= self.cut_mkt_cap].index.to_list()  # on note les entreprises hors de benchmark, For later merge with other list of exclusion
        
        df = df.copy()
        df.loc[:, 'Date'] = date
    
        # Ajuster le poids des titres dans l'indice (smoothing)
        df=self.adjust_companies_ponderation(df)

        # Recommandtions Sectorielles à la date donnée
        if isinstance(self.reco_secto, list):
            reco_secto =copy.deepcopy(self.reco_secto)
        elif isinstance(self.reco_secto, pd.DataFrame):
            try:
                reco_secto = self.reco_secto.loc[date].to_list() 
            except : 
                print(f"{date} not in reco_secto")
                raise KeyError
        
        # Appilquer les reco sectorielle aux secteurs
        weight_secto_bench = self.adjust_bench_weight_with_recommandation(df, reco_secto, date)

        # Initiate Dataframe for liste exclusion
        titles_excluded = pd.DataFrame(columns=['Date', "Raison Exclusion"])

        # Filtrage ESG only if we choose Top ptf
        if self.Top:
            # if self.score_pivot_esg is string then it will find corresponding item note in excel, 
            # if self.score_pivot_esg is float, it will use it as threshold, 
            # if self.score_pivot_esg is None, filter by esg pivot score will not apply
            if isinstance(self.score_pivot_esg, str):
                print(f"Récupération de Score Pivot ESG avec index {self.score_pivot_esg}......")
                self.score_pivot_esg = self.get_esg_pivot_score(bench_name_in_excel = self.score_pivot_esg) 
            if isinstance(self.score_pivot_esg, float):
                print(f"Score Pivot ESG est {self.score_pivot_esg}")
            df, titles_excluded = self.filtrage_esg_liste_noire(df,date)  

        # Combine titles_excluded with Market Cut Exclusion
        default_date = titles_excluded['Date'].iloc[0] if not titles_excluded.empty else date  # Add date for exclusion liste dataframe

        # Create exclusion dataframe for market cut reason
        new_entries_exclusion = pd.DataFrame({
            'Date': [default_date] * len(list_exclusion_market_cut),
            'Raison Exclusion': ['Cut Market'] * len(list_exclusion_market_cut)
        }, index=list_exclusion_market_cut)

        titles_excluded = pd.concat([titles_excluded, new_entries_exclusion], axis=0) # Concat avec le dataframe de début

        # Create exclusion dataframe for not in bench reason reason
        new_entries_not_in_bench = pd.DataFrame({
            'Date': [default_date] * len(list_exclusion_bench),
            'Raison Exclusion': ["Not in Bnech"] * len(list_exclusion_bench)
        }, index=list_exclusion_bench)


        if not new_entries_not_in_bench.empty and not new_entries_not_in_bench.isna().all().all():
            titles_excluded = pd.concat([titles_excluded, new_entries_not_in_bench], axis=0)
            

        df = self.neutralise_score_by_secteur(df, list_score_col) 

        df["Raison Repechage"] = ""

        columns = ['PTF', 'ISIN', 'Weight', 'Date', "Raison Repechage"]
        result_sec_list = pd.DataFrame()

        for i in range(len(list_score_col)):

            if self.Top == True:
                df_top = df.nlargest(nb_securities,list_score_col[i])
                df_top['Raison Repechage'] = list_score_col[i]  # Mettre la métrique de repechage comme raison, ex. Score ML/ Growth Avg Percentile

                # Selection du minimum de titres minimum par secteur pour respecter la contrainte de poid max (self.cap_weight_threshold)
                if self.cap_weight_threshold != None:
                    df_top_sector =  df.groupby(' Benchmark ICB Supersector ').apply(self.select_titles, max_weight_threshold=self.cap_weight_threshold, column = list_score_col[i])
                    df_top_sector = df_top_sector.drop( columns = [" Benchmark ICB Supersector "] )
                    df_top_sector = df_top_sector.reset_index(drop=False)
                    df_top_sector.index = df_top_sector["ISIN"]
                    df_top_sector = df_top_sector.drop( columns = ["ISIN"] )
                    df_top_sector["Raison Repechage"] = "Sector"
                
                    # Concat les deux top list
                    df_top_combined = pd.concat([df_top, df_top_sector], axis=0)
                    df_top = df_top_combined[~df_top_combined.index.duplicated(keep='first')]  # Prioritize top selected with classical way

                # Add non selected titles in list exclusion beacause of metrics
                list_exclusion_metrics = df.loc[~df.index.isin(df_top.index)].index.to_list()
                new_entries_exclusion = pd.DataFrame({
                    'Date': [default_date] * len(list_exclusion_metrics),
                    'Raison Exclusion': [f"Bad {list_score_col[i]}"] * len(list_exclusion_metrics)
                }, index=list_exclusion_metrics)

                # Append to the existing final_df
                titles_excluded = pd.concat([titles_excluded, new_entries_exclusion], axis=0)
                titles_excluded.index.name = "ISIN"
                if "ISIN" in titles_excluded.columns:
                    titles_excluded = titles_excluded.drop( columns = ["ISIN"] )
                titles_excluded = titles_excluded.reset_index()


            if self.Top == False:
                df_top=df.nsmallest(nb_securities,list_score_col[i])
                df_top['Raison Repechage'] = "Worst Metric"

            if isinstance(self.top_mandatory, int) or isinstance(self.top_mandatory, float):
                nb_top_mandatory = int(self.top_mandatory)
                # print(f"Top Mandatory is activated, top {nb_top_mandatory} companies in bench will be added to sec list")
                liste_top_mandatory = df.nlargest(nb_top_mandatory, 'Weight in ' + self.bench)
                liste_top_mandatory['Raison Repechage'] = "Top Obligatoire par Région"

                df_top_combined = pd.concat([liste_top_mandatory, df_top], axis=0)
                df_top = df_top_combined[~df_top_combined.index.duplicated(keep='first')]  # Prioritize top selected with top mandatory


            ##### Ajustement Secteur Neutre
            temp_df = pd.DataFrame(columns = columns)
            temp_df['ISIN'] = df_top.index
            if self.weight_neutral == "ICB 19":
                temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
            elif self.weight_neutral == "ICB 11":
                temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
            temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR '].values

            temp_df['Score'] = df_top[list_score_col[i]].values
            temp_df['Date'] = df_top['Date'].values
            temp_df['Raison Repechage'] = df_top['Raison Repechage'].values


            ###################### Security check : secto in temp_df is a subset of secto in weight_secto_bench ############################
            temp_df_sectors = set(temp_df['Secto'].unique())
            benchmark_sectors = set(weight_secto_bench.index)
            if not temp_df_sectors.issubset(benchmark_sectors):
                missing_sectors = temp_df_sectors.difference(benchmark_sectors)
                raise ValueError(f"Error: Sectors in temp_df {missing_sectors} are not defined in weight_secto_bench")
            #################################################################################################################################

            if self.weight_neutral != None:
                secto_weight_sum = temp_df.groupby('Secto')['Weight'].transform('sum')
                secto_benchmark_weight = temp_df['Secto'].map(weight_secto_bench)
                scaling_factor = secto_benchmark_weight / secto_weight_sum
                temp_df['Weight'] = temp_df['Weight'] * scaling_factor
                temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()

            ############ cap weight by sector if necessary ################
            if self.cap_weight_threshold != None:
                # print(f"Capping generated portfolio, no more than {self.cap_weight_threshold} for each title")
                temp_df = self.cap_weight_by_sector(temp_df)

            ##### Give name to ptf generated
            temp_df['PTF'] = self.get_portfolio_name(list_score_col[i])

            result_sec_list = pd.concat([result_sec_list,temp_df], ignore_index=True)
        
        if self.output_dir != None:
            if self.mode_monthly_prod:
                self.save_portfolio_data_incremental(result_sec_list, self.output_dir)
            else:
                result_save_path = os.path.join(self.output_dir, "sec_list_result.xlsx")
                result_sec_list.to_excel(result_save_path)
                print(f"Sec list is generated at path : {result_save_path}")

        self.sec_list_monthly = result_sec_list.copy(deep=True)
        # print(f"Monthly sec list is generated for {date}, you can check 'self.sec_list_monthly' attribute for more details.")

        self.list_exclusion_monthly = titles_excluded.copy(deep=True)

        return result_sec_list, titles_excluded

    def drift_weight(self, df_rebal, col_id, df_returns, col_date, col_weight, date_fin_drifter):
        """
        Drifter les weights avec les returns daily.
        """
        df_rebal = df_rebal[df_rebal[col_id].isin(df_returns.columns)]

        liste_rebal_date = list(df_rebal[col_date].unique())

        liste_date_returns = list(df_returns[
                                            (df_returns.index >= liste_rebal_date[0]) & 
                                            (df_returns.index <= date_fin_drifter)
                                            ].index)
        df_rebal.reset_index(inplace=True, drop=True)

        # Boucle dans le cas d'une date de rebalancement non présente dans df_returns -> changement de la date de rebalancement avec la date future la plus proche
        for i in range(len(liste_rebal_date)) :
            # Matcher la liste des dates avec les dates existantes dans la base returns
            if  liste_rebal_date[i] not in liste_date_returns :
                try:
                    # Try pour chercher la date future la plus proche
                    new_date_rebal = min(d for d in liste_date_returns if d > liste_rebal_date[i])
                except ValueError:
                    # Si pas de future date trouvée, on prend la date antérieure la plus proche (cas frequency=1 dernière date est une date de rebalancement)
                    new_date_rebal = max(d for d in liste_date_returns if d < liste_rebal_date[i])

                df_rebal = df_rebal.replace(liste_rebal_date[i], new_date_rebal)   # Change la date en question dans ptf
                liste_rebal_date[i] = new_date_rebal                               # Change la date en question dans liste rebal ['2025-10-01', '2025-11-01', '2025-12-01']

        # Tri avec la fonction sorted()
        liste_date_all = list(set(liste_rebal_date).union(set(liste_date_returns)))
        nouvelle_liste_dates = sorted(liste_date_all)


        new_df=pd.DataFrame(data=nouvelle_liste_dates, columns=['Date_returns'])
        new_df['Date_screen'] = new_df['Date_returns'].apply(lambda x: df_rebal.loc[df_rebal[col_date]<=x, col_date].max())
        # Date_returns  Date_screen
        # 2025-12-29    2025-12-01
        # 2025-12-30    2025-12-01
        # 2025-12-31    2025-12-01
        # 2026-01-01    2025-12-01


        df_rebal[col_date] = pd.to_datetime(df_rebal[col_date])

        df_merge = df_rebal.merge(new_df, how='left', left_on=col_date, right_on = 'Date_screen')
        # PTF        ISIN          Weight     Date        Raison Repechage               Secto  Score     SEDOL     Date_returns  Date_screen
        # ML EU Q1   NL0010273215  0.050000   2025-12-01  Top Obligatoire par Région     16.0   0.833333  JWGWTR-R  2025-12-01    2025-12-01
        # ML EU Q1   NL0010273215  0.050000   2025-12-01  Top Obligatoire par Région     16.0   0.833333  JWGWTR-R  2025-12-02    2025-12-01
        # ML EU Q1   NL0010273215  0.050000   2025-12-01  Top Obligatoire par Région     16.0   0.833333  JWGWTR-R  2025-12-03    2025-12-01
        # ML EU Q1   NL0010273215  0.050000   2025-12-01  Top Obligatoire par Région     16.0   0.833333  JWGWTR-R  2025-12-04    2025-12-01
        # ML EU Q1   NL0010273215  0.050000   2025-12-01  Top Obligatoire par Région     16.0   0.833333  JWGWTR-R  2025-12-05    2025-12-01


        df_merge.drop(columns=col_date,inplace=True)
        df_merge.rename(columns={'Date_returns':col_date},inplace=True)
        df_merge.sort_values(by=col_date,inplace=True)

        # Prendre les returns de la bonne période
        df_returns = df_returns[new_df['Date_screen'].min(): date_fin_drifter]
        df_returns.iloc[0, :] = 0
        returns_cum = (1+df_returns).cumprod()
        #             X5B68T-R  CHKTQ0-R  KQS7WY-R  T8JSPN-R  MF02C5-R
        # 2025-12-01   1.000000  1.000000  1.000000  1.000000  1.000000
        # 2025-12-02   1.013761  1.022564  1.000123  1.020184  1.000123
        # 2025-12-03   0.997901  0.989270  0.995270  1.009678  0.995270
        # 2025-12-04   0.995101  0.994596  1.005961  1.011745  1.005961
        # 2025-12-05   0.996441  0.995082  1.007871  1.012666  1.007871


        # Intuitivement : pour chaque ligne (une date donnée), 
        # on divise l’ensemble de la ligne par le vecteur des rendements cumulés du jour « Date_screen » précédent (dernière date de rebal) ; 
        # cela revient à réinitialiser la valeur de base à 1 à cette date de référence et à obtenir ainsi la performance relative depuis la dernière date de sélection.
        returns_drift = returns_cum.apply(lambda x:x/returns_cum.loc[(new_df.loc[new_df['Date_screen']<=x.name,'Date_screen'].max())], axis=1)
        #             X5B68T-R  CHKTQ0-R  KQS7WY-R  T8JSPN-R  MF02C5-R
        # 2025-12-01   1.000000  1.000000  1.000000  1.000000  1.000000
        # 2025-12-02   1.013761  1.022564  1.000123  1.020184  1.000123
        # 2025-12-03   0.997901  0.989270  0.995270  1.009678  0.995270
        # 2025-12-04   0.995101  0.994596  1.005961  1.011745  1.005961
        # 2025-12-05   0.996441  0.995082  1.007871  1.012666  1.007871

        returns_drift_flat = returns_drift.stack().to_frame().reset_index(names=[col_date,col_id])
        returns_drift_flat.columns=[col_date,col_id,'drift_multiplicator']
        # Date        SEDOL     drift_multiplicator
        # 2025-12-01  JWGWTR-R  1.000000
        # 2025-12-02  JWGWTR-R  1.013381
        # 2025-12-03  JWGWTR-R  1.039603
        # 2025-12-04  JWGWTR-R  1.033020
        # 2025-12-05  JWGWTR-R  1.026869


        returns_flat=df_returns.stack().to_frame().reset_index()
        returns_flat.columns=[col_date+'_shift',col_id, 'Return']
        # # Date_shift  SEDOL     Return
        # # 2025-12-01  JWGWTR-R  0.025791
        # # 2025-12-02  JWGWTR-R  0.013381
        # # 2025-12-03  JWGWTR-R  0.025876
        # # 2025-12-04  JWGWTR-R -0.006332
        # # 2025-12-05  JWGWTR-R -0.005954


        unique_date = df_merge[col_date].unique()
        df_date = pd.DataFrame(data = unique_date,columns=[col_date])
        df_date[col_date+'_shift'] = df_date[col_date].shift(-1) 
        # Date        Date_shift
        # 2025-12-01  2025-12-02
        # 2025-12-02  2025-12-03
        # 2025-12-03  2025-12-04
        # 2025-12-04  2025-12-05
        # 2025-12-05  2025-12-08   


        df_merge = df_merge.merge(df_date, how='left', on =col_date)   #Pour recupérer date shift
        # df_merge = df_merge[df_merge[col_date+'_shift'].notna()]
        # Columns: PTF | ISIN | Weight | SEDOL             | Date | Date_screen | Date_shift
        # 0   | ML EU Q1 | NL0010273215 | 0.05 | JWGWTR-R | 2025-12-01 | 2025-12-01 | 2025-12-02
        # 77  | ML EU Q1 | NL0010273215 | 0.05 | JWGWTR-R | 2025-12-02 | 2025-12-01 | 2025-12-03
        # 87  | ML EU Q1 | NL0010273215 | 0.05 | JWGWTR-R | 2025-12-03 | 2025-12-01 | 2025-12-04
        # 162 | ML EU Q1 | NL0010273215 | 0.05 | JWGWTR-R | 2025-12-04 | 2025-12-01 | 2025-12-05
        # 193 | ML EU Q1 | NL0010273215 | 0.05 | JWGWTR-R | 2025-12-05 | 2025-12-01 | 2025-12-08

        df_merge = df_merge.merge(returns_drift_flat, how='left', on = [col_date, col_id]) #Pour recupérer drift_multiplicator
        # df_merge = df_merge.merge(returns_flat, how='left', on = [col_date+'_shift', col_id])
        # PTF        ISIN           Weight  Date_screen  Date_shift  drift_multiplicator 
        # ML EU Q1   NL0010273215   0.05    2025-12-01   2025-12-02  1.000000            
        # ML EU Q1   NL0010273215   0.05    2025-12-01   2025-12-03  1.013381           
        # ML EU Q1   NL0010273215   0.05    2025-12-01   2025-12-04  1.039603           
        # ML EU Q1   NL0010273215   0.05    2025-12-01   2025-12-05  1.033020          
        # ML EU Q1   NL0010273215   0.05    2025-12-01   2025-12-08  1.026869         

        df_merge[col_weight] = df_merge[col_weight]*df_merge['drift_multiplicator']

        df_merge.drop(columns = ['Date_screen'],inplace=True)
        # df_merge.drop(columns = col_date,inplace=True)
        # df_merge.rename(columns={col_date+'_shift': col_date},inplace=True)

        res = df_merge.loc[df_merge[col_date] == max(liste_date_returns)]

        res = res.copy()
        res = res.drop(columns=['drift_multiplicator', 'Date_shift'], errors='ignore')

        # res['Weight'] = res['Weight'].transform(lambda w: w / w.sum())
        sum_weight = res['Weight'].sum()
        res['Weight'] = res['Weight'] / sum_weight if sum_weight != 0 else 0.0

        return res    

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
        # print("Longueur sec_list avant : ", len(existing_dates))

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
                    next_month_df = self.drift_weight(
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
                    # print("Longueur sec_list après : ", len(existing_dates))
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

    def build_historical_security_lists(self, start_date, freq_rebal=None, screen_start_date = "mois_impair", fill_method="drift"):
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
        
        if not isinstance(start_date, (pd.Timestamp, datetime.datetime)):
            start_date = pd.to_datetime(start_date)

        screen_agg = copy.deepcopy(self.screen)
        if type(screen_agg) == str:
            screen_agg = pd.read_parquet(screen_agg)
        

        #START DATE commence en  mois pair
        if screen_start_date == "mois_pair" :
            self.start_date  = self.find_next_closest_date(start_date,1)
        elif screen_start_date == "mois_impair" :
            self.start_date  = self.find_next_closest_date(start_date,0)
        else:
            self.start_date = start_date

        print( "Premiere date du screen_agg prise en compte : " , self.start_date)

        # Filter by start_date
        screen_agg = screen_agg[screen_agg['Date'] >= self.start_date]
        all_dates = sorted(screen_agg['Date'].unique())
        
        if not all_dates:
            return pd.DataFrame()  # Return empty DataFrame if no dates
        
        # Determine which dates to keep based on frequency
        if freq_rebal == None:
            # Keep all dates for monthly frequency (original behavior)
            dates_to_keep = all_dates
        else:
            months_step = freq_rebal
            dates_to_keep = all_dates[::months_step]
        
        # Sort the dates to keep
        dates_to_keep = sorted(dates_to_keep)
    
        # Create subsets for each date
        screen_list = [screen_agg.loc[screen_agg['Date'] == date_] for date_ in dates_to_keep]
        
        
        # Apply function - handle possible parallelization issues
        func=self.build_monthly_security_list

        result_sec_list=[]
        result_exclusion=[]
        from tqdm import tqdm
        for screen in tqdm(screen_list, desc="Generation Sec_list"):
            result = func(screen_agg_monthly=screen)  # result[0] is sec_list, result[1] is liste exclusion
            result_sec_list.append(result[0])
            result_exclusion.append(result[1])
            
        # Concatenate seclist results
        if result_sec_list and isinstance(result_sec_list[0], pd.DataFrame):
            df = pd.concat(result_sec_list, ignore_index=True)
        else:
            # Handle the case where func doesn't return DataFrames
            df = pd.DataFrame(result_sec_list)

        # Concatenate exclusion results
        if result_exclusion and isinstance(result_exclusion[0], pd.DataFrame):
            df_exclusion = pd.concat(result_exclusion, ignore_index=True)
        else:
            # Handle the case where func doesn't return DataFrames
            df_exclusion = pd.DataFrame(result_exclusion)

        # for bimestriel situation
        self.sec_list_historical = df.copy()
        if fill_method=="drift":
            self.sec_list_historical  = self.update_ptf_with_monthly_drift(self.sec_list_historical)
        if fill_method=="copy":
            self.sec_list_historical  = self.update_ptf_with_monthly_additions(self.sec_list_historical)

        self.list_exclusion_histo = df_exclusion.copy()
        self.list_exclusion_histo = self.update_ptf_with_monthly_additions(self.list_exclusion_histo)

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
                            nb_titres= nb_titres, te_max=te_max,rebalancing_start_backward=rebalancing_start_backward)

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

    def plot_portfolio_vs_benchmark(self, 
                                perf_ptf=None, perf_bench=None, 
                                title=None, save_path="portfolio_performance.html", show_plot=True,
                                save_perf_path=None):
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
        
        if save_perf_path is not None:
            if isinstance(perf_ptf, pd.Series):
                perf_ptf.to_frame().to_parquet(save_perf_path)
            else:
                perf_ptf.to_parquet(save_perf_path)

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
                

    def plot_top_vs_bottom(self, builder_bottom, title=None, save_path="comparison.html", show_plot=True):
        """
        Compare Top (self) vs Bottom (builder_bottom) against a shared Benchmark.
        """
        # 1. Get Performance for Top (this instance)
        if self.perf_ptf is None:
            self.build_historical_security_lists(start_date=self.start_date, freq_rebal=self.freq_rebal, fill_method=self.fill_method)
            self.run_portfolio_nav(self.sec_list_historical)
        perf_top = self.perf_ptf

        # 2. Get Performance for Bottom (the other instance)
        if builder_bottom.perf_ptf is None:
            builder_bottom.build_historical_security_lists(start_date=self.start_date, freq_rebal=self.freq_rebal, fill_method=self.fill_method)
            builder_bottom.run_portfolio_nav(builder_bottom.sec_list_historical)
        perf_bottom = builder_bottom.perf_ptf

        # 3. Get Performance for Benchmark (shared)
        if self.perf_bench is None:
            self.run_benchmark_nav(self.screen, self.start_date, self.bench)
        perf_bench = self.perf_bench

        # Concatenate for plotting
        df_plot = pd.concat([perf_top, perf_bottom, perf_bench], axis=1)
        df_plot.columns = ['Top', 'Bottom', 'Bench']

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                            subplot_titles=("Cumulative Performance", "Ratio vs Benchmark"))

        # --- Row 1: Performance Curves ---
        colors = {'Top': 'blue', 'Bottom': 'orange', 'Bench': 'black'}
        for col in df_plot.columns:
            fig.add_trace(go.Scatter(
                x=df_plot.index, y=df_plot[col],
                mode='lines', name=col, line=dict(width=2, color=colors[col])
            ), row=1, col=1)

        # --- Row 2: Ratios ---
        ratio_top = df_plot['Top'] / df_plot['Bench']
        ratio_bottom = df_plot['Bottom'] / df_plot['Bench']
        ratio_top_bottom = df_plot['Top'] / df_plot['Bottom'] # Calcul du ratio Top/Bottom

        fig.add_trace(go.Scatter(
            x=df_plot.index, y=ratio_top,
            mode='lines', name='Ratio Top/Bench', line=dict(width=2, color='blue')
        ), row=2, col=1)
        
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=ratio_bottom,
            mode='lines', name='Ratio Bottom/Bench', line=dict(width=2, color='orange')
        ), row=2, col=1)
        
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=ratio_top_bottom,
            mode='lines', name='Ratio Top/Bottom', line=dict(width=2, color='green') # Ajout de la ligne de ratio relatif
        ), row=2, col=1)

        # Layout adjustments (similar to existing plot_portfolio_vs_benchmark)
        fig.update_layout(
            title=title if title else "Top vs Bottom Comparison",
            width=800, height=700, template='plotly_white',
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        if save_path:
            fig.write_html(save_path)
        if show_plot:
            fig.show()



