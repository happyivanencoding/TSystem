import pandas as pd
import numpy as np
import importlib.util

try:
    import matplotlib.pyplot as plt
except ImportError:
    plt = None

try:
    from pandarallel import pandarallel
    PANDARALLEL_AVAILABLE = True
except ImportError:
    pandarallel = None
    PANDARALLEL_AVAILABLE = False

NUMBA_AVAILABLE = importlib.util.find_spec("numba") is not None

######VOLATILITE######
def vol_ewma_vectorized(df_return, decay_factor = 0.98, ):
    T = len(df_return)
    mean = df_return.mean()
    e = np.arange(T-1, -1, -1)
    r = np.repeat(decay_factor, T)
    vecLambda = np.power(r, e)
    ewm_tmp = (np.power(df_return - mean, 2) * vecLambda).sum()
    variance = ewm_tmp / vecLambda.sum()
    volatility_ewma = (variance) ** (1 / 2)
    return volatility_ewma

def ewma_vol_window_rolling(returns, decay_factor = 0.98, frec_data = 252, window = 252):
    scaling_factor = np.sqrt(frec_data)
    if NUMBA_AVAILABLE:
        vol = returns.rolling(window).apply(
            vol_ewma_vectorized,
            args=(decay_factor,),
            engine='numba',
            raw=True,
        )
    else:
        vol = returns.rolling(window).apply(
            vol_ewma_vectorized,
            args=(decay_factor,),
            raw=True,
        )
    vol = vol * scaling_factor
    return vol




#####FONCTIONS#####
def excess_rolling(returns, window=252):
    rolling_mean = returns.rolling(window=window).mean()
    excess = returns - rolling_mean
    return excess


def returns_rolling_up_down(returns, sens, window=252, benchmark_col="SXXP Bench"):
    if sens == "down":    
        mask_positive = returns[benchmark_col] <= 0 
    else :
        mask_positive = returns[benchmark_col] >= 0
    excess = returns.where(mask_positive)
    excess = excess.ffill()

    return excess


# = COV x N
def multiply_by_benchmark(df_excess_returns, benchmark_col="SXXP Bench"):

    df_multiplied = df_excess_returns.apply(lambda x: x * df_excess_returns[benchmark_col], axis=0)
    return df_multiplied


#BETA
def divide_by_var_benchmark(df, benchmark_col="SXXP Bench"):
    # Multiplie chaque colonne du dataframe par la colonne "SXXP Bench"
    df_multiplied = df.apply(lambda x: x / df[benchmark_col], axis=0)
  
    return df_multiplied





#####BENCH######
def add_weighted_benchmark_return(
    df_returns_last,
    df_aggregate,
    weight_column="Weight in STOXX EUROPE 600",
    benchmark_column="SXXP Bench",
):
    returns_with_bench = df_returns_last.copy()
    df_returns_stacked = returns_with_bench.stack().reset_index()
    df_returns_stacked.columns = ['Date', 'SEDOL', 'Return']
    weights = df_aggregate[[weight_column, 'Company SEDOL', 'Date']].copy()
    weights = weights.rename(columns={"Company SEDOL": "SEDOL"})

    df_returns_stacked = df_returns_stacked.sort_values('Date')
    weights = weights.sort_values('Date')

    df_merged = pd.merge_asof(
        df_returns_stacked,
        weights,
        on='Date',
        by='SEDOL',
        direction='backward'
    )

    df_weighted = df_merged[df_merged[weight_column].notna()]
    df_weighted = df_weighted[df_weighted[weight_column] != 0]
    df_weighted['Contribution'] = df_weighted['Return'] * df_weighted[weight_column]
    df_weighted['Sum_Weights'] = df_weighted.groupby('Date')[weight_column].transform('sum')
    df_weighted['Normalized Contribution'] = df_weighted['Contribution'] / df_weighted['Sum_Weights']
    df_performance = df_weighted.groupby('Date')['Normalized Contribution'].sum().reset_index()
    df_performance.columns = ['Date', benchmark_column]
    df_performance.index = df_performance['Date']
    df_performance = df_performance[[benchmark_column]]
    df_performance = df_performance[df_performance.index >= returns_with_bench.index[0]]
    df_performance = df_performance[df_performance.index <= returns_with_bench.index[-1]]
    returns_with_bench[benchmark_column] = df_performance[benchmark_column]
    return returns_with_bench


