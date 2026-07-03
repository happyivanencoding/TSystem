# Suppress warnings
import warnings
warnings.filterwarnings('ignore')

# Standard Python libraries
import os
import copy

# Data manipulation
import pandas as pd
import numpy as np

# Custom modules
from py_files.PARAMS_LOADING import get_items_params_without_nan, load_pickle_files

def preprocess_data(params_principal, params_preprocessing):
    """
    NETTOYAGE DE DONNEES et CREATION DE VARIABLES

    Args:
        params_principal (DataFrame): Onglet "Principal" de l'excel "Launcher ML".
        params_preprocessing (DataFrame): Onglet "Preprocessing" de l'excel "Launcher ML".

    Returns:
        screen_full_feat : Exporte en pickle sous le nom screen_ML_prod.pkl 
    """
    screen_path = params_principal.loc['screen_path', 'param'] #Chemin du screen
    returns_path = params_principal.loc['returns_path', 'param'] #Chemin des rendements historiques
    df_features_path = params_principal.loc['df_features_path', 'param'] #Chemin d'export et d'enregistrement de l'output "screen_full_feat"
    univ = params_principal.loc['univ', 'param'] #Nom du l'univers ici, STOXX EUROPE 600

    features = get_items_params_without_nan(params_preprocessing['X']) #Variables explicatives (Score Value, Dividend, Growth, Quality, Low Volatility, Momentum)
    returns_horizon = get_items_params_without_nan(params_preprocessing['returns_horizon']) #L’horizon de temps à prédire(1,3,6,12 mois)
    variations_freq = get_items_params_without_nan(params_preprocessing['variations_freq']) #Choix de la période utilisé pour calculer les incréments des inputs (1, 3, 6, 12 mois)
    returns_type = get_items_params_without_nan(params_preprocessing['Y']) #Variable expliqué (Rendements)  
    returns_neutral = get_items_params_without_nan(params_preprocessing['returns_neutral'])  #•	Choix de la classification sectorielle utilisé pour être neutre (ICB 19)

    screen_agg, df_returns = load_pickle_files(screen_path, returns_path) #load les pickles screen et returns 
    screen_agg.sort_values(by='Date', inplace=True) #Classe les lignes de screen_agg de maniere a ce que les lignes soit dans l'ordre chronologique

    screen_agg.rename(columns={"Exchange Country Region":"Region",
                            " Benchmark ICB Supersector ":"Sector ICB19",
                            " Benchmark ICB Industry ":"Sector ICB11"},inplace=True) #On Renomme certaines colonnes de screen_agg
    

    screen_clean = screen_cleaning(screen_agg, univ) # Filtre le screen sur l'univers choisit et supprime les doublons

    for horizon in returns_horizon:
        screen_clean = compute_returns(screen_clean, horizon, df_returns, returns_neutral, returns_type)  #On rajoute des colonnes au screen_clean avec des returns forward et return secteur, et ratio d'info personnalisé
    screen_full_feat, new_features = add_features_variation(screen_clean, features, variations_freq) #On a ajoute des colonnes qui sont simplement les variation des features

    
    secto_dummies = pd.get_dummies(screen_full_feat['Sector ICB19']) # Chaque secteur unique devient une colonne, avec des valeurs 0 ou 1 indiquant l'appartenance.
    secto_dummies.columns=['Sector ' + str(i+1) for i in range(19)] # Renommage des colonnes des variables indicatrices pour les rendre plus explicites
    screen_full_feat = pd.concat([screen_full_feat,secto_dummies],axis=1) #On concatenne nos colonnes

    screen_full_feat.to_pickle(df_features_path) #On exporte notre DataFrame final en pickle.


def screen_cleaning(screen_agg, univ): 
    """
    Nettoie et filtre les données de screen_agg en fonction de critères spécifiques.

    Args:
        screen_agg (pd.DataFrame) : Le DataFrame contenant les données brutes à nettoyer.
        univ (str) : L'univers choisi (chez nous c'est STOXX EUROPE 600).

    Returns:
        pd.DataFrame : Un DataFrame nettoyé et filtré.

    """
    screen_clean = copy.deepcopy(screen_agg) #Crée une copie indépendante
    screen_clean = screen_clean[screen_clean['Weight in ' + univ]>0] # Selectionner seulement les lignes où la colonne 'Weight in <univ>' est > 0.
    screen_clean.rename(columns={'Weight in ' + univ: 'Weight in univ'}, inplace=True) # Renomme la colonne
    mask = screen_clean.loc[(screen_clean['Weight in univ']>0)*(screen_clean['Company SEDOL'].notna()),'Company SEDOL'].unique() #Applique un masque pour garder uniquement les lignes dont 'Company SEDOL' n'est pas NaN et dont les poids sont > 0.
    screen_clean = screen_clean.loc[screen_clean['Company SEDOL'].isin(mask)] #On filtre en gardant que les lignes dont le SEDOL est dans notre masque
    screen_clean['Date'] = pd.to_datetime(screen_clean['Date']) #Convertit la colonne 'Date' en format datetime pour garantir une gestion correcte des dates.
    screen_clean.reset_index(inplace=True) #On fait sortir l'index

    screen_clean = screen_clean[~screen_clean[['Company SEDOL','Date','Region','Sector ICB19']].isna().any(axis=1)] #Supprime les lignes qui contiennent au moins une valeur manquante dans une de ces colonnes : 'Company SEDOL','Date','Region','Sector ICB19'.

    screen_clean.set_index(['Date', 'Company SEDOL'], inplace = True) #Construit un nouvel index basé sur la "Date" et le code "SEDOL"
    screen_clean = screen_clean[~screen_clean.index.duplicated(keep='last')] # Supprime les lignes qui ont leur index en commun et garde la derniere occurence si doublon 
    screen_clean.reset_index(inplace=True) #On fait sortir l'index

    return screen_clean

