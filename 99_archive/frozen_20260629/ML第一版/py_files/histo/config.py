# Backtesting (BT) Config
screen_path	= r"C:\GoogleDrive\TP\screen\screen_aggregate.pkl"
returns_path = r"C:\GoogleDrive\TP\screen\returns.pkl"
df_features_path = r"\\groupe-ufg.com\Commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\1_FACTEUR_ML - projet fin 2024\input_files\screen_ML_prod.pkl"
output_file_BT	= r"\\groupe-ufg.com\Commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\1_FACTEUR_ML - projet fin 2024\BT\BT.xlsx"
use_preprocessed_data = True
univ = "STOXX EUROPE 600"
meta_model	= True

# Prod Config
output_file = r"\\groupe-ufg.com\commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\1_FACTEUR_ML - projet fin 2024\Output\Prod.xlsx"


preprocessing_id = "preprocessing_prod"

strat_ML = 'XGBoost_prod' # pour prod
strat_ML_list = ['XGBoost_last'] # pour BT

###################################################################################################################################################################################################
######################################################################################## Preprocessing Parameters #################################################################################
###################################################################################################################################################################################################
{'preprocessing_prod': {'X': ['Dividend Avg Percentile',
   'Value Avg Percentile',
   'Quality Avg Percentile',
   'Mom Avg Percentile',
   'LowVol Avg Percentile',
   'Growth Avg Percentile'],
  'Y': 'returns',
  'returns_neutral': 'ICB19',
  'returns_horizon': [1.0, 3.0, 6.0, 12.0],
  'variations_freq': [1.0, 3.0, 6.0, 12.0]}}

###################################################################################################################################################################################################
######################################################################################## Hyper-Parameters ########################################################################################
###################################################################################################################################################################################################
params_preprocessing = {'X': ['Dividend Avg Percentile',
   'Value Avg Percentile',
   'Quality Avg Percentile',
   'Mom Avg Percentile',
   'LowVol Avg Percentile',
   'Growth Avg Percentile'],
  'Y': 'returns',
  'returns_neutral': 'ICB19',
  'returns_horizon': [1.0, 3.0, 6.0, 12.0],
  'variations_freq': [1.0, 3.0, 6.0, 12.0]}


params = {
    "XGBoost": {
        "subsample": 0.9,
        "reg_lambda": 0,
        "reg_alpha": 1,
        "n_estimators": 500,
        "min_child_weight": 5,
        "max_depth": 5,
        "learning_rate": 0.01,
        "gamma": 0,
        "colsample_bytree": 0.5,
        "objective": "reg:squarederror"
    },
    "XGBoostOptimizer": {
        "subsample": [0.5, 0.7, 0.9],
        "reg_lambda": 0,
        "reg_alpha": 1,
        "n_estimators": [500, 600, 700, 800, 900, 1000],
        "min_child_weight": [1, 3, 5, 7],
        "max_depth": [2, 3, 4, 5],
        "learning_rate": [0.01, 0.03, 0.05],
        "gamma": [0, 0.1, 0.2, 0.3, 0.4],
        "colsample_bytree": [0.5, 0.7, 0.9],
        "objective": "reg:squarederror"
    },
    "XGBoost1": {
        "subsample": 0.9,
        "reg_lambda": 0,
        "reg_alpha": 1,
        "n_estimators": 500,
        "min_child_weight": 5,
        "max_depth": 8,
        "learning_rate": 0.01,
        "gamma": 0,
        "colsample_bytree": 0.5,
        "objective": "reg:squarederror"
    },
    "XGBoost2": {
        "subsample": 0.5,
        "reg_lambda": 1,
        "reg_alpha": 3,
        "n_estimators": 500,
        "min_child_weight": 1,
        "max_depth": 6,
        "learning_rate": 0.01,
        "gamma": 0.1,
        "colsample_bytree": 0.7,
        "objective": "reg:squarederror"
    }
}




X = ['Dividend Avg Percentile',
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
 'Sector 1', 'Sector 2', 'Sector 3', 'Sector 4', 'Sector 5', 'Sector 6', 'Sector 7', 'Sector 8', 'Sector 9', 'Sector 10', 'Sector 11', 'Sector 12', 'Sector 13', 'Sector 14', 'Sector 15', 'Sector 16', 'Sector 17', 'Sector 18', 'Sector 19'
 ]

X_Dividend = ['Dividend Avg Percentile', 
              'Sector 1', 'Sector 2', 'Sector 3', 'Sector 4', 'Sector 5', 'Sector 6', 'Sector 7', 'Sector 8', 'Sector 9', 'Sector 10', 'Sector 11', 'Sector 12', 'Sector 13', 'Sector 14', 'Sector 15', 'Sector 16', 'Sector 17', 'Sector 18', 'Sector 19']

X_Value = ['Value Avg Percentile', 'Value Avg Percentile_change_1M', 'Value Avg Percentile_change_3M', 'Value Avg Percentile_change_6M', 'Value Avg Percentile_change_12M',
           'Sector 1', 'Sector 2', 'Sector 3', 'Sector 4', 'Sector 5', 'Sector 6', 'Sector 7', 'Sector 8', 'Sector 9', 'Sector 10', 'Sector 11', 'Sector 12', 'Sector 13', 'Sector 14', 'Sector 15', 'Sector 16', 'Sector 17', 'Sector 18', 'Sector 19']

X_Quality = ['Quality Avg Percentile', 'Quality Avg Percentile_change_1M', 'Quality Avg Percentile_change_3M', 'Quality Avg Percentile_change_6M', 'Quality Avg Percentile_change_12M', 
             'Sector 1', 'Sector 2', 'Sector 3', 'Sector 4', 'Sector 5', 'Sector 6', 'Sector 7', 'Sector 8', 'Sector 9', 'Sector 10', 'Sector 11', 'Sector 12', 'Sector 13', 'Sector 14', 'Sector 15', 'Sector 16', 'Sector 17', 'Sector 18', 'Sector 19']
X_Mom = ['Mom Avg Percentile', 
         'Sector 1', 'Sector 2', 'Sector 3', 'Sector 4', 'Sector 5', 'Sector 6', 'Sector 7', 'Sector 8', 'Sector 9', 'Sector 10', 'Sector 11', 'Sector 12', 'Sector 13', 'Sector 14', 'Sector 15', 'Sector 16', 'Sector 17', 'Sector 18', 'Sector 19']

X_LowVol = ['LowVol Avg Percentile', 
            'Sector 1', 'Sector 2', 'Sector 3', 'Sector 4', 'Sector 5', 'Sector 6', 'Sector 7', 'Sector 8', 'Sector 9', 'Sector 10', 'Sector 11', 'Sector 12', 'Sector 13', 'Sector 14', 'Sector 15', 'Sector 16', 'Sector 17', 'Sector 18', 'Sector 19']

X_Growth = ['Growth Avg Percentile', 'Growth Avg Percentile_change_1M', 'Growth Avg Percentile_change_3M', 'Growth Avg Percentile_change_6M', 'Growth Avg Percentile_change_12M', 
            'Sector 1', 'Sector 2', 'Sector 3', 'Sector 4', 'Sector 5', 'Sector 6', 'Sector 7', 'Sector 8', 'Sector 9', 'Sector 10', 'Sector 11', 'Sector 12', 'Sector 13', 'Sector 14', 'Sector 15', 'Sector 16', 'Sector 17', 'Sector 18', 'Sector 19']

