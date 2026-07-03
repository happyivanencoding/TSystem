# Suppress warnings
import warnings
warnings.filterwarnings('ignore')

# Standard Python libraries
import copy
from math import *
from operator import itemgetter
from dateutil import relativedelta

# Data manipulation and preprocessing
import pandas as pd
import numpy as np
from sklearn.preprocessing import LabelEncoder, PolynomialFeatures
from sklearn.impute import KNNImputer

# Machine learning models
from sklearn.linear_model import LogisticRegression, LinearRegression
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier
import xgboost as xgb
from xgboost import XGBClassifier  # Assuming xgboost is used for classification

# Model training and hyperparameter tuning
from sklearn.model_selection import RandomizedSearchCV
from sklearn.pipeline import make_pipeline

# Evaluation metrics
from sklearn.metrics import accuracy_score, f1_score

# Resampling techniques for imbalanced datasets
from imblearn.over_sampling import RandomOverSampler, SMOTE, ADASYN
from imblearn.under_sampling import NearMiss

# Utility for class weight computation
from sklearn.utils import class_weight

# SHAP for explainability
import shap

# Custom modules
from py_files.PARAMS_LOADING import get_items_params_without_nan


def make_predictions(data, params, split_date, params_hyper_parameters):
    """Generate predictions using the specified model."""
    return predict(
        data,
        params['model_name'],
        params_hyper_parameters,
        params['period_to_predict'],
        params['features'],
        split_date,
        params['feature_constraints'],
        params['sampling_method'],
        params['obs_weight'],
        params['type_label']
    )

