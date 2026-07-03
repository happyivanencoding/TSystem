import sys
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import copy
import pandas as pd
from datetime import datetime
from dateutil import relativedelta
import numpy as np
from Codes.BACKTEST import *


def backtest_with_frais(structure_cout,
            sec_list, 
            indice_name, 
            screen_path, 
            df_returns_path, 
            max_weight = 1, 
            col_sector= ' Benchmark ICB Supersector ', 
            col_sedol='Company SEDOL', 
            col_isin='ISIN', 
            col_date = 'Date', 
            col_mkt_cap = 'Benchmark Market Value Millions in EUR', 
            sector_neutral=False, 
            ponderation='mkt_cap'
            ):
    
    # if input is path, then read the parquet, it it's a df, then use it directly
    if type(screen_path)==str:
        screen_agg = pd.read_parquet(screen_path)
    else:
        screen_agg=copy.deepcopy(screen_path)
 
    if type(df_returns_path)==str:
        df_returns = pd.read_parquet(df_returns_path)
    else:
        df_returns=copy.deepcopy(df_returns_path)

    # Loading sec_list
    buy_list = copy.deepcopy(sec_list)
    
    # For a normal ptf that weight column is included
    if 'Weight' in buy_list.columns:
        # AVOIR UNE SECLIST AU 1ER DU MOIS pour MATCHER AVEC SCREEN AGGREGATE QUI SERA SHIFTé du 31 du mois au 1er du mois suivant
        sec_list_full = buy_list[[col_date,col_isin,'Weight']]

        ### Rebalancing weight for each date ###
        # OLD VERSION
        # sum_ptf_date = sec_list_full.groupby(col_date)['Weight'].sum()
        # sec_list_full.set_index(col_date, inplace=True)
        # sec_list_full['Weight'] /= sum_ptf_date

        # NEW TEST VERSION
        sec_list_full['Weight'] = (
                                    sec_list_full.groupby(col_date)['Weight']
                                    .transform(lambda w: w / w.sum())
                                    )
        
        # Outliers transformation into [0, 1]
        sec_list_full['Weight'] = sec_list_full['Weight'].apply(lambda x : max(x,0))
        sec_list_full['Weight'] = sec_list_full['Weight'].apply(lambda x : min(x,max_weight))


        ### Redo rebalancing
        # OLD
        # sec_list_full['Weight'] /= sec_list_full.groupby(col_date)['Weight'].sum()

        # NEW
        sec_list_full["WeightSum"] = sec_list_full.groupby("Date")["Weight"].transform("sum")
        sec_list_full['Weight'] /= sec_list_full["WeightSum"]

        sec_list_full.reset_index(inplace=True)

        sec_list_full.rename(columns={'Weight':'Portfolio weight'},inplace=True) # Rename column of weight

        # Make sure that column of date is date format
        screen_agg[col_date] = pd.to_datetime(screen_agg[col_date])

        # Then push the date to the first day of the next month
        screen_agg[col_date] = screen_agg[col_date] + pd.offsets.MonthBegin(1)

        # Generating final seclist
        sec_list_full = sec_list_full.merge(right = screen_agg.reset_index()[[col_date,col_isin,col_sedol,col_sector, col_mkt_cap]], on=[col_date,col_isin], how='left')
        sec_list_full = sec_list_full[sec_list_full[col_sedol].notna()] # Remove empty sedol companies
        sec_list_full = sec_list_full[[col_date, col_sedol,col_isin, 'Portfolio weight', col_sector]].set_index([col_date,col_sedol])
    
    # For generating all titles sec list for a BENCHMARK
    else:
        # AVOIR UNE SECLIST AU 1ER DU MOIS pour MATCHER AVEC SCREEN AGGREGATE QUI SERA SHIFTé du 31 du mois au 1er du mois suivant
        error=''
        # sec_list_full = create_ptf_weight(buy_list, indice_name, screen_agg, max_weight, col_mkt_cap, col_date, col_sector, sector_neutral, ponderation, col_sedol, col_isin)
        
    perf_ttr, weight_change, portfolio_tet = calcul_all_portfolio_with_frais(structure_cout,sec_list_full, df_returns, 'Portfolio weight', col_sector, col_date, col_sedol)
    return perf_ttr, sec_list_full[[col_date,col_isin,'Portfolio weight', col_sector]], weight_change, portfolio_tet
    
    
    
    
    
    
    
    
    
    
