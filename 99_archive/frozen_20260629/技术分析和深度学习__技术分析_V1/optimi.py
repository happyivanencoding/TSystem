import copy
import numpy as np
import pandas as pd
import pandas_ta as ta
import os
import itertools
import sys
import tradingpatterns
from candlestick import candlestick
from multiprocessing import Pool
from tqdm.contrib.concurrent import process_map
import mplfinance as mpf

def generate_stock(returns,start_date=None):
    """
    Generate stock price according to the returns starting to 100
    """
    rdt=copy.deepcopy(returns)
    if start_date==None:
        start_date=rdt.index[0]
    rdt=rdt.loc[rdt.index>=start_date]
    rdt.loc[start_date]=0
    rdt=100*(1+rdt).cumprod()
    return rdt

def scanner(group,multiprocessing=True):
    data=group.copy()
    isin_name=data.columns.get_level_values(0)[0]
    data.columns=data.columns.get_level_values(1)
    models=[tradingpatterns.detect_high_low,
            tradingpatterns.detect_wedge,
            tradingpatterns.detect_head_shoulder,
            tradingpatterns.detect_multiple_tops_bottoms,
            tradingpatterns.detect_triangle_pattern,
            tradingpatterns.detect_double_top_bottom,
            tradingpatterns.detect_trendline,
            tradingpatterns.calculate_support_resistance,
            tradingpatterns.find_pivots,
            tradingpatterns.detect_channel,
            ]
    for model in models:
        data=model(data)
    columns=[]
    for col in data.columns:
        columns.append((isin_name,col))
    if multiprocessing:
        data.columns=pd.MultiIndex.from_tuples(columns)
    return data


def candlestick_pattern(data):
    df=data.copy()
    columns=df.columns.get_level_values(0).unique()
    df.columns=df.columns.get_level_values(1)
    df.rename({'Low':'low','High':'high','Close':'close','Open':'open'},axis=1,inplace=True)
    df = candlestick.bullish_engulfing(df)
    df = candlestick.bearish_engulfing(df)
    df = candlestick.doji(df)
    df = candlestick.hammer(df)
    df = candlestick.hanging_man(df)
    df = candlestick.inverted_hammer(df)
    df = candlestick.shooting_star(df)
    df = candlestick.morning_star(df)
    df = candlestick.bullish_harami(df)
    df = candlestick.bearish_harami(df)
    df = candlestick.piercing_pattern(df)
    df = candlestick.dark_cloud_cover(df)
    df.columns=pd.MultiIndex.from_tuples(list(itertools.product(columns,df.columns)))
    return df


def detect_pattern_(returns,period='week',library='tradingpatterns',start_date=None):
    """
        detect trading pattern in the returns series
    """
    numeric_columns=returns.select_dtypes(include=float).columns
    categorical_columns=returns.select_dtypes(exclude=float).columns
    df=generate_stock(returns[numeric_columns],start_date)
    df=pd.concat([returns[categorical_columns],df],axis=1)
    index_name=df.index.name
    if index_name is None:
        index_name='index'
    df=df.reset_index()
    if period=='week':
        df['period']=df[index_name].dt.strftime('%G-W%V').values
    else:
        df['period']=df[index_name].dt.strftime('%Y-%m').values
    df=df.groupby(by='period').agg(['min','max','last','first']).rename({'min':'Low','max':'High','last':'Close','first':'Open'},axis=1)
    df_grouped=df.set_index((index_name,'Low')).drop(index_name,axis=1).rename_axis('Date').groupby(level=0,axis=1)
    if library=='tradingpatterns':
        func=scanner
    else:
        func=candlestick_pattern
    try:
        with Pool(processes=max(1, os.cpu_count()-1)) as p:
            result = p.map(func,[data[1] for data in df_grouped])
    except Exception as e:
        print(f"Multiprocessing failed with error: {e}. Falling back to serial processing.")
    patterns=pd.concat(result,axis=1)
    return patterns


def patterns_encoder(data):
    val=isinstance(data.columns,pd.MultiIndex)
    categorical_columns=data.select_dtypes(include='object').columns
    data[categorical_columns]=data[categorical_columns].replace({np.nan:'Nan'})
    data=pd.get_dummies(data,columns=categorical_columns,
                        drop_first=True, prefix_sep='_').replace({True:1,False:0})
    columns=[]
    if val:
        for col in data.columns:
            if type(col)==str:
                level0= col.split(')')[0].split(",")[0][1:].strip("'")
                level1= col.split(')')[0].split(",")[1][1:].strip("'")+col.split(')')[1].strip("'")
                col=(level0,level1)
                columns.append(col)
        data.columns=pd.MultiIndex.from_tuples(columns)
    return data


