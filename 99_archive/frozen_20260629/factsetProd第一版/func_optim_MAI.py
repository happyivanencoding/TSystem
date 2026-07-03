from pyxll import xl_macro
import pandas as pd
import numpy as np
from dateutil import relativedelta
import copy
from math import ceil
from scipy.stats import linregress
import scipy.optimize

def read_liste_noire(override_exclusion, override_inclusion, file = r"\\groupe-ufg.com\Commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_BASE\_ ESG DATA\Liste_Noire_Exclusion_NEW.xlsx", key="ISIN"):

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


# def repechage_sec_list(sec_list,univ, weight_repart, max_mean_weights,critere_repechage, repechage_type):

#     nb_titre_repart = sec_list.groupby(repechage_type).apply(lambda x: len(x))
#     missing_value = list(set(weight_repart.index) - set(nb_titre_repart.index))
#     fill_missing = [0.00000001]*len(missing_value)
#     nb_titre_repart = pd.concat([nb_titre_repart, pd.Series(data=fill_missing, index = missing_value)])
#     mean_weight = weight_repart / nb_titre_repart

#     df_concat = copy.deepcopy(sec_list)
#     repechage_values = mean_weight[(mean_weight > max_mean_weights)].index
#     if len(repechage_values)>0:
#         for value in repechage_values:
#             nb_repechage = ceil(weight_repart.loc[value]/max_mean_weights.loc[value] - nb_titre_repart.loc[value])
#             df_repechage = copy.deepcopy(univ).reset_index()
#             df_repechage = (df_repechage[df_repechage['ISIN'].isin(list(set(univ.index) - set(sec_list.index)))]).set_index('ISIN')
#             if nb_repechage > 0:
#                 df_concat = pd.concat([df_concat,repechage(df_repechage,repechage_type,value,critere_repechage,nb_repechage)])

#     return df_concat

