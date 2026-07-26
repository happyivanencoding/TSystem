# Standard library imports
import os
import copy
import threading
from queue import Queue
import datetime
from math import *
import warnings

# Third party imports
import pandas as pd
import numpy as np
from dateutil import relativedelta
from scipy.stats import linregress
import scipy.optimize
from tp_core.optimisation import (
    add_dev_facto as core_add_dev_facto,
    add_dev_secto as core_add_dev_secto,
    optimizer as core_optimizer,
    transform_flag_to_theme as core_transform_flag_to_theme,
    turnover as core_turnover,
)
from multiprocessing import Pool

# PyXLL specific imports
from pyxll import xl_macro, xlcAlert

# Configure warnings
warnings.filterwarnings("ignore")

@xl_macro('str file_tech, str file_fonda, str region, str output_dir, str curr_path, float percentile, float cut_mkt_cap')
def push_bloom(file_tech, file_fonda, region, output_dir, curr_path, percentile, cut_mkt_cap = 0):

    msg = ""
    exit = False
    list_score_col = ["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile", "Size Avg Percentile"]

    df_mapping = pd.read_excel(curr_path, sheet_name='Mapping', header = 0, na_values="@NA")
    df_mapping.rename(columns={'Benchmark ICB Supersector 19' : ' Benchmark ICB Supersector '}, inplace= True)
    df_FS_ICB = df_mapping[['FactSet Ind', 'Transco_ICB_19']]
    df_FS_ICB.rename(columns={'Transco_ICB_19' : 'ICB19'}, inplace= True)
    df_ICB_num = df_mapping.loc[df_mapping['ICB19_ID'].notna(),[' Benchmark ICB Supersector ','ICB19_ID']]

    df = pd.read_excel(file_tech, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])
    df = df[~df.index.duplicated(keep='first')]
    df = df.loc[df.index.notna()]
    df = df.loc[(df['Weight in MSCI ACWI'] > 0) & (pd.isna(df['FactSet Ind']) == False)]    
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    if file_tech != file_fonda:
        df2 = pd.read_excel(file_fonda, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])
        df2 = df2[~df2.index.duplicated(keep='first')]
        df2 = df2.loc[df2.index.notna()]
        df2 = df2.loc[(df2['Weight in MSCI ACWI'] > 0) & (pd.isna(df2['FactSet Ind']) == False)]
        df.drop(["Growth Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"], axis = 1, inplace=True)    
        df = pd.merge(df, df2[["Growth Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"]], how = 'left', left_index = True, right_index = True)
    
    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])
    
    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        ptf_name = [["FS_EU_GROWTH_Q1","FS_EU_GROWTH_Q5"], ["FS_EU_LOWVOL_Q1","FS_EU_LOWVOL_Q5"],["FS_EU_MOM_Q1","FS_EU_MOM_Q5"],["FS_EU_QUALITY_Q1","FS_EU_QUALITY_Q5"],
                    ["FS_EU_VALUE_Q1","FS_EU_VALUE_Q5"], ["FS_EU_SIZE_Q1","FS_EU_SIZE_Q5"],["FS_EU_MF_Q1","FS_EU_MF_Q5"]]
        mkt_cap_min = 2000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") + "/FS PORT EU RISK.xlsx"
        output_file_sec = output_dir +"/Pour " + date.strftime("%B %Y") + "/sec list EU.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        ptf_name = [["FS_US_GROWTH_Q1","FS_US_GROWTH_Q5"], ["FS_US_LOWVOL_Q1","FS_US_LOWVOL_Q5"],["FS_US_MOM_Q1","FS_US_MOM_Q5"],["FS_US_QUALITY_Q1","FS_US_QUALITY_Q5"],
                    ["FS_US_VALUE_Q1","FS_US_VALUE_Q5"],["FS_US_SIZE_Q1","FS_US_SIZE_Q5"],["FS_US_MF_Q1","FS_US_MF_Q5"]]
        mkt_cap_min = 4000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") + "/FS PORT US RISK.xlsx"
        output_file_sec = output_dir +"/Pour " + date.strftime("%B %Y") + "/sec list US.xlsx"
    elif region == 'Japan':
        df = df.loc[df["Exchange Country Name"] == 'JAPAN']
        ptf_name = [["FS_JP_GROWTH_Q1","FS_JP_GROWTH_Q5"], ["FS_JP_LOWVOL_Q1","FS_JP_LOWVOL_Q5"],["FS_JP_MOM_Q1","FS_JP_MOM_Q5"],["FS_JP_QUALITY_Q1","FS_JP_QUALITY_Q5"],
                    ["FS_JP_VALUE_Q1","FS_JP_VALUE_Q5"],["FS_JP_SIZE_Q1","FS_JP_SIZE_Q5"],["FS_JP_MF_Q1","FS_JP_MF_Q5"]]
        mkt_cap_min = 1000
        output_file = output_dir + "/Pour " + date.strftime("%B %Y") + "/FS PORT JP RISK.xlsx"
        output_file_sec = output_dir +"/Pour " + date.strftime("%B %Y") + "/sec list JP.xlsx"
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap
    if set(df[' Benchmark ICB Supersector ']).issubset(set(df_ICB_num[' Benchmark ICB Supersector '])) == False:
        msg += 'ICB19 manquants : ' + ('-'.join(map(str,tuple(set(df[' Benchmark ICB Supersector ']) - set(df_ICB_num[' Benchmark ICB Supersector ']))))) +'.'
        exit = True
    if set(df['FactSet Ind']).issubset(set(df_FS_ICB['FactSet Ind'])) == False:
        msg += 'FactSet Ind manquants : ' + ('-'.join(map(str,tuple(set(df['FactSet Ind']) - set(df_FS_ICB['FactSet Ind']))))) +'.'
        exit = True
    if exit:
        return msg

    for i in range(len(list_score_col)):
        if list_score_col[i] != "Size Avg Percentile":
            df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col[i]] = np.NaN
    
    df.loc[df['Benchmark Market Value Millions in EUR'] <= (mkt_cap_min/10), "Size Avg Percentile"] = np.NaN

    df['Multi Avg Percentile'] = df[list_score_col[:-1]].mean(skipna= False, axis=1)
    list_score_col.append("Multi Avg Percentile")

    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())
    df = df.reset_index().merge(df_ICB_num, how='left', on = ' Benchmark ICB Supersector ').set_index('ISIN')
    df[' Benchmark ICB Supersector '] = df['ICB19_ID']
    df = df.reset_index().merge(df_FS_ICB, how='left', on = 'FactSet Ind').set_index('ISIN')
    df.loc[df[' Benchmark ICB Supersector '] == 0, ' Benchmark ICB Supersector '] = df.loc[df[' Benchmark ICB Supersector '] == 0, 'ICB19'].values
    df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()

    for secto in np.unique(df[' Benchmark ICB Supersector ']):
        df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] = df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].rank(pct=True)
        df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] = (df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] - df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].min())


    columns = ['PTF', 'ISIN', 'Weight', 'Date']
    df_concat = pd.DataFrame()
    for i in range(len(list_score_col)):
        nb_securities = round(len(df.loc[pd.isna(df[list_score_col[i]]) == False])*percentile)
        df_top = df.nlargest(nb_securities,list_score_col[i])
        df_worst = df.nsmallest(nb_securities,list_score_col[i])

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_top.index
        temp_df['ICB19'] = df_top[' Benchmark ICB Supersector '].values
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_top[list_score_col[i]].values
        temp_df['PTF'] = ptf_name[i][0]
        temp_df['Date'] = date
        for secto in temp_df['ICB19'].unique():
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['ICB19'] == secto, 'Weight'].sum())
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_worst.index
        temp_df['ICB19'] = df_worst[' Benchmark ICB Supersector '].values
        temp_df['Weight'] = df_worst['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_worst[list_score_col[i]].values
        temp_df['PTF'] = ptf_name[i][1]
        temp_df['Date'] = date
        for secto in temp_df['ICB19'].unique():
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['ICB19'] == secto, 'Weight'].sum())
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

    if file_tech != file_fonda:
        df_concat_push = df_concat.loc[(df_concat['PTF'] != ptf_name[0][0]) & (df_concat['PTF'] != ptf_name[0][1]) & (df_concat['PTF'] != ptf_name[4][0]) & 
                                    (df_concat['PTF'] != ptf_name[4][1])& (df_concat['PTF'] != ptf_name[3][0]) & (df_concat['PTF'] != ptf_name[3][1])]
    else:
        df_concat_push = df_concat

    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       df_concat_push[columns].to_excel(writer,index = False)

    with pd.ExcelWriter(output_file_sec,datetime_format = 'dd/mm/yyyy') as writer:
       df_concat[columns].to_excel(writer,index = False)

    return msg


@xl_macro('str file_tech, str file_fonda, str region, str output_dir, str curr_path, float percentile, float cut_mkt_cap, int[] reco_secto')
def push_mf_tilt_bloom(file_tech, file_fonda, region, output_dir, curr_path, percentile, cut_mkt_cap = 0,
                        reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], reco_facto = [0,0,0,0,0]):

    msg = ""
    exit = False
    list_score_col = ["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile", "Size Avg Percentile"]

    df_mapping = pd.read_excel(curr_path, sheet_name='Mapping', header = 0, na_values="@NA")
    df_mapping.rename(columns={'Benchmark ICB Supersector 19' : ' Benchmark ICB Supersector '}, inplace= True)
    df_FS_ICB = df_mapping[['FactSet Ind', 'Transco_ICB_19']]
    df_FS_ICB.rename(columns={'Transco_ICB_19' : 'ICB19'}, inplace= True)
    df_ICB_num = df_mapping.loc[df_mapping['ICB19_ID'].notna(),[' Benchmark ICB Supersector ','ICB19_ID']]

    df = pd.read_excel(file_tech, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])
    df = df[~df.index.duplicated(keep='first')]
    df = df.loc[df.index.notna()]
    df = df.loc[(df['Weight in MSCI ACWI'] > 0) & (pd.isna(df['FactSet Ind']) == False)]    
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    if file_tech != file_fonda:
        df2 = pd.read_excel(file_fonda, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])
        df2 = df2[~df2.index.duplicated(keep='first')]
        df2 = df2.loc[df2.index.notna()]
        df2 = df2.loc[(df2['Weight in MSCI ACWI'] > 0) & (pd.isna(df2['FactSet Ind']) == False)]
        df.drop(["Growth Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"], axis = 1, inplace=True)    
        df = pd.merge(df, df2[["Growth Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"]], how = 'left', left_index = True, right_index = True)
    
    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])
    
    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        ptf_name = [["FS_EU_MF_Q1_TS","FS_EU_MF_Q5_TS"], ["FS_EU_MF_Q1_TF","FS_EU_MF_Q5_TF"], ["FS_EU_MF_Q1_TSF","FS_EU_MF_Q5_TSF"]]
        mkt_cap_min = 2000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") + "/FS PORT EU RISK tilt.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        ptf_name = [["FS_US_MF_Q1_TS","FS_US_MF_Q5_TS"], ["FS_US_MF_Q1_TF","FS_US_MF_Q5_TF"], ["FS_US_MF_Q1_TSF","FS_US_MF_Q5_TSF"]]
        mkt_cap_min = 4000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") + "/FS PORT US RISK tilt.xlsx"
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap
    if set(df[' Benchmark ICB Supersector ']).issubset(set(df_ICB_num[' Benchmark ICB Supersector '])) == False:
        msg += 'ICB19 manquants : ' + ('-'.join(map(str,tuple(set(df[' Benchmark ICB Supersector ']) - set(df_ICB_num[' Benchmark ICB Supersector ']))))) +'.'
        exit = True
    if set(df['FactSet Ind']).issubset(set(df_FS_ICB['FactSet Ind'])) == False:
        msg += 'FactSet Ind manquants : ' + ('-'.join(map(str,tuple(set(df['FactSet Ind']) - set(df_FS_ICB['FactSet Ind']))))) +'.'
        exit = True
    if exit:
        return msg

    for i in range(len(list_score_col)):
        if list_score_col[i] != "Size Avg Percentile":
            df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col[i]] = np.NaN
    
    df.loc[df['Benchmark Market Value Millions in EUR'] <= (mkt_cap_min/10), "Size Avg Percentile"] = np.NaN

    df['Multi Avg Percentile Tilt'] = df[list_score_col[:-1]].dot(reco_facto)
    list_score_col.append("Multi Avg Percentile Tilt")

    df['Multi Avg Percentile'] = df[list_score_col[:-2]].mean(skipna= False, axis=1)
    list_score_col.append("Multi Avg Percentile")

    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())
    df = df.reset_index().merge(df_ICB_num, how='left', on = ' Benchmark ICB Supersector ').set_index('ISIN')
    df[' Benchmark ICB Supersector '] = df['ICB19_ID']
    df = df.reset_index().merge(df_FS_ICB, how='left', on = 'FactSet Ind').set_index('ISIN')
    df.loc[df[' Benchmark ICB Supersector '] == 0, ' Benchmark ICB Supersector '] = df.loc[df[' Benchmark ICB Supersector '] == 0, 'ICB19'].values
    df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
    weight_secto_bench_dev = add_dev_secto(weight_secto_bench, reco_secto)

    for secto in np.unique(df[' Benchmark ICB Supersector ']):
        df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] = df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].rank(pct=True)
        df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] = (df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] - df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].min())
        df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile Tilt'] = df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile Tilt'].rank(pct=True)
        df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile Tilt'] = (df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile Tilt'] - df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile Tilt'].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile Tilt'].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile Tilt'].min())

    columns = ['PTF', 'ISIN', 'Weight', 'Date']
    df_concat = pd.DataFrame()
    list_score_col=["Multi Avg Percentile", "Multi Avg Percentile Tilt", "Multi Avg Percentile Tilt"]
    for i in range(len(list_score_col)):
        nb_securities = round(len(df.loc[pd.isna(df[list_score_col[i]]) == False])*percentile)
        df_top = df.nlargest(nb_securities,list_score_col[i])
        df_worst = df.nsmallest(nb_securities,list_score_col[i])

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_top.index
        temp_df['ICB19'] = df_top[' Benchmark ICB Supersector '].values
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_top[list_score_col[i]].values
        temp_df['PTF'] = ptf_name[i][0]
        temp_df['Date'] = date
        for secto in temp_df['ICB19'].unique():
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] / temp_df['Weight'].sum()
            if i == 1:
                temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['ICB19'] == secto, 'Weight'].sum())
            else:
                temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] * (weight_secto_bench_dev.loc[secto] / temp_df.loc[temp_df['ICB19'] == secto, 'Weight'].sum())
        
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_worst.index
        temp_df['ICB19'] = df_worst[' Benchmark ICB Supersector '].values
        temp_df['Weight'] = df_worst['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_worst[list_score_col[i]].values
        temp_df['PTF'] = ptf_name[i][1]
        temp_df['Date'] = date
        for secto in temp_df['ICB19'].unique():
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['ICB19'] == secto, 'Weight'].sum())
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       df_concat[columns].to_excel(writer,index = False)

    return df_concat[columns]


@xl_macro('str file_tech, str file_fonda, str region, str output_dir, str curr_path, float percentile, float cut_mkt_cap, int[] reco_secto, int[] reco_facto')
def push_mf_tilt_bloom_new(file_tech, file_fonda, region, output_dir, curr_path, percentile, old_ptf, cut_mkt_cap = 0,
                        reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], reco_facto = [0,0,0,0,0]):

    msg = ""
    exit = False
    list_score_col = ["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile", "Size Avg Percentile"]

    df_mapping = pd.read_excel(curr_path, sheet_name='Mapping', header = 0, na_values="@NA")
    df_mapping.rename(columns={'Benchmark ICB Supersector 19' : ' Benchmark ICB Supersector '}, inplace= True)
    df_FS_ICB = df_mapping[['FactSet Ind', 'Transco_ICB_19']]
    df_FS_ICB.rename(columns={'Transco_ICB_19' : 'ICB19'}, inplace= True)
    df_ICB_num = df_mapping.loc[df_mapping['ICB19_ID'].notna(),[' Benchmark ICB Supersector ','ICB19_ID']]

    df = pd.read_excel(file_tech, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])
    df = df[~df.index.duplicated(keep='first')]
    df = df.loc[df.index.notna()]
    df = df.loc[(df['Weight in MSCI ACWI'] > 0) & (pd.isna(df['FactSet Ind']) == False)]    
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    if file_tech != file_fonda:
        df2 = pd.read_excel(file_fonda, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])
        df2 = df2[~df2.index.duplicated(keep='first')]
        df2 = df2.loc[df2.index.notna()]
        df2 = df2.loc[(df2['Weight in MSCI ACWI'] > 0) & (pd.isna(df2['FactSet Ind']) == False)]
        df.drop(["Growth Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"], axis = 1, inplace=True)    
        df = pd.merge(df, df2[["Growth Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"]], how = 'left', left_index = True, right_index = True)
    
    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])
    
    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        ptf_name = [["FS_EU_MF_Q1_TSF2","FS_EU_MF_Q5_TSF2"]]
        mkt_cap_min = 2000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") + "/FS PORT EU RISK tilt.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        ptf_name = [["FS_US_MF_Q1_TSF","FS_US_MF_Q5_TSF"]]
        mkt_cap_min = 4000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") + "/FS PORT US RISK tilt.xlsx"
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap
    if set(df[' Benchmark ICB Supersector ']).issubset(set(df_ICB_num[' Benchmark ICB Supersector '])) == False:
        msg += 'ICB19 manquants : ' + ('-'.join(map(str,tuple(set(df[' Benchmark ICB Supersector ']) - set(df_ICB_num[' Benchmark ICB Supersector ']))))) +'.'
        exit = True
    if set(df['FactSet Ind']).issubset(set(df_FS_ICB['FactSet Ind'])) == False:
        msg += 'FactSet Ind manquants : ' + ('-'.join(map(str,tuple(set(df['FactSet Ind']) - set(df_FS_ICB['FactSet Ind']))))) +'.'
        exit = True
    if exit:
        return msg

    for i in range(len(list_score_col)):
        if list_score_col[i] != "Size Avg Percentile":
            df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col[i]] = np.NaN
    
    df.loc[df['Benchmark Market Value Millions in EUR'] <= (mkt_cap_min/10), "Size Avg Percentile"] = np.NaN

    df['Multi Avg Percentile'] = df[list_score_col[:-1]].mean(skipna= False, axis=1)
    list_score_col.append("Multi Avg Percentile")

    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())
    df = df.reset_index().merge(df_ICB_num, how='left', on = ' Benchmark ICB Supersector ').set_index('ISIN')
    df[' Benchmark ICB Supersector '] = df['ICB19_ID']
    df = df.reset_index().merge(df_FS_ICB, how='left', on = 'FactSet Ind').set_index('ISIN')
    df.loc[df[' Benchmark ICB Supersector '] == 0, ' Benchmark ICB Supersector '] = df.loc[df[' Benchmark ICB Supersector '] == 0, 'ICB19'].values
    df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
    #weight_secto_bench_dev = add_dev_secto(weight_secto_bench, reco_secto)

    for secto in np.unique(df[' Benchmark ICB Supersector ']):
        df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] = df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].rank(pct=True)
        df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] = (df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] - df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].min())

    columns = ['PTF', 'ISIN', 'Weight', 'Date', 'Success', 'Poids secto base', 'Poids secto modif', 'Poids facto base', 'Poids facto modif', 'Turnover']
    #df_concat = pd.DataFrame()
    list_score_col=["Multi Avg Percentile"]
    for i in range(len(list_score_col)):
        nb_securities = round(len(df.loc[pd.isna(df[list_score_col[i]]) == False])*percentile)
        df_top = df.nlargest(nb_securities,list_score_col[i])

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_top.index
        temp_df['ICB19'] = df_top[' Benchmark ICB Supersector '].values
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_top[list_score_col[i]].values

        temp_df['PTF'] = ptf_name[i][0]
        temp_df['Date'] = date
        for secto in temp_df['ICB19'].unique():
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['ICB19'] == secto, 'Weight'].sum())

        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        temp_df['Success'] = 1

        if np.sum(reco_facto) != 0 or np.sum(reco_secto) != 0: # or type(old_ptf) != str
            temp_df[["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"]] = df_top[["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"]].values
            temp_df[["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]] = 0
            
            temp_df.loc[temp_df["Growth Avg Percentile"] >= 0.8, "Growth Flag"] = 1
            temp_df.loc[temp_df["LowVol Avg Percentile"] >= 0.8, "LowVol Flag"] = 1
            temp_df.loc[temp_df["Mom Avg Percentile"] >= 0.8, "Mom Flag"] = 1
            temp_df.loc[temp_df["Quality Avg Percentile"] >= 0.8, "Quality Flag"] = 1
            temp_df.loc[temp_df["Value Avg Percentile"] >= 0.8, "Value Flag"] = 1
            theme_facto = np.concatenate((transform_flag_to_theme(temp_df['Growth Flag'],True),transform_flag_to_theme(temp_df['LowVol Flag'],True),transform_flag_to_theme(temp_df['Mom Flag'],True),
                                            transform_flag_to_theme(temp_df['Quality Flag'],True),transform_flag_to_theme(temp_df['Value Flag'],True)),axis=0)
            theme_secto = transform_flag_to_theme(temp_df['ICB19'])
            icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(temp_df['ICB19'].unique())
            lb = [temp_df['Weight'].min()]*len(temp_df)
            ub = [temp_df['Weight'].max()]*len(temp_df)
            nb_titres = np.array([len(temp_df[temp_df['ICB19'] == i]) for i in range(1,20)])
            max_secto = nb_titres*ub[0]
            min_secto = nb_titres*lb[0]
            if len(icb_missing) == 0:
                weight_ref_optim = copy.deepcopy(weight_secto_bench)
                ub_secto = copy.deepcopy(max_secto)
                lb_secto = copy.deepcopy(min_secto)
            else:
                for icb19 in icb_missing:
                    if int(icb19) in weight_secto_bench.index:
                        weight_ref_optim = weight_secto_bench.drop([int(icb19)])
                    else:
                        weight_ref_optim = copy.deepcopy(weight_secto_bench)
                    ub_secto = np.delete(max_secto, int(icb19) - 1)
                    lb_secto = np.delete(min_secto, int(icb19) - 1)
                    del reco_secto[int(icb19) - 1]

            x0 = temp_df['Weight'].values
            #x0 = [1/len(temp_df)]*len(temp_df)
            A = np.concatenate((theme_facto, theme_secto, theme_facto*(-1), theme_secto*(-1)), axis=0)
            eq_cons_sum = np.array([1])
            old_weight = temp_df['Weight'].values
            facto_repart = temp_df['Weight'].dot(temp_df[["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]])
            weight_min_secto, weight_max_secto = add_dev_secto(weight_ref_optim, reco_secto, ub_secto, lb_secto)
            weight_min_facto, weight_max_facto = add_dev_facto(facto_repart, reco_facto)
            ineq = np.concatenate((weight_min_facto, weight_min_secto, weight_max_facto*(-1), weight_max_secto*(-1)), axis=0)

            i = 1
            weights, success, obj = optimizer(turnover, x0, A, eq_cons_sum, ineq, ub, lb, old_weight)
            while success == False and i<40 and np.prod(A @ weights - ineq >= 0)==0:
                i+=1
                weight_min_facto[weight_min_facto>0.01] -= 0.01
                weight_max_facto[weight_max_facto<0.99] += 0.01
                ineq = np.concatenate((weight_min_facto, weight_min_secto, weight_max_facto*(-1), weight_max_secto*(-1)), axis=0)
                weights, success, obj = optimizer(turnover, x0, A, eq_cons_sum, ineq, ub, lb, old_weight)

            temp_df['Weight'] = weights
            temp_df['Success'] = i
            temp_df['Poids secto base'] = [(weight_ref_optim.values).tolist()]*len(temp_df)
            temp_df['Poids secto modif'] = [((temp_df.groupby('ICB19')['Weight'].sum()).values).tolist()]*len(temp_df)
            temp_df['Poids facto base'] = [(facto_repart.values).tolist()]*len(temp_df)
            temp_df['Poids facto modif'] = [((temp_df['Weight'].dot(temp_df[["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]])).values).tolist()]*len(temp_df)
            temp_df['Turnover'] = [[obj]]*len(temp_df)

        #df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

    #with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       #df_concat[columns].to_excel(writer,index = False)

    return temp_df[columns]


@xl_macro('str file_tech, str file_fonda, str region, str output_dir, str curr_path, float percentile, float cut_mkt_cap, float turnover_cons, int[] reco_secto, int[] reco_facto')
def push_mf_tilt_bloom_turnover(file_tech, file_fonda, region, output_dir, curr_path, percentile,turnover_cons = 0.4, cut_mkt_cap = 0,
                        reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], reco_facto = [0,0,0,0,0]):

    msg = ""
    exit = False
    list_score_col = ["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile", "Size Avg Percentile"]

    df_mapping = pd.read_excel(curr_path, sheet_name='Mapping', header = 0, na_values="@NA")
    df_mapping.rename(columns={'Benchmark ICB Supersector 19' : ' Benchmark ICB Supersector '}, inplace= True)
    df_FS_ICB = df_mapping[['FactSet Ind', 'Transco_ICB_19']]
    df_FS_ICB.rename(columns={'Transco_ICB_19' : 'ICB19'}, inplace= True)
    df_ICB_num = df_mapping.loc[df_mapping['ICB19_ID'].notna(),[' Benchmark ICB Supersector ','ICB19_ID']]

    df = pd.read_excel(file_tech, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])
    df = df[~df.index.duplicated(keep='first')]
    df = df.loc[df.index.notna()]
    df = df.loc[(df['Weight in MSCI ACWI'] > 0) & (pd.isna(df['FactSet Ind']) == False)]    
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    if file_tech != file_fonda:
        df2 = pd.read_excel(file_fonda, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])
        df2 = df2[~df2.index.duplicated(keep='first')]
        df2 = df2.loc[df2.index.notna()]
        df2 = df2.loc[(df2['Weight in MSCI ACWI'] > 0) & (pd.isna(df2['FactSet Ind']) == False)]
        df.drop(["Growth Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"], axis = 1, inplace=True)    
        df = pd.merge(df, df2[["Growth Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"]], how = 'left', left_index = True, right_index = True)
    
    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])
    
    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        ptf_name = [["FS_EU_MF_Q1_TSF","FS_EU_MF_Q5_TSF"]]
        mkt_cap_min = 2000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") + "/FS PORT EU RISK tilt.xlsx"
        old_ptf = pd.read_excel(output_dir +"/Pour " + (date - relativedelta.relativedelta(months=1)).strftime("%B %Y") + "/FS PORT EU RISK tilt.xlsx")
        nb_titres_max = 80
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        ptf_name = [["FS_US_MF_Q1_TSF","FS_US_MF_Q5_TSF"]]
        mkt_cap_min = 4000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") + "/FS PORT US RISK tilt.xlsx"
        #old_ptf = pd.read_excel(output_dir +"/Pour " + (date - relativedelta.relativedelta(months=1)).strftime("%B %Y") + "/FS PORT US RISK tilt.xlsx")
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap
    if set(df[' Benchmark ICB Supersector ']).issubset(set(df_ICB_num[' Benchmark ICB Supersector '])) == False:
        msg += 'ICB19 manquants : ' + ('-'.join(map(str,tuple(set(df[' Benchmark ICB Supersector ']) - set(df_ICB_num[' Benchmark ICB Supersector ']))))) +'.'
        exit = True
    if set(df['FactSet Ind']).issubset(set(df_FS_ICB['FactSet Ind'])) == False:
        msg += 'FactSet Ind manquants : ' + ('-'.join(map(str,tuple(set(df['FactSet Ind']) - set(df_FS_ICB['FactSet Ind']))))) +'.'
        exit = True
    if exit:
        return msg

    for i in range(len(list_score_col)):
        if list_score_col[i] != "Size Avg Percentile":
            df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col[i]] = np.NaN
    
    df.loc[df['Benchmark Market Value Millions in EUR'] <= (mkt_cap_min/10), "Size Avg Percentile"] = np.NaN

    df['Multi Avg Percentile'] = df[list_score_col[:-1]].mean(skipna= False, axis=1)
    list_score_col.append("Multi Avg Percentile")

    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())
    df = df.reset_index().merge(df_ICB_num, how='left', on = ' Benchmark ICB Supersector ').set_index('ISIN')
    df[' Benchmark ICB Supersector '] = df['ICB19_ID']
    df = df.reset_index().merge(df_FS_ICB, how='left', on = 'FactSet Ind').set_index('ISIN')
    df.loc[df[' Benchmark ICB Supersector '] == 0, ' Benchmark ICB Supersector '] = df.loc[df[' Benchmark ICB Supersector '] == 0, 'ICB19'].values
    df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
    #weight_secto_bench_dev = add_dev_secto(weight_secto_bench, reco_secto)

    for secto in np.unique(df[' Benchmark ICB Supersector ']):
        df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] = df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].rank(pct=True)
        df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] = (df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] - df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].min())

    columns = ['PTF', 'ISIN', 'Weight', 'Date', 'Success', 'Turnover','Nb titres','Poids secto base', 'Poids secto modif','Poids facto base','Poids facto modif']
    df_concat = pd.DataFrame()
    list_score_col=["Multi Avg Percentile"]
    for i in range(len(list_score_col)):
        nb_securities = round(len(df.loc[pd.isna(df[list_score_col[i]]) == False])*percentile)
        df_top = df.nlargest(nb_securities,list_score_col[i])

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_top.index
        temp_df['ICB19'] = df_top[' Benchmark ICB Supersector '].values
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_top[list_score_col[i]].values

        temp_df['PTF'] = ptf_name[i][0]
        temp_df['Date'] = date
        for secto in temp_df['ICB19'].unique():
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['ICB19'] == secto, 'Weight'].sum())

        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        temp_df['Success'] = 1

        if np.sum(reco_facto) != 0 or np.sum(reco_secto) != 0 or type(old_ptf) != str:

            old_isin = set(old_ptf['ISIN'].values)
            new_isin = set(temp_df['ISIN'].values)
            sec_list = old_ptf[['ISIN', 'Weight']].set_index('ISIN')
            sec_list = pd.concat([sec_list, pd.DataFrame([0]*len(new_isin-old_isin),index=list(new_isin-old_isin),columns=["Weight"])])
            sec_list['Weight optim'] = temp_df[['ISIN', 'Weight']].set_index('ISIN')
            sec_list.loc[sec_list["Weight optim"].isna(), "Weight optim"] = 0
            sec_list = pd.merge(sec_list,df[["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile",list_score_col[i],' Benchmark ICB Supersector ']],how = 'left', left_index=True, right_index=True)
            temp_df = sec_list.rename(columns={' Benchmark ICB Supersector ':'ICB19'})
            temp_df = temp_df[temp_df['ICB19'].notna()]
            temp_df = temp_df[temp_df[list_score_col[i]].notna()]
            temp_df = temp_df.nlargest(min(nb_titres_max,len(temp_df)),list_score_col[i])
            temp_df['PTF'] = ptf_name[i][0]
            temp_df['Date'] = date
            old_weight = temp_df['Weight'].values

            temp_df[["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]] = 0
            
            temp_df.loc[temp_df["Growth Avg Percentile"] >= 0.8, "Growth Flag"] = 1
            temp_df.loc[temp_df["LowVol Avg Percentile"] >= 0.8, "LowVol Flag"] = 1
            temp_df.loc[temp_df["Mom Avg Percentile"] >= 0.8, "Mom Flag"] = 1
            temp_df.loc[temp_df["Quality Avg Percentile"] >= 0.8, "Quality Flag"] = 1
            temp_df.loc[temp_df["Value Avg Percentile"] >= 0.8, "Value Flag"] = 1
            theme_facto = np.concatenate((transform_flag_to_theme(temp_df['Growth Flag'],True),transform_flag_to_theme(temp_df['LowVol Flag'],True),transform_flag_to_theme(temp_df['Mom Flag'],True),
                                            transform_flag_to_theme(temp_df['Quality Flag'],True),transform_flag_to_theme(temp_df['Value Flag'],True)),axis=0)
            theme_secto = transform_flag_to_theme(temp_df['ICB19'])
            icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(temp_df['ICB19'].unique())
            lb = [0.001]*len(temp_df)
            ub = [temp_df['Weight optim'].max()]*len(temp_df)
            nb_titres = np.array([len(temp_df[temp_df['ICB19'] == i]) for i in range(1,20)])
            max_secto = nb_titres*ub[0]
            min_secto = nb_titres*lb[0]
            if len(icb_missing) == 0:
                weight_ref_optim = copy.deepcopy(weight_secto_bench)
                ub_secto = copy.deepcopy(max_secto)
                lb_secto = copy.deepcopy(min_secto)
            else:
                for icb19 in icb_missing:
                    if int(icb19) in weight_secto_bench.index:
                        weight_ref_optim = weight_secto_bench.drop([int(icb19)])
                    else:
                        weight_ref_optim = copy.deepcopy(weight_secto_bench)
                    ub_secto = np.delete(max_secto, int(icb19) - 1)
                    lb_secto = np.delete(min_secto, int(icb19) - 1)
                    del reco_secto[int(icb19) - 1]

            x0 = temp_df['Weight'].values
            #x0 = [1/len(temp_df)]*len(temp_df)
            A = np.concatenate((theme_facto, theme_secto, theme_facto*(-1), theme_secto*(-1)), axis=0)
            """ A = np.concatenate((theme_facto, theme_secto), axis=0)
            tolerance = 0.00001
            eq_cons_sum = [1-tolerance, 1+tolerance] """
            eq_cons_sum = [1]
            facto_repart = temp_df['Weight'].dot(temp_df[["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]])
            weight_min_secto, weight_max_secto = add_dev_secto(weight_ref_optim, reco_secto, ub_secto, lb_secto)
            weight_min_facto, weight_max_facto = add_dev_facto(facto_repart, reco_facto)
            ineq = np.concatenate((weight_min_facto, weight_min_secto, weight_max_facto*(-1), weight_max_secto*(-1)), axis=0)
            """ ineq_min = np.concatenate((weight_min_facto, weight_min_secto), axis=0)
            ineq_max = np.concatenate((weight_max_facto, weight_max_secto), axis=0)
            ineq = [ineq_min, ineq_max] """

            j = 1
            #weights, success, turnov, constr_violation = optim_quad(max_score, x0, A, eq_cons_sum, ineq, ub, lb, old_weight,turnover_cons,temp_df[list_score_col[i]].values)
            weights, success, turnov = optimizer(max_score, x0, A, eq_cons_sum, ineq, ub, lb, old_weight,turnover_cons,temp_df[list_score_col[i]].values)
            while success == False and j<40 : #constr_violation>0.00001
                j+=1
                if j>=16:
                    weight_min_facto[weight_min_facto>0.01] -= 0.01
                    weight_max_facto[weight_max_facto<0.99] += 0.01
                turnover_cons=min(turnover_cons+0.025,1)
                """ ineq_min = np.concatenate((weight_min_facto, weight_min_secto), axis=0)
                ineq_max = np.concatenate((weight_max_facto, weight_max_secto), axis=0)
                ineq = [ineq_min, ineq_max] """
                ineq = np.concatenate((weight_min_facto, weight_min_secto, weight_max_facto*(-1), weight_max_secto*(-1)), axis=0)
                #weights, success, turnov, constr_violation = optim_quad(max_score, x0, A, eq_cons_sum, ineq, ub, lb, old_weight,turnover_cons,temp_df[list_score_col[i]].values)
                weights, success, turnov = optimizer(max_score, x0, A, eq_cons_sum, ineq, ub, lb, old_weight,turnover_cons,temp_df[list_score_col[i]].values)

            temp_df['Weight'] = weights
            temp_df['Success'] = j
            temp_df['Poids secto base'] = [(weight_ref_optim.values).tolist()]*len(temp_df)
            temp_df['Poids secto modif'] = [((temp_df.groupby('ICB19')['Weight'].sum()).values).tolist()]*len(temp_df)
            temp_df['Poids facto base'] = [(facto_repart.values).tolist()]*len(temp_df)
            temp_df['Poids facto modif'] = [((temp_df['Weight'].dot(temp_df[["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]])).values).tolist()]*len(temp_df)
            temp_df['Turnover'] = turnov
            temp_df = temp_df[temp_df['Weight']>0]
            temp_df['Nb titres'] = len(temp_df)
            temp_df.reset_index(names='ISIN',inplace=True)

        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       df_concat[columns].to_excel(writer,index = False)

    return turnov


@xl_macro('str file_tech, str file_fonda, str region, str output_dir, str curr_path, float percentile, float cut_mkt_cap, float turnover_cons, int[] reco_secto, int[] reco_facto')
def push_mf_tilt_bloom_turnover(file_tech, file_fonda, region, output_dir, curr_path, percentile,esg_cut,liste_noire,ponderation, turnover_cons = 0.4, cut_mkt_cap = 0,
                        reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], reco_facto = [0,0,0,0,0]):

    msg = ""
    exit = False
    list_score_col = ["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile", "Size Avg Percentile"]

    df_mapping = pd.read_excel(curr_path, sheet_name='Mapping', header = 0, na_values="@NA")
    df_mapping.rename(columns={'Benchmark ICB Supersector 19' : ' Benchmark ICB Supersector '}, inplace= True)
    df_FS_ICB = df_mapping[['FactSet Ind', 'Transco_ICB_19']]
    df_FS_ICB.rename(columns={'Transco_ICB_19' : 'ICB19'}, inplace= True)
    df_ICB_num = df_mapping.loc[df_mapping['ICB19_ID'].notna(),[' Benchmark ICB Supersector ','ICB19_ID']]

    df = pd.read_excel(file_tech, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])
    df = df[~df.index.duplicated(keep='first')]
    df = df.loc[df.index.notna()]
    df = df.loc[(df['Weight in MSCI ACWI'] > 0) & (pd.isna(df['FactSet Ind']) == False)]    
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    if file_tech != file_fonda:
        df2 = pd.read_excel(file_fonda, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])
        df2 = df2[~df2.index.duplicated(keep='first')]
        df2 = df2.loc[df2.index.notna()]
        df2 = df2.loc[(df2['Weight in MSCI ACWI'] > 0) & (pd.isna(df2['FactSet Ind']) == False)]
        df.drop(["Growth Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"], axis = 1, inplace=True)    
        df = pd.merge(df, df2[["Growth Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"]], how = 'left', left_index = True, right_index = True)
    
    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])
    
    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        ptf_name = [["FS_EU_MF_Q1_TSF","FS_EU_MF_Q5_TSF"]]
        mkt_cap_min = 2000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") + "/FS PORT EU RISK tilt.xlsx"
        old_ptf = pd.read_excel(output_dir +"/Pour " + (date - relativedelta.relativedelta(months=1)).strftime("%B %Y") + "/FS PORT EU RISK tilt.xlsx")
        nb_titres_max = 80
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        ptf_name = [["FS_US_MF_Q1_TSF","FS_US_MF_Q5_TSF"]]
        mkt_cap_min = 4000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") + "/FS PORT US RISK tilt.xlsx"
        #old_ptf = pd.read_excel(output_dir +"/Pour " + (date - relativedelta.relativedelta(months=1)).strftime("%B %Y") + "/FS PORT US RISK tilt.xlsx")
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap
    if set(df[' Benchmark ICB Supersector ']).issubset(set(df_ICB_num[' Benchmark ICB Supersector '])) == False:
        msg += 'ICB19 manquants : ' + ('-'.join(map(str,tuple(set(df[' Benchmark ICB Supersector ']) - set(df_ICB_num[' Benchmark ICB Supersector ']))))) +'.'
        exit = True
    if set(df['FactSet Ind']).issubset(set(df_FS_ICB['FactSet Ind'])) == False:
        msg += 'FactSet Ind manquants : ' + ('-'.join(map(str,tuple(set(df['FactSet Ind']) - set(df_FS_ICB['FactSet Ind']))))) +'.'
        exit = True
    if exit:
        return msg

    for i in range(len(list_score_col)):
        if list_score_col[i] != "Size Avg Percentile":
            df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col[i]] = np.NaN
    
    df.loc[df['Benchmark Market Value Millions in EUR'] <= (mkt_cap_min/10), "Size Avg Percentile"] = np.NaN

    df['Multi Avg Percentile'] = df[list_score_col[:-1]].mean(skipna= False, axis=1)
    list_score_col.append("Multi Avg Percentile")

    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())
    df = df.reset_index().merge(df_ICB_num, how='left', on = ' Benchmark ICB Supersector ').set_index('ISIN')
    df[' Benchmark ICB Supersector '] = df['ICB19_ID']
    df = df.reset_index().merge(df_FS_ICB, how='left', on = 'FactSet Ind').set_index('ISIN')
    df.loc[df[' Benchmark ICB Supersector '] == 0, ' Benchmark ICB Supersector '] = df.loc[df[' Benchmark ICB Supersector '] == 0, 'ICB19'].values
    df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
    #weight_secto_bench_dev = add_dev_secto(weight_secto_bench, reco_secto)

    for secto in np.unique(df[' Benchmark ICB Supersector ']):
        df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] = df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].rank(pct=True)
        df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] = (df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'] - df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, 'Multi Avg Percentile'].min())

    columns = ['PTF', 'ISIN', 'Weight', 'Date', 'Success', 'Turnover','Nb titres','Poids secto base', 'Poids secto modif','Poids facto base','Poids facto modif']
    df_concat = pd.DataFrame()
    list_score_col=["Multi Avg Percentile"]
    for i in range(len(list_score_col)):
        nb_securities = round(len(df.loc[pd.isna(df[list_score_col[i]]) == False])*percentile)
        df_top = df.nlargest(nb_securities,list_score_col[i])

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_top.index
        temp_df['ICB19'] = df_top[' Benchmark ICB Supersector '].values
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_top[list_score_col[i]].values

        temp_df['PTF'] = ptf_name[i][0]
        temp_df['Date'] = date
        for secto in temp_df['ICB19'].unique():
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['ICB19'] == secto, 'Weight'].sum())

        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        temp_df['Success'] = 1

        if np.sum(reco_facto) != 0 or np.sum(reco_secto) != 0 or type(old_ptf) != str:

            old_isin = set(old_ptf['ISIN'].values)
            new_isin = set(temp_df['ISIN'].values)
            sec_list = old_ptf[['ISIN', 'Weight']].set_index('ISIN')
            sec_list = pd.concat([sec_list, pd.DataFrame([0]*len(new_isin-old_isin),index=list(new_isin-old_isin),columns=["Weight"])])
            sec_list['Weight optim'] = temp_df[['ISIN', 'Weight']].set_index('ISIN')
            sec_list.loc[sec_list["Weight optim"].isna(), "Weight optim"] = 0
            sec_list = pd.merge(sec_list,df[["Growth Avg Percentile", "LowVol Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile",list_score_col[i],' Benchmark ICB Supersector ']],how = 'left', left_index=True, right_index=True)
            temp_df = sec_list.rename(columns={' Benchmark ICB Supersector ':'ICB19'})
            temp_df = temp_df[temp_df['ICB19'].notna()]
            temp_df = temp_df[temp_df[list_score_col[i]].notna()]
            temp_df = temp_df.nlargest(min(nb_titres_max,len(temp_df)),list_score_col[i])
            temp_df['PTF'] = ptf_name[i][0]
            temp_df['Date'] = date
            old_weight = temp_df['Weight'].values

            temp_df[["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]] = 0
            
            temp_df.loc[temp_df["Growth Avg Percentile"] >= 0.8, "Growth Flag"] = 1
            temp_df.loc[temp_df["LowVol Avg Percentile"] >= 0.8, "LowVol Flag"] = 1
            temp_df.loc[temp_df["Mom Avg Percentile"] >= 0.8, "Mom Flag"] = 1
            temp_df.loc[temp_df["Quality Avg Percentile"] >= 0.8, "Quality Flag"] = 1
            temp_df.loc[temp_df["Value Avg Percentile"] >= 0.8, "Value Flag"] = 1
            theme_facto = np.concatenate((transform_flag_to_theme(temp_df['Growth Flag'],True),transform_flag_to_theme(temp_df['LowVol Flag'],True),transform_flag_to_theme(temp_df['Mom Flag'],True),
                                            transform_flag_to_theme(temp_df['Quality Flag'],True),transform_flag_to_theme(temp_df['Value Flag'],True)),axis=0)
            theme_secto = transform_flag_to_theme(temp_df['ICB19'])
            icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(temp_df['ICB19'].unique())
            lb = [0.001]*len(temp_df)
            ub = [temp_df['Weight optim'].max()]*len(temp_df)
            nb_titres = np.array([len(temp_df[temp_df['ICB19'] == i]) for i in range(1,20)])
            max_secto = nb_titres*ub[0]
            min_secto = nb_titres*lb[0]
            if len(icb_missing) == 0:
                weight_ref_optim = copy.deepcopy(weight_secto_bench)
                ub_secto = copy.deepcopy(max_secto)
                lb_secto = copy.deepcopy(min_secto)
            else:
                for icb19 in icb_missing:
                    if int(icb19) in weight_secto_bench.index:
                        weight_ref_optim = weight_secto_bench.drop([int(icb19)])
                    else:
                        weight_ref_optim = copy.deepcopy(weight_secto_bench)
                    ub_secto = np.delete(max_secto, int(icb19) - 1)
                    lb_secto = np.delete(min_secto, int(icb19) - 1)
                    del reco_secto[int(icb19) - 1]

            x0 = temp_df['Weight'].values
            #x0 = [1/len(temp_df)]*len(temp_df)
            A = np.concatenate((theme_facto, theme_secto, theme_facto*(-1), theme_secto*(-1)), axis=0)
            """ A = np.concatenate((theme_facto, theme_secto), axis=0)
            tolerance = 0.00001
            eq_cons_sum = [1-tolerance, 1+tolerance] """
            eq_cons_sum = [1]
            facto_repart = temp_df['Weight'].dot(temp_df[["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]])
            weight_min_secto, weight_max_secto = add_dev_secto(weight_ref_optim, reco_secto, ub_secto, lb_secto)
            weight_min_facto, weight_max_facto = add_dev_facto(facto_repart, reco_facto)
            ineq = np.concatenate((weight_min_facto, weight_min_secto, weight_max_facto*(-1), weight_max_secto*(-1)), axis=0)
            """ ineq_min = np.concatenate((weight_min_facto, weight_min_secto), axis=0)
            ineq_max = np.concatenate((weight_max_facto, weight_max_secto), axis=0)
            ineq = [ineq_min, ineq_max] """

            j = 1
            #weights, success, turnov, constr_violation = optim_quad(max_score, x0, A, eq_cons_sum, ineq, ub, lb, old_weight,turnover_cons,temp_df[list_score_col[i]].values)
            weights, success, turnov = optimizer(max_score, x0, A, eq_cons_sum, ineq, ub, lb, old_weight,turnover_cons,temp_df[list_score_col[i]].values)
            while success == False and j<40 : #constr_violation>0.00001
                j+=1
                if j>=16:
                    weight_min_facto[weight_min_facto>0.01] -= 0.01
                    weight_max_facto[weight_max_facto<0.99] += 0.01
                turnover_cons=min(turnover_cons+0.025,1)
                """ ineq_min = np.concatenate((weight_min_facto, weight_min_secto), axis=0)
                ineq_max = np.concatenate((weight_max_facto, weight_max_secto), axis=0)
                ineq = [ineq_min, ineq_max] """
                ineq = np.concatenate((weight_min_facto, weight_min_secto, weight_max_facto*(-1), weight_max_secto*(-1)), axis=0)
                #weights, success, turnov, constr_violation = optim_quad(max_score, x0, A, eq_cons_sum, ineq, ub, lb, old_weight,turnover_cons,temp_df[list_score_col[i]].values)
                weights, success, turnov = optimizer(max_score, x0, A, eq_cons_sum, ineq, ub, lb, old_weight,turnover_cons,temp_df[list_score_col[i]].values)

            temp_df['Weight'] = weights
            temp_df['Success'] = j
            temp_df['Poids secto base'] = [(weight_ref_optim.values).tolist()]*len(temp_df)
            temp_df['Poids secto modif'] = [((temp_df.groupby('ICB19')['Weight'].sum()).values).tolist()]*len(temp_df)
            temp_df['Poids facto base'] = [(facto_repart.values).tolist()]*len(temp_df)
            temp_df['Poids facto modif'] = [((temp_df['Weight'].dot(temp_df[["Growth Flag", "LowVol Flag", "Mom Flag", "Quality Flag", "Value Flag"]])).values).tolist()]*len(temp_df)
            temp_df['Turnover'] = turnov
            temp_df = temp_df[temp_df['Weight']>0]
            temp_df['Nb titres'] = len(temp_df)
            temp_df.reset_index(names='ISIN',inplace=True)

        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       df_concat[columns].to_excel(writer,index = False)

    return turnov


def turnover(x, old_weight):
    return core_turnover(x, old_weight)


def turnover_cons(x, old_weight, ineq_turnover):
    return -(turnover(x, old_weight) - ineq_turnover)


def transform_flag_to_theme(flag, bool_column=False, list_flag="No"):
    return core_transform_flag_to_theme(flag, bool_column=bool_column, list_flag=list_flag)


def optimizer(fun, x0, A, eqb, ineqb, ub, lb, old_weight, ineq_turnover, *args):
    return core_optimizer(fun, x0, A, eqb, ineqb, ub, lb, old_weight, ineq_turnover, *args)


def max_score(x, score):
    return -x.dot(score)


def add_dev_secto(weight, reco, max_secto, min_secto, abs=0.05, relatif=0.2, normalize=True):
    return core_add_dev_secto(
        weight,
        reco,
        max_secto,
        min_secto,
        abs_shift=abs,
        relatif=relatif,
        normalize=normalize,
    )


def add_dev_facto(weight, reco, min_abs=0.5, min_relatif=0.15):
    return core_add_dev_facto(weight, reco, min_abs=min_abs, min_relatif=min_relatif)


@xl_macro('str[] filelist, str region, str output_dir, str curr_path, float percentile, float[] cut_mkt_cap, int[][] reco_secto, float[][] reco_facto')
def push_bloom_all_tilt(filelist, region, output_dir, curr_path, percentile, cut_mkt_cap, reco_secto, reco_facto):

    output_file = output_dir + "/factor_list_histo_80_titres_2.xlsx"
    df = pd.DataFrame()
    for i in range(0,len(filelist),3):
        if i == 0:
            df = pd.concat([df,push_mf_tilt_bloom_turnover(filelist[i], filelist[i], region, output_dir, curr_path, percentile, "none", cut_mkt_cap[i], reco_secto[i], reco_facto[i])], ignore_index=True)
        else:
            prev_df = df[df['Date'] == df['Date'].iloc[-1]]
            df = pd.concat([df,push_mf_tilt_bloom_turnover(filelist[i], filelist[i], region, output_dir, curr_path, percentile, prev_df, cut_mkt_cap[i], reco_secto[i], reco_facto[i])], ignore_index=True)
        if i+1 < len(filelist):
            prev_df = df[df['Date'] == df['Date'].iloc[-1]]
            df = pd.concat([df,push_mf_tilt_bloom_turnover(filelist[i + 1], filelist[i], region, output_dir, curr_path, percentile, prev_df, cut_mkt_cap[i + 1], reco_secto[i + 1], reco_facto[i + 1])], ignore_index=True)
        if i+2 < len(filelist):
            prev_df = df[df['Date'] == df['Date'].iloc[-1]]
            df = pd.concat([df,push_mf_tilt_bloom_turnover(filelist[i + 2], filelist[i], region, output_dir, curr_path, percentile, prev_df, cut_mkt_cap[i + 2], reco_secto[i + 2], reco_facto[i + 2])], ignore_index=True)
        if i == 90 or i==150 or i ==192:
            df.to_pickle(output_dir + "save.pkl")

    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       df.to_excel(writer,index = False)
    return df


def turnover_portfolio(ptf, ptf1, list_isin, id_col = "ISIN", weight_col = "Weight"):

    ptf2 = pd.DataFrame(columns=[id_col,weight_col])
    ptf2[id_col] = list_isin
    ptf2[weight_col] = ptf
    ptf_old = ptf1.rename(columns = {weight_col:'old_weight'})
    merged_df = pd.merge(left=ptf2, right=ptf_old[[id_col, 'old_weight']], on = id_col, how='left')
    merged_df.loc[merged_df['old_weight'].isna(), 'old_weight'] = 0
    isin_missing = set(ptf1[id_col]) - set(ptf2[id_col])
    ptf_old = ptf_old.set_index(id_col)

    return np.abs(merged_df[weight_col] - merged_df['old_weight']).sum() + ptf_old.loc[isin_missing, 'old_weight'].sum()


@xl_macro('str file_tech, str region, str output_dir, str curr_path, float percentile, float cut_mkt_cap')
def push_bloom_worst_mom(file_tech, region, output_dir, curr_path, percentile, cut_mkt_cap = 0):

    msg = ""
    exit = False
    list_score_col = "Mom Avg Percentile"

    df_mapping = pd.read_excel(curr_path, sheet_name='Mapping', header = 0, na_values="@NA")
    df_mapping.rename(columns={'Benchmark ICB Supersector 19' : ' Benchmark ICB Supersector '}, inplace= True)
    df_FS_ICB = df_mapping[['FactSet Ind', 'Transco_ICB_19']]
    df_FS_ICB.rename(columns={'Transco_ICB_19' : 'ICB19'}, inplace= True)
    df_ICB_num = df_mapping.loc[df_mapping['ICB19_ID'].notna(),[' Benchmark ICB Supersector ','ICB19_ID']]

    df = pd.read_excel(file_tech, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])
    df = df[~df.index.duplicated(keep='first')]
    df = df.loc[df.index.notna()]
    df = df.loc[(df['Weight in MSCI ACWI'] > 0) & (pd.isna(df['FactSet Ind']) == False)]    
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)
    
    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])
    
    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        ptf_name = "Worst_Mom_EU"
        mkt_cap_min = 2000
        output_file_sec = output_dir +"/Pour " + date.strftime("%B %Y") + "/sec list EU.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        ptf_name = "Worst_Mom_US"
        mkt_cap_min = 4000
        output_file_sec = output_dir +"/Pour " + date.strftime("%B %Y") + "/sec list US.xlsx"
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap
    if set(df[' Benchmark ICB Supersector ']).issubset(set(df_ICB_num[' Benchmark ICB Supersector '])) == False:
        msg += 'ICB19 manquants : ' + ('-'.join(map(str,tuple(set(df[' Benchmark ICB Supersector ']) - set(df_ICB_num[' Benchmark ICB Supersector ']))))) +'.'
        exit = True
    if set(df['FactSet Ind']).issubset(set(df_FS_ICB['FactSet Ind'])) == False:
        msg += 'FactSet Ind manquants : ' + ('-'.join(map(str,tuple(set(df['FactSet Ind']) - set(df_FS_ICB['FactSet Ind']))))) +'.'
        exit = True
    if exit:
        return msg

    df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col] = np.NaN
    
    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    #df[list_score_col] = df[list_score_col].rank(pct=True)
    #df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())
    df = df.reset_index().merge(df_ICB_num, how='left', on = ' Benchmark ICB Supersector ').set_index('ISIN')
    df[' Benchmark ICB Supersector '] = df['ICB19_ID']
    df = df.reset_index().merge(df_FS_ICB, how='left', on = 'FactSet Ind').set_index('ISIN')
    df.loc[df[' Benchmark ICB Supersector '] == 0, ' Benchmark ICB Supersector '] = df.loc[df[' Benchmark ICB Supersector '] == 0, 'ICB19'].values
    df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()

    for secto in np.unique(df[' Benchmark ICB Supersector ']):
        df.loc[df[' Benchmark ICB Supersector '] == secto, "Total Return"] = df.loc[df[' Benchmark ICB Supersector '] == secto, "Total Return"].rank(pct=True)
        df.loc[df[' Benchmark ICB Supersector '] == secto, "Total Return"] = (df.loc[df[' Benchmark ICB Supersector '] == secto, "Total Return"] - df.loc[df[' Benchmark ICB Supersector '] == secto, "Total Return"].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, "Total Return"].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, "Total Return"].min())

    columns = ['PTF', 'ISIN', 'Weight', 'Date', 'ICB19']
    df_concat = pd.DataFrame()
    nb_securities = round(len(df.loc[pd.isna(df[list_score_col]) == False])*percentile)
    df = df[df["Total Return"] <= 0.95]
    #df_top = df.nlargest(nb_securities,list_score_col[i])
    df_worst = df.nlargest(nb_securities,list_score_col)

    """ temp_df = pd.DataFrame(columns = columns)
    temp_df['ISIN'] = df_top.index
    temp_df['ICB19'] = df_top[' Benchmark ICB Supersector '].values
    temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
    temp_df['Score'] = df_top[list_score_col[i]].values
    temp_df['PTF'] = ptf_name[i][0]
    temp_df['Date'] = date
    for secto in temp_df['ICB19'].unique():
        temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] / temp_df['Weight'].sum()
        temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['ICB19'] == secto, 'Weight'].sum())
    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
    df_concat = pd.concat([df_concat,temp_df], ignore_index=True) """

    temp_df = pd.DataFrame(columns = columns)
    temp_df['ISIN'] = df_worst.index
    temp_df['ICB19'] = df_worst[' Benchmark ICB Supersector '].values
    temp_df['Weight'] = df_worst['Benchmark Market Value Millions in EUR'].values
    temp_df['Score'] = df_worst[list_score_col].values
    temp_df['PTF'] = ptf_name
    temp_df['Date'] = date
    for secto in temp_df['ICB19'].unique():
        temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] / temp_df['Weight'].sum()
        temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['ICB19'] == secto, 'Weight'].sum())
    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
    df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

    #with pd.ExcelWriter(output_file_sec,datetime_format = 'dd/mm/yyyy') as writer:
    #   df_concat[columns].to_excel(writer,index = False)

    return df_concat[columns]