def predict(df_scores, 
            model_name, 
            model_params, 
            period_to_predict, 
            include_columns, 
            split_data_date, 
            monotone_constraints, 
            sampling = 'base', 
            obs_weight = 'balanced', 
            type_label = 'regression'):

    # Split data into training and testing sets based on date
    # Rolling trainning and testing
    # if training_window_yr = 5, test_window_mth = 12, then model will use data of last 6 years, for the first 5 years as train set, for the last 12 months as test set
    training_set = df_scores.loc[df_scores.index.get_level_values('Date') < split_data_date]
    test_set = df_scores.loc[df_scores.index.get_level_values('Date') >= split_data_date]
    
    # training_set = training_set.dropna()
    y_pred=[] # This will contain predictions of returns in different months
    for period in period_to_predict: # for prod, period_to_predict : [3.0, 12.0]
        #Delete row with no Forward return / IR
        training_set_na_null = training_set.copy(deep=True).dropna(subset=[f"{period}M label"])

        if type_label == 'classification':
            le = LabelEncoder()
            training_set_na_null[f"{period}M label"] = le.fit_transform(training_set_na_null[f"{period}M label"])
            test_set[f"{period}M label"] = le.transform(test_set[f"{period}M label"])
 
        X_train = training_set_na_null.drop(f"{period}M label", axis=1) #On supprime la colonne a predire des X expliquatifs
        y_train = training_set_na_null[f"{period}M label"]
 
        if type_label == 'classification':
            if sampling == 'oversampling':
                oversample = RandomOverSampler(sampling_strategy='minority', random_state=42)
                for i in range(len(y_train.unique())-1):
                    X_train,y_train = oversample.fit_resample(X_train,y_train)
            elif sampling == 'undersampling':
                undersample = NearMiss(version=1)
                X_train,y_train = undersample.fit_resample(X_train,y_train)
            elif sampling == 'SMOTE':
                oversample = SMOTE(random_state=42)
                X_train,y_train = oversample.fit_resample(X_train,y_train)
            elif sampling == 'ADASYN':
                oversample = ADASYN(random_state=42)
                X_train,y_train = oversample.fit_resample(X_train,y_train)
 
        if type_label == 'classification':
            if obs_weight == 'contrib':
                classes_weights = np.array(np.abs(X_train[f'contrib {period}M']))
                classes_weights = classes_weights/classes_weights.sum()
            elif obs_weight == 'balanced':
                classes_weights = class_weight.compute_sample_weight(class_weight='balanced', y=y_train)
            else:
                classes_weights = np.ones(len(X_train))/len(X_train)

        X_train = X_train[include_columns]    #include_columns==features
        X_test = test_set[include_columns]
        y_test = test_set[f"{period}M label"]
   
        model = None  # Initiation of final model
 
        if model_name == 'XGBoostOptimizer':
            if type_label == 'classification':
                xgb_model = xgb.XGBClassifier()
            elif type_label == 'regression':
                xgb_model = xgb.XGBRegressor()
            for param in model_params:
                if type(model_params[param])!=list:
                    model_params[param] = [model_params[param]]
            model = RandomizedSearchCV(estimator=xgb_model, param_distributions=model_params, n_iter=1000, cv=5, scoring='neg_mean_squared_error', random_state=42, n_jobs=-1)
            #model.fit(X_train, y_train, sample_weight=classes_weights).best_params_
 
        elif model_name == 'XGBoost' or model_name == 'XGBoost1' or model_name == 'XGBoost2':
            if type_label=='classification':
                model = xgb.XGBClassifier(
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
                monotone_constraints=monotone_constraints,
                objective = model_params['objective']
                #class_weight={0:4, 1:4, 2:1}
            )
               
            elif type_label=='regression':
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
                    monotone_constraints=monotone_constraints,
                    #class_weight={0:4, 1:4, 2:1}
                    )
 
 
        elif model_name == 'Logistic Regression Optimizer':
            parameters = {
                'penalty': ['l2','none'],
                'C': [0.001, 0.01, 0.1, 1, 10, 100],
                'fit_intercept': [True, False],
                'max_iter': [50, 100, 200, 300, 500, 1000],
                'solver': ['newton-cg', 'lbfgs', 'sag', 'saga'],
                'random_state': [42],
                'class_weight': ['balanced']
            }
 
            lr_model = LogisticRegression()
            model = RandomizedSearchCV(estimator=lr_model, param_distributions=parameters, n_iter=50, cv=3, scoring='f1_weighted', random_state=42)
            print("Meilleurs hyperparamètres : ", model.fit(X_train, y_train).best_params_)
 
        elif model_name == 'Logistic Regression':
            model = LogisticRegression(
                solver='liblinear',
                random_state=42,
                penalty='l2',
                max_iter=500,
                fit_intercept=True,
                class_weight='balanced',
                C=0.01
            )
 
        elif model_name == 'Random Forest Optimizer':
            parameters = {
                'n_estimators': [int(x) for x in range(100, 1001, 100)],
                'criterion': ['gini', 'entropy', 'log_loss'],
                'max_depth': [int(x) for x in range(2, 6)],
                'min_samples_split': [2, 5, 10],
                'min_samples_leaf': [1, 2, 4],
                'bootstrap': [False, True],
                'warm_start': [False, True],
                'random_state' : [42]
                #'class_weight': ['balanced']
            }
            rf_model = RandomForestClassifier()
            model = RandomizedSearchCV(estimator=rf_model, param_distributions=parameters, n_iter=50, cv=3, scoring='f1_weighted', random_state=42)
            print("Meilleurs hyperparamètres : ", model.fit(X_train, y_train, sample_weight=classes_weights).best_params_)
 
        elif model_name == 'Random Forest':
            model = RandomForestClassifier(
                warm_start=False,
                random_state=42,
                n_estimators=300,
                # min_samples_split=10,
                # min_samples_leaf=1,
                max_depth=5,
                criterion='gini',
                #class_weight='balanced',
                bootstrap=True
            )
 
        elif model_name == 'Multilinear Regression Optimizer':
            poly = PolynomialFeatures(degree=2, include_bias=False)
            linear_model = LinearRegression()
            pipeline = make_pipeline(poly, linear_model)
 
            parameters = {
                'polynomialfeatures__degree': [1, 2, 3],
                'linearregression__fit_intercept': [True, False],  
            }
 
            model = RandomizedSearchCV(
                pipeline,
                param_distributions=parameters,
                n_iter=10,
                scoring='neg_mean_squared_error',
                cv=5,
                random_state=42
            )
            print("Meilleurs hyperparamètres : ", model.fit(X_train, y_train).best_params_)
 
        elif model_name == 'Multilinear Regression':
            poly = PolynomialFeatures(degree=2, include_bias=False)
            linear_model = LinearRegression(fit_intercept=True)
            model = make_pipeline(poly, linear_model)
 
        elif model_name == 'SVC':
            model = SVC(
                class_weight='balanced',
                random_state=42
            )
        
        ### Model Fitting ###
        if type_label == 'classification':
            model.fit(X_train, y_train, sample_weight=classes_weights)
        elif type_label == 'regression':
            # print(f"{period}M label")
            # training_set_na_null.to_excel('training_set.xlsx')
            # X_train.to_excel('X_train.xlsx')
            # y_train.to_excel('y_train.xlsx')

            # training_set_na_null.to_pickle('training_set.pkl')
            # X_train.to_pickle('X_train.pkl')
            # y_train.to_pickle('y_train.pkl')

            model.fit(X_train, y_train)
        
        ### Model Prediction ###
        if type_label == 'classification':
            if 'Optimizer' in model_name:
                shap_explainer = shap.TreeExplainer(model.best_estimator_)
            else:
                shap_explainer = shap.TreeExplainer(model)
            shap_values = shap_explainer.shap_values(X_test)
            class_names=list(le.inverse_transform(model.classes_))
            shap_val_df = pd.DataFrame()
            for i in range(len(class_names)):
                shap_val_df = pd.concat([shap_val_df, pd.DataFrame(data = np.abs(shap_values[i]).mean(0), index=include_columns, columns=[class_names[i]])], axis=1)
            shap_val_df['overall'] = shap_val_df.sum(axis=1)

            y_pred = model.predict(X_test)
            y_proba = model.predict_proba(X_test)
            
            f1 = f1_score(y_test, y_pred.round(), average='weighted')
            accuracy = accuracy_score(y_test, y_pred.round())
            if 'Regression' not in model_name:
                y_pred_labels = le.inverse_transform(y_pred)
       
        elif type_label == 'regression':
            if 'Optimizer' in model_name:
                shap_explainer = shap.TreeExplainer(model.best_estimator_)
            else:
                shap_explainer = shap.TreeExplainer(model)
            shap_values = shap_explainer.shap_values(X_test)
            shap_val_df = pd.DataFrame(data = np.abs(shap_values).mean(0), index=include_columns, columns=['overall'])

            new_pred = model.predict(X_test)
            
            y_pred.append(new_pred)
            # mse = mean_squared_error(y_test, new_pred)
            mse = 0
            # r2 = r2_score(y_test, new_pred)
            r2 = 0
            #r2_corr = 1 - (1- r2)*((len(y_test)-1)/(len(y_test)-len(include_columns)-1))
            r2_corr=0
 
    if 'Optimizer' in model_name:
        model_params = model.best_estimator_.get_params()
    else:
        model_params = model.get_params()
 
    model_params = list(itemgetter('subsample','reg_lambda','reg_alpha','random_state','n_estimators','min_child_weight','max_depth','learning_rate','gamma','colsample_bytree','monotone_constraints')(model_params))
    dict_params = dict(zip(['subsample','reg_lambda','reg_alpha','random_state','n_estimators','min_child_weight','max_depth','learning_rate','gamma','colsample_bytree','monotone_constraints'],model_params))
 
    if type_label == 'classification':
        return y_pred_labels,y_proba, shap_val_df, class_names, f1, accuracy, dict_params, [model,X_test]
    elif type_label == 'regression':
        return y_pred, shap_val_df, mse, r2_corr, dict_params, [model,X_test]
        # return y_pred