def calcul_all_portfolio_with_frais(structure_cout, df_rebal, df_returns, col_weight,col_sector = ' Benchmark ICB Supersector ', col_date='Date', col_id = 'Company SEDOL'):
    
    #Structure des couts
    structure_cout_TTF =  structure_cout["structure_cout_TTF"]
    structure_cout_Table_Exe = structure_cout["structure_cout_Table_Exe"]
    structure_cout_Table_Broker = structure_cout["structure_cout_Table_Broker"]
    structure_cout_fdg = structure_cout["structure_cout_fdg"]

    # Creating a list of available date in sec list (MONTHLY) - premier jour du mois
    liste_rebal_date = list(df_rebal.index.get_level_values(col_date).unique())
    # Creating a list of date (DAILY), but from returns dataframe, starting from the first date of the sec list
    liste_date_returns = list(df_returns[df_returns.index>=liste_rebal_date[0]].index)

    #filtrer pour avoir la période du portefeuille
    df_rebal.reset_index(inplace=True)
 
    df_rebal = df_rebal[df_rebal[col_id].isin(df_returns.columns)] #SUPPRESSION DES TITRES QUI NE SONT PAS DS LE parquet RETURN
    df_rebal.set_index(col_date,inplace=True)

    # OLD
    # df_rebal['Portfolio weight'] /= df_rebal.groupby(col_date)['Portfolio weight'].sum()

    # NEW
    df_rebal['Portfolio weight'] = (
                                    df_rebal.groupby(col_date)['Portfolio weight']
                                    .transform(lambda x: x / x.sum())
                                    )
    
    df_rebal.reset_index(inplace=True)
    
    


    # Boucle dans le cas d'une date de rebalancement non présente dans df_returns -> changement de la date de rebalancement avec la date future la plus proche
    for i in range(len(liste_rebal_date)) :
        if  liste_rebal_date[i] not in liste_date_returns :

            try:
                # Try pour chercher la date future la plus proche
                new_date_rebal = min(d for d in liste_date_returns if d > liste_rebal_date[i])
            except ValueError:
                # Si pas de future date trouvée, on prend la date antérieure la plus proche (cas frequency=1 dernière date est une date de rebalancement)
                new_date_rebal = max(d for d in liste_date_returns if d < liste_rebal_date[i])
 
            df_rebal = df_rebal.replace(liste_rebal_date[i], new_date_rebal)
            liste_rebal_date[i] = new_date_rebal

            # Monthly_TTF_cost_structure.rename(columns={'aa': 'bbb'}, inplace=True)
            # Monthly_TTF_cost_by_Date
            
            
            




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
    
    #L'objectif de ces lignes est de sortir un screen Daily avec toutes les date et poids du precedent rebal pour tous les jours du mois en cours pour faire drifter les poids M en Daily
    #ON DUPPLIQUE LES DATES DE SCREEN MENSUEL POUR CHAQUE DATE de new DF dont la colonne Date Screen = col_date de df_rebal (date de rebalancement)
    df_merge = df_rebal.merge(new_df, how='left', left_on=col_date, right_on = 'Date_screen')
    df_merge.drop(columns=col_date, inplace=True)
    df_merge.rename(columns={'Date_returns':col_date},inplace=True) #BONNE COLONNE DE DATE
    df_merge.sort_values(by=col_date, inplace=True)
 
    df_returns = df_returns[new_df['Date_screen'].min():] # ON LES RETURN A PARTIR DE LA PREMIERE DATE
    returns_cum = (1+df_returns).cumprod() # On a le ttr calculé pour à ârtir de la 1ère date de rebalancement
    
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


    df_merge = df_merge.merge(returns_drift_flat, how='left', on = [col_date, col_id])#AJOUT DE 'drift_multiplicator'
    df_merge = df_merge.merge(returns_flat, how='left', on = [col_date, col_id])
    
    #CHAQUE POIDS DAILY est DRIFTé dont celui du rebal qui est aussi drifté par 1
    df_merge[col_weight+'_drifted'] = df_merge[col_weight]*df_merge['drift_multiplicator'] 
    """ EX. the weight af asset A is 0.6, drift_multiplicator is 1.1, then drifted weight : 0.6 * 1.1 = 0.66 """
    

    # Select the date, asset identifier, original weight, drift-adjusted weight, sector (or segment), 
    # and return data to form a new data frame `portfolio_tet`, facilitating subsequent calculations by date and asset.
    columns = [col_date, col_id, col_weight, col_weight+'_drifted', col_sector, 'Return','ISIN','Date_screen']
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
    serie_ttr_gross=(1 + total_return_by_date.fillna(0)).cumprod() * 100 

    result = pd.DataFrame({'total_return_by_date': total_return_by_date, 'serie_ttr_gross': serie_ttr_gross})
    result.reset_index(drop=False,inplace=True)

    df_w_for_cost=portfolio_tet[['Date','ISIN','Date_screen','W_rebased']].sort_values('Date').reset_index()

    # 2
    df_w_for_cost['previous_rebased_drifted']=df_w_for_cost.groupby('ISIN')['W_rebased'].shift(1)
    df_w_for_cost['weight_diff_rebal'] = df_w_for_cost['W_rebased'] - df_w_for_cost['previous_rebased_drifted']
    df_w_for_cost['prev Date_screen'] =df_w_for_cost.groupby('ISIN')['Date_screen'].shift(1)
    
    df_w_for_cost['rebal_indic']=np.where(df_w_for_cost['Date_screen'] > df_w_for_cost['prev Date_screen'], 1, 0)
    pivot_weights=df_w_for_cost.loc[df_w_for_cost['rebal_indic']==1,['Date','ISIN','Date_screen','W_rebased']]

    pivot_weightsD = pivot_weights.pivot_table(
                index='ISIN',
                columns='Date',
                values='W_rebased',
                fill_value=0 # Assume 0 weight if security not listed on a specific date
            )
    pivot_weightsD_moins1 = pivot_weightsD.shift(1, axis=1)
    weight_change = pivot_weightsD.sub(pivot_weightsD_moins1, fill_value=0)


    # Calculate the change in weight, positive weight and "Country" concerned with positive weight
    # weight_change = pivot_weights.fillna(0)#,fill_value=0


    # weight_change = pivot_weights.diff(axis=1).fillna(0)#,fill_value=0
    pos_weight_change = weight_change[weight_change > 0].fillna(0)
    first2_letters_countries_TTF=list(structure_cout_TTF.Country)
    Country_concerned_pos_weight_change=pos_weight_change[pos_weight_change.index.str.startswith(tuple(first2_letters_countries_TTF))].fillna(0)

    # Define Monthly_TTF_cost_structure as "Country_concerned_pos_weight_change" * TTF FEES by Country 
    Country_concerned_pos_weight_change['Country'] = Country_concerned_pos_weight_change.index.str[:2]
    Monthly_TTF_cost_structure = Country_concerned_pos_weight_change.merge(structure_cout_TTF, on='Country', how='left')
    
    # Define Monthly_Table_cost_structure and Brokerage
    Monthly_cost_Table_exe=weight_change.abs()
    Monthly_cost_Brokerage=weight_change.abs()
    weight_change_for_TO_calcul=weight_change.abs()

    # Multiply each weight column by the corresponding TTF fee and Table and Brokerage Fee
    weight_columns = [col for col in Monthly_TTF_cost_structure.columns if col not in ['ISIN', 'Country', 'Fees']]
    for col in weight_columns:
        Monthly_TTF_cost_structure[col] = Monthly_TTF_cost_structure[col] * Monthly_TTF_cost_structure['Fees']
        Monthly_cost_Table_exe[col]= Monthly_cost_Table_exe[col] * structure_cout_Table_Exe
        Monthly_cost_Brokerage[col]= Monthly_cost_Brokerage[col] * structure_cout_Table_Broker

    # Drop the 'Country' and 'Fees' columns if no longer needed
    Monthly_TTF_cost_structure.fillna(0,inplace=True)
    Monthly_cost_Table_exe.fillna(0,inplace=True)
    Monthly_cost_Brokerage.fillna(0,inplace=True)
    Monthly_TTF_cost_structure.drop(columns=['Country', 'Fees'], inplace=True)
    Country_concerned_pos_weight_change.drop(columns=['Country'], inplace=True)

    # CALCULATE Monthly TTF Table and Brokerage Fee Cost
    # Monthly_TTF_cost_by_Date=Monthly_TTF_cost_structure.sum()
    Monthly_TTF_cost_by_Date=pd.DataFrame(Monthly_TTF_cost_structure.sum(),columns=['TTF cost']).reset_index(drop=False).rename(columns={'index': 'Date'})

    # Monthly_Table_cost_by_Date=Monthly_cost_Table_exe.sum()
    Monthly_Table_cost_by_Date=pd.DataFrame(Monthly_cost_Table_exe.sum(),columns=['Table cost']).reset_index(drop=False).rename(columns={'index': 'Date'})

    # Monthly_Broker_cost_by_Date=Monthly_cost_Brokerage.sum()
    Monthly_Broker_cost_by_Date=pd.DataFrame(Monthly_cost_Brokerage.sum(),columns=['Broker cost']).reset_index(drop=False).rename(columns={'index': 'Date'})

    # TO by Date
    Monthly_TO_by_Date=pd.DataFrame(weight_change_for_TO_calcul.sum(),columns=['Turn_Over 2w']).reset_index(drop=False).rename(columns={'index': 'Date'})

    # DF with 3 columns : TTF, Table, Broker Fees, Turn Over
    Monthly_cost_by_Date=pd.merge(Monthly_TTF_cost_by_Date, Monthly_Table_cost_by_Date, on="Date", how="inner")
    Monthly_cost_by_Date=pd.merge(Monthly_cost_by_Date, Monthly_Broker_cost_by_Date, on="Date", how="inner")
    Monthly_cost_by_Date=pd.merge(Monthly_cost_by_Date, Monthly_TO_by_Date, on="Date", how="inner") 
    # Get the Date of Daily Return where Fees is applied. First return Day equal or superior to rebalancing day
    df_returns_date=pd.DataFrame(df_returns.index,columns=["Date"])

    date_return_max= df_returns_date.loc[:,col_date].max()
    Monthly_cost_by_Date['Date'] = Monthly_cost_by_Date['Date'].apply(lambda x: min(x, date_return_max))# Replace Date by Date return max if Date goed beyond Date return
    
    Monthly_cost_by_Date["Daily Date"]=Monthly_cost_by_Date['Date'].apply(lambda x: df_returns_date.loc[df_returns_date[col_date]>=x, col_date].min())
    Monthly_cost_by_Date['TTF cost'] = Monthly_cost_by_Date['TTF cost'].fillna(0)
    Monthly_cost_by_Date['Table cost'] = Monthly_cost_by_Date['Table cost'].fillna(0)
    Monthly_cost_by_Date['Broker cost'] = Monthly_cost_by_Date['Broker cost'].fillna(0)
    Monthly_cost_by_Date['Turn_Over 2w'] = Monthly_cost_by_Date['Turn_Over 2w'].fillna(0)
    Monthly_cost_by_Date.rename(columns={'Date': 'Date Rebalancing'}, inplace=True)
    ####################################################################################################################################################################
    ####################################################################################################################################################################


    # ADDING NET RETURN AND NET CUMPROD
    result = result.merge(Monthly_cost_by_Date, how='left', left_on='Date', right_on='Daily Date')
    result = result.drop(['Daily Date'], axis=1)
    
    result['days_diff'] = result['Date'].diff().dt.days                                      #For Daily management Fees
    result['frais de gestion'] =  (result['days_diff']) * structure_cout_fdg       #For Daily management Fees
    
    result['frais de gestion'] = result['frais de gestion'].fillna(0)
    result['TTF cost'] = result['TTF cost'].fillna(0)
    result['Table cost'] = result['Table cost'].fillna(0)
    result['Broker cost'] = result['Broker cost'].fillna(0)
    
    result['net_return_by_date'] = result['total_return_by_date'] + result['TTF cost'] + result['Table cost'] + result['Broker cost'] + result['frais de gestion']
    result['serie_total_nr'] = (1 + result['net_return_by_date']).cumprod()* 100 
    result['serie_cost'] = (1 + result['frais de gestion'] + result['TTF cost'] + result['Table cost'] + result['Broker cost'] ).cumprod()* 100 
    result['Turn_Over 2w'] = result['Turn_Over 2w'].fillna(0)
    result['Turn-Over 2w cumsum'] = result['Turn_Over 2w'].cumsum()

    return result, weight_change, portfolio_tet