@xl_macro('str screen_file, str region, str output_dir, str curr_path, float percentile, float[] cut_mkt_cap, float cut_esg, str liste_noire,str ponderation, str rebal, float turnover_cons,int[][] reco_secto')
def push_bloom_all_tilt_1(screen_file, region, output_dir, curr_path, percentile, cut_mkt_cap, cut_esg,liste_noire,ponderation,rebal,turnov_cons,reco_secto):

    #file_fonda = np.concatenate([[filelist[i]]*3 for i in range(0,len(filelist),3)]).tolist()
    #file_fonda = file_fonda[:len(filelist)]
    all_screen = pd.read_pickle(screen_file)
    liste_noire = read_liste_noire([],[], liste_noire)

    start_date=pd.to_datetime(start_date)
    end_date=pd.to_datetime(end_date)
    all_screen = all_screen.loc[(all_screen['Date'] >= start_date) & (all_screen['Date'] <= end_date)]
    all_screen = all_screen[all_screen['Weight in MSCI ACWI'] >0]
    unique_dates = all_screen['Date'].unique()
    cut_mkt_cap = cut_mkt_cap[len(cut_mkt_cap) - len(unique_dates):]
    if rebal == "Monthly":
        screen_list = [all_screen.loc[all_screen['Date'] == date_] for date_ in unique_dates]
        cut_mkt_cap_list = cut_mkt_cap
    elif rebal == "Quarterly":
        screen_list = [all_screen.loc[all_screen['Date'] == unique_dates[i]] for i in range(0,len(unique_dates),3)]
        cut_mkt_cap_list = [cut_mkt_cap[i] for i in range(0,len(cut_mkt_cap),3)]

    region_list = [region]*len(screen_list)
    output_dir_list = [output_dir]*len(screen_list)
    curr_path_list = [curr_path]*len(screen_list)
    percentile_list = [percentile]*len(screen_list)
    ponderation_list = [ponderation]*len(screen_list)
    liste_noire_list = [liste_noire]*len(screen_list)
    esg_cut_list= [cut_esg]*len(screen_list)
    turnov_cons_list= [turnov_cons]*len(screen_list)

    parameters = np.array([screen_list, region_list, output_dir_list, curr_path_list, percentile_list,esg_cut_list,liste_noire_list,ponderation_list,turnov_cons_list,
                            cut_mkt_cap_list,reco_secto], dtype=object)
    parameters = np.array(parameters).transpose()

    output_file = output_dir + "/factor_list_mom_exclusion.xlsx"
    with Pool(20) as p:
        result = p.starmap(push_bloom_worst_mom, [params for params in parameters])

    df = pd.concat(result, ignore_index=True)
    #list_date = df['Date'].unique()
    """ for i in range(len(list_date)):
        if i == 0:
            df.loc[df['Date'] == list_date[i], 'Monthly turnover'] = 0
        else:
            df.loc[df['Date'] == list_date[i], 'Monthly turnover'] = turnover_portfolio(df[df['Date'] == list_date[i-1]], df[df['Date'] == list_date[i]]) """
    
    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       df.to_excel(writer,index = False)
    return 0


@xl_macro('str file, str region, str output_dir, str curr_path')
def get_bench_weight(file, region, output_dir, curr_path):

    df_mapping = pd.read_excel(curr_path, sheet_name='Mapping', header = 0, na_values="@NA")
    df_mapping.rename(columns={'Benchmark ICB Supersector 19' : ' Benchmark ICB Supersector '}, inplace= True)
    df_FS_ICB = df_mapping[['FactSet Ind', 'Transco_ICB_19']]
    df_FS_ICB.rename(columns={'Transco_ICB_19' : 'ICB19'}, inplace= True)
    df_ICB_num = df_mapping.loc[df_mapping['ICB19_ID'].notna(),[' Benchmark ICB Supersector ','ICB19_ID']]

    df = pd.read_excel(file, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])
    df = df[~df.index.duplicated(keep='first')]
    df = df.loc[df.index.notna()]
    df = df.loc[(df['Weight in MSCI ACWI'] > 0) & (pd.isna(df['FactSet Ind']) == False)] 
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)
    
    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])

    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        output_file = output_dir + "/Bench EU.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        output_file = output_dir +"/Bench US.xlsx"
    elif region == 'Japan':
        df = df.loc[df["Exchange Country Name"] == 'JAPAN']
        output_file = output_dir + "/Bench JP.xlsx"

    df = df.reset_index().merge(df_ICB_num, how='left', on = ' Benchmark ICB Supersector ').set_index('ISIN')
    df[' Benchmark ICB Supersector '] = df['ICB19_ID']
    df = df.reset_index().merge(df_FS_ICB, how='left', on = 'FactSet Ind').set_index('ISIN')
    df.loc[df[' Benchmark ICB Supersector '] == 0, ' Benchmark ICB Supersector '] = df.loc[df[' Benchmark ICB Supersector '] == 0, 'ICB19'].values
    weight_secto_bench = (df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum())

    header = ['Automobiles & Parts', 'Banks', 'Basic Resources', 'Chemicals', 'Construction & Materials', 'Financial Services', 'Food & Beverage', 'Health Care',
            'Industrial Goods & Services', 'Insurance', 'Media', 'Energy', 'Personal & Household Goods', 'Real Estate', 'Retail', 'Technology', 'Telecommunications',
            'Travel & Leisure', 'Utilities']
    return_df = weight_secto_bench.reset_index()
    return_df['Weight in MSCI ACWI'] = weight_secto_bench.values
    return_df.columns = [' Benchmark ICB Supersector ', date]
    return_df = return_df.set_index(return_df[' Benchmark ICB Supersector '].values.reshape(-1))[date].to_frame().transpose()
    return_df.columns = header

    old_bench = pd.read_excel(output_file, index_col=0, header = 0)
    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy', date_format = 'dd/mm/yyyy') as writer:
        pd.concat([old_bench, return_df]).to_excel(writer,index = True)

    return 0


@xl_macro('str file, str output_dir, str curr_path')
def maj_all_bench(file, output_dir, curr_path):

    null = get_bench_weight(file, 'Europe', output_dir, curr_path)
    null = get_bench_weight(file, 'US', output_dir, curr_path)
    null = get_bench_weight(file, 'Japan', output_dir, curr_path)
    
    return 'Bench sectors weight updated successfully'


@xl_macro('str file_tech, str file_fonda, str output_dir, str curr_path, float percentile')
def push_bloom_eu_usjp(file_tech, file_fonda, output_dir, curr_path, percentile):

    null = push_bloom(file_tech, file_fonda,'Europe', output_dir, curr_path, percentile)
    null += push_bloom(file_tech, file_fonda,'US', output_dir, curr_path, percentile)
    null += push_bloom(file_tech, file_fonda,'Japan', output_dir, curr_path, percentile)
    df = pd.read_excel(file_tech, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values="@NA")
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)
    us = pd.read_excel(output_dir +"/Pour " + date.strftime("%B %Y") + "/FS PORT US RISK.xlsx")
    jp = pd.read_excel(output_dir + "/Pour " + date.strftime("%B %Y") + "/FS PORT JP RISK.xlsx")
    us_jp = pd.concat([us,jp], axis = 0)
    with pd.ExcelWriter(output_dir + "/Pour " + date.strftime("%B %Y") + "/FS PORT US JP Benoit.xlsx",datetime_format = 'dd/mm/yyyy') as writer:
        us_jp.to_excel(writer,index = False)
    return null


@xl_macro('str[] filelist, str region, str output_dir, str curr_path, float percentile, float[] cut_mkt_cap')
def push_bloom_all(filelist, region, output_dir, curr_path, percentile, cut_mkt_cap):

    output_file = output_dir + "/factor_list_histo_us.xlsx"
    df = pd.DataFrame()
    for i in range(0,len(filelist),3):
        df = pd.concat([df,push_bloom(filelist[i], filelist[i], region, output_dir, curr_path, percentile, cut_mkt_cap[i])], ignore_index=True)
        if i+1 < len(filelist):
            df = pd.concat([df,push_bloom(filelist[i + 1], filelist[i], region, output_dir, curr_path, percentile, cut_mkt_cap[i + 1])], ignore_index=True)
        if i+2 < len(filelist):
            df = pd.concat([df,push_bloom(filelist[i + 2], filelist[i], region, output_dir, curr_path, percentile, cut_mkt_cap[i + 2])], ignore_index=True)

    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       df.to_excel(writer,index = False)
    return 0


def sec_list_spot_thematic(screen, region, output_dir, percentile, cut_mkt_cap, metrics,thematics, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire):

    list_style = ['Value Avg Percentile','Quality Avg Percentile','Mom Avg Percentile','LowVol Avg Percentile','Growth Avg Percentile']

    df = screen
    esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])

    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        mkt_cap_min = 2000
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        mkt_cap_min = 4000
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap

    df['Multi Avg Percentile'] = df[list_style].mean(skipna= False, axis=1)
    df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, thematics] = np.NaN
    #list_score_col.append("Multi Avg Percentile")

    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    elif ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    elif ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    elif ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)

    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
        """ icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
        if len(icb_missing) > 0:
            for icb19 in icb_missing:
                reco_secto = np.delete(np.array(reco_secto),int(icb19) - 1)
        weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1.5)
        weight_secto_bench[weight_secto_bench<0.0025] = 0.0025 """

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
    if metrics[0] != 'None':
        df[metrics] = df[metrics].rank(pct=True)
        df[metrics] = (df[metrics] - df[metrics].min())/(df[metrics].max() - df[metrics].min())

    #df.loc[df[' Benchmark ICB Industry '] == 'Financials', ["Ebitda_margin_FY1, Ebitda_margin_FY1_chg_3M","Ebitda_margin_FY1_chg_6M","Ebitda_margin_FY1_chg_12M"]] = df[["Net_margin_FY1", "Net_margin_FY1_chg_3M","Net_margin_FY1_chg_6M","Net_margin_FY1_chg_12M"]]

    if metrics[0] != 'None':
        if score_neutral == "ICB 11":
            for secto in df[' Benchmark ICB Industry '].unique():
                df.loc[df[' Benchmark ICB Industry '] == secto, metrics] = df.loc[df[' Benchmark ICB Industry '] == secto, metrics].rank(pct=True)
                df.loc[df[' Benchmark ICB Industry '] == secto, metrics] = (df.loc[df[' Benchmark ICB Industry '] == secto, metrics] - df.loc[df[' Benchmark ICB Industry '] == secto, metrics].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, metrics].max() - df.loc[df[' Benchmark ICB Industry '] == secto, metrics].min())
        elif weight_neutral == "ICB 19":
            for secto in df[' Benchmark ICB Supersector '].unique():
                df.loc[df[' Benchmark ICB Supersector '] == secto, metrics] = df.loc[df[' Benchmark ICB Supersector '] == secto, metrics].rank(pct=True)
                df.loc[df[' Benchmark ICB Supersector '] == secto, metrics] = (df.loc[df[' Benchmark ICB Supersector '] == secto, metrics] - df.loc[df[' Benchmark ICB Supersector '] == secto, metrics].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, metrics].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, metrics].min())

    # nb_securities = round(len(df.loc[pd.isna(df['Multi Avg Percentile']) == False])*(0.8))
    # df=df.nlargest(nb_securities,'Multi Avg Percentile')

    df_esg = copy.deepcopy(df)
    if date.year >= 2014:
        #esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        if esg_exclusion > 0:
                df_esg = df.loc[esg_pct >= esg_exclusion]
        df_esg = df_esg[~(df_esg.index.isin(liste_noire))]
        #df_esg = df.loc[esg_pct <= esg_exclusion]
        # df_esg = pd.concat([df_esg, df[df.index.isin(liste_noire)]], axis=0)
        # df_esg = df_esg[~df_esg.index.duplicated(keep='first')]
        #df_esg = df_esg[(df_esg.index.isin(liste_noire))]

    #df_esg[list_score_col] = df_esg.groupby(' Benchmark ICB Supersector ')[list_score_col].rank(pct=True)

    columns = ['PTF', 'ISIN', 'Weight', 'Date']
    df_concat = pd.DataFrame()
    for i in range(len(thematics)):
        df_thematic = df_esg[df_esg[thematics[i]] == 1]
        if metrics[0] != 'None':
            nb_securities = round(len(df_thematic.loc[pd.isna(df_thematic[metrics]) == False])*percentile)
            df_thematic = df_thematic.nlargest(nb_securities,metrics)
        # if date.year >= 2014:
        #     df_top = pd.concat([df_top,df_esg], axis= 0)
        #     df_top = df_top[~df_top.index.duplicated(keep='first')]
        #     df_top = df_top[df_top['Benchmark Market Value Millions in EUR'].notna()]
        #df_worst = df.nsmallest(nb_securities,list_score_col[i])

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_thematic.index
        temp_df['Name'] = df_thematic['Name'].values
        if weight_neutral == "ICB 19":
            temp_df['Secto'] = df_thematic[' Benchmark ICB Supersector '].values
        elif weight_neutral == "ICB 11":
            temp_df['Secto'] = df_thematic[' Benchmark ICB Industry '].values
        temp_df['Weight'] = df_thematic['Benchmark Market Value Millions in EUR'].values
        if metrics[0] != 'None':
            temp_df['Score'] = df_thematic[metrics].values
        temp_df['PTF'] = ptf_name[i]
        temp_df['Date'] = date
        
        if weight_neutral != "No":
            for secto in temp_df['Secto'].unique():
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

        """ temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_worst.index
        temp_df['ICB19'] = df_worst[' Benchmark ICB Supersector '].values
        temp_df['Weight'] = df_worst['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_worst[list_score_col[i]].values
        temp_df['PTF'] = ptf_name[i][1]
        temp_df['Date'] = date
        for secto in temp_df['ICB19'].unique():
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['ICB19'] == secto, 'Weight'].sum())
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True) """

    #with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #   df_concat[columns].to_excel(writer,index = False)

    return df_concat


@xl_macro('str screen_agg, str region, str output_dir, float percentile, float[] cut_mkt_cap, str[] metrics, str[] thematics, str[] ptf_name, str score_neutral, str weight_neutral, str ponderation, str[] liste_noire, float esg_cut, str start_date, str end_date, str rebal')
def sec_list_histo_thematic(screen_path, region, output_dir, percentile, cut_mkt_cap, metrics, thematics, ptf_name, score_neutral, weight_neutral, ponderation,liste_noire,esg_cut, start_date=datetime.date(2004,12,31), end_date=datetime.date.today(), rebal= "Monthly"):

    all_screen = pd.read_pickle(screen_path)

    start_date=pd.to_datetime(start_date)
    end_date=pd.to_datetime(end_date)
    all_screen = all_screen.loc[(all_screen['Date'] >= start_date) & (all_screen['Date'] <= end_date)]
    all_screen = all_screen[all_screen['Weight in MSCI ACWI'] >0]
    unique_dates = all_screen['Date'].unique()
    cut_mkt_cap = cut_mkt_cap[len(cut_mkt_cap) - len(unique_dates):]
    if liste_noire[0] == 'Yes':
        liste_noire = read_liste_noire([],[], liste_noire[1])
    else:
        liste_noire = []

    if rebal == "Monthly":
        screen_list = [all_screen.loc[all_screen['Date'] == date_] for date_ in unique_dates]
        cut_mkt_cap_list = cut_mkt_cap
    elif rebal == "Quarterly":
        screen_list = [all_screen.loc[all_screen['Date'] == unique_dates[i]] for i in range(0,len(unique_dates),3)]
        cut_mkt_cap_list = [cut_mkt_cap[i] for i in range(0,len(cut_mkt_cap),3)]

    region_list = [region]*len(screen_list)
    output_dir_list = [output_dir]*len(screen_list)
    percentile_list = [percentile]*len(screen_list)
    metrics_list = [metrics]*len(screen_list)
    thematics_list = [thematics]*len(screen_list)
    ptf_name_list = [ptf_name]*len(screen_list)
    score_neutral_list = [score_neutral]*len(screen_list)
    weight_neutral_list = [weight_neutral]*len(screen_list)
    ponderation_list = [ponderation]*len(screen_list)
    liste_noire_list = [liste_noire]*len(screen_list)
    esg_cut_list= [esg_cut]*len(screen_list)

    parameters = np.array([screen_list, region_list, output_dir_list, percentile_list, cut_mkt_cap_list, metrics_list,thematics_list,ptf_name_list,
                           score_neutral_list,weight_neutral_list, ponderation_list,esg_cut_list,liste_noire_list], dtype=object)
    parameters = np.array(parameters).transpose()

    output_file = output_dir + "/output_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + ".xlsx"
    with Pool(20) as p:
        result = p.starmap(sec_list_spot_thematic, [params for params in parameters])

    df = pd.concat(result, ignore_index=True)
    
    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       df.to_excel(writer,index = False)
       
    return "Sec list generated successfully in " + output_file

