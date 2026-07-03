# MLPredictorPipeline.py  

import pandas as pd  
import os  
import shutil  
from datetime import datetime  
from dateutil import relativedelta  
from Codes.ML_PREDICTOR import MLPredictor  
from Codes.ML_PREPROCESS import MLPreprocessor



class ML_MonthlyProdPipeline:  
    """  
    Pipeline class for executing complete ML prediction workflow.  
    
    This class integrates all steps from data loading to result saving.  
    Supports both Production and Backtesting modes.  
    """  


    def __init__(self, CONFIG, mode="Production", preprocessing=False,   
                input_file_path=None, output_path=None, output_file=None,   
                allow_multiprocessing=True, screen_path=None, 
                update_score_ML=False,
                train_window_in_optim=None,
                max_date=None):  
        """  
        Initialize ML prediction pipeline with configurable attributes.  
        
        Args:  
            params_strat: Strategy parameters  
            params_hyper_parameters: Model hyperparameters  
            mode (str): Operating mode - "Production" or "Backtest"  
            input_file_path (str, optional): Path to input data file  
            output_path (str, optional): Path for saving output results  
            output_file (str): Base name for output files in backtest mode  
            allow_multiprocessing (bool): Whether to use multiprocessing in backtest mode  
            screen_path (str, optional): Path to the screen aggregate file  
        """  
        # Core strategy parameters  
        self.param_principal = CONFIG["PARAMETRES PRINCICALES"].copy() 
        self.param_preprocessing = CONFIG["PARAMETRES PREPROCESSING"] 
        self.params_strat = CONFIG["PARAMETRES MODELE"]   
        self.params_hyper_parameters = CONFIG["HYPERPARAMETRES"]

        self.mode = mode 
        self.mode_lower = mode.lower()
        if self.mode_lower not in {"production", "backtest"}:
            raise ValueError(f"Invalid mode: {self.mode}. Must be 'production' or 'backtest'.")
        self.preprocessing = preprocessing 
        
        # 根据模式解析输入输出路径，避免 backtest 与 production 互相覆盖
        self.df_features_path = self._resolve_mode_path('df_features_path', 'df_features_backtest_path')
        self.param_principal['df_features_path'] = self.df_features_path
        self.score_ml_path = self._resolve_mode_path('score_ml_path', 'score_ml_backtest_path')
        self.output_path = output_path  
        self.output_file = output_file  
        self.output_prefix = self._resolve_output_prefix()
        self.score_ml_path = f"{self.output_prefix}.parquet"
        self.shap_path = f"{self.output_prefix}_SHAP.parquet"
        self.param_principal['score_ml_path'] = self.score_ml_path
        self.param_principal['shap_path'] = self.shap_path

        # Pipeline configuration  
        self.input_file_path = input_file_path or self.df_features_path
        self.allow_multiprocessing = allow_multiprocessing  
        self.screen_path = screen_path or CONFIG["PARAMETRES PRINCICALES"]['screen_path'] 
        self.prediction_results = None
        self.shap_values = None 
        self.result_model = None
        self.update_score_ML = update_score_ML

        self.train_window_in_optim = train_window_in_optim

        self.univ = CONFIG["PARAMETRES PRINCICALES"]['univ']
        self.max_date = max_date

    def _resolve_mode_path(self, production_key, backtest_key):
        path = self.param_principal[production_key]
        if self.mode_lower == "backtest":
            path = self.param_principal.get(backtest_key, path)
        return path

    def _append_mode_suffix(self, path_prefix):
        suffix = f"_{self.mode_lower}"
        if path_prefix.lower().endswith(suffix):
            return path_prefix
        return f"{path_prefix}{suffix}"

    def _resolve_output_prefix(self):
        if self.output_file:
            output_prefix = os.path.splitext(self.output_file)[0]
            if self.output_path:
                output_prefix = os.path.join(self.output_path, output_prefix)
            return self._append_mode_suffix(output_prefix)
        return os.path.splitext(self.score_ml_path)[0]

        
    def run(self):  
        """  
        Execute ML prediction workflow based on selected mode and configured attributes.  
        
        Returns:  
            DataFrame: DataFrame containing prediction scores  
        """  
        if self.preprocessing:
            self.preprocess()
        else :
            if not os.path.exists(self.input_file_path):
                raise ValueError(f"The preprocessing dataframe is not found, using 'preprocessing=True' argument to create.")  

        # Load screen after preprocessing and change the date into the last date of that month.
        input_transformed = pd.read_parquet(self.input_file_path)  
        input_transformed = input_transformed.reset_index()
        input_transformed['Date'] = input_transformed['Date'].dt.to_period('M').dt.to_timestamp('M')
        input_transformed = input_transformed.set_index(['Company SEDOL', 'Date'])
        
        
        # Select appropriate workflow based on mode  
        if self.mode_lower == "production": 
            print("Debut PREDICTION (~40 sec)") 
        elif self.mode_lower == "backtest":  
            print("Debut REPRISE SCORE")

        # Create predictor instance  
        predictor = MLPredictor(self.params_strat, self.params_hyper_parameters, self.univ)  
        print(f"Period to predict is : {self.params_strat['period_to_predict']}")


        self.screen_label = input_transformed.copy(deep=True)

        # DROP Score ML to be sure
        self.screen_label.drop(columns=['Score ML'], inplace=True, errors='ignore')
        
        # 使用 mode 对应的输出前缀
        full_output_file = self.output_prefix
        if self.update_score_ML:
            print(f"Output will be saved at {self.score_ml_path}")

        #### RECO 20 ##########
        self.prediction_results, self.shap_values = predictor.create_Score_ML(  
                self.screen_label,
                self.mode,  
                update_score_ML=self.update_score_ML,  
                output_file=full_output_file,  
                allow_multiprocessing=self.allow_multiprocessing  
            )  
        return self.prediction_results  

    def preprocess(self):
        # Load input data  
        print("Start of Preprocressing : (5 min)")
        self.preprocessor = MLPreprocessor(
                                            self.param_principal,        # 对应之前代码中的 self.config_dict['principal'] 部分
                                            self.param_preprocessing,    # 对应 self.config_dict['preprocessing']
                                            self.params_strat,           # 对应 self.config_dict['strategy']
                                            mode=self.mode,
                                            max_date=self.max_date
                                        )
        self.preprocessor.preprocess()
        print("End of Preprocressing.")
        print(f"The preprocessing file is saved at : {self.df_features_path}")

    ############# RECO 40 #################
    def backup_screen_agg(self, backup_dir = r"C:\GoogleDrive\TP\00_screen\backups\ml_score_update"):
        # Create backup with date in filename  
        today = datetime.now().strftime("%Y%m%d_%H%M%S_%f")  
        backup_filename = f"screen_aggregate_{today}_before_ml.parquet"  
        backup_path = os.path.join(backup_dir, backup_filename)  
        
        # Ensure backup directory exists  
        os.makedirs(backup_dir, exist_ok=True)  
        
        # Create backup  
        shutil.copy2(self.screen_path, backup_path)  
        print(f"Backup created at: {backup_path}") 


    def update_screen_aggregate(self):  
        """  
        使用当前 mode 对应的 Score ML 文件更新 screen aggregate。  
        """  
        if not os.path.exists(self.score_ml_path):
            print(f"Score ML file not found at: {self.score_ml_path}")
            return False  
            
        try:  
            self.backup_screen_agg()
            screen_agg = pd.read_parquet(self.screen_path).reset_index()
            score_output = pd.read_parquet(self.score_ml_path).reset_index()

            screen_agg['Date'] = pd.to_datetime(screen_agg['Date'])
            score_output['Date'] = pd.to_datetime(score_output['Date'])

            if 'Score ML' not in screen_agg.columns:
                screen_agg['Score ML'] = float('nan')

            screen_agg = screen_agg.sort_values(['ISIN', 'Date']).drop_duplicates(
                subset=['ISIN', 'Date'], keep='last'
            )
            score_output = score_output.sort_values(['ISIN', 'Date']).drop_duplicates(
                subset=['ISIN', 'Date'], keep='last'
            )

            score_histo = screen_agg.sort_values(['Date', 'ISIN'])[['ISIN', 'Date']]
            score_prod = score_output.sort_values(['Date', 'ISIN'])[['ISIN', 'Date', 'Score ML']]
            merged = pd.merge_asof(
                score_histo[['ISIN', 'Date']],
                score_prod,
                on='Date',
                by='ISIN',
                direction='nearest',
                tolerance=pd.Timedelta('7D')
            )
            merged = merged.dropna(subset=['Score ML'])
            merged = merged.sort_values(['ISIN', 'Date']).drop_duplicates(
                subset=['ISIN', 'Date'], keep='last'
            )

            screen_agg_idx = screen_agg.set_index(['ISIN', 'Date'])
            merged_idx = merged.set_index(['ISIN', 'Date'])
            screen_agg_idx.update(merged_idx[['Score ML']])

            updated_rows = merged.shape[0]
            print(f"Updated 'Score ML' for {updated_rows} rows from {self.score_ml_path}.")

            screen_agg = screen_agg_idx.reset_index()
            screen_agg.set_index('ISIN', inplace=True)
            screen_agg['Score ML'] = screen_agg.groupby(
                ['Date', ' Benchmark ICB Supersector ', 'Exchange Country Region']
            )['Score ML'].rank(pct=True, ascending=True) * 10
            screen_agg.to_parquet(self.screen_path)  
            print(f"Screen aggregate file updated successfully at: {self.screen_path}")  
            
            return True  
            
        except Exception as e:  
            print(f"Error updating screen aggregate file: {e}")  
            return False


