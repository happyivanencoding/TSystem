import pandas as pd
import matplotlib.pyplot as plt
import copy
from dateutil import relativedelta
import numpy as np

def calcul_all_portfolio(df_rebal, df_returns, col_weight,col_sector = ' Benchmark ICB Supersector ', col_date='Date', col_id = 'Company SEDOL'):

    liste_rebal_date = list(df_rebal.index.get_level_values(col_date).unique())
    liste_date_returns = list(df_returns[df_returns.index>=liste_rebal_date[0]].index)
    #filtrer pour avoir la période du portefeuille
    df_rebal.reset_index(inplace=True)

    df_rebal = df_rebal[df_rebal[col_id].isin(df_returns.columns)]

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
    
    new_df=pd.DataFrame(data=nouvelle_liste_dates, columns=['Date_returns'])
    new_df['Date_screen'] = new_df['Date_returns'].apply(lambda x: df_rebal.loc[df_rebal[col_date]<=x, col_date].max())
    df_merge=df_rebal.merge(new_df, how='left', left_on=col_date, right_on = 'Date_screen')
    df_merge.drop(columns=col_date,inplace=True)
    df_merge.rename(columns={'Date_returns':col_date},inplace=True)
    df_merge.sort_values(by=col_date,inplace=True)

    df_returns = df_returns[new_df['Date_screen'].min():]
    returns_cum = (1+df_returns).cumprod()

    returns_drift = returns_cum.apply(lambda x:x/returns_cum.loc[(new_df.loc[new_df['Date_screen']<=x.name,'Date_screen'].max())], axis=1)
    returns_drift_flat = returns_drift.stack().to_frame().reset_index(names=[col_date,col_id])
    returns_drift_flat.columns=[col_date,col_id,'drift_multiplicator']

    returns_flat=df_returns.stack().to_frame().reset_index()
    returns_flat.columns=[col_date+'_shift',col_id,'Return']
    unique_date = df_merge[col_date].unique()
    df_date = pd.DataFrame(data = unique_date,columns=[col_date])
    df_date[col_date+'_shift'] = unique_date.shift(-1)
    df_merge = df_merge.merge(df_date,how='left', on =col_date)
    df_merge = df_merge[df_merge[col_date+'_shift'].notna()]

    df_merge = df_merge.merge(returns_drift_flat, how='left', on = [col_date,col_id])
    df_merge = df_merge.merge(returns_flat, how='left', on = [col_date+'_shift',col_id])
    df_merge[col_weight] = df_merge[col_weight]*df_merge['drift_multiplicator']

    columns = [col_date, col_id,col_weight, col_sector, 'Return']

    df_merge.drop(columns = 'Date',inplace=True)
    df_merge.rename(columns={col_date+'_shift': col_date},inplace=True)

    return df_merge[columns]

def calcul_rendement(portfolio_tet, col_weight, col_date='Date') :
    # Rebasage des poids à chaque date
    weight_sum_date = portfolio_tet.groupby(col_date,group_keys=False)[[col_weight]].sum()
    weight_sum_date.columns = ['Weight_sum']
    weight_sum_date.reset_index(inplace=True)

    portfolio_tet = portfolio_tet.merge(weight_sum_date, how='left', on = col_date)
    portfolio_tet['W_rebased'] = portfolio_tet[col_weight]/portfolio_tet['Weight_sum']

    # Calculer le rendement pondéré pour chaque ligne
    portfolio_tet['Contrib'] = portfolio_tet['W_rebased']*portfolio_tet['Return']

    # Calculer le rendement total du portefeuille pour chaque date
    total_return_by_date = portfolio_tet.groupby(col_date)['Contrib'].sum()
    total_return_by_date.loc[total_return_by_date.index[0]-relativedelta.relativedelta(days=1)] = 0
    total_return_by_date.sort_index(inplace=True)

    # Calculer la performance cumulée du portefeuille
    return (1 + total_return_by_date.fillna(0)).cumprod() * 100   

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

def create_ptf_weight(sec_list, indice_name, screen_agg, col_mkt_cap='Benchmark Market Value Millions in EUR', col_date = 'Date', col_sector = ' Benchmark ICB Supersector ', sector_neutral=False, method='mkt_cap', col_sedol = 'Company SEDOL', col_isin= 'ISIN'):

    indice = screen_agg.loc[screen_agg['Weight in '+indice_name]>0, [col_date, col_sedol,col_sector,'Weight in '+indice_name]].reset_index()
    indice.rename(columns={'Weight in '+indice_name:'Indice weight'}, inplace= True)

    indice.sort_values(by=col_date,inplace=True)
    sec_list.sort_values(by=col_date,inplace=True)

    indice[col_date]=indice[col_date].apply(lambda x: x + relativedelta.relativedelta(months=1,day=1))
    screen_agg[col_date]=screen_agg[col_date].apply(lambda x: x + relativedelta.relativedelta(months=1,day=1))
    sec_list[col_date]=sec_list[col_date].apply(lambda x: x + relativedelta.relativedelta(months=1,day=1))
    sec_list = sec_list.merge(right = screen_agg.reset_index()[[col_date,col_isin,col_sedol,col_sector, col_mkt_cap]], on=[col_date,col_isin], how='left')
    sec_list = sec_list[sec_list[col_sedol].notna()]
    
    if method=='EW':
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

    sec_list.set_index(col_date,inplace=True)
    sec_list['Portfolio weight'] /= sec_list.groupby(col_date)['Portfolio weight'].sum()
    sec_list.reset_index(inplace=True)
    
    return sec_list[[col_date, col_sedol,col_isin, 'Portfolio weight', col_sector]].set_index([col_date,col_sedol])

# Fonction de backtest avec en input data_predict = df_scores adapté selon nos besoins , frequence de rebalancement , dataframe des returns
def compute_perf(sec_list, df_returns, col_sector= ' Benchmark ICB Supersector ', col_id='Company SEDOL', col_date = 'Date'):

    # Dataframe final avec l'ensemble des jours (rebal + non-rebal)
    portfolio_final = calcul_all_portfolio(sec_list, df_returns, 'Portfolio weight', col_sector, col_date, col_id)
    # Affichage des rendements cumulés , rendements journaliers, poids journaliers du portefeuille
    serie_ttr = calcul_rendement(portfolio_final,'Portfolio weight',col_date)
    # Affichage de drawdown pour évaluer notre stratégie d'investissement
    #dd = calcul_drawdown(portfolio_final, col_date, 'Weighted_Return')
    return serie_ttr

def backtest(sec_list, indice_name, screen_path, df_returns_path, col_sector= ' Benchmark ICB Supersector ', col_sedol='Company SEDOL', col_isin='ISIN', col_date = 'Date', col_mkt_cap = 'Benchmark Market Value Millions in EUR', sector_neutral=False, ponderation='mkt_cap'):

    if type(screen_path)==str:
        screen_agg = pd.read_pickle(screen_path)
    else:
        screen_agg=copy.deepcopy(screen_path)

    if type(df_returns_path)==str:
        df_returns = pd.read_pickle(df_returns_path)
    else:
        df_returns=copy.deepcopy(df_returns_path)

    buy_list = copy.deepcopy(sec_list)

    sec_list_full = create_ptf_weight(buy_list, indice_name, screen_agg, col_mkt_cap, col_date, col_sector, sector_neutral, ponderation, col_sedol, col_isin)

    perf_ttr = compute_perf(sec_list_full, df_returns, col_sector, col_sedol, col_date)
    return perf_ttr, sec_list_full[[col_date,col_isin,'Portfolio weight', col_sector]]