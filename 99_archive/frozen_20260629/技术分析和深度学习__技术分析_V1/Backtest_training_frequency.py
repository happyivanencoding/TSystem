import numpy as np
import pandas as pd
import scipy
import datetime
import sys
import os
import copy
import math
from tqdm import tqdm
from tqdm.contrib.concurrent import process_map
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import MinMaxScaler,OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from xgboost import XGBClassifier
from sklearn.metrics import confusion_matrix,f1_score,accuracy_score,r2_score
from sklearn.metrics import mean_absolute_percentage_error, mean_squared_error

from myclass import sec_list_generation
from optimi import detect_pattern_,generate_stock,scanner,patterns_encoder,candlestick_pattern
from multiprocessing import Pool
from myclass.Backtest import generation_sec_list



def generate_score_ML(params):
    """
        Generer des Scores ML à utiliser pour la construction des seclist
        Args:
                debut: date de debut du backtest
                preprocessor: pipeline de preprocessing des données
                model: model de prédiction déja entrainé
        return: 
                Score deep learning
    """
    data,fin_train,fin_test,preprocessor,model,features,target,proba=params
    df=copy.deepcopy(data)
    df=df[(df.reset_index()['Date']<fin_test).values]
    index=df.reset_index()['Date']
    X=df.loc[(index<fin_train).values,features]
    Y=df.loc[(index<fin_train).values,target]
    x_train=preprocessor.fit_transform(X)
    y_train=(Y.values.reshape(-1,1)>0).astype(int)
    f=model
    f.fit(x_train,y_train) 

    X_backtest=df.loc[(index>=fin_train).values,features]        
    X_backtest=preprocessor.transform(X_backtest)
    if proba==False:
        pred_backtest=model.predict(X_backtest)
    else:
        pred_backtest=model.predict_proba(X_backtest)[:,1]

    indices=(index>=fin_train).values
    X_backtest_=pd.concat([df.loc[indices,features],
                       pd.DataFrame(pred_backtest,columns=['pred'],index=df.loc[indices].index)],axis=1)
    X_backtest_=X_backtest_.reset_index(level=1).groupby(by='Date').apply(lambda x:x).drop('Date',axis=1)
    X_backtest_['rank']=X_backtest_.reset_index(level=0).groupby(by='Date').apply(lambda x:x[['pred']].rank(pct='True')*10)
    return X_backtest_

def Backtest_yearly(model,screen,returns,df,start_date,reco_secto,liste_noire,features,target,backtest=True,
                    Sedol=None,frequency=365, mutliprocessing=True,metrics='Score ML', percentile=0.2,
                    proba=True,bench= "STOXX EUROPE 600", ptf_name='ML EU Q1',ponderation='Market cap' ,
                    esg_exclusion=0,cut_mkt_cap=0, score_neutral="ICB 19", 
                    weight_neutral="ICB 19",top_mandatory_with_bench_weight=False,
                    top_mandatory=3):
    """ Backtest avec réentrainenement du moèle à frequence  
        Args:
                model: modèle à utiliser pour la prediction
                stard_date: date de debut du backtest
                frequency:frequence de reentrainement du modèle
                backtest: définit s'il faut retourner les returns du portefeuille backtesté ou les scores ML d'un esemble de boite
                Sedol: sedol de l'entreprise ou dun groupe d'entreprises dont on souhaite observer le score ML au cours du temps
                features: variables predictives à utiliser pour la prédiction 
        return: 
                Score ML
    """
    

    numerical_pipeline=Pipeline([('imputer',SimpleImputer(strategy='mean')),
                                    ('scaler',MinMaxScaler())])
    categorical_pipeline=Pipeline([('Imputer',SimpleImputer(strategy='most_frequent')),
                                    ('encoder',OneHotEncoder(drop='first',handle_unknown='ignore',sparse_output=False,dtype=int))])
    
    numerical_features=df[features].select_dtypes(exclude='object').columns
    categorical_features=df[features].select_dtypes(include='object').columns
    dates=[pd.to_datetime(start_date)]
    parameters=[]

    while dates[-1]<df.reset_index()['Date'].max():
        dates.append(dates[-1]+datetime.timedelta(days=frequency))
        preprocessor=ColumnTransformer([('num',numerical_pipeline,numerical_features),
                                            ('cat',categorical_pipeline,categorical_features)])
        params=[df,dates[-2],dates[-1],preprocessor,model,features,target,proba]
        parameters.append(params)
    

    if mutliprocessing:
        try:
            # Try multiprocessing first
            with Pool(processes=max(1, os.cpu_count()-1)) as p:
                x_backtest=process_map(generate_score_ML,parameters,max_workers=max(1,os.cpu_count()-1))
                
        except Exception as e:
            # Fallback to serial processing if multiprocessing fails
            print(f"Multiprocessing failed with error: {e}. Falling back to serial processing.")
    
    else:
        for date in dates:
            index=df.reset_index()['Date']
            X=df.loc[(index<date).values,features]
            Y=df.loc[(index<date).values,target]
            preprocessor=ColumnTransformer([('num',numerical_pipeline,numerical_features),
                                            ('cat',categorical_pipeline,categorical_features)])
            x_train=preprocessor.fit_transform(X)
            y_train=(Y.values.reshape(-1,1)>0).astype(int)
            f=model
            f.fit(x_train,y_train)
            stop_date=date+datetime.timedelta(days=frequency)
            if stop_date>index.values[-1]:
                stop_date=index.values[-1]
            x_date=generate_score_ML(df.loc[(index<stop_date).values],date,preprocessor,f,features,proba=proba)
            x_backtest.append(x_date)
            date=date+datetime.timedelta(days=frequency)

    x_backtest=pd.concat(x_backtest,axis=0)    
   
    if backtest==False:
        drop_columns=[  'Dividend Avg Percentile','Value Avg Percentile',
                        'Quality Avg Percentile', 'Mom Avg Percentile',
                        'LowVol Avg Percentile','Growth Avg Percentile']
        screen_agg=pd.merge(screen.drop('Score ML',axis=1).reset_index(),x_backtest.drop(drop_columns,axis=1).reset_index(),
         on=['Date','Company SEDOL'],how='inner').rename({'rank':'Score ML'},axis=1).set_index('ISIN')
    
        if type(Sedol)!=list:
            Sedol=[Sedol]

        return screen_agg[screen_agg['Company SEDOL'].isin(Sedol)][['Company SEDOL','Date','Name','Exchange Country Name','FactSet Economy']+features+['Score ML']]
    

    
    screen_agg=pd.merge(screen.drop('Score ML',axis=1).reset_index(),x_backtest[['rank']].reset_index(),
         on=['Date','Company SEDOL'],how='inner').rename({'rank':'Score ML'},axis=1).set_index('ISIN')
    
    myfunc=generation_sec_list(screen_agg,returns, bench, percentile, start_date, metrics, ptf_name, reco_secto=reco_secto,
                            ponderation=ponderation,esg_exclusion=esg_exclusion, cut_mkt_cap=cut_mkt_cap, 
                            score_neutral=score_neutral,
                            weight_neutral=weight_neutral,top_mandatory = top_mandatory,liste_noire=liste_noire,
                            top_mandatory_with_bench_weight = top_mandatory_with_bench_weight)
    select_screen= myfunc.generic_histo_seclist()
    perf_bench=myfunc.get_bench_perf(screen_agg)
    perf_ttr, buy_list=myfunc.backtest()
    return perf_bench,perf_ttr,select_screen