# def get_Score_ML_from_predictions(test_dataset, y_pred, period_to_predict):
#     """Process model predictions and calculate final scores."""
#     # Add predictions for each period, for prod, there will be predictions for 3m and 12m
#     prediction_columns = []
#     for i, period in enumerate(period_to_predict):
#         col_name = f'predicted_return_{period}M'
#         test_dataset[col_name] = y_pred[i]
#         prediction_columns.append(col_name)
    
#     # Rank predictions  
#     for col in prediction_columns:
#         test_dataset[col] = test_dataset[col].rank(ascending=True)
      
#     # Calculate final ML score
#     test_dataset['Score ML'] = test_dataset[prediction_columns].mean(axis=1)
#     test_dataset['Score ML'] = test_dataset.groupby('Date')['Score ML'].rank(
#         pct=True,
#         ascending=True
#     ) * 10
    
#     return test_dataset[test_dataset['Date'] == test_dataset['Date'].max()]

def get_Score_ML_from_predictions(test_dataset, y_pred, period_to_predict):
    """
    Process model predictions and calculate final scores.

    Args:
        test_dataset: DataFrame containing the test data.
        y_pred: List of predictions generated by the ML model for each period.
        period_to_predict: List of prediction periods (e.g., [3, 12] for 3 months and 12 months).

    Returns:
        DataFrame containing the final `Score ML` for the most recent month.
    """
    # Initialize a list to store column names for predictions
    prediction_columns = []
    
    # Add predictions for each period (e.g., 3M, 12M)
    for i, period in enumerate(period_to_predict):
        col_name = f'predicted_return_{period}M'  # Generate column name for current period
        test_dataset[col_name] = y_pred[i]  # Add predictions to the dataset
        prediction_columns.append(col_name)  # Track the column name for ranking and scoring later
    
    # Rank predictions for each prediction column
    for col in prediction_columns:
        test_dataset[col] = test_dataset[col].rank(ascending=True)  # Rank values in ascending order
    
    # Calculate the final ML score as the average rank across all prediction columns
    test_dataset['Score ML'] = test_dataset[prediction_columns].mean(axis=1)
    
    # Normalize `Score ML` by ranking it within each date and scaling it to a range of 1-10
    test_dataset['Score ML'] = test_dataset.groupby('Date')['Score ML'].rank(
        pct=True,  # Rank as a percentage
        ascending=True  # Lower scores indicate better performance
    ) * 10  # Scale the rank to a range of 1-10
    
    # Return only the results for the most recent date in the dataset
    return test_dataset[test_dataset['Date'] == test_dataset['Date'].max()]