def repechage_sec_list(sec_list, univ, weight_repart, max_mean_weights, critere_repechage, repechage_type):
    """
    Fonction qui équilibre un portefeuille en ajoutant des titres dans les catégories où le poids moyen par titre est trop élevé.
    
    Paramètres:
    -----------
    sec_list : DataFrame
        Liste des titres déjà sélectionnés dans le portefeuille
    univ : DataFrame
        Univers complet des titres disponibles pour la sélection
    weight_repart : Series
        Répartition des poids cibles par catégorie (région ou secteur) dans l'indice de référence
    max_mean_weights : Series
        Poids moyen maximum autorisé par titre dans chaque catégorie
    critere_repechage : str
        Critère utilisé pour sélectionner les meilleurs titres à repêcher (ex: "ESG Score")
    repechage_type : str
        Type de catégorisation pour le repêchage (ex: "Exchange Country Region" ou "Benchmark ICB Supersector")
    
    Retourne:
    ---------
    DataFrame
        Liste des titres enrichie des titres repêchés
        
    Exemples:
    ---------
    # Exemple 1: Repêchage par région
    # Supposons que l'on a:
    # - Une sélection initiale de 100 titres (sec_list)
    # - Poids régionaux cibles: Amérique du Nord 65%, Europe 20%, Asie-Pacifique 15%
    # - Distribution actuelle: 40 titres en Amérique du Nord, 30 en Europe, 30 en Asie-Pacifique
    # - Poids moyens maximaux: Amérique du Nord 0.9%, Europe 0.7%, Asie-Pacifique 0.6%
    # 
    # Les poids moyens actuels sont:
    # - Amérique du Nord: 65%/40 = 1.625% > 0.9% (seuil) => Repêchage nécessaire
    # - Europe: 20%/30 = 0.667% < 0.7% (seuil) => OK
    # - Asie-Pacifique: 15%/30 = 0.5% < 0.6% (seuil) => OK
    #
    # Calcul du nombre de titres à repêcher pour l'Amérique du Nord:
    # Nombre cible = 65% / 0.9% = 72.22 => 73 titres (arrondi au supérieur)
    # Titres à repêcher = 73 - 40 = 33 titres
    #
    # La fonction va donc sélectionner les 33 meilleurs titres d'Amérique du Nord 
    # selon le critère spécifié, parmi ceux qui ne sont pas déjà dans la sélection.
    
    # Exemple 2: Repêchage par secteur
    # Supposons les données suivantes pour un repêchage sectoriel:
    # - Poids sectoriels cibles: Technologie 25%, Finance 15%, Santé 12%, etc.
    # - Sélection actuelle: 15 titres en Technologie, 20 en Finance, 18 en Santé, etc.
    # - Poids moyens maximaux: Technologie 0.8%, Finance 0.6%, Santé 0.5%, etc.
    #
    # Les poids moyens actuels sont:
    # - Technologie: 25%/15 = 1.67% > 0.8% => Repêchage nécessaire
    # - Finance: 15%/20 = 0.75% > 0.6% => Repêchage nécessaire
    # - Santé: 12%/18 = 0.67% > 0.5% => Repêchage nécessaire
    #
    # Calculs des titres à repêcher:
    # - Technologie: ceiling(25%/0.8% - 15) = ceiling(31.25 - 15) = 17 titres
    # - Finance: ceiling(15%/0.6% - 20) = ceiling(25 - 20) = 5 titres
    # - Santé: ceiling(12%/0.5% - 18) = ceiling(24 - 18) = 6 titres
    """
    
    # Calcul du nombre de titres par catégorie dans la sélection actuelle
    nb_titre_repart = sec_list.groupby(repechage_type).apply(lambda x: len(x))
    
    # Identification des catégories manquantes dans la sélection actuelle
    missing_value = list(set(weight_repart.index) - set(nb_titre_repart.index))
    fill_missing = [0.00000001]*len(missing_value)  # Valeur très petite pour éviter division par zéro
    
    # Ajout des catégories manquantes avec une valeur quasi-nulle
    # Exemple: si aucun titre d'Amérique Latine n'est présent alors que cette région 
    # existe dans weight_repart, on lui attribue une valeur quasi-nulle
    nb_titre_repart = pd.concat([nb_titre_repart, pd.Series(data=fill_missing, index=missing_value)])
    
    # Calcul du poids moyen par titre dans chaque catégorie
    # Exemple: si l'Amérique du Nord a un poids de 65% et contient 40 titres,
    # son poids moyen sera de 65%/40 = 1.625% par titre
    mean_weight = weight_repart / nb_titre_repart

    # Copie de la liste des titres actuelle pour y ajouter les titres repêchés
    df_concat = copy.deepcopy(sec_list)
    
    # Identification des catégories où le poids moyen par titre dépasse le maximum autorisé
    # Exemple: si le poids moyen max autorisé pour l'Amérique du Nord est de 0.9% mais 
    # que le poids moyen actuel est de 1.625%, cette région sera identifiée pour repêchage
    repechage_values = mean_weight[(mean_weight > max_mean_weights)].index
    
    # S'il existe des catégories nécessitant un repêchage
    if len(repechage_values) > 0:
        for value in repechage_values:
            # Calcul du nombre de titres à repêcher pour rééquilibrer le poids moyen
            # Formule: ceil(poids_cible/poids_moyen_max - nb_titres_actuels)
            # Exemple: pour l'Amérique du Nord, ceil(65%/0.9% - 40) = ceil(72.22 - 40) = 33 titres
            nb_repechage = ceil(weight_repart.loc[value]/max_mean_weights.loc[value] - nb_titre_repart.loc[value])
            
            # Préparation de l'univers des titres disponibles pour le repêchage (exclusion des titres déjà sélectionnés)
            # On prend tous les titres de l'univers qui ne sont pas déjà dans notre sélection
            df_repechage = copy.deepcopy(univ).reset_index()
            df_repechage = (df_repechage[df_repechage['ISIN'].isin(list(set(univ.index) - set(sec_list.index)))]).set_index('ISIN')
            
            # Si le nombre de titres à repêcher est positif, on procède au repêchage
            if nb_repechage > 0:
                # Appel à la fonction repechage pour sélectionner les meilleurs titres selon le critère spécifié
                # Exemple: sélection des 33 titres d'Amérique du Nord ayant les meilleurs scores ESG
                df_concat = pd.concat([df_concat, repechage(df_repechage, repechage_type, value, critere_repechage, nb_repechage)])

    # Retourne la liste des titres complétée avec les titres repêchés
    return df_concat

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
    res=scipy.optimize.minimize(fun,x0, args=(args),method='SLSQP',options = {'maxiter':50000,'ftol': 1e-9},bounds=bnds,constraints=[eq_cons,ineq_cons])
    return res.x












@xl_macro('str screen, var[][] inclusion, var[][] exclusion, var[][] mf_formula, float[] max_mean_weights_values_region, str[] list_region, str critere_repechage, float[] max_mean_weights_values_secto, int[] list_secto, float cut_mkt_cap, int[] top_companies, str returns, float[] divide_lb, float[] multiply_ub, float min_weight, float max_weight, str[] liste repechage, float[] bucket_min_ub, float[][] min_ub_list, str liste_noire, float[] min_lb, var[] top_mandatory,str date_, str[] override_exclusion,str[] override_inclusion')
def get_sec_list(screen, inclusion, exclusion, mf_formula, max_mean_weights_values_region, list_region, critere_repechage, max_mean_weights_values_secto, list_secto, cut_mkt_cap, top_companies, returns, divide_lb, multiply_ub, min_weight, max_weight, liste_repechage, bucket_min_ub, min_ub_list, liste_noire, min_lb, top_mandatory,date_, override_exclusion, override_inclusion):

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