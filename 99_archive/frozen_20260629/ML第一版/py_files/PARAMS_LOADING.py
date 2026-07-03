# Suppress warnings
import warnings
warnings.filterwarnings('ignore')

# Standard Python libraries
import os

# Data manipulation
import pandas as pd
import numpy as np

def get_all_params_from_excel(Excel_Launcher_path):
    """
    Load and extract parameter configurations from Excel file sheets.

    Args:
        Excel_Launcher_path (str): Path to Excel configuration file
        
    Returns:
        tuple: Contains 4 dataframes:
            - params_principal: Main configuration parameters
            - params_preprocessing: Data preprocessing parameters  
            - params_strat_selected: Selected ML strategy parameters
            - params_hyper_parameters_selected: Selected model hyperparameters
    """
    params_principal = pd.read_excel(Excel_Launcher_path, header=0, index_col=0, sheet_name="Principal")
    strat_ml_selected = params_principal.loc['strat ML', "param"]

    params_preprocessing = pd.read_excel(Excel_Launcher_path, header=0, sheet_name="Preprocessing")

    params_strat = pd.read_excel(Excel_Launcher_path, header=0, sheet_name="Strat_ML")
    params_strat_selected = process_strategy_columns(params_strat, strat_ml_selected)

    params_hyper_parameters = pd.read_excel(Excel_Launcher_path, header=0, index_col=0, sheet_name="Hyper_parameters")
    ML_algo_selected = get_items_params_without_nan(params_strat_selected['algo'])
    params_hyper_parameters_selected = params_hyper_parameters[ML_algo_selected]

    return params_principal, params_preprocessing, params_strat_selected, params_hyper_parameters_selected


def create_feature_constraints(params_strat_selected):
    """Create feature constraints dictionary from strategy parameters."""
    return dict(zip(
        get_items_params_without_nan(params_strat_selected['X']),
        get_items_params_without_nan(params_strat_selected['X_constraints'])
    ))

def unpack_strategy_parameters(params_strat_selected):
    """Extract and return strategy parameters from the input dictionary."""
    return {
        'period_to_predict': get_items_params_without_nan(params_strat_selected['period_to_predict']),
        'returns_type': get_items_params_without_nan(params_strat_selected['Y']),
        'features': get_items_params_without_nan(params_strat_selected['X']),
        'min_pct_avail_features': get_items_params_without_nan(params_strat_selected['min_avail_features']),
        'fill_na_method': get_items_params_without_nan(params_strat_selected['fill_na_X']),
        'model_name': get_items_params_without_nan(params_strat_selected['algo']),
        'sampling_method': get_items_params_without_nan(params_strat_selected['sampling_method']),
        'training_window': get_items_params_without_nan(params_strat_selected['training_window_yr']),
        'test_window': get_items_params_without_nan(params_strat_selected['test_window_mth']),
        'obs_weight': get_items_params_without_nan(params_strat_selected['obs_weight']),
        'type_label': get_items_params_without_nan(params_strat_selected['type_label']),
        'feature_constraints': create_feature_constraints(params_strat_selected)
    }

def process_strategy_columns(df, strategy_name='XGBoost_prod'):
    """
    Find a specific strategy in a dataframe and extract its configuration columns.
    
    Args:
        df (pandas.DataFrame): Input dataframe containing strategy configurations
        strategy_name (str): Name of the strategy to search for (default: 'XGBoost_prod')
    
    Returns:
        pandas.DataFrame: A dataframe containing 24 columns starting from the strategy column,
                         with cleaned column names (removed .number suffixes)
    
    Raises:
        ValueError: If the strategy is not found in any column
    """
    # Initialize variables to store the found column info
    strategy_col = None  # Will store the column name
    strategy_idx = None  # Will store the column index
    
    # Iterate through all columns to find where the strategy exists
    for idx, col in enumerate(df.columns):
        # Check if the strategy name exists in any row of this column
        if df[col].eq(strategy_name).any():
            strategy_col = col
            strategy_idx = idx
            break
    
    # If strategy wasn't found, raise an error
    if strategy_idx is None:
        raise ValueError(f"Strategy {strategy_name} not found in any column")
    
    # Select 24 columns starting from the found strategy column
    # This includes the strategy column and 23 following columns
    selected_cols = df.columns[strategy_idx:strategy_idx+24]
    selected_df = df[selected_cols].copy()  # Create a copy to avoid modifying original
    
    # Clean up column names by removing .number suffixes
    # Example: 'strat_ML.16' becomes 'strat_ML'
    clean_columns = [col.split('.')[0] if '.' in col else col for col in selected_df.columns]
    selected_df.columns = clean_columns
    
    return selected_df

def get_items_params_without_nan(df):
    """
    Transforme un DataFrame en liste ou un élément unique après suppression des valeurs manquantes (NaN).

    Args:
        df (DataFrame)

    Returns:
        Un élément unique ou une liste :
        - Si une seule valeur reste après suppression des NaN, cette valeur unique est retournée.
        - Si plusieurs valeurs restent, une liste de ces valeurs est retournée.
        - Si aucune valeur ne reste, une liste vide est retournée.
    """
    lst = df.dropna().tolist()
    return lst[0] if len(lst) == 1 else lst

def load_pickle_files(screen_path, returns_path):
    """
    Loader les pickle et convertit l'index en type Date.

    Args:
        screen_path (str) : Le chemin d'accès au fichier pickle contenant toutes nos variables fondamentales et techniques téléchargées mensuellement (screen_agg).
        returns_path (str) : Le chemin d'accès au fichier pickle contenant tous nos rendements historiques téléchargés quotidiennement (df_returns).

    Returns:
        tuple :
            - screen_agg (pd.DataFrame)
            - df_returns (pd.DataFrame)
    """
    screen_agg = pd.read_pickle(screen_path)
    df_returns = pd.read_pickle(returns_path)
    df_returns.set_index(pd.to_datetime(df_returns.index), inplace=True)
    return screen_agg, df_returns