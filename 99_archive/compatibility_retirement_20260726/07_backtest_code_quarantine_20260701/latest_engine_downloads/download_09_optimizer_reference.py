import numpy as np
import pandas as pd
# from scipy import stats
from multiprocessing import Pool
from plotly.subplots import make_subplots
import cvxpy as cp
from sklearn.decomposition import PCA


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

def drift_weight(df_rebal, col_id, df_returns, col_date, col_weight, date_fin_drifter):
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



def generate_screen_for_optim(screen, ptf_last, returns, bench, liste_noire, init, drift):
    """
    Create a Spot Screen from the Screen at the date_str on the bench with add of row the previous portfolio
    add Blacklist indicator

    """

    ###############################################################################################################################
    screen['Date'] +=pd.offsets.MonthBegin(1)
    screen = screen[screen['Weight in '+ bench] > 0]
    screen = merge_ticker_secondaire(screen, bench)
    screen = screen.reset_index()

    ### Enlever les None dans les SEDOL et verifier qu'il y en a pas trop ##########################
    pct_none = screen[screen["Company SEDOL"] == "None"]["Weight in MSCI WORLD"].sum()
    seuil_none_max = 0.0005
    if pct_none > seuil_none_max :
        raise ValueError(f"Trop de None {pct_none} (seuil max autorise : {seuil_none_max})")
    else:
        screen = screen[screen["Company SEDOL"] != "None"]
        screen["Weight in MSCI WORLD"] = screen["Weight in MSCI WORLD"] / screen["Weight in MSCI WORLD"].sum()

    date_screen = pd.to_datetime(screen['Date'].max())

    ###############################################################################################################################
    #  GET THE LAST OPTIM PTF and DRIFT WEIGHT and Create a new Screen with current SEDOl and add SEDOL for last ptf if not present
    screen = screen.rename(columns = {" Benchmark ICB Supersector " : "Secto"})

    if not init : 
        # Get the date of last ptf and change it as the first day of next month
        date_ptf_last = ptf_last['Date'].unique()

        if len(date_ptf_last) >1:
            error_msg = f"Expected a single date in ptf_last, but found {len(date_ptf_last)} unique dates: {date_ptf_last}"
            raise ValueError(error_msg)
        else : 
            date_ptf_last = date_ptf_last[0]

        date_fin_drifter = date_ptf_last + pd.DateOffset(months=1)

        # Prepare parameters for drift function
        col_id = "Company SEDOL"
        col_weight = "Weight"
        col_date = "Date"

        ptf_last = ptf_last[ptf_last[col_weight] > 0]                 # Filter only companies with weight in ptf
        ptf_last['Score ML'] = ptf_last['Score ML'].replace(-1, 0)    # Replace non existed score ml as 0

        if drift :
            # Use drift logic to adjust weights
            ptf_last_drifter = drift_weight(
                ptf_last.copy(),
                col_id,
                returns.copy(),
                col_date,
                col_weight,
                date_fin_drifter
            )

        else:
            ptf_last_drifter = ptf_last

        # Change name for cols in last ptf to keep in screen
        ptf_last_drifter['Weight_last_drift'] = ptf_last_drifter['Weight']
        ptf_last_drifter['Score ML_last'] = ptf_last_drifter['Score ML']
        ptf_last_drifter['Raison Exclusion_last'] = ptf_last_drifter['Raison Exclusion']

        # Re-convertir sector strings as number 
        # reverse_mapping = {v: k for k, v in icb_supersectors_mapping.items()}
        # ptf_last_drifter[" Benchmark ICB Supersector "] = ptf_last_drifter['Secto'].map(reverse_mapping)
        
        # Define columns to be inherited
        # cols_to_inherit = [" Benchmark ICB Supersector ", "Exchange Country Region","ISIN","Name"]
        cols_to_inherit = ["Secto", "Exchange Country Region","ISIN","Name"]


        # Create a temporary copy of ptf_last_drifter with renamed columns to avoid suffixes
        # Création d'une copie temporaire avec des noms de colonnes modifiés pour éviter les suffixes
        ptf_tmp = ptf_last_drifter[["Company SEDOL", 
                                    "Weight_last_drift", 
                                    "Raison Exclusion_last"
                                    ] + cols_to_inherit].copy()
        ptf_tmp = ptf_tmp.rename(columns={col: f"{col}_tmp" for col in cols_to_inherit})

        # Perform the outer merge
        screen = screen.merge(
            ptf_tmp,
            how="outer",
            on="Company SEDOL"
        )

        # Fill missing values in original columns using the temporary columns
        # Remplissage des valeurs manquantes dans les colonnes originales via les colonnes temporaires
        for col in cols_to_inherit:
            tmp_col = f"{col}_tmp"
            if tmp_col in screen.columns:
                screen[col] = screen[col].fillna(screen[tmp_col])

        # Cleanup: remove temporary columns and handle Score ML
        # Suppression des colonnes temporaires et gestion du Score ML
        screen = screen.drop(columns=[f"{col}_tmp" for col in cols_to_inherit])
        screen["Weight_last_drift"] = screen["Weight_last_drift"].fillna(0)

    else : 
        screen["Weight_last_drift"] = 0

    screen['Score ML'] = screen['Score ML'].fillna(0)
    screen['Weight in ' + bench] = screen['Weight in ' + bench].fillna(0)
    screen['Date'] = screen['Date'].fillna(date_screen)
    screen['Weight'] = 0.0
    # screen["Secto"] = screen[" Benchmark ICB Supersector "]
    


    ###############################################################################################################################
    #  GET THE LAST OPTIM PTF and DRIFT WEIGHT and Create a new Screen with current SEDOl and add SEDOL for last ptf if not present
    condition = screen["ISIN"].isin(liste_noire)
    screen["Raison Exclusion"] = np.where(condition, "Blacklisted", screen.get("Raison Exclusion", "")) # Conserve la valeur existante ou vide
    screen['blacklisted'] = np.where(screen['Raison Exclusion'] == 'Blacklisted', 1, 0)
    
    # POUR REMETTRE Colonne Blacklisted  Raison Exclusion
    del screen["Raison Exclusion"]
    screen["Raison Exclusion"] = np.where(condition, "Blacklisted", screen.get("Raison Exclusion", "")) # Conserve la valeur existante ou vide

    ## NEWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW
    print("Exclusion ESG")
    esg_seuil = 20
    score_seuil = screen["ESG_ANALYST_SCORE"].quantile(esg_seuil / 100)
 
    # 1. Définir les deux conditions de blacklistage
    condition_liste_noire = screen["ISIN"].isin(liste_noire)
    condition_score_esg = screen["ESG_ANALYST_SCORE"] < score_seuil
 
    # On combine les deux : est blacklisté si (est dans la liste noire) OU (a un score ESG trop bas)
    condition_finale = condition_liste_noire | condition_score_esg
 
    # 2. Application du marquage unique "Blacklisted"
    # Si condition_finale est Vrai -> "Blacklisted", sinon on garde l'existant ou vide
    screen["Raison Exclusion"] = np.where(
        condition_finale,
        "Blacklisted",
        screen.get("Raison Exclusion", "")
    )
 
    # 3. L'indicateur binaire est à 1 si l'une ou l'autre des conditions est vraie
    screen['blacklisted'] = np.where(condition_finale, 1, 0)
    ## NEWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW

    
    ###############################################################################################################################
    #  CLEAN GEO
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
    screen["Exchange Country Region"] = screen["Exchange Country Region"].map(dict_map_geo)

    screen = screen.drop_duplicates(subset = ["ISIN"])

    return screen

def generate_covariance_matrix(result_df,returns,model_cov):

    sedol_to_isin = dict(zip(result_df['ISIN'],result_df['Company SEDOL']))
    sedol_to_isin = {k: v for k, v in sedol_to_isin.items() if not (k != k and v != v)}
    returns_short = returns.reset_index()
    returns_short = returns_short.rename(columns={'index':'Date'})
    returns_short = returns_short.rename(columns=sedol_to_isin)
    # returns = returns[[col for col in returns.columns if col in sedol_to_isin.values() or col == 'Date']]

    # Filtrer les dates pour ne garder que celles dans la plage d'une année à partir de la date maximale
    max_date = result_df['Date'].max()
    print("COVARIANCE DATE " , max_date)
    one_year = max_date - pd.DateOffset(days=365)
    returns_short = returns_short[(returns_short['Date'] >= one_year) & (returns_short['Date'] < max_date) ]

    returns_short = returns_short.set_index('Date')
    # isin_list = [isin for isin in sedol_to_isin.values() if pd.notna(isin) and str(isin).lower() != 'nan']
    isin_list = [isin for isin in sedol_to_isin.values() ]
    returns_short = returns_short[isin_list]

    
    if model_cov == "norm" : 
        sigma=returns_short.cov().to_numpy()
    elif model_cov == "ewma" : 
        print("ewma")
        sigma = returns_short.ewm(span=60).cov().iloc[-len(returns_short.columns):].to_numpy()
    return sigma


