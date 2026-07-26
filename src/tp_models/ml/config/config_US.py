from tp_core.data_sources import RETURNS_PATH as CANONICAL_RETURNS_PATH
from tp_core.data_sources import SCREEN_AGGREGATE_PATH
params_principal =  {
                    'screen_path': str(SCREEN_AGGREGATE_PATH),
                    'returns_path': str(CANONICAL_RETURNS_PATH),
                    'df_features_path': r"Input_files\screen_ML_US.parquet",
                    'df_features_backtest_path': r"Input_files\screen_ML_US_backtest.parquet",
                    'score_ml_path': r"Output_files\SCORE_ML_US_production.parquet",
                    'score_ml_backtest_path': r"Output_files\SCORE_ML_US_backtest.parquet",
                    'shap_path': r"Output_files\SCORE_ML_US_production_SHAP.parquet",
                    'shap_backtest_path': r"Output_files\SCORE_ML_US_backtest_SHAP.parquet",
                    'list_exclusion_path': r"Portfolio_BT\list_exclusion_US.parquet",
                    'univ': 'Univ ML US'}
                            

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
                            'returns_horizon': [3.0, 6.0],
                            'variations_freq': [1.0, 3.0, 6.0, 12.0],
                            'variation_method':'change_diff' #'change_pct','change_diff'
                        }


params_model = {'period_to_predict': [3.0, 6.0],
                'returns_type': 'info_ratio',
                'ranking_predict_to_score': 'homogenous_mean_and_rank', # rank_and_mean : First rank column then average, mean_and_rank : First average prediction columns then rank, homogenous_mean_and_rank
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
                                'Sector 1',
                                'Sector 2',
                                'Sector 3',
                                'Sector 4',
                                'Sector 5',
                                'Sector 6',
                                'Sector 7',
                                'Sector 8',
                                'Sector 9',
                                'Sector 10',
                                'Sector 11',
                                'Sector 12',
                                'Sector 13',
                                'Sector 14',
                                'Sector 15',
                                'Sector 16',
                                'Sector 17',
                                'Sector 18',
                                'Sector 19'
                            ],
                'min_pct_avail_features': 0.5,

                'training_window': 5.0,
                'prediction_window': 1.0,

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
                                        'Sector 19': 0}}


params_hyper_parameters_prod = {  
    'subsample': 0.9,  
    'reg_lambda': 0.7,  # Régularisation L2 légèrement réduite (de 1 à 0.7) : relâche modérément la contraction des poids.  
    'reg_alpha': 1.0,   # Régularisation L1 = 1 : sparsification des features.  
    'n_estimators': 400,  
    'min_child_weight': 5,  
    'max_depth': 5,  
    'learning_rate': 0.05, # Taux d'apprentissage modéré (0.05).  
    'gamma': 0,  
    'colsample_bytree': 0.6, # Taux d'échantillonnage des colonnes réduit (de 0.9 à 0.6) : augmente la diversité des arbres, atténue la multicolinéarité.  
    'objective': 'reg:squarederror'  
}  


CONFIG = {"PARAMETRES PRINCICALES": params_principal,
        "PARAMETRES PREPROCESSING" : params_preprocessing,
        "PARAMETRES MODELE" : params_model,
        "HYPERPARAMETRES" : params_hyper_parameters_prod
    }
