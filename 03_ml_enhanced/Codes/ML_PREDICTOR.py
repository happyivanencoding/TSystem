# ML_PREDICTOR.py  

import copy  
from math import *  
from operator import itemgetter  
from dateutil import relativedelta  
import os  
from multiprocessing import Pool  

# Data processing libraries  
import pandas as pd  
import numpy as np

# Machine learning models  
# from posthog import screen
import xgboost as xgb  

# Evaluation metrics  
from sklearn.metrics import r2_score, mean_squared_error
from scipy.stats import spearmanr

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



    def split_train_test_set(self, df_scores, end_train_date, period_to_predict, include_columns) :

        #Split prediction/train set
        training_set = df_scores.loc[(df_scores.index.get_level_values('Date') < end_train_date)]
        predict_set = df_scores.loc[df_scores.index.get_level_values('Date') >= end_train_date + relativedelta.relativedelta(months=period_to_predict)] # end_train_date = Date de fin des X en train, period_to_predict garanti de ne pas avoir de look ahead (avec le Y train qui est en date = X train + period_to_predict)
        
        # Split INPUT/OUTPUT (Training Set)
        training_set_na_null = training_set.copy(deep=True).dropna(subset=[f"{period_to_predict}M label"])   # Supprimer toutes les lignes sans target 
        X_train = training_set_na_null.drop(f"{period_to_predict}M label", axis=1)  # Supprime la colonne target 
        X_train = X_train[include_columns]    # include_columns == features 
        y_train = training_set_na_null[f"{period_to_predict}M label"] 

        #Split input (prediction set)
        X_predict = predict_set[include_columns]

        return X_train, y_train, X_predict, predict_set
    


    
    def predict(self, X_train, y_train, X_predict, predict_set, model_params, period_to_predict,   
            include_columns, monotone_constraints, type_label='regression'):  
        """  
        Train model and generate predictions based on input data and parameters.  
        
        Args:  
            df_scores (DataFrame): DataFrame containing scores  
            model_params (dict): Dictionary of model parameters  
            period_to_predict (list): List of prediction periods  
            include_columns (list): Feature columns to include in model  
            end_train_date: Date for splitting training and prediction data  
            monotone_constraints (dict): Dictionary of monotonic constraints  
            type_label (str, default='regression'): Label type  
            
        Returns:  
            tuple: Prediction results and model information  
        """  
        
        y_pred = []  # Will contain predictions of returns in different months  
        result_screen = predict_set.copy(deep=True)


        ############ MODEL ############
        model = xgb.XGBRegressor(  
        subsample=model_params['subsample'],  
        reg_lambda=model_params['reg_lambda'],  
        reg_alpha=model_params['reg_alpha'],  
        random_state=42,  
        n_estimators=model_params['n_estimators'],  
        min_child_weight=model_params['min_child_weight'],  
        max_depth=model_params['max_depth'],  
        learning_rate=model_params['learning_rate'],  
        gamma=model_params['gamma'],  
        colsample_bytree=model_params['colsample_bytree'],  
        monotone_constraints=monotone_constraints
        )  
    
        model.fit(X_train, y_train)  


        ######################## Shap ########################
        shap_explainer = shap.TreeExplainer(model)  
        shap_values = shap_explainer.shap_values(X_predict)  
        shap_val_df = pd.DataFrame(
                                    data=shap_values,               # keep all rows
                                    columns=include_columns,        # feature names
                                    index=X_predict.index          # match the original rows
                                    )
        shap_val_df['period'] = f"{period_to_predict}M"  # Add period in shap result
        shap_val_df.loc[:, 'ISIN'] = result_screen.loc[:, 'ISIN']   # Add ISIN in shap result


        ######################## Predict ########################
        new_pred = model.predict(X_predict)  
        # print("========================================================================")
        # print(
        #         f"Time range of X_train is from "
        #         f"{X_train.index.get_level_values('Date').min()} to "
        #         f"{X_train.index.get_level_values('Date').max()}"
        #     )
        # print(f"Period to predict is {period_to_predict}M")
        # print(
        #         f"Time range of X_predict is from "
        #         f"{X_predict.index.get_level_values('Date').min()} to "
        #         f"{X_predict.index.get_level_values('Date').max()}"
        #     )
        # print("========================================================================")

        result_screen[f"{period_to_predict}M y_pred"] = new_pred
        y_pred.append(new_pred)  

        model_params = model.get_params()  

        model_params = list(itemgetter('subsample', 'reg_lambda', 'reg_alpha', 'random_state', 'n_estimators', 'min_child_weight', 'max_depth', 'learning_rate', 'gamma', 'colsample_bytree', 'monotone_constraints')(model_params))  
        dict_params = dict(zip(['subsample', 'reg_lambda', 'reg_alpha', 'random_state', 'n_estimators', 'min_child_weight', 'max_depth', 'learning_rate', 'gamma', 'colsample_bytree', 'monotone_constraints'], model_params))  

        return y_pred, result_screen, shap_val_df, dict_params, [model, X_predict]  
    

    
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
        features = self.params['features']  # Features for training the model  
        training_window = self.params['training_window']  # Training window (in years)  
        prediction_window = self.params['prediction_window']  # Prediction window (in months)  

        type_label = self.params['type_label']  # Task type (e.g., classification or regression)  
        feature_constraints = self.params["feature_constraints"]  # Feature constraints  

        list_period_to_predict = self.params['period_to_predict']
        print("PRED_2")
        screen_pred = screen_label.copy(deep=True)
        screen_pred = screen_pred.reset_index()
        screen_pred = screen_pred.set_index(['ISIN', 'Date'])
        
        # shap_total = pd.DataFrame()
        shap_total = pd.DataFrame(index=screen_pred.index)


        #### RECO 7 ####
        for period_to_predict in list_period_to_predict:
            print(f"Period to predict is {period_to_predict}M")
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
                # ^ first_date                ^ end_training_date                                             ^ end_prediction_date
                # (2010-01-01)                  (2013-01-01)                                                    (2013-08-01)
                #
                # Initialisation of the first Window (1sr training Date, end prediction date)
                last_date = screen_label.index.get_level_values('Date').max()  # Last date in dataset  
                first_date = screen_label.index.get_level_values('Date').min()  # First date in dataset  
                end_training_date = first_date + relativedelta.relativedelta(years=training_window) # End date for the first trainning window
                end_prediction_date = end_training_date + relativedelta.relativedelta(months= prediction_window + period_to_predict) 
                
            if mode.lower() == 'production':
                # production mode will use only one window traning to predict one month (the most recent month)
                # Visualization for "production" mode:
                #
                # Data Slice Used (from `first_date` up to `last_date`)
                # |---------------------------------------------------------------------------------------------------|
                #
                #  [  Training Data  ]                                      [ Prediction Period (1 month) ]
                # |----------------------------|-- period_to_predict --|------------------------------|----------------------> Time
                # ^ first_date                 ^ end_training_date                                    ^ end_prediction_date
                # (2018-12-31)                  (2023-06-30)                                           (2024-01-30)
                #
                
                last_date = screen_label.index.get_level_values('Date').max() # Last date in dataset  
                first_date = last_date - relativedelta.relativedelta(years = training_window, 
                                                                    months = period_to_predict) # The start date of the dataset will be established by offsetting today's date into the past by an interval equivalent to the sum of the training window, the prediction window, and the desired prediction period.
                end_training_date = first_date + relativedelta.relativedelta(years=training_window) 
                end_prediction_date = end_training_date + relativedelta.relativedelta(months= 1 + period_to_predict)   
            
            #LISTES DES PARAMETRES QUI VA RENTRER DANS LA FONCTION PREDICT POUR CHAQUE FENETRE
            list_params_rolling = []  

            #INITIALISATION 1ERE FENETRE 
            # Initialize parameters for rolling windows  
            screen_rolling = screen_label[  
                (screen_label.index.get_level_values('Date') >= first_date) *  
                (screen_label.index.get_level_values('Date') < end_prediction_date)  
            ]  
            X_train, y_train, X_predict, predict_set = self.split_train_test_set(screen_rolling, end_training_date, period_to_predict, features)
            list_params_rolling = [[  
                X_train, y_train, X_predict, predict_set, self.params_hyper_parameters, period_to_predict,  
                features, feature_constraints, type_label  
            ]]  



            # To construct 2nd and next batches : Iterate through dataset to create rolling windows - For backtesting mode
            while end_training_date + relativedelta.relativedelta(months=prediction_window + period_to_predict) <= last_date:  
                # Update date ranges for next rolling window  
                first_date = first_date + relativedelta.relativedelta(months=prediction_window)  
                end_training_date = end_training_date + relativedelta.relativedelta(months=prediction_window)  

                # AJOUTER MAX VALUE OF LABEL VARIATION TO BE SURE THERE WILL NOT BE OVERLAP BETWEEN TRAINING AND PREDICTION
                end_prediction_date = end_prediction_date + relativedelta.relativedelta(months=prediction_window) 
                
                # Filter data for current rolling window  
                screen_rolling = screen_label[  
                    (screen_label.index.get_level_values('Date') >= first_date) *  
                    (screen_label.index.get_level_values('Date') < end_prediction_date)  
                ]  

                
                X_train, y_train, X_predict, predict_set = self.split_train_test_set(screen_rolling, end_training_date, period_to_predict, features)

                # Append parameters for current rolling window  
                list_params_rolling.append([  
                    X_train, y_train, X_predict, predict_set, self.params_hyper_parameters, period_to_predict,  
                    features, feature_constraints, type_label  
                ])  
            
            ####################### Prediction #######################
            print(f"Number of batches to predict is : {len(list_params_rolling)}")
            progress_desc = f"Backtest {period_to_predict}M"
            progress_kwargs = {
                "total": len(list_params_rolling),
                "desc": progress_desc,
                "unit": "batch",
                "dynamic_ncols": True,
                "bar_format": "{desc}: {n_fmt}/{total_fmt} |{bar}| [{elapsed}<{remaining}, {rate_fmt}]"
            }
            if (len(list_params_rolling) == 1) and mode == "production":
                last_date = screen_label.index.get_level_values('Date').max() # Last date in dataset  
                print("================================================================================================================================================")
                print(f"We are creating Score ML for {last_date}, using data starting from {first_date} (included) until {end_training_date} (not included). " )


            if mode == "backtest":
                # Perform predictions using multiprocessing or sequentially  
                if allow_multiprocessing:  
                    from tqdm.auto import tqdm
                    # Use multiprocessing for faster execution  
                    print("Using multi processing for backtesting...")
                    with Pool(os.cpu_count()-1) as p:  # Reserve 1 CPU core for system processes  
                        with tqdm(**progress_kwargs) as pbar:
                            # 在主进程更新进度条，保留多进程执行
                            def _update_progress(_):
                                pbar.update(1)

                            async_results = [
                                p.apply_async(
                                    self.predict,
                                    args=tuple(params),
                                    callback=_update_progress,
                                    error_callback=_update_progress
                                )
                                for params in list_params_rolling
                            ]

                            # result_period has 1. result of prediction, 2. shap values
                            # results_period contains all window Dataframe output (X predict + Y predict)
                            results_period = [async_result.get() for async_result in async_results]
                else:  
                    from tqdm.auto import tqdm
                    # Sequential execution (slower, but useful for debugging)  
                    print("No multi processing, sequential method is used for generating backtest...")
                    results_period = []  
                    for params in tqdm(list_params_rolling, **progress_kwargs):  
                        predict_result = self.predict(*params)  
                        results_period.append(predict_result) 

            if mode == "production":
                    results_period = []  
                    for params in list_params_rolling:  
                        predict_result = self.predict(*params)  
                        results_period.append(predict_result) 
            
            
            
            ############# Transforme Prediction Result #############
            # Here, we merge all the prediction results into one dataframe (14 years)
            result_prediction = []
            for item in results_period:
                # For Each Date of the Backtest we Keep only Prediction set (X + Y Set) that is the 2nd element of the list
                result_prediction.append(item[1].reset_index(drop=False)) # the position of result of prediction is at the 2nd

            # Concatenate all prediction DataFrames into one
            result_df = pd.concat(result_prediction, ignore_index=True)
            result_df = result_df.sort_values('Date')
            result_df = result_df.set_index(['ISIN', 'Date'])
            # Update screen with prediction result
            screen_pred.loc[: ,f"{period_to_predict}M y_pred"] = result_df[f"{period_to_predict}M y_pred"]

            ############# Transforme Shap Result #############
            shap_values = []
            for item in results_period:
                shap_values.append(item[2].reset_index(drop=False)) # the position of result of prediction is at the 3rd

            # Concatenate all prediction DataFrames into one
            shap_values_df = pd.concat(shap_values, ignore_index=True)
            shap_values_df = shap_values_df.sort_values('Date')
            shap_values_df = shap_values_df.set_index(['ISIN', 'Date'])
            # Update screen with shap result
            cols_list = shap_values_df.columns
            for col in cols_list:
                shap_total.loc[:, col] = shap_values_df.loc[:, col] 

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
            
        screen_pred = screen_pred.reset_index()
        screen_pred.set_index("ISIN", inplace = True)
        screen_pred=screen_pred.rename(columns={"Sector ICB19":" Benchmark ICB Supersector ","Sector ICB11":" Benchmark ICB Industry "})


        #################### Clean Shap df result ####################
        shap_total = shap_total.dropna()
        shap_total = shap_total.reset_index()
        
        # Save results to Excel and parquet files if requested  
        if update_score_ML:  
            # save_path_parquet = f"{output_file}.parquet"  
            # screen_pred.to_parquet(save_path_parquet)  # Save as parquet file  
            # print(f"Backtesting completed. Results saved to {save_path_parquet}")  
            save_path_parquet = f"{output_file}.parquet"  
            save_path_parquet_shap = f"{output_file}_SHAP.parquet"  
            if mode.lower() == "backtest":
                screen_pred.to_parquet(save_path_parquet)  # Save as parquet file  
                print(f"Backtesting completed. Results saved to {save_path_parquet}")  

                shap_total.to_parquet(save_path_parquet_shap)  # Save as parquet file  
                print(f"Backtesting completed. Results saved to {save_path_parquet_shap}")  


            elif mode.lower() == "production":
                screen_pred_last = screen_pred[ (screen_pred["Weight in " + self.univ] > 0 ) &  (screen_pred["Date"] == last_date) ]
                screen_pred_last.to_parquet(save_path_parquet)  # Save as parquet file  
                print(f"Production completed. Results saved to {save_path_parquet}")             

                shap_total.to_parquet(save_path_parquet_shap)  # Save as parquet file  
                print(f"Production completed. Results saved to {save_path_parquet_shap}")      
        
        return screen_pred, shap_total # shap here is only the second period to predit's shap