def define_secto_target_and_geo_target(secto_reco_path, df, date, bench, seuil_petit_secteur = 0.0015, pct_dev_secto =2):
    import pandas as pd

    ##################################################################################################
    # LECTURE DES RECO SECTO
    secto_eu = pd.read_excel(secto_reco_path, sheet_name="secto_eu", index_col=0)
    secto_eu = secto_eu/5 * pct_dev_secto

    secto_us = pd.read_excel(secto_reco_path, sheet_name="secto_us", index_col=0)
    secto_us = secto_us/5 * pct_dev_secto

    # Date du Secto
    print("Date_secto : ",date)
    reco_secto_eu = secto_eu.loc[date].to_list() 
    reco_secto_us = secto_us.loc[date].to_list() 


    ##################################################################################################
    # CREATION DES CLES PAYS SECTEURS
    import itertools
    import pandas as pd
    def get_all_combinations(numbers, regions):
        """Generates all combinations formatted as 'number_region'."""
        return [f"{num}_{region}" for region, num in itertools.product(regions, numbers)]
    nums = range(1, 20)  # 1 to 19     # Define the ranges and lists


    regions = ['West Europe']   #, 'North America', 'Others'
    all_combos = get_all_combinations(nums, regions)
    Tilt_secto_euro=pd.DataFrame(all_combos)
    new_columns = list(Tilt_secto_euro.columns)
    new_columns[0] = "Key_Secto_Geo"
    Tilt_secto_euro.columns = new_columns
    Tilt_secto_euro["tilt"]=reco_secto_eu

    regions = ['North America']   #, 'North America', 'Others'
    all_combos = get_all_combinations(nums, regions)
    Tilt_secto_us=pd.DataFrame(all_combos)
    new_columns = list(Tilt_secto_us.columns)
    new_columns[0] = "Key_Secto_Geo"
    Tilt_secto_us.columns = new_columns
    Tilt_secto_us["tilt"]=reco_secto_us


    Tilt_secto = pd.concat([
        Tilt_secto_euro[['Key_Secto_Geo', 'tilt']], 
        Tilt_secto_us[['Key_Secto_Geo', 'tilt']]
    ]).drop_duplicates(subset=['Key_Secto_Geo']) # Sécurité au cas où une clé serait présente deux fois

    ##################################################################################################



    ##################################################################################################
    # CHECK DF CONTIENT DES ZONES GEO CLEAN, FILLNA sur le Score ML et le Weight_last_drift, clé Key_Secto_Geo
    result_df=df.copy(deep=True)
    result_df['Exchange Country Region']=result_df['Exchange Country Region'].replace("East Europe","West Europe").replace("Africa","Others").replace("Asia","Others").replace("Mid East","Others").replace("Pacific","Others").replace("South America","Others")
    result_df['Score ML']=result_df['Score ML'].fillna(0)
    result_df['Weight_last_drift']=result_df['Weight_last_drift'].fillna(0)
    result_df['Key_Secto_Geo']=result_df['Secto'].astype(int).astype(str) + "_" + result_df['Exchange Country Region'].astype(str)



    ##################################################################################################
    # CALCUL DES POIDS CROISE SECTO GEO
    weight_secto_geo_bench = \
    result_df.groupby(['Secto', 'Exchange Country Region'])['Weight in ' + bench].sum() / result_df['Weight in ' + bench].sum()

    weight_secto_geo_bench=weight_secto_geo_bench.reset_index(drop=False)
    def format_float_column(df, column_name, decimal_places=2):
        df[column_name] = df[column_name].map(lambda x: f"{x:.{decimal_places}f}")
        return df
    weight_secto_geo_bench = format_float_column(weight_secto_geo_bench, 'Secto', decimal_places=0)
    weight_secto_geo_bench['Key_Secto_Geo'] = (weight_secto_geo_bench['Secto'].astype(str) + "_" + weight_secto_geo_bench['Exchange Country Region'].astype(str))
    cols_to_drop = ['Secto', 'Exchange Country Region']
    weight_secto_geo_bench.drop(columns=cols_to_drop, errors='ignore',inplace=True)



    ##################################################################################################
    # CREATION DES CLES PAYS SECTEURS
    import itertools
    nums = range(1, 20)  # 1 to 19
    regions = ['West Europe', 'North America', 'Others']
    all_combos = get_all_combinations(nums, regions)
    keyweight_secto_geo_bench=pd.DataFrame(all_combos)
    new_columns = list(keyweight_secto_geo_bench.columns)
    new_columns[0] = "Key_Secto_Geo"
    keyweight_secto_geo_bench.columns = new_columns


    ##################################################################################################
    # MERGE DE LA STRUCTURE num_zonegeo SUR LES POIDS RECUPERES
    keyweight_secto_geo_bench=keyweight_secto_geo_bench.merge(weight_secto_geo_bench,on=["Key_Secto_Geo"],how='left')
    cols_to_drop = ['Secto', 'Exchange Country Region']
    weight_secto_geo_bench.drop(columns=cols_to_drop, errors='ignore')
    weight_secto_geo_bench=weight_secto_geo_bench[["Key_Secto_Geo","Weight in " + bench]]
    weight_secto_geo_bench["Weight in " + bench] = weight_secto_geo_bench["Weight in " + bench].fillna(0)



    ##################################################################################################
    # CREATION DE LA STRUCTURE ZONE GEO
    list_geo=["North America","West Europe","Others"]
    keyweight_geo_bench=pd.DataFrame(list_geo)
    new_columns = list(keyweight_geo_bench.columns)
    new_columns[0] = "Key_Geo"
    keyweight_geo_bench.columns = new_columns

    weight_geo_bench = result_df.groupby(['Exchange Country Region'])['Weight in ' + bench].sum() / result_df['Weight in ' + bench].sum()
    weight_geo_bench=weight_geo_bench.reset_index(drop=False)
    weight_geo_bench=weight_geo_bench.rename(columns={"Exchange Country Region":"Key_Geo"})
    keyweight_geo_bench=keyweight_geo_bench.merge(weight_geo_bench,on=["Key_Geo"],how='left')
    weight_geo_bench["Weight in " + bench] = weight_geo_bench["Weight in " + bench].fillna(0)



    ##################################################################################################
    # AJOUT DES TILT SECTO AU POIDS INDICES

    # On merge weight_geo_bench et keyweight_secto_geo_bench sur les clés, pour avoir les poids de chaque zones.
    weight_geo_benchTemp=weight_geo_bench.copy(deep=True)
    weight_geo_benchTemp=weight_geo_benchTemp.rename(columns={"Weight in " + bench:"PoidsGéo"})
    keyweight_secto_geo_bench['Key_Geo'] = keyweight_secto_geo_bench['Key_Secto_Geo'].str.split('_').str[1]
    keyweight_secto_geo_bench = keyweight_secto_geo_bench.merge(weight_geo_benchTemp,how="left",on="Key_Geo")
    del weight_geo_benchTemp

    # On merge Tilt secto et keyweight_secto_geo_bench sur les clés, on fillna 0 les tilt vides
    keyweight_secto_geo_bench = keyweight_secto_geo_bench.merge(Tilt_secto, on='Key_Secto_Geo', how='left')
    keyweight_secto_geo_bench['tilt']=keyweight_secto_geo_bench['tilt'].fillna(0)

    # On crée une colonne Poids cible = Poids indices * (1 + tilt secto)
    keyweight_secto_geo_bench=keyweight_secto_geo_bench.rename(columns={"Weight in " + bench:"Before tilt W in " + bench})
    keyweight_secto_geo_bench["Weight in " + bench] = (keyweight_secto_geo_bench["Before tilt W in " + bench]
                                                + (keyweight_secto_geo_bench['tilt'] * keyweight_secto_geo_bench['PoidsGéo']))
    
    keyweight_secto_geo_bench.loc[keyweight_secto_geo_bench["Weight in " + bench]< seuil_petit_secteur,"Weight in " + bench]=0

    # On rescale pour que la somme des "Weight in " + bench par zone soit bien égale à 1
    current_sums = keyweight_secto_geo_bench.groupby('Key_Geo')["Weight in " + bench].transform('sum')
    target_weights = keyweight_secto_geo_bench.groupby('Key_Geo')['PoidsGéo'].transform('first')
    ratio = target_weights / current_sums
    keyweight_secto_geo_bench["Weight in " + bench] = keyweight_secto_geo_bench["Weight in " + bench] * ratio #RESCALING
    keyweight_secto_geo_bench=keyweight_secto_geo_bench[['Key_Secto_Geo', "Before tilt W in " + bench, 'tilt',"Weight in " + bench]]
    keyweight_secto_geo_bench['impact tilt']=keyweight_secto_geo_bench["Weight in " + bench]-keyweight_secto_geo_bench["Before tilt W in " + bench]

    ##################################################################################################
    weight_geo_bench = weight_geo_bench.rename(columns = {"Key_Geo" : "Exchange Country Region" })

    return keyweight_secto_geo_bench,weight_geo_bench,result_df