def add_bench_return(df_returns_last, df_aggregate):
    return add_weighted_benchmark_return(
        df_returns_last,
        df_aggregate,
        weight_column="Weight in STOXX EUROPE 600",
        benchmark_column="SXXP Bench",
    )


def add_regional_benchmark_returns(df_returns_last, df_aggregate):
    returns_with_bench = df_returns_last.copy()
    benchmark_specs = [
        ("Weight in STOXX EUROPE 600", "SXXP Bench"),
        ("Weight in SP500", "SP500 Bench"),
        ("Weight in MSCI WORLD", "MSCI WORLD Bench"),
    ]
    for weight_column, benchmark_column in benchmark_specs:
        if weight_column in df_aggregate.columns:
            returns_with_bench = add_weighted_benchmark_return(
                returns_with_bench,
                df_aggregate,
                weight_column=weight_column,
                benchmark_column=benchmark_column,
            )
    return returns_with_bench


#######BETA#########
def beta(df_returns_last, benchmark_col="SXXP Bench"):
    df_excess_returns = excess_rolling(df_returns_last)
    df_cov_step1 = multiply_by_benchmark(df_excess_returns, benchmark_col=benchmark_col)
    df_cov_step2 = df_cov_step1.ewm(span=100, adjust=False).mean()
    df_cov_step3 = divide_by_var_benchmark(df_cov_step2, benchmark_col=benchmark_col)
    df_beta = df_cov_step3.drop(columns=[benchmark_col], errors="ignore").dropna(how="all")

    return df_beta


def beta_up(df_returns_last, benchmark_col="SXXP Bench"):
    df_step1 = returns_rolling_up_down(df_returns_last, "up", benchmark_col=benchmark_col)
    df_step2 = multiply_by_benchmark(df_step1, benchmark_col=benchmark_col)
    df_step3 = df_step2.rolling(window=252).mean()
    df_step4 = divide_by_var_benchmark(df_step3, benchmark_col=benchmark_col)
    df_beta_up = df_step4.drop(columns=[benchmark_col], errors="ignore").dropna(how="all")
    return df_beta_up

######BETA DOWN###########
def beta_down(df_returns_last, benchmark_col="SXXP Bench"):
    df_step1 = returns_rolling_up_down(df_returns_last, "down", benchmark_col=benchmark_col)
    df_step2 = multiply_by_benchmark(df_step1, benchmark_col=benchmark_col)
    df_step3 = df_step2.rolling(window=252).mean()
    df_step4 = divide_by_var_benchmark(df_step3, benchmark_col=benchmark_col)
    df_beta_down = df_step4.drop(columns=[benchmark_col], errors="ignore").dropna(how="all")
    return df_beta_down


def regional_beta(df_returns_with_bench, df_aggregate):
    benchmark_by_sedol = _regional_benchmark_by_sedol(df_aggregate)
    beta_by_benchmark = {}
    for benchmark_col in sorted(set(benchmark_by_sedol.values())):
        if benchmark_col in df_returns_with_bench.columns:
            beta_by_benchmark[benchmark_col] = beta(df_returns_with_bench, benchmark_col=benchmark_col)

    if not beta_by_benchmark:
        return pd.DataFrame(index=df_returns_with_bench.index)

    regional_frames = []
    for sedol, benchmark_col in benchmark_by_sedol.items():
        beta_frame = beta_by_benchmark.get(benchmark_col)
        if beta_frame is not None and sedol in beta_frame.columns:
            regional_frames.append(beta_frame[[sedol]])
    if not regional_frames:
        return pd.DataFrame(index=df_returns_with_bench.index)
    return pd.concat(regional_frames, axis=1).loc[:, lambda frame: ~frame.columns.duplicated()]


def _regional_benchmark_by_sedol(df_aggregate):
    required = ['Company SEDOL', 'Date']
    missing = [column for column in required if column not in df_aggregate.columns]
    if missing:
        return {}

    screen = df_aggregate.reset_index(drop=False).copy()
    screen['Date'] = pd.to_datetime(screen['Date'])
    screen = screen.sort_values('Date').dropna(subset=['Company SEDOL']).drop_duplicates(
        subset=['Company SEDOL'], keep='last'
    )

    country = screen.get('Exchange Country Name', pd.Series(index=screen.index, dtype='object')).astype('string').str.upper()
    region = screen.get('Exchange Country Region', pd.Series(index=screen.index, dtype='object')).astype('string')

    benchmark = pd.Series('MSCI WORLD Bench', index=screen.index, dtype='object')
    benchmark.loc[country == 'UNITED STATES'] = 'SP500 Bench'
    benchmark.loc[region == 'West Europe'] = 'SXXP Bench'
    return dict(zip(screen['Company SEDOL'].astype(str), benchmark))