@xl_macro('str screen, str region, str output_dir, str curr_path, float percentile, float cut_mkt_cap, str metrics, str score_neutral, str weight_neutral, str ponderation, float esg_exclusion, str liste_noire')
def worst_esg_basket(screen, region, output_dir, curr_path, percentile, cut_mkt_cap, metrics, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire):

    list_score_col = metrics
    list_style = ['Quality Avg Percentile','LowVol Avg Percentile','Growth Avg Percentile']

    if type(screen) == str:
        df = read_screen(screen,curr_path)
    else:
        df = screen
    if type(liste_noire) == str:
        liste_noire = read_liste_noire([],[],liste_noire)

    df = df[df['Weight in MSCI ACWI'] > 0]
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])

    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        mkt_cap_min = 2000
        output_file = output_dir+"/Pour " + date.strftime("%B %Y") +"/Worst ESG Europe.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        mkt_cap_min = 4000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") +"/Worst ESG US.xlsx"
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap

    df['Multi Avg Percentile'] = df[list_style].dot([0.4,0.4,0.2])

    df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col] = np.NaN
    #list_score_col.append("Multi Avg Percentile")

    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    elif ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    elif ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    elif ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)

    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())

    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())

    df_esg = copy.deepcopy(df)
    esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
    df_esg = df.loc[esg_pct <= esg_exclusion]

    columns = ['PTF', 'ISIN', 'Weight', 'Date']

    nb_securities = round(len(df.loc[pd.isna(df[list_score_col]) == False])*percentile)
    df_top = df.nsmallest(nb_securities,list_score_col)
    df_top = df_top[(df_top.index.isin(liste_noire))|(df_top.index.isin(list(df_esg.index)))]

    temp_df = pd.DataFrame(columns = columns)
    temp_df['ISIN'] = df_top.index
    if weight_neutral == "ICB 19":
        temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
    elif weight_neutral == "ICB 11":
        temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
    temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
    temp_df['Score'] = df_top[list_score_col].values
    temp_df['PTF'] = "Worst_ESG_Basket"
    temp_df['Date'] = date
    
    if weight_neutral != "No":
        for secto in temp_df['Secto'].unique():
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()

    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       temp_df[columns].to_excel(writer,index = False)

    return "worst esg basket generated successfully in " + output_file

@xl_macro('str screen, str region, str output_dir, str curr_path, float percentile, float cut_mkt_cap, str metrics, str score_neutral, str weight_neutral, str ponderation, float esg_exclusion, str liste_noire')
def top_esg_basket(screen, region, output_dir, curr_path, percentile, cut_mkt_cap, metrics, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire):

    list_score_col = metrics
    list_style = ['Value Avg Percentile','Quality Avg Percentile','Mom Avg Percentile','LowVol Avg Percentile','Growth Avg Percentile']

    if type(screen) == str:
        df = read_screen(screen,curr_path)
    else:
        df = screen
    if type(liste_noire) == str:
        liste_noire = read_liste_noire([],[],liste_noire)

    df = df[df['Weight in MSCI ACWI'] > 0]
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])

    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        mkt_cap_min = 2000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") +"/MF ESG Europe.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        mkt_cap_min = 4000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y") +"/MF ESG US.xlsx"
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap

    df['Multi Avg Percentile'] = df[list_style].mean(skipna= False, axis=1)

    df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col] = np.NaN
    #list_score_col.append("Multi Avg Percentile")

    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    elif ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    elif ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    elif ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)

    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())

    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())

    df_esg = copy.deepcopy(df)
    esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
    if esg_exclusion > 1:
        df_esg = df[df['ESG_ANALYST_SCORE'] >= esg_exclusion]
    else:
        df_esg = df.loc[esg_pct >= esg_exclusion]
    df_esg = df_esg[~(df_esg.index.isin(liste_noire))]

    columns = ['PTF', 'ISIN', 'Weight', 'Date']
    nb_securities = round(len(df_esg.loc[pd.isna(df_esg[list_score_col]) == False])*percentile)
    df_top = df_esg.nlargest(nb_securities,list_score_col)

    temp_df = pd.DataFrame(columns = columns)
    temp_df['ISIN'] = df_top.index
    if weight_neutral == "ICB 19":
        temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
    elif weight_neutral == "ICB 11":
        temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
    temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
    temp_df['Score'] = df_top[list_score_col].values
    temp_df['PTF'] = 'MF_Q1_ESG_EU'
    temp_df['Date'] = date
    
    if weight_neutral != "No":
        for secto in temp_df['Secto'].unique():
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()

    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       temp_df[columns].to_excel(writer,index = False)

    return "top esg basket generated successfully in " + output_file

@xl_macro('str screen, str region, str output_dir, str curr_path, float percentile, float cut_mkt_cap, str metrics, str score_neutral, str weight_neutral, str ponderation, float esg_exclusion, str liste_noire, float[] reco_secto')
def ptf_dev_secto(screen, region, output_dir, curr_path, percentile, cut_mkt_cap, metrics, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire,
                  reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]):

    list_score_col = metrics
    list_style = ['Value Avg Percentile','Quality Avg Percentile','Mom Avg Percentile','LowVol Avg Percentile','Growth Avg Percentile']

    if type(screen) == str:
        df = read_screen(screen,curr_path)
    else:
        df = screen
    if type(liste_noire) == str:
        liste_noire = read_liste_noire([],[],liste_noire)

    df = df[df['Weight in MSCI ACWI'] > 0]
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])

    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        mkt_cap_min = 2000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y")+"/PTF_Dev_Secto_EU.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        mkt_cap_min = 4000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y")+"/TF_Dev_Secto_US.xlsx"
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap

    esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
    df['Multi Avg Percentile'] = df[list_style].mean(skipna= False, axis=1)

    df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col] = np.NaN
    #list_score_col.append("Multi Avg Percentile")

    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    elif ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    elif ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    elif ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)

    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
        icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
        if len(icb_missing) > 0:
            for icb19 in icb_missing:
                reco_secto = np.delete(np.array(reco_secto),int(icb19) - 1)
        weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1.5)
        weight_secto_bench[weight_secto_bench<0.0025] = 0.0025

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())

    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())

    nb_securities = round(len(df.loc[pd.isna(df['Multi Avg Percentile']) == False])*(0.6))
    df=df.nlargest(nb_securities,'Multi Avg Percentile')

    df_esg = copy.deepcopy(df)
    if esg_exclusion > 1:
        df_esg = df[df['ESG_ANALYST_SCORE'] >= esg_exclusion]
    else:
        df_esg = df.loc[esg_pct >= esg_exclusion]
    df_esg = df_esg[~(df_esg.index.isin(liste_noire))]

    columns = ['PTF', 'ISIN', 'Weight', 'Date']
    nb_securities = round(len(df_esg.loc[pd.isna(df_esg[list_score_col]) == False])*percentile)
    df_top = df_esg.nlargest(nb_securities,list_score_col)

    temp_df = pd.DataFrame(columns = columns)
    temp_df['ISIN'] = df_top.index
    if weight_neutral == "ICB 19":
        temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
    elif weight_neutral == "ICB 11":
        temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
    temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
    temp_df['Score'] = df_top[list_score_col].values
    temp_df['PTF'] = 'Ptf_dev_secto_EU'
    temp_df['Date'] = date
    
    if weight_neutral != "No":
        for secto in temp_df['Secto'].unique():
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()

    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       temp_df[columns].to_excel(writer,index = False)

    return "ptf dev secto generated successfully in " + output_file

@xl_macro('str screen, str region, str output_dir, str curr_path, float percentile, float cut_mkt_cap, str metrics, str score_neutral, str weight_neutral, str ponderation, float esg_exclusion, str liste_noire, float[] reco_secto, float[] reco_facto')
def mft_esg_eu(screen, region, output_dir,curr_path, percentile, cut_mkt_cap, metrics, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire,
                  reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], reco_facto=[0,0,0,0,0]):

    list_score_col = metrics
    list_style = ['Growth Avg Percentile','LowVol Avg Percentile','Mom Avg Percentile','Quality Avg Percentile','Value Avg Percentile']
    reco_facto = np.array(reco_facto,dtype='float')
    if reco_facto.sum() == 0:
        reco_facto = np.array([0.2]*5)
    else:
        # reco_facto[reco_facto==1] = 0.35
        # reco_facto[reco_facto==0] = 0.1
        reco_facto = reco_facto/reco_facto.sum()

    if type(screen) == str:
        df = read_screen(screen,curr_path)
    else:
        df = screen
    if type(liste_noire) == str:
        liste_noire = read_liste_noire([],[],liste_noire)

    df = df[df['Weight in MSCI ACWI'] > 0]
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])

    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        mkt_cap_min = 2000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y")+"/MF TILT ESG EU.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        mkt_cap_min = 4000
        output_file = output_dir +"/Mom EBITDA margin US.xlsx"
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap

    df['Multi Avg Percentile'] = df[list_style].mean(skipna= False, axis=1)
    df['Multi Avg Percentile 2'] = df[list_style].dot(reco_facto)
    df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col] = np.NaN

    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    elif ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    elif ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    elif ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)

    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
        icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
        if len(icb_missing) > 0:
            for icb19 in icb_missing:
                reco_secto = np.delete(np.array(reco_secto),int(icb19) - 1)
        weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1)
        weight_secto_bench[weight_secto_bench<0.0025] = 0.0025

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
    max_mean_weights = pd.Series(data = [0.03]*len(weight_secto_bench), index = weight_secto_bench.index)

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())

    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())

    df_esg = copy.deepcopy(df)
    if date.year >= 2017:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        df_esg = df.loc[esg_pct >= esg_exclusion]
        df_esg = df_esg[~(df_esg.index.isin(liste_noire))]

    univ = copy.deepcopy(df_esg)

    columns = ['PTF', 'ISIN', 'Weight', 'Date']

    nb_securities_tot = round(len(df.loc[pd.isna(df[list_score_col]) == False])*percentile)
    nb_securities_esg = round(len(df_esg.loc[pd.isna(df_esg[list_score_col]) == False])*percentile)
    df_top = univ.nlargest(nb_securities_esg,list_score_col)
    df_top['Repechage'] = 0
    df_top['Raison repechage'] = '-'

    nb_repechage = max(nb_securities_tot-nb_securities_esg,0)
    if nb_repechage>0:
        univ_repechage = univ[~univ.index.isin(df_top.index)]
        new_stocks = univ_repechage.nlargest(nb_repechage,'Multi Avg Percentile 2')
        new_stocks['Repechage'] = 1
        new_stocks['Raison repechage'] = 'New Q1'
        df_top = pd.concat([df_top, new_stocks],axis=0)

    weight_repart = weight_secto_bench
    df_top = repechage_sec_list(df_top, univ, weight_repart, max_mean_weights, 'Multi Avg Percentile 2', ' Benchmark ICB Supersector ')

    temp_df = pd.DataFrame(columns = columns)
    temp_df['ISIN'] = df_top.index
    if weight_neutral == "ICB 19":
        temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
    elif weight_neutral == "ICB 11":
        temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
    temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
    temp_df['Score'] = df_top[list_score_col].values
    temp_df['PTF'] = 'MF_TILT_ESG'
    temp_df['Date'] = date
    temp_df['Repechage'] = df_top['Repechage'].values
    
    if weight_neutral != "No":
        for secto in temp_df['Secto'].unique():
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()

    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       temp_df[columns].to_excel(writer,index = False)

    univ = univ.merge(temp_df[['ISIN','Weight']], how='left', left_index=True,right_on='ISIN')
    with pd.ExcelWriter(output_dir +"/Pour " + date.strftime("%B %Y")+"/UNIV.xlsx",datetime_format = 'dd/mm/yyyy') as writer:
       univ.to_excel(writer,index = True)
    return "ptf tilt esg Europe generated successfully in " + output_file


def mft_esg_eu_test(screen, bench, region, output_dir,curr_path, percentile, cut_mkt_cap, metrics, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire,
                  reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], reco_facto=[0,0,0,0,0]):

    list_score_col = metrics
    list_style = ['Growth Avg Percentile','LowVol Avg Percentile','Mom Avg Percentile','Quality Avg Percentile','Value Avg Percentile']
    reco_facto = np.array(reco_facto,dtype='float')
    if reco_facto.sum() == 0:
        reco_facto = np.array([0.2]*5)
    else:
        # reco_facto[reco_facto==1] = 0.35
        # reco_facto[reco_facto==0] = 0.1
        reco_facto = reco_facto/reco_facto.sum()

    if type(screen) == str:
        df = read_screen(screen,curr_path)
    else:
        df = screen
    if type(liste_noire) == str:
        liste_noire = read_liste_noire([],[],liste_noire)

    df = screen[screen['Weight in ' + bench]>0]

    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in ' + bench],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])

    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        mkt_cap_min = 2000
        output_file = output_dir +"/Pour " + date.strftime("%B %Y")+"/MF TILT ESG EU.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        mkt_cap_min = 4000
        output_file = output_dir +"/Mom EBITDA margin US.xlsx"
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap

    df['Multi Avg Percentile'] = df[list_style].mean(skipna= False, axis=1)
    df['Multi Avg Percentile 2'] = df[list_style].dot(reco_facto)
    df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col] = np.NaN

    df['Date'] = date


    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    elif ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    elif ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    elif ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)

    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
        icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
        if len(icb_missing) > 0:
            for icb19 in icb_missing:
                reco_secto = np.delete(np.array(reco_secto),int(icb19) - 1)
        weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1)
        weight_secto_bench[weight_secto_bench<0.0025] = 0.0025

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
    max_mean_weights = pd.Series(data = [0.03]*len(weight_secto_bench), index = weight_secto_bench.index)

    print(list_score_col)
    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())

    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())

    df_esg = copy.deepcopy(df)
    if date.year >= 2017:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        df_esg = df.loc[esg_pct >= esg_exclusion]
        df_esg = df_esg[~(df_esg.index.isin(liste_noire))]

    univ = copy.deepcopy(df_esg)

    columns = ['PTF', 'ISIN', 'Weight', 'Date']

    nb_securities_tot = round(len(df.loc[pd.isna(df[list_score_col]) == False])*percentile)
    nb_securities_esg = round(len(df_esg.loc[pd.isna(df_esg[list_score_col]) == False])*percentile)
    df_top = univ.nlargest(nb_securities_esg,list_score_col)
    df_top['Repechage'] = 0
    df_top['Raison repechage'] = '-'

    nb_repechage = max(nb_securities_tot-nb_securities_esg,0)
    if nb_repechage>0:
        univ_repechage = univ[~univ.index.isin(df_top.index)]
        new_stocks = univ_repechage.nlargest(nb_repechage,'Multi Avg Percentile 2')
        new_stocks['Repechage'] = 1
        new_stocks['Raison repechage'] = 'New Q1'
        df_top = pd.concat([df_top, new_stocks],axis=0)

    weight_repart = weight_secto_bench
    df_top = repechage_sec_list(df_top, univ, weight_repart, max_mean_weights, 'Multi Avg Percentile 2', ' Benchmark ICB Supersector ')

    temp_df = pd.DataFrame(columns = columns)
    temp_df['ISIN'] = df_top.index
    if weight_neutral == "ICB 19":
        temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
    elif weight_neutral == "ICB 11":
        temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
    temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
    temp_df['Score'] = df_top[list_score_col].values
    temp_df['PTF'] = 'MF_TILT_ESG'
    temp_df['Date'] = date
    temp_df['Repechage'] = df_top['Repechage'].values
    
    if weight_neutral != "No":
        for secto in temp_df['Secto'].unique():
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()

    # with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #    temp_df[columns].to_excel(writer,index = False)

    # univ = univ.merge(temp_df[['ISIN','Weight']], how='left', left_index=True,right_on='ISIN')
    # with pd.ExcelWriter(output_dir +"/Pour " + date.strftime("%B %Y")+"/UNIV.xlsx",datetime_format = 'dd/mm/yyyy') as writer:
    #    univ.to_excel(writer,index = True)
    return temp_df[columns]

# A MODIFIER POUR FAIRE DES SCREEN BT
def sec_list_spot(screen, returns, bench, output_dir, percentile, cut_mkt_cap, metrics, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire,
                  reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]):
    """
    Generate Best Scored Sec List for 1 Month, Acoording to Metrics Chosen
    
    """
    if type(metrics)==str:
        list_score_col = [metrics]
    else:
        list_score_col = metrics
    list_style = ['Value Avg Percentile','Quality Avg Percentile','Mom Avg Percentile','LowVol Avg Percentile','Growth Avg Percentile']
    
    #Merging des poids google
    if screen.index.duplicated().any():
        screen = screen[~screen.index.duplicated(keep='first')]

    if ("US02079K3059" in screen.index.tolist()) and ("US02079K1079" in screen.index.tolist()):
        screen.loc['US02079K3059', 'Weight in MSCI WORLD'] = screen.loc['US02079K3059', 'Weight in MSCI WORLD'] + screen.loc['US02079K1079', 'Weight in MSCI WORLD']
        screen.drop(index='US02079K1079', inplace=True)

    df = screen[screen['Weight in ' + bench]>0]


    date = pd.to_datetime(df['Date'].iloc[0]) + pd.offsets.MonthBegin(1)

    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in ' + bench],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in ' + bench])


    df['Multi Avg Percentile'] = df[list_style].mean(skipna= False, axis=1)
    df.loc[df['Benchmark Market Value Millions in EUR'] <= cut_mkt_cap, list_score_col] = np.NaN


    df['Date'] = date
    

    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    if ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    if ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    if ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)
    if ponderation == "Vol Tilt Racine Cube":
        std = pd.DataFrame(returns.iloc[-250:, ].std().rename('STD'))
        df = df.merge(std, how='left', left_on="Company SEDOL", right_index=True)

        from scipy import stats
        def calculate_std_multiplier(x, data):
            return (50 - stats.percentileofscore(data, x, kind='weak')) / 100 + 1
        df['STD_multiplier'] = df['STD'].apply(lambda x: calculate_std_multiplier(x, df['STD']))
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR'] * df['STD_multiplier']


    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in ' + bench].sum() / df['Weight in ' + bench].sum()
        icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
        if len(icb_missing) > 0:
            for icb19 in icb_missing:
                reco_secto = np.delete(np.array(reco_secto),int(icb19) - 1)
        weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1.5)
        weight_secto_bench[weight_secto_bench<0.0025] = 0.0025

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in ' + bench].sum() / df['Weight in ' + bench].sum()

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())

    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())


    df_esg = copy.deepcopy(df)
    if date.year >= 2014:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        df_esg = df.loc[esg_pct >= esg_exclusion]

    if liste_noire is not None:
        if isinstance(liste_noire, str):
            liste_noire = read_liste_noire([], [], liste_noire)

        # Check if 'ISIN' is a column or the index
        if 'ISIN' in df_esg.columns:
            df_esg = df_esg[~df_esg['ISIN'].isin(liste_noire)]
        elif df_esg.index.name == 'ISIN':  # If 'ISIN' is the index
            df_esg = df_esg[~df_esg.index.isin(liste_noire)]



    columns = ['PTF', 'ISIN', 'Weight', 'Date']
    df_concat = pd.DataFrame()
    for i in range(len(list_score_col)):
        nb_securities = round(len(df_esg.loc[pd.isna(df_esg[list_score_col[i]]) == False])*percentile)
        df_top = df_esg.nlargest(nb_securities,list_score_col[i])

        if ponderation == "Metric Tilt Racine Cube":
            from scipy import stats
            df_top['score_col_Z'] = stats.zscore(df_top[list_score_col[i]])
            df_top['Benchmark Market Value Millions in EUR'] = df_top['Benchmark Market Value Millions in EUR']**(1/3) * (1+ (df_top['score_col_Z']*10/100))

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_top.index
        if weight_neutral == "ICB 19":
            temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
        elif weight_neutral == "ICB 11":
            temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_top[list_score_col[i]].values
        if type(ptf_name==str):
            temp_df['PTF'] = ptf_name
        else:
            temp_df['PTF'] = ptf_name[i]
        temp_df['Date'] = date
        
        if weight_neutral != "No":
            for secto in temp_df['Secto'].unique():
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

    return df_concat

def sec_list_spot_worst(screen, bench, output_dir, percentile, cut_mkt_cap, metrics, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire,
                  reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]):
    """
    Generate Worst Scored Sec List for 1 Month, Acoording to Metrics Chosen
    
    """
    if type(metrics)==str:
        list_score_col = [metrics]
    else:
        list_score_col = metrics

    # #Merging des poids google
    # if ("US02079K3059" in screen.index.tolist()) and ("US02079K1079" in screen.index.tolist()):
    #     screen.loc['US02079K3059', 'Weight in MSCI WORLD'] = screen.loc['US02079K3059', 'Weight in MSCI WORLD'] + screen.loc['US02079K1079', 'Weight in MSCI WORLD']
    #     screen.drop(index='US02079K1079', inplace=True)

    df = screen[screen['Weight in ' + bench]>0] # Filter with bench

    # For calculating 'Multi Avg Percentile' in case if we use this as critrier for choosing companies
    list_style = ['Value Avg Percentile','Quality Avg Percentile','Mom Avg Percentile','LowVol Avg Percentile','Growth Avg Percentile']
    df['Multi Avg Percentile'] = df[list_style].mean(skipna= False, axis=1)


    # Fill in the missing values of "Benchmark Market Value Millions in EUR" in the data using linear regression.
    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in ' + bench],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in ' + bench])

    # Putting a celling for market cap
    df.loc[df['Benchmark Market Value Millions in EUR'] <= cut_mkt_cap, list_score_col] = np.NaN

    # Adjust Date
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1) # From end of last month to beginning of next month
    df['Date'] = date


    # Smoothing Weight
    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    elif ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    elif ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    elif ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)

    # Market Cap and Weight transformation : Sector Neutral and Tilt Secto
    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in ' + bench].sum() / df['Weight in ' + bench].sum()
        icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
        
        # If secto recoomandation existed, using it for secto tilt
        if len(icb_missing) > 0:
            for icb19 in icb_missing:
                reco_secto = np.delete(np.array(reco_secto),int(icb19) - 1) # Match two array's length
        weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1.5) 

        weight_secto_bench[weight_secto_bench<0.0025] = 0.0025 # Put a minimum weight per sector

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in ' + bench].sum() / df['Weight in ' + bench].sum()

    # Standarlization of Critier
    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())

    # Critier transformation : Sector Neutral
    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())


    # ESG filter
    df_esg = copy.deepcopy(df)
    if date.year >= 2014:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        # df_esg = df.loc[esg_pct >= esg_exclusion]
        #df = df[~(df.index.isin(liste_noire))]
        # df_esg = df_esg[~(df_esg.index.isin(liste_noire))]
        df_esg = df.loc[esg_pct >= esg_exclusion]
        # df_esg = pd.concat([df_esg, df[df.index.isin(liste_noire)]], axis=0)
        # df_esg = df_esg[~df_esg.index.duplicated(keep='first')]
        # df_esg = df_esg[(df_esg.index.isin(liste_noire))]

    #df_esg[list_score_col] = df_esg.groupby(' Benchmark ICB Supersector ')[list_score_col].rank(pct=True)

    columns = ['PTF', 'ISIN', 'Weight', 'Date']
    df_concat = pd.DataFrame() # Create a df for final result
    for i in range(len(list_score_col)): # For several critiers, normally we have only one

        # Fix nb of securities we want
        nb_securities = round(len(df_esg.loc[pd.isna(df_esg[list_score_col[i]]) == False])*percentile)
        
        #### Find worst noted securities
        df_top = df.nsmallest(nb_securities,list_score_col[i]) 

        # Create a temporary df for save result for one critier
        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_top.index
        if weight_neutral == "ICB 19":
            temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
        elif weight_neutral == "ICB 11":
            temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_top[list_score_col[i]].values
        if type(ptf_name==str):
            temp_df['PTF'] = ptf_name
        else:
            temp_df['PTF'] = ptf_name[i]
        temp_df['Date'] = date
        
        # Sector neutral of weight
        if weight_neutral != "No":
            for secto in temp_df['Secto'].unique():
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

    #with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #   df_concat[columns].to_excel(writer,index = False)

    return df_concat


def sec_list_spot_low_TE(screen, returns, bench, output_dir, percentile, cut_mkt_cap, metrics, ptf_name, score_neutral, weight_neutral, 
                         ponderation, 
                         esg_exclusion, 
                         liste_noire,
                         change_ratio,
                         reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]):
    """
    Generate Best Scored Sec List for 1 Month, Acoording to Metrics Chosen
    
    """
    if type(metrics)==str:
        list_score_col = [metrics]
        # Créez change_column pour chaque métrique
        change_columns = [f"{metrics}_change_1M"]
    else:
        list_score_col = metrics
        # Créez change_column pour chaque métrique dans la liste
        change_columns = [f"{metric}_change_1M" for metric in metrics]
        
    list_style = ['Value Avg Percentile','Quality Avg Percentile','Mom Avg Percentile','LowVol Avg Percentile','Growth Avg Percentile']
    
    #Merging des poids google
    if screen.index.duplicated().any():
        screen = screen[~screen.index.duplicated(keep='first')]

    if ("US02079K3059" in screen.index.tolist()) and ("US02079K1079" in screen.index.tolist()):
        screen.loc['US02079K3059', 'Weight in MSCI WORLD'] = screen.loc['US02079K3059', 'Weight in MSCI WORLD'] + screen.loc['US02079K1079', 'Weight in MSCI WORLD']
        screen.drop(index='US02079K1079', inplace=True)

    df = screen[screen['Weight in ' + bench]>0]


    date = pd.to_datetime(df['Date'].iloc[0]) + pd.offsets.MonthBegin(1)

    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in ' + bench],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in ' + bench])


    df['Multi Avg Percentile'] = df[list_style].mean(skipna= False, axis=1)
    df.loc[df['Benchmark Market Value Millions in EUR'] <= cut_mkt_cap, list_score_col] = np.NaN


    df['Date'] = date
    
    # Application de la nouvelle règle : si change_column < 0.1, remplacer metrics par metrics - change_column
    # Nous devons le faire pour chaque métrique dans list_score_col
    for i, metric in enumerate(list_score_col):
        change_column = change_columns[i]
        if change_column in df.columns:
            # Création d'une copie temporaire des valeurs originales
            df[f"{metric}_original"] = df[metric].copy()
            
            # Appliquer la règle boîte par boîte (ligne par ligne)
            mask = (df[change_column].abs() < change_ratio) & (~df[change_column].isna()) & (~df[metric].isna())
            if mask.any():
                df.loc[mask, metric] = df.loc[mask, metric] - df.loc[mask, change_column]

    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    if ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    if ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    if ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)
    if ponderation == "Vol Tilt Racine Cube":
        std = pd.DataFrame(returns.iloc[-250:, ].std().rename('STD'))
        df = df.merge(std, how='left', left_on="Company SEDOL", right_index=True)

        from scipy import stats
        def calculate_std_multiplier(x, data):
            return (50 - stats.percentileofscore(data, x, kind='weak')) / 100 + 1
        df['STD_multiplier'] = df['STD'].apply(lambda x: calculate_std_multiplier(x, df['STD']))
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR'] * df['STD_multiplier']


    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in ' + bench].sum() / df['Weight in ' + bench].sum()
        icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
        if len(icb_missing) > 0:
            for icb19 in icb_missing:
                reco_secto = np.delete(np.array(reco_secto),int(icb19) - 1)
        weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1.5)
        weight_secto_bench[weight_secto_bench<0.0025] = 0.0025

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in ' + bench].sum() / df['Weight in ' + bench].sum()

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())

    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())


    df_esg = copy.deepcopy(df)
    if date.year >= 2014:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        df_esg = df.loc[esg_pct >= esg_exclusion]

    if liste_noire is not None:
        if isinstance(liste_noire, str):
            liste_noire = read_liste_noire([], [], liste_noire)

        # Check if 'ISIN' is a column or the index
        if 'ISIN' in df_esg.columns:
            df_esg = df_esg[~df_esg['ISIN'].isin(liste_noire)]
        elif df_esg.index.name == 'ISIN':  # If 'ISIN' is the index
            df_esg = df_esg[~df_esg.index.isin(liste_noire)]



    columns = ['PTF', 'ISIN', 'Weight', 'Date']
    df_concat = pd.DataFrame()
    for i in range(len(list_score_col)):
        nb_securities = round(len(df_esg.loc[pd.isna(df_esg[list_score_col[i]]) == False])*percentile)
        df_top = df_esg.nlargest(nb_securities,list_score_col[i])

        if ponderation == "Metric Tilt Racine Cube":
            from scipy import stats
            df_top['score_col_Z'] = stats.zscore(df_top[list_score_col[i]])
            df_top['Benchmark Market Value Millions in EUR'] = df_top['Benchmark Market Value Millions in EUR']**(1/3) * (1+ (df_top['score_col_Z']*10/100))

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_top.index
        if weight_neutral == "ICB 19":
            temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
        elif weight_neutral == "ICB 11":
            temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_top[list_score_col[i]].values
        if type(ptf_name==str):
            temp_df['PTF'] = ptf_name
        else:
            temp_df['PTF'] = ptf_name[i]
        temp_df['Date'] = date
        
        if weight_neutral != "No":
            for secto in temp_df['Secto'].unique():
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

    return df_concat






def sec_list_spot_MF(screen, bench, output_dir, percentile, cut_mkt_cap, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire,
                  reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], 
                  reco_facto = {'Growth Avg Percentile' : 0,
                                'LowVol Avg Percentile' : 0,
                                'Mom Avg Percentile' : 0,
                                'Quality Avg Percentile' : 1,
                                'Value Avg Percentile' : 0}):
    """
    Generate Best Scored Sec List for 1 Month, Acoording to Several Metrics Chosen and Their Weights in Score
    
    """
    list_style = list(reco_facto.keys())
    sytle_weight = list(reco_facto.values())
    sytle_weight = np.array(sytle_weight,dtype='float')

    if sytle_weight.sum() == 0:
        sytle_weight = np.array([0.2]*5)
    else:
        sytle_weight = sytle_weight/sytle_weight.sum()


    df = screen[screen['Weight in ' + bench]>0]

    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in ' + bench],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in ' + bench])

    df['critere_repechage'] = df[list_style].dot(sytle_weight)

    score_col = 'critere_repechage'

    df.loc[df['Benchmark Market Value Millions in EUR'] <= cut_mkt_cap, score_col] = np.NaN

    df['Date'] = date

    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    elif ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    elif ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    elif ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)

    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in ' + bench].sum() / df['Weight in ' + bench].sum()
        icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
        if len(icb_missing) > 0:
            for icb19 in icb_missing:
                reco_secto = np.delete(np.array(reco_secto),int(icb19) - 1)
        weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1.5)
        weight_secto_bench[weight_secto_bench<0.0025] = 0.0025

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in ' + bench].sum() / df['Weight in ' + bench].sum()

    df[score_col] = df[score_col].rank(pct=True)
    df[score_col] = (df[score_col] - df[score_col].min())/(df[score_col].max() - df[score_col].min())

    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, score_col].min())

    df_esg = copy.deepcopy(df)
    if date.year >= 2014:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        df_esg = df.loc[esg_pct >= esg_exclusion]

    columns = ['PTF', 'ISIN', 'Weight', 'Date']

    nb_securities = round(len(df_esg.loc[pd.isna(df_esg[score_col]) == False])*percentile)
    df_top = df.nlargest(nb_securities,score_col)

    temp_df = pd.DataFrame(columns = columns)
    temp_df['ISIN'] = df_top.index
    if weight_neutral == "ICB 19":
        temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
    elif weight_neutral == "ICB 11":
        temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
    temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
    temp_df['Score'] = df_top[score_col].values
    
    temp_df['PTF'] = ptf_name
    
    temp_df['Date'] = date
    
    if weight_neutral != "No":
        for secto in temp_df['Secto'].unique():
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()

    return temp_df

def sec_list_tilt_monthly(screen, bench, output_dir, percentile, cut_mkt_cap, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire, 
                  reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], 
                  reco_facto = {'Growth Avg Percentile' : 0,
                                'LowVol Avg Percentile' : 0,
                                'Mom Avg Percentile' : 0,
                                'Quality Avg Percentile' : 1,
                                'Value Avg Percentile' : 0}):
    """
    Generate Best Scored Sec List for 1 Month, Acoording to Several Metrics Chosen and Their Weights in Score
    
    """
    
    df = screen[screen['Weight in ' + bench]>0]
    # df = df[df['Weight in MSCI ACWI'] > 0]
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    if isinstance(reco_facto, dict):
        reco_facto = reco_facto
    elif isinstance(reco_facto, pd.DataFrame):
        try:
            reco_facto = reco_facto.loc[date].to_dict()
        except : 
            reco_facto = reco_facto



    list_style = list(reco_facto.keys())
    sytle_weight = list(reco_facto.values())
    sytle_weight = np.array(sytle_weight,dtype='float')

    if sytle_weight.sum() == 0:
        sytle_weight = np.array([0.2]*5)
    else:
        sytle_weight = sytle_weight/sytle_weight.sum()


    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in ' + bench],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in ' + bench])

    df['critere_repechage'] = df[list_style].dot(sytle_weight)

    score_col = 'critere_repechage'

    df.loc[df['Benchmark Market Value Millions in EUR'] <= cut_mkt_cap, score_col] = np.NaN

    df['Date'] = date

    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    elif ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    elif ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    elif ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)


    if isinstance(reco_secto, list):
        reco_secto = reco_secto
    elif isinstance(reco_secto, pd.DataFrame):
        reco_secto = reco_secto.loc[date].to_list()



    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in ' + bench].sum() / df['Weight in ' + bench].sum()
        icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
        if len(icb_missing) > 0:
            for icb19 in icb_missing:
                reco_secto = np.delete(np.array(reco_secto),int(icb19) - 1)
        weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1.5)
        weight_secto_bench[weight_secto_bench<0.0025] = 0.0025

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in ' + bench].sum() / df['Weight in ' + bench].sum()

    df[score_col] = df[score_col].rank(pct=True)
    df[score_col] = (df[score_col] - df[score_col].min())/(df[score_col].max() - df[score_col].min())

    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, score_col].min())

    df_esg = copy.deepcopy(df)
    if date.year >= 2014:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        df_esg = df.loc[esg_pct >= esg_exclusion]

    columns = ['PTF', 'ISIN', 'Weight', 'Date']

    nb_securities = round(len(df_esg.loc[pd.isna(df_esg[score_col]) == False])*percentile)
    df_top = df.nlargest(nb_securities,score_col)

    temp_df = pd.DataFrame(columns = columns)
    temp_df['ISIN'] = df_top.index
    if weight_neutral == "ICB 19":
        temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
    elif weight_neutral == "ICB 11":
        temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
    temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
    temp_df['Score'] = df_top[score_col].values
    
    temp_df['PTF'] = ptf_name
    
    temp_df['Date'] = date
    
    if weight_neutral != "No":
        for secto in temp_df['Secto'].unique():
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
    temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()

    return temp_df


def sec_list_tilt(screen, region, output_dir, percentile, cut_mkt_cap, metrics, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire,
                  reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], reco_facto=[0,0,0,0,0]):

    list_score_col = metrics
    list_style = ['Growth Avg Percentile','LowVol Avg Percentile','Mom Avg Percentile','Quality Avg Percentile','Value Avg Percentile']
    reco_facto = np.array(reco_facto,dtype='float')
    if reco_facto.sum() == 0:
        reco_facto = np.array([0.2]*5)
    else:
        reco_facto[reco_facto==1] = 0.35
        reco_facto[reco_facto==0] = 0.1
        reco_facto = reco_facto/reco_facto.sum()
    # reco_facto = pd.Series(data = reco_facto, index=['Growth Avg Percentile','LowVol Avg Percentile','Mom Avg Percentile','Quality Avg Percentile','Value Avg Percentile'])
    # pool_facto = list(reco_facto[reco_facto==1].index)
    #list_style_2 = ['Quality Avg Percentile','LowVol Avg Percentile','Growth Avg Percentile']

    df = screen
    #esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    df=df[df['Weight in MSCI ACWI']>0]
    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])

    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        mkt_cap_min = 2000
        output_file = output_dir +"/Mom EBITDA margin EU.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        mkt_cap_min = 4000
        output_file = output_dir +"/Mom EBITDA margin US.xlsx"
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap

    # if date.year >= 2014:
    #     df['Multi Avg Percentile'] = df[list_style_2].dot([0.4,0.4,0.2])
    # else:
    df['Multi Avg Percentile'] = df[list_style].mean(skipna= False, axis=1)
    df['Multi Avg Percentile 2'] = df[list_style].dot(reco_facto)
    df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col] = np.NaN
    #list_score_col.append("Multi Avg Percentile")

    # if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
    #     os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    elif ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    elif ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    elif ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)

    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
        icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
        if len(icb_missing) > 0:
            for icb19 in icb_missing:
                reco_secto = np.delete(np.array(reco_secto),int(icb19) - 1)
        weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1)
        weight_secto_bench[weight_secto_bench<0.0025] = 0.0025

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
    max_mean_weights = pd.Series(data = [0.04]*len(weight_secto_bench), index = weight_secto_bench.index)

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())

    #df.loc[df[' Benchmark ICB Industry '] == 'Financials', ["Ebitda_margin_FY1, Ebitda_margin_FY1_chg_3M","Ebitda_margin_FY1_chg_6M","Ebitda_margin_FY1_chg_12M"]] = df[["Net_margin_FY1", "Net_margin_FY1_chg_3M","Net_margin_FY1_chg_6M","Net_margin_FY1_chg_12M"]]

    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())

    # nb_securities = round(len(df.loc[pd.isna(df['Multi Avg Percentile']) == False])*(0.8))
    # df=df.nlargest(nb_securities,'Multi Avg Percentile')

    df_esg = copy.deepcopy(df)
    if date.year >= 2017:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        df_esg = df.loc[esg_pct >= esg_exclusion]
        #df_esg = df_esg[~(df_esg.index.isin(liste_noire))]

    univ = copy.deepcopy(df_esg)
    # if reco_facto.sum()==0:
    #     univ = copy.deepcopy(df_esg)
    # else:
    #     condition = [False]*len(df_esg)
    #     for i, factor in enumerate(pool_facto):
    #         if i == 0:
    #             condition = df_esg[factor]>=(1-2*percentile)
    #         else:
    #             condition = condition | df_esg[factor]>=(1-2*percentile)
    #     univ = df_esg.loc[condition]

    columns = ['PTF', 'ISIN', 'Weight', 'Date']
    df_concat = pd.DataFrame()
    for i in range(len(list_score_col)):
        nb_securities_tot = round(len(df.loc[pd.isna(df[list_score_col[i]]) == False])*percentile)
        nb_securities_esg = round(len(df_esg.loc[pd.isna(df_esg[list_score_col[i]]) == False])*percentile)
        df_top = univ.nlargest(nb_securities_esg,list_score_col[i])
        df_top['Repechage'] = 0
        df_top['Raison repechage'] = '-'

        nb_repechage = max(nb_securities_tot-nb_securities_esg,0)
        if nb_repechage>0:
            univ_repechage = univ[~univ.index.isin(df_top.index)]
            new_stocks = univ_repechage.nlargest(nb_repechage,'Multi Avg Percentile 2')
            new_stocks['Repechage'] = 1
            new_stocks['Raison repechage'] = 'New Q1'
            df_top = pd.concat([df_top, new_stocks],axis=0)

        weight_repart = weight_secto_bench
        df_top = repechage_sec_list(df_top, univ, weight_repart, max_mean_weights, 'Multi Avg Percentile 2', ' Benchmark ICB Supersector ')

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_top.index
        if weight_neutral == "ICB 19":
            temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
        elif weight_neutral == "ICB 11":
            temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_top[list_score_col[i]].values
        temp_df['PTF'] = ptf_name[i]
        temp_df['Date'] = date
        temp_df['Repechage'] = df_top['Repechage'].values
        
        if weight_neutral != "No":
            for secto in temp_df['Secto'].unique():
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

    #with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #   df_concat[columns].to_excel(writer,index = False)
    return df_concat