def define_secto_target_and_geo_target2(secto_reco_path, df, date, bench, bool_rebal_Europe, bool_rebal_US, seuil_petit_secteur = 0.0015, pct_dev_secto = 2):
    import pandas as pd

    ##################################################################################################
    # LECTURE DES RECO SECTO
    secto_eu = pd.read_excel(secto_reco_path, sheet_name="secto_eu", index_col=0)
    secto_eu = secto_eu/5 * pct_dev_secto

    secto_us = pd.read_excel(secto_reco_path, sheet_name="secto_us", index_col=0)
    secto_us = secto_us/5 * pct_dev_secto

    # Date du Secto
    print("Date_secto : ",date)
    reco_secto_eu = secto_eu.loc[date].to_list() 
    reco_secto_us = secto_us.loc[date].to_list() 


    ##################################################################################################
    # CREATION DES CLES PAYS SECTEURS
    import itertools
    import pandas as pd
    def get_all_combinations(numbers, regions):
        """Generates all combinations formatted as 'number_region'."""
        return [f"{num}_{region}" for region, num in itertools.product(regions, numbers)]
    nums = range(1, 20)  # 1 to 19     # Define the ranges and lists


    regions = ['West Europe']   #, 'North America', 'Others'
    all_combos = get_all_combinations(nums, regions)
    Tilt_secto_euro=pd.DataFrame(all_combos)
    new_columns = list(Tilt_secto_euro.columns)
    new_columns[0] = "Key_Secto_Geo"
    Tilt_secto_euro.columns = new_columns
    Tilt_secto_euro["tilt"]=reco_secto_eu

    regions = ['North America']   #, 'North America', 'Others'
    all_combos = get_all_combinations(nums, regions)
    Tilt_secto_us=pd.DataFrame(all_combos)
    new_columns = list(Tilt_secto_us.columns)
    new_columns[0] = "Key_Secto_Geo"
    Tilt_secto_us.columns = new_columns
    Tilt_secto_us["tilt"]=reco_secto_us


    Tilt_secto = pd.concat([
        Tilt_secto_euro[['Key_Secto_Geo', 'tilt']], 
        Tilt_secto_us[['Key_Secto_Geo', 'tilt']]
    ]).drop_duplicates(subset=['Key_Secto_Geo']) # Sécurité au cas où une clé serait présente deux fois

    ##################################################################################################



    ##################################################################################################
    # CHECK DF CONTIENT DES ZONES GEO CLEAN, FILLNA sur le Score ML et le Weight_last_drift, clé Key_Secto_Geo
    result_df=df.copy(deep=True)
    result_df['Exchange Country Region']=result_df['Exchange Country Region'].replace("East Europe","West Europe").replace("Africa","Others").replace("Asia","Others").replace("Mid East","Others").replace("Pacific","Others").replace("South America","Others")
    result_df['Score ML']=result_df['Score ML'].fillna(0)
    result_df['Weight_last_drift']=result_df['Weight_last_drift'].fillna(0)
    result_df['Key_Secto_Geo']=result_df['Secto'].astype(int).astype(str) + "_" + result_df['Exchange Country Region'].astype(str)



    ##################################################################################################
    # CALCUL DES POIDS CROISE SECTO GEO

    #A sur le bench actuel
    weight_secto_geo_bench = \
    result_df.groupby(['Secto', 'Exchange Country Region'])['Weight in ' + bench].sum() / result_df['Weight in ' + bench].sum()

    weight_secto_geo_bench=weight_secto_geo_bench.reset_index(drop=False)
    def format_float_column(df, column_name, decimal_places=2):
        df[column_name] = df[column_name].map(lambda x: f"{x:.{decimal_places}f}")
        return df
    weight_secto_geo_bench = format_float_column(weight_secto_geo_bench, 'Secto', decimal_places=0)
    weight_secto_geo_bench['Key_Secto_Geo'] = (weight_secto_geo_bench['Secto'].astype(str) + "_" + weight_secto_geo_bench['Exchange Country Region'].astype(str))
    cols_to_drop = ['Secto', 'Exchange Country Region']
    weight_secto_geo_bench.drop(columns=cols_to_drop, errors='ignore',inplace=True)

    #B sur le ptf last
    weight_secto_geo_bench_Lastptf = \
    result_df.groupby(['Secto', 'Exchange Country Region'])['Weight_last_drift'].sum() / result_df['Weight_last_drift'].sum()

    weight_secto_geo_bench_Lastptf=weight_secto_geo_bench_Lastptf.reset_index(drop=False)
    weight_secto_geo_bench_Lastptf = format_float_column(weight_secto_geo_bench_Lastptf, 'Secto', decimal_places=0)
    weight_secto_geo_bench_Lastptf['Key_Secto_Geo'] = (weight_secto_geo_bench_Lastptf['Secto'].astype(str) + "_" + weight_secto_geo_bench_Lastptf['Exchange Country Region'].astype(str))
    cols_to_drop = ['Secto', 'Exchange Country Region']
    weight_secto_geo_bench_Lastptf.drop(columns=cols_to_drop, errors='ignore',inplace=True)


    ##################################################################################################
    # CREATION DES CLES PAYS SECTEURS
    import itertools
    nums = range(1, 20)  # 1 to 19
    regions = ['West Europe', 'North America', 'Others']
    all_combos = get_all_combinations(nums, regions)
    keyweight_secto_geo_bench=pd.DataFrame(all_combos)
    new_columns = list(keyweight_secto_geo_bench.columns)
    new_columns[0] = "Key_Secto_Geo"
    keyweight_secto_geo_bench.columns = new_columns
    keyweight_secto_geo_bench_Lastptf=keyweight_secto_geo_bench.copy(deep=True)

    ##################################################################################################
    # MERGE DE LA STRUCTURE num_zonegeo SUR LES POIDS RECUPERES
    #A sur le bench actuel
    keyweight_secto_geo_bench=keyweight_secto_geo_bench.merge(weight_secto_geo_bench,on=["Key_Secto_Geo"],how='left')
    cols_to_drop = ['Secto', 'Exchange Country Region']
    weight_secto_geo_bench.drop(columns=cols_to_drop, errors='ignore')
    weight_secto_geo_bench=weight_secto_geo_bench[["Key_Secto_Geo","Weight in " + bench]]
    weight_secto_geo_bench["Weight in " + bench] = weight_secto_geo_bench["Weight in " + bench].fillna(0)

    #B sur le ptf last
    keyweight_secto_geo_bench_Lastptf=keyweight_secto_geo_bench_Lastptf.merge(weight_secto_geo_bench_Lastptf,on=["Key_Secto_Geo"],how='left')
    cols_to_drop = ['Secto', 'Exchange Country Region']
    weight_secto_geo_bench_Lastptf.drop(columns=cols_to_drop, errors='ignore')
    weight_secto_geo_bench_Lastptf=weight_secto_geo_bench_Lastptf[["Key_Secto_Geo","Weight_last_drift"]]
    weight_secto_geo_bench_Lastptf["Weight_last_drift"] = weight_secto_geo_bench_Lastptf["Weight_last_drift"].fillna(0)


    ##################################################################################################
    # CREATION DE LA STRUCTURE ZONE GEO
    list_geo=["North America","West Europe","Others"]
    keyweight_geo_bench=pd.DataFrame(list_geo)
    new_columns = list(keyweight_geo_bench.columns)
    new_columns[0] = "Key_Geo"
    keyweight_geo_bench.columns = new_columns
    keyweight_geo_bench_Lastptf=keyweight_geo_bench.copy(deep=True)

    #A sur le bench actuel
    weight_geo_bench = result_df.groupby(['Exchange Country Region'])['Weight in ' + bench].sum() / result_df['Weight in ' + bench].sum()
    weight_geo_bench=weight_geo_bench.reset_index(drop=False)
    weight_geo_bench=weight_geo_bench.rename(columns={"Exchange Country Region":"Key_Geo"})
    keyweight_geo_bench=keyweight_geo_bench.merge(weight_geo_bench,on=["Key_Geo"],how='left')
    weight_geo_bench["Weight in " + bench] = weight_geo_bench["Weight in " + bench].fillna(0)

    #B sur le ptf last
    weight_geo_bench_Lastptf = result_df.groupby(['Exchange Country Region'])['Weight_last_drift'].sum() / result_df['Weight_last_drift'].sum()
    weight_geo_bench_Lastptf = weight_geo_bench_Lastptf.reset_index(drop=False)
    weight_geo_bench_Lastptf = weight_geo_bench_Lastptf.rename(columns={"Exchange Country Region":"Key_Geo"})
    keyweight_geo_bench_Lastptf=keyweight_geo_bench_Lastptf.merge(weight_geo_bench_Lastptf,on=["Key_Geo"],how='left')
    weight_geo_bench_Lastptf["Weight_last_drift"] = weight_geo_bench_Lastptf["Weight_last_drift"].fillna(0)

    ##################################################################################################
    # AJOUT DES TILT SECTO AU POIDS INDICES

    # On merge weight_geo_bench et keyweight_secto_geo_bench sur les clés, pour avoir les poids de chaque zones.
    #A sur le bench actuel
    weight_geo_benchTemp=weight_geo_bench.copy(deep=True)
    weight_geo_benchTemp=weight_geo_benchTemp.rename(columns={"Weight in " + bench:"PoidsGéo"})
    keyweight_secto_geo_bench['Key_Geo'] = keyweight_secto_geo_bench['Key_Secto_Geo'].str.split('_').str[1]
    keyweight_secto_geo_bench = keyweight_secto_geo_bench.merge(weight_geo_benchTemp,how="left",on="Key_Geo")
    del weight_geo_benchTemp

    #B sur le ptf last
    weight_geo_benchTemp_Lastptf=weight_geo_bench_Lastptf.copy(deep=True)
    weight_geo_benchTemp_Lastptf=weight_geo_benchTemp_Lastptf.rename(columns={"Weight_last_drift":"PoidsGéo"})
    keyweight_secto_geo_bench_Lastptf['Key_Geo'] = keyweight_secto_geo_bench_Lastptf['Key_Secto_Geo'].str.split('_').str[1]
    keyweight_secto_geo_bench_Lastptf = keyweight_secto_geo_bench_Lastptf.merge(weight_geo_benchTemp_Lastptf,how="left",on="Key_Geo")
    del weight_geo_benchTemp_Lastptf



    # On merge Tilt secto et keyweight_secto_geo_bench sur les clés, on fillna 0 les tilt vides
    #A sur le bench actuel
    keyweight_secto_geo_bench = keyweight_secto_geo_bench.merge(Tilt_secto, on='Key_Secto_Geo', how='left')
    keyweight_secto_geo_bench['tilt']=keyweight_secto_geo_bench['tilt'].fillna(0)

    #B sur le ptf last
    keyweight_secto_geo_bench_Lastptf = keyweight_secto_geo_bench_Lastptf.merge(Tilt_secto, on='Key_Secto_Geo', how='left')
    keyweight_secto_geo_bench_Lastptf['tilt']=keyweight_secto_geo_bench_Lastptf['tilt'].fillna(0)



    # On crée une colonne Poids cible = Poids indices * (1 + tilt secto)
    #A sur le bench actuel
    keyweight_secto_geo_bench=keyweight_secto_geo_bench.rename(columns={"Weight in " + bench:"Before tilt W in " + bench})
    keyweight_secto_geo_bench["Weight in " + bench] = (keyweight_secto_geo_bench["Before tilt W in " + bench]
                                                + (keyweight_secto_geo_bench['tilt'] * keyweight_secto_geo_bench['PoidsGéo']))
    
    keyweight_secto_geo_bench.loc[keyweight_secto_geo_bench["Weight in " + bench]< seuil_petit_secteur,"Weight in " + bench]=0

    # On rescale pour que la somme des "Weight in " + bench par zone soit bien égale à 1
    #A sur le bench actuel
    current_sums = keyweight_secto_geo_bench.groupby('Key_Geo')["Weight in " + bench].transform('sum')
    target_weights = keyweight_secto_geo_bench.groupby('Key_Geo')['PoidsGéo'].transform('first')
    ratio = target_weights / current_sums
    keyweight_secto_geo_bench["Weight in " + bench] = keyweight_secto_geo_bench["Weight in " + bench] * ratio #RESCALING
    keyweight_secto_geo_bench=keyweight_secto_geo_bench[['Key_Secto_Geo', "Before tilt W in " + bench, 'tilt',"Weight in " + bench,"Key_Geo"]]
    keyweight_secto_geo_bench['impact tilt']=keyweight_secto_geo_bench["Weight in " + bench]-keyweight_secto_geo_bench["Before tilt W in " + bench]


    #B sur le ptf last
    # ON NE FAIT RIEN PAS DE TILT ON RESTE AU PRECEDENT POIDS SECTO DS LES ZONES GEO
    keyweight_secto_geo_bench_Lastptf['impact tilt']=0
    keyweight_secto_geo_bench_Lastptf['tilt']=0
    keyweight_secto_geo_bench_Lastptf["Weight in " + bench] = keyweight_secto_geo_bench_Lastptf["Weight_last_drift"]
    keyweight_secto_geo_bench_Lastptf["Before tilt W in " + bench] = keyweight_secto_geo_bench_Lastptf["Weight_last_drift"]
    keyweight_secto_geo_bench_Lastptf=keyweight_secto_geo_bench_Lastptf[['Key_Secto_Geo', "Before tilt W in " + bench, 'tilt',"Weight in " + bench,"Key_Geo"]]

    ##################################################################################################
    #A sur le bench actuel
    weight_geo_bench = weight_geo_bench.rename(columns = {"Key_Geo" : "Exchange Country Region" })

    #B sur le ptf last
    weight_geo_bench_Lastptf = weight_geo_bench_Lastptf.rename(columns = {"Key_Geo" : "Exchange Country Region" })
    ##################################################################################################







    ##################################################################################################
    # CHOIX REBALENCEMENT OU PAS

    # EUROPE
    if bool_rebal_Europe==True:
        weight_geo_bench_temp=weight_geo_bench.loc[weight_geo_bench["Exchange Country Region"]=='West Europe',:]
        keyweight_secto_geo_bench_temp=keyweight_secto_geo_bench.loc[keyweight_secto_geo_bench["Key_Geo"]=='West Europe',:]

    else:

        weight_geo_bench_temp=weight_geo_bench_Lastptf.loc[weight_geo_bench_Lastptf["Exchange Country Region"]=='West Europe',:]
        weight_geo_bench_temp["Weight in " + bench] = weight_geo_bench_temp["Weight_last_drift"]
        keyweight_secto_geo_bench_temp=keyweight_secto_geo_bench_Lastptf.loc[keyweight_secto_geo_bench_Lastptf["Key_Geo"]=='West Europe',:]
        
    # US
    if bool_rebal_US==True:
        weight_geo_bench_temp=pd.concat([weight_geo_bench_temp,weight_geo_bench.loc[weight_geo_bench["Exchange Country Region"]=="North America",:]])
        keyweight_secto_geo_bench_temp=pd.concat([keyweight_secto_geo_bench_temp,keyweight_secto_geo_bench.loc[keyweight_secto_geo_bench["Key_Geo"]=="North America",:]])
    else:
        weight_geo_bench_temp=pd.concat([weight_geo_bench_temp,weight_geo_bench_Lastptf.loc[weight_geo_bench_Lastptf["Exchange Country Region"]=="North America",:]])
        keyweight_secto_geo_bench_temp=pd.concat([keyweight_secto_geo_bench_temp,keyweight_secto_geo_bench_Lastptf.loc[keyweight_secto_geo_bench_Lastptf["Key_Geo"]=="North America",:]])
        
    # ON AJOUTE OTHER
    weight_geo_bench_temp = pd.concat([weight_geo_bench_temp,weight_geo_bench.loc[weight_geo_bench["Exchange Country Region"]=='Others',:]])
    keyweight_secto_geo_bench_temp = pd.concat([keyweight_secto_geo_bench_temp,keyweight_secto_geo_bench.loc[keyweight_secto_geo_bench["Key_Geo"]=='Others',:]])                                        

    return keyweight_secto_geo_bench_temp,weight_geo_bench_temp,result_df


    
