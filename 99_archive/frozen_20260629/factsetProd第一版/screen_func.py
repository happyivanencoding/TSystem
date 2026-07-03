from pyxll import xl_macro
import pandas as pd
import datetime
from dateutil import relativedelta
# from Technicals import *

def add_icb_supersector_names(dataframe, icb_code_column=' Benchmark ICB Supersector '):
    """
    Add ICB Supersector names to a dataframe based on ICB code numbers.
    
    Parameters:
    -----------
    dataframe : pandas.DataFrame
        The dataframe containing ICB supersector codes
    icb_code_column : str, default=' Benchmark ICB Supersector '
        The name of the column containing ICB supersector codes
        
    Returns:
    --------
    pandas.DataFrame
        The dataframe with a new 'Supersector' column containing the ICB supersector names
    """
    # ICB Supersector mapping (name to code)
    icb_supersectors = {  
        "Auto & Parts": 1,  
        "Banks": 2,  
        "Basic Resources": 3,  
        "Chemicals": 4,  
        "Construction": 5,  
        "Financial Services": 6,  
        "Food, Beverage & Tobacco": 7,  
        "Health Care": 8,  
        "Industrial Goods & Services": 9,  
        "Insurance": 10,  
        "Media": 11,  
        "Energy": 12,  
        "Personal & Household Goods": 13,  
        "Real Estate": 14,  
        "Retail": 15,  
        "Technology": 16,  
        "Telecommunications": 17,  
        "Travel & Leisure": 18,  
        "Utilities": 19  
    }

    # Create a reverse mapping dictionary (code -> name)  
    icb_supersectors_reverse = {v: k for k, v in icb_supersectors.items()}  

    # Add a new column with the supersector name  
    dataframe_updated = dataframe.copy()
    dataframe_updated['Supersector'] = dataframe_updated[icb_code_column].map(icb_supersectors_reverse)
    
    return dataframe_updated


def read_screen(file, path_params="//groupe-ufg.com/commun/Prive/DIRR/Ingenierie Financiere/_Actions/ERP/12 - FACTEUR TIMING/Push factor bloom/PROD/factor to bloom generation.xlsm"):

    msg = ""
    exit = False

    df = pd.read_excel(file, header = 0, index_col = 4, skiprows=[0,1,2,3,5], na_values=["@NA", "#N/A"])
    df = df[~df.index.duplicated(keep='first')]
    df = df.loc[df.index.notna()]
    df = df.loc[(pd.isna(df['FactSet Ind']) == False)]
    
    df_mapping = pd.read_excel(path_params, sheet_name='Mapping', header = 0, na_values="@NA")
    df_mapping.rename(columns={'Benchmark ICB Supersector 19' : ' Benchmark ICB Supersector ', 'Benchmark ICB Industry 11' : ' Benchmark ICB Industry '}, inplace= True)

    df_FS_ICB = df_mapping[['FactSet Ind', 'Transco_ICB_19']]
    df_FS_ICB.rename(columns={'Transco_ICB_19' : 'ICB19'}, inplace= True)

    df_ICB_19_to_11 = df_mapping[['ICB_19_mapping', 'Transco_ICB_11']]
    df_ICB_19_to_11.rename(columns={'Transco_ICB_11' : 'ICB11'}, inplace= True)

    df_ICB_19_num = df_mapping.loc[df_mapping['ICB19_ID'].notna(),[' Benchmark ICB Supersector ','ICB19_ID']]
    df_ICB_11_num = df_mapping.loc[df_mapping['ICB11_ID'].notna(),[' Benchmark ICB Industry ','ICB11_ID']]

    if set(df[' Benchmark ICB Supersector '].astype(str)).issubset(set(df_ICB_19_num[' Benchmark ICB Supersector '].astype(str))) == False:
        msg = msg + 'ICB19 manquants : '('-'.join(map(str,tuple(set(df[' Benchmark ICB Supersector ']) - set(df_ICB_19_num[' Benchmark ICB Supersector ']))))) +'.'
        exit = True
    if set(df['FactSet Ind'].astype(str)).issubset(set(df_FS_ICB['FactSet Ind'].astype(str))) == False:
        msg = msg + 'FactSet Ind manquants : '('-'.join(map(str,tuple(set(df['FactSet Ind']) - set(df_FS_ICB['FactSet Ind']))))) +'.'
        exit = True
    if exit:
        return msg

    df = df.reset_index().merge(df_ICB_19_num, how='left', on = ' Benchmark ICB Supersector ').set_index('ISIN')
    df[' Benchmark ICB Supersector '] = df['ICB19_ID']
    df = df.reset_index().merge(df_FS_ICB, how='left', on = 'FactSet Ind').set_index('ISIN')
    df.loc[df[' Benchmark ICB Supersector '] == 0, ' Benchmark ICB Supersector '] = df.loc[df[' Benchmark ICB Supersector '] == 0, 'ICB19'].values

    df = df.reset_index().merge(df_ICB_11_num, how='left', on = ' Benchmark ICB Industry ').set_index('ISIN')
    df[' Benchmark ICB Industry '] = df['ICB11_ID']
    df = df.reset_index().merge(df_ICB_19_to_11, how='left', left_on = ' Benchmark ICB Supersector ', right_on="ICB_19_mapping").set_index('ISIN')
    df.loc[df[' Benchmark ICB Industry '] == 0, ' Benchmark ICB Industry '] = df.loc[df[' Benchmark ICB Industry '] == 0, 'ICB11'].values

    df.drop(columns = ['ICB19','ICB19_ID','ICB11','ICB11_ID','ICB_19_mapping'],inplace=True)

    df['Date'] = pd.to_datetime(df['Date'])

    return df