def sec_list_small(screen, region, output_dir, percentile, cut_mkt_cap, metrics, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire,
                  reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]):

    list_score_col = metrics
    list_style = ['Value Avg Percentile','Quality Avg Percentile','Mom Avg Percentile','LowVol Avg Percentile','Growth Avg Percentile']

    df = screen
    #esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI EUR SMALL'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI EUR SMALL'])

    if region == 'Europe':
        # df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        # mkt_cap_min = 2000
        output_file = output_dir +"/Small cap EU.xlsx"
    elif region == 'US':
        # df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        # mkt_cap_min = 4000
        output_file = output_dir +"/Mom EBITDA margin US.xlsx"
    
    if cut_mkt_cap > 0:
        mkt_cap_max = cut_mkt_cap

    df['Multi Avg Percentile'] = df[list_style].mean(skipna= False, axis=1)
    df.loc[df['Benchmark Market Value Millions in EUR'] >= mkt_cap_max, list_score_col] = np.NaN
    df.loc[pd.isna(df['ESG_ANALYST_SCORE']), list_score_col] = np.NaN
    #list_score_col.append("Multi Avg Percentile")

    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    elif ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    elif ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    elif ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)

    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI EUR SMALL'].sum() / df['Weight in MSCI EUR SMALL'].sum()
        icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
        if len(icb_missing) > 0:
            for icb19 in icb_missing:
                reco_secto = np.delete(np.array(reco_secto),int(icb19) - 1)
        weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1.5)
        weight_secto_bench[weight_secto_bench<0.0025] = 0.0025

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in MSCI EUR SMALL'].sum() / df['Weight in MSCI EUR SMALL'].sum()

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())

    #df.loc[df[' Benchmark ICB Industry '] == 'Financials', ["Ebitda_margin_FY1, Ebitda_margin_FY1_chg_3M","Ebitda_margin_FY1_chg_6M","Ebitda_margin_FY1_chg_12M"]] = df[["Net_margin_FY1", "Net_margin_FY1_chg_3M","Net_margin_FY1_chg_6M","Net_margin_FY1_chg_12M"]]

    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())

    # nb_securities = round(len(df.loc[pd.isna(df['Multi Avg Percentile']) == False])*(0.8))
    # df=df.nlargest(nb_securities,'Multi Avg Percentile')
    """ df_esg = copy.deepcopy(df)
    if date.year >= 2014:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        # df_esg = df.loc[esg_pct >= esg_exclusion]
        #df = df[~(df.index.isin(liste_noire))]
        # df_esg = df_esg[~(df_esg.index.isin(liste_noire))]
        df_esg = df.loc[esg_pct <= esg_exclusion]
        # df_esg = pd.concat([df_esg, df[df.index.isin(liste_noire)]], axis=0)
        # df_esg = df_esg[~df_esg.index.duplicated(keep='first')]
        # df_esg = df_esg[(df_esg.index.isin(liste_noire))] """

    #df_esg[list_score_col] = df_esg.groupby(' Benchmark ICB Supersector ')[list_score_col].rank(pct=True)

    columns = ['PTF', 'ISIN', 'Weight', 'Date']
    df_concat = pd.DataFrame()
    for i in range(len(list_score_col)):
        nb_securities = round(len(df.loc[pd.isna(df[list_score_col[i]]) == False])*percentile)
        df_top = df.nlargest(nb_securities,list_score_col[i])
        #df_top = df_top[(df_top.index.isin(liste_noire))|(df_top.index.isin(list(df_esg.index)))]
        # if date.year >= 2014:
        #     df_top = pd.concat([df_top,df_esg], axis= 0)
        #     df_top = df_top[~df_top.index.duplicated(keep='first')]
        #     df_top = df_top[df_top['Benchmark Market Value Millions in EUR'].notna()]
        #df_worst = df.nsmallest(nb_securities,list_score_col[i])

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_top.index
        if weight_neutral == "ICB 19":
            temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
        elif weight_neutral == "ICB 11":
            temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_top[list_score_col[i]].values
        temp_df['PTF'] = ptf_name[i]
        temp_df['Date'] = date
        
        if weight_neutral != "No":
            for secto in temp_df['Secto'].unique():
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
        
        temp_df.loc[temp_df['Weight'] <= 0.001] = 0.001
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

        """ temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_worst.index
        temp_df['ICB19'] = df_worst[' Benchmark ICB Supersector '].values
        temp_df['Weight'] = df_worst['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_worst[list_score_col[i]].values
        temp_df['PTF'] = ptf_name[i][1]
        temp_df['Date'] = date
        for secto in temp_df['ICB19'].unique():
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] / temp_df['Weight'].sum()
            temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] = temp_df.loc[temp_df['ICB19'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['ICB19'] == secto, 'Weight'].sum())
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True) """

    #with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #   df_concat[columns].to_excel(writer,index = False)

    return df_concat

@xl_macro('str screen_agg, str region, str output_dir, float percentile, float[] cut_mkt_cap, str[] metrics, str[] ptf_name, str score_neutral, str weight_neutral, str ponderation, str liste_noire, float esg_cut, str start_date, str end_date, str rebal')
def sec_list_histo(screen_path, region, output_dir, percentile, cut_mkt_cap, metrics, ptf_name, score_neutral, weight_neutral, ponderation,esg_cut,liste_noire,reco_secto,reco_facto, start_date=datetime.date(2004,12,31), end_date=datetime.date.today(), rebal= "Monthly"):
    """
    Generate sec list histo
    """
    all_screen = pd.read_pickle(screen_path)

    start_date=pd.to_datetime(start_date)
    end_date=pd.to_datetime(end_date)
    all_screen = all_screen.loc[(all_screen['Date'] >= start_date) & (all_screen['Date'] <= end_date)]
    all_screen = all_screen[all_screen['Weight in MSCI ACWI'] >0]
    unique_dates = all_screen['Date'].unique()
    cut_mkt_cap = cut_mkt_cap[len(cut_mkt_cap) - len(unique_dates):]
    liste_noire = read_liste_noire([],[], liste_noire)

    if rebal == "Monthly":
        screen_list = [all_screen.loc[all_screen['Date'] == date_] for date_ in unique_dates]
        cut_mkt_cap_list = cut_mkt_cap
    elif rebal == "Quarterly":
        screen_list = [all_screen.loc[all_screen['Date'] == unique_dates[i]] for i in range(0,len(unique_dates),3)]
        cut_mkt_cap_list = [cut_mkt_cap[i] for i in range(0,len(cut_mkt_cap),3)]

    region_list = [region]*len(screen_list)
    output_dir_list = [output_dir]*len(screen_list)
    percentile_list = [percentile]*len(screen_list)
    metrics_list = [metrics]*len(screen_list)
    ptf_name_list = [ptf_name]*len(screen_list)
    score_neutral_list = [score_neutral]*len(screen_list)
    weight_neutral_list = [weight_neutral]*len(screen_list)
    ponderation_list = [ponderation]*len(screen_list)
    liste_noire_list = [liste_noire]*len(screen_list)
    esg_cut_list= [esg_cut]*len(screen_list)

    parameters = np.array([screen_list, region_list, output_dir_list, percentile_list, cut_mkt_cap_list, metrics_list,ptf_name_list,score_neutral_list,
                           weight_neutral_list, ponderation_list,esg_cut_list,liste_noire_list,list(reco_secto),list(reco_facto)], dtype=object) #,list(reco_secto),list(reco_facto)]
    parameters = np.array(parameters).transpose()

    output_file = output_dir + "/output_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + ".xlsx"
    with Pool(20) as p:
        result = p.starmap(sec_list_tilt, [params for params in parameters])

    df = pd.concat(result, ignore_index=True)
    
    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       df.to_excel(writer,index = False)
       
    return "Sec list generated successfully in " + output_file

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
        msg = msg + 'ICB19 manquants : ' + ('-'.join(map(str,tuple(set(df[' Benchmark ICB Supersector ']) - set(df_ICB_19_num[' Benchmark ICB Supersector ']))))) +'.'
        exit = True
    if set(df['FactSet Ind'].astype(str)).issubset(set(df_FS_ICB['FactSet Ind'].astype(str))) == False:
        msg = msg + 'FactSet Ind manquants : ' + ('-'.join(map(str,tuple(set(df['FactSet Ind']) - set(df_FS_ICB['FactSet Ind']))))) +'.'
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
def add_screen(file, screen_agg, path_params, path_daily):

    old_base = pd.read_pickle(screen_agg)
    str_date = (datetime.date.today()).strftime("%Y%m%d")
    old_base.to_pickle(screen_agg.replace('Code/screen_aggregate.pkl','Code/backup_00_screen/screen_aggregate_' + str_date + '.pkl'))
    new_base = read_screen(file,path_params)
    if type(new_base) == str:
        return new_base
    base_updated = pd.concat([old_base, new_base])
    base_updated.to_pickle(screen_agg)
    new_base.to_pickle(screen_agg)
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

def concatenate_all_screen(path, output_path):

    list_files = os.listdir(path)
    filelist = []
    for file in list_files:
        if 'FS_BT' in file:
            filelist.append([path+file])
    with Pool(20) as p:
        result = p.starmap(read_screen, filelist)

    df = pd.concat(result)
    df.dropna(subset='Date', inplace=True)
    return df


def read_returns(file_path, sheet_name, queue):
    returns = pd.read_excel(file_path, sheet_name=sheet_name, index_col=0, engine='calamine')
    queue.put(returns)

@xl_macro('str returns1_path, str returns2_path, str save_path, str path_daily')
def save_returns(returns1_path,returns2_path, save_path, path_daily):
    #returns1_path=r"\\groupe-ufg.com\commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\BACKTEST_MATLAB\_INPUT\BBG DATA BENCH\_RETURN\PROD\RETURN_SAVE_1.xlsx"
    #returns2_path=r"\\groupe-ufg.com\commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\BACKTEST_MATLAB\_INPUT\BBG DATA BENCH\_RETURN\PROD\RETURN_SAVE_2.xlsx"
    #save_path=r"//groupe-ufg.com/commun/Prive/GestionAM/Ingenierie_Financiere/PROD/_EQUITY/FACTEUR TIMING/Push factor bloom/PROD/Code/returns.pkl"

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
    date_return_2y = returns.index[-1] + relativedelta.relativedelta(years=-2)
    returns_2y = returns[returns.index >= date_return_2y]
    returns.to_pickle(save_path)
    returns_2y.to_pickle(save_path.replace('.pkl','_2Y.pkl'))

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
    daily_weights.to_pickle(path_daily)

    return "Returns saved successfully"

@xl_macro('str screen, str[] list_region, str bench_name')
def bench_weights_agg(screen, list_region, bench_name):

    #Lecture screen et returns
    if type(screen) == str:
        df = read_screen(screen)
    else:
        df = screen

    #Merging des poids google
    df.loc['US02079K3059', bench_name] = df.loc['US02079K3059', bench_name] + df.loc['US02079K1079', bench_name]
    df.drop(index='US02079K1079', inplace=True)

    df = df[df['Company SEDOL'].notna()]
    df = df[df[bench_name]>0]
    df = df[df['Exchange Country Region'].isin(list_region)]
    df[bench_name] /= df[bench_name].sum()

    #Poids par zone géo et par secteur du bench, dvd yield moyen et carbon intensity moyenne
    weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')[bench_name].sum() / df[bench_name].sum()
    weight_region_bench = df.groupby('Exchange Country Region')[bench_name].sum() / df[bench_name].sum()
    
    missing_region = list(set(list_region) - set(weight_region_bench.index))
    if len(missing_region)>0:
        fill_missing = [0] * len(missing_region)
        weight_region_bench=(pd.concat([weight_region_bench, pd.Series(data=fill_missing, index = missing_region)])).sort_index()

    return [list(weight_region_bench.values),list(weight_secto_bench.values)]

@xl_macro('str screen, var[][] inclusion, var[][] exclusion, var[][] mf_formula, float[] max_mean_weights_values_region, str[] list_region, str critere_repechage, float[] max_mean_weights_values_secto, int[] list_secto, float cut_mkt_cap, int[] top_companies, str returns, float[] divide_lb, float[] multiply_ub, float min_weight, float max_weight, str[] liste repechage, float[] bucket_min_ub, float[][] min_ub_list, str liste_noire, float[] min_lb, var[] top_mandatory,str date_, str[] override_exclusion,str[] override_inclusion')
def get_sec_list(screen, inclusion, exclusion,mf_formula, max_mean_weights_values_region, list_region,critere_repechage, max_mean_weights_values_secto,list_secto, cut_mkt_cap, top_companies, returns, divide_lb, multiply_ub, min_weight, max_weight, liste_repechage, bucket_min_ub, min_ub_list, liste_noire, min_lb,top_mandatory,date_, override_exclusion, override_inclusion):

    #Liste des styles utilisés
    list_style = ["Growth Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile", "Dividend Avg Percentile",'Multi Avg Percentile']

    list_score_col = mf_formula[0]
    mf_weighting = mf_formula[1]
    #Liste des régions autorisées
    max_mean_weights_r = pd.Series(data = max_mean_weights_values_region, index = list_region).sort_index()
    max_mean_weights_s = pd.Series(data = max_mean_weights_values_secto, index = list_secto)
    divide_lb_r = pd.Series(data = divide_lb, index = list_region, name="divide_lb")
    multiply_ub_r = pd.Series(data = multiply_ub, index = list_region, name="multiply_ub")
    min_ub_r = pd.DataFrame(data = np.array(min_ub_list).transpose(),columns=['min_ub_1','min_ub_2','min_ub_3'], index = list_region)
    min_lb_r = pd.Series(data = min_lb[1:], index = list_region, name="min_lb")
    transpa_secto = pd.Series(data = ['Auto & Parts','Banks','Basic Resources','Chemicals','Construction & Materials','Financial Services','Food, Beverage & Tobacco','Health Care','Industrial Goods & Services',
                                      'Insurance','Media','Energy','Personal & Household Goods','Real Estate','Retail','Technology','Telecommunications','Travel & Leisure','Utilities'],
                                      index= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], name='transpa_secto')

    inclusion_factors = inclusion[0]
    inclusion_list = inclusion[1]
    exclusion_factors = exclusion[0]
    exclusion_list = exclusion[1]
    nb_top_companies = top_companies[0]
    min_top_companies = top_companies[1]

    #Lecture screen et returns
    if type(returns) == str:
        returns = pd.read_pickle(returns)
    if type(liste_noire) == str:
        liste_noire = read_liste_noire(override_exclusion,override_inclusion,liste_noire)
    if type(screen) == str:
        df = read_screen(screen)
    else:
        df = screen

    date_=pd.to_datetime(date_,dayfirst=True)
    date_return = date_ +  relativedelta.relativedelta(years=-1)
    returns = returns[(returns.index>=date_return)&(returns.index<date_)]
    
    #fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    #func = np.poly1d(fit)
    #df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])

    #Renormalisation des poids

    #Merging des poids google
    df.loc['US02079K3059', 'Weight in MSCI WORLD'] = df.loc['US02079K3059', 'Weight in MSCI WORLD'] + df.loc['US02079K1079', 'Weight in MSCI WORLD']
    df.drop(index='US02079K1079', inplace=True)

    df = df[df['Company SEDOL'].notna()]
    df = df[df['Weight in MSCI WORLD']>0]
    df = df[df['Exchange Country Region'].isin(list_region)]
    df['Weight in MSCI WORLD'] /= df['Weight in MSCI WORLD'].sum()
    df.loc[df['DVD Yield FY1'].isna(),'DVD Yield FY1'] = df['DVD Yield FY0']
    df.loc[df['Earns Yield FY1'].isna(),'Earns Yield FY1'] = df['Earns Yield FY0']
    df ['Earnings yield copy'] = df['Earns Yield FY1'].values
    df ['Dvd yield copy'] = df['DVD Yield FY1'].values
    df['Exclusion liste noire'] = 0
    df['Exclusion ESG'] = 0
    max_weight = max(max_weight, df['Weight in MSCI WORLD'].max()+0.0005)

    #Poids par zone géo et par secteur du bench, dvd yield moyen et carbon intensity moyenne
    weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI WORLD'].sum() / df['Weight in MSCI WORLD'].sum()
    weight_region_bench = df.groupby('Exchange Country Region')['Weight in MSCI WORLD'].sum() / df['Weight in MSCI WORLD'].sum()
    
    missing_region = list(set(list_region) - set(weight_region_bench.index))
    if len(missing_region)>0:
        fill_missing = [0] * len(missing_region)
        weight_region_bench=(pd.concat([weight_region_bench, pd.Series(data=fill_missing, index = missing_region)])).sort_index()

    carbon_intensity_bench = (df.loc[pd.notna(df['CarbonIntensity_Sales']), 'CarbonIntensity_Sales'].dot(df.loc[pd.notna(df['CarbonIntensity_Sales']), 'Weight in MSCI WORLD']))/df.loc[pd.notna(df['CarbonIntensity_Sales']), 'Weight in MSCI WORLD'].sum()

    #Renormalisation des scores par zone géo (uniformes [0:1])
    df['DVD Payout FY0'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['DVD Payout FY0'].rank(pct=True)
    df['DVD Payout FY0'] = (df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['DVD Payout FY0'].apply(lambda x: (x - x.min())/(x.max() - x.min())))
    df['Earns Yield FY1'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['Earns Yield FY1'].rank(pct=True)
    df['DVD Yield FY1'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['DVD Yield FY1'].rank(pct=True)
    df[list_score_col] = ((df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)[list_score_col].apply(lambda x: (x - x.min())/(x.max() - x.min()))))*10
    df['Multi Avg Percentile'] = df[list_score_col].dot(mf_weighting)

    univ = copy.deepcopy(df)
    univ['Carbon intensity'] = univ.groupby(' Benchmark ICB Supersector ')['CarbonIntensity_Sales'].rank(pct=True)
    univ = univ[univ['Weight in MSCI WORLD']>cut_mkt_cap]
    univ = univ[~(univ.index.isin(liste_noire))]
    esg_pct = univ['ESG_ANALYST_SCORE'].rank(pct=True)
    df.loc[df.index.isin(liste_noire),'Exclusion liste noire'] = 1

    #Exclusion des titres sous le seuil d'exclusion sur les scores indiqués (mom, growth et payout ratio normalement) et stockage dans un dataframe correspondant au nouvel univers filtré
    df_filtered = copy.deepcopy(univ)
    for i, factor in enumerate(exclusion_factors):
        if factor == 'DVD Payout FY0':
            df_filtered = df_filtered.loc[df_filtered[factor] <= 1-exclusion_list[i]]
        elif factor == 'ESG_ANALYST_SCORE':
            if exclusion_list[i] > 1:
                univ = univ.loc[univ[factor] >= exclusion_list[i]]
                df.loc[df[factor] < exclusion_list[i], 'Exclusion ESG'] = 1
                df_filtered = df_filtered.loc[df_filtered[factor] >= exclusion_list[i]]
            else:
                df_filtered = df_filtered.loc[esg_pct >= exclusion_list[i]]
                univ = univ.loc[esg_pct >= exclusion_list[i]]
        elif factor == 'CarbonIntensity_Sales':
            df_filtered = df_filtered.loc[(df_filtered['Carbon intensity'] <= 1-exclusion_list[i]) | (df_filtered['CarbonIntensity_Sales'] <= carbon_intensity_bench)]
        else:
            df_filtered = df_filtered.loc[df_filtered[factor] >= exclusion_list[i]*10]

    #On garde les n plus gros poids de l'indice de côté au cas où on n'en ait pas assez à la fin
    df_main_weights = univ.nlargest(nb_top_companies,'Weight in MSCI WORLD')

    #Renormalisation des scores par zone géo (uniformes [0:1])
    df_filtered.loc[df['Dividend Avg Percentile'].isna(),'Dividend Avg Percentile'] = 0
    df_filtered[inclusion_factors] = df_filtered.groupby(['Exchange Country Region',' Benchmark ICB Supersector '],group_keys=False)[inclusion_factors].rank(pct=True)
    df_filtered[inclusion_factors] = (df_filtered.groupby(['Exchange Country Region',' Benchmark ICB Supersector '],group_keys=False)[inclusion_factors].apply(lambda x: (x - x.min())/(x.max() - x.min())))

    #Exclusion des titres sous le seuil minimum sur les scores inclusifs (value, quality, dividend)
    for i, factor in enumerate(inclusion_factors):
        df_filtered = df_filtered.loc[df_filtered[factor] >= 1-inclusion_list[i]]

    df_filtered['Repechage'] = 0
    df_filtered['Raison repechage'] = '-'
    if top_mandatory[0] == 'Yes':
        missing_top_3 = list(set(df_main_weights.nlargest(int(top_mandatory[1]),'Weight in MSCI WORLD').index)-set(df_filtered.index))
        df_filtered = pd.concat([df_filtered,df_main_weights[df_main_weights.index.isin(missing_top_3)]])
        df_filtered.loc[missing_top_3,'Repechage'] = 1
        df_filtered.loc[missing_top_3,'Raison repechage'] = 'Top mandatory'
    #Check nb titres sur les régions, repêchage si nécessaire
    for repechage_type in liste_repechage:
        if repechage_type == 'Exchange Country Region':
            weight_repart = weight_region_bench
            max_mean_weights = max_mean_weights_r
            df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,repechage_type)
        elif repechage_type == 'Benchmark ICB Supersector ':
            weight_repart = weight_secto_bench
            max_mean_weights = max_mean_weights_s
            df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,' '+repechage_type)
        elif repechage_type == 'Top weights':
            #Check nb titres parmi le top n et repêchage si inférieur au nb minimum de titres parmi top n
            missing_main_weights = list(set(df_main_weights.index) - set(df_filtered.index))
            nb_top_companies_seclist = nb_top_companies - len(missing_main_weights)
            if nb_top_companies_seclist < min_top_companies:
                df_main_weights.reset_index(inplace=True)
                df_main_weights = (df_main_weights[df_main_weights['ISIN'].isin(missing_main_weights)]).set_index('ISIN')
                df_filtered = pd.concat([df_filtered,repechage(df_main_weights,'No filter','None',critere_repechage,min_top_companies-nb_top_companies_seclist)])

    #Matrice de covariance de la sec list
    returns = returns[df['Company SEDOL'].values]
    returns = returns.loc[:,~returns.columns.duplicated()]
    bench_returns = compute_bench_returns(df,returns)
    df.reset_index(inplace=True)
    df['Beta'] = df['ISIN'].apply(lambda x: linregress(bench_returns.values, returns[df.loc[df['ISIN'] == x,'Company SEDOL'].values[0]]).slope)
    df.set_index('ISIN',inplace=True)
    df_filtered['Beta'] = df['Beta']
    #ewma_cov_mat = ewma_cov(returns, 0.98)

    #Sec list finale pour l'optim
    columns_optim = ['Name','Exchange Country Name', 'Weight in MSCI WORLD', 'Exchange Country Region', ' Benchmark ICB Supersector ','DVD Yield FY1',
                     'CarbonIntensity_Sales', 'ESG_E', 'ESG_S','ESG_G', 'ESG_ANALYST_SCORE', 'Beta']
    sec_list = df_filtered[columns_optim]
    bench_list = df[columns_optim]
    bench_list[list_style] = df[list_style]
    sec_list['Earnings yield'] = df ['Earnings yield copy']
    bench_list['Earnings yield'] = df ['Earnings yield copy']
    sec_list['DVD Yield FY1'] = df['Dvd yield copy']
    bench_list['DVD Yield FY1'] = df['Dvd yield copy']
    bench_list[['Repechage','Raison repechage']] = df_filtered[['Repechage','Raison repechage']]
    bench_list[['Exclusion liste noire','Exclusion ESG']] = df[['Exclusion liste noire','Exclusion ESG']]

    #Initialisation des poids et ajout des poids du bench
    mean_weights_region = weight_region_bench/(sec_list.groupby('Exchange Country Region').apply(lambda x: len(x)))
    mean_weights_region.name='Weight'

    sec_list = sec_list.merge(right=divide_lb_r, how='left', left_on='Exchange Country Region',right_index=True)
    sec_list = sec_list.merge(right=multiply_ub_r, how='left', left_on='Exchange Country Region',right_index=True)
    for i, bucket in enumerate(bucket_min_ub):
        if i == 0:
            sec_list.loc[sec_list['Weight in MSCI WORLD']<=bucket,'min_ub'] = sec_list.merge(right=min_ub_r.iloc[:,i], how='left', left_on='Exchange Country Region',right_index=True)['min_ub_'+str(i+1)]
        elif i == len(bucket_min_ub)-1:
            sec_list.loc[sec_list['Weight in MSCI WORLD']>bucket,'min_ub'] = sec_list.merge(right=min_ub_r.iloc[:,i], how='left', left_on='Exchange Country Region',right_index=True)['min_ub_'+str(i+1)]
        else:
            sec_list.loc[(sec_list['Weight in MSCI WORLD']<=bucket)*(sec_list['Weight in MSCI WORLD']>bucket_min_ub[i-1]),'min_ub'] = sec_list.merge(right=min_ub_r.iloc[:,i], how='left', left_on='Exchange Country Region',right_index=True)['min_ub_'+str(i+1)]

    sec_list.loc[sec_list['Weight in MSCI WORLD']>min_lb[0],'min_lb'] = sec_list.merge(right=min_lb_r, how='left', left_on='Exchange Country Region',right_index=True)['min_lb']
    sec_list['lb'] = sec_list['Weight in MSCI WORLD']/sec_list['divide_lb']
    sec_list['ub'] = sec_list['Weight in MSCI WORLD']*sec_list['multiply_ub']
    sec_list.loc[sec_list['ub'] < sec_list['min_ub'], 'ub'] = sec_list['min_ub']
    sec_list.loc[sec_list['lb'] < sec_list['min_lb'], 'lb'] = sec_list['min_lb']
    sec_list.loc[sec_list['lb'] < min_weight, 'lb'] = min_weight
    sec_list.loc[sec_list['ub'] > max_weight, 'ub'] = max_weight

    sec_list.rename(columns={'Weight in MSCI WORLD':'Weight', 'DVD Yield FY1':'Dvd yield', 'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector',
                             'CarbonIntensity_Sales':'Carbon Intensity'}, inplace=True)
    bench_list.rename(columns={'Weight in MSCI WORLD':'Weight', 'DVD Yield FY1':'Dvd yield', 'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector',
                             'CarbonIntensity_Sales':'Carbon Intensity'}, inplace=True)
    sec_list.sort_values(by='Weight', ascending=False)
    bench_list.sort_values(by='Weight', ascending=False)
    bench_list['Weight_ptf'] = sec_list['Weight']
    bench_list['Weight_ptf'] = bench_list['Weight_ptf'].fillna(0)
    bench_list = bench_list.merge(right=transpa_secto,how='left', left_on='Sector', right_index=True)
    bench_list['Sector'] = bench_list['transpa_secto']
    bench_list.drop(columns='transpa_secto',inplace=True)
    bench_list[['lb','ub']] = sec_list[['lb','ub']]
    bench_list['Repechage'] = bench_list['Repechage'].fillna('-')
    bench_list['Sedol'] = df['Company SEDOL']
    #ptf_result = [list(sec_list.index),list(sec_list['Name'].values),list(sec_list['Exchange Country Name'].values),list(sec_list['Region'].values),list(sec_list['Sector'].values),
    #        list(sec_list['Weight'].values),list(sec_list['ESG_E'].values),list(sec_list['ESG_S'].values),list(sec_list['ESG_G'].values),list(sec_list['ESG_ANALYST_SCORE'].values),
    #        list(sec_list['Dvd yield'].values),list(sec_list['Carbon Intensity'].values)]
    bench_result = [list(bench_list.index),list(bench_list['Name'].values),list(bench_list['Exchange Country Name'].values),list(bench_list['Region'].values),list(bench_list['Sector'].values),
            list(bench_list['Weight'].values),list(bench_list['ESG_E'].values),list(bench_list['ESG_S'].values),list(bench_list['ESG_G'].values),list(bench_list['ESG_ANALYST_SCORE'].values),
            list(bench_list['Dvd yield'].values),list(bench_list['Earnings yield'].values),list(bench_list['Carbon Intensity'].values),list(bench_list['Weight_ptf'].values),
            list(bench_list["Growth Avg Percentile"].values),list(bench_list["Mom Avg Percentile"].values),list(bench_list["Quality Avg Percentile"].values),list(bench_list["Value Avg Percentile"].values),
            list(bench_list["Dividend Avg Percentile"].values),list(bench_list['Multi Avg Percentile'].values),list(bench_list['Repechage'].values),list(bench_list['Raison repechage'].values),
            list(bench_list['lb'].values),list(bench_list['ub'].values),list(bench_list['Beta'].values),list(bench_list['Sedol'].values),list(bench_list['Exclusion liste noire'].values),
            list(bench_list['Exclusion ESG'].values)]
    return bench_result

@xl_macro('var[][] ptf, var[][] bench, str[] list_region, int[] list_secto, str returns, str optim_type, float[][] bornes_region, float[][] bornes_secto, float[] beta_target, str date, str[] col_bench, str[] col_sec_list, float min_div_yield, float reduc_carbon')
def launch_optim(ptf, bench, list_region, list_secto,returns, optim_type, bornes_region, bornes_secto, beta_target, date_, col_bench, col_sec_list, min_div_yield, reduc_carbon):

    df = pd.DataFrame(data = np.array(bench).transpose(), columns = col_bench)
    sec_list = pd.DataFrame(data = np.array(ptf).transpose(), columns = col_sec_list)
    df.set_index('ISIN', inplace=True)
    df.sort_index(inplace=True)
    sec_list.set_index('ISIN', inplace=True)
    sec_list.sort_index(inplace=True)
    transpa_secto = pd.Series(data = ['Auto & Parts','Banks','Basic Resources','Chemicals','Construction & Materials','Financial Services','Food, Beverage & Tobacco','Health Care','Industrial Goods & Services',
                                      'Insurance','Media','Energy','Personal & Household Goods','Real Estate','Retail','Technology','Telecommunications','Travel & Leisure','Utilities'],
                                      index= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], name='transpa_secto')
    transpa_secto_inv = pd.Series(index = ['Auto & Parts','Banks','Basic Resources','Chemicals','Construction & Materials','Financial Services','Food, Beverage & Tobacco','Health Care','Industrial Goods & Services',
                                      'Insurance','Media','Energy','Personal & Household Goods','Real Estate','Retail','Technology','Telecommunications','Travel & Leisure','Utilities'],
                                      data= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], name='transpa_secto')
    df = df.merge(right=transpa_secto_inv,how='left', left_on='Sector', right_index=True)
    df['Sector'] = df['transpa_secto']
    df.drop(columns='transpa_secto',inplace=True)
    sec_list = sec_list.merge(right=transpa_secto_inv,how='left', left_on='Sector', right_index=True)
    sec_list['Sector'] = sec_list['transpa_secto']
    sec_list.drop(columns='transpa_secto',inplace=True)
    
    for col in sec_list.columns:
        if col != 'Name' and col != 'Country' and col != 'Region' and col != 'Sector' and col != 'Raison repechage' and col != 'Sedol':
            sec_list[col] = sec_list[col].astype(float)
    for col in df.columns:
        if col != 'Name' and col != 'Country' and col != 'Region' and col != 'Sector' and col != 'Sedol':
            df[col] = df[col].astype(float)
    df.replace(100000,float('NaN'),inplace=True)
    sec_list.replace(100000,float('NaN'),inplace=True)

    esg_bench = (df.loc[pd.notna(df['Score ESG']), 'Score ESG'].dot(df.loc[pd.notna(df['Score ESG']), 'Weight']))/df.loc[pd.notna(df['Score ESG']), 'Weight'].sum()
    carbon_intensity_bench = (df.loc[pd.notna(df['Carbon Intensity']), 'Carbon Intensity'].dot(df.loc[pd.notna(df['Carbon Intensity']), 'Weight']))/df.loc[pd.notna(df['Carbon Intensity']), 'Weight'].sum()
    max_carbon_intensity = carbon_intensity_bench*(1+reduc_carbon)

    lb_region = pd.Series(data = bornes_region[0], index = list_region).sort_index()
    ub_region = pd.Series(data = bornes_region[1], index = list_region).sort_index()
    lb_secto = pd.Series(data = bornes_secto[0], index = list_secto).sort_index()
    ub_secto = pd.Series(data = bornes_secto[1], index = list_secto).sort_index()
    list_region.sort()
    list_secto.sort()

    if type(returns) == str:
        returns = pd.read_pickle(returns)

    date_=pd.to_datetime(date_,dayfirst=True)
    date_return = date_ +  relativedelta.relativedelta(years=-2)
    returns = returns[(returns.index>=date_return)&(returns.index<date_)]

    #Matrice de covariance de la sec list
    returns = returns[df['Sedol'].values]
    returns = returns.loc[:,~returns.columns.duplicated()]
    ewma_cov_mat = ewma_cov(returns, 0.96)

    weight_bench = df['Weight']
    in_ptf = weight_bench.reset_index()['ISIN'].apply(lambda x: x in sec_list.index)

    #Bornes secto et bornes region
    max_secto = sec_list.groupby('Sector')['ub'].sum()
    min_secto = sec_list.groupby('Sector')['lb'].sum()
    max_region = sec_list.groupby('Region')['ub'].sum()
    min_region = sec_list.groupby('Region')['lb'].sum()
    missing_region = list(set(list_region) - set(max_region.index))
    if len(missing_region)>0:
        fill_missing = [0] * len(missing_region)
        max_region=(pd.concat([max_region, pd.Series(data=fill_missing, index = missing_region)])).sort_index()
        min_region=(pd.concat([min_region, pd.Series(data=fill_missing, index = missing_region)])).sort_index()

    lb_secto = np.minimum(np.array(lb_secto), max_secto)
    ub_secto = np.maximum(np.array(ub_secto), min_secto)
    lb_region = np.minimum(np.array(lb_region), max_region)
    ub_region = np.maximum(np.array(ub_region), min_region)

    #Création matrice themes et vecteur ineq pour contraintes d'inégalités : A.x - b >= 0
    theme_region = transform_flag_to_theme(sec_list['Region'], list_flag=list_region)
    theme_secto = transform_flag_to_theme(sec_list['Sector'])
    x0 = [1/len(sec_list)]*len(sec_list)
    A_ineq = np.concatenate(([sec_list['Dvd yield'].fillna(0).values], theme_region, theme_region*(-1),theme_secto, theme_secto*(-1),
                            [(-1)*sec_list['Carbon Intensity'].fillna(300).values],[sec_list['Beta'].values], [sec_list['Beta'].values*(-1)], 
                            [sec_list['Score ESG'].fillna(2).values]),axis=0)
    """ theme_secto, theme_region*(-1), theme_secto*(-1),
                             [(-1)*sec_list['Carbon Intensity'].fillna(300).values],[sec_list['Beta'].values], [sec_list['Beta'].values*(-1)], 
                            [sec_list['Score ESG'].fillna(2).values]), axis=0) """
    ineq = np.concatenate(([min_div_yield],lb_region,ub_region*(-1),lb_secto, ub_secto*(-1), [max_carbon_intensity*(-1)], [beta_target[0]],
                            [beta_target[1]*(-1)], [esg_bench]),axis=0)
    """ lb_region, lb_secto, ub_region*(-1), ub_secto*(-1), [max_carbon_intensity*(-1)], [beta_target[0]],
                            [beta_target[1]*(-1)], [esg_bench]), axis=0) """
    A_eq = np.ones(len(x0)).reshape(1,-1)
    eq = [1]

    if optim_type == "Min TE":
        weights_optim = optim_mai(compute_te,x0, A_eq, A_ineq, eq, ineq, sec_list['lb'], sec_list['ub'], weight_bench.values, ewma_cov_mat, in_ptf)

    sec_list['Weight'] = weights_optim
    ptf_te = compute_te(weights_optim, weight_bench.values, ewma_cov_mat, in_ptf)
    sec_list['ptf_te'] = ptf_te
    """ weight_secto_ptf = sec_list.groupby('Sector')['Weight'].sum() / sec_list['Weight'].sum()
    weight_region_ptf = sec_list.groupby('Region')['Weight'].sum() / sec_list['Weight'].sum()
    nb_titres_secto_ptf = sec_list.groupby('Sector').apply(lambda x: len(x))
    nb_titres_region_ptf = sec_list.groupby('Region').apply(lambda x: len(x))
    dvd_yield_ptf = (sec_list.loc[pd.notna(sec_list['Dvd yield']), 'Dvd yield'].dot(sec_list.loc[pd.notna(sec_list['Dvd yield']), 'Weight']))/sec_list.loc[pd.notna(sec_list['Dvd yield']), 'Weight'].sum()
    carbon_intensity_ptf = (sec_list.loc[pd.notna(sec_list['Carbon Intensity']), 'Carbon Intensity'].dot(sec_list.loc[pd.notna(sec_list['Carbon Intensity']), 'Weight']))/sec_list.loc[pd.notna(sec_list['Carbon Intensity']), 'Weight'].sum()
    score_E_ptf = (sec_list.loc[pd.notna(sec_list['ESG_E']), 'ESG_E'].dot(sec_list.loc[pd.notna(sec_list['ESG_E']), 'Weight']))/sec_list.loc[pd.notna(sec_list['ESG_E']), 'Weight'].sum()
    score_S_ptf = (sec_list.loc[pd.notna(sec_list['ESG_S']), 'ESG_S'].dot(sec_list.loc[pd.notna(sec_list['ESG_S']), 'Weight']))/sec_list.loc[pd.notna(sec_list['ESG_S']), 'Weight'].sum()
    score_G_ptf = (sec_list.loc[pd.notna(sec_list['ESG_G']), 'ESG_G'].dot(sec_list.loc[pd.notna(sec_list['ESG_G']), 'Weight']))/sec_list.loc[pd.notna(sec_list['ESG_G']), 'Weight'].sum()
    score_ESG_ptf = (sec_list.loc[pd.notna(sec_list['ESG_ANALYST_SCORE']), 'ESG_ANALYST_SCORE'].dot(sec_list.loc[pd.notna(sec_list['ESG_ANALYST_SCORE']), 'Weight']))/sec_list.loc[pd.notna(sec_list['ESG_ANALYST_SCORE']), 'Weight'].sum() """

    sec_list = sec_list.merge(right=transpa_secto,how='left', left_on='Sector', right_index=True)
    sec_list['Sector'] = sec_list['transpa_secto']
    sec_list.drop(columns='transpa_secto',inplace=True)
    sec_list.sort_values(by='Weight', ascending=False)
    sec_list_result = [list(sec_list.index)]
    for i in range(1,len(col_sec_list)):
        sec_list_result.append(list(sec_list[col_sec_list[i]].values))
    sec_list_result.append(list(sec_list['ptf_te'].values))

    return sec_list_result