# def calculate_turnover(df: pd.DataFrame,
#                        date_col: str = 'Date',
#                        id_col: str = 'ISIN',
#                        weight_col: str = 'Weight') -> pd.Series:
#     """
#     Calcule le turnover de portefeuille entre chaque date de rééquilibrage.
    
#     Turnover_t = ½ * sum_i | w_{i,t} - w_{i,t-1} |
    
#     Retourne une Series indexée par date t, contenant le turnover sur la période (t-1 -> t).
    
#     :param df: DataFrame avec au moins trois colonnes [date_col, id_col, weight_col].
#     :param date_col: nom de la colonne de date (doit être convertible en datetime).
#     :param id_col: nom de la colonne identifiant l’actif (ici ISIN).
#     :param weight_col: nom de la colonne de poids (somme à 1 ou 100 %).
#     :return: Series turnover, indexée par date de rééquilibrage.
#     """
#     # 1) Prétraitements
#     df = df.copy()
#     df[date_col] = pd.to_datetime(df[date_col])
    
#     # 2) Construction de la matrice date × actif (poids)
#     pivot = (
#         df
#         .pivot_table(index=date_col, columns=id_col, values=weight_col, aggfunc='sum')
#         .fillna(0)            # actifs absents deviennent poids 0
#         .sort_index()         # tri chronologique
#     )
    
