# MLPredictorPipeline.py  

import pandas as pd  
import os  
import shutil  
from datetime import datetime  
from dateutil import relativedelta
from pathlib import Path


def _read_dataframe(path):
    path = Path(path)
    if path.suffix.lower() != ".parquet":
        raise ValueError(f"Only parquet files are supported: {path}")
    return pd.read_parquet(path)


def _write_dataframe(df, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() != ".parquet":
        raise ValueError(f"Only parquet files are supported: {path}")
    df.to_parquet(path)
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
                train_window_in_optim=None):  
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
        self.param_principal = CONFIG["PARAMETRES PRINCICALES"] 
        self.param_preprocessing = CONFIG["PARAMETRES PREPROCESSING"] 
        self.params_strat = CONFIG["PARAMETRES MODELE"]   
        self.params_hyper_parameters = CONFIG["HYPERPARAMETRES"]

        self.mode = mode 
        self.preprocessing = preprocessing 
        
        # Pipeline configuration  
        self.input_file_path = input_file_path or CONFIG["PARAMETRES PRINCICALES"]['df_features_path']
        self.output_path = output_path  
        self.output_file = output_file  
        self.allow_multiprocessing = allow_multiprocessing  
        self.screen_path = screen_path or CONFIG["PARAMETRES PRINCICALES"]['screen_path'] 
        self.prediction_results = None
        self.shap_values = None 
        self.result_model = None
        self.update_score_ML = update_score_ML

        self.train_window_in_optim = train_window_in_optim

        self.univ = CONFIG["PARAMETRES PRINCICALES"]['univ']
        

        
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
        input_transformed = _read_dataframe(self.input_file_path)  
        input_transformed = input_transformed.reset_index()
        input_transformed['Date'] = input_transformed['Date'].dt.to_period('M').dt.to_timestamp('M')
        input_transformed = input_transformed.set_index(['Company SEDOL', 'Date'])
        
        
        # Select appropriate workflow based on mode  
        if self.mode.lower() == "production": 
            print("Debut PREDICTION (~40 sec)") 
        elif self.mode.lower() == "backtest":  
            print("Debut REPRISE SCORE")
        else:  
            raise ValueError(f"Invalid mode: {self.mode}. Must be 'production' or 'backtest'.") 

        # Create predictor instance  
        predictor = MLPredictor(self.params_strat, self.params_hyper_parameters, self.univ)  
        print(f"Period to predict is : {self.params_strat['period_to_predict']}")


        self.screen_label = input_transformed.copy(deep=True)

        # DROP Score ML to be sure
        self.screen_label.drop(columns=['Score ML'],inplace=True)
        
        # Determine the full output file path 
        full_output_file = os.path.join(self.output_path, self.output_file) if self.output_path else self.output_file 
        if self.update_score_ML:
            if not self.output_file:
                print("you have to set output_file if 'update_score_ML' is enable")
                return
            print(f"Output will be saved at {full_output_file}")

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
        preprocessor = MLPreprocessor(self.param_principal, self.param_preprocessing, self.params_strat)
        preprocessor.preprocess()
        print("End of Preprocressing.")
        print(f"The preprocessing file is saved at : {self.param_principal['df_features_path']}")

    ############# RECO 40 #################
    def backup_screen_agg(self, backup_dir = r"C:\GoogleDrive\TP\screen\bk"):
        # Create backup with date in filename  
        today = datetime.now().strftime("%Y%m%d")  
        backup_filename = f"screen_aggregate_{today}_before_ml{Path(self.screen_path).suffix}"  
        backup_path = os.path.join(backup_dir, backup_filename)  
        
        # Ensure backup directory exists  
        os.makedirs(backup_dir, exist_ok=True)  
        
        # Create backup  
        shutil.copy2(self.screen_path, backup_path)  
        print(f"Backup created at: {backup_path}") 


    def update_screen_aggregate(self):  
        """  
        Update the screen aggregate file with the latest ML scores.  
        
        This method:  
        1. Creates a backup of the original screen aggregate file  
        2. Updates the 'Score ML' column with the latest predictions  
        3. Saves the updated file back to the original location  
        
        Args:  
            update_score_ml (bool): Whether to update the 'Score ML' column  
            
        Returns:  
            bool: True if update was successful, False otherwise  
        """  
        if self.prediction_results is None:  
            print("No prediction results available. Run the pipeline first.")  
            return False  
            
        try:  
            self.backup_screen_agg()
            # Load screen aggregate file  
            screen_agg = _read_dataframe(self.screen_path)  
            screen_agg.reset_index(inplace=True)  # index will become 0 1 2 3 4 5 6...
            
            # Prepare prediction results with matching index  
            output_last_month = self.prediction_results.copy()  
            output_last_month.reset_index(inplace=True)  

            # Step 1: Prepare historical and prediction data for merging
            # We sort both datasets by 'Date' and 'ISIN' to ensure proper alignment for merge_asof
            score_histo = screen_agg.sort_values(['Date', 'ISIN'])[['ISIN', 'Date']]
            score_prod = output_last_month.sort_values(['Date', 'ISIN'])[['ISIN', 'Date', 'Score ML']]

            # 📊 Example:
            # score_histo:
            # ┌───────┬────────────┐
            # │ ISIN  │    Date     │
            # ├───────┼────────────┤
            # │ FR001 │ 2025-08-29  │
            # │ FR002 │ 2025-08-29  │
            # └───────┴────────────┘

            # score_prod:
            # ┌───────┬────────────┬────────┐
            # │ ISIN  │    Date     │ Score ML │
            # ├───────┼────────────┼────────┤
            # │ FR001 │ 2025-08-31  │  0.87  │
            # │ FR002 │ 2025-08-31  │  0.65  │
            # └───────┴────────────┴────────┘

            # Step 2: Perform merge_asof to align scores by nearest date (within 7 days)
            # This allows us to match prediction scores to historical entries even if dates differ slightly
            merged = pd.merge_asof(
                score_histo[['ISIN', 'Date']],
                score_prod,
                on='Date', by='ISIN',
                direction='nearest',
                tolerance=pd.Timedelta('7D')
            )

            merged = merged.dropna(subset='Score ML')

            # 📊 merged:
            # ┌───────┬────────────┬────────┐
            # │ ISIN  │    Date     │ Score ML │
            # ├───────┼────────────┼────────┤
            # │ FR001 │ 2025-08-29  │  0.87  │ ← matched within 2 days
            # │ FR002 │ 2025-08-29  │  0.65  │ ← matched within 2 days
            # └───────┴────────────┴────────┘


            # Step 3: Update 'Score ML' in screen_agg only where 'Score ML' in merged is available
            # Update methode:
            # Replaces existing values with values from another DataFrame where the index and columns match.
            # Does not preserve original values — it overwrites them.
            # Requires aligned index and columns.
            screen_agg.set_index(['ISIN', 'Date'], inplace=True)
            merged.set_index(['ISIN', 'Date'], inplace=True)

            screen_agg['Score ML'].update(merged['Score ML'])
            
            # Show how many rows are updated
            updated_rows = merged.shape[0]
            print(f"Updated 'Score ML' for {updated_rows} rows.")


            # Reset index for scrren_agg
            screen_agg.reset_index(inplace=True)
            screen_agg.set_index('ISIN', inplace=True)

            # ✅ Final screen_agg:
            # ┌───────┬────────────┬───────────┐
            # │ ISIN  │    Date     │ Score ML  │
            # ├───────┼────────────┼───────────┤
            # │ FR001 │ 2025-08-29  │   0.87    │
            # │ FR002 │ 2025-08-29  │   0.65    │
            # └───────┴────────────┴───────────┘

            # Save updated file  
            _write_dataframe(screen_agg, self.screen_path)  
            print(f"Screen aggregate file updated successfully at: {self.screen_path}")  
            
            return True  
            
        except Exception as e:  
            print(f"Error updating screen aggregate file: {e}")  
            return False