@xl_macro('str screen, var[][] inclusion, var[][] exclusion, var[][] mf_formula, float[] max_mean_weights_values_region, str[] list_region, str critere_repechage, float[] max_mean_weights_values_secto, int[] list_secto, float cut_mkt_cap, int[] top_companies, str returns, float pct_dvd_yield, float pct_carbon_intensity, float[] divide_lb, float[] multiply_ub, float min_weight, float max_weight, str[] liste repechage, str optim_type, float[] bucket_min_ub, float[][] min_ub_list, str liste_noire, float[][] bornes_region, float[][] bornes_secto, float[] beta_target, float[] min_lb, var[] top_mandatory')
def MAI_sec_list(screen, inclusion, exclusion,mf_formula, max_mean_weights_values_region, list_region,critere_repechage, max_mean_weights_values_secto,list_secto, cut_mkt_cap, top_companies, returns, pct_dvd_yield, pct_carbon_intensity, divide_lb, multiply_ub, min_weight, max_weight, liste_repechage, optim_type, bucket_min_ub, min_ub_list, liste_noire, bornes_region, bornes_secto, beta_target,min_lb,top_mandatory):

    #Liste des styles utilisés
    list_style = ["Growth Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile", "Dividend Avg Percentile",'Multi Avg Percentile']

    list_score_col = mf_formula[0]
    mf_weighting = mf_formula[1]
    #Liste des régions autorisées
    max_mean_weights_r = pd.Series(data = max_mean_weights_values_region, index = list_region).sort_index()
    max_mean_weights_s = pd.Series(data = max_mean_weights_values_secto, index = list_secto)
    lb_region = pd.Series(data = bornes_region[0], index = list_region).sort_index()
    ub_region = pd.Series(data = bornes_region[1], index = list_region).sort_index()
    lb_secto = pd.Series(data = bornes_secto[0], index = list_secto).sort_index()
    ub_secto = pd.Series(data = bornes_secto[1], index = list_secto).sort_index()
    divide_lb_r = pd.Series(data = divide_lb, index = list_region, name="divide_lb")
    multiply_ub_r = pd.Series(data = multiply_ub, index = list_region, name="multiply_ub")
    min_ub_r = pd.DataFrame(data = np.array(min_ub_list).transpose(),columns=['min_ub_1','min_ub_2','min_ub_3'], index = list_region)
    min_lb_r = pd.Series(data = min_lb[1:], index = list_region, name="min_lb")
    transpa_secto = pd.Series(data = ['Auto & Parts','Banks','Basic Resources','Chemicals','Construction & Materials','Financial Services','Food, Beverage & Tobacco','Health Care','Industrial Goods & Services',
                                      'Insurance','Media','Energy','Personal & Household Goods','Real Estate','Retail','Technology','Telecommunications','Travel & Leisure','Utilities'],
                                      index= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], name='transpa_secto')

    inclusion_factors = inclusion[0]
    inclusion_list = inclusion[1]
    exclusion_factors = exclusion[0]
    exclusion_list = exclusion[1]
    nb_top_companies = top_companies[0]
    min_top_companies = top_companies[1]

    #Lecture screen et returns
    if type(returns) == str:
        returns = pd.read_pickle(returns)
    if type(liste_noire) == str:
        liste_noire = read_liste_noire(liste_noire)
    if type(screen) == str:
        df = read_screen(screen)
    else:
        df = screen

    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)
    date_return = date +  relativedelta.relativedelta(years=-2)
    returns = returns[(returns.index>=date_return)&(returns.index<date)]
    
    #fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    #func = np.poly1d(fit)
    #df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])

    #Renormalisation des poids

    #Merging des poids google
    df.loc['US02079K3059', 'Weight in MSCI WORLD'] = df.loc['US02079K3059', 'Weight in MSCI WORLD'] + df.loc['US02079K1079', 'Weight in MSCI WORLD']
    df.drop(index='US02079K1079', inplace=True)

    df = df[df['Company SEDOL'].notna()]
    df = df[df['Weight in MSCI WORLD']>0]
    df = df[df['Exchange Country Region'].isin(list_region)]
    df['Weight in MSCI WORLD'] /= df['Weight in MSCI WORLD'].sum()
    df.loc[df['DVD Yield FY1'].isna(),'DVD Yield FY1'] = df['DVD Yield FY0']
    df.loc[df['Earns Yield FY1'].isna(),'Earns Yield FY1'] = df['Earns Yield FY0']
    df ['Earnings yield copy'] = df['Earns Yield FY1'].values
    max_weight = max(max_weight, df['Weight in MSCI WORLD'].max()+0.0005)

    #Poids par zone géo et par secteur du bench, dvd yield moyen et carbon intensity moyenne
    weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI WORLD'].sum() / df['Weight in MSCI WORLD'].sum()
    weight_region_bench = df.groupby('Exchange Country Region')['Weight in MSCI WORLD'].sum() / df['Weight in MSCI WORLD'].sum()
    
    missing_region = list(set(list_region) - set(weight_region_bench.index))
    if len(missing_region)>0:
        fill_missing = [0] * len(missing_region)
        weight_region_bench=(pd.concat([weight_region_bench, pd.Series(data=fill_missing, index = missing_region)])).sort_index()

    esg_bench = (df.loc[pd.notna(df['ESG_ANALYST_SCORE']), 'ESG_ANALYST_SCORE'].dot(df.loc[pd.notna(df['ESG_ANALYST_SCORE']), 'Weight in MSCI WORLD']))/df.loc[pd.notna(df['ESG_ANALYST_SCORE']), 'Weight in MSCI WORLD'].sum()
    carbon_intensity_bench = (df.loc[pd.notna(df['CarbonIntensity_Sales']), 'CarbonIntensity_Sales'].dot(df.loc[pd.notna(df['CarbonIntensity_Sales']), 'Weight in MSCI WORLD']))/df.loc[pd.notna(df['CarbonIntensity_Sales']), 'Weight in MSCI WORLD'].sum()
    #earnings_yield_bench = (df.loc[pd.notna(df['Earns Yield FY1']), 'Earns Yield FY1'].dot(df.loc[pd.notna(df['Earns Yield FY1']), 'Weight in MSCI WORLD']))/df.loc[pd.notna(df['Earns Yield FY1']), 'Weight in MSCI WORLD'].sum()
    min_div_yield = pct_dvd_yield
    max_carbon_intensity = carbon_intensity_bench*(1+pct_carbon_intensity)

    #Exclusion des mkt cap sous le seuil indiqué
    #univ = df.loc[df['Weight in MSCI ACWI'] >= cut_mkt_cap]

    #df['Multi Avg Percentile'] = df[list_score_col[:-1]].mean(skipna= False, axis=1)
    #list_score_col.append("Multi Avg Percentile")

    #if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
    #    os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    #Renormalisation des scores par zone géo (uniformes [0:1])
    df['DVD Payout FY0'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['DVD Payout FY0'].rank(pct=True)
    df['DVD Payout FY0'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['DVD Payout FY0'].apply(lambda x: (x - x.min())/(x.max() - x.min()))
    df['Earns Yield FY1'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['Earns Yield FY1'].rank(pct=True)
    df[list_score_col] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)[list_score_col].apply(lambda x: (x - x.min())/(x.max() - x.min()))*10
    df['Multi Avg Percentile'] = df[list_score_col].dot(mf_weighting)

    univ = copy.deepcopy(df)
    esg_pct = univ['ESG_ANALYST_SCORE'].rank(pct=True)
    univ['Carbon intensity'] = univ.groupby(' Benchmark ICB Supersector ')['CarbonIntensity_Sales'].rank(pct=True)
    univ = univ[univ['Weight in MSCI WORLD']>cut_mkt_cap]
    univ = univ[~(univ.index.isin(liste_noire))]

    #Exclusion des titres sous le seuil d'exclusion sur les scores indiqués (mom, growth et payout ratio normalement) et stockage dans un dataframe correspondant au nouvel univers filtré
    df_filtered = copy.deepcopy(univ)
    for i, factor in enumerate(exclusion_factors):
        if factor == 'DVD Payout FY0':
            df_filtered = df_filtered = df_filtered.loc[df_filtered[factor] <= 1-exclusion_list[i]]
        elif factor == 'ESG_ANALYST_SCORE':
            if exclusion_list[i] > 1:
                univ = univ.loc[univ[factor] >= exclusion_list[i]]
                df_filtered.loc[df_filtered[factor] >= exclusion_list[i]]
            else:
                df_filtered = df_filtered.loc[esg_pct >= exclusion_list[i]]
                univ = univ.loc[esg_pct >= exclusion_list[i]]
        elif factor == 'CarbonIntensity_Sales':
            df_filtered = df_filtered.loc[(df_filtered['Carbon intensity'] <= 1-exclusion_list[i]) | (df_filtered['CarbonIntensity_Sales'] <= carbon_intensity_bench)]
        else:
            df_filtered = df_filtered.loc[df_filtered[factor] >= exclusion_list[i]*10]

    #On garde les n plus gros poids de l'indice de côté au cas où on n'en ait pas assez à la fin
    df_main_weights = univ.nlargest(nb_top_companies,'Weight in MSCI WORLD')

    #Renormalisation des scores par zone géo (uniformes [0:1])
    df_filtered.loc[df['Dividend Avg Percentile'].isna(),'Dividend Avg Percentile'] = 0
    df_filtered[inclusion_factors] = df_filtered.groupby(['Exchange Country Region',' Benchmark ICB Supersector '],group_keys=False)[inclusion_factors].rank(pct=True)
    df_filtered[inclusion_factors] = df_filtered.groupby(['Exchange Country Region',' Benchmark ICB Supersector '],group_keys=False)[inclusion_factors].apply(lambda x: (x - x.min())/(x.max() - x.min()))

    #Exclusion des titres sous le seuil minimum sur les scores inclusifs (value, quality, dividend)
    for i, factor in enumerate(inclusion_factors):
        df_filtered = df_filtered.loc[df_filtered[factor] >= 1-inclusion_list[i]]

    missing_top_3 = list(set(df_main_weights.nlargest(3,'Weight in MSCI WORLD').index)-set(df_filtered.index))
    df_filtered = pd.concat([df_filtered,df_main_weights[df_main_weights.index.isin(missing_top_3)]])


    df_filtered['Repechage'] = 0
    df_filtered['Raison repechage'] = ''
    if top_mandatory[0] == 'Yes':
        missing_top_3 = list(set(df_main_weights.nlargest(top_mandatory[1],'Weight in MSCI WORLD').index)-set(df_filtered.index))
        df_filtered = pd.concat([df_filtered,df_main_weights[df_main_weights.index.isin(missing_top_3)]])
        df_filtered.loc[missing_top_3,'Repechage'] = 1
        df_filtered.loc[missing_top_3,'Raison repechage'] = 'Top mandatory'
    #Check nb titres sur les régions, repêchage si nécessaire
    for repechage_type in liste_repechage:
        if repechage_type == 'Exchange Country Region':
            weight_repart = weight_region_bench
            max_mean_weights = max_mean_weights_r
            df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,repechage_type)
        elif repechage_type == 'Benchmark ICB Supersector ':
            weight_repart = weight_secto_bench
            max_mean_weights = max_mean_weights_s
            df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,' '+repechage_type)
        elif repechage_type == 'Top weights':
            #Check nb titres parmi le top n et repêchage si inférieur au nb minimum de titres parmi top n
            missing_main_weights = list(set(df_main_weights.index) - set(df_filtered.index))
            nb_top_companies_seclist = nb_top_companies - len(missing_main_weights)
            if nb_top_companies_seclist < min_top_companies:
                df_main_weights.reset_index(inplace=True)
                df_main_weights = (df_main_weights[df_main_weights['ISIN'].isin(missing_main_weights)]).set_index('ISIN')
                df_filtered = pd.concat([df_filtered,repechage(df_main_weights,'No filter','None',critere_repechage,min_top_companies-nb_top_companies_seclist)])

    #Matrice de covariance de la sec list
    returns = returns[df['Company SEDOL'].values]
    returns = returns.loc[:,~returns.columns.duplicated()]
    bench_returns = compute_bench_returns(df,returns)
    df.reset_index(inplace=True)
    df['Beta'] = df['ISIN'].apply(lambda x: linregress(bench_returns.values, returns[df.loc[df['ISIN'] == x,'Company SEDOL'].values[0]]).slope)
    df.set_index('ISIN',inplace=True)
    df_filtered['Beta'] = df['Beta']
    ewma_cov_mat = ewma_cov(returns, 0.98)

    #Sec list finale pour l'optim
    columns_optim = ['Name','Exchange Country Name', 'Weight in MSCI WORLD', 'Exchange Country Region', ' Benchmark ICB Supersector ','DVD Yield FY1',
                     'CarbonIntensity_Sales', 'ESG_E', 'ESG_S','ESG_G', 'ESG_ANALYST_SCORE', 'Beta']
    sec_list = df_filtered[columns_optim]
    bench_list = df[columns_optim]
    bench_list[list_style] = df[list_style]
    sec_list['Earnings yield'] = df ['Earnings yield copy']
    bench_list[['Repechage','Raison repechage']] = df_filtered[['Repechage','Raison repechage']]

    #Initialisation des poids et ajout des poids du bench
    mean_weights_region = weight_region_bench/(sec_list.groupby('Exchange Country Region').apply(lambda x: len(x)))
    mean_weights_region.name='Weight'

    sec_list = sec_list.merge(right=divide_lb_r, how='left', left_on='Exchange Country Region',right_index=True)
    sec_list = sec_list.merge(right=multiply_ub_r, how='left', left_on='Exchange Country Region',right_index=True)
    for i, bucket in enumerate(bucket_min_ub):
        if i == 0:
            sec_list.loc[sec_list['Weight in MSCI WORLD']<=bucket,'min_ub'] = sec_list.merge(right=min_ub_r.iloc[:,i], how='left', left_on='Exchange Country Region',right_index=True)['min_ub_'+str(i+1)]
        elif i == len(bucket_min_ub)-1:
            sec_list.loc[sec_list['Weight in MSCI WORLD']>bucket,'min_ub'] = sec_list.merge(right=min_ub_r.iloc[:,i], how='left', left_on='Exchange Country Region',right_index=True)['min_ub_'+str(i+1)]
        else:
            sec_list.loc[(sec_list['Weight in MSCI WORLD']<=bucket)*(sec_list['Weight in MSCI WORLD']>bucket_min_ub[i-1]),'min_ub'] = sec_list.merge(right=min_ub_r.iloc[:,i], how='left', left_on='Exchange Country Region',right_index=True)['min_ub_'+str(i+1)]

    sec_list.loc[sec_list['Weight in MSCI WORLD']>min_lb[0],'min_lb'] = sec_list.merge(right=min_lb_r, how='left', left_on='Exchange Country Region',right_index=True)['min_lb']
    sec_list['lb'] = sec_list['Weight in MSCI WORLD']/sec_list['divide_lb']
    sec_list['ub'] = sec_list['Weight in MSCI WORLD']*sec_list['multiply_ub']
    sec_list.loc[sec_list['ub'] < sec_list['min_ub'], 'ub'] = sec_list['min_ub']
    sec_list.loc[sec_list['lb'] < sec_list['min_lb'], 'lb'] = sec_list['min_lb']
    sec_list.loc[sec_list['lb'] < min_weight, 'lb'] = min_weight
    sec_list.loc[sec_list['ub'] > max_weight, 'ub'] = max_weight

    sec_list['Weight in MSCI WORLD'] = pd.merge(left=sec_list,right=mean_weights_region, how='left', left_on='Exchange Country Region',right_index=True)['Weight']
    sec_list.rename(columns={'Weight in MSCI WORLD':'Weight', 'DVD Yield FY1':'Dvd yield', 'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector',
                             'CarbonIntensity_Sales':'Carbon Intensity'}, inplace=True)
    bench_list.rename(columns={'Weight in MSCI WORLD':'Weight', 'DVD Yield FY1':'Dvd yield', 'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector',
                             'CarbonIntensity_Sales':'Carbon Intensity'}, inplace=True)
    weight_bench = df['Weight in MSCI WORLD']
    in_ptf = weight_bench.reset_index()['ISIN'].apply(lambda x: x in sec_list.index)

    #Bornes secto et bornes region
    max_secto = sec_list.groupby('Sector')['ub'].sum()
    min_secto = sec_list.groupby('Sector')['lb'].sum()
    max_region = sec_list.groupby('Region')['ub'].sum()
    min_region = sec_list.groupby('Region')['lb'].sum()
    missing_region = list(set(list_region) - set(max_region.index))
    if len(missing_region)>0:
        fill_missing = [0] * len(missing_region)
        max_region=(pd.concat([max_region, pd.Series(data=fill_missing, index = missing_region)])).sort_index()
        min_region=(pd.concat([min_region, pd.Series(data=fill_missing, index = missing_region)])).sort_index()

    lb_secto = np.minimum(np.array(lb_secto), max_secto)
    ub_secto = np.maximum(np.array(ub_secto), min_secto)
    lb_region = np.minimum(np.array(lb_region), max_region)
    ub_region = np.maximum(np.array(ub_region), min_region)

    #Création matrice themes et vecteur ineq pour contraintes d'inégalités : A.x - b >= 0
    theme_region = transform_flag_to_theme(sec_list['Region'], list_flag=list(weight_region_bench.index))
    theme_secto = transform_flag_to_theme(sec_list['Sector'])
    x0 = [1/len(sec_list)]*len(sec_list)
    A_ineq = np.concatenate(([sec_list['Dvd yield'].fillna(0).values], theme_region, theme_secto, theme_region*(-1), theme_secto*(-1), [(-1)*sec_list['Carbon Intensity'].fillna(300).values],
                             [sec_list['Beta'].values], [sec_list['Beta'].values*(-1)], [sec_list['ESG_ANALYST_SCORE'].fillna(2).values]), axis=0)
    ineq = np.concatenate(([min_div_yield], lb_region, lb_secto, ub_region*(-1), ub_secto*(-1), [max_carbon_intensity*(-1)], [beta_target[0]],[beta_target[1]*(-1)], [esg_bench]), axis=0)
    A_eq = np.ones(len(x0)).reshape(1,-1)
    eq = [1]

    #success = False
    if optim_type == "Min TE":
        #while not success:
        weights_optim = optim_mai(compute_te,x0, A_eq, A_ineq, eq, ineq, sec_list['lb'], sec_list['ub'], weight_bench.values, ewma_cov_mat, in_ptf)
        """ if (((A_ineq @ weights_optim)-ineq < -0.00001).sum() == len(ineq)) and (abs((weights_optim.sum() - 1)) <0.00001):
                success = True
            else:
                ineq[0] = ineq[0] - 0.05 """

    sec_list['Weight'] = weights_optim
    ptf_te = compute_te(weights_optim, weight_bench.values, ewma_cov_mat, in_ptf)
    """ weight_secto_ptf = sec_list.groupby('Sector')['Weight'].sum() / sec_list['Weight'].sum()
    weight_region_ptf = sec_list.groupby('Region')['Weight'].sum() / sec_list['Weight'].sum()
    nb_titres_secto_ptf = sec_list.groupby('Sector').apply(lambda x: len(x))
    nb_titres_region_ptf = sec_list.groupby('Region').apply(lambda x: len(x))
    dvd_yield_ptf = (sec_list.loc[pd.notna(sec_list['Dvd yield']), 'Dvd yield'].dot(sec_list.loc[pd.notna(sec_list['Dvd yield']), 'Weight']))/sec_list.loc[pd.notna(sec_list['Dvd yield']), 'Weight'].sum()
    carbon_intensity_ptf = (sec_list.loc[pd.notna(sec_list['Carbon Intensity']), 'Carbon Intensity'].dot(sec_list.loc[pd.notna(sec_list['Carbon Intensity']), 'Weight']))/sec_list.loc[pd.notna(sec_list['Carbon Intensity']), 'Weight'].sum()
    score_E_ptf = (sec_list.loc[pd.notna(sec_list['ESG_E']), 'ESG_E'].dot(sec_list.loc[pd.notna(sec_list['ESG_E']), 'Weight']))/sec_list.loc[pd.notna(sec_list['ESG_E']), 'Weight'].sum()
    score_S_ptf = (sec_list.loc[pd.notna(sec_list['ESG_S']), 'ESG_S'].dot(sec_list.loc[pd.notna(sec_list['ESG_S']), 'Weight']))/sec_list.loc[pd.notna(sec_list['ESG_S']), 'Weight'].sum()
    score_G_ptf = (sec_list.loc[pd.notna(sec_list['ESG_G']), 'ESG_G'].dot(sec_list.loc[pd.notna(sec_list['ESG_G']), 'Weight']))/sec_list.loc[pd.notna(sec_list['ESG_G']), 'Weight'].sum()
    score_ESG_ptf = (sec_list.loc[pd.notna(sec_list['ESG_ANALYST_SCORE']), 'ESG_ANALYST_SCORE'].dot(sec_list.loc[pd.notna(sec_list['ESG_ANALYST_SCORE']), 'Weight']))/sec_list.loc[pd.notna(sec_list['ESG_ANALYST_SCORE']), 'Weight'].sum() """

    #with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #   df_concat[columns].to_excel(writer,index = False)

    sec_list.sort_values(by='Weight', ascending=False)
    bench_list.sort_values(by='Weight', ascending=False)
    bench_list['Weight_ptf'] = sec_list['Weight']
    bench_list['Weight_ptf'] = bench_list['Weight_ptf'].fillna(0)
    bench_list['ptf_te'] = ptf_te
    bench_list = bench_list.merge(right=transpa_secto,how='left', left_on='Sector', right_index=True)
    bench_list['Sector'] = bench_list['transpa_secto']
    bench_list.drop(columns='transpa_secto',inplace=True)
    bench_list[['lb','ub']] = sec_list[['lb','ub']]
    #ptf_result = [list(sec_list.index),list(sec_list['Name'].values),list(sec_list['Exchange Country Name'].values),list(sec_list['Region'].values),list(sec_list['Sector'].values),
    #        list(sec_list['Weight'].values),list(sec_list['ESG_E'].values),list(sec_list['ESG_S'].values),list(sec_list['ESG_G'].values),list(sec_list['ESG_ANALYST_SCORE'].values),
    #        list(sec_list['Dvd yield'].values),list(sec_list['Carbon Intensity'].values)]
    bench_result = [list(bench_list.index),list(bench_list['Name'].values),list(bench_list['Exchange Country Name'].values),list(bench_list['Region'].values),list(bench_list['Sector'].values),
            list(bench_list['Weight'].values),list(bench_list['ESG_E'].values),list(bench_list['ESG_S'].values),list(bench_list['ESG_G'].values),list(bench_list['ESG_ANALYST_SCORE'].values),
            list(bench_list['Dvd yield'].values),list(bench_list['Earnings yield'].values),list(bench_list['Carbon Intensity'].values),list(bench_list['ptf_te'].values),list(bench_list['Weight_ptf'].values),
            list(bench_list["Growth Avg Percentile"].values),list(bench_list["Mom Avg Percentile"].values),list(bench_list["Quality Avg Percentile"].values),list(bench_list["Value Avg Percentile"].values),
            list(bench_list['Earns Yield FY1'].values), list(bench_list['Multi Avg Percentile'].values),list(bench_list['Repechage'].values),list(bench_list['Raison repechage'].values),
            list(bench_list['lb'].values),list(bench_list['ub'].values),list(bench_list['Beta'].values)]
    return bench_result