######MAX DRAWDOWN###########
# Initialisation de pandarallel
def calculate_rolling_max_drawdown_series(series, window = 252):
    # Calcul de la valeur cumulative à partir des rendements pour une série individuelle
    cumulative_returns = (1 + series).cumprod()

    # Calcul du point haut roulant (rolling maximum)
    rolling_max = cumulative_returns.rolling(window=window, min_periods=252).max()

    # Calcul du drawdown
    drawdown = (cumulative_returns - rolling_max) / rolling_max

    # Calcul du drawdown maximal sur la fenêtre glissante
    rolling_max_drawdown = drawdown.rolling(window=window, min_periods=252).min()

    return rolling_max_drawdown

def calculate_rolling_max_drawdown_parallel(daily_returns, window=252):
    # Application parallèle de la fonction sur chaque colonne
    if PANDARALLEL_AVAILABLE and hasattr(daily_returns, "parallel_apply"):
        rolling_max_drawdown = daily_returns.parallel_apply(
            calculate_rolling_max_drawdown_series, args=(window,)
        )
    else:
        rolling_max_drawdown = daily_returns.apply(
            calculate_rolling_max_drawdown_series, args=(window,)
        )
    return rolling_max_drawdown


######VaR 99%############
def calculate_rolling_var(series):
    return series.rolling(window=252).quantile(0.01)