def compute_returns(screen_agg, period_to_predict, df_returns, sector_neutral='ICB19', type='return'):
    """
        Calculer un ratio d'information personnalisé.

        Arguments :
            screen_agg (DataFrame) : DataFrame d'entrée contenant les données au niveau des actions avec des colonnes telles que 
                                    'Company SEDOL', 'Date', etc.
            period_to_predict (int) : Période (en mois) pour laquelle les rendements doivent être calculés.
            df_returns (DataFrame) : DataFrame contenant les rendements historiques des actions indexés par 'Date' et identifiants d'actions.
            sector_neutral (str, optionnel) : Identifiant du secteur pour les calculs neutres par secteur ('ICB19', 'ICB11' ou None). 
                                            Par défaut, 'ICB19'.
            type (str, optionnel) : Type de calcul de rendement (actuellement inutilisé). Par défaut, 'return'.

        Retourne :
            DataFrame : DataFrame mise à jour avec les rendements calculés (actions, neutres par secteur et relatifs), 
                        ainsi que le ratio d'information et les contributions.
    """

    # On verifie que les colonnes SEDOL et Date sont dans les colonnes de screen et les met en index de la dataframe
    if ('Company SEDOL' in list(screen_agg.columns)) and ('Date' in list(screen_agg.columns)):
        data_clean = screen_agg.set_index(['Company SEDOL', 'Date'])
    else:
        data_clean = copy.deepcopy(screen_agg)

    #On cree deux nouvelles colonnes avec l'horizon en mois choisit
    col_stock_returns = f'Stock {period_to_predict}M return'
    col_neutral_returns = f'Neutral {period_to_predict}M return'


    # calculer rendement forward avec l'horizon choisit pour chaque paire SEDOL/Date
    # X[1] DATE, X[0] Sedol sont les row columns de df_returns
    # data_clean[col_stock_returns] = list(data_clean.index.map(lambda x: ((1+df_returns[x[1] : x[1]+pd.DateOffset(days=int(period_to_predict)*30)][x[0]]).cumprod()-1).iloc[-1]))
    # data_clean[col_stock_returns] = list(
    #     data_clean.index.map(
    #         lambda x: (
    #             # Calculer le rendement cumulé sur la période spécifiée
    #             (1 + df_returns[x[1] : x[1] + pd.DateOffset(days=int(period_to_predict) * 30)][x[0]])
    #             .cumprod() - 1  # Produit cumulé des rendements moins 1 pour obtenir le rendement total
    #         ).iloc[-1]  # Prendre la dernière valeur de la série de rendements cumulés (c'est-à-dire le rendement final)
    #     )
    # )

    # Set Missing Sedol as NaN
    def safe_get_return(x):
        try:
            return (
                (1 + df_returns[x[1] : x[1] + pd.DateOffset(days=int(period_to_predict) * 30)][x[0]])
                .cumprod() - 1
            ).iloc[-1]
        except (KeyError, IndexError):
            return np.nan
    
    data_clean[col_stock_returns] = list(data_clean.index.map(safe_get_return))
    
    # Drop rows with NaN
    data_clean = data_clean.dropna(subset=[col_stock_returns])


    #On créé une colonne Market Cap pour prendre la racine cubique de la Market Cap classique
    data_clean['smooth_cap'] = data_clean['Benchmark Market Value Millions in EUR']**(1/3) 


    if (sector_neutral == 'ICB19') or (sector_neutral == 'ICB11'): # par secteur => secteur neutre
        # Calcule les returns single stock pondéré intra-sectorielle
        df_sectors = data_clean.reset_index(level=1).groupby(['Date', 'Sector ' + sector_neutral]).apply(lambda x: (x['Weight in univ'].dot(x[[col_stock_returns]]))/x['Weight in univ'].sum())
        df_sectors.columns= [col_neutral_returns]

        # Calcule la market cap racine cubique de chaque secteur a chaque date pour les différentes périodes à prédire
        df_sectors[f'm_cap_bench {period_to_predict}M'] = data_clean.reset_index(level=1).groupby(['Date', 'Sector ' + sector_neutral])['smooth_cap'].sum()


        data_clean.reset_index(inplace=True)
        df_sectors.reset_index(inplace=True)
        # Assemblage des deux dataframe sur la clé primaire ("Date", "Sector <sector_neutral>")
        data_clean = data_clean.merge(df_sectors,how='left', on=['Date', 'Sector ' + sector_neutral]).set_index(['Company SEDOL','Date'])
    else: # marché neutre 
        df_market = data_clean.reset_index(level=1).groupby(['Date']).apply(lambda x: (x['Weight in univ'].dot(x[[col_stock_returns]]))/x['Weight in univ'].sum())
        df_market.columns= [col_neutral_returns]
        df_market[f'm_cap_bench {period_to_predict}M'] = data_clean.reset_index(level=1).groupby(['Date'])['smooth_cap'].sum()
        data_clean.reset_index(inplace=True)
        df_market.reset_index(inplace=True)
        data_clean = data_clean.merge(df_market,how='left', on=['Date']).set_index(['Company SEDOL','Date'])

    # Calcul rendement relatif Forward par rapport à son secteur Forward
    data_clean['Relative ' +str(period_to_predict) + 'M return'] = data_clean['Stock ' +str(period_to_predict) + 'M return'] - data_clean['Neutral ' +str(period_to_predict) + 'M return']

    # Contrib sectoriel grâce à la ponderation de la market cap en racine cubique qui permet de legerement penaliser les gros poids 
    data_clean['contrib ' +str(period_to_predict) + 'M' ] = (data_clean['smooth_cap']/data_clean[f'm_cap_bench {period_to_predict}M'])*data_clean['Relative ' +str(period_to_predict) + 'M return']

    #On supprimes les colonnes qu'on avait transformé via racine cubique ('m_cap_bench {period_to_predict}M', 'smooth_cap')
    data_clean = data_clean.drop([f'm_cap_bench {period_to_predict}M', 'smooth_cap'], axis = 1)

    # Calcul de la volatilité dynamique via une volitité calculé sur une fenetre en expansion (et non pas rolling)
    rolling_std = data_clean.groupby(level="Company SEDOL")['Relative ' +str(period_to_predict) + 'M return'].expanding().std().droplevel(0)

    # Calcul de l'information ratio via une transformation exponentielle de la volatilité afin de pénaliser davantages l'information ratio au fur et à mesure quela volatilité est grande
    data_clean['information_ratio '+ str(period_to_predict) + 'M'] = data_clean['Relative ' +str(period_to_predict) + 'M return']/np.exp(rolling_std)
    
    return data_clean


