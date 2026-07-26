from multiprocessing import Pool
import pandas as pd
import copy
from . import pandas_ta as ta
import os
from .tradingpatterns import tradingpatterns
from .candlestick import candlestick
import itertools

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

def effective_cpus() -> int:
    # Respecte les CPUs alloués (cpuset) sous Linux
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 1  # fallback

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
    grouped_data = [data[1] for data in df_grouped]
    if not grouped_data:
        return pd.DataFrame()
    workers = min(max(1, effective_cpus() // 2), len(grouped_data))
    try:
        if workers == 1:
            result = [func(data) for data in grouped_data]
        else:
            with Pool(processes=workers) as p:
                result = p.map(func, grouped_data)
    except Exception as e:
        print(f"Multiprocessing failed with error: {e}. Falling back to serial processing.")
        result = [func(data) for data in grouped_data]
    patterns=pd.concat(result,axis=1)
    return patterns


def build_period_availability(returns_index, period='week'):
    """
    Build period start/end and first tradable availability date from a returns calendar.

    For weekly technical patterns, the pattern row dated at the first trading day of
    the week is only fully available after the last trading day of that same week.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(returns_index)).dropna().sort_values().unique()
    if dates.empty:
        return pd.DataFrame(columns=['period_key', 'technical_period_start', 'technical_period_end', 'technical_available_date'])

    calendar = pd.DataFrame({'return_date': dates})
    if period == 'week':
        calendar['period_key'] = calendar['return_date'].dt.strftime('%G-W%V')
    else:
        calendar['period_key'] = calendar['return_date'].dt.strftime('%Y-%m')

    availability = (
        calendar.groupby('period_key', as_index=False)['return_date']
        .agg(technical_period_start='min', technical_period_end='max')
    )
    ordered_dates = pd.DatetimeIndex(calendar['return_date'])

    def next_trading_day(period_end):
        candidates = ordered_dates[ordered_dates > pd.Timestamp(period_end)]
        return candidates[0] if len(candidates) else pd.NaT

    availability['technical_available_date'] = availability['technical_period_end'].map(next_trading_day)
    return availability


def add_period_availability_columns(patterns, returns_index, date_col='Date', period='week'):
    """Attach availability metadata to a patterns dataframe without changing its Date label."""
    frame = patterns.copy()
    frame[date_col] = pd.to_datetime(frame[date_col], errors='coerce')
    availability = build_period_availability(returns_index, period=period)
    if period == 'week':
        frame['period_key'] = frame[date_col].dt.strftime('%G-W%V')
    else:
        frame['period_key'] = frame[date_col].dt.strftime('%Y-%m')
    frame = frame.merge(availability, on='period_key', how='left')
    frame.drop(columns=['period_key'], inplace=True)
    return frame


def calcul_indicator(group):
    """
    Calcul des indicateurs financiers techniques avec la librairie pandas-ta
    en permettant plusieurs configurations par indicateur.
    """

    # === Définition des configurations ===

    configs = {
        "ema": [10, 20, 50, 100],                # longueurs EMA
        "fwma": [10, 30, 50],               # trois longueurs FWMA
        "macd": [(12, 26, 9), (20, 50, 18), (50, 100, 25)],  # trois sets (fast, slow, signal)
        "rsi": [14, 21, 30],                # trois longueurs RSI
        "rvi": [10, 14, 20],                # trois longueurs RVI
        "momentum": [10, 20, 30, 50, 100],           # trois longueurs Momentum
        "psar": [(0.02, 0.2), (0.01, 0.1), (0.005, 0.05)], # trois sets (step, max)
        "bbands": [(5, 2.0), (20, 2.0), (10, 1.5)],     # trois sets (length, std)
        "atr": [14, 21, 30],                # trois longueurs ATR
        "stdev": [10, 20, 30]               # trois longueurs Stdev
    }

    def safe_join(frame, indicator):
        if indicator is None:
            return frame
        if isinstance(indicator, pd.Series):
            indicator = indicator.to_frame()
        if getattr(indicator, "empty", False):
            return frame
        return frame.join(indicator)


    # === Calcul des indicateurs ===
    # Trend
    for length in configs["ema"]:
        group[f'ema_{length}'] = ta.ema(group['Close'], length=length)

    for length in configs["fwma"]:
        group[f'fwma_{length}'] = ta.fwma(group['Close'], length=length)

    for fast, slow, signal in configs["macd"]:
        macd = ta.macd(group['Close'], fast=fast, slow=slow, signal=signal)
        group = safe_join(group, macd)

    # Momentum
    for length in configs["rsi"]:
        group[f'rsi_{length}'] = ta.rsi(group['Close'], length=length)

    for length in configs["rvi"]:
        group[f'rvi_{length}'] = ta.rvi(group['Close'], length=length)

    for length in configs["momentum"]:
        group[f'momentum_{length}'] = ta.momentum.mom(group['Close'], length=length)

    group['entropy'] = ta.entropy(group['Close'])
    group['skew'] = ta.skew(group['Close'])


    for step, maximum in configs["psar"]:
        psar = ta.psar(high=group['High'], low=group['Low'], step=step, maximum=maximum)
        if psar is not None:
            psar = psar.rename(columns=lambda c: f"{c}_{step}_{maximum}")  # Ajout des paramètres dans le nom
        group = safe_join(group, psar)

    for length, std in configs["bbands"]:
        bbands = ta.bbands(group['Close'], length=length, std=std)
        if bbands is not None:
            bbands = bbands.rename(columns=lambda c: f"{c}_{length}_{std}")  # Ajout des paramètres
        group = safe_join(group, bbands)


    for length in configs["atr"]:
        group[f'atr_{length}'] = ta.atr(high=group['High'], low=group['Low'], close=group['Close'], length=length)

    # Statistics
    for length in configs["stdev"]:
        group[f'stdev_{length}'] = ta.stdev(group['Close'], length=length)

    return group