def apply_ub_thresholds(df, CONFIG_UB_actif, bench):
    # Initialisation avec 0.0
    df["ub"] = 0.00001
    
    for region, config in CONFIG_UB_actif.items():
        mask = (df['Exchange Country Region'] == region) & ((df["Score ML"] > 1) | (df["Weight_last_drift"] > 0)) & (df["Raison Exclusion"] != "Blacklisted")
        
        # On récupère les indices des bins
        # labels=False retourne des entiers (0, 1, 2...)
        indices = pd.cut(df.loc[mask, "Weight in MSCI WORLD"], 
                        bins=config["bins"], 
                        labels=False)
        
        # OPTIMISATION : On utilise np.take ou un mapping direct
        # On convertit la liste de valeurs en array numpy pour l'indexation rapide
        vals = np.array(config["values"])
        
        # On remplace les NaN par -1 pour éviter les erreurs d'indexation, 
        # puis on mappe les valeurs. Les indices hors limites resteront à 0.
        # On utilise .fillna(-1).astype(int) pour pouvoir indexer le tableau vals
        valid_indices = indices.fillna(-1).astype(int)
        
        # On crée un masque pour ne mettre à jour que les indices valides (>= 0)
        update_mask = (valid_indices >= 0)
        
        # W BEnch

        # Application vectorisée : on ne modifie que les lignes qui correspondent à la région ET qui sont dans un bin
        # On utilise np.where pour gérer le cas où l'index est invalide (-1)
        # le UB est l'addition du paris actif avec le poids du bench
        df.loc[mask, "ub"] = np.where(update_mask, vals[valid_indices], 0.0) + df.loc[mask,'Weight in '+ bench]
        
    return df