def get_date_ranges(screen_label, training_window, test_window):
    """
    Calculate and prepare date ranges for model training and testing periods.
    
    Parameters:
    -----------
    screen_label : DataFrame
        Input DataFrame with MultiIndex containing 'Date' level
    training_window : int
        Number of years for training period (e.g., 5 years)
    test_window : int
        Number of months for testing period (e.g., 12 months)
    
    Returns:
    --------
    data_train_and_test : DataFrame
        Filtered DataFrame containing both training and testing periods
    date_ranges : dict
        Dictionary containing key dates:
        - cut_screen_date: Start date for entire analysis period
        - first_date: First date in filtered dataset
        - split_date: Date separating training and testing periods
    
    Example:
    --------
    For training_window=5 and test_window=12:
    - If last_date is 2023-12-31
    - cut_screen_date will be 2017-12-01 (6 years back)
    - split_date will be first_date + 5 years + 1 month
    """

    # Get the most recent date from the dataset
    last_date = screen_label.index.get_level_values('Date').max()
    
    # Calculate the start date for the entire analysis period
    # Goes back training_window years plus test_window months
    # Example: For 5 years training + 12 months test = 6 years total
    cut_screen_date = last_date - relativedelta.relativedelta(
        years=training_window,
        months=test_window,
        day=1
    )

    # Taking 6 years historical data for prediction
    data_train_and_test = screen_label[screen_label.index.get_level_values('Date') >= cut_screen_date]
    
    # Find the earliest date for the past 6 years
    first_date = data_train_and_test.index.get_level_values('Date').min()
    
    # Using the first 5 years as training data
    split_date = first_date + relativedelta.relativedelta(
        years=training_window,
        months=1,
        day=1
    )
    
    # Return all relevant dates and filtered data
    # Note: test_dataset (Taking the last year as testing data) will be created in the main pipeline
    return data_train_and_test, {
        'cut_screen_date': cut_screen_date,
        'first_date': first_date,
        'split_date': split_date
    }