def candleplot(data,start_date,end_date,addplot=[],ISIN='B2F37H-R'):
    data=data.loc[:,data.columns.get_level_values(0)==ISIN]
    data=data.loc[(data.index>=start_date) & (data.index<end_date)].iloc[:,:4]
    data=pd.DataFrame(data.values,columns=['Low','High','Close','Open'],index=data.index)
    mpf.plot(data, type='candle', addplot=addplot, volume=False, style='charles', 
         title='Candlestick Chart ' + ISIN,figratio=(12, 6),
         figscale=1.5)


def calcul_indicator(group):
    """     
        calcul des indicateurs financiers techniques avec la librairie pandas ta
    """
    # trend
    group['ema']=ta.ema(group['Close'])
    group['fwma']=ta.fwma(group['Close'])
    group[['MACD_12_26_9','MACDh_12_26_9','MACDs_12_26_9']]=ta.macd(group['Close'])
    #group['adx']=ta.adx(high=group['High'],low=group['Low'],close=group['Close'],length=14)
    # momentum
    group['rsi']=ta.rsi(group['Close'])
    group['rvi']=ta.rvi(group['Close'])
    group['momentum']=ta.momentum.mom(group['Close'])
    group['entropy']=ta.entropy(group['Close'])
    group['skew']=ta.skew(group['Close'])
    # volatility
    group[['PSARl_0.02_0.2','PSARs_0.02_0.2','PSARaf_0.02_0.2','PSARr_0.02_0.2']]=ta.psar(high=group['High'],low=group['Low'])
    group[['BBL_5_2.0','BBM_5_2.0','BBU_5_2.0','BBB_5_2.0','BBP_5_2.0']]=ta.bbands(group['Close'])
    group['atr']=ta.atr(high=group['High'],low=group['Low'],close=group['Close'],length=14)
    # statistics
    group['stdev']=ta.stdev(group['Close'])
    return group

def merge_pattern_df(df,returns):
    """
    build a new DatFrae with all the new technical indicators
    """
    def find(df,date):
        """
        Permet de retourner l'index i de l'élément antérieur le plus proche de la date
        """
        i=0
        j=len(df)
        while i<j-1:
            k=(i+j)//2
            if df['Date'].values[k]>date:
                j=k
            else:
                i=k
        if df['Date'].values[j]<=date:
            return j
        elif df['Date'].values[i]<=date:
            return i
        else:
            return i-1 
        
    # merge les fichiers contenant les patterns    
    patterns=detect_pattern_(returns[[col for col in df.index.get_level_values(0).unique()]])
    patterns=patterns.stack(level=0)
    patterns_candle=detect_pattern_(returns[[col for col in df.index.get_level_values(0).unique()]],library='candlestick')
    patterns_candle=patterns_candle.loc[:,~patterns_candle.columns.get_level_values(1).isin(['low','open','close','high'])].stack(level=0)
    patterns=pd.concat([patterns,patterns_candle.loc[patterns.index]],axis=1)
    patterns.index=patterns.index.reorder_levels([1,0])
    patterns.index.names=df.index.names
    # calcul des indicateurs supplémentaires grace a pandas ta 
    indicator=patterns[['Open','High','Low','Close']].groupby(level=0,axis=0).apply(calcul_indicator).droplevel(0)
    patterns=pd.concat([patterns,indicator.iloc[:,4:]],axis=1)

    # construction du DataFrame Final
    dates=[]
    corres={}
    patterns=patterns.reset_index()
    for date in df.index.get_level_values(1).unique():
        j=find(patterns,date)
        dates.append(patterns['Date'].iloc[j])
        corres[patterns['Date'].iloc[j]]=date
    patterns=patterns.set_index(['Company SEDOL','Date'])
    index=pd.MultiIndex.from_tuples(itertools.product(patterns.index.get_level_values(0).unique(),dates))
    data=pd.concat([df,patterns.rename(corres,axis=0).loc[df.index]],axis=1)
    return data