def define_lb_ub(df_full, 
                lb_title,
                CONFIG_UB,
                bench_4_ub,
                margin_title,
                top_mandatory, 
                bool_rebal_Europe,
                bool_rebal_US
                ):

    ################################ LB ################################
    # 1) Définition des lb_titres (REGLES CLASSIQUES) POUR GARDER DS LE POOL SI BON SCORE OU SI DEJA PRESENT DS LE PTF PRECEDENT
    seuil_ml_score = 1


    conditions_lb_title = [
        (df_full['Exchange Country Region'] == "North America") & ((df_full["Score ML"] > seuil_ml_score) | (df_full["Weight_last_drift"] > 0))& (df_full["Raison Exclusion"] != "Blacklisted"),
        (df_full['Exchange Country Region'] == "West Europe") & ((df_full["Score ML"] > seuil_ml_score) | (df_full["Weight_last_drift"] > 0)) & (df_full["Raison Exclusion"] != "Blacklisted"),
        (df_full['Exchange Country Region'] == "Others") & ((df_full["Score ML"] > seuil_ml_score) | (df_full["Weight_last_drift"] > 0)) & (df_full["Raison Exclusion"] != "Blacklisted"),
    ]

    choices_lb_title = [
        np.maximum(lb_title["North America"], df_full["Weight in MSCI WORLD"]),
        np.maximum(lb_title["West Europe"], df_full["Weight in MSCI WORLD"]),
        np.maximum(lb_title["Others"], df_full["Weight in MSCI WORLD"]),
    ]

    # On initialise la colonne 'lb' avec les valeurs classiques
    df_full["lb"] = np.select(conditions_lb_title, choices_lb_title, default=0)

    # 2) Surcharge pour les 5 plus gros poids par région
    regions = ["North America", "West Europe", "Others"]

    # On filtre d'abord pour ne garder QUE les régions définies dans la liste 'regions'
    top_5_indices = (
        df_full[
            (df_full["Weight in MSCI WORLD"] > 0) & 
            (df_full['Exchange Country Region'].isin(regions)) &
            (df_full["Raison Exclusion"] != "Blacklisted")
        ]
        .groupby('Exchange Country Region')
        .apply(lambda x: x.nlargest(top_mandatory, 'Weight in MSCI WORLD').index)
        .explode()
    )

    # 3) Application du calcul dynamique
    df_full.loc[top_5_indices, "lb"] = df_full.loc[top_5_indices, "Weight in MSCI WORLD"] - (margin_title / 2)

    ################################ UB ################################
    # 2) Définition des ub_titres
    df_full = apply_ub_thresholds(df_full, CONFIG_UB, bench_4_ub)


    # 3) Application du calcul dynamique
    df_full.loc[top_5_indices, "ub"] = df_full.loc[top_5_indices, "Weight in MSCI WORLD"] + (margin_title / 2)


    margin_not_rebal = 0.0001
    if not bool_rebal_Europe:

        mask = (df_full['Exchange Country Region'] == "West Europe") & \
            (df_full["Weight_last_drift"] > 0) & \
            (df_full["Raison Exclusion"] != "Blacklisted")

        # On applique le calcul UNIQUEMENT sur ces lignes
        df_full.loc[mask, "lb"] = df_full["Weight_last_drift"] - margin_not_rebal    
        df_full.loc[mask, "ub"] = df_full["Weight_last_drift"] + margin_not_rebal  

        mask = (df_full['Exchange Country Region'] == "West Europe") & \
            (df_full["Weight_last_drift"] < 0.000001) & \
            (df_full["Raison Exclusion"] != "Blacklisted")

        # On applique le calcul UNIQUEMENT sur ces lignes
        df_full.loc[mask, "lb"] = 0   
        df_full.loc[mask, "ub"] = 0.000001 

    if not bool_rebal_US:
        
        mask = (df_full['Exchange Country Region'] == "North America") & \
            (df_full["Weight_last_drift"] > 0) & \
            (df_full["Raison Exclusion"] != "Blacklisted")

        # On applique le calcul UNIQUEMENT sur ces lignes
        df_full.loc[mask, "lb"] = df_full["Weight_last_drift"] - margin_not_rebal    
        df_full.loc[mask, "ub"] = df_full["Weight_last_drift"] + margin_not_rebal 

        mask = (df_full['Exchange Country Region'] == "North America") & \
            (df_full["Weight_last_drift"] < 0.000001) & \
            (df_full["Raison Exclusion"] != "Blacklisted")

        # On applique le calcul UNIQUEMENT sur ces lignes
        df_full.loc[mask, "lb"] = 0   
        df_full.loc[mask, "ub"] = 0.000001     

    df_full["Weight"] = df_full["Weight"].fillna(0)

    return df_full


def verifier_contraintes(df_full, margin_country, margin_sector, df_sector_cible, df_pays_cible, name_col):

    # On crée les bornes en une seule fois
    df_sector_cible = df_sector_cible.assign(
        lb_secto = lambda x: x[name_col] - margin_sector/2,
        ub_secto = lambda x: x[name_col] + margin_sector/2
    )


    # On crée les bornes en une seule fois
    df_pays_cible = df_pays_cible.assign(
        lb_pays = lambda x: x[name_col] - margin_country,
        ub_pays = lambda x: x[name_col] + margin_country
    )



    # # 5) Verif title vs Secto
    sums_lb_title_secto = df_full.groupby("Key_Secto_Geo")["lb"].sum()
    sums_ub_title_secto  = df_full.groupby("Key_Secto_Geo")["ub"].sum()


    prob_secto_delete = []
    prob_secto_add = []

    for index, row in df_sector_cible.iterrows():
        sector = row["Key_Secto_Geo"]
        ub_secto = row["ub_secto"]
        lb_secto = row["lb_secto"]

        # On récupère la somme calculée précédemment (0 si le secteur n'existe pas dans df_full)
        sums_lb_title_secto_x = sums_lb_title_secto.get(sector, 0)
        sums_ub_title_secto_x = sums_ub_title_secto.get(sector, 0) 

        # if ub_secto < sums_lb_title_secto_x:
        #     print(ub_secto)
        #     print(sums_lb_title_secto_x)
        #     print(f"Problemes trop de titres sur secteur : {sector}")
        #     prob_secto_delete.append(sector)

        if lb_secto > sums_ub_title_secto_x:
            print(f"Problemes pas assez de titres sur secteur : {sector}")
            prob_secto_add.append(sector)    



    # # 6) Verif title vs Pays
    sums_lb_title_pays = df_full.groupby("Exchange Country Region")["lb"].sum()
    sums_ub_title_pays  = df_full.groupby("Exchange Country Region")["ub"].sum()


    prob_pays_delete = []
    prob_pays_add = []


    for index, row in df_pays_cible.iterrows():
        pays = row["Exchange Country Region"]
        ub_pays = row["ub_pays"]
        lb_pays = row["lb_pays"]

        # On récupère la somme calculée précédemment (0 si le secteur n'existe pas dans df_full)
        sums_lb_title_pays_x = sums_lb_title_pays.get(pays, 0)
        sums_ub_title_pays_x = sums_ub_title_pays.get(pays, 0) 

        # if ub_pays < sums_lb_title_pays_x :
        #     print(f"Problemes trop de titres sur secteur : {pays}")
        #     prob_pays_delete.append(pays)

        if lb_pays > sums_ub_title_pays_x:
            print(f"Problemes pas assez de titres sur secteur : {pays}")
            prob_pays_add.append(pays)

    

    return prob_secto_add, prob_pays_add





def get_ub_value(row, bench, CONFIG_UB):
    """Calcule le UB pour une seule ligne basée sur la CONFIG_UB"""
    region = row['Exchange Country Region']
    weight = row['Weight in ' + bench]
    
    if region not in CONFIG_UB:
        return 0.000001 # Valeur par défaut si région inconnue
    
    config = CONFIG_UB[region]
    # pd.cut pour une seule valeur retourne un Interval, on récupère l'index
    # On utilise np.digitize qui est plus rapide pour une valeur unique
    bin_index = np.digitize(weight, config["bins"]) - 1
    
    # Vérification que l'index est valide pour la liste des valeurs
    if 0 <= bin_index < len(config["values"]):
        return weight + config["values"][bin_index]
    
    return 0.000001

def get_lb_value(row, bench, CONFIG_LB):
    """Calcule le LB pour une seule ligne basée sur la CONFIG_LB"""
    region = row['Exchange Country Region']
    weight = row['Weight in ' + bench]

    # 2. Calcul de la valeur LB (le maximum entre le seuil config et le poids actuel)
    lb_threshold = CONFIG_LB[region]
    return max(lb_threshold, weight)


def repechage(df_to_complete, list_var, type_col, bench, CONFIG_UB, CONFIG_LB):
    for key in list_var:
        # 1. Trouver la ligne cible
        # Note: j'ai remplacé df_full par df_to_complete pour la cohérence
        mask = (df_to_complete[type_col] == key) & (df_to_complete["Raison Exclusion"] != "Blacklisted") & (df_to_complete["Score ML"] > 0) & (df_to_complete["ub"] <= 0.0001)

        filtered_df = df_to_complete[mask].sort_values("Score ML", ascending=False)
        print(len(filtered_df))
        if not filtered_df.empty:
            target_row_idx = filtered_df.index[0]
            print("Boite repechée : ", df_to_complete.loc[target_row_idx, "ISIN"])
            
            # 2. Calculer le UB spécifiquement pour cette ligne
            row_data = df_to_complete.loc[target_row_idx]
            ub_value = get_ub_value(row_data, bench, CONFIG_UB)
            lb_value = get_lb_value(row_data, bench, CONFIG_LB)
            # 3. Mise à jour
            df_to_complete.loc[target_row_idx, "ub"] = ub_value
            df_to_complete.loc[target_row_idx, "lb"] = lb_value
        else:
            print(f"Aucune boite disponible pour le repêchage de {key}")
            
    return df_to_complete


def selection_repechage(df, prob_secto_add, prob_pays_add, bench, CONFIG_UB, CONFIG_LB):


    if prob_secto_add != [] :
        print("REPECHAGE SECTO :")
        df = repechage(df, prob_secto_add, "Key_Secto_Geo",bench, CONFIG_UB, CONFIG_LB)

    if prob_pays_add != [] :
        print("REPECHAGE PAYS :")
        df = repechage(df, prob_pays_add, "Exchange Country Region",bench, CONFIG_UB, CONFIG_LB)
    
    return df

def check_data_integrity(df):
    """Vérifie l'unicité des ISIN/Company SEDOL et l'absence de NaN."""
    results = {}
    
    # 1. Vérification des NaN
    # On vérifie si n'importe quelle cellule dans les colonnes cibles est vide
    cols_to_check = ['ISIN', 'Company SEDOL']
    # On s'assure que les colonnes existent dans le df avant de tester
    existing_cols = [c for c in cols_to_check if c in df.columns]
    
    nan_counts = df[existing_cols].isna().sum()
    results['nan_found'] = nan_counts[nan_counts > 0].to_dict()
    results['no_nan_passed'] = nan_counts.sum() == 0

    # 2. Vérification de l'unicité
    duplicates = {}
    for col in existing_cols:
        is_unique = not df[col].duplicated().any()
        duplicates[col] = {
            'is_unique': is_unique,
            'duplicate_count': int(df[col].duplicated().sum())
        }
    results['uniqueness_check'] = duplicates

    return results