def labellize_data_and_fill_nan(input_transformed, params):
    """Handle the initial data preparation steps."""
    # Create a copy of input data
    screen_agg = copy.deepcopy(input_transformed)
    
    # Clean NaN values
    screen_na_clean = fill_nan_values(
        screen_agg,
        params['features'],
        params['period_to_predict'],
        params['min_pct_avail_features'],
        params['fill_na_method'],
        params['obs_weight'],
        params['returns_type']
    )
    
    # Create Label Columns based on label chosen to predict
    screen_label = labellize_data(
        screen_na_clean,
        params['period_to_predict'],
        params['returns_type'],
        params['type_label']
    )
    
    # Filter by weight of investment universe
    return screen_label[screen_label['Weight in univ'] > 0]

def fill_nan_values(data_input, features, period_to_predict, min_pct_avail_features=0.6, method='mean', obs_weight='none', returns_type='contrib'):
    """
    Fill missing values in the dataset based on specified criteria and method.
    
    Parameters:
    -----------
    data_input : DataFrame
        Input data containing features and return metrics
    features : list
        List of feature columns to process
    period_to_predict : list
        List of prediction periods (e.g., [3, 12] for 3-month and 12-month predictions)
    min_pct_avail_features : float, default=0.6
        Minimum percentage of non-missing features required to keep a row
    method : str, default='mean'
        Method to fill missing values ('mean', 'KNN Imputer', or 'median')
    obs_weight : str, default='none'
        Observation weighting method
    returns_type : str, default='contrib'
        Type of returns to process ('contrib', 'returns', or 'info_ratio')
    """
    # Fill missing values in Dividend Average Percentile with 0
    data_input['Dividend Avg Percentile'] = data_input['Dividend Avg Percentile'].fillna(0)
    
    # Calculate minimum number of features required to keep a row
    min_avail_features = ceil(len(features) * min_pct_avail_features)
    
    # Create a boolean mask for rows with sufficient non-missing features
    # True if number of missing features is less than or equal to the allowed maximum
    data_input['keep'] = data_input[features].isna().sum(axis=1) <= len(features) - min_avail_features
    
    # Generate contribution column names based on prediction periods
    col_contrib = ['contrib ' + str(period) + 'M' for period in period_to_predict]
    
    # Determine which columns need to be filled
    # Include contribution columns if obs_weight is 'contrib' or returns_type is 'contrib'
    to_fill = features + col_contrib if obs_weight == 'contrib' or returns_type == 'contrib' else features
    
    # Fill missing values based on specified method
    if method == 'mean':
        # Fill with column means
        data_input[to_fill] = data_input[to_fill].fillna(data_input[to_fill].mean())
    elif method == 'KNN Imputer':
        # Fill using K-Nearest Neighbors imputation
        imputer = KNNImputer() 
        data_input[to_fill] = imputer.fit_transform(data_input[to_fill])
    else:
        # Fill with column medians (default fallback)
        data_input[to_fill] = data_input[to_fill].fillna(data_input[to_fill].median())#groupby sector / Date
    
    # Filter out rows that don't meet the minimum feature availability requirement
    data_input = data_input[data_input['keep'] == True]
    
    # Remove the temporary 'keep' column
    data_input = data_input.drop(columns=['keep'])
    
    return data_input


    
