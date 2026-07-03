import pandas as pd
import numpy as np
from dateutil import relativedelta
from multiprocessing import Pool
from math import *
import threading
from queue import Queue
import datetime
from python_calamine.pandas import pandas_monkeypatch
from datetime import datetime 
pandas_monkeypatch()

def read_returns(file_path, sheet_name, queue):
    returns = pd.read_excel(file_path, sheet_name=sheet_name, index_col=0, engine='calamine')
    queue.put(returns)
    
    
    
if __name__=="__main__" :    

    try:
        
        returns1_path=r"\\groupe-ufg.com\commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\0_RETURNS\RETURN_SAVE_1.xlsx"
        returns2_path=r"\\groupe-ufg.com\commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\0_RETURNS\RETURN_SAVE_2.xlsx"
        save_path=r"C:\GoogleDrive\TP\screen\returns.pkl"
        path_daily=r"\\groupe-ufg.com\commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\0_SCREEN_AGG\daily_screen.pkl"
        date_str = datetime.today().strftime("%Y-%m-%d")
        path_backup = r"\\groupe-ufg.com\Commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\0_SCREEN_AGG\Histo_daily_screen\daily_screen_" +date_str + ".pkl"

        queue1 = Queue()
        queue2 = Queue()

        thread1 = threading.Thread(target=read_returns, args=(returns1_path, "Returns_Global", queue1))
        thread2 = threading.Thread(target=read_returns, args=(returns2_path, "Returns_Global", queue2))

        thread1.start()
        thread2.start()

        thread1.join()
        thread2.join()

        returns1 = queue1.get()
        returns2 = queue2.get()

        returns = pd.concat([returns1,returns2],axis=1)
        returns = returns.loc[:,~returns.columns.duplicated()]

        ############################
        # Remplacer les valeurs de la derniere ligne égales a sa valeur dans l'avant dernière ligne par 0 (Pck Facset prend pas la valeur precédente si pas de valur au jour demandé)
        past_returns = pd.read_pickle(save_path)
        last_row = returns.iloc[-1]
        second_last_row = returns.iloc[-2]
        updated_last_row = last_row.where(last_row != second_last_row, 0)
        total_values = len(last_row)
        replaced_values = (updated_last_row == 0).sum()
        percentage_replaced = (replaced_values / total_values) * 100
        returns.iloc[-1] = updated_last_row

        for col in returns.columns:
            if col not in past_returns.columns:
                past_returns[col] = 0

        returns.iloc[:-1,:] = past_returns.iloc[:,:]
        ###########################

        date_return_2y = returns.index[-1] + relativedelta.relativedelta(years=-2)
        returns_2y = returns[returns.index >= date_return_2y]
        
        

        daily_weights = pd.read_pickle(path_daily)
        daily_weights = daily_weights[daily_weights['Company SEDOL'].isin(returns.columns)]
        col_drift = daily_weights.columns[1:-1]

        dates_to_add = returns[returns.index>daily_weights.index[-1]].index
        isin_to_add = daily_weights.loc[daily_weights.index==daily_weights.index[-1],'ISIN'].values
        sedol_to_add = daily_weights.loc[daily_weights.index==daily_weights.index[-1],'Company SEDOL'].values
        isin_list = np.tile(isin_to_add, len(dates_to_add))
        sedol_list = np.tile(sedol_to_add, len(dates_to_add))
        date_list = np.repeat(dates_to_add,len(isin_to_add))

        init_df = pd.DataFrame(index = date_list, columns=daily_weights.columns)
        init_df['ISIN'] = isin_list
        init_df['Company SEDOL'] = sedol_list

        init_df.loc[dates_to_add[0],col_drift] = (daily_weights.loc[daily_weights.index==daily_weights.index[-1], col_drift].multiply((1+returns.loc[daily_weights.index[-1],sedol_to_add]).values,axis=0)).values
        for i in range(1,len(dates_to_add)):
            init_df.loc[dates_to_add[i],col_drift] = (init_df.loc[init_df.index==dates_to_add[i-1], col_drift].multiply((1+returns.loc[dates_to_add[i-1],sedol_to_add]).values,axis=0)).values

        daily_weights=pd.concat([daily_weights, init_df],axis=0, ignore_index=False)
        daily_weights = daily_weights[daily_weights.index >= (daily_weights.index[-1] + relativedelta.relativedelta(years=-1))]
        
        
        while True :
            print( "Date de la derniere ligne : " + returns.index[-1].strftime("%Y-%m-%d"))
            print("Nombre de NaN : " +  str(returns.iloc[-1].isna().sum()))
            print(f"Pourcentage de rendements remplacés par 0 : {percentage_replaced:.2f}%")
            print("-------------------------------------------------------------------------------------------------")
            user_input = input("Type 'ok' to confirme :")
            if user_input.lower() == "ok":
                print("Conversion en cours")
                returns.to_pickle(save_path)
                returns_2y.to_pickle(save_path.replace('.pkl','_2Y.pkl'))
                daily_weights.to_pickle(path_daily)
                daily_weights.to_pickle(path_backup)
                print("Reussi")
                break
            else :
                print("Fichiers pas enregistrés")
    except :
        while True :
            print("-------------------------------------------------------------------------------------------------")
            user_input = input("Une erreur est survenue., type 'c' to close :")
            if user_input.lower() == "c":
                break        
    