# def generate_heuristique_IN_OUT_element_for_lb_ub(result_df,bench,bool_rebal_Europe, init=False):
#     print("Generate Heuristics avec bool_rebal_Europe",bool_rebal_Europe,"et Ptf initial",init)
#     #  ON FORCE L'INCLUSION DES TOP 5 TITRES PAR ZONE ET ON FORCE LES BON SCORE ML DU PTF PRECEDENT
#     if init : 
#         deja_present_et_IAsup8 = [
#             1 if (row['Score ML'] > 8 and row['blacklisted'] ==0) else 0 
#             for _, row in result_df.iterrows()]
#     else:
#         deja_present_et_IAsup8 = [
#             1 if (row['Weight_last_drift'] > 0.001 and row['Score ML'] > 8 and row['blacklisted'] ==0) else 0 
#             for _, row in result_df.iterrows()]

#     top_5_indices_per_region = (
#         result_df[result_df['blacklisted'] != 1]
#         .groupby('Exchange Country Region')["Weight in " + bench]
#         .nlargest(5)
#         .index.get_level_values(1))
    
#     if bool_rebal_Europe==True:
#         top_5_indices_per_region = [1 if idx in top_5_indices_per_region else 0 for idx in result_df.index]
#     else:
#         top_5_indices_per_region = [
#             1 if (idx in top_5_indices_per_region and 
#                 result_df.loc[idx, 'Exchange Country Region'] != 'West Europe') 
#             else 0 
#             for idx in result_df.index
#         ]
#     good = [1 if (a == 1 or b == 1) else 0 for a, b in zip(deja_present_et_IAsup8, top_5_indices_per_region)]



#     #  ON FORCE LA SUPPRESSION DES BLACKLISTED et DES MAUVAIS TITRES
#     bad_black = [1 if (row['blacklisted'] == 1) else 0 for _, row in result_df.iterrows()]

#     if init: 
#         bad_us1 = [
#             1 if (
#                 row['Score ML'] < 6 and 
#                 row['Exchange Country Region'] == 'North America' and 
#                 row["Weight in " + bench] <= 0.001  # 10bps = 0.0010
#             ) else 0 for _, row in result_df.iterrows()]
#     else:
#         bad_us1 = [
#             1 if (
#                 row['Score ML'] < 6 and 
#                 row['Weight_last_drift'] <= 0.001 and 
#                 row['Exchange Country Region'] == 'North America' and 
#                 row["Weight in " + bench] <= 0.001  # 10bps = 0.0010
#             ) else 0 for _, row in result_df.iterrows()]
    


#     if bool_rebal_Europe==True:

#         if init: 
#             bad_europe1 = [
#                 1 if (
#                     row['Score ML'] < 6 and 
#                     (row['Exchange Country Region'] == 'West Europe' or row['Exchange Country Region'] == 'Others') and 
#                     row["Weight in " + bench] <= 0.001  # 10bps = 0.0010
#                 ) else 0 for _, row in result_df.iterrows()]
#             bad_europe2 = [
#                 1 if (
#                     row['Score ML'] < 8 and 
#                     (row['Exchange Country Region'] == 'West Europe' or row['Exchange Country Region'] == 'Others') and 
#                     row["Weight in " + bench] <= 0.0002  # 2bps
#                 ) else 0 for _, row in result_df.iterrows()]
#         else:
#             bad_europe1 = [
#                 1 if (
#                     row['Score ML'] < 6 and 
#                     row['Weight_last_drift'] <= 0.001 and 
#                     (row['Exchange Country Region'] == 'West Europe' or row['Exchange Country Region'] == 'Others') and 
#                     row["Weight in " + bench] <= 0.001  # 10bps = 0.0010
#                 ) else 0 for _, row in result_df.iterrows()]
#             bad_europe2 = [
#                 1 if (
#                     row['Score ML'] < 8 and 
#                     row['Weight_last_drift'] <= 0.001 and 
#                     (row['Exchange Country Region'] == 'West Europe' or row['Exchange Country Region'] == 'Others') and 
#                     row["Weight in " + bench] <= 0.0002  # 2bps
#                 ) else 0 for _, row in result_df.iterrows()]
            
#     else:

#         if init: 
#             bad_europe1 = [#TRAITEMENT DES OTHERS SANS PTF LAST
#                 1 if (
#                     row['Score ML'] < 6 and 
#                     row['Exchange Country Region'] == 'Others' and 
#                     row["Weight in " + bench] <= 0.0002  # 2bps
#                 ) else 0 for _, row in result_df.iterrows()]
#             bad_europe2 = [#TRAITEMENT DE l'EUROPE SANS PTF LAST
#                 1 if (
#                     row['Score ML'] < 6 and 
#                     row['Exchange Country Region'] == 'West Europe'
#                 ) else 0 for _, row in result_df.iterrows()]
#         else:
#             bad_europe1 = [#TRAITEMENT DES OTHERS avec PTF LAST
#                 1 if (
#                     row['Score ML'] < 6 and 
#                     row['Weight_last_drift'] <= 0.001 and 
#                     row['Exchange Country Region'] == 'Others' and 
#                     row["Weight in " + bench] <= 0.0002  # 2bps
#                 ) else 0 for _, row in result_df.iterrows()]
#             bad_europe2 = [#TRAITEMENT DE l'EUROPE avec PTF LAST
#                 1 if (
#                     row['Score ML'] < 6 and 
#                     row['Weight_last_drift'] <= 0.0005 and 
#                     row['Exchange Country Region'] == 'West Europe'
#                 ) else 0 for _, row in result_df.iterrows()]




#     #  ON REPECHE DS BAD LES TITRES QUE L'ON VEUT AVOIR POUR RESPECTER LES BORNES SECTO GEO
#     badold = [1 if (a == 1 or b == 1 or d == 1 or e == 1) else 0 for a, b, d, e in zip(bad_us1, bad_europe1, bad_europe2, bad_black)]
#     bad = [1 if (a == 1 or b == 1 or d == 1) else 0 for a, b, d in zip(bad_us1, bad_europe1, bad_europe2)]

#     # On repeche les bad si ils sont ds lb
#     lb=list(result_df["lb"])
#     for i, poids in enumerate(lb):
#         if poids > 0:
#             bad[i] = 0 # Force à 0 ds bad
#     bad = [1 if (a == 1 or b == 1) else 0 for a, b in zip(bad, bad_black)]


#     if bool_rebal_Europe==False and init==False:
#         # ON FORCE GOOD LES TITRES DEJA PRESENT ET NON BLACLISTED
#         deja_present_et_not_BL = [1 if (row['Weight_last_drift'] > 0.0005 and row['Exchange Country Region'] == 'West Europe' and 
#                                         row['blacklisted'] ==0) else 0 for _, row in result_df.iterrows()]
#         good = [1 if (a == 1 or b == 1) else 0 for a, b in zip(good, deja_present_et_not_BL)]

#     print("sum bas avant repechage",sum(badold))
#     print("sum bas apres repechage",sum(bad))
#     print("sum good",sum(good))

#     return bad,good



def generate_heuristique(result_df,bench,bool_rebal_Europe, bool_rebal_US, init=False):
    print("Generate Heuristics avec bool_rebal_Europe",bool_rebal_Europe,"et Ptf initial",init)
    #  ON FORCE L'INCLUSION DES TOP 5 TITRES PAR ZONE ET ON FORCE LES BON SCORE ML DU PTF PRECEDENT

    top_5_indices_per_region = (
        result_df[result_df['blacklisted'] != 1]
        .groupby('Exchange Country Region')["Weight in " + bench]
        .nlargest(5)
        .index.get_level_values(1))
    
    if (bool_rebal_Europe==True) and (bool_rebal_US==True) :
        top_5_indices_per_region = [1 if idx in top_5_indices_per_region else 0 for idx in result_df.index]
        
    elif not bool_rebal_Europe:
        top_5_indices_per_region = [
            1 if (idx in top_5_indices_per_region and 
                result_df.loc[idx, 'Exchange Country Region'] != 'West Europe') 
            else 0 
            for idx in result_df.index
        ]

    elif not bool_rebal_US:
        top_5_indices_per_region = [
            1 if (idx in top_5_indices_per_region and 
                result_df.loc[idx, 'Exchange Country Region'] != "North America") 
            else 0 
            for idx in result_df.index
        ]

  
    boite_obligatoire = top_5_indices_per_region

    if bool_rebal_Europe==False and init==False:
        # ON FORCE GOOD LES TITRES DEJA PRESENT ET NON BLACLISTED
        deja_present_et_not_BL = [1 if (row['Weight_last_drift'] > 0 and row['Exchange Country Region'] == 'West Europe' and 
                                        row['blacklisted'] ==0) else 0 for _, row in result_df.iterrows()]
        
        boite_obligatoire = [1 if (a == 1 or b == 1) else 0 for a, b in zip(boite_obligatoire, deja_present_et_not_BL)]

    if bool_rebal_US==False and init==False:
        # ON FORCE GOOD LES TITRES DEJA PRESENT ET NON BLACLISTED
        deja_present_et_not_BL = [1 if (row['Weight_last_drift'] > 0 and row['Exchange Country Region'] == "North America" and 
                                        row['blacklisted'] ==0) else 0 for _, row in result_df.iterrows()]
        
        boite_obligatoire = [1 if (a == 1 or b == 1) else 0 for a, b in zip(boite_obligatoire, deja_present_et_not_BL)]


    #  ON FORCE LA SUPPRESSION DES BLACKLISTED et DES MAUVAIS TITRES

    if (bool_rebal_Europe==True) and (bool_rebal_US==True) :
        boites_interdite = [1 if (row['ub'] < 0.0010) else 0 for _, row in result_df.iterrows()]
    
    elif not bool_rebal_Europe:
        boites_interdite = [1 if ((row['ub'] < 0.0010) & (row['Exchange Country Region'] != 'West Europe')) | ((row['ub'] < 0.0010) & (row['Weight_last_drift'] < 0.00001) & (row['Exchange Country Region'] == 'West Europe')) | (row['blacklisted'] == 1)  else 0 for _, row in result_df.iterrows()]
    
    elif not bool_rebal_US:
        boites_interdite = [1 if ((row['ub'] < 0.0010) & (row['Exchange Country Region'] != "North America")) | ((row['ub'] < 0.0010) & (row['Weight_last_drift'] < 0.00001) & (row['Exchange Country Region'] == "North America"))  | (row['blacklisted'] == 1)  else 0 for _, row in result_df.iterrows()]
    


    print("Nb boites interdites : ",sum(boites_interdite))
    print("Nb boites obligatoire : ",sum(boite_obligatoire))

    return boites_interdite, boite_obligatoire

