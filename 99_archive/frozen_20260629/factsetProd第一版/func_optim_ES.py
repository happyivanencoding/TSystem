from pyxll import xl_macro
import pandas as pd
import numpy as np
from dateutil import relativedelta
import copy
from math import ceil
from scipy.stats import linregress
import scipy.optimize

def read_liste_noire(override_exclusion, override_inclusion, file = '//groupe-ufg.com/Commun/Prive/DIRR/Ingenierie Financiere/_LISTE_NOIRE_EXCLUSION/Liste_Noire_Exclusion.xlsx'):
    liste_noire= pd.read_excel(file,usecols='H,I,T')
    multiple_isin = liste_noire.iloc[:,1].str.split(';',expand=True)
    multiple_isin_flatten = multiple_isin.to_numpy().flatten()
    multiple_isin_flatten = np.unique(multiple_isin_flatten.astype(str))
    liste_noire = np.concatenate([liste_noire.iloc[1:,0].dropna().unique(),liste_noire.iloc[1:,1].dropna().unique(),liste_noire.iloc[:,2].dropna().unique(), multiple_isin_flatten])
    liste_noire_tot = np.concatenate([liste_noire,np.array(override_exclusion)])
    liste_noire_unique = np.unique(liste_noire_tot)
    liste_noire_finale = list(set(liste_noire_unique) - set(override_inclusion))
    return liste_noire_finale

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

def repechage(df, col, filtre, critere, nb):
    if col != "No filter":
        df = df[df[col] == filtre]
    
    # Check if the critere column is not numeric and convert if necessary
    if df[critere].dtype not in ['float64', 'int64']:
        try:
            df[critere] = df[critere].astype(float)
        except ValueError:
            # If conversion to float fails, try to extract numeric values
            df[critere] = df[critere].str.extract('(\d+\.?\d*)').astype(float)
    
    df_return = df.nlargest(nb, critere)
    df_return['Repechage'] = 1
    
    if col == 'Exchange Country Region':
        df_return['Raison repechage'] = 'Region'
    elif col == ' Benchmark ICB Supersector ':
        df_return['Raison repechage'] = 'Sector'
    elif col =='Size':
        df_return['Raison repechage'] = 'Size'
    else:
        df_return['Raison repechage'] = 'Top weights'
    
    return df_return


def repechage_sec_list(sec_list,univ, weight_repart, max_mean_weights, critere_repechage, repechage_type):

    nb_titre_repart = sec_list.groupby(repechage_type).apply(lambda x: len(x))
    missing_value = list(set(weight_repart.index) - set(nb_titre_repart.index))
    fill_missing = [0.00000001]*len(missing_value)
    nb_titre_repart = pd.concat([nb_titre_repart, pd.Series(data=fill_missing, index = missing_value)])
    mean_weight = weight_repart / nb_titre_repart

    df_concat = copy.deepcopy(sec_list)
    repechage_values = mean_weight[(mean_weight.sort_index() > max_mean_weights.sort_index())].index
    if len(repechage_values)>0:
        for value in repechage_values:
            # nb_repechage = ceil(weight_repart.loc[value]/max_mean_weights.loc[value] - nb_titre_repart.loc[value])
            if max_mean_weights.loc[value] > 1e-10: 
                nb_repechage = ceil(weight_repart.loc[value]/max_mean_weights.loc[value] - nb_titre_repart.loc[value])
            else:
                nb_repechage = 0 
            df_repechage = copy.deepcopy(univ).reset_index()
            df_repechage = (df_repechage[df_repechage['ISIN'].isin(list(set(univ.index) - set(sec_list.index)))]).set_index('ISIN')
            if nb_repechage > 0:
                df_concat = pd.concat([df_concat,repechage(df_repechage,repechage_type,value,critere_repechage,nb_repechage)])

    return df_concat

def compute_bench_returns(bench, returns, col_weights, col_sort='Company SEDOL'):

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

def transform_flag_to_theme(flag, bool_column = False, list_flag = "No"):

    if type(list_flag) == str:
        list_flag = np.sort(flag.unique())
    
    list_theme = []
    for flag_val in list_flag:
        temp = copy.deepcopy(flag.values)
        if type(flag_val) != str:
            if flag_val == 0:
                if bool_column == False:
                    list_theme.append(np.where(temp,0,1))
            else:
                temp[temp!=flag_val] = 0
                temp[temp==flag_val] = 1
                list_theme.append(temp)
        else:
            index_0 = temp!=flag_val
            index_1 = temp==flag_val
            temp[index_0] = 0
            temp[index_1] = 1
            list_theme.append(temp)
    return np.array(list_theme)