def labellize_data(df, period_to_predict, returns_type, type_label, classes=None):
    """
    Create Label Columns based on label chosen to predict

    Parameters:
    -----------
    df : DataFrame
    period_to_predict : int or list
        Period(s) for prediction
    returns_type : str
        Type of returns ('returns', 'info_ratio', or 'contrib')
    type_label : str
        Type of labeling ('classification' or 'regression')
    classes : dict, optional
        Class thresholds for classification (default=None)
    """
    if type_label=='classification':
        if classes is None:
            raise ValueError("classes parameter is required when type_label='classification'")
            
        if returns_type == 'returns':
            for date in df.index.get_level_values('Date').unique():
                df_date = df[df.index.get_level_values('Date') == date]
                pct_rank = df_date[f'Relative {period_to_predict}M return'].rank(pct=True,ascending=False)
                for class_ in list(classes.keys()):
                    class_index = pct_rank[(pct_rank>=classes[class_][0])*(pct_rank<=classes[class_][1])].index
                    df.loc[class_index, f'{period_to_predict}M label'] = class_
        elif returns_type == 'info_ratio':
            for date in df.index.get_level_values('Date').unique():
                df_date = df[df.index.get_level_values('Date') == date]
                pct_rank = df_date[f'information_ratio {period_to_predict}M'].rank(pct=True,ascending=False)
                for class_ in list(classes.keys()):
                    class_index = pct_rank[(pct_rank>=classes[class_][0])*(pct_rank<=classes[class_][1])].index
                    df.loc[class_index, f'{period_to_predict}M label'] = class_
        elif returns_type == 'contrib':
            for date in df.index.get_level_values('Date').unique():
                df_date = df[df.index.get_level_values('Date') == date]
                pct_rank = df_date[f'contrib {period_to_predict}M'].rank(pct=True,ascending=False)
                for class_ in list(classes.keys()):
                    class_index = pct_rank[(pct_rank>=classes[class_][0])*(pct_rank<=classes[class_][1])].index
                    df.loc[class_index, f'{period_to_predict}M label'] = class_
    elif type_label=='regression':
        if returns_type=='returns':
            for period in period_to_predict:
                df[f'{period}M label'] = df[f'Relative {period}M return']
        elif returns_type == 'info_ratio':
            for period in period_to_predict:
                df[f'{period}M label'] = df[f'information_ratio {period}M']
        elif returns_type == 'contrib':
            for period in period_to_predict:
                df[f'{period}M label'] = df[f'contrib {period}M']

    return df



#####################################################################################################################
############################################ Backtesting Module #####################################################
#####################################################################################################################
# def create_historic_Score_ML(
#     screen_label,
#     params,
#     params_hyper_parameters,
#     update_score_ML=False,
#     allow_multiprocessing=True
# ):
#     """
#     Performs rolling window training and prediction using specified parameters.
    
#     Args:
#         screen_label: DataFrame containing the labeled data
#         params: Dictionary containing strategy parameters
#         params_hyper_parameters: Dictionary containing hyperparameters
#         update_score_ML: Boolean indicating whether to save results
#         allow_multiprocessing: Boolean indicating whether to use multiprocessing
    
#     Returns:
#         DataFrame containing predictions and scores
#     """
#     from multiprocessing import Pool
#     import os
#     from dateutil import relativedelta
    
#     # Extract parameters
#     period_to_predict = params['period_to_predict']
#     features = params['features']
#     model_name = params['model_name']
#     sampling_method = params['sampling_method']
#     training_window = params['training_window']
#     test_window = params['test_window']
#     obs_weight = params['obs_weight']
#     type_label = params['type_label']
#     feature_constraints = params["feature_constraints"]

#     # Set up dates
#     last_date = screen_label.index.get_level_values('Date').max()
#     first_date = screen_label.index.get_level_values('Date').min()
#     training_date = first_date + relativedelta.relativedelta(years=training_window)
#     test_date = training_date + relativedelta.relativedelta(months=test_window)
    
#     # Prepare test dataset
#     test_dataset = screen_label.loc[screen_label.index.get_level_values('Date') >= training_date].reset_index()
    
#     # Create rolling windows parameters
#     list_params_rolling = []
#     screen_rolling = screen_label[
#         (screen_label.index.get_level_values('Date') >= first_date) *
#         (screen_label.index.get_level_values('Date') <= test_date)
#     ]
    
#     list_params_rolling = [[
#         screen_rolling, model_name, params_hyper_parameters, period_to_predict,
#         features, training_date, feature_constraints, sampling_method, obs_weight, type_label
#     ]]
    
#     while training_date + relativedelta.relativedelta(months=test_window) < last_date:
#         first_date = first_date + relativedelta.relativedelta(months=test_window)
#         training_date = training_date + relativedelta.relativedelta(months=test_window)
#         test_date = training_date + relativedelta.relativedelta(months=test_window)
#         screen_rolling = screen_label[
#             (screen_label.index.get_level_values('Date') >= first_date) *
#             (screen_label.index.get_level_values('Date') <= test_date)
#         ]
#         list_params_rolling.append([
#             screen_rolling, model_name, params_hyper_parameters, period_to_predict,
#             features, training_date, feature_constraints, sampling_method, obs_weight, type_label
#         ])
    