def compute_sigma_ACP(sigma,K=30):
    N = len(sigma)
    # K = 50 # Nombre de facteurs principaux que vous souhaitez conserver (ex: 15)

    # 1. Ajuster la PCA sur la matrice de covariance
    pca = PCA(n_components=K)
    pca.fit(sigma)

    # 2. B : Les loadings (expositions) -> Taille (1300, K)
    B = pca.components_.T * np.sqrt(pca.explained_variance_)

    # 3. Omega : Covariance des facteurs (Matrice identité si PCA pure) -> Taille (K, K)
    Omega = np.eye(K)

    # 4. Delta : Risque spécifique (Le reste de la variance non expliquée par la PCA)
    # On s'assure que la variance totale par actif correspond au diagonal de Sigma
    variance_totale = np.diag(sigma)
    variance_expliquee = np.diag(B @ Omega @ B.T)
    risques_specifiques = np.maximum(variance_totale - variance_expliquee, 1e-5) # Éviter les valeurs <= 0

    Delta_diag = risques_specifiques # Vecteur de taille 1300
    
    return B,Omega,variance_totale,variance_expliquee,risques_specifiques,Delta_diag


def optimize(result_df, sigma, df_sector_cible, df_pays_cible, bench, current_params, init, scip_options, bool_rebal_Europe, bool_rebal_US, path_output=None,obj_func="Min_TE",TE_constraint=False,te_threshold=0.03):
# def optimize(result_df, sigma, df_sector_cible, df_pays_cible, bench, current_params, init, scip_options, bool_rebal_Europe, bool_rebal_US, path_output=None):

    boites_interdite , boite_obligatoire = generate_heuristique(result_df, bench, bool_rebal_Europe, bool_rebal_US, init)
    print("PARAMETRE OPTIM : ", current_params)
    # Initialisation
    n = len(result_df)
    w = cp.Variable(n)
    y = cp.Variable(n, boolean=True)
    w0 = result_df['Weight_last_drift'].values
    w_benchmark = result_df["Weight in " + bench].values  # Poids du bench
    constraints = []

    ACP_OU_NON = False
    K=50

    if ACP_OU_NON==True:
        # MODELE FACTO RISK
        B,Omega,variance_totale,variance_expliquee,risques_specifiques,Delta_diag=compute_sigma_ACP(sigma,K)
        x = cp.Variable(K) 
        w_active = w - w_benchmark
        factor_risk = cp.quad_form(x, Omega) # Quadratique sur une matrice KxK uniquement
        idiosyncratic_risk = cp.sum_squares(cp.multiply(np.sqrt(Delta_diag), w_active)) # Diagonale
        tracking_error_sq = factor_risk + idiosyncratic_risk
    else:
        tracking_error_sq = cp.quad_form(w - w_benchmark, sigma)


    # Scores et paramètres
    scores = result_df["Score ML"].values
    lower_bound = np.asarray(result_df["lb"])
    upper_bound = np.asarray(result_df["ub"])


    # ==========================================
    # 2. Définition du problème d'optimisation
    # ==========================================
    # HEURISTIC
    positions_boites_interdite = [i for i, x in enumerate(boites_interdite) if x == 1]
    positions_boite_obligatoire = [i for i, x in enumerate(boite_obligatoire) if x == 1]

    result_df['boite_interdite'] = boites_interdite
    result_df['boite_obligatoire'] = boite_obligatoire
    
    # Contraintes de base
    constraints = [
        cp.sum(w) == 1,
        w >= cp.multiply(lower_bound, y),
        w <= cp.multiply(upper_bound, y),
        # w @ scores >= current_params["min_score_target"],
        cp.sum(y) <= current_params["nb_max_titres"],
        cp.sum(y) >= current_params["nb_min_titres"],
        # tracking_error_sq <= 0.025**2
        # règles heuristiques
        y[positions_boite_obligatoire] == 1,
        y[positions_boites_interdite] == 0,
    ]

    print(f"Fonction objective {obj_func}")
    # print(f"TE_constraint {TE_constraint}. Niveau {current_params["te_max"]}")

    objective = cp.Minimize(tracking_error_sq) # Objectif : Minimiser la Tracking Error Variance
    # obj_func="Min_TE"
    if obj_func=="Min_TE":
        objective = cp.Minimize(tracking_error_sq) # Objectif : Minimiser la Tracking Error Variance
        constraints.append(w @ scores >= current_params["min_score_target"])  
    if obj_func=="Max_Score":
        objective = cp.Minimize(-(w @ scores))


    if not init :
        constraints.append(cp.sum(cp.abs(w - w0)) <= current_params["max_turnover"])    
    if ACP_OU_NON==True:
        constraints.append(x == B.T @ w_active)

    # TE_constraint=False
    te_threshold=0
    if TE_constraint==True:
        constraints.append(tracking_error_sq <= current_params["te_max"]**2)



    import os
    file_name = f"country_target.pkl" # ou .xlsx selon votre besoin
    full_path = os.path.join(path_output, file_name)
    try:
        df_pays_cible=df_pays_cible.rename(columns={"Exchange Country Region":"Key_Geo"})
    except:
        error=''
    df_pays_cible.set_index("Key_Geo").to_pickle(full_path)

    file_name = f"sector_target.pkl" # ou .xlsx selon votre besoin
    full_path = os.path.join(path_output, file_name)
    df_sector_cible.set_index("Key_Secto_Geo").to_pickle(full_path)

    file_name = f"result_df.pkl" # ou .xlsx selon votre besoin
    full_path = os.path.join(path_output, file_name)
    result_df.to_pickle(full_path)


    # Contraintes Sectorielles
    df_full_candidates = result_df[result_df["ub"] > 0.0001]
    sectors_wo_candidate = set(df_sector_cible["Key_Secto_Geo"].unique()) - set(df_full_candidates["Key_Secto_Geo"].unique())
    print("Secteur avec pas assez de titre donc relache optimiseur : ", sectors_wo_candidate)

    sector_target = df_sector_cible.set_index("Key_Secto_Geo")['Weight in MSCI WORLD']
    for s, target in sector_target.items():
        idx = (result_df["Key_Secto_Geo"] == s).values # Conversion en numpy array
        if s in sectors_wo_candidate:
            constraints.append(cp.sum(w[idx]) >= 0)    
        else:    
            constraints.append(cp.sum(w[idx]) >= target - current_params["margin_sector"])
        constraints.append(cp.sum(w[idx]) <= target + current_params["margin_sector"])


    # Contraintes Pays
    try:
        df_pays_cible=df_pays_cible.rename(columns={"Exchange Country Region":"Key_Geo"})
    except:
        error=''
        

    country_target = df_pays_cible.set_index("Key_Geo")['Weight in MSCI WORLD']
    for c, target in country_target.items():
        idx = (result_df["Exchange Country Region"] == c).values
        constraints.append(cp.sum(w[idx]) >= target - current_params["margin_country"])
        constraints.append(cp.sum(w[idx]) <= target + current_params["margin_country"])




    prob = cp.Problem(objective, constraints)
    print("Lancement de l'optimisation (cela peut prendre quelques instants)...")
    try:
        prob.solve(solver=cp.SCIP, verbose=False, **scip_options)
    except cp.error.SolverError as e:
        print(f"Erreur du solveur : {e}")

    if prob.status in ["optimal", "optimal_inaccurate"]:
        print(f"\n✅ Optimisation réussie ! Statut: {prob.status}")
        result_df["Wopt"] = w.value
        # print(f"TE input : {tracking_error_sq}")
    else : 
        print(f"\n✅ Optimisation ECHEC ! Statut: {prob.status}")

   
    return result_df, prob.status