# def compute_te(w_ptf, w_bench, cov, in_ptf):

#     w_bench_copy = copy.deepcopy(w_bench[in_ptf])
#     w_bench_copy -= w_ptf
#     w_excess = w_bench_copy *(-1)
#     return np.sqrt(w_excess.transpose() @ cov @ w_excess)

# def compute_te(w_ptf, w_bench, cov, in_ptf):

#     w_bench_copy = copy.deepcopy(w_bench)
#     w_bench_copy[in_ptf] -= w_ptf
#     w_excess = w_bench_copy[in_ptf] *(-1)
#     return np.sqrt(w_excess.transpose() @ cov @ w_excess)

def compute_te(w_ptf, w_bench, cov, in_ptf):

    w_bench_copy = copy.deepcopy(w_bench)
    w_bench_copy[in_ptf] -= w_ptf
    w_excess = w_bench_copy *(-1)
    return np.sqrt(w_excess.transpose() @ cov @ w_excess)

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
    res = scipy.optimize.minimize(fun, x0, args=(args),method='SLSQP',options = {'maxiter':10000,'ftol': 1e-4}, bounds=bnds, constraints=[eq_cons,ineq_cons])
    # res = scipy.optimize.minimize(fun, x0, args=(args),method='trust-constr',options = {'maxiter':200000,'ftol': 1e-10}, bounds=bnds, constraints=[eq_cons,ineq_cons])
    return res.x

# def optim_mai_te_constr(fun, x0, A_eq, A_ineq, eq, ineq, lb, ub,ineq_te, weight_bench, ewma_cov_mat, in_ptf, *args):

#     """
#     Fmincon function
#     return np.array of weights
#     """
#     #bnds = lb et ub de chaque actifs 
#     bnds=scipy.optimize.Bounds(lb, ub)
#     # 1 contreaintes d'inegalités :  A.x-ineqb>=0
#     ineq_cons = {'type': 'ineq',
#              'fun' : lambda x: ((A_ineq @ x)-ineq)}
#     ineq_quad = {'type': 'ineq',
#              'fun' : lambda x: -compute_te(x,weight_bench, ewma_cov_mat, in_ptf) + ineq_te}
#              #'args':(weight_bench, ewma_cov_mat, in_ptf)}
#     # 1 contrainte d'égalité somme(x)=1 => somme(x)-1=0
#     eq_cons = {'type': 'eq',
#            'fun' : lambda x: (A_eq @ x)-eq}
#            #'jac' : lambda x: np.ones(len(x)).reshape(1,-1)}
#     res=scipy.optimize.minimize(fun, x0, args=(args),method='SLSQP',options = {'maxiter':10000,'ftol': 1e-4},bounds=bnds, constraints=[eq_cons, ineq_cons, ineq_quad])
#     return res.x, res.success
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
    res=scipy.optimize.minimize(fun, x0, args=(args),method='SLSQP',options = {'maxiter':10000,'ftol': 1e-4},bounds=bnds, constraints=[eq_cons, ineq_quad])
    return res.x, res.success

