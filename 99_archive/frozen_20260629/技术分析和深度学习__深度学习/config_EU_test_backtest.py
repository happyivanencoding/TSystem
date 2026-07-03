import numpy as np
import torch.nn as nn
from pathlib import Path
import sys

_TP_ROOT = Path(__file__).resolve().parents[2]
if str(_TP_ROOT) not in sys.path:
    sys.path.insert(0, str(_TP_ROOT))

from tp_core.data_sources import RETURNS_PATH as CANONICAL_RETURNS_PATH
from tp_core.data_sources import SCREEN_AGGREGATE_PATH

params_principal =  {'screen_path': str(SCREEN_AGGREGATE_PATH),
                    'returns_path': str(CANONICAL_RETURNS_PATH),
                    'df_features_path': r"\\groupe-ufg.COM\Commun\Prive\GestionAM\Ingenierie_Financiere\DOSSIERS_UTILISATEURS\Yannick\DEEP_LEARNING_PROD\Input_files\screen_ML_prod_EU.pkl",
                    'univ': 'STOXX EUROPE 600'}
         
                            
params_preprocessing = {
                            'X': [
                                  'Dividend Avg Percentile', 
                                  'Value Avg Percentile', 
                                  'Quality Avg Percentile',
                                  'Mom Avg Percentile', 
                                  'LowVol Avg Percentile', 
                                  'Growth Avg Percentile'
                                  ],
                            'Y': ['returns'],
                            'returns_neutral': ['ICB19'],
                            'returns_horizon': [1.0, 3.0, 6.0, 12.0],
                            'variations_freq': [1.0, 3.0, 6.0, 12.0],
                            'variation_method':'change_diff',
                            # 'variation_method':'change_pct',#'change_pct','change_diff'
                        }


params_model = {'period_to_predict': [1.0],
                'returns_type': 'info_ratio',
                'ranking_predict_to_score': 'mean_and_rank', # rank_and_mean : First rank column then average, mean_and_rank : First average prediction columns then rank
                'features': [   'Dividend Avg Percentile',
                                'Value Avg Percentile',
                                'Quality Avg Percentile',
                                'Mom Avg Percentile',
                                'LowVol Avg Percentile',
                                'Growth Avg Percentile',
                                'Value Avg Percentile_change_1M',
                                'Quality Avg Percentile_change_1M',
                                'Growth Avg Percentile_change_1M',
                                'Value Avg Percentile_change_3M',
                                'Quality Avg Percentile_change_3M',
                                'Growth Avg Percentile_change_3M',
                                'Value Avg Percentile_change_6M',
                                'Quality Avg Percentile_change_6M',
                                'Growth Avg Percentile_change_6M',
                                'Value Avg Percentile_change_12M',
                                'Quality Avg Percentile_change_12M',
                                'Growth Avg Percentile_change_12M',
                                # 'Sector 1',
                                # 'Sector 2',
                                # 'Sector 3',
                                # 'Sector 4',
                                # 'Sector 5',
                                # 'Sector 6',
                                # 'Sector 7',
                                # 'Sector 8',
                                # 'Sector 9',
                                # 'Sector 10',
                                # 'Sector 11',
                                # 'Sector 12',
                                # 'Sector 13',
                                # 'Sector 14',
                                # 'Sector 15',
                                # 'Sector 16',
                                # 'Sector 17',
                                # 'Sector 18',
                                # 'Sector 19'
                            ],
                'min_pct_avail_features': 0.5,
                'fill_na_method': 'median',
                'model_name': 'MLP',
                'sampling_method': 'base',

                'testing_window': 12.0, # Jeu de test, date precede trainning window for calculating R^2 as evaluation metrics of production
                'training_window': 5.0,
                'prediction_window': 12.0,
                
                'obs_weight': 'balanced',
                'type_label': 'regression',
                'feature_constraints': {'Dividend Avg Percentile': 1,
                                        'Value Avg Percentile': 1,
                                        'Quality Avg Percentile': 1,
                                        'Mom Avg Percentile': 1,
                                        'LowVol Avg Percentile': 1,
                                        'Growth Avg Percentile': 1,
                                        'Value Avg Percentile_change_1M': 1,
                                        'Quality Avg Percentile_change_1M': 1,
                                        'Growth Avg Percentile_change_1M': 1,
                                        'Value Avg Percentile_change_3M': 1,
                                        'Quality Avg Percentile_change_3M': 1,
                                        'Growth Avg Percentile_change_3M': 1,
                                        'Value Avg Percentile_change_6M': 1,
                                        'Quality Avg Percentile_change_6M': 1,
                                        'Growth Avg Percentile_change_6M': 1,
                                        'Value Avg Percentile_change_12M': 1,
                                        'Quality Avg Percentile_change_12M': 1,
                                        'Growth Avg Percentile_change_12M': 1,
                                        'Sector 1': 0,
                                        'Sector 2': 0,
                                        'Sector 3': 0,
                                        'Sector 4': 0,
                                        'Sector 5': 0,
                                        'Sector 6': 0,
                                        'Sector 7': 0,
                                        'Sector 8': 0,
                                        'Sector 9': 0,
                                        'Sector 10': 0,
                                        'Sector 11': 0,
                                        'Sector 12': 0,
                                        'Sector 13': 0,
                                        'Sector 14': 0,
                                        'Sector 15': 0,
                                        'Sector 16': 0,
                                        'Sector 17': 0,
                                        'Sector 18': 0,
                                        'Sector 19': 0
                                        }
                                        }


params_hyper_parameters_MLP_PROD ={'activation_function_1': nn.ELU(alpha=0.1),
                    'activation_function_2': nn.ELU(alpha=0.1),
                    'activation_function_3': nn.LeakyReLU(negative_slope=0.01),
                    'hidden_units_1': 128,
                    'hidden_units_2': 128,
                    'hidden_units_3': 128}

CONFIG = {"PARAMETRES PRINCICALES": params_principal,
          "PARAMETRES PREPROCESSING" : params_preprocessing,
          "PARAMETRES MODELE" : params_model,
          "HYPERPARAMETRES" : params_hyper_parameters_MLP_PROD,
        }