#     # 3) Calcul des différences absolues et turnover
#     diff = pivot.diff().abs()        # |w_t - w_{t-1}|
#     turnover = diff.sum(axis=1) / 2  # ½ * Σ_i |Δw_i|
#     turnover.name = 'turnover'
    
#     return turnover

def normalize_to_base_100(df, plot=True):
    df_normalized = df.copy()
    
    for column in df.columns:
        first_value = df[column].dropna().iloc[0]
        df_normalized[column] = (df[column] / first_value) * 100
    
    if plot:
        (df_normalized.iloc[:,0] / df_normalized.iloc[:,1]).plot()

    return df_normalized

def generate_portfolio_performance(screen_agg_with_score, ptf_cap, bench, returns, perf_save_path, plot=True):
    # Reset index and get start date
    screen_agg_with_score = screen_agg_with_score.reset_index()
    start_date = screen_agg_with_score["Date"].min()
    screen_agg_with_score.set_index("ISIN", inplace=True)
    
    # Generate performance for portfolio
    perf_ptf, buy_list = backtest(ptf_cap, bench, screen_agg_with_score, returns)
    perf_ptf.name = "ptf"
    
    # Generate performance for benchmark STOXX 600
    indice_ref = screen_agg_with_score[
        (screen_agg_with_score['Date'] > start_date) * 
        (screen_agg_with_score['Weight in ' + bench] > 0)
    ].reset_index()[['Date', 'ISIN']]
    
    indice_ref["Date"] = indice_ref["Date"].apply(
        lambda x: x + relativedelta.relativedelta(months=1, day=1)
    )
    
    perf_bench, indice = backtest(indice_ref, bench, screen_agg_with_score, returns)
    perf_bench.name = bench
    
    # Save performance data
    perf_ptf.to_parquet(perf_save_path)
    
    # Plot performance comparison chart (optional)
    if plot:
        pd.concat([perf_ptf, perf_bench], axis=1).plot()
        plt.title(f"Portfolio vs {bench} Performance Comparison")
        plt.ylabel("Performance")
        plt.xlabel("Date")
        plt.legend()
        plt.show()
    
    return perf_ptf, perf_bench, buy_list