@xl_macro('str file, str screen_agg, str path_params, str path_daily')
def add_screen(file, screen_agg, path_params, path_daily, path_returns = r"\\groupe-ufg.com\Commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\0_RETURNS\returns_2Y.pkl"):

    old_base = pd.read_pickle(screen_agg)
    str_date = (datetime.date.today()).strftime("%Y%m%d")
    old_base.to_pickle(screen_agg.replace('screen_aggregate.pkl','backup_screen/screen_aggregate_' + str_date + '.pkl'))
    new_base = read_screen(file,path_params)
    new_base.to_pickle(screen_agg.replace('screen_aggregate','last_screen'))
    if type(new_base) == str:
        return new_base
    base_updated = pd.concat([old_base, new_base])

    ###AJOUT VARIABLES TECHNIQUES
    df_returns = pd.read_pickle(path_returns)
    # base_updated = compute_technicals(df_returns,base_updated)

    # Add ICB19 Sector Name
    # if in screen agg, ICB 19 Name is not present as Name but Number (code), use this for converting
    icb_name_create_needed = True
    if icb_name_create_needed:
        icb_supersectors = {  
            "Auto & Parts": 1,  
            "Banks": 2,  
            "Basic Resources": 3,  
            "Chemicals": 4,  
            "Construction": 5,  
            "Financial Services": 6,  
            "Food, Beverage & Tobacco": 7,  
            "Health Care": 8,  
            "Industrial Goods & Services": 9,  
            "Insurance": 10,  
            "Media": 11,  
            "Energy": 12,  
            "Personal & Household Goods": 13,  
            "Real Estate": 14,  
            "Retail": 15,  
            "Technology": 16,  
            "Telecommunications": 17,  
            "Travel & Leisure": 18,  
            "Utilities": 19  
        }

        # Create a reverse mapping dictionary (number -> name)  
        icb_supersectors_reverse = {v: k for k, v in icb_supersectors.items()}  

        # Add a new column with the supersector name  
        base_updated['Supersector'] = base_updated[' Benchmark ICB Supersector '].map(icb_supersectors_reverse)  

        # Add MF in screen
        base_updated['Multi Factors Percentile'] = base_updated[["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"]].mean(axis=1)

    ########### Save to local
    base_updated.to_pickle(screen_agg)
    # new_base.to_pickle(screen_agg)

    # 5Y screen
    date_screen_5y = base_updated['Date'].max() + relativedelta.relativedelta(years=-5)
    screen_5y = base_updated[base_updated['Date'] >= date_screen_5y]
    screen_5y.to_pickle(screen_agg.replace('.pkl','_5Y.pkl'))

    daily_weights = pd.read_pickle(path_daily)
    new_base.reset_index(inplace=True)
    new_base_wo_na = new_base.loc[(new_base['Company SEDOL'].notna())*(new_base['ISIN'].notna())]
    date_ = new_base_wo_na['Date'].iloc[0]
    daily_weights = daily_weights[daily_weights.index<date_]
    new_base_wo_na = new_base_wo_na[['Date'] + list(daily_weights.columns)].set_index('Date')

    daily_weights = pd.concat([daily_weights, new_base_wo_na],axis=0,ignore_index=False)

    daily_weights.to_pickle(path_daily)

    return "Screen aggregated successfully"