#     # Perform predictions
#     if allow_multiprocessing:
#         with Pool(os.cpu_count()-1) as p:
#             results_period = p.starmap(predict, [params for params in list_params_rolling])
#     else:
#         results_period = []
#         for params in list_params_rolling:
#             predict_result = predict(*params)
#             results_period.append(predict_result)
    
#     # Process results based on type_label
#     if type_label == 'classification':
#         for i, result in enumerate(results_period):
#             train_date = list_params_rolling[i][5]
#             test_date = train_date + relativedelta.relativedelta(months=test_window)
#             mask = (test_dataset['Date'] >= train_date) * (test_dataset['Date'] <= test_date)
#             test_dataset.loc[mask, 'predicted_class'] = result[0]
#             test_dataset.loc[mask, result[3]] = result[1]
            
#     elif type_label == 'regression':
#         for i, result in enumerate(results_period):
#             train_date = list_params_rolling[i][5]
#             test_date = train_date + relativedelta.relativedelta(months=test_window)
#             mask = (test_dataset['Date'] >= train_date) * (test_dataset['Date'] <= test_date)
            
#             prediction_columns = []
#             for j, period in enumerate(period_to_predict):
#                 col_name = f'predicted_return_{period}M'
#                 test_dataset.loc[mask, col_name] = result[0][j]
#                 prediction_columns.append(col_name)
            
#             # Rank predictions
#             for col in prediction_columns:
#                 test_dataset[col] = test_dataset[col].rank(ascending=True)
            
#             # Calculate final ML score
#             test_dataset.loc[mask, 'Score ML'] = test_dataset[prediction_columns].mean(axis=1)
#             test_dataset.loc[mask, 'Score ML'] = test_dataset.groupby('Date')['Score ML'].rank(
#                 pct=True,
#                 ascending=True
#             ) * 10
    
#     # Save results if requested
#     if update_score_ML:
#         save_path_excel = "SCORE_ML_2010_to_Today.xlsx"
#         save_path_pickle = "SCORE_ML_2010_to_Today.pkl"
#         test_dataset.to_excel(save_path_excel)
#         test_dataset.to_pickle(save_path_pickle)

#     return test_dataset