def compute_weights_for_date_acwi(df):
    # Weight US
    weight_us = (
    df[df['Exchange Country Region']=="North America"]
    .sort_values('Weight in MSCI ACWI', ascending=False)
    .iloc[:600]['Weight in MSCI ACWI']
    .sum()
    )

    # Weight West Europe  
    weight_europe = (  
        df[df['Exchange Country Region'] == "West Europe"]
        ['Weight in MSCI ACWI']  
        .sum()  
    )  

    # Weight other  
    list_autres_pays = ['JAPAN',
                        'HONG KONG', 'AUSTRALIA',
                        'ISRAEL',
                        'SINGAPORE', 
                        'NEW ZEALAND', 'SOUTH AFRICA', 'THAILAND', 'SOUTH KOREA',
                        'INDIA']
    
    
    # ['CHINA',
    #                     'AUSTRALIA',
    #                     'HONG KONG',
    #                     'MALAYSIA',
    #                     'MEXICO',
    #                     'SOUTH AFRICA',
    #                     'PHILIPPINES',
    #                     'INDIA',
    #                     'SOUTH KOREA',
    #                     'UNITED ARAB EMIRATES',
    #                     'BRAZIL',
    #                     'HUNGARY',
    #                     'TAIWAN',
    #                     'QATAR',
    #                     'POLAND',
    #                     'CHILE',
    #                     'SAUDI ARABIA',
    #                     'SINGAPORE',
    #                     'TURKEY',
    #                     'THAILAND',
    #                     'INDONESIA',
    #                     'ISRAEL',
    #                     'NEW ZEALAND',
    #                     'KUWAIT',
    #                     'COLOMBIA',
    #                     'EGYPT',
    #                     'CZECH REPUBLIC',
    #                     'JAPAN']
    
    weight_autres = df[df['Exchange Country Name'].isin(list_autres_pays)]['Weight in MSCI ACWI'].sum()  

    return pd.Series({  
        'US weight': weight_us,  
        'EU weight': weight_europe,  
        'Other weight': weight_autres  
    })  