def add_features_variation(df, features, time_periods):
    """
    Ajoute des colonnes de variations en pourcentage.

    Paramètres :
    - df : pandas DataFrame
    - features : Liste des colonnes pour lesquelles calculer les variations.
    - time_periods : Liste des périodes de temps (en mois) à utiliser pour le calcul.

    Retourne :
    - df : Le DataFrame enrichi avec les nouvelles colonnes.
    - col_name_list : La liste des noms des colonnes ajoutées.
    """
    col_name_list = []  # Initialisation d'une liste pour stocker les noms des nouvelles colonnes

    # Boucle sur chaque colonne spécifiée dans 'features'
    for feature in features:
        # Boucle sur chaque période spécifiée dans 'time_periods'
        for period in time_periods:
            # Création du nom de la nouvelle colonne
            col_name = f"{feature}_change_{int(period)}M"
            col_name_list.append(col_name)  # Ajout du nom de la colonne à la liste

            # Calcul de la variation en pourcentage pour la colonne et la période spécifiées
            # La méthode 'pct_change' calcule le pourcentage de variation par rapport à la période précédente
            # 'groupby(level=0)' garantit que le calcul est effectué par groupe (ici, le premier niveau de l'index)
            df[col_name] = df.groupby(level=0)[feature].pct_change(periods=int(period))

            # Remplacement des valeurs infinies (inf) par 1 ou -1
            # Cela peut se produire si une division par zéro a lieu lors du calcul des variations
            df[col_name].replace({np.inf: 1, -np.inf: -1}, inplace=True)

    # Retourne le DataFrame modifié et la liste des noms des colonnes ajoutées
    return df, col_name_list

    # col_name_list=[]
    # for feature in features:
    #     for period in time_periods:
    #         col_name = f"{feature}_change_{int(period)}M"
    #         col_name_list.append(col_name)
    #         df[col_name] = df.groupby(level=0)[feature].pct_change(periods=int(period))
    #         df[col_name].replace({np.inf: 1, -np.inf: -1}, inplace=True)
    # return df, col_name_list