def create_historic_Score_ML(
    screen_label,
    params,
    params_hyper_parameters,
    update_score_ML=False,
    output_file="SCORE_ML_2010_to_Today",
    allow_multiprocessing=True
):
    """
    Performs rolling window training and prediction using specified parameters.
    
    Args:
        screen_label: DataFrame containing the labeled data
        params: Dictionary containing strategy parameters
        params_hyper_parameters: Dictionary containing hyperparameters
        update_score_ML: Boolean indicating whether to save results
        allow_multiprocessing: Boolean indicating whether to use multiprocessing
    
    Returns:
        DataFrame containing predictions and scores
    """
    from multiprocessing import Pool
    import os
    from dateutil import relativedelta
    
    # Extract parameters from input
    period_to_predict = params['period_to_predict']  # Periods to predict (e.g., 3M, 12M)
    features = params['features']  # Features to be used for training the model
    model_name = params['model_name']  # Name of the ML model (e.g., XGBoost)
    sampling_method = params['sampling_method']  # Sampling method for training
    training_window = params['training_window']  # Training window (in years)
    test_window = params['test_window']  # Testing window (in months)
    obs_weight = params['obs_weight']  # Observation weighting method
    type_label = params['type_label']  # Task type (e.g., classification or regression)
    feature_constraints = params["feature_constraints"]  # Constraints on features

    # Set up date ranges for rolling training and testing
    last_date = screen_label.index.get_level_values('Date').max()  # Last date in the dataset
    first_date = screen_label.index.get_level_values('Date').min()  # First date in the dataset
    training_date = first_date + relativedelta.relativedelta(years=training_window)  # Training start date
    test_date = training_date + relativedelta.relativedelta(months=test_window)  # Test start date
    
    # Prepare test dataset for the entire period
    test_dataset = screen_label.loc[screen_label.index.get_level_values('Date') >= training_date].reset_index()
    
    # Initialize parameters for rolling windows
    list_params_rolling = []
    screen_rolling = screen_label[
        (screen_label.index.get_level_values('Date') >= first_date) *
        (screen_label.index.get_level_values('Date') <= test_date)
    ]
    
    # Append the first rolling window parameters
    list_params_rolling = [[
        screen_rolling, model_name, params_hyper_parameters, period_to_predict,
        features, training_date, feature_constraints, sampling_method, obs_weight, type_label
    ]]
    
    # Iterate through the dataset to create rolling windows
    while training_date + relativedelta.relativedelta(months=test_window) < last_date:
        # Update date ranges for the next rolling window
        first_date = first_date + relativedelta.relativedelta(months=test_window)
        training_date = training_date + relativedelta.relativedelta(months=test_window)
        test_date = training_date + relativedelta.relativedelta(months=test_window)
        
        # Filter data for the current rolling window
        screen_rolling = screen_label[
            (screen_label.index.get_level_values('Date') >= first_date) *
            (screen_label.index.get_level_values('Date') <= test_date)
        ]
        
        # Append parameters for the current rolling window
        list_params_rolling.append([
            screen_rolling, model_name, params_hyper_parameters, period_to_predict,
            features, training_date, feature_constraints, sampling_method, obs_weight, type_label
        ])
    
    # Perform predictions using multiprocessing or sequentially
    if allow_multiprocessing:
        # Use multiprocessing for faster execution
        with Pool(os.cpu_count()-1) as p:  # Reserve 1 CPU core for system processes
            results_period = p.starmap(predict, [params for params in list_params_rolling])
    else:
        # Sequential execution (slower, but useful for debugging)
        results_period = []
        for params in list_params_rolling:
            predict_result = predict(*params)
            results_period.append(predict_result)
    
    # Process results based on task type (classification or regression)
    if type_label == 'classification':
        # For classification tasks, assign predicted classes and probabilities
        for i, result in enumerate(results_period):
            train_date = list_params_rolling[i][5]  # Training start date
            test_date = train_date + relativedelta.relativedelta(months=test_window)  # Test end date
            mask = (test_dataset['Date'] >= train_date) * (test_dataset['Date'] <= test_date)  # Date range mask
            
            # Assign predicted class and probabilities
            test_dataset.loc[mask, 'predicted_class'] = result[0]
            test_dataset.loc[mask, result[3]] = result[1]
            
    elif type_label == 'regression':
        # For regression tasks, assign predicted returns and calculate scores
        for i, result in enumerate(results_period):
            train_date = list_params_rolling[i][5]  # Training start date
            test_date = train_date + relativedelta.relativedelta(months=test_window)  # Test end date
            mask = (test_dataset['Date'] >= train_date) * (test_dataset['Date'] <= test_date)  # Date range mask
            
            prediction_columns = []
            for j, period in enumerate(period_to_predict):
                # Create column names for predicted returns
                col_name = f'predicted_return_{period}M'
                test_dataset.loc[mask, col_name] = result[0][j]
                prediction_columns.append(col_name)
            
            # Rank predictions for each column
            for col in prediction_columns:
                test_dataset[col] = test_dataset[col].rank(ascending=True)
            
            # Calculate the final ML score as the average of all prediction rankings
            test_dataset.loc[mask, 'Score ML'] = test_dataset[prediction_columns].mean(axis=1)
            
            # Normalize and rank the final ML score
            test_dataset.loc[mask, 'Score ML'] = test_dataset.groupby('Date')['Score ML'].rank(
                pct=True,
                ascending=True
            ) * 10  # Scale scores to 1-10
    
    # Save results to Excel and pickle files if requested
    if update_score_ML:
        save_path_excel = f"{output_file}.xlsx"
        save_path_pickle = f"{output_file}.pkl"
        test_dataset.to_excel(save_path_excel)  # Save as Excel file
        test_dataset.to_pickle(save_path_pickle)  # Save as pickle file

    return test_dataset