def compute_weights_for_date_world(df):
    # Weight US
    weight_us = (
    df[df['Exchange Country Region']=="North America"]
    ['Weight in MSCI WORLD']  
    .sum()
    )

    # Weight West Europe  
    weight_europe = (  
        df[df['Exchange Country Region'] == "West Europe"]
        ['Weight in MSCI WORLD']  
        .sum()  
    )  

    # Weight other  
    weight_autres = df[~df['Exchange Country Region'].isin(["West Europe", "North America"])]['Weight in MSCI WORLD'].sum()  

    return pd.Series({  
        'US weight': weight_us,  
        'EU weight': weight_europe,  
        'Other weight': weight_autres  
    })  

def adjust_weights_OTHER(df, ratio_other=1.0):
    """
    Adjust weight columns while maintaining the relative ratio between US and EU weights,
    ensuring the total sum equals 1 for each row.
    
    Parameters:
    df: DataFrame containing 'US weight', 'EU weight', 'Other weight' columns
    ratio_other: float, adjustment ratio for Other weight, default is 1.0 (no change)
    
    Returns:
    DataFrame: DataFrame with adjusted weights
    """
    # Copy original dataframe to avoid modifying the original data
    df_adjusted = df.copy()
    
    # Get original weights
    us_original = df['US weight']
    eu_original = df['EU weight'] 
    other_original = df['Other weight']
    
    # Calculate adjusted Other weight
    other_new = other_original * ratio_other
    
    # Calculate original sum of US and EU weights
    us_eu_sum = us_original + eu_original
    
    # Calculate remaining weight to be allocated to US and EU
    remaining_weight = 1.0 - other_new
    
    # Distribute remaining weight proportionally to maintain US:EU ratio
    us_new = remaining_weight * us_original / us_eu_sum
    eu_new = remaining_weight * eu_original / us_eu_sum
    
    # Update dataframe
    df_adjusted['US weight'] = us_new
    df_adjusted['EU weight'] = eu_new
    df_adjusted['Other weight'] = other_new
    
    return df_adjusted


