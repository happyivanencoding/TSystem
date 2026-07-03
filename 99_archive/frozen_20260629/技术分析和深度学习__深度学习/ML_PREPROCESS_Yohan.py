import warnings
# warnings.filterwarnings('ignore')
import os
import copy
import pandas as pd
import numpy as np
import math 
from pathlib import Path


def _read_dataframe(path):
    path = Path(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_pickle(path)
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


    # RECO 8, 9, 10, 11, 12
    def _compute_returns(self, df, horizon, sector_neutral, min_periods_vol = 5):
        
        col_stock = f'Stock {horizon}M return'
        col_neutral = f'Neutral {horizon}M return'
        
        # S'assurer que les colonnes sont bien présentes
        if 'Company SEDOL' not in df.columns or 'Date' not in df.columns:
            df = df.reset_index()        
            
        
        #### -> RECO 7 et 8 #######
        def compute_forward_return(SEDOL, date, horizon_months):
            try:
                # Convertir la date en Timestamp
                base_date = pd.to_datetime(date)
                
                # RECO 8 : commencer le 2eme jour ouvré du mois
                start = base_date + pd.offsets.MonthBegin(1) # + pd.Timedelta(days=1)
                
                # RECO 9 : Avoir une fenetre d'un mois 
                end = start + pd.DateOffset(months=horizon_months) - pd.Timedelta(days=1) #- pd.Timedelta(days=2)
                
                # Extraire les rendements
                prices = 1 + self.df_returns.loc[start:end, SEDOL]  # end n'est pas inclus car rege python pour liste
                
                # Calcul du rendement cumulé
                return prices.cumprod().iloc[-1] - 1
            except (KeyError, IndexError, ValueError):
                return np.nan

        df[col_stock] = df.apply(
            lambda row: compute_forward_return(row['Company SEDOL'], row['Date'], horizon), axis=1
        )
        ###################################
            
        df = df.set_index(['Company SEDOL', 'Date'])        
        df.dropna(subset=[col_stock], inplace=True)

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

        df[f'Relative {horizon}M return'] = df[col_stock] - df[col_neutral]
        
        # RECO 12 ###############
        # rolling_std = df.groupby(level=0)[f'Relative {horizon}M return'].expanding(min_periods = min_periods_vol).std().droplevel(0)
        rolling_std = df.groupby(level=0)[f'Relative {horizon}M return'].expanding().std().droplevel(0)
        #############
        
        df[f'information_ratio {horizon}M'] = df[f'Relative {horizon}M return'] / np.exp(rolling_std)

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

                # self.variation_method='change_diff'
                # self.variation_method='change_pct'
                if self.variation_method=='change_pct':
                    print("Percentile change method is used for generating change variables")
                    series = df.groupby("ISIN",
                                        group_keys=False
                                        )[feature].apply(
                        lambda x: x.pct_change(freq=pd.DateOffset(months=int(period)), fill_method=None)
                        )#.reset_index(level=0, drop=True)
                    df[col_name] = series
                    df[col_name].replace({np.inf: 1, -np.inf: -1}, inplace=True)

                elif self.variation_method=='change_diff': #self.variation_method=='change_diff':
                    print("Difference of change method is used for generating change variables")
                    # series = df.groupby("ISIN",
                    #                     group_keys=False
                    #                     )[feature].apply(
                    #     # lambda x: calculate_offset_change(x,int(period))).reset_index(level=0, drop=True)    
                    #     lambda x: x-x.shift(period, freq=pd.DateOffset(months=1)))#.reset_index(level=0, drop=True)
                    # seriesD=pd.DataFrame(series).reset_index(drop=False).rename(columns={feature:col_name})

                    series = df.groupby("ISIN",
                                        group_keys=True
                                        )[feature].apply(
                        # lambda x: calculate_offset_change(x,int(period))).reset_index(level=0, drop=True)    
                        lambda x: x-x.shift(int(period), freq=pd.DateOffset(months=1)))#.reset_index(level=0, drop=True)
                    df = df.reset_index().set_index(['ISIN', 'Date_M'])
                    df[col_name] = series
                    df[col_name] = df[col_name].fillna(0)
                    df = df.reset_index().set_index("Date_M")


                    # screen_agg_ = screen_agg_.reset_index(drop=False)
                    # screen_agg_["Date_M"] = screen_agg_["Date"].dt.to_period("M").dt.to_timestamp()
                    # screen_agg_ = screen_agg_.sort_values(["ISIN", "Date_M"])
                    # screen_agg_.set_index("Date_M", inplace=True)
                            
                    # feature="Value Avg Percentile"
                    # period=3
                    # col_name = f"{feature}_change_{int(period)}M"


                    # series = screen_agg_.groupby("ISIN")[feature].progress_apply(lambda x: x-x.shift(period,freq=pd.DateOffset(months=int(1))))#.reset_index(level=0, drop=True)

                    # screen_agg_.reset_index(drop=False,inplace=True)
                    # screen_agg_=screen_agg_.merge(seriesD,on=['Date_M','ISIN'],how='left')

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
            print(f"Alerte : Secteurs inattendus détectés : {secteurs_inattendus}")
       
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
        # Fill missing values based on features nature 
        for feature_ in features:
            if "Percentile_change" in feature_:
                data_input[feature_] = data_input[feature_].fillna(0)  
            elif "Percentile" in feature_:
                data_input[feature_] = data_input[feature_].fillna(5)
            elif "Sector" in feature_:
                data_input[feature_] = data_input[feature_].fillna(0)   

                    
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
    
##############################################    
 
    def preprocess(self):
        screen_clean = self._clean_screen(self.screen_agg)

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

        screen_full_feat.to_pickle(self.df_features_path)