def MAI_sec_list_for_bt(screen, inclusion, exclusion, mf_formula, max_mean_weights_values_region, list_region,critere_repechage, max_mean_weights_values_secto,list_secto, cut_mkt_cap, top_companies, returns, pct_dvd_yield, pct_carbon_intensity, divide_lb, multiply_ub, min_weight, max_weight, liste_repechage, optim_type, bucket_min_ub, min_ub_list, liste_noire, beta_target,min_lb,top_mandatory, turnover):

    list_style = ["Growth Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile", "Dividend Avg Percentile",'Multi Avg Percentile']
    #Liste des styles utilisés
    list_score_col = mf_formula[0]
    mf_weighting = mf_formula[1]
    #Liste des régions autorisées
    max_mean_weights_r = pd.Series(data = max_mean_weights_values_region, index = list_region).sort_index()
    max_mean_weights_s = pd.Series(data = max_mean_weights_values_secto, index = list_secto)

    divide_lb_r = pd.Series(data = divide_lb, index = list_region, name="divide_lb")
    multiply_ub_r = pd.Series(data = multiply_ub, index = list_region, name="multiply_ub")
    min_ub_r = pd.DataFrame(data = np.array(min_ub_list).transpose(),columns=['min_ub_1','min_ub_2','min_ub_3'], index = list_region)
    min_lb_r = pd.Series(data = min_lb[1:], index = list_region, name="min_lb")
    transpa_secto = pd.Series(data = ['Auto & Parts','Banks','Basic Resources','Chemicals','Construction & Materials','Financial Services','Food, Beverage & Tobacco','Health Care','Industrial Goods & Services',
                                      'Insurance','Media','Energy','Personal & Household Goods','Real Estate','Retail','Technology','Telecommunications','Travel & Leisure','Utilities'],
                                      index= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], name='transpa_secto')

    inclusion_factors = inclusion[0]
    inclusion_list = inclusion[1]
    exclusion_factors = exclusion[0]
    exclusion_list = exclusion[1]
    nb_top_companies = top_companies[0]
    min_top_companies = top_companies[1]

    #Lecture screen et returns
    if type(returns) == str:
        returns = pd.read_pickle(returns)
    if type(liste_noire) == str:
        liste_noire = read_liste_noire([],[],liste_noire)
    if type(screen) == str:
        df = read_screen(screen)
    else:
        df = screen

    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)
    date_return = date +  relativedelta.relativedelta(years=-2)
    returns = returns[(returns.index>=date_return)&(returns.index<date)]
    if date < pd.to_datetime("01/10/2019",dayfirst=True):
        pct_carbon_intensity = -0.2
    
    #fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    #func = np.poly1d(fit)
    #df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])

    #Renormalisation des poids

    #Merging des poids google
    df.loc['US02079K3059', 'Weight in MSCI WORLD'] = df.loc['US02079K3059', 'Weight in MSCI WORLD'] + df.loc['US02079K1079', 'Weight in MSCI WORLD']
    df.drop(index='US02079K1079', inplace=True)

    #Cleaning du benchmark
    df = df[df['Company SEDOL'].notna()]
    df = df[df['Weight in MSCI WORLD']>0]
    df = df[df['Exchange Country Region'].isin(list_region)]
    df['Weight in MSCI WORLD'] /= df['Weight in MSCI WORLD'].sum()
    df.loc[df['DVD Yield FY1'].isna(),'DVD Yield FY1'] = df['DVD Yield FY0']
    df.loc[df['Earns Yield FY1'].isna(),'Earns Yield FY1'] = df['Earns Yield FY0']
    df ['Earnings yield copy'] = df['Earns Yield FY1'].values
    df ['Dvd yield copy'] = df['DVD Yield FY1'].values
    max_weight = max(max_weight, df['Weight in MSCI WORLD'].max()+0.0005)

    #Poids par zone géo et par secteur du bench, dvd yield moyen et carbon intensity moyenne du bench
    weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI WORLD'].sum() / df['Weight in MSCI WORLD'].sum()
    weight_region_bench = df.groupby('Exchange Country Region')['Weight in MSCI WORLD'].sum() / df['Weight in MSCI WORLD'].sum()
    
    missing_region = list(set(list_region) - set(weight_region_bench.index))
    if len(missing_region)>0:
        fill_missing = [0] * len(missing_region)
        weight_region_bench=(pd.concat([weight_region_bench, pd.Series(data=fill_missing, index = missing_region)])).sort_index()

    esg_bench = (df.loc[pd.notna(df['ESG_ANALYST_SCORE']), 'ESG_ANALYST_SCORE'].dot(df.loc[pd.notna(df['ESG_ANALYST_SCORE']), 'Weight in MSCI WORLD']))/df.loc[pd.notna(df['ESG_ANALYST_SCORE']), 'Weight in MSCI WORLD'].sum()
    carbon_intensity_bench = (df.loc[pd.notna(df['CarbonIntensity_Sales']), 'CarbonIntensity_Sales'].dot(df.loc[pd.notna(df['CarbonIntensity_Sales']), 'Weight in MSCI WORLD']))/df.loc[pd.notna(df['CarbonIntensity_Sales']), 'Weight in MSCI WORLD'].sum()
    earnings_yield_bench = (df.loc[pd.notna(df['Earns Yield FY1']), 'Earns Yield FY1'].dot(df.loc[pd.notna(df['Earns Yield FY1']), 'Weight in MSCI WORLD']))/df.loc[pd.notna(df['Earns Yield FY1']), 'Weight in MSCI WORLD'].sum()
    min_div_yield = pct_dvd_yield
    max_carbon_intensity = carbon_intensity_bench*(1+pct_carbon_intensity)

    #Exclusion des mkt cap sous le seuil indiqué
    #univ = df.loc[df['Weight in MSCI ACWI'] >= cut_mkt_cap]

    #df['Multi Avg Percentile'] = df[list_score_col[:-1]].mean(skipna= False, axis=1)
    #list_score_col.append("Multi Avg Percentile")

    #if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
    #    os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    #Renormalisation des scores par zone géo (uniformes [0:1])
    df['DVD Payout FY0'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['DVD Payout FY0'].rank(pct=True)
    df['DVD Payout FY0'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['DVD Payout FY0'].apply(lambda x: (x - x.min())/(x.max() - x.min()))
    df['Earns Yield FY1'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['Earns Yield FY1'].rank(pct=True)
    df['DVD Yield FY1'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['DVD Yield FY1'].rank(pct=True)
    df[list_score_col] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)[list_score_col].apply(lambda x: (x - x.min())/(x.max() - x.min()))*10
    df['Multi Avg Percentile'] = df[list_score_col].dot(mf_weighting)

    #on copie le bench (df) dans une nouvelle variable univers (univ)
    #Univ correspond au bench - exclusion esg - exclusion liste noire. Sert pour le repêchage
    univ = copy.deepcopy(df)
    univ['Carbon intensity'] = univ.groupby(' Benchmark ICB Supersector ')['CarbonIntensity_Sales'].rank(pct=True)
    univ = univ[univ['Weight in MSCI WORLD']>cut_mkt_cap]
    univ = univ[~(univ.index.isin(liste_noire))]
    esg_pct = univ['ESG_ANALYST_SCORE'].rank(pct=True)

    #Exclusion des titres sous le seuil d'exclusion sur les scores indiqués (mom, growth et payout ratio normalement) et stockage dans un dataframe correspondant au nouvel univers filtré
    df_filtered = copy.deepcopy(univ)
    for i, factor in enumerate(exclusion_factors):
        if factor == 'DVD Payout FY0':
            df_filtered = df_filtered.loc[df_filtered[factor] <= 1-exclusion_list[i]]
        elif factor == 'ESG_ANALYST_SCORE':
            if exclusion_list[i] > 1:
                univ = univ.loc[univ[factor] >= exclusion_list[i]]
                df_filtered.loc[df_filtered[factor] >= exclusion_list[i]]
            else:
                df_filtered = df_filtered.loc[esg_pct >= exclusion_list[i]]
                univ = univ.loc[esg_pct >= exclusion_list[i]]
        elif factor == 'CarbonIntensity_Sales':
            df_filtered = df_filtered.loc[(df_filtered['Carbon intensity'] <= 1-exclusion_list[i]) | (df_filtered['CarbonIntensity_Sales'] <= carbon_intensity_bench)]
        else:
            df_filtered = df_filtered.loc[df_filtered[factor] >= exclusion_list[i]]

    #On garde les n plus gros poids de l'indice de côté au cas où on n'en ait pas assez à la fin
    df_main_weights = univ.nlargest(nb_top_companies,'Weight in MSCI WORLD')

    #Renormalisation des scores par zone géo (uniformes [0:1])
    df_filtered.loc[df['Dividend Avg Percentile'].isna(),'Dividend Avg Percentile'] = 0
    df_filtered[inclusion_factors] = df_filtered.groupby(['Exchange Country Region',' Benchmark ICB Supersector '],group_keys=False)[inclusion_factors].rank(pct=True)
    df_filtered[inclusion_factors] = df_filtered.groupby(['Exchange Country Region',' Benchmark ICB Supersector '],group_keys=False)[inclusion_factors].apply(lambda x: (x - x.min())/(x.max() - x.min()))

    #Exclusion des titres sous le seuil minimum sur les scores inclusifs (value, quality, dividend)
    for i, factor in enumerate(inclusion_factors):
        df_filtered = df_filtered.loc[df_filtered[factor] >= 1-inclusion_list[i]]

    if turnover[0] == 'Yes':
        turnover_cons = turnover[1]
        date_old_ptf = date + relativedelta.relativedelta(months=-1)
        old_ptf = pd.read_excel('//groupe-ufg.com/commun/Prive/DIRR/Ingenierie Financiere/Alexandre H/MAI/BT Turnover/ptf_' + date_old_ptf.strftime('%Y%m%d') + '.xlsx', index_col=0, header=0)
        score_facto_min = old_ptf['score_facto'].iloc[0]
        old_ptf = old_ptf[['Weight', 'Repechage']]
        df_filtered = old_ptf[old_ptf['Repechage'] == 0]
        df_filtered = df_filtered.merge(right=df, how='left', left_index=True, right_index=True)
        df_filtered['Weight in MSCI WORLD'] = df_filtered['Weight']
        df_filtered.drop(columns='Weight', inplace=True)
        df_filtered=df_filtered[df_filtered.index.isin(list(univ.index))]

    df_filtered['Repechage'] = 0
    df_filtered['Raison repechage'] = ''
    if top_mandatory[0] == 'Yes':
        missing_top_3 = list(set(df_main_weights.nlargest(top_mandatory[1],'Weight in MSCI WORLD').index)-set(df_filtered.index))
        df_filtered = pd.concat([df_filtered,df_main_weights[df_main_weights.index.isin(missing_top_3)]])
        df_filtered.loc[missing_top_3,'Repechage'] = 1
        df_filtered.loc[missing_top_3,'Raison repechage'] = 'Top 3'

    #Check nb titres sur les régions, repêchage si nécessaire
    for repechage_type in liste_repechage:
        if repechage_type == 'Exchange Country Region':
            weight_repart = weight_region_bench
            max_mean_weights = max_mean_weights_r
            df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,repechage_type)
        elif repechage_type == 'Benchmark ICB Supersector ':
            weight_repart = weight_secto_bench
            max_mean_weights = max_mean_weights_s
            df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,' '+repechage_type)
        elif repechage_type == 'Top weights':
            #Check nb titres parmi le top n et repêchage si inférieur au nb minimum de titres parmi top n
            missing_main_weights = list(set(df_main_weights.index) - set(df_filtered.index))
            nb_top_companies_seclist = nb_top_companies - len(missing_main_weights)
            if nb_top_companies_seclist < min_top_companies:
                df_main_weights.reset_index(inplace=True)
                df_main_weights = (df_main_weights[df_main_weights['ISIN'].isin(missing_main_weights)]).set_index('ISIN')
                df_filtered = pd.concat([df_filtered,repechage(df_main_weights,'No filter','None',critere_repechage,min_top_companies-nb_top_companies_seclist)])

    if turnover[0] == 'Yes':
        old_isin = set(old_ptf.index)
        new_isin = set(df_filtered.index)
        new_weight = pd.DataFrame(old_ptf['Weight'])
        new_weight = pd.concat([new_weight, pd.DataFrame([0]*len(new_isin-old_isin),index=list(new_isin-old_isin),columns=["Weight"])],axis=0)
        df_filtered = pd.concat([df_filtered,pd.DataFrame(index=list(old_isin-new_isin))])
        df_filtered=df_filtered[df_filtered.index.isin(list(univ.index))]
        df_filtered.loc[df_filtered['Repechage'].isna(), 'Repechage'] = 1
        df_filtered.loc[df_filtered['Weight in MSCI WORLD'].isna(), 'Weight in MSCI WORLD'] = 0.001
        new_weight['Weight optim'] = df_filtered['Weight in MSCI WORLD']
        new_weight.loc[new_weight["Weight optim"].isna(), "Weight optim"] = 0
        in_ptf_turnover = copy.deepcopy(new_weight['Weight optim'].values)
        in_ptf_turnover[in_ptf_turnover != 0] = True
        in_ptf_turnover[in_ptf_turnover == 0] = False
        old_weight = new_weight['Weight'].values

    #Matrice de covariance de la sec list
    returns = returns[df['Company SEDOL'].values]
    returns = returns.loc[:,~returns.columns.duplicated()]
    bench_returns = compute_bench_returns(df,returns)
    df.reset_index(inplace=True)
    df['Beta'] = df['ISIN'].apply(lambda x: linregress(bench_returns.values, returns[df.loc[df['ISIN'] == x,'Company SEDOL'].values[0]]).slope)
    df.set_index('ISIN',inplace=True)
    df_filtered['Beta'] = df['Beta']
    ewma_cov_mat = ewma_cov(returns, 0.98)

    #Sec list finale pour l'optim
    columns_optim = ['Name','Exchange Country Name', 'Weight in MSCI WORLD', 'Exchange Country Region', ' Benchmark ICB Supersector ','DVD Yield FY1',
                     'CarbonIntensity_Sales', 'ESG_E', 'ESG_S','ESG_G', 'ESG_ANALYST_SCORE', 'Beta', 'Multi Avg Percentile','Repechage', 'Raison repechage']
    if turnover[0] == 'Yes':
        df_filtered[columns_optim[:-2]] = df[columns_optim[:-2]]
    sec_list = df_filtered[columns_optim]
    bench_list = df[columns_optim[:-2]]
    bench_list[list_style] = df[list_style]
    sec_list['Earnings yield'] = df['Earnings yield copy']
    sec_list['DVD Yield FY1'] = df['Dvd yield copy']

    #Ajout des poids du bench et paramétrage lb / ub
    sec_list = sec_list.merge(right=divide_lb_r, how='left', left_on='Exchange Country Region',right_index=True)
    sec_list = sec_list.merge(right=multiply_ub_r, how='left', left_on='Exchange Country Region',right_index=True)
    for i, bucket in enumerate(bucket_min_ub):
        if i == 0:
            sec_list.loc[sec_list['Weight in MSCI WORLD']<=bucket,'min_ub'] = sec_list.merge(right=min_ub_r.iloc[:,i], how='left', left_on='Exchange Country Region',right_index=True)['min_ub_'+str(i+1)]
        elif i == len(bucket_min_ub)-1:
            sec_list.loc[sec_list['Weight in MSCI WORLD']>bucket,'min_ub'] = sec_list.merge(right=min_ub_r.iloc[:,i], how='left', left_on='Exchange Country Region',right_index=True)['min_ub_'+str(i+1)]
        else:
            sec_list.loc[(sec_list['Weight in MSCI WORLD']<=bucket)*(sec_list['Weight in MSCI WORLD']>bucket_min_ub[i-1]),'min_ub'] = sec_list.merge(right=min_ub_r.iloc[:,i], how='left', left_on='Exchange Country Region',right_index=True)['min_ub_'+str(i+1)]

    sec_list.loc[sec_list['Weight in MSCI WORLD']>min_lb[0],'min_lb'] = sec_list.merge(right=min_lb_r, how='left', left_on='Exchange Country Region',right_index=True)['min_lb']
    sec_list['lb'] = sec_list['Weight in MSCI WORLD']/sec_list['divide_lb']
    sec_list['ub'] = sec_list['Weight in MSCI WORLD']*sec_list['multiply_ub']
    sec_list.loc[sec_list['ub'] < sec_list['min_ub'], 'ub'] = sec_list['min_ub']
    sec_list.loc[sec_list['lb'] < sec_list['min_lb'], 'lb'] = sec_list['min_lb']
    sec_list.loc[sec_list['lb'] < min_weight, 'lb'] = min_weight
    sec_list.loc[sec_list['ub'] > max_weight, 'ub'] = max_weight
    if turnover[0] == 'Yes':
        sec_list.loc[(sec_list['Repechage'] == 1)*(sec_list['Raison repechage'] != 'Top 3')*(sec_list['Raison repechage'] != 'Top weights'), 'lb'] = 0

    sec_list.rename(columns={'Weight in MSCI WORLD':'Weight', 'DVD Yield FY1':'Dvd yield', 'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector',
                             'CarbonIntensity_Sales':'Carbon Intensity'}, inplace=True)
    bench_list.rename(columns={'Weight in MSCI WORLD':'Weight', 'DVD Yield FY1':'Dvd yield', 'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector',
                             'CarbonIntensity_Sales':'Carbon Intensity'}, inplace=True)
    weight_bench = df['Weight in MSCI WORLD']
    in_ptf = weight_bench.reset_index()['ISIN'].apply(lambda x: x in sec_list.index)

    #Bornes secto et bornes region
    max_secto = sec_list.groupby('Sector')['ub'].sum()
    min_secto = sec_list.groupby('Sector')['lb'].sum()
    max_region = sec_list.groupby('Region')['ub'].sum()
    min_region = sec_list.groupby('Region')['lb'].sum()
    missing_region = list(set(list_region) - set(max_region.index))
    if len(missing_region)>0:
        fill_missing = [0] * len(missing_region)
        max_region=(pd.concat([max_region, pd.Series(data=fill_missing, index = missing_region)])).sort_index()
        min_region=(pd.concat([min_region, pd.Series(data=fill_missing, index = missing_region)])).sort_index()

    lb_secto = weight_secto_bench - 0.02
    ub_secto = weight_secto_bench + 0.02
    lb_region = weight_region_bench - 0.02
    ub_region = weight_region_bench + 0.02
    lb_secto[lb_secto<0] = 0
    lb_region[lb_region<0] = 0

    lb_secto = np.minimum(np.array(lb_secto), max_secto)
    ub_secto = np.maximum(np.array(ub_secto), min_secto)
    lb_region = np.minimum(np.array(lb_region), max_region)
    ub_region = np.maximum(np.array(ub_region), min_region)

    #Création matrice themes et vecteur ineq pour contraintes d'inégalités : A.x - b >= 0
    theme_region = transform_flag_to_theme(sec_list['Region'], list_flag=list(weight_region_bench.index))
    theme_secto = transform_flag_to_theme(sec_list['Sector'])
    x0 = [1/len(sec_list)]*len(sec_list)
    A_ineq = np.concatenate(([sec_list['Dvd yield'].fillna(0).values], theme_region, theme_region*(-1), theme_secto, theme_secto*(-1), [(-1)*sec_list['Carbon Intensity'].fillna(300).values],
                             [sec_list['Beta'].values], [sec_list['Beta'].values*(-1)], [sec_list['ESG_ANALYST_SCORE'].fillna(2).values]), axis=0)
    ineq = np.concatenate(([min_div_yield], lb_region, ub_region*(-1), lb_secto, ub_secto*(-1), [max_carbon_intensity*(-1)], [beta_target[0]],[beta_target[1]*(-1)], [esg_bench]), axis=0)
    A_eq = np.ones(len(x0)).reshape(1,-1)
    eq = [1]

    success_dvd_yield = False
    if optim_type == "Min TE":
        while success_dvd_yield == False:
            if turnover[0] == 'No':
                weights_optim = optim_mai(compute_te,x0, A_eq, A_ineq, eq, ineq, sec_list['lb'], sec_list['ub'], weight_bench.values, ewma_cov_mat, in_ptf)
            else:
                A_ineq = np.concatenate((A_ineq,[sec_list['Multi Avg Percentile'].fillna(6).values]),axis=0)
                ineq = np.concatenate((ineq,[score_facto_min]),axis=0)
                weights_optim = optim_mai_turnover(compute_te,x0, A_eq, A_ineq, eq, ineq, sec_list['lb'], sec_list['ub'], turnover_cons, old_weight,in_ptf_turnover, weight_bench.values, ewma_cov_mat, in_ptf)
            if (sec_list['Dvd yield'].fillna(0).values).dot(weights_optim) > ineq[0]-0.00001:
                success_dvd_yield=True
            else:
                ineq[0] = ineq[0]-0.05
    
    success_beta = True
    success_secto = True
    success_region = True
    success_esg = True
    success_carbon_int = True
    constr_not_respect = np.where(((A_ineq @ weights_optim)-ineq < -0.00001))[0]
    if len(constr_not_respect)>0:
        for constr in constr_not_respect:
            if constr <= 12:
                success_region = False
            elif constr <= 50:
                success_secto= False
            elif constr == 51:
                success_carbon_int=False
            elif constr <= 53:
                success_beta = False
            else:
                success_esg = False

    sec_list['Weight'] = weights_optim
    sec_list['Weight'] /= sec_list['Weight'].sum()
    
    #score_facto = (df.loc[pd.notna(df['Multi Avg Percentile']), 'Multi Avg Percentile'].dot(df.loc[pd.notna(df['Multi Avg Percentile']), 'Weight']))/df.loc[pd.notna(df['Multi Avg Percentile']), 'Weight'].sum()
    #ptf_for_turnover = sec_list[['Weight', 'Repechage']].reset_index()
    #ptf_for_turnover['score_facto'] = score_facto
    #ptf_for_turnover.to_excel('//groupe-ufg.com/commun/Prive/DIRR/Ingenierie Financiere/Alexandre H/MAI/BT Turnover/ptf_' & date.strftime('%Y%m%d') & '.xlsx', index=False)

    ptf_te = compute_te(weights_optim, weight_bench.values, ewma_cov_mat, in_ptf)
    """ weight_secto_ptf = sec_list.groupby('Sector')['Weight'].sum() / sec_list['Weight'].sum()
    weight_region_ptf = sec_list.groupby('Region')['Weight'].sum() / sec_list['Weight'].sum()
    nb_titres_secto_ptf = sec_list.groupby('Sector').apply(lambda x: len(x))
    nb_titres_region_ptf = sec_list.groupby('Region').apply(lambda x: len(x))
    dvd_yield_ptf = (sec_list.loc[pd.notna(sec_list['Dvd yield']), 'Dvd yield'].dot(sec_list.loc[pd.notna(sec_list['Dvd yield']), 'Weight']))/sec_list.loc[pd.notna(sec_list['Dvd yield']), 'Weight'].sum()
    carbon_intensity_ptf = (sec_list.loc[pd.notna(sec_list['Carbon Intensity']), 'Carbon Intensity'].dot(sec_list.loc[pd.notna(sec_list['Carbon Intensity']), 'Weight']))/sec_list.loc[pd.notna(sec_list['Carbon Intensity']), 'Weight'].sum()
    score_E_ptf = (sec_list.loc[pd.notna(sec_list['ESG_E']), 'ESG_E'].dot(sec_list.loc[pd.notna(sec_list['ESG_E']), 'Weight']))/sec_list.loc[pd.notna(sec_list['ESG_E']), 'Weight'].sum()
    score_S_ptf = (sec_list.loc[pd.notna(sec_list['ESG_S']), 'ESG_S'].dot(sec_list.loc[pd.notna(sec_list['ESG_S']), 'Weight']))/sec_list.loc[pd.notna(sec_list['ESG_S']), 'Weight'].sum()
    score_G_ptf = (sec_list.loc[pd.notna(sec_list['ESG_G']), 'ESG_G'].dot(sec_list.loc[pd.notna(sec_list['ESG_G']), 'Weight']))/sec_list.loc[pd.notna(sec_list['ESG_G']), 'Weight'].sum()
    score_ESG_ptf = (sec_list.loc[pd.notna(sec_list['ESG_ANALYST_SCORE']), 'ESG_ANALYST_SCORE'].dot(sec_list.loc[pd.notna(sec_list['ESG_ANALYST_SCORE']), 'Weight']))/sec_list.loc[pd.notna(sec_list['ESG_ANALYST_SCORE']), 'Weight'].sum() """

    #with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #   df_concat[columns].to_excel(writer,index = False)

    sec_list.sort_values(by='Weight', ascending=False)
    sec_list['ptf_te'] = ptf_te

    sec_list['ptf_esg'] = sec_list['Weight'].dot(sec_list['ESG_ANALYST_SCORE'].fillna(2))
    sec_list['esg_min'] = esg_bench

    sec_list['dvd yield ptf'] = sec_list['Weight'].dot(sec_list['Dvd yield'].fillna(0))
    sec_list['dvd yield min'] = min_div_yield
    sec_list['dvd yield optim min'] = ineq[0]

    sec_list['earn yield ptf'] = sec_list['Weight'].dot(sec_list['Earnings yield'].fillna(0))
    sec_list['earn yield bench'] = earnings_yield_bench

    sec_list['beta'] = sec_list['Weight'].dot(sec_list['Beta'])

    sec_list['Carbon_int'] = sec_list['Weight'].dot(sec_list['Carbon Intensity'].fillna(300))
    sec_list['Carbon_int_max'] = max_carbon_intensity

    sec_list['nb_titres'] = len(sec_list)
    sec_list['Date'] = date

    sec_list['success_beta'] = success_beta
    sec_list['success_secto'] = success_secto
    sec_list['success_region'] = success_region
    sec_list['success_esg'] = success_esg
    sec_list['success_carbon_int'] = success_carbon_int
    if turnover[0] == 'Yes':
        success_turnover = True
        ptf_turnover = (compute_turnover(weights_optim,old_weight,in_ptf_turnover, turnover_cons) - turnover_cons) *(-1)
        if compute_turnover(weights_optim,old_weight,in_ptf_turnover, turnover_cons) > turnover_cons + 0.00001:
            success_turnover = False
        sec_list['ptf_turnover'] = ptf_turnover
        sec_list['success_turnover'] = success_turnover
        return sec_list[['Date', 'Name','Weight','ptf_te','ptf_esg','ptf_turnover','esg_min','dvd yield ptf','dvd yield min','earn yield ptf','earn yield bench','beta','Carbon_int','Carbon_int_max',
                     'success_beta','success_secto','success_region','success_esg','success_carbon_int','success_turnover','nb_titres']].reset_index()

    #os.mkdir('//groupe-ufg.com/commun/Prive/DIRR/Ingenierie Financiere/Alexandre H/MAI/tests spot/histo' + "/Pour " + date.strftime("%B %Y"))
    #ptf_result = [list(sec_list.index),list(sec_list['Name'].values),list(sec_list['Exchange Country Name'].values),list(sec_list['Region'].values),list(sec_list['Sector'].values),
    #        list(sec_list['Weight'].values),list(sec_list['ESG_E'].values),list(sec_list['ESG_S'].values),list(sec_list['ESG_G'].values),list(sec_list['ESG_ANALYST_SCORE'].values),
    #        list(sec_list['Dvd yield'].values),list(sec_list['Carbon Intensity'].values)]
    print(str(date), end="",flush=True)
    return sec_list[['Date', 'Name','Weight','ptf_te','ptf_esg','esg_min','dvd yield ptf','dvd yield min','earn yield ptf','earn yield bench','beta','Carbon_int','Carbon_int_max',
                     'success_beta','success_secto','success_region','success_esg','success_carbon_int','nb_titres']].reset_index()


@xl_macro('str screen, var[][] inclusion, var[][] exclusion, var[][] mf_formula, float[] max_mean_weights_values_region, str[] list_region, str critere_repechage, float[] max_mean_weights_values_secto, int[] list_secto, int[] top_companies, str returns, float[] pct_dvd_yield, float pct_carbon_intensity, float[] divide_lb, float[] multiply_ub, float min_weight, float max_weight, str[] liste repechage, str optim_type, float[] bucket_min_ub, float[][] min_ub_list, str liste_noire, float[] beta_target, float[] min_lb, str[] dates, var[] top_mandatory, str name_, var[] turnover')
def MAI_bt(screen_path, inclusion, exclusion, mf_formula, max_mean_weights_values_region, list_region,critere_repechage, max_mean_weights_values_secto,list_secto, top_companies, returns, pct_dvd_yield, pct_carbon_intensity, divide_lb, multiply_ub, min_weight, max_weight, liste_repechage, optim_type, bucket_min_ub, min_ub_list, liste_noire, beta_target,min_lb, dates,top3,name_, turnover):

    start_date = dates[0]
    end_date = dates[1]
    rebal = dates[2]

    all_screen = pd.read_pickle(screen_path)

    liste_noire = read_liste_noire([],[],liste_noire)
    returns = pd.read_pickle(returns)
    start_date=pd.to_datetime(start_date,dayfirst=True)
    end_date=pd.to_datetime(end_date,dayfirst=True)
    all_screen = all_screen.loc[(all_screen['Date'] >= start_date) & (all_screen['Date'] <= end_date)]
    all_screen = all_screen[all_screen['Weight in MSCI WORLD'] >0]
    unique_dates = all_screen['Date'].unique()
    cut_mkt_cap = [0.0002]*len(unique_dates)

    if rebal == "Monthly":
        screen_list = [all_screen.loc[all_screen['Date'] == date_] for date_ in unique_dates]
        cut_mkt_cap = cut_mkt_cap
        pct_dvd_yield = pct_dvd_yield
    elif rebal == "Quarterly":
        screen_list = [all_screen.loc[all_screen['Date'] == unique_dates[i]] for i in range(0,len(unique_dates),3)]
        cut_mkt_cap = [cut_mkt_cap[i] for i in range(0,len(cut_mkt_cap),3)]
        pct_dvd_yield = [pct_dvd_yield[i] for i in range(0,len(pct_dvd_yield),3)]

    if turnover[0] == 'No':
        turnover_list = [turnover]*len(screen_list)
    else:
        turnover_list = [['No', turnover[1]]]
        for i in range(1,len(screen_list)):
            if i % 3 ==0:
                turnover_list.append(['No', turnover[1]])
            else:
                turnover_list.append(['Yes', turnover[1]])
    liste_noire = [liste_noire]*len(screen_list)
    returns = [returns]*len(screen_list)
    inclusion = [inclusion]*len(screen_list)
    exclusion = [exclusion]*len(screen_list)
    mf_formula = [mf_formula]*len(screen_list)
    max_mean_weights_values_region = [max_mean_weights_values_region]*len(screen_list)
    list_region = [list_region]*len(screen_list)
    critere_repechage = [critere_repechage]*len(screen_list)
    max_mean_weights_values_secto = [max_mean_weights_values_secto]*len(screen_list)
    list_secto = [list_secto]*len(screen_list)
    top_companies = [top_companies]*len(screen_list)
    pct_carbon_intensity = [pct_carbon_intensity]*len(screen_list)
    divide_lb = [divide_lb]*len(screen_list)
    multiply_ub = [multiply_ub]*len(screen_list)
    min_weight = [min_weight]*len(screen_list)
    max_weight = [max_weight]*len(screen_list)
    liste_repechage = [liste_repechage]*len(screen_list)
    optim_type = [optim_type]*len(screen_list)
    bucket_min_ub = [bucket_min_ub]*len(screen_list)
    min_ub_list = [min_ub_list]*len(screen_list)
    beta_target = [beta_target]*len(screen_list)
    min_lb = [min_lb]*len(screen_list)
    top3 = [top3]*len(screen_list)

    parameters = np.array([screen_list, inclusion, exclusion,mf_formula, max_mean_weights_values_region, list_region,critere_repechage, 
    max_mean_weights_values_secto,list_secto, cut_mkt_cap, top_companies, returns, pct_dvd_yield, pct_carbon_intensity,
    divide_lb, multiply_ub, min_weight, max_weight, liste_repechage, optim_type, bucket_min_ub, min_ub_list, liste_noire, beta_target,min_lb,top3,turnover_list])
    parameters = parameters.transpose()

    output_file = '//groupe-ufg.com/commun/Prive/DIRR/Ingenierie Financiere/Alexandre H/MAI/BT_' + name_ + ".xlsx"
    # '//groupe-ufg.com/commun/Prive/DIRR/Ingenierie Financiere/Alexandre H/MAI/BT_'+ datetime.datetime.now().strftime("%Y%m%d%H%M%S") + ".xlsx"


    with Pool(os.cpu_count()-1) as p:
        result = p.starmap(MAI_sec_list_for_bt, [params for params in parameters])

    df = pd.concat(result, ignore_index=True)
    
    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       df.to_excel(writer,index = False)
       
    return 'BT saved in ' + output_file


def repechage_sec_list(sec_list,univ, weight_repart, max_mean_weights,critere_repechage, repechage_type):
    #weight_repart== weight_secto_bench index = n°secteur
    nb_titre_repart = sec_list.groupby(repechage_type).apply(lambda x: len(x))# Nb titres par secteurs
    missing_value = list(set(weight_repart.index) - set(nb_titre_repart.index)) # Donne les secteurs de l'univers non présent ds sec list en index
    fill_missing = [0.00000001]*len(missing_value)
    nb_titre_repart = pd.concat([nb_titre_repart, pd.Series(data=fill_missing, index = missing_value)])
    mean_weight = weight_repart / nb_titre_repart

    df_concat = copy.deepcopy(sec_list)
    repechage_values = mean_weight[(mean_weight > max_mean_weights)].index # Flag des secteurs ou le poids moyen des titres ds le secteur est > au max weight autorisé ou les secteurs avec 0 titres ds sec list
    if len(repechage_values)>0:
        for value in repechage_values:
            nb_repechage = ceil(weight_repart.loc[value]/max_mean_weights.loc[value] - nb_titre_repart.loc[value])
            df_repechage = copy.deepcopy(univ).reset_index()
            
            #df_repechage = boites de l'univers non présente en sec list
            df_repechage = (df_repechage[df_repechage['ISIN'].isin(list(set(univ.index) - set(sec_list.index)))]).set_index('ISIN')
            if nb_repechage > 0:
                df_concat = pd.concat([df_concat,repechage(df_repechage,repechage_type,value,critere_repechage,nb_repechage)])

    return df_concat

def repechage(df, col, filtre, critere, nb):

    if col != "No filter":
        # if col != 'Exchange Country Region':
        #     df = df[df['Exchange Country Name'] == 'UNITED STATES']
        df = df[df[col] == filtre]
    df_return = df.nlargest(nb, critere)
    df_return['Repechage'] = 1
    if col == 'Exchange Country Region':
        df_return['Raison repechage'] = 'Region'
    elif col == ' Benchmark ICB Supersector ':
        df_return['Raison repechage'] = 'Sector'
    else:
        df_return['Raison repechage'] = 'Top weights'
    return df_return

def read_liste_noire(override_exclusion, override_inclusion, file = r"\\groupe-ufg.com\Commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_BASE\_ ESG DATA\Liste_Noire_Exclusion.xlsx", key="ISIN"):

    # liste_noire= pd.read_excel(file,usecols='H,I,T')
    # multiple_isin = liste_noire.iloc[:,1].str.split(';',expand=True)
    # multiple_isin_flatten = multiple_isin.to_numpy().flatten()
    # multiple_isin_flatten = np.unique(multiple_isin_flatten.astype(str))
    # liste_noire = np.concatenate([liste_noire.iloc[1:,0].dropna().unique(),liste_noire.iloc[1:,1].dropna().unique(),liste_noire.iloc[:,2].dropna().unique(), multiple_isin_flatten])
    # liste_noire_tot = np.concatenate([liste_noire,np.array(override_exclusion)])
    # liste_noire_unique = np.unique(liste_noire_tot)
    # liste_noire_finale = list(set(liste_noire_unique) - set(override_inclusion))
    # return liste_noire_finale


    liste_noire = pd.read_excel(file)
    liste_noire = liste_noire.dropna(subset=key)[key].tolist()
    liste_noire_tot = np.concatenate([liste_noire,np.array(override_exclusion)])
    liste_noire_unique = np.unique(liste_noire_tot)
    liste_noire_finale = list(set(liste_noire_unique) - set(override_inclusion))
    return liste_noire_finale

def ewma_cov(ret, alpha = 0.98, freq_data = 252):
    [fenetre, nb_asset] = ret.shape
    lambda_tab = alpha ** np.arange(fenetre)[::-1]
    repeat_mean = np.tile(np.mean(ret,axis=0),fenetre).reshape((fenetre,nb_asset))
    data_centered = ret - repeat_mean
    repeat_lambda = np.tile(np.sqrt(lambda_tab.reshape(-1,1)),nb_asset).reshape((fenetre,nb_asset))
    ret_weighted = repeat_lambda * data_centered
    cov_ewma_brut = (1 - alpha) * (ret_weighted.T @ ret_weighted)
    cov_ewma = freq_data * cov_ewma_brut
    return cov_ewma

def compute_bench_returns(bench, returns, col_weights='Weight in MSCI WORLD', col_sort='Company SEDOL'):

    returns.sort_index(axis=1, inplace=True)
    weights = bench.sort_values(by=col_sort)[col_weights]
    """ weights_t = np.zeros(shape=(len(returns),len(weights)))
    for i in range(len(returns)-1,-1, -1):
        if i == len(returns)-1:
            weights_t[i] = weights.values
        else:
            weights_t[i] = weights[i+1]/(1+(returns.iloc[i+1,:]).values)
            weights_t[i] = weights_t[i]/weights_t[i].sum() """
    #return (returns*weights_t).sum(axis=1)
    return (returns.dot(weights.values))

def optim_mai(fun, x0, A_eq, A_ineq, eq, ineq, lb, ub, *args):

    """
    Fmincon function
    return np.array of weights
    """
    #bnds = lb et ub de chaque actifs 
    bnds=scipy.optimize.Bounds(lb, ub)
    # 1 contreaintes d'inegalités :  A.x-ineqb>=0
    ineq_cons = {'type': 'ineq',
             'fun' : lambda x: ((A_ineq @ x)-ineq)}
    # 1 contrainte d'égalité somme(x)=1 => somme(x)-1=0
    eq_cons = {'type': 'eq',
           'fun' : lambda x: (A_eq @ x)-eq}
           #'jac' : lambda x: np.ones(len(x)).reshape(1,-1)}
    res=scipy.optimize.minimize(fun,x0, args=(args),method='SLSQP',options = {'maxiter':50000,'ftol': 1e-9},bounds=bnds,constraints=[eq_cons,ineq_cons])
    return res.x

def optim_mai_turnover(fun, x0, A_eq, A_ineq, eq, ineq, lb, ub,ineq_turnover, old_weight,in_ptf, *args):

    """
    Fmincon function
    return np.array of weights
    """
    #bnds = lb et ub de chaque actifs 
    bnds=scipy.optimize.Bounds(lb, ub)
    # 1 contreaintes d'inegalités :  A.x-ineqb>=0
    ineq_cons = {'type': 'ineq',
             'fun' : lambda x: ((A_ineq @ x)-ineq)}
    ineq_quad = {'type': 'ineq',
             'fun' : compute_turnover,
             'args':(old_weight, in_ptf, ineq_turnover)}
    # 1 contrainte d'égalité somme(x)=1 => somme(x)-1=0
    eq_cons = {'type': 'eq',
           'fun' : lambda x: (A_eq @ x)-eq}
           #'jac' : lambda x: np.ones(len(x)).reshape(1,-1)}
    res=scipy.optimize.minimize(fun,x0, args=(args),method='SLSQP',options = {'maxiter':50000,'ftol': 1e-9},bounds=bnds, constraints=[eq_cons, ineq_cons, ineq_quad])
    return res.x

def compute_te(w_ptf, w_bench, cov, in_ptf):
    w_bench_copy = copy.deepcopy(w_bench)
    w_bench_copy[in_ptf] -= w_ptf
    w_excess = w_bench_copy *(-1)
    return np.sqrt(w_excess.transpose() @ cov @ w_excess)


def compute_turnover(weight, old_weight, in_ptf, ineq_turnover):

    weight_full = np.zeros(len(old_weight))
    weight_full[in_ptf] = weight
    return ineq_turnover - np.abs(old_weight - weight_full).sum()

#AJOUTER UN NOUVEAU BENCH DANS SCREEN AGGREGATE EN HISTO
def add_bench_to_screen(screen_path, new_bench,bench_name,col_isin,col_weight,col_date):

    screen = pd.read_excel(screen_path, header = 0, skiprows=[0,1,2,3,5], na_values=["@NA", "#N/A"])
    screen['Date_match'] = pd.to_datetime(screen['Date'])
    screen.dropna(subset='Date_match', inplace=True)
    screen['Date_match'] = screen['Date_match'].apply(lambda x: x + relativedelta.relativedelta(months=0,day=1))
    new_bench[col_date] = pd.to_datetime(new_bench[col_date])
    new_bench['Date_match'] = new_bench[col_date].apply(lambda x: x + relativedelta.relativedelta(months=0,day=1))
    screen[bench_name] = pd.merge(left=screen, right=new_bench, how = 'left', left_on = ['ISIN','Date_match'], right_on = [col_isin,'Date_match'])[col_weight]
    screen.drop(columns='Date_match',inplace=True)
    screen.to_excel(screen_path, na_rep="#N/A", startrow=4, index=False)
    return 0

def add_bench(screen_folder,new_bench_path,bench_name,col_isin,col_weight,col_date):

    new_bench = pd.read_excel(new_bench_path,sheet_name='Feuil1',header=0)
    new_bench.dropna(subset=col_isin, inplace=True)
    weight_sum = new_bench.groupby(col_date)[col_weight].sum()
    weight_sum.name='weight_sum'
    new_bench= pd.merge(left = new_bench, right = weight_sum, left_on = col_date, right_index=True)
    new_bench[col_weight] = new_bench[col_weight]/new_bench['weight_sum']
    new_bench = new_bench.groupby([col_date,col_isin]).aggregate({col_weight:np.sum}).reset_index()
    list_files = os.listdir(screen_folder)
    filelist = []
    for file in list_files:
        filelist.append(screen_folder+file)
    new_bench = [new_bench]*len(filelist)
    bench_name = [bench_name]*len(filelist)
    col_isin = [col_isin]*len(filelist)
    col_weight = [col_weight]*len(filelist)
    col_date = [col_date]*len(filelist)

    parameters = np.array([filelist, new_bench, bench_name, col_isin, col_weight, col_date], dtype=object)
    parameters = np.array(parameters).transpose()

    with Pool(20) as p:
        result = p.starmap(add_bench_to_screen, [params for params in parameters])

    #df = pd.concat(result)
    #df.dropna(subset='Date', inplace=True)
    return 0

#FILL DONNEES ESG DANS SCREEN AGGREGATE EN HISTO
def add_esg_to_screen(screen_path, esg_data,e_col,s_col,g_col,esg_col,carbon_int_col,col_isin, col_date):

    screen = pd.read_excel(screen_path, header = 0, skiprows=[0,1,2,3,5], na_values=["@NA", "#N/A"])
    screen['Date_match'] = pd.to_datetime(screen['Date'])
    screen.dropna(subset='Date_match', inplace=True)
    screen['Date_match'] = screen['Date_match'].apply(lambda x: x + relativedelta.relativedelta(months=1,day=1))
    screen = pd.merge(left=screen, right=esg_data, how = 'left', left_on = ['ISIN','Date_match'], right_on = [col_isin,col_date])
    screen['ESG_E'] = screen[e_col]
    screen['ESG_S'] = screen[s_col]
    screen['ESG_G'] = screen[g_col]
    screen['ESG_ANALYST_SCORE'] = screen[esg_col]
    screen['CarbonIntensity_Sales'] = screen[carbon_int_col]
    screen.drop(columns=['Date_match',e_col,s_col,g_col,esg_col,carbon_int_col,col_isin,col_date],inplace=True)
    screen.to_excel(screen_path, na_rep="#N/A", startrow=4, index=False)
    return 0

def add_esg(screen_folder,esg_path,e_col,s_col,g_col,esg_col,carbon_int_col,col_date,col_isin):

    esg_data = pd.read_excel(esg_path,header=0,usecols='A,B,P:S,T')
    esg_data[col_date] = pd.to_datetime(esg_data[col_date], format='%Y%m%d')
    unique_isin = list(esg_data[col_isin].unique())
    unique_dates = esg_data[col_date].unique()
    isin_new = unique_isin*len(unique_dates)
    dates_new = np.array([[unique_dates[i]]*len(unique_isin) for i in range(len(unique_dates))]).reshape(1,-1)[0]
    dates_new.sort()
    new_esg_data = pd.DataFrame()
    new_esg_data[col_date] = dates_new
    new_esg_data[col_isin] = isin_new
    new_esg_data = new_esg_data.merge(esg_data[[e_col,s_col,g_col,esg_col,carbon_int_col,col_date,col_isin]], how='left', on = [col_date,col_isin])
    new_esg_data[carbon_int_col] = new_esg_data.groupby(col_isin)[carbon_int_col].fillna(method='bfill')

    list_files = os.listdir(screen_folder)
    filelist = []
    for file in list_files:
        filelist.append(screen_folder+file)
    new_esg_data = [new_esg_data]*len(filelist)
    e_col = [e_col]*len(filelist)
    s_col = [s_col]*len(filelist)
    g_col = [g_col]*len(filelist)
    esg_col = [esg_col]*len(filelist)
    carbon_int_col = [carbon_int_col]*len(filelist)
    col_isin = [col_isin]*len(filelist)
    col_date = [col_date]*len(filelist)

    parameters = np.array([filelist, new_esg_data, e_col, s_col, g_col, esg_col,carbon_int_col,col_isin,col_date], dtype=object)
    parameters = np.array(parameters).transpose()

    with Pool(20) as p:
        result = p.starmap(add_esg_to_screen, [params for params in parameters])

    #df = pd.concat(result)
    #df.dropna(subset='Date', inplace=True)
    return 0


def sec_list_tilt_to(screen, region, output_dir, percentile, cut_mkt_cap, metrics, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire, old_ptf, out_threshold,
                  reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], reco_facto=[0,0,0,0,0]):

    list_score_col = metrics
    list_style = ['Growth Avg Percentile','LowVol Avg Percentile','Mom Avg Percentile','Quality Avg Percentile','Value Avg Percentile']
    reco_facto = np.array(reco_facto,dtype='float')
    if reco_facto.sum() == 0:
        reco_facto = np.array([0.2]*5)
    else:
        # reco_facto = np.array([0.225,0.225,0.225,0.225,0.1])
        # reco_facto[reco_facto==1] = 0.3
        reco_facto[reco_facto==1] = 0.35
        reco_facto[reco_facto==0] = 0.1
        reco_facto = reco_facto/reco_facto.sum()
    # reco_facto = pd.Series(data = reco_facto, index=['Growth Avg Percentile','LowVol Avg Percentile','Mom Avg Percentile','Quality Avg Percentile','Value Avg Percentile'])
    # pool_facto = list(reco_facto[reco_facto==1].index)

    df = screen
    #esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    df=df[df['Weight in MSCI ACWI']>0]
    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in MSCI ACWI'])

    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        mkt_cap_min = 2000
        output_file = output_dir +"/Mom EBITDA margin EU.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        mkt_cap_min = 4000
        output_file = output_dir +"/Mom EBITDA margin US.xlsx"
    
    if cut_mkt_cap > 0:
        mkt_cap_min = cut_mkt_cap

    df['Multi Avg Percentile'] = df[list_style].mean(skipna= False, axis=1)
    df['Multi Avg Percentile 2'] = df[list_style].dot(reco_facto)
    df.loc[df['Benchmark Market Value Millions in EUR'] <= mkt_cap_min, list_score_col] = np.NaN
    #list_score_col.append("Multi Avg Percentile")

    # if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
    #     os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))

    df['Date'] = date

    if ponderation == "Racine cube":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/3)
    elif ponderation == "Racine carrée":
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR']**(1/2)
    elif ponderation == "Log":
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])
    elif ponderation == "Equalweight":
        df['Benchmark Market Value Millions in EUR'] = 1/len(df)

    if weight_neutral == "ICB 19":
        weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
        icb_missing = set([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]) - set(df[' Benchmark ICB Supersector '].unique())
        if len(icb_missing) > 0:
            for icb19 in icb_missing:
                reco_secto = np.delete(np.array(reco_secto),int(icb19) - 1)
        weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1)
        weight_secto_bench[weight_secto_bench<0.0025] = 0.0025

    elif weight_neutral == "ICB 11":
        weight_secto_bench = df.groupby(' Benchmark ICB Industry ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum()
    max_mean_weights = pd.Series(data = [0.04]*len(weight_secto_bench), index = weight_secto_bench.index)

    df[list_score_col] = df[list_score_col].rank(pct=True)
    df[list_score_col] = (df[list_score_col] - df[list_score_col].min())/(df[list_score_col].max() - df[list_score_col].min())

    if score_neutral == "ICB 11":
        for secto in df[' Benchmark ICB Industry '].unique():
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Industry '] == secto, list_score_col].min())
    elif score_neutral == "ICB 19":
        for secto in df[' Benchmark ICB Supersector '].unique():
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].rank(pct=True)
            df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] = (df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col] - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())/(df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].max() - df.loc[df[' Benchmark ICB Supersector '] == secto, list_score_col].min())

    # nb_securities = round(len(df.loc[pd.isna(df['Multi Avg Percentile']) == False])*(0.8))
    # df=df.nlargest(nb_securities,'Multi Avg Percentile')

    df_esg = copy.deepcopy(df)
    df_esg_2 = copy.deepcopy(df)
    if date.year >= 2017:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        carbon_pct = df['CarbonIntensity_Sales'].rank(pct=True)
        #df_esg = df_esg[~(df_esg.index.isin(liste_noire))]
        #df_esg = df.loc[(esg_pct >= esg_exclusion)]
        df_esg_2=df.loc[(esg_pct >= esg_exclusion)*(carbon_pct < 0.95)]

    univ = copy.deepcopy(df_esg_2)
    if old_ptf is not None:
        # if reco_facto.sum()!=0:
        #     condition = [False]*len(univ)
        #     for i, factor in enumerate(pool_facto):
        #         if i == 0:
        #             condition = univ[factor]>=(10*(1-2*percentile))
        #         else:
        #             condition = condition | (univ[factor]>=(10*(1-2*percentile)))
        #     univ = univ.loc[condition]

        univ = univ[~(univ.index.isin(old_ptf['ISIN'].values))]
        ptf_init = df_esg_2[(df_esg_2.index.isin(old_ptf['ISIN'].values))]
        ptf_init = ptf_init[ptf_init[list_score_col[0]]>=out_threshold]
        ptf_init['Repechage'] = 0
        ptf_init['Raison repechage'] = '-'

    columns = ['PTF', 'ISIN', 'Weight', 'Date']
    df_concat = pd.DataFrame()
    for i in range(len(list_score_col)):
        nb_securities = round(len(df_esg.loc[pd.isna(df_esg[list_score_col[i]]) == False])*percentile)
        if old_ptf is not None:
            nb_repechage = max(nb_securities-len(ptf_init),0)
            if nb_repechage>0:
                new_stocks = univ.nlargest(nb_repechage,'Multi Avg Percentile 2')
                new_stocks['Repechage'] = 1
                new_stocks['Raison repechage'] = 'New Q1'
                df_top = pd.concat([ptf_init, new_stocks],axis=0)
            else:
                df_top = ptf_init
        else:
            df_top = univ.nlargest(nb_securities,list_score_col[i])
            df_top['Repechage'] = 0
            df_top['Raison repechage'] = '-'

        weight_repart = weight_secto_bench
        df_top = repechage_sec_list(df_top, univ, weight_repart, max_mean_weights, 'Multi Avg Percentile 2', ' Benchmark ICB Supersector ')

        temp_df = pd.DataFrame(columns = columns)
        temp_df['ISIN'] = df_top.index
        if weight_neutral == "ICB 19":
            temp_df['Secto'] = df_top[' Benchmark ICB Supersector '].values
        elif weight_neutral == "ICB 11":
            temp_df['Secto'] = df_top[' Benchmark ICB Industry '].values
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values
        temp_df['Score'] = df_top[list_score_col[i]].values
        temp_df['PTF'] = ptf_name[i]
        temp_df['Date'] = date
        temp_df['Repechage'] = df_top['Repechage'].values
        temp_df['Raison repechage'] = df_top['Raison repechage'].values
        
        if weight_neutral != "No":
            for secto in temp_df['Secto'].unique():
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] / temp_df['Weight'].sum()
                temp_df.loc[temp_df['Secto'] == secto, 'Weight'] = temp_df.loc[temp_df['Secto'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / temp_df.loc[temp_df['Secto'] == secto, 'Weight'].sum())
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()
        df_concat = pd.concat([df_concat,temp_df], ignore_index=True)

    #with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #   df_concat[columns].to_excel(writer,index = False)
    print(len(df_concat))
    return df_concat


def sec_list_histo_tilt(screen_path, region, output_dir, percentile, cut_mkt_cap, metrics, ptf_name, score_neutral, weight_neutral, ponderation,esg_cut,liste_noire,reco_secto,reco_facto,out_threshold_old,out_threshold_new, start_date=datetime.date(2004,12,31), end_date=datetime.date.today(), rebal= "Monthly"):

    all_screen = pd.read_pickle(screen_path)

    start_date=pd.to_datetime(start_date)
    end_date=pd.to_datetime(end_date)
    all_screen = all_screen.loc[(all_screen['Date'] >= start_date) & (all_screen['Date'] <= end_date)]
    all_screen = all_screen[all_screen['Weight in MSCI ACWI'] >0]
    unique_dates = all_screen['Date'].unique()
    cut_mkt_cap = cut_mkt_cap[len(cut_mkt_cap) - len(unique_dates):]
    liste_noire = read_liste_noire([],[], liste_noire)

    if rebal == "Monthly":
        screen_list = [all_screen.loc[all_screen['Date'] == date_] for date_ in unique_dates]
        cut_mkt_cap_list = cut_mkt_cap
    elif rebal == "Quarterly":
        screen_list = [all_screen.loc[all_screen['Date'] == unique_dates[i]] for i in range(0,len(unique_dates),3)]
        cut_mkt_cap_list = [cut_mkt_cap[i] for i in range(0,len(cut_mkt_cap),3)]

    #list_style = ['Growth Avg Percentile','LowVol Avg Percentile','Mom Avg Percentile','Quality Avg Percentile','Value Avg Percentile']
    result=[]
    for i in range(len(screen_list)):
        reco_facto_t = np.array(reco_facto[i],dtype='float')
        if i == 0:
            old_ptf= None
        else:
            old_ptf = result[i-1]
            # if reco_facto_t.sum() == 0:
            #     old_ptf = old_ptf[old_ptf['Score']>=out_threshold_old]
            # else:
            #     # reco_facto_t = np.array([0.225,0.225,0.225,0.225,0.1])
            #     reco_facto_t[reco_facto_t==1] = 0.3
            #     reco_facto_t[reco_facto_t==0] = 0.13
            #     reco_facto_t = reco_facto_t/reco_facto_t.sum()
            #     old_ptf.set_index('ISIN', inplace=True)
            #     old_ptf['Score'] = screen_list[i-1][list_style].dot(reco_facto_t)
            #     old_ptf.reset_index(inplace=True)
            old_ptf = old_ptf[old_ptf['Score']>=out_threshold_old]
        result.append(sec_list_tilt_to(screen_list[i], region, output_dir, percentile, cut_mkt_cap_list[i], metrics, ptf_name, score_neutral, weight_neutral,
                                        ponderation, esg_cut, liste_noire, old_ptf, out_threshold_new,reco_secto[i], reco_facto_t))

    output_file = output_dir + "/output_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + ".xlsx"

    df = pd.concat(result, ignore_index=True)
    
    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
       df.to_excel(writer,index = False)
       
    return "Sec list generated successfully in " + output_file


def optim_mai_te_constr(fun, x0, A_eq, A_ineq, eq, ineq, lb, ub,ineq_te, weight_bench, ewma_cov_mat, in_ptf, *args):

    """
    Fmincon function
    return np.array of weights
    """
    #bnds = lb et ub de chaque actifs 
    bnds=scipy.optimize.Bounds(lb, ub)
    # 1 contreaintes d'inegalités :  A.x-ineqb>=0
    ineq_cons = {'type': 'ineq',
             'fun' : lambda x: ((A_ineq @ x)-ineq)}
    ineq_quad = {'type': 'ineq',
             'fun' : lambda x: -compute_te(x,weight_bench, ewma_cov_mat, in_ptf) + ineq_te}
             #'args':(weight_bench, ewma_cov_mat, in_ptf)}
    # 1 contrainte d'égalité somme(x)=1 => somme(x)-1=0
    eq_cons = {'type': 'eq',
           'fun' : lambda x: (A_eq @ x)-eq}
           #'jac' : lambda x: np.ones(len(x)).reshape(1,-1)}
    res=scipy.optimize.minimize(fun, x0, args=(args),method='SLSQP',options = {'maxiter':1000,'ftol': 1e-9},bounds=bnds, constraints=[eq_cons, ineq_cons, ineq_quad])
    return res.x, res.success


@xl_macro('str screen_agg, str output_dir, str critere_repechage, float[] max_mean_weights_values_secto, int[] list_secto, str returns, str liste_repechage, str liste_noire, int nb_titres, float max_te, float esg_exclusion, str bench')
def sec_list_ML_EU(screen_agg, output_dir, critere_repechage, max_mean_weights_values_secto,list_secto, returns,liste_repechage, liste_noire, nb_titres, max_te, esg_exclusion, bench = 'STOXX EUROPE 600', export_excel = True):

    #Liste des régions autorisées
    max_mean_weights_s = pd.Series(data = max_mean_weights_values_secto, index = list_secto)
    # transpa_secto = pd.Series(data = ['Auto & Parts','Banks','Basic Resources','Chemicals','Construction & Materials','Financial Services','Food, Beverage & Tobacco','Health Care','Industrial Goods & Services',
    #                                   'Insurance','Media','Energy','Personal & Household Goods','Real Estate','Retail','Technology','Telecommunications','Travel & Leisure','Utilities'],
    #                                   index= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], name='transpa_secto')
    if type(liste_repechage)!=list:
        liste_repechage = [liste_repechage]
    #Lecture screen et returns
    if type(returns) == str:
        returns = pd.read_pickle(returns)
    if type(liste_noire) == str:
        liste_noire = read_liste_noire([],[],liste_noire)
    if type(screen_agg) == str:
        screen_agg = pd.read_pickle(screen_agg)

    df = screen_agg[screen_agg['Date'] == screen_agg['Date'].max()]
    df = df.loc[~df.index.duplicated(keep='first')]

    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)  #date de rebal 1ere date next month
    date_return = date +  relativedelta.relativedelta(years=-2)
    returns = returns[(returns.index>=date_return)&(returns.index<date)]


    Filter_common_SEDOL = True
    if Filter_common_SEDOL:
        # Find common stocks between screen and returns
        common_sedols = list(set(df['Company SEDOL'].dropna().values).intersection(set(returns.columns)))
        print(f"Found {len(common_sedols)} common stocks between screen and returns")
        
        # Filter returns to only include these stocks
        returns = returns[common_sedols]
        returns = returns.loc[:, ~returns.columns.duplicated()]
        
        # Filter df to only include stocks with returns data if needed
        df = df[df['Company SEDOL'].isin(common_sedols)]
        print(f"After filtering for common stocks: {len(df)} stocks remaining")


    if export_excel:
        if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y").capitalize()):
            os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y").capitalize())
        output_file = output_dir +"/Pour " + date.strftime("%B %Y").capitalize()+"/ML ESG EU.xlsx"

    #Cleaning du benchmark
    df = df[df['Weight in ' + bench]>0]
    df = df[df['Company SEDOL'].notna()].sort_index()
    df['Weight in univ norm'] = df['Weight in ' + bench]/df['Weight in ' + bench].sum()
    df.rename(columns={'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector ICB19'}, inplace=True)

    df['lb'] = 0
    df['ub'] = df['Weight in univ norm'].apply(compute_ub) #pour définir les ub en fonctions des poids initiaux si optim

    #Poids par zone géo et par secteur du bench, dvd yield moyen et carbon intensity moyenne du bench
    weight_secto_bench = df.groupby('Sector ICB19')['Weight in univ norm'].sum() / df['Weight in univ norm'].sum()

    #Renormalisation des scores par zone géo (uniformes [0:1])
    #df['Multi Avg Percentile'] = df['Score ML']

    #on copie le bench (df) dans une nouvelle variable univers (univ)
    #Univ correspond au bench - exclusion esg - exclusion liste noire. Sert pour le repêchage
    df_esg = copy.deepcopy(df)
    if date.year >= 2017:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        df_esg=df.loc[(esg_pct >= esg_exclusion)]
        #df_esg = df_esg[~(df_esg.index.isin(liste_noire))]

    univ = copy.deepcopy(df_esg)
    df_filtered = copy.deepcopy(df_esg)
    # univ = univ[~(univ.index.isin(liste_noire))]

    df_filtered['Repechage'] = 0
    df_filtered['Raison repechage'] = ''
    df_filtered = df_filtered.nlargest(nb_titres, critere_repechage) #pour ne selectionner que les nlargest titres selon la colonne spécifiée

    #Check nb titres sur les régions, repêchage si nécessaire
    for repechage_type in liste_repechage:
        # if repechage_type == 'Exchange Country Region':
        #     weight_repart = weight_region_bench
        #     max_mean_weights = max_mean_weights_r
        #     df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,repechage_type)
        if repechage_type == 'Sector ICB19':
            weight_repart = weight_secto_bench
            max_mean_weights = max_mean_weights_s
            df_filtered = repechage_sec_list(df_filtered, univ, weight_repart, max_mean_weights, critere_repechage, repechage_type)

    #Matrice de covariance de la sec list

    # Find commun between df['Company SEDOL'] and returns.columns 
    common_sedols = list(set(df['Company SEDOL'].values).intersection(set(returns.columns)))
    
    # Only use SEDOL in commun
    returns = returns[common_sedols]

    # returns = returns[df['Company SEDOL'].values]
    returns = returns.loc[:,~returns.columns.duplicated()]
    #bench_returns = compute_bench_returns(df,returns)
    #df.reset_index(inplace=True)
    #df['Beta'] = df['ISIN'].apply(lambda x: linregress(bench_returns.values, returns[df.loc[df['ISIN'] == x,'Company SEDOL'].values[0]]).slope)
    #df.set_index('ISIN',inplace=True)
    #df_filtered['Beta'] = df['Beta']
    ewma_cov_mat = ewma_cov(returns, 0.98)

    #Sec list finale pour l'optim
    columns_optim = ['Name','Exchange Country Name', 'Weight in univ norm', 'Region', 'Sector ICB19', critere_repechage, 'lb', 'ub', 'Repechage', 'Raison repechage']

    sec_list = df_filtered[columns_optim].sort_index()

    sec_list.rename(columns={'Weight in univ norm':'Weight','Sector ICB19':'Sector'}, inplace=True)
    weight_bench = df['Weight in univ norm']
    in_ptf = weight_bench.reset_index()['ISIN'].apply(lambda x: x in sec_list.index)

    #Bornes secto et bornes region
    max_secto = sec_list.groupby('Sector')['ub'].sum()
    min_secto = sec_list.groupby('Sector')['lb'].sum()
    # max_region = sec_list.groupby('Region')['ub'].sum()
    # min_region = sec_list.groupby('Region')['lb'].sum()

    lb_secto = weight_secto_bench - 0.05
    ub_secto = weight_secto_bench + 0.05
    # lb_region = weight_region_bench - 0.02
    # ub_region = weight_region_bench + 0.02
    lb_secto[lb_secto<0] = 0
    #lb_region[lb_region<0] = 0

    missing_secto = list(set(list_secto) - set(max_secto.index)) #si secteur existe pas ds seclist on le rajoute a la liste de secteur
    if len(missing_secto)>0:
        fill_missing = [0] * len(missing_secto)
        max_secto=(pd.concat([max_secto, pd.Series(data=fill_missing, index = missing_secto)])).sort_index()
        min_secto=(pd.concat([min_secto, pd.Series(data=fill_missing, index = missing_secto)])).sort_index()
        
    lb_secto = np.minimum(np.array(lb_secto), max_secto)
    ub_secto = np.maximum(np.array(ub_secto), min_secto)
    # lb_region = np.minimum(np.array(lb_region), max_region)
    # ub_region = np.maximum(np.array(ub_region), min_region)

    #Création matrice themes et vecteur ineq pour contraintes d'inégalités : A.x - b >= 0
    #theme_region = transform_flag_to_theme(sec_list['Region'], list_flag=list(weight_region_bench.index))
    theme_secto = transform_flag_to_theme(sec_list['Sector'], list_flag=list(weight_secto_bench.index))
    x0 = ((sec_list['lb']+sec_list['ub'])/2).values
    A_ineq = np.concatenate((theme_secto, theme_secto*(-1)), axis=0)
    ineq = np.concatenate((lb_secto, ub_secto*(-1)), axis=0)
    A_eq = np.ones(len(x0)).reshape(1,-1)
    eq = [1]
    ineq_te = max_te

    success = False
    while success == False:
        weights_optim, success = optim_mai_te_constr(max_score, x0, A_eq, A_ineq, eq, ineq, sec_list['lb'], sec_list['ub'], ineq_te, weight_bench.values, ewma_cov_mat, in_ptf, sec_list[critere_repechage])
        ineq_te += 0.002

    ptf_te = compute_te(weights_optim, weight_bench.values, ewma_cov_mat, in_ptf)
    sec_list['Weight'] = weights_optim
    sec_list = sec_list[sec_list['Weight']>= 0.001]  ### this filter the most of companies
    sec_list['Weight'] /= sec_list['Weight'].sum()

    #with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #   df_concat[columns].to_excel(writer,index = False)

    sec_list.sort_values(by='Weight', ascending=False,inplace=True)
    sec_list['ptf_te'] = ptf_te
    sec_list['Nb titres'] = len(sec_list)

    sec_list['Date'] = date
    sec_list['PTF'] = 'ML_ESG_EU'

    columns = ['PTF', 'ISIN', 'Weight', 'Date']

    if export_excel:
        with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
            sec_list.reset_index()[columns].to_excel(writer,index = False)

        return "ptf ML Europe generated successfully in " + output_file
    else:
        return sec_list.reset_index()