def dates_sont_egales(df1: pd.DataFrame, df2: pd.DataFrame, df3: pd.DataFrame) -> bool:
    """
    Vérifie que les colonnes "Date" de trois DataFrames sont exactement les mêmes.

    Parameters
    ----------
    df1, df2, df3 : pandas.DataFrame
        Les trois DataFrames à comparer.

    Returns
    -------
    bool
        True si les colonnes "Date" sont identiques (valeurs, ordre et type), False sinon.
    """
    # Vérifie que chaque DataFrame possède bien la colonne "Date"
    for i, df in enumerate([df1, df2, df3], start=1):
        if "Date" not in df.columns:
            raise KeyError(f'DataFrame {i} ne contient pas de colonne "Date".')

    # On compare les séries en les convertissant à un type uniforme (datetime64[ns]) si besoin
    dates1 = pd.to_datetime(df1["Date"].unique())
    dates2 = pd.to_datetime(df2["Date"].unique())
    dates3 = pd.to_datetime(df3["Date"].unique())

    if dates1.equals(dates2) and dates2.equals(dates3):
        print("Les dates sont les mêmes")
    else:
        print("Les dates ne sont pas les mêmes")

    return


def adjust_single_portfolio_weights(portfolio_df, weight_regions_bench, region):
    """
    Vectorized version using merge_asof for better performance
    """
    # Convert dates to datetime format
    portfolio_df['Date'] = pd.to_datetime(portfolio_df['Date'])
    weight_regions_bench['Date'] = pd.to_datetime(weight_regions_bench['Date'])
    
    weight_regions_bench = weight_regions_bench.sort_values('Date').reset_index(drop=True)
    
    # Map region to column name
    region_columns = {'US': 'US weight', 'EU': 'EU weight', 'Other': 'Other weight'}
    weight_col = region_columns[region]
    
    # Create copy and sort
    adjusted_df = portfolio_df.copy().sort_values('Date')
    
    # Use merge_asof for efficient date matching
    merged = pd.merge_asof(
        adjusted_df,
        weight_regions_bench[['Date', weight_col]],
        on='Date',
        direction='backward'
    )
    
    # Handle dates before first benchmark date
    if merged[weight_col].isna().any():
        first_weight = weight_regions_bench.iloc[0][weight_col]
        merged[weight_col].fillna(first_weight, inplace=True)
    
    # Apply regional weight
    merged['Regional_Weight'] = merged[weight_col]
    merged['Weight'] = merged['Weight'] * merged['Regional_Weight']
    
    return merged.drop(columns=[weight_col])

# """
# Data Table - Regional Weight Distribution
# =================================================================================
# Date                    US weight           EU weight           Other weight
# =================================================================================
# 2025-01-01 00:00:00    0.772969181361176   0.147133217491316   0.079897594372578
# 2025-02-01 00:00:00    0.774211531262273   0.148642450312826   0.077146018424493
# 2025-03-01 00:00:00    0.762559373520811   0.158924932695007   0.078515693734823
# 2025-04-01 00:00:00    0.753598197539583   0.165837198278543   0.080563819674739
# 2025-05-01 00:00:00    0.747411564266831   0.169358734669482   0.083230108903968
# 2025-06-01 00:00:00    0.749719884026442   0.167110687026446   0.083173283706929
# 2025-07-01 00:00:00    0.754896472543424   0.163712447868743   0.081389095882015
# =================================================================================


# =============================================================================
# KEY TRANSFORMATION LOGIC:
# =============================================================================
# 1. Original Weight: Company's weight within its regional index (MSCI US, STOXX 600, etc.)
# 2. Regional Weight: Region's weight in global benchmark (US ≈77%, EU ≈15%, Other ≈8%)
# 3. Final Weight: Original Weight × Regional Weight = Weight in Global Portfolio