@xl_macro('str screen, str bench_name, var[][] exclusion, var[][] mf_formula, float[] max_mean_weights_values_region, str[] list_region, str critere_repechage, float[] max_mean_weights_values_secto, int[] list_secto, float[] max_mean_weights_size, str[] list_size, float cut_mkt_cap, int[] top_companies, str returns, float[] divide_lb, float[] multiply_ub, float min_weight, float max_weight, str[] liste repechage, float[] bucket_min_ub, float[][] min_ub_list, str liste_noire, float[] min_lb, int top_mandatory, str date_, str[] override_exclusion,str[] override_inclusion, var[][] analyst_score, float[] list_cap')
def ES_get_sec_list(screen, bench_name, exclusion, 
                    mf_formula, 
                    max_mean_weights_values_region, 
                    list_region,critere_repechage, max_mean_weights_values_secto,list_secto, max_mean_weights_size, list_size,
                    cut_mkt_cap, 
                    top_companies, returns, divide_lb, multiply_ub, min_weight, max_weight, 
                    liste_repechage, bucket_min_ub, min_ub_list, liste_noire, min_lb,
                    top_mandatory, date_, override_exclusion, override_inclusion,
                    analyst_score, list_cap):
    #Liste des styles utilisés
    list_style = ["Growth Avg Percentile", "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile", "Dividend Avg Percentile",'Multi Avg Percentile']

    list_score_col = mf_formula[0]
    mf_weighting = mf_formula[1]
    #Liste des régions autorisées
    max_mean_weights_r = pd.Series(data = max_mean_weights_values_region, index = list_region).sort_index()
    max_mean_weights_s = pd.Series(data = max_mean_weights_values_secto, index = list_secto)
    max_mean_weights_size = pd.Series(data = max_mean_weights_size, index = list_size)

    divide_lb_r = pd.Series(data = divide_lb, index = list_region, name="divide_lb")
    multiply_ub_r = pd.Series(data = multiply_ub, index = list_region, name="multiply_ub")
    min_ub_r = pd.DataFrame(data = np.array(min_ub_list).transpose(),columns=['min_ub_1','min_ub_2','min_ub_3'], index = list_region)
    min_lb_r = pd.Series(data = min_lb, index = list_region, name="min_lb")
    transpa_secto = pd.Series(data = ['Auto & Parts','Banks','Basic Resources','Chemicals','Construction & Materials','Financial Services','Food, Beverage & Tobacco','Health Care','Industrial Goods & Services',
                                        'Insurance','Media','Energy','Personal & Household Goods','Real Estate','Retail','Technology','Telecommunications','Travel & Leisure','Utilities'],
                                        index= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19], name='transpa_secto')

    exclusion_factors = exclusion[0]
    exclusion_list = exclusion[1]
    nb_top_companies = top_companies[0]
    min_top_companies = top_companies[1]

    analyst_score = pd.DataFrame(data = np.array(analyst_score).transpose(), columns=['ISIN', 'Name', 'Weight', 'Analyst Score'])
    analyst_score = analyst_score.set_index(['ISIN'])

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

    # Filter sur le bench
    bench_col = 'Weight in ' + bench_name
    df = df[df[bench_col]>0]

    ### Add Analyst Score to Screen Agg
    df = df.merge(analyst_score[['Analyst Score']], how = "left", left_index=True, right_index=True)
    df = df.groupby(df.index).first()

    # Forcer la region
    if bench_name == 'STOXX EUROPE 600':
        df['Exchange Country Region'] = "West Europe"


    df = df[df['Company SEDOL'].notna()]

    df = df[df['Exchange Country Region'].isin(list_region)]
    

    df[bench_col] /= df[bench_col].sum()
    df.loc[df['DVD Yield FY1'].isna(),'DVD Yield FY1'] = df['DVD Yield FY0']
    df.loc[df['Earns Yield FY1'].isna(),'Earns Yield FY1'] = df['Earns Yield FY0']
    df ['Earnings yield copy'] = df['Earns Yield FY1'].values
    df ['Dvd yield copy'] = df['DVD Yield FY1'].values
    df['Exclusion liste noire'] = 0
    df['Exclusion ESG'] = 0
    max_weight = max(max_weight, df[bench_col].max()+0.0005)


    cap_thd_small = list_cap[0]
    cap_thd_mid = list_cap[1]

    def categorize_size(row, cap_thd_small, cap_thd_mid, bench_col):
        market_value = row['Benchmark Market Value Millions in EUR']
        bench_weight = row[bench_col]
        
        if pd.isna(market_value):
            if bench_weight < 0.0002:  # 0.02%
                return 'small'
            elif bench_weight < 0.0005:  # 0.05%
                return 'mid'
            else:
                return 'large'
        else:
            if market_value < cap_thd_small:
                return 'small'
            elif market_value < cap_thd_mid:
                return 'mid'
            else:
                return 'large'

    df['Size'] = df.apply(lambda row: categorize_size(row, cap_thd_small, cap_thd_mid, bench_col), axis=1)


    #Poids par zone géo et par secteur du bench, dvd yield moyen et carbon intensity moyenne
    weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')[bench_col].sum() / df[bench_col].sum()
    weight_region_bench = df.groupby('Exchange Country Region')[bench_col].sum() / df[bench_col].sum()
    weight_size_bench = df.groupby('Size')[bench_col].sum() / df[bench_col].sum()


    # built list of all regions, empty one fill with 0
    missing_region = list(set(list_region) - set(weight_region_bench.index))
    if len(missing_region)>0:
        fill_missing = [0] * len(missing_region)
        weight_region_bench=(pd.concat([weight_region_bench, pd.Series(data=fill_missing, index = missing_region)])).sort_index()



    carbon_intensity_bench = (df.loc[pd.notna(df['CarbonIntensity_Sales']), 'CarbonIntensity_Sales'].dot(df.loc[pd.notna(df['CarbonIntensity_Sales']), bench_col]))/df.loc[pd.notna(df['CarbonIntensity_Sales']), bench_col].sum()


    #Renormalisation des scores par zone géo (uniformes [0:1])
    df['DVD Payout FY0'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['DVD Payout FY0'].rank(pct=True)
    df['DVD Payout FY0'] = (df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['DVD Payout FY0'].apply(lambda x: (x - x.min())/(x.max() - x.min())))
    df['Earns Yield FY1'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['Earns Yield FY1'].rank(pct=True)
    df['DVD Yield FY1'] = df.groupby(['Exchange Country Region',' Benchmark ICB Industry '],group_keys=False)['DVD Yield FY1'].rank(pct=True)

    # def safe_normalize(x):
    #     min_val = x.min()
    #     max_val = x.max()
    #     if min_val == max_val:  # Use np.isclose for float comparison
    #         return 5  # Return middle value if all values are the same
    #     else:
    #         return (x - min_val) / (max_val - min_val) * 10
    def safe_normalize(x):
        min_val = x.min()
        max_val = x.max()
        return (x - min_val) / (max_val - min_val) * 10
    # Calculer les scores avec pondération
    df[list_score_col] = df.groupby(['Exchange Country Region', ' Benchmark ICB Industry '], group_keys=False)[list_score_col].apply(safe_normalize)
    df['Multi Avg Percentile'] = df[list_score_col].dot(mf_weighting)
    # df['Multi Avg Percentile'] = df['Multi Avg Percentile'].astype('float')


    univ = copy.deepcopy(df)
    univ['Carbon intensity'] = univ.groupby(' Benchmark ICB Supersector ')['CarbonIntensity_Sales'].rank(pct=True)

    # EXCLUSION PART
    univ = univ[univ[bench_col]>=cut_mkt_cap]
    
    cut_list_noire = False
    if cut_list_noire:
        univ = univ[~(univ.index.isin(liste_noire))]
    # esg_pct = univ['ESG_ANALYST_SCORE'].rank(pct=True)
    # df.loc[df.index.isin(liste_noire),'Exclusion liste noire'] = 1

    #Exclusion des titres sous le seuil d'exclusion sur les scores indiqués (mom, growth et payout ratio normalement) et stockage dans un dataframe correspondant au nouvel univers filtré
    # df_esg_cut = copy.deepcopy(univ)
    # Exemple of exclusion_factors = ['Mom Avg Percentile', 'Growth Avg Percentile', 'DVD Payout FY0', 'ESG_ANALYST_SCORE', 'CarbonIntensity_Sales']
    # Exemple of exclusion_list = [0.1, 0.1, 0.1, 4.62, 0.2]

    for i, factor in enumerate(exclusion_factors):
        if factor == 'ESG_ANALYST_SCORE':
            # if exclusion_list[i] > 1:
            #     univ = univ.loc[univ['ESG_ANALYST_SCORE'] >= exclusion_list[i]]
            #     df.loc[df['ESG_ANALYST_SCORE'] < exclusion_list[i], 'Exclusion ESG'] = 1
            #     df_esg_cut = df_esg_cut.loc[df_esg_cut['ESG_ANALYST_SCORE'] >= exclusion_list[i]]
            # else:
            #     df_esg_cut = df_esg_cut.loc[esg_pct >= exclusion_list[i]]
            #     univ = univ.loc[esg_pct >= exclusion_list[i]]
            if exclusion_list[i]>0:
                univ = univ.loc[univ['ESG_ANALYST_SCORE'] >= exclusion_list[i]]
        # if factor == 'DVD Payout FY0':
        #     df_filtered = df_filtered.loc[df_filtered[factor] <= 1-exclusion_list[i]]
        # elif factor == 'CarbonIntensity_Sales':
        #     df_filtered = df_filtered.loc[(df_filtered['Carbon intensity'] <= 1-exclusion_list[i]) | (df_filtered['CarbonIntensity_Sales'] <= carbon_intensity_bench)]
        # else:
        #     df_filtered = df_filtered.loc[df_filtered[factor] >= exclusion_list[i]*10]

    df_filtered = pd.DataFrame(columns=univ.columns)

    # df_filtered['Repechage'] = 0
    # df_filtered['Raison repechage'] = '-'

    # On choisit les X plus gros boites
    if top_mandatory != 0:
        df_filtered = univ.nlargest(top_mandatory,bench_col)

        df_filtered.loc[:,'Repechage'] = 1
        df_filtered.loc[:,'Raison repechage'] = 'Top mandatory'


    
        # missing_top_3 = list(set(df_main_weights.nlargest(int(top_mandatory[1]),bench_col).index)-set(df_filtered.index))
        


    #Check nb titres sur les régions, repêchage si nécessaire
    for repechage_type in liste_repechage:
        if repechage_type == 'Exchange Country Region':
            weight_repart = weight_region_bench
            max_mean_weights = max_mean_weights_r
            df_filtered = repechage_sec_list(df_filtered,univ, weight_repart, max_mean_weights,critere_repechage,repechage_type)
        elif repechage_type == 'Benchmark ICB Supersector ':
            weight_repart = weight_secto_bench
            max_mean_weights = max_mean_weights_s
            df_filtered = repechage_sec_list(df_filtered, univ, weight_repart, max_mean_weights,critere_repechage,' '+repechage_type)
        elif repechage_type == "Size" :
            weight_repart = weight_size_bench
            max_mean_weights = max_mean_weights_size
            df_filtered = repechage_sec_list(df_filtered, univ, weight_repart, max_mean_weights,critere_repechage, 'Size')
        elif repechage_type == 'Top weights':
            #Check nb titres parmi le top n et repêchage si inférieur au nb minimum de titres parmi top n
            df_main_weights = univ.nlargest(nb_top_companies,bench_col)
            df_main_weights_2 = df_main_weights.copy(deep=True)
            missing_main_weights = list(set(df_main_weights_2.index) - set(df_filtered.index))
            df_main_weights.reset_index(inplace=True)
            df_main_weights_3 = df_main_weights.reset_index()[df_main_weights.reset_index()['ISIN'].isin(missing_main_weights)].set_index('ISIN')
            # df_top_mf_companies = df_main_weights.nlargest(min_top_companies, bench_col)
            # df_top_mf_companies.set_index("ISIN", inplace=True)
            df_filtered = pd.concat([df_filtered, repechage(df_main_weights_3,'No filter','None',critere_repechage,len(df_main_weights_3))])
            # df_filtered = pd.concat([df_filtered, df_top_mf_companies])
            # df_filtered.drop(columns=['index'], inplace=True)
            
            # nb_top_companies_seclist = nb_top_companies - len(missing_main_weights)
            # if nb_top_companies_seclist < min_top_companies:
            #     df_main_weights.reset_index(inplace=True)
            #     df_main_weights = (df_main_weights[df_main_weights['ISIN'].isin(missing_main_weights)]).set_index('ISIN')
            #     df_filtered = pd.concat([df_filtered, repechage(df_main_weights,'No filter','None',critere_repechage,min_top_companies-nb_top_companies_seclist)])



    #Matrice de covariance de la sec list for calculating BETA
    returns = returns[df['Company SEDOL'].values]
    returns = returns.loc[:,~returns.columns.duplicated()]
    bench_returns = compute_bench_returns(df,returns, bench_col)
    df.reset_index(inplace=True)
    df['Beta'] = df['ISIN'].apply(lambda x: linregress(bench_returns.values, returns[df.loc[df['ISIN'] == x,'Company SEDOL'].values[0]]).slope)
    df.set_index('ISIN',inplace=True)
    df_filtered['Beta'] = df['Beta']
    #ewma_cov_mat = ewma_cov(returns, 0.98)


    #Sec list finale pour l'optim
    columns_optim = ['Name','Benchmark Market Value Millions in EUR', 'Exchange Country Name', bench_col, 'Exchange Country Region', ' Benchmark ICB Supersector ','DVD Yield FY1',
                        'CarbonIntensity_Sales', 'ESG_E', 'ESG_S','ESG_G', 'ESG_ANALYST_SCORE', 'Beta', 'Analyst Score', 'Size']
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



    ###### Attribuer min ub en fonction de la taille des poids dans bench
    for i, bucket in enumerate(bucket_min_ub):
        if i == 0:
            sec_list.loc[sec_list[bench_col]<=bucket,'min_ub'] = sec_list.merge(right=min_ub_r.iloc[:,i+1], how='left', left_on='Exchange Country Region',right_index=True)['min_ub_'+str(i+1)]
        elif i == len(bucket_min_ub)-1:
            sec_list.loc[sec_list[bench_col]>bucket,'min_ub'] = sec_list.merge(right=min_ub_r.iloc[:,i], how='left', left_on='Exchange Country Region',right_index=True)['min_ub_'+str(i+1)]
        else:
            sec_list.loc[(sec_list[bench_col]<=bucket)*(sec_list[bench_col]>bucket_min_ub[i-1]),'min_ub'] = sec_list.merge(right=min_ub_r.iloc[:,i], how='left', left_on='Exchange Country Region',right_index=True)['min_ub_'+str(i+1)]



    ##### attribuer min lb
    sec_list.loc[sec_list[bench_col]>min_lb[0],'min_lb'] = sec_list.merge(right=min_lb_r, how='left', left_on='Exchange Country Region',right_index=True)['min_lb']

    ### transformation lb et ub
    sec_list['lb'] = sec_list[bench_col]/sec_list['divide_lb']
    sec_list['ub'] = sec_list[bench_col]*sec_list['multiply_ub']
    sec_list.loc[sec_list['ub'] < sec_list['min_ub'], 'ub'] = sec_list['min_ub']
    sec_list.loc[sec_list['lb'] < sec_list['min_lb'], 'lb'] = sec_list['min_lb']
    sec_list.loc[sec_list['lb'] < min_weight, 'lb'] = min_weight
    sec_list.loc[sec_list['ub'] > max_weight, 'ub'] = max_weight




    sec_list.rename(columns={bench_col:'Weight', 'DVD Yield FY1':'Dvd yield', 'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector',
                                'CarbonIntensity_Sales':'Carbon Intensity'}, inplace=True)
    bench_list.rename(columns={bench_col:'Weight', 'DVD Yield FY1':'Dvd yield', 'Exchange Country Region':'Region', ' Benchmark ICB Supersector ':'Sector',
                                'CarbonIntensity_Sales':'Carbon Intensity'}, inplace=True)
    # sec_list.sort_values(by='Weight', ascending=False)
    # bench_list.sort_values(by='Weight', ascending=False)
    bench_list['Weight_ptf'] = sec_list['Weight']  # create a new column in bench to show if we put weight to certains titles, this will use to find ptf in excel page OUTPUT
    bench_list['Weight_ptf'] = bench_list['Weight_ptf'].fillna(0)
    bench_list = bench_list.merge(right=transpa_secto,how='left', left_on='Sector', right_index=True)
    bench_list['Sector'] = bench_list['transpa_secto']
    bench_list.drop(columns='transpa_secto',inplace=True)
    bench_list[['lb','ub']] = sec_list[['lb','ub']]
    bench_list['Repechage'] = bench_list['Repechage'].fillna('-')
    bench_list['Sedol'] = df['Company SEDOL']

    bench_list['Benchmark Market Value Millions in EUR'] = bench_list['Benchmark Market Value Millions in EUR'].fillna(0)
    bench_list.loc[bench_list['Dividend Avg Percentile'].isna(),'Dividend Avg Percentile'] = 0
    


    bench_result = [list(bench_list.index),list(bench_list['Name'].values),list(bench_list['Exchange Country Name'].values),list(bench_list['Region'].values),list(bench_list['Sector'].values),
            list(bench_list['Weight'].values),list(bench_list['ESG_E'].values),list(bench_list['ESG_S'].values),list(bench_list['ESG_G'].values),list(bench_list['ESG_ANALYST_SCORE'].values),
            list(bench_list['Dvd yield'].values),list(bench_list['Earnings yield'].values),list(bench_list['Carbon Intensity'].values),list(bench_list['Weight_ptf'].values),
            list(bench_list["Growth Avg Percentile"].values),list(bench_list["Mom Avg Percentile"].values),list(bench_list["Quality Avg Percentile"].values),list(bench_list["Value Avg Percentile"].values),
            list(bench_list["Dividend Avg Percentile"].values),list(bench_list['Multi Avg Percentile'].values),list(bench_list['Repechage'].values),list(bench_list['Raison repechage'].values),
            list(bench_list['lb'].values),list(bench_list['ub'].values),list(bench_list['Beta'].values),list(bench_list['Sedol'].values),
            # list(bench_list['Exclusion liste noire'].values), list(bench_list['Exclusion ESG'].values), 
            list(bench_list['Benchmark Market Value Millions in EUR'].values), list(bench_list['Size'].values), list(bench_list['Analyst Score'].values)]
    return bench_result


def clean_and_convert_to_float(df, column_name, replace_value=1000):
    # Convert column to string type to ensure .str methods work
    df[column_name] = df[column_name].astype(str)
    
    # Use a regular expression to identify numeric values
    numeric_mask = df[column_name].str.match(r'^-?\d*\.?\d+$')
    
    # Replace non-numeric values with the specified replace_value
    df.loc[~numeric_mask, column_name] = replace_value
    
    # Convert the column to float
    df[column_name] = df[column_name].astype(float)
    
    return df


@xl_macro('var[][] ptf, var[][] bench, str[] list_region, int[] list_secto, str[] list_size, str returns, str optim_type, float[][] bornes_region, float[][] bornes_secto, float[][] bornes_size, float[] beta_target, str date, str[] col_bench, str[] col_sec_list,  str critere_repechage, var[][] mf_formula, float ineq_te, str[] constraints_to_consider')
def ES_launch_optim(ptf, bench, list_region, list_secto, list_size,
                    returns, optim_type, 
                    bornes_region, bornes_secto, bornes_size,
                    beta_target, 
                    date_, 
                    col_bench, col_sec_list,
                    critere_repechage,
                    mf_formula,
                    ineq_te,
                    constraints_to_consider 
                    # min_div_yield, reduc_carbon
                    ):

    list_score_col = mf_formula[0]
    mf_weighting = mf_formula[1]


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
        if col != 'Name' and col != 'Country' and col != 'Region' and col != 'Sector' and col != 'Raison repechage' and col != 'Sedol' and col != 'Size':
            sec_list = clean_and_convert_to_float(sec_list, col, 0)
            sec_list[col] = sec_list[col].astype(float)
    for col in df.columns:
        if col != 'Name' and col != 'Country' and col != 'Region' and col != 'Sector' and col != 'Sedol' and col != 'Size':
            df = clean_and_convert_to_float(df, col, 0)
            df[col] = df[col].astype(float)
    df.replace(100000,float('NaN'),inplace=True)
    sec_list.replace(100000,float('NaN'),inplace=True)

    # esg_bench = (df.loc[pd.notna(df['Score ESG']), 'Score ESG'].dot(df.loc[pd.notna(df['Score ESG']), 'Weight']))/df.loc[pd.notna(df['Score ESG']), 'Weight'].sum()
    # carbon_intensity_bench = (df.loc[pd.notna(df['Carbon Intensity']), 'Carbon Intensity'].dot(df.loc[pd.notna(df['Carbon Intensity']), 'Weight']))/df.loc[pd.notna(df['Carbon Intensity']), 'Weight'].sum()
    # max_carbon_intensity = carbon_intensity_bench*(1+reduc_carbon)



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




    lb_region = pd.Series(data = bornes_region[0], index = list_region).sort_index()
    ub_region = pd.Series(data = bornes_region[1], index = list_region).sort_index()
    lb_secto = pd.Series(data = bornes_secto[0], index = list_secto).sort_index()
    ub_secto = pd.Series(data = bornes_secto[1], index = list_secto).sort_index()
    lb_size = pd.Series(data = bornes_size[0], index = list_size).sort_index()
    ub_size = pd.Series(data = bornes_size[1], index = list_size).sort_index()
    list_region.sort()
    list_secto.sort()
    list_size.sort()



    #Bornes secto et bornes region
    max_secto = sec_list.groupby('Sector')['ub'].sum()
    min_secto = sec_list.groupby('Sector')['lb'].sum()
    max_region = sec_list.groupby('Region')['ub'].sum()
    min_region = sec_list.groupby('Region')['lb'].sum()
    max_size = sec_list.groupby('Size')['ub'].sum()
    min_size = sec_list.groupby('Size')['lb'].sum()

    #### patch for small size, a changer plus tard
    def ensure_list_item(column_name, min_, max_):
        if column_name not in max_.index:
            max_[column_name] = 0
            max_ = max_.sort_index()
        if column_name not in min_.index:
            min_[column_name] = 0
            min_ = min_.sort_index()
        
        return min_, max_
    
    for item in list_size:
        min_size, max_size = ensure_list_item(item, min_size, max_size)
    for item in list_region:
        min_region, max_region = ensure_list_item(item, min_region, max_region)
    for item in list_secto:
        min_secto, max_secto = ensure_list_item(item, min_secto, max_secto)


    missing_region = list(set(list_region) - set(max_region.index))
    if len(missing_region)>0:
        fill_missing = [0] * len(missing_region)
        max_region=(pd.concat([max_region, pd.Series(data=fill_missing, index = missing_region)])).sort_index()
        min_region=(pd.concat([min_region, pd.Series(data=fill_missing, index = missing_region)])).sort_index()

    lb_secto = np.minimum(np.array(lb_secto), max_secto)
    ub_secto = np.maximum(np.array(ub_secto), min_secto)
    lb_region = np.minimum(np.array(lb_region), max_region)
    ub_region = np.maximum(np.array(ub_region), min_region)
    lb_size = np.minimum(np.array(lb_size), max_size)
    ub_size = np.maximum(np.array(ub_size), min_size)



    #Création matrice themes et vecteur ineq pour contraintes d'inégalités : A.x - b >= 0
    theme_region = transform_flag_to_theme(sec_list['Region'], list_flag=list_region)
    theme_secto = transform_flag_to_theme(sec_list['Sector'], list_flag=list_secto)
    theme_size = transform_flag_to_theme(sec_list['Size'], list_flag = list_size)


    # x0 = [1/len(sec_list)]*len(sec_list)
    x0 = ((sec_list['lb'] + sec_list['ub'])/2).values



    constraints_to_consider = list(filter(None, constraints_to_consider))
    # Initialize empty lists to store parts of A_ineq and ineq
    A_ineq_parts = []
    ineq_parts = []

    # Check for each constraint and add corresponding parts
    if 'region' in constraints_to_consider:
        A_ineq_parts.extend([theme_region, theme_region * (-1)])
        ineq_parts.extend([lb_region, ub_region * (-1)])

    if 'sector' in constraints_to_consider:
        A_ineq_parts.extend([theme_secto, theme_secto * (-1)])
        ineq_parts.extend([lb_secto, ub_secto * (-1)])

    if 'size' in constraints_to_consider:
        A_ineq_parts.extend([theme_size, theme_size * (-1)])
        ineq_parts.extend([lb_size, ub_size * (-1)])

    # Concatenate the parts to form A_ineq and ineq
    A_ineq = np.concatenate(A_ineq_parts, axis=0)
    ineq = np.concatenate(ineq_parts, axis=0)

    A_eq = np.ones(len(x0)).reshape(1,-1)
    eq = [1]

    if optim_type == "Min TE":
        weights_optim = optim_mai(compute_te, x0, A_eq, A_ineq, eq, ineq, sec_list['lb'], sec_list['ub'], weight_bench.values, ewma_cov_mat, in_ptf)

    if optim_type == "Limite Max TE":
        def safe_normalize(x):
            min_val = x.min()
            max_val = x.max()
            return (x - min_val) / (max_val - min_val) * 10
       
        def max_score(x, score):
            return -x.dot(score)
        success = False
        while success == False:
            weights_optim, success = optim_mai_te_constr(max_score, x0, A_eq, A_ineq, eq, ineq, sec_list['lb'], sec_list['ub'], ineq_te, weight_bench.values, ewma_cov_mat, in_ptf, sec_list["Multi score"])
            ineq_te += 0.005

    sec_list['Weight'] = weights_optim
    ptf_te = compute_te(weights_optim, weight_bench.values, ewma_cov_mat, in_ptf)
    sec_list['ptf_te'] = ptf_te
    
    sec_list = sec_list.merge(right=transpa_secto,how='left', left_on='Sector', right_index=True)
    sec_list['Sector'] = sec_list['transpa_secto']
    sec_list.drop(columns='transpa_secto',inplace=True)
    sec_list.sort_values(by='Weight', ascending=False)
    sec_list_result = [list(sec_list.index)]
    for i in range(1,len(col_sec_list)):
        sec_list_result.append(list(sec_list[col_sec_list[i]].values))
    sec_list_result.append(list(sec_list['ptf_te'].values))

    return sec_list_result


@xl_macro('str screen, str[] list_region, str bench_name, float[] list_cap')
def ES_bench_weights_agg(screen, list_region, bench_name, list_cap):

    #Lecture screen et returns
    if type(screen) == str:
        df = read_screen(screen)
    else:
        df = screen

    bench_name = "Weight in " + bench_name

    # #Merging des poids google
    # df.loc['US02079K3059', bench_name] = df.loc['US02079K3059', bench_name] + df.loc['US02079K1079', bench_name]
    # df.drop(index='US02079K1079', inplace=True)


    df = df[df['Company SEDOL'].notna()]
    df = df[df[bench_name]>0]
    df = df[df['Exchange Country Region'].isin(list_region)]
    df[bench_name] /= df[bench_name].sum()

    if bench_name == 'Weight in STOXX EUROPE 600':
        df['Exchange Country Region'] = "West Europe"


    #Poids par zone géo et par secteur du bench, dvd yield moyen et carbon intensity moyenne
    weight_secto_bench = df.groupby(' Benchmark ICB Supersector ')[bench_name].sum() / df[bench_name].sum()
    weight_region_bench = df.groupby('Exchange Country Region')[bench_name].sum() / df[bench_name].sum()


    # Determiner le size
    cap_thd_small = list_cap[0]
    cap_thd_mid = list_cap[1]

    def categorize_size(value):
        if value < cap_thd_small:
            return 'small'
        elif value < cap_thd_mid:
            return 'mid'
        else:
            return 'large'

    df['Size'] = df['Benchmark Market Value Millions in EUR'].apply(categorize_size)
    weight_size_bench = df.groupby('Size')[bench_name].sum() / df[bench_name].sum()
    
    missing_region = list(set(list_region) - set(weight_region_bench.index))
    if len(missing_region)>0:
        fill_missing = [0] * len(missing_region)
        weight_region_bench=(pd.concat([weight_region_bench, pd.Series(data=fill_missing, index = missing_region)])).sort_index()

    return [list(weight_region_bench.values), list(weight_secto_bench.values), list(weight_size_bench.values)]