@xl_macro('str screen_agg, str output_dir, float perc, str critere, str bench')
def worst_list_ML_EU(screen_agg, output_dir, perc, critere, bench = 'STOXX EUROPE 600',export_excel = True):

    # transpa_secto = pd.Series(data = ['Auto & Parts','Banks','Basic Resources','Chemicals','Construction & Materials','Financial Services','Food, Beverage & Tobacco','Health Care','Industrial Goods & Services',
    #                                   'Insurance','Media','Energy','Personal & Household Goods','Real Estate','Retail','Technology','Telecommunications','Travel & Leisure','Utilities'],
    #                                   index= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], name='transpa_secto')
    #Lecture screen et returns
    if type(screen_agg) == str:
        screen_agg = pd.read_pickle(screen_agg)

    df = screen_agg[screen_agg['Date'] == screen_agg['Date'].max()]

    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    if export_excel:
        if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
            os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))
        output_file = output_dir +"/Pour " + date.strftime("%B %Y")+"/WORST ML EU.xlsx"

    #Cleaning du benchmark
    df = df[df['Weight in ' + bench]>0]
    df = df[df['Company SEDOL'].notna()].sort_index()
    df['Weight in univ norm'] = df['Weight in ' + bench]/df['Weight in ' + bench].sum()
    df.rename(columns={'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector ICB19'}, inplace=True)

    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in univ norm'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in univ norm'])

    #Poids par zone géo et par secteur du bench, dvd yield moyen et carbon intensity moyenne du bench
    weight_secto_bench = df.groupby('Sector ICB19')['Weight in univ norm'].sum() / df['Weight in univ norm'].sum()

    col_to_keep = ['Sector ICB19', 'Benchmark Market Value Millions in EUR']
    worst_list = df.loc[df[critere] <= perc*10, col_to_keep].reset_index()

    worst_list.rename(columns={'Sector ICB19':'Sector'}, inplace=True)

    worst_list['Weight'] = (worst_list['Benchmark Market Value Millions in EUR']**(1/3)).values
    worst_list['PTF'] = 'Worst_ML_EU'
    worst_list['Date'] = date
    for secto in worst_list['Sector'].unique():
        worst_list.loc[worst_list['Sector'] == secto, 'Weight'] = worst_list.loc[worst_list['Sector'] == secto, 'Weight'] / worst_list['Weight'].sum()
        worst_list.loc[worst_list['Sector'] == secto, 'Weight'] = worst_list.loc[worst_list['Sector'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / worst_list.loc[worst_list['Sector'] == secto, 'Weight'].sum())
    worst_list['Weight'] = worst_list['Weight'] / worst_list['Weight'].sum()

    columns = ['PTF', 'ISIN', 'Weight', 'Date']
    if export_excel:
        with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
            worst_list[columns].to_excel(writer,index = False)

        return "worst ML Europe generated successfully in " + output_file
    else:
        return worst_list.reset_index()


def compute_ub(w_bench):
    if w_bench>=0.01:
        return 0.04
    if w_bench>=0.005:
        return 0.03
    if w_bench>=0.002:
        return 0.02
    if w_bench>=0.001:
        return 0.015
    if w_bench>=0:
        return 0.01


def sec_list_TE_optim(screen_agg, output_dir, critere_repechage, max_mean_weights_values_secto,list_secto, returns,liste_repechage, top_mandatory, liste_noire, nb_titres, max_te, esg_exclusion, bench = 'STOXX EUROPE 600', export_excel = True):

    #Liste des régions autorisées
    max_mean_weights_s = pd.Series(data = max_mean_weights_values_secto, index = list_secto)
    # transpa_secto = pd.Series(data = ['Auto & Parts','Banks','Basic Resources','Chemicals','Construction & Materials','Financial Services','Food, Beverage & Tobacco','Health Care','Industrial Goods & Services',
    #                                   'Insurance','Media','Energy','Personal & Household Goods','Real Estate','Retail','Technology','Telecommunications','Travel & Leisure','Utilities'],
    #                                   index= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], name='transpa_secto')
    if type(liste_repechage)!=list:
        liste_repechage = [liste_repechage]
    #Lecture screen et returns
    if type(returns) == str:
        returns = pd.read_pickle(returns)
    if type(liste_noire) == str:
        liste_noire = read_liste_noire([],[],liste_noire)
    if type(screen_agg) == str:
        screen_agg = pd.read_pickle(screen_agg)

    df = screen_agg[screen_agg['Date'] == screen_agg['Date'].max()]
    df = df.loc[~df.index.duplicated(keep='first')]

    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)  #date de rebal 1ere date next month
    date_return = date +  relativedelta.relativedelta(years=-2)
    returns = returns[(returns.index>=date_return)&(returns.index<date)]

    if export_excel:
        if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y").capitalize()):
            os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y").capitalize())
        output_file = output_dir +"/Pour " + date.strftime("%B %Y").capitalize()+"/ML ESG EU.xlsx"

    #Cleaning du benchmark
    df = df[df['Weight in ' + bench]>0]
    df = df[df['Company SEDOL'].notna()].sort_index()
    df['Weight in univ norm'] = df['Weight in ' + bench]/df['Weight in ' + bench].sum()
    df.rename(columns={'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector ICB19'}, inplace=True)

    df['lb'] = 0
    df['ub'] = df['Weight in univ norm'].apply(compute_ub) #pour définir les ub en fonctions des poids initiaux si optim
    # df['ub'] = 0.05
    
    #Poids par zone géo et par secteur du bench, dvd yield moyen et carbon intensity moyenne du bench
    weight_secto_bench = df.groupby('Sector ICB19')['Weight in univ norm'].sum() / df['Weight in univ norm'].sum()

    #Renormalisation des scores par zone géo (uniformes [0:1])
    #df['Multi Avg Percentile'] = df['Score ML']

    #on copie le bench (df) dans une nouvelle variable univers (univ)
    #Univ correspond au bench - exclusion esg - exclusion liste noire. Sert pour le repêchage
    df_esg = copy.deepcopy(df)
    if date.year >= 2017:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        df_esg=df.loc[(esg_pct >= esg_exclusion)]
        #df_esg = df_esg[~(df_esg.index.isin(liste_noire))]

    univ = copy.deepcopy(df_esg)
    df_filtered = copy.deepcopy(df_esg)
    # univ = univ[~(univ.index.isin(liste_noire))]

    # On choisit les X plus gros boites
    if top_mandatory != 0:
        top_weight_list  = univ.nlargest(top_mandatory,'Weight in ' + bench)
        top_weight_list.loc[:,'Repechage'] = 1
        top_weight_list.loc[:,'Raison repechage'] = 'Top mandatory'
        top_weight_list = top_weight_list.reset_index()

    nb_titres = (nb_titres - len(top_weight_list))

    df_remaining = df_filtered[~df_filtered['Company SEDOL'].isin(top_weight_list['Company SEDOL'])]
    df_filtered_with_critere = df_remaining.nlargest(nb_titres, critere_repechage) #pour ne selectionner que les nlargest titres selon la colonne spécifiée
    df_filtered_with_critere['Repechage'] = 0
    df_filtered_with_critere['Raison repechage'] = ''
    df_filtered_with_critere = df_filtered_with_critere.reset_index()

    df_filtered = pd.concat([df_filtered_with_critere, top_weight_list], ignore_index=True)
    df_filtered = df_filtered.set_index("ISIN")

    #Check nb titres sur les régions, repêchage si nécessaire
    for repechage_type in liste_repechage:
        # if repechage_type == 'Exchange Country Region':
        #     weight_repart = weight_region_bench
        #     max_mean_weights = max_mean_weights_r
        #     df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,repechage_type)
        if repechage_type == 'Sector ICB19':
            weight_repart = weight_secto_bench
            max_mean_weights = max_mean_weights_s
            df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,repechage_type)
            df_filtered = df_filtered.reset_index()

    df_filtered = df_filtered.drop_duplicates(subset=['Company SEDOL'])
    df_filtered = df_filtered.dropna(subset=critere_repechage)
    df_filtered = df_filtered.set_index('ISIN')

    #Matrice de covariance de la sec list
    returns = returns[df['Company SEDOL'].values]
    returns = returns.loc[:,~returns.columns.duplicated()]
    #bench_returns = compute_bench_returns(df,returns)
    #df.reset_index(inplace=True)
    #df['Beta'] = df['ISIN'].apply(lambda x: linregress(bench_returns.values, returns[df.loc[df['ISIN'] == x,'Company SEDOL'].values[0]]).slope)
    #df.set_index('ISIN',inplace=True)
    #df_filtered['Beta'] = df['Beta']
    ewma_cov_mat = ewma_cov(returns, 0.98)

    #Sec list finale pour l'optim
    columns_optim = ['Name','Exchange Country Name', 'Weight in univ norm', 'Region', 'Sector ICB19', critere_repechage, 'lb', 'ub', 'Repechage', 'Raison repechage']

    sec_list = df_filtered[columns_optim].sort_index()

    sec_list.rename(columns={'Weight in univ norm':'Weight','Sector ICB19':'Sector'}, inplace=True)
    weight_bench = df['Weight in univ norm']
    in_ptf = weight_bench.reset_index()['ISIN'].apply(lambda x: x in sec_list.index)

    #Bornes secto et bornes region
    max_secto = sec_list.groupby('Sector')['ub'].sum()
    min_secto = sec_list.groupby('Sector')['lb'].sum()
    # max_region = sec_list.groupby('Region')['ub'].sum()
    # min_region = sec_list.groupby('Region')['lb'].sum()

    lb_secto = weight_secto_bench - 0.01
    ub_secto = weight_secto_bench + 0.01
    # lb_region = weight_region_bench - 0.02
    # ub_region = weight_region_bench + 0.02
    lb_secto[lb_secto<0] = 0
    #lb_region[lb_region<0] = 0

    missing_secto = list(set(list_secto) - set(max_secto.index)) #si secteur existe pas ds seclist on le rajoute a la liste de secteur
    if len(missing_secto)>0:
        fill_missing = [0] * len(missing_secto)
        max_secto=(pd.concat([max_secto, pd.Series(data=fill_missing, index = missing_secto)])).sort_index()
        min_secto=(pd.concat([min_secto, pd.Series(data=fill_missing, index = missing_secto)])).sort_index()
    lb_secto = np.minimum(np.array(lb_secto), max_secto)
    ub_secto = np.maximum(np.array(ub_secto), min_secto)
    # lb_region = np.minimum(np.array(lb_region), max_region)
    # ub_region = np.maximum(np.array(ub_region), min_region)

    #Création matrice themes et vecteur ineq pour contraintes d'inégalités : A.x - b >= 0
    #theme_region = transform_flag_to_theme(sec_list['Region'], list_flag=list(weight_region_bench.index))
    theme_secto = transform_flag_to_theme(sec_list['Sector'], list_flag=list(weight_secto_bench.index))
    x0 = ((sec_list['lb']+sec_list['ub'])/2).values
    A_ineq = np.concatenate((theme_secto, theme_secto*(-1)), axis=0)
    ineq = np.concatenate((lb_secto, ub_secto*(-1)), axis=0)
    A_eq = np.ones(len(x0)).reshape(1,-1)
    eq = [1]

    ineq_te = max_te

    success = False
    while success == False:
        weights_optim, success = optim_mai_te_constr(max_score, x0, A_eq, A_ineq, eq, ineq, sec_list['lb'], sec_list['ub'], ineq_te, weight_bench.values, ewma_cov_mat, in_ptf, sec_list[critere_repechage])
        ineq_te += 0.002

    ptf_te = compute_te(weights_optim, weight_bench.values, ewma_cov_mat, in_ptf)
    sec_list['Weight'] = weights_optim
    # sec_list = sec_list[sec_list['Weight']>= 0.001]  ### this filter the most of companies
    sec_list['Weight'] /= sec_list['Weight'].sum()

    #with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #   df_concat[columns].to_excel(writer,index = False)

    sec_list.sort_values(by='Weight', ascending=False,inplace=True)
    sec_list['ptf_te'] = ptf_te
    sec_list['Nb titres'] = len(sec_list)

    sec_list['Date'] = date
    sec_list['PTF'] = 'ML_ESG_EU'

    columns = ['PTF', 'ISIN', 'Weight', 'Date']

    if export_excel:
        with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
            sec_list.reset_index()[columns].to_excel(writer,index = False)

        return "ptf ML Europe generated successfully in " + output_file
    else:
        return sec_list.reset_index()


def transform_critere_repechage(reco_facto, date=None):
    """
    Transform critere_repechage input into standardized dictionary format
    
    Parameters
    ----------
    reco_facto : Union[dict, str, pd.DataFrame]
        Input criteria which can be:
        - dict: {'Factor1': weight1, 'Factor2': weight2, ...}
        - str: single factor name
        - pd.DataFrame: DataFrame containing factor weights
    date : datetime or str, optional
        Date for selecting data from DataFrame
        
    Returns
    -------
    dict
        Standardized dictionary of factor weights
    """
    
    # Case 1: Input is already a dictionary
    if isinstance(reco_facto, dict):
        return reco_facto
    
    # Case 2: Input is a string (single factor)
    elif isinstance(reco_facto, str):
        return {reco_facto: 1}
    
    # Case 3: Input is a DataFrame
    elif isinstance(reco_facto, pd.DataFrame):
        try:
            if date is not None:
                return reco_facto.loc[date].to_dict()
            return reco_facto.iloc[0].to_dict()  # Default to first row if no date
        except:
            # Fallback to default dictionary if DataFrame processing fails
            return {'Growth Avg Percentile': 1,
                   'LowVol Avg Percentile': 1,
                   'Mom Avg Percentile': 1,
                   'Quality Avg Percentile': 1,
                   'Value Avg Percentile': 1}
    
    # Case 4: Invalid input type
    else:
        raise TypeError(f"Unsupported input type: {type(reco_facto)}")


def sec_list_secto_tilt_TE_optim(screen_agg, 
                                 output_dir, 
                                 max_mean_weights_values_secto,
                                 list_secto, 
                                 returns,
                                 liste_repechage, 
                                 top_mandatory, 
                                 liste_noire, 
                                 nb_titres, 
                                 max_te, 
                                 esg_exclusion, 
                                 bench = 'STOXX EUROPE 600', 
                                 export_excel = True,
                                 reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                                 critere_repechage = {'Growth Avg Percentile' : 1,
                                                        'LowVol Avg Percentile' : 1,
                                                        'Mom Avg Percentile' : 1,
                                                        'Quality Avg Percentile' : 1,
                                                        'Value Avg Percentile' : 1}
                                 ):

    #Liste des régions autorisées
    max_mean_weights_s = pd.Series(data = max_mean_weights_values_secto, index = list_secto)
    # transpa_secto = pd.Series(data = ['Auto & Parts','Banks','Basic Resources','Chemicals','Construction & Materials','Financial Services','Food, Beverage & Tobacco','Health Care','Industrial Goods & Services',
    #                                   'Insurance','Media','Energy','Personal & Household Goods','Real Estate','Retail','Technology','Telecommunications','Travel & Leisure','Utilities'],
    #                                   index= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], name='transpa_secto')
    if type(liste_repechage)!=list:
        liste_repechage = [liste_repechage]
    #Lecture screen et returns
    if type(returns) == str:
        returns = pd.read_pickle(returns)
    if type(liste_noire) == str:
        liste_noire = read_liste_noire([],[],liste_noire)
    if type(screen_agg) == str:
        screen_agg = pd.read_pickle(screen_agg)

    df = screen_agg[screen_agg['Date'] == screen_agg['Date'].max()]
    df = df.loc[~df.index.duplicated(keep='first')]

    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)  #date de rebal 1ere date next month
    date_return = date +  relativedelta.relativedelta(years=-2)
    returns = returns[(returns.index>=date_return)&(returns.index<date)]

    if export_excel:
        if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y").capitalize()):
            os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y").capitalize())
        output_file = output_dir +"/Pour " + date.strftime("%B %Y").capitalize()+"/ML ESG EU.xlsx"

    # Critère rephechage multi pondéré
    critere_repechage = transform_critere_repechage(critere_repechage, date=date)
    # if isinstance(reco_facto, dict):
    #     reco_facto = critere_repechage
    # elif isinstance(reco_facto, pd.DataFrame):
    #     try:
    #         reco_facto = critere_repechage.loc[date].to_dict()
    #     except : 
    #         reco_facto = critere_repechage

    list_style = list(critere_repechage.keys())
    sytle_weight = list(critere_repechage.values())
    sytle_weight = np.array(sytle_weight,dtype='float')

    if sytle_weight.sum() == 0:
        sytle_weight = np.array([1/len(critere_repechage)]*len(critere_repechage))
    else:
        sytle_weight = sytle_weight/sytle_weight.sum()
    df['critere_repechage'] = df[list_style].dot(sytle_weight)


    #Cleaning du benchmark
    df = df[df['Weight in ' + bench]>0]
    df = df[df['Company SEDOL'].notna()].sort_index()
    df['Weight in univ norm'] = df['Weight in ' + bench]/df['Weight in ' + bench].sum()
    df.rename(columns={'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector ICB19'}, inplace=True)

    # df['lb'] = 0
    # df['ub'] = df['Weight in univ norm'].apply(compute_ub) #pour définir les ub en fonctions des poids initiaux si optim
    # df['ub'] = 0.05
    df['lb'] = df['Weight in univ norm']/2
    df['ub'] = df['Weight in univ norm'] + 0.01

    if isinstance(reco_secto, list):
        reco_secto = reco_secto
    elif isinstance(reco_secto, pd.DataFrame):
        try:
            reco_secto = reco_secto.loc[date].to_list()
        except : 
            reco_secto = reco_secto
    #Poids par zone géo et par secteur du bench, dvd yield moyen et carbon intensity moyenne du bench
    weight_secto_bench = df.groupby('Sector ICB19')['Weight in univ norm'].sum() / df['Weight in univ norm'].sum()
    weight_secto_bench = weight_secto_bench + (np.array(reco_secto)*1.5)
    weight_secto_bench[weight_secto_bench<0.0025] = 0.0025
    #Renormalisation des scores par zone géo (uniformes [0:1])
    #df['Multi Avg Percentile'] = df['Score ML']

    #on copie le bench (df) dans une nouvelle variable univers (univ)
    #Univ correspond au bench - exclusion esg - exclusion liste noire. Sert pour le repêchage
    df_esg = copy.deepcopy(df)
    if date.year >= 2017:
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
        df_esg=df.loc[(esg_pct >= esg_exclusion)]
        #df_esg = df_esg[~(df_esg.index.isin(liste_noire))]

    univ = copy.deepcopy(df_esg)
    df_filtered = copy.deepcopy(df_esg)
    # univ = univ[~(univ.index.isin(liste_noire))]

    # On choisit les X plus gros boites
    if top_mandatory != 0:
        univ = univ.nlargest(round(len(univ)*0.8), 'critere_repechage')
        top_weight_list  = univ.nlargest(top_mandatory,'Weight in ' + bench)
        top_weight_list.loc[:,'Repechage'] = 1
        top_weight_list.loc[:,'Raison repechage'] = 'Top mandatory'
        top_weight_list = top_weight_list.reset_index()

    nb_titres = (nb_titres - len(top_weight_list))

    df_remaining = df_filtered[~df_filtered['Company SEDOL'].isin(top_weight_list['Company SEDOL'])]
    df_filtered_with_critere = df_remaining.nlargest(nb_titres, 'critere_repechage') #pour ne selectionner que les nlargest titres selon la colonne spécifiée
    df_filtered_with_critere['Repechage'] = 0
    df_filtered_with_critere['Raison repechage'] = ''
    df_filtered_with_critere = df_filtered_with_critere.reset_index()

    df_filtered = pd.concat([df_filtered_with_critere, top_weight_list], ignore_index=True)
    df_filtered = df_filtered.set_index("ISIN")

    #Check nb titres sur les régions, repêchage si nécessaire
    for repechage_type in liste_repechage:
        # if repechage_type == 'Exchange Country Region':
        #     weight_repart = weight_region_bench
        #     max_mean_weights = max_mean_weights_r
        #     df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,repechage_type)
        if repechage_type == 'Sector ICB19':
            weight_repart = weight_secto_bench
            max_mean_weights = max_mean_weights_s
            df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,'critere_repechage',repechage_type)
            df_filtered = df_filtered.reset_index()

    df_filtered = df_filtered.drop_duplicates(subset=['Company SEDOL'])
    df_filtered = df_filtered.dropna(subset='critere_repechage')
    df_filtered = df_filtered.set_index('ISIN')

    #Matrice de covariance de la sec list
    returns = returns[df['Company SEDOL'].values]
    returns = returns.loc[:,~returns.columns.duplicated()]
    #bench_returns = compute_bench_returns(df,returns)
    #df.reset_index(inplace=True)
    #df['Beta'] = df['ISIN'].apply(lambda x: linregress(bench_returns.values, returns[df.loc[df['ISIN'] == x,'Company SEDOL'].values[0]]).slope)
    #df.set_index('ISIN',inplace=True)
    #df_filtered['Beta'] = df['Beta']
    ewma_cov_mat = ewma_cov(returns, 0.98)

    #Sec list finale pour l'optim
    columns_optim = ['Name','Exchange Country Name', 'Weight in univ norm', 'Region', 'Sector ICB19', 'critere_repechage', 'lb', 'ub', 'Repechage', 'Raison repechage']

    sec_list = df_filtered[columns_optim].sort_index()

    sec_list.rename(columns={'Weight in univ norm':'Weight','Sector ICB19':'Sector'}, inplace=True)
    weight_bench = df['Weight in univ norm']
    in_ptf = weight_bench.reset_index()['ISIN'].apply(lambda x: x in sec_list.index)

    #Bornes secto et bornes region
    max_secto = sec_list.groupby('Sector')['ub'].sum()
    min_secto = sec_list.groupby('Sector')['lb'].sum()
    # max_region = sec_list.groupby('Region')['ub'].sum()
    # min_region = sec_list.groupby('Region')['lb'].sum()

    lb_secto = weight_secto_bench - 0.02
    ub_secto = weight_secto_bench + 0.02
    lb_secto[lb_secto<0] = 0

    # lb_region = weight_region_bench - 0.02
    # ub_region = weight_region_bench + 0.02
    #lb_region[lb_region<0] = 0

    missing_secto = list(set(list_secto) - set(max_secto.index)) #si secteur existe pas ds seclist on le rajoute a la liste de secteur
    if len(missing_secto)>0:
        fill_missing = [0] * len(missing_secto)
        max_secto=(pd.concat([max_secto, pd.Series(data=fill_missing, index = missing_secto)])).sort_index()
        min_secto=(pd.concat([min_secto, pd.Series(data=fill_missing, index = missing_secto)])).sort_index()
    lb_secto = np.minimum(np.array(lb_secto), max_secto)
    ub_secto = np.maximum(np.array(ub_secto), min_secto)
    # lb_region = np.minimum(np.array(lb_region), max_region)
    # ub_region = np.maximum(np.array(ub_region), min_region)

    #Création matrice themes et vecteur ineq pour contraintes d'inégalités : A.x - b >= 0
    #theme_region = transform_flag_to_theme(sec_list['Region'], list_flag=list(weight_region_bench.index))
    theme_secto = transform_flag_to_theme(sec_list['Sector'], list_flag=list(weight_secto_bench.index))
    x0 = ((sec_list['lb']+sec_list['ub'])/2).values
    A_ineq = np.concatenate((theme_secto, theme_secto*(-1)), axis=0)
    ineq = np.concatenate((lb_secto, ub_secto*(-1)), axis=0)
    A_eq = np.ones(len(x0)).reshape(1,-1)
    eq = [1]

    ineq_te = max_te

    success = False
    while success == False:
        weights_optim, success = optim_mai_te_constr(max_score, x0, A_eq, A_ineq, eq, ineq, sec_list['lb'], sec_list['ub'], ineq_te, weight_bench.values, ewma_cov_mat, in_ptf, sec_list['critere_repechage'])
        ineq_te += 0.002

    ptf_te = compute_te(weights_optim, weight_bench.values, ewma_cov_mat, in_ptf)
    sec_list['Weight'] = weights_optim
    # sec_list = sec_list[sec_list['Weight']>= 0.001]  ### this filter the most of companies
    sec_list['Weight'] /= sec_list['Weight'].sum()

    #with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #   df_concat[columns].to_excel(writer,index = False)

    sec_list.sort_values(by='Weight', ascending=False,inplace=True)
    sec_list['ptf_te'] = ptf_te
    sec_list['Nb titres'] = len(sec_list)

    sec_list['Date'] = date
    sec_list['PTF'] = 'ML_ESG_EU'

    columns = ['PTF', 'ISIN', 'Weight', 'Date']

    if export_excel:
        with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
            sec_list.reset_index()[columns].to_excel(writer,index = False)

        return "ptf ML Europe generated successfully in " + output_file
    else:
        return sec_list.reset_index()