def compute_technicals(df_returns, df_aggregate):
    df_returns_all = add_bench_return(df_returns,df_aggregate)
    df_returns_last = df_returns.iloc[-280:,:]
    df_vol = ewma_vol_window_rolling(df_returns_last)
    df_var = df_returns_last.apply(calculate_rolling_var, axis=0).dropna(how="all")
    df_max_drawdown = calculate_rolling_max_drawdown_series(df_returns)
    df_beta = beta(df_returns_all)
    df_beta_up = beta_up(df_returns_all)
    df_beta_down  = beta_down(df_returns_all)


    df_vol = df_vol.reset_index().rename(columns = { "index" : "Date"})
    df_beta = df_beta.reset_index().rename(columns = { "index" : "Date"})
    df_beta_up = df_beta_up.reset_index().rename(columns = { "index" : "Date"})
    df_beta_down = df_beta_down.reset_index().rename(columns = { "index" : "Date"})
    df_max_drawdown = df_max_drawdown.reset_index().rename(columns = { "index" : "Date"})
    df_var = df_var.reset_index().rename(columns = { "index" : "Date"})

    values_var = [ x for x in df_vol.columns if x!= "Date"]
    df_vol_histo_melted = df_vol.melt(id_vars = ["Date"], value_vars = values_var , var_name = "Company SEDOL" )
    df_vol_histo_melted = df_vol_histo_melted.rename(columns = {"value" : "Volatilite Rolling ewma 250D"})

    values_var = [ x for x in df_beta.columns if x!= "Date"]
    df_beta_melted = df_beta.melt(id_vars = ["Date"], value_vars = values_var , var_name = "Company SEDOL" )
    df_beta_melted = df_beta_melted.rename(columns = {"value" : "Beta vs SXXP (Rolling ewma 250D)"})

    values_var = [ x for x in df_beta_up.columns if x!= "Date"]
    df_beta_up_melted = df_beta_up.melt(id_vars = ["Date"], value_vars = values_var , var_name = "Company SEDOL" )
    df_beta_up_melted = df_beta_up_melted.rename(columns = {"value" : "Beta Up vs SSXP (Rolling ewma 250D)"})

    values_var = [ x for x in df_beta_down.columns if x!= "Date"]
    df_beta_down_melted = df_beta_down.melt(id_vars = ["Date"], value_vars = values_var , var_name = "Company SEDOL" )
    df_beta_down_melted = df_beta_down_melted.rename(columns = {"value" : "Beta Down vs SSXP (Rolling ewma 250D)"})

    values_var = [ x for x in df_max_drawdown.columns if x!= "Date"]
    df_mdd_histo_melted = df_max_drawdown.melt(id_vars = ["Date"], value_vars = values_var , var_name = "Company SEDOL" )
    df_mdd_histo_melted = df_mdd_histo_melted.rename(columns = {"value" : "Maximum Drawdown Rolling 250D"})

    values_var = [ x for x in df_var.columns if x!= "Date"]
    df_var_histo_melted = df_var.melt(id_vars = ["Date"], value_vars = values_var , var_name = "Company SEDOL" )
    df_var_histo_melted = df_var_histo_melted.rename(columns = {"value" : "VaR 1% Rolling 250D"})

    date_last = df_aggregate["Date"].iloc[-1].strftime('%Y-%m-%d')

    df_vol_last_ligne = df_vol_histo_melted[df_vol_histo_melted["Date"]==date_last]
    df_beta_last_ligne = df_beta_melted[df_beta_melted["Date"]==date_last]
    df_beta_up_last_ligne = df_beta_up_melted[df_beta_up_melted["Date"]==date_last]
    df_beta_down_last_ligne = df_beta_down_melted[df_beta_down_melted["Date"]==date_last]
    df_mdd_histo_last_ligne = df_mdd_histo_melted[df_mdd_histo_melted["Date"]==date_last]
    df_var_histo_last_ligne = df_var_histo_melted[df_var_histo_melted["Date"]==date_last]

    print(df_beta_up_last_ligne.columns)


    index_agg = df_aggregate.index

    # Merge explicite des deux DataFrames
    df_aggregate = df_aggregate.merge(
        df_vol_last_ligne,
        on=['Date', 'Company SEDOL'],
        how='left',
        suffixes=('', '_new')
    )
    df_aggregate['Volatilite Rolling ewma 250D'] = df_aggregate['Volatilite Rolling ewma 250D_new'].combine_first(df_aggregate['Volatilite Rolling ewma 250D'])


    df_aggregate = df_aggregate.merge(
        df_beta_last_ligne,
        on=['Date', 'Company SEDOL'],
        how='left',
        suffixes=('', '_new')
    )
    df_aggregate['Beta vs SXXP (Rolling ewma 250D)'] = df_aggregate['Beta vs SXXP (Rolling ewma 250D)_new'].combine_first(df_aggregate['Beta vs SXXP (Rolling ewma 250D)'])

    df_aggregate = df_aggregate.merge(
        df_beta_up_last_ligne,
        on=['Date', 'Company SEDOL'],
        how='left',
        suffixes=('', '_new')
    )
    df_aggregate['Beta Up vs SXXP (252D)'] = df_aggregate['Beta Up vs SXXP (252D)_new'].combine_first(df_aggregate['Beta Up vs SXXP (252D)'])

    df_aggregate = df_aggregate.merge(
        df_beta_down_last_ligne,
        on=['Date', 'Company SEDOL'],
        how='left',
        suffixes=('', '_new')
    )
    df_aggregate['Beta Down vs SXXP (252D)'] = df_aggregate['Beta Down vs SXXP (252D)_new'].combine_first(df_aggregate['Beta Down vs SXXP (252D)'])

    df_aggregate = df_aggregate.merge(
        df_mdd_histo_last_ligne,
        on=['Date', 'Company SEDOL'],
        how='left',
        suffixes=('', '_new')
    )
    df_aggregate['Maximum Drawdown Rolling 250D'] = df_aggregate['Maximum Drawdown Rolling 250D_new'].combine_first(df_aggregate['Maximum Drawdown Rolling 250D'])

    df_aggregate = df_aggregate.merge(
        df_var_histo_last_ligne,
        on=['Date', 'Company SEDOL'],
        how='left',
        suffixes=('', '_new')
    )
    df_aggregate['VaR 1% Rolling 250D'] = df_aggregate['VaR 1% Rolling 250D_new'].combine_first(df_aggregate['VaR 1% Rolling 250D'])



    # Restaurer l'index d'origine
    df_aggregate.index = index_agg  

    df_aggregate = df_aggregate.drop(columns=['Volatilite Rolling ewma 250D_new', 'Beta vs SXXP (Rolling ewma 250D)_new','Beta Up vs SXXP (252D)_new','Beta Down vs SXXP (252D)_new','Maximum Drawdown Rolling 250D_new','VaR 1% Rolling 250D_new'])

    return df_aggregate
    


