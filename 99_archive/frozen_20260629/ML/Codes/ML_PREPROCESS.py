import os
import copy
import pandas as pd
import numpy as np
import math 
from datetime import datetime
from pathlib import Path


def _read_dataframe(path):
    path = Path(path)
    if path.suffix.lower() != ".parquet":
        raise ValueError(f"Only parquet files are supported: {path}")
    return pd.read_parquet(path)


def _write_dataframe(df, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() != ".parquet":
        raise ValueError(f"Only parquet files are supported: {path}")
    df.to_parquet(path)
class MLPreprocessor:
    def __init__(self, params_principal, params_preprocessing, params_strat):
        self.screen_path = params_principal['screen_path']
        self.returns_path = params_principal['returns_path']
        self.df_features_path = params_principal['df_features_path']
        self.univ = params_principal['univ']

        self.features = self._clean_list(params_preprocessing['X'])
        self.returns_horizon = self._clean_list(params_preprocessing['returns_horizon'])
        self.variations_freq = self._clean_list(params_preprocessing['variations_freq'])
        self.returns_type = self._clean_list(params_preprocessing['Y'])
        self.returns_neutral = self._clean_list(params_preprocessing['returns_neutral'])
        self.variation_method=params_preprocessing['variation_method']
        self.screen_agg, self.df_returns = self._load_data()

        self.params_strat = params_strat

    def _clean_list(self, items):
        return [item for item in items if not (isinstance(item, float) and math.isnan(item))]

    def _load_data(self):
        screen_agg = _read_dataframe(self.screen_path)
        df_returns = _read_dataframe(self.returns_path)
        df_returns.set_index(pd.to_datetime(df_returns.index), inplace=True)
        return screen_agg, df_returns

    def _clean_screen(self, df):
        df = df.sort_values(by='Date')
        df.rename(columns={
            "Exchange Country Region": "Region",
            " Benchmark ICB Supersector ": "Sector ICB19",
            " Benchmark ICB Industry ": "Sector ICB11"
        }, inplace=True)

        df_clean = df[df[f'Weight in {self.univ}'] > 0].copy()
        
        df_clean["Weight in univ"] = df_clean[f"Weight in {self.univ}"]
        
        mask = df_clean.loc[
            (df_clean['Weight in univ'] > 0) & (df_clean['Company SEDOL'].notna()),
            'Company SEDOL'
        ].unique()

        df_clean = df_clean[df_clean['Company SEDOL'].isin(mask)]
        df_clean['Date'] = pd.to_datetime(df_clean['Date'])
        df_clean.reset_index(inplace=True)
        df_clean = df_clean[~df_clean[['Company SEDOL', 'Date', 'Region', 'Sector ICB19']].isna().any(axis=1)]

        df_clean.set_index(['Date', 'Company SEDOL'], inplace=True)
        df_clean = df_clean[~df_clean.index.duplicated(keep='last')]
        df_clean.reset_index(inplace=True)

        return df_clean


    # RECO 8, 10, 11, 12
    def _compute_returns(self, df_initial, horizon, sector_neutral, min_periods_vol = 5):
        print("New Compute Return " + str(horizon) + "started","\n")
        df=df_initial.copy(deep=True)
        # print("DF HEAD",df.head())
        col_stock = f'Stock {horizon}M return'
        col_neutral = f'Neutral {horizon}M return'
        
        # S'assurer que les colonnes sont bien présentes
        if 'Company SEDOL' not in df.columns or 'Date' not in df.columns:
            df = df.reset_index()    
                
        try:
            #### -> RECO 7 et 8 ####### pour le calcul des Return Forward du 1er au 31 du mois

            def compute_forward_return(df, horizon, col_stock, col_neutral, sector_neutral):            
 
                # 1 CALCUL DES CUMM PROD pour Start Date and End Date
                cum_returns = (1 + self.df_returns).cumprod()   # shape: (date, SEDOL) # Pre‑compute the cumulative product of (1 + daily_return)
                cum_returns.reset_index(inplace=True)           
                cum_returns.rename(columns={'index': 'DateR'}, inplace=True) 
                cum_returns.set_index("DateR",inplace=True)
                cum_returns2 = cum_returns.copy(deep=True)


                # 2 DEFINITION POUR CHAQUE LIGNE DE DF, Start and End Date for Horizon Performance Calculation
                df.reset_index(drop=False,inplace=True)

                df['start'] = (
                    pd.to_datetime(df['Date'])
                    .dt.floor('D') + pd.offsets.MonthBegin(1)      # first trading day next month
                )
                df['end']   = df['start'] + pd.DateOffset(months=horizon) - pd.Timedelta(days=1)
                df['start']   = df['start']  - pd.Timedelta(days=1)  # to start at 100 the previous day and 100+x day 1
                df['Datetemp']   = df['Date']
            

                #3 On S'ASSURE QUE LES Starts Date and End Date sont présentes dans DF RETURN
                df_updated  = pd.merge_asof(
                    df[['start']],           # left table (only the key we care about)
                    cum_returns.reset_index(drop=False)[['DateR']],         # right table – the column we want to pull in
                    left_on='start',
                    right_on='DateR',
                    direction='backward')           # look forward (>=) but we want to start at 100 the previous day and 100+x day 1
                df['start'] = df_updated['DateR']

                df_updated = pd.merge_asof(
                    df[['end']],           # left table (only the key we care about)
                    cum_returns.reset_index(drop=False)[['DateR']],         # right table – the column we want to pull in
                    left_on='end',
                    right_on='DateR',
                    direction='backward')           # look backward (<=)
                df['end'] = df_updated['DateR']


                #4 Stack de cum_returns 1 et 2 avant merge avec Screen Aggregate
                cum_start_df = (
                    cum_returns.stack().reset_index(name='cum_start')
                    .rename(columns={'level_0': 'DateR', 'level_1':  'Company SEDOL'}))

                cum_end_df = (
                    cum_returns2.stack().reset_index(name='cum_end')
                    .rename(columns={'level_0': 'DateR', 'level_1':  'Company SEDOL'}))


                #5 Merge avec Screen Aggregate pour avoir TTR1 start date et TTR2 end date
                df = (df
                    .merge(cum_start_df, left_on=['start', 'Company SEDOL'],right_on=['DateR', 'Company SEDOL'], how='left')
                    .merge(cum_end_df, left_on=['end', 'Company SEDOL'],right_on=['DateR', 'Company SEDOL'], how='left'))


                #6 Perf Forward à Horizon et replace 0 by np.nan
                df[col_stock] = df['cum_end'] / df['cum_start'] - 1
                
                df.drop(columns=['DateR_x', 'DateR_y', 'Datetemp','start','end','cum_start','cum_end'], inplace=True)
                for c in ['DateR_x', 'DateR_y', 'Datetemp','start','end','cum_start','cum_end', 'level_0', 'index']:
                    try:
                        df.drop(columns=c, inplace=True)
                    except:
                        error=""

                return df

            df = compute_forward_return(df, horizon, col_stock, col_neutral, sector_neutral)

            df = df.set_index(['Company SEDOL', 'Date'])        
            
            #7 Calcul Perf Forward SECTO
            if sector_neutral in ['ICB19', 'ICB11']:
                df_sectors = df.reset_index(level=1).groupby(['Date', f'Sector {sector_neutral}']).apply(
                    lambda x: (x['Weight in univ'].dot(x[[col_stock]])) / x['Weight in univ'].sum()
                )
                df_sectors.columns = [col_neutral]
                df = df.reset_index().merge(df_sectors.reset_index(), on=['Date', f'Sector {sector_neutral}']).set_index(['Company SEDOL', 'Date'])
            else:
                df_market = df.reset_index(level=1).groupby(['Date']).apply(
                    lambda x: (x['Weight in univ'].dot(x[[col_stock]])) / x['Weight in univ'].sum()
                )
                df_market.columns = [col_neutral]
                df = df.reset_index().merge(df_market.reset_index(), on=['Date']).set_index(['Company SEDOL', 'Date'])
            
            df[col_stock] = df[col_stock].replace(0,np.nan)#################################################################################### AJOUT DE SECURITE
            df[f'Relative {horizon}M return'] = df[col_stock] - df[col_neutral]

            #8 Calcul Vol et Info Ratio
            # RECO 12 ###############
            # rolling_std = df.groupby(level=0)[f'Relative {horizon}M return'].expanding(min_periods = min_periods_vol).std().droplevel(0)
            rolling_std = df.groupby(level=0)[f'Relative {horizon}M return'].expanding(min_periods = 6).std().droplevel(0)
            #############
            df[f'std {horizon}M'] = np.exp(rolling_std)
            df[f'information_ratio {horizon}M'] = df[f'Relative {horizon}M return'] / np.exp(rolling_std)

        except Exception as e:
            print(e)

        return df




    def calculate_offset_change(series_group, period_months):
        """
        Calculates the difference for a series group relative to values from 'period_months' ago.
    
        Args:
            series_group (pd.Series): The input series for a single group (e.g., for one ISIN). Must have a DatetimeIndex.
            period_months (int): The number of months to look back for the comparison.
    
        Returns:
            pd.Series: The calculated series with differences .
        """
        if not isinstance(series_group.index, pd.DatetimeIndex):
            raise ValueError("Input series_group must have a DatetimeIndex.")
    
        series_with_future_index = series_group.copy()# Create a temporary copy of the series to manipulate its index
        series_with_future_index.index = series_group.index + pd.DateOffset(months=period_months) # This series will represent original values but with an index shifted INTO THE FUTURE by 'period_months'
    
        # Now, reindex this 'future-indexed' series back to the original series_group's index.
        # This operation effectively aligns the value from 'period_months' AGO
        # with the current row's date in 'series_group'.
        # For dates in 'series_group.index' that don't have a corresponding entry
        # in 'series_with_future_index.index' (e.g., early dates in the series),
        # 'reindex' will fill with NaN.
        previous_values = series_with_future_index.reindex(series_group.index)
    
        return series_group - previous_values
        
    
    
    
    # RECO 13, 14
    def _add_variations(self, df):
        """
        Ajoute les variations en pourcentage sur des horizons calendaires.

        Paramètres :
        - df : DataFrame d'entrée, avec au minimum ["ISIN", "Date", features...]
        - features : liste des colonnes numériques à transformer (ex: ["price"])
        - variations_freq : liste des horizons en mois (ex: [1, 3, 6])

        Retour :
        - df enrichi avec les colonnes de variation
        - liste des noms de colonnes créées
        """
        df = df.copy().reset_index()
        df["Date"] = pd.to_datetime(df["Date"])
        
        # Ajout colonne mois-année pour l'alignement mensuel
        df["Date_M"] = df["Date"].dt.to_period("M").dt.to_timestamp()

        df = df.sort_values(["ISIN", "Date_M"])
        df.set_index("Date_M", inplace=True)

        col_name_list = []
        # print(self.variation_method)
        for feature in self.features:
            for period in self.variations_freq:
                col_name = f"{feature}_change_{int(period)}M"
                col_name_list.append(col_name)

                if self.variation_method=='change_diff': #self.variation_method=='change_diff':

                    series = df.groupby("ISIN",
                                        group_keys=True
                                        )[feature].apply(
                        # lambda x: calculate_offset_change(x,int(period))).reset_index(level=0, drop=True)    
                        lambda x: x-x.shift(int(period), freq=pd.DateOffset(months=1))) # en cas de data manquante c'est NaN 
                    df = df.reset_index().set_index(['ISIN', 'Date_M'])
                    df[col_name] = series
                    df[col_name] = df[col_name].fillna(0)
                    df = df.reset_index().set_index("Date_M")


        df.reset_index(inplace=True)  # Reviens à un index normal
        df.drop(columns="Date_M", inplace=True)  # Supprime la colonne Date_M

        return df
    
 
############# RECO 6 ###########################
 
    def get_secteurs_attendus(self):
        """Retourne la liste des secteurs attendus (float)."""
        return [float(i) for i in range(1, 20)]
 
    def identifier_secteurs_inattendus(self,df, colonne='Sector ICB19', secteurs_attendus=None):
        """Identifie et affiche les secteurs inattendus présents dans le DataFrame."""
        if secteurs_attendus is None:
            secteurs_attendus = self.get_secteurs_attendus()
       
        secteurs_observés = df[colonne].dropna().unique()
        secteurs_inattendus = set(secteurs_observés) - set(secteurs_attendus)
       
        if secteurs_inattendus:
            print(f"Alerte : Secteurs inattendus détectés : {secteurs_inattendus}","\n","CHECK SCREEN AGGREGATE et SCREEN FS avec MAPPING CMAM LORS DU PROCESS")
       
        return secteurs_inattendus
 
    def ajouter_dummies_secteurs(self,df, colonne='Sector ICB19', secteurs_attendus=None):
        """Ajoute les colonnes dummies des secteurs attendus au DataFrame."""
        if secteurs_attendus is None:
            secteurs_attendus = self.get_secteurs_attendus()
       
        dummies = pd.get_dummies(df[colonne])
        dummies = dummies.reindex(columns=secteurs_attendus, fill_value=0)
        dummies.columns = [f'Sector {int(c)}' for c in dummies.columns]
       
        return pd.concat([df, dummies], axis=1)
   

    # RECO 17 et RECO 18 #####################################
    def fill_nan_values(self, data_input, features, min_pct_avail_features=0.6):  
        """  
        Fill missing values in the dataset based on specified criteria and method.  
        
        Args:  
            data_input (DataFrame): Input data containing features and return metrics  
            features (list): List of feature columns to process  
            min_pct_avail_features (float, default=0.6): Minimum percentage of non-missing features required to keep a row  
            
        Returns:  
            DataFrame: DataFrame with filled missing values  
        """  
        # Calculate minimum number of features required to keep a row  
        min_avail_features = math.ceil(len(features) * min_pct_avail_features)  
        
        # Create a boolean mask for rows with sufficient non-missing features  
        data_input['keep'] = data_input[features].isna().sum(axis=1) <= len(features) - min_avail_features  
        
        
        # RECO 17 et RECO 18 #####################################
        columns_for_fillna = ['Date', "Sector ICB19"]
        features_to_fill_median = [
                                   "Value Avg Percentile",
                                "Quality Avg Percentile",
                                "Mom Avg Percentile",
                                "LowVol Avg Percentile",
                                "Growth Avg Percentile",
                                "Value Avg Percentile_change_1M",
                                "Quality Avg Percentile_change_1M",
                                "Growth Avg Percentile_change_1M",
                                "Value Avg Percentile_change_3M",
                                "Quality Avg Percentile_change_3M",
                                "Growth Avg Percentile_change_3M",
                                "Value Avg Percentile_change_6M",
                                "Quality Avg Percentile_change_6M",
                                "Growth Avg Percentile_change_6M",
                                "Value Avg Percentile_change_12M",
                                "Quality Avg Percentile_change_12M",
                                "Growth Avg Percentile_change_12M"
                            ]

        columns_for_fillna_div = ['Date']
        features_to_fill_div = ['Dividend Avg Percentile']
        
        
        # Fill the nan by the median
        for feature_to_fill in features_to_fill_median:
            data_input[feature_to_fill] = data_input.groupby(columns_for_fillna)[feature_to_fill].transform(lambda x: x.fillna(x.median()))  
 
        # Fill the nan by 0 for dividend car pas de données veut dire mauvais score
        for feature_to_fill in features_to_fill_div:
             data_input[feature_to_fill] =data_input[feature_to_fill].fillna(0)   

        # Filter out rows that don't meet the minimum feature availability requirement  
        data_input = data_input[data_input['keep'] == True]  
        
        # Remove the temporary 'keep' column  
        data_input = data_input.drop(columns=['keep'])  
        
        return data_input  
    
    def labellize_data(self, df, returns_horizon):  
        """  
        Create Label Columns based on label chosen to predict.  
        
        Args:  
            df (DataFrame): Input data frame  
            features (int or list): Period(s) for prediction  
            
        Returns:  
            DataFrame: DataFrame with added label columns  
        """       

        for period in returns_horizon:  
            df[f'{period}M label'] = df[f'information_ratio {period}M']  
                
        return df 

    def detect_if_error_date(self, df):
        
        test_="OK"
        today = datetime.combine(datetime.today().date(), datetime.min.time())
        # today à définir
        df['Date'] = pd.to_datetime(df['Date'])

        try:
            # TEST IS DATE is > Today Date
            nb_date_sup_today=len(df.loc[df['Date']>today,"Date"])
            # print("Nombre de date > today ", nb_date_sup_today)
   
            # TEST IS DIFFERENCE OF DAYS BETWEEN 2 DATE is min 25 days
            unique_date = df.drop_duplicates(subset="Date").sort_values(by='Date', ascending=True)["Date"]
            unique_date_diff = unique_date.diff().dt.days.dropna()
            max_ecart=max(unique_date_diff)
            min_ecart=min(unique_date_diff)
            print("max ecart entre 2 dates : ",max(unique_date_diff))
            print("min ecart entre 2 dates : ",min(unique_date_diff))

            test_="OK"
            if nb_date_sup_today>0:
                print("Nombre de date > today ", nb_date_sup_today)
                test_="KO"
                raise ValueError("Les données d'entrée sont vides.")
            if max_ecart>34:
                print("max ecart entre 2 dates : ",max(unique_date_diff))
                test_="KO"
                raise ValueError("Les données d'entrée sont vides.")
            if min_ecart<26:
                print("min ecart entre 2 dates : ",min(unique_date_diff))
                test_="KO"
                raise ValueError("Les données d'entrée sont vides.")
            if test_ == "OK":
                print("TEST : detect_if_error_date REUSSI")
        except Exception as e:
            print("Erreur func detect_if_error_date()")
            raise
  

##############################################    
 
    def preprocess(self):
        screen_clean = self._clean_screen(self.screen_agg)

        # RECO CHECK DATE
        self.detect_if_error_date(screen_clean)
        ##

        for horizon in self.returns_horizon:
            screen_clean = self._compute_returns(
                                                screen_clean, 
                                                horizon,
                                                sector_neutral=self.returns_neutral[0] if self.returns_neutral else None
                                                )

        screen_full_feat = self._add_variations(screen_clean)

        secteurs_attendus = self.get_secteurs_attendus()
        self.identifier_secteurs_inattendus(screen_full_feat, secteurs_attendus=secteurs_attendus)
        screen_full_feat = self.ajouter_dummies_secteurs(screen_full_feat, secteurs_attendus=secteurs_attendus)
 
        screen_full_feat = screen_full_feat.reset_index()
        screen_full_feat['Date'] = screen_full_feat['Date'].dt.to_period('M').dt.to_timestamp('M')
        screen_full_feat = screen_full_feat.set_index(['Company SEDOL', 'Date']) 

        ################ RECO 46 47 ######################
        # Clean NaN values  
        screen_full_feat = self.fill_nan_values(  
            screen_full_feat,  
            self.params_strat['features'],   
            self.params_strat['min_pct_avail_features'] 
        )  
        
        # Create Label Columns based on label chosen to predict  
        screen_full_feat = self.labellize_data(  
            screen_full_feat,  
            self.returns_horizon  
        )  

        _write_dataframe(screen_full_feat, self.df_features_path)