def sec_list_BT_ML(screen_agg, critere_repechage, max_mean_weights_values_secto,list_secto, returns,liste_repechage, liste_noire, perc, max_te, esg_exclusion,top_mandatory, bench = 'STOXX EUROPE 600'):

    #Liste des régions autorisées
    max_mean_weights_s = pd.Series(data = max_mean_weights_values_secto, index = list_secto)
    # transpa_secto = pd.Series(data = ['Auto & Parts','Banks','Basic Resources','Chemicals','Construction & Materials','Financial Services','Food, Beverage & Tobacco','Health Care','Industrial Goods & Services',
    #                                   'Insurance','Media','Energy','Personal & Household Goods','Real Estate','Retail','Technology','Telecommunications','Travel & Leisure','Utilities'],
    #                                   index= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], name='transpa_secto')
    if type(liste_repechage)!=list:
        liste_repechage = [liste_repechage]
    #Lecture screen et returns
    if type(returns) == str:
        returns = pd.read_pickle(returns)
    if type(liste_noire) == str:
        liste_noire = read_liste_noire([],[],liste_noire)
    if type(screen_agg) == str:
        screen_agg = pd.read_pickle(screen_agg)

    df = screen_agg[screen_agg['Date'] == screen_agg['Date'].max()]

    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)
    date_return = date +  relativedelta.relativedelta(years=-2)
    returns = returns[(returns.index>=date_return)&(returns.index<date)]

    #Cleaning du benchmark
    # df = df[df['Weight in ' + bench]>0]
    df = df[df['Company SEDOL'].notna()].sort_index()
    # df['Weight in univ norm'] = df['Weight in ' + bench]/df['Weight in ' + bench].sum()
    # df.rename(columns={'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector ICB19'}, inplace=True)

    # df['lb'] = 0
    # df['ub'] = df['Weight in univ norm'].apply(compute_ub)

    #Poids par zone géo et par secteur du bench, dvd yield moyen et carbon intensity moyenne du bench
    weight_secto_bench = df.groupby('Sector ICB19')['Weight in univ norm'].sum() / df['Weight in univ norm'].sum()

    #Renormalisation des scores par zone géo (uniformes [0:1])
    #df['Multi Avg Percentile'] = df['Score ML']

    #on copie le bench (df) dans une nouvelle variable univers (univ)
    #Univ correspond au bench - exclusion esg - exclusion liste noire. Sert pour le repêchage
    df_esg = copy.deepcopy(df)
    # if date.year >= 2017:
    #     esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
    #     df_esg=df.loc[(esg_pct >= esg_exclusion)]
    #     df_esg = df_esg[~(df_esg.index.isin(liste_noire))]

    univ = copy.deepcopy(df_esg)
    df_filtered = copy.deepcopy(df_esg)
    # univ = univ[~(univ.index.isin(liste_noire))]

    df_filtered['Repechage'] = 0
    df_filtered['Raison repechage'] = ''
    df_filtered = df_filtered.nlargest(perc, critere_repechage)
    #Check nb titres sur les régions, repêchage si nécessaire
    for repechage_type in liste_repechage:
        # if repechage_type == 'Exchange Country Region':
        #     weight_repart = weight_region_bench
        #     max_mean_weights = max_mean_weights_r
        #     df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,repechage_type)
        if repechage_type == 'Sector ICB19':
            weight_repart = weight_secto_bench
            max_mean_weights = max_mean_weights_s
            df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,repechage_type)

    if top_mandatory[0] == 'Yes':
        missing_top = list(set(univ.nlargest(int(top_mandatory[1]),'Weight in univ norm').index)-set(df_filtered.index))
        if len(missing_top)>0:
            df_filtered = pd.concat([df_filtered,univ[univ.index.isin(missing_top)]])
            df_filtered.loc[missing_top,'Repechage'] = 1
            df_filtered.loc[missing_top,'Raison repechage'] = 'Top mandatory'
            df_filtered.loc[missing_top,'lb'] = univ.loc[missing_top,'Weight in univ norm'] - 0.002
            df_filtered.loc[missing_top,'ub'] = univ.loc[missing_top,'Weight in univ norm'] + 0.002

    #Matrice de covariance de la sec list
    returns = returns[df['Company SEDOL'].values]
    returns = returns.loc[:,~returns.columns.duplicated()]
    #bench_returns = compute_bench_returns(df,returns)
    #df.reset_index(inplace=True)
    #df['Beta'] = df['ISIN'].apply(lambda x: linregress(bench_returns.values, returns[df.loc[df['ISIN'] == x,'Company SEDOL'].values[0]]).slope)
    #df.set_index('ISIN',inplace=True)
    #df_filtered['Beta'] = df['Beta']
    ewma_cov_mat = ewma_cov(returns, 0.98)

    #Sec list finale pour l'optim
    columns_optim = ['Name','Exchange Country Name', 'Weight in univ norm', 'Region', 'Sector ICB19', critere_repechage, 'lb', 'ub', 'Repechage', 'Raison repechage']

    sec_list = df_filtered[columns_optim].sort_index()

    sec_list.rename(columns={'Weight in univ norm':'Weight','Sector ICB19':'Sector'}, inplace=True)
    weight_bench = df['Weight in univ norm']
    in_ptf = weight_bench.reset_index()['ISIN'].apply(lambda x: x in sec_list.index)

    #Bornes secto et bornes region
    max_secto = sec_list.groupby('Sector')['ub'].sum()
    min_secto = sec_list.groupby('Sector')['lb'].sum()
    # max_region = sec_list.groupby('Region')['ub'].sum()
    # min_region = sec_list.groupby('Region')['lb'].sum()

    lb_secto = weight_secto_bench - 0.01
    ub_secto = weight_secto_bench + 0.01
    # lb_region = weight_region_bench - 0.02
    # ub_region = weight_region_bench + 0.02
    lb_secto[lb_secto<0] = 0
    #lb_region[lb_region<0] = 0

    missing_secto = list(set(list_secto) - set(max_secto.index))
    if len(missing_secto)>0:
        fill_missing = [0] * len(missing_secto)
        max_secto=(pd.concat([max_secto, pd.Series(data=fill_missing, index = missing_secto)])).sort_index()
        min_secto=(pd.concat([min_secto, pd.Series(data=fill_missing, index = missing_secto)])).sort_index()
    lb_secto = np.minimum(np.array(lb_secto), max_secto)
    ub_secto = np.maximum(np.array(ub_secto), min_secto)
    # lb_region = np.minimum(np.array(lb_region), max_region)
    # ub_region = np.maximum(np.array(ub_region), min_region)

    #Création matrice themes et vecteur ineq pour contraintes d'inégalités : A.x - b >= 0
    #theme_region = transform_flag_to_theme(sec_list['Region'], list_flag=list(weight_region_bench.index))
    theme_secto = transform_flag_to_theme(sec_list['Sector'], list_flag=list(weight_secto_bench.index))
    x0 = ((sec_list['lb']+sec_list['ub'])/2).values
    A_ineq = np.concatenate((theme_secto, theme_secto*(-1)), axis=0)
    ineq = np.concatenate((lb_secto, ub_secto*(-1)), axis=0)
    A_eq = np.ones(len(x0)).reshape(1,-1)
    eq = [1]
    ineq_te = max_te

    success = False
    while success == False:
        weights_optim, success = optim_mai_te_constr(max_score,x0, A_eq, A_ineq, eq, ineq, sec_list['lb'], sec_list['ub'], ineq_te, weight_bench.values, ewma_cov_mat, in_ptf, sec_list[critere_repechage])
        ineq_te += 0.005

    ptf_te = compute_te(weights_optim, weight_bench.values, ewma_cov_mat, in_ptf)
    sec_list['Weight'] = weights_optim
    sec_list['Nb titres before optim'] = len(sec_list)
    sec_list = sec_list[sec_list['Weight']>= 0.001]
    sec_list['Weight'] /= sec_list['Weight'].sum()

    #with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #   df_concat[columns].to_excel(writer,index = False)

    sec_list.sort_values(by='Weight', ascending=False,inplace=True)
    sec_list['ptf_te'] = ptf_te
    sec_list['Nb titres after optim'] = len(sec_list)

    sec_list['Date'] = date
    output_dir= '//groupe-ufg.com/commun/Prive/GestionAM/Ingenierie_Financiere/PROD/_EQUITY/FACTEUR TIMING/Push factor bloom/PROD/Code/test'
    if not os.path.isdir(output_dir +"/Pour " + date.strftime("%B %Y")):
        os.mkdir(output_dir +"/Pour " + date.strftime("%B %Y"))
    # with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #     sec_list.reset_index()[columns].to_excel(writer,index = False)

    return sec_list[['Date', 'Name','Weight','Sector','ptf_te', 'Nb titres before optim','Nb titres after optim']].reset_index()


def worst_list_BT_ML(screen_agg, perc, critere, top_mandatory, esg_exclusion, bench = 'STOXX EUROPE 600'):

    # transpa_secto = pd.Series(data = ['Auto & Parts','Banks','Basic Resources','Chemicals','Construction & Materials','Financial Services','Food, Beverage & Tobacco','Health Care','Industrial Goods & Services',
    #                                   'Insurance','Media','Energy','Personal & Household Goods','Real Estate','Retail','Technology','Telecommunications','Travel & Leisure','Utilities'],
    #                                   index= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], name='transpa_secto')
    #Lecture screen et returns
    if type(screen_agg) == str:
        screen_agg = pd.read_pickle(screen_agg)

    date = pd.to_datetime(screen_agg['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)

    #Cleaning du benchmark
    df = screen_agg[(screen_agg['Weight in ' + bench]>0)]
    df = df[df['Company SEDOL'].notna()].sort_index()
    df['Weight in univ norm'] = df['Weight in ' + bench]/df['Weight in ' + bench].sum()
    df.rename(columns={'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector ICB19'}, inplace=True)

    if df['Benchmark Market Value Millions in EUR'].isna().sum()>0:
        fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Weight in univ norm'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']) == False, 'Benchmark Market Value Millions in EUR'], deg = 1)
        func = np.poly1d(fit)
        df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Benchmark Market Value Millions in EUR'] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR']),'Weight in univ norm'])

    #Poids par zone géo et par secteur du bench, dvd yield moyen et carbon intensity moyenne du bench
    weight_secto_bench = df.groupby('Sector ICB19')['Weight in univ norm'].sum() / df['Weight in univ norm'].sum()

    df_esg = copy.deepcopy(df)
    # if date.year >= 2017:
    #     esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)
    #     df_esg=df.loc[(esg_pct >= esg_exclusion)]
    #     df_esg = df_esg[~(df_esg.index.isin(liste_noire))]

    univ = copy.deepcopy(df_esg)

    col_to_keep = ['Sector ICB19', 'Benchmark Market Value Millions in EUR']
    univ[critere] = univ[critere].rank(pct=True)*10
    worst_list = univ.loc[univ[critere] >= perc, col_to_keep]
    if top_mandatory[0] == 'Yes':
        missing_top = list(set(univ.nlargest(int(top_mandatory[1]),'Weight in univ norm').index)-set(worst_list.index))
        if len(missing_top)>0:
            worst_list = pd.concat([worst_list,univ[univ.index.isin(missing_top)]])
            worst_list.loc[missing_top,'Repechage'] = 1
            worst_list.loc[missing_top,'Raison repechage'] = 'Top mandatory'
    
    worst_list.rename(columns={'Sector ICB19':'Sector'}, inplace=True)

    worst_list['Weight'] = (worst_list['Benchmark Market Value Millions in EUR']**(1)).values
    worst_list['Date'] = date
    for secto in worst_list['Sector'].unique():
        worst_list.loc[worst_list['Sector'] == secto, 'Weight'] = worst_list.loc[worst_list['Sector'] == secto, 'Weight'] / worst_list['Weight'].sum()
        worst_list.loc[worst_list['Sector'] == secto, 'Weight'] = worst_list.loc[worst_list['Sector'] == secto, 'Weight'] * (weight_secto_bench.loc[secto] / worst_list.loc[worst_list['Sector'] == secto, 'Weight'].sum())
    worst_list['Weight'] = worst_list['Weight'] / worst_list['Weight'].sum()

    columns = ['ISIN', 'Weight', 'Date']

    return worst_list.reset_index()[columns]

def ML_bt(screen_agg, critere_repechage, max_mean_weights_values_secto,list_secto, returns,liste_repechage, liste_noire, perc, max_te, esg_exclusion,top_mandatory):


    # all_screen = pd.read_pickle(screen_path)

    # liste_noire = read_liste_noire([],[],liste_noire)
    # returns = pd.read_pickle(returns)
    # start_date=pd.to_datetime(start_date,dayfirst=True)
    # end_date=pd.to_datetime(end_date,dayfirst=True)
    #all_screen = all_screen[all_screen['Weight in univ norm'] >0]
    unique_dates = screen_agg['Date'].unique()

    screen_list = [screen_agg.loc[screen_agg['Date'] == date_] for date_ in unique_dates]

    # liste_noire = [liste_noire]*len(screen_list)
    # returns = [returns]*len(screen_list)
    # critere_repechage = [critere_repechage]*len(screen_list)
    # max_mean_weights_values_secto = [max_mean_weights_values_secto]*len(screen_list)
    # list_secto = [list_secto]*len(screen_list)
    # liste_repechage = [liste_repechage]*len(screen_list)
    # nb_titres = [nb_titres]*len(screen_list)
    # max_te = [max_te]*len(screen_list)
    
    # parameters = np.array([screen_list, critere_repechage,max_mean_weights_values_secto, list_secto, liste_repechage,
    #                        liste_noire,nb_titres,max_te], dtype=object)
    # parameters = parameters.transpose()

    #output_file = '//groupe-ufg.com/commun/Prive/DIRR/Ingenierie Financiere/Alexandre H/MAI/BT_' + name_ + ".xlsx"
    # '//groupe-ufg.com/commun/Prive/DIRR/Ingenierie Financiere/Alexandre H/MAI/BT_'+ datetime.datetime.now().strftime("%Y%m%d%H%M%S") + ".xlsx"


    # with Pool(os.cpu_count()-1) as p:
    #     result = p.starmap(sec_list_BT_ML, [(screen,critere_repechage,max_mean_weights_values_secto,list_secto,returns,liste_repechage,liste_noire,perc,max_te,esg_exclusion,top_mandatory) for screen in screen_list])
    
    with Pool(os.cpu_count()-1) as p:
        result = p.starmap(sec_list_BT_ML, [(screen,critere_repechage, max_mean_weights_values_secto,list_secto, returns,liste_repechage, liste_noire, perc, max_te, esg_exclusion,top_mandatory) for screen in screen_list])

    df = pd.concat(result, ignore_index=True)
    
    # with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy') as writer:
    #    df.to_excel(writer,index = False)
       
    return df

def generic_histo_seclist(func, start_date, *args):

    screen_agg = args[0]
    if type(screen_agg) == str:
        screen_agg = pd.read_pickle(screen_agg)
    screen_agg = screen_agg[screen_agg['Date']>start_date]
    unique_dates = screen_agg['Date'].unique()

    screen_list = [screen_agg.loc[screen_agg['Date'] == date_] for date_ in unique_dates]

    liste_params = list(args[1:])

    with Pool(os.cpu_count()-1) as p:
        result = p.starmap(func, [tuple([screen]+liste_params) for screen in screen_list])

    df = pd.concat(result, ignore_index=True)

    return df




def sec_list_spot_supersector_nb(screen, returns, bench, output_dir, cut_mkt_cap, metrics, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire,  
                  supersectors_nb, reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]):
    """  
    Generate Best Scored Sec List for 1 Month, According to the Number of Companies per Supersector  
    
    """  
    # If the user passed a single metric string, make it a list  
    if isinstance(metrics, str):  
        list_score_col = [metrics]  
    else:  
        list_score_col = metrics  
        
    # List of style columns to compute 'Multi Avg Percentile'  
    list_style = [  
        'Value Avg Percentile',   
        'Quality Avg Percentile',  
        'Mom Avg Percentile',  
        'LowVol Avg Percentile',  
        'Growth Avg Percentile'  
    ]  

    # Filter to keep only securities that have a weight > 0 in the benchmark  
    df = screen[screen['Weight in ' + bench] > 0].copy()  

    # Convert date to the first day of the next month  
    date = pd.to_datetime(df['Date'].iloc[0]) + pd.offsets.MonthBegin(1)  

    # Estimate missing Market Values by a linear function of Weight  
    notna_mask = pd.notna(df['Benchmark Market Value Millions in EUR'])  
    fit = np.polyfit(  
        df.loc[notna_mask, 'Weight in ' + bench],  
        df.loc[notna_mask, 'Benchmark Market Value Millions in EUR'],  
        deg=1  
    )  
    func = np.poly1d(fit)  
    df.loc[~notna_mask, 'Benchmark Market Value Millions in EUR'] = func(  
        df.loc[~notna_mask, 'Weight in ' + bench]  
    )  

    # Compute 'Multi Avg Percentile'  
    df['Multi Avg Percentile'] = df[list_style].mean(axis=1, skipna=False)  

    # If below market-cap cutoff, set listed score columns to NaN  
    df.loc[  
        df['Benchmark Market Value Millions in EUR'] <= cut_mkt_cap,   
        list_score_col  
    ] = np.NaN  

    # Convert date column  
    df['Date'] = date  

    # Handle different weighting schemes (cubic root, square root, etc.)  
    if ponderation == "Racine cube":  
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR'] ** (1/3)  
    elif ponderation == "Racine carrée":  
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR'] ** (1/2)  
    elif ponderation == "Log":  
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])  
    elif ponderation == "Equalweight":  
        df['Benchmark Market Value Millions in EUR'] = 1 / len(df)  
    elif ponderation == "Vol Tilt Racine Cube":  
        std = returns.iloc[-250:].std().rename('STD')  
        # Merge the standard deviation data based on "Company SEDOL"  
        df = df.merge(  
            std,   
            how='left',   
            left_on="Company SEDOL",   
            right_index=True  
        )  
        from scipy import stats  
        def calculate_std_multiplier(x, data):  
            return (50 - stats.percentileofscore(data, x, kind='weak'))/100 + 1  
        df['STD_multiplier'] = df['STD'].apply(lambda x: calculate_std_multiplier(x, df['STD']))  
        # Apply cubic root tilt  
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR'] ** (1/3)  
        df['Benchmark Market Value Millions in EUR'] *= df['STD_multiplier']  

    # If weighting neutralization is by supersector (“ICB 19”) or industry (“ICB 11”),  
    # compute a target weight for each sector:  
    if weight_neutral == "ICB 19":  
        weight_secto_bench = (  
            df.groupby('ICB19 Supersector')['Weight in ' + bench]  
            .sum()  
            .div(df['Weight in ' + bench].sum())  
        )  
        # Adjust for possible missing supersectors  
        all_super = set(supersectors_nb.values())  # Not strictly needed  
        icb_missing = set(supersectors_nb.keys()) - set(df['ICB19 Supersector'].unique())  
        if len(icb_missing) > 0:  
            # If any supersectors are missing, remove from reco_secto  
            # (the code below is the same logic you originally had)  
            pass  # your logic for adjusting reco_secto if needed  

        # Example of offsetting the benchmark weights by reco_secto  
        # (as in your original code)  
        len_weight_secto = len(weight_secto_bench)
        if len(reco_secto) > len_weight_secto:
        # Too many elements in reco_secto → slice down
            reco_secto = reco_secto[:len_weight_secto]
        elif len(reco_secto) < len_weight_secto:
        # Too few elements → extend with zeros
            short_by = len_weight_secto - len(reco_secto)
            reco_secto = reco_secto + [0]*short_by
            
        weight_secto_bench = (  
            weight_secto_bench   
            + (np.array(reco_secto)*1.5)   # shift by user-defined amounts  
        )  
        weight_secto_bench[weight_secto_bench < 0.0025] = 0.0025  

    elif weight_neutral == "ICB 11":  
        weight_secto_bench = (  
            df.groupby(' Benchmark ICB Industry ')['Weight in ' + bench]  
            .sum()  
            .div(df['Weight in ' + bench].sum())  
        )  

    # Rank each metric within the entire DataFrame first  
    df[list_score_col] = df[list_score_col].rank(pct=True)  
    df[list_score_col] = (  
        df[list_score_col]   
        .sub(df[list_score_col].min())   
        .div(df[list_score_col].max() - df[list_score_col].min())  
    )  

    # If you want to neutralize the scoring within each Supersector (“ICB 19”)  
    if score_neutral == "ICB 19":  
        for secto_val in df['ICB19 Supersector'].unique():  
            mask = (df['ICB19 Supersector'] == secto_val)  
            subset = df.loc[mask, list_score_col]  
            # ranked = subset.rank(pct=True).sub(subset.min()).div(subset.max() - subset.min())  
            # df.loc[mask_secto, list_score_col] = ranked  

            # Step A: rank inside that group  
            df.loc[mask, list_score_col] = subset.rank(pct=True)  

            # Step B: min–max scale inside that group  
            min_vals = df.loc[mask, list_score_col].min()  
            max_vals = df.loc[mask, list_score_col].max()  
            df.loc[mask, list_score_col] = (  
                df.loc[mask, list_score_col] - min_vals  
            ) / (  
                max_vals - min_vals  
            )

    # If date >= 2014, apply ESG filter  
    df_esg = copy.deepcopy(df)  
    if date.year >= 2014:  
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)  
        # Keep only rows above an ESG threshold  
        df_esg = df.loc[esg_pct >= esg_exclusion]  

    if liste_noire is not None:
        if isinstance(liste_noire, str):
            liste_noire = read_liste_noire([], [], liste_noire)

        # Check if 'ISIN' is a column or the index
        if 'ISIN' in df_esg.columns:
            df_esg = df_esg[~df_esg['ISIN'].isin(liste_noire)]
        elif df_esg.index.name == 'ISIN':  # If 'ISIN' is the index
            df_esg = df_esg[~df_esg.index.isin(liste_noire)]


    # Now, for each metric, pick top N from each supersector  
    # using the supersectors_nb dictionary.  
    # Then handle weighting and combine into one final DataFrame  
    columns = ['PTF', 'ISIN', 'Weight', 'Date']  
    df_concat = pd.DataFrame()  

    for i, score_col in enumerate(list_score_col):  
        # Group by supersector and pick top N rows from 'df_esg'  
        # using the 'nlargest' approach:  
        df_top = (  
            df_esg  
            .groupby('ICB19 Supersector', group_keys=True, as_index=False)  
            .apply(  
                lambda grp: grp.nlargest(  
                    supersectors_nb.get(grp.name, 0),  # get N from dictionary  
                    score_col  
                )  
            )  
        )  
        # Remove the extra index levels from groupby/apply  
        df_top.reset_index(drop=False, inplace=True)  

        # Optional: If we want to apply an additional tilt  
        #   e.g., "Metric Tilt Racine Cube", as in your code  
        if ponderation == "Metric Tilt Racine Cube":  
            from scipy import stats  
            df_top['score_col_Z'] = stats.zscore(df_top[score_col])  
            df_top['Benchmark Market Value Millions in EUR'] = (  
                df_top['Benchmark Market Value Millions in EUR']**(1/3)   
                * (1 + (df_top['score_col_Z'] * 10/100))  
            )  

        # Build temp DataFrame for final output  
        temp_df = pd.DataFrame(columns = columns)  
        temp_df["ISIN"] = df_top["ISIN"].values
        temp_df['Secto'] = df_top['ICB19 Supersector'].values  
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values  
        temp_df['Score'] = df_top[score_col].values  
        
        # PTF name  
        if isinstance(ptf_name, str):  
            temp_df['PTF'] = ptf_name  
        else:  
            temp_df['PTF'] = ptf_name[i]  # if multiple names  

        temp_df['Date'] = date  

        # If weighting neutralization is not “No,” scale weights by sector  
        if weight_neutral != "No":  
            for secto in temp_df['Secto'].unique():  
                mask_secto = (temp_df['Secto'] == secto)  
                # First, scale to sum 1 within that sector  
                temp_df.loc[mask_secto, 'Weight'] = (  
                    temp_df.loc[mask_secto, 'Weight']   
                    / temp_df['Weight'].sum()  
                )  
                # Then multiply by the target sector weight from the benchmark  
                # This uses 'weight_secto_bench' previously computed  
                if weight_neutral == "ICB 19" and secto in weight_secto_bench.index:  
                    temp_df.loc[mask_secto, 'Weight'] *= (  
                        weight_secto_bench.loc[secto]  
                        / temp_df.loc[mask_secto, 'Weight'].sum()  
                    )  

        # Final normalization so total sums to 1  
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()  

        # Append to final DataFrame  
        df_concat = pd.concat([df_concat, temp_df], ignore_index=True)  

    # Return the final DataFrame with chosen securities  
    return df_concat


def sec_list_spot_supersector_nb_worst(screen, returns, bench, output_dir, cut_mkt_cap, metrics, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire,  
                  supersectors_nb, reco_secto = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]):
    """  
    Generate Best Scored Sec List for 1 Month, According to the Number of Companies per Supersector  
    
    """  
    # If the user passed a single metric string, make it a list  
    if isinstance(metrics, str):  
        list_score_col = [metrics]  
    else:  
        list_score_col = metrics  
        
    # List of style columns to compute 'Multi Avg Percentile'  
    list_style = [  
        'Value Avg Percentile',   
        'Quality Avg Percentile',  
        'Mom Avg Percentile',  
        'LowVol Avg Percentile',  
        'Growth Avg Percentile'  
    ]  

    # Filter to keep only securities that have a weight > 0 in the benchmark  
    df = screen[screen['Weight in ' + bench] > 0].copy()  

    # Convert date to the first day of the next month  
    date = pd.to_datetime(df['Date'].iloc[0]) + pd.offsets.MonthBegin(1)  

    # Estimate missing Market Values by a linear function of Weight  
    notna_mask = pd.notna(df['Benchmark Market Value Millions in EUR'])  
    fit = np.polyfit(  
        df.loc[notna_mask, 'Weight in ' + bench],  
        df.loc[notna_mask, 'Benchmark Market Value Millions in EUR'],  
        deg=1  
    )  
    func = np.poly1d(fit)  
    df.loc[~notna_mask, 'Benchmark Market Value Millions in EUR'] = func(  
        df.loc[~notna_mask, 'Weight in ' + bench]  
    )  

    # Compute 'Multi Avg Percentile'  
    df['Multi Avg Percentile'] = df[list_style].mean(axis=1, skipna=False)  

    # If below market-cap cutoff, set listed score columns to NaN  
    df.loc[  
        df['Benchmark Market Value Millions in EUR'] <= cut_mkt_cap,   
        list_score_col  
    ] = np.NaN  

    # Convert date column  
    df['Date'] = date  

    # Handle different weighting schemes (cubic root, square root, etc.)  
    if ponderation == "Racine cube":  
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR'] ** (1/3)  
    elif ponderation == "Racine carrée":  
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR'] ** (1/2)  
    elif ponderation == "Log":  
        df['Benchmark Market Value Millions in EUR'] = np.log(df['Benchmark Market Value Millions in EUR'])  
    elif ponderation == "Equalweight":  
        df['Benchmark Market Value Millions in EUR'] = 1 / len(df)  
    elif ponderation == "Vol Tilt Racine Cube":  
        std = returns.iloc[-250:].std().rename('STD')  
        # Merge the standard deviation data based on "Company SEDOL"  
        df = df.merge(  
            std,   
            how='left',   
            left_on="Company SEDOL",   
            right_index=True  
        )  
        from scipy import stats  
        def calculate_std_multiplier(x, data):  
            return (50 - stats.percentileofscore(data, x, kind='weak'))/100 + 1  
        df['STD_multiplier'] = df['STD'].apply(lambda x: calculate_std_multiplier(x, df['STD']))  
        # Apply cubic root tilt  
        df['Benchmark Market Value Millions in EUR'] = df['Benchmark Market Value Millions in EUR'] ** (1/3)  
        df['Benchmark Market Value Millions in EUR'] *= df['STD_multiplier']  

    # If weighting neutralization is by supersector (“ICB 19”) or industry (“ICB 11”),  
    # compute a target weight for each sector:  
    if weight_neutral == "ICB 19":  
        weight_secto_bench = (  
            df.groupby('ICB19 Supersector')['Weight in ' + bench]  
            .sum()  
            .div(df['Weight in ' + bench].sum())  
        )  
        # Adjust for possible missing supersectors  
        all_super = set(supersectors_nb.values())  # Not strictly needed  
        icb_missing = set(supersectors_nb.keys()) - set(df['ICB19 Supersector'].unique())  
        if len(icb_missing) > 0:  
            # If any supersectors are missing, remove from reco_secto  
            # (the code below is the same logic you originally had)  
            pass  # your logic for adjusting reco_secto if needed  

        # Example of offsetting the benchmark weights by reco_secto  
        # (as in your original code)  
        len_weight_secto = len(weight_secto_bench)
        if len(reco_secto) > len_weight_secto:
        # Too many elements in reco_secto → slice down
            reco_secto = reco_secto[:len_weight_secto]
        elif len(reco_secto) < len_weight_secto:
        # Too few elements → extend with zeros
            short_by = len_weight_secto - len(reco_secto)
            reco_secto = reco_secto + [0]*short_by
            
        weight_secto_bench = (  
            weight_secto_bench   
            + (np.array(reco_secto)*1.5)   # shift by user-defined amounts  
        )  
        weight_secto_bench[weight_secto_bench < 0.0025] = 0.0025  

    elif weight_neutral == "ICB 11":  
        weight_secto_bench = (  
            df.groupby(' Benchmark ICB Industry ')['Weight in ' + bench]  
            .sum()  
            .div(df['Weight in ' + bench].sum())  
        )  

    # Rank each metric within the entire DataFrame first  
    df[list_score_col] = df[list_score_col].rank(pct=True)  
    df[list_score_col] = (  
        df[list_score_col]   
        .sub(df[list_score_col].min())   
        .div(df[list_score_col].max() - df[list_score_col].min())  
    )  

    # If you want to neutralize the scoring within each Supersector (“ICB 19”)  
    if score_neutral == "ICB 19":  
        for secto_val in df['ICB19 Supersector'].unique():  
            mask = (df['ICB19 Supersector'] == secto_val)  
            subset = df.loc[mask, list_score_col]  
            # ranked = subset.rank(pct=True).sub(subset.min()).div(subset.max() - subset.min())  
            # df.loc[mask_secto, list_score_col] = ranked  

            # Step A: rank inside that group  
            df.loc[mask, list_score_col] = subset.rank(pct=True)  

            # Step B: min–max scale inside that group  
            min_vals = df.loc[mask, list_score_col].min()  
            max_vals = df.loc[mask, list_score_col].max()  
            df.loc[mask, list_score_col] = (  
                df.loc[mask, list_score_col] - min_vals  
            ) / (  
                max_vals - min_vals  
            )

    # If date >= 2014, apply ESG filter  
    df_esg = copy.deepcopy(df)  
    if date.year >= 2014:  
        esg_pct = df['ESG_ANALYST_SCORE'].rank(pct=True)  
        # Keep only rows above an ESG threshold  
        df_esg = df.loc[esg_pct >= esg_exclusion]  

    # Now, for each metric, pick top N from each supersector  
    # using the supersectors_nb dictionary.  
    # Then handle weighting and combine into one final DataFrame  
    columns = ['PTF', 'ISIN', 'Weight', 'Date']  
    df_concat = pd.DataFrame()  

    for i, score_col in enumerate(list_score_col):  
        # Group by supersector and pick top N rows from 'df_esg'  
        # using the 'nlargest' approach:  
        df_top = (  
            df_esg  
            .groupby('ICB19 Supersector', group_keys=True, as_index=False)  
            .apply(  
                lambda grp: grp.nsmallest(  
                    supersectors_nb.get(grp.name, 0),  # get N from dictionary  
                    score_col  
                )  
            )  
        )  
        # Remove the extra index levels from groupby/apply  
        df_top.reset_index(drop=False, inplace=True)  

        # Optional: If we want to apply an additional tilt  
        #   e.g., "Metric Tilt Racine Cube", as in your code  
        if ponderation == "Metric Tilt Racine Cube":  
            from scipy import stats  
            df_top['score_col_Z'] = stats.zscore(df_top[score_col])  
            df_top['Benchmark Market Value Millions in EUR'] = (  
                df_top['Benchmark Market Value Millions in EUR']**(1/3)   
                * (1 + (df_top['score_col_Z'] * 10/100))  
            )  

        # Build temp DataFrame for final output  
        temp_df = pd.DataFrame(columns = columns)  
        temp_df["ISIN"] = df_top["ISIN"].values
        temp_df['Secto'] = df_top['ICB19 Supersector'].values  
        temp_df['Weight'] = df_top['Benchmark Market Value Millions in EUR'].values  
        temp_df['Score'] = df_top[score_col].values  
        
        # PTF name  
        if isinstance(ptf_name, str):  
            temp_df['PTF'] = ptf_name  
        else:  
            temp_df['PTF'] = ptf_name[i]  # if multiple names  

        temp_df['Date'] = date  

        # If weighting neutralization is not “No,” scale weights by sector  
        if weight_neutral != "No":  
            for secto in temp_df['Secto'].unique():  
                mask_secto = (temp_df['Secto'] == secto)  
                # First, scale to sum 1 within that sector  
                temp_df.loc[mask_secto, 'Weight'] = (  
                    temp_df.loc[mask_secto, 'Weight']   
                    / temp_df['Weight'].sum()  
                )  
                # Then multiply by the target sector weight from the benchmark  
                # This uses 'weight_secto_bench' previously computed  
                if weight_neutral == "ICB 19" and secto in weight_secto_bench.index:  
                    temp_df.loc[mask_secto, 'Weight'] *= (  
                        weight_secto_bench.loc[secto]  
                        / temp_df.loc[mask_secto, 'Weight'].sum()  
                    )  

        # Final normalization so total sums to 1  
        temp_df['Weight'] = temp_df['Weight'] / temp_df['Weight'].sum()  

        # Append to final DataFrame  
        df_concat = pd.concat([df_concat, temp_df], ignore_index=True)  

    # Return the final DataFrame with chosen securities  
    return df_concat


def convert_icb2name(df, original_col, new_col):
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
    df[new_col] = df[original_col].map(icb_supersectors_reverse) 

    return df