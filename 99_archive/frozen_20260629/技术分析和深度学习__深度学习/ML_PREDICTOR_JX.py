# ML_PREDICTOR.py  

import copy  
from math import *  
from operator import itemgetter  
from dateutil import relativedelta  
import os  
import sys
from multiprocessing import Pool  



# Data processing libraries  
import pandas as pd  
import numpy as np  

# Deep learning models  
from Codes.MLP_prod import MLP
# from posthog import screen
import torch.nn as nn

# Evaluation metrics  
from sklearn.metrics import r2_score, mean_squared_error
from scipy.stats import spearmanr

# Resampling techniques  
from imblearn.over_sampling import RandomOverSampler, SMOTE, ADASYN  
from imblearn.under_sampling import NearMiss  

# Model explainability  
import shap  


class MLPredictor:  
    """  
    Machine Learning Prediction Framework for financial data prediction and scoring.  
    
    This class integrates all functionality for data preparation, model training, and prediction.  
    """  
    
    def __init__(self, params, params_hyper_parameters=None, univ="STOXX EUROPE 600"):  
        """  
        Initialize the predictor.  
        
        Args:  
            params (dict): Strategy parameters dictionary  
            params_hyper_parameters (dict, optional): Model hyperparameters  
        """  
        self.params = params  
        self.params_hyper_parameters = params_hyper_parameters
        self.univ = univ
    
    def predict(self, df_scores, model_name, model_params, period_to_predict,   
               include_columns, end_test_train_date, end_test_date, monotone_constraints,   
               sampling='base', obs_weight='balanced', type_label='regression'):  
        """  
        Train model and generate predictions based on input data and parameters.  
        
        Args:  
            df_scores (DataFrame): DataFrame containing scores  
            model_name (str): Name of model to use  
            model_params (dict): Dictionary of model parameters  
            period_to_predict (list): List of prediction periods  
            include_columns (list): Feature columns to include in model  
            end_test_train_date: Date for splitting training and prediction data  
            monotone_constraints (dict): Dictionary of monotonic constraints  
            sampling (str, default='base'): Resampling method  
            obs_weight (str, default='balanced'): Observation weighting method  
            type_label (str, default='regression'): Label type  
            
        Returns:  
            tuple: Prediction results and model information  
        """  
        
        y_pred = []  # Will contain predictions of returns in different months  
        predict_set = df_scores.loc[df_scores.index.get_level_values('Date') >= end_test_train_date + relativedelta.relativedelta(months=period_to_predict)]
        X_predict = predict_set[include_columns]
        X_result=predict_set.copy(deep=True)

        if end_test_date != df_scores.index.get_level_values('Date').min():
            training_set = df_scores.loc[(df_scores.index.get_level_values('Date') < end_test_train_date) & 
                                         (df_scores.index.get_level_values('Date') >= end_test_date + relativedelta.relativedelta(months=period_to_predict))]
            testing_set = df_scores.loc[(df_scores.index.get_level_values('Date') < end_test_date)]  
        
        if end_test_date == df_scores.index.get_level_values('Date').min():   # If end_test_date is the same as the first date of df, which means we dont test (backtest mode)
            training_set = df_scores.loc[(df_scores.index.get_level_values('Date') < end_test_train_date)]  
            testing_set = None
    
        # Delete rows with no Forward return / IR  
        training_set_na_null = training_set.copy(deep=True).dropna(subset=[f"{period_to_predict}M label"])   
        X_train = training_set_na_null.drop(f"{period_to_predict}M label", axis=1)  # Remove column to predict from explanatory X  
        X_train = X_train[include_columns]    # include_columns == features 
        y_train = training_set_na_null[f"{period_to_predict}M label"]  

        if testing_set is not None:
            test_set_na_null = testing_set.copy(deep=True).dropna(subset=[f"{period_to_predict}M label"])  
            X_test_screen = test_set_na_null.copy(deep=True) 

            X_test = test_set_na_null.drop(f"{period_to_predict}M label", axis=1)  # Remove column to predict from explanatory X  
            X_test = X_test[include_columns]    # include_columns == features 
            y_test = test_set_na_null[f"{period_to_predict}M label"]

        parameters={'activation_function_1': nn.ELU(alpha=0.1),
                    'activation_function_2': nn.ELU(alpha=0.1),
                    'activation_function_3': nn.LeakyReLU(negative_slope=0.01),
                    'hidden_units_1': 128,
                    'hidden_units_2': 128,
                    'hidden_units_3': 128}   
        
        
        model = MLP(X_train.values.shape[1], 1, parameters)
        model.fit(X_train, y_train,l1_lambda=0,l2_lambda=0.001)  
    
        new_pred = model.predict(X_predict)  
        X_result[f"{period_to_predict}M y_pred"] = new_pred
        y_pred.append(new_pred)  

        test_metrics = 0
        if testing_set is not None:
            test_metrics = {}
            y_test_predict = model.predict(X_test)
            X_test_screen[f'{period_to_predict}M y_pred'] = y_test_predict
         
        return y_pred, X_result, 0, test_metrics, [model, X_predict]  
    
    # RECO 20 #####################################
    def create_Score_ML(  
        self,  
        screen_label,
        mode,  
        update_score_ML=False,  
        output_file="SCORE_ML_2010_to_Today",  
        allow_multiprocessing=True  
    ):  
        """  
        Performs rolling window training and prediction using specified parameters.  
        
        Args:  
            screen_label (DataFrame): DataFrame containing labeled data  
            update_score_ML (bool): Boolean indicating whether to save results  
            output_file (str): Output file name  
            allow_multiprocessing (bool): Boolean indicating whether to use multiprocessing  
        
        Returns:  
            DataFrame: DataFrame containing predictions and scores  
        """  
        from dateutil import relativedelta  
        
        # Extract parameters from input  
        period_to_predict = self.params['period_to_predict']  # Periods to predict (e.g., 3M, 12M)  
        features = self.params['features']  # Features for training the model  
        model_name = self.params['model_name']  # ML model name (e.g., XGBoost or XGBoostOptimizer)  
        sampling_method = self.params['sampling_method']  # Sampling method for training  
        training_window = self.params['training_window']  # Training window (in years)  
        prediction_window = self.params['prediction_window']  # Prediction window (in months)  
        testing_window = self.params['testing_window']

        obs_weight = self.params['obs_weight']  # Observation weighting method  
        type_label = self.params['type_label']  # Task type (e.g., classification or regression)  
        feature_constraints = self.params["feature_constraints"]  # Feature constraints  

        list_period_to_predict = self.params['period_to_predict']

        screen_pred = screen_label.copy(deep=True)
        screen_pred = screen_pred.reset_index()
        screen_pred = screen_pred.set_index(['ISIN', 'Date'])

        for period_to_predict in list_period_to_predict:
            if mode.lower() == "backtest":
                # backtest mode will use all historical data
                # Visualization for a SINGLE iteration/fold in a conceptual backtest (actual backtest would roll these windows):
                #
                # |---------------------------------------------------------------------------------------------------|
                # screen_label Data (from first_date to last_date)
                #
                # Conceptual First Fold:
                #
                #  [ Training Data (initial) ]                                    [ Prediction Target Period ]
                # |---------------------------|------ period_to_predict -----|--------------------------------|-------------------------------> Time
                # ^ first_date                ^ end_test_and_training_date                                    ^ end_prediction_date
                # (2010-01-01)                  (2013-01-01)                                                    (2013-08-01)
                #
                # Backtesting window, perf of predictoin will be analysized with the monthly statistical of top and worst performers
                last_date = screen_label.index.get_level_values('Date').max()  # Last date in dataset  
                first_date = screen_label.index.get_level_values('Date').min()  # First date in dataset  
                end_test_and_training_date = first_date + relativedelta.relativedelta(years=training_window) 
                end_test_date = first_date
                end_prediction_date = end_test_and_training_date + relativedelta.relativedelta(months= prediction_window + period_to_predict) 
                
            if mode.lower() == 'production':
                # production mode will use only one window traning to predict one month (the most recent month)
                # Visualization for "production" mode:
                #
                # Data Slice Used (from `first_date` up to `last_date`)
                # |---------------------------------------------------------------------------------------------------|
                #
                #  [   Testing Data   ]                              [  Training Data  ]                                      [ Prediction Period (1 month) ]
                # |---------------------|-- period_to_predict --|----------------------------|-- period_to_predict --|------------------------------|----------------------> Time
                # ^ first_date          ^ end_test_date                                      ^ end_test_and_training_date                           ^ end_prediction_date
                # (2018-12-31)          (2019-12-31)                                          (2023-06-30)                                           (2024-01-30)
                #
                
                last_date = screen_label.index.get_level_values('Date').max() # Last date in dataset  
                first_date = last_date - relativedelta.relativedelta(years = training_window, 
                                                                    months = period_to_predict*2 + testing_window)# The start date of the dataset will be established by offsetting today's date into the past by an interval equivalent to the sum of the training window, the prediction window, and the desired prediction period.
                end_test_and_training_date = first_date + relativedelta.relativedelta(years=training_window,
                                                                                    months=period_to_predict + testing_window) 
                end_test_date = end_test_and_training_date - relativedelta.relativedelta(years=training_window,
                                                                                        months=period_to_predict)
                end_prediction_date = end_test_and_training_date + relativedelta.relativedelta(months= 1 + period_to_predict)   
            
            # Initialize parameters for rolling windows  
            list_params_rolling = []  
            screen_rolling = screen_label[  
                (screen_label.index.get_level_values('Date') >= first_date) *  
                (screen_label.index.get_level_values('Date') < end_prediction_date)  
            ]  
            
            # Append first rolling window parameters  
            list_params_rolling = [[  
                screen_rolling, model_name, self.params_hyper_parameters, period_to_predict,  
                features, end_test_and_training_date, end_test_date, feature_constraints, sampling_method, obs_weight, type_label  
            ]]  
            
            # Iterate through dataset to create rolling windows - For backtesting mode
            while end_test_and_training_date + relativedelta.relativedelta(months=prediction_window + period_to_predict) <= last_date:  
                # Update date ranges for next rolling window  
                first_date = first_date + relativedelta.relativedelta(months=prediction_window)  
                end_test_and_training_date = end_test_and_training_date + relativedelta.relativedelta(months=prediction_window)  
                end_test_date = end_test_and_training_date - relativedelta.relativedelta(years=training_window)

                # AJOUTER MAX VALUE OF LABEL VARIATION TO BE SURE THERE WILL NOT BE OVERLAP BETWEEN TRAINING AND PREDICTION
                end_prediction_date = end_prediction_date + relativedelta.relativedelta(months=prediction_window) 
                
                # Filter data for current rolling window  
                screen_rolling = screen_label[  
                    (screen_label.index.get_level_values('Date') >= first_date) *  
                    (screen_label.index.get_level_values('Date') < end_prediction_date)  
                ]  
                
                # Append parameters for current rolling window  
                list_params_rolling.append([  
                    screen_rolling, model_name, self.params_hyper_parameters, period_to_predict,  
                    features, end_test_and_training_date, end_test_date, feature_constraints, sampling_method, obs_weight, type_label  
                ])  
            
            print(f"Number of batches to predict is : {len(list_params_rolling)}")
            if (len(list_params_rolling) == 1) and mode == "production":
                last_date = screen_label.index.get_level_values('Date').max() # Last date in dataset  
                print(f"We are creating Score ML for {last_date}, using data starting from {first_date} (included) until {end_test_and_training_date} (not included). " )


            if mode == "backtest":
                # Perform predictions using multiprocessing or sequentially  
                if allow_multiprocessing:  
                    # Use multiprocessing for faster execution  
                    print("Using multi processing for backtesting...")
                    with Pool(os.cpu_count()-1) as p:  # Reserve 1 CPU core for system processes  
                        results_period = p.starmap(self.predict, [params for params in list_params_rolling])  
                else:  
                    from tqdm import tqdm
                    # Sequential execution (slower, but useful for debugging)  
                    print("No multi processing, sequential method is used for generating backtest...")
                    results_period = []  
                    for params in tqdm(list_params_rolling, desc="Generating Backtest", unit="parameter"):  
                        predict_result = self.predict(*params)  
                        results_period.append(predict_result) 

            if mode == "production":
                    results_period = []  
                    for params in list_params_rolling:  
                        predict_result = self.predict(*params)  
                        results_period.append(predict_result) 
            
            # Here, we merge all the prediction results into one dataframe (14 years)
            result_prediction = []
            shap_values = []
            test_metrics = []
            for item in results_period:
                # Assuming each item is a tuple and the first element is a DataFrame
                result_prediction.append(item[1].reset_index(drop=False))
                # shap_values.append(item[2].reset_index(drop=False))
                # test_metrics.append(item[3])

            # Concatenate all DataFrames into one
            result_df = pd.concat(result_prediction, ignore_index=True)
            result_df = result_df.sort_values('Date')

            # shap_values_df = pd.concat(shap_values, ignore_index=True)

            result_df = result_df.set_index(['ISIN', 'Date'])
            
            screen_pred.loc[: ,f"{period_to_predict}M y_pred"] = result_df[f"{period_to_predict}M y_pred"]
        
        #################### Combine different prediction ####################
        print(self.params['ranking_predict_to_score'])
        if self.params['ranking_predict_to_score']=='rank_and_mean':
            prediction_columns = []  
            for period in list_period_to_predict:
                col = f"{period}M y_pred"
                col_rank = f"{period}M y_pred_rank"
                screen_pred[col_rank] = screen_pred.groupby('Date')[col].rank(ascending=True) 
                
                prediction_columns.append(col_rank) 
                
            screen_pred['average_rank'] = screen_pred[prediction_columns].mean(axis=1)  

            # Normalize and rank final ML score  
            screen_pred['Score ML'] = screen_pred.groupby('Date')['average_rank'].rank(  
                pct=True,  
                ascending=True  
                ) * 10
            
        elif self.params['ranking_predict_to_score']=='mean_and_rank':
            prediction_columns = []  
            for period in list_period_to_predict:
                col = f"{period}M y_pred"
                prediction_columns.append(col) 
            screen_pred['average_prediction'] = screen_pred[prediction_columns].mean(axis=1)  
            # Normalize and rank final ML score  
            screen_pred['Score ML'] = screen_pred.groupby('Date')['average_prediction'].rank(  
                pct=True,  
                ascending=True  
                ) * 10
            
        elif self.params['ranking_predict_to_score']=='homogenous_mean_and_rank':
            pred_columns = []
            for period in list_period_to_predict:
                col = f"{period}M y_pred"
                col_scaled = f"{period}M y_pred_scaled"
                screen_pred[col_scaled] = screen_pred[col]/period # montly weighted prediction
                pred_columns.append(col_scaled) 
            screen_pred = screen_pred.dropna(subset=pred_columns)
            screen_pred['average_prediction'] = screen_pred[pred_columns].mean(axis=1)  
            # Normalize and rank final ML score  
            screen_pred['Score ML'] = screen_pred.groupby('Date')['average_prediction'].rank(  
                pct=True,  
                ascending=True  
                ) * 10
            
        
        # Fusionner screen_agg_msci_us et screen_agg sur la colonne 'Company SEDOL' et la date la plus proche
        merged = pd.merge_asof(
            screen_pred.sort_values("Date"),
            # screen_label.reset_index()[["ISIN","Date", "Company SEDOL", "Weight in MSCI ACWI","Weight in SP500","Weight in STOXX EUROPE 600","Weight in MSCI WORLD",'Benchmark Market Value Millions in EUR ',"Sector ICB19","Sector ICB11",'ESG_ANALYST_SCORE']].sort_values("Date"),
            screen_label.reset_index()[["ISIN","Date"]].sort_values("Date"),
            on="Date",
            # by="Company SEDOL",
            by="ISIN",
            direction="nearest",
            suffixes=('_previous', ''),
            )
        merged.to_pickle('merged.pkl')
        screen_pred.to_pickle('result_df.pkl')
        screen_label.to_pickle('screen_label.pkl')
        
        merged.set_index("ISIN", inplace = True)
        merged=merged.rename(columns={"Sector ICB19":" Benchmark ICB Supersector ","Sector ICB11":" Benchmark ICB Industry "})
        
        # Save results to Excel and pickle files if requested  
        if update_score_ML:  
            # save_path_excel = f"{output_file}.xlsx"  
            save_path_pickle = f"{output_file}.pkl"  
            # predict_dataset.to_excel(save_path_excel)  # Save as Excel file  
            merged.to_pickle(save_path_pickle)  # Save as pickle file  
            # print(f"Backtesting completed. Results saved to {save_path_excel} and {save_path_pickle}")  
            print(f"Backtesting completed. Results saved to {save_path_pickle}")  
            
        return merged, "test1", "test2"