def log_constraints(df_constraint, df, date, rapport_secto, rapport_pays, current_params, sigma, bench, eps_optimiser=0.0005):
    """
    Vérifie et affiche le respect des contraintes de secteurs, pays et titres.
    """
    margin_sector = current_params["margin_sector"]
    margin_country = current_params["margin_country"]
    nb_max_titre = current_params["nb_max_titres"]
    nb_min_titres = current_params["nb_min_titres"]
    max_turnover = current_params["max_turnover"]


    # Verif Contrainte secto
    ecart_max_secto = max(abs(rapport_secto['ECART']))
    if len(rapport_secto[abs(rapport_secto["ECART"]) > margin_sector + eps_optimiser]) == 0:
        print("#### CONTRAINTE SECTO ###### OK")
    else:
        print("#### CONTRAINTE SECTO ###### ECHEC")
    print(f"Ecart absolue max : {ecart_max_secto:.4f} < {margin_sector:.4f}")    

    # 3. Vérification Contrainte Pays
    ecart_max_pays = max(abs(rapport_pays['ECART']))
    if len(rapport_pays[abs(rapport_pays["ECART"]) > margin_country + eps_optimiser]) == 0:
        print("#### CONTRAINTE PAYS ###### OK")
    else:
        print("#### CONTRAINTE PAYS ###### ECHEC")
    print(f"Ecart absolue max : {ecart_max_pays:.4f} < {margin_country:.4f}")

    # 4. Vérification Contrainte Titres
    df_opt = df[df["Wopt"] > 0]
    nb_titres_opt = len(df_opt)

    if nb_titres_opt == 0:
        print("#### CONTRAINTE TITRES ###### AUCUN TITRE OPTIMISÉ")
        return

    nb_titres_under_lb = len(df_opt[df_opt["Wopt"] < df_opt["lb"] - eps_optimiser])
    nb_titres_over_ub = len(df_opt[df_opt["Wopt"] > df_opt["ub"] + eps_optimiser])
    nb_titres_at_lb = len(df_opt[df_opt["Wopt"] == df_opt["lb"]])
    nb_titres_at_ub = len(df_opt[df_opt["Wopt"] == df_opt["ub"]])

    if (nb_titres_under_lb == 0) and (nb_titres_over_ub == 0):
        print("#### CONTRAINTE TITRES ###### OK ")
    else:
        print("#### CONTRAINTE TITRES ###### ECHEC ")
    print(f"Proportion de Titre à lb : {nb_titres_at_lb / nb_titres_opt:.2f}")
    print(f"Proportion de Titre à ub : {nb_titres_at_ub / nb_titres_opt:.2f}")


    # Verif Turnover
    turnover = (abs(df["Wopt"] - df["Weight_last_drift"]) / 2).sum()
    if turnover < max_turnover + eps_optimiser:
        print("#### CONTRAINTE TURNOVER ###### OK")
    else :
        print("#### CONTRAINTE TURNOVER ###### ECHEC")
        print(f"TO: {turnover:.2f}")
    print(f"TO: {turnover:.2f}")

    # Verif Score ML
    score_ml_agg = (df["Wopt"] * df["Score ML"]).sum()
    if score_ml_agg > max_turnover - eps_optimiser:
        print("#### CONTRAINTE SCORE ML ###### OK")
    else :
        print("#### CONTRAINTE SCORE ML ###### ECHEC")
        print(f"Score ML : {score_ml_agg:.2f}")
    print(f"Score ML : {score_ml_agg:.2f}")

    
    # Verif Nombre de titres
    nb_titres = len(df[df["Wopt"]>0.0001])
    if (nb_titres >= nb_min_titres) & (nb_titres <= nb_max_titre) :
        print("#### CONTRAINTE NB TITRES ###### OK")
    else :
        print("#### CONTRAINTE NB TITRES ###### ECHEC")
    print(f"Nombre de titres : {nb_titres}")

    # Verif Tracking Error
    active_weights = df["Wopt"].values - df["Weight in " + bench].values
    active_variance = active_weights.T @ sigma @ active_weights
    tracking_error = np.sqrt(active_variance*252)

    print("#### OBJECTIF TRACKING ERROR ###### ")
    print(f"TE : {tracking_error}")

    # --- AJOUT : Insertion des données dans df_constraint ---
    new_row = pd.DataFrame({
        "ecart_max_secto": [ecart_max_secto],
        "ecart_max_pays": [ecart_max_pays],
        "nb_titres_under_lb": [nb_titres_under_lb],
        "nb_titres_over_ub": [nb_titres_over_ub],
        "turnover": [turnover],
        "score_ml_agg": [score_ml_agg],
        "nb_titres": [nb_titres], 
        "Tracking Error" : [tracking_error]
    }, index=[date])
    
    df_constraint = pd.concat([df_constraint, new_row])
    # -------------------------------------------------------

    return df_constraint



def generate_exposure_reports(result_df, df_pays_cible, df_sector_cible):
    """
    Génère les rapports d'exposition par pays et par secteur 
    en comparant les poids optimisés (Wopt) aux poids cibles.
    """
    
    # Sélection des colonnes nécessaires
    cols_to_keep = [
        'ISIN', 'Date', 'Company SEDOL', 'Name', 'Exchange Country Region',
        'Secto', "Score ML", "blacklisted", "Key_Secto_Geo", "lb", "ub",
        "Before tilt W in MSCI WORLD", "Weight in MSCI WORLD", 'Wopt', 'Weight_last_drift', 'Raison Exclusion'
    ]
    result_df2 = result_df[cols_to_keep].copy()

    # --- CHECK PAYS ---
    rapport_pays = (
        result_df2[['Exchange Country Region', "Wopt"]]
        .groupby(['Exchange Country Region'])
        .sum(numeric_only=True)
    )
    rapport_pays = pd.merge(
        rapport_pays, 
        df_pays_cible, 
        how="left", 
        on='Exchange Country Region'
    )
    rapport_pays["ECART"] = rapport_pays["Wopt"] - rapport_pays["Weight in MSCI WORLD"]

    # --- CHECK SECTO ---
    # Somme des poids optimisés par secteur
    rapport_secto = (
        result_df2[["Key_Secto_Geo", "Wopt"]]
        .groupby(["Key_Secto_Geo"])
        .sum(numeric_only=True)
    )
    rapport_secto = pd.merge(
        rapport_secto, 
        df_sector_cible, 
        how="left", 
        on="Key_Secto_Geo"
    )

    # Calcul des sommes de lb et ub
    check_lb = result_df2.groupby('Key_Secto_Geo')['lb'].sum().rename("sum lb")
    check_ub = result_df2.groupby('Key_Secto_Geo')['ub'].sum().rename("sum ub")

    # Fusion des bornes et calcul de l'écart
    rapport_secto = rapport_secto.merge(check_lb, on="Key_Secto_Geo", how="left")
    rapport_secto = rapport_secto.merge(check_ub, on="Key_Secto_Geo", how="left")
    
    rapport_secto["ECART"] = rapport_secto["Wopt"] - rapport_secto["Weight in MSCI WORLD"]

    return result_df2, rapport_pays, rapport_secto


def adjust_constraint(df, theme_to_adjust, incr_contrainte, current_params):
    
    current_params = current_params.copy() 

    if theme_to_adjust == "ouvir_ub_title":
        mask = df["ub"] > 0.0001
        df.loc[mask, 'ub'] += incr_contrainte[theme_to_adjust]

    elif theme_to_adjust == "ouvrir_ub_secto_geo":
        current_params["margin_sector"] += incr_contrainte[theme_to_adjust]

    elif theme_to_adjust == "ouvrir_ub_country":
        current_params["margin_country"] += incr_contrainte[theme_to_adjust]

    elif theme_to_adjust == "augmenter_turnover":
        current_params["max_turnover"] += incr_contrainte[theme_to_adjust]

    elif theme_to_adjust == "diminuer_score_ml":
        current_params["min_score_target"] += incr_contrainte[theme_to_adjust]

    elif theme_to_adjust == "augmenter_te":
        current_params["te_max"] += incr_contrainte[theme_to_adjust]


    return df, current_params


def define_bool_rebal(date, mois_rebal_europe=[1,2,3,4,5,6,7,8,9,10,11,12], mois_rebal_us=[1,2,3,4,5,6,7,8,9,10,11,12]):
    # Check si Europe Rebal ou non
    # Rebal Europe Date 02 04 06 08 10 12
    # Check Rebal
    if date.month in mois_rebal_europe:
        bool_rebal_Europe=True
    else:
        bool_rebal_Europe=False

    if date.month in mois_rebal_us:
        bool_rebal_US=True
    else:
        bool_rebal_US=False

    print("rebal US ?",bool_rebal_US)
    print("rebal EUR ?",bool_rebal_Europe)

    return bool_rebal_Europe, bool_rebal_US


def adjust_lb_ub_rebal(screen, critere):
    """
    Filtre le dataframe et met à jour les colonnes lb et ub selon les critères fournis.
    """
    col_name = list(critere.keys())[0]
    target_value = critere[col_name]

    # Masque pour les lignes correspondant aux critères de région
    mask_region = screen[col_name] == target_value

    # Étape 1: Initialisation à 0
    screen.loc[mask_region, ["lb", "ub"]] = 0

    # Identification des sous-groupes au sein de la région filtrée
    drift_vals = screen.loc[mask_region, "Weight_last_drift"]
    mask_zero = (drift_vals == 0)
    mask_nonzero = (drift_vals != 0)

    # Cas spécifique: Weight_last_drift est égal à 0
    screen.loc[mask_region & mask_zero, "lb"] = 0
    screen.loc[mask_region & mask_zero, "ub"] = 1e-5 # 10e-6 correspond à 0.00001

    # Cas général: Weight_last_drift est différent de 0 (+/- 10bps)
    screen.loc[mask_region & mask_nonzero, "lb"] = drift_vals[mask_nonzero] - 0.0010
    screen.loc[mask_region & mask_nonzero, "ub"] = drift_vals[mask_nonzero] + 0.0010

    return screen
