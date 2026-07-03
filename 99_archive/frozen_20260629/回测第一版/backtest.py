import pandas as pd
import matplotlib.pyplot as plt
import copy
from dateutil import relativedelta
import numpy as np

import warnings
warnings.filterwarnings("ignore")
 
def calcul_all_portfolio(df_rebal, df_returns, col_weight,col_sector = ' Benchmark ICB Supersector ', col_date='Date', col_id = 'Company SEDOL'):
    
    # Creating a list of available date in sec list (MONTHLY) - premier jour du mois
    liste_rebal_date = list(df_rebal.index.get_level_values(col_date).unique())
    # Creating a list of date (DAILY), but from returns dataframe, starting from the first date of the sec list
    liste_date_returns = list(df_returns[df_returns.index>=liste_rebal_date[0]].index)

    #filtrer pour avoir la période du portefeuille
    df_rebal.reset_index(inplace=True)
 
    df_rebal = df_rebal[df_rebal[col_id].isin(df_returns.columns)] #SUPPRESSION DES TITRES QUI NE SONT PAS DS LE PICKLE RETURN
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

 
# def calcul_rendement(portfolio_tet, col_weight, col_date='Date') :
#     # Rebasage des poids à chaque date
#     weight_sum_date = portfolio_tet.groupby(col_date,group_keys=False)[[col_weight]].sum()
#     weight_sum_date.columns = ['Weight_sum']
#     weight_sum_date.reset_index(inplace=True)
 
#     portfolio_tet = portfolio_tet.merge(weight_sum_date, how='left', on = col_date)
#     portfolio_tet['W_rebased'] = portfolio_tet[col_weight]/portfolio_tet['Weight_sum']
 
#     # Calculer le rendement pondéré pour chaque ligne
#     portfolio_tet['Contrib'] = portfolio_tet['W_rebased']*portfolio_tet['Return']
 
#     # Calculer le rendement total du portefeuille pour chaque date
#     total_return_by_date = portfolio_tet.groupby(col_date)['Contrib'].sum()
#     total_return_by_date.loc[total_return_by_date.index[0]-relativedelta.relativedelta(days=1)] = 0
#     total_return_by_date.sort_index(inplace=True)
 
#     # Calculer la performance cumulée du portefeuille
#     return (1 + total_return_by_date.fillna(0)).cumprod() * 100  
 
def calcul_drawdown(portfolio_tet, col_date, col_ttr):
 
    # Assuming the Date column is a string type that represents dates.
    # You might need to specify the exact format if it's not automatically recognized.
    # For example, if your dates are in the format 'YYYYMMDD', you would use:
    # portfolio_tet['Date'] = pd.to_datetime(portfolio_tet['Date'], format='%Y%m%d')
    portfolio_tet[col_date] = pd.to_datetime(portfolio_tet[col_date])
 
    # Now calculate the running max and drawdown
    running_max = np.maximum.accumulate(portfolio_tet[col_ttr])
    return (portfolio_tet[col_ttr] - running_max) / running_max
 
    # # Start plotting
    # fig, ax1 = plt.subplots(figsize=(14, 7))
 
    # # Plot the cumulative returns
    # color = 'tab:blue'
    # ax1.set_xlabel('Date')
    # ax1.set_ylabel('Weighted_Return_cumulative', color=color)
    # ax1.plot(portfolio_tet['Date'], portfolio_tet['Weighted_Return_cumulative'], color=color)
    # ax1.tick_params(axis='y', labelcolor=color)
 
    # # Plot the drawdown on a secondary y-axis
    # ax2 = ax1.twinx()
    # color = 'tab:red'
    # ax2.set_ylabel('Drawdown', color=color)
    # ax2.plot(portfolio_tet['Date'], drawdown, color=color)
    # ax2.tick_params(axis='y', labelcolor=color)
 
    # # Rotate the dates and format them
    # fig.autofmt_xdate()
    # ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    # ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
 
    # plt.title('Portfolio Value and Drawdown')
    # plt.show()
 
def create_ptf_weight(sec_list, 
                      indice_name, 
                      screen_agg, 
                      max_weight ,  
                      col_mkt_cap='Benchmark Market Value Millions in EUR', 
                      col_date = 'Date', 
                      col_sector = ' Benchmark ICB Supersector ', 
                      sector_neutral=False, method='mkt_cap', 
                      col_sedol = 'Company SEDOL', 
                      col_isin= 'ISIN'
                      ):
    
    # INDICE, SCREENAGGREGATE et SECLIST SERONT INVESTI AU 1er du mois
    # Filter Bench related securities and take the weight of bench as sec list
    indice = screen_agg.loc[screen_agg['Weight in '+indice_name]>0, [col_date, col_sedol,col_sector,'Weight in '+indice_name]].reset_index()
    indice.rename(columns={'Weight in '+indice_name:'Indice weight'}, inplace= True)
 
    indice.sort_values(by=col_date,inplace=True)
    sec_list.sort_values(by=col_date,inplace=True)

    # OLD
    # indice[col_date]=indice[col_date].apply(lambda x: x + relativedelta.relativedelta(months=1,day=1))
    # screen_agg[col_date]=screen_agg[col_date].apply(lambda x: x + relativedelta.relativedelta(months=1,day=1))
    # NEW
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
 
# Fonction de backtest avec en input data_predict = df_scores adapté selon nos besoins , frequence de rebalancement , dataframe des returns
# def compute_perf(sec_list, df_returns, col_sector= ' Benchmark ICB Supersector ', col_id='Company SEDOL', col_date = 'Date'):
 
#     # Dataframe final avec l'ensemble des jours (rebal + non-rebal) avec les poids DRIFTé
#     portfolio_final, serie_ttr = calcul_all_portfolio(sec_list, df_returns, 'Portfolio weight', col_sector, col_date, col_id)
    
#     # Affichage des rendements cumulés , rendements journaliers, poids journaliers du portefeuille
#     # serie_ttr = calcul_rendement(portfolio_final,'Portfolio weight',col_date)
#     # Affichage de drawdown pour évaluer notre stratégie d'investissement
#     #dd = calcul_drawdown(portfolio_final, col_date, 'Weighted_Return')
#     return serie_ttr
 
 
def backtest(sec_list, 
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
    
    # if input is path, then read the pickle, it it's a df, then use it directly
    if type(screen_path)==str:
        screen_agg = pd.read_pickle(screen_path)
    else:
        screen_agg=copy.deepcopy(screen_path)
 
    if type(df_returns_path)==str:
        df_returns = pd.read_pickle(df_returns_path)
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
        sec_list_full = create_ptf_weight(buy_list, indice_name, screen_agg, max_weight, col_mkt_cap, col_date, col_sector, sector_neutral, ponderation, col_sedol, col_isin)
        
    perf_ttr = calcul_all_portfolio(sec_list_full, df_returns, 'Portfolio weight', col_sector, col_date, col_sedol)
    return perf_ttr, sec_list_full[[col_date,col_isin,'Portfolio weight', col_sector]]