# =============================================================================
# PORTFOLIO WEIGHT ADJUSTMENT - INPUT/OUTPUT EXAMPLES
# =============================================================================

# BEFORE ADJUSTMENT - Original Portfolio Example:
# =============================================================================
# PTF_US:
# Date        | Company | Weight | Sector    | Market_Cap
# ------------|---------|--------|-----------|------------
# 2025-01-01  | AAPL    | 0.0650 | Tech      | 3500B
# 2025-01-01  | MSFT    | 0.0580 | Tech      | 3200B
# 2025-01-01  | GOOGL   | 0.0420 | Tech      | 2100B
# 2025-02-01  | AAPL    | 0.0680 | Tech      | 3600B
# 2025-02-01  | MSFT    | 0.0590 | Tech      | 3250B
# ...

# Regional Weights Benchmark:
# Date        | US weight | EU weight | Other weight
# ------------|-----------|-----------|-------------
# 2025-01-01  | 0.7730    | 0.1471    | 0.0799
# 2025-02-01  | 0.7742    | 0.1486    | 0.0771
# 2025-03-01  | 0.7626    | 0.1589    | 0.0785
# ...
# =============================================================================

# AFTER ADJUSTMENT - Final Output Examples:
# =============================================================================

# us_adjusted:
# Date        | Company | Weight | Sector | Market_Cap | Regional_Weight | Weight (Adjusted)
# ------------|---------|--------|--------|------------|-----------------|------------------
# 2025-01-01  | AAPL    | 0.0650 | Tech   | 3500B      | 0.7730          | 0.0502 (=0.065×0.773)
# 2025-01-01  | MSFT    | 0.0580 | Tech   | 3200B      | 0.7730          | 0.0448 (=0.058×0.773)
# 2025-01-01  | GOOGL   | 0.0420 | Tech   | 2100B      | 0.7730          | 0.0325 (=0.042×0.773)
# 2025-02-01  | AAPL    | 0.0680 | Tech   | 3600B      | 0.7742          | 0.0526 (=0.068×0.774)
# 2025-02-01  | MSFT    | 0.0590 | Tech   | 3250B      | 0.7742          | 0.0457 (=0.059×0.774)
# ...

# eu_adjusted:
# Date        | Company | Weight | Sector | Market_Cap | Regional_Weight | Weight (Adjusted)
# ------------|---------|--------|--------|------------|-----------------|------------------
# 2025-01-01  | ASML    | 0.0320 | Tech   | 280B       | 0.1471          | 0.0047 (=0.032×0.147)
# 2025-01-01  | SAP     | 0.0280 | Tech   | 190B       | 0.1471          | 0.0041 (=0.028×0.147)
# 2025-01-01  | LVMH    | 0.0250 | Cons   | 420B       | 0.1471          | 0.0037 (=0.025×0.147)
# 2025-02-01  | ASML    | 0.0330 | Tech   | 290B       | 0.1486          | 0.0049 (=0.033×0.149)
# 2025-02-01  | SAP     | 0.0290 | Tech   | 195B       | 0.1486          | 0.0043 (=0.029×0.149)
# ...

# other_adjusted:
# Date        | Company | Weight | Sector | Market_Cap | Regional_Weight | Weight (Adjusted)
# ------------|---------|--------|--------|------------|-----------------|------------------
# 2025-01-01  | TSMC    | 0.0280 | Tech   | 550B       | 0.0799          | 0.0022 (=0.028×0.0799)
# 2025-01-01  | TENCENT | 0.0240 | Tech   | 420B       | 0.0799          | 0.0019 (=0.024×0.0799)
# 2025-01-01  | SAMSUNG | 0.0220 | Tech   | 380B       | 0.0799          | 0.0018 (=0.022×0.0799)
# 2025-02-01  | TSMC    | 0.0290 | Tech   | 580B       | 0.0771          | 0.0022 (=0.029×0.0771)
# 2025-02-01  | TENCENT | 0.0250 | Tech   | 430B       | 0.0771          | 0.0019 (=0.025×0.0771)
# ...

# """